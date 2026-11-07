from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.account_deletion import (
    AccountDeletionAuthorityReader,
    AccountDeletionRequest,
    AccountDeletionValueSnapshot,
    DeletionAssetBalance,
    DeletionBlockerCode,
    DeletionExecutionStatus,
    evaluate_account_deletion_preflight,
    execute_account_deletion,
)


def _request(**overrides: object) -> AccountDeletionRequest:
    request = AccountDeletionRequest(
        request_id=str(uuid4()),
        user_id=str(uuid4()),
        wallet="RiderWallet1111111111111111111111111111111",
        status="queued",
        unuploaded_rides_acknowledged=True,
        storage_paths=("rides/user/ride.fit", "avatars/user/avatar.jpg"),
        lease_token=str(uuid4()),
    )
    return replace(request, **overrides)


def _ready_snapshot(**overrides: object) -> AccountDeletionValueSnapshot:
    snapshot = AccountDeletionValueSnapshot(
        balances=(),
        active_stakes=0,
        pending_claims=0,
        unresolved_provenance=0,
        unavailable_sources=(),
        destructive_boundary_available=True,
    )
    return replace(snapshot, **overrides)


def _authorize(repository: AsyncMock) -> None:
    repository.authorize_storage_deletion.return_value = {
        "status": "processing",
        "storage_authorized_at": "2026-08-24T17:00:00Z",
    }


@pytest.mark.parametrize(
    ("snapshot", "expected_code"),
    [
        (
            _ready_snapshot(
                balances=(DeletionAssetBalance(asset="CAL", amount_base_units=1, source="balance"),)
            ),
            DeletionBlockerCode.BALANCE_REMAINS,
        ),
        (_ready_snapshot(active_stakes=1), DeletionBlockerCode.STAKE_REMAINS),
        (_ready_snapshot(pending_claims=1), DeletionBlockerCode.CLAIM_REMAINS),
        (
            _ready_snapshot(unresolved_provenance=1),
            DeletionBlockerCode.POLICY_REVIEW_REQUIRED,
        ),
    ],
)
def test_preflight_blocks_every_value_or_unresolved_policy_boundary(
    snapshot: AccountDeletionValueSnapshot,
    expected_code: DeletionBlockerCode,
) -> None:
    preflight = evaluate_account_deletion_preflight(snapshot)

    assert preflight.allowed is False
    assert expected_code in {blocker.code for blocker in preflight.blockers}


def test_preflight_fails_closed_when_any_authority_is_unavailable() -> None:
    preflight = evaluate_account_deletion_preflight(
        _ready_snapshot(unavailable_sources=("rider_balance",))
    )

    assert preflight.allowed is False
    assert preflight.available is False
    assert {blocker.code for blocker in preflight.blockers} == {
        DeletionBlockerCode.PREFLIGHT_UNAVAILABLE
    }


