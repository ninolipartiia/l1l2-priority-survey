# METHOD — resolving and attributing the L2-side recipient

## 1. Inputs and join keys

| Input | Use |
|---|---|
| `../results/enriched/<chain>.jsonl` | the 45,711 classified records; source of `to`, `class`, `selector`, `value`, `ts`, `canonical_hash`, `tx_id` |
| `../results/scripts/labels.json` (57 entries) | seed address→label registry to extend |
| `../KNOWN_ADDRESSES.md` §"Fixed L2 system addresses" | the system-contract addresses to filter out |
| `../CHAINS.md` | L2 RPCs, chain ids, explorers |

Join key for everything produced here: **`(chain, tx_id)`** per tx and **`(chain, address)`**
per recipient. `tx_id` is unique per chain and already deduped in the census.

Fields consumed from each record: `to` (the literal L2 recipient — **never un-alias it**;
aliasing applies to `from` only), `class`, `selector`, `value`, `ts`, `canonical_hash`
(needed to find the L2 block in §4), and `data` for the deposit decode below.

**Deposit beneficiary decode.** For `class = canonical-deposit` with selector `0xcfe7af7c`
= `finalizeDeposit(address l1Sender, address l2Receiver, address l1Token, uint256 amount,
bytes data)`, the beneficiary is the 2nd ABI word: `data[98:138]` on the hex string
(implemented once, in `scripts/resolve_l2_code.py:beneficiary_of`, and imported by
`check_code_time.py` so the two scripts cannot drift). The word's high 12 bytes must be zero
padding; anything else is not an address and is skipped rather than truncated into one.

The 140 era records with the v26 selector `0x9c884fd1` =
`finalizeDeposit(uint256,bytes32,bytes)` carry the receiver inside the nested `bytes` blob.
**They are out of scope for the shipped resolver** and are reported as a counted skip on
stderr on every run (`!! 140 canonical-deposit record(s) contributed no address: …`), so
under-coverage is never mistaken for complete coverage. `deposit_records_not_decoded` in
`seed-data/ground-truth.json` carries the figure per chain. Decoding them is a legitimate
extension — it would add beneficiaries and change `address_lookups`, so recompute the
workload table if you do it, and say so in the report either way.

## 2. Resolving code status

`eth_getCode(<recipient>, <block>)` on the **chain's own L2 RPC** (`../CHAINS.md`). Empty
result (`0x`) ⇒ no code at that block. On ZK-stack chains plain EOAs are served by the
system `DefaultAccount` and have **no deployed code**, so this is a valid EOA test.

- Batch JSON-RPC works and is ~60× faster than serial: verified on era, abstract, lens and
  zero (2026-08-26). `resolve_l2_code.py` batches ≤60 per request, checkpoints the cache
  every 10 batches (the file is rewritten in full, so saving after each one is O(n²) I/O on
  era), and retries only the addresses a batch reply actually missed.
- Cache per chain, keyed by lowercase address, storing `{len, kind, codehash, block}` where
  `codehash` is **sha256 of the returned code hex, lowercased first** — a clustering key
  only, not the EVM keccak codehash; label it as such if published. Lowercasing is not
  cosmetic: endpoints differ in hex case, families are joined *across* chains and therefore
  across endpoints (§5), and an un-normalised hash would silently split one family in two.
- `block` records which block the verdict is for, always as a **concrete block number**: a
  moving tag is resolved through `eth_blockNumber` before anything is written, because a
  cache full of the literal string `"latest"` makes the one-block-per-file rule
  unenforceable — era takes hundreds of batches, and a run resumed the next day would merge
  two chain tips while the guard compared `"latest"` to `"latest"`. A resumed run adopts the
  block already in the cache. All 7 live endpoints served `eth_getCode` at a concrete tip
  block (verified 2026-08-26), so this costs nothing.
- The endpoint must be confirmed with `eth_chainId` before any address is resolved, and
  every per-chain file passed in (`--in` *and* `--code`) must name the chain being resolved.
  Both scripts assert this and abort; see pitfall 2.
- A failed or errored call is **`unresolvable`**, never `eoa`. This distinction is the whole
  point of the phase; collapsing it silently invalidates the headline number. It is enforced
  in code, not by convention: `classify()` refuses anything that is not a code hex string, so
  a `{"result": null}` reply — what a stub, a proxy error page or a hard-throttling endpoint
  produces — raises instead of yielding a confident `eoa`. `--classes` values are checked
  against the census's four class names for the same reason: a typo must abort, not resolve
  zero addresses and exit 0.

## 3. Taxonomy

