# L1→L2 Priority Transactions — the L2-Side Recipient Census (Phase 6)

**Window `T` = 2025-08-26 00:00 UTC .. 2026-08-26 00:00 UTC · CHAINS = all 8 · CLASSES =
`direct-transfer,other` · RECUR_MIN = 2 · run date 2026-08-26**

Input: `../results/` (45,711 priority txs, census run 2026-08-25) — read-only and unmodified.
Every number below is derivable from `aggregates-l2.json`; endpoints, substitutions and archive
capability are in `run-manifest-l2.json`.

---

## 1. Executive summary

Of the **24,067 EOA-origin L1→L2 priority transactions**, **889 (3.7%) paid an address that
already had code when the money arrived** — verified at the block *before* each funding tx, not
at today's chain tip. Of those 889, **865 (97.3%) went to the sender's own smart-contract
wallet** — 864 to Abstract Global Wallet accounts on abstract, 1 to a Safe on era — and only
**24 txs (0.10% of the whole candidate set) reached something that is not a user account**: 19 to
**Veno Finance**'s `BridgeReceiver` on era (7.167 ETH of liquid-staking flow), 4 to token
contracts (USDC.e, ZK, WETH on era), and 1 to a single unverified private contract on abstract.
The remaining **23,174 txs (96.3%) paid a plain codeless address**.

So the honest headline is: **genuine protocol interaction in the EOA-origin set is one protocol
and 19 transactions.** The "EOA → contract" number is real but it is almost entirely *users
funding their own wallets*: reporting it without the Axis-B split would present 889 txs as
protocol usage where 19 of them are — a 47× overstatement.

**Coverage is complete — there are no unresolved denominators.** All **22,162 (chain, address)
lookups** got a verdict; **0** are `unresolvable`, `contract-later`, `delegated-eoa` or
`code-time-unverified`. That includes **zkcandy**, which the input package expected to be
unresolvable: its RPC is still dead, but its **block explorer is alive again** and served all
1,251 recipients + 10 deposit beneficiaries (§2.3). Every one of them is a plain address —
zkcandy has **zero** contract recipients.

Three secondary results:

- **The counterfactual-deployment trap did not bite anywhere.** All 371 contract addresses
  already had code at `funding_block − 1`; `contract-later` is **0**, so the error term METHOD §4
  exists to size is empty (0 straddling recipients, 0 straddling txs).
- **The `eoa` bucket held up under its control.** 1,298 recipients across 7 chains that are
  codeless today were also codeless when they were paid; **0** contradictions.
- **The `protocol-message` control refuted its own stated expectation** and that is a finding,
  not a fault (§3.5): on cronos, openzk, abstract and zero, *every* protocol-message recipient is
  a plain EOA. That class is defined by the **sender** being a contract; on the small chains the
  sender is a deposit-wrapper contract paying the user's own L2 address.

---

## 2. Method & coverage

### 2.1 What was resolved

| | txs | (chain, address) pairs |
|---|---|---|
| candidate set (`direct-transfer` + `other`) | 24,067 | 21,515 recipients (21,480 distinct addresses; 31 on ≥2 chains) |
| secondary set (decoded canonical-deposit beneficiaries) | 2,924 deposits | 787 beneficiaries (775 distinct; 11 on ≥2 chains) |
| control set (`protocol-message`) | 18,580 | 172 recipients |
| **getCode workload** | | **22,162** = the per-chain **union** of recipients and beneficiaries (they overlap on 140 pairs, so it is *not* 21,515 + 787) |

Phase 0 reproduced **every** number in `seed-data/ground-truth.json` from
`../results/enriched/*.jsonl` — all totals, all per-chain values, and all top-10 recipient lists
under the stated tiebreak (txs DESC, address ASC) — with zero discrepancies
(`scripts/reproduce_ground_truth.py`).

**140 era canonical-deposit records were not decoded.** They carry the v26 selector `0x9c884fd1`
= `finalizeDeposit(uint256,bytes32,bytes)`, whose receiver is nested inside the `bytes` blob;
METHOD §1 puts them out of scope for the shipped resolver, and they are reported as a counted
skip on every run. Consequences, stated rather than buried: era's beneficiary count is 201 rather
than up to 341, the workload total is 22,162 rather than larger, and the deposit-side coverage in
§6 is **2,924 of 3,064** canonical deposits (95.4%).

### 2.2 How code-time was proven

