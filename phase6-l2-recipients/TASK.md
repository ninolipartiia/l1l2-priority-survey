# TASK — L2-side recipient census: which L1→L2 txs pay a contract, and whose contract is it?

## Objective

Over the existing census dataset (`../results/`, 45,711 priority txs, 8 chains, window
2025-08-26 → 2026-08-26):

1. For every **EOA-origin** priority tx (`class ∈ {direct-transfer, other}`; 24,067 txs)
   resolve the **L2-side recipient's code status** — EOA, contract, delegated EOA, or
   system address — *as of the moment the tx arrived*, not merely today.
2. Do the same for the **decoded beneficiaries of canonical deposits** (787 addresses),
   so "EOA deposits a token into a protocol contract" is captured too.
3. **Filter to the genuine EOA → contract set** and quantify it per chain and overall.
4. **Find the patterns**: which recipients recur, how the recurrence is distributed, which
   recipients share identical bytecode (clone families), which selectors recur, and which
   recipients/families appear on more than one chain.
5. **Attribute the recurring contract recipients**: for every contract recipient that
   appears several times, determine whether it belongs to a known protocol — and
   distinguish **user-controlled smart wallets** (still user activity) from genuine
   **protocol contracts** (real protocol usage). Give addresses, roles, evidence,
   confidence.
6. Produce the deliverables in `OUTPUT_SPEC.md`, and state plainly how the answer changes
   the census's picture of "~59% plain user activity".

## Parameters

- `CHAINS` ⊆ {era, abstract, sophon, lens, cronos, zero, zkcandy, openzk} — default: all 8
  (zkcandy will be partly unresolvable — see METHOD §6).
- `CLASSES` — candidate classes; default `direct-transfer,other`.
- `RECUR_MIN` — "appears several times" threshold for mandatory attribution; default **2**,
  with everything at **≥5 txs** required to reach a verdict (attributed or explicitly
  declared unattributable).

## Phases

### Phase 0 — Preflight (fast)
- Re-verify each L2 RPC with `eth_chainId` against `../CHAINS.md`; if one is dead, look for
  a replacement (chainlist.org, chain docs, explorer-backed RPC) and **record the
  substitution**. Status as of 2026-08-26 is in `INPUTS.md` — 7/8 live, zkcandy dead. Both
  scripts re-assert this on every run and abort on a mismatch (including for a `--rpc`
  substitution), so a dead or wrong endpoint fails in seconds instead of producing
  wrong-chain output; `--no-chain-check` exists only for an endpoint that genuinely cannot
  serve `eth_chainId`, and using it must be justified in the manifest.
- Reproduce every number in `seed-data/ground-truth.json` from `../results/enriched/*.jsonl`.
  **If any count differs, stop and report** — the input dataset is not what this plan assumes.
  Read `counting_rules` first: the top-10 lists are cut inside a tie on zero and zkcandy, so
  they only reproduce under the stated sort (txs DESC, then address ASC); `distinct_recipients`
  is per-chain — compare it against `distinct_recipients_per_chain_sum` (21,515), not
  `distinct_recipients_global` (21,480); and `address_lookups` is a per-chain **union**, so it
  is smaller than that chain's recipients + beneficiaries wherever the two sets overlap.
- Run the `README.md` quickstart.
- Probe archive capability per chain: `eth_getCode(<any contract>, <old block>)`. Record
  which endpoints serve historical code (verified working on zero) — this decides how much
  of Phase 2 is provable vs. unverified.

### Phase 1 — Resolve code status (mechanical, resumable)
- `scripts/resolve_l2_code.py` per chain for `CLASSES`, plus `--deposit-beneficiaries`,
  plus a separate run with `--classes protocol-message` as the control set.
- Sophon first (wind-down risk), then the rest; era is the bulk (18,482 lookups).
- Batches of ≤60, keep the built-in sleeps. Every address must end up either resolved or
  explicitly listed as unresolved — never defaulted to EOA.
- The resolver prints a **skip tally** for canonical-deposit records it cannot decode (140 on
  era carry the v26 selector — METHOD §1). Carry that number into the report; do not let it
  vanish between the workload table and the results.

### Phase 2 — Code-time verification (the correctness gate)
- `scripts/check_code_time.py` for every recipient marked `contract`, **with the same
  `--classes` / `--deposit-beneficiaries` flags used to build that chain's code cache** —
  otherwise the contracts that only appear as decoded beneficiaries have no earliest tx and
  land in the "no in-window record" bucket. Split the results into `contract` (code existed
  at tx time → genuine EOA→contract) vs `contract-later` (deployed afterwards → the tx
  actually paid a codeless address) vs `unavailable`.
- The verdict is dated at `blockNumber − 1` of the funding tx, not at its own block
  (METHOD §4). Do not "fix" this to the tx's block; it is the whole point of the gate.
- For `unavailable`, fall back to the explorer's contract-creation tx/timestamp and compare
  against the tx `ts`; if that also fails, mark `code-time-unverified` and keep it visible
  in every downstream number (never fold it silently into either bucket).
- Apply the system-address filter (METHOD §3) before any of this is called a "protocol
  interaction".

### Phase 3 — Families & pattern extraction (mechanical)
- Cluster contract recipients by exact bytecode identity (`codehash` from the resolver) into
  **families**; a family is the unit of attribution — one verdict covers all members.
- Build the recurrence distribution per chain (recipients with 1, 2–4, 5–9, ≥10 txs) and the
  top-N recipient tables; group the `other`-class records by `(to, selector)`.
