# TASK — L1→L2 Priority-Transaction Census across ZKsync-stack chains

## Objective

For each chain in `CHAINS`, over window `T`:

1. Enumerate **every L1→L2 priority transaction** (complete set, provably — see
   completeness checks in `METHOD.md` §7).
2. For each transaction capture: inner `from` / `to` (the L2-side sender/target),
   value, calldata selector, and the **L1 initiator** (`from`/`to` of the Ethereum
   transaction that enqueued it).
3. Count and evaluate the users: unique initiators, EOA vs contract, activity
   distribution, cross-chain overlap.
4. Find patterns and attribute them: which **bridges and protocols** use L1→L2
   messaging on each chain.
5. Produce the deliverables in `OUTPUT_SPEC.md`, precisely and explicitly:
   **for each chain, the list of protocols using L1→L2; for each protocol, the exact
   addresses/contracts involved** (both L1 and L2 side), with evidence.

## Parameters

- `CHAINS` ⊆ {era, abstract, sophon, lens, cronos, zero, zkcandy, openzk} — default: all.
- `T` — UTC date window; default: 1 year ending on the run date.

## Phases

### Phase 0 — Preflight (fast)
- Re-verify each chain's RPC (`eth_chainId`) and the Ethereum log endpoints against
  `CHAINS.md`. If an endpoint is dead, find a replacement (chainlist.org,
  chain's own docs) and **record the substitution** in the final report.
- Run the quickstart from `README.md`.

### Phase 1 — Scan (mechanical, resumable)
- For each chain run `scripts/scan_priority.py --chain <c> --from <T0> --to <T1>`.
  Scan **Sophon first** (wind-down risk). Era is the largest (~50–100k events/yr
  expected; everything else is thousands). Store raw JSONL per chain.
- Use one `--out` per (chain, window) — checkpoints are identity-bound and the scanner
  refuses mismatches; to restart deliberately, delete both the output and its `.ckpt`.
- Derive the per-chain txId range/gap report from the JSONL files themselves (dedupe on
  `tx_id` first). The scanner's final summary also reads the file back, but the JSONL
  is the source of truth.

### Phase 2 — Completeness verification
- Apply `METHOD.md` §7: txId continuity, boundary check vs `getTotalPriorityTxs()`,
  L2 spot-verification of ≥10 sampled canonical hashes per chain (expect type `0xff`).
- If txId gaps exist inside the window (likely for chains that settled via the
  now-deprecated ZK Gateway before ~Q1 2026): recover the missing range from the L2
  side per `METHOD.md` §7.3, or explicitly document the gap size and period if
  recovery is impossible. **Never silently ignore a gap.**

### Phase 3 — Classification (mechanical)
- Classify every record per the taxonomy in `METHOD.md` §5 into:
  `canonical-deposit`, `direct-transfer`, `protocol-message`, `other`.
- Group non-deposit traffic by `(unaliased inner from, inner to, selector)`.

### Phase 4 — Attribution (research)
- For each group, identify the protocol: seed labels in `KNOWN_ADDRESSES.md`,
  contract names on explorers, verified source code, selector databases
  (4byte.directory / openchain.xyz), bytecode equality across chains, protocol docs,
  web search. Assign a confidence level (high/medium/low) and keep the evidence.
- Also attribute the **L1 initiators of canonical deposits** that are contracts —
  this surfaces protocols that rebalance through the canonical bridge.

### Phase 5 — Analysis & report
- User metrics per `METHOD.md` §6, aggregates and `REPORT.md` per `OUTPUT_SPEC.md`.

## Acceptance criteria (self-check before declaring done)

- [ ] Every chain in `CHAINS` scanned over the full window `T`, raw JSONL saved.
- [ ] Completeness checks executed per chain and their results stated in the report
      (including "no gaps" statements — absence of evidence must be explicit).
- [ ] Every priority tx classified; class totals per chain sum to the scan total.
- [ ] Each attributed protocol lists concrete L1 and L2 addresses with roles and
      evidence; confidence stated.
- [ ] Unattributed non-deposit traffic is quantified and its top groups shown —
      not hidden.
- [ ] Report reproducible: parameters, endpoints used (incl. substitutions), run
      dates, and script version recorded.
- [ ] Numbers are consistent between JSON aggregates and the markdown report.

## Constraints

- Read-only, public endpoints only. Politeness: keep the scanner's built-in sleeps;
  do not hammer free RPCs in parallel loops beyond ~4 concurrent chains.
- Do not trust labels from memory: verify addresses on-chain or via at least one
  independent public source; mark anything unverified as such.
- If a data source contradicts this package (addresses, endpoints), trust the live
  chain, note the discrepancy in the report.