`eth_getCode(recipient, blockNumber − 1)` of the recipient's earliest in-window tx — the block
**before** the funding tx, because `getCode(N)` returns end-of-block-`N` state and would include
a deployment done later in the same block. All 7 live endpoints serve full archive state; the
probe is in `run-manifest-l2.json` and is more than a smoke test: on cronos and zero,
`eth_getCode(0x…10003)` returns a *different* code size at tip−1M (39,392 B) than at the tip
(42,528 B), which proves genuine historical state rather than a silent latest-block fallback.

| chain | endpoint | archive `getCode` | code cache block |
|---|---|---|---|
| era | `mainnet.era.zksync.io` | yes | `0x4468d6d` |
| abstract | `api.mainnet.abs.xyz` | yes | `0x4d6b534` |
| sophon | `rpc.sophon.xyz` | yes | `0x1c48007` |
| lens | `rpc.lens.xyz` | yes | `0x5ed1fb` |
| cronos | `mainnet.zkevm.cronos.org` | yes | `0x285621` |
| zero | `rpc.zerion.io/v1/zero` | yes | `0x34bc68` |
| openzk | `rpc.openzk.net` | yes (tip−1k; the chain is only 9,136 blocks old) | `0x23b0` |
| zkcandy | **`explorer.zkcandy.io/api`** (substitution) | n/a — creation block instead | explorer tip |

`--no-chain-check` and `--allow-input-name-mismatch` were **never** used: every RPC run passed the
`eth_chainId` assertion and every per-chain file named its own chain.

### 2.3 The zkcandy substitution

The input package predicted zkcandy would strand 1,396 txs / 1,251 recipients. That prediction no
longer holds, and the live chain wins over the package.

`rpc.zkcandy.io` is still dead, and so is every free JSON-RPC alternative probed —
`zkcandy.drpc.org` (404), `rpc.ankr.com/zkcandy` (403), `zkcandy-mainnet.public.blastapi.io`,
`mainnet.zkcandy.io`, `rpc.zkcandy.com`, `zkcandy-mainnet.rpc.caldera.xyz`; `chainid.network`
lists only the dead endpoint. `320.rpc.thirdweb.com` *does* answer `eth_chainId` with `0x140`
(= 320, genuinely zkcandy) but refuses every other method without an API key.

Its **block explorer**, however, answers — and it indexes the census's canonical hashes.
`scripts/resolve_zkcandy_explorer.py` substitutes two explorer endpoints for the two RPC calls:

| RPC call the shipped scripts use | explorer substitute |
|---|---|
| `eth_getCode(addr, latest)` | `contract&getcontractcreation` — a creation record means the address has code |
| `eth_getTransactionByHash` + historical `eth_getCode` | `account&txlist` for the funding tx's block, compared against the creation block |

Code-time on zkcandy is therefore **derived** (`created_block < funding_block`) rather than
probed; the semantics match the block−1 probe ("code existed before the funding tx's block").

