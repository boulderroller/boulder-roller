"""Real disposable PostgreSQL, synthetic finalized payout projection rows."""
from pathlib import Path
import pytest

from tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn, isolated_postgres_dsn, _connection,
)

MIGRATION = Path(__file__).parents[2] / 'sql/173_stage1_notifications.sql'


@pytest.fixture
def db(isolated_postgres_dsn):
    with _connection(isolated_postgres_dsn, dict_rows=True) as c, c.cursor() as cursor:
        cursor.execute('''
          CREATE TABLE users(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), wallet text UNIQUE, account_state text DEFAULT 'active');
          CREATE TABLE notification_preferences(user_id uuid PRIMARY KEY REFERENCES users(id), in_app_enabled boolean DEFAULT true,
            payout_alerts boolean DEFAULT true, payout_received boolean DEFAULT true, push_enabled boolean DEFAULT true);
          CREATE TABLE notifications(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), user_id uuid REFERENCES users(id), wallet text,
            notification_type text, event_type text, schema_version text, title text, message text, metadata jsonb, data jsonb,
            occurred_at timestamptz, delivery_status text, delivery_channels jsonb, dedupe_key text);
          CREATE UNIQUE INDEX idx_notifications_dedupe_key ON notifications(dedupe_key) WHERE dedupe_key IS NOT NULL;
        ''')
        # Use the exact deployed projection table shape, without the unrelated
        # keeper/boundary schema or any chain process.
        source = (MIGRATION.parent / '171_stage1_indexer.sql').read_text()
        start = source.index('CREATE TABLE public.indexed_stage1_payouts (')
        cursor.execute(source[start:source.index(';', start)+1])
        if MIGRATION.exists():
            cursor.execute(MIGRATION.read_text())
        cursor.execute("INSERT INTO users(wallet) VALUES('person'),('recipient'),('unrelated')")
        yield cursor


def payout(db, leaf=0):
    db.execute('''INSERT INTO indexed_stage1_payouts VALUES('set',%s,'sig','hill',4,'mint','person','recipient',
                  9007199254740993,'cash',100) ON CONFLICT DO NOTHING''', (leaf,))


def test_payout_creates_one_exact_in_app_notification_and_replay_is_idempotent(db):
    payout(db); payout(db)
    db.execute('SELECT * FROM notifications')
    rows = db.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row['wallet'] == 'person'  # owner inbox; recipient is the registered token destination
    assert row['event_type'] == row['notification_type'] == 'payout_received'
    assert row['delivery_channels'] == ['in_app']
    assert row['metadata']['amountBaseUnits'] == '9007199254740993'
    assert row['metadata']['mint'] == 'mint'
    assert row['metadata']['stage1'] is True
    assert row['metadata']['actionUrl'] == '/profile?tab=portfolio'


@pytest.mark.parametrize('preference', ['payout_alerts', 'payout_received', 'in_app_enabled'])
def test_payout_respects_existing_preferences(db, preference):
    db.execute(f"INSERT INTO notification_preferences(user_id,{preference}) SELECT id,false FROM users WHERE wallet='person'")
    payout(db)
    db.execute('SELECT count(*) AS n FROM notifications')
    assert db.fetchone()['n'] == 0


def test_deleted_or_deleting_owner_cannot_reacquire_notification_data(db):
    db.execute("UPDATE users SET account_state='deletion_pending' WHERE wallet='person'")
    payout(db)
    db.execute("UPDATE users SET account_state='anonymized',wallet='anonymous:person' WHERE wallet='person'")
    payout(db, 1)
    db.execute('SELECT count(*) AS n FROM notifications')
    assert db.fetchone()['n'] == 0


def test_notification_and_projection_share_rollback(db):
    db.execute('BEGIN')
    payout(db)
    db.execute('ROLLBACK')
    db.execute('SELECT count(*) AS n FROM notifications')
    assert db.fetchone()['n'] == 0
