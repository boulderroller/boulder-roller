from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest

from app.services.canon_commitment import build_canon_commitment
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "141_canon_runtime_activation.sql"
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260721_149_canon_runtime_activation.sql"
)
DIGEST_PORTABILITY_MIGRATION = (
    BACKEND_ROOT / "sql" / "143_canon_runtime_digest_portability.sql"
)
DEPLOY_DIGEST_PORTABILITY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260727_151_canon_runtime_digest_portability.sql"
)
V4A_PROJECTION_ARCHIVE_MIGRATION = (
    BACKEND_ROOT / "sql" / "144_v4a_projection_archive.sql"
)
DEPLOY_V4A_PROJECTION_ARCHIVE_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260727_152_v4a_projection_archive.sql"
)
CANON_ID = UUID("22222222-2222-2222-2222-222222222222")
PROFILE_HASH = "ab" * 32
CHAIN_METRIC_MANIFEST = (
    REPO_ROOT
    / "history/canon-runtime-cutover-2026-07-21/"
    "chain-metric-projection-launch-manifest.json"
)
CANON_WRITER = REPO_ROOT / "indexer" / "src" / "writers" / "canon.ts"


def _quarantine_projection_sql() -> str:
    source = CANON_WRITER.read_text(encoding="utf-8")
    start = source.index("`WITH quarantine_write AS (") + 1
    end = source.index("`,\n    [", start)
    return source[start:end]


