#!/usr/bin/env python3
"""Phase 5: build results/aggregates.json from enriched JSONL + completeness.json +
attribution.json (protocol metadata) + labels.json (address labels).

Definitions used (stated in REPORT.md):
- non_deposit = all classes except canonical-deposit (includes direct-transfer).
- unattributed = records of class protocol-message/other with protocol == null.
- unique users of a protocol = distinct l1_from among its records (unknown for
  gateway-period records lacking l1_from).
"""
import datetime, json, os, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(__file__)
CHAIN_IDS = {"era": 324, "abstract": 2741, "sophon": 50104, "lens": 232,
             "cronos": 388, "zero": 543210, "zkcandy": 320, "openzk": 1345}


def week(ts):
    d = datetime.datetime.utcfromtimestamp(ts).isocalendar()
    return f"{d[0]}-W{d[1]:02d}"


def day(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


def main():
    chains = sys.argv[1:]
    attrib = json.load(open(os.path.join(HERE, "attribution.json")))
    completeness = json.load(open(os.path.join(HERE, "completeness.json")))
    labels = json.load(open(os.path.join(HERE, "labels.json")))
    meta = {p["protocol"]: p for p in attrib["protocol_meta"]}
    sig = attrib.get("selector_signatures", {})
    runlog_bounds = {}
    agg = {"run": {"window": {"from": "2025-08-26", "to": "2026-08-26"},
                   "generated": datetime.datetime.now(datetime.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "chains": chains},
           "chains": {}, "cross_chain": {}}
    proto_chains = defaultdict(lambda: {"chains": set(), "l1": set()})
    init_chains = defaultdict(lambda: {"chains": set(), "n": 0})

    for chain in chains:
        recs = [json.loads(l) for l in open(f"results/enriched/{chain}.jsonl")]
        for line in open(f"results/raw/{chain}.jsonl.runlog"):
            ev = json.loads(line)
            if ev["event"] == "start":
                runlog_bounds[chain] = ev["eth_blocks"]
        by_class = Counter(r["class"] for r in recs)
        l1s = {r["l1_from"] for r in recs if r.get("l1_from")}
        inner = {r["from"] for r in recs}
        n = len(recs)
        nd = [r for r in recs if r["class"] != "canonical-deposit"]
        n_nd = len(nd)

        protos = []
        for pname, pr in sorted(
                ((p, [r for r in recs if r["protocol"] == p])
                 for p in {r["protocol"] for r in recs if r["protocol"]}),
                key=lambda kv: -len(kv[1])):
            m = meta[pname]
            ts = [r["ts"] for r in pr if r.get("ts")]
            users = {r["l1_from"] for r in pr if r.get("l1_from")}
            wk = Counter(week(t) for t in ts)
            sels = Counter(r["selector"] for r in pr)
            protos.append({
                "name": pname, "category": m["category"], "confidence": m["confidence"],
                "tx_count": len(pr), "share_of_all": round(len(pr) / n, 4) if n else 0,
                "share_of_non_deposit": round(len(pr) / n_nd, 4) if n_nd else 0,
                "unique_users": len(users),
                "first_seen": day(min(ts)) if ts else None,
                "last_seen": day(max(ts)) if ts else None,
                "weekly": [{"week": w, "tx_count": c} for w, c in sorted(wk.items())],
                "l1_addresses": m["l1_addresses"],
                "l2_addresses": m.get("l2_addresses_by_chain", {}).get(
                    chain, m.get("l2_addresses", [])),
                "selectors": [{"selector": s, "signature": sig.get(s, "?"), "count": c}
                              for s, c in sels.most_common()],
                "evidence": m["evidence"],
            })
            proto_chains[pname]["chains"].add(chain)
            proto_chains[pname]["l1"].update(a["address"] for a in m["l1_addresses"])

        dep_c = Counter(r["l1_from"] for r in recs
                        if r["class"] == "canonical-deposit" and r.get("deposit_by_contract"))
        dep_7702 = [r for r in recs
                    if r["class"] == "canonical-deposit" and r.get("deposit_via_7702")]
        top_init = Counter(r["l1_from"] for r in recs if r.get("l1_from"))
        code_of = json.load(open(os.path.join(HERE, "codecache.json")))
        kinds = json.load(open(os.path.join(HERE, "initiator-kinds.json")))["kinds"]
        una = [r for r in nd if r["class"] in ("protocol-message", "other")
               and not r["protocol"]]
        una_groups = Counter((r["unaliased_from"] or (r.get("l1_from") or "?"),
                              r["to"], r["selector"]) for r in una)
        for a, cnt in top_init.items():
            init_chains[a]["chains"].add(chain); init_chains[a]["n"] += cnt

        agg["chains"][chain] = {
            "chain_id": CHAIN_IDS[chain],
            "eth_blocks": runlog_bounds.get(chain),
            "totals": {"priority_txs": n, "by_class": dict(by_class),
                       "non_deposit_txs": n_nd,
                       "unique_l1_initiators": len(l1s),
                       "unique_inner_senders": len(inner)},
            "completeness": completeness[chain],
            "protocols": protos,
            "deposit_initiator_contracts": [
                {"address": a, "label": labels.get(a), "tx_count": c}
                for a, c in dep_c.most_common(20)],
            "deposits_via_7702_accounts": {
                "tx_count": len(dep_7702),
                "unique_accounts": len({r["l1_from"] for r in dep_7702}),
                "note": "EIP-7702-delegated EOAs (smart accounts); counted as users, not protocol contracts"},
            "top_initiators": [
                {"address": a,
                 "is_contract": (kinds.get(a) == "contract" if a in kinds
                                 else code_of.get(a, None)),
                 "is_7702_account": kinds.get(a) == "7702" if a in kinds else None,
                 "tx_count": c, "label": labels.get(a)}
                for a, c in top_init.most_common(20)],
            "top_share": {
                "top1": round(top_init.most_common(1)[0][1] / n, 4) if top_init and n else 0,
                "top10": round(sum(c for _, c in top_init.most_common(10)) / n, 4) if n else 0},
            "initiator_eoa_contract_split": {
                "plain_eoa": len([a for a in l1s if not code_of.get(a)]),
                "eip7702_account": len([a for a in l1s if kinds.get(a) == "7702"]),
                "true_contract": len([a for a in l1s if kinds.get(a) == "contract"]),
                "note": "getCode at latest block (approximation; see caveats)"},
            "unattributed": {
                "tx_count": len(una),
                "share_of_non_deposit": round(len(una) / n_nd, 4) if n_nd else 0,
                "top_groups": [{"unaliased_from": k[0], "to": k[1], "selector": k[2],
                                "count": c} for k, c in una_groups.most_common(15)]},
        }

    agg["cross_chain"] = {
        "protocols_multi_chain": [
            {"name": p, "chains": sorted(v["chains"]), "l1_addresses": sorted(v["l1"])}
            for p, v in sorted(proto_chains.items()) if len(v["chains"]) >= 2],
        "initiators_multi_chain_total": len(
            [a for a, v in init_chains.items() if len(v["chains"]) >= 2]),
        "initiators_multi_chain": sorted(
            [{"address": a, "chains": sorted(v["chains"]), "total_txs": v["n"]}
             for a, v in init_chains.items() if len(v["chains"]) >= 2],
            key=lambda x: -x["total_txs"])[:40],
    }
    with open("results/aggregates.json", "w") as f:
        json.dump(agg, f, indent=1)
    print("wrote results/aggregates.json", file=sys.stderr)


if __name__ == "__main__":
    main()
