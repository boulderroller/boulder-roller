"""Route-level Balance operation adapters for vault actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .balance_transaction_coordinator import BalanceOperationIntent
from .boulder_balance_authority import AuthorityModel


class BalanceRouteAdapter(str, Enum):
    """Concrete route adapter selected before transaction submission."""

    ADD_FUNDS_TO_BALANCE = "add_funds_to_balance"
    COLLECT_DUNG_FOR_RIDER = "collect_stake_rewards_for"
    DEPOSIT_CAL_FROM_BALANCE = "deposit_cal_from_balance"
    WITHDRAW_CAL_TO_BALANCE = "withdraw_cal_to_balance"
    WITHDRAW_TO_WALLET = "withdraw_to_wallet"
    WALLET_BOUNDARY_FALLBACK = "wallet_boundary_fallback"


@dataclass(frozen=True)
class VaultBalanceRouteScope:
    """Shared route facts needed to prepare a Balance operation intent."""

    rider_account_id: str
    protocol_wallet: str
    vault_id: int
    vault_signature: str | None = None
    prepared_message_hash: str | None = None
    tx_signature: str | None = None
    client_request_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioBalanceRouteScope:
    """Shared route facts needed to prepare a portfolio Balance operation."""

    rider_account_id: str
    protocol_wallet: str
    prepared_message_hash: str | None = None
    tx_signature: str | None = None
    client_request_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


def add_funds_intent(
    *,
    scope: PortfolioBalanceRouteScope,
    asset: str,
    amount: str,
    destination: str,
) -> BalanceOperationIntent:
    """Prepare Add funds as an explicit wallet-boundary operation."""

    normalized_asset = asset.strip().upper()
    return _portfolio_intent(
        scope=scope,
        action_type="add_funds",
        asset=normalized_asset,
        amount=amount,
        source=f"wallet:{scope.protocol_wallet}:{normalized_asset.lower()}",
        destination=destination,
        adapter=BalanceRouteAdapter.ADD_FUNDS_TO_BALANCE,
    )


def withdraw_to_wallet_intent(
    *,
    scope: PortfolioBalanceRouteScope,
    asset: str,
    amount: str,
    source: str,
) -> BalanceOperationIntent:
    """Prepare Withdraw to wallet as an explicit wallet-boundary operation."""

    normalized_asset = asset.strip().upper()
    return _portfolio_intent(
        scope=scope,
        action_type="withdraw_to_wallet",
        asset=normalized_asset,
        amount=amount,
        source=source,
        destination=f"wallet:{scope.protocol_wallet}:{normalized_asset.lower()}",
        adapter=BalanceRouteAdapter.WITHDRAW_TO_WALLET,
    )


def collect_dung_intent(
    *,
    scope: VaultBalanceRouteScope,
    amount: str,
    destination: str,
    fee_payer: str | None = None,
) -> BalanceOperationIntent:
    """Prepare permissionless-for-rider Collect DUNG operation scope."""

    return _intent(
        scope=scope,
        action_type="collect_dung",
        authority_model=AuthorityModel.PERMISSIONLESS_FOR_RIDER,
        asset="DUNG",
        amount=amount,
        source=f"vault:{scope.vault_id}:stake_rewards",
        destination=destination,
        fee_payer=fee_payer,
        adapter=BalanceRouteAdapter.COLLECT_DUNG_FOR_RIDER,
        boundary_fallback=False,
        operation_metadata={
            "destination_type": "spl_wallet_ata",
            "destination_owner": scope.protocol_wallet,
        },
    )


def deposit_cal_intent(
    *,
    scope: VaultBalanceRouteScope,
    amount: str,
    use_balance: bool = False,
    rider_session_id: str | None = None,
) -> BalanceOperationIntent:
    """Prepare Deposit CAL scope for rider-session or wallet execution."""

    if use_balance:
        session_id = _require_rider_session_id(rider_session_id)
        return _intent(
            scope=scope,
            action_type="deposit_cal",
            authority_model=AuthorityModel.RIDER_SESSION,
            asset="CAL",
            amount=amount,
            source="RiderBalance CAL token PDA",
            destination=f"vault:{scope.vault_id}:cal_escrow",
            adapter=BalanceRouteAdapter.DEPOSIT_CAL_FROM_BALANCE,
            boundary_fallback=False,
            policy_or_delegate_id=session_id,
            operation_metadata={"rider_session_id": session_id},
        )

    return _intent(
        scope=scope,
        action_type="deposit_cal",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        asset="CAL",
        amount=amount,
        source=scope.protocol_wallet,
        destination=f"vault:{scope.vault_id}:cal_escrow",
        adapter=BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK,
        boundary_fallback=True,
        step_up_satisfied=True,
    )


def withdraw_cal_intent(
    *,
    scope: VaultBalanceRouteScope,
    amount: str,
    use_balance: bool = False,
    rider_session_id: str | None = None,
) -> BalanceOperationIntent:
    """Prepare Withdraw CAL scope for rider-session or wallet execution."""

    if use_balance:
        session_id = _require_rider_session_id(rider_session_id)
        return _intent(
            scope=scope,
            action_type="withdraw_cal",
            authority_model=AuthorityModel.RIDER_SESSION,
            asset="LP",
            amount=amount,
            source=f"vault:{scope.vault_id}:balance_lp",
            destination="RiderBalance CAL token PDA",
            adapter=BalanceRouteAdapter.WITHDRAW_CAL_TO_BALANCE,
            boundary_fallback=False,
            policy_or_delegate_id=session_id,
            operation_metadata={"rider_session_id": session_id},
        )

    return _intent(
        scope=scope,
        action_type="withdraw_cal",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        asset="LP",
        amount=amount,
        source=f"vault:{scope.vault_id}:lp",
        destination=f"wallet:{scope.protocol_wallet}:cal",
        adapter=BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK,
        boundary_fallback=True,
        step_up_satisfied=True,
    )


def create_vault_intent(
    *,
    scope: VaultBalanceRouteScope,
    amount: str,
    payment_method: str,
    destination: str,
) -> BalanceOperationIntent:
    """Prepare Create Vault scope for wallet-boundary execution."""

    return _intent(
        scope=scope,
        action_type="create_vault",
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        asset="CAL+USDC" if payment_method == "cal_usdc" else "DUNG",
        amount=amount,
        source=scope.protocol_wallet,
        destination=destination,
        adapter=BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK,
        boundary_fallback=True,
        step_up_satisfied=True,
    )


def _intent(
    *,
    scope: VaultBalanceRouteScope,
    action_type: str,
    authority_model: AuthorityModel,
    asset: str,
    amount: str,
    source: str,
    destination: str,
    adapter: BalanceRouteAdapter,
    boundary_fallback: bool,
    fee_payer: str | None = None,
    policy_or_delegate_id: str | None = None,
    step_up_satisfied: bool = False,
    operation_metadata: Mapping[str, str] | None = None,
) -> BalanceOperationIntent:
    metadata = {
        "vault_id": str(scope.vault_id),
        "adapter": adapter.value,
        "boundary_fallback": str(boundary_fallback).lower(),
        **dict(scope.metadata),
        **dict(operation_metadata or {}),
    }
    if scope.vault_signature:
        metadata["vault_signature"] = scope.vault_signature
    if scope.client_request_id:
        metadata["client_request_id"] = scope.client_request_id

    idempotency_tail = scope.client_request_id or scope.prepared_message_hash or "unbound"

    return BalanceOperationIntent(
        action_type=action_type,
        authority_model=authority_model,
        rider_account_id=scope.rider_account_id,
        protocol_wallet=scope.protocol_wallet,
        idempotency_key=(
            f"{action_type}:{scope.protocol_wallet}:{scope.vault_id}:"
            f"{adapter.value}:{asset}:{amount}:{idempotency_tail}"
        ),
        asset=asset,
        amount=amount,
        source=source,
        destination=destination,
        reference_type="vault",
        reference_id=str(scope.vault_id),
        prepared_message_hash=scope.prepared_message_hash,
        fee_payer=fee_payer,
        policy_or_delegate_id=policy_or_delegate_id,
        tx_signature=scope.tx_signature,
        step_up_satisfied=step_up_satisfied,
        metadata=metadata,
    )


def _require_rider_session_id(value: str | None) -> str:
    session_id = (value or "").strip()
    if not session_id:
        raise ValueError("Balance-funded Vault actions require a rider_session_id")
    return session_id


def _portfolio_intent(
    *,
    scope: PortfolioBalanceRouteScope,
    action_type: str,
    asset: str,
    amount: str,
    source: str,
    destination: str,
    adapter: BalanceRouteAdapter,
) -> BalanceOperationIntent:
    metadata = {
        "surface": "portfolio_balance",
        "adapter": adapter.value,
        "boundary_fallback": "false",
        **dict(scope.metadata),
    }
    if scope.client_request_id:
        metadata["client_request_id"] = scope.client_request_id

    idempotency_tail = scope.client_request_id or scope.prepared_message_hash or "prepared"
    return BalanceOperationIntent(
        action_type=action_type,
        authority_model=AuthorityModel.WALLET_BOUNDARY,
        rider_account_id=scope.rider_account_id,
        protocol_wallet=scope.protocol_wallet,
        idempotency_key=(
            f"{action_type}:{scope.protocol_wallet}:{asset}:{amount}:"
            f"{adapter.value}:{idempotency_tail}"
        ),
        asset=asset,
        amount=amount,
        source=source,
        destination=destination,
        reference_type="portfolio_balance",
        reference_id=asset.lower(),
        prepared_message_hash=scope.prepared_message_hash,
        tx_signature=scope.tx_signature,
        step_up_satisfied=True,
        metadata=metadata,
    )
