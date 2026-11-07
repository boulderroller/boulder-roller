"""The privacy preference opts in only by an explicit persisted boolean."""

from contextlib import closing
from pathlib import Path

import psycopg2

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn, isolated_postgres_dsn,
)


def test_existing_and_new_accounts_default_private_and_opt_in_can_be_revoked(isolated_postgres_dsn):
    sql = Path(__file__).resolve().parents[2] / "sql/177_share_wkg_privacy.sql"
    mirror = sql.parents[1] / "supabase/migrations/20261020170000_177_share_wkg_privacy.sql"
    assert sql.read_bytes() == mirror.read_bytes()
    first = next(line.strip() for line in sql.read_text().splitlines() if line.strip() and not line.startswith('--'))
    assert first == "SET LOCAL lock_timeout = '5s';"
    with closing(psycopg2.connect(isolated_postgres_dsn)) as conn, conn, conn.cursor() as c:
        c.execute("CREATE TABLE users(id integer PRIMARY KEY)")
        c.execute("INSERT INTO users VALUES (1)")
        c.execute(sql.read_text())
        c.execute("INSERT INTO users(id) VALUES (2)")
        c.execute("SELECT share_wkg FROM users ORDER BY id")
        assert c.fetchall() == [(False,), (False,)]
        c.execute("UPDATE users SET share_wkg=true WHERE id=1")
        c.execute("SELECT share_wkg FROM users WHERE id=1")
        assert c.fetchone() == (True,)
        c.execute(sql.read_text())
        c.execute("SELECT share_wkg FROM users ORDER BY id")
        assert c.fetchall() == [(True,), (False,)]
        c.execute("UPDATE users SET share_wkg=false WHERE id=1")
        c.execute("SELECT share_wkg FROM users WHERE id=1")
        assert c.fetchone() == (False,)
