# Phase 6 — L2-Side Recipient Census (input package)

This folder is the **complete, self-contained input** for an autonomous agent to perform
the follow-up research the main census could not answer:

> Of the L1→L2 priority transactions that were **originated by an EOA**, which ones
> actually deliver money/calls to a **smart contract on the L2 side** rather than to
> another EOA? Which recipients recur? And for the recurring contract recipients — do
> they belong to an identifiable protocol?

It extends the completed census in `../results/` (45,711 priority txs across 8 ZK-stack
chains, window 2025-08-26 → 2026-08-26). **That dataset is the input; it is already
verified and must not be modified.**

## Why this phase exists (the gap being closed)

The census classified every tx on the **sender axis only** — `classify()` in
`../results/scripts/enrich.py:144` reads the inner `from`, its un-aliased L1 identity,
`l1_from`, and the calldata/value flags. It never reads `to`, and no `eth_getCode` was
ever issued against an L2 RPC (all 21,135 cached code lookups were on Ethereum L1).

Consequence: the 24,052 `direct-transfer` records are defined purely as "an EOA sent
base-token with empty calldata". Whether the money landed on a plain EOA, a
smart-contract wallet, or a protocol contract is **not recorded anywhere**. This package
resolves that axis and mines it for patterns.

## Scope decisions (already made — do not re-litigate)

- **Candidate set = EOA-origin txs**: records with `class ∈ {direct-transfer, other}` —
  **24,067 txs** over **21,515 (chain, recipient) pairs = 21,480 distinct addresses**, 31 of
  which receive on more than one chain. These are the only records where the *originator* is
  a user rather than a contract, so they are the only ones where "EOA → contract" is a
  meaningful question. Code status is per-chain, so 21,515 is the amount of *work*; 21,480 is
  the *population* — INPUTS §3 has the full table, and conflating the two is METHOD §6
  pitfall 10. Together with the deposit beneficiaries below, the `getCode` workload is
  **22,162 lookups** (a per-chain union, not 21,515 + 787 — the two sets overlap on 140 pairs).
- **Secondary set = canonical-deposit beneficiaries**: the deposits' inner `to` is always
  the L2AssetRouter (verified: all 3,064 target `0x…10003`), so the real recipient must be
  decoded from `finalizeDeposit` calldata — **787 (chain, beneficiary) pairs = 775 distinct
  addresses**, 149 of which are also candidate recipients. An EOA depositing a token *into a
  protocol contract* belongs to this phase's question and is invisible without the decode.
- **`protocol-message` (18,580 txs) is out of scope as a finding** — its sender is already
  a contract and Phase 4 attributed it. Resolve its recipients anyway as a **control**
  (they should be overwhelmingly contracts; if not, something is wrong with the method).
- **Direction stays L1 → L2.** No L2→L1, no L2-internal traffic.
- **Do not mutate `../results/`.** New outputs go to `../results-l2/` and join back on
  `(chain, tx_id)`.

## File map

| File | Contents |
|---|---|
| `TASK.md` | The mission: objective, phases, acceptance criteria, constraints |
| `METHOD.md` | Analysis logic: recipient taxonomy, code-time proof, clone clustering, attribution, pitfalls |
| `OUTPUT_SPEC.md` | Exact output formats (JSON/JSONL schemas, report structure) |
| `INPUTS.md` | The existing dataset, verified endpoint status, workload sizing |
| `scripts/resolve_l2_code.py` | **Tested** batched-`eth_getCode` resolver (resumable cache) |
| `scripts/check_code_time.py` | **Tested** "did it have code when the tx arrived?" verifier |
| `seed-data/ground-truth.json` | Per-chain candidate/recipient/recurrence counts — reproduce these first |
| `seed-data/probe-samples.json` | Live-verified probe results incl. the abstract clone family |

Inherited from the parent package and still authoritative: `../CHAINS.md` (chain ids,
RPCs, diamond proxies, explorers), `../KNOWN_ADDRESSES.md` and
`../results/scripts/labels.json` (57 seed labels), `../METHOD.md` §5 (the sender-side
taxonomy this phase extends), `../OUTPUT_SPEC.md` (record field meanings).

