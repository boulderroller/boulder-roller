from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

import psycopg2

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "129_vault_creation_handoff.sql"
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260716_137_vault_creation_handoff.sql"
)
COMPATIBILITY_MIGRATION = (
    BACKEND_ROOT / "sql" / "135_vault_handoff_optional_balance_ledger.sql"
)
COMPATIBILITY_DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260717_143_vault_handoff_optional_balance_ledger.sql"
)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                CREATE ROLE anon NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                CREATE ROLE authenticated NOLOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                CREATE ROLE service_role NOLOGIN;
            END IF;
        END;
        $$;
        GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

        CREATE TABLE public.indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE,
            signature_hash_hex TEXT NOT NULL UNIQUE,
            pda TEXT NOT NULL UNIQUE,
            minter TEXT NOT NULL,
            name TEXT NOT NULL,
            vert_m DOUBLE PRECISION NOT NULL,
            distance_m INTEGER NOT NULL,
            avg_gradient_pct DOUBLE PRECISION NOT NULL,
            total_completions BIGINT NOT NULL DEFAULT 0,
            signature_v2_hex TEXT,
            signature_version SMALLINT,
            start_lat DOUBLE PRECISION,
            start_lon DOUBLE PRECISION,
            end_lat DOUBLE PRECISION,
            end_lon DOUBLE PRECISION,
            backfill_status TEXT,
            backfill_started_at TIMESTAMPTZ,
            backfill_completed_at TIMESTAMPTZ,
            backfill_completions_found INTEGER DEFAULT 0,
            backfill_error TEXT,
            chain_slot BIGINT,
            indexed_at TIMESTAMPTZ
        );

        CREATE TABLE public.vault_backfill_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id BIGINT NOT NULL REFERENCES public.indexed_vaults(id),
            vault_signature TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 0,
            total_candidates INTEGER DEFAULT 0,
            processed_count INTEGER DEFAULT 0,
            matched_count INTEGER DEFAULT 0,
            leaderboard_updates INTEGER DEFAULT 0,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            UNIQUE (vault_id)
        );

        CREATE TABLE public.balance_operations (
            operation_id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            reference_type TEXT,
            reference_id TEXT,
            confirmation_status TEXT NOT NULL,
            projection_status TEXT NOT NULL,
            rider_state TEXT,
            failure_reason TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        INSERT INTO public.indexed_vaults (
            id, signature_hex, signature_hash_hex, pda, minter, name,
            vert_m, distance_m, avg_gradient_pct, total_completions,
            signature_v2_hex, signature_version,
            start_lat, start_lon, end_lat, end_lon,
            backfill_status, chain_slot, indexed_at
        ) VALUES (
            9, repeat('09', 64), repeat('19', 32), 'vault-pda-9',
            'legacy-rider', 'Legacy Vault', 90, 900, 10, 4,
            repeat('29', 64), 2, 39.90, -75.10, 39.91, -75.09,
            'queued', 90, TIMESTAMPTZ '2026-07-15 10:00:00+00'
        );

        INSERT INTO public.vault_backfill_jobs (
            vault_id, vault_signature, status, priority
        ) VALUES (9, repeat('09', 64), 'queued', 10);

        INSERT INTO public.indexed_vaults (
            id, signature_hex, signature_hash_hex, pda, minter, name,
            vert_m, distance_m, avg_gradient_pct, total_completions,
            signature_v2_hex, signature_version,
            start_lat, start_lon, end_lat, end_lon,
            backfill_status, chain_slot, indexed_at
        ) VALUES (
            8, repeat('08', 64), repeat('18', 32), 'vault-pda-8',
            'legacy-shell-rider', 'Legacy Partial Shell', 80, 800, 10, 0,
            repeat('28', 64), 2, 39.80, NULL, NULL, NULL,
            'queued', NULL, NULL
        );

        INSERT INTO public.vault_backfill_jobs (
            vault_id, vault_signature, status, priority
        ) VALUES (8, repeat('08', 64), 'queued', 20);
        """
    )


def _stage(
    cursor: Any,
    *,
    vault_id: int,
    pda: str,
    signature_byte: str,
    hash_byte: str,
    v2_byte: str,
    creator: str,
    tx_signature: str,
    source_climb_id: uuid.UUID,
) -> tuple[uuid.UUID, bool, int | None]:
    cursor.execute("SET ROLE service_role")
    try:
        cursor.execute(
            """
            SELECT job_id, projection_ready, chain_slot
            FROM public.stage_confirmed_vault_creation(
                %s, %s, repeat(%s, 64), repeat(%s, 32), repeat(%s, 64),
                39.95, -75.16, 39.96, -75.15,
                %s, %s, %s, %s, 100
            )
            """,
            (
                vault_id,
                pda,
                signature_byte,
                hash_byte,
                v2_byte,
                creator,
                tx_signature,
                str(source_climb_id),
                f"op-vault-{vault_id}",
            ),
        )
        return cursor.fetchone()
    finally:
        cursor.execute("RESET ROLE")


def _insert_balance_operation(cursor: Any, vault_id: int) -> None:
    cursor.execute(
        """
        INSERT INTO public.balance_operations (
            operation_id, action_type, reference_type, reference_id,
            confirmation_status, projection_status, rider_state
        ) VALUES (
            %s, 'create_vault', 'vault', %s, 'confirmed', 'not_started', 'Delayed'
        )
        """,
        (f"op-vault-{vault_id}", str(vault_id)),
    )


def _insert_indexer_projection(
    cursor: Any,
    *,
    vault_id: int,
    signature_byte: str,
    hash_byte: str,
    pda: str,
    slot: int,
    completions: int,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.indexed_vaults (
            id, signature_hex, signature_hash_hex, pda, minter, name,
            vert_m, distance_m, avg_gradient_pct, total_completions,
            chain_slot, indexed_at
        ) VALUES (
            %s, repeat(%s, 64), repeat(%s, 32), %s,
            'chain-minter', 'Chain Name', 120, 1200, 10,
            %s, %s, now()
        )
        """,
        (vault_id, signature_byte, hash_byte, pda, completions, slot),
    )


