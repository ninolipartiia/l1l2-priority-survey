#!/usr/bin/env python3
"""
fetch_contract_names.py — Phase 4 evidence gathering (attribution playbook step 1 and 2).

For every contract address this phase must attribute — candidate recipients, deposit
beneficiaries, protocol-message control recipients, and the ERC1967 implementations behind
them — ask that chain's block explorer for the verified contract name/source.

Explorer API bases were discovered at runtime in Phase 0/4 and are recorded here; CHAINS.md
only had era and lens verified, and it said abstract needs an Etherscan V2 key. It does not:
`block-explorer-api.mainnet.abs.xyz` is the same ZKsync-era-style API era uses and needs no
key. The substitution is recorded in run-manifest-l2.json.

A name is evidence, not proof: `getsourcecode` returning `{"Address": ...}` alone means
"indexed but source not verified", which this script records as unverified rather than
silently dropping. METHOD §7 ranks verified source above everything else, so the
distinction has to survive into the output.

Usage: python3 fetch_contract_names.py --out ../seed/contract-names.json
"""
import argparse, json, os, subprocess, sys, time

EXPLORER = {                                   # verified answering 2026-08-26
    "era":      "https://block-explorer-api.mainnet.zksync.io/api",
    "abstract": "https://block-explorer-api.mainnet.abs.xyz/api",
    "sophon":   "https://api-explorer.sophon.xyz/api",
    "lens":     "https://explorer-api.lens.xyz/api",
    "zero":     "https://explorer.zero.network/api",
    "openzk":   "https://explorer.openzk.net/api",
    "zkcandy":  "https://explorer.zkcandy.io/api",
    # cronos: no API base found (CHAINS.md says /api 301-redirects); it has 0 contract
    # recipients, so nothing is lost — recorded rather than silently omitted.
}


def get(base, params, tries=3, timeout=30):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    err = "no attempt"
    for attempt in range(tries):
        p = subprocess.run(["curl", "-s", "-m", str(timeout), f"{base}?{qs}"],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return json.loads(p.stdout), None
            except ValueError:
                err = f"unparseable {p.stdout.strip()[:100]}"
        else:
            err = f"curl rc={p.returncode}"
        if attempt + 1 < tries:
            time.sleep(1.0 * (2 ** attempt))
    return None, err


def source_of(base, addr):
    """-> {"name":…, "verified":bool, "proxy":…, "implementation":…} or {"error":…}."""
    d, err = get(base, {"module": "contract", "action": "getsourcecode", "address": addr})
    if err is not None:
        return {"error": err}
    if d.get("status") != "1":
        return {"error": f"status={d.get('status')} message={str(d.get('message'))[:80]}"}
    res = (d.get("result") or [{}])[0]
    name = res.get("ContractName") or ""
    # A bare {"Address": …} row is "indexed, source NOT verified" — do not read it as a name.
    return {"name": name or None,
            "verified": bool(name or res.get("SourceCode") or res.get("ABI")),
            "proxy": res.get("Proxy"),
            "implementation": res.get("Implementation") or None,
            "compiler": res.get("CompilerVersion") or None}


def creation_of(base, addr):
    d, err = get(base, {"module": "contract", "action": "getcontractcreation",
                        "contractaddresses": addr})
    if err is not None or d.get("status") != "1":
        return None
    res = (d.get("result") or [None])[0]
    if not res:
        return None
    return {"creator": res.get("contractCreator"), "tx": res.get("txHash"),
            "block": res.get("blockNumber"), "factory": res.get("contractFactory")}


def targets():
    """(chain, address, role) for everything Phase 4 has to attribute."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(here, "..", "..")
    want = {}

    def add(chain, addr, role):
        want.setdefault((chain, addr.lower()), set()).add(role)

    recips = {}
    for chain in list(EXPLORER) + ["cronos"]:
        path = os.path.join(root, "results", "enriched", f"{chain}.jsonl")
        if not os.path.exists(path):
            continue
        seen = {}
        for line in open(path):
            r = json.loads(line)
            if r.get("class") in ("direct-transfer", "other"):
                a = r["to"].lower()
                seen[a] = seen.get(a, 0) + 1
        recips[chain] = seen

    for chain in list(EXPLORER) + ["cronos"]:
        for sub, role in (("code", "candidate-or-deposit"), ("code-pm", "protocol-message")):
            path = os.path.join(here, "..", sub, f"{chain}.json")
            if not os.path.exists(path):
                continue
            for a, v in json.load(open(path)).items():
                if v.get("kind") != "contract":
                    continue
                if role == "candidate-or-deposit":
                    add(chain, a, "candidate-recipient" if a in recips.get(chain, {})
                        else "deposit-beneficiary")
                else:
                    add(chain, a, role)

    slots = os.path.join(here, "..", "seed", "proxy-slots.json")
    if os.path.exists(slots):
        for chain, d in json.load(open(slots)).items():
            for _addr, v in d.items():
                for key in ("erc1967_impl", "erc1967_beacon", "erc1967_admin"):
                    if v.get(key):
                        add(chain, v[key], key)
    return {k: sorted(v) for k, v in want.items()}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(here, "..", "seed", "contract-names.json"))
    ap.add_argument("--sleep", type=float, default=0.1)
    a = ap.parse_args()

    want = targets()
    out = {}
    if os.path.exists(a.out):
        out = json.load(open(a.out))
    todo = [(c, ad) for (c, ad) in sorted(want) if f"{c}:{ad}" not in out]
    print(f"{len(want)} contract addresses to identify, {len(todo)} not yet fetched",
          file=sys.stderr)
    skipped = set()
    for n, (chain, addr) in enumerate(todo, start=1):
        base = EXPLORER.get(chain)
        if base is None:
            skipped.add(chain)
            out[f"{chain}:{addr}"] = {"roles": want[(chain, addr)],
                                      "error": f"no explorer API base known for {chain}"}
            continue
        rec = {"roles": want[(chain, addr)], "explorer": base}
        rec.update(source_of(base, addr))
        rec["creation"] = creation_of(base, addr)
        out[f"{chain}:{addr}"] = rec
        if n % 25 == 0:
            json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
            print(f"  {n}/{len(todo)}", file=sys.stderr)
        time.sleep(a.sleep)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)

    named = {k: v for k, v in out.items() if v.get("name")}
    print(f"\nwrote {a.out}: {len(out)} addresses, {len(named)} with a VERIFIED contract name",
          file=sys.stderr)
    if skipped:
        print(f"  !! no explorer API for: {sorted(skipped)}", file=sys.stderr)
    tally = {}
    for k, v in named.items():
        tally[v["name"]] = tally.get(v["name"], 0) + 1
    for name, cnt in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {cnt:5d}  {name}", file=sys.stderr)


if __name__ == "__main__":
    main()
