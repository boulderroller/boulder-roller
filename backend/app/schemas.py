from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_serializer, model_validator

from .rider_identity_contracts import PublicRiderRef


# Enums

class PreferredUnits(str, Enum):
    metric = "metric"
    imperial = "imperial"


class ThemeId(str, Enum):
    hoo_breddin = "hoo-breddin"
    water = "water"
    sunny = "sunny"
    safari = "safari"
    moss = "moss"
    foundries = "foundries"


class RiderType(str, Enum):
    climber = "climber"
    sprinter = "sprinter"
    tt = "tt"
    rouleur = "rouleur"
    allrounder = "allrounder"
    diesel = "diesel"


class NonceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    wallet: str = Field(..., min_length=1)
    device_id: UUID = Field(validation_alias=AliasChoices("device_id", "deviceId"))


class NonceResponse(BaseModel):
    nonce: str
    message: str  # Full SIWS message for client to sign
    issued_at: datetime
    expires_at: datetime


class VerifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    wallet: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=1)
    nonce: str = Field(..., min_length=1)
    device_id: UUID = Field(validation_alias=AliasChoices("device_id", "deviceId"))
    invite_code: Optional[str] = Field(
        None,
        min_length=1,
        description="Invite code for gated signup",
        validation_alias=AliasChoices("invite_code", "inviteCode"),
    )


class PrivyVerifyRequest(BaseModel):
    """Request to verify a Privy access token."""
    model_config = ConfigDict(populate_by_name=True)
    wallet: str = Field(..., min_length=1)
    privy_token: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("privy_token", "privyToken"),
    )
    device_id: UUID = Field(validation_alias=AliasChoices("device_id", "deviceId"))
    invite_code: Optional[str] = Field(
        None,
        min_length=1,
        description="Invite code for gated signup",
        validation_alias=AliasChoices("invite_code", "inviteCode"),
    )


class TokenPair(BaseModel):
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class VerifyResponse(TokenPair):
    user_id: UUID
    wallet: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    refresh_token: Optional[str] = Field(
        None,
        min_length=1,
        description="Refresh token. Required for mobile clients that cannot send HttpOnly cookies.",
        validation_alias=AliasChoices("refresh_token", "refreshToken"),
    )
    device_id: UUID = Field(validation_alias=AliasChoices("device_id", "deviceId"))


class RefreshResponse(TokenPair):
    wallet: str


class LogoutRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    refresh_token: Optional[str] = Field(
        None,
        min_length=1,
        description="Refresh token. Required for mobile clients that cannot send HttpOnly cookies.",
        validation_alias=AliasChoices("refresh_token", "refreshToken"),
    )
    device_id: UUID = Field(validation_alias=AliasChoices("device_id", "deviceId"))


class OnboardingStateResponse(BaseModel):
    authenticated: bool
    invite_required: bool
    invite_validated: bool
    needs_profile_setup: bool
    auth_method_hint: Optional[str] = None


class UserProfile(BaseModel):
    id: UUID
    wallet: str
    email: Optional[str] = None
    created_at: Optional[datetime] = None


class RideUploadRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    file_data_b64: str = Field(validation_alias=AliasChoices("file_data_b64", "fileDataB64"))
    file_type: str = Field(validation_alias=AliasChoices("file_type", "fileType"))  # "fit", "gpx", "tcx"
    preliminary_ride_hash: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description=(
            "Device-side canonical ride hash (hex) captured at stop time. "
            "Required for first-party recorder uploads; provider/manual uploads "
            "use provenance policy instead."
        ),
        validation_alias=AliasChoices("preliminary_ride_hash", "preliminaryRideHash"),
    )
    parser_version: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "Device-side parser version used to compute preliminary_ride_hash. "
            "Required for first-party recorder uploads; provider/manual uploads "
            "use provenance policy instead."
        ),
        validation_alias=AliasChoices("parser_version", "parserVersion"),
    )
    visibility: Optional[Literal["public", "followers", "private"]] = None
    map_visibility: Optional[Literal["show_all", "hide_start_end", "hide_entire"]] = Field(
        None,
        validation_alias=AliasChoices("map_visibility", "mapVisibility"),
    )
    map_hide_start_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_start_m", "mapHideStartM"),
    )
    map_hide_end_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_end_m", "mapHideEndM"),
    )


class RideUploadResponse(BaseModel):
    ride_id: UUID
    status: str
    message: str


class UploadInitRequest(BaseModel):
    """Request to initiate a presigned upload."""
    model_config = ConfigDict(populate_by_name=True)
    client_request_id: Optional[UUID] = Field(
        None,
        description=(
            "Stable rider-generated upload identity. The backend uses this UUID "
            "as the upload/ride ID so an interrupted client can reconcile or retry "
            "the same logical upload without creating another row."
        ),
        validation_alias=AliasChoices("client_request_id", "clientRequestId"),
    )
    file_type: str = Field(..., description="File extension: fit, gpx, or tcx")
    file_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hex digest of the file",
    )
    file_size: int = Field(
        ...,
        gt=0,
        le=50 * 1024 * 1024,
        description="File size in bytes (max 50 MB)",
        validation_alias=AliasChoices("file_size", "fileSize"),
    )
    preliminary_ride_hash: Optional[str] = Field(
        None,
        min_length=64,
        max_length=64,
        description=(
            "Device-side canonical ride hash (hex) captured at stop time. "
            "Required for first-party recorder uploads; provider/manual uploads "
            "use provenance policy instead."
        ),
        validation_alias=AliasChoices("preliminary_ride_hash", "preliminaryRideHash"),
    )
    parser_version: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "Device-side parser version used to compute preliminary_ride_hash. "
            "Required for first-party recorder uploads; provider/manual uploads "
            "use provenance policy instead."
        ),
        validation_alias=AliasChoices("parser_version", "parserVersion"),
    )
    client_completed_at: Optional[datetime] = Field(
        None,
        description=(
            "Client-observed activity completion timestamp for advisory upload "
            "warnings; backend re-parses the file before economics."
        ),
        validation_alias=AliasChoices("client_completed_at", "clientCompletedAt"),
    )
    visibility: Optional[Literal["public", "followers", "private"]] = None
    map_visibility: Optional[Literal["show_all", "hide_start_end", "hide_entire"]] = Field(
        None,
        validation_alias=AliasChoices("map_visibility", "mapVisibility"),
    )
    map_hide_start_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_start_m", "mapHideStartM"),
    )
    map_hide_end_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_end_m", "mapHideEndM"),
    )