def _bootstrap(cursor) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
        DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

        CREATE TABLE public.canon_climbs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canon_id UUID,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            status TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            display_name TEXT NOT NULL,
            canonical_profile JSONB NOT NULL,
            provenance JSONB NOT NULL,
            supersedes_climb_id UUID REFERENCES public.canon_climbs(id),
            record_continuity_policy TEXT NOT NULL DEFAULT 'new_record_board',
            retired_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX idx_canon_climbs_candidate_fingerprint
            ON public.canon_climbs(candidate_fingerprint);
        CREATE UNIQUE INDEX idx_canon_climbs_canon_version
            ON public.canon_climbs(canon_id, version);

        CREATE TABLE public.canon_corridor_cells (
            canon_climb_id UUID NOT NULL REFERENCES public.canon_climbs(id),
            h3_resolution SMALLINT NOT NULL DEFAULT 10,
            tile_id TEXT NOT NULL,
            coverage_role TEXT NOT NULL,
            PRIMARY KEY (canon_climb_id, h3_resolution, tile_id, coverage_role)
        );

        CREATE TABLE public.indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE,
            signature_hash_hex TEXT NOT NULL UNIQUE,
            pda TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            chain_slot BIGINT,
            indexed_at TIMESTAMPTZ
        );

        CREATE TABLE public.indexed_vault_activations (
            vault_id BIGINT PRIMARY KEY,
            pda TEXT NOT NULL UNIQUE,
            is_active BOOLEAN NOT NULL DEFAULT false,
            seed_completions_written INTEGER NOT NULL DEFAULT 0,
            leaderboard_seeded BOOLEAN NOT NULL DEFAULT false,
            created_at BIGINT NOT NULL DEFAULT 0,
            activated_at BIGINT NOT NULL DEFAULT 0,
            last_seed_at BIGINT NOT NULL DEFAULT 0,
            chain_slot BIGINT,
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            bump SMALLINT,
            seed_generation BIGINT NOT NULL DEFAULT 0,
            seed_cutoff_at BIGINT NOT NULL DEFAULT 0,
            economics_start_epoch BIGINT NOT NULL DEFAULT 0,
            matched_users INTEGER NOT NULL DEFAULT 0,
            matched_completions INTEGER NOT NULL DEFAULT 0,
            evidence_hash CHAR(64)
        );
        """
    )


def _apply_current_canon_runtime(cursor) -> None:
    cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
    cursor.execute(DIGEST_PORTABILITY_MIGRATION.read_text(encoding="utf-8"))


def _insert_ratified(cursor, *, row_id, version: int = 2) -> str:
    commitment = build_canon_commitment(
        canon_id=CANON_ID,
        version=version,
        profile_hash_hex=PROFILE_HASH,
    ).hex()
    cursor.execute(
        """
        INSERT INTO public.canon_climbs (
            id, canon_id, version, status, candidate_fingerprint,
            display_name, canonical_profile, provenance
        ) VALUES (
            %s, %s, %s, 'ratified', repeat('a', 64), 'Ratified Climb',
            '[{"dist_m": 0, "elev_m": 1}, {"dist_m": 10, "elev_m": 2}]',
            jsonb_build_object(
                'canonical_profile_hash',
                jsonb_build_object(
                    'algorithm', 'blake3_canonical_profile_v1',
                    'value', %s
                )
            )
        )
        """,
        (str(row_id), str(CANON_ID), version, PROFILE_HASH),
    )
    cursor.execute(
        """
        INSERT INTO public.canon_corridor_cells (
            canon_climb_id, h3_resolution, tile_id, coverage_role
        ) VALUES (%s, 10, '8a2a1342b5a7fff', 'corridor')
        """,
        (str(row_id),),
    )
    cursor.execute(
        """
        INSERT INTO public.indexed_climbs (
            pda, canon_climb_id, canon_commitment_hex, commitment_hash_hex,
            canon_id, canon_version, canonical_profile_hash_hex,
            record_continuity_policy, name, vert_m, distance_m,
            avg_gradient_pct, registered_at, registered_by, chain_slot
        ) VALUES (
            'climb-pda', %s, %s, %s, %s, %s, %s,
            'new_record_board', 'Ratified Climb', 10, 100, 10,
            now(), 'backend-admin', 100
        )
        """,
        (
            str(row_id),
            commitment,
            hashlib.sha256(bytes.fromhex(commitment)).hexdigest(),
            str(CANON_ID),
            version,
            PROFILE_HASH,
        ),
    )
    return commitment


def test_canon_runtime_activation_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()
    assert (
        DIGEST_PORTABILITY_MIGRATION.read_bytes()
        == DEPLOY_DIGEST_PORTABILITY_MIGRATION.read_bytes()
    )
    assert (
        V4A_PROJECTION_ARCHIVE_MIGRATION.read_bytes()
        == DEPLOY_V4A_PROJECTION_ARCHIVE_MIGRATION.read_bytes()
    )


def test_canon_reservation_does_not_depend_on_public_pgcrypto_schema(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute("CREATE SCHEMA IF NOT EXISTS extensions")
            cursor.execute("ALTER EXTENSION pgcrypto SET SCHEMA extensions")
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            cursor.execute(
                """
                SELECT preparation_id, activation_status
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-pgcrypto-schema',
                    %s, %s, 'climb-pda', 7, 'vault-pda',
                    'vault-activation-pda', 'blockhash-1', 500
                )
                """,
                (str(row_id), commitment, commitment_hash),
            )
            preparation_id, activation_status = cursor.fetchone()
            assert preparation_id is not None
            assert activation_status == "reserved"


def test_digest_portability_patch_repairs_the_deployed_legacy_function(
    postgres_dsn: str,
) -> None:
    portable_fragment = """\
                pg_catalog.sha256(
                    pg_catalog.decode(v_expected_commitment, 'hex')
                )"""
    legacy_fragment = """\
                public.digest(
                    pg_catalog.decode(v_expected_commitment, 'hex'),
                    'sha256'
                )"""
    legacy_migration = CANONICAL_MIGRATION.read_text(encoding="utf-8")
    assert legacy_fragment in legacy_migration
    assert portable_fragment not in legacy_migration

    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute("CREATE SCHEMA IF NOT EXISTS extensions")
            cursor.execute("ALTER EXTENSION pgcrypto SET SCHEMA extensions")
            cursor.execute(legacy_migration)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            reservation_sql = """
                SELECT preparation_id, activation_status
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-digest-patch',
                    %s, %s, 'climb-pda', 7, 'vault-pda',
                    'vault-activation-pda', 'blockhash-1', 500
                )
            """
            connection.autocommit = False
            cursor.execute("SAVEPOINT before_legacy_reservation")
            with pytest.raises(psycopg2.errors.UndefinedFunction):
                cursor.execute(
                    reservation_sql,
                    (str(row_id), commitment, commitment_hash),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT before_legacy_reservation")

            cursor.execute(
                DIGEST_PORTABILITY_MIGRATION.read_text(encoding="utf-8")
            )
            cursor.execute(
                DIGEST_PORTABILITY_MIGRATION.read_text(encoding="utf-8")
            )
            cursor.execute(
                reservation_sql,
                (str(row_id), commitment, commitment_hash),
            )
            preparation_id, activation_status = cursor.fetchone()
            assert preparation_id is not None
            assert activation_status == "reserved"


def test_postgres_projection_matches_all_57_pinned_launch_candidates(
    postgres_dsn: str,
) -> None:
    manifest = json.loads(CHAIN_METRIC_MANIFEST.read_text())
    candidates = manifest["candidates"]
    assert len(candidates) == 57

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            for candidate in candidates:
                metrics = candidate["registry_metrics"]
                cursor.execute(
                    """
                    SELECT
                        round(%s::numeric * 10)::bigint,
                        round(%s::numeric)::bigint,
                        round(%s::numeric * 100)::bigint
                    """,
                    (
                        str(metrics["vert_m"]),
                        str(metrics["length_m"]),
                        str(metrics["avg_gradient_pct"]),
                    ),
                )
                expected = candidate["chain_metric_projection"]
                assert cursor.fetchone() == (
                    expected["vert_decimeters"],
                    expected["distance_meters"],
                    expected["avg_gradient_basis_points"],
                )


def test_migration_declares_private_rpc_and_db_freeze_contract() -> None:
    sql = CANONICAL_MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.canon_vault_activations" in sql
    assert "CREATE TABLE IF NOT EXISTS public.indexed_climbs" in sql
    assert "CREATE TABLE IF NOT EXISTS public.canon_indexer_quarantine" in sql
    assert "CREATE TABLE IF NOT EXISTS public.canon_indexer_pending" in sql
    assert "reserve_canon_vault_activation" in sql
    assert "confirm_canon_vault_activation" in sql
    assert "finalize_canon_vault_activation" in sql
    assert "SET search_path = ''" in sql
    assert "freeze_committed_canon_climb" in sql
    assert "freeze_committed_canon_corridor_cell" in sql
    assert "version BETWEEN 1 AND 65535" in sql
    assert "absence_observed_block_height" in sql
    assert "p_observed_finalized_block_height > v_row.last_valid_block_height" in sql
    assert "v_climb.canon_id = '00000000-0000-0000-0000-000000000000'::uuid" in sql
    assert "v_profile_hash = repeat('0', 64)" in sql
    assert "vert_m > 0 AND vert_m < 'Infinity'::double precision" in sql
    assert "avg_gradient_pct <= 655.35" in sql
    assert "quarantined BOOLEAN NOT NULL DEFAULT FALSE CHECK" not in sql
    assert "DROP CONSTRAINT IF EXISTS indexed_climbs_quarantined_check" in sql
    assert not any(
        "GRANT EXECUTE ON FUNCTION public.finalize_canon_vault_activation" in line
        for line in sql.splitlines()
    )


def test_quarantine_projection_is_atomic_slot_monotonic_and_recoverable(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            cursor.execute(
                """
                INSERT INTO public.indexed_vaults (
                    id, signature_hex, signature_hash_hex, pda, name,
                    chain_slot, indexed_at, climb_pda, canon_climb_id,
                    canon_commitment_hex, canon_binding_status
                ) VALUES (
                    7, repeat('c', 128), repeat('d', 64), 'vault-pda',
                    'Ratified Climb', 100, now(), 'climb-pda', %s, %s, 'active'
                )
                """,
                (str(row_id), commitment),
            )
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'vault-pda' WHERE pda = 'climb-pda'"
            )
            cursor.execute(
                "PREPARE quarantine_projection(text,text,text,integer,bigint,text) AS "
                + _quarantine_projection_sql()
            )

            def quarantine(account_type: str, slot: int, reason: str) -> None:
                pda = "climb-pda" if account_type == "Climb" else "vault-pda"
                cursor.execute(
                    "EXECUTE quarantine_projection(%s,%s,%s,%s,%s,%s)",
                    (pda, account_type, reason, 0x4B, slot, "ef" * 32),
                )
                cursor.fetchone()

            quarantine("Climb", 101, "invalid Climb at N+1")
            cursor.execute(
                "SELECT chain_slot, quarantined FROM public.indexed_climbs WHERE pda = 'climb-pda'"
            )
            assert cursor.fetchone() == (101, True)
            cursor.execute(
                "SELECT chain_slot, canon_binding_status FROM public.indexed_vaults WHERE pda = 'vault-pda'"
            )
            assert cursor.fetchone() == (101, "quarantined")

            # A later exact Climb write clears only the Climb quarantine. The
            # dependent Vault remains closed until it is revalidated itself.
            cursor.execute(
                "UPDATE public.indexed_climbs SET chain_slot = 102, quarantined = FALSE WHERE pda = 'climb-pda'"
            )
            quarantine("Climb", 101, "stale invalid Climb replay")
            cursor.execute(
                "SELECT chain_slot, quarantined FROM public.indexed_climbs WHERE pda = 'climb-pda'"
            )
            assert cursor.fetchone() == (102, False)
            cursor.execute(
                "SELECT canon_binding_status FROM public.indexed_vaults WHERE pda = 'vault-pda'"
            )
            assert cursor.fetchone() == ("quarantined",)

            # A newer Vault is still closed when its Climb becomes invalid,
            # but the Vault's own monotonic boundary never regresses.
            cursor.execute(
                "UPDATE public.indexed_vaults SET chain_slot = 200, canon_binding_status = 'active' WHERE pda = 'vault-pda'"
            )
            quarantine("Climb", 150, "invalid Climb older than its attached Vault")
            cursor.execute(
                "SELECT chain_slot, quarantined FROM public.indexed_climbs WHERE pda = 'climb-pda'"
            )
            assert cursor.fetchone() == (150, True)
            cursor.execute(
                "SELECT chain_slot, canon_binding_status FROM public.indexed_vaults WHERE pda = 'vault-pda'"
            )
            assert cursor.fetchone() == (200, "quarantined")
            cursor.execute(
                "UPDATE public.indexed_climbs SET chain_slot = 201, quarantined = FALSE WHERE pda = 'climb-pda'"
            )

            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET chain_slot = 175, canon_binding_status = 'active'
                WHERE pda = 'vault-pda' AND 175 >= chain_slot
                """
            )
            assert cursor.rowcount == 0
            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET chain_slot = 200, canon_binding_status = 'active'
                WHERE pda = 'vault-pda' AND 200 >= chain_slot
                """
            )
            assert cursor.rowcount == 1

            quarantine("Vault", 202, "invalid Vault at N+1")
            cursor.execute(
                "SELECT chain_slot, canon_binding_status FROM public.indexed_vaults WHERE pda = 'vault-pda'"
            )
            assert cursor.fetchone() == (202, "quarantined")

            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET chain_slot = 201, canon_binding_status = 'active'
                WHERE pda = 'vault-pda' AND 201 >= chain_slot
                """
            )
            assert cursor.rowcount == 0
            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET chain_slot = 203, canon_binding_status = 'active'
                WHERE pda = 'vault-pda' AND 203 >= chain_slot
                """
            )
            assert cursor.rowcount == 1
            cursor.execute(
                "SELECT chain_slot, canon_binding_status FROM public.indexed_vaults WHERE pda = 'vault-pda'"
            )
            assert cursor.fetchone() == (203, "active")

            cursor.execute("DEALLOCATE quarantine_projection")


def test_already_attached_climb_cannot_advertise_or_reserve_a_new_vault(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'attached-vault' WHERE pda = 'climb-pda'"
            )
            connection.commit()

            cursor.execute(
                "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                (str(row_id),),
            )
            runtime_row = cursor.fetchone()
            assert runtime_row is not None
            assert (str(runtime_row[0]), runtime_row[1]) == (
                str(row_id),
                "unavailable",
            )

            cursor.execute("SET ROLE service_role")
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="exact indexed V4-B Climb is unavailable",
            ):
                cursor.execute(
                    """
                    SELECT * FROM public.reserve_canon_vault_activation(
                        %s, 'wallet-1', 'dung', 'attached-retry', %s, %s,
                        'climb-pda', 8, 'new-vault-pda', 'new-activation-pda',
                        'blockhash-1', 500
                    )
                    """,
                    (str(row_id), commitment, commitment_hash),
                )
            connection.rollback()
            cursor.execute("RESET ROLE")


def test_confirmation_is_exactly_idempotent_and_only_indexer_can_finalize(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    tx_signature = "1" * 64
    prepared_message_hash = "cd" * 32

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            connection.commit()

            finalize_signature = (
                "public.finalize_canon_vault_activation(text,text,bigint,text)"
            )
            cursor.execute(
                "SELECT has_function_privilege('service_role', %s, 'EXECUTE')",
                (finalize_signature,),
            )
            assert cursor.fetchone() == (False,)

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-1', %s, %s,
                    'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                    'blockhash-1', 500
                )
                """,
                (str(row_id), commitment, commitment_hash),
            )
            preparation_id = cursor.fetchone()[0]
            cursor.execute("RESET ROLE")
            connection.commit()

            cursor.execute("SET ROLE service_role")
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="confirmation evidence is invalid",
            ):
                cursor.execute(
                    "SELECT * FROM public.confirm_canon_vault_activation(%s, 'wallet-1', '', %s)",
                    (str(preparation_id), prepared_message_hash),
                )
            connection.rollback()
            cursor.execute("RESET ROLE")

            cursor.execute("SET ROLE service_role")
            for _ in range(2):
                cursor.execute(
                    """
                    SELECT preparation_id, activation_status
                    FROM public.confirm_canon_vault_activation(
                        %s, 'wallet-1', %s, %s
                    )
                    """,
                    (
                        str(preparation_id),
                        tx_signature,
                        prepared_message_hash,
                    ),
                )
                assert cursor.fetchone() == (preparation_id, "confirmed")
            cursor.execute("RESET ROLE")
            connection.commit()

            for conflicting_signature, conflicting_hash in (
                (tx_signature, "ef" * 32),
                ("2" * 64, prepared_message_hash),
            ):
                cursor.execute("SET ROLE service_role")
                with pytest.raises(
                    psycopg2.errors.UniqueViolation,
                    match="conflicts with prior confirmation",
                ):
                    cursor.execute(
                        """
                        SELECT * FROM public.confirm_canon_vault_activation(
                            %s, 'wallet-1', %s, %s
                        )
                        """,
                        (
                            str(preparation_id),
                            conflicting_signature,
                            conflicting_hash,
                        ),
                    )
                connection.rollback()
                cursor.execute("RESET ROLE")

            cursor.execute(
                "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                (str(row_id),),
            )
            runtime_row = cursor.fetchone()
            assert runtime_row is not None
            assert (str(runtime_row[0]), runtime_row[1]) == (
                str(row_id),
                "reserved",
            )

            cursor.execute(
                """
                INSERT INTO public.indexed_vaults (
                    id, signature_hex, signature_hash_hex, pda, name, chain_slot,
                    indexed_at, climb_pda, canon_climb_id,
                    canon_commitment_hex, canon_binding_status
                ) VALUES (
                    7, %s, %s, 'vault-pda', 'Ratified Climb', 900,
                    now(), 'climb-pda', %s, %s, 'active'
                )
                """,
                (commitment, commitment_hash, str(row_id), commitment),
            )
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'vault-pda' WHERE pda = 'climb-pda'"
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_vault_activations (
                    vault_id, pda, is_active, seed_completions_written,
                    leaderboard_seeded, created_at, activated_at, last_seed_at,
                    seed_generation, seed_cutoff_at, matched_users,
                    matched_completions, evidence_hash, chain_slot
                ) VALUES (
                    7, 'vault-activation-pda', true, 0, true,
                    100, 100, 100, 2, 100, 0, 0, repeat('e', 64), 901
                )
                """
            )
            connection.commit()

            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="projection and activation state disagree",
            ):
                cursor.execute(
                    "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                    (str(row_id),),
                )
            connection.rollback()

            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="projection slot is invalid",
            ):
                cursor.execute(
                    "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', -1, repeat('e', 64))"
                )
            connection.rollback()

            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="binding is incomplete",
            ):
                cursor.execute(
                    "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 899, repeat('e', 64))"
                )
            connection.rollback()

            invalid_activation_updates = (
                "pda = 'wrong-activation-pda'",
                "is_active = false",
                "seed_generation = 1",
                "seed_completions_written = 1",
                "leaderboard_seeded = false",
                "matched_users = 1",
                "matched_completions = 1",
                "activated_at = created_at + 1",
                "evidence_hash = repeat('f', 64)",
                "evidence_hash = repeat('0', 64)",
            )
            for mutation in invalid_activation_updates:
                cursor.execute(
                    f"UPDATE public.indexed_vault_activations SET {mutation} WHERE vault_id = 7"
                )
                connection.commit()
                with pytest.raises(
                    psycopg2.errors.CheckViolation,
                    match="binding is incomplete",
                ):
                    cursor.execute(
                        "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 900, repeat('e', 64))"
                    )
                connection.rollback()
                cursor.execute(
                    """
                    UPDATE public.indexed_vault_activations
                    SET pda = 'vault-activation-pda', is_active = true,
                        seed_generation = 2, seed_completions_written = 0,
                        leaderboard_seeded = true, matched_users = 0,
                        matched_completions = 0, created_at = 100,
                        activated_at = 100, last_seed_at = 100,
                        seed_cutoff_at = 100, evidence_hash = repeat('e', 64)
                    WHERE vault_id = 7
                    """
                )
                connection.commit()

            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'wrong-vault-pda' WHERE pda = 'climb-pda'"
            )
            connection.commit()
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="binding is incomplete",
            ):
                cursor.execute(
                    "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 900, repeat('e', 64))"
                )
            connection.rollback()
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'vault-pda' WHERE pda = 'climb-pda'"
            )
            connection.commit()

            for column, invalid_value in (
                ("signature_hex", "ef" * 64),
                ("signature_hash_hex", "ef" * 32),
            ):
                cursor.execute(
                    f"UPDATE public.indexed_vaults SET {column} = %s WHERE id = 7",
                    (invalid_value,),
                )
                connection.commit()
                with pytest.raises(
                    psycopg2.errors.CheckViolation,
                    match="binding is incomplete",
                ):
                    cursor.execute(
                        "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 900, repeat('e', 64))"
                    )
                connection.rollback()
                cursor.execute(
                    """
                    UPDATE public.indexed_vaults
                    SET signature_hex = %s, signature_hash_hex = %s
                    WHERE id = 7
                    """,
                    (commitment, commitment_hash),
                )
                connection.commit()

            cursor.execute(
                """
                SELECT preparation_id, activation_status
                FROM public.finalize_canon_vault_activation(
                    'climb-pda', 'vault-pda', 900, repeat('e', 64)
                )
                """
            )
            assert cursor.fetchone() == (preparation_id, "finalized")
            connection.commit()
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'wrong-vault-pda' WHERE pda = 'climb-pda'"
            )
            connection.commit()
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="projection and activation state disagree",
            ):
                cursor.execute(
                    "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                    (str(row_id),),
                )
            connection.rollback()
            cursor.execute(
                "UPDATE public.indexed_climbs SET vault_pda = 'vault-pda' WHERE pda = 'climb-pda'"
            )
            connection.commit()
            with pytest.raises(
                psycopg2.errors.UniqueViolation,
                match="constructor evidence conflicts",
            ):
                cursor.execute(
                    "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 900, repeat('f', 64))"
                )
            connection.rollback()
            cursor.execute(
                "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                (str(row_id),),
            )
            runtime_row = cursor.fetchone()
            assert runtime_row is not None
            assert (str(runtime_row[0]), runtime_row[1]) == (
                str(row_id),
                "active",
            )

            cursor.execute(
                "UPDATE public.indexed_vaults SET chain_slot = 902 WHERE id = 7"
            )
            cursor.execute(
                "UPDATE public.indexed_vault_activations SET chain_slot = 903 WHERE vault_id = 7"
            )
            cursor.execute(
                "SELECT * FROM public.finalize_canon_vault_activation('climb-pda', 'vault-pda', 902, repeat('e', 64))"
            )
            assert cursor.fetchone() == (preparation_id, "finalized")
            cursor.execute(
                "SELECT chain_slot, constructor_evidence_verified, constructor_evidence_hash FROM public.canon_vault_activations WHERE id = %s",
                (str(preparation_id),),
            )
            assert cursor.fetchone() == (900, True, "e" * 64)
            cursor.execute(
                "SELECT * FROM public.get_canon_climb_runtime_states(ARRAY[%s]::uuid[])",
                (str(row_id),),
            )
            runtime_row = cursor.fetchone()
            assert runtime_row is not None
            assert (str(runtime_row[0]), runtime_row[1]) == (
                str(row_id),
                "active",
            )


def test_exact_row_reservation_is_private_and_freezes_canon_bytes(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    preparation_id = None
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            connection.commit()

            signature = (
                "public.reserve_canon_vault_activation(uuid,text,text,text,text,text,"
                "text,bigint,text,text,text,bigint)"
            )
            cursor.execute(
                """
                SELECT
                    has_function_privilege('service_role', %s, 'EXECUTE'),
                    has_function_privilege('anon', %s, 'EXECUTE'),
                    has_function_privilege('authenticated', %s, 'EXECUTE'),
                    has_table_privilege(
                        'service_role', 'public.canon_vault_activations', 'SELECT'
                    )
                """,
                (signature, signature, signature),
            )
            assert cursor.fetchone() == (True, False, False, False)

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id, activation_status
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-1', %s, %s,
                    'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                    'blockhash-1', 500
                )
                """,
                (str(row_id), commitment, commitment_hash),
            )
            preparation_id, activation_status = cursor.fetchone()
            assert activation_status == "reserved"
            cursor.execute("RESET ROLE")
            connection.commit()

            with pytest.raises(
                psycopg2.errors.DataException,
                match="committed canon climb is immutable",
            ):
                cursor.execute(
                    "UPDATE public.canon_climbs SET display_name = 'Mutated' WHERE id = %s",
                    (str(row_id),),
                )
            connection.rollback()

            with pytest.raises(
                psycopg2.errors.DataException,
                match="committed canon corridor is immutable",
            ):
                cursor.execute(
                    "DELETE FROM public.canon_corridor_cells WHERE canon_climb_id = %s",
                    (str(row_id),),
                )
            connection.rollback()

            assert preparation_id is not None


