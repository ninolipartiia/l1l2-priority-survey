#!/usr/bin/env python3
"""check_acceptance.py — mechanically re-check every TASK.md acceptance criterion.

Prints one line per criterion and exits non-zero if any fails, so "done" is a verified
statement rather than a claim.
"""
import json, os, subprocess, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
CHAINS = ["era", "abstract", "zkcandy", "zero", "lens", "cronos", "sophon", "openzk"]
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def load(p):
    return json.load(open(p)) if os.path.exists(p) else {}


agg = load(f"{OUT}/aggregates-l2.json")
t = agg["totals"]
rows = [json.loads(l) for c in CHAINS for l in open(f"{OUT}/recipients/{c}.jsonl")]
brows = [json.loads(l) for c in CHAINS for l in open(f"{OUT}/recipients-deposits/{c}.jsonl")]
fams = json.load(open(f"{OUT}/families.json"))["families"]

# 1 — ground truth reproduced
p = subprocess.run([sys.executable, os.path.join(HERE, "reproduce_ground_truth.py")],
                   capture_output=True, text=True)
check("ground-truth.json reproduced exactly", p.returncode == 0,
      p.stdout.strip().splitlines()[-1] if p.stdout else p.stderr[:120])

LEGACY_L2_SHARED_BRIDGE = "0x11f943b2c77b743ab90f4a0ae7d5a4e7fca3e102"


def is_system(addr):
    """Must match build_outputs.is_system EXACTLY (METHOD §3): the reserved range PLUS era's
    legacy L2SharedBridge. An audit found this re-implementation had dropped the second
    clause, so the checker was enforcing a weaker rule than the pipeline applied."""
    try:
        return int(addr, 16) < 0x20000 or addr.lower() == LEGACY_L2_SHARED_BRIDGE
    except ValueError:
        return False


sys.path.insert(0, os.path.join(ROOT, "phase6-l2-recipients", "scripts"))
from resolve_l2_code import beneficiary_of

# Re-derive the candidate and beneficiary sets from the SOURCE dataset. Everything below
# compares outputs against THIS, never against another field of the same output file.
src_recip, src_benef, src_txs = {}, {}, collections.Counter()
for c in CHAINS:
    rec, ben = collections.Counter(), set()
    for line in open(f"{ROOT}/results/enriched/{c}.jsonl"):
        r = json.loads(line)
        if r.get("class") in ("direct-transfer", "other"):
            rec[r["to"].lower()] += 1
            src_txs[c] += 1
        elif r.get("class") == "canonical-deposit":
            b, _ = beneficiary_of(r)
            if b:
                ben.add(b)
    src_recip[c], src_benef[c] = rec, ben

# 2 — every lookup has a verdict, none defaulted. Compare KEY SETS, not just sizes: 22,162
# entries for the wrong addresses would satisfy a size check.
lookups = sum(len(load(f"{OUT}/code/{c}.json")) for c in CHAINS)
missing_keys = []
for c in CHAINS:
    want = set(src_recip[c]) | src_benef[c]
    have = set(load(f"{OUT}/code/{c}.json"))
    missing_keys += [f"{c}:{a}" for a in want - have] + [f"{c}:+{a}" for a in have - want]
unresolved_files = [f for c in CHAINS
                    for f in [f"{OUT}/code/{c}.json.unresolved.json"] if os.path.exists(f)]
check("all 22,162 (chain,address) lookups have a code verdict (key sets compared, not sizes)",
      lookups == 22162 and not missing_keys and t["by_to_kind"]["unresolvable"] == 0,
      f"{lookups} cache entries, {len(missing_keys)} key mismatches vs the source dataset, "
      f"{t['by_to_kind']['unresolvable']} unresolvable, "
      f"{len(unresolved_files)} unresolved-list file(s)")

# 3 — reconciliation, recomputed from recipients/*.jsonl and the SOURCE dataset. Every
#     recipient must carry exactly one of the six values and its txs must match the census.
KINDS = ["eoa", "contract", "contract-later", "delegated-eoa", "unresolvable",
         "code-time-unverified"]
own_kind, own_txs, bad_kind, bad_txs = collections.Counter(), collections.Counter(), [], []
for c in CHAINS:
    seen = set()
    for line in open(f"{OUT}/recipients/{c}.jsonl"):
        r = json.loads(line)
        if r["to_kind"] not in KINDS or r["address"] in seen:
            bad_kind.append(f"{c}:{r['address']}")
        seen.add(r["address"])
        own_kind[r["to_kind"]] += 1
        own_txs[r["to_kind"]] += r["txs"]
        if src_recip[c].get(r["address"]) != r["txs"]:
            bad_txs.append(f"{c}:{r['address']}")
    if seen != set(src_recip[c]):
        bad_kind.append(f"{c}: recipient set differs from the census")
