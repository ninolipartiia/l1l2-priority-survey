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
at today's chain tip. Of those 889, **865 (97.3%) went to a user-controlled smart-contract
wallet** — 864 to Abstract Global Wallet accounts on abstract, 1 to a Safe on era — and only
**24 txs (0.10% of the whole candidate set) reached something that is not a user account**: 19 to
**Veno Finance**'s `BridgeReceiver` on era (7.167 ETH of liquid-staking flow), 4 to token
contracts (USDC.e, ZK, WETH on era), and 1 to a single unverified private contract on abstract.
A further **4 txs** were bytecode publications addressed to the reserved address `0x0`
(`is_system`, excluded from the 889; see §3.1). The remaining **23,174 txs (96.3%) paid a plain codeless address**. 23,174 + 889 + 4 =
24,067.

**Two of those 889 txs reverted on L2.** Receipts were fetched for all 893 contract-recipient
candidate txs during review: 891 succeeded, and 2 failed with `status 0x0` — era tx 3294649
(0.001 ETH to the ZK token) and abstract tx 26927 (0.0163 ETH to the unattributed contract). A
priority request is counted by the census when it is *requested*, so those two are correctly
inside the 24,067 and inside the 889 "paid an address with code"; but the value was **not
delivered**, and every ETH figure below is requested value unless stated otherwise. All 19 Veno
txs and all 3 era `approve` calls succeeded.

On "user-controlled": the wallets are AGW/Safe smart accounts, which is established (§4). That
the *payer* owns the wallet they funded is an **inference, not a measurement** — no output here
proves the link, and 10 of the 294 AGW accounts were funded by 2–4 distinct L1 initiators. What
the data supports is the load-bearing claim: these are user accounts, not protocol contracts.

So the honest headline is: **genuine protocol interaction in the EOA-origin set is one protocol
and 19 transactions.** The "EOA → contract" number is real but it is almost entirely *users
funding smart accounts*: reporting it without the Axis-B split would present 889 txs as
protocol usage where 19 of them are — a 47× overstatement.

**Coverage is complete — there are no unresolved denominators**, with one instrument caveat
stated up front. All **22,162 (chain, address) lookups** got a verdict; **0** are
`unresolvable`, `contract-later`, `delegated-eoa` or `code-time-unverified`. The `delegated-eoa`
zero is a genuine measurement on the 7 RPC chains but **not** on zkcandy's 1,256 addresses
(5.7% of the workload): the explorer substitute reads creation records, and an EIP-7702
delegation is code without one, so zkcandy's delegated-eoa count is **unknown, not zero**.

That zkcandy is resolved at all is the surprise: the input package expected it to be
unresolvable. Its RPC is still dead, but its **block explorer is alive again** and served all
1,251 recipients + 10 deposit beneficiaries (§2.3). zkcandy has **zero contract recipients
outside the reserved range** — the one exception is address `0x0`, which *does* have code on
zkcandy and *is* one of the 1,251 (the bytecode publication, tx_id 6348); it carries `is_system`
and sits in the `eoa` bucket because the creation-record method cannot see genesis contracts.

Three secondary results:

- **The counterfactual-deployment trap did not bite anywhere.** All 371 contract
  (chain, address) pairs already had code at `funding_block − 1`; `contract-later` is **0**, so the error term METHOD §4
  exists to size is empty (0 straddling recipients, 0 straddling txs).
- **The `eoa` bucket held up under its control.** 1,298 addresses across 7 chains that are
  codeless today were also codeless when they were paid; **0** contradictions. (Those 1,298 are
  drawn from the code caches, so only 1,011 of them are candidate `eoa` recipients — §10 sizes
  the coverage honestly.)
