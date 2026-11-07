from pathlib import Path

import pytest

from backend.tests.services import test_settlement_clock_postgres_runtime as pg_runtime


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "backend/sql/152_account_deletion_lifecycle.sql"
DEPLOYMENT = ROOT / "backend/supabase/migrations/20260824174338_account_deletion_lifecycle.sql"


def _sql() -> str:
    return CANONICAL.read_text(encoding="utf-8").lower()


def test_canonical_and_deployment_migrations_are_identical() -> None:
    assert CANONICAL.exists()
    assert DEPLOYMENT.exists()
    assert CANONICAL.read_bytes() == DEPLOYMENT.read_bytes()


def test_request_lifecycle_is_durable_private_and_recoverable() -> None:
    sql = _sql()
    for state in (
        "queued", "processing", "blocked", "failed_retryable",
        "needs_support", "completed", "legacy_unverified",
    ):
        assert f"'{state}'" in sql
    for field in (
        "status_token_hash", "blockers", "attempt_count",
        "worker_lease_token", "worker_lease_until",
        "unuploaded_rides_acknowledged", "storage_paths",
        "storage_authorized_at", "storage_completed_at", "failure_code", "retryable",
        "completion_verified_at",
    ):
        assert field in sql
    assert "alter table public.deletion_requests enable row level security" in sql
    assert "revoke all on public.deletion_requests from public, anon, authenticated" in sql
    assert "revoke all on public.deletion_requests from service_role" in sql
    assert "grant select on public.deletion_requests to service_role" in sql
    assert "revoke all on public.deleted_wallets from service_role" in sql
    assert "grant select on public.deleted_wallets to service_role" not in sql
    assert "create_account_deletion_request" in sql
    assert "claim_account_deletion_request" in sql
    assert "retry_account_deletion_request" in sql
    assert "retry_account_deletion_request(uuid, jsonb)" in sql
    assert "br_account_deletion_storage_paths" in sql
    assert "list_recoverable_account_deletions" in sql


def test_storage_authorization_is_an_explicit_irreversible_boundary() -> None:
    sql = _sql()
    assert "storage_authorized_at timestamptz" in sql
    assert "authorize_account_deletion_storage" in sql
    assert "public.br_account_deletion_db_blockers" in sql.split(
        "create or replace function public.authorize_account_deletion_storage", 1
    )[1].split("$$;", 1)[0]
    assert "storage_authorized_at is null" in sql.split(
        "create or replace function public.fail_account_deletion_request", 1
    )[1].split("$$;", 1)[0]
    storage_marker = sql.split(
        "create or replace function public.mark_account_deletion_storage_removed", 1
    )[1].split("$$;", 1)[0]
    assert "storage_authorized_at is null" in storage_marker
    assert "confirmed_absent" in storage_marker
    assert "'deleted'" not in storage_marker


def test_lifecycle_uses_timestamps_and_a_generated_retryability_projection() -> None:
    sql = _sql()
    assert "add column if not exists request_phase" not in sql
    assert "request_phase =" not in sql
    assert "drop column if exists request_phase" in sql
    assert "generated always as" in sql
    assert "status in ('queued', 'processing', 'blocked', 'failed_retryable')" in sql
    assert "and storage_authorized_at is null" in sql


def test_transaction_local_fence_capabilities_are_closed_after_guarded_writes() -> None:
    sql = _sql()
    for setting in (
        "app.account_deletion_user_create",
        "app.account_deletion_request_id",
    ):
        assert sql.count(f"'{setting}', ''") >= 1
    assert sql.count("'app.account_deletion_nonce_write', 'on'") == sql.count(
        "'app.account_deletion_nonce_write', ''"
    )
    assert "app.account_deletion_invite_write" not in sql


def test_pgcrypto_binding_is_independent_of_the_extension_schema() -> None:
    sql = _sql()
    assert "create extension if not exists pgcrypto with schema extensions" not in sql
    assert "extensions.gen_random_bytes" not in sql
    assert "extensions.hmac" not in sql
    assert "br_private.account_deletion_random_bytes" in sql
    assert "br_private.account_deletion_hmac" in sql


def test_invite_consumption_keeps_the_migration_145_contract() -> None:
    sql = _sql()
    assert "create or replace function public.consume_invite_code(" not in sql
    assert "br_account_deletion_assert_wallet_write_allowed" in sql
    assert "br_account_deletion_invite_usage_fence" in sql


def test_hot_ride_children_use_statement_level_fences_and_indexed_request_lookups() -> None:
    sql = _sql()
    assert "account_deletion_ride_write_fence_statement" in sql
    assert "for each statement execute function" in sql
    assert "idx_deletion_requests_write_fence_user" in sql
    assert "idx_deletion_requests_write_fence_wallet" in sql
    row_trigger_tables = sql.split("foreach v_table in array array[", 1)[1].split(
        "]", 1
    )[0]
    for table in (
        "activity_streams",
        "gps_points",
        "activity_tile_samples",
        "ride_climb_backfill_reviews",
        "segment_efforts",
    ):
        assert f"'{table}'" not in row_trigger_tables