**Validated, not assumed** (`seed/zkcandy-method-validation.json`). era has both a working archive
RPC *and* the same explorer API, so the substitute was scored against `eth_getCode` ground truth
there: **208/208 agreement** — all 8 era contract recipients and 200 randomly sampled era EOA
recipients, 0 disagreements, 0 API errors. A positive control on zkcandy itself found 8 real
zkcandy contracts (discovered independently through the explorer's own `tokentx`/`txlist` data),
so the all-EOA sweep result is not a broken detector.

One API trap was load-bearing: `contractaddresses` caps at **10** and returns `status:1 "OK"` with
**zero** results above it — silent truncation that would have produced a whole chain of confident
false "EOA" verdicts. The script hard-caps at 10 and asserts every returned address was one it
asked for. (era's copy of the same API caps at 5 but fails loudly with `status:0 NOTOK`; that
difference is exactly why the cap was measured per host rather than assumed.)

**Declared limitations of the substitute:**

1. **No bytecode.** zkcandy contributes no `code_len`, no `codehash`, and therefore **no bytecode
   families**. Had it contained contract recipients, they could not have been clustered.
2. **EIP-7702 is undetectable** — a delegation is code, not a creation record. zkcandy's
   `delegated-eoa` count is **unknown, not zero**.
3. **Genesis contracts have no creation record** and read as codeless. Verified for `0x…8007`,
   `0x…800a`, `0x…800b`, `0x…10002`, `0x…10005`. Every genesis contract on a ZK-stack chain lives
   inside the reserved range METHOD §3 flags `is_system`, so no user-chosen counterparty can be
   mis-filed — but it is why address `0x0` sits in zkcandy's `eoa` bucket while it is `contract`
   on abstract, sophon, zero and openzk. That single address is the only known divergence between
   the two methods, and it is `is_system` on both sides.

### 2.4 Other deviations from the package

- **abstract needs no Etherscan V2 key.** `CHAINS.md` says it does;
  `block-explorer-api.mainnet.abs.xyz` is the same ZKsync-era-style API era uses and answered
  `getsourcecode`/`getcontractcreation` unauthenticated. This is what made attributing the
  352-member AGW family cheap.
- **Explorer API bases discovered at runtime** for sophon (`api-explorer.sophon.xyz`), zero
  (`explorer.zero.network/api`) and openzk (`explorer.openzk.net/api`).
- **No explorer API found for cronos.** Several bases were probed; none answered. cronos has 0
  contract recipients and 0 contract deposit beneficiaries, so nothing depended on it.

---

## 3. The recipient landscape

### 3.1 `to_kind` — the six disjoint buckets

| `to_kind` | recipients (chain, address) | txs | share of txs |
|---|---|---|---|
| `eoa` | 21,211 | 23,174 | 96.29% |
| `contract` (code verified at tx time) | 304 | 893 | 3.71% |
| `contract-later` | 0 | 0 | — |
| `delegated-eoa` | 0 | 0 | — |
| `unresolvable` | 0 | 0 | — |
| `code-time-unverified` | 0 | 0 | — |
| **total** | **21,515** | **24,067** | **100%** |

**`is_system` is a flag inside those buckets, not a seventh one.** 5 recipients / 5 txs are
reserved addresses — address `0x0` on abstract, openzk, sophon, zero and zkcandy, the target of
the cross-chain tester's 0-value pings. Four of them sit in the `contract` bucket (224 bytes of
`EmptyContract` code) and one in `eoa` (zkcandy, per §2.3). They are excluded from the headline
and never given an `actor_type`.

**Headline, system-filtered: 889 txs to 300 contract recipients.**

### 3.2 Smart wallet vs. protocol — the split that matters

| `actor_type` | recipients | txs | share of the 24,067 |
|---|---|---|---|
| `smart-wallet` | 295 | 865 | 3.59% |
| `protocol-contract` | 1 | 19 | 0.079% |
| `token` | 3 | 4 | 0.017% |
| `unknown-contract` | 1 | 1 | 0.004% |
| **total** | **300** | **889** | **3.69%** |

Collapsing Axis B would turn 865 txs of *users funding their own AGW wallets* into "protocol
usage": 889 txs presented as protocol interaction where 19 actually are, a **47×** overstatement.
The distinction is not a technicality — an AGW account is the user's wallet, reached from L1 by
the same person who owns it.

### 3.3 Recurrence — the one-shot skew is the shape of the data

| txs received | recipients | of which contracts |
|---|---|---|
| exactly 1 | 20,708 (96.2%) | 198 |
| 2–4 | 709 | 82 |
| 5–9 | 64 | 18 |
| ≥10 | 34 | 6 |

807 (chain, address) pairs received ≥2 txs, 98 received ≥5, 34 received ≥10 — counted per chain
and summed, never across chains. Contract recipients are *over*-represented in the recurring tail
(24 of the 98 recipients at ≥5 txs are contracts, vs. 1.4% of the population overall), which is
what you would expect if the recurring head is people topping up wallets they control.

**Self-funding is the dominant EOA pattern and is entirely absent among contracts.** 4,354
recipients (6,239 txs, 25.9%) are addresses that also appear as an `l1_from` on the same chain —
the user paying themselves across the bridge. **Zero** of the 300 contract recipients do this,
which is the expected signature of a counterfactual smart account: the wallet address is not the
key that signs on L1.

### 3.4 The three hypotheses, decided

- **H1 — "recipients are overwhelmingly plain EOAs": CONFIRMED, and more strongly than the seed
  data suggested.** 21,211 of 21,515 (98.6%) recipients and 23,174 of 24,067 txs (96.3%) are plain
  addresses. era, which carries 79% of the candidate traffic, has **5 contract recipients out of
  18,325**.
- **H2 — "contract recipients cluster into a few bytecode families dominated by smart wallets, not
  protocols": CONFIRMED.** 352 of the 371 contract addresses (95%) are one family, AGW, and it is
  a smart-account family. Across the whole dataset, `smart-wallet` outweighs `protocol-contract`
  by 865 txs to 19.
