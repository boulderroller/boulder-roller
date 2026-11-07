"""
Climbs API routes.

These are the canonical Climbs (segments) from the vault that riders can
stake on and compete for Record Board positions.

Per BACKEND_TRUTHS §12 and PROTOCOL_TRUTHS §11, the canonical vocabulary is
``Climb`` (not "segment"). The router is mounted at both ``/climbs`` (canonical)
and ``/segments`` (back-compat alias) so existing clients keep working during
the broader rename rollout tracked under wdvr.8 + 0uv8.
"""
import logging
import json
from datetime import datetime, timezone
from typing import Any, Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

from ..client_contracts import (
    ClimbSummary,
    RecordBoard,
    RecordBoardEntry,
    TruthSource,
    VaultEconomy,
    VaultCreationAvailability,
    ClimbEffort,
)
from ..dependencies import AuthenticatedUser, get_optional_current_user, get_repository
from ..feed_contracts import build_route_preview
from ..repositories import DatabaseRepository
from ..repositories.vault import VaultRepository
from ..repositories.climb_effort import ClimbEffortRepository
from ..services.climb_effort_reads import admitted_kom, enrich_board, read_effort, rides_board
from ..services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    project_public_record_board,
)
from ..services.balance_production_rollout import is_balance_action_enabled
from ..services.canon_vault_activation import load_canon_climb_runtime_states
from ..token_amounts import exact_token_amount
from ..utils.polyline import decode_polyline
from ..utils.postgrest_paging import PageCursor, order_by
from ..services.geographic_data import geographic_data_for_row
from ..services.climb_read_metrics import climb_category

logger = logging.getLogger(__name__)

# NOTE: prefix is intentionally blank on the router itself; main.py mounts this
# router at both ``/climbs`` (canonical) and ``/segments`` (compat alias) so a
# single handler serves both surfaces without duplication. The public OpenAPI
# tag is ``climbs`` to reflect post-TRUTHS vocabulary.
router = APIRouter(tags=["climbs"])


