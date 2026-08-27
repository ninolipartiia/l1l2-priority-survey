#!/usr/bin/env python3
"""
resolve_zkcandy_explorer.py — code status + code-time for zkcandy WITHOUT a JSON-RPC endpoint.

Why this exists
---------------
zkcandy's JSON-RPC (`https://rpc.zkcandy.io`) is dead, and every free alternative probed on
2026-08-26 either 404s, needs a key, or (thirdweb `https://320.rpc.thirdweb.com`) answers
`eth_chainId` and then refuses every other method as rate-limited. `resolve_l2_code.py`
therefore cannot run on zkcandy at all — it aborts at the `eth_chainId` check, exactly as
METHOD §6.3 says it should.

Its **block explorer is alive** (`https://explorer.zkcandy.io/api`, a **Blockscout** instance
with an Etherscan-compatible subset — NOT the same software era runs), and it indexes the
census's canonical hashes.
This script substitutes two explorer endpoints for the two RPC calls the shipped scripts use:

  RPC method                         ->  explorer substitute
  eth_getCode(addr, latest)          ->  contract&getcontractcreation  (creation record?)
  eth_getTransactionByHash + getCode ->  account&txlist  (block of the funding tx),
                                         compared against the creation block

What this buys and what it costs (state both in the report)
-----------------------------------------------------------
+ zkcandy's 1,256 addresses stop being `unresolvable`, and contract verdicts come with an
  exact creation block, so code-time is *derived*, not probed — no archive endpoint needed.
- This endpoint returns no bytecode, so there is **no `code_len` and no `codehash`**: zkcandy
  contributes nothing to the bytecode-family analysis (METHOD §5). Entries carry
  `"method": "explorer-getcontractcreation"` so no downstream step can mistake a null
  codehash for "resolved but unclustered". NOTE this is a limit of the endpoint CHOSEN, not
  of the host: the same Blockscout instance serves `/api/v2/smart-contracts/{addr}` with
  `deployed_bytecode`, and `/api/v2/addresses/{addr}` with a direct `is_contract` flag that
  is a truer `eth_getCode` equivalent than a creation record. A re-implementation should
  prefer those.
- `delegated-eoa` (EIP-7702) cannot be detected at all — a delegation is code, not a
  creation record. zkcandy's `delegated-eoa` count is therefore *unknown*, not zero.
- A contract deployed **at genesis** has no creation record and reads as `eoa`. Measured
  exhaustively against the chain's full contract population (314 addresses via
  `listcontracts`): 294 found, **20 missed, every one inside the reserved range** — so recall
  is 291/291 on non-system contracts and 0/20 on genesis. Correct examples of the miss are
  `0x0`, `0x…8006`, `0x…800a`, `0x…800b`, `0x…8014`, `0x…10000`; `0x…10003`/`0x…10004`
  (deployed in block 136) are found. An earlier version of this note cited `0x…8007`,
  `0x…10002` and `0x…10005` — wrong, those are not contracts on zkcandy at all, so they
  return nothing simply because they are codeless. Every genesis contract on a ZK-stack chain
  lives in the reserved range METHOD §3 filters out as `is_system`, so this cannot mis-file a
  user-chosen counterparty — but it IS why address `0x0` lands in the `eoa` bucket here while
  it is `contract` on the four RPC chains.

Two API traps this script defends against
-----------------------------------------
1. **Silent truncation.** `contractaddresses` accepts at most 10 addresses; pass more and the
   API answers `status:1 "OK"` having silently **truncated to the first 10**. A caller that
   chunked at 60 would get no record for addresses 11..60 and, under the "no record means no
   code" rule, would mint confident false `eoa` verdicts for 83% of every chunk. The chunk is
   hard-capped at 10 and every reply is checked to contain only addresses that were asked
   for. Anything else aborts.
   (An earlier version of this comment said the API returns results for *none* of them above
   the cap. That was a misdiagnosis from a confounded probe — 10 EOAs followed by 1 contract
   in position 11, so the only address that could have produced a row was the truncated one.
   Re-measured: 11/12/15 known contracts each return exactly the first 10.)
2. **Failure is not a verdict** (METHOD §2). Only `status == "1"` (OK) or the literal
   `status == "0" / "No data found"` count as answers; every other status, an HTTP failure or
   an unparseable body leaves the address UNRESOLVED, never `eoa`.

Usage
  python3 resolve_zkcandy_explorer.py --in ../../results/enriched/zkcandy.jsonl \
      --out ../code/zkcandy.json --codetime-out ../codetime/zkcandy.json \
      --deposit-beneficiaries
"""
import argparse, json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "phase6-l2-recipients", "scripts"))
from resolve_l2_code import (beneficiary_of, check_classes, collect_targets,   # shared decode
                             load_json, report_skips, save_json)

