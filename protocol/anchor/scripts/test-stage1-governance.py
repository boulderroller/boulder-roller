#!/usr/bin/env python3
"""Real Squads dump + deployable BoulderRoller on a private time-travel localnet."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from stage1_test_process import run_suite

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', choices=['default', 'devnet'], required=True)
    p.add_argument('--wallet', required=True)
    p.add_argument('--squads-program', required=True)
    p.add_argument('--squads-config', required=True)
    p.add_argument('--pool-program')
    p.add_argument('--version-upgrade', action='store_true')
    p.add_argument('--guardian-only', action='store_true')
    p.add_argument('--initial-program', help='Exact parent 1c ELF for a real city migration rehearsal')
    args = p.parse_args()
    if args.guardian_only and (args.initial_program or args.version_upgrade):
        p.error('Guardian-only uses the current program directly')
    version = subprocess.check_output(['solana-test-validator', '--version'], text=True)
    if not version.startswith('solana-test-validator 2.1.21 '):
        p.error('Requires Agave 2.1.21')
    binary = ROOT / ('target/deploy/boulder_rollers.so' if args.build == 'default' else '.anchor/stage1-devnet/deploy/boulder_rollers.so')
    if any(name not in binary.read_bytes() for name in [b'SetStage1Guardian', b'PauseStage1Intake', b'ResumeStage1Intake', b'MigrateStage1City', b'PauseStage1Settlement', b'ResumeStage1Settlement']):
        p.error('Upgrade artifact lacks governance handlers; rebuild the current source in its own target directory')
    subprocess.run(['python3', str(ROOT / 'scripts/check-deployable-artifact.py'), str(binary), '--cluster',
                    'mainnet-beta' if args.build == 'default' else 'devnet'], check=True)
    provenance = json.loads((ROOT / 'tests/fixtures/stage1_governance/squads-provenance.json').read_text())
    for path, field in [(args.squads_program, 'binarySha256'), (args.squads_config, 'configDumpSha256')]:
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != provenance[field]:
            p.error(f'{field} differs from reviewed mainnet capture')
    (ROOT / '.anchor').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage1-governance-', dir=ROOT / '.anchor') as tmp:
        out = Path(tmp)
        for name in ['node_modules', 'tests', 'tsconfig.json', 'package.json', 'scripts', 'programs', 'Cargo.toml', 'Cargo.lock']:
            (out / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
        (out / 'target/deploy').mkdir(parents=True)
        (out / 'target/idl').mkdir(parents=True)
        shutil.copyfile(Path(args.initial_program) if args.initial_program else binary, out / 'target/deploy/boulder_rollers.so')
        shutil.copyfile(ROOT / ('idl/boulder_rollers.json' if args.build == 'default' else 'idl/boulder_rollers.devnet.json'), out / 'target/idl/boulder_rollers.json')
        rpc_port = int(os.environ.get('STAGE1_GOVERNANCE_RPC_PORT', '31999'))
        faucet_port = int(os.environ.get('STAGE1_GOVERNANCE_FAUCET_PORT', '31998'))
        dynamic_ports = os.environ.get('STAGE1_GOVERNANCE_DYNAMIC_PORTS', f'{rpc_port + 100}-{rpc_port + 200}')
        config = f'''[programs.localnet]
boulder_rollers = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
[workspace]
members = ["programs/boulder_rollers"]
[provider]
cluster = "Localnet"
wallet = "{Path(args.wallet).resolve()}"
[test]
upgradeable = true
startup_wait = 20000
[test.validator]
rpc_port = {rpc_port}
faucet_port = {faucet_port}
dynamic_port_range = "{dynamic_ports}"
bind_address = "127.0.0.1"
[[test.genesis]]
address = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"
program = "{Path(args.squads_program).resolve()}"
[[test.validator.account]]
address = "BSTq9w3kZwNwpBXJEvTZz2G9ZTNyKBvoSeXMvwb4cNZr"
filename = "{Path(args.squads_config).resolve()}"
[[test.validator.account]]
address = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
filename = "{ROOT / 'tests/fixtures/stage1_providers/jito-mint.json'}"
[scripts]
test = "npm test -- --bail --exit --fail-zero"
'''
        if args.pool_program:
            config += f'\n[[test.genesis]]\naddress = "DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib"\nprogram = "{Path(args.pool_program).resolve()}"\n'
        if args.version_upgrade:
            # Anchor splits this command on whitespace rather than parsing shell
            # quotes. Keep the entire grep expression in one unquoted argument.
            config = config.replace('--fail-zero', '--fail-zero --grep=creates.3-of-5|atomically.hands|real.loader|advances.actual')
        (out / 'Anchor.toml').write_text(config)
        env = dict(os.environ, ANCHOR_WALLET=str(Path(args.wallet).resolve()), COPYFILE_DISABLE='1',
                   STAGE1_GOVERNANCE='0' if args.guardian_only else '1', STAGE1_GUARDIAN_RUNTIME='1' if args.guardian_only else '0', STAGE1_GOVERNANCE_INITIAL='1' if args.initial_program else '0', STAGE1_GOVERNANCE_VERSION='1' if args.version_upgrade else '0', STAGE1_GOVERNANCE_BUILD=args.build, STAGE1_GOVERNANCE_BINARY=str(binary),
                   STAGE1_REPLAY_RPC_PORT=os.environ.get('STAGE1_REPLAY_RPC_PORT', '24999'),
                   STAGE1_REPLAY_FAUCET_PORT=os.environ.get('STAGE1_REPLAY_FAUCET_PORT', '24998'),
                   STAGE1_REPLAY_DYNAMIC_PORTS=os.environ.get('STAGE1_REPLAY_DYNAMIC_PORTS', '25100-25200'),
                   ANCHOR_TEST_FILES='tests/stage1_guardian_runtime.spec.ts' if args.guardian_only else 'tests/stage1_governance.spec.ts')
        run_suite(['anchor', 'test', '--skip-build', '--provider.wallet', env['ANCHOR_WALLET']],
                  cwd=out, env=env, ports=(rpc_port, rpc_port + 1, faucet_port))


if __name__ == '__main__':
    main()