class UploadInitResponse(BaseModel):
    """Response from upload init with presigned URL."""
    upload_id: str = Field(alias="uploadId")
    signed_url: str = Field(alias="signedUrl")
    expires_in: int = Field(alias="expiresIn")

    model_config = {"populate_by_name": True, "by_alias": True}


class UploadCompleteRequest(BaseModel):
    """Request to finalize a presigned upload."""
    model_config = ConfigDict(populate_by_name=True)
    upload_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("upload_id", "uploadId"),
    )


class UploadCompleteResponse(BaseModel):
    """Response from upload complete."""
    ride_id: str = Field(alias="rideId")
    status: str

    model_config = {"populate_by_name": True, "by_alias": True}


class UploadAbortRequest(BaseModel):
    """Request to abort a presigned upload."""
    model_config = ConfigDict(populate_by_name=True)
    upload_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("upload_id", "uploadId"),
    )


class UploadAbortResponse(BaseModel):
    """Response from upload abort."""
    status: str


class RideMedia(BaseModel):
    """A persisted image attached to a ride."""
    id: UUID
    ride_id: UUID = Field(alias="rideId")
    url: Optional[str] = None
    file_name: Optional[str] = Field(default=None, alias="fileName")
    mime_type: str = Field(alias="mimeType")
    size_bytes: int = Field(alias="sizeBytes")
    width: Optional[int] = None
    height: Optional[int] = None
    sort_order: int = Field(default=0, alias="sortOrder")
    role: Literal["photo", "cover"] = "photo"
    moderation_state: str = Field(default="visible", alias="moderationState")
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")

    model_config = {"populate_by_name": True, "by_alias": True}


class RideMediaInitRequest(BaseModel):
    """Request to initiate a presigned ride media upload."""
    model_config = ConfigDict(populate_by_name=True)

    client_request_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasChoices("client_request_id", "clientRequestId"),
    )

    file_name: Optional[str] = Field(
        default=None,
        max_length=240,
        validation_alias=AliasChoices("file_name", "fileName"),
    )
    mime_type: str = Field(
        ...,
        min_length=3,
        max_length=80,
        validation_alias=AliasChoices("mime_type", "mimeType"),
    )
    file_size: int = Field(
        ...,
        gt=0,
        le=15 * 1024 * 1024,
        validation_alias=AliasChoices("file_size", "fileSize"),
    )
    sort_order: Optional[int] = Field(
        default=None,
        ge=0,
        le=1000,
        validation_alias=AliasChoices("sort_order", "sortOrder"),
    )
    role: Literal["photo", "cover"] = "photo"


class RideMediaInitResponse(BaseModel):
    """Response from ride media upload init."""
    media_id: str = Field(alias="mediaId")
    signed_url: str = Field(alias="signedUrl")
    expires_in: int = Field(alias="expiresIn")

    model_config = {"populate_by_name": True, "by_alias": True}


class RideMediaCompleteRequest(BaseModel):
    """Request to finalize a presigned ride media upload."""
    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("media_id", "mediaId"),
    )


class RideMediaUpdateRequest(BaseModel):
    """Owner controls for an existing ride photo."""
    model_config = ConfigDict(populate_by_name=True)

    sort_order: Optional[int] = Field(
        default=None,
        ge=0,
        le=1000,
        validation_alias=AliasChoices("sort_order", "sortOrder"),
    )
    role: Optional[Literal["photo", "cover"]] = None


class RideMediaReorderItem(BaseModel):
    """One ride photo's desired display position."""
    model_config = ConfigDict(populate_by_name=True)

    media_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("media_id", "mediaId"),
    )
    sort_order: int = Field(
        ...,
        ge=0,
        le=1000,
        validation_alias=AliasChoices("sort_order", "sortOrder"),
    )


class RideMediaReorderRequest(BaseModel):
    """Batch reorder request for ride photos."""
    model_config = ConfigDict(populate_by_name=True)

    items: list[RideMediaReorderItem] = Field(default_factory=list, max_length=6)


class AvatarUploadInitRequest(BaseModel):
    """Request to initiate a presigned rider avatar upload."""
    model_config = ConfigDict(populate_by_name=True)

    file_name: Optional[str] = Field(
        default=None,
        max_length=240,
        validation_alias=AliasChoices("file_name", "fileName"),
    )
    mime_type: str = Field(
        ...,
        min_length=3,
        max_length=80,
        validation_alias=AliasChoices("mime_type", "mimeType"),
    )
    file_size: int = Field(
        ...,
        gt=0,
        le=15 * 1024 * 1024,
        validation_alias=AliasChoices("file_size", "fileSize"),
    )


