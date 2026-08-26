# OUTPUT SPEC — exact deliverable formats

Produce a **new** results folder (never write inside `../results/`):

```
results-l2/
  code/<chain>.json          # address -> code verdict (resolver cache, resumable)
  codetime/<chain>.json      # address -> "did it have code at tx time" verdict
  recipients/<chain>.jsonl   # one row per distinct L2 recipient (the analytical unit)
  txs/<chain>.jsonl          # one row per candidate tx (joins back to the census)
  families.json              # bytecode family -> members, tx counts, attribution
  aggregates-l2.json         # every number the report cites
  REPORT-L2.md               # the human-readable deliverable
  run-manifest-l2.json       # reproducibility record
  scripts/                   # any scripts you write beyond the two provided
```

## 1. `code/<chain>.json` — resolver cache (written by `resolve_l2_code.py`)

```jsonc
{ "0x…": { "len": 1632, "kind": "eoa|contract|delegated-eoa",
           "codehash": "<sha256 of lowercased code hex>|null", "block": "0x4d6a410" } }
```

`codehash` is sha256 over the code hex string **lowercased first** — a **clustering key
only**, not the EVM keccak codehash. Label it that way anywhere it is published.

`block` is the block the whole file was resolved at, always a **concrete block number** —
never the literal `"latest"`. `--block latest` is resolved through `eth_blockNumber` before
the first write, because a file full of `"latest"` cannot be checked for consistency: era's
sweep is hundreds of batches, and a run resumed the next day would merge two chain tips while
the guard compared `"latest"` to `"latest"`. One file = one block; the resolver refuses to
mix, a resumed run adopts the block already in the cache, and a historical run needs its own
`--out` (e.g. `code/<chain>@0x34ad51.json`).

## 2. `codetime/<chain>.json` — code-time verdicts (written by `check_code_time.py`)

```jsonc
{ "0x…": { "source": "candidate|deposit-beneficiary|null",
           "earliest_tx_id": 5235, "ts": 1783080179,
           "txs_in_window": 1, "last_tx_id": 5235,
           "l2_block": "0x34ad52", "probe_block": "0x34ad51",
           "code_at_tx": "contract|eoa|delegated-eoa|unavailable",
           "len_at_tx": 224,
           "code_at_last_tx": null, "straddles_deployment": null,
           "detail": null, "retryable": false } }
```

Every key is always present. `len_at_tx` is `null` whenever `code_at_tx = "unavailable"`;
`detail` carries the reason. **Every address the code cache marks `contract` gets an entry**,
including ones with no matching in-window record (those get `unavailable`, `retryable:false`,
and a `detail` saying so) — silence would be indistinguishable from "already verified".

`probe_block` is `l2_block − 1`, because `getCode(N)` is end-of-block-N state (METHOD §4).

`txs_in_window` is how many txs this **single** verdict covers — only the earliest tx is
dated. When `code_at_tx = "eoa"` and the recipient received more than once, the last in-window
tx is dated too: `code_at_last_tx` is that verdict and `straddles_deployment` says whether
code had appeared by then. `straddles_deployment: false`, or `txs_in_window: 1`, means the
verdict is exact for every tx; `true` means the recipient's txs are split by the deployment
and the headline must report that population rather than absorbing it silently (METHOD §4).
Both are `null` when the probe did not apply or did not answer.

`retryable: true` marks a failed **call**, not a verdict — a non-archive endpoint, a pruned
block, a transient miss. The script re-attempts those on the next run so
`--rpc <archive endpoint>` does real work; do not read them as results. Two `unavailable`
causes are *terminal* and carry `retryable: false`: no in-window record, and a canonical hash
the L2 does not know (the tx never executed there, or the endpoint does not index it). A
better endpoint cannot fix either, and marking them retryable would leave entries that can
never be cleared.

Taxonomy mapping (METHOD §3): `code_at_tx = "contract"` ⇒ `to_kind = contract`;
`"eoa"` ⇒ `contract-later`; `"delegated-eoa"` ⇒ `delegated-eoa`; `"unavailable"` ⇒
`code-time-unverified` once the explorer fallback has also failed.

## 3. `recipients/<chain>.jsonl` — one JSON object per distinct L2 recipient