check("six to_kind buckets: exactly one per recipient, recomputed from recipients/*.jsonl, "
      "summing to 24,067 txs / 21,515 pairs",
      sum(own_txs.values()) == 24067 and sum(own_kind.values()) == 21515
      and not bad_kind and not bad_txs
      and own_kind == collections.Counter({k: v for k, v in t["by_to_kind"].items() if v})
      and all(agg["chains"][c]["candidate_txs"] == src_txs[c] for c in CHAINS),
      f"recomputed {dict(own_kind)}; {len(bad_kind)} bad kinds, {len(bad_txs)} tx mismatches")
sys_rows = [json.loads(l) for c in CHAINS for l in open(f"{OUT}/recipients/{c}.jsonl")
            if is_system(json.loads(l)["address"])]
check("is_system counted WITHIN the buckets, not as a seventh",
      len(sys_rows) == t["system"]["recipients"]
      and sum(r["txs"] for r in sys_rows) == t["system"]["txs"]
      # the load-bearing property: system recipients are INSIDE the 21,515, not carved out
      and sum(own_kind.values()) == 21515
      and all(r["actor_type"] is None for r in sys_rows)
      and all(is_system(r["address"]) == r["is_system"]
              for c in CHAINS for r in map(json.loads, open(f"{OUT}/recipients/{c}.jsonl"))),
      f"{len(sys_rows)} system recipients, all inside the 21,515, none with an actor_type")

# 4 — code-time coverage, block-1 dating, no unexplained retryable
missing, badblock, retry = [], [], []
for c in CHAINS:
    for sub, ctd in (("code", "codetime"), ("code-pm", "codetime-pm")):
        code, ct = load(f"{OUT}/{sub}/{c}.json"), load(f"{OUT}/{ctd}/{c}.json")
        for a_, v in code.items():
            if v.get("kind") == "contract" and a_ not in ct:
                missing.append(f"{c}:{a_}")
        for a_, v in ct.items():
            if v.get("retryable"):
                retry.append(f"{c}:{a_}")
            if v.get("l2_block") and v.get("probe_block") \
                    and int(v["probe_block"], 16) != int(v["l2_block"], 16) - 1:
                badblock.append(f"{c}:{a_}")
check("every `contract` (incl. deposit-only and control-set) has a code-time verdict",
      not missing, f"{len(missing)} missing")
check("code-time dated at blockNumber-1, never the tx's own block", not badblock,
      f"{len(badblock)} wrong")
check("no `retryable: true` left unexplained", not retry, f"{len(retry)} retryable")
# Test the NAMED property: no contract-later tx may be inside eoa_to_contract_txs. Recompute
# the headline from the rows so this would fail if contract-later were folded in.
head_txs = sum(r["txs"] for c in CHAINS for r in map(json.loads, open(f"{OUT}/recipients/{c}.jsonl"))
               if r["to_kind"] == "contract" and not r["is_system"])
later_txs = sum(r["txs"] for c in CHAINS for r in map(json.loads, open(f"{OUT}/recipients/{c}.jsonl"))
                if r["to_kind"] == "contract-later")
check("contract-later excluded from the headline but reported",
      head_txs == t["eoa_to_contract_txs"]
      and later_txs == t["contract_later"]["txs"]
      and t["by_to_kind"]["contract-later"] == t["contract_later"]["recipients"],
      f"headline {head_txs} recomputed from rows excludes {later_txs} contract-later txs")

# 5 — the dating error is sized, and the eoa control ran and is reported
check("per-recipient dating error SIZED (straddling population reported)",
      "straddling_recipients" in t["contract_later"] and "straddling_txs" in t["contract_later"],
      f"{t['contract_later']['straddling_recipients']} recipients / "
      f"{t['contract_later']['straddling_txs']} txs straddle a deployment")
check("`--kinds eoa` control run on >=1 archive chain and reported (incl. a null result)",
      t["eoa_control"]["sampled"] > 0 and len(t["eoa_control"]["chains"]) >= 1
      # the sample is drawn from the code cache, so it is NOT a subset of the candidate `eoa`
      # recipients; the aggregate must carry that honest denominator explicitly
      and "sampled_that_are_candidate_recipients" in t["eoa_control"],
      f"{t['eoa_control']['sampled']} addresses sampled on "
      f"{len(t['eoa_control']['chains'])} chains, of which "
      f"{t['eoa_control']['sampled_that_are_candidate_recipients']} are candidate `eoa` "
      f"recipients ({100 * t['eoa_control']['sampled_that_are_candidate_recipients'] / t['by_to_kind']['eoa']:.1f}% "
      f"of {t['by_to_kind']['eoa']}); {t['eoa_control']['had_code_at_tx_time']} contradictions")