@router.get("/efforts/{effort_id}", response_model=ClimbEffort, response_model_exclude_none=True)
async def get_climb_effort(
    effort_id: UUID,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """One canonical effort, under the ride's audience and map privacy."""
    return await read_effort(ClimbEffortRepository(repo.client), str(effort_id), current_user)


def _is_legacy_segment_request(request: Optional[Request]) -> bool:
    """Return whether the request targets the legacy/back-compat alias."""
    return request is not None and request.url.path.startswith("/segments/")


class ClimbResponse(ClimbSummary):
    """Climb data matching frontend Climb type.

    Field names preserve the legacy segment-era shape (start_lat/end_lat etc.)
    so the compat alias stays byte-compatible with existing clients.

    Canonical clients should read `vault_economy` for the optional economic
    wrapper. The flat vault fields remain as explicit rollout compatibility
    aliases until boulderroller-v2-ejy8 retires them.
    """
    geographic_data: Optional[dict[str, Any]] = None


class ClimbListResponse(BaseModel):
    """Response for climb list endpoint."""
    climbs: List[ClimbResponse] = Field(default_factory=list)
    # Back-compat alias for older mobile/portal builds. Canonical clients
    # should read `climbs`.
    segments: List[ClimbResponse] = Field(default_factory=list)

    @model_validator(mode="after")
    def mirror_compat_fields(self) -> "ClimbListResponse":
        if self.climbs and not self.segments:
            self.segments = self.climbs
        if self.segments and not self.climbs:
            self.climbs = self.segments
        return self


class PopularClimb(BaseModel):
    """Popular climb with activity metrics for trending display."""
    id: str
    name: str
    region: Optional[str] = None
    length_m: Optional[float] = None
    elev_gain_m: float
    avg_gradient_pct: Optional[float] = None
    category: Optional[str] = None
    route_preview: Optional[dict[str, Any]] = None
    vault_id: Optional[int] = None
    vault_signature: Optional[str] = None
    has_vault: bool = True
    completions: int = 0  # Number of completions/attempts
    staked: str = "0"
    staked_base_units: str = "0"


class PopularClimbsResponse(BaseModel):
    """Response for popular climbs endpoint."""
    climbs: List[PopularClimb] = Field(default_factory=list)
    # Back-compat alias for older mobile/portal builds. Canonical clients
    # should read `climbs`.
    segments: List[PopularClimb] = Field(default_factory=list)

    @model_validator(mode="after")
    def mirror_compat_fields(self) -> "PopularClimbsResponse":
        if self.climbs and not self.segments:
            self.segments = self.climbs
        if self.segments and not self.climbs:
            self.climbs = self.segments
        return self


def build_climb_route_preview(polyline_json: Any, place_label: Optional[str] = None) -> Optional[dict[str, Any]]:
    if not polyline_json:
        return None

    try:
        raw_points = json.loads(polyline_json) if isinstance(polyline_json, str) else polyline_json
    except (TypeError, ValueError):
        return None

    if not isinstance(raw_points, list):
        return None

    points: list[dict[str, Any]] = []
    for point in raw_points:
        lat: Any = None
        lon: Any = None
        if isinstance(point, dict):
            lat = point.get("latitude", point.get("lat"))
            lon = point.get("longitude", point.get("lon"))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            lat, lon = point[0], point[1]

        if lat is not None and lon is not None:
            points.append({"latitude": lat, "longitude": lon})

    if not points:
        return None

    return build_route_preview(
        points,
        source="climb_polyline",
        place_label=place_label,
    )


def _active_cal_amount(vault_row: Optional[dict]):
    return exact_token_amount(
        (vault_row or {}).get("total_cal_staked_base_units") or 0,
        field_name="total_cal_staked",
    )


async def _attach_active_stake_totals(
    client: Any,
    vault_rows: List[dict],
) -> List[dict]:
    if not vault_rows:
        return []
    totals = await VaultRepository(client).get_vault_stake_totals(
        [int(row["id"]) for row in vault_rows]
    )
    return [
        {
            **row,
            "total_cal_staked_base_units": str(
                totals[int(row["id"])]["total_cal_staked"]
            ),
            "total_lp_tokens_base_units": str(
                totals[int(row["id"])]["total_lp_tokens"]
            ),
        }
        for row in vault_rows
    ]


def build_climb_response(row: dict, vault_row: Optional[dict] = None) -> ClimbResponse:
    active_cal = _active_cal_amount(vault_row)
    vault_economy = VaultEconomy(
        has_vault=bool(vault_row),
        vault_id=int(vault_row["id"]) if vault_row and vault_row.get("id") is not None else None,
        vault_signature=(vault_row or {}).get("signature_hex") or row.get("signature_hex"),
        total_staked=active_cal.units,
        total_staked_base_units=active_cal.base_units,
        total_cal_staked=active_cal.units,
        total_cal_staked_base_units=active_cal.base_units,
        total_completions=int((vault_row or {}).get("total_completions") or 0),
    )
    return ClimbResponse(
        id=row["id"],
        name=row.get("name"),
        length_m=row.get("distance_m"),
        elev_gain_m=row.get("total_vert_m"),
        start_lat=row.get("bounds_min_lat"),
        start_lon=row.get("bounds_min_lon"),
        end_lat=row.get("bounds_max_lat"),
        end_lon=row.get("bounds_max_lon"),
        avg_gradient_pct=row.get("avg_gradient_pct"),
        category=climb_category(row.get("distance_m"), row.get("avg_gradient_pct")),
        region=row.get("region"),
        vault_economy=vault_economy,
        route_preview=build_climb_route_preview((vault_row or {}).get("polyline_json"), row.get("region")),
    )


def build_vault_climb_response(row: dict) -> ClimbResponse:
    active_cal = _active_cal_amount(row)
    vault_economy = VaultEconomy(
        has_vault=True,
        vault_id=int(row["id"]),
        vault_signature=row.get("signature_hex"),
        total_staked=active_cal.units,
        total_staked_base_units=active_cal.base_units,
        total_cal_staked=active_cal.units,
        total_cal_staked_base_units=active_cal.base_units,
        total_completions=int(row.get("total_completions") or 0),
    )
    return ClimbResponse(
        id=str(row["id"]),
        name=row.get("name"),
        length_m=row.get("distance_m"),
        elev_gain_m=row.get("vert_m"),
        avg_gradient_pct=row.get("avg_gradient_pct"),
        category=climb_category(row.get("distance_m"), row.get("avg_gradient_pct")),
        region=row.get("region"),
        vault_economy=vault_economy,
        route_preview=build_climb_route_preview(
            row.get("polyline_json"), row.get("region")
        ),
    )


def _canon_route_points(row: dict) -> list[dict[str, float]]:
    encoded = row.get("centerline_polyline")
    if not encoded:
        return []
    try:
        return [
            {"latitude": float(lat), "longitude": float(lon)}
            for lat, lon in decode_polyline(str(encoded))
        ]
    except (TypeError, ValueError):
        return []


def _canon_elevation_profile(row: dict) -> list[dict[str, float]]:
    profile = row.get("canonical_profile")
    if not isinstance(profile, list):
        return []
    samples: list[dict[str, float]] = []
    for point in profile:
        if not isinstance(point, dict):
            return []
        try:
            distance_m = float(point["dist_m"])
            elevation_m = float(point["elev_m"])
        except (KeyError, TypeError, ValueError):
            return []
        if distance_m < 0:
            return []
        samples.append({"distance_m": distance_m, "elevation_m": elevation_m})
    return samples


def _canon_row_in_bbox(row: dict, bbox: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return any(
        min_lat <= point["latitude"] <= max_lat
        and min_lon <= point["longitude"] <= max_lon
        for point in _canon_route_points(row)
    )


def build_canon_climb_response(
    row: dict,
    *,
    indexed_climb: Optional[dict] = None,
    vault_row: Optional[dict] = None,
    reserved: bool = False,
    runtime_state: Optional[str] = None,
) -> ClimbResponse:
    """Build the rider contract from one immutable registry row UUID."""
    active_cal = _active_cal_amount(vault_row)
    has_vault = bool(vault_row)
    if runtime_state is not None and (runtime_state == "active") != has_vault:
        raise ValueError("canonical Vault projection and activation state disagree")
    vault_economy = VaultEconomy(
        truth_source=(TruthSource.onchain if has_vault else TruthSource.projected),
        has_vault=has_vault,
        vault_id=(
            int(vault_row["id"])
            if vault_row and vault_row.get("id") is not None
            else None
        ),
        vault_signature=(vault_row or {}).get("signature_hex"),
        total_staked=active_cal.units,
        total_staked_base_units=active_cal.base_units,
        total_cal_staked=active_cal.units,
        total_cal_staked_base_units=active_cal.base_units,
        total_completions=int((vault_row or {}).get("total_completions") or 0),
    )
    is_current = row.get("status") == "ratified"
    if has_vault and runtime_state in {None, "active"}:
        creation_state = "active"
    elif reserved or runtime_state == "reserved":
        creation_state = "reserved"
    elif is_current and indexed_climb and runtime_state in {None, "available"}:
        creation_state = "available"
    else:
        creation_state = "unavailable"
    route_points = _canon_route_points(row)
    return ClimbResponse(
        truth_source=(TruthSource.onchain if indexed_climb else TruthSource.projected),
        id=str(row["id"]),
        canon_id=row.get("canon_id"),
        version=int(row["version"]),
        revision_state="current" if is_current else "retired",
        name=row.get("display_name"),
        length_m=row.get("length_m"),
        elev_gain_m=row.get("vert_m"),
        start_lat=route_points[0]["latitude"] if route_points else None,
        start_lon=route_points[0]["longitude"] if route_points else None,
        end_lat=route_points[-1]["latitude"] if route_points else None,
        end_lon=route_points[-1]["longitude"] if route_points else None,
        avg_gradient_pct=row.get("avg_gradient_pct"),
        category=climb_category(row.get("length_m"), row.get("avg_gradient_pct")),
        region=(row.get("provenance") or {}).get("region"),
        vault_economy=vault_economy,
        vault_creation=VaultCreationAvailability(
            state=creation_state,
            payment_methods=(
                [
                    "dung",
                    *(
                        ["cal_usdc"]
                        if is_balance_action_enabled("create_vault_usdc")
                        else []
                    ),
                ]
                if creation_state == "available"
                else []
            ),
        ),
        route_preview=(
            build_route_preview(
                route_points,
                source="canon_centerline",
                place_label=(row.get("provenance") or {}).get("region"),
            )
            if route_points
            else None
        ),
        elevation_profile=_canon_elevation_profile(row),
        geographic_data=geographic_data_for_row(row),
    )


@router.get("/list", response_model=ClimbListResponse)
async def list_climbs(
    q: Optional[str] = Query(None, description="Search query for climb name"),
    bbox: Optional[str] = Query(None, description="Bounding box: min_lon,min_lat,max_lon,max_lat"),
    limit: int = Query(50, le=100, description="Maximum climbs to return"),
    repo: DatabaseRepository = Depends(get_repository),
):
    """List current ratified Climb revisions by immutable registry-row ID."""
    client = repo.client

    try:
        query = (
            client.from_("canon_climbs")
            .select(
                "id, canon_id, version, status, display_name, route_name, "
                "centerline_polyline, canonical_profile, length_m, vert_m, avg_gradient_pct, "
                "worthiness_score, provenance, supersedes_climb_id, dem_source, odbl_source, odbl_extract_at"
            )
            .eq("status", "ratified")
        )
        if q:
            query = query.ilike("display_name", f"%{q}%")
        parsed_bbox: Optional[tuple[float, float, float, float]] = None
        if bbox:
            try:
                values = tuple(float(value) for value in bbox.split(","))
                if len(values) != 4:
                    raise ValueError
                parsed_bbox = values  # type: ignore[assignment]
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="bbox must be min_lon,min_lat,max_lon,max_lat",
                )
        result = query.order("worthiness_score", desc=True).limit(
            500 if parsed_bbox else limit
        ).execute()
        rows = list(result.data or [])
        if parsed_bbox:
            rows = [row for row in rows if _canon_row_in_bbox(row, parsed_bbox)][:limit]

        row_ids = [str(row["id"]) for row in rows]
        runtime_states = load_canon_climb_runtime_states(
            client=client,
            climb_ids=[UUID(row_id) for row_id in row_ids],
        )
        indexed_by_registry: dict[str, dict] = {}
        if row_ids:
            indexed_result = (
                client.from_("indexed_climbs")
                .select("pda, canon_climb_id, vault_pda, quarantined")
                .in_("canon_climb_id", row_ids)
                .eq("quarantined", False)
                .execute()
            )
            indexed_by_registry = {
                str(indexed["canon_climb_id"]): indexed
                for indexed in (indexed_result.data or [])
            }
        climb_pdas = [
            str(indexed["pda"])
            for indexed in indexed_by_registry.values()
            if indexed.get("pda")
        ]
        vaults_by_climb: dict[str, dict] = {}
        if climb_pdas:
            vault_result = (
                client.from_("indexed_vaults")
                .select(
                    "id, pda, climb_pda, signature_hex, total_completions, "
                    "canon_binding_status"
                )
                .in_("climb_pda", climb_pdas)
                .eq("canon_binding_status", "active")
                .execute()
            )
            vault_rows = await _attach_active_stake_totals(
                client, list(vault_result.data or [])
            )
            vaults_by_climb = {
                str(vault["climb_pda"]): vault for vault in vault_rows
            }

        climbs = []
        for row in rows:
            indexed = indexed_by_registry.get(str(row["id"]))
            vault = (
                vaults_by_climb.get(str(indexed["pda"])) if indexed else None
            )
            climbs.append(
                build_canon_climb_response(
                    row,
                    indexed_climb=indexed,
                    vault_row=vault,
                    runtime_state=runtime_states.get(str(row["id"]), "unavailable"),
                )
            )
        logger.info("[Climbs] Returning %s current ratified climbs", len(climbs))
        return ClimbListResponse(climbs=climbs)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing climbs: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canonical climbs are temporarily unavailable",
        ) from e


