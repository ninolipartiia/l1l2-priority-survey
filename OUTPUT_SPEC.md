# OUTPUT SPEC — exact deliverable formats

Produce a results folder:

```
results/
  raw/<chain>.jsonl            # scanner output, one record per priority tx
  enriched/<chain>.jsonl       # raw + classification + attribution fields
  aggregates.json              # all numbers the report cites
  REPORT.md                    # the human-readable deliverable
  run-manifest.json            # reproducibility record
```

## 1. `raw/<chain>.jsonl` — one JSON object per priority tx (scanner output)

| Field | Type | Meaning |
|---|---|---|
| `tx_id` | int | sequential priority-op id (per chain) |
| `canonical_hash` | hex32 | == the tx hash on the L2 |
| `tx_type` | int | always 255 |
| `from` | addr | L2-side sender (aliased if L1 contract) |
| `to` | addr | L2-side target |
| `gas_limit`, `value` | int | value in base-token wei |
| `reserved` | int[4] | raw; `[0]`≈total locked, `[1]`≈refund recipient (heuristic) |
| `data_len` | int | calldata length (bytes) |
| `selector` | hex4 | first 4 bytes of calldata ("" if none) |
| `data` | hex | calldata, capped at 8 KiB (`data_truncated` flag) |
| `ts` | int\|null | L1 block timestamp (from the endpoint's `blockTimestamp` log field; null if an endpoint omits it — backfill in enrichment) |
| `l1_block`, `l1_tx`, `log_index` | — | provenance on Ethereum |
| `l1_from`, `l1_to` | addr\|null | initiator of the enqueueing L1 tx (null with `--no-initiators` or for gateway-period recoveries) |

**Dedupe raw JSONL on `tx_id` before enrichment/aggregation** — a crash-resume can
leave duplicate records.

The scanner also appends an execution-audit sidecar **`<out>.runlog`** (JSON lines:
a `start` event per run with identity and resolved ETH block bounds, a `chunk` event
per completed chunk with block range / serving endpoint / counts / wall seconds, and
a `done` event with totals, txId range, gaps). Keep the `.runlog` files next to the
raw data and reference them in `run-manifest.json` — together with the chain-
addressable records they are the execution provenance of the run.

Gateway-period records recovered from the L2 side (METHOD §7.3) join the same
`raw/<chain>.jsonl` with: `l1_block`/`l1_tx`/`log_index`/`l1_from`/`l1_to` = null,
`ts` = the **L2** block timestamp (close to, but not identical with, the L1 enqueue
time), and an extra field `source: "l2-recovery"` (L1-scanned records may omit
`source`). They count toward all totals; `completeness.gap_handling` discloses them.

## 2. `enriched/<chain>.jsonl` — raw record plus:

| Field | Type | Meaning |
|---|---|---|
| `class` | enum | `canonical-deposit` \| `direct-transfer` \| `protocol-message` \| `other` |
| `deposit_by_contract` | bool | only for canonical-deposit |
| `unaliased_from` | addr\|null | `from - 0x1111…1111` when aliasing applies, else null |
| `initiator_is_contract` | bool\|null | null when unknown (e.g. gateway-period recovery) |
| `protocol` | string\|null | attributed protocol name, null if unattributed |
| `ts` | int | L1 block timestamp — copied from raw; backfilled via `eth_getBlockByNumber` where raw is null (record the backfill in the manifest) |

## 3. `aggregates.json`

```jsonc
{
  "run": { "window": {"from": "...", "to": "..."}, "generated": "...", "chains": [...] },
  "chains": {
    "<chain>": {
      "chain_id": 324,
      "eth_blocks": [<from>, <to>],
      "totals": { "priority_txs": 0, "by_class": {"canonical-deposit":0, "...":0},
                  "unique_l1_initiators": 0, "unique_inner_senders": 0 },
      "completeness": { "tx_id_range": [a, b], "gaps": [[c,d]],
                        "gap_handling": "recovered-from-l2|documented-unrecovered|none",
                        "l2_spot_checks": {"sampled": 10, "ok": 10},
                        "boundary_check": "ok|mismatch: <detail>" },
      "protocols": [
        {
          "name": "Across Protocol",
          "category": "bridge|messaging|defi|governance|infra|other",
          "confidence": "high|medium|low",
          "tx_count": 0, "share_of_all": 0.0, "share_of_non_deposit": 0.0,
          "unique_users": 0, "first_seen": "date", "last_seen": "date",
          "weekly": [ {"week": "2025-W35", "tx_count": 0} ],  // include when the report cites trends
          "l1_addresses": [ {"address": "0x…", "role": "HubPool (message sender)"} ],
          "l2_addresses": [ {"address": "0x…", "role": "SpokePool (message target)"} ],
          "selectors": [ {"selector": "0x493a4f84", "signature": "relayRootBundle(bytes32,bytes32)", "count": 0} ],
          "evidence": ["verified source on explorer …", "bytecode match with era spokepool", "docs url"]
        }
      ],
      "deposit_initiator_contracts": [ {"address": "0x…", "label": "…", "tx_count": 0} ],
      "top_initiators": [ {"address": "0x…", "is_contract": false, "tx_count": 0, "label": "…|null"} ],
      "unattributed": { "tx_count": 0, "share_of_non_deposit": 0.0,
                        "top_groups": [ {"unaliased_from": "0x…", "to": "0x…", "selector": "0x…", "count": 0} ] }
    }
  },
  "cross_chain": {
    "protocols_multi_chain": [ {"name": "…", "chains": ["era","lens"], "l1_addresses": ["0x…"]} ],
    "initiators_multi_chain": [ {"address": "0x…", "chains": ["…"], "total_txs": 0} ]
  }
}
```

## 4. `REPORT.md` structure (the primary deliverable)

1. **Executive summary** — headline numbers; the protocol landscape in ≤10 sentences.
2. **Method & completeness** — 1 page: source, window, per-chain completeness results
   (txId ranges, gaps and their handling, spot checks), endpoint substitutions if any.
3. **Per-chain sections** (one per chain, all chains present even if near-empty):
   - Traffic overview: totals, class breakdown, weekly trend note.
   - **Protocol table** (the core ask — explicit and precise):

     | Protocol | Category | L1 address(es) + role | L2 address(es) + role | Txs | Share of non-deposit | Confidence |
     |---|---|---|---|---|---|---|

   - Notable initiators (top users, contract depositors with labels).
   - Unattributed remainder: size + top groups (address/selector) so a reader can dig.
4. **Cross-chain patterns** — protocols/users spanning chains; anything anomalous
   (e.g. OpenZK's round-number activity, Sophon's cliff on 2026-06-25).
5. **Caveats** — base-token denominations, gateway-period records without initiators,
   attribution confidence semantics.
6. **Appendix** — full address→label registry discovered during the run (merge of
   `KNOWN_ADDRESSES.md` seeds + new finds), and pointers to the raw data files.

Rules: every number in REPORT.md must be derivable from `aggregates.json`; every
protocol row must cite at least one piece of evidence; unverified labels marked "(low)".

## 5. `run-manifest.json`

Parameters (`CHAINS`, `T`), script version/hash, endpoints actually used per chain,
start/end times, total RPC calls (approximate ok), and any deviations from this package.
