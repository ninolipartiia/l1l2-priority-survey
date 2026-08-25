# L1→L2 Priority-Transaction Census — ZKsync Elastic Network
**Window `T` = 2025-08-26 00:00 UTC .. 2026-08-26 00:00 UTC (end exclusive; effectively through scan time 2026-08-25 ~15:20 UTC) · CHAINS = all 8 · run date 2026-08-25**

---

## 1. Executive summary

Across the 8 ZK-stack chains, the window contains **45,711 L1→L2 priority transactions**, all
enumerated from `NewPriorityRequest` events on each chain's Ethereum diamond proxy and **provably
complete** (gap-free sequential txIds, exact `getTotalPriorityTxs()` boundary proofs at both window
edges, 96/96 L2 spot-checks passed). Era dominates volume (33,779; 74%), followed by lens (4,391),
abstract (4,092), zkcandy (1,407), sophon (1,139), zero (378), cronos (343), openzk (182).

The protocol landscape is narrow and bridge-centric. **Across Protocol** is by far the largest
protocol user of L1→L2 messaging (17,010 txs on era+lens — 37.5% of all era traffic and 99.2% of
lens traffic — relaying root bundles to its SpokePools). A **shared L1USDCBridge** (Circle
"Bridged USDC Standard", matter-labs/usdc-bridge fork) serves both sophon and lens from one L1
contract. **Chainlink** (sequencer uptime feed), **Rocket Pool** (rETH rate oracle), and
**zkLink Nova** (state-sync gateway) each run continuous ~1/day messaging on era. Base-token
wrapper bridges are the defining traffic of the small chains: Sophon's **BridgeHubWrapper** (SOPH),
Cronos's **ZkCroMintAndBridge** (zkCRO), and OpenZK's **BridgeMiddleware** (ozETH/ozUSD
stake-and-bridge). Long-tail-but-real users of canonical messaging on era: **Lido** (wstETH
bridge), **Nodle** (NODL bridge), **Aave** (a.DI governance), **Unlock Protocol** (one cross-chain
upgrade). Plain user activity (direct base-token transfers + canonical deposits) accounts for
~59% of all records; only **22 of 45,711 records (0.05%) remain unattributed**, all enumerated below.

Two findings deserve emphasis: (1) **not a single canonical-bridge deposit in the whole window was
initiated by a true protocol contract** — every code-bearing deposit initiator turned out to be an
EIP-7702-delegated user account (790 such smart accounts seen across all chains; the dominant
delegator is MetaMask's `EIP7702StatelessDeleGator`, 361 of the 525 delegations recorded);
protocols move funds through their own wrappers instead. (2) The
package's assumption "zero Sophon deposits after the 2026-06-25 shutdown" is **wrong in detail**:
three native SOPH deposits (305,800 SOPH, one EOA) executed 2026-06-30..07-03; Sophon's true last
priority tx is txId 10211 on **2026-07-03**.

## 2. Method & completeness

**Source.** For each chain, `eth_getLogs` on Ethereum mainnet for topic
`NewPriorityRequest` (`0x4531cd57…a382`) at the chain's diamond proxy, in ≤10k-block chunks over
ETH blocks **23,221,564 → ~25,832,86x** (2,611,300 blocks; bounds binary-searched from the UTC
window). Every event's embedded `L2CanonicalTransaction` was decoded (txId, canonical hash, inner
from/to, value, calldata) and the enqueueing L1 tx fetched for `l1_from`/`l1_to`
(scanner: `scripts/scan_priority.py`, sha256 `f9c2372c623da5f1…`). 2,096 getLogs chunks total.

**Completeness proof per chain** (all three checks pass on all 8 chains):
1. *txId continuity* — after dedupe, txIds within the window are consecutive with **no gaps**.
2. *Window-start boundary* — `getTotalPriorityTxs()` called **at block 23,221,563** (historical
   `eth_call`) equals the first collected txId exactly.
3. *Window-end boundary* — max txId + 1 ≤ current `getTotalPriorityTxs()` (equal on all chains
   except lens, where exactly one post-scan tx had arrived).