@router.get("/popular", response_model=PopularClimbsResponse)
async def get_popular_climbs(
    limit: int = Query(6, le=20, description="Maximum climbs to return"),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get popular/trending climbs for feed display.

    Returns climbs ordered by activity (completions) with staking metrics.
    Falls back to elevation-ordered climbs if no activity data available.
    """
    client = repo.client

    try:
        # Exact active Vault projections remain subordinate to current registry UUIDs.
        vault_result = client.from_("indexed_vaults") \
            .select("id, name, signature_hex, canon_climb_id, canon_binding_status, "
                    "total_completions, polyline_json") \
            .eq("canon_binding_status", "active") \
            .order("total_completions", desc=True) \
            .limit(limit) \
            .execute()

        if vault_result.data and len(vault_result.data) > 0:
            vault_by_climb = {
                str(row["canon_climb_id"]): row
                for row in vault_result.data
                if row.get("canon_climb_id")
            }
            canon_result = client.from_("canon_climbs") \
                .select("id, canon_id, version, status, display_name, length_m, "
                        "vert_m, avg_gradient_pct, centerline_polyline, provenance") \
                .in_("id", list(vault_by_climb)) \
                .eq("status", "ratified") \
                .execute()
            canon_by_id = {
                str(row["id"]): row for row in (canon_result.data or [])
            }
            runtime_states = load_canon_climb_runtime_states(
                client=client,
                climb_ids=[UUID(climb_id) for climb_id in vault_by_climb],
            )
            vault_rows = await _attach_active_stake_totals(
                client,
                list(vault_result.data),
            )
            segments = []
            for row in vault_rows:
                climb_id = str(row.get("canon_climb_id") or "")
                canon = canon_by_id.get(climb_id)
                if not canon or runtime_states.get(climb_id) != "active":
                    continue
                active_cal = _active_cal_amount(row)
                segments.append(PopularClimb(
                    id=climb_id,
                    name=canon.get("display_name") or "Unnamed Climb",
                    region=(canon.get("provenance") or {}).get("region"),
                    length_m=canon.get("length_m") or 0,
                    elev_gain_m=canon.get("vert_m") or 0,
                    avg_gradient_pct=canon.get("avg_gradient_pct") or 0,
                    route_preview=(
                        build_route_preview(
                            _canon_route_points(canon),
                            source="canon_centerline",
                            place_label=(canon.get("provenance") or {}).get("region"),
                        )
                        if _canon_route_points(canon)
                        else None
                    ),
                    vault_id=int(row["id"]) if row.get("id") is not None else None,
                    vault_signature=row.get("signature_hex"),
                    has_vault=True,
                    completions=row.get("total_completions") or 0,
                    staked=active_cal.units,
                    staked_base_units=active_cal.base_units,
                ))
            logger.info(f"[Climbs] Returning {len(segments)} popular climbs from vaults")
            return PopularClimbsResponse(climbs=segments)

        # Discovery fallback is still current ratified canon, never detector output.
        result = client.from_("canon_climbs") \
            .select("id, display_name, length_m, vert_m, avg_gradient_pct, "
                    "centerline_polyline, provenance, status") \
            .eq("status", "ratified") \
            .order("worthiness_score", desc=True) \
            .limit(limit) \
            .execute()

        segments = []
        for row in result.data or []:
            segments.append(PopularClimb(
                id=str(row["id"]),
                name=row.get("display_name") or "Unnamed Climb",
                category=climb_category(row.get("length_m"), row.get("avg_gradient_pct")),
        region=(row.get("provenance") or {}).get("region"),
                length_m=row.get("length_m") or 0,
                elev_gain_m=row.get("vert_m") or 0,
                avg_gradient_pct=row.get("avg_gradient_pct") or 0,
                route_preview=(
                    build_route_preview(
                        _canon_route_points(row),
                        source="canon_centerline",
                        place_label=(row.get("provenance") or {}).get("region"),
                    )
                    if _canon_route_points(row)
                    else None
                ),
                has_vault=False,
                completions=0,
                staked="0",
                staked_base_units="0",
            ))

        logger.info(f"[Climbs] Returning {len(segments)} popular current canon climbs")
        return PopularClimbsResponse(climbs=segments)

    except Exception as e:
        logger.error(f"Error getting popular climbs: {e}")
        return PopularClimbsResponse(climbs=[])


@router.get("/{climb_id}/leaderboard")
async def get_climb_leaderboard(
    climb_id: str,
    request: Request = None,
    repo: DatabaseRepository = Depends(get_repository),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    """Get one canon Record Board; numeric IDs survive only on legacy/back-compat /segments."""
    try:
        client = repo.client
        climb_name: Optional[str] = None
        vault_row: Optional[dict] = None
        canonical_runtime_state: Optional[str] = None

        if climb_id.isdigit():
            if not _is_legacy_segment_request(request):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Climb not found",
                )
            result = client.from_("indexed_vaults") \
                .select("id, pda, name, signature_hex, kom_holder, kom_time_s") \
                .eq("id", int(climb_id)) \
                .limit(1) \
                .execute()
            vault_row = (result.data or [None])[0]
            if vault_row:
                climb_name = vault_row.get("name")
        elif _is_legacy_segment_request(request):
            climb_result = client.from_("climb_vault") \
                .select("id, name, signature_hex") \
                .eq("id", climb_id) \
                .eq("active", True) \
                .limit(1) \
                .execute()

            climb_row = (climb_result.data or [None])[0]
            if not climb_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Climb not found",
                )

            climb_name = climb_row.get("name")
            vault_result = client.from_("indexed_vaults") \
                .select("id, pda, name, signature_hex, kom_holder, kom_time_s") \
                .eq("signature_hex", climb_row["signature_hex"]) \
                .limit(1) \
                .execute()
            vault_row = (vault_result.data or [None])[0]
        else:
            try:
                normalized_climb_id = str(UUID(climb_id))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Climb not found",
                ) from exc
            climb_result = client.from_("canon_climbs") \
                .select("id, display_name, status, canon_id, version") \
                .eq("id", normalized_climb_id) \
                .in_("status", ["ratified", "retired"]) \
                .limit(1) \
                .execute()

            climb_row = (climb_result.data or [None])[0]
            if not climb_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Climb not found",
                )

            climb_name = climb_row.get("display_name")
            canonical_runtime_state = load_canon_climb_runtime_states(
                client=client,
                climb_ids=[UUID(normalized_climb_id)],
            ).get(normalized_climb_id, "unavailable")
            if canonical_runtime_state != "active":
                return await rides_board(ClimbEffortRepository(client), climb_row, viewer=current_user)
            indexed_result = client.from_("indexed_climbs") \
                .select("pda, canon_climb_id, vault_pda, quarantined") \
                .eq("canon_climb_id", normalized_climb_id) \
                .eq("quarantined", False) \
                .limit(1) \
                .execute()
            indexed_climb = (indexed_result.data or [None])[0]
            if indexed_climb:
                vault_result = client.from_("indexed_vaults") \
                    .select(
                        "id, pda, name, signature_hex, kom_holder, kom_time_s, "
                        "climb_pda, canon_binding_status"
                    ) \
                    .eq("climb_pda", indexed_climb["pda"]) \
                    .eq("canon_binding_status", "active") \
                    .limit(1) \
                    .execute()
                vault_row = (vault_result.data or [None])[0]

        if not vault_row:
            if canonical_runtime_state == "active":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Canonical Record Board projection is temporarily unavailable",
                )
            return RecordBoard(
                climb_id=climb_id,
                climb_name=climb_name,
                vault_id=None,
                entries=[],
                kom_holder=None,
                kom_time_s=None,
            ).model_dump(mode="json")

        lb_result = client.from_("indexed_leaderboards") \
            .select("entries") \
            .eq("vault_id", vault_row["id"]) \
            .execute()
        raw_entries = (
            lb_result.data[0].get("entries")
            if lb_result.data and lb_result.data[0].get("entries")
            else []
        )
        try:
            public_projection = project_public_record_board(
                client,
                vault_row=vault_row,
                raw_entries=raw_entries,
            )
        except PublicRecordBoardPrivacyUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Public Record Board privacy projection is temporarily "
                    "unavailable"
                ),
            ) from exc

        entries_json, viewer_entry = await enrich_board(
            ClimbEffortRepository(client), public_projection,
            vault_signature=vault_row["signature_hex"], viewer=current_user,
        )
        kom_holder, kom_time_s = admitted_kom(public_projection, entries_json)

        return RecordBoard(
            truth_source=TruthSource.projected,
            climb_id=climb_id,
            climb_name=climb_name or vault_row.get("name"),
            vault_id=vault_row["id"],
            entries=entries_json,
            viewer_entry=viewer_entry,
            kom_holder=kom_holder,
            kom_time_s=kom_time_s,
        ).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Record Board for climb {climb_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load climb leaderboard",
        ) from e


@router.get("/{climb_id}/leaderboard/window")
async def get_climb_window_leaderboard(
    climb_id: str,
    window: str = Query(..., description="today | year"),
    repo: DatabaseRepository = Depends(get_repository),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    """A sporting window over one climb's confirmed completions (today /
    this year). The protocol Record Board stays all-time; this projection
    ranks each rider's best confirmed time inside the window, through the
    same public-privacy projection as the Board."""
    if window not in {"today", "year"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window must be today or year",
        )
    try:
        client = repo.client
        try:
            normalized_climb_id = str(UUID(climb_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Climb not found",
            ) from exc

        climb_result = client.from_("canon_climbs") \
            .select("id, display_name, status, canon_id, version") \
            .eq("id", normalized_climb_id) \
            .in_("status", ["ratified", "retired"]) \
            .limit(1) \
            .execute()
        climb_row = (climb_result.data or [None])[0]
        if not climb_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Climb not found",
            )
        climb_name = climb_row.get("display_name")

        indexed_result = client.from_("indexed_climbs") \
            .select("pda, canon_climb_id, quarantined") \
            .eq("canon_climb_id", normalized_climb_id) \
            .eq("quarantined", False) \
            .limit(1) \
            .execute()
        indexed_climb = (indexed_result.data or [None])[0]
        vault_row = None
        if indexed_climb:
            vault_result = client.from_("indexed_vaults") \
                .select(
                    "id, pda, name, signature_hex, kom_holder, kom_time_s, "
                    "climb_pda, canon_binding_status"
                ) \
                .eq("climb_pda", indexed_climb["pda"]) \
                .eq("canon_binding_status", "active") \
                .limit(1) \
                .execute()
            vault_row = (vault_result.data or [None])[0]
        now = datetime.now(timezone.utc)
        if window == "today":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            window_start = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )

        if not vault_row:
            return await rides_board(ClimbEffortRepository(client), climb_row, viewer=current_user,
                                     window_start=window_start.isoformat())

        best_by_wallet: dict[str, dict] = {}
        page_size = 1000
        pages = PageCursor(page_size)
        while True:
            query = client.from_("vault_completions") \
                .select("wallet, time_seconds, completed_at") \
                .eq("vault_signature", vault_row["signature_hex"]) \
                .eq("validated", True) \
                .eq("chain_confirmation_status", "confirmed") \
                .not_.is_("time_seconds", "null") \
                .gte("completed_at", window_start.isoformat())
            result = order_by(query, "completed_at", "id") \
                .range(pages.offset, pages.offset + page_size - 1) \
                .execute()
            page = list(result.data or [])
            for row in page:
                wallet = str(row.get("wallet") or "")
                if not wallet:
                    continue
                time_seconds = int(row["time_seconds"])
                best = best_by_wallet.get(wallet)
                if best is None or time_seconds < int(best["time_s"]):
                    best_by_wallet[wallet] = {
                        "user": wallet,
                        "time_s": time_seconds,
                        "achieved_at": row.get("completed_at"),
                        "recorded_at": int(datetime.fromisoformat(
                            str(row["completed_at"]).replace("Z", "+00:00")
                        ).timestamp()),
                    }
            if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                break

        raw_entries = sorted(
            best_by_wallet.values(), key=lambda entry: int(entry["time_s"])
        )[:10]
        if not raw_entries:
            return RecordBoard(
                truth_source=TruthSource.projected,
                climb_id=climb_id,
                climb_name=climb_name or vault_row.get("name"),
                vault_id=vault_row["id"],
                entries=[],
                kom_holder=None,
                kom_time_s=None,
            ).model_dump(mode="json")

        try:
            public_projection = project_public_record_board(
                client,
                vault_row=vault_row,
                raw_entries=raw_entries,
            )
        except PublicRecordBoardPrivacyUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Public Record Board privacy projection is temporarily "
                    "unavailable"
                ),
            ) from exc

        entries_json, viewer_entry = await enrich_board(
            ClimbEffortRepository(client), public_projection,
            vault_signature=vault_row["signature_hex"], viewer=current_user,
            window_start=window_start.isoformat(),
        )
        return RecordBoard(
            truth_source=TruthSource.projected,
            climb_id=climb_id,
            climb_name=climb_name or vault_row.get("name"),
            vault_id=vault_row["id"],
            entries=entries_json,
            viewer_entry=viewer_entry,
            kom_holder=None,
            kom_time_s=None,
        ).model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting window board for climb {climb_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load climb leaderboard window",
        ) from e


@router.get("/{climb_id}", response_model=ClimbResponse)
async def get_climb(
    climb_id: str,
    request: Request = None,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get one immutable registry revision by its exact row UUID."""
    try:
        client = repo.client
        if _is_legacy_segment_request(request):
            if climb_id.isdigit():
                legacy_result = client.from_("indexed_vaults") \
                    .select(
                        "id, name, signature_hex, distance_m, vert_m, "
                        "avg_gradient_pct, total_completions, polyline_json"
                    ) \
                    .eq("id", int(climb_id)) \
                    .limit(1) \
                    .execute()
                legacy_row = (legacy_result.data or [None])[0]
                if legacy_row:
                    projected_rows = await _attach_active_stake_totals(
                        client, [legacy_row]
                    )
                    return build_vault_climb_response(projected_rows[0])

            legacy_result = client.from_("climb_vault") \
                .select(
                    "id, name, distance_m, total_vert_m, avg_gradient_pct, "
                    "signature_hex, bounds_min_lat, bounds_min_lon, "
                    "bounds_max_lat, bounds_max_lon, uci_category, region"
                ) \
                .eq("id", climb_id) \
                .eq("active", True) \
                .limit(1) \
                .execute()
            legacy_row = (legacy_result.data or [None])[0]
            if legacy_row:
                legacy_vault = None
                if legacy_row.get("signature_hex"):
                    vault_result = client.from_("indexed_vaults") \
                        .select(
                            "id, signature_hex, total_completions, polyline_json"
                        ) \
                        .eq("signature_hex", legacy_row["signature_hex"]) \
                        .limit(1) \
                        .execute()
                    legacy_vault = (vault_result.data or [None])[0]
                    if legacy_vault:
                        legacy_vault = (
                            await _attach_active_stake_totals(
                                client, [legacy_vault]
                            )
                        )[0]
                return build_climb_response(legacy_row, legacy_vault)

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Climb not found",
            )

        try:
            normalized_climb_id = str(UUID(climb_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Climb not found",
            ) from exc
        result = client.from_("canon_climbs") \
            .select(
                "id, canon_id, version, status, display_name, route_name, "
                "centerline_polyline, canonical_profile, length_m, vert_m, avg_gradient_pct, "
                "worthiness_score, provenance, supersedes_climb_id, dem_source, odbl_source, odbl_extract_at"
            ) \
            .eq("id", normalized_climb_id) \
            .in_("status", ["ratified", "retired"]) \
            .limit(1) \
            .execute()

        row = (result.data or [None])[0]
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Climb not found",
            )

        runtime_states = load_canon_climb_runtime_states(
            client=client,
            climb_ids=[UUID(normalized_climb_id)],
        )

        indexed_result = client.from_("indexed_climbs") \
            .select("pda, canon_climb_id, vault_pda, quarantined") \
            .eq("canon_climb_id", normalized_climb_id) \
            .eq("quarantined", False) \
            .limit(1) \
            .execute()
        indexed_climb = (indexed_result.data or [None])[0]
        vault_row = None
        if indexed_climb:
            vault_result = client.from_("indexed_vaults") \
                .select(
                    "id, pda, climb_pda, signature_hex, total_completions, "
                    "canon_binding_status"
                ) \
                .eq("climb_pda", indexed_climb["pda"]) \
                .eq("canon_binding_status", "active") \
                .limit(1) \
                .execute()
            vault_row = (vault_result.data or [None])[0]
            if vault_row:
                vault_row = (await _attach_active_stake_totals(client, [vault_row]))[0]

        return build_canon_climb_response(
            row,
            indexed_climb=indexed_climb,
            vault_row=vault_row,
            runtime_state=runtime_states.get(normalized_climb_id, "unavailable"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting climb {climb_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load climb",
        ) from e
