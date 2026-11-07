from __future__ import annotations

import pytest

from app.services.balance_lifecycle import (
    BalanceLifecycleAction,
    BalanceLifecycleBlocker,
    BalanceTokenState,
    RiderBalanceLifecycle,
    RiderBalanceStatus,
    balance_authority_active_for_status,
    describe_balance_lifecycle,
    no_prompt_lifecycle_blockers,
    prepare_balance_lifecycle_action,
)


def _lifecycle(
    *,
    initialized: bool = True,
    status: RiderBalanceStatus = RiderBalanceStatus.ACTIVE,
    token_accounts: dict[str, BalanceTokenState] | None = None,
) -> RiderBalanceLifecycle:
    return RiderBalanceLifecycle(
        rider_account_id="rider-123",
        protocol_wallet="7rider",
        initialized=initialized,
        status=status,
        token_accounts=token_accounts
        if token_accounts is not None
        else {
            "CAL": BalanceTokenState(asset="CAL", exists=True, balance_base_units=1_000),
            "USDC": BalanceTokenState(asset="USDC", exists=True, balance_base_units=0),
            "DUNG": BalanceTokenState(asset="DUNG", exists=True, balance_base_units=50),
        },
    )


def test_missing_balance_plans_header_and_token_setup() -> None:
    plan = describe_balance_lifecycle(
        _lifecycle(initialized=False, token_accounts={}),
        required_assets=("CAL", "USDC"),
    )

    assert not plan.no_prompt_execution_allowed
    assert not plan.can_add_funds
    assert not plan.can_withdraw_to_wallet
    assert BalanceLifecycleBlocker.RIDER_BALANCE_REQUIRED in plan.blockers
    assert BalanceLifecycleBlocker.TOKEN_ACCOUNT_REQUIRED in plan.blockers
    assert [step.action_type for step in plan.setup_steps] == [
        BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE.value,
        BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE_TOKEN.value,
        BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE_TOKEN.value,
    ]
    assert [step.asset for step in plan.setup_steps[1:]] == ["CAL", "USDC"]
    assert plan.rider_detail == "Set up Boulder Roller Balance to use in-app actions."


def test_active_balance_exposes_asset_rows_and_boundary_availability() -> None:
    plan = describe_balance_lifecycle(_lifecycle(), required_assets=("CAL", "USDC", "DUNG"))

    assert plan.no_prompt_execution_allowed
    assert plan.can_add_funds
    assert plan.can_withdraw_to_wallet
    assert not plan.setup_steps
    assert [(asset.asset, asset.rider_state) for asset in plan.assets] == [
        ("CAL", "Available"),
        ("USDC", "Ready"),
        ("DUNG", "Available"),
    ]
    assert plan.rider_headline == "Boulder Roller Balance"
    assert plan.rider_detail == "Balance is ready."


def test_add_funds_stays_available_when_one_funding_asset_is_ready() -> None:
    plan = describe_balance_lifecycle(
        _lifecycle(
            token_accounts={
                "CAL": BalanceTokenState(asset="CAL", exists=True, balance_base_units=100),
                "USDC": BalanceTokenState(asset="USDC", exists=False, balance_base_units=0),
                "DUNG": BalanceTokenState(asset="DUNG", exists=True, balance_base_units=50),
            },
        ),
        required_assets=("CAL", "USDC", "DUNG"),
    )

    assert plan.can_add_funds
    assert not plan.no_prompt_execution_allowed
    assert BalanceLifecycleBlocker.TOKEN_ACCOUNT_REQUIRED in plan.blockers


def test_add_funds_requires_boundary_step_up() -> None:
    blocked = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.ADD_FUNDS,
        asset="CAL",
        amount_base_units=500,
    )
    allowed = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.ADD_FUNDS,
        asset="CAL",
        amount_base_units=500,
        step_up_satisfied=True,
    )

    assert blocked.boundary_action
    assert blocked.step_up_required
    assert BalanceLifecycleBlocker.STEP_UP_REQUIRED in blocked.blockers
    assert blocked.rider_detail == "Confirm this boundary action to continue."
    assert allowed.allowed
    assert allowed.rider_label == "Add funds"


def test_use_in_balance_requires_existing_asset_and_balance() -> None:
    allowed = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.USE_IN_BALANCE,
        asset="CAL",
        amount_base_units=999,
    )
    insufficient = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.USE_IN_BALANCE,
        asset="USDC",
        amount_base_units=1,
    )

    assert allowed.allowed
    assert BalanceLifecycleBlocker.INSUFFICIENT_BALANCE in insufficient.blockers


def test_withdraw_to_wallet_is_boundary_and_uses_account_security_language() -> None:
    recovering = prepare_balance_lifecycle_action(
        _lifecycle(status=RiderBalanceStatus.RECOVERING),
        action_type=BalanceLifecycleAction.WITHDRAW_TO_WALLET,
        asset="CAL",
        amount_base_units=100,
        step_up_satisfied=True,
    )
    allowed = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.WITHDRAW_TO_WALLET,
        asset="CAL",
        amount_base_units=100,
        step_up_satisfied=True,
    )

    assert recovering.boundary_action
    assert BalanceLifecycleBlocker.ACCOUNT_RECOVERING in recovering.blockers
    assert recovering.rider_headline == "Account recovery"
    assert recovering.rider_detail == "Account recovery is in progress. New in-app Balance actions are paused."
    assert not any(word in recovering.rider_detail.lower() for word in ("gas", "transaction", "signature"))
    assert allowed.allowed
    assert allowed.rider_label == "Withdraw to wallet"


@pytest.mark.parametrize(
    ("status", "blocker"),
    (
        (RiderBalanceStatus.LOCKED, BalanceLifecycleBlocker.ACCOUNT_LOCKED),
        (RiderBalanceStatus.RECOVERING, BalanceLifecycleBlocker.ACCOUNT_RECOVERING),
        (RiderBalanceStatus.REVOKED, BalanceLifecycleBlocker.ACCOUNT_REVOKED),
    ),
)
def test_locked_recovering_and_revoked_disable_no_prompt_execution(
    status: RiderBalanceStatus,
    blocker: BalanceLifecycleBlocker,
) -> None:
    plan = describe_balance_lifecycle(_lifecycle(status=status))

    assert not plan.no_prompt_execution_allowed
    assert blocker in plan.blockers
    assert no_prompt_lifecycle_blockers(status) == (blocker,)
    assert not balance_authority_active_for_status(status)


def test_unsupported_asset_is_rejected_without_primary_crypto_language() -> None:
    decision = prepare_balance_lifecycle_action(
        _lifecycle(),
        action_type=BalanceLifecycleAction.ADD_FUNDS,
        asset="SOL",
        amount_base_units=1,
        step_up_satisfied=True,
    )

    assert not decision.allowed
    assert BalanceLifecycleBlocker.UNSUPPORTED_ASSET in decision.blockers
    assert not any(word in decision.rider_detail.lower() for word in ("gas", "transaction", "signature"))
