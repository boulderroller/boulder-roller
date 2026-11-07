"""Local Postgres: exact, permanent, atomic effort claims."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
import hashlib
import psycopg2
import pytest
from psycopg2.extras import Json
from backend.tests.repositories.test_parser_provenance_postgres_runtime import (
    _connection,
)
from backend.tests.repositories.test_derived_threshold_authority_postgres_runtime import (
    _install as _base_install,
    _insert_ride,
)
from backend.tests.repositories.test_threshold_provisional_hold_postgres_runtime import (
    _migration_sql,
    _zero_hold_plan,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn

MIGRATION = Path(__file__).resolve().parents[2] / "sql/164_ride_effort_trim.sql"
START = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
MS = int(START.timestamp() * 1000)


def _install(cur, migrate=True, verified_user=None):
    def before(cur):
        if verified_user is not None:
            cur.execute("INSERT INTO public.users(id) VALUES(%s)", (verified_user,))
            cur.execute(
                """INSERT INTO public.reward_ftp_authorities(user_id,ftp_w,source,evidence,evidence_hash,verified_by,verified_at,effective_at)
                VALUES(%s,200,'verified_power_test','{}',sha256(convert_to('{}','UTF8')),'legacy-test','2026-01-01','2026-01-05 12:00+00')""",
                (verified_user,),
            )
        cur.execute(
            "CREATE TABLE public.detector_configs (id SERIAL PRIMARY KEY, algorithm TEXT, version TEXT, params JSONB, params_hash CHAR(64) UNIQUE, notes TEXT)"
        )
        for name in ("127_parser_v4_climb_authority.sql", "130_cal_tribute_policy.sql"):
            cur.execute((MIGRATION.parent / name).read_text())

    _base_install(cur, before)
    cur.execute(
        "ALTER TABLE public.rides ADD COLUMN started_at TIMESTAMPTZ, ADD COLUMN completed_at TIMESTAMPTZ"
    )
    cur.execute(_migration_sql())
    for name in (
        "157_segment_tss_cal_tribute.sql",
        "163_threshold_hold_freeze_uses_measured_policy.sql",
    ):
        cur.execute((MIGRATION.parent / name).read_text())
    if migrate:
        cur.execute(MIGRATION.read_text())


def _draft(cur, user, start=0, end=3600, paid=None, write_effort=True, economic_tss=0):
    cur.execute(
        "INSERT INTO public.users(id) VALUES(%s) ON CONFLICT DO NOTHING", (user,)
    )
    ride = _insert_ride(
        cur, user_id=user, received_at=START + timedelta(seconds=end), eligible=False
    )
    began = START + timedelta(seconds=start)
    cur.execute(
        "UPDATE public.rides SET started_at=%s, completed_at=%s WHERE id=%s",
        (began, START + timedelta(seconds=end), ride),
    )
    cur.execute("SELECT * FROM public.bind_ride_reward_ftp(%s,%s)", (ride, began))
    snapshot = cur.fetchone()
    cur.execute(
        "UPDATE public.rides SET economic_tss=%s WHERE id=%s", (economic_tss, ride)
    )
    plan = _zero_hold_plan(
        cur,
        ride_id=ride,
        user_id=user,
        started_at=began,
        completed_at=START + timedelta(seconds=end),
    )
    effort = [[MS + int(start * 1000), MS + int(end * 1000)]]
    paid = (
        effort
        if paid is None
        else [[MS + int(a * 1000), MS + int(b * 1000)] for a, b in paid]
    )
    covered = []
    if write_effort:
        cur.execute(
            "SELECT public.ride_effort_spans_to_ms(coalesce(range_agg(paid_spans),'{}') * public.ride_effort_spans_from_ms(%s)) FROM public.ride_economic_plans WHERE user_id=%s",
            (Json(effort), user),
        )
        covered = cur.fetchone()[0]
    plan.update(
        tribute_policy_version="cal_tribute_segment_tss_v2",
        exact_tribute_budget_base_units="0",
        reward_policy="threshold_provisional_hold_v1" if paid else "not_counted",
        effort_trim={
            "version": "ride_effort_trim_v1",
            "effort_spans_ms": effort,
            "paid_spans_ms": paid,
            "covered_spans_ms": covered,
            "paid_metrics": None,
        },
    )
    if snapshot[1] != "network_default":
        plan.update(
            reward_ftp_w=snapshot[0],
            reward_ftp_source=snapshot[1],
            reward_ftp_authority_id=str(snapshot[2]),
            reward_ftp_policy_version=snapshot[3],
        )
    if write_effort:
        cur.execute(
            "UPDATE public.rides SET effort_spans_ms=%s WHERE id=%s",
            (Json(effort), ride),
        )
    return plan


def _freeze(cur, plan):
    cur.execute(
        "SELECT public.freeze_ride_economic_plan(%s,%s)", (Json(plan), Json([]))
    )
    return cur.fetchone()[0]


def test_chain_and_slice(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        for i in range(5):
            start = i * 480
            end = start + 600
            plan = _draft(cur, user, start, end, [(0 if i == 0 else start + 120, end)])
            _freeze(cur, plan)
        cur.execute(
            "SELECT public.ride_effort_spans_to_ms(range_agg(paid_spans)),sum((SELECT sum(extract(epoch FROM upper(r)-lower(r))) FROM unnest(paid_spans) r)) FROM public.ride_economic_plans"
        )
        spans, seconds = cur.fetchone()
        assert spans == [[MS, MS + 2520000]]
        assert seconds == 2520
        plan = _draft(cur, user, 600, 900, [])
        _freeze(cur, plan)
        assert _freeze(cur, plan)["ride_id"] == plan["ride_id"]
        stale = _draft(cur, user, 600, 900)
        with pytest.raises(psycopg2.Error) as error:
            _freeze(cur, stale)
        assert error.value.pgcode == "BRR08"


def test_mirror_identical():
    assert (
        MIGRATION.read_bytes()
        == (
            MIGRATION.parents[1]
            / "supabase/migrations/20260925160000_ride_effort_trim.sql"
        ).read_bytes()
    )


@pytest.mark.parametrize(
    "paid,code",
    [
        ([(3600, 7200)], None),
        ([(3590, 7200)], "BRR08"),
        ([(3602, 7200)], "P0001"),
        ([(3600.5, 7200)], None),
    ],
)
def test_handover_exact_and_maximal(postgres_dsn, paid, code):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _freeze(cur, _draft(cur, user))
        plan = _draft(cur, user, 3590, 7200, paid)
        if code:
            with pytest.raises(psycopg2.Error) as error:
                _freeze(cur, plan)
            assert error.value.pgcode == code
        else:
            _freeze(cur, plan)


def test_out_of_order_and_full_file_after_pieces(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _freeze(cur, _draft(cur, user, 0, 3600))
        _freeze(cur, _draft(cur, user, 7200, 10800))
        _freeze(cur, _draft(cur, user, 3500, 7300, [(3600, 7200)]))
        _freeze(cur, _draft(cur, user, 0, 10800, []))
        cur.execute(
            "SELECT public.ride_effort_spans_to_ms(range_agg(paid_spans)) FROM public.ride_economic_plans"
        )
        assert cur.fetchone()[0] == [[MS, MS + 10800000]]


@pytest.mark.parametrize(
    "spans",
    [
        [[1000, 2000], [0, 1000]],
        [[0, 1000], [1000, 2000]],
        [[0, 0]],
        [[0, 2000], [1000, 3000]],
        [[0.5, 1000]],
        [[True, 1000]],
    ],
)
def test_noncanonical_ms_rejected(postgres_dsn, spans):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        plan = _draft(cur, uuid.uuid4())
        plan["effort_trim"]["paid_spans_ms"] = spans
        with pytest.raises(psycopg2.Error):
            _freeze(cur, plan)


@pytest.mark.parametrize(
    "isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"]
)
def test_concurrent_admission_recomputes_loser(postgres_dsn, isolation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        plans = [_draft(cur, user), _draft(cur, user)]
    barrier = Barrier(2)

    def admit(plan):
        with psycopg2.connect(postgres_dsn) as conn, conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
            cur.execute("SELECT count(*) FROM public.ride_economic_plans")
            barrier.wait(timeout=10)
            try:
                _freeze(cur, plan)
                conn.commit()
                return "admitted"
            except psycopg2.Error as error:
                assert error.pgcode in ("BRR08", "40001")
                conn.rollback()
                with pytest.raises(psycopg2.Error) as fresh:
                    _freeze(cur, plan)
                assert fresh.value.pgcode == "BRR08"
                conn.rollback()
                plan["effort_trim"]["paid_spans_ms"] = []
                plan["effort_trim"]["covered_spans_ms"] = plan["effort_trim"][
                    "effort_spans_ms"
                ]
                plan["reward_policy"] = "not_counted"
                _freeze(cur, plan)
                conn.commit()
                return "recomputed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(admit, plans)) == ["admitted", "recomputed"]
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*),count(*) FILTER(WHERE paid_spans='{}'::tstzmultirange) FROM public.ride_economic_plans"
        )
        assert cur.fetchone() == (2, 1)


def test_presence_immutability_replay_basis_and_privacy(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        plan = _draft(cur, user)
        _freeze(cur, plan)
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s)", (user, plan["ride_id"])
        )
        basis = cur.fetchone()[0]
        assert basis["frozen"]["paid_spans_ms"] == plan["effort_trim"]["paid_spans_ms"]
        other = _draft(cur, user, 3600, 7200)
        _freeze(cur, other)
        assert _freeze(cur, plan)["state"] == "planned"
        for column in ("effort_spans", "paid_spans", "covered_spans"):
            with pytest.raises(psycopg2.Error, match="cannot change"):
                cur.execute(
                    f"UPDATE public.ride_economic_plans SET {column}=NULL WHERE ride_id=%s",
                    (plan["ride_id"],),
                )
        with pytest.raises(psycopg2.Error, match="cannot change"):
            cur.execute(
                "UPDATE public.rides SET effort_spans_ms='[]' WHERE id=%s",
                (plan["ride_id"],),
            )
        # A lower layer bypassing admission cannot commit NULL spans.
        bypass = _draft(cur, user, 7200, 10800)
        with pytest.raises(psycopg2.Error, match="frozen effort spans required"):
            cur.execute(
                "SELECT public.freeze_ride_economic_plan_unreviewed_without_effort_trim(%s,%s)",
                (Json(bypass), Json([])),
            )
        changed = {
            **plan,
            "plan_evidence_hash_hex": "11" * 32,
            "effort_trim": {**plan["effort_trim"], "paid_spans_ms": []},
        }
        assert _freeze(cur, changed)["state"] == "review"
        cur.execute(
            "SELECT public.ride_effort_spans_to_ms(paid_spans) FROM public.ride_economic_plans WHERE ride_id=%s",
            (plan["ride_id"],),
        )
        assert cur.fetchone()[0] == plan["effort_trim"]["paid_spans_ms"]
        cur.execute("SET ROLE service_role")
        for table in ("ride_effort_admission_locks", "ride_effort_completion_windows"):
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"DELETE FROM public.{table}")
        cur.execute("RESET ROLE")


def _hold(cur, plan, windows):
    hold = {
        "ride_id": plan["ride_id"],
        "user_id": plan["user_id"],
        "ride_started_at": plan["started_at"],
        "admission_plan_evidence_hash_hex": plan["plan_evidence_hash_hex"],
        "hold_evidence": {
            "version": 2,
            "effort_trim": plan["effort_trim"],
            "completion_steps": [
                {"vault_id": v, "segment_start_offset_s": a, "segment_end_offset_s": b}
                for v, a, b in windows
            ],
        },
    }
    cur.execute(
        "SELECT public.freeze_ride_economic_plan(%s,%s,%s)",
        (Json(plan), Json([]), Json(hold)),
    )
    return cur.fetchone()[0]


def test_hold_windows_same_pass_and_later_pass(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        first = _draft(cur, user, 0, 3600)
        _hold(cur, first, [(41, 3500, 3700)])
        second = _draft(cur, user, 3590, 7200, [(3600, 7200)])
        with pytest.raises(psycopg2.Error) as error:
            _hold(cur, second, [(41, 10, 120)])
        assert error.value.pgcode == "BRR08"
        _hold(cur, second, [(41, 121, 300)])
        third = _draft(cur, user, 7100, 10800, [(7200, 10800)])
        with pytest.raises(psycopg2.Error, match="outside paid effort"):
            _hold(cur, third, [(42, 0, 90)])
        _hold(cur, first, [(41, 3500, 3700)])
        cur.execute("SELECT count(*) FROM public.ride_effort_completion_windows")
        assert cur.fetchone()[0] == 2


def test_legacy_duplicates_backfill_once_and_keep_value(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, migrate=False, verified_user=user)
        plans = []
        for _ in range(2):
            plan = _draft(cur, user, write_effort=False, economic_tss=100)
            plan.update(
                reward_policy="rewardable",
                total_tss=100,
                exact_cal_base_units="100000000000",
            )
            _freeze(cur, plan)
            plans.append(plan)
        cur.execute(MIGRATION.read_text())
        cur.execute(MIGRATION.read_text())
        cur.execute(
            "SELECT exact_cal_base_units,public.ride_effort_spans_to_ms(paid_spans) FROM public.ride_economic_plans ORDER BY created_at,ride_id"
        )
        assert cur.fetchall() == [
            (100000000000, [[MS, MS + 3600000]]),
            (100000000000, []),
        ]
        _freeze(cur, _draft(cur, user, 600, 900, []))
        with pytest.raises(psycopg2.Error) as error:
            _freeze(cur, _draft(cur, user, 600, 900))
        assert error.value.pgcode == "BRR08"


def test_snapshot_attests_paid_tss_and_rejects_wrong_totals(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, verified_user=user)
        first = _draft(cur, user, economic_tss=100)
        first.update(
            reward_policy="rewardable",
            total_tss=99,
            exact_cal_base_units="100000000000",
        )
        with pytest.raises(psycopg2.Error, match="economic TSS differs"):
            _freeze(cur, first)
        first["total_tss"] = 100
        _freeze(cur, first)
        trim = _draft(cur, user, 1800, 5400, [(3600, 5400)], economic_tss=100)
        trim.update(
            reward_policy="rewardable", total_tss=50, exact_cal_base_units="50000000000"
        )
        _freeze(cur, trim)
        wrong = _draft(cur, user, 5300, 7200, [(5400, 7200)], economic_tss=100)
        wrong.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="50000000000",
        )
        with pytest.raises(psycopg2.Error, match="economic TSS differs"):
            _freeze(cur, wrong)
        covered = _draft(cur, user, 100, 900, [], economic_tss=100)
        _freeze(cur, covered)


def test_missing_legacy_ride_aborts_backfill(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur, migrate=False)
        user = uuid.uuid4()
        plan = _draft(cur, user, write_effort=False)
        _freeze(cur, plan)
        cur.execute("DELETE FROM public.rides WHERE id=%s", (plan["ride_id"],))
        with pytest.raises(psycopg2.Error, match="legacy effort backfill missing ride"):
            cur.execute(MIGRATION.read_text())
        cur.execute("ROLLBACK")


def _ordinary_step(plan, vault, start, end):
    return {
        "step_index": 0,
        "pattern_id": str(uuid.uuid4()),
        "vault_id": vault,
        "vault_signature": f"{vault:064x}",
        "completion_time_s": end - start + 1,
        "completed_at": plan["completed_at"],
        "exact_tribute_base_units": "0",
        "intensity_bps": 0,
        "completion_evidence_hash_hex": hashlib.sha256(
            (plan["ride_id"] + str(vault)).encode()
        ).hexdigest(),
        "completion_evidence_version": 2,
        "expected_receipt_pda": f'receipt-{plan["ride_id"]}-{vault}',
        "segment_start_offset_s": start,
        "segment_end_offset_s": end,
        "segment_np_w": None,
        "segment_np_milliwatts": None,
        "segment_np_duration_s": 0,
        "segment_power_sample_count": 0,
        "segment_power_coverage_bps": 0,
        "segment_power_metrics_version": "workout_parse_metrics_v1",
        "tribute_weight": 0,
        "climb_distance_m": 100,
        "climb_vert_m": 10,
    }


def test_ordinary_completion_conflicts_are_retryable_and_outside_paid_rejected(
    postgres_dsn,
):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, verified_user=user)
        first = _draft(cur, user, economic_tss=100)
        first.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="100000000000",
            climbs_crossed=1,
        )
        # Partial pass crossing the device boundary claims the physical pass once.
        step = _ordinary_step(first, 41, 3500, 3700)
        cur.execute(
            "SELECT public.freeze_ride_economic_plan(%s,%s)",
            (Json(first), Json([step])),
        )
        second = _draft(cur, user, 3590, 7200, [(3600, 7200)], economic_tss=100)
        second.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="100000000000",
            climbs_crossed=1,
        )
        with pytest.raises(psycopg2.Error) as error:
            cur.execute(
                "SELECT public.freeze_ride_economic_plan(%s,%s)",
                (Json(second), Json([_ordinary_step(second, 41, 10, 120)])),
            )
        assert error.value.pgcode == "BRR08"
        with pytest.raises(psycopg2.Error, match="outside paid effort"):
            cur.execute(
                "SELECT public.freeze_ride_economic_plan(%s,%s)",
                (Json(second), Json([_ordinary_step(second, 42, 0, 9)])),
            )
        cur.execute(
            "SELECT public.freeze_ride_economic_plan(%s,%s)",
            (Json(second), Json([_ordinary_step(second, 41, 121, 300)])),
        )
        cur.execute("SELECT count(*) FROM public.ride_effort_completion_windows")
        assert cur.fetchone()[0] == 2


def test_fully_covered_network_default_with_positive_whole_tss_freezes_zero(
    postgres_dsn,
):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _freeze(cur, _draft(cur, user, economic_tss=100))
        covered = _draft(cur, user, paid=[], economic_tss=100)
        frozen = _freeze(cur, covered)
        assert frozen["reward_policy"] == "not_counted"
        assert int(frozen["total_tss"]) == int(frozen["exact_cal_base_units"]) == 0


def test_pre_155_network_default_backfill_preserves_frozen_economics(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur, migrate=False)
        plan = _draft(cur, uuid.uuid4(), write_effort=False, economic_tss=100)
        plan.update(reward_policy="not_counted", total_tss=100)
        # Reproduce the snapshot that was legal before 155 tightened admission.
        cur.execute(
            "ALTER TABLE public.ride_economic_plans DISABLE TRIGGER trg_ride_economic_plan_reward_ftp"
        )
        _freeze(cur, plan)
        cur.execute(
            "ALTER TABLE public.ride_economic_plans ENABLE TRIGGER trg_ride_economic_plan_reward_ftp"
        )
        cur.execute(MIGRATION.read_text())
        cur.execute(MIGRATION.read_text())
        cur.execute(
            "SELECT total_tss, exact_cal_base_units, public.ride_effort_spans_to_ms(paid_spans) FROM public.ride_economic_plans"
        )
        # A zero-value plan claims no seconds, as at a live freeze.
        assert cur.fetchone() == (100, 0, [])
        cur.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname='trg_ride_economic_plan_reward_ftp'"
        )
        assert cur.fetchone()[0] == "O"
        later = _draft(cur, plan["user_id"], 600, 4200)
        assert later["effort_trim"]["covered_spans_ms"] == []
        _hold(cur, later, [])
        cur.execute(
            "SELECT public.ride_effort_spans_to_ms(paid_spans) FROM public.ride_economic_plans WHERE ride_id=%s",
            (later["ride_id"],),
        )
        assert cur.fetchone()[0] == [[MS + 600000, MS + 4200000]]


def test_uncovered_not_counted_preserves_tss_and_frozen_coverage(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, verified_user=user)
        plan = _draft(cur, user, paid=[], economic_tss=100)
        plan.update(total_tss=100)
        assert _freeze(cur, plan)["total_tss"] == 100
        # Later claims must not change the original untrimmed decision on replay.
        later = _draft(cur, user, economic_tss=100)
        later.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="100000000000",
        )
        _freeze(cur, later)
        assert _freeze(cur, plan)["total_tss"] == 100
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s)", (user, plan["ride_id"])
        )
        assert cur.fetchone()[0]["frozen"]["covered_spans_ms"] == []


@pytest.mark.parametrize(
    "start,end", [(None, None), (0, None), (None, 30), (0.5, 30), (-1, 30), (False, 30)]
)
def test_hold_offsets_must_be_unsigned_integers(postgres_dsn, start, end):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        plan = _draft(cur, uuid.uuid4())
        with pytest.raises(psycopg2.Error):
            _hold(cur, plan, [(41, start, end)])
        cur.execute("SELECT count(*) FROM public.ride_effort_completion_windows")
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("upload_defaults", [False, True])
def test_basis_only_returns_completion_windows_overlapping_ride(
    postgres_dsn, upload_defaults
):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _hold(cur, _draft(cur, user, 0, 3600), [(41, 0, 100)])
        _hold(cur, _draft(cur, user, 7200, 10800), [(42, 0, 100)])
        target = _draft(cur, user, 50, 150, [])
        if upload_defaults:
            # Non-phased admission has frozen effort, but still has upload-time
            # display timestamps until the ride's final projection is written.
            cur.execute(
                "UPDATE public.rides SET started_at=%s, completed_at=NULL WHERE id=%s",
                (START + timedelta(hours=5), target["ride_id"]),
            )
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s)", (user, target["ride_id"])
        )
        assert [
            w["vault_id"] for w in cur.fetchone()[0]["covered_completion_windows"]
        ] == [41]


@pytest.mark.parametrize(
    "spans", [[[MS + 0.0, MS + 3600000]], [[MS, MS + 1000], [MS + 1000, MS + 3600000]]]
)
def test_declared_coverage_requires_canonical_integer_spans(postgres_dsn, spans):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _freeze(cur, _draft(cur, user))
        plan = _draft(cur, user, paid=[])
        plan["effort_trim"]["covered_spans_ms"] = spans
        with pytest.raises(psycopg2.Error):
            _freeze(cur, plan)


def test_zero_value_untrimmed_candidate_retries_when_coverage_arrives(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, verified_user=user)
        candidate = _draft(cur, user, paid=[], economic_tss=100)
        candidate["total_tss"] = 100
        winner = _draft(cur, user, economic_tss=100)
        winner.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="100000000000",
        )
        _freeze(cur, winner)
        with pytest.raises(psycopg2.Error) as error:
            _freeze(cur, candidate)
        assert error.value.pgcode == "BRR08"
        candidate["effort_trim"]["covered_spans_ms"] = candidate["effort_trim"][
            "effort_spans_ms"
        ]
        candidate["total_tss"] = 0
        assert _freeze(cur, candidate)["total_tss"] == 0


def test_basis_keeps_conflicting_pass_inside_frozen_effort_pause(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _hold(cur, _draft(cur, user, 70, 100), [(41, 0, 29)])
        target = _draft(cur, user, 0, 180, write_effort=False)
        # A new climb [30,150) intersects paid effort on both sides of this
        # pause, and overlaps the prior pass only inside the pause.
        effort = [[MS, MS + 60000], [MS + 120000, MS + 180000]]
        cur.execute(
            "UPDATE public.rides SET effort_spans_ms=%s, started_at=%s, completed_at=NULL WHERE id=%s",
            (Json(effort), START + timedelta(hours=5), target["ride_id"]),
        )
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s)", (user, target["ride_id"])
        )
        basis = cur.fetchone()[0]
        assert basis["covered_spans_ms"] == []
        assert [w["vault_id"] for w in basis["covered_completion_windows"]] == [41]


def test_basis_includes_climb_window_beyond_last_effort_bucket(postgres_dsn):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        _hold(cur, _draft(cur, user, 70, 100), [(41, 0, 29)])
        _hold(cur, _draft(cur, user, 7200, 10800), [(42, 0, 100)])
        target = _draft(cur, user, 0, 121, write_effort=False)
        # Samples 0..59 and an isolated sample at 120 produce E=[0,60),
        # but a climb [30,121) still has 30 NP seconds and 31 source samples.
        cur.execute(
            "UPDATE public.rides SET effort_spans_ms=%s, started_at=%s, completed_at=NULL WHERE id=%s",
            (Json([[MS, MS + 60000]]), START + timedelta(hours=5), target["ride_id"]),
        )
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s,%s)",
            (user, target["ride_id"], Json([[MS + 30000, MS + 121000]])),
        )
        basis = cur.fetchone()[0]
        assert basis["covered_spans_ms"] == []
        assert [w["vault_id"] for w in basis["covered_completion_windows"]] == [41]


def test_legacy_plan_replay_compares_its_own_frozen_effort(postgres_dsn):
    import asyncio

    from app.services.ride_effort_trim import resolve_effort_trim

    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        user = uuid.uuid4()
        _install(cur, migrate=False, verified_user=user)
        plan = _draft(cur, user, write_effort=False, economic_tss=100)
        plan.update(
            reward_policy="rewardable",
            total_tss=100,
            exact_cal_base_units="100000000000",
        )
        _freeze(cur, plan)
        cur.execute(MIGRATION.read_text())
        cur.execute(MIGRATION.read_text())
        cur.execute(
            "SELECT effort_spans_ms FROM public.rides WHERE id=%s", (plan["ride_id"],)
        )
        stored = cur.fetchone()[0]
        assert stored == [[MS, MS + 3600000]]
        cur.execute(
            "SELECT tgname, tgenabled FROM pg_trigger WHERE tgname IN ('trg_rides_reward_ftp_immutable','trg_rides_threshold_evidence') ORDER BY 1"
        )
        assert [row[1] for row in cur.fetchall()] == ["O", "O"]
        cur.execute(
            "SELECT public.get_ride_effort_trim_basis(%s,%s)", (user, plan["ride_id"])
        )
        basis = cur.fetchone()[0]

    class Repository:
        async def get_effort_trim_basis(self, **kwargs):
            return basis

    async def no_native():
        raise AssertionError("a settled legacy plan is not priced again")

    trim = asyncio.run(
        resolve_effort_trim(
            repository=Repository(),
            ride_id=plan["ride_id"],
            user_id=user,
            effort_ms=stored,
            load_native_activity=no_native,
            reward_ftp_w=200,
        )
    )
    assert trim.frozen
    assert trim.paid_ms == trim.effort_ms == [(MS, MS + 3600000)]


@pytest.mark.parametrize("state", ["planned", "complete"])
def test_hold_replay_with_different_evidence_returns_stored_plan(postgres_dsn, state):
    with _connection(postgres_dsn) as conn, conn.cursor() as cur:
        _install(cur)
        user = uuid.uuid4()
        plan = _draft(cur, user, 0, 3600)
        _hold(cur, plan, [(41, 100, 200)])
        if state == "complete":
            cur.execute(
                "UPDATE public.ride_economic_plans SET state='complete', attestation_confirmed_at=now(), cal_confirmed_at=now() WHERE ride_id=%s",
                (plan["ride_id"],),
            )
        # A replay under the previous evidence domain hashes differently.
        replay = dict(plan, plan_evidence_hash_hex="ab" * 32)
        returned = _hold(cur, replay, [(41, 100, 200)])
        assert returned["plan_evidence_hash_hex"] == plan["plan_evidence_hash_hex"]
        assert returned["state"] == ("review" if state == "planned" else "complete")
        cur.execute(
            "SELECT event_type FROM public.ride_economic_plan_audits WHERE ride_id=%s",
            (plan["ride_id"],),
        )
        assert cur.fetchone()[0] == (
            "nonterminal_plan_evidence_mismatch"
            if state == "planned"
            else "completed_plan_evidence_mismatch"
        )