| Field | Type | Meaning |
|---|---|---|
| `chain`, `address` | str | join key |
| `txs` | int | candidate txs received (`class ∈ CLASSES`) |
| `txs_value_gt0` | int | of those, how many carried value > 0 |
| `value_total` | str | summed value in the chain's **base token** wei, as a decimal string (never cross-chain) |
| `first_seen`, `last_seen` | date | from record `ts` |
| `selectors` | obj | `{selector: count}` — non-empty only for `other`-class records |
| `to_kind` | enum | `eoa` \| `contract` \| `contract-later` \| `delegated-eoa` \| `unresolvable` \| `code-time-unverified` — six **disjoint** values, exactly one per recipient |
| `is_system` | bool | reserved ZK-stack address (METHOD §3). Orthogonal to `to_kind`, **not** a value of it: `0x0` on zero is `contract` **and** `is_system`. Excluded from every protocol claim |
| `code_len`, `codehash` | int/str\|null | from the resolver |
| `family` | str\|null | `codehash` of the bytecode family, null for EOAs |
| `erc1967_impl` | addr\|null | implementation behind a proxy, if any |
| `actor_type` | enum\|null | `smart-wallet` \| `protocol-contract` \| `token` \| `unknown-contract` (null for non-contracts) |
| `protocol` | str\|null | attributed protocol name |
| `confidence` | enum\|null | `high` \| `medium` \| `low` |
| `evidence` | str[] | at least one entry whenever `protocol` is set |
| `also_on_chains` | str[] | other chains where this same address received candidate txs |
| `is_own_l1_initiator` | bool | the address also appears as `l1_from` on this chain (self-funding) |

Deposit beneficiaries (secondary set) go in the same file with `source: "deposit-beneficiary"`
and `txs` counting deposits rather than candidates — or in a parallel
`recipients-deposits/<chain>.jsonl`. Either way the two sets must be **separable**, so the
headline candidate numbers are never inflated by deposits.

## 4. `txs/<chain>.jsonl` — per-tx augmentation (joins to `../results/enriched/`)

One object per candidate tx: `{chain, tx_id, to, class, selector, value, ts, to_kind,
is_system, family, actor_type, protocol}`. This is the file that lets anyone re-derive every aggregate,
and it is what a future phase would merge back into `enriched/`. Do not restate the census
fields beyond those listed.

## 5. `families.json`

```jsonc
{
  "families": [
    { "codehash": "fbd752b5…", "code_len": 1632,
      "chains": ["abstract"],
      "members": ["0xf175e01a…", "0xa74c14b8…", "0xa592221a…"],
      "member_count": 3, "tx_count": 316,
      "erc1967_impl": "0xaa3633b4…",
      "actor_type": "smart-wallet", "protocol": "…", "confidence": "high",
      "evidence": ["verified source of implementation on abscan", "docs url"] }
  ]
}
```

## 6. `aggregates-l2.json`

```jsonc
{
  "run": { "window": {"from": "2025-08-26", "to": "2026-08-26"}, "generated": "…",
           "chains": [...], "classes": ["direct-transfer","other"],
           "source_dataset": "results/ (45,711 records, run 2026-08-25)" },
  "totals": {
    "candidate_txs": 24067,
    // Three different quantities — carry each under its own name (METHOD §6.10).
    "distinct_recipients_per_chain_sum": 21515,   // the (chain,recipient) pair count
    "distinct_recipients_global": 21480,          // distinct addresses; 31 are on >=2 chains
    "address_lookups_total": 22162,               // getCode workload: per-chain UNION of
                                                  // recipients and deposit beneficiaries.
                                                  // NOT 21515+787 — those overlap on 140 pairs
    "deposit_records_not_decoded": 140,           // v26 selector; out of scope, still reported
    "by_to_kind": { "eoa": 0, "contract": 0, "contract-later": 0, "delegated-eoa": 0,
                    "unresolvable": 0, "code-time-unverified": 0 },   // disjoint, sums to the total
    "txs_by_to_kind": { "…": 0 },
    "system": { "recipients": 0, "txs": 0, "by_to_kind": {"…": 0} },  // orthogonal flag, NOT a 7th bucket
    "eoa_to_contract_txs": 0,              // headline: code-time-verified contracts, is_system excluded
    "eoa_to_contract_recipients": 0,
    // One dated verdict covers all of a recipient's txs; this sizes the error (METHOD §4).
    "contract_later": { "recipients": 0, "txs": 0,
                        "straddling_recipients": 0, "straddling_txs": 0,
                        "single_tx_recipients": 0 },
    "eoa_control": { "sampled": 0, "codeless_at_tx_time": 0, "had_code_at_tx_time": 0 },
    "by_actor_type": { "smart-wallet": {"txs":0,"recipients":0}, "protocol-contract": {"txs":0,"recipients":0},
                       "token": {"txs":0,"recipients":0}, "unknown-contract": {"txs":0,"recipients":0} },
    "reconciliation": "sum(txs_by_to_kind) == candidate_txs; sum(by_to_kind) == distinct_recipients_per_chain_sum"
  },
  "chains": {
    "<chain>": {
      "chain_id": 324,
      "candidate_txs": 0, "distinct_recipients": 0,
      "by_to_kind": {...}, "txs_by_to_kind": {...}, "by_actor_type": {...},
      "recurrence": { "1": 0, "2-4": 0, "5-9": 0, "ge10": 0, "max_txs_to_one_recipient": 0 },
      "top_recipients": [ {"address":"0x…","txs":0,"to_kind":"…","actor_type":"…","protocol":"…|null"} ],
      "protocols": [ {"name":"…","category":"bridge|messaging|defi|governance|infra|token|other",
                      "confidence":"high|medium|low","recipient_addresses":["0x…"],
                      "txs":0,"unique_senders":0,"first_seen":"…","last_seen":"…","evidence":["…"]} ],
      "other_class_groups": [ {"to":"0x…","selector":"0x…","signature":"…|unknown","count":0} ],
      "deposit_beneficiaries": { "distinct": 0, "by_to_kind": {...}, "by_actor_type": {...} },
      "unresolved": { "recipients": 0, "txs": 0, "reason": "rpc dead|endpoint refused|…" },
      "endpoint": "https://…", "chain_id_verified": 324, "archive_getcode": true
    }
  },
  "cross_chain": {
    // 31 candidate recipients and 11 deposit beneficiaries are on >=2 chains — enumerate all
    "recipients_multi_chain": [ {"address":"0x…","chains":["era","abstract"],"txs":0} ],
    "deposit_beneficiaries_multi_chain": [ {"address":"0x…","chains":["…"]} ],
    "families_multi_chain": [ {"codehash":"…","chains":["…"],"tx_count":0,"protocol":"…|null"} ]
  }
}
```