def test_vault_creation_handoff_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_vault_handoff_balance_compatibility_migration_is_exactly_mirrored() -> None:
    assert COMPATIBILITY_MIGRATION.read_bytes() == (
        COMPATIBILITY_DEPLOY_MIGRATION.read_bytes()
    )


def test_vault_creation_handoff_preserves_projection_ownership(
    postgres_dsn: str,
) -> None:
    metadata_first_source = uuid.uuid4()
    indexer_first_source = uuid.uuid4()

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))

            for signature in (
                "public.queue_vault_backfill(bigint,text,integer)",
                "public.reconcile_waiting_vault_backfills(integer)",
                "public.get_ready_vault_backfill_jobs(integer)",
                "public.start_backfill_job(uuid)",
                "public.complete_backfill_job(uuid,integer,integer)",
                "public.fail_backfill_job(uuid,text)",
                (
                    "public.stage_confirmed_vault_creation("
                    "bigint,text,text,text,text,double precision,double precision,"
                    "double precision,double precision,text,text,uuid,text,integer)"
                ),
            ):
                cursor.execute(
                    """
                    SELECT
                        has_function_privilege('service_role', %s, 'EXECUTE'),
                        has_function_privilege('anon', %s, 'EXECUTE'),
                        has_function_privilege('authenticated', %s, 'EXECUTE')
                    """,
                    (signature, signature, signature),
                )
                assert cursor.fetchone() == (True, False, False), signature

            for table_name in (
                "public.vault_creation_handoffs",
                "public.vault_backfill_jobs",
            ):
                cursor.execute(
                    """
                    SELECT
                        has_table_privilege('service_role', %s, 'SELECT'),
                        has_table_privilege('service_role', %s, 'INSERT'),
                        has_table_privilege('service_role', %s, 'UPDATE'),
                        has_table_privilege('anon', %s, 'SELECT'),
                        has_table_privilege('authenticated', %s, 'SELECT')
                    """,
                    (table_name, table_name, table_name, table_name, table_name),
                )
                assert cursor.fetchone() == (
                    False,
                    False,
                    False,
                    False,
                    False,
                ), table_name

            cursor.execute(
                """
                SELECT c.confrelid::regclass::text
                FROM pg_constraint AS c
                WHERE c.conrelid = 'public.vault_backfill_jobs'::regclass
                  AND c.contype = 'f'
                  AND c.conkey = ARRAY[
                      (
                          SELECT attnum
                          FROM pg_attribute
                          WHERE attrelid = c.conrelid
                            AND attname = 'vault_id'
                      )
                  ]::smallint[]
                """
            )
            assert cursor.fetchone()[0] == "vault_creation_handoffs"

            cursor.execute(
                """
                SELECT vault_pda, projected_chain_slot
                FROM public.vault_creation_handoffs
                WHERE vault_id = 9
                """
            )
            assert cursor.fetchone() == ("vault-pda-9", 90)

            cursor.execute(
                """
                SELECT start_lat, start_lon, end_lat, end_lon
                FROM public.vault_creation_handoffs
                WHERE vault_id = 8
                """
            )
            assert cursor.fetchone() == (None, None, None, None)
            cursor.execute(
                "SELECT status FROM public.vault_backfill_jobs WHERE vault_id = 8"
            )
            assert cursor.fetchone()[0] == "waiting_projection"

            cursor.execute(
                "UPDATE public.vault_backfill_jobs SET status = 'queued' WHERE vault_id = 8"
            )
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                "SELECT vault_id FROM public.get_ready_vault_backfill_jobs(10)"
            )
            assert 8 not in {row[0] for row in cursor.fetchall()}
            cursor.execute("RESET ROLE")
            cursor.execute(
                "SELECT status FROM public.vault_backfill_jobs WHERE vault_id = 8"
            )
            assert cursor.fetchone()[0] == "waiting_projection"

            _insert_balance_operation(cursor, 21)
            first_job, first_ready, first_slot = _stage(
                cursor,
                vault_id=21,
                pda="vault-pda-21",
                signature_byte="21",
                hash_byte="31",
                v2_byte="41",
                creator="rider-21",
                tx_signature="tx-create-21",
                source_climb_id=metadata_first_source,
            )
            assert first_ready is False
            assert first_slot is None

            cursor.execute("SELECT count(*) FROM public.indexed_vaults WHERE id = 21")
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                """
                SELECT status, priority
                FROM public.vault_backfill_jobs
                WHERE vault_id = 21
                """
            )
            assert cursor.fetchone() == ("waiting_projection", 100)
            cursor.execute(
                """
                SELECT projection_status, rider_state
                FROM public.balance_operations
                WHERE reference_id = '21'
                """
            )
            assert cursor.fetchone() == ("pending", "Pending")

            _insert_indexer_projection(
                cursor,
                vault_id=21,
                signature_byte="21",
                hash_byte="31",
                pda="vault-pda-21",
                slot=200,
                completions=7,
            )
            cursor.execute(
                """
                SELECT
                    name, total_completions, chain_slot,
                    signature_v2_hex, signature_version,
                    start_lat, start_lon, end_lat, end_lon
                FROM public.indexed_vaults
                WHERE id = 21
                """
            )
            assert cursor.fetchone() == (
                "Chain Name",
                7,
                200,
                "41" * 64,
                2,
                39.95,
                -75.16,
                39.96,
                -75.15,
            )
            cursor.execute(
                """
                SELECT projected_chain_slot, projection_attached_at IS NOT NULL
                FROM public.vault_creation_handoffs
                WHERE vault_id = 21
                """
            )
            assert cursor.fetchone() == (200, True)
            cursor.execute(
                "SELECT status FROM public.vault_backfill_jobs WHERE vault_id = 21"
            )
            assert cursor.fetchone()[0] == "queued"
            cursor.execute(
                """
                SELECT projection_status, rider_state
                FROM public.balance_operations
                WHERE reference_id = '21'
                """
            )
            assert cursor.fetchone() == ("recorded", None)

            retry_job, retry_ready, retry_slot = _stage(
                cursor,
                vault_id=21,
                pda="vault-pda-21",
                signature_byte="21",
                hash_byte="31",
                v2_byte="41",
                creator="rider-21",
                tx_signature="tx-create-21",
                source_climb_id=metadata_first_source,
            )
            assert (retry_job, retry_ready, retry_slot) == (first_job, True, 200)
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM public.vault_creation_handoffs WHERE vault_id = 21),
                    (SELECT count(*) FROM public.vault_backfill_jobs WHERE vault_id = 21),
                    (SELECT total_completions FROM public.indexed_vaults WHERE id = 21),
                    (SELECT chain_slot FROM public.indexed_vaults WHERE id = 21)
                """
            )
            assert cursor.fetchone() == (1, 1, 7, 200)
            cursor.execute(
                """
                SELECT projection_status, rider_state
                FROM public.balance_operations
                WHERE reference_id = '21'
                """
            )
            assert cursor.fetchone() == ("recorded", None)

            _insert_balance_operation(cursor, 22)
            _insert_indexer_projection(
                cursor,
                vault_id=22,
                signature_byte="22",
                hash_byte="32",
                pda="vault-pda-22",
                slot=300,
                completions=11,
            )
            second_job, second_ready, second_slot = _stage(
                cursor,
                vault_id=22,
                pda="vault-pda-22",
                signature_byte="22",
                hash_byte="32",
                v2_byte="42",
                creator="rider-22",
                tx_signature="tx-create-22",
                source_climb_id=indexer_first_source,
            )
            assert second_job != first_job
            assert second_ready is True
            assert second_slot == 300
            cursor.execute(
                """
                SELECT name, total_completions, chain_slot, signature_v2_hex,
                       start_lat, start_lon, end_lat, end_lon
                FROM public.indexed_vaults
                WHERE id = 22
                """
            )
            assert cursor.fetchone() == (
                "Chain Name",
                11,
                300,
                "42" * 64,
                39.95,
                -75.16,
                39.96,
                -75.15,
            )
            cursor.execute(
                "SELECT status FROM public.vault_backfill_jobs WHERE vault_id = 22"
            )
            assert cursor.fetchone()[0] == "queued"
            cursor.execute(
                """
                SELECT projection_status, rider_state
                FROM public.balance_operations
                WHERE reference_id = '22'
                """
            )
            assert cursor.fetchone() == ("recorded", None)

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT vault_id
                FROM public.get_ready_vault_backfill_jobs(10)
                WHERE vault_id IN (21, 22)
                ORDER BY vault_id
                """
            )
            assert cursor.fetchall() == [(21,), (22,)]
            cursor.execute("RESET ROLE")