- **H3 — "genuine protocol interactions are rare and concentrated on era/abstract": CONFIRMED for
  era, REFUTED for abstract.** There is exactly one protocol recipient in the candidate set —
  Veno Finance on era, 19 txs. Abstract, despite holding 97% of the EOA→contract flow, has
  **zero** protocol-contract recipients: its whole contract population is user wallets.

### 3.5 The `protocol-message` control

The package predicted the control's recipients "should be overwhelmingly contracts; if not,
something is wrong with the method." They are not, and nothing is wrong with the method.

| chain | pm txs | txs → contract recipient | txs → EOA recipient |
|---|---|---|---|
| era | 13,844 | 13,799 | 45 |
| lens | 4,376 | 4,376 | 0 |
| sophon | 217 | 107 | 110 |
| cronos | 100 | 0 | 100 |
| openzk | 40 | 0 | 40 |
| abstract | 2 | 0 | 2 |
| zero | 1 | 0 | 1 |
| **total** | **18,580** | **18,282 (98.4%)** | **298** |

Where the class means what its name suggests — era and lens, i.e. Across, Chainlink, Rocket Pool,
zkLink, Lido, Nodle — recipients are contracts, 18,175 of 18,220 txs. The exceptions are
structural: `protocol-message` is defined by the **sender** being a contract (aliased inner
`from` ≠ `l1_from`), and on cronos, openzk and sophon the sender is the chain's own
deposit-wrapper contract (`ZkCroMintAndBridge`, `BridgeMiddleware`, `BridgeHubWrapper`) paying the
user's own L2 address — every one of those 298 records has `to == l1_from`, `data_len ≤ 2`, and
non-zero value. The control therefore confirms the method rather than failing it, and it
incidentally corrects a reasonable-looking assumption in the input package.

All 16 contract recipients in the control set were code-time verified: 16/16 `contract`.

---

## 4. Bytecode families

A family is a set of recipients whose `getCode` output is byte-identical, keyed by the sha256 of
the lowercased code hex — a **clustering key, not the EVM keccak codehash**. 13 families cover all
371 contract addresses found across the candidate, deposit-beneficiary and control sets.

| codehash (sha256, 12) | bytes | members | candidate txs | chains | actor_type | attribution | conf. |
|---|---|---|---|---|---|---|---|
| `fbd752b557db` | 1,632 | **352** (294 cand + 58 deposit-only) | **864** | abstract | `smart-wallet` | **Abstract Global Wallet (AGW)** — proxies to `AGWAccount` `0xaa3633b4…` | high |
| `80c17066accb` | 3,104 | 1 | 19 | era | `protocol-contract` | **Veno Finance** `BridgeReceiver` | high |
| `85ee7f0e9128` | 224 | 4 | 4 | abstract, openzk, sophon, zero | — (`is_system`) | `EmptyContract` at address `0x0` | high |
| `fc11c64adec8` | 11,168 | 1 | 2 | era | `token` | **ZK token** (impl `ZkTokenV3` `0x4fcd824d…`) | high |
| `b097d90d9e43` | 9,248 | 1 | 1 | era | `token` | **USDC.e** — beacon → `BridgedStandardERC20` | high |
| `1a0647714d64` | 15,840 | 1 | 1 | era | `token` | **WETH (era)** (impl `L2WETH` `0x2ff821c3…`) | high |
| `4c0d9dfd76a6` | 171 | 1 | 1 | era | `smart-wallet` | **Safe** (`GnosisSafeProxy`) | high |
| `3e7b5a30d7d4` | 51,936 | 1 | 1 | abstract | `unknown-contract` | **unattributable** — see below | — |
| `580f1200e492` | 5,216 | 1 (deposit-only) | 0 | era | `protocol-contract` | **Across Protocol** `ZkSync_SpokePool` | high |
| `00705b5baa7a` | 8,288 | 1 (deposit-only) | 0 | era | `protocol-contract` | **Domani Protocol** `RewardsManager` | high |
| `78a2ecb0ee29` | 170 | 1 (deposit-only) | 0 | era | `smart-wallet` | **Safe** (older proxy build) | high |
| `eaeedde5a874` | 8,032 | 5 (deposit-only) | 0 | sophon | `smart-wallet` | **ZKsync SSO** — beacon `SsoBeacon` → `SsoAccount` | high |
| `645ea2612eb1` | 1,595 | 1 (deposit-only) | 0 | openzk | `protocol-contract` | **OpenZK `OzkVault`** | medium |

