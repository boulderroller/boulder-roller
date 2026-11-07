"""Execution-plan gate for Boulder Roller Balance authority paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .balance_privy_policy_prototype import constraint_for_action
from .boulder_balance_authority import (
    AuthorityModel,
    BalanceAuthorityPolicy,
    BoundaryStepUp,
    policy_for_action,
)


class BalanceExecutionAdapter(str, Enum):
    """Concrete backend adapter families for Balance execution."""

    PERMISSIONLESS_FOR_RIDER = "permissionless_for_rider"
    RIDER_BALANCE_INSTRUCTION = "rider_balance_instruction"
    RIDER_SESSION_SIGNER = "rider_session_signer"
    PRIVY_POLICY_SIGNER = "privy_policy_signer"
    SPL_DELEGATE = "spl_delegate"
    WALLET_BOUNDARY_CONFIRMATION = "wallet_boundary_confirmation"


class BalanceExecutionFailure(str, Enum):
    """Reasons an authority path cannot be prepared for execution."""

    UNKNOWN_ACTION = "unknown_action"
    AUTHORITY_NOT_ALLOWED = "authority_not_allowed"
    BALANCE_AUTHORITY_INACTIVE = "balance_authority_inactive"
    MISSING_POLICY_OR_DELEGATE_ID = "missing_policy_or_delegate_id"
    STALE_POLICY_OR_DELEGATE_ID = "stale_policy_or_delegate_id"
    BOULDER_CONSTRAINTS_REQUIRED = "boulder_constraints_required"
    STEP_UP_REQUIRED = "step_up_required"


@dataclass(frozen=True)
class BalanceAuthorityExecutionPlan:
    """Prepared authority route before any signer or submission adapter is used."""

    action_type: str
    rider_label: str | None
    authority_model: AuthorityModel
    adapter: BalanceExecutionAdapter | None
    allowed: bool
    failures: tuple[BalanceExecutionFailure, ...]
    requires_boulder_constraints: bool
    provider_sufficient_for_production: bool | None
    fallback_behavior: tuple[str, ...]


ADAPTER_BY_AUTHORITY: dict[AuthorityModel, BalanceExecutionAdapter] = {
    AuthorityModel.PERMISSIONLESS_FOR_RIDER: BalanceExecutionAdapter.PERMISSIONLESS_FOR_RIDER,
    AuthorityModel.APP_BALANCE: BalanceExecutionAdapter.RIDER_BALANCE_INSTRUCTION,
    AuthorityModel.RIDER_SESSION: BalanceExecutionAdapter.RIDER_SESSION_SIGNER,
    AuthorityModel.PRIVY_POLICY_SIGNER: BalanceExecutionAdapter.PRIVY_POLICY_SIGNER,
    AuthorityModel.SPL_DELEGATE: BalanceExecutionAdapter.SPL_DELEGATE,
    AuthorityModel.WALLET_BOUNDARY: BalanceExecutionAdapter.WALLET_BOUNDARY_CONFIRMATION,
}


def plan_balance_authority_execution(
    *,
    action_type: str,
    authority_model: AuthorityModel,
    policy_or_delegate_id: str | None = None,
    balance_authority_active: bool = True,
    policy_or_delegate_active: bool = True,
    boulder_constraints_checked: bool = False,
    step_up_satisfied: bool = False,
) -> BalanceAuthorityExecutionPlan:
    """Validate the concrete authority adapter before any signing or submission.

    This sits between route intent construction and transaction signing. It does
    not execute transactions. It only decides whether a route may ask a concrete
    adapter to continue.
    """

    try:
        policy = policy_for_action(action_type)
    except ValueError:
        return BalanceAuthorityExecutionPlan(
            action_type=action_type,
            rider_label=None,
            authority_model=authority_model,
            adapter=None,
            allowed=False,
            failures=(BalanceExecutionFailure.UNKNOWN_ACTION,),
            requires_boulder_constraints=False,
            provider_sufficient_for_production=None,
            fallback_behavior=("use wallet-boundary confirmation",),
        )

    adapter = ADAPTER_BY_AUTHORITY.get(authority_model)
    provider_sufficient = _provider_sufficient_for_production(action_type, authority_model)
    requires_boulder_constraints = _requires_boulder_constraints(policy, authority_model, provider_sufficient)
    failures: list[BalanceExecutionFailure] = []

    if authority_model not in policy.authority_models:
        failures.append(BalanceExecutionFailure.AUTHORITY_NOT_ALLOWED)

    if authority_model is not AuthorityModel.WALLET_BOUNDARY and not balance_authority_active:
        failures.append(BalanceExecutionFailure.BALANCE_AUTHORITY_INACTIVE)

    if authority_model in (
        AuthorityModel.RIDER_SESSION,
        AuthorityModel.PRIVY_POLICY_SIGNER,
        AuthorityModel.SPL_DELEGATE,
    ):
        if not policy_or_delegate_id:
            failures.append(BalanceExecutionFailure.MISSING_POLICY_OR_DELEGATE_ID)
        elif not policy_or_delegate_active:
            failures.append(BalanceExecutionFailure.STALE_POLICY_OR_DELEGATE_ID)

    if requires_boulder_constraints and not boulder_constraints_checked:
        failures.append(BalanceExecutionFailure.BOULDER_CONSTRAINTS_REQUIRED)

    if authority_model is AuthorityModel.WALLET_BOUNDARY and policy.step_up is not BoundaryStepUp.NONE:
        if not step_up_satisfied:
            failures.append(BalanceExecutionFailure.STEP_UP_REQUIRED)

    return BalanceAuthorityExecutionPlan(
        action_type=action_type,
        rider_label=policy.rider_label,
        authority_model=authority_model,
        adapter=adapter,
        allowed=not failures,
        failures=tuple(dict.fromkeys(failures)),
        requires_boulder_constraints=requires_boulder_constraints,
        provider_sufficient_for_production=provider_sufficient,
        fallback_behavior=policy.fallback_behavior,
    )


def _provider_sufficient_for_production(
    action_type: str,
    authority_model: AuthorityModel,
) -> bool | None:
    if authority_model is not AuthorityModel.PRIVY_POLICY_SIGNER:
        return None
    try:
        return constraint_for_action(action_type).provider_sufficient_for_production
    except ValueError:
        return False


def _requires_boulder_constraints(
    policy: BalanceAuthorityPolicy,
    authority_model: AuthorityModel,
    provider_sufficient: bool | None,
) -> bool:
    if authority_model is AuthorityModel.WALLET_BOUNDARY:
        return False
    if authority_model is AuthorityModel.PRIVY_POLICY_SIGNER:
        return not bool(provider_sufficient)
    return bool(
        policy.program_constraints
        or policy.account_constraints
        or policy.amount_constraints
        or policy.destination_constraints
    )
