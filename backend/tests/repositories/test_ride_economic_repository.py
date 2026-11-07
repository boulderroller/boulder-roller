from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.repositories.ride_economic import (
    RideEconomicRepository,
    ThresholdReleaseAuthorityConflictError,
    is_authoritative_completion,
    is_authoritative_tribute,
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


class _RpcErrorRequest:
    def __init__(self, error: Exception):
        self.error = error

    def execute(self):
        raise self.error


class _RpcErrorClient:
    def __init__(self, error: Exception):
        self.error = error

    def rpc(self, _name, _params):
        return _RpcErrorRequest(self.error)


class _PostgrestLikeError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["BRR01", "BRR02", "BRR03", "BRR04", "BRR05", "BRR06", "BRR07"]
)
async def test_repository_classifies_immutable_release_conflict(code: str) -> None:
    repository = RideEconomicRepository(
        _RpcErrorClient(_PostgrestLikeError(code, "immutable conflict"))
    )

    with pytest.raises(ThresholdReleaseAuthorityConflictError) as captured:
        await repository.project_threshold_release_terminal(
            snapshot_id=UUID("11111111-1111-4111-8111-111111111111")
        )

    assert captured.value.code == code


@pytest.mark.asyncio
async def test_repository_keeps_missing_projection_retryable() -> None:
    error = _PostgrestLikeError("P0001", "indexed authority is incomplete")
    repository = RideEconomicRepository(_RpcErrorClient(error))

    with pytest.raises(_PostgrestLikeError) as captured:
        await repository.project_threshold_release_terminal(
            snapshot_id=UUID("11111111-1111-4111-8111-111111111111")
        )

    assert captured.value is error


@pytest.mark.asyncio
async def test_threshold_hold_and_release_repository_use_private_rpcs() -> None:
    client = _RpcClient({"snapshot_id": "snapshot-1"})
    repository = RideEconomicRepository(client)
    owner = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    ride_id = UUID("11111111-1111-4111-8111-111111111111")

    await repository.register_threshold_provisional_hold(
        hold={"ride_id": "ride-1", "hold_evidence": {"version": 1}}
    )
    await repository.record_threshold_provisional_hold_admission(
        ride_id=ride_id,
        admitted_at="2026-08-24T16:05:00+00:00",
        expected_attestation_pda="parent-attestation-pda",
    )
    await repository.claim_due_threshold_release_item(
        lease_owner=owner, lease_seconds=60
    )
    await repository.freeze_threshold_release_snapshot(
        snapshot={"batch_item_id": "item-1"}, steps=[], lease_owner=owner
    )
    await repository.claim_due_release_execution(
        lease_owner=owner, lease_seconds=60
    )

    assert client.calls == [
        (
            "register_reward_threshold_provisional_hold",
            {"p_hold": {"ride_id": "ride-1", "hold_evidence": {"version": 1}}},
        ),
        (
            "record_reward_threshold_provisional_hold_admission",
            {
                "p_ride_id": str(ride_id),
                "p_admitted_at": "2026-08-24T16:05:00+00:00",
                "p_ride_attestation_pda": "parent-attestation-pda",
            },
        ),
        (
            "claim_due_reward_threshold_release_item",
            {"p_lease_owner": str(owner), "p_lease_seconds": 60},
        ),
        (
            "freeze_reward_threshold_release_snapshot",
            {
                "p_snapshot": {"batch_item_id": "item-1"},
                "p_steps": [],
                "p_planner_lease_owner": str(owner),
            },
        ),
        (
            "claim_due_reward_threshold_release_execution",
            {"p_lease_owner": str(owner), "p_lease_seconds": 60},
        ),
    ]


@pytest.mark.asyncio
async def test_threshold_release_repository_cas_payloads_are_exact() -> None:
    client = _RpcClient({"state": "release_authority_confirmed"})
    repository = RideEconomicRepository(client)
    owner = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    snapshot_id = UUID("11111111-1111-4111-8111-111111111111")

    await repository.advance_release_execution(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        expected_state="planned",
        next_state="release_authority_confirmed",
        fields={"release_authority_tx_signature": "sig"},
    )
    await repository.confirm_release_step(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        step_index=2,
        expected_receipt_pda="pda",
        tx_signature="sig-2",
        confirmed_at="2026-08-24T16:00:00+00:00",
    )
    await repository.reconcile_release_completion(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        step_index=2,
    )
    await repository.mark_release_step_projected(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        step_index=2,
    )
    await repository.checkpoint_release_retry(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        error="retry",
        step_index=2,
        retry_delay_seconds=3,
    )

    assert [name for name, _ in client.calls] == [
        "advance_reward_threshold_release_execution",
        "confirm_reward_threshold_release_step",
        "reconcile_confirmed_reward_threshold_release_completion",
        "mark_reward_threshold_release_step_projected",
        "checkpoint_reward_threshold_release_retry",
    ]
    assert client.calls[0][1] == {
        "p_snapshot_id": str(snapshot_id),
        "p_lease_owner": str(owner),
        "p_expected_state": "planned",
        "p_next_state": "release_authority_confirmed",
        "p_fields": {"release_authority_tx_signature": "sig"},
    }


