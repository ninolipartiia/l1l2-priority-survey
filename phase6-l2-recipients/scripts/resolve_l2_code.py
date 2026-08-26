#!/usr/bin/env python3
"""
resolve_l2_code.py — resolve the code status of L2-side recipient addresses.

Reads an enriched census file (results/enriched/<chain>.jsonl), collects the distinct
L2 recipient addresses for the selected classes, and resolves each one's code on that
chain's L2 RPC via batched eth_getCode. Output is a resumable JSON cache:

    { "<address>": {"len": <int>, "codehash": "<sha256 of lowercased code hex>",
                    "kind": "eoa|contract|delegated-eoa", "block": "0x<block>"} }

Design notes
- stdlib + curl only (no third-party packages), matching the parent package.
- Resumable: existing --out entries are kept and skipped. Writes are atomic (tmp+rename),
  so Ctrl-C or a crash mid-checkpoint cannot corrupt the cache.
- Every run asserts eth_chainId against CHAINS.md *and* that --in and --out belong to
  --chain, so a wrong endpoint, a wrong input file, or a cache about to be written under
  another chain's name fails loudly instead of producing cross-chain garbage
  (METHOD §6 pitfall 2).
- **A missing or null `result` is a failed call, never `eoa`.** classify() refuses anything
  that is not a code hex string, because a stub or throttling endpoint that answers
  `{"result": null}` would otherwise turn a whole chain into confident `eoa` verdicts with
  no warning — the single failure mode this phase exists to prevent (METHOD §2).
- Batched JSON-RPC (verified supported on era/abstract/lens/zero, 2026-08-26); only the
  addresses actually missing from a batch reply are retried one-by-one. A batch that
  produces nothing usable costs ONE single-address probe before the batch is declared dead,
  so a dead endpoint aborts the run in seconds instead of grinding every address through
  four attempts with backoff (METHOD §6.9).
- post() backs off on JSON-RPC error replies as well as transport failures: a rate-limited
  endpoint answers HTTP 200 with an {"error": ...} body, and retrying only transport errors
  would fire the whole batch at a host that just asked us to slow down.
- `codehash` is sha256 over the **lowercased** returned code hex string — used only to
  cluster byte-identical clones (it is NOT the EVM keccak codehash; do not publish it as
  one). Lowercasing matters: endpoints differ in hex case and the family join is
  cross-endpoint (METHOD §5).
- --block resolves the whole chain at ONE concrete block, recorded in every entry. A moving
  tag (`latest`) is turned into a block number via eth_blockNumber before anything is
  written, because storing the literal "latest" would make the one-block-per-cache guard
  vacuous — an interrupted run resumed a day later would merge verdicts read at two
  different chain tips and the guard would compare "latest" against "latest". A resumed run
  adopts the block already in the cache. Per-recipient code-at-tx-time is a different
  question — that is check_code_time.py (METHOD §4).

Usage
  python3 resolve_l2_code.py --chain lens  --in ../../results/enriched/lens.jsonl \
                             --out ../../results-l2/code/lens.json
  python3 resolve_l2_code.py --chain era --in ... --out ... --deposit-beneficiaries
  python3 resolve_l2_code.py --chain era --in ... --out ... --classes protocol-message
"""
import argparse, hashlib, json, os, re, subprocess, sys, time

# chain -> (chainId per ../CHAINS.md, default L2 RPC). ONE table, shaped like
# ../../scripts/scan_priority.py and ../../results/scripts/check_completeness.py: splitting
# the id and the URL into two dicts only creates a way for them to disagree.
CHAINS = {
    "era":      (324,    "https://mainnet.era.zksync.io"),
    "abstract": (2741,   "https://api.mainnet.abs.xyz"),
    "sophon":   (50104,  "https://rpc.sophon.xyz"),
    "lens":     (232,    "https://rpc.lens.xyz"),
    "cronos":   (388,    "https://mainnet.zkevm.cronos.org"),
    "zero":     (543210, "https://rpc.zerion.io/v1/zero"),
    "zkcandy":  (320,    "https://rpc.zkcandy.io"),   # DEAD since 2026-08-26 — see METHOD §6
    "openzk":   (1345,   "https://rpc.openzk.net"),
}
# The only classes ../../results/scripts/enrich.py:classify() emits. --classes is checked
# against this so `direct_transfer` (underscore) aborts instead of resolving 0 addresses and
# exiting 0, which is indistinguishable from "this chain has none".
KNOWN_CLASSES = {"direct-transfer", "other", "canonical-deposit", "protocol-message"}

