"""Admin endpoints for the Platform Command Center dashboard."""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..compliance_repository import ComplianceRepository
from ..dependencies import get_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository
from .admin import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/platform", tags=["admin-platform"])

DUNG_BASE_UNITS_PER_TOKEN = 1_000_000_000
MAX_DUNG_SUPPLY_BASE_UNITS = 1_000_000_000 * DUNG_BASE_UNITS_PER_TOKEN
COMMUNITY_CAP_BASE_UNITS = 400_000_000 * DUNG_BASE_UNITS_PER_TOKEN
TREASURY_CAP_BASE_UNITS = 250_000_000 * DUNG_BASE_UNITS_PER_TOKEN
TEAM_CAP_BASE_UNITS = 200_000_000 * DUNG_BASE_UNITS_PER_TOKEN
INVESTOR_CAP_BASE_UNITS = 100_000_000 * DUNG_BASE_UNITS_PER_TOKEN
POL_CAP_BASE_UNITS = 50_000_000 * DUNG_BASE_UNITS_PER_TOKEN


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class UserKPIs(BaseModel):
    total: int = 0
    new_7d: int = 0


class RideKPIs(BaseModel):
    total: int = 0
    this_week: int = 0
    total_tss: float = 0
    total_distance_m: float = 0
    total_elevation_m: float = 0
    by_status: Dict[str, int] = Field(default_factory=dict)


class VaultKPIs(BaseModel):
    total: int = 0
    total_completions: int = 0
    total_staked_cal: str = "0"
    unique_stakers: int = 0


class ClimbKPIs(BaseModel):
    total: int = 0
    scored: int = 0
    pct_scored: float = 0


class EpochSummary(BaseModel):
    current_epoch: int = 0
    stored_epoch: int = 0
    epoch_needs_transition: bool = False
    pending_distributions: int = 0
    pending_dung_total: str = "0"
    blocked_distributions: int = 0
    blocked_reasons: List[str] = Field(default_factory=list)
    oldest_blocked_at: Optional[str] = None
    preconditions_pending: int = 0
    reconciliation_pending: int = 0
    review_required: int = 0
    settlement_healthy: bool = True


class SupplyState(BaseModel):
    max_supply_base_units: str = str(MAX_DUNG_SUPPLY_BASE_UNITS)
    total_minted_base_units: str = "0"
    protocol_burned_base_units: str = "0"
    circulating_supply_base_units: Optional[str] = None
    circulating_source: str = "unavailable"
    community_minted_base_units: str = "0"
    community_cap_base_units: str = str(COMMUNITY_CAP_BASE_UNITS)
    treasury_minted_base_units: str = "0"
    treasury_cap_base_units: str = str(TREASURY_CAP_BASE_UNITS)
    team_minted_base_units: str = "0"
    team_cap_base_units: str = str(TEAM_CAP_BASE_UNITS)
    investor_minted_base_units: str = "0"
    investor_cap_base_units: str = str(INVESTOR_CAP_BASE_UNITS)
    pol_minted_base_units: str = "0"
    pol_cap_base_units: str = str(POL_CAP_BASE_UNITS)


class EmissionState(BaseModel):
    current_epoch: int = 1
    current_emission_rate_bps: int = 10000
    total_halvings: int = 0
    next_halving_at: Optional[str] = None


class ControlSnapshot(BaseModel):
    staking_enabled: bool = True
    minting_enabled: bool = True
    uploads_enabled: bool = True
    withdrawals_enabled: bool = True
    maintenance_mode: bool = False


class PlatformOverviewResponse(BaseModel):
    users: UserKPIs
    rides: RideKPIs
    vaults: VaultKPIs
    climbs: ClimbKPIs
    epoch: EpochSummary
    supply: SupplyState
    emission: EmissionState
    controls: ControlSnapshot
    health_status: str  # HEALTHY | WARNING | CRITICAL
    generated_at: str


