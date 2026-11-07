"""
Privacy Zones Routes: GPS redaction area management.

Privacy zones allow users to hide GPS data within a radius of specific locations.
The portal supplies device-selected or manually entered coordinates plus a
radius choice (200/400/800/1600m); private addresses are not geocoded publicly.

Endpoints:
- GET  /privacy/zones        - List user's privacy zones
- POST /privacy/zones        - Create a new privacy zone
- PUT  /privacy/zones/{id}   - Update a privacy zone
- DELETE /privacy/zones/{id} - Delete a privacy zone
"""

from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository
from ..services.privacy_resolver import PROTOCOL_PUBLIC_RIDE_FIELDS, Visibility, normalize_visibility
from ..services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy

router = APIRouter(prefix="/privacy", tags=["privacy"])

# Allowed radius values (meters)
ALLOWED_RADII = [200, 400, 800, 1600]
MAX_ZONES_PER_USER = 5


class PrivacyZoneCreate(BaseModel):
    """Request to create a privacy zone."""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_m: Literal[200, 400, 800, 1600]
    label: Optional[str] = Field(None, max_length=50)


class PrivacyZoneUpdate(BaseModel):
    """Request to update a privacy zone."""
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: Optional[Literal[200, 400, 800, 1600]] = None
    label: Optional[str] = Field(None, max_length=50)


class PrivacyZoneResponse(BaseModel):
    """Privacy zone response model."""
    id: UUID
    latitude: float
    longitude: float
    radius_m: int
    label: Optional[str]
    created_at: str
    updated_at: str


class PrivacyZonesListResponse(BaseModel):
    """List of privacy zones."""
    zones: List[PrivacyZoneResponse]
    max_zones: int = MAX_ZONES_PER_USER


class PrivacySettingsUpdate(BaseModel):
    """Set-and-forget profile and ride visibility defaults."""
    model_config = ConfigDict(populate_by_name=True)
    share_wkg: Optional[StrictBool] = Field(
        default=None, validation_alias=AliasChoices("share_wkg", "shareWkg"),
    )

    is_public: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("is_public", "isPublic"),
    )
    default_ride_visibility: Optional[Visibility] = Field(
        default=None,
        validation_alias=AliasChoices("default_ride_visibility", "defaultRideVisibility"),
    )
    default_map_visibility: Optional[
        Literal["show_all", "hide_start_end", "hide_entire"]
    ] = Field(
        default=None,
        validation_alias=AliasChoices("default_map_visibility", "defaultMapVisibility"),
    )
    default_map_hide_start_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        default=None,
        validation_alias=AliasChoices(
            "default_map_hide_start_m",
            "defaultMapHideStartM",
        ),
    )
    default_map_hide_end_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        default=None,
        validation_alias=AliasChoices(
            "default_map_hide_end_m",
            "defaultMapHideEndM",
        ),
    )


class PrivacySettingsResponse(BaseModel):
    """Quiet privacy settings contract for profile defaults."""
    contract_version: str = Field(default="privacy.v2", alias="contractVersion")
    share_wkg: bool = Field(default=False, alias="shareWkg")
    profile_visibility: Literal["public", "private"] = Field(alias="profileVisibility")
    default_ride_visibility: Visibility = Field(alias="defaultRideVisibility")
    default_map_visibility: Literal[
        "show_all", "hide_start_end", "hide_entire"
    ] = Field(alias="defaultMapVisibility")
    default_map_hide_start_m: int = Field(alias="defaultMapHideStartM")
    default_map_hide_end_m: int = Field(alias="defaultMapHideEndM")
    defaults_apply_to: Literal["future_rides"] = Field(
        default="future_rides",
        alias="defaultsApplyTo",
    )
    provider_privacy_inherited: Literal[False] = Field(
        default=False,
        alias="providerPrivacyInherited",
    )
    privacy_zone_count: int = Field(alias="privacyZoneCount")
    privacy_zones_loaded: Literal[True] = Field(
        default=True,
        alias="privacyZonesLoaded",
    )
    ride_override_mode: Literal["optional"] = Field(default="optional", alias="rideOverrideMode")
    protocol_public_fields: List[str] = Field(alias="protocolPublicFields")

    model_config = ConfigDict(populate_by_name=True)


