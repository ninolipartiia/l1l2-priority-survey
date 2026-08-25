# VALIDATION LOG — what was verified, 2026-08-25

All checks performed live from this machine via `curl` against free public endpoints.

## 1. L2 RPC liveness + chain IDs (`eth_chainId`, `eth_blockNumber`)

| Chain | RPC | chainId | Latest L2 block |
|---|---|---|---|
| era | mainnet.era.zksync.io | 324 ✅ | 71,712,802 |
| abstract | api.mainnet.abs.xyz | 2741 ✅ | 80,901,002 |
| sophon | rpc.sophon.xyz | 50104 ✅ | 29,654,327 |
| lens | rpc.lens.xyz | 232 ✅ | 6,210,478 |
| cronos | mainnet.zkevm.cronos.org | 388 ✅ | 2,642,550 |
| zero | rpc.zerion.io/v1/zero | 543210 ✅ | 3,455,080 |
| zkcandy | rpc.zkcandy.io | 320 ✅ | 418,459 |
| openzk | rpc.openzk.net | 1345 ✅ | 9,132 |
| (gateway) | rpc.era-gateway-mainnet.zksync.dev | — | **dead: empty response** |

## 2. Bridgehub registry (Ethereum `eth_call`)

- `getZKChain(chainId)` returned a diamond proxy for **all 8 chains + Gateway**
  (addresses in `CHAINS.md` / `KNOWN_ADDRESSES.md`).
- `settlementLayer(chainId) = 1` (Ethereum) for all chains → no chain currently on Gateway.
- `getTotalPriorityTxs()` per diamond: era 3,315,667; abstract 26,934; sophon 10,212;
  lens 7,227; cronos 4,842; zkcandy 6,360; openzk 6,000; zero 5,255.
- Era's diamond `0x32400084…000324` matches the long-known Era address — sanity anchor.

## 3. End-to-end pipeline proof (per chain)

For each chain: fetched a real `NewPriorityRequest` from its L1 diamond, decoded it,
looked up the canonical hash on the chain's L2 RPC → **type `0xff` confirmed, inner
from/to match the decode exactly**. Samples stored in
`seed-data/perchain-l1-event-samples.json`.

| Chain | Sample nature | L2 lookup |
|---|---|---|
| era | Across HubPool (aliased) → SpokePool `relayRootBundle` | ✅ type 0xff — stored sample (txId 3,315,666) was pending at first capture, re-verified after execution at block 71,712,888; an older sample (txId 3,315,423) verified live during prep at block 71,687,236 |
| abstract | EOA self-deposit 15.2 ETH | ✅ type 0xff |
| sophon | canonical deposit: aliased L1AssetRouter → `0x…10003`, `finalizeDeposit` (June 2026 window — post-shutdown window has zero events, as expected) | ✅ type 0xff |
| lens | Across HubPool → SpokePool | ✅ type 0xff |
| cronos | EOA deposit 30,395 zkCRO | ✅ type 0xff |
| zero | EOA self-transfer | ✅ type 0xff |
| zkcandy | EOA self-transfer | ✅ type 0xff |
| openzk | EOA transfer | ✅ type 0xff |

Alias math verified: `0xd297fa91…cfeb − 0x1111…1111 = 0xc186fa91…beda` (Across HubPool);
`0x993aad80…df67 − 0x1111…1111 = 0x8829ad80…ce56` (L1AssetRouter).

## 4. Scanner test run (`scripts/scan_priority.py`)

`--chain lens --from 2026-08-23 --to 2026-08-25`:
19 records, txId 7205–7223, **no gaps**, all `l1_from` populated, ~40 s wall-clock.
Output preserved as `seed-data/example-lens-2026-08-23_25.jsonl`. All 19 records were
Across `relayRootBundle` relays (initiator `0xf7bac63f…` via Multicall3).

## 5. Ethereum log-endpoint limits (measured, not assumed)

- `eth.drpc.org`: getLogs OK at 10k blocks; 25k → "ranges over 10000 blocks are not
  supported on free plan"; occasional "Request timeout on the free plan" under load;
  item-level throttling inside batch responses observed (scanner handles it).
- `rpc.mevblocker.io`: getLogs OK at 10k; 25k → "range 25000 exceeds limit of 10000";
  batch requests OK.
