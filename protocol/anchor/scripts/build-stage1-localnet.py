#!/usr/bin/env python3
"""Build/test the simulated adapter in an isolated localnet Anchor workspace.

Never writes target/deploy or the canonical IDL/client mirrors. Anchor 0.29's
macros do not filter handler cfg attributes, so local-only wrappers are
inserted in an IDL-only source copy; the binary uses feature-gated dispatch.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from stage1_test_process import run_suite

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ID = "5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt"
OUT = ROOT / ".anchor/stage1-localnet"
DEFAULT = ROOT / "target/deploy/boulder_rollers.so"


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    if "--test" in sys.argv:
        version = subprocess.check_output(["solana-test-validator", "--version"], text=True).strip()
        if not version.startswith("solana-test-validator 2.1.21 "):
            sys.exit(f"Replay tests require Agave 2.1.21 first in PATH; got {version}")
    run(sys.executable, str(ROOT / "scripts/check-deployable-artifact.py"), str(DEFAULT))
    original = hashlib.sha256(DEFAULT.read_bytes()).digest()
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "target"
    (target / "deploy").mkdir(parents=True, exist_ok=True)
    (target / "idl").mkdir(exist_ok=True)
    run("cargo", "build-sbf", "--manifest-path", str(ROOT / "programs/boulder_rollers/Cargo.toml"),
        "--features", "stage1-localnet", "--sbf-out-dir", str(target / "deploy"), cwd=ROOT)
    parser = OUT / "programs/boulder_rollers"
    shutil.copytree(ROOT / "programs/boulder_rollers/src", parser / "src", dirs_exist_ok=True)
    shutil.copy2(ROOT / "programs/boulder_rollers/Cargo.toml", parser / "Cargo.toml")
    shutil.copy2(ROOT / "Cargo.toml", OUT / "Cargo.toml")
    shutil.copy2(ROOT / "Cargo.lock", OUT / "Cargo.lock")
    src = parser / "src/lib.rs"
    text = src.read_text()
    wrappers = ((parser / "src/stage1_localnet_idl.rs").read_text()
                + (parser / "src/smoke_helpers_idl.rs").read_text())
    text = text.replace("pub mod boulder_rollers {", "pub mod boulder_rollers {\n" + wrappers, 1)
    src.write_text(text)
    rpc_port = int(os.environ.get("STAGE1_LOCALNET_RPC_PORT", "28999"))
    faucet_port = int(os.environ.get("STAGE1_LOCALNET_FAUCET_PORT", "28998"))
    (OUT / "Anchor.toml").write_text(f'''[programs.localnet]
boulder_rollers = "{LOCAL_ID}"
[provider]
cluster = "Localnet"
wallet = "{os.environ['ANCHOR_WALLET']}"
[workspace]
members = ["programs/boulder_rollers"]
[test]
upgradeable = true
[test.validator]
rpc_port = {rpc_port}
faucet_port = {faucet_port}
bind_address = "127.0.0.1"
[scripts]
test = "npm test -- --bail --exit"
''')
    # Match the default build's compiled-IDL pipeline, including legacy types.
    manifest = parser / "Cargo.toml"
    manifest.write_text(manifest.read_text().replace('default = ["no-idl"]', 'default = ["no-idl", "stage1-localnet"]'))
    # Compiled IDL builds the Rust test target, whose include_bytes! fixtures
    # require this tests link even on the first isolated build.
    for name in ("node_modules", "tests", "tsconfig.json", "package.json"):
        link = OUT / name
        if not link.exists():
            link.symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
    env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / "target"))
    run("anchor", "idl", "build", "--out", str(target / "idl/boulder_rollers.json"), cwd=parser, env=env)
    assert hashlib.sha256(DEFAULT.read_bytes()).digest() == original, "default binary changed"
    print(f"Isolated localnet program {LOCAL_ID}; default binary unchanged", flush=True)
    if "--test" in sys.argv:
        env = dict(os.environ, COPYFILE_DISABLE="1", STAGE1_LOCALNET="1",
                   STAGE1_REPLAY_RPC_PORT=os.environ.get("STAGE1_REPLAY_RPC_PORT", "26999"),
                   STAGE1_REPLAY_FAUCET_PORT=os.environ.get("STAGE1_REPLAY_FAUCET_PORT", "26998"),
                   STAGE1_REPLAY_DYNAMIC_PORTS=os.environ.get("STAGE1_REPLAY_DYNAMIC_PORTS", "27100-27200"),
                   ANCHOR_TEST_FILES=os.environ.get("ANCHOR_TEST_FILES", "tests/stage1_custody.spec.ts tests/stage1_rate_adapters.spec.ts tests/stage1_claims.spec.ts tests/stage1_sponsor.spec.ts tests/stage1_dung.spec.ts"))
        try:
            run_suite(["anchor", "test", "--skip-build", "--provider.wallet", env["ANCHOR_WALLET"]],
                      cwd=OUT, env=env, ports=(rpc_port, rpc_port + 1, faucet_port))
        finally:
            shutil.rmtree(OUT / ".anchor/test-ledger", ignore_errors=True)
        assert hashlib.sha256(DEFAULT.read_bytes()).digest() == original, "default binary changed"


if __name__ == "__main__":
    main()