class AvatarUploadInitResponse(BaseModel):
    """Response from avatar upload init."""
    upload_id: str = Field(alias="uploadId")
    signed_url: str = Field(alias="signedUrl")
    expires_in: int = Field(alias="expiresIn")

    model_config = {"populate_by_name": True, "by_alias": True}


class AvatarUploadCompleteRequest(BaseModel):
    """Request to finalize a presigned rider avatar upload."""
    model_config = ConfigDict(populate_by_name=True)

    upload_id: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("upload_id", "uploadId"),
    )


class RideUpdateRequest(BaseModel):
    """Request to update ride metadata."""
    title: Optional[str] = None
    description: Optional[str] = None
    activity_type: Optional[str] = None
    visibility: Optional[Literal["public", "followers", "private"]] = None
    map_visibility: Optional[Literal["show_all", "hide_start_end", "hide_entire"]] = None
    map_hide_start_m: Optional[Literal[0, 200, 400, 800, 1600]] = None
    map_hide_end_m: Optional[Literal[0, 200, 400, 800, 1600]] = None
    comments_enabled: Optional[bool] = None
    hide_from_leaderboards: Optional[bool] = None
    perceived_exertion: Optional[int] = Field(
        None, ge=1, le=10, alias="perceivedExertion",
        description="Rider-entered effort 1-10; explicit null clears.",
    )


class PrivacyState(BaseModel):
    """Resolved visibility state clients can render without duplicating policy."""
    visibility: Literal["public", "followers", "private"]
    can_view: bool = Field(alias="canView")
    is_owner: bool = Field(default=False, alias="isOwner")
    is_follower: bool = Field(default=False, alias="isFollower")
    redact_gps: bool = Field(default=True, alias="redactGps")
    map_visibility: Literal["show_all", "hide_start_end", "hide_entire"] = Field(
        default="hide_entire",
        alias="mapVisibility",
    )
    map_hide_start_m: int = Field(default=0, alias="mapHideStartM")
    map_hide_end_m: int = Field(default=0, alias="mapHideEndM")
    protocol_public: bool = Field(default=False, alias="protocolPublic")
    protocol_public_fields: list[str] = Field(default_factory=list, alias="protocolPublicFields")
    reason: str

    model_config = {"populate_by_name": True, "by_alias": True}


class VaultCompletionInfo(BaseModel):
    """Vault completion info embedded in ride records."""
    vault_id: int = Field(alias="vaultId")
    vault_name: str = Field(alias="vaultName")
    vault_signature: str = Field(alias="vaultSignature")
    time_seconds: Optional[int] = Field(default=None, alias="timeSeconds")

    model_config = {"populate_by_name": True, "by_alias": True}


class RoutePreviewPoint(BaseModel):
    x: float
    y: float


class RoutePreviewBounds(BaseModel):
    min_lat: float = Field(alias="minLat")
    min_lon: float = Field(alias="minLon")
    max_lat: float = Field(alias="maxLat")
    max_lon: float = Field(alias="maxLon")

    model_config = {"populate_by_name": True, "by_alias": True}


class RoutePreview(BaseModel):
    contract_version: str = Field(default="route_preview.v1", alias="contractVersion")
    source: str
    points: list[RoutePreviewPoint] = Field(default_factory=list)
    segments: list[list[RoutePreviewPoint]] = Field(default_factory=list)
    point_count: int = Field(default=0, alias="pointCount")
    bounds: Optional[RoutePreviewBounds] = None
    place_label: Optional[str] = Field(default=None, alias="placeLabel")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")
    privacy: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "by_alias": True}


class ElevationCorrectionInfo(BaseModel):
    """Provenance for the DEM elevation correction projection.

    ``status`` is ``corrected`` or ``unavailable``. The object is absent
    entirely on rides where correction was never attempted (legacy rides).
    ``elevationCorrectedM`` on the ride carries the trustworthy total; when it
    is null clients render a dash, never a zero.
    """

    status: str
    source_version: Optional[str] = Field(default=None, alias="sourceVersion")
    correction_version: Optional[str] = Field(default=None, alias="correctionVersion")
    coverage_bps: Optional[int] = Field(default=None, alias="coverageBps")
    reason: Optional[str] = None

    model_config = {"populate_by_name": True, "by_alias": True}


class RideCalItemizationClimb(BaseModel):
    """One matched climb's share of a ride's CAL itemization.

    ``cal_tribute_base_units`` is the exact measured Climb-TSS tribute frozen
    for this climb by ``cal_tribute_segment_tss_v2``. It is accounted to the
    Vault's flow meter and is never minted as CAL or deducted from the rider.
    """

    pattern_id: str = Field(alias="patternId")
    vault_id: int = Field(alias="vaultId")
    vault_signature: str = Field(alias="vaultSignature")
    climb_name: Optional[str] = Field(default=None, alias="climbName")
    cal_tribute_base_units: str = Field(alias="calTributeBaseUnits")
    completion_time_s: Optional[int] = Field(default=None, alias="completionTimeS")
    intensity_bps: Optional[int] = Field(default=None, alias="intensityBps")

    model_config = {"populate_by_name": True, "by_alias": True}


