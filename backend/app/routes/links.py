from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import AuthenticatedUser, get_optional_current_user, get_repository
from ..link_contracts import (
    LinkAccessStatus,
    LinkTargetType,
    build_resolved_link,
    link_schema,
    normalize_link_target_type,
    parse_link_target,
)
from ..repositories import DatabaseRepository
from ..rider_identity_contracts import public_rider_ref_dict, rider_route_identifier
from ..scan_contracts import (
    scan_targets_for_climb,
    scan_targets_for_profile,
    scan_targets_for_protocol,
    scan_targets_for_ride,
)
from ..services.privacy_resolver import resolve_profile_visibility, resolve_ride_visibility


router = APIRouter(tags=["links"])


def _public_ride_title(ride: dict) -> str:
    file_name = str(ride.get("file_name") or "").strip()
    return file_name.rsplit(".", 1)[0] if file_name else "Ride"


async def _get_climb_row(repo: DatabaseRepository, climb_id: str) -> Optional[dict]:
    get_link_climb = getattr(repo, "get_link_climb", None)
    if get_link_climb:
        return await get_link_climb(climb_id)

    client = getattr(repo, "client", None)
    if client is None:
        return None

    if climb_id.isdigit():
        legacy_result = client.from_("indexed_vaults") \
            .select("id, name, signature_hex, distance_m, vert_m, avg_gradient_pct, total_completions") \
            .eq("id", int(climb_id)) \
            .limit(1) \
            .execute()
        legacy_row = (legacy_result.data or [None])[0]
        if legacy_row:
            return dict(legacy_row)

    result = client.from_("climb_vault") \
        .select("id, name, distance_m, total_vert_m, avg_gradient_pct, signature_hex, region") \
        .eq("id", climb_id) \
        .eq("active", True) \
        .limit(1) \
        .execute()
    row = (result.data or [None])[0]
    return dict(row) if row else None


async def _resolve_rider_link(
    identifier: str,
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
) -> dict:
    user = await repo.get_user_by_identifier(identifier.lstrip("@"))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link target not found")

    privacy = await resolve_profile_visibility(user, current_user)
    rider_ref = public_rider_ref_dict(user)
    display_name = rider_ref.get("displayName") or rider_ref.get("username") or "Rider"
    scan_state, scan_targets = scan_targets_for_profile(user)
    if not privacy.can_view:
        return build_resolved_link(
            target_type=LinkTargetType.rider,
            target_id=identifier,
            title="Private rider profile",
            description="This rider profile is private.",
            status=LinkAccessStatus.forbidden,
            can_view=False,
            reason=privacy.reason,
            metadata={"privacy": privacy.to_client_dict()},
            scan_state="private",
            scan_targets=[],
        )

    return build_resolved_link(
        target_type=LinkTargetType.rider,
        target_id=rider_route_identifier(user),
        title=f"{display_name} on Boulder Roller",
        description="Rider profile on Boulder Roller.",
        reason=privacy.reason,
        metadata={
            "userId": str(user["id"]),
            "username": user.get("username"),
            "rider": rider_ref,
            "privacy": privacy.to_client_dict(),
        },
        scan_state=scan_state.value,
        scan_targets=scan_targets,
    )


async def _resolve_ride_link(
    ride_id: str,
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
) -> dict:
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link target not found")

    privacy = await resolve_ride_visibility(ride, current_user, repo=repo)
    scan_state, scan_targets = scan_targets_for_ride(ride, can_view=privacy.can_view)
    if not privacy.can_view:
        return build_resolved_link(
            target_type=LinkTargetType.ride,
            target_id=ride_id,
            title="Private ride",
            description="This ride is private.",
            status=LinkAccessStatus.forbidden,
            can_view=False,
            reason=privacy.reason,
            metadata={"privacy": privacy.to_client_dict()},
            scan_state=scan_state.value,
            scan_targets=scan_targets,
        )

    title = _public_ride_title(ride)
    distance_km = (float(ride.get("distance_m") or 0) / 1000) if ride.get("distance_m") else None
    description = (
        f"{distance_km:.1f} km ride on Boulder Roller"
        if distance_km
        else "Ride on Boulder Roller"
    )
    return build_resolved_link(
        target_type=LinkTargetType.ride,
        target_id=ride_id,
        title=title,
        description=description,
        reason=privacy.reason,
        protocol_public=privacy.protocol_public,
        metadata={
            "rideId": ride_id,
            "ownerId": ride.get("user_id"),
            "status": ride.get("processing_status"),
            "visibility": ride.get("visibility") or "public",
            "privacy": privacy.to_client_dict(),
        },
        scan_state=scan_state.value,
        scan_targets=scan_targets,
    )