- **The `protocol-message` control's outcome depends on which axis you measure**, and both are
  reported (§3.5): tx-weighted the package's expectation *holds* (18,282 of 18,580 txs, 98.4%,
  went to contracts), but recipient-weighted it *fails* (16 of 172 recipients, 9.3%). On cronos,
  openzk, abstract and zero *every* protocol-message recipient is a plain EOA. That is structural,
  not a broken method: the class is defined by the **sender** being a contract, and on the small
  chains that sender is a deposit-wrapper contract crediting a user address.

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
than at most 341 (`report_figures.era_beneficiaries_if_v26_were_decoded_upper_bound`), the
workload total is 22,162 rather than larger, and the deposit-side coverage in §6 is **2,924 of
3,064** canonical deposits (95.4%).

### 2.2 How code-time was proven

`eth_getCode(recipient, blockNumber − 1)` of the recipient's earliest in-window tx — the block
**before** the funding tx, because `getCode(N)` returns end-of-block-`N` state and would include
a deployment done later in the same block. All 7 live endpoints serve full archive state; the
probe is in `run-manifest-l2.json`. On cronos and zero it is more than a smoke test:
`eth_getCode(0x…10003)` returns a *different* code size at tip−1M (39,392 B) than at the tip
(42,528 B), which proves genuine historical state rather than a silent latest-block fallback.
For the other five the recorded probe shows only that the call was *served* at depth — which a
latest-block fallback would also do. The stronger evidence that they are genuinely archival is
indirect but decisive: had any of them silently answered at the tip, every contract recipient
would have read as `contract` and `contract-later` would be 0 **by construction**. An independent
re-test during review confirmed real historical state on era, abstract, sophon, lens and openzk
(`eth_getCode(<contract>, 0x1)` returns `0x` while `latest` returns code).

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

**Validated, and the validation was rebuilt after review** (`seed/zkcandy-method-validation.json`).
The original argument leaned on a cross-validation against era — 208/208 agreement between
`eth_getCode` and the same explorer call — on the premise that "era has the same explorer API".
**That premise is false.** zkcandy runs Blockscout; era runs matter-labs/block-explorer. They
differ in routes, response schema, address cap (10 vs 5) and over-cap behaviour, and — decisively
— they differ *precisely* on this method's one blind spot: era's explorer returns creation records
for genesis contracts, zkcandy's does not. The era run therefore had no power over the failure
mode that actually exists here. It is retained for transparency (and was independently reproduced
at 208/208 with a fresh sample) but it is no longer load-bearing.

What earns the verdict instead is zkcandy-side evidence:

1. **Complete enumeration.** `listcontracts` returns the chain's entire contract population —
   **314 addresses**, page 2 empty. Intersected with the census's 1,256 addresses, the only
   member is `0x0`. This does not depend on the substitute method being sensitive at all: if no
   census address is a contract on the chain, no verdict can be a false negative.
2. **Recall measured exhaustively, not sampled.** Running `getcontractcreation` over all 314
   known contracts finds 294 and misses 20 — **291/291 on non-system contracts, 0/20 on
   genesis**, every miss inside the reserved range.
