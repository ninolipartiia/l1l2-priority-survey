#!/usr/bin/env python3
"""Scan L1->L2 priority transactions for a ZK-stack chain via NewPriorityRequest events.

Reads NewPriorityRequest events from the chain's diamond proxy on Ethereum L1,
decodes the embedded L2CanonicalTransaction, optionally attaches the L1 initiator
(the EOA/contract that sent the L1 tx), and writes one JSON record per priority
transaction to a JSONL file.

Resumable: a .ckpt sidecar records (chain, window, last completed block). The
checkpoint is bound to that identity — rerunning with a different chain or window
against the same --out aborts instead of corrupting data. On resume, records already
on disk are never duplicated (dedupe on tx_id), and a malformed final line left by a
crash mid-write is dropped and rescanned. To restart from scratch, delete BOTH the
output file and its .ckpt.

Audit trail: every run appends JSON lines to <out>.runlog — a "start" event (identity,
resolved ETH block bounds, resume state), one "chunk" event per completed chunk (block
range, which endpoint served it, log/record counts, wall seconds), and a "done" event
(totals, txId range, gaps). Pair it with the run manifest for execution provenance.

Usage:
  python3 scan_priority.py --chain lens --from 2026-08-20 --to 2026-08-22 --out lens.jsonl
  python3 scan_priority.py --chain era --from 2025-08-25 --to 2026-08-25 --out era.jsonl

Dates are UTC (YYYY-MM-DD, end date exclusive). Requires only python3 + curl.

Verified 2026-08-25 against all 8 target chains (see VALIDATION_LOG.md).
"""
import argparse, datetime, json, os, subprocess, sys, time

NEW_PRIORITY_REQUEST_TOPIC = "0x4531cd5795773d7101c17bdeb9f5ab7f47d7056017506f937083be5d6e77a382"

# chain -> (chainId, diamond proxy on Ethereum L1, public L2 RPC)
# Diamond proxies read from Bridgehub 0x303a465B659cBB0ab36eE643eA362c509EEb5213
# via getZKChain(chainId) on 2026-08-25.
CHAINS = {
    "era":      (324,    "0x32400084c286cf3e17e7b677ea9583e60a000324", "https://mainnet.era.zksync.io"),
    "abstract": (2741,   "0x2edc71e9991a962c7fe172212d1aa9e50480fbb9", "https://api.mainnet.abs.xyz"),
    "sophon":   (50104,  "0x05ede6ad1f39b7a16c949d5c33a0658c9c7241e3", "https://rpc.sophon.xyz"),
    "lens":     (232,    "0xc29d04a93f893700015138e3e334eb828dac3cef", "https://rpc.lens.xyz"),
    "cronos":   (388,    "0x7b2da4e77bae0e0d23c53c3be6650497d0576cfc", "https://mainnet.zkevm.cronos.org"),
    "zero":     (543210, "0xdbd849acc6ba61f461cb8a41bbaee2d673ca02d9", "https://rpc.zerion.io/v1/zero"),
    "zkcandy":  (320,    "0xf2704433d11842d15aa76bbf0e00407267a99c92", "https://rpc.zkcandy.io"),
    "openzk":   (1345,   "0x89f90748a9a36c30a324481133fa198f4e16a824", "https://rpc.openzk.net"),
}

# Public Ethereum RPCs that serve historical eth_getLogs (verified 2026-08-25).
# Both cap ranges at 10k blocks; both rate-limit under sustained load; both include
# the (non-standard) blockTimestamp field in log objects.
ETH_RPCS = ["https://eth.drpc.org", "https://rpc.mevblocker.io"]
CHUNK = 10_000
DATA_CAP_HEX = 16_384  # cap stored calldata at 8 KiB (16384 hex chars)


class RangeLimitError(RuntimeError):
    """Deterministic 'query too large' getLogs failure — don't waste retries on it."""


