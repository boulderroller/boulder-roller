from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_SQL = REPO_ROOT / "backend" / "sql" / "118_stake_settlement_snapshots.sql"
SUPABASE_SQL = (
    REPO_ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260714_125_stake_settlement_snapshots.sql"
)


def test_stake_snapshot_migrations_are_identical():
    assert CANONICAL_SQL.read_text() == SUPABASE_SQL.read_text()


def test_stake_snapshot_migration_preserves_legacy_provenance():
    sql = CANONICAL_SQL.read_text()

    for column in (
        "effective_lp_tokens",
        "pending_lp_tokens",
        "pending_effective_week_plus_one",
        "snapshot_epoch",
    ):
        assert column in sql

    assert "ADD COLUMN IF NOT EXISTS effective_lp_tokens" in sql
    assert "ADD COLUMN IF NOT EXISTS pending_lp_tokens" in sql
    assert "ADD COLUMN IF NOT EXISTS pending_effective_week_plus_one" in sql
    assert "ADD COLUMN IF NOT EXISTS snapshot_epoch" in sql
    assert "SET snapshot_epoch = epoch" in sql
    assert "RENAME COLUMN" not in sql
    assert "Legacy pre-snapshot eligibility week" in sql
