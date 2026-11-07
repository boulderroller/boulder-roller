from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SQL = BACKEND_ROOT / "sql" / "114_ride_economic_recovery.sql"
MIGRATION_SQL = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260713_121_ride_economic_recovery.sql"
)


def test_ride_economic_sql_and_supabase_migration_are_identical() -> None:
    assert SOURCE_SQL.read_text(encoding="utf-8") == MIGRATION_SQL.read_text(
        encoding="utf-8"
    )


def test_ride_economic_schema_locks_state_and_receipt_authority() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")

    required_fragments = (
        "exact_cal_base_units NUMERIC(20, 0) NOT NULL",
        "exact_tribute_base_units NUMERIC(20, 0) NOT NULL",
        "UNIQUE (ride_id, step_index)",
        "UNIQUE (ride_id, vault_id)",
        "UNIQUE (expected_receipt_pda)",
        "UNIQUE (completion_evidence_hash)",
        "idx_vault_completions_evidence_hash",
        "cannot confirm ride completions while a step is pending",
        "cannot reconcile ride projections while a step is pending",
        "exists:<pda> is not a transaction signature",
        "on_chain_tx = EXCLUDED.on_chain_tx",
        "confirmed_vault_completion_candidates",
        "get_confirmed_local_legend_candidates",
        "'confirmed_receipt_count', v_confirmed_receipt_count",
        "count(*)::BIGINT AS completion_count",
        "chain_confirmation_status = 'confirmed'",
    )
    missing = [fragment for fragment in required_fragments if fragment not in sql]

    assert not missing, "missing ride-economic schema contract:\n" + "\n".join(
        missing
    )


def test_chain_bound_columns_enforce_exact_unsigned_protocol_ranges() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")
    required_fragments = (
        "parser_version BIGINT NOT NULL",
        "parser_version <= 4294967295",
        "source_kind BETWEEN 0 AND 255",
        "total_tss <= 4294967295",
        "total_distance_m <= 4294967295",
        "total_vert_m <= 4294967295",
        "exact_cal_base_units <= 18446744073709551615",
        "climbs_crossed <= 65535",
        "exact_tribute_base_units NUMERIC(39, 0) NOT NULL",
        "exact_tribute_base_units <= 340282366920938463463374607431768211455",
        "vault_id NUMERIC(20, 0) NOT NULL",
        "vault_id <= 18446744073709551615",
        "completion_time_s BIGINT NOT NULL",
        "completion_time_s <= 4294967295",
        "ride economic integer field must contain unsigned decimal digits",
    )
    missing = [fragment for fragment in required_fragments if fragment not in sql]
    assert not missing, "missing protocol integer range:\n" + "\n".join(missing)


def test_plan_finality_and_deletion_survival_are_schema_invariants() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.ride_economic_plan_audits" in sql
    assert "completed_plan_evidence_mismatch" in sql
    assert "IF v_existing.state <> 'complete' THEN" in sql
    assert "ride_id UUID PRIMARY KEY REFERENCES public.rides" not in sql
    assert "user_id UUID NOT NULL REFERENCES public.users" not in sql


def test_service_role_uses_select_and_security_definer_rpcs_only() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")

    assert "GRANT SELECT ON public.ride_economic_plans TO service_role" in sql
    assert "GRANT SELECT ON public.ride_economic_completion_steps TO service_role" in sql
    assert "GRANT SELECT ON public.ride_economic_plan_audits TO service_role" in sql
    assert "GRANT SELECT, INSERT" not in sql
    assert "GRANT USAGE, SELECT ON SEQUENCE" not in sql
    assert "GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan" in sql
    assert (
        "GRANT EXECUTE ON FUNCTION public.get_confirmed_local_legend_candidates"
        in sql
    )


def test_reconciliation_clears_unverified_legacy_transaction_text() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")

    assert "on_chain_tx = EXCLUDED.on_chain_tx" in sql
    assert "COALESCE(EXCLUDED.on_chain_tx, target.on_chain_tx)" not in sql


def test_completion_reconciliation_does_not_create_a_second_leaderboard_authority() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")
    function_sql = sql.split(
        "CREATE OR REPLACE FUNCTION public.reconcile_confirmed_vault_completion",
        maxsplit=1,
    )[1].split("CREATE OR REPLACE FUNCTION", maxsplit=1)[0]

    assert "INSERT INTO public.vault_completions" in function_sql
    assert "update_vault_leaderboard" not in function_sql
    assert "vault_leaderboards" not in function_sql


def test_legacy_completion_rows_are_forced_out_of_legend_eligibility() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.enforce_vault_completion_chain_authority" in sql
    assert "NEW.validated := false" in sql
    assert "chain_confirmation_status <> 'confirmed'" in sql