class RideCalItemization(BaseModel):
    """Per-climb CAL itemization for a completed ride.

    This exposes the decomposition the protocol already computes: the frozen
    economic plan's vault-tribute flow (PROTOCOL_TRUTHS tribute policy). The
    rider's credited CAL is never reduced by tribute; climbs are attributed
    their exact tribute share and ``everything_between_base_units`` is the
    un-attributed remainder, so the parts always sum exactly to the ride
    total. Base units are decimal strings (CAL has 9 decimals) — never parse
    them through binary floats.
    """

    contract_version: str = Field(default="client.v1", alias="contractVersion")
    basis: str = Field(default="vault_tribute_flow")
    tribute_policy_version: str = Field(alias="tributePolicyVersion")
    cal_decimals: int = Field(default=9, alias="calDecimals")
    ride_cal_base_units: str = Field(alias="rideCalBaseUnits")
    tribute_budget_base_units: str = Field(alias="tributeBudgetBaseUnits")
    climbs: list[RideCalItemizationClimb] = Field(default_factory=list)
    everything_between_base_units: str = Field(alias="everythingBetweenBaseUnits")

    model_config = {"populate_by_name": True, "by_alias": True}


class RideElevationPoint(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    distance_m: float = Field(alias="distanceM")
    elevation_m: float = Field(alias="elevationM")


class RideCountedSpan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    start_distance_m: float = Field(alias="startDistanceM")
    end_distance_m: float = Field(alias="endDistanceM")
    pattern_id: Optional[str] = Field(
        default=None, alias="patternId",
        description="Frozen canonical pattern identity shared with the ride's climb rows; omitted when unavailable.",
    )

    @model_serializer(mode="wrap")
    def omit_absent_pattern_id(self, handler):
        data = handler(self)
        if self.pattern_id is None:
            data.pop("pattern_id", None)
            data.pop("patternId", None)
        return data


class RideRecord(BaseModel):
    """
    Ride record with camelCase aliases for frontend compatibility.

    Status values (multi-phase processing):
    - pending: Uploaded, waiting for processing
    - processing: Phase 1 in progress
    - metrics_ready: Phase 1 complete - metrics/GPS available
    - enriched: Phase 2 complete - patterns/leaderboards available
    - completed: Phase 3 complete - all data including rewards
    - under_review: canonical mismatch detected; ride stored but not auto-attested
    - failed: Processing failed
    """
    id: UUID
    # Tim S3: caption empty; these facts do not authorize numeric rider copy.
    effort_seconds: Optional[int] = Field(default=None, alias="effortSeconds")
    covered_effort_seconds: Optional[int] = Field(default=None, alias="coveredEffortSeconds")
    paid_effort_seconds: Optional[int] = Field(default=None, alias="paidEffortSeconds")
    subject_states: dict[str, dict[str, str | None]] = Field(default_factory=dict, alias="subjectStates")
    elevation_profile: Optional[list[RideElevationPoint]] = Field(default=None, alias="elevationProfile")
    counted_spans: Optional[list[RideCountedSpan]] = Field(default=None, alias="countedSpans")

    @model_serializer(mode="wrap")
    def omit_unavailable_list_fields(self, handler):
        data = handler(self)
        for key in ("elevation_profile", "elevationProfile", "counted_spans", "countedSpans"):
            if data.get(key) is None:
                data.pop(key, None)
        if self.uploaded_at is None or not (self.privacy and self.privacy.is_owner):
            data.pop("uploaded_at", None)
            data.pop("uploadedAt", None)
        return data

    rider_id: UUID = Field(alias="riderId")
    started_at: datetime = Field(alias="startedAt")
    uploaded_at: Optional[datetime] = Field(
        default=None, alias="uploadedAt",
        description="Stored upload time, projected only in the owner's ride list; omitted when unavailable.",
    )
    completed_at: Optional[datetime] = Field(default=None, alias="completedAt")
    patterns: list[dict[str, Any]] = Field(default_factory=list)
    calories_burned: Optional[float] = Field(default=None, alias="calories")
    training_metrics: Optional[dict[str, Any]] = Field(default=None, alias="trainingMetrics")
    moving_time_sec: Optional[int] = Field(default=None, alias="movingTimeS")
    recording_time_sec: Optional[int] = Field(default=None, alias="recordingTimeS")
    # Status supports: pending, processing, metrics_ready, enriched, completed, under_review, failed
    status: str = "completed"
    distance_m: Optional[float] = Field(default=None, alias="distanceM")
    elevation_gain_m: Optional[float] = Field(default=None, alias="elevationM")
    # DEM-corrected climbing total (projection; boulderroller-v2-odmi6.2.1).
    # None = no trustworthy corrected value — clients dash, never zero.
    # elevation_gain_m above stays raw device truth and is never replaced.
    elevation_corrected_m: Optional[float] = Field(
        default=None, alias="elevationCorrectedM"
    )
    elevation_correction: Optional[ElevationCorrectionInfo] = Field(
        default=None, alias="elevationCorrection"
    )
    duration_sec: Optional[int] = Field(default=None, alias="durationS")
    tss: Optional[float] = None
    threshold_training_state: Optional[Literal["pending"]] = Field(
        default=None, alias="thresholdTrainingState"
    )
    # Token earnings
    dung_minted: Optional[int] = Field(default=None, alias="dungEarned")
    cal_earned: Optional[int] = Field(default=None, alias="calEarned")
    effort_evidence_tier: Optional[str] = Field(default=None, alias="effortEvidenceTier")
    reward_policy: Optional[str] = Field(default=None, alias="rewardPolicy")
    threshold_economy_state: Optional[
        Literal["held", "counted", "lapsed", "review", "not_counted"]
    ] = Field(default=None, alias="thresholdEconomyState")
    estimated_cal: Optional[int] = Field(default=None, alias="estimatedCal")
    rewardable_cal: Optional[int] = Field(default=None, alias="rewardableCal")
    tributable_cal: Optional[int] = Field(default=None, alias="tributableCal")
    threshold_release_status: Optional[str] = Field(
        default=None, alias="thresholdReleaseStatus"
    )
    title: Optional[str] = None
    description: Optional[str] = None
    avg_power_w: Optional[float] = Field(default=None, alias="avgPowerW")
    normalized_power_w: Optional[float] = Field(default=None, alias="normalizedPowerW")
    # Average heart rate in bpm. None = the ride carried no HR data; the
    # backend never fabricates a zero for absent sensors.
    avg_hr_bpm: Optional[float] = Field(default=None, alias="avgHrBpm")
    # Per-climb CAL itemization from the frozen economic plan. None = no
    # complete frozen plan exists for this ride (legacy or still processing).
    cal_itemization: Optional[RideCalItemization] = Field(
        default=None, alias="calItemization"
    )
    # Ride depth fields (2026-08-18): rider-entered effort, display-only
    # weather, device laps, and power balance. The record model is a
    # whitelist — new ride columns must be named here to reach clients.
    perceived_exertion: Optional[int] = Field(default=None, alias="perceivedExertion")
    weather_temp_c: Optional[float] = Field(default=None, alias="weatherTempC")
    weather_wind_mps: Optional[float] = Field(default=None, alias="weatherWindMps")
    weather_wind_deg: Optional[int] = Field(default=None, alias="weatherWindDeg")
    weather_source: Optional[str] = Field(default=None, alias="weatherSource")
    laps: Optional[list[dict[str, Any]]] = None
    power_balance: Optional[dict[str, Any]] = Field(default=None, alias="powerBalance")
    attestation_status: str = Field(default="pending", alias="attestationStatus")
    ride_hash_hex: Optional[str] = Field(default=None, alias="rideHashHex")
    attestation_commitment_hex: Optional[str] = Field(default=None, alias="attestationCommitmentHex")
    parser_version: Optional[int] = Field(default=None, alias="parserVersion")
    preliminary_ride_hash_hex: Optional[str] = Field(default=None, alias="preliminaryRideHashHex")
    preliminary_parser_version: Optional[int] = Field(default=None, alias="preliminaryParserVersion")
    canonical_match: Optional[bool] = Field(default=None, alias="canonicalMatch")
    review_reason: Optional[str] = Field(default=None, alias="reviewReason")
    visibility: Literal["public", "followers", "private"] = "public"
    privacy: Optional[PrivacyState] = None
    ride_attestation_pda: Optional[str] = Field(default=None, alias="rideAttestationPda")
    ride_attestation_tx_signature: Optional[str] = Field(default=None, alias="rideAttestationTxSignature")
    ride_attested_at: Optional[datetime] = Field(default=None, alias="rideAttestedAt")
    # BACKEND_TRUTHS §3.3 — settlement-week finalization time (chain-derived).
    # NULL = earnings not yet locked; any value = this ride's settlement
    # week is immutable and all economic consequences are permanent.
    finalized_at: Optional[datetime] = Field(default=None, alias="finalizedAt")
    # Vault completions for this ride
    vault_completions: list[VaultCompletionInfo] = Field(default_factory=list, alias="vaultCompletions")
    route_preview: Optional[RoutePreview] = Field(default=None, alias="routePreview")
    media: list[RideMedia] = Field(default_factory=list)
    # Processing progress indicators (for frontend polling)
    has_gps: bool = Field(default=False, alias="hasGps")
    has_patterns: bool = Field(default=False, alias="hasPatterns")
    has_leaderboards: bool = Field(default=False, alias="hasLeaderboards")
    has_achievements: bool = Field(default=False, alias="hasAchievements")

    model_config = {"populate_by_name": True, "by_alias": True}


class ProofVerifyRequest(BaseModel):
    ride_id: UUID
    signature: str


class ProofVerifyResponse(BaseModel):
    proof_id: UUID
    effort_score: float


class MintIssueRequest(BaseModel):
    proof_id: UUID
    amount: float


class MintIssueResponse(BaseModel):
    event_id: UUID
    proof_id: UUID
    tx_hash: str
    amount: float
    status: Literal["submitted"]
    created_at: datetime


class TokenBalanceResponse(BaseModel):
    dung: str
    dung_base_units: str
    dung_source: Literal["spl_wallet_ata"]
    dung_status: Literal["live", "not_initialized"]
    dung_token_account: str
    dung_slot: int
    kcal: float


class HealthResponse(BaseModel):
    status: Literal["ok"]


class BalanceRolloutActionStatus(BaseModel):
    key: str
    label: str
    enabled: bool
    order: int
    boundary_action: bool = False


class BalanceRolloutStatus(BaseModel):
    stage: str
    cohort: str
    enabled_actions: list[str]
    action_order: list[str]
    actions: list[BalanceRolloutActionStatus]
    owner: Optional[str] = None
    rollback_owner: Optional[str] = None
    rollback_contact: Optional[str] = None
    started_at: Optional[str] = None
    enforced: bool = True
    order_valid: bool = True
    blockers: list[str] = Field(default_factory=list)


class MobileCapabilities(BaseModel):
    """Self-hosted mobile feature availability (L3.08/L3.04 contract).

    A fixed allowlist of shipped native capabilities — a flag can disable
    one in an emergency, never enable something unshipped. Operator levers
    are the ``BR_MOBILE_CAP_*`` environment variables (documented with the
    kill-switch runbook, bead f4acp.2.5); the safe default is available.
    """
    contract_version: str = "mobile_caps.v1"
    owner: str = "mobile-lane"
    ride_upload: bool = True
    push_registration: bool = True
    profile_writes: bool = True


class Stage1UIStatus(BaseModel):
    live: bool = False
    actions: bool = False


class StatusResponse(BaseModel):
    invite_required: bool = False
    cohort_admission_required: bool = False
    """System status including feature flags and environment info."""
    environment: str  # "development", "staging", "production"
    environment_public: bool = False
    solana_stub_mode: bool  # True if using stubbed Solana transactions
    version: Optional[str] = None
    auth_signature_bypass_requested: bool = False
    auth_signature_bypass_effective: bool = False
    auth_cookie_secure: bool = True
    dev_routes_enabled: bool = False
    balance_rollout: BalanceRolloutStatus
    mobile_capabilities: MobileCapabilities = Field(default_factory=MobileCapabilities)
    stage1: Stage1UIStatus = Field(default_factory=Stage1UIStatus)


class SolBalanceResponse(BaseModel):
    """Payer wallet SOL balance for operational monitoring."""
    balance_sol: float
    alert: bool  # True if balance < threshold (default 0.5 SOL)
    wallet: str  # Base58 pubkey of the payer wallet
    cached: bool = False  # True if result is from cache


# Profile Hub Schemas

class UsernameCheckRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20)