def test_indexed_climb_freezes_registry_and_corridor_before_vault_reservation(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    successor_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            _insert_ratified(cursor, row_id=row_id)
            connection.commit()

            with pytest.raises(
                psycopg2.errors.DataException,
                match="committed canon climb is immutable",
            ):
                cursor.execute(
                    "UPDATE public.canon_climbs SET display_name = 'Mutated' WHERE id = %s",
                    (str(row_id),),
                )
            connection.rollback()

            corridor_mutations = (
                (
                    "DELETE FROM public.canon_corridor_cells WHERE canon_climb_id = %s",
                    (str(row_id),),
                ),
                (
                    """
                    UPDATE public.canon_corridor_cells
                    SET tile_id = '8a2a1342b5a7ffe'
                    WHERE canon_climb_id = %s
                    """,
                    (str(row_id),),
                ),
                (
                    """
                    INSERT INTO public.canon_corridor_cells (
                        canon_climb_id, h3_resolution, tile_id, coverage_role
                    ) VALUES (%s, 10, '8a2a1342b5a7ffe', 'corridor')
                    """,
                    (str(row_id),),
                ),
            )
            for sql, params in corridor_mutations:
                with pytest.raises(
                    psycopg2.errors.DataException,
                    match="committed canon corridor is immutable",
                ):
                    cursor.execute(sql, params)
                connection.rollback()

            connection.autocommit = False
            cursor.execute(
                "UPDATE public.canon_climbs SET status = 'retired', retired_at = now() WHERE id = %s",
                (str(row_id),),
            )
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="explicit canon successor",
            ):
                connection.commit()
            connection.rollback()

            cursor.execute(
                "UPDATE public.canon_climbs SET status = 'retired', retired_at = now() WHERE id = %s",
                (str(row_id),),
            )
            cursor.execute(
                """
                INSERT INTO public.canon_climbs (
                    id, canon_id, version, status, candidate_fingerprint,
                    display_name, canonical_profile, provenance,
                    supersedes_climb_id, record_continuity_policy
                )
                SELECT %s, canon_id, version + 1, 'ratified', candidate_fingerprint,
                       display_name, canonical_profile, provenance,
                       id, 'new_record_board'
                FROM public.canon_climbs WHERE id = %s
                """,
                (str(successor_id), str(row_id)),
            )
            connection.commit()
            cursor.execute(
                "SELECT status FROM public.canon_climbs WHERE id = %s",
                (str(row_id),),
            )
            assert cursor.fetchone() == ("retired",)


