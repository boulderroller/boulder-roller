#!/usr/bin/env python3
"""Run one release suite against prebuilt artifacts, on local validators only."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("custody", "providers", "claims", "sponsor", "dung", "governance", "legacy")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--group", choices=GROUPS, required=True)
    p.add_argument("--wallet", required=True)
    p.add_argument("--pool-program", required=True)
    p.add_argument("--squads-program")
    args = p.parse_args()

    def suite(build, files, **extra):
        env = dict(os.environ, ANCHOR_TEST_FILES=" ".join("tests/" + f + ".spec.ts" for f in files), **extra)
        subprocess.run([sys.executable, str(ROOT / "scripts/test-stage1-release.py"), "--build", build,
                        "--wallet", args.wallet, "--pool-program", args.pool_program], cwd=ROOT, env=env, check=True)

    if args.group == "custody":
        suite("localnet", ["stage1_custody"])
        suite("devnet", ["stage1_devnet_release"])
        for build in ("default", "devnet", "localnet"):
            suite(build, ["stage1_release_roles"], STAGE1_RELEASE_ROLES="1")
    elif args.group == "providers":
        for build in ("default", "devnet", "localnet"):
            suite(build, ["stage1_rate_adapters"])
    elif args.group == "claims":
        suite("localnet", ["stage1_claims"])
        for build in ("default", "devnet", "localnet"):
            suite(build, ["stage1_claim_storage"])
    elif args.group == "dung":
        for build in ("default", "devnet", "localnet"):
            suite(build, ["stage1_dung"])
    elif args.group == "sponsor":
        for build in ("default", "devnet", "localnet"):
            suite(build, ["stage1_sponsor"])
    elif args.group == "governance":
        p.error("--squads-program required") if not args.squads_program else None
        for build in ("default", "devnet"):
            subprocess.run([sys.executable, str(ROOT / "scripts/test-stage1-governance.py"), "--build", build,
                "--wallet", args.wallet, "--squads-program", args.squads_program,
                "--squads-config", str(ROOT / "tests/fixtures/stage1_governance/squads-config.json"),
                "--initial-program", str(ROOT / ".anchor/stage1-initial/deploy/boulder_rollers.so"),
                "--pool-program", args.pool_program], cwd=ROOT, check=True)
            subprocess.run([sys.executable, str(ROOT / "scripts/test-stage1-governance.py"), "--build", build,
                "--wallet", args.wallet, "--squads-program", args.squads_program,
                "--squads-config", str(ROOT / "tests/fixtures/stage1_governance/squads-config.json"),
                "--guardian-only"], cwd=ROOT, check=True)
            subprocess.run([sys.executable, str(ROOT / "scripts/test-stage1-governance.py"), "--build", build,
                "--wallet", args.wallet, "--squads-program", args.squads_program,
                "--squads-config", str(ROOT / "tests/fixtures/stage1_governance/squads-config.json"),
                "--initial-program", str(ROOT / ".anchor/stage1-previous/deploy/boulder_rollers.so"),
                "--pool-program", args.pool_program, "--version-upgrade"], cwd=ROOT, check=True)
    else:
        files = ["boulder_rollers_protocol_truths", "canon_commitment_v1", "configure_program_mints",
                 "migrate_local_legends", "register_ratified_climb", "vault_creation_authority", "stage1_custody",
                 "stage1_operator", "stage1_release_operator", "stage1_claim_batches", "stage1_cutover", "stage1_guardian_operator", "stage1_governance_contract", "stage1_governance_pending", "stage1_replay_cleanup"]
        for build in ("default", "devnet", "localnet"):
            suite(build, files)


if __name__ == "__main__":
    main()