def test_vault_creation_handoff_reconciles_overlapping_commits(
    postgres_dsn: str,
) -> None:
    vault_id = 23
    lock_key = 2_026_071_623
    stage_source = uuid.uuid4()

    with _connection(postgres_dsn) as setup_connection:
        with setup_connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            _insert_balance_operation(cursor, vault_id)
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION public.zz_test_hold_handoff_insert()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                SET search_path = ''
                AS $$
                BEGIN
                    PERFORM pg_catalog.pg_advisory_xact_lock(2026071623);
                    RETURN NEW;
                END;
                $$;

                CREATE TRIGGER zz_test_hold_handoff_insert
                AFTER INSERT ON public.vault_creation_handoffs
                FOR EACH ROW
                EXECUTE FUNCTION public.zz_test_hold_handoff_insert();
                """
            )

    coordinator = psycopg2.connect(postgres_dsn, application_name="vault-race-coordinator")
    coordinator.autocommit = True
    indexer_connection = psycopg2.connect(
        postgres_dsn,
        application_name="vault-indexer-race",
    )
    indexer_connection.autocommit = False
    stage_result: dict[str, Any] = {}

    def stage_handoff() -> None:
        connection = psycopg2.connect(
            postgres_dsn,
            application_name="vault-stage-race",
        )
        connection.autocommit = False
        try:
            with connection.cursor() as cursor:
                stage_result["value"] = _stage(
                    cursor,
                    vault_id=vault_id,
                    pda="vault-pda-23",
                    signature_byte="23",
                    hash_byte="33",
                    v2_byte="43",
                    creator="rider-23",
                    tx_signature="tx-create-23",
                    source_climb_id=stage_source,
                )
            connection.commit()
        except BaseException as exc:
            stage_result["error"] = exc
            connection.rollback()
        finally:
            connection.close()

    stage_thread = threading.Thread(target=stage_handoff, daemon=True)
    try:
        with coordinator.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (lock_key,))

        stage_thread.start()
        deadline = time.monotonic() + 10
        while True:
            with coordinator.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_stat_activity
                        WHERE application_name = 'vault-stage-race'
                          AND wait_event_type = 'Lock'
                          AND wait_event = 'advisory'
                    )
                    """
                )
                if cursor.fetchone()[0]:
                    break
            if time.monotonic() >= deadline:
                raise AssertionError("stage transaction did not reach the advisory barrier")
            time.sleep(0.01)

        with indexer_connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            _insert_indexer_projection(
                cursor,
                vault_id=vault_id,
                signature_byte="23",
                hash_byte="33",
                pda="vault-pda-23",
                slot=400,
                completions=13,
            )

        with coordinator.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

        stage_thread.join(timeout=10)
        assert not stage_thread.is_alive()
        assert "error" not in stage_result, stage_result.get("error")
        assert stage_result["value"][1:] == (False, None)
        indexer_connection.commit()
    finally:
        if stage_thread.is_alive():
            with coordinator.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            stage_thread.join(timeout=5)
        indexer_connection.rollback()
        indexer_connection.close()
        coordinator.close()

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT jobs.status, operations.projection_status,
                       operations.rider_state, vaults.signature_v2_hex
                FROM public.vault_backfill_jobs AS jobs
                JOIN public.balance_operations AS operations
                  ON operations.reference_id = jobs.vault_id::TEXT
                JOIN public.indexed_vaults AS vaults
                  ON vaults.id = jobs.vault_id
                WHERE jobs.vault_id = %s
                """,
                (vault_id,),
            )
            assert cursor.fetchone() == (
                "waiting_projection",
                "pending",
                "Pending",
                None,
            )

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                "SELECT public.reconcile_waiting_vault_backfills(%s)",
                (10,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute("RESET ROLE")

            cursor.execute(
                """
                SELECT jobs.status, operations.projection_status,
                       operations.rider_state, vaults.signature_v2_hex,
                       vaults.total_completions, vaults.chain_slot
                FROM public.vault_backfill_jobs AS jobs
                JOIN public.balance_operations AS operations
                  ON operations.reference_id = jobs.vault_id::TEXT
                JOIN public.indexed_vaults AS vaults
                  ON vaults.id = jobs.vault_id
                WHERE jobs.vault_id = %s
                """,
                (vault_id,),
            )
            assert cursor.fetchone() == (
                "queued",
                "recorded",
                None,
                "43" * 64,
                13,
                400,
            )


def test_queue_vault_backfill_accepts_migration_first_legacy_shell(
    postgres_dsn: str,
) -> None:
    vault_id = 24

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            _insert_indexer_projection(
                cursor,
                vault_id=vault_id,
                signature_byte="24",
                hash_byte="34",
                pda="vault-pda-24",
                slot=0,
                completions=0,
            )
            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET chain_slot = NULL,
                    signature_v2_hex = repeat('44', 64),
                    signature_version = 2,
                    start_lat = 39.95,
                    start_lon = -75.16,
                    end_lat = 39.96,
                    end_lon = -75.15
                WHERE id = %s
                """,
                (vault_id,),
            )

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                "SELECT public.queue_vault_backfill(%s, repeat('24', 64), 100)",
                (vault_id,),
            )
            assert cursor.fetchone()[0] is not None
            cursor.execute("RESET ROLE")

            cursor.execute(
                """
                SELECT handoffs.creator_wallet, handoffs.signature_v2_hex,
                       jobs.status
                FROM public.vault_creation_handoffs AS handoffs
                JOIN public.vault_backfill_jobs AS jobs
                  ON jobs.vault_id = handoffs.vault_id
                WHERE handoffs.vault_id = %s
                """,
                (vault_id,),
            )
            assert cursor.fetchone() == (
                "chain-minter",
                "44" * 64,
                "waiting_projection",
            )

            cursor.execute(
                "UPDATE public.indexed_vaults SET chain_slot = 500 WHERE id = %s",
                (vault_id,),
            )
            cursor.execute(
                """
                SELECT handoffs.projected_chain_slot, jobs.status,
                       vaults.total_completions, vaults.chain_slot
                FROM public.vault_creation_handoffs AS handoffs
                JOIN public.vault_backfill_jobs AS jobs
                  ON jobs.vault_id = handoffs.vault_id
                JOIN public.indexed_vaults AS vaults
                  ON vaults.id = handoffs.vault_id
                WHERE handoffs.vault_id = %s
                """,
                (vault_id,),
            )
            assert cursor.fetchone() == (500, "queued", 0, 500)