**The AGW family is the entire story of "EOA → contract" in this dataset.** The seed data sampled
three members at ranks 1, 5 and 6 (162 + 94 + 60 = 316 txs); the full sweep found **352** members
carrying **864** txs — 97.2% of the whole headline. Every member's verified contract name on
abstract's explorer is `contracts/AccountProxy.sol:AccountProxy`, every one has the same ERC1967
implementation slot value `0xaa3633b417483f932969edaef7cc4f1068f6faa9`, and that implementation is
verified as `contracts/AGWAccount.sol:AGWAccount`. The hypothesis in the input package (H2) is
confirmed on all three counts: the family is real, it is a smart-account family, and it is not a
protocol. Its distribution is itself long-tailed — of the 294 members that are candidate recipients, 190
received exactly 1 tx, 81 got 2–4, 18 got 5–9, and 5 got ≥10; the other 58 members appear only as
deposit beneficiaries.

**The one unattributable contract.** abstract `0xed68e19181108758d17c2b1992a5e6b46a60f7d5`,
51,936 bytes, 1 tx (0.0163 ETH). Tried and failed: source is not verified on abstract's explorer;
no ERC1967 impl/beacon/admin slot is set; `name()`/`symbol()` return nothing; its selector
`0x64e7f93b` is unknown to both openchain.xyz and 4byte.directory. What *is* known is decisive
about its nature: it was created by `0x94a8ce783060c8e519ca85fe2de8068bf3917d22`, and that address
is the only one that has ever called it (3 calls, all `0x64e7f93b`) and the only L1 initiator that
paid it. It is a single-user private contract, not shared infrastructure.

Only one family spans chains — `85ee7f0e` (`EmptyContract` at `0x0`), on abstract, openzk, sophon
and zero. AGW is abstract-only; ZKsync SSO is sophon-only in this dataset.

---

## 5. Per-chain results

| chain | candidate txs | recipients | `contract` recipients | headline txs → contract | protocol-contract txs |
|---|---|---|---|---|---|
| era | 19,044 | 18,325 | 5 | 24 | 19 (Veno) |
| abstract | 3,273 | 1,676 | 296 (1 system) | 865 | 0 |
| zkcandy | 1,396 | 1,251 | 0 | 0 | 0 |
| zero | 339 | 257 | 1 (system) | 0 | 0 |
| lens | 11 | 2 | 0 | 0 | 0 |
| cronos | 2 | 2 | 0 | 0 | 0 |
| sophon | 1 | 1 | 1 (system) | 0 | 0 |
| openzk | 1 | 1 | 1 (system) | 0 | 0 |

### 5.1 ZKsync Era — 19,044 candidate txs, 18,325 recipients

Almost perfectly one-shot: 18,057 recipients received exactly one tx. Only **5** recipients have
code, carrying 24 txs (8.167 ETH).

| address | txs | actor_type | identity |
|---|---|---|---|
| `0x9cb1e077e7253a4f022e74862a93ee7cecab788b` | 19 | `protocol-contract` | **Veno Finance** `BridgeReceiver` |
| `0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e` | 2 | `token` | ZK token |
| `0x3355df6d4c9c3035724fd0e3914de96a5a83aaf4` | 1 | `token` | USDC.e |
| `0x5aea5775959fbc2557cc8789bc1bf90a239d9a91` | 1 | `token` | WETH |
| `0xab8454126722dbcb3da5ab2cbb647663c2e56659` | 1 | `smart-wallet` | Safe |

**Veno Finance** is the only genuine protocol interaction in the entire EOA-origin set: 19 txs,
**7.167 ETH**, 2025-08-26 → 2026-08-19, all from one L1 initiator
`0x24ebbe07f22bb7cf667030a3902c81d3439365bf`. Evidence chain: verified source
`src/BridgeReceiver.sol:BridgeReceiver` whose doc comment reads "the receiver for bridged ETH to
the chain … flow back into LiquidToken contract"; the source tree carries `IVenoNft.sol` and
`ILiquidToken.sol`; the constructor argument `_liquidToken = 0xe7895ed01a1a6aacf1c2e955af14e7cf612e7f9d`
answers `name() = "Liquid ETH"`, `symbol() = "LETH"` live on chain; and Veno Finance launched
ETH-native liquid staking on ZKsync Era in January 2024. The single-sender, steady-cadence
pattern is a protocol operator returning unbonded ETH from the L1 staking leg, not retail traffic.