# 6 — mandatory attribution at >=5 txs, for recipients and for families
def attributed(r):
    return bool(r.get("actor_type")) and (
        r.get("protocol") or r["actor_type"] == "unknown-contract")


unattr_r = [f"{r['chain']}:{r['address']}" for r in rows
            if r["to_kind"] in ("contract", "contract-later") and r["txs"] >= 5
            and not r["is_system"] and not attributed(r)]
unattr_f = [f["codehash"][:12] for f in fams
            if f["tx_count"] >= 5 and f["actor_type"] is None
            and not all(int(m, 16) < 0x20000 for m in f["members"])]
check("every contract recipient with >=5 txs has actor_type + protocol or an explicit "
      "'unattributable'", not unattr_r, f"{len(unattr_r)} missing")
check("every family with >=5 txs has actor_type + protocol or an explicit 'unattributable'",
      not unattr_f, f"{len(unattr_f)} missing")
allc = [r for r in rows + brows if r["to_kind"] in ("contract", "contract-later")
        and not r["is_system"]]
check("in fact EVERY contract recipient (any tx count) carries an actor_type",
      all(attributed(r) for r in allc), f"{sum(1 for r in allc if not attributed(r))} without")
check("every `protocol` set carries at least one piece of evidence",
      all(r["evidence"] for r in rows + brows if r.get("protocol")))

# 7 — smart wallets separated from protocols
check("smart wallets reported separately from protocol contracts",
      t["by_actor_type"]["smart-wallet"]["txs"] > 0
      and t["by_actor_type"]["protocol-contract"]["txs"]
      != t["by_actor_type"]["smart-wallet"]["txs"]
      and sum(v["txs"] for v in t["by_actor_type"].values()) == t["eoa_to_contract_txs"],
      f"smart-wallet {t['by_actor_type']['smart-wallet']['txs']} vs protocol-contract "
      f"{t['by_actor_type']['protocol-contract']['txs']} txs; the four actor types sum to the "
      f"headline {t['eoa_to_contract_txs']}")

# 8 — zkcandy quantified and disclosed
zk = agg["chains"]["zkcandy"]
man = load(f"{OUT}/run-manifest-l2.json")
check("zkcandy quantified and disclosed, not silently dropped",
      zk["address_lookups"] == 1256 and zk["candidate_txs"] == 1396
      and "zkcandy_substitution" in man
      and os.path.exists(f"{OUT}/seed/zkcandy-method-validation.json"),
      f"{zk['address_lookups']} lookups resolved, {zk['unresolved']['recipients']} unresolved; "
      f"substitution + validation recorded")

# 9 — results/ untouched
g = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "results/"],
                   capture_output=True, text=True)
check("../results/ byte-identical to its committed state", not g.stdout.strip(),
      g.stdout.strip()[:120] or "clean")

# 10 — deliverables present and self-consistent
need = ["aggregates-l2.json", "REPORT-L2.md", "run-manifest-l2.json", "families.json",
        "labels-l2.json"] + \
       [f"{d}/{c}.json{'l' if d in ('recipients', 'txs', 'recipients-deposits') else ''}"
        for d in ("code", "recipients", "txs", "recipients-deposits") for c in CHAINS] + \
       [f"codetime/{c}.json" for c in CHAINS
        # lens and cronos have no contract recipients at all, so there is nothing to date and
        # check_code_time.py writes no file. Recorded here rather than silently exempted.
        if any(v.get("kind") == "contract" for v in load(f"{OUT}/code/{c}.json").values())]
absent = [f for f in need if not os.path.exists(f"{OUT}/{f}")]
check("all OUTPUT_SPEC deliverables present", not absent, f"missing {absent}")
# Do not simply read totals.reconciliation_checks — build_outputs.py wrote that dict, so
# trusting it validates the output against itself. Recompute the same assertions here.
indep = {
    "candidate_txs == 24067": sum(own_txs.values()) == 24067,
    "pairs == 21515": sum(own_kind.values()) == 21515,
    "lookups == 22162": lookups == 22162,
    "global distinct recipients == 21480":
        len({r["address"] for c in CHAINS
             for r in map(json.loads, open(f"{OUT}/recipients/{c}.jsonl"))}) == 21480,
    "actor types sum to the headline":
        sum(v["txs"] for v in t["by_actor_type"].values()) == head_txs,
}
check("reconciliation assertions RECOMPUTED here (not read from the pipeline's own flag)",
      all(indep.values()) and all(t.get("reconciliation_checks", {}).values()),
      str({k: v for k, v in indep.items() if not v} or "all ok"))
