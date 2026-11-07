from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.balance_transaction_coordinator import (
    BalanceActionBudgetExceeded,
    BalanceActionBudgetPolicy,
    BalanceConfirmationStatus,
    BalanceOperationError,
    BalanceOperationIntent,
    BalanceProjectionStatus,
    BalanceRiderState,
    BalanceTransactionCoordinator,
    InMemoryBalanceOperationLog,
    SupabaseBalanceOperationSink,
)
from app.services.boulder_balance_authority import AuthorityModel, NORMAL_BALANCE_ACTIONS
from app.services.balance_lifecycle import RiderBalanceStatus


def _intent(
    *,
    action_type: str = "deposit_cal",
    authority_model: AuthorityModel = AuthorityModel.RIDER_SESSION,
    asset: str = "CAL",
    amount: str = "250000000000",
    source: str = "RiderBalance CAL token PDA",
    destination: str = "Vault CAL Escrow PDA",
    policy_or_delegate_id: str | None = "rider-session-123",
    step_up_satisfied: bool = False,
    program_config_checked: bool = True,
    revocation_checked: bool = True,
    balance_authority_active: bool = True,
    policy_or_delegate_active: bool = True,
    boulder_constraints_checked: bool = True,
    balance_lifecycle_status: RiderBalanceStatus = RiderBalanceStatus.ACTIVE,
) -> BalanceOperationIntent:
    return BalanceOperationIntent(
        action_type=action_type,
        rider_account_id="rider-123",
        protocol_wallet="Wallet111111111111111111111111111111111",
        authority_model=authority_model,
        asset=asset,
        amount=amount,
        source=source,
        destination=destination,
        reference_type="vault",
        reference_id="42",
        prepared_message_hash="msg-hash-123",
        fee_payer="BoulderRollerFeePayer111111111111111",
        policy_or_delegate_id=policy_or_delegate_id,
        program_config_checked=program_config_checked,
        revocation_checked=revocation_checked,
        step_up_satisfied=step_up_satisfied,
        balance_authority_active=balance_authority_active,
        policy_or_delegate_active=policy_or_delegate_active,
        boulder_constraints_checked=boulder_constraints_checked,
        balance_lifecycle_status=balance_lifecycle_status,
        metadata={"surface": "vault"},
    )


class _BudgetStore:
    def __init__(self, *, rider_count: int = 0, global_count: int = 0) -> None:
        self.rider_count = rider_count
        self.global_count = global_count
        self.rider_calls: list[dict[str, object]] = []
        self.global_calls: list[dict[str, object]] = []

    def count_rider_actions(self, **kwargs) -> int:
        self.rider_calls.append(dict(kwargs))
        return self.rider_count

    def count_global_actions(self, **kwargs) -> int:
        self.global_calls.append(dict(kwargs))
        return self.global_count


def _noon_utc() -> datetime:
    return datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def test_prepare_operation_records_required_ledger_fields() -> None:
    log = InMemoryBalanceOperationLog()
    coordinator = BalanceTransactionCoordinator(sink=log)

    record = coordinator.prepare_operation(_intent())

    assert record.operation_id.startswith("br-op-")
    assert record.action_type == "deposit_cal"
    assert record.authority_model == "rider_session"
    assert record.asset == "CAL"
    assert record.source == "RiderBalance CAL token PDA"
    assert record.destination == "Vault CAL Escrow PDA"
    assert record.idempotency_key.startswith("br:deposit_cal:")
    assert record.prepared_message_hash == "msg-hash-123"
    assert record.fee_payer == "BoulderRollerFeePayer111111111111111"
    assert record.confirmation_status == BalanceConfirmationStatus.PREPARED.value
    assert record.projection_status == BalanceProjectionStatus.NOT_STARTED.value
    assert record.rider_state == BalanceRiderState.PENDING.value
    assert record.retry_count == 0
    assert record.failure_reason is None
    assert log.get(record.operation_id) == record