@pytest.mark.asyncio
async def test_threshold_release_repository_persists_terminal_review_evidence() -> None:
    client = _RpcClient({"state": "review"})
    repository = RideEconomicRepository(client)
    owner = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    item_id = UUID("22222222-2222-4222-8222-222222222222")
    snapshot_id = UUID("11111111-1111-4111-8111-111111111111")

    await repository.mark_threshold_release_item_terminal(
        batch_item_id=item_id,
        lease_owner=owner,
        disposition="not_counted",
        reason="below counted CAL floor",
        evidence={"version": 1, "exact_cal_base_units": 0},
    )
    await repository.mark_threshold_release_review(
        snapshot_id=snapshot_id,
        lease_owner=owner,
        reason="indexed authority mismatch",
        conflict_evidence={"version": 1, "field": "release_plan_hash"},
    )

    assert client.calls == [
        (
            "mark_reward_threshold_release_item_terminal",
            {
                "p_batch_item_id": str(item_id),
                "p_lease_owner": str(owner),
                "p_disposition": "not_counted",
                "p_reason": "below counted CAL floor",
                "p_evidence": {"version": 1, "exact_cal_base_units": 0},
            },
        ),
        (
            "mark_reward_threshold_release_review",
            {
                "p_snapshot_id": str(snapshot_id),
                "p_lease_owner": str(owner),
                "p_reason": "indexed authority mismatch",
                "p_conflict_evidence": {
                    "version": 1,
                    "field": "release_plan_hash",
                },
            },
        ),
    ]


def test_local_legend_candidates_exclude_legacy_and_placeholder_completions() -> None:
    legacy = {
        "chain_confirmation_status": "legacy_unverified",
        "on_chain_tx": "old-database-signature",
    }
    placeholder = {
        "chain_confirmation_status": "confirmed",
        "on_chain_tx": "exists:CompletionPda111",
        "completion_receipt_pda": None,
        "chain_confirmed_at": None,
    }
    receipt_confirmed = {
        "chain_confirmation_status": "confirmed",
        "on_chain_tx": None,
        "completion_receipt_pda": "CompletionPda111",
        "completion_evidence_hash": "\\x" + "ab" * 32,
        "chain_confirmed_at": "2026-07-13T13:00:00+00:00",
        "cal_tribute": 104,
    }
    missing_evidence = {
        **receipt_confirmed,
        "completion_evidence_hash": None,
    }

    assert is_authoritative_completion(legacy) is False
    assert is_authoritative_completion(placeholder) is False
    assert is_authoritative_completion(missing_evidence) is False
    assert is_authoritative_completion(receipt_confirmed) is True
    assert is_authoritative_tribute(receipt_confirmed) is False
    assert is_authoritative_tribute(
        {**receipt_confirmed, "completion_evidence_version": 2}
    ) is True
    assert is_authoritative_tribute(
        {**receipt_confirmed, "completion_evidence_version": 3}
    ) is True


@pytest.mark.asyncio
async def test_local_legend_aggregate_accepts_complete_server_totals() -> None:
    first_at = "2026-07-13T13:00:00+00:00"
    client = _RpcClient(
        {
            "authoritative": True,
            "confirmed_receipt_count": 10001,
            "wallet_count": 2,
            "candidates": [
                {
                    "wallet": "winner",
                    "completion_count": 5001,
                    "first_completed_at": first_at,
                },
                {
                    "wallet": "runner-up",
                    "completion_count": 5000,
                    "first_completed_at": first_at,
                },
            ],
        }
    )
    repository = RideEconomicRepository(client)

    candidates = await repository.list_confirmed_local_legend_candidates(
        vault_id=7,
        completed_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
        completed_before=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    assert [candidate["completion_count"] for candidate in candidates] == [5001, 5000]
    assert client.calls[0][0] == "get_confirmed_local_legend_candidates"


@pytest.mark.asyncio
async def test_local_legend_aggregate_rejects_truncated_payload() -> None:
    client = _RpcClient(
        {
            "authoritative": True,
            "confirmed_receipt_count": 10001,
            "wallet_count": 2,
            "candidates": [
                {
                    "wallet": "runner-up",
                    "completion_count": 5000,
                    "first_completed_at": "2026-07-13T13:00:00+00:00",
                }
            ],
        }
    )
    repository = RideEconomicRepository(client)

    with pytest.raises(RuntimeError, match="incomplete"):
        await repository.list_confirmed_local_legend_candidates(
            vault_id=7,
            completed_from=datetime(2026, 7, 1, tzinfo=timezone.utc),
            completed_before=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_trim_basis_passes_candidate_completion_windows() -> None:
    client = _RpcClient({"covered_completion_windows": []})
    repository = RideEconomicRepository(client)
    owner = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    ride_id = UUID("11111111-1111-4111-8111-111111111111")
    await repository.get_effort_trim_basis(
        ride_id=ride_id, user_id=owner, completion_spans_ms=[[30000, 121000]]
    )
    assert client.calls == [
        (
            "get_ride_effort_trim_basis",
            {
                "p_ride_id": str(ride_id),
                "p_user_id": str(owner),
                "p_completion_spans_ms": [[30000, 121000]],
            },
        )
    ]
