"""
Distribution Routes: User-facing distribution receipt history.

Endpoints:
- GET /distributions/my - Get current user's on-chain staker allocation history grouped by vault+epoch
- GET /distributions/vault/{vault_id} - Get distribution history for a specific vault
- GET /distributions/epoch/current - Get current epoch info
"""
from datetime import datetime, timezone
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from ..client_contracts import CarryBuckets, SettlementStatus
from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository
from ..settlement_clock import SettlementClock, SettlementClockError
from ..token_amounts import ExactTokenAmount, exact_token_amount
from ..utils.postgrest_paging import order_by, window

router = APIRouter()


class DistributionReceipt(BaseModel):
    id: str
    receipt_type: str
    amount: str
    amount_base_units: str
    rank: Optional[int]
    created_at: str
    tx_signature: Optional[str] = None


class DistributionGroup(BaseModel):
    distribution_id: str
    vault_signature: str
    epoch: int
    total_amount: str
    total_amount_base_units: str
    leaderboard_amount: str
    leaderboard_amount_base_units: str
    staker_amount: str
    staker_amount_base_units: str
    local_legend_amount: str
    local_legend_amount_base_units: str
    pol_amount: str
    pol_amount_base_units: str
    protocol_amount: str
    protocol_amount_base_units: str
    distributed_at: str
    # BACKEND_TRUTHS §3.3 — settlement finalization time (chain-derived).
    # Empty string means the chain event has not yet been observed; any
    # value means this vault+epoch is immutable.
    finalized_at: str = ""
    current_carry: CarryBuckets = Field(default_factory=CarryBuckets)
    settlement_status: Optional[SettlementStatus] = None
    receipts: list[DistributionReceipt]


class MyDistributionsResponse(BaseModel):
    distributions: list[DistributionGroup]
    receipt_count: int
    distribution_count: int
    limit: int
    offset: int


