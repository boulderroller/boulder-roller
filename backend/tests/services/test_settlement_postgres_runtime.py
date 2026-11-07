from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor, register_uuid


U64_MAX = 18_446_744_073_709_551_615
register_uuid()


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    external_dsn = os.getenv("BR_TEST_POSTGRES_DSN")
    if external_dsn:
        yield external_dsn
        return
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for the PostgreSQL settlement runtime contract")
    probe = _docker("info", check=False)
    if probe.returncode != 0:
        pytest.skip("Docker daemon is unavailable for the PostgreSQL settlement runtime contract")

    container = f"br-settlement-pgtest-{uuid.uuid4().hex[:10]}"
    started = _docker(
        "run",
        "--rm",
        "-d",
        "--name",
        container,
        "-e",
        "POSTGRES_PASSWORD=postgres",
        "-P",
        "postgres:17",
    )
    assert started.stdout.strip()
    try:
        port_result = _docker(
            "inspect",
            "-f",
            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
            container,
        )
        port = int(port_result.stdout.strip())
        dsn = f"host=127.0.0.1 port={port} dbname=postgres user=postgres password=postgres"
        deadline = time.monotonic() + 30
        while True:
            try:
                connection = psycopg2.connect(dsn)
                connection.close()
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        yield dsn
    finally:
        _docker("rm", "-f", "-v", container, check=False)  # -v: drop the data volume too


def _connection(dsn: str, *, dict_rows: bool = False) -> Any:
    connection = psycopg2.connect(
        dsn,
        cursor_factory=RealDictCursor if dict_rows else None,
    )
    connection.autocommit = True
    return connection


@contextmanager
def _open_connection(dsn: str, *, dict_rows: bool = False) -> Any:
    connection = _connection(dsn, dict_rows=dict_rows)
    try:
        yield connection
    finally:
        connection.close()


def _scope_evidence(count: int, slot: int) -> dict[str, Any]:
    return {
        "commitment": "finalized",
        "counter_count": str(count),
        "source_slot_min": str(slot),
        "source_slot_max": str(slot),
        "batches": [],
    }


def _bootstrap_vault(vault_id: int, open_week: int) -> dict[str, str]:
    return {
        "vault_id": str(vault_id),
        "vault_pda": f"vault-pda-{vault_id}",
        "vault_signature": f"vault-signature-{vault_id}",
        "open_settlement_week": str(open_week),
        "snapshot_hash": f"snapshot-{vault_id}-{open_week}",
    }


