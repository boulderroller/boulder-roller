"""Local PostgreSQL contracts for migration 178; no production connection.

Table shells retain the production types/constraints. The old and current
refresh functions are read verbatim from canonical migrations. The complete
writer/trigger stack is also exercised by test_vault_completion_new_best.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import time

import psycopg2
import pytest

from backend.scripts.apply_sql_migrations import apply_migration, discover_migrations, ensure_ledger
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn, isolated_postgres_dsn,
)
from backend.tests.services.vault_completion_trigger_stack import SHELLS, latest_function

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "sql/178_db_hygiene.sql"
RIDE = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
INITIAL = datetime(2023, 1, 1, tzinfo=timezone.utc)
FINAL = datetime(2024, 1, 3, tzinfo=timezone.utc)


def old_function():
    source = (BACKEND / "sql/155_threshold_provisional_hold.sql").read_text()
    start = source.index("CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(")
    end = source.index("$$;", source.index("AS $$", start) + 5) + 3
    return source[start:end]


def install(cursor):
    cursor.execute(SHELLS)
    cursor.execute("""
        CREATE INDEX idx_vault_completions_wallet_signature
            ON public.vault_completions(wallet, vault_signature);
        CREATE TABLE refresh_updates (ride_id uuid);
        CREATE FUNCTION count_refresh_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN INSERT INTO refresh_updates VALUES (NEW.id); RETURN NEW; END $$;
        CREATE TRIGGER count_refresh_update AFTER UPDATE ON rides
            FOR EACH ROW EXECUTE FUNCTION count_refresh_update();
    """)
    cursor.execute(old_function())


@pytest.fixture
def db(isolated_postgres_dsn):
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            install(cursor)
            yield cursor


def seed(cursor):
    cursor.execute("INSERT INTO rides VALUES (%s, %s)", (RIDE, INITIAL))
    cursor.execute("INSERT INTO indexed_vaults VALUES (7, 'a'), (8, 'b')")
    cursor.execute("""
        INSERT INTO vault_completions (
            vault_signature, wallet, activity_id, cal_tribute,
            chain_confirmation_status, completion_receipt_pda,
            completion_evidence_hash, completion_evidence_version,
            chain_confirmed_at, settlement_week, settlement_clock_version
        ) VALUES
            ('a', 'rider', %s, 5, 'confirmed', 'receipt-a', decode(repeat('a',64),'hex'), 2, now(), 11, 2),
            ('b', 'rider', %s, 7, 'confirmed', 'receipt-b', decode(repeat('b',64),'hex'), 3, now(), 12, 2);
        INSERT INTO indexed_climb_completion_flows (
            vault_id, ride_attestation, completion_evidence_hash,
            credited_settlement_week, cal_tributed, completion_evidence_version
        ) VALUES
            (7, 'att', decode(repeat('a',64),'hex'), 11, 5, 2),
            (8, 'att', decode(repeat('b',64),'hex'), 12, 7, 3);
        INSERT INTO indexed_epoch_distributions VALUES
            (7, 11, '2024-01-01Z'), (7, 11, '2024-01-02Z'),
            (8, 12, '2024-01-03Z'), (8, 12, '2024-01-04Z');
    """, (RIDE, RIDE))


def exercise(cursor, function, activity_id, cast="text"):
    cursor.execute("UPDATE rides SET finalized_at = %s", (INITIAL,))
    cursor.execute("TRUNCATE refresh_updates")
    cursor.execute(function)
    # A second call must not write an unchanged finalized_at.
    for _ in range(2):
        cursor.execute(f"SELECT br_refresh_ride_finalized_at(%s::{cast}::text)", (activity_id,))
    cursor.execute("SELECT id::text, finalized_at FROM rides ORDER BY id")
    rows = cursor.fetchall()
    cursor.execute("SELECT count(*) FROM refresh_updates")
    return rows, cursor.fetchone()[0]


@pytest.mark.parametrize("change, expected", [
    ("SELECT 1", FINAL),
    ("DELETE FROM vault_completions", None),
    ("UPDATE vault_completions SET chain_confirmation_status='legacy_unverified'", None),
    ("DELETE FROM indexed_climb_completion_flows WHERE vault_id=8", None),
    ("DELETE FROM indexed_epoch_distributions WHERE vault_id=8", None),
    ("UPDATE indexed_epoch_distributions SET finalized_at=NULL WHERE vault_id=8", None),
    ("UPDATE indexed_climb_completion_flows SET completion_evidence_version=1 WHERE vault_id=8", None),
    ("UPDATE indexed_climb_completion_flows SET cal_tributed=8 WHERE vault_id=8", None),
    ("UPDATE indexed_climb_completion_flows SET vault_id=9 WHERE vault_id=8", None),
    ("UPDATE indexed_climb_completion_flows SET credited_settlement_week=13 WHERE vault_id=8", None),
    ("UPDATE vault_completions SET cal_tribute=0; UPDATE indexed_climb_completion_flows SET cal_tributed=0", None),
    ("UPDATE vault_completions SET cal_tribute=0 WHERE vault_signature='a'; "
     "UPDATE indexed_climb_completion_flows SET cal_tributed=0 WHERE vault_id=7; "
     "DELETE FROM indexed_epoch_distributions WHERE vault_id=7", FINAL),
])
def test_refresh_preserves_settlement_results_and_noop_updates(db, change, expected):
    seed(db)
    db.execute(change)
    before = exercise(db, old_function(), RIDE)
    after = exercise(db, latest_function("br_refresh_ride_finalized_at")[1], RIDE)
    assert before == after == ([(RIDE, expected)], 1)


@pytest.mark.parametrize("activity_id, cast, expected, writes", [
    (RIDE, "text", FINAL, 1),
    (RIDE, "uuid", FINAL, 1),
    (RIDE.upper(), "text", INITIAL, 0),
    ("{" + RIDE + "}", "text", INITIAL, 0),
    (RIDE.replace("-", ""), "text", INITIAL, 0),
    (" " + RIDE, "text", INITIAL, 0),
    ("not-a-uuid", "text", INITIAL, 0),
    ("123456789", "text", INITIAL, 0),
    ("", "text", INITIAL, 0),
    (None, "text", INITIAL, 0),
    ("00000000-0000-0000-0000-000000000000", "text", INITIAL, 0),
])
def test_refresh_preserves_uuid_and_text_input_behavior(db, activity_id, cast, expected, writes):
    seed(db)
    before = exercise(db, old_function(), activity_id, cast)
    after = exercise(db, latest_function("br_refresh_ride_finalized_at")[1], activity_id, cast)
    assert before == after == ([(RIDE, expected)], writes)


def test_refresh_update_uses_rides_primary_key(db):
    db.execute("INSERT INTO rides SELECT gen_random_uuid(), NULL FROM generate_series(1,50000)")
    db.execute("INSERT INTO rides VALUES (%s,NULL)", (RIDE,))
    db.execute("ANALYZE rides")
    function = latest_function("br_refresh_ride_finalized_at")[1]
    update = re.search(r"UPDATE public\.rides\b.*?;", function, re.S).group(0)
    update = update.replace("v_finalized_at", "'2024-01-03Z'::timestamptz")
    update = update.replace("p_activity_id", db.mogrify("%s::text", (RIDE,)).decode())
    update = update.replace("v_ride_id", db.mogrify("%s::uuid", (RIDE,)).decode())
    db.execute("EXPLAIN (FORMAT JSON) " + update)
    plan = db.fetchone()[0][0]["Plan"]["Plans"][0]
    assert plan["Node Type"] == "Index Scan", plan
    assert plan["Index Name"] == "rides_pkey"


def test_migration_mirror_rerun_index_dependencies_and_function_acl(db):
    mirrors = list((BACKEND / "supabase/migrations").glob("*_178_db_hygiene.sql"))
    assert len(mirrors) == 1
    assert mirrors[0].read_bytes() == MIGRATION.read_bytes()
    assert MIGRATION.read_text().splitlines()[0] == "SET LOCAL lock_timeout = '5s';"
    db.execute("REVOKE EXECUTE ON FUNCTION br_refresh_ride_finalized_at(text) FROM PUBLIC")
    db.execute("SELECT oid, proacl FROM pg_proc WHERE oid='br_refresh_ride_finalized_at(text)'::regprocedure")
    identity = db.fetchone()
    db.execute("SELECT count(*) FROM pg_constraint WHERE conindid IN "
               "('idx_vault_completions_wallet_vault'::regclass, 'idx_vault_completions_wallet_signature'::regclass)")
    assert db.fetchone() == (0,)
    for _ in range(2):
        db.execute("BEGIN")
        db.execute(MIGRATION.read_text())
        db.execute("SHOW lock_timeout")
        assert db.fetchone() == ("5s",)
        db.execute("COMMIT")
    db.execute("SELECT to_regclass('idx_vault_completions_wallet_signature'), "
               "to_regclass('idx_vault_completions_wallet_vault')")
    assert db.fetchone() == (None, "idx_vault_completions_wallet_vault")
    db.execute("SELECT oid, proacl FROM pg_proc WHERE oid='br_refresh_ride_finalized_at(text)'::regprocedure")
    assert db.fetchone() == identity


def test_lock_timeout_rolls_back_migration_and_runner_retries(isolated_postgres_dsn):
    migration = next(m for m in discover_migrations(BACKEND / "sql") if m.path == MIGRATION)
    with closing(psycopg2.connect(isolated_postgres_dsn)) as writer, \
            closing(psycopg2.connect(isolated_postgres_dsn)) as blocker:
        with writer.cursor() as cursor:
            install(cursor)
        writer.commit()
        ensure_ledger(writer)
        with blocker.cursor() as cursor:
            cursor.execute("SELECT 1 FROM vault_completions")  # AccessShareLock until rollback.
        started = time.monotonic()
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            apply_migration(writer, migration)
        assert time.monotonic() - started >= 4.5
        with writer.cursor() as cursor:
            cursor.execute("SELECT to_regclass('idx_vault_completions_wallet_signature')")
            assert cursor.fetchone()[0] is not None
            cursor.execute("SELECT count(*) FROM br_sql_migrations")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT pg_get_functiondef('br_refresh_ride_finalized_at(text)'::regprocedure)")
            assert "WHERE id::TEXT = p_activity_id" in cursor.fetchone()[0]
        writer.rollback()
        blocker.rollback()
        apply_migration(writer, migration)
        with writer.cursor() as cursor:
            cursor.execute("SELECT filename FROM br_sql_migrations")
            assert cursor.fetchall() == [(MIGRATION.name,)]
            cursor.execute("SELECT to_regclass('idx_vault_completions_wallet_signature')")
            assert cursor.fetchone() == (None,)