def test_per_rider_daily_budget_blocks_action_before_insert() -> None:
    log = InMemoryBalanceOperationLog()
    budget_store = _BudgetStore(rider_count=2, global_count=0)
    coordinator = BalanceTransactionCoordinator(
        sink=log,
        budget_store=budget_store,
        budget_policy=BalanceActionBudgetPolicy(
            rider_daily_budgets={"deposit_cal": 2},
            global_daily_budget=100,
        ),
        clock=_noon_utc,
    )

    with pytest.raises(BalanceActionBudgetExceeded) as exc_info:
        coordinator.prepare_operation(_intent(action_type="deposit_cal"))

    exc = exc_info.value
    assert exc.scope == "rider"
    assert exc.limit == 2
    assert exc.used == 2
    assert exc.rider_message == "Today's Deposit CAL limit is reached. Try again tomorrow."
    assert exc.retry_after_seconds == 12 * 60 * 60
    assert log.records == {}
    assert budget_store.rider_calls[0]["rider_account_id"] == "rider-123"
    assert budget_store.rider_calls[0]["action_type"] == "deposit_cal"


def test_global_daily_budget_blocks_before_insert() -> None:
    log = InMemoryBalanceOperationLog()
    coordinator = BalanceTransactionCoordinator(
        sink=log,
        budget_store=_BudgetStore(rider_count=0, global_count=500),
        budget_policy=BalanceActionBudgetPolicy(
            rider_daily_budgets={"collect_dung": 12},
            global_daily_budget=500,
        ),
        clock=_noon_utc,
    )

    with pytest.raises(BalanceActionBudgetExceeded) as exc_info:
        coordinator.prepare_operation(
            _intent(
                action_type="collect_dung",
                authority_model=AuthorityModel.PERMISSIONLESS_FOR_RIDER,
                asset="DUNG",
            )
        )

    exc = exc_info.value
    assert exc.scope == "global"
    assert exc.rider_message == "Today's Balance action limit is reached. Try again tomorrow."
    assert log.records == {}


def test_budget_policy_reads_action_and_global_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BALANCE_RIDER_DAILY_COLLECT_DUNG_BUDGET", "3")
    monkeypatch.setenv("BALANCE_GLOBAL_DAILY_ACTION_BUDGET", "27")

    policy = BalanceActionBudgetPolicy.from_env()

    assert policy.rider_limit_for("collect_dung") == 3
    assert policy.global_daily_budget == 27
    assert policy.enabled is True


def test_operation_id_is_stable_for_same_intent() -> None:
    coordinator = BalanceTransactionCoordinator()

    first = coordinator.prepare_operation(_intent())
    second = coordinator.prepare_operation(_intent())

    assert first.idempotency_key == second.idempotency_key
    assert first.operation_id == second.operation_id


def test_prepared_message_hash_is_sha256() -> None:
    digest = BalanceTransactionCoordinator.prepared_message_hash(b"prepared message bytes")

    assert digest == "af68b8cd7c216338f9b5035fc1525202c9e8a8f9e98b0c0c937ec81dc6d2fb6b"


@pytest.mark.parametrize("action_type", NORMAL_BALANCE_ACTIONS)
def test_normal_actions_allow_primary_no_prompt_authority_models(action_type: str) -> None:
    authority_model = (
        AuthorityModel.PERMISSIONLESS_FOR_RIDER
        if action_type == "collect_dung"
        else AuthorityModel.RIDER_SESSION
    )
    asset = {
        "collect_dung": "DUNG",
        "deposit_cal": "CAL",
        "withdraw_cal": "LP",
        "create_vault": "CAL+USDC",
        "pay_usdc": "USDC",
    }[action_type]

    record = BalanceTransactionCoordinator().prepare_operation(
        _intent(action_type=action_type, authority_model=authority_model, asset=asset)
    )

    assert record.action_type == action_type
    assert record.authority_model == authority_model.value
    assert record.rider_state == BalanceRiderState.PENDING.value


def test_wrong_authority_model_is_rejected_before_transaction_build() -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="authority model backend_authorized is not allowed"):
        coordinator.prepare_operation(_intent(authority_model=AuthorityModel.BACKEND_AUTHORIZED))


@pytest.mark.parametrize(
    "authority_model",
    (AuthorityModel.RIDER_SESSION, AuthorityModel.PRIVY_POLICY_SIGNER, AuthorityModel.SPL_DELEGATE),
)
def test_policy_and_delegate_execution_require_authority_id(authority_model: AuthorityModel) -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="policy_or_delegate_id is required"):
        coordinator.prepare_operation(_intent(authority_model=authority_model, policy_or_delegate_id=None))

    record = coordinator.prepare_operation(
        _intent(authority_model=authority_model, policy_or_delegate_id="authority-123")
    )
    assert record.policy_or_delegate_id == "authority-123"


