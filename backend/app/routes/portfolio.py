from __future__ import annotations

from ..services.privacy_logging import scrub_log_text
import asyncio
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from solders.transaction import Transaction

from .. import solana_direct
from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository, VaultRepository
from ..services.balance_route_adapters import (
    PortfolioBalanceRouteScope,
    add_funds_intent,
    withdraw_to_wallet_intent,
)
from ..services.balance_transaction_coordinator import (
    BalanceActionBudgetExceeded,
    BalanceOperationError,
    BalanceOperationRecord,
    BalanceTransactionCoordinator,
    SupabaseBalanceOperationSink,
    prepared_message_hash,
)
from ..services.balance_transaction_submission import (
    BalanceSubmissionError,
    submit_confirmed_balance_transaction,
)
from ..services.balance_lifecycle import (
    BalanceLifecycleAction,
    BalanceTokenState,
    RiderBalanceLifecycle,
    RiderBalanceStatus,
    describe_balance_lifecycle,
    normalize_asset,
    prepare_balance_lifecycle_action,
)
from ..services.collection_snapshot import get_collection_snapshot
from ..services.balance_production_rollout import is_balance_action_enabled
from ..services.tx_builder import BuildTxResult, get_tx_builder
from ..token_amounts import (
    TokenAmountError,
    base_units_to_units,
    exact_token_amount,
    parse_base_units,
    require_base_units_string,
    units_to_base_units,
)
from .distributions import get_my_distributions

router = APIRouter()
logger = logging.getLogger(__name__)

BALANCE_LIFECYCLE_ASSETS = ("CAL", "USDC", "DUNG")
BALANCE_FUNDING_ASSETS = ("CAL", "USDC")
BALANCE_WITHDRAW_ASSETS = ("CAL", "USDC", "DUNG")


def _require_balance_rollout_action(action: str) -> None:
    if is_balance_action_enabled(action):
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="This Balance action is not open yet.",
    )


class _ExactBaseUnitsRequest(BaseModel):
    amount_base_units: str

    @field_validator("amount_base_units", mode="before")
    @classmethod
    def validate_amount_base_units(cls, value: object) -> str:
        try:
            return require_base_units_string(value, allow_zero=False)
        except TokenAmountError as exc:
            raise ValueError(str(exc)) from exc

    @property
    def amount_base_units_int(self) -> int:
        return parse_base_units(self.amount_base_units, allow_zero=False)


class BalanceAddFundsPrepareRequest(_ExactBaseUnitsRequest):
    asset: str = Field(..., min_length=1, max_length=12)


class BalanceAddFundsSubmitRequest(BalanceAddFundsPrepareRequest):
    signed_transaction: str = Field(..., min_length=1)
    last_valid_block_height: int = Field(..., gt=0)
    client_request_id: Optional[str] = Field(default=None, min_length=1, max_length=120)


class BalanceWithdrawToWalletPrepareRequest(_ExactBaseUnitsRequest):
    asset: str = Field(..., min_length=1, max_length=12)


class BalanceWithdrawToWalletSubmitRequest(BalanceWithdrawToWalletPrepareRequest):
    signed_transaction: str = Field(..., min_length=1)
    last_valid_block_height: int = Field(..., gt=0)
    client_request_id: Optional[str] = Field(default=None, min_length=1, max_length=120)


def _build_balance_lifecycle_view(
    current_user: AuthenticatedUser,
    *,
    balance_snapshot: object | None,
    balance_dung_source: object | None,
) -> dict:
    lifecycle, source_metadata = _balance_lifecycle_from_sources(
        current_user,
        balance_snapshot=balance_snapshot,
        balance_dung_source=balance_dung_source,
    )
    plan = asdict(
        describe_balance_lifecycle(
            lifecycle,
            required_assets=BALANCE_LIFECYCLE_ASSETS,
        )
    )
    for asset in plan["assets"]:
        amount = asset["balance_base_units"]
        asset["balance_base_units"] = str(amount) if amount is not None else None
    plan.update(source_metadata)
    source_statuses = [
        str(source_metadata["source_status"]),
        *(str(asset["source_status"]) for asset in plan["assets"]),
    ]
    plan["projection_status"] = (
        "delayed" if "unavailable" in source_statuses else "recorded"
    )
    return plan