3. **A second, independent instrument, run exhaustively.** Blockscout also serves
   `/api/v2/addresses/{addr}` with a direct `is_contract` flag — a truer `eth_getCode` equivalent
   than a creation record. An independent auditor ran it over **all 1,256 census addresses**: 0
   unresolved and **exactly one `is_contract: true`**, namely `0x0`. That is the declared genesis
   limitation showing up exactly where it should, and nowhere else. (A separate 184-address
   sample by this phase's author agreed on all 174 that answered.) The same audit re-verified 204
   addresses one at a time against the batched verdicts with 0 disagreements, and checked 30
   canonical hashes against the census with 0 field mismatches.

Chain identity was established without `eth_chainId`, which this endpoint cannot serve: the
explorer indexes the census's canonical hashes with matching `to`/`from`/`value`, and those
hashes come from `NewPriorityRequest` logs on the L1 diamond
`0xf2704433d11842d15aa76bbf0e00407267a99c92`, whose `getChainId()` returns `0x140` = 320.

One API trap was load-bearing: `contractaddresses` caps at **10** and, above it, **silently
truncates to the first 10** while still answering `status:1 "OK"`. A caller chunking at 60 would
get no record for addresses 11–60 and mint confident false "EOA" verdicts for 83% of every chunk.
The script hard-caps at 10 and asserts every returned address was one it asked for. (This report
previously described the over-cap behaviour as returning results for *none* of them — a
misdiagnosis from a probe that put the only contract in position 11, i.e. exactly the address
truncation removes. era's API caps at 5 and fails loudly with `status:0 NOTOK`.)

**Declared limitations of the substitute:**

1. **No bytecode — from the endpoint chosen, not from the host.** zkcandy contributes no
   `code_len`, no `codehash` and therefore **no bytecode families**. This was previously stated
   as a property of the instrument; it is not. The same Blockscout host serves
   `/api/v2/smart-contracts/{addr}` with `deployed_bytecode`, so the capability was available and
   the run did not use it. Moot for the headline — there are no contract recipients to cluster —
   but the earlier claim was wrong.
2. **EIP-7702 is undetectable** — a delegation is code, not a creation record. zkcandy's
   `delegated-eoa` count is **unknown, not zero**.
3. **Genesis contracts have no creation record** and read as codeless — 20 of the chain's 314
   contracts, every one inside the reserved range METHOD §3 flags `is_system`, so no user-chosen
   counterparty can be mis-filed. Correct examples are `0x0`, `0x…8006`, `0x…800a`, `0x…800b`,
   `0x…8014`, `0x…10000`. (An earlier draft cited `0x…8007`, `0x…10002` and `0x…10005`; those are
   not contracts on zkcandy at all, so they return nothing merely because they are codeless.)
   This is why address `0x0` sits in zkcandy's `eoa` bucket while it is `contract` on abstract,
   sophon, zero and openzk — the only known divergence between the two methods, and `is_system`
   on both sides.
4. **Four further limitations**, added after review: `getcontractcreation` cannot distinguish
   "indexed, no code" from "never indexed" (closed empirically here — all 1,256 are known to the
   indexer); the verdict is at the explorer's tip with indexer lag rather than at a pinned block;
   zkcandy has **no `eoa`-control coverage at all**, so the one chain resolved by a substitute is
   the one chain with no negative control; and METHOD §3's self-destruct worry is *inapplicable*
   on a ZK-stack chain, which has no `SELFDESTRUCT`.

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
reserved addresses — address `0x0` on abstract, openzk, sophon, zero and zkcandy. Four of them
sit in the `contract` bucket (224 bytes of `EmptyContract` code) and one in `eoa` (zkcandy, per
§2.3). They are excluded from the headline and never given an `actor_type`.

**These 5 are bytecode publications, not calls and not pings.** All five have `data_len = 0` and
`value = 0`, but the payload is not absent — it travels in `factoryDeps`, which the census does
not decode. The L1 side is identical on all five: `Bridgehub`
`0x303a465b659cbb0ab36ee643ea362c509eeb5213`, selector `0xd52471c1`
(`requestL2TransactionDirect`), 7,652 bytes of calldata carrying a single 7,200-byte EraVM
contract, and an L2 gas limit of 72,000,000 — two orders of magnitude above the 500–800k a real
empty ping requests (§7). The L2 receipts confirm the effect: each emits a `KnownCodesStorage`
(`0x…8004`) `MarkedAsKnown` log for bytecode hash
`0x010000e1188404f17e87c75fc34cf3500754091f43168ccb2d9d7890598ed5b6`, and sophon tx 9599 burns
265,068 gas on what would otherwise be a no-op call to an empty contract. Two senders account for
all five — `0x58551793…` (abstract, sophon) and `0x953a9df5…` (openzk, zero, zkcandy) — publishing
the same bytecode across five chains. Sending to `0x0` is incidental to the mechanism: the
publication happens whatever the `to` field says. The `is_system` filter and the bucket
assignments above are unaffected; only the description of what these txs do is at issue.

**Headline, system-filtered: 889 txs to 300 contract recipients.**

### 3.2 Smart wallet vs. protocol — the split that matters

| `actor_type` | recipients | txs | share of the 24,067 |
|---|---|---|---|
| `smart-wallet` | 295 | 865 | 3.59% |
| `protocol-contract` | 1 | 19 | 0.079% |
| `token` | 3 | 4 | 0.017% |
| `unknown-contract` | 1 | 1 | 0.004% |
| **total** | **300** | **889** | **3.69%** |

Collapsing Axis B would turn 865 txs of *users funding AGW smart accounts* into "protocol
usage": 889 txs presented as protocol interaction where 19 actually are, a **47×** overstatement.
The distinction is not a technicality — an AGW account is a user's wallet, not a protocol's
contract, whoever funded it.

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

**Self-funding is a major EOA pattern and is entirely absent among contracts.** 4,354
recipients — 20.5% of the 21,211 `eoa` recipients, carrying 6,239 txs (25.9% of all candidate
txs) — are addresses that also appear as an `l1_from` on the same chain —
the user paying themselves across the bridge. **Zero** of the 300 contract recipients do this,
which is the expected signature of a counterfactual smart account: the wallet address is not the
key that signs on L1.

### 3.4 The three hypotheses, decided

- **H1 — "recipients are overwhelmingly plain EOAs": CONFIRMED, and more strongly than the seed
  data suggested.** 21,211 of 21,515 (98.6%) recipients and 23,174 of 24,067 txs (96.3%) are plain
  addresses. era, which carries 79% of the candidate traffic, has **5 contract recipients out of
  18,325**.
- **H2 — "contract recipients cluster into a few bytecode families dominated by smart wallets, not
  protocols": CONFIRMED.** 352 of the 371 contract (chain, address) pairs (95%) are one family,
  AGW — 371 pairs are 368 distinct addresses, since `0x0` recurs on 4 chains — and it is
  a smart-account family. Across the whole dataset, `smart-wallet` outweighs `protocol-contract`
  by 865 txs to 19.
- **H3 — "genuine protocol interactions are rare and concentrated on era/abstract": CONFIRMED for
  era, REFUTED for abstract.** There is exactly one protocol recipient in the candidate set —
  Veno Finance on era, 19 txs. Abstract, despite holding 97% of the EOA→contract flow, has
  **zero** protocol-contract recipients: its whole contract population is user wallets.

### 3.5 The `protocol-message` control

The package predicted the control's recipients "should be overwhelmingly contracts; if not,
something is wrong with the method." **Which axis you measure decides the answer**, and the
report states both rather than picking the flattering one:

- **tx-weighted the expectation HOLDS**: 18,282 of 18,580 control txs (98.4%) went to a contract.
- **recipient-weighted it FAILS**: only 16 of 172 distinct control recipients (9.3%) are
  contracts.

Nothing is wrong with the method; the two axes are measuring different things.

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
deposit-wrapper contract (`ZkCroMintAndBridge`, `BridgeMiddleware`, `BridgeHubWrapper`) crediting
a user address. All 298 of those records have `data_len ≤ 2` and non-zero value, and **293 of the
298 have `to == l1_from`** — the depositor crediting themselves. The 5 that do not are the same
wrapper flow crediting a *third-party* address: zero tx_id 4907, cronos 4774, and sophon 9467,
9999 and 10181. The control therefore confirms the method rather than failing it, and it
incidentally corrects a reasonable-looking assumption in the input package.

All 16 contract recipients in the control set were code-time verified: 16/16 `contract`.

---

## 4. Bytecode families

A family is a set of recipients whose `getCode` output is byte-identical, keyed by the sha256 of
the lowercased code hex — a **clustering key, not the EVM keccak codehash**. 13 families cover all
371 contract **(chain, address) pairs** — 368 distinct addresses, since `0x0` recurs on 4
chains — across the candidate and deposit-beneficiary sets. The **control set is not clustered
here**: its 16 contract recipients contribute 14 further addresses and 13 further codehashes that
appear in no family, including both Across `Lens_SpokePool` deployments and Circle's lens
`L2USDCBridge`. They are attributed individually in §3.5, §5.5 and `labels-l2.json`.

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

**The one contract with no project attribution.** abstract
`0xed68e19181108758d17c2b1992a5e6b46a60f7d5`, 51,936 bytes, 1 tx (0.0163 ETH requested — the tx
**reverted**, so nothing was delivered). Tried and failed: source is not verified on abstract's
explorer; no ERC1967 impl/beacon/admin slot is set; `name()`/`symbol()` return nothing; its
selector `0x64e7f93b` is unknown to both openchain.xyz and 4byte.directory.

Its **function**, however, is identifiable, and calling it simply "unattributable" understated
what the calldata shows. The `0x64e7f93b` argument list carries pool addresses and tick bounds:
`0x157beaa1c7dcc2aad79846ec693c558609ebc0ea` answers `factory()` =
`0xa1160e73b63f322ae88cc2d8e700833e71d0b2a1`, whose verified name on abstract is
`contracts/UniswapV3Factory.sol:UniswapV3Factory`, with `token0()` = the verified `WETH9`. So it
is an automated **Uniswap-V3 concentrated-liquidity position manager**. `actor_type` stays
`unknown-contract` because Axis B asks *whose* contract it is and that is still unknown — it was
created by `0x94a8ce783060c8e519ca85fe2de8068bf3917d22`, the only address that has ever called it
(3 calls) and the only L1 initiator that paid it, i.e. one user's private bot rather than shared
infrastructure.

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
code, carrying 24 txs and **8.167 ETH requested / 7.166 ETH delivered** — era tx 3294649
(0.001 ETH to the ZK token) reverted.

| address | txs | actor_type | identity |
|---|---|---|---|
| `0x9cb1e077e7253a4f022e74862a93ee7cecab788b` | 19 | `protocol-contract` | **Veno Finance** `BridgeReceiver` |
| `0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e` | 2 | `token` | ZK token — one 0-value `approve`, one reverted transfer, so it received nothing |
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
3,273 txs (26.4%)**, 36.481 ETH requested / 36.465 ETH delivered (abstract tx 26927 reverted).
But **864 of those 865 are AGW smart
wallets**, so abstract's number is a measure of *account-abstraction onboarding*, not protocol
usage: 305 distinct L1 initiators funded 294 AGW accounts. Abstract has **zero**
protocol-contract recipients in the candidate set.

Ranks 2, 3, 4 and 7–10 of abstract's recipients are plain self-funding EOAs; ranks 1, 5 and 6 are
AGW wallets. The family is a bytecode fact, not a head-of-distribution fact.

### 5.3 zkcandy — 1,396 candidate txs, 1,251 recipients

**Zero contract recipients outside the reserved range.** Of the 1,251 recipients and 10 deposit
beneficiaries, exactly one — address `0x0`, the bytecode-publication target (§3.1) — has code on
zkcandy; it is `is_system` and therefore excluded from every protocol claim, and sits in the
`eoa` bucket because the creation-record method cannot see genesis contracts (§2.3). The other
1,255 are plain addresses, established three ways: the chain's complete contract population
(314 addresses) intersects the census set only at `0x0`; the method's recall on non-system
contracts is 291/291; and an independent `is_contract` instrument agreed on every one of 174
sampled addresses. This chain was expected to be unresolvable and is now fully resolved.

Caveat that survives: EIP-7702 delegations are invisible to the substitute, so zkcandy's
`delegated-eoa` count is unknown rather than zero — and this is not idle, since **96 of the 1,256
addresses carry a `0xef0100` delegation on Ethereum L1**. No sampled address showed a Blockscout
`eip7702` proxy type, but there is no positive control, so "unknown" stands.

### 5.4 ZERϴ Network — 339 candidate txs, 257 recipients

256 plain EOAs plus address `0x0` (224 bytes, `is_system`, the bytecode-publication target,
§3.1) — the seed data's finding reproduced exactly, including the code-time proof (funding tx in
`0x34ad52`, probed at `0x34ad51`). No protocol recipients. The full 269-address `eoa` control ran
here with 0 contradictions.

### 5.5 Lens — 11 candidate txs, 2 recipients

Both plain EOAs; one received 10 of the 11 txs. Lens's real traffic is the control set: 4,376
protocol-messages, 100% to contracts — Across's `Lens_SpokePool` (both the current
`0xb234ca48…` and the initial `0xe7cb3e16…` deployment) and Circle's `L2USDCBridge`
`0x7188b697…`. **No protocol recipients in the candidate set** — that is a result, not an omission.

