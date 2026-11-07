from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import uuid

import psycopg2
from psycopg2.extras import Json, register_uuid
import pytest

from backend.tests.services.test_completion_tribute_evidence_postgres_runtime import (
    MIGRATION as COMPLETION_EVIDENCE_MIGRATION,
    PREREQUISITES,
    _bootstrap,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


SQL_ROOT = Path(__file__).resolve().parents[2] / "sql"
PARSER_PROVENANCE_MIGRATION = SQL_ROOT / "117_parser_provenance.sql"
AUTHORITATIVE_METRICS_MIGRATION = SQL_ROOT / "122_authoritative_ride_metrics.sql"
REWARD_FTP_MIGRATION = SQL_ROOT / "123_reward_ftp_authority.sql"
PARSER_V4_MIGRATION = SQL_ROOT / "127_parser_v4_climb_authority.sql"
CANONICAL_MIGRATION = SQL_ROOT / "130_cal_tribute_policy.sql"
DEPLOY_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260716_138_cal_tribute_policy.sql"
)
SEGMENT_TSS_MIGRATION = SQL_ROOT / "157_segment_tss_cal_tribute.sql"
SEGMENT_TSS_DEPLOY_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260901172000_segment_tss_cal_tribute.sql"
)
register_uuid()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plan(
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    cal: int,
    tribute: int,
    budget: int,
    ftp_w: int = 200,
    parser_version: int = 5,
) -> dict[str, Any]:
    marker = ride_id.hex
    return {
        "ride_id": str(ride_id),
        "user_id": str(user_id),
        "wallet": f"wallet-{marker}",
        "ride_hash_hex": _hash(f"ride:{marker}"),
        "attestation_commitment_hex": _hash(f"commitment:{marker}"),
        "parser_version": parser_version,
        "policy_version": "ride_effort_policy_2026_07_14_ftp_v1",
        "reward_policy": "rewardable",
        "tribute_policy_version": "cal_tribute_segment_np_fixed_10pct_v1",
        "reward_ftp_w": ftp_w,
        "reward_ftp_source": "network_default",
        "reward_ftp_authority_id": None,
        "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": "2026-07-13T13:00:00+00:00",
        "total_tss": 84,
        "total_distance_m": 12_000,
        "total_vert_m": 300,
        "exact_cal_base_units": str(cal),
        "climbs_crossed": 2,
        "exact_tribute_budget_base_units": str(budget),
        "exact_tribute_base_units": str(tribute),
        "plan_evidence_hash_hex": _hash(f"plan:{marker}"),
        "expected_attestation_pda": f"attestation-{marker}",
        "expected_cal_receipt_pda": f"cal-{marker}",
    }


def _step(
    ride_id: uuid.UUID,
    *,
    index: int,
    vault_id: int,
    start_s: int,
    time_s: int,
    np_w: int | None,
    sample_count: int,
    coverage_bps: int,
    weight: int,
    intensity_bps: int,
    tribute: int,
) -> dict[str, Any]:
    return {
        "step_index": index,
        "pattern_id": str(uuid.uuid5(ride_id, f"pattern:{index}")),
        "vault_id": str(vault_id),
        "vault_signature": f"vault-{vault_id}",
        "completion_time_s": time_s,
        "completed_at": "2026-07-13T13:00:00+00:00",
        "exact_tribute_base_units": str(tribute),
        "intensity_bps": intensity_bps,
        "segment_start_offset_s": start_s,
        "segment_end_offset_s": start_s + time_s - 1,
        "segment_np_w": np_w,
        "segment_power_sample_count": sample_count,
        "segment_power_coverage_bps": coverage_bps,
        "segment_power_metrics_version": "workout_parse_metrics_v1",
        "tribute_weight": str(weight),
        "climb_distance_m": 600,
        "climb_vert_m": 60,
        "completion_evidence_hash_hex": _hash(
            f"completion:{ride_id.hex}:{index}:{tribute}"
        ),
        "completion_evidence_version": 2,
        "expected_receipt_pda": f"completion-{ride_id.hex}-{index}",
    }