def test_wallet_boundary_execution_requires_step_up() -> None:
    coordinator = BalanceTransactionCoordinator()
    intent = _intent(
        action_type="withdraw_to_wallet",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        asset="CAL",
        source="RiderBalance CAL token PDA",
        destination="Rider wallet CAL token account",
    )

    with pytest.raises(BalanceOperationError, match="wallet-boundary execution requires step-up"):
        coordinator.prepare_operation(intent)

    record = coordinator.prepare_operation(
        _intent(
            action_type="withdraw_to_wallet",
            authority_model=AuthorityModel.WALLET_BOUNDARY,
            asset="CAL",
            source="RiderBalance CAL token PDA",
            destination="Rider wallet CAL token account",
            step_up_satisfied=True,
        )
    )
    assert record.authority_model == AuthorityModel.WALLET_BOUNDARY.value


def test_program_config_and_revocation_checks_are_required_for_balance_actions() -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="ProgramConfig check is required"):
        coordinator.prepare_operation(_intent(program_config_checked=False))

    with pytest.raises(BalanceOperationError, match="revocation check is required"):
        coordinator.prepare_operation(_intent(revocation_checked=False))


def test_unsupported_asset_is_rejected() -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="unsupported asset"):
        coordinator.prepare_operation(_intent(asset="SOL"))


def test_inactive_balance_authority_is_rejected_before_submission() -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="balance_authority_inactive"):
        coordinator.prepare_operation(_intent(balance_authority_active=False))


@pytest.mark.parametrize(
    "authority_model",
    (AuthorityModel.RIDER_SESSION, AuthorityModel.PRIVY_POLICY_SIGNER, AuthorityModel.SPL_DELEGATE),
)
def test_stale_policy_or_delegate_id_is_rejected_before_submission(
    authority_model: AuthorityModel,
) -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="stale_policy_or_delegate_id"):
        coordinator.prepare_operation(
            _intent(
                authority_model=authority_model,
                policy_or_delegate_id="authority-123",
                policy_or_delegate_active=False,
            )
        )


def test_provider_gap_paths_require_boulder_constraints_before_submission() -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match="boulder_constraints_required"):
        coordinator.prepare_operation(
            _intent(
                authority_model=AuthorityModel.PRIVY_POLICY_SIGNER,
                policy_or_delegate_id="authority-123",
                boulder_constraints_checked=False,
            )
        )


@pytest.mark.parametrize(
    ("status", "failure"),
    (
        (RiderBalanceStatus.LOCKED, "account_locked"),
        (RiderBalanceStatus.RECOVERING, "account_recovering"),
        (RiderBalanceStatus.REVOKED, "account_revoked"),
    ),
)
@pytest.mark.parametrize(
    "authority_model",
    (
        AuthorityModel.RIDER_SESSION,
        AuthorityModel.PRIVY_POLICY_SIGNER,
        AuthorityModel.SPL_DELEGATE,
    ),
)
def test_locked_recovering_and_revoked_balance_blocks_no_prompt_execution(
    status: RiderBalanceStatus,
    failure: str,
    authority_model: AuthorityModel,
) -> None:
    coordinator = BalanceTransactionCoordinator()

    with pytest.raises(BalanceOperationError, match=failure):
        coordinator.prepare_operation(
            _intent(
                authority_model=authority_model,
                policy_or_delegate_id=(
                    "authority-123"
                    if authority_model
                    in (
                        AuthorityModel.RIDER_SESSION,
                        AuthorityModel.PRIVY_POLICY_SIGNER,
                        AuthorityModel.SPL_DELEGATE,
                    )
                    else None
                ),
                balance_lifecycle_status=status,
            )
        )


