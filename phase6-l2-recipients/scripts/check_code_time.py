#!/usr/bin/env python3
"""
check_code_time.py — did the recipient already have code when the money arrived?

`eth_getCode(addr, "latest")` answers "is it a contract NOW". That is NOT the same as
"the EOA sent value to a contract": on ZK-stack chains, smart-contract wallets are
routinely FUNDED FIRST and DEPLOYED LATER (counterfactual/lazy deployment), so a
latest-block test systematically over-counts EOA->contract flows.

For every recipient the code cache marks as `contract` (or whatever `--kinds` selects), this
script:
  1. finds that recipient's earliest in-window tx (by ts, tx_id) among the selected classes
     (and, with --deposit-beneficiaries, among decoded canonical-deposit beneficiaries),
  2. resolves that tx's L2 block via eth_getTransactionByHash(canonical_hash),
  3. calls eth_getCode(recipient, <that block MINUS ONE>) — requires an ARCHIVE endpoint.

Why block-1 and not the tx's own block: `eth_getCode(addr, N)` returns state at the END of
block N, i.e. after the funding tx and after every other tx in N — including a deployment
that happened later in the same block. Probing N-1 answers the question actually being
asked. The bias is deliberate and one-directional: a contract deployed earlier in the same
block reads as `eoa`, so the headline EOA->contract count can only be under-stated, never
inflated (METHOD §4).

**One verdict per recipient, not per tx.** Only the earliest tx is dated, and the verdict is
then applied to every tx that recipient received. For a recipient funded across a deployment
that is wrong for the later txs, so whenever the earliest tx reads `eoa` the script *also*
dates the recipient's LAST in-window tx and sets `straddles_deployment`. That makes the
residual error measurable instead of assumed: a straddling recipient's `txs_in_window` txs
are split by the deployment, and METHOD §4 requires the report to size that population
rather than silently excluding all of them.

Verdicts written per address:
  code_at_tx = "contract"      -> genuine EOA->contract transfer at the time it happened
             = "eoa"           -> recipient was still codeless; deployed later (reclassify!)
             = "delegated-eoa" -> 0xef0100 delegation present at that block; a user account
             = "unavailable"   -> endpoint refused / pruned / no in-window record / the
                                  canonical hash is not on this L2: report as unverified,
                                  never silently assume either way

`retryable: true` means the CALL failed and a better endpoint would help. A canonical hash
that the L2 does not know is *terminal* (`retryable: false`) — re-running against an archive
endpoint cannot conjure a tx that never executed, and marking it retryable would leave an
entry that can never be cleared (TASK acceptance criteria).

Usage
  python3 check_code_time.py --chain zero --in ../../results/enriched/zero.jsonl \
      --code ../../results-l2/code/zero.json --out ../../results-l2/codetime/zero.json
  # optional control (METHOD §4): date a deterministic sample of `eoa` recipients
  python3 check_code_time.py --chain zero --in ... --code ... --out /tmp/zero-eoa-control.json \
      --kinds eoa --limit 50
"""
import argparse, json, os, sys, time

from resolve_l2_code import (CHAINS, call_batch, classify,           # shared transport
                             beneficiary_of, check_chain_id, check_classes, check_file_name,
                             check_input_name, load_json, report_skips, save_json)

KNOWN_KINDS = {"eoa", "contract", "delegated-eoa"}


def collect_window(path, classes, deposit_beneficiaries):
    """addr -> {"first": (key, rec, source), "last": (...), "txs": n}, plus a skip tally.

    `first`/`last` are the earliest and latest in-window records that paid the address;
    `txs` counts every in-window hit (candidate records plus, when enabled, decoded deposit
    beneficiaries), which is the population a single dated verdict is applied to.
    """
    window, skips = {}, {}
    for line in open(path):
        r = json.loads(line)
        cls = r.get("class")
        hits = []
        if cls in classes:
            hits.append((r["to"].lower(), "candidate"))
        if deposit_beneficiaries and cls == "canonical-deposit":
            addr, why = beneficiary_of(r)
            if addr:
                hits.append((addr, "deposit-beneficiary"))
            else:
                skips[why] = skips.get(why, 0) + 1
        key = (r.get("ts") or 0, r.get("tx_id") or 0)   # tx_id breaks ts ties deterministically
        for addr, source in hits:
            cur = window.get(addr)
            if cur is None:
                window[addr] = {"first": (key, r, source), "last": (key, r, source), "txs": 1}
                continue
            cur["txs"] += 1
            if key < cur["first"][0]:
                cur["first"] = (key, r, source)
            if key > cur["last"][0]:
                cur["last"] = (key, r, source)
    return window, skips


