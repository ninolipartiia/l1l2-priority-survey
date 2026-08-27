#!/usr/bin/env python3
"""
build_outputs.py — Phase 3 + Phase 5: join everything and emit every deliverable.

Reads
  ../../results/enriched/<chain>.jsonl   the census (read-only)
  ../code/<chain>.json                   Phase 1 code verdicts (candidates + deposit benefs)
  ../code-pm/<chain>.json                Phase 1 protocol-message control verdicts
  ../codetime/<chain>.json               Phase 2 code-at-tx-time verdicts
  ../codetime-pm/<chain>.json            Phase 2 for the control set
  ../codetime-eoa-control/<chain>.json   METHOD §3 `eoa` control
  ../seed/proxy-slots.json               ERC1967 impl/beacon/admin slot reads
  ../seed/contract-names.json            explorer-verified contract names
  attribution.json                       Phase 4 verdicts (families + per-address)

Writes ../recipients/, ../recipients-deposits/, ../txs/, ../families.json,
../aggregates-l2.json.

Invariants asserted here rather than assumed (TASK acceptance criteria):
  * the six `to_kind` values are disjoint and exhaustive, and the tx counts behind them
    sum to the chain's candidate_txs (and 24,067 overall);
  * `is_system` is a flag counted WITHIN those buckets, never a seventh bucket;
  * every address the code cache marks `contract` has a code-time entry;
  * a family-attribution prefix that matches zero or >1 families aborts the run.
"""
import argparse, json, os, sys, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "phase6-l2-recipients", "scripts"))
from resolve_l2_code import beneficiary_of

CHAINS = ["era", "abstract", "zkcandy", "zero", "lens", "cronos", "sophon", "openzk"]
CHAIN_IDS = {"era": 324, "abstract": 2741, "sophon": 50104, "lens": 232,
             "cronos": 388, "zero": 543210, "zkcandy": 320, "openzk": 1345}
CANDIDATE_CLASSES = ("direct-transfer", "other")
LEGACY_L2_SHARED_BRIDGE = "0x11f943b2c77b743ab90f4a0ae7d5a4e7fca3e102"   # era-only (METHOD §3)
KINDS = ["eoa", "contract", "contract-later", "delegated-eoa", "unresolvable",
         "code-time-unverified"]


def is_system(addr):
    """METHOD §3: the reserved ZK-stack range, plus era's legacy L2SharedBridge."""
    try:
        n = int(addr, 16)
    except ValueError:
        return False
    return n < 0x20000 or addr.lower() == LEGACY_L2_SHARED_BRIDGE


def load(path, default=None):
    if not os.path.exists(path):
        return {} if default is None else default
    with open(path) as f:
        return json.load(f)


def day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if ts else None


def to_kind_of(code_entry, codetime_entry):
    """Map (resolver verdict, code-time verdict) onto the six disjoint METHOD §3 values.

    The resolver's `contract` is only provisional: §4's gate is what decides between
    `contract`, `contract-later` and `code-time-unverified`. Anything the resolver could not
    answer at all is `unresolvable` — never defaulted to `eoa` (METHOD §2).
    """
    if code_entry is None:
        return "unresolvable"
    kind = code_entry.get("kind")
    if kind == "eoa":
        return "eoa"
    if kind == "delegated-eoa":
        return "delegated-eoa"
    if kind != "contract":
        return "unresolvable"
    if codetime_entry is None:
        return "code-time-unverified"
    return {"contract": "contract", "eoa": "contract-later",
            "delegated-eoa": "delegated-eoa"}.get(codetime_entry.get("code_at_tx"),
                                                  "code-time-unverified")