| chain | records | txId range | count-at-window-start | lifetime now | L2 spot checks (type 0xff, from/to match) |
|---|---|---|---|---|---|
| era | 33,779 | 3,281,895..3,315,673 | 3,281,895 ✓ | 3,315,674 ✓ | 12/12 ✓ |
| abstract | 4,092 | 22,842..26,933 | 22,842 ✓ | 26,934 ✓ | 12/12 ✓ |
| lens | 4,391 | 2,837..7,227 | 2,837 ✓ | 7,229 ✓ (1 post-scan) | 12/12 ✓ |
| zkcandy | 1,407 | 4,953..6,359 | 4,953 ✓ | 6,360 ✓ | 12/12 ✓ |
| sophon | 1,139 | 9,073..10,211 | 9,073 ✓ | 10,212 ✓ | 12/12 ✓ |
| zero | 378 | 4,877..5,254 | 4,877 ✓ | 5,255 ✓ | 12/12 ✓ |
| cronos | 343 | 4,499..4,841 | 4,499 ✓ | 4,842 ✓ | 12/12 ✓ |
| openzk | 182 | 5,818..5,999 | 5,818 ✓ | 6,000 ✓ | 12/12 ✓ |

**Gap handling.** Three chains initially showed txId gaps: sophon (9518–9528), zero (4971–4976),
lens (3475–3486). **None were ZK-Gateway settlement gaps** — all 29 missing events exist on
Ethereum and were silently omitted from otherwise-successful `eth_getLogs` responses of
**eth.drpc.org's free tier**, all inside the same L1 block region (~23.575M–23.595M,
2025-10-14..16). All 29 were recovered directly from L1 via a two-endpoint union rescan
(`results/scripts/rescan_gaps.py`; tenderly + onfinality + mevblocker), initiators intact, and are
regular records (`source: "gap-rescan"`). **No chain settled via ZK Gateway during the window**
(also implied by the exact start/end boundary proofs), so no L2-side recovery and no
`initiator: unknown(gateway-period)` records exist.

**Endpoints.** L1: eth.drpc.org and rpc.mevblocker.io (per package) **plus two additions found at
runtime**: eth.api.onfinality.io/public (getLogs 10k, has `blockTimestamp`) and
gateway.tenderly.co/public/mainnet (getLogs 10k, historical eth_call; no `blockTimestamp` — 13
openzk records had `ts` backfilled via `eth_getBlockByNumber`). Era was rescanned via
mevblocker+onfinality after drpc item-level batch throttling made initiator fetches ~15× slower.
L2: the 8 package RPCs, all verified live (`eth_chainId` correct). Explorers used for attribution:
eth.blockscout.com, block-explorer-api.mainnet.zksync.io, explorer-api.lens.xyz; plus
openchain.xyz selector DB, GitHub/docs sources cited per protocol.

**Classification** (METHOD §5, applied to all 45,711 records; per-chain class totals sum to scan
totals):

| chain | total | canonical-deposit | direct-transfer | protocol-message | other |
|---|---|---|---|---|---|
| era | 33,779 | 891 | 19,035 | 13,844 | 9 |
| abstract | 4,092 | 817 | 3,271 | 2 | 2 |
| lens | 4,391 | 4 | 11 | 4,376 | 0 |
| zkcandy | 1,407 | 11 | 1,395 | 0 | 1 |
| sophon | 1,139 | 921 | 0 | 217 | 1 |
| zero | 378 | 38 | 338 | 1 | 1 |
| cronos | 343 | 241 | 2 | 100 | 0 |
| openzk | 182 | 141 | 0 | 40 | 1 |
| **all** | **45,711** | **3,064** | **24,052** | **18,580** | **15** |

100% of canonical deposits on every chain flow through the modern route (aliased **L1AssetRouter**
`0x8829ad80…ce56` → **L2AssetRouter** `0x…10003`); the legacy Era bridge path had **zero** traffic.
Deposit ABI: legacy `finalizeDeposit(address,address,address,uint256,bytes)` `0xcfe7af7c`
(2,924 txs, all chains) and v26 `finalizeDeposit(uint256,bytes32,bytes)` `0x9c884fd1`
(140 txs, era only).

## 3. Per-chain results

Non-deposit share below = share of all priority txs that are not canonical deposits.
"Users" = distinct L1 initiators (`l1_from`) touching the protocol.

### 3.1 ZKsync Era (chainId 324) — 33,779 txs

**Traffic.** 19,035 direct transfers (56%), 13,844 protocol messages (41%), 891 canonical
deposits, 9 other. 17,343 unique L1 initiators (17,109 plain EOAs, 234 EIP-7702 accounts,
0 true contracts — L1 senders are by nature EOAs). Top-1 initiator (Across dataworker
`0xf7bac63f…`) accounts for 37.3% of all traffic; top-10 for 39.9%. Trend: direct transfers
collapsed from ~4,100/month (Sep–Nov 2025) to ~200–300/month baseline in 2026 (spikes May/Jul
2026), while Across relays grew from ~800 to a steady ~1,200/month from Nov 2025; deposits
declined 111→~40–70/month.

