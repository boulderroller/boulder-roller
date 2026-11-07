"""Local PostgreSQL only: canonical identity, replay, access and deletion."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn, isolated_postgres_dsn,
)

SQL = Path(__file__).resolve().parents[2] / "sql/175_climb_effort_metrics.sql"
MIRROR = SQL.parents[1] / "supabase/migrations/20261020150000_175_climb_effort_metrics.sql"


@pytest.fixture
def storage(isolated_postgres_dsn):
    conn = psycopg2.connect(isolated_postgres_dsn)
    conn.autocommit = True
    user, ride, climb, effort = [str(uuid4()) for _ in range(4)]
    inputs = {"started_at": "2026-10-01T12:00:00Z", "threshold": {"value": 250}}
    row = {
        "id": effort, "climb_id": climb, "canon_version": 1,
        "start_offset_s": 10.5, "end_offset_s": 70.5,
        "achieved_at": "2026-10-01T12:01:10.5Z",
        "metrics": {"engine_version": 1, "time_s": 60, "avg_power_w": 250,
                    "power_kind": "measured", "w_per_kg": 4},
    }
    trace = {"registry_id": climb, "canon_version": 1,
             "gate_crossings": {"start_time_s_raw": 10.5, "finish_time_s_raw": 70.5}}
    with conn.cursor() as c:
        c.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
        END $$;
        CREATE TABLE users(id uuid PRIMARY KEY, account_state text DEFAULT 'active');
        CREATE TABLE rides(id uuid PRIMARY KEY,user_id uuid REFERENCES users,training_inputs jsonb,
            idle bool DEFAULT true,processing_status text DEFAULT 'completed');
        CREATE TABLE canon_climbs(id uuid PRIMARY KEY);
        CREATE TABLE patterns_climb(id uuid PRIMARY KEY,activity_id uuid REFERENCES rides ON DELETE CASCADE,
            detector_version text,match_trace jsonb,time_s int);
        CREATE FUNCTION training_payment_idle(uuid) RETURNS bool LANGUAGE sql AS
          'SELECT idle FROM public.rides WHERE id=$1';
        CREATE FUNCTION training_counted_statuses() RETURNS text[] LANGUAGE sql AS
          $$ SELECT ARRAY['metrics_ready','enriched','completed','under_review']::text[] $$;
        """)
        c.execute("INSERT INTO users(id) VALUES(%s)", (user,))
        c.execute("INSERT INTO rides(id,user_id,training_inputs) VALUES(%s,%s,%s)", (ride, user, Json(inputs)))
        c.execute("INSERT INTO canon_climbs VALUES(%s)", (climb,))
        c.execute("INSERT INTO patterns_climb VALUES(%s,%s,'canon_traversal_v1',%s,60)",
                  (effort, ride, Json(trace)))
        c.execute(SQL.read_text())
    yield conn, user, ride, inputs, row
    conn.close()


def store(storage, row=None, inputs=None):
    conn, user, ride, frozen, original = storage
    with conn.cursor() as c:
        c.execute("SELECT store_climb_efforts(%s,%s,%s,%s)",
                  (ride, user, Json(inputs or frozen), Json([row or original])))


def test_migration_mirror_is_exact():
    assert SQL.read_bytes() == MIRROR.read_bytes()
    first = next(line.strip() for line in SQL.read_text().splitlines() if line.strip() and not line.startswith('--'))
    assert first == "SET LOCAL lock_timeout = '5s';"


def test_estimated_storage_rejects_measured_watts_even_without_wkg(storage):
    row = {**storage[-1], 'metrics': {'engine_version': 3, 'time_s': 60,
           'power_kind': 'estimated', 'estimated_power_w': 200,
           'estimated_power_range_w': [180, 220], 'avg_power_w': 200}}
    with pytest.raises(psycopg2.errors.CheckViolation):
        store(storage, row)


def test_replay_is_idempotent_and_only_service_can_read(storage):
    store(storage)
    store(storage)
    conn, _, _, _, row = storage
    with conn.cursor() as c:
        c.execute("SELECT count(*), min(avg_power_w) FROM climb_efforts")
        assert c.fetchone() == (1, 250)
        for role in ("anon", "authenticated"):
            c.execute("SELECT has_table_privilege(%s,'climb_efforts','SELECT'), "
                      "has_function_privilege(%s,'store_climb_efforts(uuid,uuid,jsonb,jsonb)','EXECUTE')",
                      (role, role))
            assert c.fetchone() == (False, False)
        c.execute("SELECT has_table_privilege('service_role','climb_efforts','INSERT')")
        assert c.fetchone() == (False,)
        c.execute("SELECT metrics FROM climb_efforts WHERE id=%s", (row["id"],))
        assert c.fetchone()[0] == row["metrics"]


@pytest.mark.parametrize("field,value", [("start_offset_s", 10), ("end_offset_s", 71),
                                       ("climb_id", str(uuid4())), ("canon_version", 2)])
def test_storage_rejects_forged_canonical_span(storage, field, value):
    row = {**storage[-1], field: value}
    with pytest.raises(psycopg2.Error, match="canonical span conflict"):
        store(storage, row)


