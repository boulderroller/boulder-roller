from __future__ import annotations

from pathlib import Path

import pytest

from backend.scripts.apply_sql_migrations import (
    Migration,
    assert_manual_approval,
    baseline_migrations,
    discover_migrations,
    expected_catalog_fingerprint,
)


APPROVAL_ENV = "APPROVED_PUBLIC_DATA_API_RLS_SHA256"
APPROVAL_PROJECT_ENV = "APPROVED_PUBLIC_DATA_API_RLS_PROJECT_REF"
APPROVAL_CATALOG_ENV = "APPROVED_PUBLIC_DATA_API_RLS_CATALOG_SHA256"
LOCKED_MIGRATION = "153_public_data_api_rls_lockdown.sql"
PROJECT_REF = "qzkqjevawthyboymqrle"
CATALOG_FINGERPRINT = "c" * 64
OTHER_CATALOG_FINGERPRINT = "d" * 64
DIRECT_DATABASE_URL = (
    f"postgresql://postgres:secret@db.{PROJECT_REF}.supabase.co:5432/postgres"
)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _migration(filename: str = LOCKED_MIGRATION) -> Migration:
    return Migration(
        path=BACKEND_ROOT / "sql" / filename,
        filename=filename,
        number=153,
        checksum="a" * 64,
    )


def test_locked_migration_requires_exact_checksum_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    monkeypatch.delenv(APPROVAL_ENV, raising=False)
    monkeypatch.setenv(APPROVAL_PROJECT_ENV, PROJECT_REF)
    monkeypatch.setenv(APPROVAL_CATALOG_ENV, CATALOG_FINGERPRINT)

    with pytest.raises(SystemExit, match=APPROVAL_ENV):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_ENV, "b" * 64)
    with pytest.raises(SystemExit, match=migration.checksum):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_ENV, migration.checksum.upper())
    assert_manual_approval(
        migration,
        database_url=DIRECT_DATABASE_URL,
        catalog_fingerprint=CATALOG_FINGERPRINT,
        expected_catalog_fingerprint=CATALOG_FINGERPRINT,
    )


def test_locked_migration_binds_approval_to_supabase_project_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    monkeypatch.setenv(APPROVAL_ENV, migration.checksum)
    monkeypatch.setenv(APPROVAL_CATALOG_ENV, CATALOG_FINGERPRINT)
    monkeypatch.delenv(APPROVAL_PROJECT_ENV, raising=False)

    with pytest.raises(SystemExit, match=APPROVAL_PROJECT_ENV):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_PROJECT_ENV, "wrong-project")
    with pytest.raises(SystemExit, match=PROJECT_REF):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_PROJECT_ENV, PROJECT_REF)
    pooler_url = (
        "postgresql://postgres."
        f"{PROJECT_REF}:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    )
    assert_manual_approval(
        migration,
        database_url=pooler_url,
        catalog_fingerprint=CATALOG_FINGERPRINT,
        expected_catalog_fingerprint=CATALOG_FINGERPRINT,
    )

    other_project_ref = "abcdefghijklmnopqrst"
    monkeypatch.setenv(APPROVAL_PROJECT_ENV, other_project_ref)
    with pytest.raises(SystemExit, match=PROJECT_REF):
        assert_manual_approval(
            migration,
            database_url=(
                "postgresql://postgres:secret@db."
                f"{other_project_ref}.supabase.co:5432/postgres"
            ),
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    with pytest.raises(SystemExit, match="project ref"):
        assert_manual_approval(
            migration,
            database_url="postgresql://postgres:secret@localhost:5432/postgres",
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )


def test_locked_migration_binds_approval_to_catalog_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    monkeypatch.setenv(APPROVAL_ENV, migration.checksum)
    monkeypatch.setenv(APPROVAL_PROJECT_ENV, PROJECT_REF)
    monkeypatch.delenv(APPROVAL_CATALOG_ENV, raising=False)

    with pytest.raises(SystemExit, match=APPROVAL_CATALOG_ENV):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_CATALOG_ENV, OTHER_CATALOG_FINGERPRINT)
    with pytest.raises(SystemExit, match=CATALOG_FINGERPRINT):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_CATALOG_ENV, CATALOG_FINGERPRINT.upper())
    assert_manual_approval(
        migration,
        database_url=DIRECT_DATABASE_URL,
        catalog_fingerprint=CATALOG_FINGERPRINT,
        expected_catalog_fingerprint=CATALOG_FINGERPRINT,
    )


def test_locked_migration_requires_live_and_env_to_match_committed_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    monkeypatch.setenv(APPROVAL_ENV, migration.checksum)
    monkeypatch.setenv(APPROVAL_PROJECT_ENV, PROJECT_REF)
    monkeypatch.setenv(APPROVAL_CATALOG_ENV, CATALOG_FINGERPRINT)

    with pytest.raises(SystemExit, match="committed catalog"):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=OTHER_CATALOG_FINGERPRINT,
        )

    monkeypatch.setenv(APPROVAL_CATALOG_ENV, OTHER_CATALOG_FINGERPRINT)
    with pytest.raises(SystemExit, match="live catalog"):
        assert_manual_approval(
            migration,
            database_url=DIRECT_DATABASE_URL,
            catalog_fingerprint=CATALOG_FINGERPRINT,
            expected_catalog_fingerprint=OTHER_CATALOG_FINGERPRINT,
        )


def test_locked_migration_has_a_committed_catalog_expectation() -> None:
    fingerprint = expected_catalog_fingerprint(_migration())
    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")


def test_locked_migration_checksum_pins_sql_and_catalog_manifest(
    tmp_path: Path,
) -> None:
    sql_path = tmp_path / LOCKED_MIGRATION
    manifest_path = tmp_path / "153_public_data_api_rls_lockdown.catalog.json"
    sql_path.write_text("SELECT 1;\n", encoding="utf-8")
    manifest_path.write_text('{"version":1}\n', encoding="utf-8")
    first = discover_migrations(tmp_path)[0].checksum

    manifest_path.write_text('{"version":1,"changed":true}\n', encoding="utf-8")
    second = discover_migrations(tmp_path)[0].checksum
    assert second != first


def test_unlocked_migration_does_not_require_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(APPROVAL_ENV, raising=False)

    assert_manual_approval(
        _migration("151_unrelated.sql"),
        database_url=None,
        catalog_fingerprint=None,
        expected_catalog_fingerprint=None,
    )


def test_locked_migration_cannot_be_baselined() -> None:
    class FakeCursor:
        def __enter__(self) -> "FakeCursor":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, *_args: object) -> None:
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.cursor_calls = 0

        def cursor(self) -> FakeCursor:
            self.cursor_calls += 1
            return FakeCursor()

        def commit(self) -> None:
            return None

    connection = FakeConnection()
    with pytest.raises(SystemExit, match="cannot be baselined"):
        baseline_migrations(  # type: ignore[arg-type]
            connection, [_migration()], {}, 153
        )
    assert connection.cursor_calls == 0
