# METHOD — how to enumerate, decode, classify and verify L1→L2 traffic

## 1. Background: how L1→L2 works on ZK-stack chains

- A user or contract on Ethereum L1 requests an L2 transaction through the shared
  **Bridgehub** (`requestL2TransactionDirect` / `requestL2TransactionTwoBridges`), which
  routes to the target chain's **diamond proxy** (Mailbox facet) on L1.
- The mailbox enqueues a **priority operation** and emits
  **`NewPriorityRequest(uint256 txId, bytes32 txHash, uint64 expirationTimestamp, L2CanonicalTransaction transaction, bytes[] factoryDeps)`**.
- The sequencer must execute every priority op on the L2, where it appears as a
  transaction with **type `0xff` (255)** and hash exactly equal to the event's
  `txHash` (the "canonical hash"). This is verified working on all 8 chains.
- `txId` is **sequential per chain** (0,1,2,…). This gives a built-in completeness proof.
- **Address aliasing**: when the L1 sender is a *contract*, its address on L2 is
  `L1_address + 0x1111000000000000000000000000000000001111` (mod 2^160). EOAs are not
  aliased. To recover the true L1 contract, subtract the offset.
  Verified example: Across HubPool `0xc186fa914353c44b2e33ebe05f21846f1048beda` appears
  as inner `from` = `0xd297fa914353c44b2e33ebe05f21846f1048cfeb`.
