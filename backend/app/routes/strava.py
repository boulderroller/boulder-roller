"""
Strava Integration Routes

Endpoints for Strava OAuth, activity import, webhooks, and backfill.
"""
from ..services.privacy_logging import scrub_log_text
import time
import httpx
import logging
import secrets
import uuid as uuid_module
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from ..config import load_strava_settings
from ..dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_strava_service,
    get_ride_repository,
    get_user_repository,
)
from ..metrics import (
    record_strava_api_request,
    record_strava_webhook_event,
    record_strava_webhook_ignored,
    set_strava_last_webhook_event,
    set_strava_subscription_active,
)
from ..middleware.rate_limiter import rate_limit
from ..repositories import RideRepository, UserRepository, get_supabase_client
from ..services.file_storage import (
    create_file_storage_service,
    StorageUnavailableError,
    FileTooLargeError,
)
from ..services.provider_imports import requeue_pending_provider_ride
from ..services.ride_ingest import RideIngestJob, enqueue_ride_ingest
from ..services.ride_privacy import RidePrivacyPolicy
from ..schemas import (
    StravaActivitiesResponse,
    StravaActivitySummary,
    StravaAuthUrlResponse,
    StravaConnectionResponse,
    StravaImportRequest,
    StravaImportResponse,
    StravaImportResult,
)
from ..services.strava_service import (
    StravaService,
    StravaNotConfiguredError,
    StravaAuthError,
    StravaAPIError,
    StravaRevocationError,
)
from ..services.strava_monitoring import get_strava_health_snapshot
from .admin import require_admin

logger = logging.getLogger(__name__)
router = APIRouter()

STRAVA_OAUTH_STATE_COOKIE = "br_strava_oauth_state"
STRAVA_OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60


class StravaError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail={"error": {"code": code, "message": message}})