def _privacy_settings_from_user(
    user: dict,
    *,
    privacy_zone_count: int,
) -> PrivacySettingsResponse:
    if type(user.get("is_public")) is not bool:
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        )
    try:
        policy = RidePrivacyPolicy.from_values(
            visibility=user.get("default_ride_visibility"),
            map_visibility=user.get("default_map_visibility"),
            map_hide_start_m=user.get("default_map_hide_start_m"),
            map_hide_end_m=user.get("default_map_hide_end_m"),
        )
    except PrivacySettingsUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        ) from exc

    return PrivacySettingsResponse(
        shareWkg=user.get("share_wkg") is True,
        profileVisibility="public" if user["is_public"] else "private",
        defaultRideVisibility=policy.visibility,
        defaultMapVisibility=policy.map_visibility,
        defaultMapHideStartM=policy.map_hide_start_m,
        defaultMapHideEndM=policy.map_hide_end_m,
        privacyZoneCount=privacy_zone_count,
        protocolPublicFields=list(PROTOCOL_PUBLIC_RIDE_FIELDS),
    )


def _privacy_rows_or_503(response: object) -> list[dict]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        )
    if not all(isinstance(row, dict) for row in data):
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        )
    return data


async def _count_privacy_zones(repo: DatabaseRepository, user_id: str) -> int:
    """Count zones as part of the same fail-closed pre-submit contract."""
    count_method = getattr(repo, "count_privacy_zones", None)
    try:
        if count_method:
            return int(await count_method(user_id))
        response = await repo._run(
            lambda: repo._client.table("privacy_zones")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        ) from exc

    count = getattr(response, "count", None)
    if count is None:
        data = getattr(response, "data", None)
        if data is None:
            raise HTTPException(
                status_code=503,
                detail="Privacy settings are temporarily unavailable. Please retry.",
            )
        count = len(data)
    return int(count)


@router.get("/settings", response_model=PrivacySettingsResponse)
async def get_privacy_settings(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> PrivacySettingsResponse:
    """Return the rider's quiet profile and default ride visibility settings."""
    user = await repo.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Profile not found")
    zone_count = await _count_privacy_zones(repo, current_user.user_id)
    return _privacy_settings_from_user(user, privacy_zone_count=zone_count)


@router.put("/settings", response_model=PrivacySettingsResponse)
async def update_privacy_settings(
    payload: PrivacySettingsUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> PrivacySettingsResponse:
    """Update set-and-forget privacy defaults without touching each ride."""
    updates = {}
    if payload.share_wkg is not None:
        updates["share_wkg"] = payload.share_wkg
    if payload.is_public is not None:
        updates["is_public"] = payload.is_public
    if payload.default_ride_visibility is not None:
        updates["default_ride_visibility"] = normalize_visibility(
            payload.default_ride_visibility,
            default="public",
        )
    if payload.default_map_visibility is not None:
        updates["default_map_visibility"] = payload.default_map_visibility
    if payload.default_map_hide_start_m is not None:
        updates["default_map_hide_start_m"] = payload.default_map_hide_start_m
    if payload.default_map_hide_end_m is not None:
        updates["default_map_hide_end_m"] = payload.default_map_hide_end_m
    if not updates:
        raise HTTPException(status_code=400, detail="No privacy settings to update")
    updated = await repo.update_user_profile(current_user.wallet, updates)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update privacy settings")
    zone_count = await _count_privacy_zones(repo, current_user.user_id)
    return _privacy_settings_from_user(updated, privacy_zone_count=zone_count)


@router.get("/zones", response_model=PrivacyZonesListResponse)
async def list_privacy_zones(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> PrivacyZonesListResponse:
    """
    List all privacy zones for the current user.

    Returns up to 5 zones (maximum allowed per user).
    """
    response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .select("*")
        .eq("user_id", current_user.user_id)
        .order("created_at", desc=False)
        .execute()
    )
    zones_data = _privacy_rows_or_503(response)

    try:
        zones = [
            PrivacyZoneResponse(
                id=UUID(z["id"]),
                latitude=z["latitude"],
                longitude=z["longitude"],
                radius_m=z["radius_m"],
                label=z.get("label"),
                created_at=z["created_at"],
                updated_at=z["updated_at"],
            )
            for z in zones_data
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        ) from exc

    return PrivacyZonesListResponse(zones=zones, max_zones=MAX_ZONES_PER_USER)


@router.post("/zones", response_model=PrivacyZoneResponse)
async def create_privacy_zone(
    payload: PrivacyZoneCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> PrivacyZoneResponse:
    """
    Create a new privacy zone.

    Maximum 5 zones per user. Radius must be 200, 400, 800, or 1600 meters.
    """
    # Check existing zone count without treating an unavailable read as zero.
    zone_count = await _count_privacy_zones(repo, current_user.user_id)

    if zone_count >= MAX_ZONES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_ZONES_PER_USER} privacy zones allowed"
        )

    # Create zone
    insert_data = {
        "user_id": current_user.user_id,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "radius_m": payload.radius_m,
        "label": payload.label,
    }

    response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .insert(insert_data)
        .execute()
    )
    created = _privacy_rows_or_503(response)
    if len(created) == 0:
        raise HTTPException(status_code=500, detail="Failed to create privacy zone")

    z = created[0]
    return PrivacyZoneResponse(
        id=UUID(z["id"]),
        latitude=z["latitude"],
        longitude=z["longitude"],
        radius_m=z["radius_m"],
        label=z.get("label"),
        created_at=z["created_at"],
        updated_at=z["updated_at"],
    )