class UsernameCheckResponse(BaseModel):
    available: bool
    reason: Optional[str] = None


class UserProfileUpdate(BaseModel):
    """Profile update request - accepts both camelCase (frontend) and snake_case."""
    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="before")
    @classmethod
    def ignore_retired_profile_keys(cls, value: Any) -> Any:
        """Keep one client generation working after manual FTP retirement."""
        if not isinstance(value, dict):
            return value
        filtered = dict(value)
        for key in (
            "ftp_w",
            "ftpW",
            "ftp_w_source",
            "ftpWSource",
            "unit_preference",
            "unitPreference",
            "preferred_units",
            "preferredUnits",
        ):
            filtered.pop(key, None)
        return filtered

    username: Optional[str] = Field(None, min_length=3, max_length=20)
    display_name: Optional[str] = Field(None, max_length=50, alias="displayName")
    bio: Optional[str] = Field(None, max_length=280)
    avatar_url: Optional[str] = Field(
        None,
        alias="avatarUrl",
        description="Deprecated. Use /users/me/avatar upload endpoints.",
    )
    weight_kg: Optional[float] = Field(None, ge=30, le=300, alias="weightKg")
    preferred_units: Optional[PreferredUnits] = Field(None, alias="units")
    is_public: Optional[bool] = Field(None, alias="isPublic")
    default_ride_visibility: Optional[Literal["public", "followers", "private"]] = Field(
        None,
        alias="defaultRideVisibility",
    )
    # Theme and display preferences
    theme_id: Optional[ThemeId] = Field(None, alias="themeId")
    is_dark_mode: Optional[bool] = Field(None, alias="isDarkMode")
    rider_type: Optional[RiderType] = Field(None, alias="riderType")
    location: Optional[str] = Field(None, max_length=100)


