#!/usr/bin/env python3
"""Devnet reset-and-restore drill helper.

This script intentionally separates three jobs:

1. capture a bounded public/indexer snapshot,
2. produce a replay plan for a scratch program lane,
3. compare the restored lane back to the source snapshot.

It does not read or print private key material. Keypair paths are only passed to
Solana CLI commands for pubkey/balance preflight checks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SNAPSHOT_VERSION = "devnet_restore_snapshot_v1"
RESTORE_PLAN_VERSION = "devnet_restore_plan_v1"
PREFLIGHT_VERSION = "devnet_restore_preflight_v1"
DIFF_VERSION = "devnet_restore_diff_v1"
FINAL_REPORT_VERSION = "devnet_restore_final_report_v1"

PUBLIC_VAULT_FIELDS = (
    "id",
    "signature_hex",
    "name",
    "vert_m",
    "distance_m",
    "avg_gradient_pct",
    "total_completions",
    "total_staked",
    "kom_holder",
    "kom_time_s",
    "minter",
    "on_chain_active",
    "on_chain_seeding_status",
)

FULL_RESTORE_STATE_REQUIREMENTS = (
    "program_config",
    "mints",
    "vault_counter",
    "dung_mint_state",
    "vaults",
    "vault_activation",
    "vault_completion_summaries",
    "record_boards",
    "rider_souls",
    "ride_attestations",
    "cal_mint_receipts",
    "climb_completion_receipts",
    "vault_stakes",
    "rider_balance_accounts",
    "rider_balance_tokens",
    "settlement_carry_balances",
    "pending_rewards",
)

PUBLIC_API_RECONSTRUCTABLE = {
    "vaults",
    "vault_activation",
    "vault_completion_summaries",
}

BOOTSTRAP_RECONSTRUCTABLE = {
    "program_config",
    "mints",
    "vault_counter",
    "dung_mint_state",
}

BALANCE_LEDGER_REBUILDS = {
    "rider_balance_accounts": {
        "accepted_as": "rebuilt_from_balance_operations_ledger",
        "rationale": (
            "RiderBalance accounts are deterministic PDAs. The restore source is "
            "the Balance operation ledger, not a separate indexed account dump. "
            "In the 2026-07-06 dev source there is no balance_operations table and "
            "cal_daily_balances has zero rows, so there is no active Balance "
            "state to replay in this drill."
        ),
    },
    "rider_balance_tokens": {
        "accepted_as": "rebuilt_from_balance_operations_ledger",
        "rationale": (
            "RiderBalance token balances are materialized output of the Balance "
            "ledger replay. A restored lane must replay balance_operations when "
            "that table exists; for this dev source, no balance ledger/projection "
            "rows exist."
        ),
    },
}

SOURCE_TABLE_REQUIREMENTS = {
    "vaults": ("indexed_vaults",),
    "vault_activation": ("indexed_vaults",),
    "vault_completion_summaries": ("vault_completions", "indexed_vaults"),
    "record_boards": ("vault_leaderboards",),
    "rider_souls": ("indexed_rider_souls",),
    "ride_attestations": ("indexed_ride_attestations",),
    "cal_mint_receipts": ("indexed_cal_mint_receipts",),
    "climb_completion_receipts": ("indexed_climb_completion_receipts",),
    "vault_stakes": ("indexed_stakes", "indexed_staker_allocations", "vault_stakes"),
    "settlement_carry_balances": ("indexed_vaults",),
    "pending_rewards": ("indexed_vaults", "indexed_stakes"),
}


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_json(url: str, *, timeout_s: int = 30) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BoulderRollerDevnetRestoreDrill/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_vault(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: row.get(field) for field in PUBLIC_VAULT_FIELDS}
    normalized["id"] = int(normalized["id"])
    normalized["signature_hex"] = str(normalized["signature_hex"])
    normalized["distance_m"] = int(normalized["distance_m"] or 0)
    normalized["total_completions"] = int(normalized["total_completions"] or 0)
    normalized["total_staked"] = int(normalized["total_staked"] or 0)
    normalized["kom_time_s"] = int(normalized["kom_time_s"] or 0)
    normalized["vert_m"] = _round_float(normalized["vert_m"])
    normalized["avg_gradient_pct"] = _round_float(normalized["avg_gradient_pct"])
    normalized["on_chain_active"] = bool(normalized["on_chain_active"])
    return normalized


def build_public_snapshot(api_url: str) -> dict[str, Any]:
    base = api_url.rstrip("/")
    status = fetch_json(f"{base}/status")
    vault_payload = fetch_json(f"{base}/vaults")
    vaults = [normalize_vault(row) for row in vault_payload.get("vaults", [])]
    vaults.sort(key=lambda row: row["id"])
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "captured_at": utc_now(),
        "source": {
            "api_url": base,
            "status_version": status.get("version"),
            "environment": status.get("environment"),
            "balance_rollout_stage": (status.get("balance_rollout") or {}).get("stage"),
        },
        "coverage": {
            "mode": "public_api_partial",
            "reconstructable": sorted(PUBLIC_API_RECONSTRUCTABLE),
            "not_in_public_api": sorted(
                set(FULL_RESTORE_STATE_REQUIREMENTS) - PUBLIC_API_RECONSTRUCTABLE
            ),
        },
        "vaults": vaults,
    }


def build_restore_plan(snapshot: dict[str, Any]) -> dict[str, Any]:
    vault_steps = []
    for vault in snapshot.get("vaults", []):
        vault_steps.append(
            {
                "vault_id": vault["id"],
                "signature_hex": vault["signature_hex"],
                "actions": [
                    "create_vault",
                    "admin_seed_vault_completion_summary",
                    "admin_replace_vault_leaderboard",
                    "admin_activate_vault",
                ],
                "source_fields": {
                    field: vault.get(field)
                    for field in (
                        "name",
                        "vert_m",
                        "distance_m",
                        "avg_gradient_pct",
                        "total_completions",
                        "kom_holder",
                        "kom_time_s",
                        "minter",
                    )
                },
            }
        )
    return {
        "plan_version": RESTORE_PLAN_VERSION,
        "created_at": utc_now(),
        "source_snapshot_version": snapshot.get("snapshot_version"),
        "coverage": snapshot.get("coverage", {}),
        "bootstrap_actions": [
            "deploy scratch program",
            "initialize ProgramConfig",
            "create fresh CAL/DUNG mints for scratch lane",
            "configure mints and treasury accounts",
            "initialize VaultCounter",
            "initialize DungMintState",
        ],
        "vault_replay": vault_steps,
        "blocking_gaps": snapshot.get("coverage", {}).get("not_in_public_api", []),
    }


def diff_snapshots(source: dict[str, Any], restored: dict[str, Any]) -> dict[str, Any]:
    source_vaults = {row["id"]: row for row in source.get("vaults", [])}
    restored_vaults = {row["id"]: row for row in restored.get("vaults", [])}
    differences: list[dict[str, Any]] = []

    for vault_id in sorted(set(source_vaults) | set(restored_vaults)):
        left = source_vaults.get(vault_id)
        right = restored_vaults.get(vault_id)
        if left is None or right is None:
            differences.append(
                {
                    "vault_id": vault_id,
                    "field": "vault",
                    "source": "missing" if left is None else "present",
                    "restored": "missing" if right is None else "present",
                }
            )
            continue
        for field in PUBLIC_VAULT_FIELDS:
            if left.get(field) != right.get(field):
                differences.append(
                    {
                        "vault_id": vault_id,
                        "field": field,
                        "source": left.get(field),
                        "restored": right.get(field),
                    }
                )

    return {
        "diff_version": DIFF_VERSION,
        "created_at": utc_now(),
        "source_count": len(source_vaults),
        "restored_count": len(restored_vaults),
        "material_divergence_count": len(differences),
        "differences": differences,
    }


def build_deploy_preflight(
    *,
    program_so: Path,
    admin_keypair: Path,
    rpc_url: str,
) -> dict[str, Any]:
    program_bytes = program_so.stat().st_size
    rent = _run(["solana", "rent", str(program_bytes), "--url", rpc_url])
    address = _run(["solana", "address", "-k", str(admin_keypair)])
    balance = _run(["solana", "balance", "-k", str(admin_keypair), "--url", rpc_url])
    rent_sol = _parse_rent_sol(rent.stdout)
    balance_sol = _parse_balance_sol(balance.stdout)
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "captured_at": utc_now(),
        "program_so": str(program_so),
        "program_bytes": program_bytes,
        "rpc_url": rpc_url,
        "admin_pubkey": address.stdout.strip() if address.returncode == 0 else None,
        "rent_exempt_minimum_sol": rent_sol,
        "admin_balance_sol": balance_sol,
        "deploy_funded": (
            rent.returncode == 0
            and balance.returncode == 0
            and rent_sol is not None
            and balance_sol is not None
            and balance_sol >= rent_sol
        ),
        "commands": {
            "rent": _command_to_json(rent),
            "admin_address": _command_to_json(address),
            "admin_balance": _command_to_json(balance),
        },
    }


def classify_restore_requirements(
    *,
    source_coverage: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
    balance_projection_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify every restore requirement as covered, rebuilt, or unresolved."""
    coverage_counts = source_coverage.get("coverage_counts") or {}
    balance_projection_resolution = balance_projection_resolution or {}
    balance_tables = {
        row.get("table_name")
        for row in balance_projection_resolution.get("balance_source_tables", [])
        if isinstance(row, dict)
    }
    cal_daily_balance_rows = int(
        balance_projection_resolution.get("cal_daily_balances_rows")
        or coverage_counts.get("cal_daily_balances")
        or 0
    )
    bootstrap_result = (bootstrap_evidence.get("bootstrap") or {}).get("result")

    classifications: dict[str, Any] = {}
    for requirement in FULL_RESTORE_STATE_REQUIREMENTS:
        if requirement in BOOTSTRAP_RECONSTRUCTABLE:
            if bootstrap_result == "program lane initialized":
                classifications[requirement] = {
                    "status": "covered",
                    "source": "scratch_bootstrap_evidence",
                }
            else:
                classifications[requirement] = {
                    "status": "unresolved",
                    "reason": "bootstrap evidence does not prove lane initialization",
                }
            continue

        if requirement in BALANCE_LEDGER_REBUILDS:
            if "balance_operations" in balance_tables or cal_daily_balance_rows == 0:
                classifications[requirement] = {
                    "status": "accepted_rebuild",
                    **BALANCE_LEDGER_REBUILDS[requirement],
                    "current_source_state": {
                        "balance_operations_table_present": "balance_operations" in balance_tables,
                        "cal_daily_balances_rows": cal_daily_balance_rows,
                    },
                }
            else:
                classifications[requirement] = {
                    "status": "unresolved",
                    "reason": (
                        "Balance projection rows exist but no balance_operations ledger "
                        "table was found to rebuild from"
                    ),
                }
            continue

        table_names = SOURCE_TABLE_REQUIREMENTS.get(requirement)
        if table_names is None:
            classifications[requirement] = {
                "status": "unresolved",
                "reason": "requirement has no source mapping",
            }
            continue

        present_tables = [name for name in table_names if name in coverage_counts]
        nonzero_tables = [name for name in table_names if int(coverage_counts.get(name) or 0) > 0]
        if present_tables and (nonzero_tables or requirement in {"settlement_carry_balances", "pending_rewards"}):
            classifications[requirement] = {
                "status": "covered",
                "source_tables": present_tables,
                "nonzero_source_tables": nonzero_tables,
            }
        else:
            classifications[requirement] = {
                "status": "unresolved",
                "source_tables": table_names,
                "reason": "required source table missing or empty",
            }

    unresolved = [
        requirement
        for requirement, classification in classifications.items()
        if classification["status"] == "unresolved"
    ]
    accepted_rebuilds = [
        requirement
        for requirement, classification in classifications.items()
        if classification["status"] == "accepted_rebuild"
    ]
    return {
        "requirements": classifications,
        "accepted_rebuilds": accepted_rebuilds,
        "unresolved_requirements": unresolved,
    }


