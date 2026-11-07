from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = REPO_ROOT / "backend/sql/139_canon_traversal_evidence.sql"
SUPABASE = (
    REPO_ROOT
    / "backend/supabase/migrations/20260720_147_canon_traversal_evidence.sql"
)
SINGLE_RATIFIED = REPO_ROOT / "backend/sql/140_single_ratified_canon.sql"
SINGLE_RATIFIED_SUPABASE = (
    REPO_ROOT / "backend/supabase/migrations/20260720_148_single_ratified_canon.sql"
)


def test_canon_traversal_evidence_migration_is_private_immutable_and_mirrored() -> None:
    sql = CANONICAL.read_text(encoding="utf-8")

    assert sql == SUPABASE.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.canon_traversal_evidence" in sql
    assert "PRIMARY KEY (ride_id, ride_hash_hex, ride_parser_version, evidence_version)" in sql
    assert "jsonb_array_length(samples) = sample_count" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "sample_count BETWEEN 0 AND 250000" in sql
    assert "REVOKE ALL ON TABLE public.canon_traversal_evidence FROM PUBLIC, anon, authenticated" in sql
    assert "REVOKE ALL ON FUNCTION public.br_guard_canon_traversal_evidence_immutable()" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE public.canon_traversal_evidence TO service_role" in sql
    assert "canon traversal evidence is immutable for a ride identity" in sql


def test_single_ratified_canon_invariant_is_mirrored() -> None:
    sql = SINGLE_RATIFIED.read_text(encoding="utf-8")

    assert sql == SINGLE_RATIFIED_SUPABASE.read_text(encoding="utf-8")
    assert "idx_canon_climbs_one_ratified_version" in sql
    assert "ON public.canon_climbs(canon_id)" in sql
    assert "WHERE status = 'ratified'" in sql


def test_canon_reference_guard_migration_is_insert_only_and_mirrored() -> None:
    sql = (REPO_ROOT / 'backend/sql/179_canon_reference_guards.sql').read_bytes()
    assert b'BEFORE INSERT ON public.patterns_climb' in sql
    assert b'br_lock_stage1_canon_reference' not in sql
    assert b'br_stage1_canon_reference' not in sql
    assert sql == (REPO_ROOT / 'backend/supabase/migrations/20261021090000_179_canon_reference_guards.sql').read_bytes()
