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

# 2 — every lookup has a verdict, none defaulted
lookups = sum(len(load(f"{OUT}/code/{c}.json")) for c in CHAINS)
unresolved_files = [f for c in CHAINS
                    for f in [f"{OUT}/code/{c}.json.unresolved.json"] if os.path.exists(f)]
check("all 22,162 (chain,address) lookups have a code verdict",
      lookups == 22162 and t["by_to_kind"]["unresolvable"] == 0,
      f"{lookups} cache entries, {t['by_to_kind']['unresolvable']} unresolvable, "
      f"{len(unresolved_files)} unresolved-list file(s)")

# 3 — reconciliation, and is_system is not a seventh bucket
check("six to_kind buckets are disjoint and sum to 24,067 txs / 21,515 pairs",
      sum(t["txs_by_to_kind"].values()) == 24067
      and sum(t["by_to_kind"].values()) == 21515
      and all(agg["chains"][c]["candidate_txs"] == sum(agg["chains"][c]["txs_by_to_kind"].values())
              for c in CHAINS))
check("is_system counted WITHIN the buckets, not as a seventh",
      sum(t["system"]["by_to_kind"].values()) == t["system"]["recipients"]
      and set(t["system"]["by_to_kind"]) <= set(t["by_to_kind"]),
      f"{t['system']['recipients']} system recipients across {t['system']['by_to_kind']}")

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
check("contract-later excluded from the headline but reported",
      t["by_to_kind"]["contract-later"] == t["contract_later"]["recipients"],
      f"contract-later = {t['contract_later']}")

# 5 — the dating error is sized, and the eoa control ran and is reported
check("per-recipient dating error SIZED (straddling population reported)",
      "straddling_recipients" in t["contract_later"] and "straddling_txs" in t["contract_later"],
      f"{t['contract_later']['straddling_recipients']} recipients / "
      f"{t['contract_later']['straddling_txs']} txs straddle a deployment")
check("`--kinds eoa` control run on >=1 archive chain and reported (incl. a null result)",
      t["eoa_control"]["sampled"] > 0 and len(t["eoa_control"]["chains"]) >= 1,
      f"{t['eoa_control']['sampled']} sampled on {len(t['eoa_control']['chains'])} chains, "
      f"{t['eoa_control']['had_code_at_tx_time']} contradictions")

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
        for d in ("code", "codetime", "recipients", "txs", "recipients-deposits")
        for c in CHAINS if not (d == "codetime" and c in ("lens", "cronos"))]
absent = [f for f in need if not os.path.exists(f"{OUT}/{f}")]
check("all OUTPUT_SPEC deliverables present", not absent, f"missing {absent}")
check("aggregates' own reconciliation assertions all pass",
      all(t.get("reconciliation_checks", {}).values()),
      str({k: v for k, v in t.get("reconciliation_checks", {}).items() if not v} or "all ok"))
check("labels-l2.json extends rather than overwrites the parent registry",
      load(f"{OUT}/labels-l2.json").get("parent_entries") == 57
      and len(load(f"{ROOT}/results/scripts/labels.json")) == 57)

width = max(len(n) for n, _o, _d in results)
bad = 0
for name, ok, detail in results:
    bad += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
print(f"\n{len(results) - bad}/{len(results)} acceptance criteria pass")
sys.exit(1 if bad else 0)