def note(entry, msg):
    """Append a secondary diagnostic without discarding the primary one."""
    entry["detail"] = f"{entry['detail']}; {msg}" if entry["detail"] else msg


def new_entry(info):
    """A fresh verdict record. Every key is always present (OUTPUT_SPEC §2)."""
    _, rec, source = info["first"]
    return {"source": source, "earliest_tx_id": rec.get("tx_id"), "ts": rec.get("ts"),
            "txs_in_window": info["txs"], "last_tx_id": info["last"][1].get("tx_id"),
            "l2_block": None, "probe_block": None,
            "code_at_tx": "unavailable", "len_at_tx": None,
            "code_at_last_tx": None, "straddles_deployment": None,
            "detail": None, "retryable": True}


def orphan_entry(classes, deposit_beneficiaries):
    """A contract recipient with no matching in-window record still needs an explicit verdict:
    silence in the output would be indistinguishable from "already verified"."""
    return {"source": None, "earliest_tx_id": None, "ts": None, "txs_in_window": 0,
            "last_tx_id": None, "l2_block": None, "probe_block": None,
            "code_at_tx": "unavailable", "len_at_tx": None,
            "code_at_last_tx": None, "straddles_deployment": None, "retryable": False,
            "detail": f"no record with class in {sorted(classes)}"
                      f"{' or decoded deposit beneficiary' if deposit_beneficiaries else ''}"
                      f" pays this address; re-run with the --classes / "
                      f"--deposit-beneficiaries that produced the code cache"}


def probe_block_of(blk):
    """State BEFORE the funding tx: end of the previous block (see module docstring)."""
    n = int(blk, 16)
    return hex(n - 1) if n > 0 else blk


def tx_blocks(url, addrs, hashes, batch):
    """-> ({addr: block_hex}, {addr: error_or_None_meaning_not_on_chain}, dead)."""
    results, dead = call_batch(url, [("eth_getTransactionByHash", [h]) for h in hashes],
                               chunk=batch)
    blocks, failed = {}, {}
    for addr, (tx, err) in zip(addrs, results):
        blk = tx.get("blockNumber") if err is None and isinstance(tx, dict) else None
        if isinstance(blk, str):
            blocks[addr] = blk
        else:
            failed[addr] = err        # None here means "answered, but the tx is not on this L2"
    return blocks, failed, dead