class Attribution:
    """Family-first attribution with a per-address override (METHOD §5, §7)."""

    def __init__(self, path, code_caches):
        raw = json.load(open(path))
        self.addresses = raw.get("addresses", {})
        self.shared = raw.get("shared", {})
        seen = collections.defaultdict(set)
        for chain, cache in code_caches.items():
            for v in cache.values():
                if v.get("kind") == "contract" and v.get("codehash"):
                    seen[v["codehash"][:8]].add(v["codehash"])
        self.by_hash = {}
        for prefix, rec in raw.get("families_by_prefix", {}).items():
            match = seen.get(prefix, set())
            if len(match) != 1:
                sys.exit(f"FATAL: attribution family prefix {prefix!r} matches {len(match)} "
                         f"bytecode families in the code caches ({sorted(match)}). A prefix that "
                         f"matches none silently attributes nothing; one that matches several "
                         f"attributes the wrong contracts. Fix attribution.json.")
            self.by_hash[match.pop()] = rec

    def for_address(self, chain, addr, codehash):
        rec = dict(self.by_hash.get(codehash) or {})
        over = self.addresses.get(f"{chain}:{addr}")
        if over:
            if over.get("_use"):
                rec.update(self.shared[over["_use"]])
            rec.update({k: v for k, v in over.items() if k != "_use"})
        return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", default="direct-transfer,other")
    ap.add_argument("--recur-min", type=int, default=2)
    a = ap.parse_args()
    classes = tuple(c.strip() for c in a.classes.split(",") if c.strip())

    code = {c: load(f"{OUT}/code/{c}.json") for c in CHAINS}
    code_pm = {c: load(f"{OUT}/code-pm/{c}.json") for c in CHAINS}
    ct = {c: load(f"{OUT}/codetime/{c}.json") for c in CHAINS}
    ct_pm = {c: load(f"{OUT}/codetime-pm/{c}.json") for c in CHAINS}
    ct_eoa = {c: load(f"{OUT}/codetime-eoa-control/{c}.json") for c in CHAINS}
    slots = load(f"{OUT}/seed/proxy-slots.json")
    names = load(f"{OUT}/seed/contract-names.json")
    attrib = Attribution(os.path.join(HERE, "attribution.json"), code)

    for d in ("recipients", "recipients-deposits", "txs"):
        os.makedirs(f"{OUT}/{d}", exist_ok=True)

    agg_chains, families = {}, collections.defaultdict(
        lambda: {"members": [], "chains": set(), "tx_count": 0, "code_len": None,
                 "erc1967_impl": None})
    all_recip_chains, all_benef_chains = collections.defaultdict(set), collections.defaultdict(set)
    recip_tx_total = collections.Counter()
    totals = collections.Counter()
    by_kind_t, txs_by_kind_t, by_actor_t = collections.Counter(), collections.Counter(), {}
    sys_recip = sys_txs = 0
    sys_by_kind = collections.Counter()
    problems = []

    for chain in CHAINS:
        path = f"{ROOT}/results/enriched/{chain}.jsonl"
        rec_stats, benef_stats, l1_from, cand_records = {}, {}, set(), []
        deposit_not_decoded = 0
        for line in open(path):
            r = json.loads(line)
            cls = r.get("class")
            if cls in classes:
                addr = r["to"].lower()
                s = rec_stats.setdefault(addr, {"txs": 0, "txs_value_gt0": 0, "value_total": 0,
                                                "first": None, "last": None,
                                                "selectors": collections.Counter()})
                s["txs"] += 1
                v = int(r.get("value") or 0)
                if v > 0:
                    s["txs_value_gt0"] += 1
                s["value_total"] += v
                ts = r.get("ts") or 0
                s["first"] = ts if s["first"] is None else min(s["first"], ts)
                s["last"] = ts if s["last"] is None else max(s["last"], ts)
                if r.get("selector"):
                    s["selectors"][r["selector"]] += 1
                if r.get("l1_from"):
                    l1_from.add(r["l1_from"].lower())
                cand_records.append(r)
            elif cls == "canonical-deposit":
                b, _why = beneficiary_of(r)
                if b:
                    d = benef_stats.setdefault(b, {"txs": 0, "value_total": 0,
                                                   "first": None, "last": None})
                    d["txs"] += 1
                    d["value_total"] += int(r.get("value") or 0)
                    ts = r.get("ts") or 0
                    d["first"] = ts if d["first"] is None else min(d["first"], ts)
                    d["last"] = ts if d["last"] is None else max(d["last"], ts)
                else:
                    deposit_not_decoded += 1

        for addr in rec_stats:
            all_recip_chains[addr].add(chain)
            recip_tx_total[addr] += rec_stats[addr]["txs"]
        for addr in benef_stats:
            all_benef_chains[addr].add(chain)

        def build_row(addr, stats, source):
            ce, cte = code[chain].get(addr), ct[chain].get(addr)
            kind = to_kind_of(ce, cte)
            att = attrib.for_address(chain, addr, (ce or {}).get("codehash")) \
                if kind in ("contract", "contract-later") else {}
            sysflag = is_system(addr)
            nm = names.get(f"{chain}:{addr}") or {}
            row = {
                "chain": chain, "address": addr, "source": source,
                "txs": stats["txs"], "txs_value_gt0": stats.get("txs_value_gt0", stats["txs"]),
                "value_total": str(stats["value_total"]),
                "first_seen": day(stats["first"]), "last_seen": day(stats["last"]),
                "selectors": dict(stats.get("selectors") or {}),
                "to_kind": kind, "is_system": sysflag,
                "code_len": (ce or {}).get("len"), "codehash": (ce or {}).get("codehash"),
                "family": (ce or {}).get("codehash") if kind in ("contract", "contract-later")
                          else None,
                "erc1967_impl": (slots.get(chain, {}).get(addr) or {}).get("erc1967_impl"),
                "erc1967_beacon": (slots.get(chain, {}).get(addr) or {}).get("erc1967_beacon"),
                "explorer_name": nm.get("name"),
                # METHOD §3: is_system WINS over actor_type — a reserved address is never
                # assigned an Axis-B label and never counts as a protocol interaction.
                "actor_type": None if sysflag else att.get("actor_type"),
                "protocol": None if sysflag else att.get("protocol"),
                "confidence": None if sysflag else att.get("confidence"),
                "evidence": [] if sysflag else list(att.get("evidence") or []),
                "role": None if sysflag else att.get("role"),
                "code_at_tx": (cte or {}).get("code_at_tx"),
                "txs_in_window_dated": (cte or {}).get("txs_in_window"),
                "straddles_deployment": (cte or {}).get("straddles_deployment"),
                "also_on_chains": [],
                "is_own_l1_initiator": addr in l1_from,
            }
            if sysflag and att:
                row["evidence"] = list(att.get("evidence") or [])
            return row

        rows = [build_row(a_, s, "candidate") for a_, s in rec_stats.items()]
        brows = [build_row(a_, s, "deposit-beneficiary") for a_, s in benef_stats.items()]

        by_kind = collections.Counter(r["to_kind"] for r in rows)
        txs_by_kind = collections.Counter()
        for r in rows:
            txs_by_kind[r["to_kind"]] += r["txs"]
        if sum(txs_by_kind.values()) != len(cand_records):
            problems.append(f"{chain}: txs_by_to_kind sums to {sum(txs_by_kind.values())}, "
                            f"expected {len(cand_records)}")

        by_actor = collections.defaultdict(lambda: {"txs": 0, "recipients": 0})
        for r in rows:
            if r["actor_type"]:
                by_actor[r["actor_type"]]["txs"] += r["txs"]
                by_actor[r["actor_type"]]["recipients"] += 1
        for r in rows:
            if r["is_system"]:
                globals_ = None
        n_sys = sum(1 for r in rows if r["is_system"])
        n_sys_txs = sum(r["txs"] for r in rows if r["is_system"])
        sys_recip += n_sys
        sys_txs += n_sys_txs
        for r in rows:
            if r["is_system"]:
                sys_by_kind[r["to_kind"]] += 1

        # An address can appear in BOTH rows and brows (it is a candidate recipient *and* a
        # decoded deposit beneficiary on the same chain — 140 such pairs overall). A family
        # member is a (chain, address), not a (chain, address, role), so merge by address
        # first: appending both roles would inflate member_count and make the AGW family read
        # as 358 members when abstract only has 352 such contracts.
        merged = {}
        for r in rows + brows:
            m = merged.setdefault(r["address"], {"chain": chain, "address": r["address"],
                                                 "txs": 0, "sources": set(), "row": r})
            m["sources"].add(r["source"])
            if r["source"] == "candidate":
                m["txs"] = r["txs"]          # candidate txs only; deposits are a separate set
                m["row"] = r
        for m in merged.values():
            r = m["row"]
            if r["to_kind"] in ("contract", "contract-later") and r["codehash"]:
                f = families[r["codehash"]]
                f["members"].append({"chain": chain, "address": r["address"], "txs": m["txs"],
                                     "is_candidate": "candidate" in m["sources"],
                                     "is_deposit_beneficiary":
                                         "deposit-beneficiary" in m["sources"]})
                f["chains"].add(chain)
                f["tx_count"] += m["txs"]
                f["code_len"] = r["code_len"]
                if r["erc1967_impl"]:
                    f["erc1967_impl"] = r["erc1967_impl"]
                for key in ("actor_type", "protocol", "confidence"):
                    f.setdefault(key, r[key])
                f.setdefault("evidence", r["evidence"])

        counts = sorted(((r["address"], r["txs"]) for r in rows), key=lambda kv: (-kv[1], kv[0]))
        n = collections.Counter()
        for _a, t in counts:
            n["1" if t == 1 else "2-4" if t <= 4 else "5-9" if t <= 9 else "ge10"] += 1
        rowmap = {r["address"]: r for r in rows}

        other_groups = collections.Counter()
        for r in cand_records:
            if r.get("class") == "other":
                other_groups[(r["to"].lower(), r.get("selector") or "")] += 1

        # NOTE: this list is keyed by attributed *name*, and a name can be a smart-wallet
        # family (AGW, Safe, ZKsync SSO) rather than a protocol. Each row therefore carries
        # `actor_type`, so nothing downstream can sum the list into "protocol usage" — that
        # conflation is METHOD §6 pitfall 7 and the whole point of Axis B.
        protocols = collections.defaultdict(
            lambda: {"txs": 0, "recipient_addresses": [], "senders": set(),
                     "first": None, "last": None, "evidence": [], "category": None,
                     "confidence": None, "actor_type": None})
        for r in rows:
            if r["protocol"] and not r["is_system"]:
                p = protocols[r["protocol"]]
                p["actor_type"] = r["actor_type"]
                p["txs"] += r["txs"]
                p["recipient_addresses"].append(r["address"])
                p["category"] = attrib.for_address(chain, r["address"],
                                                   r["codehash"]).get("category")
                p["confidence"] = r["confidence"]
                p["evidence"] = r["evidence"]
                p["first"] = r["first_seen"] if p["first"] is None else min(p["first"],
                                                                           r["first_seen"])
                p["last"] = r["last_seen"] if p["last"] is None else max(p["last"],
                                                                        r["last_seen"])
        for r in cand_records:
            addr = r["to"].lower()
            row = rowmap.get(addr)
            if row and row["protocol"] and not row["is_system"] and r.get("l1_from"):
                protocols[row["protocol"]]["senders"].add(r["l1_from"].lower())

        pm_contracts = [a_ for a_, v in code_pm[chain].items() if v.get("kind") == "contract"]
        pm_recip = set()
        pm_txs = collections.Counter()
        for line in open(path):
            r = json.loads(line)
            if r.get("class") == "protocol-message":
                pm_recip.add(r["to"].lower())
                pm_txs[r["to"].lower()] += 1

        agg_chains[chain] = {
            "chain_id": CHAIN_IDS[chain],
            "candidate_txs": len(cand_records),
            "distinct_recipients": len(rows),
            "by_to_kind": {k: by_kind.get(k, 0) for k in KINDS},
            "txs_by_to_kind": {k: txs_by_kind.get(k, 0) for k in KINDS},
            "by_actor_type": {k: dict(v) for k, v in by_actor.items()},
            "system": {"recipients": n_sys, "txs": n_sys_txs},
            "eoa_to_contract_txs": sum(r["txs"] for r in rows
                                       if r["to_kind"] == "contract" and not r["is_system"]),
            "eoa_to_contract_recipients": sum(1 for r in rows
                                              if r["to_kind"] == "contract" and not r["is_system"]),
            "recurrence": {"1": n["1"], "2-4": n["2-4"], "5-9": n["5-9"], "ge10": n["ge10"],
                           "max_txs_to_one_recipient": counts[0][1] if counts else 0},
            "top_recipients": [
                {"address": a_, "txs": t, "to_kind": rowmap[a_]["to_kind"],
                 "is_system": rowmap[a_]["is_system"], "actor_type": rowmap[a_]["actor_type"],
                 "protocol": rowmap[a_]["protocol"],
                 "is_own_l1_initiator": rowmap[a_]["is_own_l1_initiator"]}
                for a_, t in counts[:20]],
            "protocols": [
                {"name": k, "actor_type": v["actor_type"], "category": v["category"],
                 "confidence": v["confidence"],
                 "recipient_addresses": sorted(v["recipient_addresses"]), "txs": v["txs"],
                 "unique_senders": len(v["senders"]), "first_seen": v["first"],
                 "last_seen": v["last"], "evidence": v["evidence"]}
                for k, v in sorted(protocols.items(), key=lambda kv: -kv[1]["txs"])],
            "other_class_groups": [
                {"to": t, "selector": s or None,
                 "signature": {"0x095ea7b3": "approve(address,uint256)"}.get(s, "unknown"),
                 "count": c_, "has_calldata": bool(s),
                 "to_kind": rowmap[t]["to_kind"], "is_system": rowmap[t]["is_system"]}
                for (t, s), c_ in sorted(other_groups.items(), key=lambda kv: (-kv[1], kv[0]))],
            "deposit_beneficiaries": {
                "distinct": len(brows),
                "deposit_records_not_decoded": deposit_not_decoded,
                "by_to_kind": {k: sum(1 for r in brows if r["to_kind"] == k) for k in KINDS},
                "by_actor_type": {
                    k: sum(1 for r in brows if r["actor_type"] == k)
                    for k in ("smart-wallet", "protocol-contract", "token", "unknown-contract")},
            },
            "protocol_message_control": {
                "txs": sum(pm_txs.values()), "distinct_recipients": len(pm_recip),
                "contract_recipients": len(pm_contracts),
                "eoa_recipients": sum(1 for v in code_pm[chain].values()
                                      if v.get("kind") == "eoa"),
                "txs_to_contract_recipients": sum(
                    n_ for a_, n_ in pm_txs.items()
                    if code_pm[chain].get(a_, {}).get("kind") == "contract"),
                "txs_to_eoa_recipients": sum(
                    n_ for a_, n_ in pm_txs.items()
                    if code_pm[chain].get(a_, {}).get("kind") == "eoa"),
                "code_time_verified_contract": sum(
                    1 for a_ in pm_contracts
                    if ct_pm[chain].get(a_, {}).get("code_at_tx") == "contract"),
            },
            "eoa_control": {
                "sampled": len(ct_eoa[chain]),
                "codeless_at_tx_time": sum(1 for v in ct_eoa[chain].values()
                                           if v.get("code_at_tx") == "eoa"),
                "had_code_at_tx_time": sum(1 for v in ct_eoa[chain].values()
                                           if v.get("code_at_tx") in ("contract",
                                                                      "delegated-eoa")),
                "unavailable": sum(1 for v in ct_eoa[chain].values()
                                   if v.get("code_at_tx") == "unavailable"),
            },
            "address_lookups": len(code[chain]),
            "unresolved": {"recipients": by_kind.get("unresolvable", 0),
                           "txs": txs_by_kind.get("unresolvable", 0),
                           "reason": None if not by_kind.get("unresolvable") else
                                     "endpoint could not answer; see run-manifest-l2.json"},
        }

        for r in rows:
            by_kind_t[r["to_kind"]] += 1
            txs_by_kind_t[r["to_kind"]] += r["txs"]
            if r["actor_type"]:
                d = by_actor_t.setdefault(r["actor_type"], {"txs": 0, "recipients": 0})
                d["txs"] += r["txs"]
                d["recipients"] += 1
        totals["candidate_txs"] += len(cand_records)
        totals["deposit_records_not_decoded"] += deposit_not_decoded
        totals["distinct_recipients_per_chain_sum"] += len(rows)
        totals["deposit_beneficiaries_per_chain_sum"] += len(brows)
        totals["address_lookups_total"] += len(code[chain])

        with open(f"{OUT}/recipients/{chain}.jsonl", "w") as f:
            for r in sorted(rows, key=lambda r: (-r["txs"], r["address"])):
                f.write(json.dumps(r, sort_keys=True) + "\n")
        with open(f"{OUT}/recipients-deposits/{chain}.jsonl", "w") as f:
            for r in sorted(brows, key=lambda r: (-r["txs"], r["address"])):
                f.write(json.dumps(r, sort_keys=True) + "\n")
        with open(f"{OUT}/txs/{chain}.jsonl", "w") as f:
            for r in cand_records:
                row = rowmap[r["to"].lower()]
                f.write(json.dumps({
                    "chain": chain, "tx_id": r["tx_id"], "to": r["to"].lower(),
                    "class": r["class"], "selector": r.get("selector") or None,
                    "value": str(r.get("value") or 0), "ts": r.get("ts"),
                    "to_kind": row["to_kind"], "is_system": row["is_system"],
                    "family": row["family"], "actor_type": row["actor_type"],
                    "protocol": row["protocol"]}, sort_keys=True) + "\n")

        # every `contract` in the cache must have a code-time entry (acceptance criterion)
        for a_, v in code[chain].items():
            if v.get("kind") == "contract" and a_ not in ct[chain]:
                problems.append(f"{chain}: {a_} is `contract` in the code cache but has no "
                                f"codetime entry")
        for a_, v in ct[chain].items():
            if v.get("retryable"):
                problems.append(f"{chain}: codetime {a_} still retryable: {v.get('detail')}")

    # ---- cross-chain and families ----
    multi_recip = sorted(({"address": ad, "chains": sorted(ch), "txs": recip_tx_total[ad]}
                          for ad, ch in all_recip_chains.items() if len(ch) >= 2),
                         key=lambda r: (-r["txs"], r["address"]))
    multi_benef = sorted(({"address": ad, "chains": sorted(ch)}
                          for ad, ch in all_benef_chains.items() if len(ch) >= 2),
                         key=lambda r: r["address"])
    for chain in CHAINS:
        p = f"{OUT}/recipients/{chain}.jsonl"
        rows = [json.loads(x) for x in open(p)]
        for r in rows:
            r["also_on_chains"] = sorted(all_recip_chains[r["address"]] - {chain})
        with open(p, "w") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    fam_out = []
    for h, v in sorted(families.items(), key=lambda kv: -kv[1]["tx_count"]):
        fam_out.append({
            "codehash": h, "codehash_note": "sha256 of the lowercased code hex — a clustering "
                                            "key only, NOT the EVM keccak codehash",
            "code_len": v["code_len"], "chains": sorted(v["chains"]),
            # distinct (chain, address) members; the three counts below overlap deliberately —
            # candidate_members + deposit_only_members == member_count, while
            # deposit_beneficiary_members also counts addresses that are in both sets.
            "member_count": len(v["members"]),
            "candidate_members": sum(1 for m in v["members"] if m["is_candidate"]),
            "deposit_only_members": sum(1 for m in v["members"] if not m["is_candidate"]),
            "deposit_beneficiary_members": sum(1 for m in v["members"]
                                               if m["is_deposit_beneficiary"]),
            "tx_count": v["tx_count"], "erc1967_impl": v.get("erc1967_impl"),
            "actor_type": v.get("actor_type"), "protocol": v.get("protocol"),
            "confidence": v.get("confidence"), "evidence": v.get("evidence") or [],
            "members": sorted((m["address"] for m in v["members"]))})
    json.dump({"families": fam_out}, open(f"{OUT}/families.json", "w"), indent=1)

    fam_multi = [{"codehash": f["codehash"], "chains": f["chains"], "tx_count": f["tx_count"],
                  "protocol": f["protocol"], "actor_type": f["actor_type"]}
                 for f in fam_out if len(f["chains"]) >= 2]

    ct_all = [v for c in CHAINS for v in ct[c].values()]
    later = [v for v in ct_all if v.get("code_at_tx") == "eoa"]
    eoa_ctl = {"sampled": sum(len(ct_eoa[c]) for c in CHAINS),
               "codeless_at_tx_time": sum(1 for c in CHAINS for v in ct_eoa[c].values()
                                          if v.get("code_at_tx") == "eoa"),
               "had_code_at_tx_time": sum(1 for c in CHAINS for v in ct_eoa[c].values()
                                          if v.get("code_at_tx") in ("contract",
                                                                     "delegated-eoa")),
               "chains": sorted(c for c in CHAINS if ct_eoa[c])}

    agg = {
        "run": {"window": {"from": "2025-08-26", "to": "2026-08-26"},
                "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
                "chains": CHAINS, "classes": list(classes), "recur_min": a.recur_min,
                "source_dataset": "results/ (45,711 records, census run 2026-08-25)"},
        "totals": {
            "candidate_txs": totals["candidate_txs"],
            "distinct_recipients_per_chain_sum": totals["distinct_recipients_per_chain_sum"],
            "distinct_recipients_global": len(all_recip_chains),
            "recipients_on_ge2_chains": len(multi_recip),
            "address_lookups_total": totals["address_lookups_total"],
            "deposit_beneficiaries_per_chain_sum": totals["deposit_beneficiaries_per_chain_sum"],
            "deposit_beneficiaries_global": len(all_benef_chains),
            "deposit_beneficiaries_on_ge2_chains": len(multi_benef),
            "distinct_addresses_total_global": len(set(all_recip_chains) | set(all_benef_chains)),
            "deposit_records_not_decoded": totals["deposit_records_not_decoded"],
            # Recurrence thresholds are counted PER CHAIN and summed (METHOD §5) — they are
            # not distinct-address counts across chains.
            "recipients_ge2_txs": sum(v["recurrence"]["2-4"] + v["recurrence"]["5-9"]
                                      + v["recurrence"]["ge10"] for v in agg_chains.values()),
            "recipients_ge5_txs": sum(v["recurrence"]["5-9"] + v["recurrence"]["ge10"]
                                      for v in agg_chains.values()),
            "recipients_ge10_txs": sum(v["recurrence"]["ge10"] for v in agg_chains.values()),
            "recurrence": {k: sum(v["recurrence"][k] for v in agg_chains.values())
                           for k in ("1", "2-4", "5-9", "ge10")},
            "by_to_kind": {k: by_kind_t.get(k, 0) for k in KINDS},
            "txs_by_to_kind": {k: txs_by_kind_t.get(k, 0) for k in KINDS},
            "system": {"recipients": sys_recip, "txs": sys_txs,
                       "by_to_kind": dict(sys_by_kind)},
            "eoa_to_contract_txs": sum(v["eoa_to_contract_txs"] for v in agg_chains.values()),
            "eoa_to_contract_recipients": sum(v["eoa_to_contract_recipients"]
                                              for v in agg_chains.values()),
            "contract_later": {
                "recipients": len(later), "txs": sum(v.get("txs_in_window", 0) for v in later),
                "straddling_recipients": sum(1 for v in later if v.get("straddles_deployment")),
                "straddling_txs": sum(v.get("txs_in_window", 0) for v in later
                                      if v.get("straddles_deployment")),
                "single_tx_recipients": sum(1 for v in later if v.get("txs_in_window") == 1)},
            "eoa_control": eoa_ctl,
            "by_actor_type": {k: by_actor_t.get(k, {"txs": 0, "recipients": 0})
                              for k in ("smart-wallet", "protocol-contract", "token",
                                        "unknown-contract")},
            "reconciliation": "sum(txs_by_to_kind) == candidate_txs; sum(by_to_kind) == "
                              "distinct_recipients_per_chain_sum; is_system is counted WITHIN "
                              "those buckets, not as a seventh one",
        },
        "chains": agg_chains,
        "families": fam_out,
        "cross_chain": {"recipients_multi_chain": multi_recip,
                        "deposit_beneficiaries_multi_chain": multi_benef,
                        "families_multi_chain": fam_multi},
    }

    t = agg["totals"]
    checks = [
        ("sum(txs_by_to_kind) == candidate_txs",
         sum(t["txs_by_to_kind"].values()) == t["candidate_txs"]),
        ("sum(by_to_kind) == distinct_recipients_per_chain_sum",
         sum(t["by_to_kind"].values()) == t["distinct_recipients_per_chain_sum"]),
        ("candidate_txs == 24067", t["candidate_txs"] == 24067),
        ("distinct_recipients_per_chain_sum == 21515",
         t["distinct_recipients_per_chain_sum"] == 21515),
        ("address_lookups_total == 22162", t["address_lookups_total"] == 22162),
        ("deposit_records_not_decoded == 140", t["deposit_records_not_decoded"] == 140),
        ("recipients_on_ge2_chains == 31", t["recipients_on_ge2_chains"] == 31),
        ("deposit_beneficiaries_on_ge2_chains == 11",
         t["deposit_beneficiaries_on_ge2_chains"] == 11),
        ("distinct_addresses_total_global == 22106",
         t["distinct_addresses_total_global"] == 22106),
        ("recipients_ge2/5/10 == 807/98/34",
         (t["recipients_ge2_txs"], t["recipients_ge5_txs"], t["recipients_ge10_txs"])
         == (807, 98, 34)),
    ]
    agg["totals"]["reconciliation_checks"] = {k: bool(v) for k, v in checks}
    json.dump(agg, open(f"{OUT}/aggregates-l2.json", "w"), indent=1)

    print(json.dumps(t["by_to_kind"], indent=1))
    print("txs:", json.dumps(t["txs_by_to_kind"]))
    print("actor:", json.dumps(t["by_actor_type"]))
    print("system:", json.dumps(t["system"]))
    print(f"headline eoa->contract: {t['eoa_to_contract_txs']} txs / "
          f"{t['eoa_to_contract_recipients']} recipients")
    for k, v in checks:
        print(f"  [{'ok' if v else 'FAIL'}] {k}")
    if problems:
        print(f"\n!! {len(problems)} problem(s):")
        for p in problems[:20]:
            print("   ", p)
    if not all(v for _k, v in checks) or problems:
        sys.exit(1)
    print("\nwrote recipients/, recipients-deposits/, txs/, families.json, aggregates-l2.json")


if __name__ == "__main__":
    main()