class UserStats(BaseModel):
    total_rides: int = 0
    total_distance_km: float = 0
    total_elevation_m: float = 0
    total_tss: float = 0
    total_kcals: float = 0
    total_duration_sec: int = 0
    total_dung_earned: int = 0


class UserProfilePublic(BaseModel):
    id: UUID
    wallet: Optional[str] = Field(
        default=None,
        exclude=True,
        description="Internal lookup identity; omitted from public profile responses.",
    )
    rider: Optional[PublicRiderRef] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    is_public: bool = True
    privacy: Optional[PrivacyState] = None
    created_at: Optional[datetime] = None
    # Public stats
    total_rides: int = 0
    total_distance_km: float = 0
    total_elevation_m: float = 0
    follower_count: int = 0
    following_count: int = 0


class UserProfileOwnerView(UserProfilePublic):
    """Public profile fields plus self-only aggregate economy."""

    total_dung_earned: int = 0


class UserProfilePrivate(UserProfileOwnerView):
    """Full profile with private fields - only for own profile"""
    model_config = ConfigDict(populate_by_name=True)

    wallet: str
    email: Optional[str] = None
    default_ride_visibility: Literal["public", "followers", "private"] = Field(
        default="public",
        alias="defaultRideVisibility",
    )
    # Truthful rider weight: None = never provided.
    weight_kg: Optional[float] = None
    weight_kg_source: Optional[Literal["manual", "derived"]] = None
    preferred_units: PreferredUnits = PreferredUnits.metric
    # Theme and display preferences
    theme_id: ThemeId = ThemeId.hoo_breddin
    is_dark_mode: bool = True
    rider_type: RiderType = RiderType.climber
    location: Optional[str] = None
    # Full stats
    total_kcals: float = 0
    total_duration_sec: int = 0
    # Daily earnings (from today's rides)
    cal_earned_today: float = 0
    dung_earned_today: float = 0


class ThresholdPendingMondayResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    watts: int = Field(ge=50, le=500)
    effective_at: datetime = Field(alias="effectiveAt")


class ThresholdResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contract_version: Literal["threshold.v1"] = Field(
        default="threshold.v1", alias="contractVersion"
    )
    state: Literal["establishing", "established"]
    current_w: Optional[int] = Field(default=None, alias="currentW", ge=50, le=500)
    established_at: Optional[datetime] = Field(default=None, alias="establishedAt")
    last_raised_at: Optional[datetime] = Field(default=None, alias="lastRaisedAt")
    pending_monday: Optional[ThresholdPendingMondayResponse] = Field(
        default=None, alias="pendingMonday"
    )
    sealing_in_progress: bool = Field(
        default=False, alias="sealingInProgress"
    )


class AuthBootstrapResponse(OnboardingStateResponse):
    cohort_admission_required: bool = False
    cohort_admitted: bool = False
    user: Optional[UserProfilePrivate] = None


class WebVitalMetric(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metric: Literal[
        "lcp",
        "inp",
        "cls",
        "fcp",
        "ttfb",
        "tbt",
        "route_load",
        "background_fetch",
    ]
    value: float = Field(..., ge=0, le=600000)
    rating: Optional[str] = Field(default=None, min_length=2, max_length=32)
    route: str = Field(default="/", min_length=1, max_length=256)
    device: Literal["mobile", "tablet", "desktop", "unknown"] = "unknown"
    timestamp: datetime
    source: Optional[str] = Field(default=None, min_length=2, max_length=32)
    visibility_state: Optional[str] = Field(default=None, min_length=2, max_length=16)
    navigation_type: Optional[str] = Field(default=None, min_length=2, max_length=32)
    pending_count: Optional[int] = Field(default=None, ge=0, le=1000)


class WebVitalsIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metrics: list[WebVitalMetric] = Field(default_factory=list, min_length=1, max_length=60)
    sampled: bool = True


class WebVitalsIngestResponse(BaseModel):
    accepted: int
    dropped: int = 0


class DeviceInfo(BaseModel):
    """Parsed user-agent information for human-friendly display."""
    browser_name: Optional[str] = None
    browser_version: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    device_type: str = "desktop"  # desktop, mobile, tablet
    display_name: str = "Unknown Device"  # e.g., "Chrome 120 on Windows 11"


class SessionInfo(BaseModel):
    id: UUID
    device_id: str
    user_agent: Optional[str] = None
    device_info: Optional[DeviceInfo] = None
    ip_address: Optional[str] = None
    location_hint: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_current: bool = False


class SessionsListResponse(BaseModel):
    sessions: list[SessionInfo]


class RevokeAllSessionsRequest(BaseModel):
    """Request to revoke all sessions."""
    include_current: bool = Field(
        default=False,
        description="If true, also revoke the current session (full logout)"
    )


class RevokeSessionsResponse(BaseModel):
    status: str
    count: int


class UpdateAccessoriesRequest(BaseModel):
    equipped: list[str] = Field(..., description="List of accessory IDs to equip")


class UpdateAccessoriesResponse(BaseModel):
    equipped: list[str]


# Invite Code Schemas

class InviteValidateRequest(BaseModel):
    """Request to check an invite code before signup."""
    code: str = Field(..., min_length=8)
    # Deprecated/ignored. Invite usage is consumed during final signup once the
    # canonical wallet is known.
    wallet: Optional[str] = None


class InviteValidateResponse(BaseModel):
    """Response from invite code validation."""
    valid: bool
    message: str
    code_id: Optional[UUID] = None


# Strava Integration Schemas

class StravaAuthUrlResponse(BaseModel):
    """Response with Strava OAuth authorization URL."""
    url: str
    state: str


class StravaConnectionResponse(BaseModel):
    """Response showing Strava connection status."""
    connected: bool
    athlete_id: Optional[int] = None
    athlete_username: Optional[str] = None
    athlete_firstname: Optional[str] = None
    athlete_lastname: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None


class StravaActivitySummary(BaseModel):
    """Summary of a Strava activity for import selection."""
    id: int
    name: str
    type: str
    sport_type: str
    start_date: datetime
    distance_km: float
    moving_time_minutes: int
    elevation_gain_m: float
    has_power: bool
    already_imported: bool


class StravaActivitiesResponse(BaseModel):
    """Response listing available Strava activities."""
    activities: list[StravaActivitySummary]
    page: int
    has_more: bool


class StravaImportRequest(BaseModel):
    """Request to import selected Strava activities."""
    model_config = ConfigDict(populate_by_name=True)

    activity_ids: list[int] = Field(..., min_length=1, max_length=10)
    visibility: Optional[Literal["public", "followers", "private"]] = None
    map_visibility: Optional[Literal["show_all", "hide_start_end", "hide_entire"]] = Field(
        None,
        validation_alias=AliasChoices("map_visibility", "mapVisibility"),
    )
    map_hide_start_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_start_m", "mapHideStartM"),
    )
    map_hide_end_m: Optional[Literal[0, 200, 400, 800, 1600]] = Field(
        None,
        validation_alias=AliasChoices("map_hide_end_m", "mapHideEndM"),
    )


class StravaImportResult(BaseModel):
    """Result of importing a single activity."""
    strava_activity_id: int
    success: bool
    activity_id: Optional[UUID] = None
    error: Optional[str] = None


class StravaImportResponse(BaseModel):
    """Response from batch activity import."""
    results: list[StravaImportResult]
    imported_count: int
    failed_count: int


# User Leaderboard Summary Schemas

class VaultPosition(BaseModel):
    """A user's position on a vault leaderboard."""
    vault_id: int
    canon_climb_id: Optional[UUID] = None
    vault_name: str
    vault_signature: str
    rank: int
    best_time_seconds: int
    is_kom: bool
    total_riders: int
    percentile: Optional[float] = None
    achieved_at: Optional[datetime] = None