- Cross-chain joins: same recipient address on ≥2 chains, same family bytecode on ≥2 chains.
- Resolve proxies: read the ERC1967 implementation slot
  `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc` (verified to work on
  abstract) and treat the implementation as part of the family's identity.

### Phase 4 — Attribution (research)
- For every family and every recipient with ≥`RECUR_MIN` txs (mandatory at ≥5): identify
  what it is. Techniques, in order of strength: verified source / contract name on the
  chain's explorer; the implementation address behind a proxy; exact bytecode equality with
  an already-identified contract (incl. across chains); `../results/scripts/labels.json` and
  `../KNOWN_ADDRESSES.md` seeds; selector DBs (openchain.xyz, 4byte.directory) for the
  `other`-class calldata; protocol docs / GitHub; web search.
- Assign **two** labels per contract recipient: `actor_type`
  (`smart-wallet` | `protocol-contract` | `token` | `unknown-contract`) and, where
  applicable, `protocol` with `confidence` (high/medium/low, semantics per
  `../results/REPORT.md` §5) and the evidence that supports it.
- `eth_call` probing of `name()` / `owner()` / `implementation()` proved **unreliable**
  (returns `0x` or errors on the samples in `seed-data/probe-samples.json`) — do not rely
  on it as primary evidence.
- Do **not** propagate a code-status or label across chains without re-verifying on that
  chain: the same address can be an EOA on one chain and a contract on another.

### Phase 5 — Analysis & report
- Aggregates and `REPORT-L2.md` per `OUTPUT_SPEC.md`. Lead with the headline split:
  of the 24,067 EOA-origin txs, how many paid an EOA, a smart wallet, a protocol contract,
  and how many are unresolvable/unverified — plus, as a separate line rather than a bucket,
  how many landed on a reserved system address (`is_system`, METHOD §3).
- State the correction to the parent census explicitly: which part of its "plain user
  activity" is really users driving L2 contracts, and which recurring recipients it missed.

## Hypotheses to test (from live probes — expect to be surprised)

- **H1: recipients are overwhelmingly plain EOAs.** era has 18,325 distinct recipients for
  19,044 txs (near 1:1, one-shot sends); zero resolved 256/257 recipients as EOAs.
- **H2: contract recipients cluster into a few bytecode families dominated by
  smart-contract wallets, not protocols.** On abstract, three of the top six recipients
  (ranks 1, 5, 6 — 162 + 94 + 60 = 316 txs) are byte-identical proxies to one implementation
  (`0xaa3633b4…`) — verify what it is; AGW/native-AA is the obvious candidate. Ranks 2–4 are
  not in the family, so this is not "abstract's head is one wallet family"; the sweep decides
  how many of the 1,676 recipients actually share that bytecode.
- **H3: genuine protocol interactions are rare and concentrated on era/abstract.** Confirm
  or refute with numbers, and name the protocols.

## Acceptance criteria (self-check before declaring done)

- [ ] `seed-data/ground-truth.json` reproduced exactly in Phase 0 (or a discrepancy reported).
- [ ] All 22,162 (chain, address) lookups — the per-chain **union** of the 21,515
      candidate-recipient and 787 deposit-beneficiary pairs, which overlap on 140 pairs and
      cover 22,106 distinct addresses — have a code verdict or appear in an explicit
      unresolved list with the reason. 21,515 + 787 = 22,302 double-counts the overlap; the
      resolver resolves each (chain, address) once, so the caches hold 22,162 entries
      (`ground-truth.json:per_chain.*.address_lookups`).
- [ ] Per-chain and total tx counts reconcile: the six disjoint `to_kind` buckets sum to
      24,067 candidate txs; nothing is lost or double-counted. `is_system` is counted
      *within* those buckets, not as a seventh one (METHOD §3).
- [ ] Every recipient marked `contract` — including ones reached only as deposit
      beneficiaries or via the control run — has a **code-time** verdict (`contract` /
      `contract-later` / `code-time-unverified`), dated at the block **before** the funding
      tx's block, and `contract-later` txs are excluded from the headline EOA→contract number
      while still being reported. `codetime/<chain>.json` must contain an entry for every
      such address, with no `retryable: true` left unexplained (a failed *call*; a canonical
      hash that is not on the L2 and a recipient with no in-window record are terminal and
      carry `retryable: false` plus a reason).
- [ ] The per-recipient dating error is **sized, not assumed**: report how many
      `contract-later` recipients have `straddles_deployment: true` and how many txs they
      account for, since a single verdict covers all of a recipient's `txs_in_window`
      (METHOD §4). Run the `--kinds eoa` control on at least one archive chain and report its
      result, including a null one (METHOD §3).
- [ ] Every contract recipient with ≥5 txs, and every family with ≥5 txs total, has an
      `actor_type` and either a protocol attribution with evidence or an explicit
      "unattributable, here is what was tried".
- [ ] Smart wallets are reported separately from protocol contracts — the headline number
      does not conflate them.
- [ ] zkcandy's unresolvable set is quantified and disclosed, not silently dropped.
- [ ] `../results/` files are byte-identical to their committed state (verify with
      `git status`); all new output is under `../results-l2/`.
- [ ] Every number in `REPORT-L2.md` is derivable from `aggregates-l2.json`; endpoints,
      substitutions, archive availability and run dates recorded in `run-manifest-l2.json`.

## Constraints

- Read-only, public endpoints only. Don't hammer free RPCs: keep the scripts' sleeps, ≤4
  chains in parallel.
- Never assume "no code" from a failed RPC call. Failure ≠ EOA.
- Do not trust labels from memory: verify on-chain or against one independent public
  source, and mark anything unverified as such.
- If a source contradicts this package, trust the live chain and note the discrepancy.
