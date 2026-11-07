"""Local PostgreSQL proof for the durable service cutover boundary."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import psycopg2
from psycopg2.extensions import parse_dsn
import pytest

from app import db_pool, program_compatibility
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn
from backend.scripts.apply_sql_migrations import apply_migration, discover_migrations, ensure_ledger
from backend.scripts.check_schema_invariants import check_schema_invariants


@pytest.fixture(scope="module")
def observation_database(postgres_dsn):
    migration = next(item for item in discover_migrations(Path(__file__).resolve().parents[2] / "sql")
                     if item.filename == "169_stage1_program_version_window.sql")
    with psycopg2.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;")
        ensure_ledger(connection)
        apply_migration(connection, migration)
        assert not check_schema_invariants(connection)[2]
    return postgres_dsn


@pytest.mark.asyncio
async def test_backend_advance_is_durable_before_enable_and_survives_restart(observation_database, monkeypatch):
    parameters = parse_dsn(observation_database)
    parameters["database"] = parameters.pop("dbname")
    parameters["port"] = int(parameters["port"])
    pool = await asyncpg.create_pool(**parameters, min_size=1, max_size=2)
    monkeypatch.setattr(db_pool, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(program_compatibility, "_networks", {})
    client = SimpleNamespace(get_genesis_hash=AsyncMock(return_value=SimpleNamespace(value="backend-genesis")))
    try:
        state = await program_compatibility.observe_program_version(client, "rpc-a", "program-a", 77)
        assert state.stage1_available
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT highest_version FROM program_version_observations WHERE genesis_hash='backend-genesis'") == 77
        program_compatibility._networks.clear()
        # Provider changes and new processes share the same chain identity.
        with pytest.raises(ValueError, match="version downgrade"):
            await program_compatibility.observe_program_version(client, "rpc-b", "program-a", 76)
        assert not program_compatibility.program_compatibility("rpc-b", "program-a").stage1_available
        other = await program_compatibility.observe_program_version(client, "rpc-b", "program-b", 76)
        assert other.program_version == 76
        client.get_genesis_hash.return_value = SimpleNamespace(value="other-genesis")
        other_chain = await program_compatibility.observe_program_version(client, "rpc-c", "program-a", 76)
        assert other_chain.program_version == 76
        for rejected in (0xFF, 0x4B, 0x4F):
            genesis = f"rejected-genesis-{rejected}"
            client.get_genesis_hash.return_value = SimpleNamespace(value=genesis)
            with pytest.raises(ValueError, match="version mismatch"):
                await program_compatibility.observe_program_version(client, f"rpc-rejected-{rejected}", "program-a", rejected)
            async with pool.acquire() as connection:
                assert await connection.fetchval("SELECT highest_version FROM program_version_observations WHERE genesis_hash=$1", genesis) is None
            await program_compatibility.observe_program_version(client, f"rpc-rejected-{rejected}", "program-a", 76)
            with pytest.raises(ValueError, match="version mismatch"):
                await program_compatibility.observe_program_version(client, f"rpc-rejected-{rejected}", "program-a", rejected)
            async with pool.acquire() as connection:
                assert await connection.fetchval("SELECT highest_version FROM program_version_observations WHERE genesis_hash=$1", genesis) == 76
            state = await program_compatibility.observe_program_version(client, f"rpc-rejected-{rejected}", "program-a", 77)
            assert state.stage1_available
            program_compatibility._networks.clear()
            with pytest.raises(ValueError, match="version downgrade"):
                await program_compatibility.observe_program_version(client, "rpc-restarted", "program-a", 76)
            async with pool.acquire() as connection:
                assert await connection.fetchval("SELECT highest_version FROM program_version_observations WHERE genesis_hash=$1", genesis) == 77
        # An outage cannot expose a remembered Stage 1 capability.
        monkeypatch.setattr(db_pool, "get_pool", AsyncMock(side_effect=RuntimeError("database unavailable")))
        with pytest.raises(RuntimeError, match="database unavailable"):
            await program_compatibility.observe_program_version(client, "rpc-a", "program-a", 77)
        assert not program_compatibility.program_compatibility("rpc-a", "program-a").stage1_available
    finally:
        await pool.close()


def test_atomic_maximum_and_data_api_roles_cannot_mutate_it(observation_database):
    def observe(version):
        with psycopg2.connect(observation_database) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT public.observe_program_version(%s,%s,%s::smallint)", ("race-genesis", "program", version))
                return cursor.fetchone()[0]
    assert observe(77) == 77
    with ThreadPoolExecutor(max_workers=6) as threads:
        assert list(threads.map(observe, [76, 77] * 8)) == [77] * 16
    with psycopg2.connect(observation_database) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.program_version_observations'::regclass")
            assert cursor.fetchone()[0]
            for role in ("anon", "authenticated", "service_role"):
                cursor.execute("SELECT has_table_privilege(%s,'public.program_version_observations','SELECT,INSERT,UPDATE,DELETE'), has_function_privilege(%s,'public.observe_program_version(text,text,smallint)','EXECUTE')", (role, role))
                assert cursor.fetchone() == (False, False)


def test_documented_reset_repairs_only_the_scoped_unsupported_row(observation_database):
    runbook = Path(__file__).resolve().parents[3] / "docs/runbooks/STAGE1_SERVICE_VERSION_RECOVERY.md"
    reset_sql = runbook.read_text().split("```sql\n", 1)[1].split("\n```", 1)[0]
    reset_sql = reset_sql.replace("REPLACE_WITH_VERIFIED_GENESIS_HASH", "repair-genesis").replace("REPLACE_WITH_VERIFIED_PROGRAM_ID", "repair-program")
    with psycopg2.connect(observation_database) as connection:
        with connection.cursor() as cursor:
            for genesis, program in (("repair-genesis", "repair-program"), ("other-genesis", "repair-program"), ("repair-genesis", "other-program")):
                cursor.execute("SELECT public.observe_program_version(%s,%s,255::smallint)", (genesis, program))
            cursor.execute(reset_sql)
            assert cursor.fetchall() == [("repair-genesis", "repair-program", 77)]
            cursor.execute("SELECT highest_version FROM public.program_version_observations WHERE (genesis_hash='other-genesis' AND program_id='repair-program') OR (genesis_hash='repair-genesis' AND program_id='other-program')")
            assert cursor.fetchall() == [(255,), (255,)]
            # Even selecting the supported row explicitly cannot reset 77 to 76.
            cursor.execute(reset_sql.replace("255::smallint AS expected_rejected_version", "77::smallint AS expected_rejected_version").replace("77::smallint AS recovered_high_water", "76::smallint AS recovered_high_water"))
            assert cursor.fetchall() == []
            cursor.execute("SELECT highest_version FROM public.program_version_observations WHERE genesis_hash='repair-genesis' AND program_id='repair-program'")
            assert cursor.fetchone()[0] == 77