### 5.6 Cronos zkEVM — 2 candidate txs, 2 recipients

Both plain EOAs, one tx each. All 56 protocol-message recipients are EOAs too (§3.5). All 30
decoded deposit beneficiaries are EOAs. No contracts anywhere on this chain in this dataset.

### 5.7 Sophon — 1 candidate tx, 1 recipient

The single candidate tx (tx_id 9599) is a bytecode publication addressed to `0x0` (`is_system`,
§3.1) — it succeeded on L2 with `status 0x1`, burning 265,068 gas. Sophon was
resolved first because of its wind-down; its RPC answered normally. The interesting result is in
the secondary set: **5 of its 194 deposit beneficiaries are ZKsync SSO smart accounts**
(`AccountProxy` → beacon `SsoBeacon` → `SsoAccount`), receiving 7 deposits.

### 5.8 OpenZK — 1 candidate tx, 1 recipient

Again a bytecode publication addressed to `0x0` (`is_system`, §3.1). Its secondary set is the
notable part: **132 of openzk's 141 decoded deposits (93.6%) land on `OzkVault`**
`0x7cafe5e0218454abc86c78ba23b311e9a2412e49`
— an owner-controlled vault. Source is not verified, but its creation bytecode carries the revert
strings `"OzkVault: tx already sent"` and `"OzkVault: insufficient token amount"` and an
`owner()/transferOwnership()/withdraw(address,address,uint256)` surface. The project link is not
just the name: live `owner()` returns `0xee65cca8fe8f2f657c05755779fcad29348c76e2`, which the
**parent census independently attributed** — from the sender side, in a separate investigation —
as "OpenZK BridgeMiddleware main L2 recipient / L1 deposit initiator". Confidence **medium**
(METHOD §7: "verified name on one side, project inferred"): the contract's own identity is solid
and the OpenZK link is corroborated by its owner, but the source is not verified on OpenZK's
explorer and no public disclosure of "OzkVault" exists. Two reviewers split low-vs-medium on this
during review; the `owner()` corroboration is what settles it. This is the deliverable's only
non-`high` attribution.

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
| abstract | 26927 | `0xed68e191…` (unverified) | `0x64e7f93b` | unknown to openchain.xyz and 4byte.directory; a Uniswap-V3 position call by function (§4) | 0.0163 ETH — **reverted** |