**Protocols using L1→L2 messaging on era:**

| Protocol | Category | Txs | Share all / non-dep | Users | Active | Conf. |
|---|---|---|---|---|---|---|
| Across Protocol | bridge | 12,653 | 37.5% / 38.5% | 4 | full window | high |
| Chainlink sequencer uptime feed | infra | 434 | 1.3% / 1.3% | 10 | full window | high |
| Rocket Pool rETH rate oracle | infra | 364 | 1.1% / 1.1% | 13 | full window | high |
| zkLink Nova state-sync gateway | messaging | 356 | 1.1% / 1.1% | 1 | 2025-09-05→ | high |
| Lido wstETH bridge | bridge | 18 | 0.05% / 0.05% | 7 | to 2026-06-09 | high |
| Nodle NODL token bridge | bridge | 8 | 0.02% | 3 | 2025-10-22→ | high |
| Aave a.DI governance messaging | governance | 3 | 0.01% | 3 | Nov 25–Feb 26 | high |
| Unlock Protocol cross-chain upgrade | governance | 1 | — | 1 | 2025-12-08 | medium |
| L2Scan bridge | bridge | 1 | — | 1 | 2025-11-26 | low |

Addresses and roles (all verified as cited in `aggregates.json` evidence):

- **Across**: L1 HubPool `0xc186fa914353c44b2e33ebe05f21846f1048beda` (aliased
  `0xd297fa91…cfeb`) → L2 ZkSync_SpokePool `0xe0b015e54d54fc84a6cb9b666099c46ade9335ff`;
  12,572 × `relayRootBundle(bytes32,bytes32)`, 32 value rebalances, 4 × `setEnableRoute`,
  3 × `upgradeToAndCall` (admin via canonical messaging). Submissions by dataworker EOA
  `0xf7bac63fc7ceacf0589f25454ecf5c2ce904997c` through Multicall3. Plus relayer-funding leg:
  **AtomicWethDepositor** `0x64668fbd18b967b46dd22dc8675134d91efedd8d` sent 42 plain-value
  top-ups to relayer addresses `0x07ae8551…` and `0xa36bc686…`.
- **Chainlink**: L1 ZKSyncValidator `0xdd2e524d186615dedd052c35d3f669b35c5faa8c` →
  L2 ZKSyncSequencerUptimeFeed `0x21cf759a1523fa0aa50b16fadd2fbc9b4d6471ac`,
  `updateStatus(bool,uint64)`.
- **Rocket Pool**: L1 RocketZkSyncPriceMessenger `0x6cf6cb29754aebf88af12089224429bd68b0b8c8` →
  L2 RocketZkSyncPriceOracle `0x6aacd3ed8443a7f4cb19eb4f289a5829842da2b1`, `updateRate(uint256)`.
- **zkLink Nova**: L1 ZkSyncL1Gateway `0xecd189e0f390826e137496a4e4a23acf76c942ab` →
  L2 ZkSyncL2Gateway `0xc203a2df4ddff9ede2200f1f02054fd721182535`
  (impl `0x84639893…`, verified), `claimMessageCallback(uint256,bytes)`; operator EOA
  `0x4eb759a55c56ee1bc06c2b3744df3e1c8fbcfd91`.
- **Lido**: L1 L1ERC20Bridge `0x41527b2d03844db6b0945f25702cb958b6d55989` → L2 wstETH bridge
  `0xe1d6a50e7101c8f8db77352897ee3f1ac53f782b`, `finalizeDeposit` (18 wstETH bridgings).
- **Nodle**: L1 L1Bridge `0x2d02b651ea9630351719c8c55210e042e940d69a` → L2Bridge/NODL
  `0x2c1b65da72d5cf19b41de6edccfb7dd83d1b529e` (selector `0x4ddf75e6`, unnamed in public DBs).
- **Aave**: L1 GovernanceV3 CrossChainController `0xed42a7d8559a463722ca4bed50e0cc05a386b0e1`
  (exact match to aave-address-book) → L2 adapter `0x1bc5c10cae378fdbd7d52ec4f9f34590a619c68e`
  (unverified), `receiveMessage(bytes)`.
- **Unlock Protocol**: L1 ProtocolUpgradeHandler proxy `0xe30dca3047b37dc7d88849de4a4dc07937ad5ab3`
  → L2 ProxyAdmin `0xdb1e46b448e68a5e35cb693a99d59f784ad115cc` (verified UnlockV13 source),
  one `upgrade(address,address)`.