def test_identity_retention_policy_drives_blocking_scrubbing_and_residue_checks() -> None:
    sql = _sql()
    registry = "br_private.account_deletion_identity_policy"
    assert f"create table if not exists {registry}" in sql
    assert "'swanny_seats', 'wallet', 'is_active is true', 'is_active is not true'" in sql
    blockers = sql.split(
        "create or replace function public.br_account_deletion_db_blockers", 1
    )[1].split("$$;", 1)[0]
    residue = sql.split(
        "create or replace function public.br_account_deletion_personal_residue", 1
    )[1].split("$$;", 1)[0]
    finalizer = sql.split(
        "create or replace function public.finalize_account_anonymization", 1
    )[1].split("$$;", 1)[0]
    for body in (blockers, residue, finalizer):
        assert registry in body


def test_residue_scan_skips_only_physically_empty_heaps() -> None:
    sql = _sql()
    residue = sql.split(
        "create or replace function public.br_account_deletion_personal_residue", 1
    )[1].split("$$;", 1)[0]
    assert "pg_catalog.pg_relation_size(v_spec.relation_oid) = 0" in residue
    assert "v_spec.relkind = 'r'" in residue
    assert "reltuples" not in residue
    assert "relation.relkind in ('r', 'p')" in residue


def test_shared_postgres_runtime_resolver_searches_path_for_pg17(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    postgres_bin = tmp_path / "pg17-bin"
    postgres_bin.mkdir()
    for tool in ("initdb", "pg_ctl"):
        (postgres_bin / tool).touch()
    monkeypatch.setattr(pg_runtime, "POSTGRES_17_HOME", tmp_path / "missing")
    monkeypatch.setattr(
        pg_runtime.shutil,
        "which",
        lambda tool: str(postgres_bin / tool) if tool in {"initdb", "pg_ctl"} else None,
    )
    monkeypatch.setattr(pg_runtime, "_postgres_major_version", lambda _path: 17)

    assert pg_runtime._find_postgres_17_bin() == postgres_bin


def test_shared_postgres_runtime_unavailability_fails_closed_in_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="PostgreSQL runtime unavailable"):
        pg_runtime._unavailable_postgres_runtime("PostgreSQL runtime unavailable")


def test_server_functions_are_not_public_capabilities() -> None:
    sql = _sql()
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "revoke execute on function" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant execute on function" in sql
    assert "to service_role" in sql
    assert "revoke all on schema br_private from public, anon, authenticated, service_role" in sql
    assert (
        "revoke execute on function public.br_account_deletion_wallet_fingerprint(text) "
        "from public, anon, authenticated, service_role"
    ) in sql
    assert (
        "revoke execute on function public.br_get_auth_account_authority(text) "
        "from public, anon, authenticated"
    ) in sql
    assert (
        "grant execute on function public.br_get_auth_account_authority(text) "
        "to service_role"
    ) in sql


def test_atomic_finalization_rechecks_the_destructive_boundary() -> None:
    sql = _sql()
    finalizer = sql.split(
        "create or replace function public.finalize_account_anonymization", 1
    )[1]
    assert "public.br_account_deletion_db_blockers" in finalizer
    assert "storage_completed_at is null" in finalizer
    assert "unuploaded_rides_acknowledged" in finalizer
    assert "worker_lease_token is distinct from p_lease_token" in finalizer
    assert finalizer.index("status = 'completed'") > finalizer.index("delete from public.users")
    assert finalizer.index("status = 'completed'") > finalizer.index(
        "public.br_account_deletion_personal_residue"
    )
    assert finalizer.index("status = 'completed'") > finalizer.index(
        "insert into public.deleted_account_tombstones"
    )
    assert "set user_id = null, wallet = null" in finalizer
    assert "completion_verified_at = clock_timestamp()" in finalizer


def test_tombstone_is_private_hmac_fingerprint_not_raw_wallet() -> None:
    sql = _sql()
    tombstone = sql.split(
        "create table if not exists public.deleted_account_tombstones", 1
    )[1].split(";", 1)[0]
    assert "wallet_fingerprint" in tombstone
    assert "wallet text" not in tombstone
    assert "wallet_fingerprint ~ '^[0-9a-f]{64}$'" in sql
    assert "status_token_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "anonymous_marker" in sql
    assert "account_deleted_at" in sql
    assert "set wallet = null" in sql
    assert "alter table public.deleted_account_tombstones enable row level security" in sql
    assert "revoke all on public.deleted_account_tombstones from public, anon, authenticated" in sql


def test_active_request_fences_value_creating_database_writes() -> None:
    sql = _sql()
    assert "account_deletion_write_fence" in sql
    for table in (
        "rides", "claims", "vesting_schedules", "user_state",
        "balance_operations", "ride_economic_plans", "economic_events",
    ):
        assert f"'{table}'" in sql
