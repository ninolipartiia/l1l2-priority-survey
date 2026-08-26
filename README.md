# L1→L2 Priority-Transaction Census — Input Package

This folder is the **complete, self-contained input** for an autonomous agent to perform
the following research end-to-end:

> For each ZKsync-stack chain in `CHAINS`, over timeline `T`, enumerate **every L1→L2
> transaction** (priority transactions), analyze `from`/`to`, count and evaluate the users,
> find patterns — especially bridges and cross-chain protocols — and document precisely,
> per chain, which protocols use L1→L2 messaging and exactly which addresses/contracts
> each protocol uses.

Everything in this package was **live-verified on 2026-08-25** against public RPCs
(see `VALIDATION_LOG.md`). The scanning method was proven end-to-end on all 8 chains.

## Scope decision (already made — do not re-litigate)

- **Direction: L1 → L2 only.** L2→L1 (withdrawals/messenger) is out of scope.
- On ZK-stack chains **every** L1→L2 transaction is a *priority transaction*
  (L2 tx type `0xff`), including canonical bridge deposits. The dataset is therefore the
  complete priority-tx set, and the analysis **separates plain deposits from protocol
  traffic by classification** (see `METHOD.md` §5). Plain deposits are counted as a
  baseline; the research focus is the non-deposit protocol traffic, plus protocols that
  are visible *through* deposits (contracts programmatically depositing via the canonical
  bridge, revealed by the L1 initiator field).

## Parameters (provided at run time)

| Param | Meaning | Default |
|---|---|---|
| `CHAINS` | subset of `era, abstract, sophon, lens, cronos, zero, zkcandy, openzk` | all 8 |
| `T` | analysis window (UTC dates) | 1 year ending on the run date |

## File map

| File | Contents |
|---|---|
| `TASK.md` | The mission: objective, phases, deliverables, acceptance criteria |
| `CHAINS.md` | Verified per-chain connection details, scale stats, caveats |
| `METHOD.md` | The analysis logic: data source, decoding, classification, completeness checks, pitfalls |
| `OUTPUT_SPEC.md` | Exact output formats (JSONL/JSON schemas, report structure) |
| `KNOWN_ADDRESSES.md` | Verified seed labels: system contracts, bridges, first protocol finds |
| `VALIDATION_LOG.md` | What was verified on 2026-08-25 and how |
| `scripts/scan_priority.py` | **Tested** reference scanner (python3 + curl only) |
| `seed-data/example-lens-2026-08-23_25.jsonl` | Real scanner output (Lens, 2 days, 19 records) |
| `seed-data/perchain-l1-event-samples.json` | One decoded live event + L2 lookup per chain |

## Follow-up phase (separate package)

`phase6-l2-recipients/` is a self-contained input package for the **L2-side recipient
census**: this census classifies every tx on the sender axis only and never resolves what
the L2 `to` address is, so "an EOA sent value to a contract on L2" is not counted anywhere.
That package closes the gap over the completed `results/` dataset. Start with its
`README.md`; it treats `results/` as read-only input.

## Quickstart (sanity check before the real run)

```bash
# ~1 minute; expect ~19 records, all Across Protocol relayRootBundle
python3 scripts/scan_priority.py --chain lens --from 2026-08-23 --to 2026-08-25 --out /tmp/lens.jsonl
```

Then read `TASK.md` and execute the phases in order.

## Environment assumptions

- `python3` and `curl` available (no third-party Python packages required; `jq`/`cast`
  are NOT assumed). Internet access to public RPCs and the web (for protocol attribution).
- All chain data is read via **free public endpoints** — no API keys required. Respect
  rate limits (the scanner already does backoff/rotation/checkpointing).

## Urgency note

**Sophon is winding down** (shutdown announced 2026-06-25; deposits already blocked;
chain promised live only through ~end of 2026). Scan Sophon first — its RPC may not
exist forever. Its L1 event history on Ethereum is permanent, but L2-side verification
needs the live RPC.