def _balance_token_state(asset: str, source: object | None) -> BalanceTokenState:
    if source is None:
        return BalanceTokenState(
            asset=asset,
            exists=False,
            balance_base_units=None,
            source="rider_balance_token_pda",
            source_status="unavailable",
        )

    source_status = str(getattr(source, "status"))
    if source_status not in ("live", "not_initialized", "unavailable"):
        raise ValueError(f"Unsupported {asset} Balance source status: {source_status}")
    exists = bool(getattr(source, "exists"))
    if (source_status == "live") != exists:
        raise ValueError(f"Inconsistent {asset} Balance source existence")
    amount_base_units = None
    if source_status != "unavailable":
        amount_base_units = parse_base_units(
            getattr(source, "amount_base_units"),
            field_name=f"balance_{asset.lower()}_base_units",
        )
    return BalanceTokenState(
        asset=asset,
        exists=exists,
        balance_base_units=amount_base_units,
        mint=str(getattr(source, "mint", None)) if getattr(source, "mint", None) else None,
        token_account=(
            str(getattr(source, "token_account"))
            if getattr(source, "token_account", None)
            else None
        ),
        source=str(getattr(source, "source")),
        source_status=source_status,
        slot=(
            int(getattr(source, "slot"))
            if getattr(source, "slot", None) is not None
            else None
        ),
    )


def _balance_lifecycle_from_sources(
    current_user: AuthenticatedUser,
    *,
    balance_snapshot: object | None,
    balance_dung_source: object | None,
) -> tuple[RiderBalanceLifecycle, dict]:
    if balance_snapshot is None:
        initialized = False
        status = RiderBalanceStatus.ACTIVE
        source_status = "unavailable"
        token_accounts = {
            "CAL": _balance_token_state("CAL", None),
            "USDC": _balance_token_state("USDC", None),
        }
        source_metadata = {
            "source": "rider_balance_header_pda",
            "source_status": "unavailable",
            "account": None,
            "slot": None,
            "authority_model": None,
            "policy_hash": None,
            "delegate_authority": None,
            "last_authority_rotation_at": None,
            "revoked_at": None,
            "program_config_account": None,
            "program_config_slot": None,
        }
    else:
        header = getattr(balance_snapshot, "header")
        initialized = bool(getattr(header, "initialized"))
        header_status = getattr(header, "status", None)
        status = RiderBalanceStatus(header_status or RiderBalanceStatus.ACTIVE.value)
        source_status = str(getattr(header, "source_status"))
        token_accounts = {
            "CAL": _balance_token_state("CAL", getattr(balance_snapshot, "cal")),
            "USDC": _balance_token_state("USDC", getattr(balance_snapshot, "usdc")),
        }
        source_metadata = {
            "source": str(getattr(header, "source")),
            "source_status": source_status,
            "account": str(getattr(header, "account")),
            "slot": int(getattr(header, "slot")),
            "authority_model": getattr(header, "authority_model", None),
            "policy_hash": getattr(header, "policy_hash", None),
            "delegate_authority": getattr(header, "delegate_authority", None),
            "last_authority_rotation_at": getattr(
                header,
                "last_authority_rotation_at",
                None,
            ),
            "revoked_at": getattr(header, "revoked_at", None),
            "program_config_account": str(
                getattr(balance_snapshot, "program_config_account")
            ),
            "program_config_slot": int(
                getattr(balance_snapshot, "program_config_slot")
            ),
        }

    token_accounts["DUNG"] = _balance_token_state("DUNG", balance_dung_source)
    return (
        RiderBalanceLifecycle(
            rider_account_id=current_user.user_id,
            protocol_wallet=current_user.wallet,
            initialized=initialized,
            status=status,
            token_accounts=token_accounts,
            source_status=source_status,
        ),
        source_metadata,
    )


