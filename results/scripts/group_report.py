#!/usr/bin/env python3
"""Phase 4 input: summarize attributable traffic per chain from enriched JSONL.

Prints, per chain:
  A. protocol-message + other groups by (sender key, to, selector) with counts
     (sender key = unaliased_from for aliased senders, else l1_from EOA)
  B. canonical-deposit L1 initiators that are contracts (deposit_by_contract)
  C. selector frequency at the L2AssetRouter (deposit ABI variants)

Usage: python3 group_report.py <chain> [...] [--min N]
"""
import json, sys
from collections import Counter, defaultdict


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    min_n = 1
    if "--min" in sys.argv:
        min_n = int(sys.argv[sys.argv.index("--min") + 1])
    for chain in args:
        recs = [json.loads(l) for l in open(f"results/enriched/{chain}.jsonl")]
        print(f"\n===== {chain} ({len(recs)} records) =====")
        groups = defaultdict(list)
        for r in recs:
            if r["class"] in ("protocol-message", "other"):
                key = (r["class"], r["unaliased_from"] or (r.get("l1_from") or "?"),
                       r["to"], r["selector"])
                groups[key].append(r)
        print(f"-- A. attributable groups (class, sender, to, selector) n>={min_n}:")
        for key, g in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(g) < min_n:
                continue
            ts = [r["ts"] for r in g if r.get("ts")]
            import datetime
            span = ""
            if ts:
                f = datetime.datetime.utcfromtimestamp(min(ts)).strftime("%Y-%m-%d")
                t = datetime.datetime.utcfromtimestamp(max(ts)).strftime("%Y-%m-%d")
                span = f" [{f}..{t}]"
            ex = g[0]
            print(f"  {len(g):6d}  {key[0][:8]:8s} from={key[1]} to={key[2]} sel={key[3] or '-'}"
                  f"{span} ex_l2={ex['canonical_hash'][:16]} ex_l1tx={ (ex.get('l1_tx') or '-')[:16] }"
                  f" data_len={ex['data_len']} val={ex['value']}")
        dep = [r for r in recs if r["class"] == "canonical-deposit" and r.get("deposit_by_contract")]
        c = Counter(r["l1_from"] for r in dep)
        print(f"-- B. contract deposit-initiators ({len(dep)} txs, {len(c)} contracts):")
        for a, n in c.most_common(25):
            print(f"  {n:6d}  {a}")
        depsel = Counter(r["selector"] for r in recs if r["class"] == "canonical-deposit")
        print(f"-- C. deposit selectors: {dict(depsel)}")
        othersel = Counter((r["to"], r["selector"]) for r in recs
                           if r["class"] == "canonical-deposit" and
                           r["to"] != "0x0000000000000000000000000000000000010003")
        if othersel:
            print(f"   deposit targets besides 0x…10003: {dict(othersel)}")


if __name__ == "__main__":
    main()
