# INPUTS — what you are starting from

## 1. The existing dataset (`../results/`) — treat as read-only

The parent census is complete and verified: **45,711 L1→L2 priority transactions** across 8
ZK-stack chains, window 2025-08-26 → 2026-08-26, provably gap-free (txId continuity,
`getTotalPriorityTxs()` boundary proofs at both edges, 96/96 L2 spot checks). Class split:

| class | txs | in scope here? |
|---|---|---|
| `direct-transfer` | 24,052 | **yes — primary candidate set** |
| `other` | 15 | **yes — primary candidate set** (every EOA-origin record that is not a plain empty-calldata transfer) |
| `canonical-deposit` | 3,064 | secondary — via decoded `l2Receiver`, not via `to` |
| `protocol-message` | 18,580 | control set only (sender is already a contract) |

`other` is a residual bucket, not a calldata bucket: **only 4 of the 15 carry calldata**
(abstract tx 26927 selector `0x64e7f93b`, and era 3301321/3301322/3301323 selector
`0x095ea7b3` = `approve`). The remaining 11 have `data_len = 0`, `value = 0` — 0-value pings,
5 of which target `0x0` and are removed by the system filter (METHOD §3). Size the "users
driving L2 contracts from L1" analysis at **4 records**, and note that these 15 are also
exactly the 14 zero-value candidates plus the one abstract call.

`../results/REPORT.md` is the parent deliverable; §3 lists the 14 protocols already
attributed from the **sender** side. A recipient you find here may well belong to one of
them — check before opening a new investigation.

## 2. Why the recipient axis is missing (do not re-derive this)

`classify()` in `../results/scripts/enrich.py:144` decides the class from: `unalias(inner
from) ∈ CANONICAL_L1_BRIDGES`, `inner from == l1_from`, `data_len`, `value`. It never reads
`to`. `../results/scripts/codecache.json` holds 21,135 `eth_getCode` results — **all on
Ethereum L1**, for initiators and alias tests. No L2 `getCode` has ever been run. `l1_to`
is populated but feeds neither classification nor aggregation.

## 3. Workload sizing (ground truth — reproduce exactly in Phase 0)

Full per-chain detail with top-10 recipient lists: `seed-data/ground-truth.json`.

| chain | candidate txs | distinct recipients (per chain) | ≥2 txs | ≥5 txs | ≥10 txs | max to one | deposit beneficiaries |
|---|---|---|---|---|---|---|---|
| era | 19,044 | 18,325 | 268 | 28 | 11 | 94 | 201 |
| abstract | 3,273 | 1,676 | 397 | 60 | 20 | 162 | 323 |
| zkcandy | 1,396 | 1,251 | 106 | 2 | 1 | 10 | 10 |
| zero | 339 | 257 | 35 | 7 | 1 | 12 | 21 |
| lens | 11 | 2 | 1 | 1 | 1 | 10 | 3 |
| cronos | 2 | 2 | 0 | 0 | 0 | 1 | 30 |
| sophon | 1 | 1 | 0 | 0 | 0 | 1 | 194 |
| openzk | 1 | 1 | 0 | 0 | 0 | 1 | 5 |
| **all** | **24,067** | **21,515** (sum) | **807** | **98** | **34** | 162 | **787** (sum) |

Of the 24,067 candidates, **24,053 move value > 0**; 14 are 0-value (pings/calls).

**Per-chain sums are not distinct-address counts.** The 21,515 and 787 columns add up
per-chain totals, which is the right number for *work* (code status is per-chain — METHOD
§6.2 — so every (chain, address) pair is its own lookup) and the wrong number for
*population*. Globally:

| quantity | per-chain sum | globally distinct (addresses) | on ≥2 chains |
|---|---|---|---|
| candidate recipients | 21,515 | **21,480** | 31 |
| deposit beneficiaries | 787 | **775** | 11 |
| both sets combined | 22,302 sum / **22,162** union | **22,106** | — (149 addresses are in both sets) |

Say which one you mean everywhere. "21,515 distinct recipients" and "31 addresses appear on
≥2 chains" cannot both be true in the same sentence; `aggregates-l2.json` carries both
figures under distinct names (OUTPUT_SPEC §6).