The other 9 of era's top-10 recipients are plain EOAs, 7 of them self-funding — confirming
hypothesis H1.

### 5.2 Abstract — 3,273 candidate txs, 1,676 recipients

The one chain where "EOA → contract" is a meaningful share: **296 of 1,676** recipients have code
— 295 of them user addresses, the 296th being the reserved `0x0` — and those 295 take **865 of
3,273 txs (26.4%)**, 36.481 ETH. But **864 of those 865 are AGW smart
wallets**, so abstract's number is a measure of *account-abstraction onboarding*, not protocol
usage: 305 distinct L1 initiators funded 294 AGW accounts. Abstract has **zero**
protocol-contract recipients in the candidate set.

Ranks 2, 3, 4 and 7–10 of abstract's recipients are plain self-funding EOAs; ranks 1, 5 and 6 are
AGW wallets. The family is a bytecode fact, not a head-of-distribution fact.

### 5.3 zkcandy — 1,396 candidate txs, 1,251 recipients

**All 1,251 recipients and all 10 deposit beneficiaries are plain addresses; 0 contracts.** This
chain was expected to be unresolvable and is now fully resolved via its explorer (§2.3). Caveat
that survives: EIP-7702 delegations are invisible to the substitute method, so zkcandy's
`delegated-eoa` count is unknown rather than zero.

### 5.4 ZERϴ Network — 339 candidate txs, 257 recipients

256 plain EOAs plus address `0x0` (224 bytes, `is_system`, the tester ping) — the seed data's
finding reproduced exactly, including the code-time proof (funding tx in `0x34ad52`, probed at
`0x34ad51`). No protocol recipients. The full 269-address `eoa` control ran here with 0
contradictions.

### 5.5 Lens — 11 candidate txs, 2 recipients

Both plain EOAs; one received 10 of the 11 txs. Lens's real traffic is the control set: 4,376
protocol-messages, 100% to contracts — Across's `Lens_SpokePool` (both the current
`0xb234ca48…` and the initial `0xe7cb3e16…` deployment) and Circle's `L2USDCBridge`
`0x7188b697…`. **No protocol recipients in the candidate set** — that is a result, not an omission.

### 5.6 Cronos zkEVM — 2 candidate txs, 2 recipients

Both plain EOAs, one tx each. All 56 protocol-message recipients are EOAs too (§3.5). All 30
decoded deposit beneficiaries are EOAs. No contracts anywhere on this chain in this dataset.

### 5.7 Sophon — 1 candidate tx, 1 recipient

The single candidate tx is a 0-value tester ping to address `0x0` (`is_system`). Sophon was
resolved first because of its wind-down; its RPC answered normally. The interesting result is in
the secondary set: **5 of its 194 deposit beneficiaries are ZKsync SSO smart accounts**
(`AccountProxy` → beacon `SsoBeacon` → `SsoAccount`), receiving 7 deposits.

### 5.8 OpenZK — 1 candidate tx, 1 recipient

Again a 0-value ping to `0x0` (`is_system`). Its secondary set is the notable part: **132 of
openzk's 141 decoded deposits (93.6%) land on `OzkVault`** `0x7cafe5e0218454abc86c78ba23b311e9a2412e49`
— an owner-controlled vault. Source is not verified, but its creation bytecode carries the revert
strings `"OzkVault: tx already sent"` and `"OzkVault: insufficient token amount"` and an
`owner()/transferOwnership()/withdraw(address,address,uint256)` surface. Confidence **medium**:
the name ties it to OpenZK, but no verified source or official registry entry was found.

---

## 6. Deposit beneficiaries (secondary set)

