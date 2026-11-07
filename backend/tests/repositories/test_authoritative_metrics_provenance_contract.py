"""Static contract for authoritative ride-metrics provenance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    REPO_ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260714_130_authoritative_ride_metrics.sql"
)
CANONICAL_SQL = (
    REPO_ROOT / "backend" / "sql" / "122_authoritative_ride_metrics.sql"
)
IMPLEMENTATION_COMMIT = "5d4c2c2eb150115a9b2deb771e7bcde2e199f3c7"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_ride_metrics_evidence_is_persisted_without_inventing_history() -> None:
    sql = _sql()

    for column in (
        "moving_time_sec INTEGER",
        "metrics_version TEXT",
        "power_sample_count INTEGER",
        "power_sample_coverage_bps INTEGER",
        "heart_rate_sample_count INTEGER",
        "heart_rate_sample_coverage_bps INTEGER",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql

    assert "CHECK (moving_time_sec IS NULL OR moving_time_sec >= 0)" in sql
    assert "CHECK (power_sample_count IS NULL OR power_sample_count >= 0)" in sql
    assert "power_sample_coverage_bps BETWEEN 0 AND 10000" in sql
    assert (
        "CHECK (heart_rate_sample_count IS NULL OR heart_rate_sample_count >= 0)"
        in sql
    )
    assert "heart_rate_sample_coverage_bps BETWEEN 0 AND 10000" in sql
    assert "UPDATE public.rides" not in sql
    assert "NULL for rides processed before authoritative metrics versioning" in sql


def test_parser_v3_policy_vector_is_exact_single_active_and_immutable() -> None:
    sql = _sql()

    assert "parser_version = '3'" in sql
    assert "ride_parser_version = 3" in sql
    assert "ride_effort_policy_2026_07_14" in sql
    assert IMPLEMENTATION_COMMIT in sql
    assert "authoritative metrics V3 provenance conflict" in sql
    assert (
        "authoritative metrics V3 pipeline version is inactive "
        "and cannot be reactivated"
        in sql
    )
    assert "WHERE deactivated_at IS NULL AND id <> v_v3_id" in sql
    assert "v_template.detector_algorithm" in sql
    assert "v_template.detector_params_hash" in sql
    assert "v_template.sig_format_version" in sql
    assert "v_template.integrity_version" in sql


def test_canonical_sql_mirror_is_byte_identical_to_supabase_migration() -> None:
    assert CANONICAL_SQL.read_bytes() == MIGRATION.read_bytes()
