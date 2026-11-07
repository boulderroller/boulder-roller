from __future__ import annotations

import pytest

from app.services.balance_authority_execution import (
    BalanceExecutionAdapter,
    BalanceExecutionFailure,
    plan_balance_authority_execution,
)
from app.services.boulder_balance_authority import AuthorityModel


@pytest.mark.parametrize(
    ("action_type", "authority_model", "adapter"),
    (
        ("collect_dung", AuthorityModel.PERMISSIONLESS_FOR_RIDER, BalanceExecutionAdapter.PERMISSIONLESS_FOR_RIDER),
        ("deposit_cal", AuthorityModel.RIDER_SESSION, BalanceExecutionAdapter.RIDER_SESSION_SIGNER),
        ("withdraw_cal", AuthorityModel.RIDER_SESSION, BalanceExecutionAdapter.RIDER_SESSION_SIGNER),
        ("create_vault", AuthorityModel.RIDER_SESSION, BalanceExecutionAdapter.RIDER_SESSION_SIGNER),
        ("pay_usdc", AuthorityModel.RIDER_SESSION, BalanceExecutionAdapter.RIDER_SESSION_SIGNER),
        ("pay_usdc", AuthorityModel.PRIVY_POLICY_SIGNER, BalanceExecutionAdapter.PRIVY_POLICY_SIGNER),
        ("deposit_cal", AuthorityModel.SPL_DELEGATE, BalanceExecutionAdapter.SPL_DELEGATE),
        ("withdraw_to_wallet", AuthorityModel.WALLET_BOUNDARY, BalanceExecutionAdapter.WALLET_BOUNDARY_CONFIRMATION),
    ),
)
def test_authority_models_resolve_to_separate_execution_adapters(
    action_type: str,
    authority_model: AuthorityModel,
    adapter: BalanceExecutionAdapter,
) -> None:
    plan = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=authority_model,
        policy_or_delegate_id="authority-123",
        boulder_constraints_checked=True,
        step_up_satisfied=authority_model is AuthorityModel.WALLET_BOUNDARY,
    )

    assert plan.allowed
    assert plan.adapter is adapter


def test_backend_authorized_cannot_sneak_into_balance_execution() -> None:
    plan = plan_balance_authority_execution(
        action_type="deposit_cal",
        authority_model=AuthorityModel.BACKEND_AUTHORIZED,
        boulder_constraints_checked=True,
    )

    assert not plan.allowed
    assert BalanceExecutionFailure.AUTHORITY_NOT_ALLOWED in plan.failures


@pytest.mark.parametrize("action_type", ("deposit_cal", "withdraw_cal", "create_vault", "pay_usdc"))
def test_balance_vault_value_actions_require_rider_session_authority(action_type: str) -> None:
    plain_balance = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=AuthorityModel.APP_BALANCE,
        boulder_constraints_checked=True,
    )
    missing_session = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=AuthorityModel.RIDER_SESSION,
        boulder_constraints_checked=True,
    )
    rider_session = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=AuthorityModel.RIDER_SESSION,
        policy_or_delegate_id="rider-session-123",
        boulder_constraints_checked=True,
    )

    assert BalanceExecutionFailure.AUTHORITY_NOT_ALLOWED in plain_balance.failures
    assert BalanceExecutionFailure.MISSING_POLICY_OR_DELEGATE_ID in missing_session.failures
    assert rider_session.allowed
    assert rider_session.adapter is BalanceExecutionAdapter.RIDER_SESSION_SIGNER


@pytest.mark.parametrize(
    "authority_model",
    (
        AuthorityModel.PERMISSIONLESS_FOR_RIDER,
        AuthorityModel.RIDER_SESSION,
        AuthorityModel.PRIVY_POLICY_SIGNER,
        AuthorityModel.SPL_DELEGATE,
    ),
)
def test_inactive_balance_authority_blocks_no_prompt_paths(authority_model: AuthorityModel) -> None:
    action_type = "collect_dung" if authority_model is AuthorityModel.PERMISSIONLESS_FOR_RIDER else "deposit_cal"
    plan = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=authority_model,
        policy_or_delegate_id="authority-123",
        balance_authority_active=False,
        boulder_constraints_checked=True,
    )

    assert not plan.allowed
    assert BalanceExecutionFailure.BALANCE_AUTHORITY_INACTIVE in plan.failures


@pytest.mark.parametrize(
    "authority_model",
    (AuthorityModel.RIDER_SESSION, AuthorityModel.PRIVY_POLICY_SIGNER, AuthorityModel.SPL_DELEGATE),
)
def test_policy_and_delegate_paths_require_live_authority_id(authority_model: AuthorityModel) -> None:
    missing = plan_balance_authority_execution(
        action_type="deposit_cal",
        authority_model=authority_model,
        boulder_constraints_checked=True,
    )
    stale = plan_balance_authority_execution(
        action_type="deposit_cal",
        authority_model=authority_model,
        policy_or_delegate_id="authority-123",
        policy_or_delegate_active=False,
        boulder_constraints_checked=True,
    )

    assert BalanceExecutionFailure.MISSING_POLICY_OR_DELEGATE_ID in missing.failures
    assert BalanceExecutionFailure.STALE_POLICY_OR_DELEGATE_ID in stale.failures


@pytest.mark.parametrize(
    ("action_type", "authority_model"),
    (
        ("collect_dung", AuthorityModel.PERMISSIONLESS_FOR_RIDER),
        ("deposit_cal", AuthorityModel.RIDER_SESSION),
        ("deposit_cal", AuthorityModel.PRIVY_POLICY_SIGNER),
        ("deposit_cal", AuthorityModel.SPL_DELEGATE),
    ),
)
def test_custom_anchor_and_balance_paths_require_boulder_constraints(
    action_type: str,
    authority_model: AuthorityModel,
) -> None:
    plan = plan_balance_authority_execution(
        action_type=action_type,
        authority_model=authority_model,
        policy_or_delegate_id="authority-123",
        boulder_constraints_checked=False,
    )

    assert not plan.allowed
    assert BalanceExecutionFailure.BOULDER_CONSTRAINTS_REQUIRED in plan.failures
    assert plan.requires_boulder_constraints


def test_privy_usdc_transfer_can_rely_on_provider_policy_when_quote_matches() -> None:
    plan = plan_balance_authority_execution(
        action_type="pay_usdc",
        authority_model=AuthorityModel.PRIVY_POLICY_SIGNER,
        policy_or_delegate_id="br-balance-pay-usdc-devnet",
        boulder_constraints_checked=False,
    )

    assert plan.allowed
    assert plan.provider_sufficient_for_production is True
    assert not plan.requires_boulder_constraints


def test_wallet_boundary_requires_step_up_but_not_balance_authority() -> None:
    blocked = plan_balance_authority_execution(
        action_type="withdraw_to_wallet",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        balance_authority_active=False,
    )
    allowed = plan_balance_authority_execution(
        action_type="withdraw_to_wallet",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        balance_authority_active=False,
        step_up_satisfied=True,
    )

    assert BalanceExecutionFailure.STEP_UP_REQUIRED in blocked.failures
    assert allowed.allowed


def test_unknown_action_is_rejected_before_adapter_selection() -> None:
    plan = plan_balance_authority_execution(
        action_type="unknown",
        authority_model=AuthorityModel.APP_BALANCE,
    )

    assert not plan.allowed
    assert plan.adapter is None
    assert plan.failures == (BalanceExecutionFailure.UNKNOWN_ACTION,)
