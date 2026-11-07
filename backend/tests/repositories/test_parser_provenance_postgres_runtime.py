"""PostgreSQL runtime contract for parser/economic provenance migration 124."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg2
import pytest
from psycopg2.extras import Json, register_uuid


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RECOVERY_SQL = (BACKEND_ROOT / "sql" / "114_ride_economic_recovery.sql").read_text(
    encoding="utf-8"
)
PROVENANCE_SQL = (BACKEND_ROOT / "sql" / "117_parser_provenance.sql").read_text(
    encoding="utf-8"
)
SUPERSEDED_V1_COMMIT = "e212e9e57ef93635b7ca5d21a68a5834af3ec1d0"
PARSER_V2_COMMIT = "9e6d49aa217c522222bb9922282df40ea799afeb"
POLICY = "ride_effort_policy_2026_05_06"
register_uuid()


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


@pytest.fixture
def postgres_dsn() -> Iterator[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for the PostgreSQL parser provenance contract")
    if _docker("info", check=False).returncode != 0:
        pytest.skip("Docker daemon is unavailable for the PostgreSQL parser provenance contract")

    container = f"br-parser-provenance-pgtest-{uuid.uuid4().hex[:10]}"
    _docker(
        "run", "--rm", "-d", "--name", container,
        "-e", "POSTGRES_PASSWORD=postgres", "-P", "postgres:17",
    )
    try:
        port = int(_docker(
            "inspect", "-f",
            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
            container,
        ).stdout.strip())
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


@contextmanager
def _connection(dsn: str):
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _plan(ride_id: uuid.UUID, user_id: uuid.UUID, parser_version: int) -> dict[str, str | int]:
    marker = ride_id.hex
    return {
        "ride_id": str(ride_id),
        "user_id": str(user_id),
        "wallet": f"wallet-{marker}",
        "ride_hash_hex": _hash(f"ride:{marker}"),
        "attestation_commitment_hex": _hash(f"commitment:{marker}"),
        "parser_version": parser_version,
        "policy_version": POLICY,
        "reward_policy": "rewardable",
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": "2026-07-13T13:00:00+00:00",
        "total_tss": 84,
        "total_distance_m": 12000,
        "total_vert_m": 300,
        "exact_cal_base_units": "101",
        "climbs_crossed": 0,
        "exact_tribute_base_units": "0",
        "plan_evidence_hash_hex": _hash(f"plan:{marker}"),
        "expected_attestation_pda": f"attestation-{marker}",
        "expected_cal_receipt_pda": f"cal-{marker}",
    }


def _bootstrap(cursor) -> None:
    cursor.execute(
        """
        CREATE EXTENSION pgcrypto;
        CREATE ROLE anon NOLOGIN;
        CREATE ROLE authenticated NOLOGIN;
        CREATE ROLE service_role NOLOGIN;
        CREATE TABLE public.users (id UUID PRIMARY KEY);
        CREATE TABLE public.rides (id UUID PRIMARY KEY, user_id UUID);
        CREATE TABLE public.vault_completions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), vault_signature TEXT NOT NULL,
            wallet TEXT NOT NULL, activity_id TEXT NOT NULL, time_seconds BIGINT,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(), validated BOOLEAN DEFAULT true,
            validation_override BOOLEAN DEFAULT false, validation_notes TEXT,
            cal_tribute NUMERIC NOT NULL DEFAULT 0, best_time_seconds BIGINT,
            best_time_achieved_at TIMESTAMPTZ, total_completions INTEGER DEFAULT 1,
            on_chain_tx TEXT, on_chain_tx_error TEXT, UNIQUE (vault_signature, activity_id)
        );
        CREATE OR REPLACE FUNCTION public.increment_vault_completions(TEXT)
        RETURNS VOID LANGUAGE sql AS $$ SELECT $$;
        CREATE TABLE public.pipeline_versions (
            id SERIAL PRIMARY KEY, parser_version TEXT NOT NULL,
            detector_algorithm TEXT NOT NULL, detector_version TEXT NOT NULL,
            detector_params_hash TEXT NOT NULL, sig_format_version TEXT NOT NULL,
            sig_match_version TEXT NOT NULL, economics_version TEXT NOT NULL,
            integrity_version TEXT NOT NULL, git_commit CHAR(40) NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL DEFAULT now(), deactivated_at TIMESTAMPTZ,
            notes TEXT,
            UNIQUE (parser_version, detector_algorithm, detector_version,
                    sig_format_version, sig_match_version, economics_version,
                    integrity_version)
        );
        CREATE TABLE public.economic_events (
            id BIGSERIAL PRIMARY KEY, event_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
            event_type TEXT NOT NULL, wallet TEXT NOT NULL, counterparty TEXT,
            amount NUMERIC NOT NULL, denomination TEXT NOT NULL DEFAULT 'CAL',
            balance_after NUMERIC NOT NULL, caused_by_id BIGINT, batch_id UUID,
            pipeline_version_id INTEGER REFERENCES public.pipeline_versions(id),
            reference_type TEXT, reference_id TEXT, valid_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(), reversal_of_id BIGINT,
            is_reversed BOOLEAN NOT NULL DEFAULT false, evidence JSONB,
            prev_hash CHAR(64), event_hash CHAR(64) NOT NULL
        );
        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version, detector_params_hash,
            sig_format_version, sig_match_version, economics_version, integrity_version,
            git_commit, notes
        ) VALUES (
            'wp-0.1.0', 'persistence', '1.0.0', repeat('a', 64), 'v2',
            'dct6-gps150', 'ride_effort_policy_2026_05_06', 'si-1.0',
            '1111111111111111111111111111111111111111', 'legacy active template'
        );
        """
    )
    cursor.execute(RECOVERY_SQL)


def test_migration_runtime_binds_live_freeze_plans_and_preserves_legacy_ledger(
    postgres_dsn: str,
) -> None:
    """Run canonical SQL twice and exercise the actual freeze-plan insertion path."""
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            user_id = uuid.uuid4()
            legacy_ride_id = uuid.uuid4()
            cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(_plan(legacy_ride_id, user_id, 1)), Json([])),
            )
            cursor.execute(
                """
                INSERT INTO public.economic_events (
                    event_type, wallet, amount, balance_after, valid_at, event_hash
                ) VALUES ('legacy_credit', 'legacy-wallet', 5, 5, now(), %s)
                RETURNING id
                """,
                (_hash("legacy-event"),),
            )
            legacy_event_id = cursor.fetchone()[0]

            cursor.execute(PROVENANCE_SQL)
            cursor.execute(PROVENANCE_SQL)  # exact seed lookup must make reruns idempotent

            cursor.execute(
                """
                SELECT plan.pipeline_version_id, version.ride_parser_version,
                       version.policy_version, version.git_commit
                FROM public.ride_economic_plans AS plan
                JOIN public.pipeline_versions AS version ON version.id = plan.pipeline_version_id
                WHERE plan.ride_id = %s
                """,
                (legacy_ride_id,),
            )
            legacy_pipeline_id, parser_version, policy_version, git_commit = cursor.fetchone()
            assert legacy_pipeline_id is not None
            assert parser_version == 1
            assert policy_version == POLICY
            assert git_commit == SUPERSEDED_V1_COMMIT

            cursor.execute(
                """
                SELECT count(*) FROM public.pipeline_versions
                WHERE ride_parser_version = 1 AND policy_version = %s
                  AND git_commit = %s
                """,
                (POLICY, SUPERSEDED_V1_COMMIT),
            )
            assert cursor.fetchone()[0] == 1

            v2_ride_id = uuid.uuid4()
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(_plan(v2_ride_id, user_id, 2)), Json([])),
            )
            cursor.execute(
                """
                SELECT plan.pipeline_version_id, version.ride_parser_version, version.git_commit
                FROM public.ride_economic_plans AS plan
                JOIN public.pipeline_versions AS version ON version.id = plan.pipeline_version_id
                WHERE plan.ride_id = %s
                """,
                (v2_ride_id,),
            )
            v2_pipeline_id, parser_version, git_commit = cursor.fetchone()
            assert parser_version == 2
            assert git_commit == PARSER_V2_COMMIT

            with pytest.raises(psycopg2.errors.RaiseException, match="frozen ride economic provenance"):
                cursor.execute(
                    "UPDATE public.ride_economic_plans SET parser_version = 1 WHERE ride_id = %s",
                    (v2_ride_id,),
                )
            with pytest.raises(psycopg2.errors.RaiseException, match="frozen ride economic provenance"):
                cursor.execute(
                    "UPDATE public.ride_economic_plans SET pipeline_version_id = %s WHERE ride_id = %s",
                    (legacy_pipeline_id, v2_ride_id),
                )
            with pytest.raises(psycopg2.errors.RaiseException, match="pipeline_versions are immutable"):
                cursor.execute(
                    "UPDATE public.pipeline_versions SET notes = 'mutated' WHERE id = %s",
                    (v2_pipeline_id,),
                )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    """
                    INSERT INTO public.pipeline_versions (
                        parser_version, detector_algorithm, detector_version,
                        detector_params_hash, sig_format_version, sig_match_version,
                        economics_version, integrity_version, git_commit,
                        ride_parser_version, policy_version
                    ) VALUES ('future', 'other', '1', repeat('b', 64), 'v3', 'other',
                              'other', 'si-2', repeat('2', 40), 99, 'future')
                    """
                )

            # Historical NULL provenance may reverse, but it must not be used
            # to smuggle a pipeline ID during that otherwise allowed update.
            with pytest.raises(psycopg2.errors.RaiseException, match="UPDATE on economic_events"):
                cursor.execute(
                    """
                    UPDATE public.economic_events
                    SET is_reversed = true, pipeline_version_id = %s
                    WHERE id = %s
                    """,
                    (v2_pipeline_id, legacy_event_id),
                )
            cursor.execute(
                "UPDATE public.economic_events SET is_reversed = true WHERE id = %s",
                (legacy_event_id,),
            )
            cursor.execute(
                "SELECT is_reversed, pipeline_version_id, event_hash FROM public.economic_events WHERE id = %s",
                (legacy_event_id,),
            )
            assert cursor.fetchone() == (True, None, _hash("legacy-event"))
            with pytest.raises(psycopg2.errors.RaiseException, match="require pipeline_version_id"):
                cursor.execute(
                    """
                    INSERT INTO public.economic_events (
                        event_type, wallet, amount, balance_after, valid_at, event_hash
                    ) VALUES ('new_credit', 'new-wallet', 1, 1, now(), %s)
                    """,
                    (_hash("new-event"),),
                )
            with pytest.raises(psycopg2.errors.RaiseException, match="UPDATE on economic_events"):
                cursor.execute(
                    "UPDATE public.economic_events SET event_hash = %s WHERE id = %s",
                    (_hash("mutated"), legacy_event_id),
                )

            cursor.execute(
                "UPDATE public.pipeline_versions SET deactivated_at = now() WHERE id = %s",
                (v2_pipeline_id,),
            )
            cursor.execute(
                "SELECT count(*) FROM public.pipeline_versions WHERE deactivated_at IS NULL"
            )
            assert cursor.fetchone()[0] == 0


def test_migration_rejects_an_unknown_historical_plan_pair(
    postgres_dsn: str,
) -> None:
    """Unknown history must not receive a fabricated pipeline commit."""
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            user_id = uuid.uuid4()
            ride_id = uuid.uuid4()
            cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(_plan(ride_id, user_id, 7)), Json([])),
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="provenance backfill did not resolve every frozen plan",
            ):
                cursor.execute(PROVENANCE_SQL)
