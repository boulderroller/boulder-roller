"""Static contract for parser/economic provenance hardening migration."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "backend" / "supabase" / "migrations" / "20260713_124_parser_provenance.sql"
CANONICAL_SQL = REPO_ROOT / "backend" / "sql" / "117_parser_provenance.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_live_ride_economic_plan_path_binds_an_immutable_pipeline_version() -> None:
    sql = _sql()

    assert "ADD COLUMN IF NOT EXISTS pipeline_version_id INTEGER" in sql
    assert "REFERENCES public.pipeline_versions(id)" in sql
    assert "ALTER COLUMN pipeline_version_id SET NOT NULL" in sql
    assert "CREATE OR REPLACE FUNCTION public.bind_ride_economic_plan_pipeline_version" in sql
    assert "v_pipeline_version_id" in sql
    assert "BEFORE INSERT OR UPDATE ON public.ride_economic_plans" in sql
    assert "ride_parser_version = NEW.parser_version" in sql
    assert "policy_version = NEW.policy_version" in sql
    assert "UPDATE public.ride_economic_plans AS plan" in sql
    assert "parser_version = '1'" in sql
    assert "e212e9e57ef93635b7ca5d21a68a5834af3ec1d0" in sql
    assert "9e6d49aa217c522222bb9922282df40ea799afeb" in sql
    assert "Parser semantic V1 replay row" in sql
    assert "Historical frozen ride-economic plan provenance backfill" not in sql


def test_pipeline_versions_freeze_version_vector_and_allow_only_deactivation() -> None:
    sql = _sql()

    assert "CREATE OR REPLACE FUNCTION public.prevent_pipeline_version_mutation" in sql
    assert "OLD.deactivated_at IS NULL" in sql
    assert "NEW.deactivated_at IS NOT NULL" in sql
    assert "NEW.ride_parser_version IS NOT DISTINCT FROM OLD.ride_parser_version" in sql
    assert "NEW.policy_version IS NOT DISTINCT FROM OLD.policy_version" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_versions_one_active" in sql
    assert "WHERE deactivated_at IS NULL" in sql


def test_new_ledger_rows_require_pipeline_provenance_without_breaking_legacy_reversal() -> None:
    sql = _sql()

    assert "CREATE OR REPLACE FUNCTION public.require_economic_event_pipeline_version" in sql
    assert "BEFORE INSERT ON public.economic_events" in sql
    assert "BEFORE UPDATE" not in sql.split(
        "CREATE OR REPLACE FUNCTION public.require_economic_event_pipeline_version", 1
    )[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    insert_only_function = sql.split(
        "CREATE OR REPLACE FUNCTION public.require_economic_event_pipeline_version", 1
    )[1].split("-- Keep the historical reversal workflow", 1)[0]
    assert "event_hash" not in insert_only_function
    assert "CREATE OR REPLACE FUNCTION public.prevent_ledger_mutation" in sql
    assert "NEW.pipeline_version_id IS NOT DISTINCT FROM OLD.pipeline_version_id" in sql
    assert "NEW.event_hash IS NOT DISTINCT FROM OLD.event_hash" in sql
    assert "NEW.is_reversed = TRUE" in sql


def test_canonical_sql_mirror_is_byte_identical_to_supabase_migration() -> None:
    assert CANONICAL_SQL.read_bytes() == MIGRATION.read_bytes()