@router.get("/my", response_model=MyDistributionsResponse)
async def get_my_distributions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get projected on-chain staker allocation history for the current user.

    Limit/offset apply to allocation rows; results are grouped by settlement
    distribution (vault + epoch).
    """
    supabase = repo.client

    receipt_count_resp = supabase.table("indexed_staker_allocations") \
        .select("tx_signature", count="exact") \
        .eq("staker", current_user.wallet) \
        .execute()
    receipt_count = receipt_count_resp.count or 0

    receipts_query = supabase.table("indexed_staker_allocations") \
        .select("tx_signature, event_index, vault_id, epoch, amount, block_time") \
        .eq("staker", current_user.wallet)
    receipts_resp = window(
        order_by(receipts_query, "epoch.desc", "block_time", desc=True), offset, limit,
    ).execute()
    receipts = receipts_resp.data or []

    if not receipts:
        return MyDistributionsResponse(
            distributions=[],
            receipt_count=receipt_count,
            distribution_count=0,
            limit=limit,
            offset=offset,
        )

    vault_ids = sorted({int(r["vault_id"]) for r in receipts if r.get("vault_id") is not None})
    epochs = sorted({int(r["epoch"]) for r in receipts if r.get("epoch") is not None}, reverse=True)

    vaults_resp = supabase.table("indexed_vaults") \
        .select(
            "id, signature_hex, carry_record_royalty, carry_stakers, "
            "carry_local_legend, carry_pol, carry_treasury"
        ) \
        .in_("id", vault_ids) \
        .execute()
    vaults_by_id = {int(row["id"]): row for row in (vaults_resp.data or [])}

    distributions_resp = supabase.table("indexed_epoch_distributions") \
        .select(
            "vault_id, epoch, total_distributed, leaderboard_distributed, "
            "staker_distributed, local_legend_distributed, pol_distributed, "
            "protocol_distributed, block_time, finalized_at"
        ) \
        .in_("vault_id", vault_ids) \
        .in_("epoch", epochs) \
        .execute()
    distributions_by_key = {
        (int(row["vault_id"]), int(row["epoch"])): row
        for row in (distributions_resp.data or [])
    }

    grouped: dict[str, list[dict]] = {}
    for receipt in receipts:
        vault_id = receipt.get("vault_id")
        epoch = receipt.get("epoch")
        if vault_id is None or epoch is None:
            continue
        dist_id = f"v4a:{vault_id}:{epoch}"
        grouped.setdefault(dist_id, []).append(receipt)

    distribution_groups = []
    for dist_id, dist_receipts in grouped.items():
        first = dist_receipts[0]
        vault_id = int(first["vault_id"])
        epoch = int(first["epoch"])
        dist = distributions_by_key.get((vault_id, epoch), {})
        vault_row = vaults_by_id.get(vault_id, {})
        amounts = _distribution_amounts(dist)
        distribution_groups.append(
            DistributionGroup(
                distribution_id=dist_id,
                vault_signature=vault_row.get("signature_hex", ""),
                epoch=epoch,
                total_amount=amounts["total"].units,
                total_amount_base_units=amounts["total"].base_units,
                leaderboard_amount=amounts["leaderboard"].units,
                leaderboard_amount_base_units=amounts["leaderboard"].base_units,
                staker_amount=amounts["staker"].units,
                staker_amount_base_units=amounts["staker"].base_units,
                local_legend_amount=amounts["local_legend"].units,
                local_legend_amount_base_units=amounts["local_legend"].base_units,
                pol_amount=amounts["pol"].units,
                pol_amount_base_units=amounts["pol"].base_units,
                protocol_amount=amounts["protocol"].units,
                protocol_amount_base_units=amounts["protocol"].base_units,
                distributed_at=_timestamp_to_iso(dist.get("block_time") or first.get("block_time")),
                # BACKEND_TRUTHS §3.3 — finalized_at from the chain event.
                # Prefer the generated column; fall back to deriving from
                # block_time on the chain projection, or the legacy
                # reconciled value.
                finalized_at=_finalized_at_iso(dist),
                current_carry=_carry_from_vault(vault_row),
                settlement_status=_settlement_status_from_distribution(
                    vault_id=vault_id,
                    vault_signature=vault_row.get("signature_hex", ""),
                    dist=dist,
                    current_carry=_carry_from_vault(vault_row),
                ),
                receipts=[
                    _distribution_receipt(receipt)
                    for receipt in dist_receipts
                ],
            )
        )

    distribution_groups.sort(key=lambda group: group.distributed_at or "", reverse=True)

    return MyDistributionsResponse(
        distributions=distribution_groups,
        receipt_count=receipt_count,
        distribution_count=len(distribution_groups),
        limit=limit,
        offset=offset,
    )


# =====================================================
# VAULT DISTRIBUTION HISTORY
# =====================================================


class VaultDistributionSummary(BaseModel):
    """Summary of a single epoch distribution for a vault."""
    distribution_id: str
    epoch: int
    total_amount: str
    total_amount_base_units: str
    leaderboard_amount: str
    leaderboard_amount_base_units: str
    staker_amount: str
    staker_amount_base_units: str
    local_legend_amount: str
    local_legend_amount_base_units: str
    pol_amount: str
    pol_amount_base_units: str
    protocol_amount: str
    protocol_amount_base_units: str
    distributed_at: str
    # BACKEND_TRUTHS §3.3 — settlement finalization time (chain-derived).
    finalized_at: str = ""
    staker_count: Optional[int] = None
    unlock_pct: Optional[int] = None
    locked_staker_amount: Optional[str] = None
    locked_staker_amount_base_units: Optional[str] = None
    leaderboard_details: Optional[list[dict]] = None
    settlement_status: Optional[SettlementStatus] = None


class VaultDistributionHistoryResponse(BaseModel):
    """Distribution history for a vault."""
    vault_id: int
    vault_signature: str
    vault_name: str
    current_carry: CarryBuckets = Field(default_factory=CarryBuckets)
    distributions: list[VaultDistributionSummary]
    total_distributed: str
    total_distributed_base_units: str
    distribution_count: int


@router.get("/vault/{vault_id}", response_model=VaultDistributionHistoryResponse)
async def get_vault_distribution_history(
    vault_id: int,
    limit: int = Query(20, ge=1, le=100),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get distribution history for a specific vault.

    Shows all past epoch distributions with breakdowns.
    """
    supabase = repo.client

    # Get vault info
    vault_resp = supabase.table("indexed_vaults") \
        .select(
            "id, signature_hex, name, carry_record_royalty, carry_stakers, "
            "carry_local_legend, carry_pol, carry_treasury"
        ) \
        .eq("id", vault_id) \
        .limit(1) \
        .execute()

    if not vault_resp.data:
        raise HTTPException(status_code=404, detail="Vault not found")

    vault = vault_resp.data[0]
    vault_signature = vault.get("signature_hex", "")

    # Get chain-derived settlement history for this vault
    dist_resp = supabase.table("indexed_epoch_distributions") \
        .select(
            "tx_signature, event_index, epoch, total_distributed, "
            "leaderboard_distributed, staker_distributed, local_legend_distributed, "
            "pol_distributed, protocol_distributed, block_time, finalized_at, "
            "staker_count, unlock_pct, locked_staker_amount"
        ) \
        .eq("vault_id", vault_id) \
        .order("epoch", desc=True) \
        .limit(limit) \
        .execute()
    distribution_rows = dist_resp.data or []

    distributions = []
    total_distributed_base_units = 0

    for dist in distribution_rows:
        amounts = _distribution_amounts(dist)
        locked_staker = _dung_amount(
            dist.get("locked_staker_amount"),
            "locked_staker_amount",
        )
        total_distributed_base_units += int(amounts["total"].base_units)
        current_carry = _carry_from_vault(vault)
        distributions.append(VaultDistributionSummary(
            distribution_id=f"{dist.get('tx_signature')}:{dist.get('event_index')}",
            epoch=int(dist.get("epoch") or 0),
            total_amount=amounts["total"].units,
            total_amount_base_units=amounts["total"].base_units,
            leaderboard_amount=amounts["leaderboard"].units,
            leaderboard_amount_base_units=amounts["leaderboard"].base_units,
            staker_amount=amounts["staker"].units,
            staker_amount_base_units=amounts["staker"].base_units,
            local_legend_amount=amounts["local_legend"].units,
            local_legend_amount_base_units=amounts["local_legend"].base_units,
            pol_amount=amounts["pol"].units,
            pol_amount_base_units=amounts["pol"].base_units,
            protocol_amount=amounts["protocol"].units,
            protocol_amount_base_units=amounts["protocol"].base_units,
            distributed_at=_timestamp_to_iso(dist.get("block_time")),
            finalized_at=_finalized_at_iso(dist),
            staker_count=int(dist.get("staker_count") or 0),
            unlock_pct=int(dist.get("unlock_pct") or 0),
            locked_staker_amount=locked_staker.units,
            locked_staker_amount_base_units=locked_staker.base_units,
            leaderboard_details=None,
            settlement_status=_settlement_status_from_distribution(
                vault_id=vault_id,
                vault_signature=vault_signature,
                dist=dist,
                current_carry=current_carry,
            ),
        ))

    return VaultDistributionHistoryResponse(
        vault_id=vault_id,
        vault_signature=vault_signature,
        vault_name=vault.get("name", "Unknown"),
        current_carry=_carry_from_vault(vault),
        distributions=distributions,
        total_distributed=_dung_amount(
            total_distributed_base_units,
            "total_distributed",
        ).units,
        total_distributed_base_units=str(total_distributed_base_units),
        distribution_count=len(distributions),
    )