API = "https://explorer.zkcandy.io/api"
CHAIN = "zkcandy"
MAX_ADDRS = 10          # hard API cap; above it the API SILENTLY TRUNCATES to the first 10
                        # and still answers status:1 OK (see module docstring)
METHOD_TAG = "explorer-getcontractcreation"


def get(params, tries=4, timeout=30):
    """GET the explorer API -> (parsed, error). A non-OK status is an error, never a verdict."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    err = "no attempt made"
    for attempt in range(tries):
        p = subprocess.run(["curl", "-s", "-m", str(timeout), f"{API}?{qs}"],
                           capture_output=True, text=True)
        if p.returncode != 0 or not p.stdout.strip():
            err = f"curl rc={p.returncode} {(p.stderr or '').strip()[:80]}".strip()
        else:
            try:
                d = json.loads(p.stdout)
            except ValueError:
                err = f"unparseable reply {p.stdout.strip()[:120]}"
            else:
                if d.get("status") == "1":
                    return d, None
                # "No data found" with status 0 is a real answer meaning "nothing indexed",
                # which the callers below interpret per endpoint. Anything else is a failure.
                if d.get("status") == "0" and d.get("message") == "No data found":
                    return d, None
                err = f"api status={d.get('status')!r} message={str(d.get('message'))[:100]!r}"
        if attempt + 1 < tries:
            time.sleep(1.5 * (2 ** attempt))
    return None, err


def creation_records(addrs):
    """-> ({addr: {"blockNumber": int, "txHash": str, "creator": str}}, error).

    Absence from the returned dict means "the API answered and had no creation record",
    i.e. EOA (or a genesis contract — see the docstring). An error means NOTHING is known
    about any address in the chunk.
    """
    if len(addrs) > MAX_ADDRS:
        sys.exit(f"FATAL: {len(addrs)} addresses in one getcontractcreation call; the API caps "
                 f"at {MAX_ADDRS} and silently TRUNCATES to the first {MAX_ADDRS} while still "
                 f"answering 'OK'. Everything past the cap would read as a confident EOA "
                 f"verdict. Refusing.")
    d, err = get({"module": "contract", "action": "getcontractcreation",
                  "contractaddresses": ",".join(addrs)})
    if err is not None:
        return None, err
    asked = {a.lower() for a in addrs}
    out = {}
    for rec in (d.get("result") or []):
        a = str(rec.get("contractAddress", "")).lower()
        if a not in asked:
            sys.exit(f"FATAL: getcontractcreation returned {a}, which was not in the chunk "
                     f"{sorted(asked)}. The API is not answering the question asked; refusing "
                     f"to write verdicts from it.")
        blk = rec.get("blockNumber")
        out[a] = {"blockNumber": int(blk) if blk is not None and str(blk).isdigit() else None,
                  "txHash": rec.get("txHash") or rec.get("creationTxHash"),
                  "creator": rec.get("contractCreator")}
    return out, None


def tx_block(addr, want_hash):
    """Block number of `want_hash` among the address's indexed txs -> (int|None, error)."""
    want = want_hash.lower()
    for page in (1, 2, 3):
        d, err = get({"module": "account", "action": "txlist", "address": addr,
                      "page": page, "offset": 100, "sort": "asc"})
        if err is not None:
            return None, err
        rows = d.get("result") or []
        for t in rows:
            if str(t.get("hash", "")).lower() == want:
                b = t.get("blockNumber")
                return (int(b) if str(b).isdigit() else None), None
        if len(rows) < 100:
            break
        time.sleep(0.15)
    return None, None          # answered, hash simply not among this address's indexed txs