def test_vault_handoff_projection_does_not_require_balance_operations(
    postgres_dsn: str,
) -> None:
    vault_id = 30
    source_climb_id = uuid.uuid4()

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute("DROP TABLE public.balance_operations")
            cursor.execute(COMPATIBILITY_MIGRATION.read_text(encoding="utf-8"))

            job_id, projection_ready, chain_slot = _stage(
                cursor,
                vault_id=vault_id,
                pda="vault-pda-30",
                signature_byte="30",
                hash_byte="40",
                v2_byte="50",
                creator="handoff-rider",
                tx_signature="tx-30",
                source_climb_id=source_climb_id,
            )
            assert job_id is not None
            assert projection_ready is False
            assert chain_slot is None

            _insert_indexer_projection(
                cursor,
                vault_id=vault_id,
                signature_byte="30",
                hash_byte="40",
                pda="vault-pda-30",
                slot=300,
                completions=0,
            )

            cursor.execute(
                """
                SELECT handoffs.projected_chain_slot, jobs.status,
                       vaults.backfill_status
                FROM public.vault_creation_handoffs AS handoffs
                JOIN public.vault_backfill_jobs AS jobs
                  ON jobs.vault_id = handoffs.vault_id
                JOIN public.indexed_vaults AS vaults
                  ON vaults.id = handoffs.vault_id
                WHERE handoffs.vault_id = %s
                """,
                (vault_id,),
            )
            assert cursor.fetchone() == (300, "queued", "pending")