# =====================================================
# EPOCH INFO
# =====================================================


class CurrentEpochResponse(BaseModel):
    """Current canonical Settlement Week information."""
    settlement_week: int
    current_epoch: int
    starts_at: str
    ends_at: str
    finalizes_at: str
    duration_seconds: int
    epoch_duration_seconds: int
    clock_version: int
    cutover_at: str
    transition_week: Optional[int] = None
    is_transition_week: bool


def _dung_amount(value: Optional[object], field_name: str) -> ExactTokenAmount:
    return exact_token_amount(value or 0, field_name=field_name)


def _distribution_amounts(row: dict) -> dict[str, ExactTokenAmount]:
    return {
        "total": _dung_amount(row.get("total_distributed"), "total_distributed"),
        "leaderboard": _dung_amount(
            row.get("leaderboard_distributed"),
            "leaderboard_distributed",
        ),
        "staker": _dung_amount(row.get("staker_distributed"), "staker_distributed"),
        "local_legend": _dung_amount(
            row.get("local_legend_distributed"),
            "local_legend_distributed",
        ),
        "pol": _dung_amount(row.get("pol_distributed"), "pol_distributed"),
        "protocol": _dung_amount(
            row.get("protocol_distributed"),
            "protocol_distributed",
        ),
    }


def _distribution_receipt(row: dict) -> DistributionReceipt:
    amount = _dung_amount(row.get("amount"), "staker_allocation_amount")
    return DistributionReceipt(
        id=f"{row.get('tx_signature')}:{row.get('event_index')}",
        receipt_type="STAKER",
        amount=amount.units,
        amount_base_units=amount.base_units,
        rank=None,
        created_at=_timestamp_to_iso(row.get("block_time")),
        tx_signature=row.get("tx_signature"),
    )


