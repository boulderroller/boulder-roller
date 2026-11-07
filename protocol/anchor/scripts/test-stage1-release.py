#!/usr/bin/env python3
"""Run actual deployable binaries on a private local validator, then clean it."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from stage1_test_process import run_suite

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", choices=["default", "devnet", "localnet"], required=True)
    parser.add_argument("--wallet", required=True)
    parser.add_argument("--pool-program")
    parser.add_argument("--failure-log", help="Retain at most 200 KB of validator diagnostics on failure")
    args = parser.parse_args()
    version = subprocess.check_output(["solana-test-validator", "--version"], text=True).strip()
    if not version.startswith("solana-test-validator 2.1.21 "):
        parser.error(f"Replay tests require Agave 2.1.21 first in PATH; got {version}")
    if args.build == "devnet" and not args.pool_program:
        parser.error("Devnet local rehearsal requires an explicit --pool-program")
    print(version, flush=True)
    binary = ROOT / {"default": "target/deploy/boulder_rollers.so", "devnet": ".anchor/stage1-devnet/deploy/boulder_rollers.so",
                     "localnet": ".anchor/stage1-localnet/target/deploy/boulder_rollers.so"}[args.build]
    if args.build == "localnet":
        if b"BOULDERROLLER_STAGE1_LOCALNET_ONLY" not in binary.read_bytes():
            parser.error("Localnet test requires the isolated test artifact")
    else:
        subprocess.run(["python3", str(ROOT / "scripts/check-deployable-artifact.py"), str(binary), "--cluster", "devnet" if args.build == "devnet" else "mainnet-beta"], check=True)
    with tempfile.TemporaryDirectory(prefix="stage1-release-", dir=ROOT / ".anchor") as tmp:
        out = Path(tmp)
        for name in ("node_modules", "tests", "tsconfig.json", "package.json", "programs", "Cargo.toml", "Cargo.lock"):
            (out / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
        for directory in ("deploy", "idl"):
            (out / "target" / directory).mkdir(parents=True)
        shutil.copy2(binary, out / "target/deploy/boulder_rollers.so")
        idl = ROOT / {"default": "idl/boulder_rollers.json", "devnet": "idl/boulder_rollers.devnet.json",
                      "localnet": ".anchor/stage1-localnet/target/idl/boulder_rollers.json"}[args.build]
        shutil.copy2(idl, out / "target/idl/boulder_rollers.json")
        config = (ROOT / "Anchor.toml").read_text().replace('test = "npm test"', 'test = "npm test -- --bail --exit"')
        config = config.replace('[test]\n', '[test]\nstartup_wait = 20000\n')
        if args.build == "localnet":
            config = config.replace('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH', '5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt')
            config = config.replace('AZBtJszKNqY2wGhuDhr9vi4QDQLhrEXEQYSM385fSmDL', 'AJ8GKxmqNtWsdiAso8F4ysrpiYvw8SK8HC2w7SMLV8FT')
            config = config.replace('legacy_local_legend_424242.json', 'legacy_local_legend_424242.localnet.json')
        rpc_port = int(os.environ.get("STAGE1_RELEASE_RPC_PORT", "28999"))
        faucet_port = int(os.environ.get("STAGE1_RELEASE_FAUCET_PORT", "28998"))
        dynamic_ports = os.environ.get("STAGE1_RELEASE_DYNAMIC_PORTS", f"{rpc_port + 100}-{rpc_port + 200}")
        config += f'\n[test.validator]\nrpc_port = {rpc_port}\nfaucet_port = {faucet_port}\ndynamic_port_range = "{dynamic_ports}"\nbind_address = "127.0.0.1"\n'
        # Keep normal slot duration for every artifact. Fast slots expire a
        # blockhash before web3.js's ordinary 30-second blockhash cache does.
        if args.pool_program:
            config += f'\n[[test.genesis]]\naddress = "DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib"\nprogram = "{Path(args.pool_program).resolve()}"\n'
        (out / "Anchor.toml").write_text(config)
        env = dict(os.environ, ANCHOR_WALLET=str(Path(args.wallet).resolve()), COPYFILE_DISABLE="1", STAGE1_DEPLOYABLE="1",
                   STAGE1_REPLAY_RPC_PORT=os.environ.get("STAGE1_REPLAY_RPC_PORT", "26999"),
                   STAGE1_REPLAY_FAUCET_PORT=os.environ.get("STAGE1_REPLAY_FAUCET_PORT", "26998"),
                   STAGE1_REPLAY_DYNAMIC_PORTS=os.environ.get("STAGE1_REPLAY_DYNAMIC_PORTS", "27100-27200"))
        if args.build == "devnet":
            env.update(STAGE1_DEVNET="1", ANCHOR_TEST_FILES=os.environ.get("ANCHOR_TEST_FILES", "tests/stage1_devnet_release.spec.ts tests/stage1_sponsor.spec.ts"))
        if args.build == "localnet":
            env.update(STAGE1_LOCALNET="1")
            env.pop("STAGE1_DEPLOYABLE", None)
        try:
            run_suite(["anchor", "test", "--skip-build", "--provider.wallet", env["ANCHOR_WALLET"]],
                      cwd=out, env=env, ports=(rpc_port, rpc_port + 1, faucet_port))
        except subprocess.CalledProcessError:
            log = out / ".anchor/test-ledger/validator.log"
            if args.failure_log and log.exists():
                with log.open("rb") as source:
                    source.seek(max(0, log.stat().st_size - 200_000))
                    Path(args.failure_log).write_bytes(source.read())
            raise


if __name__ == "__main__":
    main()