The three era `approve` calls all come from one L1 initiator
`0x000040d6c85a13a1aa74565fde87e499dc023c6f` within two minutes — one user approving three tokens
from L1 in a single session; all three **succeeded**. The fourth record, abstract 26927, is the
only L1-initiated *call* to a non-token L2 contract in the whole window, and it **reverted** —
so on the strictest reading, the number of successful user-driven L2 contract calls from L1 in a
year across 8 chains is **3, all of them `approve`**.

The remaining **11** records all carry `data_len = 0` and `value = 0`, so none of them is a call —
but they are two different things, not one. **5** target address `0x0` (abstract, sophon, zero,
openzk, zkcandy, from `0x953a9df5…` and `0x58551793…`, removed by the system filter) and are
**bytecode publications**, carrying a 7,200-byte contract in `factoryDeps` rather than in calldata
(§3.1) — empty calldata, but not empty transactions. The other **6** are genuine empty pings:
self-calls on era where `to == l1_from`, sent via `requestL2Transaction` with 292 bytes of L1
calldata, no `factoryDeps`, and 500–800k L2 gas limits. Grouping those 11 by selector would yield
11 rows signed "unknown" that are not calls at all. 4 + 11 = 15; the class reconciles.

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
against an L2 RPC. Four corrections and confirmations:

