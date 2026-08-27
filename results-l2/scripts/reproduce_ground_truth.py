#!/usr/bin/env python3
"""
reproduce_ground_truth.py — Phase 0 gate.

Recomputes every number in phase6-l2-recipients/seed-data/ground-truth.json straight from
../results/enriched/*.jsonl and diffs the two. TASK Phase 0: "If any count differs, stop and
report — the input dataset is not what this plan assumes."

Counting rules are taken from ground-truth.json:counting_rules and METHOD §6.10:
  * distinct_recipients is PER CHAIN; the per-chain values sum to
    distinct_recipients_per_chain_sum (21,515), which is NOT a distinct-address count.
  * address_lookups is the per-chain UNION of candidate recipients and decoded deposit
    beneficiaries (what resolve_l2_code.py actually resolves), so it is smaller than the
    sum of the two columns wherever they overlap on the same chain.
  * top10_recipients sorts by txs DESC then address ASC — the cut falls inside a tie on
    several chains, so the tiebreak is part of the definition.

Usage: python3 reproduce_ground_truth.py [--truth <path>] [--enriched <dir>]
Exit status 0 = every number reproduced; 1 = at least one discrepancy (printed).
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "phase6-l2-recipients", "scripts"))
from resolve_l2_code import beneficiary_of          # one decoder, shared with the resolver

CANDIDATE_CLASSES = {"direct-transfer", "other"}
CHAINS = ["abstract", "cronos", "era", "lens", "openzk", "sophon", "zero", "zkcandy"]


def scan(path):
    """One pass over a chain's enriched file -> everything ground-truth.json asserts."""
    st = {
        "candidate_txs": 0, "candidate_txs_value_gt0": 0,
        "recipients": {},                 # addr -> tx count (candidates only)
        "protocol_message_recipients": set(),
        "deposit_beneficiaries": set(),
        "deposit_records_not_decoded": 0,
        "candidate_selectors": {},
        "l1_from": set(),
    }
    for line in open(path):
        r = json.loads(line)
        cls = r.get("class")
        if cls in CANDIDATE_CLASSES:
            st["candidate_txs"] += 1
            if int(r.get("value") or 0) > 0:
                st["candidate_txs_value_gt0"] += 1
            to = r["to"].lower()
            st["recipients"][to] = st["recipients"].get(to, 0) + 1
            sel = r.get("selector") or ""
            st["candidate_selectors"][sel] = st["candidate_selectors"].get(sel, 0) + 1
            if r.get("l1_from"):
                st["l1_from"].add(r["l1_from"].lower())
        elif cls == "protocol-message":
            st["protocol_message_recipients"].add(r["to"].lower())
        elif cls == "canonical-deposit":
            addr, _why = beneficiary_of(r)
            if addr:
                st["deposit_beneficiaries"].add(addr)
            else:
                st["deposit_records_not_decoded"] += 1
    return st