def window_index(path, classes, deposit_beneficiaries):
    """addr -> {"first": rec, "last": rec, "txs": n, "source": str} over the in-window records."""
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
        key = (r.get("ts") or 0, r.get("tx_id") or 0)
        for addr, source in hits:
            cur = window.get(addr)
            if cur is None:
                window[addr] = {"first": (key, r), "last": (key, r), "txs": 1, "source": source}
            else:
                cur["txs"] += 1
                if key < cur["first"][0]:
                    cur["first"] = (key, r)
                if key > cur["last"][0]:
                    cur["last"] = (key, r)
    return window, skips


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default=os.path.join(here, "..", "..", "results", "enriched", "zkcandy.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "..", "code", "zkcandy.json"))
    ap.add_argument("--codetime-out", default=os.path.join(here, "..", "codetime", "zkcandy.json"))
    ap.add_argument("--classes", default="direct-transfer,other")
    ap.add_argument("--deposit-beneficiaries", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.12)
    ap.add_argument("--checkpoint", type=int, default=20, help="atomic save every N chunks")
    ap.add_argument("--max-dead-chunks", type=int, default=3)
    a = ap.parse_args()

    for p in (a.out, a.codetime_out):
        if CHAIN not in os.path.basename(p).lower():
            sys.exit(f"FATAL: '{os.path.basename(p)}' does not name '{CHAIN}' — same rule as the "
                     f"shipped scripts (METHOD §6 pitfall 2).")
    classes = {c.strip() for c in a.classes.split(",") if c.strip()}
    check_classes(classes)
    if not os.path.exists(a.inp):
        sys.exit(f"FATAL: {a.inp} does not exist.")

    targets, skips = collect_targets(a.inp, classes, a.deposit_beneficiaries)
    report_skips(skips, "canonical-deposit")
    window, _ = window_index(a.inp, classes, a.deposit_beneficiaries)

    cache = load_json(a.out)
    todo = sorted(t for t in targets if t not in cache)
    print(f"{CHAIN}: {len(targets)} targets, {len(cache)} cached, {len(todo)} to resolve via {API}",
          file=sys.stderr)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    unresolved, dead = {}, 0
    try:
        for n, i in enumerate(range(0, len(todo), MAX_ADDRS), start=1):
            chunk = todo[i:i + MAX_ADDRS]
            recs, err = creation_records(chunk)
            if err is not None:
                for addr in chunk:
                    unresolved[addr] = err
                dead += 1
                print(f"    ! chunk of {len(chunk)} failed: {err}", file=sys.stderr)
                if dead >= a.max_dead_chunks:
                    save_json(cache, a.out)
                    sys.exit(f"FATAL: {dead} consecutive chunks resolved nothing via {API}. "
                             f"{len(cache)} entries checkpointed in {a.out}; fix and re-run.")
            else:
                dead = 0
                for addr in chunk:
                    rec = recs.get(addr)
                    cache[addr] = {
                        "len": None, "codehash": None, "block": "latest-via-explorer",
                        "kind": "contract" if rec else "eoa", "method": METHOD_TAG,
                        "creation_block": rec["blockNumber"] if rec else None,
                        "creation_tx": rec["txHash"] if rec else None,
                        "creator": rec["creator"] if rec else None}
            if n % a.checkpoint == 0:
                save_json(cache, a.out)
                print(f"  {min(i + MAX_ADDRS, len(todo))}/{len(todo)}", file=sys.stderr)
            time.sleep(a.sleep)
    finally:
        save_json(cache, a.out)

    resolved = {t: cache[t] for t in targets if t in cache}
    kinds = {}
    for v in resolved.values():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
    print(f"\n{CHAIN}: resolved {len(resolved)}/{len(targets)}  kinds={kinds}  "
          f"(method={METHOD_TAG}; no bytecode, so no codehash/family and no 7702 detection)",
          file=sys.stderr)
    if unresolved:
        print(f"  !! {len(unresolved)} address(es) UNRESOLVED — declare them, do not assume EOA",
              file=sys.stderr)

    # ---- code-time, derived from the creation block rather than probed at block-1 ----
    ct = load_json(a.codetime_out)
    contracts = sorted(t for t, v in resolved.items() if v["kind"] == "contract")
    print(f"{CHAIN}: dating {len(contracts)} contract recipient(s) from creation blocks",
          file=sys.stderr)
    for addr in contracts:
        info = window.get(addr)
        if info is None:
            ct[addr] = {"source": None, "earliest_tx_id": None, "ts": None, "txs_in_window": 0,
                        "last_tx_id": None, "l2_block": None, "probe_block": None,
                        "code_at_tx": "unavailable", "len_at_tx": None, "code_at_last_tx": None,
                        "straddles_deployment": None, "retryable": False,
                        "detail": f"no record with class in {sorted(classes)} pays this address"}
            continue
        first, last = info["first"][1], info["last"][1]
        blk, err = tx_block(addr, first["canonical_hash"])
        entry = {"source": info["source"], "earliest_tx_id": first.get("tx_id"),
                 "ts": first.get("ts"), "txs_in_window": info["txs"],
                 "last_tx_id": last.get("tx_id"),
                 "l2_block": hex(blk) if blk is not None else None,
                 "probe_block": hex(blk - 1) if blk else None,
                 "code_at_tx": "unavailable", "len_at_tx": None,
                 "code_at_last_tx": None, "straddles_deployment": None,
                 "detail": None, "retryable": True,
                 "creation_block": resolved[addr]["creation_block"], "method": METHOD_TAG}
        if err is not None:
            entry["detail"] = f"explorer txlist failed: {err}"
        elif blk is None:
            entry["retryable"] = False
            entry["detail"] = ("the canonical hash is not among this address's indexed txs on "
                               "explorer.zkcandy.io: the priority tx never executed on L2, or "
                               "the explorer does not index it. Terminal.")
        elif resolved[addr]["creation_block"] is None:
            entry["detail"] = "creation record carries no block number"
        else:
            created = resolved[addr]["creation_block"]
            # Same semantics as probing block-1: code existed BEFORE the funding tx's block.
            entry["code_at_tx"] = "contract" if created < blk else "eoa"
            entry["retryable"] = False
            entry["detail"] = (f"derived: created in block {created}, earliest in-window tx in "
                               f"block {blk} (no RPC; creation-block comparison, "
                               f"strictly-earlier = had code)")
            if entry["code_at_tx"] == "eoa" and last.get("tx_id") != first.get("tx_id"):
                lblk, lerr = tx_block(addr, last["canonical_hash"])
                if lerr is None and lblk is not None:
                    entry["code_at_last_tx"] = "contract" if created < lblk else "eoa"
                    entry["straddles_deployment"] = entry["code_at_last_tx"] != "eoa"
                else:
                    entry["detail"] += f"; last-tx probe skipped: {lerr or 'hash not indexed'}"
        ct[addr] = entry
        time.sleep(a.sleep)
    save_json(ct, a.codetime_out)
    tally = {}
    for addr in contracts:
        v = ct[addr]["code_at_tx"]
        tally[v] = tally.get(v, 0) + 1
    print(f"{CHAIN}: code_at_tx tally = {tally}", file=sys.stderr)
    if unresolved:
        json.dump(unresolved, open(a.out + ".unresolved.json", "w"), indent=1, sort_keys=True)
        print(f"  wrote {a.out}.unresolved.json", file=sys.stderr)


if __name__ == "__main__":
    main()