Reported separately so it can never inflate the candidate headline. 787 (chain, beneficiary)
pairs decoded from `finalizeDeposit` calldata, covering **2,924 of 3,064** canonical deposits
(the 140 undecoded v26 records are era's).

| beneficiary kind | beneficiaries | deposits |
|---|---|---|
| plain address | 713 | 2,629 |
| `smart-wallet` | 71 | 141 |
| `protocol-contract` | 3 | 154 |

The three protocol beneficiaries: **OpenZK `OzkVault`** (132 deposits), **Across
`ZkSync_SpokePool`** on era (19 deposits, all from the Across dataworker EOA), and **Domani
Protocol `RewardsManager`** on era (3 deposits from 3 distinct initiators). The 71 smart wallets
are 64 AGW accounts on abstract, 5 ZKsync SSO accounts on sophon, and 2 Safes on era.

This is where the deposit decode earns its place: "an EOA deposits a token into a protocol
contract" is invisible from the deposits' inner `to`, which is always the L2AssetRouter
`0x…10003` (verified for all 3,064).

---

## 7. Users driving L2 contracts from L1

The `other` class is a residual bucket of **15** records, and only **4 carry calldata**. That is
the true size of "a user sent a *call* from L1 to an L2 contract":

| chain | tx_id | to | selector | signature | value |
|---|---|---|---|---|---|
| era | 3301321 | `0x3355df6d…` USDC.e | `0x095ea7b3` | `approve(address,uint256)` | 0 |
| era | 3301322 | `0x5a7d6b2f…` ZK token | `0x095ea7b3` | `approve(address,uint256)` | 0 |
| era | 3301323 | `0x5aea5775…` WETH | `0x095ea7b3` | `approve(address,uint256)` | 0 |
| abstract | 26927 | `0xed68e191…` (unverified) | `0x64e7f93b` | unknown to openchain.xyz and 4byte.directory | 0.0163 ETH |

The three era `approve` calls all come from one L1 initiator
`0x000040d6c85a13a1aa74565fde87e499dc023c6f` within two minutes — one user approving three tokens
from L1 in a single session.

The remaining **11** records are `data_len = 0`, `value = 0` pings, not calls: **5** target
address `0x0` (abstract, sophon, zero, openzk, zkcandy — the cross-chain testers
`0x953a9df5…` and `0x58551793…`, removed by the system filter) and **6** are empty self-calls on
era where `to == l1_from`. Grouping those 11 by selector would yield 11 rows signed "unknown" that
are not calls at all. 4 + 11 = 15; the class reconciles.

---

## 8. Cross-chain patterns

**31 recipient addresses appear on ≥2 chains** (of 21,480 distinct), plus **11 of 775** deposit
beneficiaries. Every one is enumerated in `aggregates-l2.json:cross_chain`. The join is small
because the population is overwhelmingly one-shot.

The self-funding pattern the seed data flagged is confirmed and correctly sized.
`0xf70da97812cb96acdf810712aa562db8dfa3dbef` is the largest cross-chain recipient (230 txs):
rank 1 on era (94), rank 2 on abstract (133), and the rank-1 L1 *initiator* on both — it pays
itself. On zero it is marginal (3 txs of 257 recipients), so this is an era+abstract phenomenon,
not a three-chain one. It is a plain EOA on all three chains.

One address in the cross-chain list deserves a note:
`0x6f6426a9b93a7567fcccbfe5d0d6f26c1085999b` (abstract + era, 6 txs) is a plain EOA as a
recipient — and is also the deployer of abstract's `AGWAccount` implementation.

**Only one bytecode family spans chains**, and it is the `EmptyContract` at address `0x0`. No
wallet implementation and no protocol deployment is shared across these 8 chains in this dataset —
notable given they all run the same stack.

---

## 9. What this changes about the parent census

The parent census reported that "plain user activity (direct base-token transfers + canonical
deposits) accounts for ~59% of all records" and classified every tx on the **sender** axis only.
This phase resolved the recipient axis for the first time — no `eth_getCode` had ever been run
against an L2 RPC. Three corrections and confirmations:

1. **"~59% plain user activity" survives, with one qualification.** Of the 24,067 EOA-origin txs,
   24,043 (99.90%) went to a plain address or to the sender's own smart wallet — both are user
   activity. Only **24 txs (0.10%)** paid something that is not a user account. The share of the
   full 45,711-record census that this phase re-classifies away from "plain user activity" is
   **0.05%**. The parent's headline was right, and it is now measured rather than assumed.
2. **The recipient axis found a protocol the sender axis could not: Veno Finance.** The parent
   attributed 14 protocols, all from the sender side, and none of them is Veno. Its 19 txs look
   like ordinary `direct-transfer` records from the sender side because they *are* ordinary
   transfers — the protocol is on the receiving end. **Domani Protocol** (`RewardsManager`, 3
   deposits) and **OpenZK's `OzkVault`** (132 deposits) are likewise new, found only by decoding
   deposit beneficiaries. `labels-l2.json` records 368 new address labels and re-confirms 14 of
   the parent's 57 from the L2 side.