def test_storage_obeys_frozen_inputs_payment_and_deletion(storage):
    conn, user, ride, _, _ = storage
    with pytest.raises(psycopg2.Error, match="snapshot conflict"):
        store(storage, inputs={"threshold": {"value": 999}})
    with conn.cursor() as c:
        c.execute("UPDATE rides SET idle=false WHERE id=%s", (ride,))
    with pytest.raises(psycopg2.Error, match="payment attempt active"):
        store(storage)
    with conn.cursor() as c:
        c.execute("UPDATE rides SET idle=true WHERE id=%s", (ride,))
    store(storage)
    with conn.cursor() as c:
        c.execute("UPDATE users SET account_state='deletion_pending' WHERE id=%s", (user,))
        c.execute("SELECT count(*) FROM climb_efforts")
        assert c.fetchone() == (1,)  # pending can be rolled back by the deletion worker
    with pytest.raises(psycopg2.Error, match="owner unavailable"):
        store(storage)
    with conn.cursor() as c:
        c.execute("UPDATE users SET account_state='active' WHERE id=%s", (user,))
    store(storage)
    with conn.cursor() as c:
        # The real deletion finalizer detaches retained patterns, then checks
        # every ride FK before DELETE (it will not rely on ON DELETE CASCADE).
        c.execute("UPDATE patterns_climb SET activity_id=NULL WHERE activity_id=%s", (ride,))
        c.execute("SELECT count(*) FROM climb_efforts WHERE ride_id=%s OR user_id=%s", (ride, user))
        assert c.fetchone() == (0,)
        c.execute("DELETE FROM rides WHERE id=%s", (ride,))
        c.execute("SELECT count(*) FROM climb_efforts")
        assert c.fetchone() == (0,)


def test_failed_ride_cannot_receive_effort_reads(storage):
    with storage[0].cursor() as c:
        c.execute("UPDATE rides SET processing_status='failed'")
    with pytest.raises(psycopg2.Error, match="ineligible"):
        store(storage)


@pytest.mark.asyncio
async def test_training_path_persists_each_canonical_effort_with_frozen_threshold():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from datetime import datetime, timezone
    from backend.tests.services.test_canon_traversal import _evaluate, _sample
    from backend.tests.services.test_climb_effort_metrics import vectors
    from app.services.training_metrics import TrainingMetricsService

    patterns = _evaluate([_sample(i * 10, i / 5) for i in range(6)]).climb_patterns
    repo = SimpleNamespace(
        bind_training_inputs=AsyncMock(return_value={
            "started_at": "2026-10-01T12:00:00Z", "threshold": {"value": 200},
            "settings": {"timezone": "UTC"},
        }),
        training_climb_patterns=AsyncMock(return_value=[p.to_dict() for p in patterns]),
        store_climb_efforts=AsyncMock(),
        store_training_metrics=AsyncMock(return_value={"stored": True}),
    )
    parsed = SimpleNamespace(
        started_at=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
        _native_activity=vectors.synthetic_activity(list(range(51)), [200] * 51, [5] * 51),
    )
    assert await TrainingMetricsService(repo).score(ride_id="r", user_id="u", parsed_ride=parsed) == {"stored": True}
    args = repo.store_climb_efforts.await_args.args
    assert args[:2] == ("r", "u")
    assert len(args[3]) == len(patterns) == 1
    assert args[3][0]["metrics"]["intensity_factor"] == 1
    assert args[3][0]["id"] == str(patterns[0].id)


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_parse_or_write():
    import importlib.util
    from unittest.mock import AsyncMock

    path = SQL.parents[1] / "scripts/backfill_climb_efforts.py"
    spec = importlib.util.spec_from_file_location("effort_backfill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo, parse = AsyncMock(), AsyncMock()
    counts = await module.backfill(repo, [
        {"training_inputs": {"threshold": 250}, "raw_file_path": "synthetic.fit", "processing_status": "completed"},
        {"training_inputs": None, "raw_file_path": "synthetic.fit", "processing_status": "completed"},
        {"training_inputs": {"threshold": 250}, "raw_file_path": "synthetic.fit", "processing_status": "failed"},
    ], parse)
    assert counts == dict(eligible=1, scored=0, unavailable=1, skipped=1, failed=0)
    parse.assert_not_awaited()
    repo.store_climb_efforts.assert_not_awaited()


def test_effort_migration_is_rerunnable_without_erasing_rows(storage):
    store(storage)
    with storage[0].cursor() as c:
        c.execute(SQL.read_text())
        c.execute('SELECT count(*) FROM climb_efforts')
        assert c.fetchone() == (1,)


@pytest.mark.asyncio
async def test_effort_failure_logs_ride_and_training_still_stores(monkeypatch, caplog):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services.training_metrics import TrainingMetricsService
    from app.services import climb_effort_metrics
    from backend.tests.services.test_climb_effort_metrics import vectors
    def broken(*_):
        raise RuntimeError('synthetic effort failure')
    monkeypatch.setattr(climb_effort_metrics, 'build_effort_rows', broken)
    repo = SimpleNamespace(bind_training_inputs=AsyncMock(return_value={
        'started_at': '2026-10-01T12:00:00Z', 'threshold': {'value': 200}, 'settings': {'timezone': 'UTC'}}),
        training_climb_patterns=AsyncMock(return_value=[]), store_climb_efforts=AsyncMock(),
        store_training_metrics=AsyncMock(return_value={'stored': True}))
    parsed = SimpleNamespace(started_at=datetime(2026,10,1,12,tzinfo=timezone.utc),
                             _native_activity=vectors.synthetic_activity(list(range(21)),[200]*21,[5]*21))
    assert await TrainingMetricsService(repo).score(ride_id='failed-effort-ride', user_id='u', parsed_ride=parsed) == {'stored': True}
    repo.store_training_metrics.assert_awaited_once()
    assert 'failed-effort-ride' in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('ride_hash_hex','cd'*32), ('ride_parser_version',4)])