@pytest.mark.asyncio
async def test_worker_cannot_start_destructive_actions_without_unuploaded_ride_acknowledgement() -> None:
    request = _request(unuploaded_rides_acknowledged=False)
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.BLOCKED
    storage.delete_ride_file.assert_not_awaited()
    repository.finalize_anonymization.assert_not_awaited()
    repository.mark_blocked.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    [
        _ready_snapshot(
            balances=(DeletionAssetBalance(asset="DUNG", amount_base_units=1, source="balance"),)
        ),
        _ready_snapshot(active_stakes=1),
        _ready_snapshot(pending_claims=1),
    ],
)
async def test_worker_rechecks_preflight_before_any_destructive_action(
    snapshot: AccountDeletionValueSnapshot,
) -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = snapshot
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.BLOCKED
    storage.delete_ride_file.assert_not_awaited()
    repository.finalize_anonymization.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_sends_unresolved_provenance_to_support_without_destroying_data() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot(unresolved_provenance=1)
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.NEEDS_SUPPORT
    repository.mark_needs_support.assert_awaited_once()
    storage.delete_ride_file.assert_not_awaited()
    repository.finalize_anonymization.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_treats_unavailable_preflight_as_retryable_not_blocked() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot(
        unavailable_sources=("rider_balance",)
    )
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.FAILED_RETRYABLE
    repository.mark_failed.assert_awaited_once_with(
        request,
        failure_code="preflight_unavailable",
    )
    repository.mark_blocked.assert_not_awaited()
    storage.delete_ride_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_reports_retryable_failure_without_tombstoning_when_storage_fails() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()
    storage.delete_ride_file.side_effect = RuntimeError("storage unavailable")

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.FAILED_RETRYABLE
    repository.finalize_anonymization.assert_not_awaited()
    repository.mark_failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_only_reports_completion_after_atomic_anonymization_completes() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()
    storage.delete_ride_file.return_value = True
    storage.file_exists_strict.return_value = False
    repository.finalize_anonymization.return_value = {
        "status": "completed",
        "completion_verified_at": "2026-08-24T17:01:00Z",
    }

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.COMPLETED
    assert storage.delete_ride_file.await_count == len(request.storage_paths)
    assert storage.file_exists_strict.await_count == len(request.storage_paths)
    assert {
        call.kwargs["outcome"]
        for call in repository.record_storage_receipt.await_args_list
    } == {"confirmed_absent"}
    repository.finalize_anonymization.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_worker_runs_the_final_external_and_database_gates_before_storage() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.side_effect = [
        _ready_snapshot(),
        _ready_snapshot(active_stakes=1),
    ]
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.BLOCKED
    assert preflight_reader.read.await_count == 2
    repository.authorize_storage_deletion.assert_not_awaited()
    storage.delete_ride_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_treats_a_final_authority_outage_as_preflight_unavailable() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.side_effect = [
        _ready_snapshot(),
        RuntimeError("chain reader unavailable"),
    ]
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.FAILED_RETRYABLE
    assert outcome.failure_code == "preflight_unavailable"
    repository.mark_failed.assert_awaited_once_with(
        request,
        failure_code="preflight_unavailable",
    )
    repository.authorize_storage_deletion.assert_not_awaited()
    storage.delete_ride_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_honors_atomic_database_authorization_before_storage() -> None:
    request = _request()
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    repository.authorize_storage_deletion.return_value = {
        "status": "needs_support",
        "blockers": [
            {
                "code": "policy_review_required",
                "category": "policy",
                "source": "database_write_fence",
            }
        ],
    }
    preflight_reader = AsyncMock(return_value=_ready_snapshot())
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.NEEDS_SUPPORT
    storage.delete_ride_file.assert_not_awaited()
    repository.mark_storage_removed.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_never_receipts_a_remove_until_strict_absence_is_proven() -> None:
    request = _request(storage_paths=("rides/user/ride.fit",))
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()
    storage.delete_ride_file.return_value = True
    storage.file_exists_strict.return_value = True

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.FAILED_RETRYABLE
    repository.record_storage_receipt.assert_not_awaited()
    repository.mark_storage_removed.assert_not_awaited()
    repository.finalize_anonymization.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_receipts_a_missing_object_only_as_confirmed_absent() -> None:
    request = _request(storage_paths=("rides/user/missing.fit",))
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()
    storage.delete_ride_file.return_value = False
    storage.file_exists_strict.return_value = False
    repository.finalize_anonymization.return_value = {
        "status": "completed",
        "completion_verified_at": "2026-08-24T17:01:00Z",
    }

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
    )

    assert outcome.status is DeletionExecutionStatus.COMPLETED
    repository.record_storage_receipt.assert_awaited_once_with(
        request,
        path="rides/user/missing.fit",
        outcome="confirmed_absent",
    )


@pytest.mark.asyncio
async def test_worker_renews_lease_by_elapsed_threshold_not_per_object() -> None:
    request = _request(storage_paths=("one.fit", "two.fit", "three.fit"))
    repository = AsyncMock()
    repository.claim_for_processing.return_value = request
    _authorize(repository)
    preflight_reader = AsyncMock()
    preflight_reader.read.return_value = _ready_snapshot()
    storage = AsyncMock()
    storage.delete_ride_file.return_value = True
    storage.file_exists_strict.return_value = False
    repository.finalize_anonymization.return_value = {
        "status": "completed",
        "completion_verified_at": "2026-08-24T17:01:00Z",
    }
    ticks = iter((0.0, 1.0, 2.0, 3.0, 121.0, 122.0, 123.0, 124.0, 125.0))

    outcome = await execute_account_deletion(
        request.request_id,
        repository=repository,
        preflight_reader=preflight_reader,
        storage=storage,
        monotonic=lambda: next(ticks),
        lease_renewal_interval_seconds=120,
    )

    assert outcome.status is DeletionExecutionStatus.COMPLETED
    assert repository.renew_lease.await_count == 1


