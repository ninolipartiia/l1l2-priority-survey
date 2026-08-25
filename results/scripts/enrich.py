#!/usr/bin/env python3
"""Phase 3 enrichment: classify every raw record per METHOD.md §5 and emit
enriched/<chain>.jsonl. Optionally applies protocol attributions from
results/scripts/attribution.json (rerun after Phase 4 to fill `protocol`).

- Dedupes on tx_id, sorts by tx_id.
- Backfills null ts via eth_getBlockByNumber (batched).
- initiator_is_contract via batched eth_getCode(l1_from) on Ethereum, cached in
  results/scripts/codecache.json ("0x"==EOA approximation; EIP-7702 caveat applies).
- Classification:
    canonical-deposit : unalias(from) in CANONICAL_L1_BRIDGES (aliased bridge sender)
    direct-transfer   : inner_from == l1_from, data_len < 4, value > 0
    protocol-message  : inner_from != l1_from (aliased contract sender), not canonical
    other             : the rest (EOA calls with calldata; zero-value empty EOA txs)
  Gateway-recovered records (l1_from null): fallback aliasing test via L1 getCode.

Usage: python3 enrich.py <chain> [<chain> ...]
"""
import json, os, subprocess, sys, time

ALIAS = 0x1111000000000000000000000000000000001111
MOD = 1 << 160

# L1 contracts whose aliased address as inner `from` marks a canonical deposit
CANONICAL_L1_BRIDGES = {
    "0x8829ad80e425c646dab305381ff105169feece56": "L1AssetRouter",
    "0x57891966931eb4bb6fb81430e6ce0a03aabde063": "Era legacy L1ERC20Bridge",
    "0xd7f9f54194c633f36ccd5f3da84ad4a1c38cb2cb": "L1Nullifier (pre-v26 L1SharedBridge)",
}
ETH_RPCS = ["https://rpc.mevblocker.io", "https://eth.drpc.org"]
CODECACHE = os.path.join(os.path.dirname(__file__), "codecache.json")
ATTRIB = os.path.join(os.path.dirname(__file__), "attribution.json")
try:
    KINDS = json.load(open(os.path.join(os.path.dirname(__file__),
                                        "initiator-kinds.json")))["kinds"]
except (IOError, ValueError):
    KINDS = {}


def unalias(addr):
    return "0x%040x" % ((int(addr, 16) - ALIAS) % MOD)


def batch_rpc(calls, timeout=60, tries=6):
    """calls: [(method, params)]; returns list of results (None on persistent error)."""
    payload = json.dumps([{"jsonrpc": "2.0", "id": i, "method": m, "params": p}
                          for i, (m, p) in enumerate(calls)])
    delay = 1.0
    for a in range(tries):
        url = ETH_RPCS[a % len(ETH_RPCS)]
        r = subprocess.run(["curl", "-s", "-m", str(timeout), "-X", "POST",
                            "-H", "Content-Type: application/json", "--data", payload, url],
                           capture_output=True, text=True)
        try:
            resp = json.loads(r.stdout)
        except ValueError:
            resp = None
        if isinstance(resp, list):
            out = [None] * len(calls)
            for item in resp:
                if isinstance(item, dict) and "result" in item:
                    out[item["id"]] = item["result"]
            missing = [i for i, v in enumerate(out) if v is None]
            if not missing:
                return out
            # retry missing individually on the other endpoint
            time.sleep(1.0)
            for i in missing:
                m, p = calls[i]
                pl = json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p})
                for b in range(4):
                    rr = subprocess.run(["curl", "-s", "-m", "30", "-X", "POST",
                                         "-H", "Content-Type: application/json",
                                         "--data", pl, ETH_RPCS[(a + 1 + b) % len(ETH_RPCS)]],
                                        capture_output=True, text=True)
                    try:
                        j = json.loads(rr.stdout)
                        if "result" in j:
                            out[i] = j["result"]; break
                    except ValueError:
                        pass
                    time.sleep(1.0)
            return out
        time.sleep(delay); delay = min(delay * 2, 15)
    return [None] * len(calls)


def load_cache():
    try:
        return json.load(open(CODECACHE))
    except (IOError, ValueError):
        return {}