def test_vault_handoff_projection_reconciles_installed_balance_operation_once(
    postgres_dsn: str,
) -> None:
    vault_id = 31

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(COMPATIBILITY_MIGRATION.read_text(encoding="utf-8"))
            stage_signature = (
                "public.stage_confirmed_vault_creation("
                "bigint,text,text,text,text,double precision,double precision,"
                "double precision,double precision,text,text,uuid,text,integer)"
            )
            marker_signature = (
                "public.br_mark_vault_handoff_projected(bigint,bigint)"
            )
            cursor.execute(
                """
                SELECT
                    has_function_privilege('service_role', %s, 'EXECUTE'),
                    has_function_privilege('anon', %s, 'EXECUTE'),
                    has_function_privilege('authenticated', %s, 'EXECUTE'),
                    has_function_privilege('service_role', %s, 'EXECUTE')
                """,
                (
                    stage_signature,
                    stage_signature,
                    stage_signature,
                    marker_signature,
                ),
            )
            assert cursor.fetchone() == (True, False, False, False)
            _insert_balance_operation(cursor, vault_id)

            _, projection_ready, chain_slot = _stage(
                cursor,
                vault_id=vault_id,
                pda="vault-pda-31",
                signature_byte="31",
                hash_byte="41",
                v2_byte="51",
                creator="balance-rider",
                tx_signature="tx-31",
                source_climb_id=uuid.uuid4(),
            )
            assert projection_ready is False
            assert chain_slot is None

            cursor.execute(
                """
                SELECT projection_status, rider_state
                FROM public.balance_operations
                WHERE operation_id = 'op-vault-31'
                """
            )
            assert cursor.fetchone() == ("pending", "Pending")

            _insert_indexer_projection(
                cursor,
                vault_id=vault_id,
                signature_byte="31",
                hash_byte="41",
                pda="vault-pda-31",
                slot=310,
                completions=0,
            )
            cursor.execute(
                """
                UPDATE public.balance_operations
                SET updated_at = TIMESTAMPTZ '2026-01-01 00:00:00+00'
                WHERE operation_id = 'op-vault-31';

                UPDATE public.indexed_vaults
                SET chain_slot = 311
                WHERE id = 31;
                """
            )

            cursor.execute(
                """
                SELECT COUNT(*), min(projection_status),
                       bool_and(rider_state IS NULL),
                       bool_and(
                           updated_at = TIMESTAMPTZ '2026-01-01 00:00:00+00'
                       )
                FROM public.balance_operations
                WHERE operation_id = 'op-vault-31'
                """
            )
            assert cursor.fetchone() == (1, "recorded", True, True)