class UserLeaderboardStats(BaseModel):
    """Aggregated leaderboard statistics for a user."""
    total_positions: int = Field(..., description="Total top-10 positions held across all vaults")
    kom_count: int = Field(..., description="Number of KOMs (rank 1)")
    podium_count: int = Field(..., description="Number of podium positions (top 3)")
    top10_count: int = Field(..., description="Number of top-10 positions")
    total_vaults_completed: int = Field(..., description="Unique vaults the user has completed")
    best_percentile: Optional[float] = Field(None, description="Best percentile ranking achieved")


class RiddenClimb(BaseModel):
    """One canon climb the rider has confirmed completions on."""
    canon_climb_id: Optional[UUID] = None
    vault_id: Optional[int] = None
    name: Optional[str] = None
    attempts: int = 0
    best_time_seconds: Optional[int] = None
    last_ridden_at: Optional[datetime] = None
    length_m: Optional[float] = None
    avg_gradient_pct: Optional[float] = None


class RiddenClimbsResponse(BaseModel):
    climbs: list[RiddenClimb] = Field(default_factory=list)


class UserLeaderboardSummaryResponse(BaseModel):
    """Complete leaderboard summary for a user across all vaults."""
    wallet: str
    stats: UserLeaderboardStats
    positions: list[VaultPosition]


# Full Leaderboard Schemas (all positions, not just top 10)

class FullLeaderboardEntry(BaseModel):
    """Entry in the full leaderboard (all positions)."""
    rank: int
    wallet: str
    best_time_seconds: int
    avg_power_w: Optional[int] = None
    total_completions: int
    achieved_at: Optional[datetime] = None
    is_top_10: bool = Field(..., description="Whether this position earns rewards")


class FullLeaderboardResponse(BaseModel):
    """Response for paginated full leaderboard."""
    vault_id: int
    vault_name: str
    total_riders: int
    entries: list[FullLeaderboardEntry]
    has_more: bool


class NearbyRider(BaseModel):
    """A rider near the user's position."""
    rank: int
    wallet: str
    best_time_seconds: int
    gap_seconds: int = Field(..., description="Positive = behind user, negative = ahead")
    is_user: bool


class UserPositionInfo(BaseModel):
    """User's position details in a vault."""
    rank: int
    best_time_seconds: int
    percentile: float = Field(..., description="Top X% (e.g., 15.2 means top 15.2%)")
    is_top_10: bool
    time_to_next_rank: Optional[int] = Field(None, description="Seconds to beat rank above")
    avg_power_w: Optional[int] = None
    total_completions: int = 1
    achieved_at: Optional[datetime] = None


class UserPositionResponse(BaseModel):
    """Response for user's specific position with nearby context."""
    vault_id: int
    vault_name: str
    user_position: UserPositionInfo
    total_riders: int
    nearby_riders: list[NearbyRider]


# Global Aggregate Leaderboard Schemas

class TimeFilter(str, Enum):
    """Time filter options for global leaderboards."""
    all_time = "all_time"
    this_epoch = "this_epoch"
    last_30_days = "last_30_days"


class GlobalKomEntry(BaseModel):
    """Entry in the global KOM count leaderboard."""
    rank: int
    wallet: str
    kom_count: int = Field(..., description="Total number of top-1 positions held")
    podium_count: int = Field(..., description="Total number of top-3 positions held")
    top10_count: int = Field(..., description="Total number of top-10 positions held")
    total_vaults: int = Field(..., description="Total unique vaults with a position")
    most_recent_kom_at: Optional[datetime] = Field(None, description="When most recent KOM was achieved")


class GlobalKomLeaderboardResponse(BaseModel):
    """Response for global KOM count leaderboard."""
    entries: list[GlobalKomEntry]
    total: int
    offset: int
    limit: int
    time_filter: str


class GlobalEarningsEntry(BaseModel):
    """Entry in the global earnings leaderboard."""
    rank: int
    wallet: str
    total_earnings: float = Field(..., description="Total DUNG earned from vaults")
    leaderboard_earnings: float = Field(..., description="Earnings from leaderboard positions")
    staking_earnings: float = Field(..., description="Earnings from staking")
    legend_earnings: float = Field(..., description="Earnings from being Local Legend")
    vaults_with_earnings: int = Field(..., description="Number of unique vaults with earnings")
    last_earning_at: Optional[datetime] = Field(None, description="When most recent earning was received")


class GlobalEarningsLeaderboardResponse(BaseModel):
    """Response for global earnings leaderboard."""
    entries: list[GlobalEarningsEntry]
    total: int
    offset: int
    limit: int
    time_filter: str


class UserGlobalKomRank(BaseModel):
    """User's rank on the global KOM leaderboard."""
    user_rank: int
    total_users: int
    kom_count: int
    podium_count: int
    top10_count: int
    percentile: Optional[float] = Field(None, description="Top X% (e.g., 15.2 means top 15.2%)")


class UserGlobalEarningsRank(BaseModel):
    """User's rank on the global earnings leaderboard."""
    user_rank: int
    total_users: int
    total_earnings: float
    leaderboard_earnings: float
    staking_earnings: float
    legend_earnings: float
    percentile: Optional[float] = Field(None, description="Top X% (e.g., 15.2 means top 15.2%)")



class LedgerHashChainResponse(BaseModel):
    """Result of verifying the hash chain for a wallet+denomination."""
    wallet: str
    denomination: str
    valid: bool
    events_checked: int
    first_broken_id: Optional[int] = None
    error: Optional[str] = None