@pytest.mark.asyncio
async def test_authority_reader_combines_database_balance_chain_stakes_and_claims() -> None:
    repository = AsyncMock()
    repository.get_deletion_database_blockers.return_value = [
        {
            "code": "balance_remains",
            "category": "balance",
            "asset": "CAL",
            "count": 1,
            "source": "app_cal_state",
            "action": "open_balance",
        },
        {
            "code": "claim_remains",
            "category": "claim",
            "count": 2,
            "source": "claims_and_vesting",
            "action": "open_balance",
        },
        {
            "code": "policy_review_required",
            "category": "policy",
            "count": 2,
            "source": "claims_and_vesting",
            "action": "contact_support",
        },
    ]
    balance_snapshot = type(
        "BalanceSnapshot",
        (),
        {
            "header": type("Header", (), {"source_status": "live"})(),
            "cal": type("Balance", (), {"amount_base_units": 0, "status": "live"})(),
            "usdc": type("Balance", (), {"amount_base_units": 7, "status": "live"})(),
        },
    )()
    dung_balance = type(
        "Balance",
        (),
        {"amount_base_units": 0, "status": "live"},
    )()
    balance_loader = AsyncMock(return_value=balance_snapshot)
    dung_loader = AsyncMock(return_value=dung_balance)
    stake_loader = AsyncMock(
        return_value=[
            {
                "lp_tokens": "2",
                "cal_staked": 0,
                "effective_lp_tokens": 0,
                "pending_lp_tokens": 0,
                "pending_effective_week_plus_one": 0,
                "rewards_earned": "3",
            }
        ]
    )
    reader = AccountDeletionAuthorityReader(
        repository=repository,
        balance_snapshot_loader=balance_loader,
        balance_dung_loader=dung_loader,
        stake_loader=stake_loader,
    )

    snapshot = await reader.read(user_id="user-1", wallet="wallet-1")

    assert {(balance.asset, balance.amount_base_units, balance.source) for balance in snapshot.balances} == {
        ("USDC", 7, "boulder_roller_balance"),
    }
    assert snapshot.active_stakes == 1
    assert snapshot.pending_claims == 1
    assert snapshot.unresolved_provenance == 1
    assert {blocker.code for blocker in snapshot.database_blockers} == {
        DeletionBlockerCode.BALANCE_REMAINS,
        DeletionBlockerCode.CLAIM_REMAINS,
        DeletionBlockerCode.POLICY_REVIEW_REQUIRED,
    }
    assert snapshot.unavailable_sources == ()


@pytest.mark.asyncio
async def test_authority_reader_names_unavailable_sources_instead_of_assuming_zero() -> None:
    repository = AsyncMock()
    repository.get_deletion_database_blockers.side_effect = RuntimeError("database unavailable")
    reader = AccountDeletionAuthorityReader(
        repository=repository,
        balance_snapshot_loader=AsyncMock(side_effect=RuntimeError("rpc unavailable")),
        balance_dung_loader=AsyncMock(side_effect=RuntimeError("rpc unavailable")),
        stake_loader=AsyncMock(side_effect=RuntimeError("index unavailable")),
    )

    snapshot = await reader.read(user_id="user-1", wallet="wallet-1")

    assert set(snapshot.unavailable_sources) == {
        "database",
        "rider_balance",
        "balance_dung",
        "vault_stakes",
    }
    assert evaluate_account_deletion_preflight(snapshot).available is False


@pytest.mark.asyncio
async def test_authority_reader_escalates_claim_rows_and_wallet_keyed_provenance_even_at_zero() -> None:
    repository = AsyncMock()
    repository.get_deletion_database_blockers.return_value = [
        {
            "code": "claim_remains",
            "category": "claim",
            "count": 3,
            "source": "legacy_claims",
            "action": "open_balance",
        },
        {
            "code": "policy_review_required",
            "category": "policy",
            "count": 9,
            "source": "wallet_keyed_provenance",
            "action": "contact_support",
        },
    ]
    balance_snapshot = type(
        "BalanceSnapshot",
        (),
        {
            "header": type("Header", (), {"source_status": "not_initialized"})(),
            "cal": type("Balance", (), {"amount_base_units": 0, "status": "not_initialized"})(),
            "usdc": type("Balance", (), {"amount_base_units": 0, "status": "not_initialized"})(),
        },
    )()
    zero_dung = type(
        "Balance",
        (),
        {"amount_base_units": 0, "status": "not_initialized"},
    )()
    reader = AccountDeletionAuthorityReader(
        repository=repository,
        balance_snapshot_loader=AsyncMock(return_value=balance_snapshot),
        balance_dung_loader=AsyncMock(return_value=zero_dung),
        stake_loader=AsyncMock(return_value=[]),
    )

    snapshot = await reader.read(user_id="user-1", wallet="wallet-1")

    assert snapshot.pending_claims == 0
    assert snapshot.unresolved_provenance == 0
    assert [blocker.count for blocker in snapshot.database_blockers] == [3, 9]