## Quickstart (sanity check before the real run)

```bash
cd scripts
# ~10 seconds; expect "resolved 4/4  kinds={'eoa': 4}"
# (4, not 2+3: lens's 2 recipients and 3 deposit beneficiaries overlap on one address)
python3 resolve_l2_code.py --chain lens --in ../../results/enriched/lens.jsonl \
        --out /tmp/lens-code.json --deposit-beneficiaries

# seconds; expect "resolved 257/257  kinds={'eoa': 256, 'contract': 1}"
# (the single contract is address 0x0 — see METHOD §6 pitfall 4)
python3 resolve_l2_code.py --chain zero --in ../../results/enriched/zero.jsonl \
        --out /tmp/zero-code.json

# expect "code_at_tx tally = {'contract': 1}", l2_block 0x34ad52, probe_block 0x34ad51
python3 check_code_time.py --chain zero --in ../../results/enriched/zero.jsonl \
        --code /tmp/zero-code.json --out /tmp/zero-codetime.json
```

Both scripts print the concrete block they resolved at (`--block latest resolved to 0x…`) and
every per-chain filename they read or write — `--in`, `--out`, and `--code` — must name
`--chain`, so `/tmp/zero-code.json` is fine but `/tmp/era.json` with `--chain zero` aborts.
`--out` is checked too, not just the inputs: the read-side guards trust filenames to be
truthful, so zero's verdicts written to `era.json` would later satisfy the `--code` check on
an era run. Pass `--allow-input-name-mismatch` if you renamed the files deliberately.

Then read `INPUTS.md` (what you are starting from), then `TASK.md`, and execute the
phases in order.

## Environment assumptions

- `python3` + `curl` only; no third-party packages, no API keys. Internet access to the
  public L2 RPCs, block explorers, and the web (for protocol attribution).
- Both scripts checkpoint through a temp file and an atomic rename, and skip addresses that
  already have a verdict, so Ctrl-C mid-write cannot corrupt the cache and a re-run resumes.
  Cached *failed calls* are the exception: `check_code_time.py` marks them `retryable` and
  tries them again, so re-running with `--rpc <archive endpoint>` does real work. Outcomes a
  better endpoint cannot change (a canonical hash the L2 does not know, a recipient with no
  in-window record) are terminal instead, so no entry stays retryable forever.
- Both scripts refuse to run unless the endpoint's `eth_chainId` matches `../CHAINS.md` for
  `--chain` and every per-chain file (`--in`, and `--code` for the verifier) names that same
  chain. Cross-chain contamination otherwise produces output that looks entirely plausible
  (METHOD §6 pitfall 2) — an era code cache probed against zero's RPC would read as a whole
  chain of "deployed later" verdicts.
- A missing result is never a verdict: a `{"result": null}` reply raises rather than becoming
  `eoa`, an unknown `--classes` value aborts rather than selecting nothing, and a required
  input path that does not exist aborts rather than reading as empty. Silent success on a typo
  is the failure mode this package is most exposed to.

## Urgency / risk notes

- **zkcandy's RPC is dead** (`https://rpc.zkcandy.io`, no response as of 2026-08-26; its
  explorer is down too). Its 1,396 candidate txs / 1,251 distinct recipients are
  **unresolvable with free endpoints** — see METHOD §6 pitfall 3. Declare, don't guess. The
  resolver aborts on zkcandy at the `eth_chainId` check rather than spending hours on serial
  retries; find a replacement endpoint and pass `--rpc`, or report the chain as unresolvable.
  If an endpoint dies *mid-sweep*, the abort takes about a minute at the defaults (three dead
  batches, each costing one batch attempt plus one single-address probe).
- **Sophon is winding down** (last priority tx 2026-07-03; chain promised live only to
  ~end of 2026). Its RPC still answered on 2026-08-26 — resolve sophon early.
- The main **correctness trap** is counterfactual wallet deployment: ZK-stack smart
  accounts are routinely funded *before* they are deployed, so `eth_getCode(…, "latest")`
  over-counts "EOA → contract". `check_code_time.py` exists precisely for this.