def test_reservation_rejects_wrong_commitment_and_non_u16_registry_versions(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            wrong = commitment[:-2] + ("00" if commitment[-2:] != "00" else "01")
            connection.commit()
            cursor.execute("SET ROLE service_role")
            with pytest.raises(psycopg2.errors.CheckViolation, match="commitment"):
                cursor.execute(
                    """
                    SELECT * FROM public.reserve_canon_vault_activation(
                        %s, 'wallet-1', 'dung', 'request-1', %s, %s,
                        'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                        'blockhash-1', 500
                    )
                    """,
                    (
                        str(row_id),
                        wrong,
                        hashlib.sha256(bytes.fromhex(wrong)).hexdigest(),
                    ),
                )
            connection.rollback()
            cursor.execute("RESET ROLE")

            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    """
                    INSERT INTO public.canon_climbs (
                        id, canon_id, version, status, candidate_fingerprint,
                        display_name, canonical_profile, provenance
                    )
                    SELECT gen_random_uuid(), gen_random_uuid(), 65536, 'candidate',
                           repeat('b', 64), display_name, canonical_profile, provenance
                    FROM public.canon_climbs WHERE id = %s
                    """,
                    (str(row_id),),
                )


def test_competing_reservations_allow_exactly_one_live_winner(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
        connection.commit()

    commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []
    lock = threading.Lock()

    def reserve(index: int) -> None:
        try:
            with _connection(postgres_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET ROLE service_role")
                    barrier.wait(timeout=5)
                    cursor.execute(
                        """
                        SELECT preparation_id
                        FROM public.reserve_canon_vault_activation(
                            %s, %s, 'dung', %s, %s, %s,
                            'climb-pda', %s, %s, %s, %s, 500
                        )
                        """,
                        (
                            str(row_id),
                            f"wallet-{index}",
                            f"request-{index}",
                            commitment,
                            commitment_hash,
                            7 + index,
                            f"vault-pda-{index}",
                            f"vault-activation-pda-{index}",
                            f"blockhash-{index}",
                        ),
                    )
                    preparation_id = str(cursor.fetchone()[0])
                connection.commit()
            outcome = ("reserved", preparation_id)
        except psycopg2.Error as exc:
            outcome = ("rejected", exc.pgcode or type(exc).__name__)
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=reserve, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(outcome[0] for outcome in outcomes) == ["rejected", "reserved"]
    assert [outcome[1] for outcome in outcomes if outcome[0] == "rejected"] == ["23505"]


def test_release_requires_explicit_finalized_chain_absence(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            connection.commit()
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-1', %s, %s,
                    'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                    'blockhash-1', 500
                )
                """,
                (
                    str(row_id),
                    commitment,
                    hashlib.sha256(bytes.fromhex(commitment)).hexdigest(),
                ),
            )
            preparation_id = cursor.fetchone()[0]
            cursor.execute("RESET ROLE")
            connection.commit()

            cursor.execute("SET ROLE service_role")
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="finalized on-chain absence",
            ):
                cursor.execute(
                    "SELECT public.release_canon_vault_activation(%s, 'wallet-1', false, NULL, NULL, 'rpc unknown')",
                    (str(preparation_id),),
                )
            connection.rollback()
            cursor.execute("RESET ROLE")
            cursor.execute(
                "SELECT activation_status FROM public.canon_vault_activations WHERE id = %s",
                (str(preparation_id),),
            )
            assert cursor.fetchone()[0] == "reserved"

            cursor.execute("SET ROLE service_role")
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="prepared transaction expiry",
            ):
                cursor.execute(
                    "SELECT public.release_canon_vault_activation(%s, 'wallet-1', true, 777, 500, 'not expired')",
                    (str(preparation_id),),
                )
            connection.rollback()
            cursor.execute("RESET ROLE")
            cursor.execute(
                "SELECT activation_status FROM public.canon_vault_activations WHERE id = %s",
                (str(preparation_id),),
            )
            assert cursor.fetchone()[0] == "reserved"

            cursor.execute("SET ROLE service_role")
            cursor.execute(
                "SELECT public.release_canon_vault_activation(%s, 'wallet-1', true, 777, 501, 'finalized absence after expiry')",
                (str(preparation_id),),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute("RESET ROLE")
            cursor.execute(
                """
                SELECT activation_status, absence_observed_slot,
                       absence_observed_block_height
                FROM public.canon_vault_activations WHERE id = %s
                """,
                (str(preparation_id),),
            )
            assert cursor.fetchone() == ("released", 777, 501)
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id, activation_status
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-2', 'dung', 'request-2', %s, %s,
                    'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                    'blockhash-2', 700
                )
                """,
                (
                    str(row_id),
                    commitment,
                    hashlib.sha256(bytes.fromhex(commitment)).hexdigest(),
                ),
            )
            replacement_id, replacement_status = cursor.fetchone()
            assert replacement_id != preparation_id
            assert replacement_status == "reserved"
            cursor.execute("RESET ROLE")


def test_expired_reservation_release_ignores_a_legacy_program_vault_id_collision(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            commitment_hash = hashlib.sha256(bytes.fromhex(commitment)).hexdigest()
            cursor.execute(
                """
                CREATE TABLE public.indexed_vault_counter (
                    id INTEGER PRIMARY KEY,
                    count BIGINT NOT NULL,
                    pda TEXT NOT NULL,
                    chain_slot BIGINT NOT NULL
                );
                INSERT INTO public.indexed_vault_counter
                VALUES (
                    1, 0, '8qcexnhoo8YYfh73yLY54ng9vfpBG8YdJkA1w7E6C3dT',
                    479347928
                );

                CREATE TABLE public.settlement_clock_program_lineage (
                    predecessor_program_id TEXT NOT NULL,
                    successor_program_id TEXT NOT NULL,
                    successor_handoff_slot BIGINT NOT NULL,
                    cutover_unix BIGINT NOT NULL
                );
                INSERT INTO public.settlement_clock_program_lineage VALUES (
                    'HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst',
                    'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH',
                    479325255,
                    1784548800
                );

                CREATE TABLE public.indexed_leaderboards (
                    vault_id BIGINT, chain_slot BIGINT
                );
                CREATE TABLE public.indexed_legends (
                    vault_id BIGINT, chain_slot BIGINT
                );
                CREATE TABLE public.indexed_stakes (
                    row_id BIGINT, vault_id BIGINT, chain_slot BIGINT
                );
                CREATE TABLE public.indexed_completions (
                    row_id BIGINT, vault_id BIGINT, chain_slot BIGINT
                );
                CREATE TABLE public.indexed_events (
                    id BIGINT, vault_id BIGINT, slot BIGINT
                );
                CREATE TABLE public.indexed_epoch_distributions (
                    row_id BIGINT, vault_id BIGINT, slot BIGINT
                );
                CREATE TABLE public.indexed_staker_allocations (
                    row_id BIGINT, vault_id BIGINT, slot BIGINT
                );
                CREATE TABLE public.indexed_climb_completion_flows (
                    row_id BIGINT, vault_id BIGINT, slot BIGINT
                );
                CREATE TABLE public.vault_creation_handoffs (
                    vault_id BIGINT PRIMARY KEY, updated_at TIMESTAMPTZ
                );
                CREATE TABLE public.vault_backfill_jobs (
                    row_id BIGINT,
                    vault_id BIGINT REFERENCES public.vault_creation_handoffs(vault_id)
                        ON DELETE RESTRICT,
                    created_at TIMESTAMPTZ
                );

                INSERT INTO public.indexed_vaults (
                    id, signature_hex, signature_hash_hex, pda, name,
                    chain_slot, indexed_at
                )
                SELECT legacy_id,
                       lpad(to_hex(legacy_id), 128, '0'),
                       lpad(to_hex(legacy_id), 64, '0'),
                       'legacy-program-vault-' || legacy_id,
                       'Legacy V4-A Vault ' || legacy_id,
                       477399018,
                       '2026-07-19 14:28:10+00'
                FROM generate_series(0, 32) AS legacy(legacy_id);

                INSERT INTO public.indexed_vault_activations (
                    vault_id, pda, is_active, seed_generation,
                    matched_users, matched_completions, chain_slot
                )
                SELECT legacy_id,
                       'legacy-program-activation-' || legacy_id,
                       TRUE, 1, 1, 1, 477399019
                FROM generate_series(0, 16) AS legacy(legacy_id);

                INSERT INTO public.indexed_leaderboards
                SELECT legacy_id, 477399020
                FROM generate_series(0, 16) AS legacy(legacy_id);
                INSERT INTO public.indexed_legends
                SELECT legacy_id, 477399015
                FROM generate_series(0, 16) AS legacy(legacy_id);
                INSERT INTO public.indexed_stakes
                SELECT row_id, row_id % 17, 477399020
                FROM generate_series(1, 23) AS legacy(row_id);
                INSERT INTO public.indexed_completions
                SELECT row_id, row_id % 17, 477399019
                FROM generate_series(1, 9) AS legacy(row_id);
                INSERT INTO public.indexed_events
                SELECT row_id, row_id % 17, 477172334
                FROM generate_series(1, 195) AS legacy(row_id);
                INSERT INTO public.indexed_epoch_distributions
                SELECT row_id, row_id % 17, 477172286
                FROM generate_series(1, 12) AS legacy(row_id);
                INSERT INTO public.indexed_staker_allocations
                SELECT row_id, row_id % 17, 477172286
                FROM generate_series(1, 11) AS legacy(row_id);
                INSERT INTO public.indexed_climb_completion_flows
                VALUES (1, 16, 477169736);
                INSERT INTO public.vault_creation_handoffs
                SELECT legacy_id, '2026-07-19 14:28:10+00'
                FROM generate_series(0, 32) AS legacy(legacy_id);
                INSERT INTO public.vault_backfill_jobs
                SELECT row_id, row_id % 17, '2026-01-27 18:04:29+00'
                FROM generate_series(1, 7) AS legacy(row_id);
                """
            )
            connection.commit()
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'legacy-id-collision', %s, %s,
                    'climb-pda', 0, 'v4b-vault-pda', 'v4b-activation-pda',
                    'blockhash-1', 500
                )
                """,
                (str(row_id), commitment, commitment_hash),
            )
            preparation_id = cursor.fetchone()[0]
            connection.commit()
            connection.autocommit = False
            cursor.execute("SET ROLE service_role")
            cursor.execute("SAVEPOINT before_archive")
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="indexed Climb to Vault binding must be absent",
            ):
                cursor.execute(
                    """
                    SELECT public.release_canon_vault_activation(
                        %s, 'wallet-1', TRUE, 777, 501,
                        'finalized V4-B account absence after expiry'
                    )
                    """,
                    (str(preparation_id),),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT before_archive")
            cursor.execute("RESET ROLE")
            connection.commit()
            connection.autocommit = True
            cursor.execute(
                V4A_PROJECTION_ARCHIVE_MIGRATION.read_text(encoding="utf-8")
            )
            cursor.execute(
                V4A_PROJECTION_ARCHIVE_MIGRATION.read_text(encoding="utf-8")
            )
            cursor.execute(
                """
                SELECT archived_row_count, archive_sha256 <> repeat('0', 64)
                FROM legacy_v4a_audit.cutover_manifests
                WHERE cutover_key = 'devnet_v4a_to_v4b_20260727'
                """
            )
            assert cursor.fetchone() == (375, True)
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM public.indexed_vaults),
                    (SELECT count(*) FROM public.indexed_vault_activations),
                    (SELECT count(*) FROM legacy_v4a_audit.projection_rows)
                """
            )
            assert cursor.fetchone() == (0, 0, 375)
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT public.release_canon_vault_activation(
                    %s, 'wallet-1', TRUE, 777, 501,
                    'finalized V4-B account absence after expiry'
                )
                """,
                (str(preparation_id),),
            )
            assert cursor.fetchone() == (True,)


def test_committed_retirement_requires_exact_successor_at_commit(
    postgres_dsn: str,
) -> None:
    row_id = uuid4()
    successor_id = uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_current_canon_runtime(cursor)
            commitment = _insert_ratified(cursor, row_id=row_id)
            connection.commit()
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                """
                SELECT preparation_id
                FROM public.reserve_canon_vault_activation(
                    %s, 'wallet-1', 'dung', 'request-1', %s, %s,
                    'climb-pda', 7, 'vault-pda', 'vault-activation-pda',
                    'blockhash-1', 500
                )
                """,
                (
                    str(row_id),
                    commitment,
                    hashlib.sha256(bytes.fromhex(commitment)).hexdigest(),
                ),
            )
            preparation_id = cursor.fetchone()[0]
            cursor.execute("RESET ROLE")
            connection.commit()

            connection.autocommit = False

            cursor.execute(
                "UPDATE public.canon_climbs SET status = 'retired', retired_at = now() WHERE id = %s",
                (str(row_id),),
            )
            with pytest.raises(
                psycopg2.errors.CheckViolation,
                match="explicit canon successor",
            ):
                connection.commit()
            connection.rollback()

            cursor.execute(
                "UPDATE public.canon_climbs SET status = 'retired', retired_at = now() WHERE id = %s",
                (str(row_id),),
            )
            cursor.execute(
                """
                INSERT INTO public.canon_climbs (
                    id, canon_id, version, status, candidate_fingerprint,
                    display_name, canonical_profile, provenance,
                    supersedes_climb_id, record_continuity_policy
                )
                SELECT %s, canon_id, version + 1, 'ratified', candidate_fingerprint,
                       display_name, canonical_profile, provenance,
                       id, 'new_record_board'
                FROM public.canon_climbs WHERE id = %s
                """,
                (str(successor_id), str(row_id)),
            )
            connection.commit()
            cursor.execute(
                "SELECT status FROM public.canon_climbs WHERE id = %s",
                (str(row_id),),
            )
            assert cursor.fetchone()[0] == "retired"
            cursor.execute(
                "UPDATE public.indexed_climbs SET successor_climb_pda = 'successor-climb-pda' WHERE canon_climb_id = %s",
                (str(row_id),),
            )
            cursor.execute("SET ROLE service_role")
            cursor.execute(
                "SELECT public.release_canon_vault_activation(%s, 'wallet-1', true, 778, 501, 'expired after exact successor retirement')",
                (str(preparation_id),),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute("RESET ROLE")
            cursor.execute(
                "SELECT activation_status FROM public.canon_vault_activations WHERE id = %s",
                (str(preparation_id),),
            )
            assert cursor.fetchone() == ("released",)
