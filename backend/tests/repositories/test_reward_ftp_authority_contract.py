"""Static contract for immutable reward-FTP authority and provenance."""

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = BACKEND_ROOT / "sql" / "123_reward_ftp_authority.sql"
MIGRATION_PATH = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260714_131_reward_ftp_authority.sql"
)


def test_reward_ftp_migration_is_canonical_and_complete() -> None:
    assert CANONICAL_PATH.exists()
    assert MIGRATION_PATH.exists()
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert migration == canonical

    for contract in (
        "CREATE TABLE IF NOT EXISTS public.reward_ftp_authorities",
        "CREATE OR REPLACE FUNCTION public.register_reward_ftp_authority",
        "CREATE OR REPLACE FUNCTION public.bind_ride_reward_ftp",
        "trg_reward_ftp_authorities_immutable",
        "trg_rides_reward_ftp_immutable",
        "reward_ftp_policy_2026_07_14",
        "ride_effort_policy_2026_07_14_ftp_v1",
        "reward_ftp_authority_id",
        "reward_ftp_policy_version",
        "economic_tss",
        "date_trunc('week'",
        "pg_catalog.sha256",
    ):
        assert contract in canonical

    assert "public.digest" not in canonical
    assert "REVOKE ALL ON public.reward_ftp_authorities FROM anon, authenticated" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.bind_ride_reward_ftp" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.register_reward_ftp_authority" in canonical
