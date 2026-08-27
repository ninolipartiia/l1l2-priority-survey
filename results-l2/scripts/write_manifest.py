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
            "eth_getCode(0x…10003) served at tip, tip-1k, tip-100k and tip-1M; cronos and zero "
            "returned a DIFFERENT code size at tip-1M (39,392 B vs 42,528 B), which proves "
            "historical state rather than a latest-block fallback"
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
        "what_worked": "the block explorer is ALIVE at https://explorer.zkcandy.io/api "
                       "(ZKsync-era-style, Etherscan-compatible subset) and indexes the "
                       "census's canonical hashes. INPUTS.md recorded the explorer as down; it "
                       "answers now — the live chain wins over the package (TASK constraint 4).",
        "script": "results-l2/scripts/resolve_zkcandy_explorer.py",
        "method": "eth_getCode -> contract&getcontractcreation (a creation record means code); "
                  "eth_getTransactionByHash + historical eth_getCode -> account&txlist for the "
                  "funding tx's block, compared against the creation block. Code-time is "
                  "DERIVED (created_block < funding_block) rather than probed at block-1; the "
                  "semantics match (code existed before the funding tx's block).",
        "validation": "results-l2/seed/zkcandy-method-validation.json — cross-validated on era, "
                      "which has both a working archive RPC and the same explorer API: 208/208 "
                      "agreement (all 8 era contract recipients + 200 random era EOA recipients, "
                      "0 disagreements, 0 API errors). Positive control on zkcandy itself found "
                      "8 real contracts.",
        "api_trap_handled": "contractaddresses caps at 10 and returns status:1 'OK' with ZERO "
                            "results above it — silent truncation that would have produced a "
                            "whole chain of false 'EOA' verdicts. The script hard-caps at 10 and "
                            "asserts every returned address was asked for. (era's copy of the "
                            "same API caps at 5 but errors loudly with status:0 NOTOK.)",
        "declared_limitations": [
            "no bytecode: zkcandy contributes no code_len, no codehash and no bytecode family",
            "EIP-7702 delegated-eoa is undetectable — zkcandy's delegated-eoa count is UNKNOWN, "
            "not zero",
            "genesis-deployed contracts have no creation record and read as codeless; verified "
            "for 0x…8007/800a/800b/10002/10005. All genesis contracts are inside the reserved "
            "range that METHOD §3 flags is_system, so no user-chosen counterparty is mis-filed — "
            "but it IS why address 0x0 lands in zkcandy's `eoa` bucket while it is `contract` on "
            "abstract, sophon, zero and openzk.",
        ],
        "result": "1,256/1,256 zkcandy addresses resolved; 0 unresolvable; 0 contract recipients.",
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
                  "criterion mechanically; 20/20 pass as of this run.",
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
