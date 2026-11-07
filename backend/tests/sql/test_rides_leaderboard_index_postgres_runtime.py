"""Migration 181 on an isolated local PostgreSQL database."""

from contextlib import closing
from pathlib import Path

import psycopg2

from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn, isolated_postgres_dsn


def test_exact_registry_index_mirror_rerun_and_query_plan(isolated_postgres_dsn):
    root = Path(__file__).resolve().parents[2]
    migration = root / "sql/181_rides_leaderboard_registry_index.sql"
    assert migration.read_bytes() == (root / "supabase/migrations/20261021181000_181_rides_leaderboard_registry_index.sql").read_bytes()
    assert migration.read_text().startswith("SET LOCAL lock_timeout = '5s';")
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        with connection, connection.cursor() as cursor:
            cursor.execute("CREATE TABLE public.patterns_climb (id UUID PRIMARY KEY, detector_version TEXT, match_trace JSONB)")
            cursor.execute(migration.read_text())
            cursor.execute(migration.read_text())
            cursor.execute("SELECT current_setting('lock_timeout')")
            assert cursor.fetchone()[0] == "5s"
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute("""EXPLAIN (FORMAT JSON) SELECT id FROM public.patterns_climb
                WHERE detector_version = 'canon_traversal_v1' AND match_trace->>'registry_id' = 'exact-version'
                ORDER BY id LIMIT 500""")
            plan = str(cursor.fetchone()[0])
            assert "patterns_climb_registry_traversal" in plan and "exact-version" in plan
