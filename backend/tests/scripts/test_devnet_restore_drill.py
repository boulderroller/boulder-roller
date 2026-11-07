from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "devnet_restore_drill.py"
SPEC = importlib.util.spec_from_file_location("devnet_restore_drill", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
drill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = drill
SPEC.loader.exec_module(drill)


def _snapshot(vaults: list[dict]) -> dict:
    return {
        "snapshot_version": drill.SNAPSHOT_VERSION,
        "coverage": {
            "mode": "public_api_partial",
            "not_in_public_api": ["ride_attestations", "vault_stakes"],
        },
        "vaults": [drill.normalize_vault(row) for row in vaults],
    }


def _vault(**overrides: object) -> dict:
    row = {
        "id": 7,
        "signature_hex": "a" * 128,
        "name": "Smoke Climb",
        "vert_m": 123.456789,
        "distance_m": 1234,
        "avg_gradient_pct": 10.004,
        "total_completions": 2,
        "total_staked": 0,
        "kom_holder": "Wallet111111111111111111111111111111111",
        "kom_time_s": 2275,
        "minter": "Wallet111111111111111111111111111111111",
        "on_chain_active": True,
        "on_chain_seeding_status": "active",
    }
    row.update(overrides)
    return row


def _source_coverage() -> dict:
    return {
        "source": {
            "provider": "Supabase MCP read-only query",
            "project_id": "qzkqjevawthyboymqrle",
        },
        "coverage_counts": {
            "indexed_vaults": 33,
            "vault_completions": 54,
            "vault_leaderboards": 18,
            "indexed_rider_souls": 11,
            "indexed_ride_attestations": 21,
            "indexed_cal_mint_receipts": 12,
            "indexed_climb_completion_receipts": 8,
            "indexed_stakes": 22,
            "indexed_staker_allocations": 10,
            "vault_stakes": 23,
            "cal_daily_balances": 0,
        },
    }


def _bootstrap_evidence() -> dict:
    return {
        "scratch_program": {"program_id": "Scratch111111111111111111111111111111111"},
        "scratch_mints": {
            "cal_mint": {"address": "Cal1111111111111111111111111111111111111"},
            "dung_mint": {"address": "Dung11111111111111111111111111111111111"},
        },
        "bootstrap": {"result": "program lane initialized"},
        "removed_instruction_probe": {
            "signature": "ScratchProbeTx",
            "result": "failed_unknown_instruction",
        },
    }


def _live_deploy_evidence() -> dict:
    return {
        "live_program": {
            "program_id": "Live1111111111111111111111111111111111111",
            "source_commit": "3100db2a60592cf4d70ff2c85624d69845ac8314",
            "upgrade_tx": "LiveDeployTx",
        },
        "removed_instruction_probe": {
            "signature": "LiveProbeTx",
            "result": "failed_unknown_instruction",
        },
    }


def test_normalize_vault_stabilizes_public_api_shape() -> None:
    normalized = drill.normalize_vault(_vault(vert_m="123.4567894", total_staked=None))

    assert normalized["id"] == 7
    assert normalized["signature_hex"] == "a" * 128
    assert normalized["vert_m"] == 123.456789
    assert normalized["total_staked"] == 0
    assert normalized["on_chain_active"] is True


def test_restore_plan_names_public_api_gaps() -> None:
    snapshot = _snapshot([_vault()])

    plan = drill.build_restore_plan(snapshot)

    assert plan["plan_version"] == drill.RESTORE_PLAN_VERSION
    assert plan["vault_replay"][0]["actions"] == [
        "create_vault",
        "admin_seed_vault_completion_summary",
        "admin_replace_vault_leaderboard",
        "admin_activate_vault",
    ]
    assert "ride_attestations" in plan["blocking_gaps"]
    assert "vault_stakes" in plan["blocking_gaps"]


def test_diff_snapshots_reports_zero_material_divergence_for_identical_vaults() -> None:
    source = _snapshot([_vault()])
    restored = _snapshot([_vault()])

    diff = drill.diff_snapshots(source, restored)

    assert diff["material_divergence_count"] == 0
    assert diff["differences"] == []


def test_diff_snapshots_reports_field_divergence() -> None:
    source = _snapshot([_vault()])
    restored = _snapshot([_vault(total_completions=3)])

    diff = drill.diff_snapshots(source, restored)

    assert diff["material_divergence_count"] == 1
    assert diff["differences"][0] == {
        "vault_id": 7,
        "field": "total_completions",
        "source": 2,
        "restored": 3,
    }


def test_classify_restore_requirements_accepts_empty_balance_state_as_ledger_rebuilt() -> None:
    classification = drill.classify_restore_requirements(
        source_coverage=_source_coverage(),
        bootstrap_evidence=_bootstrap_evidence(),
        balance_projection_resolution={
            "balance_source_tables": [
                {"table_schema": "public", "table_name": "cal_daily_balances"}
            ],
            "cal_daily_balances_rows": 0,
        },
    )

    assert classification["unresolved_requirements"] == []
    assert classification["requirements"]["rider_balance_accounts"]["status"] == "accepted_rebuild"
    assert classification["requirements"]["rider_balance_tokens"]["current_source_state"] == {
        "balance_operations_table_present": False,
        "cal_daily_balances_rows": 0,
    }


def test_classify_restore_requirements_blocks_balance_projection_without_ledger() -> None:
    source = _source_coverage()
    source["coverage_counts"]["cal_daily_balances"] = 3

    classification = drill.classify_restore_requirements(
        source_coverage=source,
        bootstrap_evidence=_bootstrap_evidence(),
        balance_projection_resolution={
            "balance_source_tables": [
                {"table_schema": "public", "table_name": "cal_daily_balances"}
            ],
            "cal_daily_balances_rows": 3,
        },
    )

    assert "rider_balance_accounts" in classification["unresolved_requirements"]
    assert "rider_balance_tokens" in classification["unresolved_requirements"]


def test_final_report_passes_only_when_all_evidence_conditions_hold() -> None:
    diff = {
        "source_count": 33,
        "restored_count": 33,
        "material_divergence_count": 0,
        "differences": [],
    }

    report = drill.build_final_report(
        source_coverage=_source_coverage(),
        bootstrap_evidence=_bootstrap_evidence(),
        diff=diff,
        live_deploy_evidence=_live_deploy_evidence(),
        balance_projection_resolution={"cal_daily_balances_rows": 0},
    )

    assert report["result"] == "pass"
    assert report["pass_conditions"]["source_requirements_resolved"] is True
    assert report["restore_requirement_classification"]["accepted_rebuilds"] == [
        "rider_balance_accounts",
        "rider_balance_tokens",
    ]


def test_final_report_fails_with_material_divergence() -> None:
    report = drill.build_final_report(
        source_coverage=_source_coverage(),
        bootstrap_evidence=_bootstrap_evidence(),
        diff={
            "source_count": 33,
            "restored_count": 33,
            "material_divergence_count": 1,
            "differences": [{"vault_id": 7, "field": "total_completions"}],
        },
        live_deploy_evidence=_live_deploy_evidence(),
        balance_projection_resolution={"cal_daily_balances_rows": 0},
    )

    assert report["result"] == "fail"
    assert report["pass_conditions"]["material_divergence_count_zero"] is False