## 7. `REPORT-L2.md` structure (the primary deliverable)

1. **Executive summary** — the headline in the first two sentences: of 24,067 EOA-origin
   L1→L2 txs, N paid a contract on L2 (code verified at tx time), of which N were the
   sender's own smart wallet and N a real protocol; name the protocols. State the
   unresolved denominators (zkcandy) up front, not in a footnote.
2. **Method & coverage** — what was resolved, on which endpoints, archive availability per
   chain, how code-time was proven, and exactly what could not be resolved and why.
3. **The recipient landscape** — recurrence distribution (the one-shot skew), the
   `to_kind` table per chain, and the smart-wallet vs protocol split with the reasoning for
   the distinction.
4. **Bytecode families** — table of families with member counts, tx counts, implementation
   addresses, attribution and evidence. This is where the abstract clone family lands.
5. **Per-chain sections** — all 8 chains present even when near-empty (cronos/openzk/sophon
   have ≤2 candidates; say so rather than omitting them). Include each chain's top
   recipients and any protocol found.
6. **Users driving L2 contracts from L1** — the **4** `other`-class records that actually
   carry calldata, with resolved selectors and targets; small but the qualitatively distinct
   usage. Account for the other 11 `other` records in the same section as zero-value pings
   (5 of them at `0x0`) so the class still reconciles to 15.
7. **Cross-chain patterns** — addresses and families spanning chains; the self-funding
   pattern.
8. **What this changes about the parent census** — explicit: which slice of its "~59% plain
   user activity" is really user→contract, whether any recipient belongs to a protocol the
   census attributed only from the sender side, and any correction to its numbers.
9. **Caveats** — base-token value semantics, latest-vs-tx-time code, counterfactual wallet
   deployment, unresolvable zkcandy, confidence semantics. Also state the two error terms the
   pipeline does not remove: one code-time verdict covers all of a recipient's txs (sized by
   `contract_later.straddling_*`), and the `eoa` bucket is a latest-block verdict that only the
   `--kinds eoa` control samples (METHOD §3, §4).
10. **Appendix** — merged address→label registry (extend `../results/scripts/labels.json`,
    do not overwrite it), and pointers to the data files.

Rules: every number in `REPORT-L2.md` must be derivable from `aggregates-l2.json`; every
protocol row cites at least one piece of evidence; unverified labels marked as such;
absence of evidence stated explicitly ("no protocol recipients found on chain X" is a
result, not an omission).

## 8. `run-manifest-l2.json`

Parameters (`CHAINS`, `CLASSES`, `RECUR_MIN`), script versions/hashes, endpoints actually
used per chain incl. substitutions **with the `eth_chainId` each one returned**,
archive-capability probe results, the block each code cache was resolved at, start/end times,
approximate RPC call counts, and any deviation from this package with its justification —
including every use of `--no-chain-check` or `--allow-input-name-mismatch`.