class ActivityFeedItem(BaseModel):
    id: str
    source: str  # "points_event" | "audit_log"
    event_type: str
    wallet: Optional[str] = None
    detail: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: str


class ActivityFeedResponse(BaseModel):
    items: List[ActivityFeedItem]
    count: int


class AuditLogEntry(BaseModel):
    id: str
    action: str
    user_id: Optional[str] = None
    target_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: str


class AuditLogResponse(BaseModel):
    entries: List[AuditLogEntry]
    count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_control_enabled(value) -> bool:
    """Extract enabled bool from a system_controls value column."""
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    return True


def _decimal_string(value: Any) -> str:
    return format(Decimal(str(value)), "f")


def _supply_state_from_indexed_row(row: Dict[str, Any]) -> SupplyState:
    spl_mint_supply = row.get("spl_mint_supply")
    return SupplyState(
        max_supply_base_units=_decimal_string(
            row.get("max_supply", MAX_DUNG_SUPPLY_BASE_UNITS)
        ),
        total_minted_base_units=_decimal_string(row.get("total_minted", 0)),
        protocol_burned_base_units=_decimal_string(row.get("total_burned", 0)),
        circulating_supply_base_units=(
            None if spl_mint_supply is None else _decimal_string(spl_mint_supply)
        ),
        circulating_source=(
            "unavailable" if spl_mint_supply is None else "spl_mint_supply"
        ),
        community_minted_base_units=_decimal_string(
            row.get("community_minted", 0)
        ),
        community_cap_base_units=str(COMMUNITY_CAP_BASE_UNITS),
        treasury_minted_base_units=_decimal_string(row.get("treasury_minted", 0)),
        treasury_cap_base_units=str(TREASURY_CAP_BASE_UNITS),
        team_minted_base_units=_decimal_string(row.get("team_minted", 0)),
        team_cap_base_units=str(TEAM_CAP_BASE_UNITS),
        investor_minted_base_units=_decimal_string(row.get("investor_minted", 0)),
        investor_cap_base_units=str(INVESTOR_CAP_BASE_UNITS),
        pol_minted_base_units=_decimal_string(row.get("pol_minted", 0)),
        pol_cap_base_units=str(POL_CAP_BASE_UNITS),
    )


def _determine_health(
    controls: ControlSnapshot,
    epoch_overdue: bool,
    settlement_healthy: bool = True,
) -> str:
    if controls.maintenance_mode:
        return "CRITICAL"
    any_paused = not all([
        controls.staking_enabled,
        controls.minting_enabled,
        controls.uploads_enabled,
        controls.withdrawals_enabled,
    ])
    if any_paused or epoch_overdue or not settlement_healthy:
        return "WARNING"
    return "HEALTHY"


# ---------------------------------------------------------------------------
# GET /admin/platform/overview
# ---------------------------------------------------------------------------