1. **"~59% plain user activity" survives, but the correction is larger than the candidate set
   alone suggests.** The parent's bucket is `direct-transfer` (24,052) + `canonical-deposit`
   (3,064) = **27,116 records, 59.32% of 45,711**. Two slices come out of it:

   - **20 `direct-transfer` txs** paid a contract that is not a user account (19 Veno + 1 token;
     the other 4 of the 24 in §1 are `other`-class records, which were never inside the parent's
     bucket).
   - **154 canonical deposits** were delivered to a protocol contract — OpenZK's `OzkVault`
     (132), Across's era `ZkSync_SpokePool` (19) and Domani's `RewardsManager` (3). These are
     squarely inside the parent's 59% and are only visible once the `finalizeDeposit`
     beneficiary is decoded (§6).

   Total re-classified: **174 records = 0.38% of the census, 0.64% of the parent's bucket** — not
   the 0.05% a candidate-set-only reading gives. The parent's headline still stands (99.36% of
   that bucket really is plain user activity), but the honest correction is ~8× the figure the
   candidate set alone would suggest, and the deposit half of it is the larger half.
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
4. **Three of the parent's own attributions are re-confirmed from the opposite side.** Across's
   era `ZkSync_SpokePool`, Circle's lens/sophon `L2USDCBridge` and the ZK token were all found
   independently here as recipients, matching the parent's sender-side labels exactly — a useful
   cross-check that the two axes agree where they overlap.