lab = load(f"{OUT}/labels-l2.json")
parent = load(f"{ROOT}/results/scripts/labels.json")
absent_parent = [a for a in parent if a not in lab.get("labels", {})]
check("labels-l2.json extends rather than overwrites the parent registry",
      len(parent) == 57 and not absent_parent
      and lab.get("total") == len(lab.get("labels", {})),
      f"all {len(parent)} parent addresses present in the merged registry of "
      f"{len(lab.get('labels', {}))}")

# 10b — the pipeline is build_outputs.py -> write_labels.py -> write_manifest.py, and only the
# second writes report_figures.labels_registry. Re-running build_outputs.py ALONE silently drops
# that block, degrading aggregates-l2.json with nothing to catch it: criterion 11 below is loose
# enough (it accepts any pairwise ratio) that the registry numbers still "derive". So assert the
# block is present AND agrees with labels-l2.json, which makes a partial rebuild fail loudly.
reg = agg.get("report_figures", {}).get("labels_registry") or {}
reg_ok = (reg.get("total") == lab.get("total")
          and reg.get("parent_entries") == lab.get("parent_entries")
          and reg.get("new_from_l2_side") == lab.get("new_from_l2_side")
          and reg.get("confirmed_from_l2_side") == lab.get("confirmed_from_l2_side"))
check("aggregates carries labels_registry, in sync with labels-l2.json (partial-rebuild guard)",
      bool(reg) and reg_ok,
      f"labels_registry present, total {reg.get('total')} == labels-l2.json total "
      f"{lab.get('total')}" if reg_ok else
      ("report_figures.labels_registry is MISSING — re-run write_labels.py after build_outputs.py"
       if not reg else f"labels_registry {reg} disagrees with labels-l2.json"))

# 11 — OUTPUT_SPEC §7 closing rule: every number in the report is derivable from the
#      aggregates. Flatten every numeric value in aggregates-l2.json, add the percentages and
#      ratios formable from any two of them, and require every data number in the report to
#      land in that set.
import re


def flatten(o, out):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)):
        out.add(round(float(o), 6))
    elif isinstance(o, str):
        if re.fullmatch(r"-?\d+", o):
            out.add(float(o))
    elif isinstance(o, dict):
        for v in o.values():
            flatten(v, out)
    elif isinstance(o, list):
        for v in o:
            flatten(v, out)


base = set()
flatten(agg, base)
derived = set(base)
for x in base:
    derived.add(round(x * 100, 6))          # fractions stored as 0.5932 -> 59.32
ints = sorted(v for v in base if v == int(v) and 0 < v <= 100000)
for x in ints:                              # percentages and x-fold ratios
    for y in ints:
        if y and x <= y:
            for dp in (0, 1, 2):
                derived.add(round(100.0 * x / y, dp))
        if y and x >= y:
            derived.add(round(float(x) / y, 0))
report = open(f"{OUT}/REPORT-L2.md").read()
# strip fenced/inline code, addresses, block numbers, dates, section refs and table pipes
txt = re.sub(r"0x[0-9a-fA-F…]+", " ", report)            # incl. elided forms like 0x…10003
txt = re.sub(r"\b(EIP|ERC|SHA)-?\s?\d+", " ", txt)      # standard numbers are not data
txt = re.sub(r"\b(19|20)\d\d\b", " ", txt)              # bare years
txt = re.sub(r"§\d+(\.\d+)?", " ", txt)
txt = re.sub(r"\b(19|20)\d\d-\d\d-\d\d\b", " ", txt)
txt = re.sub(r"^#+ .*$", " ", txt, flags=re.M)          # headings carry section numbers
txt = re.sub(r"METHOD |OUTPUT_SPEC |TASK ", " ", txt)
nums = set()
for m in re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])", txt):
    raw = m.group(1).replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        continue
    if v in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 40, 100):
        continue                                        # structural / list counts
    nums.add(round(v, 6))
unmatched = sorted(v for v in nums if v not in derived
                   and round(v, 1) not in derived and round(v, 0) not in derived)
if unmatched:
    print("  unmatched:", unmatched, file=sys.stderr)
check("every number in REPORT-L2.md is derivable from aggregates-l2.json (OUTPUT_SPEC §7)",
      not unmatched,
      f"{len(nums)} data numbers checked, {len(unmatched)} not derivable"
      + (f": {unmatched[:12]}" if unmatched else ""))

width = max(len(n) for n, _o, _d in results)
bad = 0
for name, ok, detail in results:
    bad += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
print(f"\n{len(results) - bad}/{len(results)} acceptance criteria pass")
sys.exit(1 if bad else 0)