@router.put("/zones/{zone_id}", response_model=PrivacyZoneResponse)
async def update_privacy_zone(
    zone_id: UUID,
    payload: PrivacyZoneUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> PrivacyZoneResponse:
    """
    Update an existing privacy zone.

    Only the owner can update their zones.
    """
    # Verify ownership
    check_response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .select("id")
        .eq("id", str(zone_id))
        .eq("user_id", current_user.user_id)
        .limit(1)
        .execute()
    )
    existing = _privacy_rows_or_503(check_response)
    if not existing:
        raise HTTPException(status_code=404, detail="Privacy zone not found")

    # Build update
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .update(update_data)
        .eq("id", str(zone_id))
        .eq("user_id", current_user.user_id)
        .execute()
    )
    updated = _privacy_rows_or_503(response)
    if len(updated) == 0:
        raise HTTPException(status_code=500, detail="Failed to update privacy zone")

    z = updated[0]
    return PrivacyZoneResponse(
        id=UUID(z["id"]),
        latitude=z["latitude"],
        longitude=z["longitude"],
        radius_m=z["radius_m"],
        label=z.get("label"),
        created_at=z["created_at"],
        updated_at=z["updated_at"],
    )


@router.delete("/zones/{zone_id}")
async def delete_privacy_zone(
    zone_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> dict:
    """
    Delete a privacy zone.

    Only the owner can delete their zones.
    """
    # Verify ownership and delete
    response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .delete()
        .eq("id", str(zone_id))
        .eq("user_id", current_user.user_id)
        .execute()
    )
    deleted = _privacy_rows_or_503(response)
    if len(deleted) == 0:
        raise HTTPException(status_code=404, detail="Privacy zone not found")

    return {"status": "deleted", "id": str(zone_id)}


# =============================================================================
# UTILITY: Check if a point is within any privacy zone
# =============================================================================

async def get_user_privacy_zones(repo: DatabaseRepository, user_id: str) -> List[dict]:
    """
    Get all privacy zones for a user.

    Returns list of dicts with lat, lng, radius_m for efficient point checking.
    """
    response = await repo._run(
        lambda: repo._client.table("privacy_zones")
        .select("latitude, longitude, radius_m")
        .eq("user_id", user_id)
        .execute()
    )
    return _privacy_rows_or_503(response)


def is_point_in_privacy_zone(
    lat: float,
    lon: float,
    zones: List[dict],
) -> bool:
    """
    Check if a GPS point falls within any privacy zone.

    Uses Haversine formula for distance calculation.
    """
    import math

    EARTH_RADIUS_M = 6_371_000  # meters

    for zone in zones:
        zone_lat = zone["latitude"]
        zone_lon = zone["longitude"]
        radius_m = zone["radius_m"]

        # Haversine formula
        lat1 = math.radians(lat)
        lat2 = math.radians(zone_lat)
        dlat = math.radians(zone_lat - lat)
        dlon = math.radians(zone_lon - lon)

        a = (
            math.sin(dlat / 2) ** 2 +
            math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance_m = EARTH_RADIUS_M * c

        if distance_m <= radius_m:
            return True

    return False


def redact_gps_for_privacy(
    gps_points: List[dict],
    zones: List[dict],
) -> List[dict]:
    """
    Redact GPS points that fall within privacy zones.

    Points within zones have their lat/lon set to None while preserving
    other data (timestamp, elevation, etc.).
    """
    if not zones:
        return gps_points

    redacted = []
    for point in gps_points:
        lat = point.get("latitude")
        lon = point.get("longitude")

        if lat is not None and lon is not None and is_point_in_privacy_zone(lat, lon, zones):
            # Redact coordinates but keep other data
            redacted_point = {**point, "latitude": None, "longitude": None, "redacted": True}
            redacted.append(redacted_point)
        else:
            redacted.append(point)

    return redacted
