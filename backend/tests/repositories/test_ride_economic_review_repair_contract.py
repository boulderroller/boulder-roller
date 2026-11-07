from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.repositories.ride_economic import RideEconomicRepository


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SQL = BACKEND_ROOT / "sql" / "115_ride_economic_review_repair.sql"
MIGRATION_SQL = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260713_122_ride_economic_review_repair.sql"
)


class _RpcRequest:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _RpcClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return _RpcRequest(self.data)


def test_review_repair_sql_mirror_and_security_contract() -> None:
    sql = SOURCE_SQL.read_text(encoding="utf-8")
    assert sql == MIGRATION_SQL.read_text(encoding="utf-8")

    required_fragments = (
        "CREATE TABLE IF NOT EXISTS public.ride_economic_reviews",
        "CREATE TABLE IF NOT EXISTS public.ride_economic_review_resolutions",
        "UNIQUE (ride_id, review_version)",
        "request_id UUID PRIMARY KEY",
        "CHECK (outcome IN ('reconcile', 'resume', 'reject'))",
        "ride_economic_review_resolutions_liability_length",
        "length(liability_disposition) <= 2000",
        "ride_economic_review_resolutions_effects_length",
        "length(effects_disposition) <= 2000",
        "p_expected_review_version BIGINT",
        "p_request_id UUID",
        "p_actor_id UUID",
        "p_outcome TEXT",
        "p_selected_checkpoint TEXT",
        "IF v_outcome IS NULL\n       OR v_outcome NOT IN",
        "SET search_path = ''",
        "ride economic review request_id payload conflict",
        "ride economic review already resolved",
        "resume checkpoint is not proven safe by finalized chain evidence",
        "terminal rejection requires an explicit liability disposition",
        "terminal rejection requires an explicit effects disposition",
        "state NOT IN ('complete', 'review', 'rejected')",
        "GRANT SELECT ON public.ride_economic_reviews TO service_role",
        "GRANT SELECT ON public.ride_economic_review_resolutions TO service_role",
        "GRANT EXECUTE ON FUNCTION public.resolve_ride_economic_review",
        "REVOKE ALL ON public.ride_economic_reviews FROM service_role",
        "REVOKE ALL ON public.ride_economic_review_resolutions FROM service_role",
    )
    missing = [fragment for fragment in required_fragments if fragment not in sql]
    assert not missing, "missing ride review repair contract:\n" + "\n".join(missing)

    assert "GRANT INSERT" not in sql
    assert "GRANT UPDATE" not in sql
    assert "GRANT DELETE" not in sql

    for function_name in (
        "enter_ride_economic_review",
        "mark_ride_economic_review",
        "validate_ride_economic_chain_evidence",
        "resolve_ride_economic_review",
        "get_ride_economic_review",
    ):
        assert (
            sql.count(f"CREATE OR REPLACE FUNCTION public.{function_name}(") == 1
        ), f"duplicate or missing definition: {function_name}"


@pytest.mark.asyncio
async def test_repository_marks_review_with_structured_conflict_evidence() -> None:
    client = _RpcClient({"state": "review", "review_version": 2})
    repository = RideEconomicRepository(client)
    ride_id = UUID("10000000-0000-0000-0000-000000000001")
    lease_owner = UUID("20000000-0000-0000-0000-000000000001")
    conflict_evidence = {
        "version": 1,
        "kind": "pda_mismatch",
        "operation": "cal",
        "message": "account data conflicts with the frozen receipt",
        "observed_at": "2026-07-13T20:00:00+00:00",
    }

    result = await repository.mark_review(
        ride_id=ride_id,
        lease_owner=lease_owner,
        reason="pda_mismatch",
        actor="service:ride-economic-coordinator",
        conflict_evidence=conflict_evidence,
    )

    assert result["review_version"] == 2
    assert client.calls == [
        (
            "mark_ride_economic_review",
            {
                "p_ride_id": str(ride_id),
                "p_lease_owner": str(lease_owner),
                "p_reason": "pda_mismatch",
                "p_actor": "service:ride-economic-coordinator",
                "p_conflict_evidence": conflict_evidence,
            },
        )
    ]


@pytest.mark.asyncio
async def test_repository_resolution_uses_one_exact_fenced_rpc() -> None:
    client = _RpcClient(
        {
            "request_id": "30000000-0000-0000-0000-000000000001",
            "outcome": "resume",
            "result_state": "attestation_confirmed",
            "replayed": False,
        }
    )
    repository = RideEconomicRepository(client)
    ride_id = UUID("10000000-0000-0000-0000-000000000001")
    request_id = UUID("30000000-0000-0000-0000-000000000001")
    actor_id = UUID("40000000-0000-0000-0000-000000000001")
    evidence = {
        "version": 1,
        "commitment": "finalized",
        "cluster": "devnet",
        "finalized_slot": "1234",
        "verified_at": "2026-07-13T20:00:00+00:00",
        "attestation": {},
        "completions": [],
        "cal": {},
    }

    result = await repository.resolve_review(
        ride_id=ride_id,
        expected_review_version=3,
        request_id=request_id,
        actor_id=actor_id,
        outcome="resume",
        selected_checkpoint="attestation_confirmed",
        reason="verified finalized account state",
        chain_evidence=evidence,
        liability_disposition=None,
        effects_disposition=None,
    )

    assert result["result_state"] == "attestation_confirmed"
    assert client.calls == [
        (
            "resolve_ride_economic_review",
            {
                "p_ride_id": str(ride_id),
                "p_expected_review_version": 3,
                "p_request_id": str(request_id),
                "p_actor_id": str(actor_id),
                "p_outcome": "resume",
                "p_selected_checkpoint": "attestation_confirmed",
                "p_reason": "verified finalized account state",
                "p_chain_evidence": evidence,
                "p_liability_disposition": None,
                "p_effects_disposition": None,
            },
        )
    ]


def test_recovery_source_excludes_unresolved_and_terminal_review_states() -> None:
    source = (
        BACKEND_ROOT / "app" / "repositories" / "ride_economic.py"
    ).read_text(encoding="utf-8")
    assert '.not_.in_("state", ["complete", "review", "rejected"])' in source