Two independent axes plus a filter. Record all three per recipient.

### Axis A — `to_kind` (what the address was **when the tx arrived**, see §4)

| Value | Test |
|---|---|
| `eoa` | **no code now** — a latest-block verdict only; see the caveat below |
| `contract` | code present at tx time (verified) — **the genuine EOA→contract case** |
| `contract-later` | code now, but none at tx time → the tx paid a codeless address; the contract was deployed afterwards |
| `delegated-eoa` | code begins `0xef0100` (EIP-7702 delegation). Confirm whether the chain supports 7702 at all before reporting any; treat as a user account, not a protocol |
| `unresolvable` | endpoint dead / refused (zkcandy) |
| `code-time-unverified` | code now, but no archive endpoint and no explorer creation record to date it |

These six values are **mutually exclusive and exhaustive**: every candidate recipient gets
exactly one, and the tx counts behind them sum to 24,067 (the reconciliation line in §8).

**`eoa` is the one bucket nothing dates.** The §4 gate runs only on recipients the resolver
marked `contract`, so `eoa` rests entirely on `getCode(latest)` returning `0x`. A recipient
that *had* code when it was paid and has none now — self-destructed, or resolved against a
degraded endpoint — is filed here silently, the exact inverse of the counterfactual-deployment
trap §4 exists to catch. Do not describe the bucket as "no code at tx time and none now"
unless you dated it. `check_code_time.py --kinds eoa --limit N` runs that control on a
deterministic sample and reports any contradiction separately (§4); run it on at least one
archive chain and report the result, including a null one.

`system` is **not** one of them — it is a separate boolean, `is_system`, orthogonal to
`to_kind`. A system address usually *also* has code, so putting it in the same enum would
make the buckets overlap and the reconciliation impossible: address `0x0` on zero is
`to_kind = contract` **and** `is_system = true` at the same time (224 bytes of code,
verified). Report the system set as its own line — "N of the M `contract` recipients are
reserved system addresses, excluded from the headline" — never by moving them out of their
`to_kind` bucket.

### System-address filter (sets `is_system`; apply before calling anything a protocol interaction)

Treat `int(address, 16) < 0x20000` as reserved: the system-contract range
`0x…0000–0x…ffff` plus the `0x…10000–0x…1ffff` block that holds L2Bridgehub `0x…10002`,
L2AssetRouter `0x…10003`, L2NativeTokenVault `0x…10004`, MessageRoot `0x…10005`
(full list: `../KNOWN_ADDRESSES.md` lines 18–28). Also filter the Era-only legacy
L2SharedBridge `0x11f943b2c77b743AB90f4A0Ae7d5A4e7FCA3E102`. These are transport or
protocol plumbing, not a counterparty a user chose.

Precedence: `is_system` **wins over `actor_type`** (a system address is never assigned an
Axis-B label and never counts as a protocol interaction) and is **independent of `to_kind`**
(it does not change what the code test found).

### Axis B — `actor_type` (only for `contract` / `contract-later` recipients)

| Value | Meaning | Reporting consequence |
|---|---|---|
| `smart-wallet` | user-controlled account: native-AA / AGW / Safe / 4337-style | **still user activity** — must not inflate "protocol usage" |
| `protocol-contract` | bridge, DeFi, infra, governance contract owned by a project | genuine protocol interaction |
| `token` | ERC-20/721 contract | usually a user calling `approve`/`transfer` from L1 |
| `unknown-contract` | code exists, identity not established after the §7 playbook | report count + addresses openly |

This axis is the analytically load-bearing one: "EOA sent value to something with code" is
*not* the same claim as "a protocol was used", and the abstract sample in
`seed-data/probe-samples.json` shows the difference is large.

## 4. Code-time verification (the correctness gate)

