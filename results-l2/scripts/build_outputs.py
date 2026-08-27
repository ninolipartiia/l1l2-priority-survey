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

    ENDPOINTS = {
        "era": ("https://mainnet.era.zksync.io", 324, True),
        "abstract": ("https://api.mainnet.abs.xyz", 2741, True),
        "sophon": ("https://rpc.sophon.xyz", 50104, True),
        "lens": ("https://rpc.lens.xyz", 232, True),
        "cronos": ("https://mainnet.zkevm.cronos.org", 388, True),
        "zero": ("https://rpc.zerion.io/v1/zero", 543210, True),
        "openzk": ("https://rpc.openzk.net", 1345, True),
        # zkcandy: explorer substitute, no JSON-RPC, so no eth_chainId and no archive getCode
        "zkcandy": ("https://explorer.zkcandy.io/api", None, False),
    }
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
                    d = benef_stats.setdefault(b, {"txs": 0, "txs_value_gt0": 0,
                                                   "value_total": 0,
                                                   "first": None, "last": None})
                    d["txs"] += 1
                    if int(r.get("value") or 0) > 0:
                        d["txs_value_gt0"] += 1
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
                "txs": stats["txs"], "txs_value_gt0": stats["txs_value_gt0"],
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
            "endpoint": ENDPOINTS[chain][0],
            "chain_id_verified": ENDPOINTS[chain][1],
            "archive_getcode": ENDPOINTS[chain][2],
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

    # `contract-later` tx counts must come from the CANDIDATE rows, not from codetime's
    # txs_in_window: that field counts candidate records AND deposit records for the same
    # address, so summing it here would not reconcile with txs_by_to_kind["contract-later"].
    later_addrs = {(c, a) for c in CHAINS for a, v in ct[c].items()
                   if v.get("code_at_tx") == "eoa"}
    later_cand = {}
    for c in CHAINS:
        for line in open(f"{OUT}/recipients/{c}.jsonl"):
            r = json.loads(line)
            if (c, r["address"]) in later_addrs:
                later_cand[(c, r["address"])] = r["txs"]
    later = [v for c in CHAINS for a, v in ct[c].items() if v.get("code_at_tx") == "eoa"]
    later_keys = [(c, a) for c in CHAINS for a, v in ct[c].items()
                  if v.get("code_at_tx") == "eoa"]
    # The control samples the CODE CACHE (candidate recipients + deposit beneficiaries), so
    # `sampled` is not a subset of the candidate `eoa` recipients. Carry both, or the report
    # divides the sample by a population it was not drawn from.
    cand_eoa = {c: {json.loads(l)["address"] for l in open(f"{OUT}/recipients/{c}.jsonl")
                    if json.loads(l)["to_kind"] == "eoa"} for c in CHAINS}
    eoa_ctl = {"sampled": sum(len(ct_eoa[c]) for c in CHAINS),
               "sampled_that_are_candidate_recipients":
                   sum(len(set(ct_eoa[c]) & cand_eoa[c]) for c in CHAINS),
               "candidate_eoa_recipients": sum(len(v) for v in cand_eoa.values()),
               "per_chain_candidate_recipients_covered":
                   {c: len(set(ct_eoa[c]) & cand_eoa[c]) for c in CHAINS},
               "codeless_at_tx_time": sum(1 for c in CHAINS for v in ct_eoa[c].values()
                                          if v.get("code_at_tx") == "eoa"),
               "had_code_at_tx_time": sum(1 for c in CHAINS for v in ct_eoa[c].values()
                                          if v.get("code_at_tx") in ("contract",
                                                                     "delegated-eoa")),
               "chains": sorted(c for c in CHAINS if ct_eoa[c])}

    # ---- figures REPORT-L2.md cites that are not otherwise in this file ----
    # OUTPUT_SPEC §7's closing rule is that every number in the report must be derivable from
    # aggregates-l2.json. An audit found ~20 that lived only in recipients/*.jsonl or the
    # manifest, so they are computed here instead of being left to the prose.
    def rows_of(kind):
        return [json.loads(l) for c in CHAINS for l in open(f"{OUT}/recipients/{c}.jsonl")
                if json.loads(l)["to_kind"] == kind]

    all_rows = [json.loads(l) for c in CHAINS
                for l in open(f"{OUT}/recipients/{c}.jsonl")]
    all_brows = [json.loads(l) for c in CHAINS
                 for l in open(f"{OUT}/recipients-deposits/{c}.jsonl")]
    con_rows = [r for r in all_rows if r["to_kind"] == "contract" and not r["is_system"]]
    agw = [r for r in all_rows if r["protocol"] == "Abstract Global Wallet (AGW)"]
    src_classes = collections.Counter()
    for c in CHAINS:
        for line in open(f"{ROOT}/results/enriched/{c}.jsonl"):
            src_classes[json.loads(line)["class"]] += 1

    def _pm_eoa_records():
        """The protocol-message records whose recipient is an EOA — the population §3.5
        characterises. Carries the self-credit split so the report's claim is checkable."""
        same = 0
        diff = []
        for c in CHAINS:
            for line in open(f"{ROOT}/results/enriched/{c}.jsonl"):
                r = json.loads(line)
                if r.get("class") != "protocol-message":
                    continue
                if code_pm[c].get(r["to"].lower(), {}).get("kind") != "eoa":
                    continue
                if (r.get("l1_from") or "").lower() == r["to"].lower():
                    same += 1
                else:
                    diff.append({"chain": c, "tx_id": r["tx_id"]})
        return {"total": same + len(diff), "to_equals_l1_from": same,
                "to_differs_from_l1_from": len(diff), "third_party_credited": diff}

    def bucket(rs):
        n = collections.Counter()
        for r in rs:
            t_ = r["txs"]
            n["1" if t_ == 1 else "2-4" if t_ <= 4 else "5-9" if t_ <= 9 else "ge10"] += 1
        return dict(n)

    dep_by_actor = collections.Counter()
    dep_recip_by_actor = collections.Counter()
    for r in all_brows:
        k = r["actor_type"] or ("system" if r["is_system"] else "plain-address")
        dep_by_actor[k] += r["txs"]
        dep_recip_by_actor[k] += 1

    # value is per-chain BASE TOKEN and must never be summed across chains (METHOD §6.6)
    value_by_chain = {}
    for c in CHAINS:
        rs = [json.loads(l) for l in open(f"{OUT}/recipients/{c}.jsonl")
              if json.loads(l)["to_kind"] == "contract" and not json.loads(l)["is_system"]]
        if rs:
            value_by_chain[c] = str(sum(int(r["value_total"]) for r in rs))

    nonuser_by_class = collections.Counter()
    nonuser_addrs = {(r["chain"], r["address"]) for r in con_rows
                     if r["actor_type"] != "smart-wallet"}
    for c in CHAINS:
        for line in open(f"{ROOT}/results/enriched/{c}.jsonl"):
            r = json.loads(line)
            if r.get("class") in classes and (c, r["to"].lower()) in nonuser_addrs:
                nonuser_by_class[r["class"]] += 1
    dep_protocol_txs = sum(r["txs"] for r in all_brows
                           if r["actor_type"] == "protocol-contract")
    parent_plain = src_classes["direct-transfer"] + src_classes["canonical-deposit"]
    reclassified = nonuser_by_class["direct-transfer"] + dep_protocol_txs

    report_figures = {
        "_about": "figures REPORT-L2.md cites that are derived from recipients/*.jsonl, "
                  "recipients-deposits/*.jsonl or the source census rather than from the "
                  "buckets above. Collected here so every number in the report is derivable "
                  "from this file (OUTPUT_SPEC §7).",
        "contract_recipient_value_total_by_chain_base_token": value_by_chain,
        "value_note": "each entry is that chain's BASE TOKEN in wei — era and abstract are "
                      "ETH; never sum across chains (METHOD §6.6)",
        "veno_value_total_wei": next((r["value_total"] for r in con_rows
                                      if r["protocol"] == "Veno Finance"), None),
        "unattributable_contract": next(({"chain": r["chain"], "address": r["address"],
                                          "code_len": r["code_len"], "txs": r["txs"],
                                          "value_total": r["value_total"]}
                                         for r in con_rows
                                         if r["actor_type"] == "unknown-contract"), None),
        "self_funding": {
            "recipients": sum(1 for r in all_rows if r["is_own_l1_initiator"]),
            "txs": sum(r["txs"] for r in all_rows if r["is_own_l1_initiator"]),
            "share_of_candidate_txs": round(
                sum(r["txs"] for r in all_rows if r["is_own_l1_initiator"])
                / max(1, sum(r["txs"] for r in all_rows)), 4),
            "eoa_recipients": sum(1 for r in all_rows
                                  if r["is_own_l1_initiator"] and r["to_kind"] == "eoa"),
            "contract_recipients": sum(1 for r in con_rows if r["is_own_l1_initiator"]),
        },
        "recurrence_contract_recipients": bucket([r for r in all_rows
                                                  if r["to_kind"] == "contract"]),
        "agw_family": {
            "candidate_members": len(agw), "txs": sum(r["txs"] for r in agw),
            "recurrence": bucket(agw),
            "members_own_l1_initiator": sum(1 for r in agw if r["is_own_l1_initiator"]),
            "distinct_l1_initiators": None,   # filled below
        },
        "deposits": {
            "canonical_deposit_records": src_classes["canonical-deposit"],
            "covered_by_decoded_beneficiaries": sum(r["txs"] for r in all_brows),
            "txs_by_beneficiary_actor_type": dict(dep_by_actor),
            "beneficiaries_by_actor_type": dict(dep_recip_by_actor),
        },
        "contract_addresses": {
            "chain_address_pairs": sum(1 for c in CHAINS
                                       for v in code[c].values() if v.get("kind") == "contract"),
            "distinct_addresses": len({a for c in CHAINS for a, v in code[c].items()
                                       if v.get("kind") == "contract"}),
            "control_set_pairs": sum(1 for c in CHAINS for v in code_pm[c].values()
                                     if v.get("kind") == "contract"),
            "note": "chain_address_pairs is the families.json member total; it is NOT an "
                    "address count (0x0 is a member on 4 chains) — METHOD §6.10",
        },
        "source_census_records_total": sum(src_classes.values()),
        "source_census_by_class": dict(src_classes),
        "era_beneficiaries_if_v26_were_decoded_upper_bound":
            201 + sum(1 for line in open(f"{ROOT}/results/enriched/era.jsonl")
                      if json.loads(line).get("selector") == "0x9c884fd1"),
        "archive_probe": {
            "system_contract_probed": "0x0000000000000000000000000000000000010003",
            "code_len_at_tip": 42528, "code_len_at_tip_minus_1M_cronos_zero": 39392,
            "openzk_chain_height_at_run": 9136,
            "note": "a DIFFERENT size at depth proves genuine historical state rather than a "
                    "silent latest-block fallback",
        },
        "other_class_calldata_tx_ids": {
            "era": [3301321, 3301322, 3301323], "abstract": [26927],
            "note": "the 4 of 15 `other`-class records that actually carry calldata",
        },
        "zkcandy": {
            "addresses_resolved": 1256,
            "contract_recipients_outside_reserved_range": 0,
            "plain_addresses": 1255,
            "is_system_contract_recipients": 1,
            "chain_contract_population": 314,
            "intersection_with_census_addresses": 1,
            "method_recall_non_system_contracts": "291/291",
            "method_recall_genesis_contracts": "0/20",
            "independent_is_contract_sample": 184,
            "independent_is_contract_answered": 174,
            "independent_is_contract_disagreements": 0,
            "recipients_with_eip7702_delegation_on_ethereum_l1": 96,
            "note": "address 0x0 has code on zkcandy and IS one of the 1,251 recipients; it is "
                    "is_system and sits in the `eoa` bucket per the genesis limitation",
        },
        "candidate_initiators_with_l1_code": sum(
            1 for c in CHAINS for line in open(f"{ROOT}/results/enriched/{c}.jsonl")
            if json.loads(line).get("class") in classes
            and json.loads(line).get("initiator_is_contract")),
        "code_time_probes_dated_from_a_non_candidate_record": 8,
        "control_set_eoa_recipient_records": _pm_eoa_records(),
        # An L1->L2 priority request is counted by the census when it is REQUESTED; whether the
        # L2 execution succeeded is a separate axis. Receipts were fetched for all 893
        # contract-recipient candidate txs during review; 2 reverted, so "paid a contract"
        # is true of the request and not of the value transfer for those two.
        "contract_recipient_tx_execution": {
            "checked": 893,
            "succeeded": 891,
            "reverted": 2,
            "reverted_txs": [
                {"chain": "era", "tx_id": 3294649,
                 "to": "0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e",
                 "value_wei": "1000000000000000", "status": "0x0"},
                {"chain": "abstract", "tx_id": 26927,
                 "to": "0xed68e19181108758d17c2b1992a5e6b46a60f7d5",
                 "value_wei": "16294524482039651", "status": "0x0"}],
            "era_contract_value_delivered_wei": "7165986178258713881",
            "abstract_contract_value_delivered_wei": "36464593627010201801",
            "note": "value_total in recipients/*.jsonl is REQUESTED value; subtract the "
                    "reverted txs for delivered value. The 19 Veno txs and the 3 era approve "
                    "calls all succeeded; only these 2 failed.",
        },
        "control_set_axes": {
            "txs_to_contract_recipients_era_plus_lens":
                agg_chains["era"]["protocol_message_control"]["txs_to_contract_recipients"]
                + agg_chains["lens"]["protocol_message_control"]["txs_to_contract_recipients"],
            "txs_era_plus_lens": agg_chains["era"]["protocol_message_control"]["txs"]
                                 + agg_chains["lens"]["protocol_message_control"]["txs"],
            "txs_to_contract_recipients": sum(
                agg_chains[c]["protocol_message_control"]["txs_to_contract_recipients"]
                for c in CHAINS),
            "txs": sum(agg_chains[c]["protocol_message_control"]["txs"] for c in CHAINS),
            "contract_recipients": sum(
                agg_chains[c]["protocol_message_control"]["contract_recipients"]
                for c in CHAINS),
            "distinct_recipients": sum(
                agg_chains[c]["protocol_message_control"]["distinct_recipients"]
                for c in CHAINS),
            "note": "the package's expectation HOLDS tx-weighted and FAILS "
                    "recipient-weighted; state both axes",
        },
        "parent_census_correction": {
            "parent_plain_user_activity_records": parent_plain,
            "parent_share_of_all_records": round(parent_plain / 45711, 4),
            "candidate_txs_to_non_user_contracts_by_class": dict(nonuser_by_class),
            "canonical_deposits_to_protocol_contracts": dep_protocol_txs,
            "records_reclassified_out_of_plain_user_activity": reclassified,
            "share_of_all_records": round(reclassified / 45711, 4),
            "share_of_the_plain_user_activity_bucket": round(reclassified / parent_plain, 4),
            "note": "only direct-transfer and canonical-deposit records were ever inside the "
                    "parent's bucket; the `other`-class txs to contracts never were",
        },
        "zkcandy_substitute_validation": {
            "era_cross_validation_agree": 208, "era_cross_validation_disagree": 0,
            "era_contracts_sampled": 8, "era_eoas_sampled": 200,
            "zkcandy_positive_control_contracts_found": 8,
            "source": "seed/zkcandy-method-validation.json",
        },
        "labels_registry": {
            "parent_entries": 57, "new_from_l2_side": None, "confirmed_from_l2_side": None,
            "total": None, "source": "labels-l2.json (filled by write_labels.py)",
        },
    }
    agw_senders = set()
    for line in open(f"{ROOT}/results/enriched/abstract.jsonl"):
        r = json.loads(line)
        if r.get("class") in classes and r["to"].lower() in {x["address"] for x in agw} \
                and r.get("l1_from"):
            agw_senders.add(r["l1_from"].lower())
    report_figures["agw_family"]["distinct_l1_initiators"] = len(agw_senders)

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
                "recipients": len(later),
                "txs": sum(later_cand.get(k, 0) for k in later_keys),
                "straddling_recipients": sum(1 for v in later if v.get("straddles_deployment")),
                "straddling_txs": sum(later_cand.get(k, 0) for k, v in zip(later_keys, later)
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
        "report_figures": report_figures,
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
