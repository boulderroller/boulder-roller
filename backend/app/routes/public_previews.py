"""Public preview API routes for app-domain object links."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ..dependencies import get_repository, get_vault_repository
from ..feed_contracts import build_route_preview
from ..public_preview_contracts import (
    build_climb_public_preview,
    build_ride_public_preview,
    build_rider_public_preview,
    is_public_preview_fixture_like,
    public_preview_cache_control,
    public_route_unavailable_preview,
)
from ..repositories import DatabaseRepository, VaultRepository
from ..repositories.ride import RideRepository
from ..ride_media_contracts import serialize_ride_media_list
from ..services.privacy_resolver import VisibilityDecision, resolve_ride_visibility
from ..services.public_ride_shape import build_public_ride_shape
from .climbs import get_climb, get_climb_leaderboard
from .rides import _ride_place_label, _decode_ride_gps_points, _project_route_for_viewer
from .users import get_public_user_profile_bootstrap


logger = logging.getLogger(__name__)

router = APIRouter(tags=["public-previews"])


def _cache_public_preview(response: Response) -> None:
    response.headers["Cache-Control"] = public_preview_cache_control()
    response.headers["X-Robots-Tag"] = "index,follow"


async def _ride_owner(repo: DatabaseRepository, ride: dict[str, Any]) -> Optional[dict[str, Any]]:
    owner_id = ride.get("user_id") or ride.get("rider_id")
    get_user_by_id = getattr(repo, "get_user_by_id", None)
    if not owner_id or not get_user_by_id:
        return None
    try:
        return await get_user_by_id(str(owner_id))
    except Exception as exc:
        logger.debug("[PublicPreview] Owner profile unavailable for ride %s: %s", ride.get("id"), exc)
        return None


async def _public_ride_media(repo: DatabaseRepository, ride_id: str) -> list[dict[str, Any]]:
    list_media = getattr(repo, "list_ride_media", None)
    if not list_media:
        return []
    try:
        rows = await list_media(ride_id)
        media = await serialize_ride_media_list(rows)
    except Exception as exc:
        logger.debug("[PublicPreview] Ride media unavailable for %s: %s", ride_id, exc)
        return []
    return [
        item.model_dump(mode="json", by_alias=True)
        for item in media
        if item.url
    ]


async def _attach_threshold_economy_state(
    ride: dict[str, Any], repo: DatabaseRepository
) -> dict[str, Any]:
    if ride.get("reward_policy") != "threshold_provisional_hold_v1":
        return ride
    reader = getattr(repo, "get_reward_threshold_ride_projections", None)
    if not callable(reader):
        client = getattr(repo, "client", None)
        if client is None:
            return ride
        reader = RideRepository(client).get_reward_threshold_ride_projections
    try:
        projection = (await reader([str(ride.get("id"))])).get(str(ride.get("id")))
    except Exception as exc:
        logger.warning("Threshold public preview projection unavailable: %s", exc)
        return ride
    if not isinstance(projection, dict):
        return ride
    projected = dict(ride)
    projected["_threshold_economy_state"] = projection.get("state")
    if projection.get("state") == "counted":
        projected["_threshold_released_cal"] = projection.get("cal_earned")
    return projected


async def _public_route_assets(
    ride: dict[str, Any],
    decision: VisibilityDecision,
    repo: DatabaseRepository,
) -> tuple[dict[str, Any], dict[str, Any]]:
    privacy = decision.to_client_dict()
    raw = _decode_ride_gps_points(ride)
    points, zones = await _project_route_for_viewer(ride, raw, decision, repo)
    preview = build_route_preview(
        points,
        source="server_gps",
        place_label=_ride_place_label(ride),
        privacy=privacy,
        privacy_zones=zones,
    )
    if preview is not None:
        steps = []
        reader = getattr(repo, "list_counted_climb_steps", None)
        if not callable(reader) and getattr(repo, "client", None) is not None:
            reader = RideRepository(repo.client).list_counted_climb_steps
        if callable(reader) and preview.get("segments"):
            authority_ride = {**ride, "threshold_economy_state": ride.get("_threshold_economy_state", ride.get("threshold_economy_state"))}
            try:
                steps = (await reader([authority_ride])).get(str(ride.get("id")), [])
            except Exception as exc:
                logger.warning("Public counted spans unavailable: %s", exc)
        return preview, build_public_ride_shape(ride, raw, points, steps, preview)
    return public_route_unavailable_preview(
        source="server_gps",
        place_label=_ride_place_label(ride),
        redacted_gps=bool(privacy.get("redactGps")),
    ), {}


def _climb_name(climb: Any) -> Optional[str]:
    if isinstance(climb, dict):
        value = climb.get("name")
    else:
        value = getattr(climb, "name", None)
    return str(value).strip() if value else None


@router.get("/rides/{ride_id}")
async def get_ride_public_preview(
    ride_id: str,
    response: Response,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Return a signed-out-safe ride preview for app-domain public routes."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride preview unavailable")
    if is_public_preview_fixture_like(
        ride.get("title"),
        ride.get("name"),
        ride.get("file_name"),
        ride.get("fileName"),
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride preview unavailable")

    decision = await resolve_ride_visibility(ride, None, repo=repo)
    if not decision.can_view:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride preview unavailable")

    ride = await _attach_threshold_economy_state(ride, repo)
    from ..services.training_metrics import project_training
    ride = project_training(ride, owner=False)
    privacy = decision.to_client_dict()
    owner, media = await _load_ride_sidecars(repo, ride_id, ride)
    route_preview, shape = await _public_route_assets(ride, decision, repo)
    preview = build_ride_public_preview(
        ride,
        privacy=privacy,
        owner=owner,
        route_preview=route_preview,
        shape=shape,
        media=media,
    )
    _cache_public_preview(response)
    return preview


@router.get("/activities/{ride_id}")
async def get_activity_public_preview(
    ride_id: str,
    response: Response,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Compatibility alias for Strava-style activity links."""
    return await get_ride_public_preview(ride_id, response, repo)


async def _load_ride_sidecars(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
    owner = await _ride_owner(repo, ride)
    media = await _public_ride_media(repo, ride_id)
    return owner, media


@router.get("/climbs/{climb_id}")
async def get_climb_public_preview(
    climb_id: str,
    response: Response,
    repo: DatabaseRepository = Depends(get_repository),
):
    """Return a signed-out-safe climb preview with an attached Record Board."""
    climb = await get_climb(climb_id, repo=repo)
    if is_public_preview_fixture_like(_climb_name(climb)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Climb preview unavailable")
    record_board: Optional[Any]
    try:
        record_board = await get_climb_leaderboard(climb_id, repo=repo, current_user=None)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        record_board = None
    preview = build_climb_public_preview(climb, record_board=record_board)
    _cache_public_preview(response)
    return preview


@router.get("/riders/{identifier}")
async def get_rider_public_preview(
    identifier: str,
    response: Response,
    limit: int = Query(5, ge=1, le=10),
    repo: DatabaseRepository = Depends(get_repository),
    vault_repo: VaultRepository = Depends(get_vault_repository),
):
    """Return a signed-out-safe rider preview without private ride history."""
    profile = await get_public_user_profile_bootstrap(
        identifier=identifier,
        limit=limit,
        current_user=None,
        repo=repo,
        vault_repo=vault_repo,
    )
    preview = build_rider_public_preview(profile, identifier=identifier)
    _cache_public_preview(response)
    if preview["seo"]["robots"] == "noindex,nofollow":
        response.headers["X-Robots-Tag"] = "noindex,nofollow"
    return preview