async def test_backfill_rejects_changed_original_identity_and_names_ride(field, value, monkeypatch, caplog):
    import importlib.util
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services.canon_traversal_evidence import CanonTraversalEvidence
    from app.services import climb_effort_metrics
    from backend.tests.services.test_canon_traversal_evidence import _TileService
    spec = importlib.util.spec_from_file_location('effort_backfill', SQL.parents[1] / 'scripts/backfill_climb_efforts.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    ride = dict(id=str(uuid4()), user_id='u', training_inputs={'threshold':250},
                raw_file_path='synthetic.fit', processing_status='completed', ride_hash_hex='ab'*32, ride_parser_version=5)
    parsed = {key:ride[key] for key in ('ride_hash_hex','ride_parser_version')}; parsed[field]=value
    # Valid evidence agrees with the changed parse, so the later identity fence
    # cannot mask a bypass of the original-file check.
    evidence = CanonTraversalEvidence.build(ride_id=UUID(ride['id']), **parsed,
        parsed_ride=SimpleNamespace(started_at=None, records=[{'timestamp':t, 'lat':40+t*.001, 'lon':-75} for t in range(3)]),
        tile_service=_TileService()).to_row()
    repo = SimpleNamespace(store_climb_efforts=AsyncMock(), training_climb_patterns=AsyncMock(return_value=[]),
        get_canon_traversal_evidence=AsyncMock(return_value=evidence))
    monkeypatch.setattr(climb_effort_metrics, 'build_effort_rows', lambda *_: [{'id':'synthetic-effort'}])
    counts = await module.backfill(repo, [ride],
        AsyncMock(return_value=SimpleNamespace(**parsed, _native_activity=object())), apply=True)
    assert counts['failed'] == 1 and ride['id'] in caplog.text
    assert 're-parsed original identity mismatch' in caplog.text
    repo.get_canon_traversal_evidence.assert_not_awaited()
    repo.store_climb_efforts.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('corrupt', [None, 'digest', 'ride', 'hash', 'version'])
async def test_backfill_evidence_identity_and_digest_are_independent_of_reparse_check(monkeypatch, corrupt, caplog):
    import importlib.util
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services.canon_traversal_evidence import CanonTraversalEvidence
    from app.services import climb_effort_metrics
    from backend.tests.services.test_canon_traversal_evidence import _TileService
    spec = importlib.util.spec_from_file_location('effort_backfill', SQL.parents[1] / 'scripts/backfill_climb_efforts.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    ride = dict(id=str(uuid4()), user_id='u', training_inputs={'threshold':250}, raw_file_path='synthetic.fit',
                processing_status='completed', ride_hash_hex='ab'*32, ride_parser_version=5)
    evidence = CanonTraversalEvidence.build(
        ride_id=uuid4() if corrupt == 'ride' else UUID(ride['id']),
        ride_hash_hex='cd'*32 if corrupt == 'hash' else ride['ride_hash_hex'],
        ride_parser_version=4 if corrupt == 'version' else 5,
        parsed_ride=SimpleNamespace(started_at=None, records=[{'timestamp':t, 'lat':40+t*.001, 'lon':-75} for t in range(3)]),
        tile_service=_TileService()).to_row()
    if corrupt == 'digest':
        evidence['sample_digest'] = '00'*32
    repo = SimpleNamespace(get_canon_traversal_evidence=AsyncMock(return_value=evidence),
        training_climb_patterns=AsyncMock(return_value=[]), store_climb_efforts=AsyncMock())
    monkeypatch.setattr(climb_effort_metrics, 'build_effort_rows', lambda *_: [{'id':'synthetic-effort'}])
    parsed = SimpleNamespace(ride_hash_hex=ride['ride_hash_hex'], ride_parser_version=5, _native_activity=object())
    counts = await module.backfill(repo, [ride], AsyncMock(return_value=parsed), apply=True)
    if corrupt:
        assert counts['failed'] == 1 and ride['id'] in caplog.text
        repo.store_climb_efforts.assert_not_awaited()
    else:
        assert counts['scored'] == 1 and counts['failed'] == 0
        repo.store_climb_efforts.assert_awaited_once()