- **L2Scan bridge**: L1 L2ScanEthereumBridgeV2 `0x375424756f4a5ada1ce1e0849abdd19255b1729e`,
  one value transfer.

**Deposits & initiators.** 891 canonical deposits; **none initiated by a true contract** — 263
deposits came from 52 EIP-7702 smart accounts (the largest, `0xd0ce021b…`, 36 txs), the rest from
plain EOAs. Notable "other": 3 L1-initiated `approve()` calls on era tokens (USDC.e, WETH) by one
vanity EOA, 5 empty self-calls.

**Unattributed remainder: 15 txs (0.11% of non-deposit).** 4 Safe/GnosisSafe multisig value/token
moves (`0x21465ea9…` ×2, `0xcf75bd79…` ×1, `0xe97daa96…` ×1 token transfer), 2 messages
selector `receiveHashes(uint256,bytes32[])` from unverified `0xab23df3fd78f45e54466d08926c3a886211ac5a1`
(Hashi-oracle-like pattern) to unverified targets `0x40f58bd4…`/`0xf69a42ef…`, 9 "other"-class
user calls listed above. Top groups are in `aggregates.json → chains.era.unattributed`.

### 3.2 Abstract (chainId 2741) — 4,092 txs

Almost purely retail: 3,271 direct transfers + 817 canonical deposits (99.9%). 1,889 unique
initiators (1,563 plain EOA, 326 7702 accounts), top-1 only 3.5%. Trend: steady, peak Sep–Oct 2025
(~700/mo), ~100–380/mo after. **Protocols:** only **AbstractBridge**
(`0x8696a96c606bd48872e7e42fcbef41c250e8792a`, verified fee-taking Bridgehub wrapper; operator
unknown; medium confidence), 2 txs, 2026-06/07. 128 deposits came from 36 7702 accounts (largest
`0xf097cb45…`, 41 txs); zero from true contracts. Unattributed: 2 (one 0-value ping by the
cross-chain tester `0x58551793…`, one user call sel `0x64e7f93b` — unknown signature — to
unverified `0xed68e191…`).

### 3.3 Sophon (chainId 50104) — 1,139 txs · base token SOPH

Deposit-dominated: 921 canonical deposits + 217 protocol messages + 1 ping; **zero plain direct
transfers** (native SOPH moves through the wrapper instead). 266 unique initiators; only **4
distinct inner senders** (aliased AssetRouter, aliased BridgeHubWrapper, aliased L1USDCBridge, one
EOA) — all Sophon L1→L2 traffic is intermediated. Nearly every deposit's `l1_to` is the
**BridgeHubWrapperProxy** `0xc97f5f2fde4fe6e220069f8d3718be4fac7c00f0`.

| Protocol | Category | Txs | Share all / non-dep | Users | Active | Conf. |
|---|---|---|---|---|---|---|
| Sophon BridgeHubWrapper (native SOPH deposits) | bridge | 110 | 9.7% / 50.5% | 73 | 2025-09-04..2026-07-03 | high |
| Bridged USDC Standard (matter-labs usdc-bridge) | bridge | 107 | 9.4% / 49.1% | 35 | 2025-08-26..2026-06-16 | high |

- **BridgeHubWrapper** (impl `0x5a278c11…`, verified): aliased sender `0xda905f2f…1201` delivers
  SOPH base-token to the depositor's own L2 address (empty calldata, value>0).
- **USDC bridge**: L1USDCBridge `0xf553e6d903aa43420ed7e3bc2313be9286a8f987` → sophon
  L2USDCBridge `0x0f44bac3ec514be912aa4359017593b35e868d74`, `finalizeDeposit`; per
  github.com/sophon-org/custom-usdc-bridge (fork of matter-labs/usdc-bridge).

**Wind-down timeline** (announced 2026-06-25): monthly volume 302 (Sep-25) → ~20/mo (Apr–Jun 26)
→ 2 (Jul). USDC bridging stopped 2026-06-16, canonical ERC-20 deposits 2026-06-20 — but **three
native SOPH wrapper deposits executed after the announcement** (txIds 10209–10211; 2026-06-30,
07-03 ×2; 15,800 + 30,000 + 260,000 SOPH; single EOA `0xbaeb9288…`). Sophon's last priority tx is
2026-07-03; nothing since (verified zero events in the final ~7.5 weeks and boundary-exact count
10,212). 138 deposits by 47 EIP-7702 accounts; none by true contracts.

