"""Focused contracts for the 2026-08-25 Threshold-hold review findings."""

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND_ROOT / "sql" / "155_threshold_provisional_hold.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_h1_hold_and_zero_parent_freeze_share_one_transaction() -> None:
    sql = _sql()
    assert "p_threshold_hold JSONB" in sql
    assert "public.register_reward_threshold_provisional_hold" in sql
    assert "Threshold hold policy requires atomic hold evidence" in sql
    assert "Threshold hold evidence does not bind zero parent plan" in sql
    assert "Frozen zero parent does not match Threshold hold evidence" in sql


def test_h2_sub_display_cal_can_reach_terminal_projection() -> None:
    sql = _sql()
    terminal = sql[sql.index("CREATE OR REPLACE FUNCTION public.project_reward_threshold_release_terminal"):]
    assert "v_display_cal NOT BETWEEN 0 AND 2147483647" in terminal


def test_h3_frozen_release_week_is_checked_across_projection_receipts_and_flow() -> None:
    sql = _sql()
    assert "release_settlement_week" in sql
    assert "v_receipt.credited_settlement_week IS DISTINCT FROM\n            v_indexed_release.release_settlement_week" in sql
    assert "v_flow.credited_settlement_week IS DISTINCT FROM\n            v_indexed_release.release_settlement_week" in sql


def test_h4_operator_review_reentry_preserves_confirmed_receipts() -> None:
    sql = _sql()
    assert "review_from_state" in sql
    assert "CREATE OR REPLACE FUNCTION public.repair_reward_threshold_release_execution" in sql
    assert "cal_confirmed" in sql
    repair = sql[
        sql.index("CREATE OR REPLACE FUNCTION public.repair_reward_threshold_release_execution"):
        sql.index("CREATE OR REPLACE FUNCTION public.project_reward_threshold_release_terminal")
    ]
    assert "AND state = 'review'" in repair
    assert "AND chain_confirmed_at IS NULL" in repair


def test_h5_lifecycle_reader_ops_view_and_review_exits_exist() -> None:
    sql = _sql()
    assert "CREATE OR REPLACE FUNCTION public.resolve_reward_threshold_release_lifecycle" in sql
    assert "CREATE OR REPLACE VIEW public.reward_threshold_release_ops" in sql
    assert "repair_reward_threshold_release_item_review" in sql
    for status in ("held", "lapsed", "planning", "not_counted", "under_review", "releasing", "released"):
        assert f"'{status}'" in sql


def test_h8_only_earliest_init_or_establishment_materializes_a_release_batch() -> None:
    sql = _sql()
    trigger = sql[sql.index("CREATE OR REPLACE FUNCTION public.bind_reward_threshold_release_batch_on_seal"):]
    assert "NEW.promotion_kind IN ('initialization', 'establishment')" in trigger
    assert "earlier.promotion_kind IN ('initialization', 'establishment')" in trigger
    assert "IF NOT EXISTS" in trigger


def test_h9_reprocessing_preserves_existing_raw_power_pair() -> None:
    sql = _sql()
    guard = sql[sql.index("CREATE OR REPLACE FUNCTION public.enforce_ride_threshold_release_power_inputs"):]
    assert "NEW.normalized_power_raw_w := OLD.normalized_power_raw_w" in guard
    assert "Threshold release power inputs are immutable" not in guard


def test_h10_due_execution_index_matches_complete_terminal_recovery_query() -> None:
    sql = _sql()
    predicate = "state <> 'review' AND (state <> 'complete' OR terminal_projected_at IS NULL)"
    assert predicate in " ".join(sql.split())


def test_h12_runtime_gate_and_canonical_number_are_ci_required() -> None:
    workflow = (BACKEND_ROOT.parent / ".github" / "workflows" / "backend-ci.yml").read_text(encoding="utf-8")
    runtime = (BACKEND_ROOT / "tests" / "services" / "test_settlement_clock_postgres_runtime.py").read_text(encoding="utf-8")
    pg_suite = (BACKEND_ROOT / "tests" / "repositories" / "test_threshold_provisional_hold_postgres_runtime.py").read_text(encoding="utf-8")
    assert 'REQUIRE_PG_RUNTIME: "1"' in workflow
    assert "REQUIRE_PG_RUNTIME" in runtime
    assert "155_threshold_provisional_hold.sql" in pg_suite
