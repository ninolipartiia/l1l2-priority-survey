# KNOWN ADDRESSES — verified seed labels (2026-08-25)

Status legend: ✅ = read from chain / observed in live data during preparation;
⚠️ = from documentation/prior knowledge, verify before citing.

## Ecosystem contracts on Ethereum L1 (shared by all 8 chains)

| Address | Label | Status |
|---|---|---|
| `0x303a465B659cBB0ab36eE643eA362c509EEb5213` | Bridgehub (proxy) — entry point for all L1→L2 requests | ✅ (all getters answered) |
| `0x8829AD80E425C646DAB305381ff105169FeEcE56` | L1AssetRouter (= `Bridgehub.assetRouter()` = `sharedBridge()`) | ✅ |
| `0xbeD1EB542f9a5aA6419Ff3deb921A372681111f6` | L1NativeTokenVault (`assetRouter.nativeTokenVault()`) | ✅ |
| `0xD7f9f54194C633F36CCD5F3da84ad4a1c38cB2cB` | L1Nullifier (`assetRouter.L1_NULLIFIER()`); pre-v26 this address was "L1SharedBridge" | ✅ |
| `0x57891966931Eb4Bb6FB81430E6cE0A03AAbDe063` | Era legacy L1ERC20Bridge (`assetRouter.legacyBridge()`) | ✅ |
| `0x6E96D1172a6593d5027af3c2664c5112cA75F2b9` | ZK Gateway diamond proxy (`getZKChain(9075)`) — relevant only for gateway-period gap recovery | ✅ |
| per-chain diamond proxies | see `CHAINS.md` | ✅ |

## Fixed L2 system addresses (identical on every ZK-stack chain)

| Address | Label |
|---|---|
| `0x0000000000000000000000000000000000008006` | ContractDeployer |
| `0x0000000000000000000000000000000000008008` | L1Messenger (L2→L1; out of scope, listed to avoid confusion) |
| `0x000000000000000000000000000000000000800a` | L2BaseToken |
| `0x0000000000000000000000000000000000010002` | L2 Bridgehub |
| `0x0000000000000000000000000000000000010003` | **L2AssetRouter — the `to` of canonical deposits** ✅ (observed live, Sophon sample) |
| `0x0000000000000000000000000000000000010004` | L2NativeTokenVault |
| `0x0000000000000000000000000000000000010005` | L2 MessageRoot |
| `0x11f943b2c77b743AB90f4A0Ae7d5A4e7FCA3E102` | Era-only legacy L2SharedBridge | ⚠️ |

## Aliasing

`alias(x) = x + 0x1111000000000000000000000000000000001111 (mod 2^160)` — applied to
contract senders only. Key aliased forms seen in live data:

| Inner `from` (aliased) | Unaliased L1 contract | Status |
|---|---|---|
| `0x993aad80e425c646dab305381ff105169feedf67` | L1AssetRouter → **marks canonical deposits** | ✅ |
| `0xd297fa914353c44b2e33ebe05f21846f1048cfeb` | `0xc186fA914353c44b2E33eBE05f21846F1048bEda` Across Protocol HubPool | ✅ |

## First protocol attribution (found during preparation — treat as a worked example)

**Across Protocol** (intent bridge) uses canonical L1→L2 messaging to relay root bundles:

- L1: HubPool `0xc186fA914353c44b2E33eBE05f21846F1048bEda`; submissions come from
  dataworker EOA `0xf7bac63fc7ceacf0589f25454ecf5c2ce904997c` via Multicall3
  (`0xcA11bde05977b3631167028862bE2a173976CA11`).
- L2 SpokePools (message targets, `relayRootBundle(bytes32,bytes32)` = `0x493a4f84`):
  - Era: `0xE0B015E54d54fc84a6cB9B666099c46adE9335FF` ✅
  - Lens: `0xb234Ca484866C811d0E6d3318866F583781eD045` ✅
- On Lens this was 100% of priority traffic in the sampled window (19/19 over 2 days);
  on Era it was the most recent sender too. Expect SpokePools on other chains — check
  via bytecode match.

## Selector seeds

| Selector | Signature | Context |
|---|---|---|
| `0xcfe7af7c` | `finalizeDeposit(address,address,address,uint256,bytes)` | canonical deposit into `0x…10003` (legacy ABI; newer variants exist — collect empirically) ✅ |
| `0x493a4f84` | `relayRootBundle(bytes32,bytes32)` | Across SpokePool ✅ |

## Useful function selectors (L1 reads)

| Selector | Function | On |
|---|---|---|
| `0xe680c4c1` | `getZKChain(uint256)` | Bridgehub |
| `0x671a7131` | `settlementLayer(uint256)` | Bridgehub |
| `0x68b8d331` | `getAllZKChainChainIDs()` | Bridgehub |
| `0xa1954fc5` | `getTotalPriorityTxs()` | chain diamond |

Full Bridgehub registry on 2026-08-25 (`getAllZKChainChainIDs`): 324, 388, 50104,
543210, 2741, 325, 61166, 1345, 9637, 320, 232, 1217, 2904, 375, 51888, 9075, 30715,
5010405, 2787, 30716, 88629869, 1942323 — the 8 targets are a subset; the others are
out of scope but confirm the registry works.
