"""Static contract for derived Threshold evidence and Monday authority."""

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = BACKEND_ROOT / "sql" / "154_derived_threshold_authority.sql"


def test_derived_threshold_migration_is_private_complete_and_mirrored() -> None:
    assert CANONICAL_PATH.exists()
    mirrors = list(
        (BACKEND_ROOT / "supabase" / "migrations").glob(
            "*_derived_threshold_authority.sql"
        )
    )
    assert len(mirrors) == 1
    assert mirrors[0].name > "20260825012923_public_data_api_rls_lockdown.sql"
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    assert mirrors[0].read_text(encoding="utf-8") == canonical

    for contract in (
        "CREATE TABLE public.reward_threshold_efforts",
        "CREATE TABLE public.reward_threshold_candidates",
        "CREATE TABLE public.reward_threshold_source_envelopes",
        "CREATE TABLE public.reward_threshold_ratchets",
        "CREATE TABLE public.reward_threshold_pending_promotions",
        "CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort",
        "CREATE OR REPLACE FUNCTION public.seal_due_reward_threshold_promotions",
        "CREATE OR REPLACE FUNCTION public.bind_ride_reward_ftp",
        "derived_eftp",
        "threshold_cp_3_7_15_v1",
        "reward_ftp_policy_2026_08_24_threshold_v1",
        "2.5",
        "date_trunc('week'",
        "pg_catalog.sha256",
        "ENABLE ROW LEVEL SECURITY",
        "upload_verified_at",
        "ceil_after_raw_deadband",
    ):
        assert contract in canonical

    assert "GRANT EXECUTE ON FUNCTION public.register_reward_threshold_effort" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.seal_due_reward_threshold_promotions" in canonical
    assert "REVOKE ALL ON FUNCTION public.register_reward_ftp_authority" in canonical
    assert "FROM PUBLIC, anon, authenticated, service_role" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.register_reward_ftp_authority" not in canonical
    assert "GRANT INSERT ON public.reward_threshold" not in canonical
    assert "ON DELETE SET NULL" in canonical
    assert "br_account_deletion_db_blockers_pre_threshold" in canonical
    for table_name in (
        "reward_threshold_efforts",
        "reward_threshold_candidates",
        "reward_threshold_source_envelopes",
        "reward_threshold_ratchets",
        "reward_threshold_pending_promotions",
    ):
        assert f"'{table_name}'" in canonical
    assert "public.account_deletion_write_fence(''false'')" in canonical
    assert "public.reward_threshold_account_owner_fence()" in canonical
    assert "account_deletion_00_threshold_owner_lock" in canonical
    assert "FOR KEY SHARE" in canonical
    assert "idx_reward_threshold_candidates_user_created" not in canonical
    assert "idx_reward_threshold_efforts_user" in canonical
    assert "idx_reward_threshold_candidates_user" in canonical
    assert "economic_candidate_w BETWEEN 50 AND 500" in canonical
    assert "accepted_candidate_w BETWEEN 50 AND 500" in canonical
    assert "target_candidate_w BETWEEN 50 AND 500" in canonical
    assert "(disposition = 'superseded') = (superseded_at IS NOT NULL)" in canonical
    assert "WITH active_authority_users AS MATERIALIZED" in canonical
    assert '"user".account_state = \'active\'' in canonical
    assert "GRANT EXECUTE ON FUNCTION public.repair_reward_threshold_promotion" in canonical
    assert "SET TimeZone = 'UTC'" in canonical


def test_threshold_migration_does_not_reintroduce_repeated_corroboration() -> None:
    canonical = CANONICAL_PATH.read_text(encoding="utf-8").lower()
    assert "repeated_corrob" not in canonical
    assert "physics_residual" not in canonical
