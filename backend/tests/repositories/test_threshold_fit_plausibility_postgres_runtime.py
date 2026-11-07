"""Regression for a sprint-plus-easy-ride establishing a lifetime denominator."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
import psycopg2
import pytest
import uuid

from backend.tests.repositories.test_derived_threshold_authority_postgres_runtime import (
    _connection,
    _install,
    _insert_ride,
    _register_anchors,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


MIGRATION = (
    Path(__file__).resolve().parents[2] / "sql/165_threshold_fit_plausibility.sql"
)


def _current(cursor):
    _install(cursor)
    # The release tables are part of the production migration chain.
    from backend.tests.repositories.test_threshold_provisional_hold_postgres_runtime import (
        _migration_sql,
    )

    cursor.execute(
        "ALTER TABLE public.rides ADD COLUMN IF NOT EXISTS cal_earned INTEGER, ADD COLUMN IF NOT EXISTS tss NUMERIC"
    )
    cursor.execute(_migration_sql())
    cursor.execute(
        (MIGRATION.parent / "156_threshold_rider_projection.sql").read_text()
    )
    cursor.execute(
        (MIGRATION.parent / "158_segment_tss_threshold_release.sql").read_text()
    )
    cursor.execute(MIGRATION.read_text())


def _register_profile(cursor, user_id, received, anchors, source_id=None):
    ride = _insert_ride(
        cursor, user_id=user_id, received_at=received, source_id=source_id
    )
    row = _register_anchors(cursor, ride, anchors, received)
    return dict(zip([column[0] for column in cursor.description], row))


@pytest.mark.parametrize("middle", [60 + 61200 / 420, 205.7])
def test_degenerate_fit_goes_to_review_and_cannot_seal(postgres_dsn, middle):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        user_id = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
        received = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=received)
        candidate = _register_anchors(cursor, ride_id, (400, middle, 128), received)
        candidate = dict(zip([column[0] for column in cursor.description], candidate))
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_for_user_at(%s, %s)",
            (user_id, datetime(2026, 9, 28, 12, tzinfo=timezone.utc)),
        )
        sealed_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT ftp_w FROM public.reward_ftp_authorities WHERE user_id=%s",
            (user_id,),
        )
        authorities = cursor.fetchall()
        assert candidate["disposition"] == "below_bounds_review", (
            candidate["disposition"],
            sealed_count,
            authorities,
        )
        assert sealed_count == 0
        assert authorities == []


def test_honest_envelope_still_seals_234_w(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        user_id = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
        received = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=received)
        candidate = _register_anchors(cursor, ride_id, (400, 300, 270), received)
        candidate = dict(zip([column[0] for column in cursor.description], candidate))
        assert candidate["disposition"] == "pending_establishment"
        assert candidate["target_ftp_w"] == 234
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_for_user_at(%s, %s)",
            (user_id, datetime(2026, 9, 28, 12, tzinfo=timezone.utc)),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT ftp_w FROM public.reward_ftp_authorities WHERE user_id=%s",
            (user_id,),
        )
        assert cursor.fetchall() == [(234,)]
        print(
            "honest fitted CP:",
            candidate["fitted_candidate_w"],
            "sealed:",
            candidate["target_ftp_w"],
        )


def test_raise_rejects_implausible_fit_without_poisoning_economic_max(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        user = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user,))
        t = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        _register_profile(cursor, user, t, (400, 300, 270))
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_for_user_at(%s,%s)",
            (user, t + timedelta(days=4)),
        )
        assert cursor.fetchone()[0] == 1
        # CP=300 would pass the old bounds and raise the lifetime authority;
        # W'=90 kJ makes this profile implausible.
        rejected = _register_profile(
            cursor, user, t + timedelta(days=5), (800, 300 + 90000 / 420, 400)
        )
        assert rejected["disposition"] == "below_bounds_review"
        cursor.execute(
            "SELECT economic_candidate_w, sealed_ftp_w FROM public.reward_threshold_ratchets WHERE user_id=%s",
            (user,),
        )
        assert cursor.fetchone() == (Decimal("233.814103"), 234)
        good = _register_profile(cursor, user, t + timedelta(days=6), (430, 330, 300))
        assert good["disposition"] == "pending_raise"
        assert good["target_ftp_w"] == 264


def test_gated_establishment_keeps_held_release_unpaid_then_good_evidence_releases(
    postgres_dsn,
):
    from backend.tests.repositories.test_threshold_provisional_hold_postgres_runtime import (
        _insert_hold,
        _insert_complete_zero_parent_plan,
    )

    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        user = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user,))
        t = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        hold, ride = _insert_hold(cursor, user_id=user, held_at=t - timedelta(weeks=8))
        _insert_complete_zero_parent_plan(
            cursor,
            ride_id=ride,
            user_id=user,
            started_at=t - timedelta(weeks=8, hours=1),
            completed_at=t - timedelta(weeks=8),
        )
        source = uuid.uuid4()
        bad = _register_profile(cursor, user, t, (400, 60 + 61200 / 420, 128), source)
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
            (t + timedelta(days=4),),
        )
        assert cursor.fetchone()[0] == 0
        assert bad["disposition"] == "below_bounds_review"
        cursor.execute(
            "SELECT public.claim_due_reward_threshold_release_item(%s,300)",
            (uuid.uuid4(),),
        )
        assert cursor.fetchone()[0] is None
        cursor.execute("SELECT count(*) FROM public.reward_threshold_release_snapshots")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT exact_cal_base_units FROM public.ride_economic_plans WHERE ride_id=%s",
            (ride,),
        )
        assert cursor.fetchone()[0] == 0
        # Evidence is retained. A longer honest effort on the same source makes
        # its proposed lifetime envelope plausible without rewriting the review.
        good = _register_profile(
            cursor, user, t + timedelta(days=5), (400, 300, 270), source
        )
        assert good["target_ftp_w"] == 234
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
            (t + timedelta(days=11),),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT public.claim_due_reward_threshold_release_item(%s,300)",
            (uuid.uuid4(),),
        )
        claim = cursor.fetchone()[0]
        assert claim["reward_ftp_w"] == 234
        assert claim["ride_id"] == str(ride)
        cursor.execute(
            "SELECT disposition FROM public.reward_threshold_candidates WHERE id=%s",
            (bad["id"],),
        )
        assert cursor.fetchone()[0] == "below_bounds_review"


@pytest.mark.parametrize(
    "cp,work,accepted",
    [
        # Ratio floor at E180=300 W, independently below the W-prime ceiling.
        ("74.999", "40500.18", False),
        ("75", "40500", True),
        ("75.001", "40499.82", True),
        # Work-capacity ceiling, independently above the ratio floor.
        ("300", "59999.999", True),
        ("300", "60000", True),
        ("300", "60000.001", False),
        # Perfectly collinear, physiologically ordinary model remains valid.
        ("200", "18000", True),
        # Existing absolute CP bounds remain inclusive.
        ("49.999", "18000", False),
        ("50", "18000", True),
        ("500", "18000", True),
        ("500.001", "18000", False),
    ],
)
def test_plausibility_boundaries_and_ideal_model(postgres_dsn, cp, work, accepted):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        anchors = [
            Decimal(cp) + Decimal(work) / duration for duration in (180, 420, 900)
        ]
        cursor.execute(
            "SELECT public.reward_threshold_fit_is_plausible(%s,%s,%s)", anchors
        )
        assert cursor.fetchone()[0] is accepted


@pytest.mark.parametrize(
    "anchors",
    [
        (None, 200, 180),
        (300, None, 180),
        (300, 200, None),
        (0, 0, 0),
        ("NaN", 200, 180),
        (300, "Infinity", 180),
        (300, 200, "-Infinity"),
    ],
)
def test_plausibility_incomplete_or_nonfinite_fails_closed(postgres_dsn, anchors):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        cursor.execute(
            "SELECT public.reward_threshold_fit_is_plausible(%s,%s,%s)", anchors
        )
        assert cursor.fetchone()[0] is False


@pytest.mark.parametrize("seal_before_migration", [False, True])
def test_migration_refuses_legacy_bad_economic_state_atomically(
    postgres_dsn, seal_before_migration
):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _install(cursor)
        user = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user,))
        t = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        pending = _register_profile(cursor, user, t, (400, 60 + 61200 / 420, 128))
        assert pending["disposition"] == "pending_establishment"
        from backend.tests.repositories.test_threshold_provisional_hold_postgres_runtime import (
            _migration_sql,
        )

        cursor.execute(
            "ALTER TABLE public.rides ADD COLUMN cal_earned INTEGER, ADD COLUMN tss NUMERIC"
        )
        cursor.execute(_migration_sql())
        if seal_before_migration:
            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (t + timedelta(days=4),),
            )
            assert cursor.fetchone()[0] == 1
        connection.commit()
        with pytest.raises(psycopg2.Error, match="migration requires review") as error:
            cursor.execute(MIGRATION.read_text())
        assert error.value.pgcode == "BRR07"
        cursor.execute("ROLLBACK")
        cursor.execute(
            "SELECT to_regprocedure('public.reward_threshold_fit_is_plausible(numeric,numeric,numeric)')"
        )
        assert cursor.fetchone()[0] is None
        cursor.execute(
            "SELECT status FROM public.reward_threshold_pending_promotions WHERE user_id=%s",
            (user,),
        )
        assert cursor.fetchone()[0] == (
            "sealed" if seal_before_migration else "pending"
        )


def test_migration_mirror_and_private_predicates(postgres_dsn):
    mirror = (
        MIGRATION.parents[1]
        / "supabase/migrations/20260928120000_threshold_fit_plausibility.sql"
    )
    assert MIGRATION.read_bytes() == mirror.read_bytes()
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        for role in ("anon", "authenticated", "service_role"):
            cursor.execute(
                "SELECT has_function_privilege(%s,'public.reward_threshold_fit_is_plausible(numeric,numeric,numeric)','EXECUTE')",
                (role,),
            )
            assert cursor.fetchone()[0] is False


def test_release_gate_uses_the_same_fit_predicate(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        user = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user,))
        t = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        _register_profile(cursor, user, t, (400, 300, 270))
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
            (t + timedelta(days=4),),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT public.reward_threshold_authority_fit_is_plausible(id) FROM public.reward_ftp_authorities WHERE user_id=%s",
            (user,),
        )
        assert cursor.fetchone()[0] is True
        # Missing authority fails before a new snapshot can authorize any pay.
        with pytest.raises(psycopg2.Error) as error:
            cursor.execute(
                "INSERT INTO public.reward_threshold_release_snapshots (user_id,reward_ftp_authority_id) VALUES (%s,%s)",
                (user, uuid.uuid4()),
            )
        assert error.value.pgcode == "BRR07"
        cursor.execute("SELECT count(*) FROM public.reward_threshold_release_snapshots")
        assert cursor.fetchone()[0] == 0


def test_exploratory_corpus_matches_production_sql(postgres_dsn):
    import os
    import json
    import sqlite3

    corpus = os.environ.get("THRESHOLD_CALIBRATION_CORPUS")
    if not corpus:
        pytest.skip(
            "Set THRESHOLD_CALIBRATION_CORPUS to the retained private historical corpus"
        )
    import importlib.util

    script = MIGRATION.parents[2] / "tools/corpus/calibrate_threshold_fit.py"
    spec = importlib.util.spec_from_file_location("threshold_calibration", script)
    calibration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calibration)
    fit = calibration.fit
    workout_parse = calibration.workout_parse

    counts = {"power": 0, "complete": 0, "review": 0, "errors": 0, "incomplete": 0}
    with sqlite3.connect(
        "file:" + str(Path(corpus).resolve()) + "?mode=ro&immutable=1", uri=True
    ) as source:
        with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
            _current(cursor)
            for (raw,) in source.execute("SELECT streams_json FROM activity_streams"):
                streams = json.loads(raw)
                streams = (
                    {v["type"]: v["data"] for v in streams}
                    if isinstance(streams, list)
                    else {
                        k: v.get("data", v) if isinstance(v, dict) else v
                        for k, v in streams.items()
                    }
                )
                if "watts" not in streams:
                    continue
                counts["power"] += 1
                try:
                    anchors = workout_parse.compute_mean_max_power_series(
                        [int(round(t * 1000)) for t in streams["time"]],
                        [65535 if w is None else int(w) for w in streams["watts"]],
                        [180, 420, 900],
                    )
                except ValueError:
                    counts["errors"] += 1
                    continue
                expected = fit(anchors)
                if expected is None:
                    counts["incomplete"] += 1
                    continue
                cursor.execute(
                    "SELECT cp_w,work_capacity_j,public.reward_threshold_fit_is_plausible(%s,%s,%s) FROM public.derive_reward_threshold_cp(%s,%s,%s)",
                    (*anchors, *anchors),
                )
                cp, work, accepted = cursor.fetchone()
                assert abs(float(cp) - expected["cp"]) <= 0.000001
                assert abs(float(work) - expected["w"]) <= 0.000001
                counts["complete"] += 1
                counts["review"] += not accepted
    assert counts == {
        "power": 480,
        "complete": 468,
        "review": 0,
        "errors": 6,
        "incomplete": 6,
    }


def test_old_registration_body_cannot_resume_and_accept_bad_fit(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _current(cursor)
        # Model an in-flight pre-upgrade PL/pgSQL body. PostgreSQL can retain it
        # while migration locks wait/complete. New table triggers must fence it.
        old = (MIGRATION.parent / "154_derived_threshold_authority.sql").read_text()
        start = old.index(
            "CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort_at("
        )
        end = old.index(
            "CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort(", start
        )
        cursor.execute(old[start:end])
        user = uuid.uuid4()
        cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user,))
        t = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
        with pytest.raises(psycopg2.Error) as error:
            _register_profile(cursor, user, t, (400, 60 + 61200 / 420, 128))
        assert error.value.pgcode == "40001"
        cursor.execute(
            "SELECT economic_candidate_w FROM public.reward_threshold_ratchets WHERE user_id=%s",
            (user,),
        )
        assert cursor.fetchone() is None
        cursor.execute(
            "SELECT count(*) FROM public.reward_threshold_candidates WHERE user_id=%s",
            (user,),
        )
        assert cursor.fetchone()[0] == 0
