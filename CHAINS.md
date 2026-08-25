# CHAINS — verified connection details (as of 2026-08-25)

All 8 chains are ZK-stack ("Elastic Network") chains registered in the shared **Bridgehub**
on Ethereum L1: `0x303a465B659cBB0ab36eE643eA362c509EEb5213`.
Diamond proxies below were read live from `Bridgehub.getZKChain(chainId)` (selector
`0xe680c4c1`). All chains currently report `settlementLayer(chainId) = 1` (direct
Ethereum settlement).

## Target chains

| key | Chain | chainId | Public L2 RPC (verified) | Diamond proxy on Ethereum (verified) | Lifetime priority txs¹ | Base token | DA |
|---|---|---|---|---|---|---|---|
| era | ZKsync Era | 324 | https://mainnet.era.zksync.io | `0x32400084c286cf3e17e7b677ea9583e60a000324` | 3,315,667 | ETH | Ethereum |
| abstract | Abstract | 2741 | https://api.mainnet.abs.xyz | `0x2edc71e9991a962c7fe172212d1aa9e50480fbb9` | 26,934 | ETH | Ethereum |
| sophon | Sophon | 50104 | https://rpc.sophon.xyz | `0x05ede6ad1f39b7a16c949d5c33a0658c9c7241e3` | 10,212 | SOPH | Avail |
| lens | Lens Chain | 232 | https://rpc.lens.xyz | `0xc29d04a93f893700015138e3e334eb828dac3cef` | 7,227 | GHO | Avail |
| cronos | Cronos zkEVM | 388 | https://mainnet.zkevm.cronos.org | `0x7b2da4e77bae0e0d23c53c3be6650497d0576cfc` | 4,842 | zkCRO | NoDA (validium) |
| zero | ZERϴ Network | 543210 | https://rpc.zerion.io/v1/zero | `0xdbd849acc6ba61f461cb8a41bbaee2d673ca02d9` | 5,255 | ETH | Ethereum |
| zkcandy | ZKcandy | 320 | https://rpc.zkcandy.io | `0xf2704433d11842d15aa76bbf0e00407267a99c92` | 6,360 | ETH | Avail |
| openzk | OpenZK | 1345 | https://rpc.openzk.net | `0x89f90748a9a36c30a324481133fa198f4e16a824` | 6,000 | ozETH | Ethereum |

¹ `getTotalPriorityTxs()` (selector `0xa1954fc5`) called on each diamond proxy,
2026-08-25. This is the **cumulative lifetime count** — use it for scale planning and
the boundary completeness check, not as the in-window count.

Chain IDs, base tokens and DA cross-checked against the official Elastic Network chain
registry (docs.zksync.io/zksync-network/environment) and chainid.network.

## Ethereum L1 endpoints (for the event scan)

| Endpoint | eth_getLogs | Notes |
|---|---|---|
| https://eth.drpc.org | ✅ max 10,000-block range | free tier throttles under sustained load ("Request timeout on the free plan") — backoff + rotate |
| https://rpc.mevblocker.io | ✅ max 10,000-block range | good second endpoint; supports batch requests |
| https://ethereum-rpc.publicnode.com | ❌ historical logs need a token | fine for `eth_call`/`eth_getBlockByNumber`; **rejects python-urllib TLS — always go through `curl`** |
| https://eth-mainnet.public.blastapi.io | ❌ 10-block getLogs limit | — |
| https://1rpc.io/eth | ❌ 50-block getLogs limit | — |
| https://eth.merkle.io | ❌ no eth_getLogs | — |
| https://eth.llamarpc.com | ❌ Cloudflare-blocks server IPs | — |

A 1-year window ≈ 2.63M Ethereum blocks ≈ **263 getLogs calls per chain** at 10k chunks.

## Block explorers (optional, for attribution/labels — not required for the scan)

| Chain | Explorer UI | API (status 2026-08-25) |
|---|---|---|
| era | https://explorer.zksync.io | https://block-explorer-api.mainnet.zksync.io — ✅ verified (zksync-era style REST: `/transactions`, `/address/{a}`, `/batches`) |
| abstract | https://abscan.org | Etherscan **V2** API (`api.etherscan.io/v2/api?chainid=2741`, key needed); legacy api.abscan.org responds but deprecated |
| lens | https://explorer.lens.xyz | https://explorer-api.lens.xyz — ✅ verified (zksync-era style) |
| sophon | https://explorer.sophon.xyz | API base not verified — discover at runtime |
| cronos | https://explorer.zkevm.cronos.org | `/api` redirects (301) — discover at runtime |
| zero | https://explorer.zero.network | API base not verified — discover at runtime |
| zkcandy | https://explorer.zkcandy.io | API base not verified — discover at runtime |
| openzk | unknown — discover at runtime | — |

## Per-chain caveats

- **era**: The only high-volume chain. Traffic is bursty: ~240 priority txs per 10k
  ETH blocks at peaks but ~45–70/day in typical weeks (measured Aug 2026); plan with
  the 50–100k events per year-window band. Also the oldest (pre-dates the
  shared Bridgehub era; legacy bridge contracts still in play — see `KNOWN_ADDRESSES.md`).
- **sophon**: Shutdown announced **2026-06-25**; L1→L2 deposits blocked since then (zero
  new priority txs after that date is *expected*, verified: no events in the last ~46
  days of L1 blocks). Chain stays live "at least through end of 2026". **Scan first.**
  Base token SOPH: `value` fields denominate SOPH, not ETH.
- **lens**: Base token GHO. Current traffic is dominated by Across root-bundle relays
  (~10/day).
- **cronos**: Base token zkCRO — large `value` numbers are zkCRO. Validium (NoDA).
- **zero**: RPC is operated by Zerion (`rpc.zerion.io/v1/zero`). If it 429s, no verified
  fallback exists — check explorer.zero.network / docs at runtime.
- **zkcandy**: low L2 block height (~418k) — young or slow chain; volumes tiny.
- **openzk**: Youngest/smallest (L2 block height ~9,100 (!) on 2026-08-25; only 9,024
  batches). Lifetime priority count is exactly 6,000 — a suspiciously round number
  suggesting scripted/bot deposit activity; worth a close look in the analysis.
  Not present in chainid.network; identity confirmed via the official ZKsync chain
  registry (chainId 1345, base token ozETH) and via Bridgehub registration.
- **Gateway history (all chains)**: ZK Gateway (chainId 9075) was a settlement layer some
  chains used during ~2025–Q1 2026; it is **deprecated** and its RPC
  (`rpc.era-gateway-mainnet.zksync.dev`) no longer answers. If a chain settled via
  Gateway during part of the window, its L1 diamond will show a **txId gap** for that
  period. Handle per `METHOD.md` §7.3.