def looks_range_limited(msg):
    m = msg.lower()
    # throttling/transient wordings must keep retrying + rotating, never fail fast
    if any(s in m for s in ("rate", "429", "too many requests", "concurrent", "timeout")):
        return False
    return any(s in m for s in (
        "range", "response size", "returned more than",
        "too many results", "too many logs", "too large", "too big"))


class Rpc:
    def __init__(self, urls):
        self.urls = list(urls)
        self.i = 0
        self.last_url = None  # endpoint that served the most recent request

    def _post(self, payload, timeout):
        url = self.urls[self.i % len(self.urls)]
        self.last_url = url
        r = subprocess.run(
            ["curl", "-s", "-m", str(timeout), "-X", "POST",
             "-H", "Content-Type: application/json", "--data", payload, url],
            capture_output=True, text=True)
        if not r.stdout:
            raise RuntimeError(f"empty response from {url}")
        return json.loads(r.stdout)

    def call(self, method, params, timeout=45, fail_fast_range=False):
        """fail_fast_range is passed ONLY by the eth_getLogs call site, which sits in
        a chunk-halving loop; everywhere else all errors get the full retry cycle."""
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        delay = 1.0
        for attempt in range(8):
            try:
                resp = self._post(payload, timeout)
                if "result" in resp:
                    return resp["result"]
                msg = str(resp.get("error", ""))
                if fail_fast_range and looks_range_limited(msg):
                    raise RangeLimitError(msg[:200])
                raise RuntimeError(msg[:200])
            except RangeLimitError:
                raise
            except Exception as e:
                self.i += 1  # rotate endpoint
                if attempt == 7:
                    raise
                print(f"    retry {attempt+1} ({e})", file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 2, 30)

    def batch(self, calls, timeout=60):
        """calls: list of (method, params). Returns list of results (None on per-item error)."""
        payload = json.dumps([
            {"jsonrpc": "2.0", "id": i, "method": m, "params": p}
            for i, (m, p) in enumerate(calls)])
        delay = 1.0
        for attempt in range(8):
            try:
                resp = self._post(payload, timeout)
                if isinstance(resp, list):
                    out = [None] * len(calls)
                    for item in resp:
                        if "result" in item:
                            out[item["id"]] = item["result"]
                    return out
                raise RuntimeError(str(resp.get("error", "batch rejected"))[:200])
            except Exception as e:
                self.i += 1
                if attempt == 7:
                    # fall back to sequential
                    return [self.call(m, p) for m, p in calls]
                print(f"    batch retry {attempt+1} ({e})", file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 2, 30)


def block_at_timestamp(rpc, ts):
    """First Ethereum block with timestamp >= ts (binary search)."""
    lo, hi = 1, int(rpc.call("eth_blockNumber", []), 16)
    while lo < hi:
        mid = (lo + hi) // 2
        bts = int(rpc.call("eth_getBlockByNumber", [hex(mid), False])["timestamp"], 16)
        if bts < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def decode_event(lg):
    """Decode NewPriorityRequest(uint256 txId, bytes32 txHash, uint64 expiration,
    L2CanonicalTransaction tx, bytes[] factoryDeps) from raw log data."""
    d = lg["data"][2:]
    w = lambda i: d[i * 64:(i + 1) * 64]
    base = int(w(3), 16) // 32  # word offset of the struct
    f = lambda i: w(base + i)
    data_off = base + int(f(14), 16) // 32
    data_len = int(w(data_off), 16)
    data_hex = d[(data_off + 1) * 64:(data_off + 1) * 64 + data_len * 2]
    truncated = len(data_hex) > DATA_CAP_HEX
    bts = lg.get("blockTimestamp")  # non-standard field; present on both verified endpoints
    return {
        "tx_id": int(w(0), 16),
        "canonical_hash": "0x" + w(1),
        "tx_type": int(f(0), 16),
        "from": "0x" + f(1)[-40:],
        "to": "0x" + f(2)[-40:],
        "gas_limit": int(f(3), 16),
        "value": int(f(9), 16),
        "reserved": [int(f(10 + i), 16) for i in range(4)],
        "data_len": data_len,
        "selector": "0x" + data_hex[:8] if data_len >= 4 else "",
        "data": "0x" + (data_hex[:DATA_CAP_HEX] if truncated else data_hex),
        "data_truncated": truncated,
        "ts": int(bts, 16) if bts else None,
        "l1_block": int(lg["blockNumber"], 16),
        "l1_tx": lg["transactionHash"],
        "log_index": int(lg["logIndex"], 16),
        "l1_from": None,
        "l1_to": None,
    }