def per_chain_view(st):
    rec = st["recipients"]
    counts = sorted(rec.items(), key=lambda kv: (-kv[1], kv[0]))   # txs DESC, address ASC
    return {
        "candidate_txs": st["candidate_txs"],
        "candidate_txs_value_gt0": st["candidate_txs_value_gt0"],
        "distinct_recipients": len(rec),
        "recipients_ge2_txs": sum(1 for n in rec.values() if n >= 2),
        "recipients_ge5_txs": sum(1 for n in rec.values() if n >= 5),
        "recipients_ge10_txs": sum(1 for n in rec.values() if n >= 10),
        "max_txs_to_one_recipient": max(rec.values()) if rec else 0,
        "distinct_protocol_message_recipients": len(st["protocol_message_recipients"]),
        "distinct_decoded_deposit_beneficiaries": len(st["deposit_beneficiaries"]),
        "deposit_records_not_decoded": st["deposit_records_not_decoded"],
        "recipients_that_are_also_deposit_beneficiaries":
            len(set(rec) & st["deposit_beneficiaries"]),
        "address_lookups": len(set(rec) | st["deposit_beneficiaries"]),
        "candidate_selectors": st["candidate_selectors"],
        "top10_recipients": [{"address": a, "txs": n} for a, n in counts[:10]],
    }


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", default=os.path.join(
        here, "..", "..", "phase6-l2-recipients", "seed-data", "ground-truth.json"))
    ap.add_argument("--enriched", default=os.path.join(here, "..", "..", "results", "enriched"))
    ap.add_argument("--dump", help="write the recomputed view to this JSON path")
    a = ap.parse_args()

    truth = json.load(open(a.truth))
    states = {}
    for chain in CHAINS:
        path = os.path.join(a.enriched, f"{chain}.jsonl")
        if not os.path.exists(path):
            sys.exit(f"FATAL: {path} missing — cannot reproduce ground truth.")
        states[chain] = scan(path)

    got = {"per_chain": {c: per_chain_view(states[c]) for c in CHAINS}}

    all_rec, all_ben = {}, {}                 # address -> set(chains), globally
    for c in CHAINS:
        for addr in states[c]["recipients"]:
            all_rec.setdefault(addr, set()).add(c)
        for addr in states[c]["deposit_beneficiaries"]:
            all_ben.setdefault(addr, set()).add(c)
    tx_by_addr = {}
    for c in CHAINS:
        for addr, n in states[c]["recipients"].items():
            tx_by_addr[addr] = tx_by_addr.get(addr, 0) + n

    got["totals"] = {
        "candidate_txs": sum(states[c]["candidate_txs"] for c in CHAINS),
        "candidate_txs_value_gt0": sum(states[c]["candidate_txs_value_gt0"] for c in CHAINS),
        "distinct_recipients_per_chain_sum": sum(len(states[c]["recipients"]) for c in CHAINS),
        "distinct_recipients_global": len(all_rec),
        "recipients_on_ge2_chains": sum(1 for v in all_rec.values() if len(v) >= 2),
        # Per METHOD §5 these thresholds are counted PER CHAIN and summed, never across chains.
        "recipients_ge2_txs": sum(got["per_chain"][c]["recipients_ge2_txs"] for c in CHAINS),
        "recipients_ge5_txs": sum(got["per_chain"][c]["recipients_ge5_txs"] for c in CHAINS),
        "recipients_ge10_txs": sum(got["per_chain"][c]["recipients_ge10_txs"] for c in CHAINS),
        "distinct_decoded_deposit_beneficiaries_per_chain_sum":
            sum(len(states[c]["deposit_beneficiaries"]) for c in CHAINS),
        "distinct_decoded_deposit_beneficiaries_global": len(all_ben),
        "deposit_beneficiaries_on_ge2_chains": sum(1 for v in all_ben.values() if len(v) >= 2),
        "address_lookups_total": sum(got["per_chain"][c]["address_lookups"] for c in CHAINS),
        "distinct_addresses_total_global": len(set(all_rec) | set(all_ben)),
        "recipients_that_are_also_deposit_beneficiaries": len(set(all_rec) & set(all_ben)),
        "recipients_that_are_also_deposit_beneficiaries_same_chain":
            sum(got["per_chain"][c]["recipients_that_are_also_deposit_beneficiaries"]
                for c in CHAINS),
        "deposit_records_not_decoded":
            sum(states[c]["deposit_records_not_decoded"] for c in CHAINS),
    }

    diffs = []

    def cmp(where, key, want, have):
        if want != have:
            diffs.append(f"{where}.{key}: ground-truth={want!r} recomputed={have!r}")

    for key, want in truth["totals"].items():
        cmp("totals", key, want, got["totals"].get(key, "<not computed>"))
    for chain, want_chain in truth["per_chain"].items():
        have_chain = got["per_chain"].get(chain, {})
        for key, want in want_chain.items():
            cmp(f"per_chain.{chain}", key, want, have_chain.get(key, "<not computed>"))

    print(json.dumps(got["totals"], indent=1))
    print()
    for c in CHAINS:
        v = got["per_chain"][c]
        print(f"{c:9s} txs={v['candidate_txs']:6d} recips={v['distinct_recipients']:6d} "
              f"ge2={v['recipients_ge2_txs']:4d} ge5={v['recipients_ge5_txs']:3d} "
              f"ge10={v['recipients_ge10_txs']:3d} max={v['max_txs_to_one_recipient']:4d} "
              f"benef={v['distinct_decoded_deposit_beneficiaries']:4d} "
              f"lookups={v['address_lookups']:6d} pm_recips={v['distinct_protocol_message_recipients']:3d}")

    if a.dump:
        os.makedirs(os.path.dirname(os.path.abspath(a.dump)) or ".", exist_ok=True)
        payload = dict(got)
        payload["multi_chain_recipients"] = sorted(
            ({"address": ad, "chains": sorted(ch), "txs": tx_by_addr[ad]}
             for ad, ch in all_rec.items() if len(ch) >= 2),
            key=lambda r: (-r["txs"], r["address"]))
        payload["multi_chain_deposit_beneficiaries"] = sorted(
            ({"address": ad, "chains": sorted(ch)} for ad, ch in all_ben.items() if len(ch) >= 2),
            key=lambda r: r["address"])
        with open(a.dump, "w") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
        print(f"\nwrote {a.dump}")

    print()
    if diffs:
        print(f"!! {len(diffs)} DISCREPANC{'Y' if len(diffs) == 1 else 'IES'} vs ground-truth.json:")
        for d in diffs:
            print(f"   {d}")
        sys.exit(1)
    print("ground-truth.json reproduced EXACTLY (all totals, per-chain values and top-10 lists).")


if __name__ == "__main__":
    main()