def _carry_from_vault(row: dict) -> CarryBuckets:
    record_royalty = _dung_amount(row.get("carry_record_royalty"), "carry_record_royalty")
    stakers = _dung_amount(row.get("carry_stakers"), "carry_stakers")
    local_legend = _dung_amount(row.get("carry_local_legend"), "carry_local_legend")
    pol = _dung_amount(row.get("carry_pol"), "carry_pol")
    treasury = _dung_amount(row.get("carry_treasury"), "carry_treasury")
    total_base_units = sum(
        int(amount.base_units)
        for amount in (record_royalty, stakers, local_legend, pol, treasury)
    )
    total = _dung_amount(total_base_units, "carry_total")
    return CarryBuckets(
        record_royalty=record_royalty.units,
        record_royalty_base_units=record_royalty.base_units,
        stakers=stakers.units,
        stakers_base_units=stakers.base_units,
        local_legend=local_legend.units,
        local_legend_base_units=local_legend.base_units,
        pol=pol.units,
        pol_base_units=pol.base_units,
        treasury=treasury.units,
        treasury_base_units=treasury.base_units,
        total=total.units,
        total_base_units=total.base_units,
    )


def _settlement_status_from_distribution(
    *,
    vault_id: int,
    vault_signature: str,
    dist: dict,
    current_carry: CarryBuckets,
) -> SettlementStatus:
    epoch = int(dist.get("epoch") or 0)
    amounts = _distribution_amounts(dist)
    return SettlementStatus(
        settlement_week=epoch,
        epoch=epoch,
        finalized_at=_finalized_at_iso(dist),
        distributed_at=_timestamp_to_iso(dist.get("block_time")),
        vault_id=vault_id,
        vault_signature=vault_signature,
        total_amount=amounts["total"].units,
        total_amount_base_units=amounts["total"].base_units,
        record_royalty_amount=amounts["leaderboard"].units,
        record_royalty_amount_base_units=amounts["leaderboard"].base_units,
        staker_amount=amounts["staker"].units,
        staker_amount_base_units=amounts["staker"].base_units,
        local_legend_amount=amounts["local_legend"].units,
        local_legend_amount_base_units=amounts["local_legend"].base_units,
        pol_amount=amounts["pol"].units,
        pol_amount_base_units=amounts["pol"].base_units,
        treasury_amount=amounts["protocol"].units,
        treasury_amount_base_units=amounts["protocol"].base_units,
        current_carry=current_carry,
    )


def _timestamp_to_iso(value: Optional[object]) -> str:
    if value in (None, "", 0, "0"):
        return ""
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _finalized_at_iso(row: dict) -> str:
    """Surface BACKEND_TRUTHS §3.3 `finalized_at` as ISO-8601.

    Prefer the chain-derived finalized column on indexed_epoch_distributions.
    Fall back to deriving from `block_time` (unix seconds) when the row comes
    from a source that does not have the generated column (legacy queue
    reconciliation path, pre-migration DBs).

    Returns "" when the chain event has not yet been observed — honest "not
    yet finalized" signal, never fabricated wall-clock.
    """
    if not row:
        return ""
    # Chain projection: prefer the explicit TIMESTAMPTZ if reconciliation
    # has populated it.
    existing = row.get("finalized_at")
    if existing not in (None, ""):
        if isinstance(existing, datetime):
            return existing.isoformat()
        return str(existing)
    # Fallback: derive from block_time (unix seconds on the chain event).
    block_time = row.get("block_time")
    if block_time in (None, "", 0, "0"):
        return ""
    return _timestamp_to_iso(block_time)


@router.get("/epoch/current", response_model=CurrentEpochResponse)
async def get_current_epoch_info(
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get current epoch information.

    Returns the current epoch number and when it ends.
    """
    result = (
        repo.client.table("indexed_program_config")
        .select("settlement_clock_version,settlement_clock_v2_starts_at,chain_slot")
        .order("chain_slot", desc=True)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    if not rows:
        raise HTTPException(
            status_code=503,
            detail="Settlement clock is not indexed",
        )
    try:
        clock = SettlementClock.from_program_config(rows[0])
    except SettlementClockError as exc:
        raise HTTPException(
            status_code=503,
            detail="Settlement clock is not configured",
        ) from exc

    window = clock.window_at(int(time.time()))
    return CurrentEpochResponse(
        settlement_week=window.settlement_week,
        current_epoch=window.settlement_week,
        starts_at=datetime.fromtimestamp(window.starts_at, timezone.utc).isoformat(),
        ends_at=datetime.fromtimestamp(window.ends_at, timezone.utc).isoformat(),
        finalizes_at=datetime.fromtimestamp(window.finalizes_at, timezone.utc).isoformat(),
        duration_seconds=window.duration_seconds,
        epoch_duration_seconds=window.duration_seconds,
        clock_version=window.clock_version,
        cutover_at=datetime.fromtimestamp(clock.v2_starts_at, timezone.utc).isoformat(),
        transition_week=clock.transition_week,
        is_transition_week=window.is_transition_week,
    )