def _dung_source_view(source: object) -> tuple[int, dict]:
    amount_base_units = parse_base_units(
        getattr(source, "amount_base_units"),
        field_name="dung_balance_base_units",
    )
    source_status = str(getattr(source, "status"))
    if source_status not in ("live", "not_initialized"):
        raise ValueError(f"Unsupported DUNG source status: {source_status}")
    return amount_base_units, {
        "amount": base_units_to_units(amount_base_units),
        "amount_base_units": str(amount_base_units),
        "source": str(getattr(source, "source")),
        "status": source_status,
        "token_account": str(getattr(source, "token_account")),
        "slot": int(getattr(source, "slot")),
    }


def _unavailable_dung_source_view(source: str) -> dict:
    return {
        "amount": None,
        "amount_base_units": None,
        "source": source,
        "status": "unavailable",
        "token_account": None,
        "slot": None,
    }


def _normalize_funding_asset(asset: str) -> str:
    normalized = normalize_asset(asset)
    if normalized not in BALANCE_FUNDING_ASSETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add funds supports CAL and USDC.",
        )
    return normalized


def _normalize_withdraw_asset(asset: str) -> str:
    normalized = normalize_asset(asset)
    if normalized not in BALANCE_WITHDRAW_ASSETS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Withdraw to wallet supports CAL, USDC, and DUNG.",
        )
    return normalized


async def _balance_lifecycle_for_action(
    current_user: AuthenticatedUser,
    *,
    asset: str,
) -> RiderBalanceLifecycle:
    snapshot_task = asyncio.create_task(
        solana_direct.get_rider_balance_account_snapshot(current_user.wallet)
    )
    dung_task = (
        asyncio.create_task(
            solana_direct.get_balance_dung_balance_source(current_user.wallet)
        )
        if asset == "DUNG"
        else None
    )

    balance_snapshot: object | None = None
    try:
        balance_snapshot = await snapshot_task
    except Exception as exc:
        logger.warning("Failed to load RiderBalance for Balance action: %s", exc)

    balance_dung_source: object | None = None
    if dung_task is not None:
        try:
            balance_dung_source = await dung_task
        except Exception as exc:
            logger.warning("Failed to load Balance DUNG for Balance action: %s", exc)

    lifecycle, _ = _balance_lifecycle_from_sources(
        current_user,
        balance_snapshot=balance_snapshot,
        balance_dung_source=balance_dung_source,
    )
    return lifecycle


def _balance_coordinator(repo: DatabaseRepository) -> BalanceTransactionCoordinator:
    client = getattr(repo, "client", None)
    sink = SupabaseBalanceOperationSink(client) if client is not None else None
    return BalanceTransactionCoordinator(sink=sink, budget_store=sink)


def _balance_operation_http_exception(exc: BalanceOperationError, detail: str) -> HTTPException:
    if isinstance(exc, BalanceActionBudgetExceeded):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.rider_message,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )


def _decode_signed_transaction_or_400(signed_transaction: str) -> Transaction:
    try:
        return get_tx_builder().decode_signed_transaction(signed_transaction)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read wallet confirmation.",
        ) from exc


def _assert_signed_transaction_matches(
    signed_tx: Transaction,
    expected_result: BuildTxResult,
) -> None:
    expected_tx = Transaction.from_bytes(base64.b64decode(expected_result.transaction))
    if signed_tx.message_data() != expected_tx.message_data():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet confirmation does not match the prepared action.",
        )


def _signed_transaction_signature(signed_tx: Transaction) -> str:
    if not signed_tx.signatures:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet confirmation has no transaction signature.",
        )
    return str(signed_tx.signatures[0])


