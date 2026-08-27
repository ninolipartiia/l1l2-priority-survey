#!/usr/bin/env python3
"""write_manifest.py — emit ../run-manifest-l2.json (OUTPUT_SPEC §8)."""
import hashlib, json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, ".."))
CHAINS = ["era", "abstract", "zkcandy", "zero", "lens", "cronos", "sophon", "openzk"]


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None


def load(p):
    return json.load(open(p)) if os.path.exists(p) else {}


pins = load(f"{OUT}/seed/pinned-blocks.json")
agg = load(f"{OUT}/aggregates-l2.json")

# Endpoint actually used per chain, with the eth_chainId it returned (Phase 0, 2026-08-26).
ENDPOINTS = {
    "era":      {"url": "https://mainnet.era.zksync.io",   "chain_id_returned": "0x144   (324)"},
    "abstract": {"url": "https://api.mainnet.abs.xyz",     "chain_id_returned": "0xab5   (2741)"},
    "sophon":   {"url": "https://rpc.sophon.xyz",          "chain_id_returned": "0xc3b8  (50104)"},
    "lens":     {"url": "https://rpc.lens.xyz",            "chain_id_returned": "0xe8    (232)"},
    "cronos":   {"url": "https://mainnet.zkevm.cronos.org", "chain_id_returned": "0x184  (388)"},
    "zero":     {"url": "https://rpc.zerion.io/v1/zero",   "chain_id_returned": "0x849ea (543210)"},
    "openzk":   {"url": "https://rpc.openzk.net",          "chain_id_returned": "0x541   (1345)"},
    "zkcandy":  {"url": "https://explorer.zkcandy.io/api",
                 "chain_id_returned": "n/a — this is the block explorer's Etherscan-compatible "
                                      "API, not a JSON-RPC node; it cannot serve eth_chainId",
                 "substitution": True},
}

per_chain = {}
for c in CHAINS:
    ct = load(f"{OUT}/codetime/{c}.json")
    ct_pm = load(f"{OUT}/codetime-pm/{c}.json")
    ct_eoa = load(f"{OUT}/codetime-eoa-control/{c}.json")
    code = load(f"{OUT}/code/{c}.json")
    per_chain[c] = {
        "endpoint": ENDPOINTS[c]["url"],
        "chain_id_verified": ENDPOINTS[c]["chain_id_returned"],
        "is_substitution": ENDPOINTS[c].get("substitution", False),
        "code_cache_block": pins.get(c, {}).get("block", "latest-via-explorer"),
        "archive_getcode": c != "zkcandy",
        "archive_probe": (
            "eth_getCode(0x…10003) served at tip, tip-1k, tip-100k and tip-1M. On cronos and "
            "zero this DISCRIMINATES: a different code size at tip-1M (39,392 B vs 42,528 B) "
            "proves historical state. On the other chains the probe shows only that the call "
            "was served at depth, which a silent latest-block fallback would also do — an "
            "independent review re-test confirmed real historical state on era, abstract, "
            "sophon, lens and openzk via eth_getCode(<contract>, 0x1) == 0x while latest "
            "returns code. See REPORT-L2.md §2.2."
            if c not in ("zkcandy", "openzk") else
            "openzk's tip is only 9,136 blocks, so tip-100k/tip-1M clamp to block 1; archive was "
            "confirmed at tip-1k" if c == "openzk" else
            "no JSON-RPC endpoint; code-time is DERIVED from the explorer's contract-creation "
            "block instead of probed (see zkcandy_substitution)"),
        "address_lookups": len(code),
        "code_time_verdicts": len(ct),
        "code_time_verdicts_control_set": len(ct_pm),
        "eoa_control_sampled": len(ct_eoa),
        "explorer_api": {
            "era": "https://block-explorer-api.mainnet.zksync.io/api",
            "abstract": "https://block-explorer-api.mainnet.abs.xyz/api",
            "sophon": "https://api-explorer.sophon.xyz/api",
            "lens": "https://explorer-api.lens.xyz/api",
            "zero": "https://explorer.zero.network/api",
            "openzk": "https://explorer.openzk.net/api",
            "zkcandy": "https://explorer.zkcandy.io/api",
            "cronos": None,
        }[c],
    }