@router.get("/overview", response_model=PlatformOverviewResponse)
@rate_limit(category="general")
async def get_platform_overview(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Aggregate platform overview for the admin command center.

    Returns KPIs (users, rides, vaults, climbs), epoch status,
    supply state, emission state, controls snapshot, and health status.
    """
    from ..services.epoch_processor import get_epoch_processor

    # --- Fire parallel DB queries ---

    async def fetch_kpis():
        return await asyncio.to_thread(
            lambda: repo.client.rpc("admin_platform_kpis", params={}).execute()
        )

    async def fetch_epoch():
        processor = get_epoch_processor(repo.client)
        settlement_clock = await processor._load_settlement_clock()
        current = settlement_clock.week_at(
            int(datetime.now(timezone.utc).timestamp())
        )
        stored = await processor.get_stored_epoch()
        status = await processor._settlement_queue.status()
        return current, stored, status

    async def fetch_supply():
        table_name = "indexed_supply"
        return await asyncio.to_thread(
            lambda: repo.client.table(table_name)
            .select("*")
            .eq("id", 1)
            .limit(1)
            .execute()
        )

    async def fetch_emission():
        return await asyncio.to_thread(
            lambda: repo.client.table("emission_schedule")
            .select("*")
            .eq("id", 1)
            .limit(1)
            .execute()
        )

    async def fetch_controls():
        return await asyncio.to_thread(
            lambda: repo.client.table("system_controls")
            .select("key, value")
            .execute()
        )

    try:
        kpis_result, epoch_tuple, supply_result, emission_result, controls_result = (
            await asyncio.gather(
                fetch_kpis(),
                fetch_epoch(),
                fetch_supply(),
                fetch_emission(),
                fetch_controls(),
            )
        )
    except Exception as e:
        logger.error(f"Platform overview query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch platform overview")

    # --- Parse KPIs from Postgres function ---
    kpis_data = kpis_result.data
    # rpc() returns the function result — may be a dict directly or wrapped in a list
    if isinstance(kpis_data, list) and kpis_data:
        kpis = kpis_data[0] if isinstance(kpis_data[0], dict) else kpis_data
    elif isinstance(kpis_data, dict):
        kpis = kpis_data
    else:
        kpis = {}

    users_kpi = UserKPIs(**(kpis.get("users") or {}))
    rides_kpi = RideKPIs(**(kpis.get("rides") or {}))
    vault_values = dict(kpis.get("vaults") or {})
    vault_values["total_staked_cal"] = _decimal_string(
        vault_values.get("total_staked_cal", 0)
    )
    vaults_kpi = VaultKPIs(**vault_values)
    climbs_kpi = ClimbKPIs(**(kpis.get("climbs") or {}))

    # --- Epoch ---
    current_epoch, stored_epoch, settlement_status = epoch_tuple
    epoch_summary = EpochSummary(
        current_epoch=current_epoch,
        stored_epoch=stored_epoch,
        epoch_needs_transition=current_epoch > stored_epoch,
        pending_distributions=settlement_status["pending"],
        pending_dung_total=settlement_status["pending_dung"],
        blocked_distributions=settlement_status["blocked"],
        blocked_reasons=settlement_status["blocked_reasons"],
        oldest_blocked_at=settlement_status["oldest_blocked_at"],
        preconditions_pending=settlement_status["preconditions_pending"],
        reconciliation_pending=settlement_status["reconciliation_pending"],
        review_required=settlement_status["review_required"],
        settlement_healthy=settlement_status["healthy"],
    )

    # --- Supply ---
    supply_row = (supply_result.data or [{}])[0] if supply_result.data else {}
    supply = _supply_state_from_indexed_row(supply_row)

    # --- Emission ---
    em_row = (emission_result.data or [{}])[0] if emission_result.data else {}
    emission = EmissionState(
        current_epoch=int(em_row.get("current_epoch", 1)),
        current_emission_rate_bps=int(em_row.get("current_emission_rate_bps", 10000)),
        total_halvings=int(em_row.get("total_halvings", 0)),
        next_halving_at=em_row.get("next_halving_at"),
    )

    # --- Controls ---
    controls_map: Dict[str, bool] = {}
    for row in (controls_result.data or []):
        controls_map[row["key"]] = _parse_control_enabled(row.get("value"))

    controls_snap = ControlSnapshot(
        staking_enabled=controls_map.get("staking_enabled", True),
        minting_enabled=controls_map.get("minting_enabled", True),
        uploads_enabled=controls_map.get("uploads_enabled", True),
        withdrawals_enabled=controls_map.get("withdrawals_enabled", True),
        maintenance_mode=controls_map.get("maintenance_mode", False),
    )

    # --- Health ---
    epoch_overdue = current_epoch > stored_epoch
    health = _determine_health(
        controls_snap,
        epoch_overdue,
        settlement_status["healthy"],
    )

    generated_at = kpis.get("generated_at") or datetime.now(timezone.utc).isoformat()

    return PlatformOverviewResponse(
        users=users_kpi,
        rides=rides_kpi,
        vaults=vaults_kpi,
        climbs=climbs_kpi,
        epoch=epoch_summary,
        supply=supply,
        emission=emission,
        controls=controls_snap,
        health_status=health,
        generated_at=str(generated_at),
    )


# ---------------------------------------------------------------------------
# GET /admin/platform/activity-feed
# ---------------------------------------------------------------------------

@router.get("/activity-feed", response_model=ActivityFeedResponse)
@rate_limit(category="general")
async def get_activity_feed(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Unified activity feed merging recent economic ledger events and audit_log entries.

    Returns items sorted by created_at descending.
    """

    async def fetch_economic_events():
        return await asyncio.to_thread(
            lambda: repo.client.table("economic_events")
            .select("event_uuid, wallet, event_type, amount, evidence, valid_at, recorded_at")
            .eq("is_reversed", False)
            .order("recorded_at", desc=True)
            .limit(limit)
            .execute()
        )

    async def fetch_audit():
        return await asyncio.to_thread(
            lambda: repo.client.table("audit_log")
            .select("id, action, user_id, target_type, metadata, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

    try:
        pe_result, audit_result = await asyncio.gather(
            fetch_economic_events(), fetch_audit(), return_exceptions=True
        )
        # If either returned an exception, treat as empty
        if isinstance(pe_result, BaseException):
            logger.warning(f"Economic events query failed: {pe_result}")
            pe_result = type("R", (), {"data": []})()
        if isinstance(audit_result, BaseException):
            logger.warning(f"Audit log query failed: {audit_result}")
            audit_result = type("R", (), {"data": []})()
    except Exception as e:
        logger.error(f"Activity feed query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch activity feed")

    items: List[ActivityFeedItem] = []

    for row in (pe_result.data or []):
        delta = row.get("amount", row.get("points_delta", 0))
        created_at = row.get("valid_at") or row.get("created_at") or row.get("recorded_at", "")
        items.append(ActivityFeedItem(
            id=str(row.get("event_uuid") or row["id"]),
            source="points_event",
            event_type=row.get("event_type", ""),
            wallet=row.get("wallet"),
            detail=f"{row.get('event_type', '')} {'+' if float(delta) >= 0 else ''}{delta} pts",
            metadata=row.get("evidence", row.get("metadata")),
            created_at=str(created_at),
        ))

    for row in (audit_result.data or []):
        items.append(ActivityFeedItem(
            id=str(row["id"]),
            source="audit_log",
            event_type=row.get("action", ""),
            wallet=str(row["user_id"]) if row.get("user_id") else None,
            detail=f"{row.get('action', '')} on {row.get('target_type', 'system')}",
            metadata=row.get("metadata"),
            created_at=str(row.get("created_at", "")),
        ))

    # Sort by created_at descending and trim to limit
    items.sort(key=lambda x: x.created_at, reverse=True)
    items = items[:limit]

    return ActivityFeedResponse(items=items, count=len(items))


# ---------------------------------------------------------------------------
# GET /admin/platform/audit-log
# ---------------------------------------------------------------------------

@router.get("/audit-log", response_model=AuditLogResponse)
@rate_limit(category="general")
async def get_audit_log(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Recent audit log entries for the admin command center."""
    compliance = ComplianceRepository()
    entries_data = await compliance.get_recent_audit_log(limit=limit)

    entries = [
        AuditLogEntry(
            id=str(row.get("id", "")),
            action=row.get("action", ""),
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            target_type=row.get("target_type"),
            metadata=row.get("metadata"),
            ip_address=str(row["ip_address"]) if row.get("ip_address") else None,
            created_at=str(row.get("created_at", "")),
        )
        for row in entries_data
    ]

    return AuditLogResponse(entries=entries, count=len(entries))