LEGACY_FINALIZE_DEPOSIT = "0xcfe7af7c"  # finalizeDeposit(address,address,address,uint256,bytes)
V26_FINALIZE_DEPOSIT = "0x9c884fd1"     # finalizeDeposit(uint256,bytes32,bytes) — the receiver
                                        # is nested in the bytes blob; NOT decoded (METHOD §1)
DELEGATION_PREFIX = "0xef0100"          # EIP-7702 delegation indicator
HEXDIGITS = set("0123456789abcdefABCDEF")


def unusable(reply):
    """Describe a reply that carries no result, or None if it does. Never returns ''."""
    if isinstance(reply, dict) and "error" in reply:
        return f"json-rpc error {json.dumps(reply['error'])[:160]}"
    return f"unusable reply {str(reply)[:120]}"


def post(url, payload, timeout=40, tries=4):
    """POST JSON via curl -> (parsed_reply, error). error is None once a usable reply arrives.

    "Usable" means a list for a batch payload and an object carrying `result` for a single
    call. Everything else — transport failure, unparseable body, or a JSON-RPC {"error": ...}
    object — is retried with exponential backoff. Backing off on error replies is the point:
    a throttling endpoint returns HTTP 200 with an error body, so retrying only transport
    failures gives it no backoff at all and converts throttling into lost addresses
    (METHOD §6.9).
    """
    batched = isinstance(payload, list)
    reply, err = None, "no attempt made"
    for attempt in range(tries):
        p = subprocess.run(
            ["curl", "-s", "-m", str(timeout), "-X", "POST",
             "-H", "content-type: application/json", "--data", json.dumps(payload), url],
            capture_output=True, text=True)
        if p.returncode != 0 or not p.stdout.strip():
            reply, err = None, f"curl rc={p.returncode} {(p.stderr or '').strip()[:80]}".strip()
        else:
            try:
                reply = json.loads(p.stdout)
            except ValueError:
                reply, err = None, f"unparseable reply {p.stdout.strip()[:120]}"
            else:
                if batched:
                    err = None if isinstance(reply, list) else unusable(reply)
                else:
                    err = None if isinstance(reply, dict) and "result" in reply else unusable(reply)
                if err is None:
                    return reply, None
        if attempt + 1 < tries:           # no backoff after the final attempt
            time.sleep(1.5 * (2 ** attempt))
    return reply, err


def call_one(url, call):
    """Run one (method, params) -> (result, error). `result` may legitimately be null."""
    method, params = call
    reply, err = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    return (reply["result"], None) if err is None else (None, err)


def call_batch(url, calls, chunk=60):
    """Run [(method, params), ...] as batched JSON-RPC -> (results, dead).

    results[i] = (value, error), aligned with `calls`. error is None when the endpoint
    answered call i; `value` is then the raw `result`, which may be null — whether null is a
    value (eth_getTransactionByHash on a tx that is not on the chain) or a failure
    (eth_getCode) is the caller's decision, never this function's.

    dead=True means a chunk produced nothing usable AND a single-call probe of it also
    produced nothing: the endpoint is down or throttling hard. Remaining calls are returned
    as skips rather than retried, because grinding 60 calls × 4 attempts × backoff through a
    dead host is exactly what --max-dead-batches exists to prevent.
    """
    results = []
    for start in range(0, len(calls), chunk):
        part = calls[start:start + chunk]
        got = [None] * len(part)
        payload = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                   for i, (m, p) in enumerate(part)]
        reply, err = post(url, payload)
        if err is None:
            for item in reply:
                if not isinstance(item, dict):
                    continue
                i = item.get("id")
                if not (isinstance(i, int) and 0 <= i < len(part)):
                    continue          # never trust a server-supplied index
                got[i] = (item["result"], None) if "result" in item else (None, unusable(item))
        else:
            print(f"    ! batch of {len(part)} failed: {err}", file=sys.stderr)
        pending = [j for j in range(len(part)) if got[j] is None]
        if pending and not any(g and g[1] is None for g in got):
            # The batch answered nothing usable. Probe exactly ONE call to tell "endpoint is
            # dead" from "endpoint is alive but dislikes batches" before spending the rest.
            j = pending[0]
            got[j] = call_one(url, part[j])
            if got[j][1] is not None:
                for k in pending[1:]:
                    got[k] = (None, "skipped: endpoint answered neither the batch nor a probe")
                results.extend(got)
                results.extend([(None, "skipped: endpoint declared dead earlier in this batch")]
                               * (len(calls) - len(results)))
                return results, True
            pending = pending[1:]
        for j in pending:                 # only the calls the batch actually missed
            got[j] = call_one(url, part[j])
        results.extend(got)
    return results, False