def test_confirmation_projection_and_failure_transitions_use_rider_language() -> None:
    log = InMemoryBalanceOperationLog()
    coordinator = BalanceTransactionCoordinator(sink=log)
    record = coordinator.prepare_operation(
        _intent(action_type="collect_dung", authority_model=AuthorityModel.PERMISSIONLESS_FOR_RIDER, asset="DUNG")
    )

    submitted = coordinator.mark_submitted(record, "tx-sig-123")
    assert submitted.confirmation_status == BalanceConfirmationStatus.SUBMITTED.value
    assert submitted.tx_signature == "tx-sig-123"
    assert submitted.rider_state == BalanceRiderState.PENDING.value

    confirmed = coordinator.mark_confirmed(submitted)
    assert confirmed.confirmation_status == BalanceConfirmationStatus.CONFIRMED.value
    assert confirmed.rider_state == BalanceRiderState.DELAYED.value

    pending = coordinator.mark_projection(confirmed, BalanceProjectionStatus.PENDING)
    assert pending.projection_status == BalanceProjectionStatus.PENDING.value
    assert pending.rider_state == BalanceRiderState.PENDING.value

    recorded = coordinator.mark_projection(confirmed, BalanceProjectionStatus.RECORDED)
    assert recorded.projection_status == BalanceProjectionStatus.RECORDED.value
    assert recorded.rider_state == BalanceRiderState.COLLECTED.value

    delayed = coordinator.mark_projection(confirmed, BalanceProjectionStatus.DELAYED)
    assert delayed.rider_state == BalanceRiderState.DELAYED.value

    failed = coordinator.mark_failed(delayed, reason="projection failed")
    assert failed.confirmation_status == BalanceConfirmationStatus.FAILED.value
    assert failed.projection_status == BalanceProjectionStatus.NEEDS_REVIEW.value
    assert failed.rider_state == BalanceRiderState.NEEDS_REVIEW.value
    assert failed.failure_reason == "projection failed"


def test_retry_count_updates_operation_log() -> None:
    log = InMemoryBalanceOperationLog()
    coordinator = BalanceTransactionCoordinator(sink=log)
    record = coordinator.prepare_operation(_intent())

    retried = coordinator.mark_retry(record)

    assert retried.retry_count == 1
    assert log.get(record.operation_id) == retried


def test_supabase_sink_inserts_new_operation_and_upserts_updates() -> None:
    client = MagicMock()
    table = MagicMock()
    table.insert.return_value = table
    table.upsert.return_value = table
    table.execute.return_value = None
    client.table.return_value = table
    coordinator = BalanceTransactionCoordinator(sink=SupabaseBalanceOperationSink(client))

    record = coordinator.prepare_operation(_intent())
    coordinator.mark_submitted(record, "tx-signature")

    client.table.assert_any_call("balance_operations")
    table.insert.assert_called_once()
    assert table.insert.call_args.args[0]["confirmation_status"] == BalanceConfirmationStatus.PREPARED.value
    table.upsert.assert_called_once()
    assert table.upsert.call_args.args[0]["confirmation_status"] == BalanceConfirmationStatus.SUBMITTED.value


def test_supabase_sink_counts_rider_action_budget_window() -> None:
    client = MagicMock()
    table = MagicMock()
    query = MagicMock()
    response = MagicMock()
    response.count = 4
    client.table.return_value = table
    table.select.return_value = query
    query.gte.return_value = query
    query.lt.return_value = query
    query.eq.return_value = query
    query.execute.return_value = response
    sink = SupabaseBalanceOperationSink(client)

    count = sink.count_rider_actions(
        rider_account_id="rider-123",
        action_type="collect_dung",
        window_start=datetime(2026, 7, 6, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )

    assert count == 4
    client.table.assert_called_once_with("balance_operations")
    table.select.assert_called_once_with("operation_id", count="exact")
    query.gte.assert_called_once_with("created_at", "2026-07-06T00:00:00+00:00")
    query.lt.assert_called_once_with("created_at", "2026-07-07T00:00:00+00:00")
    query.eq.assert_any_call("rider_account_id", "rider-123")
    query.eq.assert_any_call("action_type", "collect_dung")


def test_supabase_sink_insert_failure_blocks_submission_preparation() -> None:
    client = MagicMock()
    table = MagicMock()
    table.insert.return_value = table
    table.execute.side_effect = RuntimeError("database unavailable")
    client.table.return_value = table
    coordinator = BalanceTransactionCoordinator(sink=SupabaseBalanceOperationSink(client))

    with pytest.raises(BalanceOperationError, match="Failed to persist Balance operation"):
        coordinator.prepare_operation(_intent())