3. **A large slice of abstract's "user activity" is account-abstraction onboarding.** 865 of
   abstract's 3,273 candidate txs (26.4%) fund AGW smart accounts. That is still user activity by
   the Axis-B rule, but it is qualitatively different from an EOA-to-EOA transfer and the parent
   census had no way to see it.

Nothing in the parent's numbers is contradicted. One assumption in the *Phase 6 input package* is:
zkcandy is no longer unresolvable (§2.3), and the `protocol-message` control's expected outcome
was wrong for 4 of 8 chains (§3.5).

---

## 10. Caveats

- **Base-token semantics.** `value` is denominated in each chain's base token — ETH on era,
  abstract, zero, zkcandy; SOPH, GHO, zkCRO, ozETH elsewhere. The 8.167 and 36.481 figures in §5
  are ETH because era and abstract are ETH chains; **never sum value across chains.** 14 of the
  24,067 candidates carry `value = 0`.
- **One code-time verdict covers all of a recipient's txs.** Only the earliest tx is dated. Here
  the error term is provably empty: `contract-later` is 0, so there are **0 straddling recipients
  and 0 straddling txs**. Had any recipient been deployed mid-window, its later txs would have
  been wrongly excluded from the headline; none was.
- **The block−1 probe under-states, never inflates.** A contract deployed *earlier in the same
  block* as its funding tx reads as codeless, so `contract` is a lower bound. A per-tx-index probe
  is not available over JSON-RPC.
- **The `eoa` bucket is a latest-block verdict for everything the control did not sample.** The
  control covered 1,298 of 21,211 `eoa` recipients (6.1%) — all of cronos, lens, openzk, sophon
  and zero, plus 400 each on era and abstract — and found 0 contradictions. A recipient that had
  code when paid and self-destructed since would be silently filed as `eoa`; nothing in the
  sample behaved that way, but the remaining 93.9% rest on the latest-block test.
- **zkcandy's verdicts come from a different instrument.** See §2.3 for the validation (208/208
  on era) and the three declared limitations: no bytecode/families, no EIP-7702 detection, and
  genesis contracts reading as codeless.
- **140 era deposits are undecoded** (v26 selector), so deposit-side coverage is 95.4%, not 100%.
- **`codehash` here is sha256 of the lowercased code hex** — a clustering key only, **not** the
  EVM keccak codehash.
- **Confidence semantics** (unchanged from `../results/REPORT.md` §5): **high** = both sides
  verified on-chain/source or an exact registry match; **medium** = verified name on one side,
  project inferred; **low** = name-only or single tx. One attribution is medium (OpenZK
  `OzkVault`, §5.8) and one contract is explicitly unattributable (§4); everything else is high.

---

## 11. Appendix — data files

| File | Contents |
|---|---|
| `aggregates-l2.json` | every number cited above, incl. 10 self-checking reconciliation assertions |
| `REPORT-L2.md` | this document |
| `run-manifest-l2.json` | endpoints + the `eth_chainId` each returned, substitutions, archive probes, code-cache blocks, call counts, script hashes, deviations |
| `families.json` | the 13 bytecode families with members, tx counts, implementations, attribution, evidence |
| `labels-l2.json` | merged address→label registry: 57 inherited + 368 new + 14 confirmed = 425. `../results/scripts/labels.json` is **not** modified |
| `recipients/<chain>.jsonl` | one row per distinct candidate recipient (the analytical unit) |
| `recipients-deposits/<chain>.jsonl` | the same for decoded deposit beneficiaries, kept separable |
| `txs/<chain>.jsonl` | one row per candidate tx, joining back to `../results/enriched/` on `(chain, tx_id)` |
| `code/<chain>.json` | resolver cache: address → code verdict, one block per file |
| `code-pm/<chain>.json` | the same for the `protocol-message` control set |
| `codetime/<chain>.json` | code-at-tx-time verdicts, dated at `blockNumber − 1` |
| `codetime-pm/`, `codetime-eoa-control/` | control-set and METHOD §3 `eoa`-control verdicts |
| `seed/zkcandy-method-validation.json` | the era cross-validation and zkcandy positive control |
| `seed/proxy-slots.json`, `seed/contract-names.json` | ERC1967 slot reads; explorer-verified names |
| `scripts/` | `reproduce_ground_truth.py`, `resolve_zkcandy_explorer.py`, `fetch_contract_names.py`, `build_outputs.py`, `write_manifest.py`, `write_labels.py`, `attribution.json` |