**The getCode workload is 22,162, not 22,302.** The resolver builds one address set per
chain, so an address that is both a candidate recipient and a deposit beneficiary *on the
same chain* is resolved once — that happens 140 times (era 44, abstract 82, zero 8, zkcandy
5, lens 1), and it is a different quantity from the 149 addresses that are in both sets
globally. Per-chain lookup counts are in `ground-truth.json:per_chain.*.address_lookups`
(era 18,482 · abstract 1,917 · zkcandy 1,256 · zero 270 · sophon 195 · cronos 32 · openzk 6
· lens 4). The quickstart shows it directly: lens has 2 candidate recipients and 3 deposit
beneficiaries but the resolver reports **4 targets**.

Reading of the shape: era has 18,325 distinct recipients for 19,044 txs — nearly one-shot
sends, so the *recurring* set that Phase 4 must attribute is small (807 addresses ≥2 txs,
98 at ≥5). Abstract is the opposite: 3,273 txs over 1,676 recipients with a heavy head
(top recipient 162 txs). **Attribution effort is therefore concentrated on abstract and
era**, and the mechanical `getCode` sweep (22,162 lookups over 22,106 distinct addresses,
batched at 60) is a few hundred batched RPC calls — cheap: abstract's 1,917 lookups are 32
batches, and code-time-dating its 354 contract recipients took 5 seconds (measured
2026-08-26; both calls in that gate are batched too).

## 4. Endpoint status (verified 2026-08-26)

Full results in `seed-data/probe-samples.json`. Summary:

- **7 of 8 L2 RPCs live**: era, abstract, sophon, lens, cronos, zero, openzk — all returned
  the correct `eth_chainId`.
- **zkcandy is dead**: `https://rpc.zkcandy.io` returns nothing, explorer down, no free
  alternative found. **1,396 candidate txs / 1,251 recipients (5.8% of the candidate set)
  are unresolvable** unless you find a new endpoint. Declare, don't guess (METHOD §6.3).
- **Batched `eth_getCode` verified** on era, abstract, lens, zero at batch size 60.
- **Historical `eth_getCode` verified on zero** (archive available) — probe the other chains
  in Phase 0; this determines how much of the code-time gate (METHOD §4) is provable.
- **Sophon still answers** despite the wind-down — resolve it early anyway.
- Explorer APIs: era (`block-explorer-api.mainnet.zksync.io`) and lens
  (`explorer-api.lens.xyz`) verified in `../CHAINS.md`; abstract needs an Etherscan V2 key;
  the rest must be discovered at runtime. zkcandy's explorer is gone.

## 5. Already-verified starting findings

From `seed-data/probe-samples.json` — these are real, and each is a thread to pull:

1. **abstract clone family**: three recipients at **ranks 1, 5 and 6** (162 + 94 + 60 =
   **316 txs**) are **byte-identical** proxies (1,632 bytes, `sha256 fbd752b5…`) pointing at
   one ERC1967 implementation `0xaa3633b417483f932969edaef7cc4f1068f6faa9`. Almost certainly
   a smart-account family (AGW/native AA) rather than a protocol — **verify, then label**.
   Not the top three: ranks 2–4 (133 + 129 + 102) are outside the family, and abstract's
   actual top three total 424 txs. Only these three addresses were sampled — the Phase 1
   sweep decides the family's real size.
2. **era's only recurring contract recipient in the top 10**:
   `0x9cb1e077e7253a4f022e74862a93ee7cecab788b`, 19 txs, 3,104 bytes, unidentified.
3. **zero fully resolved**: 256 of 257 recipients are plain EOAs; the one "contract" is
   address `0x0` (224 bytes of code) — the tester ping target, i.e. a false positive that
   the system-address filter must remove.
4. **Cross-chain self-funding**: `0xf70da97812cb96acdf810712aa562db8dfa3dbef` is the #1
   *recipient* on era (94 txs) and #2 on abstract (133) **and** the #1 L1 *initiator* on both
   (94/17,122 and 133/1,654) — it pays itself. It also appears on zero, but marginally
   there: 3 txs, rank 17 of zero's **257** recipients (not of 255, which is zero's distinct
   initiator count — METHOD §6.10). So the pattern is real and concentrated on era + abstract,
   not a three-chain phenomenon. Expect it to explain a large share of the recurring-EOA head.

## 6. What "done" looks like

A `REPORT-L2.md` that can answer, with numbers that reconcile to 24,067: *of the L1→L2 txs
a user originated, how many actually paid a contract on L2 — and of those, how many were the
user's own smart wallet versus a real protocol, and which protocols.* Plus the honest
denominators: how many recipients could not be resolved (zkcandy) and how many contract
verdicts could not be dated (no archive).