def save_json(obj, path):
    """Atomic checkpoint: write to <path>.tmp, fsync, rename over <path>."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=0, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_json(path, required=False):
    """Load a checkpointed cache, or {} if absent. Never silently return {} on a corrupt file.

    `required=True` is for an *input* file: a path typo must abort, not read as "empty", or
    the run produces a plausible empty output and exits 0.
    """
    if not os.path.exists(path):
        if required:
            sys.exit(f"FATAL: {path} does not exist.\n"
                     f"       This is a required input, not something to default to empty — a "
                     f"path typo would otherwise look exactly like 'nothing to do' and exit 0.")
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except ValueError as e:
        sys.exit(f"FATAL: {path} is not valid JSON ({e}).\n"
                 f"       A leftover {path}.tmp may hold a partial write — inspect both, do not "
                 f"delete blindly.")
    if required and not data:
        sys.exit(f"FATAL: {path} is empty ({{}}). Nothing was ever resolved into it, so there is "
                 f"nothing to verify — run resolve_l2_code.py for this chain first.")
    return data


def check_chain_id(url, chain):
    """Abort unless the endpoint reports the chain id ../CHAINS.md records for `chain`."""
    want = CHAINS[chain][0]
    reply, err = post(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
                      timeout=15, tries=2)
    got = reply.get("result") if err is None else None
    if not isinstance(got, str):
        sys.exit(f"FATAL: {url} did not answer eth_chainId (expected {want} for '{chain}'): "
                 f"{err or repr(got)}\n"
                 f"       The endpoint is dead or not a JSON-RPC node. Find a replacement and "
                 f"pass --rpc, and record the substitution in the manifest (TASK Phase 0).")
    try:
        got_i = int(got, 16)
    except ValueError:
        sys.exit(f"FATAL: {url} returned a non-numeric eth_chainId: {got!r}")
    if got_i != want:
        sys.exit(f"FATAL: chain mismatch — {url} reports chainId {got_i}, but --chain {chain} "
                 f"expects {want} (../CHAINS.md).\n"
                 f"       Resolving one chain's addresses against another's RPC is METHOD §6 "
                 f"pitfall 2; refusing to continue.")
    return got_i


def check_file_name(path, chain, allow_mismatch, flag):
    """Every per-chain file, read or written, must name --chain and no other chain.

    Applied to --in, --code *and* --out. --in and --code are the doors pitfall 2 comes
    through directly: a code cache from another chain passes the eth_chainId and --in checks
    untouched and then probes the wrong chain's addresses. --out is checked because the other
    two guards trust filenames to be truthful — zero's verdicts written to `era.json` later
    satisfy the --code check on an `--chain era` run, so a mislabelled write defeats the
    read-side guard downstream. Naming is enforced where the lie would be created.

    The filename is split into tokens, so `zero.jsonl`, `zero-code.json` and
    `zero@0x34ad51.json` all name zero while `era.json` never does. Token matching, not
    substring matching: a chain key must not be found inside an unrelated word.
    """
    if allow_mismatch:
        return
    name = os.path.basename(path)
    tokens = set(re.split(r"[^a-z0-9]+", name.lower()))
    if chain in tokens:
        wrong = sorted(tokens & (set(CHAINS) - {chain}))
        if not wrong:
            return
        sys.exit(f"FATAL: {flag} is '{name}', which names both '{chain}' and {wrong}.\n"
                 f"       Rename it so exactly one chain is identifiable, or pass "
                 f"--allow-input-name-mismatch.")
    wrong = sorted(tokens & set(CHAINS))
    sys.exit(f"FATAL: {flag} is '{name}' but --chain is '{chain}'"
             f"{f' — that filename names {wrong}' if wrong else ''}.\n"
             f"       Mixing one chain's addresses with another chain's RPC produces "
             f"plausible-looking nonsense (METHOD §6 pitfall 2). Put the chain in the filename "
             f"(e.g. {chain}.json, {chain}-code.json), or pass --allow-input-name-mismatch if "
             f"you renamed the file deliberately.")


def check_input_name(path, chain, allow_mismatch):
    check_file_name(path, chain, allow_mismatch, "--in")


def classify(code):
    """-> (kind, code_len_bytes). Empty code on a ZK-stack chain means a plain EOA (METHOD §2).

    `code` must be the hex string an endpoint actually returned. None, a missing field, or a
    JSON null is a FAILED CALL, not empty code, and raises here: accepting one would let a
    stub, dead or throttling endpoint report a whole chain as `eoa` without a single warning
    (METHOD §2, §6 pitfall 2). Callers must check the error before calling this.
    """
    if not isinstance(code, str):
        raise TypeError(f"classify() needs the code hex an endpoint returned, got {code!r} — "
                        f"a missing result is a failed call, never 'eoa'")
    if code in ("", "0x", "0x0"):
        return "eoa", 0
    if not (code.startswith("0x") and len(code) % 2 == 0 and HEXDIGITS.issuperset(code[2:])):
        raise ValueError(f"classify() got something that is not a code hex string: {code[:40]!r}")
    n = len(code) // 2 - 1
    if code.lower().startswith(DELEGATION_PREFIX):
        return "delegated-eoa", n
    return "contract", n


def codehash(code):
    """Clustering key: sha256 of the lowercased code hex. NOT the EVM keccak codehash."""
    return hashlib.sha256(code.lower().encode()).hexdigest()


def get_code_batch(url, addrs, block):
    """-> ({addr: code_hex}, dead). Only addresses that answered with a code STRING appear."""
    results, dead = call_batch(url, [("eth_getCode", [a, block]) for a in addrs],
                               chunk=max(1, len(addrs)))
    out = {}
    for a, (code, err) in zip(addrs, results):
        if err is None and isinstance(code, str):
            out[a] = code
        elif not dead:                    # a dead batch already printed its own diagnostic
            print(f"    ! unresolved {a}: "
                  f"{err or f'result is not a code string: {code!r}'}", file=sys.stderr)
    return out, dead


def beneficiary_of(rec):
    """Canonical-deposit record -> (l2_receiver, None) or (None, skip_reason).

    Legacy `finalizeDeposit(address l1Sender, address l2Receiver, address l1Token,
    uint256 amount, bytes data)`: the beneficiary is the 2nd ABI word, `data[98:138]`.
    The v26 selector 0x9c884fd1 = finalizeDeposit(uint256,bytes32,bytes) carries the
    receiver inside the nested bytes blob and is NOT decoded here (METHOD §1); those records
    are returned as counted skips, never silently dropped.

    This lives here and check_code_time.py imports it: if the two scripts decoded deposits
    differently, the extra beneficiaries would reach the code cache with no earliest tx and
    land in the "no in-window record" bucket, looking like a data problem rather than skew.
    """
    sel = rec.get("selector")
    if sel == V26_FINALIZE_DEPOSIT:
        return None, (f"v26 selector {V26_FINALIZE_DEPOSIT} finalizeDeposit(uint256,bytes32,"
                      f"bytes): receiver is nested in the bytes blob, not decoded (METHOD §1)")
    if sel != LEGACY_FINALIZE_DEPOSIT:
        return None, f"unhandled canonical-deposit selector {sel!r}"
    d = rec.get("data") or ""
    if len(d) < 138:
        return None, (f"calldata too short for 2 ABI words ({len(d)} hex chars"
                      f"{', truncated in the census' if rec.get('data_truncated') else ''})")
    word = d[10 + 64:10 + 128]            # 2nd ABI word, all 32 bytes
    if word[:24].strip("0"):
        return None, f"2nd ABI word is not a zero-padded address ({word})"
    return "0x" + word[24:].lower(), None


def collect_targets(path, classes, deposit_beneficiaries):
    """-> (targets, skips): distinct lowercase L2 addresses to resolve, plus a skip tally."""
    targets, skips = set(), {}
    for line in open(path):
        r = json.loads(line)
        cls = r.get("class")
        if cls in classes:
            targets.add(r["to"].lower())
        if deposit_beneficiaries and cls == "canonical-deposit":
            addr, why = beneficiary_of(r)
            if addr:
                targets.add(addr)
            else:
                skips[why] = skips.get(why, 0) + 1
    return targets, skips


def report_skips(skips, label):
    """Under-coverage must be visible; a silent skip reads as complete coverage."""
    for why, n in sorted(skips.items(), key=lambda kv: -kv[1]):
        print(f"!! {n} {label} record(s) contributed no address: {why}", file=sys.stderr)


def check_classes(classes):
    unknown = sorted(classes - KNOWN_CLASSES)
    if unknown:
        sys.exit(f"FATAL: unknown --classes value(s) {unknown}.\n"
                 f"       The census only emits {sorted(KNOWN_CLASSES)} "
                 f"(../../results/scripts/enrich.py:classify). A typo such as 'direct_transfer' "
                 f"would otherwise resolve 0 addresses and exit 0.")


def normalize_block(tag):
    """Decimal or hex block -> hex quantity; None for a moving tag (latest/pending/safe/...)."""
    t = str(tag)
    if t.isdigit():
        return hex(int(t))
    if t.startswith("0x") and len(t) > 2 and HEXDIGITS.issuperset(t[2:]):
        return t
    return None


def resolve_block(url, tag, cached_blocks):
    """Turn --block into ONE concrete block before anything is written to the cache.

    A moving tag stored verbatim makes the one-block-per-cache guard vacuous: era's 18k
    addresses take hundreds of batches, and an interrupted run resumed the next day would
    merge verdicts read at two chain tips while the guard compared "latest" to "latest"
    (OUTPUT_SPEC §1). A resumed run adopts the block already in the cache so that
    resumability survives the fix.
    """
    explicit = normalize_block(tag)
    if explicit:
        return explicit
    if len(cached_blocks) == 1:
        block = cached_blocks[0]
        print(f"--block {tag}: resuming at {block}, the block already in the cache — reading the "
              f"current tip instead would mix two chain states in one file", file=sys.stderr)
        return block
    reply, err = post(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
                      timeout=15, tries=3)
    block = reply.get("result") if err is None else None
    if not isinstance(block, str) or not normalize_block(block):
        sys.exit(f"FATAL: --block {tag} must become a concrete block and {url} did not serve "
                 f"eth_blockNumber ({err or repr(block)}).\n"
                 f"       Pass --block <hex block> explicitly.")
    print(f"--block {tag} resolved to {block}; every entry records that block", file=sys.stderr)
    return block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=sorted(CHAINS))
    ap.add_argument("--in", dest="inp", required=True, help="results/enriched/<chain>.jsonl")
    ap.add_argument("--out", required=True, help="code cache JSON (resumable)")
    ap.add_argument("--classes", default="direct-transfer,other",
                    help="comma-separated record classes whose 'to' to resolve")
    ap.add_argument("--deposit-beneficiaries", action="store_true",
                    help="also resolve l2Receiver decoded from canonical-deposit calldata")
    ap.add_argument("--rpc", help="override endpoint (record substitutions in the manifest)")
    ap.add_argument("--block", default="latest",
                    help="block tag/number for the whole run (archive needed if historical). A "
                         "moving tag is resolved to a concrete block via eth_blockNumber. One "
                         "cache file holds exactly one block; use a separate --out per block.")
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=0.25, help="pause between batches (be polite)")
    ap.add_argument("--checkpoint", type=int, default=10,
                    help="atomic save every N batches (the cache is rewritten in full each "
                         "time, so saving every batch is O(n^2) I/O on era)")
    ap.add_argument("--max-dead-batches", type=int, default=3,
                    help="abort after this many consecutive batches that resolve nothing")
    ap.add_argument("--allow-empty", action="store_true",
                    help="proceed when the selected classes yield no address (legitimate for "
                         "e.g. --classes protocol-message on zkcandy, which has none)")
    ap.add_argument("--allow-input-name-mismatch", action="store_true",
                    help="skip the --in/--out (and --code, in check_code_time.py) filename "
                         "checks against --chain (you renamed the files yourself)")
    ap.add_argument("--no-chain-check", action="store_true",
                    help="skip the eth_chainId assertion (only for an endpoint that cannot serve "
                         "it; record the reason in the manifest)")
    a = ap.parse_args()

    url = a.rpc or CHAINS[a.chain][1]
    check_input_name(a.inp, a.chain, a.allow_input_name_mismatch)
    # Enforced on the way OUT too: a cache written under the wrong chain's name passes the
    # --code check on a later run of that other chain (see check_file_name).
    check_file_name(a.out, a.chain, a.allow_input_name_mismatch, "--out")
    if a.no_chain_check:
        print(f"!! eth_chainId check skipped for {url} — justify this in the manifest",
              file=sys.stderr)
    else:
        check_chain_id(url, a.chain)

    classes = {c.strip() for c in a.classes.split(",") if c.strip()}
    check_classes(classes)
    targets, skips = collect_targets(a.inp, classes, a.deposit_beneficiaries)
    report_skips(skips, "canonical-deposit")
    if not targets and not a.allow_empty:
        sys.exit(f"FATAL: --classes {a.classes}"
                 f"{' --deposit-beneficiaries' if a.deposit_beneficiaries else ''} selects no "
                 f"address in {a.inp}.\n"
                 f"       Writing an empty cache and exiting 0 would be indistinguishable from "
                 f"a successful run. Check --classes/--in, or pass --allow-empty if this chain "
                 f"genuinely has none.")

    cache = load_json(a.out)
    cached_blocks = sorted({str(v.get("block")) for v in cache.values() if isinstance(v, dict)})
    block = resolve_block(url, a.block, cached_blocks)
    other_blocks = [b for b in cached_blocks if b != block]
    if other_blocks:
        sys.exit(f"FATAL: {a.out} already holds entries resolved at block(s) "
                 f"{', '.join(other_blocks)}, but this run resolves at '{block}'.\n"
                 f"       Code status is block-dependent; mixing blocks in one cache would make "
                 f"latest and historical verdicts indistinguishable. Re-run with --block "
                 f"{other_blocks[0]} (needs archive), or use a separate --out per block "
                 f"(e.g. code/{a.chain}@{block}.json).")
    todo = sorted(t for t in targets if t not in cache)
    print(f"{a.chain}: {len(targets)} targets, {len(cache)} cached, {len(todo)} to resolve "
          f"via {url} @ {block}", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    dead = 0
    try:
        for n, i in enumerate(range(0, len(todo), a.batch), start=1):
            chunk = todo[i:i + a.batch]
            got, batch_dead = get_code_batch(url, chunk, block)
            for addr, code in got.items():
                kind, size = classify(code)
                cache[addr] = {"len": size, "kind": kind, "block": block,
                               "codehash": codehash(code) if size else None}
            if n % a.checkpoint == 0:
                save_json(cache, a.out)
            print(f"  {min(i + a.batch, len(todo))}/{len(todo)}", file=sys.stderr)
            if got and not batch_dead:
                dead = 0
            else:
                dead += 1
                if dead >= a.max_dead_batches:
                    save_json(cache, a.out)
                    sys.exit(f"FATAL: {dead} consecutive batches resolved nothing via {url}. The "
                             f"endpoint is down or throttling hard — stopping instead of grinding "
                             f"through {len(todo) - i - len(chunk)} more addresses one at a "
                             f"time.\n"
                             f"       {len(cache)} entries are checkpointed in {a.out}; fix the "
                             f"endpoint (--rpc) and re-run to resume.")
            time.sleep(a.sleep)
    finally:
        save_json(cache, a.out)

    resolved = {t: cache[t] for t in targets if t in cache}
    kinds, fams = {}, {}
    for v in resolved.values():
        kinds[v["kind"]] = kinds.get(v["kind"], 0) + 1
        if v["kind"] == "contract":
            fams[v["codehash"]] = fams.get(v["codehash"], 0) + 1
    print(f"\n{a.chain}: resolved {len(resolved)}/{len(targets)}  kinds={kinds}  "
          f"distinct_contract_bytecodes={len(fams)}", file=sys.stderr)
    if len(resolved) != len(targets):
        print(f"  !! {len(targets) - len(resolved)} address(es) UNRESOLVED — "
              f"declare them in the report, do not assume EOA", file=sys.stderr)


if __name__ == "__main__":
    main()