manifest = {
    "phase": "6 — L2-side recipient census",
    "input_package": "phase6-l2-recipients/",
    "source_dataset": "results/ (45,711 priority txs, 8 chains, window 2025-08-26 → 2026-08-26; "
                      "census run 2026-08-25). NOT modified — verified with `git status results/`.",
    "run_dates": {"started": "2026-08-26", "finished": "2026-08-26"},
    "parameters": {"CHAINS": CHAINS, "CLASSES": ["direct-transfer", "other"],
                   "RECUR_MIN": 2,
                   "control_set": "--classes protocol-message, resolved and code-time-dated "
                                  "separately into code-pm/ and codetime-pm/",
                   "secondary_set": "--deposit-beneficiaries (decoded canonical-deposit "
                                    "l2Receiver), resolved into the same per-chain code cache"},

    "phase0_preflight": {
        "ground_truth_reproduced": True,
        "how": "results-l2/scripts/reproduce_ground_truth.py recomputes every field of "
               "phase6-l2-recipients/seed-data/ground-truth.json from results/enriched/*.jsonl "
               "and diffs them. All totals, all per-chain values and all top-10 recipient lists "
               "(txs DESC, address ASC) reproduced exactly; exit 0.",
        "quickstart": "README quickstart reproduced exactly: lens 4/4 kinds={'eoa': 4}; zero "
                      "257/257 kinds={'eoa': 256, 'contract': 1}; zero code_at_tx tally "
                      "{'contract': 1} with l2_block 0x34ad52 / probe_block 0x34ad51.",
        "endpoint_liveness": "7/8 JSON-RPC endpoints returned the chain id CHAINS.md records. "
                             "zkcandy's rpc.zkcandy.io still returns an empty response, exactly "
                             "as INPUTS.md recorded.",
    },

    "zkcandy_substitution": {
        "problem": "rpc.zkcandy.io is dead. INPUTS.md/METHOD §6.3 expected its 1,396 candidate "
                   "txs / 1,251 recipients to be UNRESOLVABLE.",
        "rpc_alternatives_probed_and_rejected": {
            "https://320.rpc.thirdweb.com": "answers eth_chainId 0x140 (=320, genuinely zkcandy) "
                                            "but refuses every other method without an API key",
            "https://zkcandy.drpc.org": "404 Not Found",
            "https://rpc.ankr.com/zkcandy": "403, key required",
            "https://zkcandy-mainnet.public.blastapi.io": "no response",
            "https://mainnet.zkcandy.io / rpc.zkcandy.com / rpc-mainnet.zkcandy.io "
            "/ zkcandy-mainnet.rpc.caldera.xyz": "no response / 404",
            "chainid.network registry": "lists only rpc.zkcandy.io for chainId 320",
        },
        "what_worked": "the block explorer is ALIVE at https://explorer.zkcandy.io/api — a "
                       "BLOCKSCOUT instance with an Etherscan-compatible subset (NOT the "
                       "matter-labs/block-explorer software era runs) — and it indexes the "
                       "census's canonical hashes. INPUTS.md recorded the explorer as down; it "
                       "answers now — the live chain wins over the package (TASK constraint 4).",
        "script": "results-l2/scripts/resolve_zkcandy_explorer.py",
        "method": "eth_getCode -> contract&getcontractcreation (a creation record means code); "
                  "eth_getTransactionByHash + historical eth_getCode -> account&txlist for the "
                  "funding tx's block, compared against the creation block. Code-time is "
                  "DERIVED (created_block < funding_block) rather than probed at block-1; the "
                  "semantics match (code existed before the funding tx's block).",
        "validation": "results-l2/seed/zkcandy-method-validation.json. REBUILT 2026-08-27: the "
                      "original argument leaned on a 208/208 cross-validation against era on the "
                      "premise that era runs 'the same explorer API'. That premise is FALSE "
                      "(Blockscout vs matter-labs/block-explorer), and the two diverge precisely "
                      "on this method's blind spot — era's explorer returns creation records for "
                      "genesis contracts, zkcandy's does not — so the era run had no power over "
                      "the failure mode that exists here. It is retained (and was independently "
                      "reproduced at 208/208) but demoted. The load-bearing evidence is now "
                      "zkcandy-side: (1) listcontracts enumerates the chain's COMPLETE contract "
                      "population, 314 addresses, whose intersection with the census's 1,256 is "
                      "exactly {0x0}; (2) recall measured over all 314, 291/291 on non-system "
                      "contracts and 0/20 on genesis; (3) an independent instrument, Blockscout "
                      "/api/v2/addresses/{addr} -> is_contract, agreeing on 174 of 174 answered "
                      "of 184 sampled.",
        "chain_identity_without_eth_chainId": "the endpoint cannot serve eth_chainId, so identity "
                      "rests on: the explorer indexing the census's canonical hashes with "
                      "matching to/from/value, and those hashes coming from NewPriorityRequest "
                      "logs on the L1 diamond 0xf2704433d11842d15aa76bbf0e00407267a99c92, whose "
                      "getChainId() returns 0x140 = 320. 320.rpc.thirdweb.com answering 0x140 is "
                      "evidence about a DIFFERENT host and was not relied on.",
        "api_trap_handled": "contractaddresses caps at 10 and, above the cap, SILENTLY TRUNCATES "
                            "TO THE FIRST 10 while still answering status:1 'OK' — a caller "
                            "chunking at 60 would mint false 'EOA' verdicts for 83% of every "
                            "chunk. The script hard-caps at 10 and asserts every returned address "
                            "was asked for. (An earlier note here said the API returns results "
                            "for NONE of them above the cap; that was a misdiagnosis from a probe "
                            "that placed the only contract in position 11 — exactly the address "
                            "truncation removes. era's API caps at 5 and errors loudly with "
                            "status:0 NOTOK.)",
        "declared_limitations": [
            "no bytecode FROM THE ENDPOINT CHOSEN — so no code_len, no codehash, no families. "
            "Corrected 2026-08-27: this is not a property of the host. The same Blockscout "
            "instance serves /api/v2/smart-contracts/{addr} with deployed_bytecode, so the "
            "capability existed and was not used. Moot for the headline (no contract recipients "
            "to cluster).",
            "EIP-7702 delegated-eoa is undetectable — zkcandy's delegated-eoa count is UNKNOWN, "
            "not zero. Not idle: 96 of the 1,256 addresses carry a 0xef0100 delegation on "
            "Ethereum L1. No sampled address showed a Blockscout eip7702 proxy_type, but there "
            "is no positive control on zkcandy, so 'unknown' stands.",
            "genesis-deployed contracts have no creation record and read as codeless — measured "
            "exhaustively: 20 of the chain's 314 contracts, ALL inside the reserved range. "
            "Correct examples are 0x0, 0x…8006, 0x…800a, 0x…800b, 0x…8014, 0x…10000. An earlier "
            "version cited 0x…8007/10002/10005, which are NOT contracts on zkcandy at all and "
            "return nothing merely because they are codeless. This is why address 0x0 lands in "
            "zkcandy's `eoa` bucket while it is `contract` on abstract, sophon, zero and openzk.",
            "getcontractcreation cannot distinguish 'indexed, no code' from 'never indexed' — "
            "closed empirically (all 1,256 are known to the indexer) but not by the method.",
            "the verdict is at the explorer's tip WITH INDEXER LAG, not at a pinned block as on "
            "the seven RPC chains.",
            "zkcandy has NO METHOD §3 `eoa`-control coverage — the control needs an archive "
            "endpoint and there is none, so codetime-eoa-control/zkcandy.json does not exist. "
            "The one chain resolved by a substitute instrument is the one chain with no negative "
            "control.",
            "METHOD §3's self-destruct concern is INAPPLICABLE on a ZK-stack chain (no "
            "SELFDESTRUCT opcode), so the 'had code when paid, none now' failure mode cannot "
            "occur here.",
        ],
        "result": "1,256/1,256 zkcandy addresses resolved; 0 unresolvable; 0 contract recipients "
                  "OUTSIDE THE RESERVED RANGE. Address 0x0 is a contract on zkcandy and is one "
                  "of the 1,251 candidate recipients (tx_id 6348), but carries is_system and "
                  "sits in the `eoa` bucket per the genesis limitation above.",
    },

    "deviations_from_the_package": [
        {"what": "zkcandy resolved via the block explorer instead of JSON-RPC",
         "why": "no JSON-RPC endpoint exists; the alternative was leaving 1,396 txs / 1,251 "
                "recipients unresolvable. See zkcandy_substitution for the validation.",
         "justified": True},
        {"what": "abstract's explorer API used without an Etherscan V2 key",
         "why": "CHAINS.md says abstract needs an Etherscan V2 key. It does not: "
                "block-explorer-api.mainnet.abs.xyz is the same ZKsync-era-style API era uses "
                "and answered getsourcecode/getcontractcreation unauthenticated.",
         "justified": True},
        {"what": "explorer API bases discovered at runtime for sophon, zero and openzk",
         "why": "CHAINS.md marks them 'discover at runtime'. Found: api-explorer.sophon.xyz, "
                "explorer.zero.network/api, explorer.openzk.net/api.",
         "justified": True},
        {"what": "no explorer API found for cronos",
         "why": "CHAINS.md notes /api 301-redirects; several bases probed, none answered. "
                "cronos has 0 contract recipients and 0 contract deposit beneficiaries, so no "
                "attribution depended on it.",
         "justified": True},
        {"what": "--no-chain-check was NEVER used; --allow-input-name-mismatch was NEVER used",
         "why": "every RPC run passed the eth_chainId assertion and every file named its chain.",
         "justified": True},
        {"what": "code/zkcandy.json carries the sentinel block \"latest-via-explorer\" and "
                 "len: null, where OUTPUT_SPEC §1 requires a concrete block number and the "
                 "other 7 caches carry len: 0 for EOAs",
         "why": "the explorer substitute answers about contract-creation RECORDS, not about "
                "state at a block, so there is no block number to record and no code length to "
                "measure. A fabricated block number would be worse than a sentinel. Downstream "
                "consequence: code_len is null on all 1,251 zkcandy recipient rows and is not "
                "comparable across chains — stated in REPORT-L2.md §10.",
         "justified": True},
        {"what": "REPORT-L2.md has ELEVEN top-level sections where OUTPUT_SPEC §7 lists ten",
         "why": "a section 6 'Deposit beneficiaries (secondary set)' was inserted, shifting the "
                "spec's §6-§10 to §7-§11. All ten required topics are present and in the spec's "
                "order; the secondary set needed its own section to keep it from being read as "
                "part of the candidate headline. A reader following the spec's numbering will "
                "land one section early from §6 onward.",
         "justified": True},
        {"what": "the input package's committed state (aa71a57) differs from the commit this "
                 "phase started against (a88ecdf) in 4 files: README.md, "
                 "scripts/check_code_time.py, scripts/resolve_l2_code.py, "
                 "seed-data/probe-samples.json",
         "why": "those edits were present as uncommitted working-tree changes when this phase "
                "began and were folded into the input-package commit, not made by this phase's "
                "work. They add an --out filename guard to both scripts and correct a ranking "
                "claim in probe-samples.json, and they match what README.md and METHOD.md "
                "already described. seed-data/ground-truth.json and all of results/ are "
                "byte-identical between a88ecdf and HEAD, so the Phase 0 gate and the source "
                "dataset are unaffected. script_versions below pins the MODIFIED hashes; "
                "`git diff a88ecdf HEAD -- phase6-l2-recipients/` shows the drift.",
         "justified": True},
        {"what": "the 140 era canonical-deposit records carrying the v26 selector 0x9c884fd1 "
                 "were NOT decoded",
         "why": "METHOD §1 puts them out of scope for the shipped resolver. They are reported as "
                "a counted skip on every run and carried into the report; the workload table is "
                "therefore the package's 22,162 and not larger.",
         "justified": True},
    ],

    "approximate_call_counts": {
        "eth_getCode (code caches, batched ≤60)": sum(len(load(f"{OUT}/code/{c}.json"))
                                                      for c in CHAINS if c != "zkcandy")
        + sum(len(load(f"{OUT}/code-pm/{c}.json")) for c in CHAINS),
        "explorer getcontractcreation (zkcandy sweep, ≤10 addresses/call)": 126,
        "eth_getTransactionByHash + eth_getCode (code-time gate, batched)":
            2 * sum(len(load(f"{OUT}/codetime/{c}.json")) + len(load(f"{OUT}/codetime-pm/{c}.json"))
                    for c in CHAINS),
        "eth_getCode (METHOD §3 eoa control)":
            2 * sum(len(load(f"{OUT}/codetime-eoa-control/{c}.json")) for c in CHAINS),
        "eth_getStorageAt (3 proxy slots × every contract)":
            3 * sum(1 for c in CHAINS for v in load(f"{OUT}/code/{c}.json").values()
                    if v.get("kind") == "contract"),
        "explorer getsourcecode + getcontractcreation (attribution)": 800,
    },

    "script_versions": {p: sha(os.path.join(HERE, "..", "..", p)) for p in (
        "phase6-l2-recipients/scripts/resolve_l2_code.py",
        "phase6-l2-recipients/scripts/check_code_time.py",
        "results-l2/scripts/reproduce_ground_truth.py",
        "results-l2/scripts/resolve_zkcandy_explorer.py",
        "results-l2/scripts/fetch_contract_names.py",
        "results-l2/scripts/build_outputs.py",
        "results-l2/scripts/write_manifest.py",
        "results-l2/scripts/write_labels.py",
        "results-l2/scripts/check_acceptance.py",
        "results-l2/scripts/attribution.json",
    )},

    "acceptance": "results-l2/scripts/check_acceptance.py re-checks every TASK.md acceptance "
                  "criterion mechanically; 22/22 pass as of this run. Strengthened after an "
                  "independent audit found several checks circular or vacuous: the bucket "
                  "reconciliation and the lookup-coverage check now re-derive from "
                  "results/enriched/ and compare KEY SETS rather than counts; the "
                  "contract-later, is_system and labels checks now test the named property "
                  "rather than a proxy for it; and a new check enforces OUTPUT_SPEC §7's rule "
                  "that every number in REPORT-L2.md is derivable from aggregates-l2.json — "
                  "the one criterion the earlier checker did not test, and the one that failed. "
                  "A 22nd check was added later: the pipeline order is build_outputs.py -> "
                  "write_labels.py -> write_manifest.py, and re-running build_outputs.py alone "
                  "leaves report_figures.labels_registry nulled; the guard asserts that block is "
                  "present and agrees with labels-l2.json so a partial rebuild fails loudly.",
    "independent_audit": {
        "when": "2026-08-27",
        "what": "four independent agents re-derived the numbers from results/enriched/ without "
                "using this phase's scripts, re-verified verdicts against the live L2 RPCs and "
                "explorers, attacked the zkcandy substitute, and audited the report against the "
                "spec.",
        "outcome": "no arithmetic error was found in aggregates-l2.json, families.json or the "
                   "per-row outputs, and contract-later = 0 survived independent on-chain "
                   "re-testing. Defects found and fixed: the parent-census correction in §9 was "
                   "understated ~8x (it omitted the 154 canonical deposits landing on protocol "
                   "contracts); a categorical claim about 298 control records was true for 293; "
                   "the eoa-control coverage divided a 1,298-address sample by a 21,211 "
                   "population it was not drawn from; §4 claimed family coverage of the control "
                   "set it does not cluster; txs_value_gt0 was defaulted rather than counted on "
                   "all 787 deposit rows; OzkVault's confidence was medium where the rubric "
                   "says low; the merged registry had overwritten 10 parent label texts; and "
                   "'the sender's own wallet' was an inference stated as measurement.",
    },
    "per_chain": per_chain,
    "reconciliation_checks": agg.get("totals", {}).get("reconciliation_checks", {}),
    "headline": {
        "candidate_txs": agg.get("totals", {}).get("candidate_txs"),
        "eoa_to_contract_txs": agg.get("totals", {}).get("eoa_to_contract_txs"),
        "eoa_to_contract_recipients": agg.get("totals", {}).get("eoa_to_contract_recipients"),
        "by_actor_type": agg.get("totals", {}).get("by_actor_type"),
    },
}

manifest["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
json.dump(manifest, open(f"{OUT}/run-manifest-l2.json", "w"), indent=1)
print(f"wrote {OUT}/run-manifest-l2.json")