async def _resolve_import_privacy_policy(
    *,
    ride_repo: RideRepository,
    user_id: str,
    payload: StravaImportRequest,
) -> RidePrivacyPolicy:
    """Resolve one complete submitted snapshot before any provider mutation."""
    try:
        policy = await ride_repo.resolve_ride_privacy_policy(
            user_id,
            visibility=payload.visibility,
            map_visibility=payload.map_visibility,
            map_hide_start_m=payload.map_hide_start_m,
            map_hide_end_m=payload.map_hide_end_m,
        )
    except Exception as exc:
        raise StravaError(
            "privacy_settings_unavailable",
            "Your privacy settings could not be loaded. No ride was imported.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if not isinstance(policy, RidePrivacyPolicy):
        raise StravaError(
            "privacy_settings_unavailable",
            "Your privacy settings could not be loaded. No ride was imported.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return policy


async def _persist_pending_import_privacy_policy(
    *,
    ride_repo: RideRepository,
    ride_id: str,
    policy: RidePrivacyPolicy,
) -> dict[str, Any]:
    """Freeze the submitted snapshot on an existing pending ride before queueing."""
    try:
        await ride_repo.update_ride_metadata(ride_id, policy.to_storage_dict())
        persisted_ride = await ride_repo.get_ride(ride_id)
        if not isinstance(persisted_ride, dict):
            raise ValueError("pending provider ride disappeared during privacy update")
        if str(persisted_ride.get("processing_status") or "") != "pending":
            raise ValueError("pending provider ride changed state during privacy update")
        persisted_policy = RidePrivacyPolicy.from_values(
            visibility=persisted_ride.get("visibility"),
            map_visibility=persisted_ride.get("map_visibility"),
            map_hide_start_m=persisted_ride.get("map_hide_start_m"),
            map_hide_end_m=persisted_ride.get("map_hide_end_m"),
        )
        if persisted_policy != policy:
            raise ValueError("pending provider ride privacy update was not persisted")
    except Exception as exc:
        raise StravaError(
            "privacy_settings_unavailable",
            "Your privacy settings could not be saved. No ride was imported.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    return persisted_ride


class StravaAdminSubscriptionStatus(BaseModel):
    active: bool
    subscription_id: Optional[int] = None
    callback_url: Optional[str] = None
    created_at: Optional[str] = None


class StravaAdminConnectionStatus(BaseModel):
    active_count: int = 0
    recent_sync_24h: int = 0
    stale_sync_7d: int = 0
    last_webhook_at: Optional[str] = None


class StravaAdminRateStatus(BaseModel):
    storage: str
    redis_available: bool
    usage_15min: int
    limit_15min: int
    remaining_15min: int
    usage_daily: int
    limit_daily: int
    remaining_daily: int
    reset_in_seconds_15min: int


class StravaAdminHealthResponse(BaseModel):
    health_status: str
    enabled: bool
    sync_enabled: bool
    integration_mode: str
    state_verified: bool
    redirect_uri: Optional[str] = None
    webhook_callback_url: Optional[str] = None
    subscription: StravaAdminSubscriptionStatus
    connections: StravaAdminConnectionStatus
    backfill: Dict[str, int]
    rate_limits: StravaAdminRateStatus
    alerts: list[str]
    generated_at: str


def _require_strava_sync_enabled() -> None:
    """Keep retired rider sync and provider subscription creation fail-closed."""
    if load_strava_settings().sync_enabled:
        return
    raise StravaError(
        "strava_file_import_only",
        "Strava sync is retired. Upload a FIT or GPX ride file instead.",
        status.HTTP_410_GONE,
    )


def _set_strava_oauth_state_cookie(request: Request, response: Response, state: str) -> None:
    response.set_cookie(
        STRAVA_OAUTH_STATE_COOKIE,
        state,
        max_age=STRAVA_OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/strava/auth",
    )


def _clear_strava_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(STRAVA_OAUTH_STATE_COOKIE, path="/strava/auth")


def _validate_strava_oauth_state(
    request: Any,
    response: Response,
    *,
    state: str,
    wallet: str,
) -> None:
    expected_state = request.cookies.get(STRAVA_OAUTH_STATE_COOKIE)
    _clear_strava_oauth_state_cookie(response)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise StravaError("invalid_state", "Invalid state parameter")
    if not state.startswith(f"{wallet}:"):
        raise StravaError("invalid_state", "Invalid state parameter")


@router.get("/auth/url", response_model=StravaAuthUrlResponse)
@rate_limit(category="strava")
async def get_auth_url(
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> StravaAuthUrlResponse:
    """
    Get Strava OAuth authorization URL.

    Returns a URL to redirect the user to for Strava authorization.
    The state parameter should be passed back to the callback for validation.
    """
    _require_strava_sync_enabled()
    try:
        state = f"{user.wallet}:{secrets.token_urlsafe(16)}"
        url = strava.get_authorization_url(state)
        _set_strava_oauth_state_cookie(request, response, state)
        return StravaAuthUrlResponse(url=url, state=state)
    except StravaNotConfiguredError:
        raise StravaError(
            "strava_not_configured",
            "Strava integration is not configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/auth/callback")
@rate_limit(category="strava")
async def handle_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from Strava"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    scope: Optional[str] = Query(None, description="Granted scopes"),
    error: Optional[str] = Query(None, description="Error from Strava"),
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> StravaConnectionResponse:
    """
    Handle Strava OAuth callback.

    Exchanges the authorization code for tokens and saves the connection.
    """
    _require_strava_sync_enabled()
    if error:
        logger.warning(f"Strava OAuth error for {user.user_id}: {scrub_log_text(error)}")
        raise StravaError("strava_auth_denied", f"Strava authorization denied: {error}")

    _validate_strava_oauth_state(request, response, state=state, wallet=user.wallet)

    try:
        # Exchange code for tokens
        tokens = await strava.exchange_code_for_tokens(code)

        # Save connection
        connection = await strava.save_connection(user.wallet, tokens)

        logger.info(f"Strava connected for wallet {user.user_id}, athlete {connection.strava_athlete_id}")

        # Auto-trigger historical backfill via NATS
        try:
            from ..services.nats_client import get_nats_client
            nats_backfill = get_nats_client()
            await nats_backfill.publish("strava.events.backfill", {
                "connection_id": str(connection.id),
            })
            logger.info(f"Queued Strava backfill for connection {connection.id}")
        except Exception as e:
            logger.warning(f"Failed to queue Strava backfill: {e}")

        return StravaConnectionResponse(
            connected=True,
            athlete_id=connection.strava_athlete_id,
            athlete_username=connection.athlete_username,
            athlete_firstname=connection.athlete_firstname,
            athlete_lastname=connection.athlete_lastname,
            connected_at=connection.connected_at,
            last_sync_at=connection.last_sync_at,
        )

    except StravaNotConfiguredError:
        raise StravaError(
            "strava_not_configured",
            "Strava integration is not configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except StravaAuthError as e:
        logger.error(f"Strava token exchange failed for {user.user_id}: {scrub_log_text(e)}")
        raise StravaError("token_exchange_failed", str(e))


@router.get("/connection", response_model=StravaConnectionResponse)
@rate_limit(category="strava")
async def get_connection(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> StravaConnectionResponse:
    """
    Get current Strava connection status.
    """
    _require_strava_sync_enabled()
    connection = strava.get_connection(user.wallet)

    if not connection:
        return StravaConnectionResponse(connected=False)

    return StravaConnectionResponse(
        connected=True,
        athlete_id=connection.strava_athlete_id,
        athlete_username=connection.athlete_username,
        athlete_firstname=connection.athlete_firstname,
        athlete_lastname=connection.athlete_lastname,
        connected_at=connection.connected_at,
        last_sync_at=connection.last_sync_at,
    )


@router.delete("/connection")
@rate_limit(category="strava")
async def disconnect(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> dict:
    """
    Disconnect Strava account.
    """
    _require_strava_sync_enabled()
    disconnected = await strava.disconnect(user.wallet)

    if not disconnected:
        raise StravaError("not_connected", "No active Strava connection found")

    logger.info(f"Strava disconnected for wallet {user.user_id}")
    return {"success": True, "message": "Strava account disconnected"}


@router.get("/activities", response_model=StravaActivitiesResponse)
@rate_limit(category="strava")
async def list_activities(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(30, ge=1, le=100, description="Activities per page"),
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> StravaActivitiesResponse:
    """
    List available Strava activities for import.

    Only returns cycling activities (Ride, VirtualRide, EBikeRide).
    """
    _require_strava_sync_enabled()
    connection = strava.get_connection(user.wallet)
    if not connection:
        raise StravaError("not_connected", "No active Strava connection")

    try:
        activities = await strava.get_activities(connection, page=page, per_page=per_page)

        # Convert to response format
        summaries = [
            StravaActivitySummary(
                id=a.id,
                name=a.name,
                type=a.type,
                sport_type=a.sport_type,
                start_date=a.start_date,
                distance_km=round(a.distance / 1000, 2),
                moving_time_minutes=round(a.moving_time / 60),
                elevation_gain_m=round(a.total_elevation_gain),
                has_power=a.has_power,
                already_imported=a.already_imported,
            )
            for a in activities
        ]

        # Assume there are more if we got a full page
        has_more = len(activities) >= per_page

        return StravaActivitiesResponse(
            activities=summaries,
            page=page,
            has_more=has_more,
        )

    except StravaRevocationError as e:
        logger.warning(f"Strava connection revoked for {user.user_id}: {scrub_log_text(e)}")
        raise StravaError(
            "strava_revoked",
            "Your Strava connection was revoked. Please reconnect your Strava account.",
            status.HTTP_401_UNAUTHORIZED,
        )
    except StravaAPIError as e:
        logger.error(f"Strava API error for {user.user_id}: {scrub_log_text(e)}")
        raise StravaError("strava_api_error", str(e))


@router.post("/import", response_model=StravaImportResponse)
@rate_limit(category="strava")
async def import_activities(
    request: Request,
    payload: StravaImportRequest = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
    ride_repo: RideRepository = Depends(get_ride_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> StravaImportResponse:
    """
    Import selected Strava activities.

    Mirrors the canonical ride ingest flow:
    1. Download activity data from Strava via streams API
    2. Build GPX bytes from streams
    3. Compute file hash (SHA256) for dedup
    4. Upload to Supabase Storage via FileStorageService
    5. Create ride record via RideRepository
    6. Enqueue the canonical ride-processing job
    7. Track provenance in strava_imported_activities
    """
    _require_strava_sync_enabled()
    connection = strava.get_connection(user.wallet)
    if not connection:
        raise StravaError("not_connected", "No active Strava connection")

    # Get user profile for processing params
    profile = await user_repo.get_user_profile(user.wallet)
    user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

    storage = create_file_storage_service()

    results = []
    imported_count = 0
    failed_count = 0

    for activity_id in payload.activity_ids:
        try:
            existing_provider_ride = await ride_repo.find_ride_by_import_identity(
                user.user_id,
                "strava",
                str(activity_id),
            )
            if existing_provider_ride:
                if str(existing_provider_ride.get("processing_status") or "") == "pending":
                    privacy_policy = await _resolve_import_privacy_policy(
                        ride_repo=ride_repo,
                        user_id=str(user.user_id),
                        payload=payload,
                    )
                    existing_provider_ride = await _persist_pending_import_privacy_policy(
                        ride_repo=ride_repo,
                        ride_id=str(existing_provider_ride["id"]),
                        policy=privacy_policy,
                    )
                requeue = await requeue_pending_provider_ride(
                    ride_repo=ride_repo,
                    user_repo=user_repo,
                    ride=existing_provider_ride,
                    wallet=user.wallet,
                    user_id=str(user.user_id),
                    default_file_type="gpx",
                    enqueue_source="strava_manual_import_retry",
                    source_id=str(activity_id),
                )
                if requeue.attempted and not requeue.accepted:
                    results.append(StravaImportResult(
                        strava_activity_id=activity_id,
                        success=False,
                        activity_id=UUID(str(existing_provider_ride["id"])),
                        error=requeue.error or "Processing queue unavailable",
                    ))
                    failed_count += 1
                    continue
                strava.mark_activity_imported(
                    connection_id=connection.id,
                    strava_activity_id=activity_id,
                    activity_id=existing_provider_ride["id"],
                )
                if requeue.accepted:
                    results.append(StravaImportResult(
                        strava_activity_id=activity_id,
                        success=True,
                        activity_id=UUID(str(existing_provider_ride["id"])),
                    ))
                    imported_count += 1
                else:
                    results.append(StravaImportResult(
                        strava_activity_id=activity_id,
                        success=False,
                        activity_id=UUID(str(existing_provider_ride["id"])),
                        error=f"Already imported (ride {existing_provider_ride['id']})",
                    ))
                    failed_count += 1
                continue

            privacy_policy = await _resolve_import_privacy_policy(
                ride_repo=ride_repo,
                user_id=str(user.user_id),
                payload=payload,
            )

            # 1. Download activity data from Strava (builds GPX from streams)
            file_data, file_type, import_diagnostics = (
                await strava.download_activity_file_with_diagnostics(connection, activity_id)
            )

            # 2. Compute file hash for dedup
            file_hash = storage.compute_file_hash(file_data)

            # Check for duplicate (same user, same file hash)
            existing = await ride_repo.find_ride_by_hash(user.user_id, file_hash)
            if existing:
                logger.info(
                    f"[StravaImport] Duplicate detected for activity {activity_id}: "
                    f"existing_ride={existing['id']}"
                )
                if str(existing.get("processing_status") or "") == "pending":
                    existing = await _persist_pending_import_privacy_policy(
                        ride_repo=ride_repo,
                        ride_id=str(existing["id"]),
                        policy=privacy_policy,
                    )
                requeue = await requeue_pending_provider_ride(
                    ride_repo=ride_repo,
                    user_repo=user_repo,
                    ride=existing,
                    wallet=user.wallet,
                    user_id=str(user.user_id),
                    default_file_type=file_type,
                    enqueue_source="strava_manual_import_retry",
                    source_id=str(activity_id),
                )
                if requeue.attempted and not requeue.accepted:
                    results.append(StravaImportResult(
                        strava_activity_id=activity_id,
                        success=False,
                        activity_id=UUID(str(existing["id"])),
                        error=requeue.error or "Processing queue unavailable",
                    ))
                    failed_count += 1
                    continue
                if requeue.accepted:
                    strava.mark_activity_imported(
                        connection_id=connection.id,
                        strava_activity_id=activity_id,
                        activity_id=existing["id"],
                    )
                    results.append(StravaImportResult(
                        strava_activity_id=activity_id,
                        success=True,
                        activity_id=UUID(str(existing["id"])),
                    ))
                    imported_count += 1
                    continue
                results.append(StravaImportResult(
                    strava_activity_id=activity_id,
                    success=False,
                    activity_id=UUID(str(existing["id"])),
                    error=f"Already imported (ride {existing['id']})",
                ))
                failed_count += 1
                continue

            # 3. Generate ride ID upfront
            ride_id = str(uuid_module.uuid4())

            # 4. Upload to Supabase Storage
            storage_result = await storage.upload_ride_file(
                user_id=user.user_id,
                ride_id=ride_id,
                file_bytes=file_data,
                file_type=file_type,
            )
            logger.info(
                f"[StravaImport] Stored file: path={storage_result.path}, "
                f"size={storage_result.size_bytes}"
            )

            # 5. Create ride record before enqueueing the canonical ingest job
            await ride_repo.create_ride(
                user_id=user.user_id,
                ride_id=ride_id,
                status="processing",
                file_type=file_type,
                raw_file_path=storage_result.path,
                raw_file_size_bytes=storage_result.size_bytes,
                file_hash=storage_result.file_hash,
                import_source=import_diagnostics.import_source,
                import_source_id=import_diagnostics.source_activity_id,
                import_diagnostics=import_diagnostics.to_dict(),
                privacy_policy=privacy_policy,
            )

            enqueue_result = await enqueue_ride_ingest(
                RideIngestJob(
                    ride_id=ride_id,
                    wallet=user.wallet,
                    user_id=str(user.user_id),
                    file_type=file_type,
                    file_path=storage_result.path,
                    user_weight_kg=user_weight,
                    source="strava_manual_import",
                    source_id=str(activity_id),
                )
            )
            if not enqueue_result.accepted:
                await ride_repo.update_ride_status(
                    UUID(ride_id),
                    "pending",
                    error_message=enqueue_result.error,
                )
                results.append(StravaImportResult(
                    strava_activity_id=activity_id,
                    success=False,
                    activity_id=UUID(ride_id),
                    error="Processing queue unavailable",
                ))
                failed_count += 1
                continue

            # 6. Track Strava provenance after the ingest job is accepted
            strava.mark_activity_imported(
                connection_id=connection.id,
                strava_activity_id=activity_id,
                activity_id=ride_id,
            )

            results.append(StravaImportResult(
                strava_activity_id=activity_id,
                success=True,
                activity_id=ride_id,
            ))
            imported_count += 1

            logger.info(f"[StravaImport] Imported Strava activity {activity_id} as ride {ride_id}")

        except StravaRevocationError:
            raise StravaError(
                "strava_revoked",
                "Your Strava connection was revoked. Please reconnect.",
                status.HTTP_401_UNAUTHORIZED,
            )
        except StravaError:
            raise
        except (FileTooLargeError, StorageUnavailableError) as e:
            logger.error(f"[StravaImport] Storage error for activity {activity_id}: {e}")
            results.append(StravaImportResult(
                strava_activity_id=activity_id,
                success=False,
                error=str(e),
            ))
            failed_count += 1
        except Exception as e:
            logger.error(f"[StravaImport] Failed to import activity {activity_id}: {e}")
            results.append(StravaImportResult(
                strava_activity_id=activity_id,
                success=False,
                error=str(e),
            ))
            failed_count += 1

    return StravaImportResponse(
        results=results,
        imported_count=imported_count,
        failed_count=failed_count,
    )


# =============================================================================
# WEBHOOK ENDPOINTS (no auth — Strava doesn't send tokens)
# =============================================================================


@router.get("/webhook")
async def strava_webhook_validate(request: Request) -> dict:
    """
    Strava webhook subscription validation (GET).

    Strava sends a GET request with hub.mode, hub.verify_token, and hub.challenge
    to validate the callback URL during subscription creation.
    """
    _require_strava_sync_enabled()
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    settings = load_strava_settings()

    if mode != "subscribe":
        raise HTTPException(status_code=400, detail="Invalid hub.mode")

    if not settings.webhook_verify_token or verify_token != settings.webhook_verify_token:
        logger.warning("[StravaWebhook] Invalid verify token received")
        raise HTTPException(status_code=403, detail="Invalid verify token")

    logger.info("[StravaWebhook] Subscription validation successful")
    return {"hub.challenge": challenge}


@router.post("/webhook")
async def strava_webhook_event(request: Request) -> dict:
    """
    Strava webhook event receiver (POST).

    Strava sends POST events for:
    - activity.create: New activity uploaded
    - activity.update: Activity metadata changed
    - activity.delete: Activity deleted
    - athlete.deauthorize: User revoked our app

    Must return 200 quickly — all processing is async via NATS.
    """
    if not load_strava_settings().sync_enabled:
        record_strava_webhook_ignored("sync_disabled")
        return {"status": "ignored", "reason": "file_import_only"}

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    object_type = data.get("object_type")
    aspect_type = data.get("aspect_type")
    owner_id = data.get("owner_id")  # Strava athlete ID
    object_id = data.get("object_id")  # Activity or athlete ID
    subscription_id = data.get("subscription_id")

    logger.info(
        f"[StravaWebhook] Event: {object_type}.{aspect_type} "
        f"owner={owner_id} object={object_id} sub={subscription_id}"
    )
    record_strava_webhook_event(object_type, aspect_type, "received")

    # Validate subscription_id exists in our DB
    db = get_supabase_client()
    sub_result = db.table("strava_webhook_subscriptions").select("id").eq(
        "subscription_id", subscription_id
    ).eq("is_active", True).limit(1).execute()

    if not sub_result.data:
        record_strava_webhook_event(object_type, aspect_type, "ignored")
        record_strava_webhook_ignored("unknown_subscription")
        logger.warning(f"[StravaWebhook] Unknown subscription_id: {subscription_id}")
        # Still return 200 to avoid Strava retries
        return {"status": "ignored"}

    # Queue async processing via NATS (replaces Celery task)
    from ..services.nats_client import get_nats_client
    nats = get_nats_client()
    set_strava_last_webhook_event(time.time())
    record_strava_webhook_event(object_type, aspect_type, "queued")
    published = await nats.publish("strava.events.webhook", {
        "object_type": object_type,
        "aspect_type": aspect_type,
        "owner_id": owner_id,
        "object_id": object_id,
    })
    if not published:
        logger.error("[StravaWebhook] Failed to publish to NATS, event may be lost")
        record_strava_webhook_event(object_type, aspect_type, "publish_failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook queue unavailable",
        )

    return {"status": "ok"}


# =============================================================================
# BACKFILL STATUS
# =============================================================================


@router.get("/backfill/status")
@rate_limit(category="strava")
async def get_backfill_status(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    strava: StravaService = Depends(get_strava_service),
) -> dict:
    """Get Strava historical backfill progress for the current user."""
    _require_strava_sync_enabled()
    connection = strava.get_connection(user.wallet)
    if not connection:
        raise StravaError("not_connected", "No active Strava connection")

    db = get_supabase_client()
    result = db.table("strava_connections").select(
        "backfill_status, backfill_cursor, total_activities_synced"
    ).eq("id", str(connection.id)).limit(1).execute()

    if not result.data:
        return {"backfill_status": "unknown"}

    row = result.data[0]
    return {
        "backfill_status": row.get("backfill_status", "none"),
        "backfill_cursor": row.get("backfill_cursor", 0),
        "total_activities_synced": row.get("total_activities_synced", 0),
    }


# =============================================================================
# ADMIN WEBHOOK SUBSCRIPTION MANAGEMENT
# =============================================================================

admin_router = APIRouter(prefix="/admin/strava", tags=["admin-strava"])


@admin_router.post("/subscribe")
async def admin_create_subscription(
    request: Request,
    admin_ctx=Depends(require_admin),
) -> dict:
    """
    Create a Strava webhook subscription.

    Admin-only: registers our callback URL with Strava so we receive
    activity events in real-time.
    """
    _require_strava_sync_enabled()
    settings = load_strava_settings()
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Strava not configured")
    if not settings.webhook_verify_token or not settings.webhook_callback_url:
        raise HTTPException(
            status_code=400,
            detail="STRAVA_WEBHOOK_VERIFY_TOKEN and STRAVA_WEBHOOK_CALLBACK_URL must be set",
        )

    async with httpx.AsyncClient() as client:
        started = time.perf_counter()
        response = await client.post(
            "https://www.strava.com/api/v3/push_subscriptions",
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "callback_url": settings.webhook_callback_url,
                "verify_token": settings.webhook_verify_token,
            },
        )
    record_strava_api_request(
        endpoint="push_subscriptions",
        method="POST",
        status_code=response.status_code,
        duration_seconds=time.perf_counter() - started,
    )

    if response.status_code not in (200, 201):
        logger.error(
            f"[StravaWebhook] Subscription creation failed: "
            f"{response.status_code} {response.text}"
        )
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Strava subscription failed: {response.text}",
        )

    resp_data = response.json()
    subscription_id = resp_data.get("id")

    # Store in DB
    db = get_supabase_client()
    db.table("strava_webhook_subscriptions").upsert({
        "subscription_id": subscription_id,
        "verify_token": settings.webhook_verify_token,
        "callback_url": settings.webhook_callback_url,
        "is_active": True,
    }, on_conflict="subscription_id").execute()
    set_strava_subscription_active(True)

    logger.info(f"[StravaWebhook] Created subscription {subscription_id}")
    return {"subscription_id": subscription_id, "status": "active"}


@admin_router.delete("/subscribe")
async def admin_delete_subscription(
    request: Request,
    admin_ctx=Depends(require_admin),
) -> dict:
    """Delete the active Strava webhook subscription."""
    settings = load_strava_settings()
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Strava not configured")

    db = get_supabase_client()
    result = db.table("strava_webhook_subscriptions").select("*").eq(
        "is_active", True
    ).limit(1).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="No active subscription found")

    sub = result.data[0]
    subscription_id = sub["subscription_id"]

    async with httpx.AsyncClient() as client:
        started = time.perf_counter()
        response = await client.delete(
            f"https://www.strava.com/api/v3/push_subscriptions/{subscription_id}",
            params={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
            },
        )
    record_strava_api_request(
        endpoint="push_subscriptions",
        method="DELETE",
        status_code=response.status_code,
        duration_seconds=time.perf_counter() - started,
    )

    # Mark as inactive locally regardless of Strava response
    db.table("strava_webhook_subscriptions").update({
        "is_active": False,
    }).eq("subscription_id", subscription_id).execute()
    set_strava_subscription_active(False)

    if response.status_code not in (200, 204):
        logger.warning(
            f"[StravaWebhook] Strava returned {response.status_code} on delete, "
            f"but marked local subscription as inactive"
        )

    logger.info(f"[StravaWebhook] Deleted subscription {subscription_id}")
    return {"subscription_id": subscription_id, "status": "deleted"}


@admin_router.get("/subscription")
async def admin_get_subscription(
    request: Request,
    admin_ctx=Depends(require_admin),
) -> dict:
    """Get current Strava webhook subscription status."""
    db = get_supabase_client()
    result = db.table("strava_webhook_subscriptions").select("*").eq(
        "is_active", True
    ).limit(1).execute()

    if not result.data:
        return {"active": False}

    sub = result.data[0]
    return {
        "active": True,
        "subscription_id": sub["subscription_id"],
        "callback_url": sub["callback_url"],
        "created_at": sub["created_at"],
    }


@admin_router.get("/health", response_model=StravaAdminHealthResponse)
@rate_limit(category="general")
async def admin_get_health(
    request: Request,
    admin_ctx=Depends(require_admin),
) -> StravaAdminHealthResponse:
    """Get current Strava integration health, quota, and backfill status."""
    snapshot = await get_strava_health_snapshot()
    return StravaAdminHealthResponse(**snapshot)
