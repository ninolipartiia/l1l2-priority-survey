#!/usr/bin/env python3
"""write_labels.py — emit ../labels-l2.json: the parent registry EXTENDED, never overwritten.

OUTPUT_SPEC §7.10 asks for a merged address->label registry that extends
results/scripts/labels.json. That file belongs to the parent census and TASK forbids touching
results/, so the merge is written here instead and records, per entry, whether it is
`inherited` (already in the parent registry, unchanged), `confirmed` (in the parent registry
and independently re-verified from the L2 recipient side by this phase), or `new`.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

parent = json.load(open(f"{ROOT}/results/scripts/labels.json"))
names = json.load(open(f"{OUT}/seed/contract-names.json"))
attrib = json.load(open(f"{HERE}/attribution.json"))
CHAINS = ["era", "abstract", "zkcandy", "zero", "lens", "cronos", "sophon", "openzk"]

merged = {}
for addr, label in parent.items():
    merged[addr] = {"label": label, "origin": "inherited from results/scripts/labels.json",
                    "chains": [], "source": "parent census (sender side)"}

seen = {}
for kind in ("recipients", "recipients-deposits"):
    for chain in CHAINS:
        p = f"{OUT}/{kind}/{chain}.jsonl"
        if not os.path.exists(p):
            continue
        for line in open(p):
            r = json.loads(line)
            if r["to_kind"] not in ("contract", "contract-later"):
                continue
            key = r["address"]
            e = seen.setdefault(key, {"chains": set(), "roles": set(), "protocol": r["protocol"],
                                      "actor_type": r["actor_type"], "role": r.get("role"),
                                      "confidence": r["confidence"], "evidence": r["evidence"],
                                      "explorer_name": r.get("explorer_name"),
                                      "is_system": r["is_system"], "txs": 0})
            e["chains"].add(chain)
            e["roles"].add("candidate-recipient" if kind == "recipients"
                           else "deposit-beneficiary")
            if kind == "recipients":
                e["txs"] += r["txs"]

# the control set's contract recipients too — they are attributed here even though they are
# not part of the headline (TASK: resolve protocol-message recipients as a control)
for chain in CHAINS:
    p = f"{OUT}/code-pm/{chain}.json"
    if not os.path.exists(p):
        continue
    for addr, v in json.load(open(p)).items():
        if v.get("kind") != "contract":
            continue
        att = attrib["addresses"].get(f"{chain}:{addr}", {})
        if att.get("_use"):
            att = {**attrib["shared"][att["_use"]], **att}
        e = seen.setdefault(addr, {"chains": set(), "roles": set(),
                                   "protocol": att.get("protocol"),
                                   "actor_type": att.get("actor_type"), "role": att.get("role"),
                                   "confidence": att.get("confidence"),
                                   "evidence": att.get("evidence") or [],
                                   "explorer_name": (names.get(f"{chain}:{addr}") or {}).get("name"),
                                   "is_system": False, "txs": 0})
        e["chains"].add(chain)
        e["roles"].add("protocol-message-recipient")

new = confirmed = 0
for addr, e in seen.items():
    label = e["role"] or e["protocol"] or e["explorer_name"] or "unidentified contract"
    entry = {"label": label, "protocol": e["protocol"], "actor_type": e["actor_type"],
             "confidence": e["confidence"], "explorer_name": e["explorer_name"],
             "chains": sorted(e["chains"]), "roles": sorted(e["roles"]),
             "candidate_txs": e["txs"], "is_system": e["is_system"],
             "evidence": e["evidence"], "source": "phase 6 (L2 recipient side)"}
    if addr in parent:
        entry["origin"] = "confirmed — in the parent registry and re-verified here from the L2 side"
        # Keep the PARENT's label as the primary text: it carries protocol attribution that a
        # bare explorer contract name drops ("Across Lens_SpokePool" vs "Lens_SpokePool").
        # Re-verification must not silently downgrade the registry.
        entry["l2_side_label"] = entry["label"]
        entry["label"] = parent[addr]
        confirmed += 1
    else:
        entry["origin"] = "new — found only from the L2 recipient side"
        new += 1
    merged[addr] = entry

json.dump({"_about": "address -> label. Extends results/scripts/labels.json (57 entries), which "
                     "is NOT modified. `origin` says whether an entry is inherited, confirmed or "
                     "new. Labels marked confidence 'medium'/'low' or actor_type "
                     "'unknown-contract' are explicitly not fully verified.",
           "parent_entries": len(parent), "confirmed_from_l2_side": confirmed,
           "new_from_l2_side": new, "total": len(merged),
           "labels": dict(sorted(merged.items()))},
          open(f"{OUT}/labels-l2.json", "w"), indent=1)
# Feed the counts back into aggregates-l2.json so the report's registry line is derivable
# from that file, per OUTPUT_SPEC §7's closing rule.
aggp = f"{OUT}/aggregates-l2.json"
if os.path.exists(aggp):
    agg = json.load(open(aggp))
    agg.setdefault("report_figures", {})["labels_registry"] = {
        "parent_entries": len(parent), "new_from_l2_side": new,
        "confirmed_from_l2_side": confirmed, "total": len(merged),
        "note": "total = parent_entries + new_from_l2_side; the confirmed are a SUBSET of the "
                "parent entries, not a third addend",
        "source": "labels-l2.json"}
    json.dump(agg, open(aggp, "w"), indent=1)

print(f"wrote {OUT}/labels-l2.json: {len(parent)} parent + {new} new + {confirmed} confirmed "
      f"= {len(merged)} entries")
for addr, e in sorted(merged.items()):
    if isinstance(e, dict) and e.get("origin", "").startswith("new"):
        print(f"  NEW {addr} {e['chains']} {e['label'][:60]} ({e['actor_type']})")
