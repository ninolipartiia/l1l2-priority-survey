#!/usr/bin/env python3
"""Phase 2 completeness checks on raw/<chain>.jsonl (METHOD.md §7).

Per chain: dedupe on tx_id, report txId range + internal gaps, boundary check vs
getTotalPriorityTxs() on the L1 diamond, and L2 spot-verification of >=10 sampled
canonical hashes (expect type 0xff and matching from/to).

Usage: python3 check_completeness.py <chain> [<chain> ...]
Writes results to stdout as JSON (one object per chain).
"""
import json, random, subprocess, sys, time

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
ETH_RPCS = ["https://rpc.mevblocker.io", "https://eth.drpc.org"]


def rpc(url, method, params, timeout=30, tries=5):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    delay = 1.0
    for a in range(tries):
        r = subprocess.run(["curl", "-s", "-m", str(timeout), "-X", "POST",
                            "-H", "Content-Type: application/json", "--data", payload, url],
                           capture_output=True, text=True)
        try:
            resp = json.loads(r.stdout)
            if "result" in resp:
                return resp["result"]
        except ValueError:
            pass
        time.sleep(delay); delay = min(delay * 2, 10)
    raise RuntimeError(f"{method} failed on {url}")


def load(chain):
    seen, recs = set(), []
    for line in open(f"results/raw/{chain}.jsonl"):
        r = json.loads(line)
        if r["tx_id"] in seen:
            continue
        seen.add(r["tx_id"]); recs.append(r)
    return recs


def main():
    random.seed(20260825)
    out = {}
    for chain in sys.argv[1:]:
        cid, diamond, l2 = CHAINS[chain]
        recs = load(chain)
        ids = sorted(r["tx_id"] for r in recs)
        gaps = [[a + 1, b - 1] for a, b in zip(ids, ids[1:]) if b - a > 1]
        total_now = int(rpc(ETH_RPCS[1], "eth_call",
                            [{"to": diamond, "data": "0xa1954fc5"}, "latest"]), 16)
        boundary = "ok" if (not ids or ids[-1] + 1 <= total_now) else \
                   f"mismatch: max txId {ids[-1]} vs total {total_now}"
        # window-start proof: getTotalPriorityTxs at b_from-1 == first in-window txId
        # (historical eth_call verified working on tenderly + mevblocker)
        b_from = None
        for line in open(f"results/raw/{chain}.jsonl.runlog"):
            ev = json.loads(line)
            if ev["event"] == "start":
                b_from = ev["eth_blocks"][0]
        try:
            total_at_start = int(rpc("https://gateway.tenderly.co/public/mainnet",
                                     "eth_call", [{"to": diamond, "data": "0xa1954fc5"},
                                                  hex(b_from - 1)]), 16)
        except RuntimeError:
            total_at_start = int(rpc("https://rpc.mevblocker.io",
                                     "eth_call", [{"to": diamond, "data": "0xa1954fc5"},
                                                  hex(b_from - 1)]), 16)
        start_check = "ok" if (ids and ids[0] == total_at_start) else \
                      f"mismatch: first txId {ids[0] if ids else None} vs " \
                      f"count-at-window-start {total_at_start}"
        # sample across the window; avoid the newest 5 records (may be unexecuted)
        pool = recs[:-5] if len(recs) > 15 else recs
        sample = random.sample(pool, min(12, len(pool)))
        ok = bad = 0
        fails = []
        for r in sample:
            try:
                t = rpc(l2, "eth_getTransactionByHash", [r["canonical_hash"]])
            except RuntimeError:
                t = None
            if t and int(t.get("type", "0x0"), 16) == 255 and \
               t["from"].lower() == r["from"].lower() and \
               (t.get("to") or "").lower() == r["to"].lower():
                ok += 1
            else:
                bad += 1
                fails.append({"tx_id": r["tx_id"], "hash": r["canonical_hash"],
                              "got": None if not t else
                              {"type": t.get("type"), "from": t.get("from"), "to": t.get("to")}})
            time.sleep(0.3)
        out[chain] = {
            "records_deduped": len(recs),
            "tx_id_range": [ids[0], ids[-1]] if ids else None,
            "gaps": gaps,
            "expected_in_window": (ids[-1] - ids[0] + 1) if ids else 0,
            "total_priority_txs_now": total_now,
            "boundary_check": boundary,
            "window_start_check": start_check,
            "l2_spot_checks": {"sampled": len(sample), "ok": ok, "failed": bad,
                               **({"failures": fails} if fails else {})},
        }
        print(f"{chain}: {json.dumps(out[chain])}", file=sys.stderr)
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
