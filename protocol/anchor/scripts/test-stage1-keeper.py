#!/usr/bin/env python3
"""Run the keeper against the isolated localnet build using 1c cleanup tooling."""
import argparse
import os
from pathlib import Path
import re
import shutil

from stage1_test_process import run_suite

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wallet", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--dsn", required=True, help="Disposable local PostgreSQL database")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--test-file", default='tests/stage1_keeper.spec.ts')
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    out = ROOT / ".anchor/stage1-localnet"
    config = out / "Anchor.toml"
    text = config.read_text()
    if "startup_wait" not in text:
        text = text.replace("[test]\n", "[test]\nstartup_wait = 20000\n")
    text = re.sub(r"rpc_port = \d+", "rpc_port = 22899", text)
    text = re.sub(r"faucet_port = \d+", "faucet_port = 22898", text)
    config.write_text(text)
    env = dict(os.environ, COPYFILE_DISABLE="1", STAGE1_LOCALNET="1",
        PYTHONPATH=os.pathsep.join((str(ROOT.parents[1]),str(ROOT.parents[1]/'backend'))),
        ANCHOR_WALLET=str(Path(args.wallet).resolve()), ANCHOR_TEST_FILES=args.test_file,
        STAGE1_KEEPER_TEST_DSN=args.dsn, STAGE1_KEEPER_PYTHON=args.python,
        STAGE1_KEEPER_EVIDENCE=str(evidence),
        STAGE1_REPLAY_RPC_PORT="23899", STAGE1_REPLAY_FAUCET_PORT="23898", STAGE1_REPLAY_DYNAMIC_PORTS="24000-24100")
    try:
        run_suite(["anchor", "test", "--skip-build", "--provider.wallet", env["ANCHOR_WALLET"]], cwd=out, env=env, ports=(22899,22900,22898))
    finally:
        log = out / ".anchor/test-ledger/validator.log"
        try:
            if log.exists():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 100_000))
                    (evidence / "keeper-validator-tail.log").write_bytes(stream.read())
        finally:
            shutil.rmtree(out / ".anchor/test-ledger", ignore_errors=True)


if __name__ == "__main__":
    main()