def _prepared_balance_response(
    *,
    action_type: str,
    rider_label: str,
    asset: str,
    amount_base_units: int,
    rider_state: str,
    rider_detail: str,
    next_step: str,
    prepared_transaction: BuildTxResult | None = None,
    operation: BalanceOperationRecord | None = None,
    blockers: tuple[object, ...] = (),
) -> dict:
    return {
        "contractVersion": "portfolio_balance_action.v2",
        "action_type": action_type,
        "rider_label": rider_label,
        "asset": asset,
        "amount_base_units": str(amount_base_units),
        "rider_state": rider_state,
        "rider_detail": rider_detail,
        "next_step": next_step,
        "blockers": [
            getattr(blocker, "value", str(blocker))
            for blocker in blockers
        ],
        "prepared_transaction": asdict(prepared_transaction) if prepared_transaction else None,
        "operation": operation.to_row() if operation else None,
    }


async def _build_add_funds_transaction(
    *,
    current_user: AuthenticatedUser,
    asset: str,
    amount_base_units: int,
    blockhash=None,
) -> BuildTxResult:
    try:
        return await get_tx_builder().build_add_funds_to_balance_tx(
            user_wallet=current_user.wallet,
            asset=asset,
            amount=amount_base_units,
            blockhash=blockhash,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


async def _build_withdraw_to_wallet_transaction(
    *,
    current_user: AuthenticatedUser,
    asset: str,
    amount_base_units: int,
    blockhash=None,
) -> BuildTxResult:
    try:
        return await get_tx_builder().build_withdraw_to_wallet_tx(
            user_wallet=current_user.wallet,
            asset=asset,
            amount=amount_base_units,
            blockhash=blockhash,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _normalize_staked_positions(rows: list[dict]) -> tuple[list[dict], int, int]:
    positions: list[dict] = []
    total_staked_base_units = 0
    total_rewards_base_units = 0

    for row in rows:
        cal_staked = exact_token_amount(
            row.get("cal_staked") or 0,
            field_name="cal_staked",
        )
        lp_tokens = parse_base_units(
            row.get("lp_tokens") or 0,
            field_name="lp_tokens",
        )
        rewards_earned = exact_token_amount(
            row.get("rewards_earned") or 0,
            field_name="rewards_earned",
        )
        positions.append(
            {
                **row,
                "subjectStates": {},
                "cal_staked": cal_staked.base_units,
                "lp_tokens": str(lp_tokens),
                "rewards_earned": rewards_earned.base_units,
                "cal_deposited": cal_staked.units,
                "cal_deposited_base_units": cal_staked.base_units,
                "dung_ready": None,
                "dung_ready_base_units": None,
            }
        )
        total_staked_base_units += int(cal_staked.base_units)
        total_rewards_base_units += int(rewards_earned.base_units)

    return positions, total_staked_base_units, total_rewards_base_units


async def _load_portfolio_core(
    current_user: AuthenticatedUser,
    repo: DatabaseRepository,
) -> dict:
    collection_task = asyncio.create_task(get_collection_snapshot(current_user.wallet))
    claims_task = asyncio.create_task(repo.get_user_claims(current_user.user_id))
    vault_repo = VaultRepository(repo.client)
    vault_stakes_task = asyncio.create_task(vault_repo.get_wallet_stakes(current_user.wallet))
    cal_balance_task = asyncio.create_task(
        solana_direct.get_wallet_cal_balance_source(current_user.wallet)
    )
    wallet_dung_task = asyncio.create_task(
        solana_direct.get_wallet_dung_balance_source(current_user.wallet)
    )
    balance_dung_task = asyncio.create_task(
        solana_direct.get_balance_dung_balance_source(current_user.wallet)
    )
    balance_snapshot_task = asyncio.create_task(
        solana_direct.get_rider_balance_account_snapshot(current_user.wallet)
    )

    cal_balance_base_units = 0
    cal_status = "unavailable"
    cal_source = None
    try:
        cal_balance_base_units = parse_base_units(
            (cal_source := await cal_balance_task).amount_base_units,
            field_name="cal_balance_base_units",
        )
        cal_status = cal_source.status
    except Exception as exc:
        cal_status = "unavailable"
        cal_source = None
        logger.warning("Failed to load SPL CAL balance for portfolio: %s", exc)

    wallet_dung = _unavailable_dung_source_view("spl_wallet_ata")
    try:
        _, wallet_dung = _dung_source_view(await wallet_dung_task)
    except Exception as exc:
        logger.warning("Failed to load wallet DUNG token account for portfolio: %s", scrub_log_text(exc))

    balance_dung_source: object | None = None
    balance_dung = _unavailable_dung_source_view("rider_balance_token_pda")
    try:
        balance_dung_source = await balance_dung_task
        _, balance_dung = _dung_source_view(balance_dung_source)
    except Exception as exc:
        logger.warning("Failed to load Balance DUNG token account for portfolio: %s", exc)

    balance_snapshot: object | None = None
    try:
        balance_snapshot = await balance_snapshot_task
    except Exception as exc:
        logger.warning("Failed to load RiderBalance account snapshot for portfolio: %s", exc)

    vault_stakes, claims = await asyncio.gather(
        vault_stakes_task,
        claims_task,
    )
    balance_header_status = (
        str(getattr(getattr(balance_snapshot, "header"), "source_status"))
        if balance_snapshot is not None
        else "unavailable"
    )
    balance_cal_status = (
        str(getattr(getattr(balance_snapshot, "cal"), "status"))
        if balance_snapshot is not None
        else "unavailable"
    )
    balance_usdc_status = (
        str(getattr(getattr(balance_snapshot, "usdc"), "status"))
        if balance_snapshot is not None
        else "unavailable"
    )
    chain_status = "unavailable" if "unavailable" in (
        cal_status,
        wallet_dung["status"],
        balance_dung["status"],
        balance_header_status,
        balance_cal_status,
        balance_usdc_status,
    ) else "live"
    staked_positions, total_staked_base_units, weekly_yield_base_units = (
        _normalize_staked_positions(vault_stakes)
    )
    collection_snapshot = None
    try:
        collection_snapshot = await collection_task
    except Exception as exc:
        logger.warning("Failed to load collection snapshot: %s", exc)
    ready_by_vault = {
        row["vaultId"]: row["dungReadyBaseUnits"]
        for row in (collection_snapshot or {}).get("positions", [])
    }
    for position in staked_positions:
        ready = ready_by_vault.get(position["vault_id"])
        position["dung_ready_base_units"] = ready
        position["dung_ready"] = base_units_to_units(int(ready)) if ready is not None else None
    total_staked = exact_token_amount(
        total_staked_base_units,
        field_name="total_staked",
    )
    weekly_yield = exact_token_amount(
        weekly_yield_base_units,
        field_name="weekly_yield",
    )
    harvest_fee_bps = int(
        getattr(balance_snapshot, "harvest_fee_bps", solana_direct.HARVEST_FEE_BPS)
    )
    exit_fee_bps = int(
        getattr(balance_snapshot, "exit_fee_bps", solana_direct.EXIT_FEE_BPS)
    )

    return {
        "contractVersion": "portfolio.v5",
        "collectionSnapshot": collection_snapshot,
        "dung_balance": wallet_dung["amount"],
        "dung_balance_base_units": wallet_dung["amount_base_units"],
        "wallet_dung": wallet_dung,
        "balance_dung": balance_dung,
        "cal_balance": base_units_to_units(cal_balance_base_units),
        "cal_balance_base_units": str(cal_balance_base_units),
        "balance_lifecycle": _build_balance_lifecycle_view(
            current_user,
            balance_snapshot=balance_snapshot,
            balance_dung_source=balance_dung_source,
        ),
        "staked_positions": staked_positions,
        "pending_claims": claims,
        "total_claims": len(claims),
        "total_staked": total_staked.units,
        "total_staked_base_units": total_staked.base_units,
        "weekly_yield": weekly_yield.units,
        "weekly_yield_base_units": weekly_yield.base_units,
        "harvest_fee_bps": str(harvest_fee_bps),
        "exit_fee_bps": str(exit_fee_bps),
        "total_yield": weekly_yield.units,
        "total_yield_base_units": weekly_yield.base_units,
        "claims": claims,
        "freshness": {
            "source": "backend",
            "chainStatus": chain_status,
            "calStatus": cal_status,
            "calAccountExists": cal_source.exists if cal_source is not None else None,
            "calAccountSlot": cal_source.slot if cal_source is not None else None,
            "walletDungStatus": wallet_dung["status"],
            "balanceDungStatus": balance_dung["status"],
            "balanceHeaderStatus": balance_header_status,
            "balanceCalStatus": balance_cal_status,
            "balanceUsdcStatus": balance_usdc_status,
            "balanceLifecycleSource": "rider_balance_header_pda",
            "balanceLifecycleSlot": (
                int(getattr(getattr(balance_snapshot, "header"), "slot"))
                if balance_snapshot is not None
                else None
            ),
            "loadedAt": datetime.now(timezone.utc).isoformat(),
        },
    }


@router.get("")
async def get_portfolio(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Return a simple portfolio summary based on the user's claims.
    """
    return await _load_portfolio_core(current_user, repo)


@router.get("/snapshot")
async def get_portfolio_snapshot(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """One account-sheet economy snapshot: balances, backing, and receipts."""
    portfolio, distributions = await asyncio.gather(
        _load_portfolio_core(current_user, repo),
        get_my_distributions(limit=limit, offset=offset, current_user=current_user, repo=repo),
    )
    return {
        "contractVersion": "portfolio_snapshot.v4",
        "portfolio": portfolio,
        "distributions": distributions.model_dump(mode="json"),
        "freshness": {
            **portfolio.get("freshness", {}),
            "distributionCount": distributions.distribution_count,
            "receiptCount": distributions.receipt_count,
        },
    }


@router.post("/balance/add-funds/prepare")
async def prepare_balance_add_funds(
    payload: BalanceAddFundsPrepareRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Prepare a wallet-confirmed Add funds action for Boulder Roller Balance."""
    _require_balance_rollout_action("add_funds")
    asset = _normalize_funding_asset(payload.asset)
    amount_base_units = payload.amount_base_units_int
    lifecycle = await _balance_lifecycle_for_action(
        current_user,
        asset=asset,
    )
    decision = prepare_balance_lifecycle_action(
        lifecycle,
        action_type=BalanceLifecycleAction.ADD_FUNDS,
        asset=asset,
        amount_base_units=amount_base_units,
        step_up_satisfied=True,
    )
    if not decision.allowed:
        return _prepared_balance_response(
            action_type=decision.action_type,
            rider_label=decision.rider_label,
            asset=asset,
            amount_base_units=amount_base_units,
            rider_state="Needs setup",
            rider_detail=decision.rider_detail,
            next_step="finish_setup",
            blockers=decision.blockers,
        )

    try:
        prepared = await _build_add_funds_transaction(
            current_user=current_user,
            asset=asset,
            amount_base_units=amount_base_units,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            return _prepared_balance_response(
                action_type=decision.action_type,
                rider_label=decision.rider_label,
                asset=asset,
                amount_base_units=amount_base_units,
                rider_state="Needs setup",
                rider_detail=str(exc.detail),
                next_step="finish_setup",
            )
        raise
    return _prepared_balance_response(
        action_type=decision.action_type,
        rider_label=decision.rider_label,
        asset=asset,
        amount_base_units=amount_base_units,
        rider_state="Pending",
        rider_detail="Confirm in wallet to continue.",
        next_step="confirm_wallet",
        prepared_transaction=prepared,
    )


@router.post("/balance/add-funds")
async def submit_balance_add_funds(
    payload: BalanceAddFundsSubmitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Submit a wallet-confirmed Add funds action and record coordinator state."""
    _require_balance_rollout_action("add_funds")
    asset = _normalize_funding_asset(payload.asset)
    amount_base_units = payload.amount_base_units_int
    lifecycle = await _balance_lifecycle_for_action(
        current_user,
        asset=asset,
    )
    decision = prepare_balance_lifecycle_action(
        lifecycle,
        action_type=BalanceLifecycleAction.ADD_FUNDS,
        asset=asset,
        amount_base_units=amount_base_units,
        step_up_satisfied=True,
    )
    if not decision.allowed:
        return _prepared_balance_response(
            action_type=decision.action_type,
            rider_label=decision.rider_label,
            asset=asset,
            amount_base_units=amount_base_units,
            rider_state="Needs setup",
            rider_detail=decision.rider_detail,
            next_step="finish_setup",
            blockers=decision.blockers,
        )

    signed_tx = _decode_signed_transaction_or_400(payload.signed_transaction)
    expected = await _build_add_funds_transaction(
        current_user=current_user,
        asset=asset,
        amount_base_units=amount_base_units,
        blockhash=signed_tx.message.recent_blockhash,
    )
    _assert_signed_transaction_matches(signed_tx, expected)

    coordinator = _balance_coordinator(repo)
    operation: BalanceOperationRecord | None = None
    try:
        scope = PortfolioBalanceRouteScope(
            rider_account_id=current_user.user_id,
            protocol_wallet=current_user.wallet,
            prepared_message_hash=prepared_message_hash(expected.transaction),
            tx_signature=_signed_transaction_signature(signed_tx),
            client_request_id=payload.client_request_id,
            metadata={
                "asset": asset,
                "last_valid_block_height": str(payload.last_valid_block_height),
            },
        )
        operation = coordinator.prepare_operation(
            add_funds_intent(
                scope=scope,
                asset=asset,
                amount=str(amount_base_units),
                destination=expected.pda or "Boulder Roller Balance",
            )
        )
        submission = await submit_confirmed_balance_transaction(
            builder=get_tx_builder(),
            coordinator=coordinator,
            operation=operation,
            transaction_b64=payload.signed_transaction,
            last_valid_block_height=payload.last_valid_block_height,
        )
        operation = submission.operation
    except BalanceOperationError as exc:
        raise _balance_operation_http_exception(
            exc,
            "Boulder Roller could not prepare Add funds. Please try again.",
        ) from exc
    except BalanceSubmissionError as exc:
        logger.error("[PortfolioBalance] Add funds did not confirm: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Boulder Roller could not finish Add funds. Please try again.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[PortfolioBalance] Add funds failed: %s", exc, exc_info=True)
        if operation is not None:
            coordinator.mark_failed(operation, reason="add_funds_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Boulder Roller could not finish Add funds. Please try again.",
        ) from exc

    return _prepared_balance_response(
        action_type=decision.action_type,
        rider_label=decision.rider_label,
        asset=asset,
        amount_base_units=amount_base_units,
        rider_state=operation.rider_state or "Pending",
        rider_detail="Add funds saved. Balance is refreshing.",
        next_step="pending",
        operation=operation,
    )


@router.post("/balance/withdraw-to-wallet/prepare")
async def prepare_balance_withdraw_to_wallet(
    payload: BalanceWithdrawToWalletPrepareRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Prepare a wallet-confirmed Withdraw to wallet action."""
    _require_balance_rollout_action("withdraw_to_wallet")
    asset = _normalize_withdraw_asset(payload.asset)
    amount_base_units = payload.amount_base_units_int
    lifecycle = await _balance_lifecycle_for_action(
        current_user,
        asset=asset,
    )
    decision = prepare_balance_lifecycle_action(
        lifecycle,
        action_type=BalanceLifecycleAction.WITHDRAW_TO_WALLET,
        asset=asset,
        amount_base_units=amount_base_units,
        step_up_satisfied=True,
    )
    if not decision.allowed:
        return _prepared_balance_response(
            action_type=decision.action_type,
            rider_label=decision.rider_label,
            asset=asset,
            amount_base_units=amount_base_units,
            rider_state="Needs review",
            rider_detail=decision.rider_detail,
            next_step="needs_review",
            blockers=decision.blockers,
        )

    try:
        prepared = await _build_withdraw_to_wallet_transaction(
            current_user=current_user,
            asset=asset,
            amount_base_units=amount_base_units,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            return _prepared_balance_response(
                action_type=decision.action_type,
                rider_label=decision.rider_label,
                asset=asset,
                amount_base_units=amount_base_units,
                rider_state="Needs review",
                rider_detail=str(exc.detail),
                next_step="needs_review",
            )
        raise

    return _prepared_balance_response(
        action_type=decision.action_type,
        rider_label=decision.rider_label,
        asset=asset,
        amount_base_units=amount_base_units,
        rider_state="Pending",
        rider_detail="Confirm in wallet to continue.",
        next_step="confirm_wallet",
        prepared_transaction=prepared,
    )


@router.post("/balance/withdraw-to-wallet")
async def submit_balance_withdraw_to_wallet(
    payload: BalanceWithdrawToWalletSubmitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Submit a wallet-confirmed Withdraw to wallet action and record state."""
    _require_balance_rollout_action("withdraw_to_wallet")
    asset = _normalize_withdraw_asset(payload.asset)
    amount_base_units = payload.amount_base_units_int
    lifecycle = await _balance_lifecycle_for_action(
        current_user,
        asset=asset,
    )
    decision = prepare_balance_lifecycle_action(
        lifecycle,
        action_type=BalanceLifecycleAction.WITHDRAW_TO_WALLET,
        asset=asset,
        amount_base_units=amount_base_units,
        step_up_satisfied=True,
    )
    if not decision.allowed:
        return _prepared_balance_response(
            action_type=decision.action_type,
            rider_label=decision.rider_label,
            asset=asset,
            amount_base_units=amount_base_units,
            rider_state="Needs review",
            rider_detail=decision.rider_detail,
            next_step="needs_review",
            blockers=decision.blockers,
        )

    signed_tx = _decode_signed_transaction_or_400(payload.signed_transaction)
    expected = await _build_withdraw_to_wallet_transaction(
        current_user=current_user,
        asset=asset,
        amount_base_units=amount_base_units,
        blockhash=signed_tx.message.recent_blockhash,
    )
    _assert_signed_transaction_matches(signed_tx, expected)

    coordinator = _balance_coordinator(repo)
    operation: BalanceOperationRecord | None = None
    try:
        scope = PortfolioBalanceRouteScope(
            rider_account_id=current_user.user_id,
            protocol_wallet=current_user.wallet,
            prepared_message_hash=prepared_message_hash(expected.transaction),
            tx_signature=_signed_transaction_signature(signed_tx),
            client_request_id=payload.client_request_id,
            metadata={
                "asset": asset,
                "last_valid_block_height": str(payload.last_valid_block_height),
            },
        )
        operation = coordinator.prepare_operation(
            withdraw_to_wallet_intent(
                scope=scope,
                asset=asset,
                amount=str(amount_base_units),
                source=expected.pda or "Boulder Roller Balance",
            )
        )
        submission = await submit_confirmed_balance_transaction(
            builder=get_tx_builder(),
            coordinator=coordinator,
            operation=operation,
            transaction_b64=payload.signed_transaction,
            last_valid_block_height=payload.last_valid_block_height,
        )
        operation = submission.operation
    except BalanceOperationError as exc:
        raise _balance_operation_http_exception(
            exc,
            "Boulder Roller could not prepare Withdraw to wallet. Please try again.",
        ) from exc
    except BalanceSubmissionError as exc:
        logger.error(
            "[PortfolioBalance] Withdraw to wallet did not confirm: %s",
            scrub_log_text(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Boulder Roller could not finish Withdraw to wallet. Please try again.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[PortfolioBalance] Withdraw to wallet failed: %s", scrub_log_text(exc), exc_info=True)
        if operation is not None:
            coordinator.mark_failed(operation, reason="withdraw_to_wallet_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Boulder Roller could not finish Withdraw to wallet. Please try again.",
        ) from exc

    return _prepared_balance_response(
        action_type=decision.action_type,
        rider_label=decision.rider_label,
        asset=asset,
        amount_base_units=amount_base_units,
        rider_state=operation.rider_state or "Pending",
        rider_detail="Withdraw to wallet saved. Balance is refreshing.",
        next_step="pending",
        operation=operation,
    )