Nothing in the parent's numbers is contradicted — the 174 records above are a *refinement* of a
bucket the parent measured correctly, not an error in it. Two assumptions in the *Phase 6 input
package* did not survive: zkcandy is no longer unresolvable (§2.3), and the `protocol-message`
control's expected outcome holds only tx-weighted, failing on the recipient axis and failing
outright on 4 of 8 chains (§3.5).

---

## 10. Caveats

- **Base-token semantics.** `value` is denominated in each chain's base token — ETH on era,
  abstract, zero, zkcandy; SOPH, GHO, zkCRO, ozETH elsewhere. The 8.167 and 36.481 figures in §5
  are ETH because era and abstract are ETH chains; **never sum value across chains.** 14 of the
  24,067 candidates carry `value = 0`.
- **Value figures are REQUESTED, not delivered, unless stated.** The census counts a priority
  transaction when it is requested on L1; its L2 execution can still revert. Receipts for all 893
  contract-recipient candidate txs were checked during review and 2 reverted (§1), which is why
  §5.1 and §5.2 give both figures. The other 23,174 txs — those paying codeless addresses — were
  **not** receipt-checked; a plain value transfer to an address with no code has nothing to
  revert in, but this is an argument, not a measurement.
- **Eight of the 371 code-time probes are dated from a record that is not the earliest
  *candidate* tx** (an earlier deposit or contract-origin transfer to the same address). The bias
  is one-directional and conservative — it probes strictly earlier, a harder test to pass — so no
  verdict is affected.