def load_tx_ids(path, repair=False):
    """tx_ids present in a JSONL file. A malformed FINAL line (crash remnant from a
    kill mid-write) is dropped — and physically removed when repair=True — because
    its block range was never checkpointed and will be rescanned. Malformed lines
    anywhere else mean real corruption: abort."""
    ids = set()
    try:
        lines = open(path).read().splitlines()
    except FileNotFoundError:
        return ids
    for i, line in enumerate(lines):
        try:
            ids.add(json.loads(line)["tx_id"])
        except (ValueError, KeyError):
            if i != len(lines) - 1:
                sys.exit(f"ERROR: {path} line {i+1} is malformed mid-file — "
                         f"inspect manually before rerunning")
            print(f"WARNING: dropping malformed final line of {path} "
                  f"(crash remnant; its block range will be rescanned)", file=sys.stderr)
            if repair:
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    f.write("".join(l + "\n" for l in lines[:-1]))
                os.replace(tmp, path)
    return ids


def summarize(out_path):
    """Source of truth for count/range/gaps: the file itself (survives resumes)."""
    ids = load_tx_ids(out_path)
    if not ids:
        return 0, None, None, []
    s = sorted(ids)
    gaps = [(a + 1, b - 1) for a, b in zip(s, s[1:]) if b - a > 1]
    return len(s), s[0], s[-1], gaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=sorted(CHAINS))
    ap.add_argument("--from", dest="date_from", required=True, help="UTC start date YYYY-MM-DD (inclusive)")
    ap.add_argument("--to", dest="date_to", required=True, help="UTC end date YYYY-MM-DD (exclusive)")
    ap.add_argument("--out", required=True, help="output JSONL path")
    ap.add_argument("--no-initiators", action="store_true", help="skip fetching L1 tx senders")
    ap.add_argument("--eth-rpc", action="append", default=None, help="override Ethereum RPC (repeatable)")
    args = ap.parse_args()

    # checkpoint is bound to (chain, window); validate identity BEFORE any RPC work
    ckpt_path = args.out + ".ckpt"
    ident = {"chain": args.chain, "from": args.date_from, "to": args.date_to}
    ckpt = None
    if os.path.exists(ckpt_path):
        try:
            ckpt = json.load(open(ckpt_path))
        except ValueError:
            ckpt = "corrupt"
        if not isinstance(ckpt, dict):  # also catches pre-v2 bare-int checkpoints
            sys.exit(f"ERROR: unreadable/legacy checkpoint {ckpt_path} — "
                     f"delete BOTH it and {args.out} to restart")
        if {k: ckpt.get(k) for k in ident} != ident:
            sys.exit(f"ERROR: {ckpt_path} belongs to {ckpt}, not to {ident}.\n"
                     f"Use a different --out, or delete BOTH {args.out} and {ckpt_path} to restart.")
    elif os.path.exists(args.out) and os.path.getsize(args.out) > 0:
        sys.exit(f"ERROR: {args.out} exists (no checkpoint) — refusing to overwrite; "
                 f"delete it or choose another --out")

    chain_id, diamond, l2rpc = CHAINS[args.chain]
    rpc = Rpc(args.eth_rpc or ETH_RPCS)
    ts_from = int(datetime.datetime.fromisoformat(args.date_from + "T00:00:00+00:00").timestamp())
    ts_to = int(datetime.datetime.fromisoformat(args.date_to + "T00:00:00+00:00").timestamp())
    b_from = block_at_timestamp(rpc, ts_from)
    b_to = block_at_timestamp(rpc, ts_to) - 1
    print(f"{args.chain} (chainId {chain_id}): ETH blocks {b_from}..{b_to} "
          f"({max(0, (b_to - b_from) // CHUNK + 1)} chunks)")

    start, seen_ids = b_from, set()
    if ckpt is not None:
        start = max(start, ckpt["last_block"] + 1)
        seen_ids = load_tx_ids(args.out, repair=True)
        print(f"resuming from block {start} ({len(seen_ids)} records already on disk)")
    else:
        open(args.out, "w").close()

    runlog_path = args.out + ".runlog"

    def runlog(event, **kw):
        rec = {"event": event,
               "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               **kw}
        with open(runlog_path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    runlog("start", **ident, eth_blocks=[b_from, b_to],
           resumed=ckpt is not None, from_block=start, records_on_disk=len(seen_ids))

    def save_ckpt(last_block):
        tmp = ckpt_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({**ident, "last_block": last_block}, f)
        os.replace(tmp, ckpt_path)

    n_new = n_dup = 0
    with open(args.out, "a") as out:
        cur = start
        while cur <= b_to:
            t0 = time.time()
            span = CHUNK
            while True:  # halve on too-large responses
                end = min(cur + span - 1, b_to)
                try:
                    logs = rpc.call("eth_getLogs", [{
                        "address": diamond, "fromBlock": hex(cur), "toBlock": hex(end),
                        "topics": [NEW_PRIORITY_REQUEST_TOPIC]}], fail_fast_range=True)
                    served = rpc.last_url
                    break
                except Exception as e:
                    if span <= 100:
                        raise
                    span //= 2
                    rpc.i += 1     # try the smaller chunk on the other endpoint
                    time.sleep(1.0)
                    print(f"    shrinking chunk to {span} ({e})", file=sys.stderr)
            recs = [decode_event(lg) for lg in logs]
            fresh = [r for r in recs if r["tx_id"] not in seen_ids]
            n_dup += len(recs) - len(fresh)
            if fresh and not args.no_initiators:
                for i in range(0, len(fresh), 50):
                    chunk = fresh[i:i + 50]
                    txs = rpc.batch([("eth_getTransactionByHash", [r["l1_tx"]]) for r in chunk])
                    for r, t in zip(chunk, txs):
                        if t is None:  # item-level error (e.g. throttled) -> retry solo
                            time.sleep(0.5)
                            t = rpc.call("eth_getTransactionByHash", [r["l1_tx"]])
                        r["l1_from"] = t["from"] if t else None
                        r["l1_to"] = t["to"] if t else None
                    time.sleep(0.25)
            for r in fresh:
                seen_ids.add(r["tx_id"])
                out.write(json.dumps(r) + "\n")
            n_new += len(fresh)
            out.flush()
            save_ckpt(end)
            runlog("chunk", from_block=cur, to_block=end, endpoint=served,
                   logs=len(recs), fresh=len(fresh), wall_s=round(time.time() - t0, 2))
            print(f"  blocks {cur}..{end}: +{len(fresh)} (total on disk {len(seen_ids)})")
            cur = end + 1
            time.sleep(0.25)

    # completeness: priority tx ids are sequential per chain; gaps within the
    # window mean events were emitted elsewhere (e.g. Gateway period) or missed.
    total, lo, hi, gaps = summarize(args.out)
    runlog("done", new=n_new, dups_skipped=n_dup, total_on_disk=total,
           tx_id_range=[lo, hi], gaps=gaps)
    dup_note = f" ({n_dup} crash-resume duplicates skipped)" if n_dup else ""
    if total:
        print(f"done: {total} priority txs on disk ({n_new} new this run{dup_note}), "
              f"txId {lo}..{hi}, internal gaps: {gaps if gaps else 'none'}")
    else:
        print("done: 0 priority txs in window")


if __name__ == "__main__":
    main()
