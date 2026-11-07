"""Training admission and terminal replay on disposable, real PostgreSQL."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json
from psycopg2 import sql
from postgrest.exceptions import APIError

from app.services.fitness_analytics import FitnessAnalyticsService
from app.services.riding_days import aggregate_riding_days, aggregate_training_weeks
from app.services.training_backfill import error_class
from app.services.training_metrics import project_training
from app.services.training_backfill import backfill_training, replay_training_batch
from app.repositories.ride import RideRepository
from backend.tests.services.test_training_storage_runtime import (
    SQL, EVIDENCE, db, pre_cleanup_db, postgres_dsn, isolated_postgres_dsn, row, bind,
)


@pytest.mark.parametrize("path", ["idle", "startup", "finished_attempt"])
def test_failed_ride_never_claimed(db, path):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("UPDATE rides SET processing_status='failed' WHERE id=%s", (ride,))
        if path != "idle":
            c.execute(
                "SELECT set_training_pay_attempt(%s,%s,gen_random_uuid(),false)",
                (ride, user),
            )
        if path == "finished_attempt":
            c.execute("UPDATE training_pay_attempts SET active=false")
        c.execute("SELECT claim_training_replay(10,clock_timestamp())")
        assert c.fetchone()[0] == []
        c.execute("SELECT count(*) FROM training_replay_state")
        assert c.fetchone()[0] == 0


def test_failed_metrics_do_not_affect_any_training_read(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute(
            "UPDATE rides SET processing_status='failed',training_metrics=%s,training_evidence=%s WHERE id=%s",
            (Json({"engine_version": 2, "load": 100, "local_date": "2026-10-01",
                   "distance_m": 1000, "moving_s": 100, "elevation_gain_m": 20}),
             Json(EVIDENCE), ride),
        )
        c.execute("SELECT to_jsonb(r) FROM rides r WHERE id=%s", (ride,))
        rides = [c.fetchone()[0]]
        c.execute("SELECT current_training_threshold(%s,'2026-10-02')", (user,))
        assert c.fetchone()[0] is None
    snapshot = FitnessAnalyticsService.threshold_training_snapshot(
        rides, threshold_w=0, threshold={"threshold_version": "training.v2"},
        start_date=date(2026, 10, 1), target_date=date(2026, 10, 1),
    )
    assert snapshot["training_load"]["total_tss"] == 0
    assert snapshot["coverage"]["expected_count"] == 0
    assert snapshot["fitness_metrics"]["ctl"] == 0
    assert snapshot["fitness_metrics"]["atl"] == 0
    assert snapshot["fitness_metrics"]["tsb"] == 0
    assert aggregate_riding_days(rides, start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)) == []
    assert aggregate_training_weeks(rides, end_date=date(2026, 10, 1), weeks=1)[0]["distance_m"] == 0
    assert project_training(rides[0], owner=True)["tss"] is None
    assert "training_metrics" not in project_training(rides[0], owner=True)


@pytest.mark.parametrize("failure", ["missing_original", "FileNotFoundError", "ParseError", "training_date_conflict"])
def test_permanent_failure_is_not_claimed_when_backoff_is_due(db, failure):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
        c.execute("SELECT finish_training_replay(%s,%s,%s)", (ride, user, failure))
        c.execute("UPDATE training_replay_state SET next_attempt_at=now()-interval '1 day'")
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []


def test_date_conflict_class_comes_from_database_refusal(db):
    user, ride = row(db)
    with pytest.raises(psycopg2.Error) as error:
        bind(db, user, ride, day="2026-10-02T12:00:00Z")
    database_error = error.value
    api_error = APIError({"code": database_error.pgcode, "message": database_error.diag.message_primary,
                          "details": None, "hint": None})
    assert error_class(api_error) == "training_date_conflict"
    for code, message in [("P0001", "training payment attempt active"), ("08006", "training date conflict")]:
        assert error_class(APIError({"code": code, "message": message, "details": None, "hint": None})) == "APIError"


def test_legacy_review_without_payment_completion_stays_blocked(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("UPDATE rides SET processing_status='under_review' WHERE id=%s", (ride,))
        c.execute("SELECT training_payment_idle(%s),training_has_payment_lease(%s)", (ride, ride))
        assert c.fetchone() == (False, False)
        c.execute("SELECT claim_training_replay(10,clock_timestamp())")
        assert c.fetchone()[0] == []
    with pytest.raises(psycopg2.Error, match="payment attempt active"):
        bind(db, user, ride)


def test_python_and_sql_share_exact_eligibility(db):
    from app.services.training_eligibility import COUNTED_STATUSES
    with db.cursor() as c:
        c.execute("SELECT training_counted_statuses()")
        assert set(c.fetchone()[0]) == COUNTED_STATUSES


def test_terminal_reopens_only_for_a_newer_engine(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError')", (ride, user))
        for version in (1, 2, 3):
            c.execute("SELECT claim_training_replay(10,NULL,'{}',%s)", (version,))
            assert [r["id"] for r in c.fetchone()[0]] == ([ride] if version == 3 else [])
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError',3)", (ride, user))
        c.execute("SELECT claim_training_replay(10,NULL,'{}',3)")
        assert c.fetchone()[0] == []


@pytest.mark.parametrize("change", ["raw_file_path='replacement.fit'", "started_at=started_at+interval '1 day'", "file_type='gpx'", "processing_status='failed'"])
def test_terminal_reopens_on_scoring_input_change(db, change):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError')", (ride, user))
        c.execute("UPDATE rides SET " + change + " WHERE id=%s", (ride,))
        if change.startswith("processing_status"):
            c.execute("SELECT claim_training_replay(10)")
            assert c.fetchone()[0] == []
            c.execute("UPDATE rides SET processing_status='completed' WHERE id=%s", (ride,))
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]


def test_noop_and_eligible_status_changes_do_not_reopen_terminal(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError')", (ride, user))
        c.execute("UPDATE rides SET raw_file_path=raw_file_path,started_at=started_at,processing_status='under_review',phase3_completed_at=now() WHERE id=%s", (ride,))
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []


def test_transient_failure_keeps_existing_backoff(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
        c.execute("BEGIN")
        c.execute("SELECT finish_training_replay(%s,%s,'APIError')", (ride, user))
        c.execute("SELECT next_attempt_at-now()=interval '30 minutes',terminal_engine_version FROM training_replay_state")
        assert c.fetchone() == (True, None)
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []
        c.execute("UPDATE training_replay_state SET attempts=99,next_attempt_at=now()-interval '1 day'")
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
        c.execute("SELECT finish_training_replay(%s,%s,'APIError')", (ride, user))
        c.execute("SELECT next_attempt_at-now()=interval '24 hours' FROM training_replay_state")
        assert c.fetchone()[0]
        c.execute("COMMIT")


def test_migration_marks_47_completed_failures_without_losing_data_and_reverses(pre_cleanup_db):
    db = pre_cleanup_db
    user, _ = row(db)
    with db.cursor() as c:
        for status, failure, count in [
            ("completed", "missing_original", 46), ("completed", "ParseError", 1),
            ("failed", "APIError", 108), ("failed", "missing_original", 55),
            ("failed", "ParseError", 5), ("failed", "FileNotFoundError", 4),
        ]:
            for _ in range(count):
                ride = str(uuid4())
                c.execute("INSERT INTO rides(id,user_id,processing_status) VALUES(%s,%s,%s)", (ride, user, status))
                c.execute("INSERT INTO training_replay_state VALUES(%s,4,now()+interval '1 day',%s)", (ride, failure))
        c.execute("SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM rides r")
        rides_before = c.fetchone()[0]
        c.execute("SELECT jsonb_agg(to_jsonb(s) ORDER BY ride_id) FROM training_replay_state s")
        before = c.fetchone()[0]
        migration = (SQL / "168_training_eligibility_terminal_replay.sql").read_text()
        mirror = SQL.parent / "supabase/migrations/20261013220000_training_eligibility_terminal_replay.sql"
        assert mirror.read_text() == migration
        c.execute(migration)
        c.execute("SELECT terminal_engine_version,count(*) FROM training_replay_state GROUP BY 1 ORDER BY 1")
        assert c.fetchall() == [(2, 47), (None, 172)]
        c.execute("SELECT jsonb_agg(to_jsonb(r) ORDER BY id) FROM rides r")
        assert c.fetchone()[0] == rides_before
        c.execute("SELECT jsonb_agg(to_jsonb(s)-'terminal_engine_version' ORDER BY ride_id) FROM training_replay_state s")
        assert c.fetchone()[0] == before
        c.execute("UPDATE public.training_replay_state SET terminal_engine_version=NULL WHERE terminal_engine_version=2")
        c.execute("SELECT count(*) FROM training_replay_state WHERE terminal_engine_version IS NOT NULL")
        assert c.fetchone()[0] == 0
        c.execute("SELECT jsonb_agg(to_jsonb(s)-'terminal_engine_version' ORDER BY ride_id) FROM training_replay_state s")
        assert c.fetchone()[0] == before


@pytest.mark.asyncio
async def test_backfill_skips_ineligible_and_terminal_but_explicit_force_retries(monkeypatch):
    from app.services.training_metrics import ENGINE_VERSION, TrainingMetricsService

    score = AsyncMock(return_value={"engine_version": ENGINE_VERSION})
    monkeypatch.setattr(TrainingMetricsService, "score", score)
    parse, repo = AsyncMock(), AsyncMock()
    terminal = {"id": "terminal", "user_id": "u", "processing_status": "completed",
                "started_at": "2026-10-01", "raw_file_path": "synthetic.fit",
                "training_metrics": {"engine_version": ENGINE_VERSION},
                "training_replay_state": {"terminal_engine_version": ENGINE_VERSION, "error_class": "ParseError"}}
    failed = {**terminal, "id": "failed", "processing_status": "failed"}
    dry = await backfill_training(repo, [failed, terminal], parse, force=True)
    assert dry["skipped"] == 2 and dry["failed"] == 0
    parse.assert_not_awaited()
    repo.finish_training_replay.assert_not_awaited()
    ordinary = await backfill_training(repo, [failed, terminal], parse, apply=True, force=True)
    assert ordinary["skipped"] == 2
    forced = await backfill_training(repo, [failed, terminal], parse, apply=True, force_terminal=True)
    assert forced["skipped"] == 1 and forced["scored"] == 1 and forced["failed"] == 0
    score.assert_awaited_once()
    repo.finish_training_replay.assert_awaited_once_with("terminal", "u", None, scoring_inputs=terminal)


def test_failure_from_old_file_cannot_terminalize_replacement(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(10)")
        inputs = c.fetchone()[0][0]
        c.execute("UPDATE rides SET raw_file_path='replacement.fit' WHERE id=%s", (ride,))
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError',2,%s)", (ride, user, Json(inputs)))
        c.execute("SELECT terminal_engine_version FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone()[0] is None
        # The stale result does not clear the existing claim's ten-minute lease.
        c.execute("UPDATE training_replay_state SET next_attempt_at=now() WHERE ride_id=%s", (ride,))
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0][0]["raw_file_path"] == "replacement.fit"


@pytest.mark.asyncio
async def test_repository_reads_filter_failed_metrics_in_postgres(db):
    user, completed = row(db)
    _, failed = row(db, user=user)
    with db.cursor() as c:
        c.execute("UPDATE rides SET processing_status='failed',training_metrics='{}' WHERE id=%s", (failed,))

    class Query:
        def __init__(self):
            self.predicates, self.values = [], []

        def table(self, name):
            assert name == "rides"
            return self

        def select(self, columns):
            return self

        def eq(self, name, value):
            assert name == "user_id"
            self.predicates.append("r.user_id=%s")
            self.values.append(value)
            return self

        def in_(self, name, values):
            assert name == "processing_status"
            self.predicates.append("r.processing_status=ANY(%s)")
            self.values.append(values)
            return self

        def order(self, *args, **kwargs):
            return self

        def range(self, start, end):
            self.page = [end-start+1, start]
            return self

        def execute(self):
            with db.cursor() as c:
                c.execute("SELECT to_jsonb(r) FROM rides r WHERE " + " AND ".join(self.predicates)
                          + " ORDER BY started_at,id LIMIT %s OFFSET %s", self.values+self.page)
                return SimpleNamespace(data=[r[0] for r in c.fetchall()])

    reads = await RideRepository(Query()).list_threshold_training_rides(user)
    assert [ride["id"] for ride in reads] == [completed]


class PostgresRPC:
    """Use the production repository RPC arguments against disposable PostgreSQL."""

    def __init__(self, db):
        self.db = db

    def rpc(self, name, arguments):
        def execute():
            with self.db.cursor() as c:
                c.execute(
                    sql.SQL("SELECT public.{}({})").format(
                        sql.Identifier(name),
                        sql.SQL(",").join(sql.SQL("{} => %s").format(sql.Identifier(key)) for key in arguments),
                    ),
                    [Json(v) if isinstance(v, dict) else v for v in arguments.values()],
                )
                return SimpleNamespace(data=c.fetchone()[0])
        return SimpleNamespace(execute=execute)


@pytest.mark.asyncio
async def test_repository_uses_running_engine_for_claim_and_failure(db, monkeypatch):
    from app.services import training_metrics

    user, ride = row(db)
    repo = RideRepository(PostgresRPC(db))
    current = training_metrics.ENGINE_VERSION
    with monkeypatch.context() as historical:
        historical.setattr(training_metrics, "ENGINE_VERSION", current - 1)
        await repo.finish_training_replay(ride, user, "ParseError")
        assert await repo.claim_training_replay() == []
    claimed = await repo.claim_training_replay()
    assert [r["id"] for r in claimed] == [ride]
    await repo.finish_training_replay(ride, user, "ParseError", scoring_inputs=claimed[0])
    with db.cursor() as c:
        c.execute("SELECT terminal_engine_version FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone()[0] == current
    assert await repo.claim_training_replay() == []


@pytest.mark.asyncio
async def test_repaired_original_flows_through_native_score_to_reads_without_economic_writes(db):
    from backend.tests.services.test_training_pipeline import parsed

    user, ride = row(db, "2026-10-08T01:00:00Z")
    with db.cursor() as c:
        c.execute("UPDATE rides SET raw_file_path=NULL WHERE id=%s", (ride,))
        c.execute("UPDATE users SET training_settings_history=%s WHERE id=%s", (
            Json([{"effective_at": "2026-01-01T00:00:00Z", "settings": {"timezone": "America/New_York"}}]), user))
    repo = RideRepository(PostgresRPC(db))
    repo.training_climb_patterns = AsyncMock(return_value=[])
    parse = AsyncMock(return_value=parsed())
    missing = await replay_training_batch(repo, parse=parse)
    assert missing["unavailable"] == 1
    parse.assert_not_awaited()
    assert (await replay_training_batch(repo, parse=parse))["eligible"] == 0
    with db.cursor() as c:
        c.execute("UPDATE rides SET raw_file_path='repaired.fit' WHERE id=%s", (ride,))
    repaired = await replay_training_batch(repo, parse=parse)
    assert repaired["scored"] == 1 and repaired["failed"] == 0
    with db.cursor() as c:
        c.execute("SELECT to_jsonb(r) FROM rides r WHERE id=%s", (ride,))
        saved = c.fetchone()[0]
        assert (saved["tss"], saved["cal_earned"]) == (77, 91)
        c.execute("SELECT error_class,terminal_engine_version FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone() == (None, None)  # success preserves the receipt
        c.execute("SELECT count(*) FROM training_pay_attempts")
        assert c.fetchone()[0] == 0
    # This flat-power file has no plausible CP fit; its synthetic HR yields HRSS.
    assert saved["training_metrics"]["load_basis"] == "hrss"
    assert saved["training_metrics"]["load"] == 63
    assert aggregate_riding_days([saved], start_date=date(2026, 10, 7), end_date=date(2026, 10, 7))[0]["ride_count"] == 1
    assert await repo.claim_training_replay() == []


@pytest.mark.parametrize("stale_result", [None, "ParseError"])
def test_old_input_result_cannot_clear_replacement_terminal_failure(db, stale_result):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(10)")
        old_inputs = c.fetchone()[0][0]
        c.execute("UPDATE rides SET raw_file_path='replacement.fit' WHERE id=%s", (ride,))
        c.execute("SELECT to_jsonb(r) FROM rides r WHERE id=%s", (ride,))
        new_inputs = c.fetchone()[0]
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError',2,%s)", (ride, user, Json(new_inputs)))
        c.execute("SELECT finish_training_replay(%s,%s,%s,2,%s)", (ride, user, stale_result, Json(old_inputs)))
        c.execute("SELECT terminal_engine_version,error_class FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone() == (2, "ParseError")
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []


@pytest.mark.parametrize("stale_result", [None, "ParseError", "APIError"])
def test_old_engine_result_cannot_clear_new_engine_terminal_failure(db, stale_result):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,'ParseError',3)", (ride, user))
        c.execute("SELECT finish_training_replay(%s,%s,%s,2)", (ride, user, stale_result))
        c.execute("SELECT terminal_engine_version,error_class FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone() == (3, "ParseError")
        c.execute("SELECT claim_training_replay(10,NULL,'{}',3)")
        assert c.fetchone()[0] == []


def test_success_resets_attempts_for_next_rescore_transient_backoff(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(10)")
        assert len(c.fetchone()[0]) == 1
        c.execute("UPDATE rides SET training_metrics=%s WHERE id=%s", (Json({"engine_version": 2, "load": 80, "local_date": "2026-10-01"}), ride))
        c.execute("SELECT finish_training_replay(%s,%s,NULL)", (ride, user))
        # A newly detected climb needs an additional stored read projection.
        c.execute("INSERT INTO patterns_climb(id,activity_id) VALUES(%s,%s)", (str(uuid4()), ride))
        c.execute("SELECT claim_training_replay(10)")
        assert len(c.fetchone()[0]) == 1
        c.execute("BEGIN")
        c.execute("SELECT finish_training_replay(%s,%s,'APIError')", (ride, user))
        c.execute("SELECT attempts,next_attempt_at-now()=interval '30 minutes' FROM training_replay_state WHERE ride_id=%s", (ride,))
        assert c.fetchone() == (1, True)
        c.execute("COMMIT")