def _job(
    vault_id: int,
    *,
    week: int,
    state: str,
    dung: int = 0,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    raw = {
        "id": str(vault_id),
        "open_settlement_week": str(week),
        "pending_rewards": str(dung),
        "cal_tribute_accumulated": "0",
        "pending_rewards_next_week": "0",
        "cal_tribute_accumulated_next": "0",
        "carry_record_royalty": "0",
        "carry_stakers": "0",
        "carry_local_legend": "0",
        "carry_pol": "0",
        "carry_treasury": "0",
    }
    return {
        "vault_id": str(vault_id),
        "vault_signature": f"vault-signature-{vault_id}",
        "state": state,
        "skip_reason": skip_reason,
        "blocked_reason": None,
        "expected_pre_open_week": str(week),
        "auto_roll_from_empty": False,
        "cal_to_convert": "0",
        "dung_to_mint": str(dung),
        "current_week_value": str(dung),
        "next_week_value": "0",
        "pending_rewards": str(dung),
        "cal_tribute_accumulated": "0",
        "pending_rewards_next_week": "0",
        "cal_tribute_accumulated_next": "0",
        "carry_record_royalty": "0",
        "carry_stakers": "0",
        "carry_local_legend": "0",
        "carry_pol": "0",
        "carry_treasury": "0",
        "raw_snapshot": raw,
    }


class _PostgresQuery:
    def __init__(self, dsn: str, table: str) -> None:
        assert table == "settlement_jobs"
        self.dsn = dsn
        self.table = table
        self.columns = "*"
        self.filters: list[tuple[str, str, Any]] = []
        self.row_limit: int | None = None

    def select(self, columns: str) -> "_PostgresQuery":
        self.columns = columns
        return self

    def eq(self, column: str, value: Any) -> "_PostgresQuery":
        self.filters.append((column, "=", value))
        return self

    def lte(self, column: str, value: Any) -> "_PostgresQuery":
        self.filters.append((column, "<=", value))
        return self

    def in_(self, column: str, values: list[Any]) -> "_PostgresQuery":
        self.filters.append((column, "IN", list(values)))
        return self

    def limit(self, value: int) -> "_PostgresQuery":
        self.row_limit = value
        return self

    def execute(self) -> Any:
        allowed_columns = {
            "id",
            "state",
            "dung_to_mint",
            "blocked_reason",
            "last_error",
            "created_at",
            "settlement_week",
            "legacy_evidence_only",
        }
        selected = [column.strip() for column in self.columns.split(",")]
        assert set(selected) <= allowed_columns
        clauses: list[str] = []
        params: list[Any] = []
        for column, operator, value in self.filters:
            assert column in allowed_columns
            if operator == "IN":
                clauses.append(f"{column} = ANY(%s)")
            else:
                clauses.append(f"{column} {operator} %s")
            params.append(value)
        sql = f"SELECT {', '.join(selected)} FROM public.{self.table}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if self.row_limit is not None:
            sql += " LIMIT %s"
            params.append(self.row_limit)
        with _open_connection(self.dsn, dict_rows=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return SimpleNamespace(data=[dict(row) for row in cursor.fetchall()])


class _PostgresClient:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def from_(self, table: str) -> _PostgresQuery:
        return _PostgresQuery(self.dsn, table)


def test_postgres_migration_runtime_fencing_recovery_and_exactness(
    postgres_dsn: str,
) -> None:
    from app.solana_direct import SETTLEMENT_COMPUTE_UNIT_LIMIT

    backend = Path(__file__).parents[2]
    migration = (backend / "sql" / "113_settlement_crank_state_machine.sql").read_text()
    compute_envelope_migration = (
        backend / "sql" / "126_settlement_compute_envelope.sql"
    ).read_text()
    v0_transport_migration = (
        backend / "sql" / "137_settlement_v0_transport.sql"
    ).read_text()
    legacy_ids = {status: uuid.uuid4() for status in ("pending", "processing", "failed", "completed")}
    fractional_id = uuid.uuid4()
    declared_live_id = uuid.uuid4()

    with _open_connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$; DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$; DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
            cursor.execute(
                """
                CREATE TABLE public.epoch_state (
                    id SMALLINT PRIMARY KEY,
                    current_epoch INTEGER NOT NULL
                );
                CREATE TABLE public.epoch_distributions (
                    id UUID PRIMARY KEY,
                    epoch INTEGER NOT NULL,
                    vault_signature CHAR(128) NOT NULL,
                    vault_id INTEGER,
                    is_points_period BOOLEAN NOT NULL DEFAULT TRUE,
                    cal_to_convert NUMERIC(12, 6) NOT NULL,
                    dung_to_mint INTEGER NOT NULL,
                    leaderboard_amount INTEGER DEFAULT 0,
                    staker_amount INTEGER DEFAULT 0,
                    local_legend_amount INTEGER DEFAULT 0,
                    pol_amount INTEGER DEFAULT 0,
                    protocol_amount INTEGER DEFAULT 0,
                    locked_staker_amount INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    tx_signature TEXT,
                    error_message TEXT,
                    processed_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute("INSERT INTO public.epoch_state VALUES (1, 99)")
            for offset, status in enumerate(("pending", "processing", "failed", "completed")):
                cursor.execute(
                    """
                    INSERT INTO public.epoch_distributions (
                        id, epoch, vault_signature, vault_id, cal_to_convert,
                        dung_to_mint, status, tx_signature
                    ) VALUES (%s, %s, %s, %s, 12.000000, 12, %s, %s)
                    """,
                    (
                        legacy_ids[status],
                        20 + offset,
                        chr(ord("a") + offset) * 128,
                        offset,
                        status,
                        f"legacy-{status}-signature" if status == "completed" else None,
                    ),
                )
            cursor.execute(
                """
                INSERT INTO public.epoch_distributions (
                    id, epoch, vault_signature, vault_id, is_points_period,
                    cal_to_convert, dung_to_mint, status
                ) VALUES (%s, 24, %s, 4, FALSE, 1.500000, 1, 'pending')
                """,
                (fractional_id, "e" * 128),
            )
            cursor.execute(
                """
                INSERT INTO public.epoch_distributions (
                    id, epoch, vault_signature, vault_id, is_points_period,
                    cal_to_convert, dung_to_mint, status
                ) VALUES (%s, 25, %s, 5, FALSE, 9.000000, 9, 'pending')
                """,
                (declared_live_id, "f" * 128),
            )
            cursor.execute(migration)
            cursor.execute(
                """
                SELECT id
                FROM public.settlement_jobs
                WHERE legacy_distribution_id IS NOT NULL
                ORDER BY created_at, id
                LIMIT 1
                """
            )
            historical_job_id = cursor.fetchone()[0]
            historical_attempt_id = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO public.settlement_attempts (
                    id, job_id, attempt_no, lease_token, outcome, tx_signature
                ) VALUES (%s, %s, 1, %s, 'submitted', 'historical-signature')
                """,
                (historical_attempt_id, historical_job_id, uuid.uuid4()),
            )
            cursor.execute(compute_envelope_migration)
            cursor.execute(v0_transport_migration)
            cursor.execute((backend / "sql/167_settlement_reconciliation_failures.sql").read_text())
            cursor.execute((backend / "supabase/migrations/20260908235715_reopen_zero_value_settlement_jobs.sql").read_text())

            cursor.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'settlement_attempts'
                  AND column_name = 'compute_unit_limit'
                """
            )
            assert cursor.fetchone()[0] == "YES"
            cursor.execute(
                "SELECT compute_unit_limit FROM public.settlement_attempts WHERE id = %s",
                (historical_attempt_id,),
            )
            assert cursor.fetchone()[0] is None
            for invalid_limit in (0, 1_400_001):
                with pytest.raises(
                    psycopg2.Error,
                    match="settlement_attempts_compute_unit_limit_check",
                ):
                    cursor.execute(
                        "UPDATE public.settlement_attempts SET compute_unit_limit = %s WHERE id = %s",
                        (invalid_limit, historical_attempt_id),
                    )
            for valid_limit in (1, 1_400_000):
                cursor.execute(
                    "UPDATE public.settlement_attempts SET compute_unit_limit = %s WHERE id = %s",
                    (valid_limit, historical_attempt_id),
                )
            cursor.execute(
                "UPDATE public.settlement_attempts SET compute_unit_limit = NULL WHERE id = %s",
                (historical_attempt_id,),
            )
            with pytest.raises(
                psycopg2.Error,
                match="settlement_attempts_v0_transport_check",
            ):
                cursor.execute(
                    """
                    UPDATE public.settlement_attempts
                    SET transaction_version = 0,
                        lookup_table_address = 'partial-v0-evidence'
                    WHERE id = %s
                    """,
                    (historical_attempt_id,),
                )
            cursor.execute(
                """
                SELECT
                    to_regprocedure(
                        'public.br_mark_settlement_prepared(uuid,uuid,text)'
                    ) IS NOT NULL,
                    to_regprocedure(
                        'public.br_mark_settlement_prepared(uuid,uuid,text,integer)'
                    ) IS NOT NULL
                """
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute(
                """
                SELECT p.pronargs, pg_catalog.pg_get_userbyid(p.proowner)
                FROM pg_catalog.pg_proc AS p
                JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname = 'br_mark_settlement_prepared'
                ORDER BY p.pronargs
                """
            )
            prepared_owners = cursor.fetchall()
            assert [row[0] for row in prepared_owners] == [3, 4]
            assert len({row[1] for row in prepared_owners}) == 1
            cursor.execute(
                """
                SELECT
                    has_function_privilege(
                        'service_role',
                        'public.br_mark_settlement_prepared(uuid,uuid,text,integer)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'anon',
                        'public.br_mark_settlement_prepared(uuid,uuid,text,integer)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'authenticated',
                        'public.br_mark_settlement_prepared(uuid,uuid,text,integer)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (True, False, False)

            cursor.execute(
                """
                SELECT legacy_distribution_id, state, blocked_reason, raw_snapshot,
                       tx_signature
                FROM public.settlement_jobs
                WHERE legacy_distribution_id IS NOT NULL
                """
            )
            imported = {str(row[0]): row for row in cursor.fetchall()}
            assert len(imported) == 6
            assert imported[str(legacy_ids["pending"])][1] == "blocked"
            assert imported[str(legacy_ids["processing"])][1] == "reconciling"
            assert imported[str(legacy_ids["failed"])][1] == "blocked"
            assert imported[str(legacy_ids["completed"])][1] == "reconciling"
            assert imported[str(legacy_ids["completed"])][4] == "legacy-completed-signature"
            fractional = imported[str(fractional_id)]
            assert fractional[1] == "blocked"
            assert "non-integral" in fractional[2]
            assert fractional[3]["legacy_original_cal_to_convert"] == "1.500000"
            assert fractional[3]["legacy_amount_valid"] is False
            assert imported[str(declared_live_id)][1] == "reconciling"
            for legacy_id in legacy_ids.values():
                assert imported[str(legacy_id)][3]["legacy_original_is_points_period"] is True

            from app.services.settlement_queue import SettlementQueue

            queue = SettlementQueue(_PostgresClient(postgres_dsn))
            assert asyncio.run(queue.has_unfinished_jobs(settlement_week=20)) is False

            cursor.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'epoch_distributions'
                  AND column_name = 'is_points_period'
                """
            )
            assert cursor.fetchone()[0].lower() == "false"

            cursor.execute(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'service_role'
                  AND table_schema = 'public'
                  AND table_name LIKE 'settlement_%'
                ORDER BY privilege_type
                """
            )
            assert {row[0] for row in cursor.fetchall()} == {"SELECT"}
            cursor.execute(
                """
                SELECT
                    has_table_privilege(
                        'service_role',
                        'public.settlement_lookup_table_generations',
                        'SELECT'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.settlement_lookup_table_generations',
                        'INSERT'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.settlement_lookup_table_generations',
                        'UPDATE'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.settlement_lookup_table_generations',
                        'DELETE'
                    )
                """
            )
            assert cursor.fetchone() == (False, False, False, False)
            cursor.execute(
                """
                SELECT
                    has_function_privilege(
                        'service_role',
                        'public.br_get_or_plan_settlement_lookup_table(text,text,text,text,text)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.br_rotate_settlement_lookup_table(uuid,text,text)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.br_record_settlement_lookup_table_ready(uuid,text,text,text,integer,text)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.br_mark_settlement_prepared_v0(uuid,uuid,text,integer,text,integer,text,text,integer)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.br_return_settlement_to_preparation(uuid,uuid,text)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'authenticated',
                        'public.br_mark_settlement_prepared_v0(uuid,uuid,text,integer,text,integer,text,text,integer)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (True, True, True, True, True, False)
            cursor.execute(
                """
                SELECT proconfig
                FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.prosecdef
                  AND p.proname LIKE 'br_%settlement%'
                """
            )
            assert all(row[0] == ["search_path=pg_catalog"] for row in cursor.fetchall())

            cursor.execute("TRUNCATE public.settlement_week_runs CASCADE")
            cursor.execute(
                """
                UPDATE public.settlement_planning_state SET
                    bootstrap_state = 'uninitialized', last_materialized_week = NULL,
                    bootstrap_counter_count = NULL, bootstrap_source_slot = NULL,
                    bootstrap_source_slot_min = NULL, bootstrap_source_slot_max = NULL,
                    bootstrap_scope_hash = NULL, bootstrap_min_open_week = NULL,
                    bootstrap_latest_finalizable_week = NULL,
                    bootstrap_evidence = NULL, bootstrapped_at = NULL
                WHERE id = 1
                """
            )

            mixed_vaults = [_bootstrap_vault(0, 8), _bootstrap_vault(1, 11)]
            with pytest.raises(psycopg2.Error, match="incomplete bootstrap scope"):
                cursor.execute(
                    "SELECT * FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)",
                    ("2", "9001", "12", Json(mixed_vaults[:1]), Json(_scope_evidence(2, 9001))),
                )
            cursor.execute(
                "SELECT bootstrap_state, last_materialized_week FROM public.settlement_planning_state"
            )
            assert cursor.fetchone() == ("uninitialized", None)

            bootstrap_args = (
                "2",
                "9001",
                "12",
                Json(mixed_vaults),
                Json(_scope_evidence(2, 9001)),
            )
            cursor.execute(
                """
                SELECT last_materialized_week, bootstrap_scope_hash, bootstrapped_at
                FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)
                """,
                bootstrap_args,
            )
            bootstrap = cursor.fetchone()
            assert str(bootstrap[0]) == "7"
            cursor.execute(
                """
                SELECT last_materialized_week, bootstrap_scope_hash, bootstrapped_at
                FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)
                """,
                bootstrap_args,
            )
            assert cursor.fetchone() == bootstrap
            cursor.execute("SELECT current_epoch FROM public.epoch_state WHERE id = 1")
            assert str(cursor.fetchone()[0]) == "99"
            with pytest.raises(psycopg2.Error, match="different authoritative evidence"):
                cursor.execute(
                    "SELECT * FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)",
                    ("2", "9002", "12", Json(mixed_vaults), Json(_scope_evidence(2, 9002))),
                )

            week8_jobs = [
                _job(0, week=8, state="ready", dung=U64_MAX),
                _job(1, week=11, state="skipped_empty", skip_reason="already advanced empty"),
            ]
            materialize_sql = """
                SELECT * FROM public.br_materialize_settlement_week(
                    %s,%s,%s,%s,%s,%s,%s
                )
            """
            materialize_args = (
                "8",
                "2",
                "9010",
                "9010",
                "9010",
                Json(_scope_evidence(2, 9010)),
                Json(week8_jobs),
            )
            with pytest.raises(psycopg2.Error, match="incomplete VaultCounter scope"):
                cursor.execute(materialize_sql, (*materialize_args[:-1], Json(week8_jobs[:1])))
            cursor.execute("SELECT last_materialized_week FROM public.settlement_planning_state")
            assert str(cursor.fetchone()[0]) == "7"
            cursor.execute("SELECT count(*) FROM public.settlement_week_runs WHERE settlement_week = 8")
            assert cursor.fetchone()[0] == 0

            cursor.execute(materialize_sql, materialize_args)
            materialized = cursor.fetchone()
            assert materialized[3:] == (2, 1, 1)
            cursor.execute(
                "SELECT dung_to_mint::text FROM public.settlement_jobs WHERE vault_id = 0"
            )
            assert cursor.fetchone()[0] == str(U64_MAX)

    def claim(worker_id: str) -> list[tuple[str, str]]:
        with _open_connection(postgres_dsn) as worker_connection:
            with worker_connection.cursor() as worker_cursor:
                worker_cursor.execute(
                    """
                    SELECT id::text, lease_token::text
                    FROM public.br_claim_settlement_job(%s, 30, NULL)
                    """,
                    (worker_id,),
                )
                return list(worker_cursor.fetchall())

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, ("worker-a", "worker-b")))
    nonempty_claims = [rows[0] for rows in claims if rows]
    assert len(nonempty_claims) == 1
    job_id, stale_token = nonempty_claims[0]

    transport = {
        "transaction_version": "0",
        "lookup_table_address": "lookup-table-1",
        "lookup_table_generation": "1",
        "manifest_sha256": "a" * 64,
        "last_extended_slot": "101",
        "planned_serialized_bytes": "815",
    }

    with _open_connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, generation, lookup_table_address, status
                FROM public.br_get_or_plan_settlement_lookup_table(
                    '9999', 'program-1', 'payer-1', '100', 'lookup-table-1'
                )
                """
            )
            generation_id, generation_no, table_address, generation_status = cursor.fetchone()
            assert (generation_no, table_address, generation_status) == (
                1,
                "lookup-table-1",
                "planned",
            )
            cursor.execute(
                """
                SELECT id, lookup_table_address
                FROM public.br_get_or_plan_settlement_lookup_table(
                    '9999', 'program-1', 'payer-1', '101', 'ignored-candidate'
                )
                """
            )
            assert cursor.fetchone() == (generation_id, "lookup-table-1")
            cursor.execute(
                """
                SELECT public.br_record_settlement_lookup_table_ready(
                    %s, 'create-signature', 'extend-signature', '101', 25, %s
                )
                """,
                (generation_id, "a" * 64),
            )
            assert cursor.fetchone()[0] is True

            cursor.execute(
                "SELECT public.br_return_settlement_to_preparation(%s::uuid,%s::uuid,%s)",
                (job_id, stale_token, "manifest changed before signing"),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT state, precondition_result FROM public.settlement_jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone() == ("precondition_retry", None)
            cursor.execute(
                """
                SELECT id::text, lease_token::text
                FROM public.br_claim_settlement_preparation('prep-worker', 30, NULL)
                """
            )
            prep_job_id, prep_token = cursor.fetchone()
            assert prep_job_id == job_id
            cursor.execute(
                """
                SELECT public.br_finish_settlement_preparation(
                    %s::uuid, %s::uuid, TRUE, NULL, 1, %s::jsonb
                )
                """,
                (
                    job_id,
                    prep_token,
                    Json({"completed": True, "transport": transport}),
                ),
            )
            cursor.execute(
                """
                SELECT id::text, lease_token::text
                FROM public.br_claim_settlement_job('worker-v0', 30, NULL)
                """
            )
            job_id_again, stale_token = cursor.fetchone()
            assert job_id_again == job_id
            cursor.execute(
                "SELECT attempt_count FROM public.settlement_jobs WHERE id = %s",
                (job_id,),
            )
            attempt_no = cursor.fetchone()[0]
            with pytest.raises(
                psycopg2.Error,
                match="prepared v0 settlement transport evidence is invalid",
            ):
                cursor.execute(
                    """
                    SELECT public.br_mark_settlement_prepared_v0(
                        %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        job_id,
                        stale_token,
                        "oversize-v0-signature",
                        SETTLEMENT_COMPUTE_UNIT_LIMIT,
                        transport["lookup_table_address"],
                        1,
                        transport["manifest_sha256"],
                        transport["last_extended_slot"],
                        901,
                    ),
                )
            cursor.execute(
                """
                SELECT public.br_mark_settlement_prepared_v0(
                    %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    job_id,
                    stale_token,
                    "v0-prepared-signature",
                    SETTLEMENT_COMPUTE_UNIT_LIMIT,
                    transport["lookup_table_address"],
                    1,
                    transport["manifest_sha256"],
                    transport["last_extended_slot"],
                    815,
                ),
            )
            cursor.execute(
                """
                SELECT transaction_version, lookup_table_address,
                       lookup_table_generation, transport_manifest_sha256,
                       lookup_table_last_extended_slot, signed_transaction_bytes
                FROM public.settlement_attempts
                WHERE job_id = %s AND attempt_no = %s
                """,
                (job_id, attempt_no),
            )
            assert cursor.fetchone() == (
                0,
                "lookup-table-1",
                1,
                "a" * 64,
                101,
                815,
            )
            cursor.execute(
                """
                UPDATE public.settlement_attempts
                SET outcome = 'claimed', tx_signature = NULL,
                    compute_unit_limit = NULL, transaction_version = NULL,
                    lookup_table_address = NULL, lookup_table_generation = NULL,
                    transport_manifest_sha256 = NULL,
                    lookup_table_last_extended_slot = NULL,
                    signed_transaction_bytes = NULL
                WHERE job_id = %s AND attempt_no = %s
                """,
                (job_id, attempt_no),
            )
            with pytest.raises(
                psycopg2.Error,
                match="prepared settlement job signature fence was lost",
            ):
                cursor.execute(
                    """
                    SELECT public.br_mark_settlement_prepared_v0(
                        %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        job_id,
                        stale_token,
                        "replacement-v0-signature",
                        SETTLEMENT_COMPUTE_UNIT_LIMIT,
                        transport["lookup_table_address"],
                        1,
                        transport["manifest_sha256"],
                        transport["last_extended_slot"],
                        815,
                    ),
                )
            cursor.execute(
                """
                UPDATE public.settlement_attempts
                SET outcome = 'prepared', tx_signature = 'v0-prepared-signature',
                    compute_unit_limit = %s, transaction_version = 0,
                    lookup_table_address = %s, lookup_table_generation = 1,
                    transport_manifest_sha256 = %s,
                    lookup_table_last_extended_slot = %s,
                    signed_transaction_bytes = 815
                WHERE job_id = %s AND attempt_no = %s
                """,
                (
                    SETTLEMENT_COMPUTE_UNIT_LIMIT,
                    transport["lookup_table_address"],
                    transport["manifest_sha256"],
                    transport["last_extended_slot"],
                    job_id,
                    attempt_no,
                ),
            )
            with pytest.raises(
                psycopg2.Error,
                match="unsigned settlement preparation fence was lost",
            ):
                cursor.execute(
                    "SELECT public.br_return_settlement_to_preparation(%s::uuid,%s::uuid,%s)",
                    (job_id, stale_token, "must not reopen signed settlement"),
                )
            cursor.execute(
                "UPDATE public.settlement_jobs SET prepared_tx_signature = NULL WHERE id = %s",
                (job_id,),
            )
            cursor.execute(
                """
                UPDATE public.settlement_attempts
                SET outcome = 'claimed', tx_signature = NULL,
                    compute_unit_limit = NULL, transaction_version = NULL,
                    lookup_table_address = NULL, lookup_table_generation = NULL,
                    transport_manifest_sha256 = NULL,
                    lookup_table_last_extended_slot = NULL,
                    signed_transaction_bytes = NULL
                WHERE job_id = %s AND attempt_no = %s
                """,
                (job_id, attempt_no),
            )
            cursor.execute(
                "SELECT public.br_mark_settlement_prepared(%s::uuid,%s::uuid,%s)",
                (job_id, stale_token, "compatibility-signature"),
            )
            cursor.execute(
                """
                SELECT j.prepared_tx_signature, a.tx_signature, a.compute_unit_limit
                FROM public.settlement_jobs AS j
                JOIN public.settlement_attempts AS a
                  ON a.job_id = j.id AND a.attempt_no = j.attempt_count
                WHERE j.id = %s
                """,
                (job_id,),
            )
            assert cursor.fetchone() == (
                "compatibility-signature",
                "compatibility-signature",
                None,
            )
            cursor.execute(
                "UPDATE public.settlement_jobs SET prepared_tx_signature = NULL WHERE id = %s",
                (job_id,),
            )
            cursor.execute(
                """
                UPDATE public.settlement_attempts
                SET outcome = 'claimed', tx_signature = NULL
                WHERE job_id = %s AND attempt_no = %s
                """,
                (job_id, attempt_no),
            )
            with pytest.raises(psycopg2.Error, match="compute unit limit is required"):
                cursor.execute(
                    "SELECT public.br_mark_settlement_prepared(%s::uuid,%s::uuid,%s,NULL)",
                    (job_id, stale_token, "missing-limit-signature"),
                )
            cursor.execute(
                """
                SELECT j.prepared_tx_signature, a.tx_signature, a.compute_unit_limit
                FROM public.settlement_jobs AS j
                JOIN public.settlement_attempts AS a
                  ON a.job_id = j.id AND a.attempt_no = j.attempt_count
                WHERE j.id = %s
                """,
                (job_id,),
            )
            assert cursor.fetchone() == (None, None, None)
            cursor.execute(
                "DELETE FROM public.settlement_attempts WHERE job_id = %s AND attempt_no = %s",
                (job_id, attempt_no),
            )
            with pytest.raises(psycopg2.Error, match="settlement attempt fence was lost"):
                cursor.execute(
                    "SELECT public.br_mark_settlement_prepared(%s::uuid,%s::uuid,%s,%s)",
                    (
                        job_id,
                        stale_token,
                        "must-roll-back-signature",
                        SETTLEMENT_COMPUTE_UNIT_LIMIT,
                    ),
                )
            cursor.execute(
                "SELECT prepared_tx_signature FROM public.settlement_jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone()[0] is None
            cursor.execute(
                """
                INSERT INTO public.settlement_attempts (
                    job_id, attempt_no, lease_token, outcome
                ) VALUES (%s, %s, %s, 'claimed')
                """,
                (job_id, attempt_no, stale_token),
            )
            cursor.execute(
                "SELECT public.br_mark_settlement_prepared(%s::uuid,%s::uuid,%s,%s)",
                (
                    job_id,
                    stale_token,
                    "local-prepared-signature",
                    SETTLEMENT_COMPUTE_UNIT_LIMIT,
                ),
            )
            cursor.execute(
                """
                SELECT j.prepared_tx_signature, a.tx_signature, a.compute_unit_limit
                FROM public.settlement_jobs AS j
                JOIN public.settlement_attempts AS a
                  ON a.job_id = j.id AND a.attempt_no = j.attempt_count
                WHERE j.id = %s
                """,
                (job_id,),
            )
            assert cursor.fetchone() == (
                "local-prepared-signature",
                "local-prepared-signature",
                SETTLEMENT_COMPUTE_UNIT_LIMIT,
            )
            cursor.execute(
                "UPDATE public.settlement_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                (job_id,),
            )
            cursor.execute("SELECT public.br_reap_stale_settlement_leases()")
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT state, prepared_tx_signature FROM public.settlement_jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone() == ("reconciling", "local-prepared-signature")
            with pytest.raises(psycopg2.Error, match="fence was lost"):
                cursor.execute(
                    "SELECT public.br_mark_settlement_submitted(%s::uuid,%s::uuid,%s)",
                    (job_id, stale_token, "replacement-signature"),
                )
            cursor.execute("SELECT count(*) FROM public.br_claim_settlement_job('worker-c',30,NULL)")
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                """
                SELECT id::text, lease_token::text
                FROM public.br_claim_settlement_reconciliation('reconciler',30,NULL)
                """
            )
            reconciled_job_id, reconcile_token = cursor.fetchone()
            assert reconciled_job_id == job_id
            evidence = {
                "indexed_distribution": {
                    "vault_id": "0",
                    "epoch": "8",
                    "tx_signature": "indexed-finalized-signature",
                    "total_distributed": str(U64_MAX),
                }
            }
            cursor.execute(
                """
                SELECT public.br_finish_settlement_reconciliation(
                    p_job_id => %s::uuid,
                    p_lease_token => %s::uuid,
                    p_decision => 'confirmed',
                    p_evidence => %s::jsonb,
                    p_signature_state => 'finalized',
                    p_chain_commitment => 'finalized',
                    p_observed_open_week => '9',
                    p_indexed_tx_signature => 'indexed-finalized-signature',
                    p_indexed_signature_finalized => TRUE,
                    p_recovered_tx_signature => NULL,
                    p_error => NULL,
                    p_retry_seconds => 1
                )
                """,
                (job_id, reconcile_token, Json(evidence)),
            )
            cursor.execute(
                "SELECT state, tx_signature, terminal_evidence_quality FROM public.settlement_jobs WHERE id = %s",
                (job_id,),
            )
            assert cursor.fetchone() == (
                "confirmed",
                "indexed-finalized-signature",
                "finalized_indexed_distribution",
            )
            cursor.execute(
                "SELECT tx_signature, raw_pending_dung::text, total_distributed::text FROM public.settlement_notification_outbox WHERE job_id = %s",
                (job_id,),
            )
            assert cursor.fetchone() == (
                "indexed-finalized-signature",
                str(U64_MAX),
                str(U64_MAX),
            )
            cursor.execute(
                "SELECT array_agg(outcome ORDER BY attempt_no) FROM public.settlement_attempts WHERE job_id = %s",
                (job_id,),
            )
            assert cursor.fetchone()[0] == ["blocked", "prepared"]
            cursor.execute(
                "SELECT state FROM public.settlement_week_runs WHERE settlement_week = 8"
            )
            assert cursor.fetchone()[0] == "confirmed"

            week9_jobs = [
                _job(0, week=9, state="precondition_pending", dung=5),
                _job(1, week=12, state="skipped_empty", skip_reason="already advanced empty"),
            ]
            cursor.execute(
                materialize_sql,
                (
                    "9",
                    "2",
                    "9020",
                    "9020",
                    "9020",
                    Json(_scope_evidence(2, 9020)),
                    Json(week9_jobs),
                ),
            )

    from app.services.settlement_queue import SettlementQueue

    queue = SettlementQueue(_PostgresClient(postgres_dsn))
    status = asyncio.run(queue.status())
    assert status["preconditions_pending"] == 1
    assert status["healthy"] is False
    assert asyncio.run(queue.has_unfinished_jobs(settlement_week=9)) is True

    with _open_connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id::text, lease_token::text
                FROM public.br_claim_settlement_preparation('legend-worker',30,'0')
                """
            )
            prep_job_id, prep_token = cursor.fetchone()
            intent = {"required": False, "reason": "term_not_due"}
            cursor.execute(
                "SELECT count(*) FROM public.br_set_settlement_precondition_intent(%s::uuid,%s::uuid,%s::jsonb)",
                (prep_job_id, prep_token, Json(intent)),
            )
            assert cursor.fetchone()[0] == 1
            with pytest.raises(psycopg2.Error, match="already frozen"):
                cursor.execute(
                    "SELECT * FROM public.br_set_settlement_precondition_intent(%s::uuid,%s::uuid,%s::jsonb)",
                    (prep_job_id, prep_token, Json({"required": True})),
                )
            cursor.execute(
                """
                SELECT public.br_finish_settlement_preparation(
                    %s::uuid,%s::uuid,TRUE,NULL,1,%s::jsonb
                )
                """,
                (prep_job_id, prep_token, Json({"completed": True, "intent": intent})),
            )
            cursor.execute(
                "SELECT id::text, lease_token::text FROM public.br_claim_settlement_job('block-worker',30,'0')"
            )
            blocked_job_id, blocked_token = cursor.fetchone()
            cursor.execute(
                "SELECT public.br_mark_settlement_blocked(%s::uuid,%s::uuid,%s)",
                (blocked_job_id, blocked_token, "invalid frozen settlement plan"),
            )

    status = asyncio.run(queue.status())
    assert status["blocked"] == 1
    assert status["blocked_reasons"] == ["invalid frozen settlement plan"]
    assert status["oldest_blocked_at"] is not None
    assert status["healthy"] is False

    with _open_connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.settlement_jobs
                SET last_error_class = 'repairable_preflight',
                    next_attempt_at = now() - interval '1 second'
                WHERE id = %s
                """,
                (blocked_job_id,),
            )
            cursor.execute("SELECT public.br_retry_repairable_settlement_jobs(1)")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT state FROM public.settlement_jobs WHERE id = %s", (blocked_job_id,))
            assert cursor.fetchone()[0] == "reconciling"
            cursor.execute(
                """
                INSERT INTO public.settlement_week_runs (
                    settlement_week, state, source_kind, vault_counter_count,
                    expected_job_count, materialized_job_count
                ) VALUES (30, 'materialized', 'authoritative', 2, 2, 1)
                RETURNING id
                """
            )
            incomplete_run_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO public.settlement_jobs (
                    run_id, settlement_week, vault_id, vault_signature,
                    source_kind, legacy_evidence_only, state, skip_reason,
                    expected_pre_open_week, raw_snapshot
                ) VALUES (%s, 30, 0, 'incomplete-vault', 'authoritative', FALSE,
                          'skipped_empty', 'empty', 30, '{}'::jsonb)
                """,
                (incomplete_run_id,),
            )
            cursor.execute("SELECT public.br_refresh_settlement_run(%s)", (incomplete_run_id,))
            cursor.execute(
                "SELECT state, materialized_job_count, expected_job_count FROM public.settlement_week_runs WHERE id = %s",
                (incomplete_run_id,),
            )
            assert cursor.fetchone() == ("materialized", 1, 2)

            cursor.execute("TRUNCATE public.settlement_week_runs CASCADE")
            cursor.execute(
                """
                UPDATE public.settlement_planning_state SET
                    bootstrap_state = 'uninitialized', last_materialized_week = NULL,
                    bootstrap_counter_count = NULL, bootstrap_source_slot = NULL,
                    bootstrap_source_slot_min = NULL, bootstrap_source_slot_max = NULL,
                    bootstrap_scope_hash = NULL, bootstrap_min_open_week = NULL,
                    bootstrap_latest_finalizable_week = NULL,
                    bootstrap_evidence = NULL, bootstrapped_at = NULL
                WHERE id = 1
                """
            )
            zero_args = (
                "0",
                "9900",
                "12",
                Json([]),
                Json(_scope_evidence(0, 9900)),
            )
            cursor.execute(
                "SELECT last_materialized_week, bootstrap_min_open_week, bootstrap_evidence FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)",
                zero_args,
            )
            zero_bootstrap = cursor.fetchone()
            assert str(zero_bootstrap[0]) == "12"
            assert zero_bootstrap[1] is None
            assert zero_bootstrap[2]["zero_vault_policy"] == "cursor_equals_latest_finalizable_week"
            cursor.execute(
                "SELECT last_materialized_week FROM public.br_bootstrap_settlement_planning(%s,%s,%s,%s,%s)",
                zero_args,
            )
            assert str(cursor.fetchone()[0]) == "12"

    # H1 cutover: two historical skips, with the cursor already beyond both.
    # Recovery may reopen only the finalized stored open week, never signed work.
    from app.services.settlement_chain import build_materialization_job
    from test_settlement_state_machine import _vault
    with _open_connection(postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            for week in (13, 14):
                cursor.execute(
                    "SELECT * FROM public.br_materialize_settlement_week(%s,%s,%s,%s,%s,%s,%s)",
                    (str(week), "1", "9901", "9901", "9901", Json(_scope_evidence(1, 9901)),
                     Json([_job(0, week=week, state="skipped_empty", skip_reason="empty_current_week")])),
                )
            def recover(open_week, latest=14):
                job = build_materialization_job(_vault(0, open_week=open_week), settlement_week=open_week)
                job["vault_signature"] = "vault-signature-0"
                job["state"] = "precondition_pending"
                cursor.execute("SELECT public.br_reopen_zero_value_settlement_jobs(%s,%s,%s) AS changed",
                               (str(latest), Json(_scope_evidence(1, 9902)), Json([job])))
                return cursor.fetchone()["changed"]
            assert recover(13, latest=12) == 0
            assert recover(13) == 1
            assert recover(13) == 0
            cursor.execute("SELECT settlement_week,state,open_week_recovery_evidence FROM public.settlement_jobs ORDER BY settlement_week")
            recovered_rows = cursor.fetchall()
            assert [(int(r["settlement_week"]), r["state"]) for r in recovered_rows] == [
                (13, "precondition_pending"), (14, "skipped_empty")]
            assert recovered_rows[0]["open_week_recovery_evidence"]["prior_job"]["skip_reason"] == "empty_current_week"
            # A stored signature is an absolute recovery fence even on a skip row.
            cursor.execute("UPDATE public.settlement_jobs SET prepared_tx_signature='durable-signature' WHERE settlement_week=14")
            cursor.execute("SELECT to_jsonb(j) AS row FROM public.settlement_jobs j WHERE settlement_week=14")
            before = cursor.fetchone()["row"]
            assert recover(14) == 0
            cursor.execute("SELECT to_jsonb(j) AS row FROM public.settlement_jobs j WHERE settlement_week=14")
            assert cursor.fetchone()["row"] == before
            cursor.execute("SELECT last_materialized_week FROM public.settlement_planning_state")
            assert int(cursor.fetchone()["last_materialized_week"]) == 14