async def _resolve_climb_like_link(
    target_type: LinkTargetType,
    climb_id: str,
    repo: DatabaseRepository,
) -> dict:
    climb = await _get_climb_row(repo, climb_id)
    if not climb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link target not found")

    name = climb.get("name") or "Climb"
    titles = {
        LinkTargetType.climb: f"{name} on Boulder Roller",
        LinkTargetType.record_board: f"{name} Leaderboard",
        LinkTargetType.local_legend: f"{name} Local Legend",
    }
    descriptions = {
        LinkTargetType.climb: "Canonical climb on Boulder Roller.",
        LinkTargetType.record_board: "Leaderboard standings for this climb.",
        LinkTargetType.local_legend: "Local Legend status for this climb.",
    }
    scan_state, scan_targets = scan_targets_for_climb(climb)
    return build_resolved_link(
        target_type=target_type,
        target_id=climb_id,
        title=titles[target_type],
        description=descriptions[target_type],
        reason="protocol_public",
        protocol_public=True,
        metadata={
            "climbId": climb_id,
            "vaultId": climb.get("id") if str(climb.get("id")) != climb_id else None,
            "vaultSignature": climb.get("signature_hex"),
            "region": climb.get("region"),
        },
        scan_state=scan_state.value,
        scan_targets=scan_targets,
    )


def _resolve_protocol_link(target_type: LinkTargetType, target_id: str) -> dict:
    titles = {
        LinkTargetType.proof: "Boulder Roller proof",
        LinkTargetType.scan_tx: "BoulderScan transaction",
        LinkTargetType.scan_account: "BoulderScan account",
    }
    descriptions = {
        LinkTargetType.proof: "Protocol proof on Boulder Roller.",
        LinkTargetType.scan_tx: "Transaction on BoulderScan.",
        LinkTargetType.scan_account: "Account on BoulderScan.",
    }
    scan_state, scan_targets = scan_targets_for_protocol(target_type.value, target_id)
    return build_resolved_link(
        target_type=target_type,
        target_id=target_id,
        title=titles[target_type],
        description=descriptions[target_type],
        reason="protocol_public",
        protocol_public=True,
        metadata={"protocolPublic": True},
        scan_state=scan_state.value,
        scan_targets=scan_targets,
    )


async def _resolve_report_link(
    report_id: str,
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
) -> dict:
    if not current_user:
        return build_resolved_link(
            target_type=LinkTargetType.report,
            target_id=report_id,
            title="Report",
            description="Sign in to view this report.",
            status=LinkAccessStatus.forbidden,
            can_view=False,
            reason="auth_required",
            metadata={},
            scan_state="missing",
            scan_targets=[],
        )

    get_report = getattr(repo, "get_social_report_for_reporter", None)
    report = await get_report(report_id=report_id, reporter_id=current_user.user_id) if get_report else None
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link target not found")

    return build_resolved_link(
        target_type=LinkTargetType.report,
        target_id=report_id,
        title="Report status",
        description="Status of content you sent for review.",
        reason="reporter",
        metadata={
            "reportId": report_id,
            "targetType": report.get("targetType") or report.get("target_type"),
            "targetId": report.get("targetId") or report.get("target_id"),
            "status": report.get("status"),
        },
        scan_state="missing",
        scan_targets=[],
    )


async def _resolve_link(
    target_type: LinkTargetType,
    target_id: str,
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
) -> dict:
    if target_type == LinkTargetType.rider:
        return await _resolve_rider_link(target_id, repo, current_user)
    if target_type == LinkTargetType.ride:
        return await _resolve_ride_link(target_id, repo, current_user)
    if target_type in {LinkTargetType.climb, LinkTargetType.record_board, LinkTargetType.local_legend}:
        return await _resolve_climb_like_link(target_type, target_id, repo)
    if target_type in {LinkTargetType.proof, LinkTargetType.scan_tx, LinkTargetType.scan_account}:
        return _resolve_protocol_link(target_type, target_id)
    if target_type == LinkTargetType.report:
        return await _resolve_report_link(target_id, repo, current_user)
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported link target type")


@router.get("/schema")
async def get_link_schema() -> dict:
    return link_schema()


@router.get("/resolve")
async def resolve_link_query(
    target_type: Optional[str] = Query(default=None),
    target_id: Optional[str] = Query(default=None),
    url: Optional[str] = Query(default=None),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    if url:
        parsed = parse_link_target(url)
        if not parsed:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported link URL")
        resolved_type, resolved_id = parsed
    else:
        resolved_type = normalize_link_target_type(target_type)
        resolved_id = target_id
        if not resolved_type or not resolved_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_type and target_id are required when url is not provided",
            )

    return await _resolve_link(resolved_type, resolved_id, repo, current_user)


@router.get("/{target_type}/{target_id}")
async def resolve_link_path(
    target_type: str,
    target_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    resolved_type = normalize_link_target_type(target_type)
    if not resolved_type:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported link target type")
    return await _resolve_link(resolved_type, target_id, repo, current_user)