**The trap:** ZK-stack smart accounts are commonly **funded before they are deployed**
(counterfactual/lazy deployment). A recipient that has code today may have had none when
the priority tx landed — in which case the tx was EOA→EOA at the time. Judging by
`"latest"` alone systematically over-counts EOA→contract. (The parent census already flags
the mirror-image version of this for L1 initiators — `../results/REPORT.md` §5, "an account
that added/removed a delegation after its txs is classified by its current state".)

Procedure, implemented in `scripts/check_code_time.py`, for **every** `contract` recipient —
including ones that only reach the code cache as decoded deposit beneficiaries (pass
`--deposit-beneficiaries`, matching the resolver run) or via a `--classes protocol-message`
control run. A contract recipient with no matching in-window record still gets an explicit
`unavailable` entry stating why; none may be silently absent from the output:

1. Earliest in-window tx to that recipient (min `(ts, tx_id)` among candidate records; the
   `tx_id` tiebreak keeps the choice deterministic when two txs share a timestamp).
2. `eth_getTransactionByHash(canonical_hash)` on the L2 → `blockNumber`. The canonical hash
   **is** the L2 tx hash, so this resolves directly.
3. `eth_getCode(recipient, <blockNumber − 1>)` — needs an archive endpoint. Verified working
   on zero's RPC (funding tx in `0x34ad52`, probed at `0x34ad51`); probe each chain in Phase 0.
4. Verdict → `contract` / `contract-later` (code empty at that block) / `delegated-eoa` /
   `unavailable`.

**Probe the block *before*, never the tx's own block.** `eth_getCode(addr, N)` returns
end-of-block-N state: after the funding tx, and after every other tx in N — including a
deployment that a *different* tx did later in the same block. Since counterfactual wallets
are frequently funded and deployed in quick succession, querying block N is precisely the
over-count this section exists to prevent. Block N−1 answers the question asked.

The residual error is one-directional and acceptable: a contract deployed *earlier in the
same block* than the funding tx reads as `eoa`, so `contract` is under-stated, never
inflated. Say so in the report rather than trying to correct it — a per-tx-index probe is
not available over JSON-RPC.

**The bigger error term: one verdict per recipient, not per tx.** Only the earliest tx is
dated, and that verdict is then applied to every tx the recipient received — for abstract's
rank-1 recipient, 162 of them. If the recipient was deployed midway through the window, the
earliest tx correctly reads `eoa`, the recipient becomes `contract-later`, and excluding it
from the headline also excludes the later txs that genuinely did pay a deployed contract.
This dwarfs the block-N/N−1 off-by-one above, so it is measured rather than assumed:
whenever the earliest tx reads `eoa`, `check_code_time.py` also dates the recipient's **last**
in-window tx and records

- `txs_in_window` — how many txs the single verdict covers,
- `code_at_last_tx` and `straddles_deployment` — whether code had appeared by the last tx.

`straddles_deployment = false` (or `txs_in_window = 1`) means the verdict is exact for every
tx. `true` means the recipient's txs are split by the deployment and the true `contract`
count sits between the two bounds. Report the straddling population and its tx count next to
the headline; do not silently exclude it, and do not silently include it either. Dating every
tx is possible with the same batched calls if a tighter bound is needed — say so if you do it.

Fallbacks when step 3 is unavailable: the explorer's contract-creation tx and timestamp
(era and lens have verified APIs — `../CHAINS.md`), compared against the record's `ts`. If
that fails too, the recipient is `code-time-unverified` and stays visible as its own bucket
in every table.

`unavailable` is a **failure, not a verdict**: `check_code_time.py` marks those entries
`retryable` and re-attempts them on the next run, so switching to an archive endpoint with
`--rpc` actually re-does the calls. Never let a cached failure masquerade as a result.

Two `unavailable` causes are **terminal**, not retryable, and the script separates them —
otherwise the entries can never be cleared and the acceptance criterion "no `retryable: true`
left unexplained" is unreachable:

- the recipient has **no in-window record** under the `--classes` / `--deposit-beneficiaries`
  in force (re-run with the flags that built the code cache);
- `eth_getTransactionByHash(canonical_hash)` **answers with no block** — the priority tx
  never executed on L2, or the endpoint does not index it. An archive endpoint cannot conjure
  a tx that never ran, so this is `retryable: false` with a detail saying to confirm on the
  explorer. Only a *failed call* (transport error, JSON-RPC error, pruned state) is retryable,
  and the run's closing summary reports the actual causes rather than assuming "not archive".

Report `contract-later` separately and **exclude it from the headline EOA→contract count** —
but do report it: "N txs funded addresses that only later became contracts" is itself a
finding about smart-wallet onboarding through the bridge.

## 5. Families, proxies, and pattern extraction

- **Family = set of recipients whose `getCode` output is byte-identical** (equal
  `codehash`). Attribute the family once; the verdict covers every member. Verified real:
  three abstract recipients at ranks 1, 5 and 6 (162 + 94 + 60 txs) share one bytecode
  (`sha256 fbd752b5…`, 1,632 bytes). Ranks 2–4 are *not* in it — the family is a bytecode
  fact, not a head-of-the-distribution fact, and the sample of three is a lower bound on
  its size.
- **Proxies:** read the ERC1967 implementation slot
  `0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc` via
  `eth_getStorageAt` (verified on abstract → implementation `0xaa3633b417483f932969edaef7cc4f1068f6faa9`).
  The implementation is part of the family's identity and usually the only thing with
  verified source. Also try the transparent-proxy admin slot and beacon slot if the ERC1967
  slot is empty.
- **Recurrence distribution** per chain: recipients with exactly 1 tx, 2–4, 5–9, ≥10, plus
  max. Ground truth for the candidate set: **807 (chain, address) pairs see ≥2 txs, 98 see
  ≥5, 34 see ≥10** — these are sums of the per-chain counts, computed per chain and never
  across chains (per-chain in `seed-data/ground-truth.json`). Everything else is a one-shot address
  — that skew is the headline shape of the data, so report it, don't bury it.
- **Selector patterns** for `other`-class records: group by `(to, selector)` and resolve the
  signature (openchain.xyz / 4byte.directory). `other` is a residual bucket, so filter it
  before analysing: **only 4 of the 15 carry calldata** (abstract 26927 `0x64e7f93b`; era
  3301321/3301322/3301323 `0x095ea7b3` = `approve`). The other 11 are `data_len = 0`,
  `value = 0` pings — 5 of them at `0x0` — and grouping them by selector yields 11 rows
  signed `unknown` that are not calls at all. "Users driving L2 contracts from L1" is a
  4-record story; report it as such rather than inflating it to 15.
- **Cross-chain joins:** same recipient address on ≥2 chains, and same family bytecode on
  ≥2 chains (a shared wallet implementation or a multi-chain protocol deployment). Ground
  truth for the address side: **31 of the 21,480 distinct recipients appear on ≥2 chains**
  (and 11 of 775 deposit beneficiaries) — the join is small, so enumerate it fully rather
  than sampling. The clearest case is `0xf70da97812cb96acdf810712aa562db8dfa3dbef`: rank-1
  recipient on era (94) and rank-2 on abstract (133), and the rank-1 *L1 initiator* on both,
  i.e. someone funding their own address across chains. It reaches zero too, but only with
  3 txs (rank 17 of zero's **257** candidate recipients) — don't upgrade that to a third chain
  of the same pattern, and don't rank recipients against 255, which is zero's distinct *L1
  initiator* count (pitfall 10 applies to this ranking too).

## 6. Pitfalls

1. **Latest-block code ≠ code at tx time — and the tx's own block ≠ code at tx time either.**
   §4. The single biggest source of a wrong answer, and the off-by-one is the subtle half of
   it: `getCode(N)` is end-of-block-N state. Probe `N−1`.
2. **Never propagate code status or labels across chains.** The same address can be an EOA
   on one chain and a contract on another; address derivation and deployments are
   per-chain. Re-run `getCode` on each chain. Both scripts assert `eth_chainId` against
   `../CHAINS.md` and that `--in` names the chain being resolved, and abort on either
   mismatch — a wrong-endpoint run otherwise produces plausible output (every address
   resolves as a plain EOA) and errors nowhere. If you substitute an endpoint, the assertion
   still applies; record the substitution in the manifest.
3. **zkcandy is unresolvable.** `https://rpc.zkcandy.io` returned nothing on 2026-08-26 and
   its explorer is down; no free alternative was found. That strands **1,396 candidate txs /
   1,251 distinct recipients** (99.2% of that chain's traffic is direct transfers). Search
   for a replacement endpoint at runtime; if none, report the whole chain as `unresolvable`
   with the exact counts and exclude it from percentage claims about the resolved set.
4. **Address `0x0` can have code.** On zero, `0x0000…0000` returned 224 bytes and is the
   target of the tester ping — it resolves as `contract` but is meaningless as a protocol
   interaction. Apply the system filter (§3) *before* pattern analysis; verified example in
   `seed-data/probe-samples.json`.
5. **`eth_call` probing is unreliable.** `name()`, `owner()`, `implementation()` returned
   `0x` on the abstract proxy family and errored on the era sample. Use bytecode identity,
   the ERC1967 slot, and explorer source as primary evidence; treat successful probes as a
   bonus, not the method.
6. **Value semantics.** `value` is in the chain's **base token** (ETH on era/abstract/zero/
   zkcandy; SOPH, GHO, zkCRO, ozETH elsewhere) — never sum across chains. 14 of the 24,067
   candidates have `value = 0` (pings/calls); "sends money" claims must filter `value > 0`
   (24,053 txs).
7. **Smart wallet ≠ protocol.** Reporting "EOA→contract" without splitting Axis B would
   turn ordinary users funding their own AA wallets into fake protocol adoption.
8. **Deposits' inner `to` is always `0x…10003`** (verified for all 3,064). Any "protocol
   interaction" among deposits must come from the decoded beneficiary (§1), not from `to`.
9. **Rate limits.** Free L2 RPCs throttle; keep the batch sleeps, and if an endpoint starts
   erroring, back off rather than converting errors into `eoa` verdicts. A throttling endpoint
   answers **HTTP 200 with an `{"error": …}` body**, so backing off on transport failures
   alone gives it no backoff at all; `post()` retries both, with exponential backoff. A batch
   that produces nothing usable costs exactly **one** single-address probe before the batch is
   declared dead, and 3 consecutive dead batches abort the run — the probe is what tells
   "endpoint is down" from "endpoint dislikes batches", and it is why the abort takes ~1 minute
   at the defaults instead of grinding every remaining address through four attempts each.
10. **Per-chain sums are not distinct-address counts.** 21,515 is the sum of the eight
    per-chain recipient counts; **21,480** addresses are distinct globally, 31 of them on ≥2
    chains (deposit beneficiaries: 787 vs **775**, 11 shared; combined universe **22,106**
    addresses over **22,162** lookups). The sum is the correct workload figure — code status is
    per-chain (pitfall 2) — and the wrong population figure. A report that says "21,515
    distinct recipients" and "31 addresses on ≥2 chains" contradicts itself. Ground truth for
    both is in `seed-data/ground-truth.json:totals`.

    The lookup total is **not** 21,515 + 787: the resolver builds one address set per chain, so
    an address that is both a candidate recipient and a deposit beneficiary **on the same
    chain** is resolved once. That happens 140 times (era 44, abstract 82, zero 8, zkcandy 5,
    lens 1), giving 22,162 — and it is a different quantity from the 149 addresses that are in
    both sets *globally*. Per-chain figures are in `ground-truth.json:per_chain.*.address_lookups`.

    The same trap applies to **rankings**: rank a recipient against that chain's distinct
    *recipient* count, never against its initiator count. §5's zero example got this wrong
    once already ("rank 17 of 255" — 255 is zero's distinct `l1_from` count; the recipient
    population is 257).
11. **Ties make top-N lists non-unique.** zero's rank 8–10 and zkcandy's rank 8–10 sit inside
    ties, so two correct implementations disagree on membership. The stated order is txs
    DESC, then address ASC (`ground-truth.json:counting_rules`); use it, or a Phase 0
    reproduction check will "fail" on a difference that is not one.

## 7. Attribution playbook (strongest evidence first)

1. Verified **source or contract name** on the chain's explorer (era and lens APIs verified
   in `../CHAINS.md`; abstract via abscan/Etherscan V2 needs a key; others discover at
   runtime).
2. The **implementation behind a proxy** (§5) — often verified even when the proxy is not.
3. **Exact bytecode equality** with an already-identified contract, including one identified
   on another chain (propagate the *label*, never the code status).
4. **Seed registries**: `../results/scripts/labels.json`, `../KNOWN_ADDRESSES.md`, and the 14
   protocols already attributed in `../results/REPORT.md` §3 — a recipient may belong to a
   protocol the census already found from the sender side.
5. **Selector databases** for `other`-class calldata; **protocol docs / GitHub**; targeted
   web search on the address.

Confidence semantics (unchanged from `../results/REPORT.md` §5): **high** = both sides
verified on-chain/source or exact match to an official registry; **medium** = verified name
on one side, project inferred; **low** = name-only or single tx. Mark unverified labels as
unverified everywhere they appear.

## 8. Metrics to compute (per chain and overall)

- Candidate txs and distinct recipients by `to_kind` (six disjoint buckets); the
  resolved-vs-unresolvable split; and `is_system` as its own count *within* those buckets,
  never as a seventh bucket (§3).
- **Headline:** txs and distinct recipients where `to_kind = contract` (code-time verified)
  and `actor_type = protocol-contract`; then the same for `smart-wallet`, `token`,
  `unknown-contract`; then `contract-later`.
- Recurrence distribution and top-20 recipients per chain with kind, actor type, protocol.
- Families: member count, tx count, chains, attribution, implementation address.
- `other`-class `(to, selector)` groups with resolved signatures — the 4 records with
  calldata separated from the 11 zero-value pings.
- Cross-chain: recipients and families on ≥2 chains (expect 31 recipients; verify).
- Deposit beneficiaries by kind/actor type (secondary set), reported separately from the
  candidate set so the two are never conflated.
- Reconciliation line: candidate buckets must sum to 24,067 (and 45,711 across all classes
  once the control set is included).