def _insert_ride(cursor: Any, ride_id: uuid.UUID, user_id: uuid.UUID) -> None:
    cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
    cursor.execute(
        "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
        (ride_id, user_id),
    )
    cursor.execute(
        "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
        (ride_id, "2026-07-13T12:00:00+00:00"),
    )
    cursor.execute(
        "UPDATE public.rides SET economic_tss = 84 WHERE id = %s",
        (ride_id,),
    )


def _install_pipeline_bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE public.detector_configs (
            id SERIAL PRIMARY KEY,
            algorithm TEXT NOT NULL,
            version TEXT NOT NULL,
            params JSONB NOT NULL,
            params_hash CHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            notes TEXT
        );
        CREATE TABLE public.pipeline_versions (
            id SERIAL PRIMARY KEY,
            parser_version TEXT NOT NULL,
            detector_algorithm TEXT NOT NULL,
            detector_version TEXT NOT NULL,
            detector_params_hash TEXT NOT NULL,
            sig_format_version TEXT NOT NULL,
            sig_match_version TEXT NOT NULL,
            economics_version TEXT NOT NULL,
            integrity_version TEXT NOT NULL,
            git_commit CHAR(40) NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deactivated_at TIMESTAMPTZ,
            notes TEXT,
            UNIQUE (
                parser_version, detector_algorithm, detector_version,
                sig_format_version, sig_match_version, economics_version,
                integrity_version
            )
        );
        CREATE TABLE public.economic_events (
            id BIGSERIAL PRIMARY KEY,
            event_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
            event_type TEXT NOT NULL,
            wallet TEXT NOT NULL,
            counterparty TEXT,
            amount NUMERIC NOT NULL,
            denomination TEXT NOT NULL DEFAULT 'CAL',
            balance_after NUMERIC NOT NULL,
            caused_by_id BIGINT,
            batch_id UUID,
            pipeline_version_id INTEGER REFERENCES public.pipeline_versions(id),
            reference_type TEXT,
            reference_id TEXT,
            valid_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reversal_of_id BIGINT,
            is_reversed BOOLEAN NOT NULL DEFAULT false,
            evidence JSONB,
            prev_hash CHAR(64),
            event_hash CHAR(64) NOT NULL
        );
        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version,
            detector_params_hash, sig_format_version, sig_match_version,
            economics_version, integrity_version, git_commit, notes
        ) VALUES (
            'wp-0.1.0', 'persistence', '1.0.0', repeat('a', 64), 'v2',
            'dct6-gps150', 'ride_effort_policy_2026_05_06', 'si-1.0',
            '1111111111111111111111111111111111111111',
            'legacy active template'
        );
        """
    )


def _apply_production_prerequisites(cursor: Any) -> None:
    _install_pipeline_bootstrap(cursor)
    cursor.execute(PREREQUISITES[0].read_text(encoding="utf-8"))
    cursor.execute(PREREQUISITES[1].read_text(encoding="utf-8"))
    cursor.execute(PARSER_PROVENANCE_MIGRATION.read_text(encoding="utf-8"))
    cursor.execute(PREREQUISITES[2].read_text(encoding="utf-8"))
    cursor.execute(PREREQUISITES[3].read_text(encoding="utf-8"))
    cursor.execute(AUTHORITATIVE_METRICS_MIGRATION.read_text(encoding="utf-8"))
    cursor.execute(REWARD_FTP_MIGRATION.read_text(encoding="utf-8"))
    cursor.execute(PARSER_V4_MIGRATION.read_text(encoding="utf-8"))
    cursor.execute(COMPLETION_EVIDENCE_MIGRATION.read_text(encoding="utf-8"))


def _valid_payload() -> tuple[uuid.UUID, uuid.UUID, dict[str, Any], list[dict[str, Any]]]:
    ride_id = uuid.uuid4()
    user_id = uuid.uuid4()
    plan = _plan(ride_id, user_id, cal=1_000, tribute=100, budget=100)
    steps = [
        _step(
            ride_id,
            index=0,
            vault_id=41,
            start_s=0,
            time_s=60,
            np_w=100,
            sample_count=60,
            coverage_bps=10_000,
            weight=6_000,
            intensity_bps=5_000,
            tribute=25,
        ),
        _step(
            ride_id,
            index=1,
            vault_id=42,
            start_s=60,
            time_s=60,
            np_w=300,
            sample_count=60,
            coverage_bps=10_000,
            weight=18_000,
            intensity_bps=15_000,
            tribute=75,
        ),
    ]
    return ride_id, user_id, plan, steps


def test_cal_tribute_policy_migration_pair_exists_and_matches() -> None:
    assert CANONICAL_MIGRATION.exists()
    assert DEPLOY_MIGRATION.exists()
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()
    assert SEGMENT_TSS_MIGRATION.read_bytes() == SEGMENT_TSS_DEPLOY_MIGRATION.read_bytes()


def test_postgres_recomputes_measured_segment_tss_and_rejects_overlap(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_production_prerequisites(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(SEGMENT_TSS_MIGRATION.read_text(encoding="utf-8"))

            ride_id = uuid.uuid4()
            user_id = uuid.uuid4()
            _insert_ride(cursor, ride_id, user_id)
            tributes = [416_666_666, 3_750_000_000]
            plan = _plan(
                ride_id,
                user_id,
                cal=10_000_000_000,
                tribute=sum(tributes),
                budget=sum(tributes),
                ftp_w=200,
            )
            plan["tribute_policy_version"] = "cal_tribute_segment_tss_v2"
            steps = [
                _step(
                    ride_id,
                    index=index,
                    vault_id=41 + index,
                    start_s=index * 60,
                    time_s=60,
                    np_w=np_w,
                    sample_count=60,
                    coverage_bps=10_000,
                    weight=0,
                    intensity_bps=np_w * 10_000 // 200,
                    tribute=tributes[index],
                )
                for index, np_w in enumerate((100, 300))
            ]
            for step, np_w in zip(steps, (100, 300)):
                step["segment_np_milliwatts"] = np_w * 1_000
                step["segment_np_duration_s"] = 60

            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(plan), Json(steps)),
            )
            frozen = cursor.fetchone()[0]
            assert int(frozen["exact_tribute_budget_base_units"]) == sum(tributes)
            cursor.execute(
                """
                SELECT segment_np_milliwatts, segment_np_duration_s,
                       exact_tribute_base_units
                FROM public.ride_economic_completion_steps
                WHERE ride_id = %s
                ORDER BY step_index
                """,
                (ride_id,),
            )
            assert cursor.fetchall() == [
                (100_000, 60, tributes[0]),
                (300_000, 60, tributes[1]),
            ]

            overlapping_ride = uuid.uuid4()
            overlapping_user = uuid.uuid4()
            _insert_ride(cursor, overlapping_ride, overlapping_user)
            overlapping_plan = {
                **plan,
                "ride_id": str(overlapping_ride),
                "user_id": str(overlapping_user),
                "wallet": f"wallet-{overlapping_ride.hex}",
                "ride_hash_hex": _hash(f"ride:{overlapping_ride.hex}"),
                "attestation_commitment_hex": _hash(
                    f"commitment:{overlapping_ride.hex}"
                ),
                "plan_evidence_hash_hex": _hash(f"plan:{overlapping_ride.hex}"),
                "expected_attestation_pda": f"attestation-{overlapping_ride.hex}",
                "expected_cal_receipt_pda": f"cal-{overlapping_ride.hex}",
            }
            overlapping_steps = [dict(step) for step in steps]
            for index, step in enumerate(overlapping_steps):
                step["pattern_id"] = str(
                    uuid.uuid5(overlapping_ride, f"pattern:{index}")
                )
                step["segment_start_offset_s"] = 0 if index == 0 else 59
                step["segment_end_offset_s"] = 59 if index == 0 else 118
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="overlapping eligible climb windows require review",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                    (Json(overlapping_plan), Json(overlapping_steps)),
                )


def test_postgres_preserves_historical_fixed_policy_replay_after_cutover(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_production_prerequisites(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            ride_id, user_id, plan, steps = _valid_payload()
            _insert_ride(cursor, ride_id, user_id)
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(plan), Json(steps)),
            )
            original = cursor.fetchone()[0]
            cursor.execute(SEGMENT_TSS_MIGRATION.read_text(encoding="utf-8"))

            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(plan), Json(steps)),
            )
            replay = cursor.fetchone()[0]
            assert replay["plan_evidence_hash_hex"] == original["plan_evidence_hash_hex"]


def test_postgres_enforces_fixed_budget_np_weighting_and_legacy_cutover(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            _apply_production_prerequisites(cursor)

            legacy_ride = uuid.uuid4()
            legacy_user = uuid.uuid4()
            _insert_ride(cursor, legacy_ride, legacy_user)
            legacy_plan = _plan(
                legacy_ride,
                legacy_user,
                cal=101,
                tribute=11,
                budget=10,
                parser_version=4,
            )
            legacy_plan.pop("tribute_policy_version")
            legacy_plan.pop("exact_tribute_budget_base_units")
            legacy_step = _step(
                legacy_ride,
                index=0,
                vault_id=9,
                start_s=0,
                time_s=60,
                np_w=None,
                sample_count=0,
                coverage_bps=0,
                weight=0,
                intensity_bps=0,
                tribute=11,
            )
            for field in (
                "segment_start_offset_s",
                "segment_end_offset_s",
                "segment_np_w",
                "segment_power_sample_count",
                "segment_power_coverage_bps",
                "segment_power_metrics_version",
                "tribute_weight",
            ):
                legacy_step.pop(field)
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(legacy_plan), Json([legacy_step])),
            )

            completed_legacy_ride = uuid.uuid4()
            completed_legacy_user = uuid.uuid4()
            _insert_ride(cursor, completed_legacy_ride, completed_legacy_user)
            completed_legacy_plan = _plan(
                completed_legacy_ride,
                completed_legacy_user,
                cal=100,
                tribute=0,
                budget=10,
                parser_version=4,
            )
            completed_legacy_plan.pop("tribute_policy_version")
            completed_legacy_plan.pop("exact_tribute_budget_base_units")
            completed_legacy_plan["climbs_crossed"] = 0
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, '[]'::jsonb)",
                (Json(completed_legacy_plan),),
            )
            cursor.execute(
                """
                UPDATE public.ride_economic_plans
                SET state = 'complete',
                    attestation_actual_tx_signature = 'legacy-attestation-tx',
                    attestation_confirmed_at = now(),
                    cal_actual_tx_signature = 'legacy-cal-tx',
                    cal_confirmed_at = now()
                WHERE ride_id = %s
                """,
                (completed_legacy_ride,),
            )

            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT parser_version, ride_parser_version, btrim(git_commit),
                       deactivated_at IS NULL
                FROM public.pipeline_versions
                WHERE ride_parser_version IN (4, 5)
                ORDER BY ride_parser_version
                """
            )
            assert cursor.fetchall() == [
                (
                    "4-ftp-v1",
                    4,
                    "bb7604ddc0af3f983d0a21191bf27bddfa463e80",
                    False,
                ),
                (
                    "5-ftp-v1",
                    5,
                    "73bfee87359b0573014c16674e36ae6639a0276f",
                    True,
                ),
            ]

            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """
                SELECT count(*) FILTER (WHERE ride_parser_version = 5),
                       count(*) FILTER (WHERE deactivated_at IS NULL),
                       max(ride_parser_version) FILTER (
                           WHERE deactivated_at IS NULL
                       )
                FROM public.pipeline_versions
                """
            )
            assert cursor.fetchone() == (1, 1, 5)

            cursor.execute(
                "SELECT state, review_reason FROM public.ride_economic_plans WHERE ride_id = %s",
                (legacy_ride,),
            )
            assert cursor.fetchone() == (
                "review",
                "legacy_cal_tribute_policy_cutover",
            )
            cursor.execute(
                """
                SELECT state, tribute_policy_version,
                       exact_tribute_budget_base_units
                FROM public.ride_economic_plans WHERE ride_id = %s
                """,
                (completed_legacy_ride,),
            )
            assert cursor.fetchone() == ("complete", None, None)

            ride_id, user_id, plan, steps = _valid_payload()
            _insert_ride(cursor, ride_id, user_id)
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(plan), Json(steps)),
            )
            cursor.execute(
                """
                SELECT tribute_policy_version, exact_tribute_budget_base_units,
                       exact_tribute_base_units
                FROM public.ride_economic_plans WHERE ride_id = %s
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == (
                "cal_tribute_segment_np_fixed_10pct_v1",
                100,
                100,
            )
            cursor.execute(
                """
                SELECT vault_id, segment_np_w, tribute_weight,
                       exact_tribute_base_units
                FROM public.ride_economic_completion_steps
                WHERE ride_id = %s ORDER BY step_index
                """,
                (ride_id,),
            )
            assert cursor.fetchall() == [(41, 100, 6_000, 25), (42, 300, 18_000, 75)]
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="frozen CAL tribute policy cannot be changed",
            ):
                cursor.execute(
                    """
                    UPDATE public.ride_economic_plans
                    SET exact_tribute_budget_base_units = 99
                    WHERE ride_id = %s
                    """,
                    (ride_id,),
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="frozen CAL tribute step evidence cannot be changed",
            ):
                cursor.execute(
                    """
                    UPDATE public.ride_economic_completion_steps
                    SET segment_np_w = 101 WHERE ride_id = %s AND step_index = 0
                    """,
                    (ride_id,),
                )

            bad_ride, bad_user, bad_plan, bad_steps = _valid_payload()
            _insert_ride(cursor, bad_ride, bad_user)
            bad_steps[1]["exact_tribute_base_units"] = "74"
            bad_plan["exact_tribute_base_units"] = "99"
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="deterministic fixed-budget allocation",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                    (Json(bad_plan), Json(bad_steps)),
                )

            ftp_ride, ftp_user, ftp_plan, ftp_steps = _valid_payload()
            _insert_ride(cursor, ftp_ride, ftp_user)
            ftp_plan["reward_ftp_w"] = 250
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="immutable reward FTP",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                    (Json(ftp_plan), Json(ftp_steps)),
                )

            no_power_ride = uuid.uuid4()
            no_power_user = uuid.uuid4()
            _insert_ride(cursor, no_power_ride, no_power_user)
            no_power_plan = _plan(
                no_power_ride,
                no_power_user,
                cal=1_000,
                tribute=0,
                budget=100,
            )
            no_power_plan["climbs_crossed"] = 1
            no_power_steps = [
                _step(
                    no_power_ride,
                    index=0,
                    vault_id=43,
                    start_s=0,
                    time_s=60,
                    np_w=None,
                    sample_count=0,
                    coverage_bps=0,
                    weight=0,
                    intensity_bps=0,
                    tribute=0,
                )
            ]
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(no_power_plan), Json(no_power_steps)),
            )
            cursor.execute(
                "SELECT exact_tribute_budget_base_units, exact_tribute_base_units "
                "FROM public.ride_economic_plans WHERE ride_id = %s",
                (no_power_ride,),
            )
            assert cursor.fetchone() == (100, 0)

            v4_ride, v4_user, v4_plan, v4_steps = _valid_payload()
            _insert_ride(cursor, v4_ride, v4_user)
            v4_plan["parser_version"] = 4
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="new CAL tribute plans require parser V5 authority",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                    (Json(v4_plan), Json(v4_steps)),
                )


def test_postgres_composes_with_reward_ftp_wrapper_in_production_order(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DROP SCHEMA public CASCADE;
                CREATE SCHEMA public;
                DROP ROLE IF EXISTS anon, authenticated, service_role;
                """
            )
            _bootstrap(cursor)
            _apply_production_prerequisites(cursor)
            cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))

            ride_id = uuid.uuid4()
            user_id = uuid.uuid4()
            _insert_ride(cursor, ride_id, user_id)
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (ride_id, "2026-07-13T12:00:00+00:00"),
            )
            assert cursor.fetchone()[:3] == (200, "network_default", None)
            cursor.execute(
                "UPDATE public.rides SET economic_tss = 84 WHERE id = %s",
                (ride_id,),
            )

            plan = _plan(ride_id, user_id, cal=1_000, tribute=0, budget=100)
            plan["climbs_crossed"] = 0
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, '[]'::jsonb)",
                (Json(plan),),
            )
            cursor.execute(
                """
                SELECT tribute_policy_version, exact_tribute_budget_base_units,
                       exact_tribute_base_units, reward_ftp_w,
                       reward_ftp_source, reward_ftp_policy_version
                FROM public.ride_economic_plans WHERE ride_id = %s
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == (
                "cal_tribute_segment_np_fixed_10pct_v1",
                100,
                0,
                200,
                "network_default",
                "reward_ftp_policy_2026_07_14",
            )
