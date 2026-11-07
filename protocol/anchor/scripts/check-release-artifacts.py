#!/usr/bin/env python3
"""Verify the real six-way artifact boundary and committed deployable IDLs."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "scripts/check-deployable-artifact.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

for build, relative, admitted in [
    ("default", "target/deploy/boulder_rollers.so", {"mainnet-beta", "devnet"}),
    ("devnet", ".anchor/stage1-devnet/deploy/boulder_rollers.so", {"devnet"}),
    ("localnet", ".anchor/stage1-localnet/target/deploy/boulder_rollers.so", set()),
]:
    for cluster in ("mainnet-beta", "devnet"):
        try:
            digest = guard.check(ROOT / relative, cluster)
        except ValueError:
            assert cluster not in admitted, (build, cluster, "wrongly rejected")
        else:
            assert cluster in admitted, (build, cluster, "wrongly admitted")
        print(f"{build} -> {cluster}: expected {'admission' if cluster in admitted else 'refusal'}")
for built, canonical in [("target/idl/boulder_rollers.json", "idl/boulder_rollers.json"),
                         (".anchor/stage1-devnet/idl/boulder_rollers.json", "idl/boulder_rollers.devnet.json")]:
    assert json.loads((ROOT / built).read_text()) == json.loads((ROOT / canonical).read_text()), f"Built IDL differs: {built}"
assert (ROOT / "target/types/boulder_rollers.ts").read_bytes() == (ROOT / "clients/typescript/boulder_rollers.ts").read_bytes(), "Built TypeScript client differs"
print("Real artifact guard matrix: 6/6; both deployable IDLs and the TypeScript client match.")