### 3.4 Lens (chainId 232) — 4,391 txs · base token GHO

The most protocol-concentrated chain: **99.6% of all priority traffic is two protocols; only 8
unique initiators all window.**

| Protocol | Category | Txs | Share all | Users | Active | Conf. |
|---|---|---|---|---|---|---|
| Across Protocol | bridge | 4,357 | 99.2% | 4 | full window | high |
| Bridged USDC Standard | bridge | 19 | 0.4% | 5 | full window | high |

- **Across**: 4,338 × `relayRootBundle` + 15 value/GHO rebalances + 4 upgrade calls. Two
  SpokePools: initial `0xe7cb3e167e7475de1331cf6e0ceb187654619e12` (46 relays + 2×`upgradeTo`,
  2025-08-26..08-30) replaced by current `0xb234ca484866c811d0e6d3318866f583781ed045` (verified
  `Lens_SpokePool`) from 2025-09-02 — the census pins the SpokePool migration to 2025-08-30/09-02.
  Cadence extremely steady (~11–12 relays/day, 271–474/month).
- **USDC bridge**: same L1 contract as sophon → lens L2USDCBridge
  `0x7188b6975eec82ae914b6ec7ac32b3c9a18b2c81` (verified source).

Residual: 4 canonical deposits, 11 direct transfers. Zero unattributed.

### 3.5 Cronos zkEVM (chainId 388) — 343 txs · base token zkCRO

241 canonical deposits + 100 wrapper messages + 2 direct transfers. One protocol:
**ZkCroMintAndBridge** `0xe69a535730858fd8dc386b448972a9f801ab4e12` (verified; mints zkCRO from
CRO and bridges as base token; 100 txs = 98% of non-deposit, 56 users, full window). 40 deposits
by 10 7702 accounts. 125 unique initiators. Zero unattributed. Quiet chain: 8–64 txs/month,
June 2026 had zero.

### 3.6 ZERϴ Network (chainId 543210) — 378 txs

Almost purely retail: 338 direct transfers + 38 deposits. 269 unique initiators, top-1 5%.
**No protocol traffic** except one self-deposit by a (formerly code-bearing) smart account
`0x42260072…` submitted by bundler-style EOA `0x4337009b…`. Unattributed: that tx + one 0-value
ping (tester `0x953a9df5…`, also seen on zkcandy/openzk). No verified fallback RPC exists —
rpc.zerion.io held up fine.

### 3.7 ZKcandy (chainId 320) — 1,407 txs

99.2% direct transfers (1,395), 11 deposits, 1 ping. **No protocol traffic at all.**
1,255 unique initiators but top-1 only 0.7% — wide, shallow, and **85% of the whole window's
volume happened in September 2025** (1,198 txs; likely a campaign/airdrop-driven burst of tiny
self-transfers, median-value analysis in enriched data), then ≤8/month from November on. A ghost
chain since.

### 3.8 OpenZK (chainId 1345) — 182 txs · base token ozETH