- **"EOA-origin" is the input package's term, inherited.** It means `class ∈ {direct-transfer,
  other}`, i.e. inner `from == l1_from`, which METHOD §5 makes authoritative. On the parent
  census's separate `initiator_is_contract` flag, 1,189 of the 24,067 initiators carry code on L1
  (EIP-7702 delegated accounts); they are still user accounts, but a reader should not take
  "EOA-origin" to mean "the L1 sender provably had no code".
- **One code-time verdict covers all of a recipient's txs.** Only the earliest tx is dated. Here
  the error term is provably empty: `contract-later` is 0, so there are **0 straddling recipients
  and 0 straddling txs**. Had any recipient been deployed mid-window, its later txs would have
  been wrongly excluded from the headline; none was.
- **The block−1 probe under-states, never inflates.** A contract deployed *earlier in the same
  block* as its funding tx reads as codeless, so `contract` is a lower bound. A per-tx-index probe
  is not available over JSON-RPC.
- **The `eoa` bucket is a latest-block verdict for everything the control did not sample.** The
  control ran on **1,298 addresses** across 7 chains and found 0 contradictions — but those
  addresses come from the *code caches*, i.e. the union of candidate recipients and deposit
  beneficiaries, so they are not all candidate recipients. Only **1,011 of the 21,211 candidate
  `eoa` recipients (4.8%)** were covered; **95.2% rest on the latest-block test**. Per chain the
  candidate `eoa` recipients covered are: era 398, abstract 353, zero 256 (all of them), lens 2
  (all), cronos 2 (all), **sophon 0 and openzk 0** — those two chains have no candidate `eoa`
  recipient at all (their single candidate recipient is `0x0`), so their 189 and 4 control
  entries are entirely deposit beneficiaries. zkcandy is not covered by this control. A recipient
  that had code when paid and self-destructed since would be silently filed as `eoa`; nothing in
  the sample behaved that way.
- **zkcandy's verdicts come from a different instrument.** See §2.3 for the validation (208/208
  on era) and the three declared limitations: no bytecode/families, no EIP-7702 detection, and
  genesis contracts reading as codeless. Two schema consequences: `code/zkcandy.json` carries the
  sentinel `"block": "latest-via-explorer"` where OUTPUT_SPEC §1 requires a concrete block number
  (there is none — the explorer answers about creation records, not about a block), and
  `code_len` is `null` rather than `0` on all 1,251 zkcandy rows, so that field is not comparable
  across chains. Both are recorded as deviations in `run-manifest-l2.json`.
- **140 era deposits are undecoded** (v26 selector), so deposit-side coverage is 95.4%, not 100%.
- **`codehash` here is sha256 of the lowercased code hex** — a clustering key only, **not** the
  EVM keccak codehash.
- **Confidence semantics** (unchanged from `../results/REPORT.md` §5): **high** = both sides
  verified on-chain/source or an exact registry match; **medium** = verified name on one side,
  project inferred; **low** = name-only or single tx. One attribution is **medium** (OpenZK
  `OzkVault`, §5.8) and one contract has no project attribution at all — though its *function* is
  identified (§4); everything else is high.

---

## 11. Appendix — data files

| File | Contents |
|---|---|
| `aggregates-l2.json` | every number cited above, incl. 10 self-checking reconciliation assertions |
| `REPORT-L2.md` | this document |
| `run-manifest-l2.json` | endpoints + the `eth_chainId` each returned, substitutions, archive probes, code-cache blocks, call counts, script hashes, deviations |
| `families.json` | the 13 bytecode families with members, tx counts, implementations, attribution, evidence |
| `labels-l2.json` | merged address→label registry: the parent's **57** entries + **368** found only from the L2 side = **425**. 14 of the 57 were independently re-verified here and are marked `confirmed` (they are a subset of the 57, not a third addend); their parent label text is preserved. `../results/scripts/labels.json` is **not** modified |
| `recipients/<chain>.jsonl` | one row per distinct candidate recipient (the analytical unit) |
| `recipients-deposits/<chain>.jsonl` | the same for decoded deposit beneficiaries, kept separable |
| `txs/<chain>.jsonl` | one row per candidate tx, joining back to `../results/enriched/` on `(chain, tx_id)` |
| `code/<chain>.json` | resolver cache: address → code verdict, one block per file |
| `code-pm/<chain>.json` | the same for the `protocol-message` control set |
| `codetime/<chain>.json` | code-at-tx-time verdicts, dated at `blockNumber − 1` |
| `codetime-pm/`, `codetime-eoa-control/` | control-set and METHOD §3 `eoa`-control verdicts |
| `seed/zkcandy-method-validation.json` | the era cross-validation and zkcandy positive control |
| `seed/proxy-slots.json`, `seed/contract-names.json` | ERC1967 slot reads; explorer-verified names |
| `scripts/` | `reproduce_ground_truth.py`, `resolve_zkcandy_explorer.py`, `fetch_contract_names.py`, `build_outputs.py`, `write_manifest.py`, `write_labels.py`, `check_acceptance.py`, `attribution.json` |