- `ethereum-rpc.publicnode.com`: getLogs refused ("Archive requests require a personal
  token"); also **403s python-urllib TLS while accepting curl** — all HTTP in the
  scanner goes through curl for this reason.
- blastapi (10-block limit), 1rpc (50), merkle (no getLogs), llamarpc (Cloudflare
  challenge): unusable for the scan.

## 6. External facts checked (web, 2026-08-25)

- OpenZK: chainId 1345, base token ozETH, DA Ethereum — official ZKsync Elastic Network
  registry (docs.zksync.io/zksync-network/environment). Not listed on chainid.network.
- ZK Gateway: chainId 9075; **deprecated**, all chains migrated back to direct L1
  settlement (docs.zksync.io gateway FAQ); migration tied to the early-Q1-2026 protocol
  upgrade. Historical which-chain-when data was NOT found — hence the txId-gap
  detection procedure in `METHOD.md` §7.3.
- Sophon: shutdown announced 2026-06-25 (The Defiant); deposits blocked from that day;
  chain to stay live ≥ end of 2026; Binance moved SOPH to ERC-20 on 2026-08-04.
- Event topic + selectors confirmed via 4byte.directory and observed live.

## 7. Independent review + fixes (2026-08-25, later the same day)

An adversarial review re-verified all claims above live (chain IDs, diamond addresses,
Bridgehub registry, selectors/topic via keccak, decoder byte-for-byte, quickstart,
scale figures) and found the following issues — all confirmed independently and fixed:

**Scanner (`scripts/scan_priority.py`):**
- Checkpoints were not bound to (chain, window): rerunning with a different window or
  chain against the same `--out` silently mis-reported (demonstrated: an earlier window
  reported "0 priority txs" for a window containing ~20). Now: identity-checked,
  atomically written checkpoints; mismatched, corrupt, or orphaned state aborts with
  instructions.
- After a resume, the end-of-run summary covered only the current process's records
  (demonstrated: "8 txs" printed for a 19-record file). Now derived by reading the
  output file back.
- A crash between data flush and checkpoint write duplicated records on resume
  (demonstrated: 27 lines / 19 unique). Now deduped on `tx_id` at resume; docs also
  mandate defensive dedupe before aggregation.
- Deterministic "range too large" errors burned ~90 s of retries before chunk-halving.
  Now fail fast (rate-limit errors still retry).
- Records now carry `ts` (the log's `blockTimestamp`, verified present on both
  endpoints); `l1_from`/`l1_to` are explicit nulls with `--no-initiators`.
- Post-fix regression tests: fresh scan matches the seed example record-for-record
  (seed regenerated with the current schema, incl. `ts`); resume summary correct;
  both mismatch repros now abort; crash-dup simulation leaves 19/19 unique.

**Docs:**
- METHOD §5 rules 3/4 overlapped for EOA-with-calldata records — now disjoint
  (rule 3 = aliased-contract senders; rule 4 `other` = EOA-sent calls with calldata).
- Added a classification fallback for gateway-period records lacking `l1_from`.
- Class name unified to `other`; EIP-7702 caveat added to the getCode split;
  checkpoint semantics and `ts` sourcing documented.

**Evidence:**
- The era sample's L2 proof is now stored post-execution (block 71,712,888); the
  original §3 row had cited a different, older sample (txId 3,315,423, block
  71,687,236) whose evidence was never packaged — row corrected.
- The missing sophon seed sample was added (canonical-deposit worked example,
  aliased L1AssetRouter → `0x…10003`, `finalizeDeposit`, L2 execution block
  29,500,625; L1 initiator `0xdfceaf0c…` → `0xc97f5f2f…`, a Sophon-side deposit
  helper — attribution left to the main agent).

**Second review pass (same day):** an independent re-verification confirmed all 13
findings fixed (per-finding FIXED verdicts, with the corrected era/sophon evidence
re-corroborated on-chain) and flagged four follow-on issues introduced by the scanner
rewrite — fixed and regression-tested immediately:
- the fail-fast error classifier applied to every RPC method and could misread
  throttle wordings ("too many concurrent…", "query timeout…") as fatal → now active
  only at the `eth_getLogs` call site (which sits in the halving loop), with
  throttle/timeout wordings explicitly excluded (11-case unit test, both directions);
- the halving loop now rotates endpoints and sleeps between attempts;
- legacy bare-int checkpoints from the pre-rewrite script exit gracefully with
  instructions instead of a raw traceback;
- a malformed final JSONL line (crash-mid-write remnant) is warned about, physically
  repaired, and its range rescanned — instead of crashing the resume/summary paths;
- the checkpoint identity check moved before the block binary-search (a doomed
  mismatched rerun aborts instantly, no RPC calls);
- the seed example was regenerated with the current record schema (incl. `ts`).

**Final acceptance pass (same day):** a third, fresh reviewer role-played the main
agent through Phase 0 with no ambiguities, re-derived 10 facts live (incl. a full
end-to-end decode on abstract and kill/resume stress on an era window with zero
loss/duplication), and issued a SHIP verdict. Its two minor spec gaps were closed
(recovered-record shape in OUTPUT_SPEC §1; optional `weekly` series in aggregates)
plus nits (era rate wording made honest about burstiness; mid-file-corruption stop
added to §9 pitfalls). Afterward an execution-audit sidecar was added and tested:
every scanner run appends start/chunk/done events to `<out>.runlog` — block ranges,
serving endpoint per chunk, counts, wall time — completing the provenance story
(what ran, on which blocks, via which endpoint).

## 8. Known unknowns left for the main agent

- Which chains had Gateway-settled periods inside `T` (detect via txId gaps).
- Explorer API bases for sophon/cronos/zero/zkcandy/openzk (optional tooling).
- Era legacy L2SharedBridge address (⚠️ in `KNOWN_ADDRESSES.md`) — verify if Era's
  early-window deposits reference it.
- Exact semantics of `reserved[0..3]` — heuristics only; confirm against era-contracts
  if used analytically.