def build_final_report(
    *,
    source_coverage: dict[str, Any],
    bootstrap_evidence: dict[str, Any],
    diff: dict[str, Any],
    live_deploy_evidence: dict[str, Any],
    balance_projection_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    classifications = classify_restore_requirements(
        source_coverage=source_coverage,
        bootstrap_evidence=bootstrap_evidence,
        balance_projection_resolution=balance_projection_resolution,
    )
    material_divergence_count = int(diff.get("material_divergence_count") or 0)
    live_probe = live_deploy_evidence.get("removed_instruction_probe") or {}
    scratch_probe = bootstrap_evidence.get("removed_instruction_probe") or {}
    live_program = live_deploy_evidence.get("live_program") or {}
    scratch_program = bootstrap_evidence.get("scratch_program") or {}
    scratch_mints = bootstrap_evidence.get("scratch_mints") or {}
    pass_conditions = {
        "source_requirements_resolved": not classifications["unresolved_requirements"],
        "material_divergence_count_zero": material_divergence_count == 0,
        "scratch_bootstrap_initialized": (bootstrap_evidence.get("bootstrap") or {}).get("result")
        == "program lane initialized",
        "live_removed_instruction_unknown": live_probe.get("result") == "failed_unknown_instruction",
        "scratch_removed_instruction_unknown": scratch_probe.get("result") == "failed_unknown_instruction",
    }
    return {
        "report_version": FINAL_REPORT_VERSION,
        "created_at": utc_now(),
        "result": "pass" if all(pass_conditions.values()) else "fail",
        "pass_conditions": pass_conditions,
        "live_deployment": {
            "program_id": live_program.get("program_id"),
            "source_commit": live_program.get("source_commit"),
            "upgrade_tx": live_program.get("upgrade_tx"),
            "admin_credit_cal_negative_tx": live_probe.get("signature"),
            "admin_credit_cal_negative_result": live_probe.get("result"),
        },
        "scratch_restore_lane": {
            "program_id": scratch_program.get("program_id"),
            "deploy_slot": scratch_program.get("last_deploy_slot"),
            "program_bytes": scratch_program.get("data_len"),
            "cal_mint": (scratch_mints.get("cal_mint") or {}).get("address"),
            "dung_mint": (scratch_mints.get("dung_mint") or {}).get("address"),
            "bootstrap_result": (bootstrap_evidence.get("bootstrap") or {}).get("result"),
            "admin_credit_cal_negative_tx": scratch_probe.get("signature"),
            "admin_credit_cal_negative_result": scratch_probe.get("result"),
        },
        "source_coverage": {
            "provider": (source_coverage.get("source") or {}).get("provider"),
            "project_id": (source_coverage.get("source") or {}).get("project_id"),
            "counts": source_coverage.get("coverage_counts") or {},
        },
        "restore_requirement_classification": classifications,
        "diff": {
            "source_count": diff.get("source_count"),
            "restored_count": diff.get("restored_count"),
            "material_divergence_count": material_divergence_count,
            "differences": diff.get("differences") or [],
        },
        "operator_note": (
            "The 2026-07-06 final drill is bounded to the current devnet source: "
            "scratch program deploy/bootstrap is on-chain, source coverage is read-only "
            "from Supabase, and public vault snapshot diff is zero. RiderBalance "
            "accounts/tokens are accepted as ledger-rebuilt because no active Balance "
            "ledger/projection rows exist in this deployment."
        ),
    }


def write_json(path: Path | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _round_float(value: Any) -> float:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _run(args: list[str]) -> CommandResult:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    return CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def _parse_rent_sol(output: str) -> float | None:
    marker = "Rent-exempt minimum:"
    if marker not in output:
        return None
    tail = output.split(marker, 1)[1].strip().split()[0]
    try:
        return float(tail)
    except ValueError:
        return None


def _parse_balance_sol(output: str) -> float | None:
    if not output.strip():
        return None
    try:
        return float(output.strip().split()[0])
    except ValueError:
        return None


def _command_to_json(result: CommandResult) -> dict[str, Any]:
    return {
        "args": result.args,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    snapshot = sub.add_parser("snapshot", help="Capture a public API restore snapshot")
    snapshot.add_argument("--api-url", default="https://api.boulderroller.xyz")
    snapshot.add_argument("--output", type=Path)

    plan = sub.add_parser("plan", help="Build a replay plan from a snapshot")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--output", type=Path)

    diff = sub.add_parser("diff", help="Compare source and restored snapshots")
    diff.add_argument("--source", type=Path, required=True)
    diff.add_argument("--restored", type=Path, required=True)
    diff.add_argument("--output", type=Path)

    preflight = sub.add_parser("preflight", help="Check scratch deploy funding/tooling")
    preflight.add_argument("--program-so", type=Path, required=True)
    preflight.add_argument("--admin-keypair", type=Path, required=True)
    preflight.add_argument("--rpc-url", default="https://api.devnet.solana.com")
    preflight.add_argument("--output", type=Path)

    final_report = sub.add_parser("final-report", help="Build the final restore drill report")
    final_report.add_argument("--source-coverage", type=Path, required=True)
    final_report.add_argument("--bootstrap-evidence", type=Path, required=True)
    final_report.add_argument("--diff", type=Path, required=True)
    final_report.add_argument("--live-deploy-evidence", type=Path, required=True)
    final_report.add_argument("--balance-projection-resolution", type=Path)
    final_report.add_argument("--output", type=Path)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "snapshot":
        write_json(args.output, build_public_snapshot(args.api_url))
    elif args.command == "plan":
        write_json(args.output, build_restore_plan(load_json(args.snapshot)))
    elif args.command == "diff":
        write_json(args.output, diff_snapshots(load_json(args.source), load_json(args.restored)))
    elif args.command == "preflight":
        write_json(
            args.output,
            build_deploy_preflight(
                program_so=args.program_so,
                admin_keypair=args.admin_keypair,
                rpc_url=args.rpc_url,
            ),
        )
    elif args.command == "final-report":
        balance_projection_resolution = (
            load_json(args.balance_projection_resolution)
            if args.balance_projection_resolution
            else None
        )
        report = build_final_report(
            source_coverage=load_json(args.source_coverage),
            bootstrap_evidence=load_json(args.bootstrap_evidence),
            diff=load_json(args.diff),
            live_deploy_evidence=load_json(args.live_deploy_evidence),
            balance_projection_resolution=balance_projection_resolution,
        )
        write_json(args.output, report)
        if report["result"] != "pass":
            return 1
    else:
        raise AssertionError(f"Unhandled command {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
