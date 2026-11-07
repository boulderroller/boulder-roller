from __future__ import annotations

import json
from pathlib import Path

from ._alignment_helpers import anchor_program_source


ROOT = Path(__file__).resolve().parents[4]
INDEXER = ROOT / "indexer" / "src" / "modes" / "replay.ts"
CANONICAL_SQL = ROOT / "backend" / "sql" / "120_exact_credited_settlement_flow.sql"
SUPABASE_SQL = (
    ROOT
    / "backend"
    / "supabase"
    / "migrations"
    / "20260714_128_exact_credited_settlement_flow.sql"
)
IDL_PATHS = (
    ROOT / "protocol" / "anchor" / "idl" / "boulder_rollers.json",
    ROOT / "backend" / "idl" / "boulder_rollers.json",
    ROOT / "web" / "portal" / "public" / "idl" / "boulder_rollers.json",
)


def _event(idl_path: Path, name: str) -> dict:
    events = json.loads(idl_path.read_text(encoding="utf-8"))["events"]
    return next(event for event in events if event["name"] == name)


def test_chain_emits_immutable_exact_completion_flow_evidence() -> None:
    source = anchor_program_source()

    assert "pub struct ClimbCompletionFlowAssigned" in source
    assert "pub struct ClimbCompletionFlowAssignedV2" in source
    assert "let credited_settlement_week = vault.open_settlement_week;" in source
    assert "emit!(ClimbCompletionFlowAssignedV2 {" in source
    for field in (
        "vault_id",
        "ride_attestation",
        "completion_evidence_hash",
        "credited_settlement_week",
        "cal_tributed",
        "timestamp",
    ):
        assert field in source.split("pub struct ClimbCompletionFlowAssignedV2", 1)[1]

    for idl_path in IDL_PATHS:
        event = _event(idl_path, "ClimbCompletionFlowAssignedV2")
        assert [field["name"] for field in event["fields"]] == [
            "evidenceVersion",
            "vaultId",
            "rideAttestation",
            "completionEvidenceHash",
            "creditedSettlementWeek",
            "calTributed",
            "timestamp",
        ]


def test_indexer_projects_exact_flow_by_evidence_hash() -> None:
    source = INDEXER.read_text(encoding="utf-8")

    assert "export function decodeClimbCompletionFlow" in source
    assert "ClimbCompletionFlowAssignedV2: { evidenceVersion: 2 }" in source
    assert "INSERT INTO indexed_climb_completion_flows" in source
    assert "completion_evidence_hash" in source
    assert "credited_settlement_week" in source
    assert "if (shouldProjectCanonicalEvent(transactionError))" in source
    assert "const transactionError = tx.meta?.err ?? err;" in source
    assert "commitment: 'finalized'" in source
    assert "const connection = new Connection(config.rpcUrl, 'finalized')" in source
    assert "runStage1ProgramStream(stage1Connection(), processTransaction)" in source
    shared=(INDEXER.parents[1]/"stage1-program-stream.ts").read_text(encoding="utf-8")
    assert "new Connection(config.rpcUrl, 'finalized')" in shared
    assert "disableRetryOnRateLimit:true" not in shared


def test_forward_migrations_match_and_fail_closed_without_flow_evidence() -> None:
    assert CANONICAL_SQL.is_file()
    assert SUPABASE_SQL.is_file()
    canonical = CANONICAL_SQL.read_bytes()
    assert canonical == SUPABASE_SQL.read_bytes()

    source = canonical.decode("utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.indexed_climb_completion_flows" in source
    assert "completion_evidence_hash BYTEA NOT NULL" in source
    assert "vault_id NUMERIC(20, 0) NOT NULL" in source
    assert "credited_settlement_week NUMERIC(20, 0) NOT NULL" in source
    assert "ALTER COLUMN vault_id TYPE NUMERIC(20, 0)" in source
    refresh = source.split(
        "CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at", 1
    )[1].split(
        "CREATE OR REPLACE FUNCTION public.br_sync_epoch_distribution_finalized_at", 1
    )[0]
    assert "vc.completion_evidence_hash" in refresh
    assert "flow.credited_settlement_week" in refresh
    assert "vc.settlement_week" not in refresh
    assert "vc.completed_at" not in refresh
    assert "COUNT(flow.credited_settlement_week) = COUNT(*)" in refresh
    assert "FILTER (WHERE flow.cal_tributed > 0)" in refresh
    assert "PERFORM public.br_refresh_ride_finalized_at(v_activity_id);" in source
    assert "AFTER INSERT OR UPDATE OR DELETE ON public.indexed_epoch_distributions" in source
    assert "UPDATE public.indexed_climb_completion_flows" not in source
    assert "INSERT INTO public.indexed_climb_completion_flows" not in source
