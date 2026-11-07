from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = BACKEND_ROOT / "sql" / "124_economic_ledger_atomic_append.sql"
MIGRATION_PATH = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260714_132_economic_ledger_atomic_append.sql"
)


def test_atomic_ledger_migration_is_canonical_and_complete() -> None:
    assert CANONICAL_PATH.exists()
    assert MIGRATION_PATH.exists()
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    assert MIGRATION_PATH.read_text(encoding="utf-8") == canonical

    for contract in (
        "ADD COLUMN IF NOT EXISTS hash_version",
        "canonical_ledger_numeric",
        "economic_event_hash_v2",
        "pg_catalog.sha256",
        "append_economic_event",
        "pg_advisory_xact_lock",
        "SECURITY DEFINER",
        "SET search_path = ''",
        "p_amount TEXT",
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE",
        "REVOKE ALL ON FUNCTION public.append_economic_event",
        "GRANT EXECUTE ON FUNCTION public.append_economic_event",
        "ENABLE ROW LEVEL SECURITY",
    ):
        assert contract in canonical

    assert "GRANT INSERT" not in canonical
    assert "GRANT UPDATE" not in canonical
    assert "GRANT DELETE" not in canonical
