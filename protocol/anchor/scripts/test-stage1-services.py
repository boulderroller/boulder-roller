#!/usr/bin/env python3
"""Run the real indexer across local 0x4C -> 0x4D -> 0x4E loader/version advances."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from stage1_test_process import run_suite, wait_for_ports

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def postgres_tools(supplied):
    candidates = [Path(supplied)] if supplied else []
    if shutil.which('initdb'):
        candidates.append(Path(shutil.which('initdb')).parent)
    candidates.extend([Path('/opt/homebrew/opt/postgresql@17/bin'), Path('/usr/lib/postgresql/17/bin')])
    candidates.extend(sorted(Path('/usr/lib/postgresql').glob('*/bin'), reverse=True))
    for candidate in candidates:
        if all((candidate / name).is_file() for name in ['initdb', 'pg_ctl', 'psql']):
            return candidate
    raise RuntimeError('PostgreSQL tools are required; pass --postgres-bin')


def schema_sql():
    # A private schema fixture using the production indexer migrations. There
    # are no inserted projection rows: all rows must come from actual localnet.
    migrations = REPO / 'backend/supabase/migrations'
    sql = '''CREATE TABLE indexed_vaults (
        id BIGINT PRIMARY KEY, created_at BIGINT, total_completions BIGINT,
        total_staked NUMERIC);
        CREATE TABLE canon_indexer_pending (account_pda TEXT PRIMARY KEY,
            chain_slot BIGINT, next_retry_at TIMESTAMPTZ);\n'''
    for name in [
        '20260306_080_indexer_tables.sql',
        '20260307_081_numeric_token_columns.sql',
        '20260415_091_v4a_settlement_indexer_alignment.sql',
        '20260420_098_drop_legacy_program_config_allocation_fields.sql',
        '20260420_099_program_config_protocol_parameters.sql',
        '20260714_127_dung_reservation_observability.sql',
        '20260716_140_dung_circulating_supply_authority.sql',
    ]:
        sql += (migrations / name).read_text() + '\n'
    clock = (migrations / '20260714_126_settlement_clock_v2.sql').read_text()
    start = clock.index('ALTER TABLE public.indexed_program_config')
    sql += clock[start:clock.index(';', start) + 1]
    sql += '\nCREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;\n'
    sql += (REPO / 'backend/sql/169_stage1_program_version_window.sql').read_text()
    # At 0x4D the indexer runs the Stage 1 replay, which needs production's
    # 171 tables. 171 builds on the keeper (170), and both wrap account-deletion
    # objects from 152, whose own predecessors are the whole rides schema. The
    # cutover never deletes an account, so stand in for just those 152 objects.
    sql += ACCOUNT_DELETION_STAND_INS
    for name in ['170_stage1_keeper.sql', '171_stage1_indexer.sql']:
        sql += '\n' + (REPO / 'backend/sql' / name).read_text()
    return sql


ACCOUNT_DELETION_STAND_INS = '''
CREATE TABLE public.users (id uuid PRIMARY KEY, wallet text, account_state text,
    account_deletion_request_id uuid);
CREATE TABLE public.deletion_requests (id uuid PRIMARY KEY, user_id uuid, wallet text,
    status varchar(32) NOT NULL DEFAULT 'legacy_unverified', blockers jsonb NOT NULL DEFAULT '[]',
    worker_lease_token uuid, worker_lease_until timestamptz,
    storage_authorized_at timestamptz, storage_completed_at timestamptz);
CREATE TABLE public.deleted_account_tombstones (wallet_fingerprint text PRIMARY KEY,
    anonymous_marker uuid NOT NULL);
CREATE TABLE public.deleted_wallets (wallet text PRIMARY KEY);
CREATE FUNCTION public.br_account_deletion_wallet_fingerprint(p_wallet text) RETURNS text
    LANGUAGE sql IMMUTABLE AS $$ SELECT encode(sha256(convert_to(p_wallet, 'UTF8')), 'hex') $$;
CREATE FUNCTION public.br_account_deletion_assert_wallet_write_allowed(p_wallet text) RETURNS void
    LANGUAGE sql AS $$ SELECT $$;
CREATE FUNCTION public.br_lock_account_deletion_wallet(p_wallet_fingerprint text) RETURNS void
    LANGUAGE sql AS $$ SELECT $$;
CREATE FUNCTION public.br_account_deletion_db_blockers(p_user_id uuid, p_wallet text) RETURNS jsonb
    LANGUAGE sql AS $$ SELECT '[]'::jsonb $$;
CREATE FUNCTION public.finalize_account_anonymization(p_request_id uuid, p_user_id uuid, p_lease_token uuid)
    RETURNS SETOF public.deletion_requests LANGUAGE sql AS $$ SELECT * FROM public.deletion_requests WHERE false $$;
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wallet', required=True)
    parser.add_argument('--legacy-program', required=True, help='0x4C ELF: build-stage1-initial.py --legacy-version')
    parser.add_argument('--previous-program', required=True, help='0x4D ELF: build-stage1-initial.py --previous-version')
    parser.add_argument('--program', required=True)
    parser.add_argument('--idl', default=str(ROOT / 'idl/boulder_rollers.devnet.json'))
    parser.add_argument('--postgres-bin')
    parser.add_argument('--report', required=True)
    parser.add_argument('--rpc-port', type=int, default=21999)
    parser.add_argument('--postgres-port', type=int, default=54983)
    parser.add_argument('--health-port', type=int, default=33301)
    args = parser.parse_args()
    legacy, previous, current, wallet = (Path(value).resolve() for value in
                                         [args.legacy_program, args.previous_program, args.program, args.wallet])
    for file in [legacy, previous, current, wallet]:
        if not file.is_file():
            parser.error(f'Missing required input: {file}')
    pg = postgres_tools(args.postgres_bin)
    subprocess.run(['npm', 'run', 'build'], cwd=REPO / 'indexer', check=True)
    wait_for_ports([args.postgres_port, args.health_port])
    (ROOT / '.anchor').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage1-service-cutover-', dir=ROOT / '.anchor') as directory:
        work = Path(directory)
        candidate = work / 'candidate.so'
        shutil.copyfile(current, candidate)
        data = work / 'postgres'
        log = work / 'postgres.log'
        subprocess.run([str(pg / 'initdb'), '-D', str(data), '-A', 'trust', '--no-locale', '-U', 'stage1_cutover'], check=True, stdout=subprocess.DEVNULL)
        with (data / 'postgresql.conf').open('a') as configuration:
            configuration.write("\nunix_socket_directories = ''\n")
        try:
            subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-l', str(log), '-o',
                            f'-h 127.0.0.1 -p {args.postgres_port}', '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print(log.read_text(), flush=True)
            shutil.copyfile(log, Path(args.report).resolve().with_suffix('.postgres.log'))
            raise
        try:
            database = f'postgresql://stage1_cutover@127.0.0.1:{args.postgres_port}/postgres'
            subprocess.run([str(pg / 'psql'), database, '-v', 'ON_ERROR_STOP=1', '-q'], input=schema_sql(), text=True, check=True)
            for name in ['node_modules', 'tests', 'tsconfig.json', 'package.json', 'scripts', 'programs', 'Cargo.toml', 'Cargo.lock']:
                (work / name).symlink_to(ROOT / name, target_is_directory=(ROOT / name).is_dir())
            (work / 'target/deploy').mkdir(parents=True)
            (work / 'target/idl').mkdir(parents=True)
            shutil.copyfile(legacy, work / 'target/deploy/boulder_rollers.so')
            shutil.copyfile(Path(args.idl).resolve(), work / 'target/idl/boulder_rollers.json')
            (work / 'Anchor.toml').write_text(f'''[programs.localnet]
boulder_rollers = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
[workspace]
members = ["programs/boulder_rollers"]
[provider]
cluster = "Localnet"
wallet = "{wallet}"
[test]
upgradeable = true
startup_wait = 20000
[test.validator]
rpc_port = {args.rpc_port}
faucet_port = {args.rpc_port - 1}
dynamic_port_range = "{args.rpc_port + 100}-{args.rpc_port + 200}"
bind_address = "127.0.0.1"
[scripts]
test = "npm test -- --bail --exit --fail-zero"
''')
            env = dict(os.environ, ANCHOR_WALLET=str(wallet), COPYFILE_DISABLE='1',
                       ANCHOR_TEST_FILES='tests/stage1_service_cutover.spec.ts', STAGE1_SERVICE_CUTOVER='1',
                       STAGE1_SERVICE_LEGACY=str(legacy), STAGE1_SERVICE_PREVIOUS=str(previous),
                       STAGE1_SERVICE_PROGRAM=str(candidate),
                       STAGE1_SERVICE_DATABASE=database, STAGE1_SERVICE_INDEXER=str(REPO / 'indexer'),
                       STAGE1_SERVICE_REPORT=str(Path(args.report).resolve()), STAGE1_SERVICE_WORK=str(work),
                       STAGE1_SERVICE_HEALTH_PORT=str(args.health_port))
            run_suite(['anchor', 'test', '--skip-build', '--provider.wallet', str(wallet)],
                      cwd=work, env=env, ports=(args.rpc_port, args.rpc_port + 1, args.rpc_port - 1))
        finally:
            # Preserve diagnostics outside the owned temporary build/ledger
            # directory on both failure and success before cleanup removes it.
            for source, suffix in [(log, '.postgres.log'), (work / 'indexer.log', '.indexer.log'),
                                   (work / '.anchor/test-ledger/validator.log', '.validator.log')]:
                if source.is_file():
                    shutil.copyfile(source, Path(args.report).resolve().with_suffix(suffix))
            subprocess.run([str(pg / 'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop'], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
