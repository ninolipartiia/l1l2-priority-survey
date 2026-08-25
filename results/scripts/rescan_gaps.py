#!/usr/bin/env python3
"""Rescan txId gaps in raw/<chain>.jsonl against independent L1 endpoints.

Root cause discovered 2026-08-25: eth.drpc.org free tier can return a successful
eth_getLogs response with events silently missing. Because priority txIds are dense
and sequential, every such loss shows up as a txId gap — this script closes them:

For each gap [a,b]: bound the L1 block range by the neighbor records' l1_block,
re-run eth_getLogs on endpoints independent of the original scan (tenderly,
onfinality, mevblocker), decode with the reference decoder from scan_priority.py,
fetch initiators, backfill ts, and append the recovered records to the JSONL.
Appends a "gap-rescan" event to <out>.runlog for provenance.

Usage: python3 rescan_gaps.py <chain> [...]
"""
import datetime, importlib.util, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "scan_priority", os.path.join(HERE, "..", "..", "scripts", "scan_priority.py"))
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

RESCUE_RPCS = ["https://gateway.tenderly.co/public/mainnet",
               "https://eth.api.onfinality.io/public",
               "https://rpc.mevblocker.io"]


def getlogs_multi(diamond, b0, b1):
    """Query the SAME range on >=2 independent endpoints; union the results,
    keyed by (blockNumber, logIndex). Belt and braces against silent loss."""
    seen = {}
    got = 0
    for url in RESCUE_RPCS:
        rpc = sp.Rpc([url])
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": diamond, "fromBlock": hex(b0), "toBlock": hex(b1),
                "topics": [sp.NEW_PRIORITY_REQUEST_TOPIC]}], timeout=60)
        except Exception as e:
            print(f"    {url} failed: {e}", file=sys.stderr)
            continue
        got += 1
        for lg in logs:
            seen[(lg["blockNumber"], lg["logIndex"])] = lg
        time.sleep(1.0)
        if got >= 2:
            break
    if got < 2:
        raise RuntimeError("fewer than 2 endpoints answered the gap rescan")
    return list(seen.values())


def main():
    for chain in sys.argv[1:]:
        cid, diamond, l2 = sp.CHAINS[chain]
        path = f"results/raw/{chain}.jsonl"
        recs = {}
        for line in open(path):
            r = json.loads(line)
            recs[r["tx_id"]] = r
        ids = sorted(recs)
        gaps = [(a + 1, b - 1) for a, b in zip(ids, ids[1:]) if b - a > 1]
        if not gaps:
            print(f"{chain}: no gaps", file=sys.stderr)
            continue
        rpc = sp.Rpc(RESCUE_RPCS[::-1])  # mevblocker first for tx fetches
        recovered = []
        for a, b in gaps:
            lo_blk = recs[a - 1]["l1_block"]          # neighbor below
            hi_blk = recs[b + 1]["l1_block"]          # neighbor above
            print(f"{chain}: gap {a}..{b} -> rescanning L1 blocks {lo_blk}..{hi_blk}",
                  file=sys.stderr)
            logs = getlogs_multi(diamond, lo_blk, hi_blk)
            new = [sp.decode_event(lg) for lg in logs]
            new = [r for r in new if a <= r["tx_id"] <= b]
            # initiators
            for i in range(0, len(new), 50):
                chunk = new[i:i + 50]
                txs = rpc.batch([("eth_getTransactionByHash", [r["l1_tx"]]) for r in chunk])
                for r, t in zip(chunk, txs):
                    if t is None:
                        t = rpc.call("eth_getTransactionByHash", [r["l1_tx"]])
                    r["l1_from"] = t["from"] if t else None
                    r["l1_to"] = t["to"] if t else None
            # ts backfill for endpoints without blockTimestamp
            need = sorted({r["l1_block"] for r in new if r["ts"] is None})
            if need:
                bts = rpc.batch([("eth_getBlockByNumber", [hex(bn), False]) for bn in need])
                m = {bn: int(bk["timestamp"], 16) for bn, bk in zip(need, bts) if bk}
                for r in new:
                    if r["ts"] is None:
                        r["ts"] = m.get(r["l1_block"])
            for r in new:
                r["source"] = "gap-rescan"
            recovered.extend(new)
            missing = set(range(a, b + 1)) - {r["tx_id"] for r in new}
            if missing:
                print(f"{chain}: STILL MISSING after rescan: {sorted(missing)}",
                      file=sys.stderr)
        if recovered:
            with open(path, "a") as f:
                for r in sorted(recovered, key=lambda x: x["tx_id"]):
                    f.write(json.dumps(r) + "\n")
            with open(path + ".runlog", "a") as f:
                f.write(json.dumps({
                    "event": "gap-rescan",
                    "at": datetime.datetime.now(datetime.timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "gaps": gaps, "recovered": sorted(r["tx_id"] for r in recovered),
                    "endpoints": RESCUE_RPCS}) + "\n")
        allids = sorted(set(list(recs) + [r["tx_id"] for r in recovered]))
        left = [(x + 1, y - 1) for x, y in zip(allids, allids[1:]) if y - x > 1]
        print(f"{chain}: recovered {len(recovered)}; remaining gaps: {left or 'none'}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