- Canonical **bridge deposits are themselves priority txs**: the L1AssetRouter (or the
  chain's legacy bridge) is the L1 sender, so the inner `from` is its aliased address and
  the inner `to` is the L2 asset router. The end user is visible in (a) the L1 initiator
  of the enqueueing tx and (b) the finalizeDeposit calldata.
- Protocol upgrade txs (type `0xfe`/254) do NOT appear in `NewPriorityRequest` — every
  event decodes to `tx_type = 255` (verified). No filtering needed.
- `value` and fee fields are denominated in the chain's **base token**
  (ETH on era/abstract/zero/zkcandy; SOPH, GHO, zkCRO, ozETH elsewhere — see `CHAINS.md`).

## 2. Primary data source: L1 event scan

Scan `eth_getLogs` on Ethereum for each chain's diamond proxy with

```
topic0 = 0x4531cd5795773d7101c17bdeb9f5ab7f47d7056017506f937083be5d6e77a382   # NewPriorityRequest
address = <diamond proxy from CHAINS.md>
```

in ≤10,000-block chunks. This is complete (every L1→L2 tx passes the mailbox), cheap
(~263 requests per chain-year), and independent of L2 RPC health. The reference
implementation is `scripts/scan_priority.py` — **tested; use it** (or port it faithfully).

### Event data layout (non-indexed, ABI-encoded; word = 32 bytes)

```
word 0: txId                      word 3: offset of transaction struct
word 1: txHash (canonical hash)   word 4: offset of factoryDeps
word 2: expirationTimestamp
struct L2CanonicalTransaction (19 head words at its offset):
  0 txType  1 from  2 to  3 gasLimit  4 gasPerPubdataByteLimit  5 maxFeePerGas
  6 maxPriorityFeePerGas  7 paymaster  8 nonce  9 value  10..13 reserved[4]
  14 off(data)  15 off(signature)  16 off(factoryDeps)  17 off(paymasterInput)
  18 off(reservedDynamic)          # dynamic offsets relative to struct start
```

`data` (the L2 calldata) is what the L2 target gets called with — the key classification
signal. `reserved[0]` typically carries the total base-token amount locked on L1
(value + fees); `reserved[1]` the refund recipient (observed; treat interpretations as
heuristics, confirm against era-contracts source if it matters).

## 3. Window → block range

Binary-search Ethereum block numbers from the UTC window bounds via
`eth_getBlockByNumber` timestamps (~25 calls per bound; implemented in the script).

## 4. L1 initiator resolution

For every event, fetch the enqueueing L1 tx (`eth_getTransactionByHash`, batched 50/req)
and record `l1_from` (the true initiating EOA/contract) and `l1_to` (usually Bridgehub;
often a router/multicall — e.g. Across's dataworker EOA goes through Multicall3
`0xca11bde05977b3631167028862be2a173976ca11`). To distinguish EOA vs contract initiators,
`eth_getCode(l1_from)` (batch; "0x" = EOA — note: contracts deployed after the window
still show code, and EIP-7702-delegated EOAs show a delegation designator as code;
the `inner_from == l1_from` rule in §5 is the authoritative aliasing test, while this
getCode split is an approximation — say so in the report).

## 5. Classification taxonomy (apply in order; record the class per record)

1. **`canonical-deposit`** — inner `from` = aliased L1AssetRouter
   (`0x993aad80e425c646dab305381ff105169feedf67`) or aliased legacy Era bridge; inner
   `to` = L2AssetRouter `0x…10003` or Era legacy L2 bridge. Selector observed live:
   `0xcfe7af7c` = `finalizeDeposit(address,address,address,uint256,bytes)` (legacy ABI;
   newer asset-router variants exist — collect all selectors seen at `to = 0x…10003`).
   The *user* is `l1_from` of the enqueueing tx (and/or the receiver inside calldata —
   decode when needed). Sub-flag `deposit-by-contract` when `l1_from` has code → these
   surface protocols using the canonical bridge programmatically (analyze them in Phase 4).
2. **`direct-transfer`** — empty calldata (`data_len` < 4), inner `from` unaliased EOA
   (== `l1_from`), value > 0. Plain base-token movement (often `from == to`). Baseline
   user activity; count, don't attribute.
3. **`protocol-message`** — the inner `from` is an *aliased contract*
   (`inner_from != l1_from`, see notes below) other than the canonical bridge.
   Contract-sent cross-chain messages: the primary research target.
   Group by `(unalias(from), to, selector)`.
4. **`other`** — anything left; chiefly EOA-sent calls **with** calldata (users invoking
   L2 contracts directly from L1). Attribute the `to` contract in Phase 4 just like
   protocol messages, but keep the class distinct so contract-driven messaging is not
   conflated with user-driven calls.

Notes:
- Deciding "was inner `from` aliased?" — you cannot tell from the address alone.
  Rule: if `inner_from == l1_from` → EOA, not aliased. Else if
  `inner_from == alias(l1_from)` → direct contract call via its own address. Else the
  sender is a contract *called by* `l1_from` (e.g. HubPool called by dataworker via
  Multicall3) — unalias and attribute the contract.
- Gateway-period records recovered from the L2 side (§7.3) have no `l1_from`, so the
  rule above cannot run. Fallback aliasing test against Ethereum: if
  `eth_getCode(unalias(inner_from))` is non-empty and `eth_getCode(inner_from)` is
  empty → aliased contract sender (attribute `unalias(inner_from)`); if neither has
  code → treat as EOA; if both have code → mark ambiguous and resolve manually.
- The same protocol deploys identical contracts across chains — compare `to` bytecode
  (`eth_getCode` on the L2s) to propagate an attribution made on one chain to others.

## 6. User evaluation metrics (per chain, and cross-chain)

- Totals: priority-tx count, per class; unique `l1_from`; unique inner senders.
- Distribution: top-20 initiators with counts and share; share of top-1/top-10;
  EOA vs contract split.
- Per protocol: tx count, share of all priority txs and of non-deposit txs, unique
  users touching it, first/last seen in window, weekly time series (spot regime changes,
  e.g. Sophon deposits dying on 2026-06-25).
- Cross-chain: initiators and protocols active on ≥2 chains (join on unaliased L1
  address — the L1 side is the natural join key).

## 7. Completeness & correctness verification (mandatory)

1. **txId continuity**: within the window, collected txIds must be gap-free and
   consecutive. Derive this from the JSONL file itself, after deduping on `tx_id`
   (a crash between data flush and checkpoint write can leave duplicates; the scanner
   skips them on resume, but dedupe defensively before any counting). The scanner's
   end-of-run summary reads the file back — but the JSONL is the source of truth;
   never rely on a mid-run console line.
2. **Boundary check**: `max(txId) + 1 ≤ getTotalPriorityTxs()` (diamond, selector
   `0xa1954fc5`); for a window ending "now" they should be ≈ equal.
3. **Gateway-period gaps**: if txIds jump inside the window, the chain settled via
   ZK Gateway (chainId 9075, RPC dead) during that period, and those events were
   emitted there, not on Ethereum. Recovery, in order of preference:
   a. Bound the gap window by the ETH timestamps of the last event before / first
      event after the gap.
   b. Recover from the **L2 side**: binary-search the chain's L2 blocks to the gap
      window, then walk blocks (`eth_getBlockByNumber` with full txs) collecting
      type-`0xff` txs. All L2 RPCs are alive and serve full history (verified).
      The number of missing ops is known exactly (gap size), so you know when to stop.
   c. If the gap is large and the L2 walk is too slow: use the chain's explorer API,
      or decode the wrapped relays from the Gateway diamond
      (`0x6e96d1172a6593d5027af3c2664c5112ca75f2b9`) `NewPriorityRequest` events on
      Ethereum — the Gateway-relayed op is inside the inner calldata (verify the exact
      wrapping against the era-contracts source, matterlabs/era-contracts on GitHub).
   L2-side records lack `l1_from`; mark them `initiator: unknown(gateway-period)`.
4. **L2 spot verification**: sample ≥10 canonical hashes per chain across the window →
   `eth_getTransactionByHash` on the L2 → expect type `0xff` and matching from/to.
   (A just-enqueued op may not be executed yet — don't sample the last few minutes.)
5. **Expected zero-activity**: Sophon after 2026-06-25 must have no events; any event
   found is a red flag for the scan or a fact worth reporting.

## 8. Operational guidance

- Rate limits are the main risk: keep the script's sleeps and backoff; scan chains
  serially or ≤4 in parallel. Full 8-chain year scan ≈ 2,100 getLogs +
  (Era-dominated) ~1–2k batched tx fetches — roughly 1–3 hours wall-clock.
- Everything is resumable (`.ckpt` sidecars). Never restart from scratch after a crash.
  Checkpoints are bound to `(chain, window)`: use one `--out` per chain per window; the
  scanner refuses mismatched, corrupt, or orphaned state. To restart deliberately,
  delete **both** the output file and its `.ckpt`.
- Every run appends an audit trail to `<out>.runlog` (start/chunk/done events, incl.
  which endpoint served each chunk and resolved block bounds). This is the execution
  record to pair with the self-authenticating data (every record is re-verifiable
  on-chain via `l1_block`/`l1_tx`/`canonical_hash`); keep it and cite it in the
  run manifest. Also capture agent stdout (`... 2>&1 | tee run.log`) on long runs.
- Raw records carry `ts` (the L1 block timestamp) from the non-standard
  `blockTimestamp` field both verified log endpoints include. If a substitute endpoint
  omits it, `ts` is null — backfill during enrichment via batched
  `eth_getBlockByNumber` (~1 call per unique block) and budget for that.
- 4byte.directory selector/event lookups: `GET https://www.4byte.directory/api/v1/signatures/?hex_signature=0x…`
  (also `/event-signatures/`). openchain.xyz is an alternative.

## 9. Known pitfalls (all hit during preparation)

- publicnode 403s python-urllib TLS — shell out to `curl` for ALL HTTP (the script does).
- drpc free tier throttles: item-level errors inside otherwise-successful batch
  responses — retry failed items individually (handled in the script).
- getLogs >10k blocks fails on both working endpoints; a busy chunk can also exceed
  response limits — the script halves the chunk on failure.
- An event's L2 execution lags enqueueing by seconds–minutes: "not found on L2" for the
  newest events is normal.
- Don't compare `value` across chains without base-token conversion.
- OpenZK's dataset (6,000 lifetime txs, ~9k blocks) fits in seconds of scanning — its
  entire history is coverable regardless of `T`.
- The scanner deliberately stops (with instructions) on mid-file JSONL corruption —
  the one non-self-healing state. If an unattended run halts, check stderr for that
  message before anything else.