141 canonical deposits + 40 protocol messages + 1 ping. One protocol: **OpenZK BridgeMiddleware**
`0xbd9a30a63df163dc91efd65060d47ed350061b53` (verified source: stake-and-bridge, mints
ozUSD/ozETH; 40 txs, 19 users, full window; main L2 recipient `0xee65cca8…`, itself the #2
deposit initiator). 61 deposits by 9 7702 accounts (largest `0xa91206fa…`, 37 txs — 20% of the
chain's entire traffic). **The "suspiciously round" lifetime count of exactly 6,000** in the
package resolves mundanely: the chain simply crossed 6,000 with txId 5999 on **2026-08-23** and
had no further txs before the scan — timing coincidence, not a scripted cap; in-window activity is
a steady organic trickle (6–36/month), 5,818 of 6,000 lifetime txs predate the window.
The chain remains extremely small (~9k L2 blocks).

## 4. Cross-chain patterns

**Protocols on ≥2 chains** (join key: L1 address):
- **Across Protocol** — era + lens, same HubPool `0xc186fa91…beda` and dataworker; 17,010 txs
  combined. (Across serves no other chain in this set.)
- **Bridged USDC Standard** — sophon + lens, the **same** L1USDCBridge `0xf553e6d9…8f987`
  serving two chains through Bridgehub's two-bridges route; 126 txs combined.

**Initiators on ≥2 chains**: 62 addresses. Top: Across dataworker `0xf7bac63f…` (era+lens,
16,952 txs), `0xf70da978…` (era+abstract+zero, 230), `0x65a8f07b…` (era+abstract+cronos, 158),
`0x9452ed6d…` (era+sophon, 157), Across relayer `0x07ae8551…` (era+lens, 125). Two 0-value
"tester" EOAs pinged 5 chains between them (`0x953a9df5…`: zero/zkcandy/openzk;
`0x58551793…`: abstract/sophon) — someone systematically probing Elastic-chain mailboxes.

**Structural pattern — the wrapper-bridge family.** Every non-ETH-base-token chain runs its own
L1 wrapper that converts the native asset and delivers base-token via a priority tx with empty
calldata to the depositor's address: Sophon BridgeHubWrapper (SOPH), Cronos ZkCroMintAndBridge
(zkCRO), OpenZK BridgeMiddleware (ozETH/ozUSD, with staking). AbstractBridge is the same shape
run by a third party for fees on an ETH-base chain. These four are functionally the "native
deposit rails" of their chains and together explain nearly all wrapper-class traffic.

**Anomalies.**
- Sophon's post-shutdown deposits (§3.3) — deposits were *not* fully blocked on 2026-06-25.
- eth.drpc.org silent getLogs data loss (§2) — a data-integrity hazard for anyone scanning
  Ethereum logs via that free tier; three independent chains lost events in the same block region.
- zkcandy's September-2025 one-month burst (85% of its year).
- Era saw EOA-initiated L1→L2 *token approvals* and Safe-initiated token transfers — users
  driving L2 contracts from L1 directly, a niche but real usage of the mailbox.

## 5. Caveats

- **Value units are per-chain base tokens** (ETH on era/abstract/zero/zkcandy; SOPH, GHO, zkCRO,
  ozETH elsewhere). No cross-chain value totals are quoted anywhere in this report.
- **EOA/contract splits** use `eth_getCode` at the latest block; EIP-7702 delegations are counted
  separately (`eip7702_account`), but an account that added/removed a delegation after its txs is
  classified by its *current* state. One era initiator had code during the window that has since
  been removed ("eoa-now").
- **No gateway-period records exist** in this dataset (every record has a live `l1_from`), so the
  gateway-recovery caveats in the package do not apply to this window.
- **Confidence semantics**: high = both sides verified on-chain/source or exact match to official
  registry/docs; medium = verified name on one side, project inferred; low = name-only, single tx.
  Unverified labels are marked as such everywhere.
- Across's `unique_users` counts L1 submitters (dataworker etc.), not end bridge users — end users
  interact with SpokePools on L2/other chains and never appear in L1→L2 priority traffic.
- The two selectors `0x4ddf75e6` (Nodle) and `0x64e7f93b` (1 abstract tx) have no public
  signature-DB entry; the Nodle one is attributed via verified target source anyway.

## 6. Appendix

### 6.1 Address→label registry
The full registry (57 entries: ecosystem contracts, per-protocol L1/L2 addresses, 7702 delegator
implementations, notable EOAs) is machine-readable in **`results/scripts/labels.json`**, merged
from `KNOWN_ADDRESSES.md` seeds plus this run's findings; per-protocol addresses with roles and
evidence live in **`results/scripts/attribution.json`** (`protocol_meta`).

### 6.2 Data files
- `results/raw/<chain>.jsonl` — 45,711 records (dedupe key `tx_id`; 29 carry
  `source:"gap-rescan"`); `.runlog` sidecars = per-chunk execution audit incl. serving endpoint;
  `.ckpt` = resume state; `.run.log`/`.run2.log`/`.run3.log` = scanner stdout.
- `results/enriched/<chain>.jsonl` — + class, unaliased_from, deposit_by_contract,
  deposit_via_7702, initiator_is_contract, protocol, ts.
- `results/aggregates.json` — every number cited here.
- `results/run-manifest.json` — parameters, endpoints, timings, RPC-call accounting.
- `results/scripts/` — completeness/enrichment/aggregation/rescan tooling (this run's code),
  `completeness.json`, `codecache.json`, `initiator-kinds.json`.

### 6.3 Reproduction
`python3 scripts/scan_priority.py --chain <c> --from 2025-08-26 --to 2026-08-26 --out raw/<c>.jsonl`
per chain, then `results/scripts/{rescan_gaps,check_completeness,enrich,aggregate}.py` in that
order. Every record is independently re-verifiable on-chain via (`l1_block`, `l1_tx`, `log_index`)
on Ethereum and `canonical_hash` on the L2.
