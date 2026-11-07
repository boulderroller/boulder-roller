"""Lifecycle model for Boulder Roller Balance account readiness.

This module does not read chain state. It turns already-read RiderBalance and
token-account facts into deterministic setup, boundary-action, and account
security decisions for route adapters and rider surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class RiderBalanceStatus(str, Enum):
    """On-chain RiderBalance header state."""

    ACTIVE = "active"
    LOCKED = "locked"
    RECOVERING = "recovering"
    REVOKED = "revoked"


class BalanceLifecycleAction(str, Enum):
    """Lifecycle actions route adapters can prepare."""

    INITIALIZE_RIDER_BALANCE = "initialize_rider_balance"
    INITIALIZE_RIDER_BALANCE_TOKEN = "initialize_rider_balance_token"
    ADD_FUNDS = "add_funds"
    USE_IN_BALANCE = "use_in_balance"
    WITHDRAW_TO_WALLET = "withdraw_to_wallet"
    ACCOUNT_SECURITY = "account_security"


class BalanceLifecycleBlocker(str, Enum):
    """Reasons a lifecycle action is not currently available."""

    RIDER_BALANCE_REQUIRED = "rider_balance_required"
    TOKEN_ACCOUNT_REQUIRED = "token_account_required"
    UNSUPPORTED_ASSET = "unsupported_asset"
    ZERO_AMOUNT = "zero_amount"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_RECOVERING = "account_recovering"
    ACCOUNT_REVOKED = "account_revoked"
    STEP_UP_REQUIRED = "step_up_required"
    CHAIN_STATE_UNAVAILABLE = "chain_state_unavailable"


SUPPORTED_BALANCE_ASSETS = ("CAL", "USDC", "DUNG", "LP")
DEFAULT_SETUP_ASSETS = ("CAL", "USDC", "DUNG")

_STATUS_BLOCKERS: dict[RiderBalanceStatus, BalanceLifecycleBlocker] = {
    RiderBalanceStatus.LOCKED: BalanceLifecycleBlocker.ACCOUNT_LOCKED,
    RiderBalanceStatus.RECOVERING: BalanceLifecycleBlocker.ACCOUNT_RECOVERING,
    RiderBalanceStatus.REVOKED: BalanceLifecycleBlocker.ACCOUNT_REVOKED,
}

_STATUS_HEADLINES: dict[RiderBalanceStatus, str] = {
    RiderBalanceStatus.ACTIVE: "Boulder Roller Balance",
    RiderBalanceStatus.LOCKED: "Account security",
    RiderBalanceStatus.RECOVERING: "Account recovery",
    RiderBalanceStatus.REVOKED: "Balance inactive",
}

_STATUS_DETAILS: dict[RiderBalanceStatus, str] = {
    RiderBalanceStatus.ACTIVE: "Balance is ready for in-app actions.",
    RiderBalanceStatus.LOCKED: "New in-app Balance actions are paused while account security reviews this Balance.",
    RiderBalanceStatus.RECOVERING: "Account recovery is in progress. New in-app Balance actions are paused.",
    RiderBalanceStatus.REVOKED: "This Balance is no longer active. Set up a new Balance to continue.",
}

_ACTION_LABELS: dict[BalanceLifecycleAction, str] = {
    BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE: "Set up Balance",
    BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE_TOKEN: "Set up asset",
    BalanceLifecycleAction.ADD_FUNDS: "Add funds",
    BalanceLifecycleAction.USE_IN_BALANCE: "Use Balance",
    BalanceLifecycleAction.WITHDRAW_TO_WALLET: "Withdraw to wallet",
    BalanceLifecycleAction.ACCOUNT_SECURITY: "Account security",
}


@dataclass(frozen=True)
class BalanceTokenState:
    """One mint-scoped token account inside Boulder Roller Balance."""

    asset: str
    exists: bool
    balance_base_units: int | None = 0
    mint: str | None = None
    token_account: str | None = None
    source: str | None = None
    source_status: str | None = None
    slot: int | None = None


@dataclass(frozen=True)
class RiderBalanceLifecycle:
    """Already-read Balance account facts for one rider."""

    rider_account_id: str
    protocol_wallet: str
    initialized: bool
    status: RiderBalanceStatus = RiderBalanceStatus.ACTIVE
    token_accounts: Mapping[str, BalanceTokenState] = field(default_factory=dict)
    recovery_started_at: str | None = None
    revoked_at: str | None = None
    source_status: str | None = None


@dataclass(frozen=True)
class BalanceLifecycleStep:
    """Setup or boundary step a route/UI can present."""

    action_type: str
    rider_label: str
    asset: str | None = None
    step_up_required: bool = False


@dataclass(frozen=True)
class BalanceAssetView:
    """Reader-friendly asset row for Balance state surfaces."""

    asset: str
    exists: bool
    balance_base_units: int | None
    rider_state: str
    mint: str | None = None
    token_account: str | None = None
    source: str | None = None
    source_status: str = "not_initialized"
    slot: int | None = None


@dataclass(frozen=True)
class BalanceLifecyclePlan:
    """Complete lifecycle view for setup, visibility, and account state."""

    rider_account_id: str
    protocol_wallet: str
    status: RiderBalanceStatus
    initialized: bool
    rider_headline: str
    rider_detail: str
    no_prompt_execution_allowed: bool
    can_add_funds: bool
    can_withdraw_to_wallet: bool
    setup_steps: tuple[BalanceLifecycleStep, ...]
    assets: tuple[BalanceAssetView, ...]
    blockers: tuple[BalanceLifecycleBlocker, ...]


@dataclass(frozen=True)
class BalanceLifecycleDecision:
    """Decision for one lifecycle action."""

    action_type: str
    rider_label: str
    allowed: bool
    blockers: tuple[BalanceLifecycleBlocker, ...]
    step_up_required: bool
    boundary_action: bool
    rider_headline: str
    rider_detail: str


def describe_balance_lifecycle(
    lifecycle: RiderBalanceLifecycle,
    *,
    required_assets: Sequence[str] = DEFAULT_SETUP_ASSETS,
) -> BalanceLifecyclePlan:
    """Build the Balance lifecycle view from already-known account facts."""

    status = normalize_balance_status(lifecycle.status)
    normalized_assets = _normalize_assets(required_assets)
    blockers = no_prompt_lifecycle_blockers(status)
    lifecycle_source_status = _source_status(
        lifecycle.source_status,
        exists=lifecycle.initialized,
    )
    missing_assets = tuple(
        asset
        for asset in normalized_assets
        if _token_source_status(_token_for(lifecycle, asset)) == "not_initialized"
    )
    unavailable_assets = tuple(
        asset
        for asset in normalized_assets
        if _token_source_status(_token_for(lifecycle, asset)) == "unavailable"
    )
    setup_steps = _setup_steps(
        initialized=lifecycle.initialized or lifecycle_source_status == "unavailable",
        missing_assets=missing_assets,
    )
    chain_state_available = (
        lifecycle_source_status != "unavailable" and not unavailable_assets
    )
    active_and_initialized = (
        status is RiderBalanceStatus.ACTIVE
        and lifecycle.initialized
        and chain_state_available
    )
    no_prompt_allowed = active_and_initialized and not missing_assets
    can_add_funds = active_and_initialized and any(
        _token_for(lifecycle, asset).exists for asset in ("CAL", "USDC")
    )
    can_withdraw = active_and_initialized and any(
        token.exists
        and token.balance_base_units is not None
        and token.balance_base_units > 0
        for token in lifecycle.token_accounts.values()
    )

    if lifecycle_source_status == "unavailable" or unavailable_assets:
        blockers = blockers + (BalanceLifecycleBlocker.CHAIN_STATE_UNAVAILABLE,)
    if not lifecycle.initialized and lifecycle_source_status != "unavailable":
        blockers = blockers + (BalanceLifecycleBlocker.RIDER_BALANCE_REQUIRED,)
    if missing_assets:
        blockers = blockers + (BalanceLifecycleBlocker.TOKEN_ACCOUNT_REQUIRED,)

    unique_blockers = tuple(dict.fromkeys(blockers))
    return BalanceLifecyclePlan(
        rider_account_id=lifecycle.rider_account_id,
        protocol_wallet=lifecycle.protocol_wallet,
        status=status,
        initialized=lifecycle.initialized,
        rider_headline=_STATUS_HEADLINES[status],
        rider_detail=_detail_for(status, unique_blockers),
        no_prompt_execution_allowed=no_prompt_allowed,
        can_add_funds=can_add_funds,
        can_withdraw_to_wallet=can_withdraw,
        setup_steps=setup_steps,
        assets=tuple(_asset_view(lifecycle, asset) for asset in normalized_assets),
        blockers=unique_blockers,
    )


def prepare_balance_lifecycle_action(
    lifecycle: RiderBalanceLifecycle,
    *,
    action_type: BalanceLifecycleAction | str,
    asset: str,
    amount_base_units: int,
    step_up_satisfied: bool = False,
) -> BalanceLifecycleDecision:
    """Decide if a Balance lifecycle action may continue."""

    action = normalize_lifecycle_action(action_type)
    normalized_asset = normalize_asset(asset)
    status = normalize_balance_status(lifecycle.status)
    blockers: list[BalanceLifecycleBlocker] = list(no_prompt_lifecycle_blockers(status))
    lifecycle_source_status = _source_status(
        lifecycle.source_status,
        exists=lifecycle.initialized,
    )
    if lifecycle_source_status == "unavailable":
        blockers.append(BalanceLifecycleBlocker.CHAIN_STATE_UNAVAILABLE)

    if normalized_asset not in SUPPORTED_BALANCE_ASSETS:
        blockers.append(BalanceLifecycleBlocker.UNSUPPORTED_ASSET)
    if amount_base_units <= 0:
        blockers.append(BalanceLifecycleBlocker.ZERO_AMOUNT)
    if not lifecycle.initialized and lifecycle_source_status != "unavailable":
        blockers.append(BalanceLifecycleBlocker.RIDER_BALANCE_REQUIRED)

    token = _token_for(lifecycle, normalized_asset)
    token_source_status = _token_source_status(token)
    if token_source_status == "unavailable":
        blockers.append(BalanceLifecycleBlocker.CHAIN_STATE_UNAVAILABLE)
    elif not token.exists:
        blockers.append(BalanceLifecycleBlocker.TOKEN_ACCOUNT_REQUIRED)

    if action in (
        BalanceLifecycleAction.USE_IN_BALANCE,
        BalanceLifecycleAction.WITHDRAW_TO_WALLET,
    ):
        if (
            token.balance_base_units is not None
            and token.balance_base_units < amount_base_units
        ):
            blockers.append(BalanceLifecycleBlocker.INSUFFICIENT_BALANCE)

    step_up_required = action in (
        BalanceLifecycleAction.ADD_FUNDS,
        BalanceLifecycleAction.WITHDRAW_TO_WALLET,
    )
    if step_up_required and not step_up_satisfied:
        blockers.append(BalanceLifecycleBlocker.STEP_UP_REQUIRED)

    unique_blockers = tuple(dict.fromkeys(blockers))
    return BalanceLifecycleDecision(
        action_type=action.value,
        rider_label=_ACTION_LABELS[action],
        allowed=not unique_blockers,
        blockers=unique_blockers,
        step_up_required=step_up_required,
        boundary_action=step_up_required,
        rider_headline=_STATUS_HEADLINES[status],
        rider_detail=_detail_for(status, unique_blockers),
    )


def no_prompt_lifecycle_blockers(
    status: RiderBalanceStatus | str,
) -> tuple[BalanceLifecycleBlocker, ...]:
    """Return account-security blockers for no-prompt Balance execution."""

    normalized = normalize_balance_status(status)
    blocker = _STATUS_BLOCKERS.get(normalized)
    return (blocker,) if blocker is not None else ()


def balance_authority_active_for_status(status: RiderBalanceStatus | str) -> bool:
    """Whether app-balance, policy, delegate, or permissionless execution may run."""

    return not no_prompt_lifecycle_blockers(status)


def normalize_balance_status(status: RiderBalanceStatus | str) -> RiderBalanceStatus:
    try:
        return status if isinstance(status, RiderBalanceStatus) else RiderBalanceStatus(status)
    except ValueError as exc:
        raise ValueError(f"Unknown RiderBalance status: {status}") from exc


def normalize_lifecycle_action(action: BalanceLifecycleAction | str) -> BalanceLifecycleAction:
    try:
        return action if isinstance(action, BalanceLifecycleAction) else BalanceLifecycleAction(action)
    except ValueError as exc:
        raise ValueError(f"Unknown Balance lifecycle action: {action}") from exc


def normalize_asset(asset: str) -> str:
    return asset.strip().upper()


def _normalize_assets(assets: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(normalize_asset(asset) for asset in assets if asset.strip()))
    unsupported = [asset for asset in normalized if asset not in SUPPORTED_BALANCE_ASSETS]
    if unsupported:
        raise ValueError(f"Unsupported Balance asset(s): {', '.join(unsupported)}")
    return normalized


def _setup_steps(
    *,
    initialized: bool,
    missing_assets: Sequence[str],
) -> tuple[BalanceLifecycleStep, ...]:
    steps: list[BalanceLifecycleStep] = []
    if not initialized:
        steps.append(
            BalanceLifecycleStep(
                action_type=BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE.value,
                rider_label=_ACTION_LABELS[BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE],
            )
        )
    steps.extend(
        BalanceLifecycleStep(
            action_type=BalanceLifecycleAction.INITIALIZE_RIDER_BALANCE_TOKEN.value,
            rider_label=f"Set up {asset}",
            asset=asset,
        )
        for asset in missing_assets
    )
    return tuple(steps)


def _asset_view(lifecycle: RiderBalanceLifecycle, asset: str) -> BalanceAssetView:
    token = _token_for(lifecycle, asset)
    source_status = _token_source_status(token)
    if source_status == "unavailable":
        rider_state = "Unavailable"
    elif not token.exists:
        rider_state = "Needs setup"
    elif token.balance_base_units is not None and token.balance_base_units > 0:
        rider_state = "Available"
    else:
        rider_state = "Ready"
    return BalanceAssetView(
        asset=asset,
        exists=token.exists,
        balance_base_units=token.balance_base_units,
        rider_state=rider_state,
        mint=token.mint,
        token_account=token.token_account,
        source=token.source,
        source_status=source_status,
        slot=token.slot,
    )


def _detail_for(
    status: RiderBalanceStatus,
    blockers: Sequence[BalanceLifecycleBlocker],
) -> str:
    if BalanceLifecycleBlocker.CHAIN_STATE_UNAVAILABLE in blockers:
        return "Live Balance data is unavailable. Retry to refresh."
    if status is not RiderBalanceStatus.ACTIVE:
        return _STATUS_DETAILS[status]
    if BalanceLifecycleBlocker.RIDER_BALANCE_REQUIRED in blockers:
        return "Set up Boulder Roller Balance to use in-app actions."
    if BalanceLifecycleBlocker.TOKEN_ACCOUNT_REQUIRED in blockers:
        return "Set up missing assets before all in-app Balance actions are available."
    if BalanceLifecycleBlocker.STEP_UP_REQUIRED in blockers:
        return "Confirm this boundary action to continue."
    if blockers:
        return "Review this Balance action before continuing."
    return "Balance is ready."


def _token_for(lifecycle: RiderBalanceLifecycle, asset: str) -> BalanceTokenState:
    normalized_asset = normalize_asset(asset)
    token = lifecycle.token_accounts.get(normalized_asset)
    if token is None:
        return BalanceTokenState(asset=normalized_asset, exists=False)
    return token


def _source_status(source_status: str | None, *, exists: bool) -> str:
    normalized = source_status or ("live" if exists else "not_initialized")
    if normalized not in ("live", "not_initialized", "unavailable"):
        raise ValueError(f"Unknown Balance source status: {normalized}")
    return normalized


def _token_source_status(token: BalanceTokenState) -> str:
    return _source_status(token.source_status, exists=token.exists)