def probe_slice(url, addrs, window, out, a):
    """Date one slice of addresses in place. -> True if the endpoint stopped answering."""
    live = []
    for addr in addrs:
        info = window.get(addr)
        if info is None:
            out[addr] = orphan_entry(a.classes_set, a.deposit_beneficiaries)
        else:
            out[addr] = new_entry(info)
            live.append(addr)
    if not live:
        return False

    # 1. earliest tx -> its L2 block
    blocks, failed, dead = tx_blocks(
        url, live, [window[x]["first"][1]["canonical_hash"] for x in live], a.batch)
    for addr, err in failed.items():
        entry = out[addr]
        if err is not None:
            entry["detail"] = f"eth_getTransactionByHash failed: {err}"   # stays retryable
        else:
            # A usable reply with no block: the canonical hash is not on this L2. An archive
            # endpoint cannot fix that, so the entry is terminal rather than retryable.
            entry["retryable"] = False
            entry["detail"] = ("eth_getTransactionByHash returned no block for the canonical "
                               "hash: the priority tx never executed on L2, or this endpoint "
                               "does not index it. Terminal — a different endpoint does not "
                               "change it; confirm on the explorer before reporting.")
    if dead:
        return True

    # 2. code at <block - 1>
    staged = sorted(blocks)
    for addr in staged:
        out[addr]["l2_block"] = blocks[addr]
        out[addr]["probe_block"] = probe_block_of(blocks[addr])
        if int(blocks[addr], 16) == 0:
            out[addr]["detail"] = "tx is in block 0; no earlier block to probe"
    results, dead = call_batch(
        url, [("eth_getCode", [x, out[x]["probe_block"]]) for x in staged], chunk=a.batch)
    later = []
    for addr, (code, err) in zip(staged, results):
        entry = out[addr]
        if err is not None:
            note(entry, f"eth_getCode at {entry['probe_block']} failed: {err}")
            continue
        if not isinstance(code, str):
            note(entry, f"eth_getCode at {entry['probe_block']} returned {code!r}, not a code "
                        f"string — a null result is a failed call, not empty code")
            continue
        try:
            entry["code_at_tx"], entry["len_at_tx"] = classify(code)
        except ValueError as exc:
            note(entry, f"eth_getCode at {entry['probe_block']}: {exc}")
            continue
        entry["retryable"] = False
        if entry["code_at_tx"] == "eoa" and entry["last_tx_id"] != entry["earliest_tx_id"]:
            later.append(addr)
    if dead or not later:
        return dead

    # 3. `contract-later` recipients that received more than once: date the LAST tx too, so the
    #    per-recipient verdict's error term is measured rather than assumed (METHOD §4).
    blocks, failed, dead = tx_blocks(
        url, later, [window[x]["last"][1]["canonical_hash"] for x in later], a.batch)
    for addr, err in failed.items():
        note(out[addr], f"last-tx probe skipped: {err or 'canonical hash not on this L2'}")
    if dead:
        return True
    probes = sorted(blocks)
    results, dead = call_batch(
        url, [("eth_getCode", [x, probe_block_of(blocks[x])]) for x in probes], chunk=a.batch)
    for addr, (code, err) in zip(probes, results):
        entry = out[addr]
        if err is not None or not isinstance(code, str):
            note(entry, f"last-tx probe failed: {err or repr(code)}")
            continue
        try:
            kind, _ = classify(code)
        except ValueError as exc:
            note(entry, f"last-tx probe: {exc}")
            continue
        entry["code_at_last_tx"] = kind
        entry["straddles_deployment"] = kind != "eoa"
    return dead


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=sorted(CHAINS))
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--code", required=True, help="code cache from resolve_l2_code.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--classes", default="direct-transfer,other")
    ap.add_argument("--deposit-beneficiaries", action="store_true",
                    help="also date recipients that only appear as decoded deposit beneficiaries")
    ap.add_argument("--kinds", default="contract",
                    help="code-cache kinds to date. 'contract' is the correctness gate; "
                         "'eoa' runs the METHOD §4 control (did a recipient that is codeless "
                         "today have code when it was paid?)")
    ap.add_argument("--limit", type=int, default=0,
                    help="date only the first N addresses by sorted address (deterministic "
                         "sample; 0 = all)")
    ap.add_argument("--rpc")
    ap.add_argument("--batch", type=int, default=60, help="JSON-RPC batch size")
    ap.add_argument("--sleep", type=float, default=0.25, help="pause between slices (be polite)")
    ap.add_argument("--checkpoint", type=int, default=200, help="atomic save every N addresses")
    ap.add_argument("--max-dead-batches", type=int, default=3,
                    help="abort after this many consecutive slices the endpoint did not answer")
    ap.add_argument("--allow-empty", action="store_true",
                    help="proceed when no selected address has an in-window record (otherwise "
                         "that combination aborts as a --classes/--code mismatch)")
    ap.add_argument("--allow-input-name-mismatch", action="store_true",
                    help="skip the --in/--code/--out filename checks against --chain (you "
                         "renamed the files yourself)")
    ap.add_argument("--no-chain-check", action="store_true")
    a = ap.parse_args()

    url = a.rpc or CHAINS[a.chain][1]
    check_input_name(a.inp, a.chain, a.allow_input_name_mismatch)
    # The code cache is the input that carries code status; an era cache probed against zero's
    # RPC passes the eth_chainId and --in checks and then fabricates a chain of verdicts.
    check_file_name(a.code, a.chain, a.allow_input_name_mismatch, "--code")
    # And on the way out: a verdict file written under another chain's name is the same lie,
    # created rather than consumed (see check_file_name in resolve_l2_code.py).
    check_file_name(a.out, a.chain, a.allow_input_name_mismatch, "--out")
    if a.no_chain_check:
        print(f"!! eth_chainId check skipped for {url} — justify this in the manifest",
              file=sys.stderr)
    else:
        check_chain_id(url, a.chain)

    a.classes_set = {c.strip() for c in a.classes.split(",") if c.strip()}
    check_classes(a.classes_set)
    kinds = {k.strip() for k in a.kinds.split(",") if k.strip()}
    if not kinds <= KNOWN_KINDS:
        sys.exit(f"FATAL: unknown --kinds value(s) {sorted(kinds - KNOWN_KINDS)}; "
                 f"resolve_l2_code.py only emits {sorted(KNOWN_KINDS)}.")

    code = load_json(a.code, required=True)
    selected = sorted(addr for addr, v in code.items()
                      if isinstance(v, dict) and v.get("kind") in kinds)
    if a.limit:
        selected = selected[:a.limit]
    window, skips = collect_window(a.inp, a.classes_set, a.deposit_beneficiaries)
    report_skips(skips, "canonical-deposit")
    orphans = [t for t in selected if t not in window]
    if selected and len(orphans) == len(selected) and not a.allow_empty:
        sys.exit(f"FATAL: not one of the {len(selected)} address(es) to date has an in-window "
                 f"record under --classes {a.classes}"
                 f"{' --deposit-beneficiaries' if a.deposit_beneficiaries else ''}.\n"
                 f"       Every one would be written as a terminal 'no in-window record' "
                 f"verdict, which reads like a data problem rather than mismatched flags. Pass "
                 f"the --classes / --deposit-beneficiaries that produced {a.code}, or "
                 f"--allow-empty if they really are undatable.")

    out = load_json(a.out)
    # Retry anything that never got a definitive answer — an `unavailable` from a failed call is
    # a failure, not a result, so a re-run against an archive endpoint must actually re-do it.
    todo = [t for t in selected if t not in out or out[t].get("retryable")]
    print(f"{a.chain}: {len(selected)} recipient(s) with kind in {sorted(kinds)}, {len(todo)} to "
          f"check via {url} ({len(selected) - len(todo)} already verdicted, {len(orphans)} with "
          f"no in-window record for --classes {a.classes})", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    dead = 0
    try:
        for start in range(0, len(todo), a.checkpoint):
            chunk = todo[start:start + a.checkpoint]
            went_dead = probe_slice(url, chunk, window, out, a)
            save_json(out, a.out)
            print(f"  {min(start + a.checkpoint, len(todo))}/{len(todo)}", file=sys.stderr)
            dead = dead + 1 if went_dead else 0
            if dead >= a.max_dead_batches:
                sys.exit(f"FATAL: the endpoint {url} stopped answering ({dead} consecutive "
                         f"slices). {len(out)} verdicts are checkpointed in {a.out}; fix the "
                         f"endpoint (--rpc) and re-run to resume — failed calls are marked "
                         f"retryable and will be redone.")
            time.sleep(a.sleep)
    finally:
        save_json(out, a.out)

    tally, reasons, straddling, single_tx_later = {}, {}, 0, 0
    for addr in selected:
        v = out.get(addr)
        if not v:
            continue
        tally[v["code_at_tx"]] = tally.get(v["code_at_tx"], 0) + 1
        if v.get("straddles_deployment"):
            straddling += 1
        if v["code_at_tx"] == "eoa" and v.get("txs_in_window") == 1:
            single_tx_later += 1
        if v.get("retryable"):
            why = (v.get("detail") or "no detail recorded")[:90]
            reasons[why] = reasons.get(why, 0) + 1
    missing = [t for t in selected if t not in out]
    print(f"{a.chain}: code_at_tx tally = {tally}", file=sys.stderr)
    if missing:
        print(f"  !! {len(missing)} recipient(s) have NO verdict (interrupted run?) — "
              f"re-run before reporting", file=sys.stderr)
    if "contract" in kinds and tally.get("eoa"):
        print(f"  note: of {tally['eoa']} `contract-later` recipient(s), {single_tx_later} "
              f"received exactly one in-window tx (verdict is exact) and {straddling} also "
              f"received a tx AFTER the code appeared (straddles_deployment) — those later txs "
              f"are genuine EOA->contract, so excluding the whole recipient under-states the "
              f"headline. Size this in the report (METHOD §4).", file=sys.stderr)
    if "eoa" in kinds:
        # The METHOD §3 `eoa` bucket is a latest-block verdict that nothing else dates. This
        # control is the only thing that can catch a recipient which HAD code when it was paid
        # and has none now (self-destructed, or a degraded endpoint) — the inverse of the
        # counterfactual-deployment trap, and otherwise filed as a plain EOA in silence.
        contradictions = tally.get("contract", 0) + tally.get("delegated-eoa", 0)
        print(f"  control: {tally.get('eoa', 0)} recipient(s) codeless today were also codeless "
              f"at tx time; {contradictions} HAD code when paid and have none now — those are "
              f"the cases the `eoa` bucket mis-files. Report them; do not fold them into `eoa` "
              f"(METHOD §3, §4).", file=sys.stderr)
    if reasons:
        total = sum(reasons.values())
        print(f"  note: {total} entr(ies) are retryable — the CALL failed, not the recipient. "
              f"Causes:", file=sys.stderr)
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
            print(f"        {n:6d}  {why}", file=sys.stderr)
        print(f"        A non-archive endpoint is the usual cause for eth_getCode failures; "
              f"re-run with --rpc <archive endpoint>, or fall back to the explorer's "
              f"contract-creation tx (METHOD §4). They stay unverified until then.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