def has_code(addrs):
    """addr -> bool (code at latest on Ethereum). Cached."""
    cache = load_cache()
    todo = sorted({a.lower() for a in addrs if a} - set(cache))
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        res = batch_rpc([("eth_getCode", [a, "latest"]) for a in chunk])
        for a, c in zip(chunk, res):
            if c is not None:
                cache[a] = (c != "0x")
        print(f"  getCode {i + len(chunk)}/{len(todo)}", file=sys.stderr)
        time.sleep(0.3)
        if (i // 100) % 20 == 19:
            json.dump(cache, open(CODECACHE, "w"))
    json.dump(cache, open(CODECACHE, "w"))
    return cache


def load_raw(chain):
    seen, recs = set(), []
    for line in open(f"results/raw/{chain}.jsonl"):
        r = json.loads(line)
        if r["tx_id"] in seen:
            continue
        seen.add(r["tx_id"]); recs.append(r)
    recs.sort(key=lambda r: r["tx_id"])
    return recs


def backfill_ts(recs):
    missing_blocks = sorted({r["l1_block"] for r in recs
                             if r.get("ts") is None and r.get("l1_block")})
    if not missing_blocks:
        return 0
    ts_map = {}
    for i in range(0, len(missing_blocks), 50):
        chunk = missing_blocks[i:i + 50]
        res = batch_rpc([("eth_getBlockByNumber", [hex(b), False]) for b in chunk])
        for b, blk in zip(chunk, res):
            if blk:
                ts_map[b] = int(blk["timestamp"], 16)
        time.sleep(0.3)
    n = 0
    for r in recs:
        if r.get("ts") is None and r.get("l1_block") in ts_map:
            r["ts"] = ts_map[r["l1_block"]]; n += 1
    return n


def classify(r, code_of):
    l1f = r.get("l1_from")
    inner = r["from"].lower()
    una = unalias(inner)
    if una in CANONICAL_L1_BRIDGES:
        cls = "canonical-deposit"
    elif l1f is None:  # gateway-period recovery: fallback aliasing test
        cu, ci = code_of.get(una), code_of.get(inner)
        if cu and not ci:
            cls = "protocol-message"
        elif not cu and not ci:
            cls = "direct-transfer" if (r["data_len"] < 4 and r["value"] > 0) else "other"
        else:
            cls = "other"  # ambiguous — flagged below
    elif inner == l1f.lower():
        cls = "direct-transfer" if (r["data_len"] < 4 and r["value"] > 0) else "other"
    else:
        cls = "protocol-message"
    aliased = cls in ("canonical-deposit", "protocol-message")
    e = dict(r)
    e["class"] = cls
    e["unaliased_from"] = una if aliased else None
    if cls == "canonical-deposit":
        # 7702-delegated EOAs are users, not protocol contracts: only true
        # contracts (per initiator-kinds.json code-prefix classification) count.
        if l1f and code_of.get(l1f.lower()):
            kind = KINDS.get(l1f.lower(), "contract")
            e["deposit_by_contract"] = kind in ("contract", "eoa-now")
            e["deposit_via_7702"] = kind == "7702"
        else:
            e["deposit_by_contract"] = False if l1f else None
            e["deposit_via_7702"] = False if l1f else None
    e["initiator_is_contract"] = (bool(code_of.get(l1f.lower())) if l1f else None)
    e["protocol"] = None
    return e


def apply_attribution(recs):
    try:
        rules = json.load(open(ATTRIB))["rules"]
    except (IOError, ValueError):
        return
    for e in recs:
        for rule in rules:
            m = rule["match"]
            if "class" in m and e["class"] not in m["class"]:
                continue
            if "unaliased_from" in m and (e["unaliased_from"] or "") not in m["unaliased_from"]:
                continue
            if "to" in m and e["to"].lower() not in m["to"]:
                continue
            if "selector" in m and e["selector"] not in m["selector"]:
                continue
            if "l1_from" in m and (e.get("l1_from") or "").lower() not in m["l1_from"]:
                continue
            e["protocol"] = rule["protocol"]
            break


def main():
    for chain in sys.argv[1:]:
        recs = load_raw(chain)
        n_bf = backfill_ts(recs)
        # getCode targets: every l1_from; plus aliased/unaliased inner from for
        # gateway-period records (fallback aliasing test)
        targets = {r["l1_from"] for r in recs if r.get("l1_from")}
        for r in recs:
            if r.get("l1_from") is None:
                targets.add(r["from"]); targets.add(unalias(r["from"]))
        code_of = has_code(targets)
        enriched = [classify(r, code_of) for r in recs]
        apply_attribution(enriched)
        with open(f"results/enriched/{chain}.jsonl", "w") as f:
            for e in enriched:
                f.write(json.dumps(e) + "\n")
        from collections import Counter
        print(f"{chain}: {len(enriched)} records, ts backfilled {n_bf}, "
              f"classes {dict(Counter(e['class'] for e in enriched))}", file=sys.stderr)


if __name__ == "__main__":
    main()
