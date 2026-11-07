"""
User Profile & Session Management Routes

Endpoints:
- GET  /users/me              - Get current user's full profile (private view)
- PUT  /users/me              - Update current user's profile
- POST /users/check-username  - Check username availability (public)
- GET  /users/{identifier}    - Get user's public profile by user id, wallet, or @username
- GET  /users/me/sessions     - List current user's active sessions
- DELETE /users/me/sessions/{id} - Revoke a specific session
- DELETE /users/me/sessions   - Revoke all other sessions
- GET  /users/me/leaderboard-positions - Cross-vault leaderboard summary
- GET  /users/{wallet}/leaderboard-positions - User's cross-vault leaderboard summary
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Union
from uuid import UUID
import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..avatar_media_contracts import (
    ALLOWED_AVATAR_MIME_TYPES,
    AVATAR_SIGNED_URL_EXPIRY_SECONDS,
    avatar_storage_path,
    normalize_avatar_mime_type,
    with_signed_avatar_url,
)
from ..feed_contracts import _ride_route_preview
from ..ride_media_contracts import serialize_ride_media_list
from ..dependencies import (
    AuthenticatedUser,
    get_achievement_repository,
    get_current_user,
    get_optional_current_user,
    get_repository,
    get_ride_repository,
    get_user_repository,
    get_vault_repository,
)
from ..repositories import AuthRepository, DatabaseRepository, UserRepository, create_auth_repository, create_notification_repository
from ..repositories_legacy import clear_user_row_cache
from ..middleware.rate_limiter import rate_limit
from ..repositories.achievement import AchievementRepository
from ..repositories.ride import RideRepository
from ..repositories.vault import VaultRepository
from ..rider_identity_contracts import PublicRiderRef, ViewerRelationship, public_rider_ref, public_rider_ref_dict
from ..target_action_contracts import viewer_capabilities_dict
from ..services.notification_service import create_notification_service
from ..services.file_storage import StorageUnavailableError, FileNotFoundError as StorageFileNotFoundError, create_file_storage_service
from ..services.photo_metadata import InvalidPhotoError
from ..services.privacy_resolver import (
    resolve_profile_visibility,
    resolve_ride_visibility,
    viewer_user_id,
)
from ..services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    project_public_record_board,
)

import logging
_logger = logging.getLogger(__name__)
from ..schemas import (
    AvatarUploadCompleteRequest,
    RiddenClimb,
    RiddenClimbsResponse,
    AvatarUploadInitRequest,
    AvatarUploadInitResponse,
    PreferredUnits,
    RevokeSessionsResponse,
    RiderType,
    SessionInfo,
    SessionsListResponse,
    ThemeId,
    UserLeaderboardStats,
    UserLeaderboardSummaryResponse,
    UsernameCheckRequest,
    UsernameCheckResponse,
    UserProfilePrivate,
    UserProfileOwnerView,
    UserProfilePublic,
    UserProfileUpdate,
    ThresholdPendingMondayResponse,
    ThresholdResponse,
    VaultPosition,
)
from ..services.reward_threshold import parse_threshold_rider_projection

router = APIRouter()


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse datetime from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _session_is_current(
    session: dict[str, Any],
    *,
    current_hash: Optional[str],
    current_device_id: Optional[str],
) -> bool:
    token_hash = session.get("token_hash")
    if current_hash and token_hash in {current_hash, current_hash[:16]}:
        return True
    if current_device_id and current_device_id != "unknown":
        return str(session.get("device_id") or "") == str(current_device_id)
    return False


def _build_private_profile_response(
    profile: dict[str, Any],
    stats: dict[str, Any],
    today_rides: list[dict[str, Any]],
    fallback_wallet: str,
) -> UserProfilePrivate:
    cal_earned_today = sum(float(r.get("cal_earned") or 0) for r in today_rides)
    dung_earned_today = sum(float(r.get("dung_minted") or 0) for r in today_rides)

    return UserProfilePrivate(
        id=UUID(str(profile.get("id"))),
        wallet=profile.get("wallet", fallback_wallet),
        rider=public_rider_ref(
            profile,
            viewer_relationship=ViewerRelationship.self,
        ),
        username=profile.get("username"),
        display_name=profile.get("display_name"),
        bio=profile.get("bio"),
        avatar_url=profile.get("avatar_url"),
        email=profile.get("email"),
        privacy={
            "visibility": "public" if profile.get("is_public", True) else "private",
            "canView": True,
            "isOwner": True,
            "isFollower": False,
            "redactGps": False,
            "protocolPublic": False,
            "protocolPublicFields": [],
            "reason": "owner",
        },
        default_ride_visibility=profile.get("default_ride_visibility") or "public",
        # Truthful rider weight: absence flows as null.
        weight_kg=(
            float(profile["weight_kg"]) if profile.get("weight_kg") is not None else None
        ),
        weight_kg_source=profile.get("weight_kg_source"),
        preferred_units=PreferredUnits(profile.get("preferred_units") or "metric"),
        is_public=profile.get("is_public", True),
        created_at=_parse_datetime(profile.get("created_at")),
        theme_id=ThemeId(profile.get("theme_id") or "hoo-breddin"),
        is_dark_mode=profile.get("is_dark_mode", True),
        rider_type=RiderType(profile.get("rider_type") or "climber"),
        location=profile.get("location"),
        total_rides=stats.get("total_rides", 0),
        total_distance_km=stats.get("total_distance_km", 0),
        total_elevation_m=stats.get("total_elevation_m", 0),
        total_kcals=stats.get("total_kcals", 0),
        total_duration_sec=stats.get("total_duration_sec", 0),
        total_dung_earned=stats.get("total_dung_earned", 0),
        cal_earned_today=cal_earned_today,
        dung_earned_today=dung_earned_today,
    )


async def _public_recent_media_by_ride(
    repo: DatabaseRepository,
    ride_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    unique_ids = [str(ride_id) for ride_id in dict.fromkeys(ride_ids) if ride_id]
    if not unique_ids:
        return {}

    list_many = getattr(repo, "list_ride_media_for_rides", None)
    rows_by_ride: Optional[dict[str, list[dict[str, Any]]]] = None
    if list_many:
        try:
            rows_by_ride = await list_many(unique_ids)
        except Exception:
            rows_by_ride = None

    if rows_by_ride is None:
        list_media = getattr(repo, "list_ride_media", None)
        if not list_media:
            return {}
        try:
            grouped_rows = await asyncio.gather(*(list_media(ride_id) for ride_id in unique_ids))
            rows_by_ride = dict(zip(unique_ids, grouped_rows))
        except Exception:
            rows_by_ride = {}

    async def _serialize_group(ride_id: str, rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        try:
            media = await serialize_ride_media_list(rows)
        except Exception:
            return ride_id, []
        return ride_id, [
            item.model_dump(by_alias=True, mode="json")
            for item in media
            if item.url
        ]

    groups = await asyncio.gather(*(
        _serialize_group(ride_id, rows_by_ride.get(ride_id, []))
        for ride_id in unique_ids
    ))
    return {ride_id: media for ride_id, media in groups}


def _public_ride_summary(ride: dict[str, Any]) -> dict[str, Any]:
    from ..services.training_metrics import project_training
    ride = project_training(ride, owner=(ride.get("privacy") or {}).get("isOwner") is True)
    # rides.title (processing default or rider edit) wins; legacy untitled
    # rides keep the filename-stem fallback.
    ride_title = ride.get("title")
    if isinstance(ride_title, str) and ride_title.strip():
        title = ride_title.strip()
    else:
        file_name = ride.get("file_name", "")
        title = file_name.rsplit(".", 1)[0] if file_name else "Ride"
    privacy = ride.get("privacy") if isinstance(ride.get("privacy"), dict) else {}
    summary = {
        "id": ride.get("id"),
        "title": title,
        "status": ride.get("processing_status"),
        "started_at": ride.get("started_at"),
        "created_at": ride.get("created_at"),
        "distance_m": ride.get("distance_m"),
        "elevation_gain_m": ride.get("elevation_gain_m"),
        "duration_sec": ride.get("duration_sec"),
        "visibility": ride.get("visibility") or "public",
        "privacy": privacy,
    }
    if privacy.get("isOwner") is True:
        summary["dung_minted"] = ride.get("dung_minted")
    media = ride.get("_media") if isinstance(ride.get("_media"), list) else []
    visible_media = [
        item for item in media
        if isinstance(item, dict) and item.get("url")
    ]
    if visible_media:
        summary["media"] = visible_media
        cover = next((item for item in visible_media if item.get("role") == "cover"), None)
        summary["primaryMedia"] = cover or visible_media[0]
    route_preview = _ride_route_preview(ride, privacy)
    if route_preview:
        summary["routePreview"] = route_preview
    return summary


def _viewer_relationship_from_privacy(privacy: Any) -> ViewerRelationship:
    if getattr(privacy, "is_owner", False):
        return ViewerRelationship.self
    if getattr(privacy, "is_follower", False):
        return ViewerRelationship.following
    return ViewerRelationship.none


def _public_rider_for_profile(user: dict[str, Any], privacy: Any) -> PublicRiderRef:
    return public_rider_ref(
        user,
        is_public=user.get("is_public", True) if getattr(privacy, "can_view", False) else False,
        viewer_relationship=_viewer_relationship_from_privacy(privacy),
    )


def _profile_module(
    module_id: str,
    *,
    state: str,
    title: str,
    reason: Optional[str] = None,
    count: Optional[int] = None,
) -> dict[str, Any]:
    return {
        "contractVersion": "public_profile_module.v1",
        "id": module_id,
        "state": state,
        "title": title,
        "reason": reason,
        "count": count,
    }


async def load_private_user_profile(
    current_user: AuthenticatedUser,
    user_repo: UserRepository,
    ride_repo: RideRepository,
) -> UserProfilePrivate:
    """Build the authenticated user's private profile without duplicate stats work."""
    profile = await user_repo.get_private_user_profile(current_user.wallet)
    if not profile:
        await user_repo.create_user(current_user.wallet)
        profile = await user_repo.get_private_user_profile(current_user.wallet)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
    profile = await with_signed_avatar_url(profile) or profile

    user_id = str(profile.get("id"))
    stats, today_rides = await asyncio.gather(
        user_repo.get_user_stats(user_id),
        ride_repo.get_user_rides_for_date(user_id, date.today()),
    )
    return _build_private_profile_response(profile, stats, today_rides, current_user.wallet)


async def _leaderboard_summary_for_wallet(
    wallet: str,
    vault_repo: VaultRepository,
) -> UserLeaderboardSummaryResponse:
    positions_data = await vault_repo.get_user_leaderboard_positions(wallet)
    stats_data = await vault_repo.get_user_leaderboard_stats(wallet)

    positions = [
        VaultPosition(
            vault_id=p.get("vault_id", 0),
            canon_climb_id=p.get("canon_climb_id"),
            vault_name=p.get("vault_name", ""),
            vault_signature=p.get("vault_signature", ""),
            rank=p.get("rank", 0),
            best_time_seconds=p.get("best_time_seconds", 0),
            is_kom=p.get("is_kom", False),
            total_riders=p.get("total_riders", 0),
            percentile=p.get("percentile"),
            achieved_at=_parse_datetime(p.get("last_achieved_at")),
        )
        for p in positions_data
    ]

    stats = UserLeaderboardStats(
        total_positions=stats_data.get("total_positions", 0),
        kom_count=stats_data.get("kom_count", 0),
        podium_count=stats_data.get("podium_count", 0),
        top10_count=stats_data.get("top10_count", 0),
        total_vaults_completed=stats_data.get("total_vaults_completed", 0),
        best_percentile=stats_data.get("best_percentile"),
    )

    return UserLeaderboardSummaryResponse(
        wallet=wallet,
        stats=stats,
        positions=positions,
    )


def _public_board_achieved_at(value: Any) -> Optional[datetime]:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (OSError, OverflowError, TypeError, ValueError):
        return None


async def _public_leaderboard_summary_for_wallet(
    wallet: str,
    vault_repo: VaultRepository,
) -> UserLeaderboardSummaryResponse:
    """Build a cross-Vault summary only from privacy-eligible Board seats."""
    try:
        candidate_rows = await vault_repo.get_user_leaderboard_positions(wallet)
    except Exception as exc:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        ) from exc
    if not candidate_rows:
        return UserLeaderboardSummaryResponse(
            wallet=wallet,
            stats=UserLeaderboardStats(
                total_positions=0,
                kom_count=0,
                podium_count=0,
                top10_count=0,
                total_vaults_completed=0,
                best_percentile=None,
            ),
            positions=[],
        )
    client = getattr(vault_repo, "client", None)
    raw_reader = getattr(vault_repo, "get_vault_record_board_entries", None)
    if client is None or raw_reader is None:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    positions: list[VaultPosition] = []
    seen_vault_ids: set[int] = set()
    for candidate in candidate_rows:
        raw_vault_id = candidate.get("vault_id")
        if isinstance(raw_vault_id, bool):
            continue
        try:
            vault_id = int(raw_vault_id)
        except (TypeError, ValueError, OverflowError):
            continue
        if vault_id in seen_vault_ids:
            continue
        seen_vault_ids.add(vault_id)

        try:
            vault = await vault_repo.get_vault_by_id(vault_id)
            if not vault:
                continue
            raw_entries = await raw_reader(vault_id)
            projection = project_public_record_board(
                client,
                vault_row=vault,
                raw_entries=raw_entries,
            )
        except PublicRecordBoardPrivacyUnavailable:
            raise
        except Exception as exc:
            raise PublicRecordBoardPrivacyUnavailable(
                "public Record Board privacy projection unavailable"
            ) from exc

        public_entry = next(
            (
                entry
                for entry in projection.entries
                if str(entry.get("user") or "") == wallet
            ),
            None,
        )
        if public_entry is None:
            continue

        seat = int(public_entry["position"])
        canon_climb_id = vault.get("canon_climb_id") or candidate.get(
            "canon_climb_id"
        )
        positions.append(
            VaultPosition(
                vault_id=vault_id,
                canon_climb_id=canon_climb_id,
                vault_name=str(vault.get("name") or candidate.get("vault_name") or ""),
                vault_signature=str(
                    vault.get("signature_hex")
                    or candidate.get("vault_signature")
                    or ""
                ),
                rank=seat,
                best_time_seconds=int(public_entry.get("time_s") or 0),
                is_kom=(
                    projection.kom_holder == wallet
                    and projection.kom_time_s == int(public_entry.get("time_s") or 0)
                ),
                total_riders=len(projection.entries),
                percentile=None,
                achieved_at=_public_board_achieved_at(
                    public_entry.get("recorded_at")
                ),
            )
        )

    positions.sort(key=lambda position: (position.rank, position.vault_id))
    stats = UserLeaderboardStats(
        total_positions=len(positions),
        kom_count=sum(position.is_kom for position in positions),
        podium_count=sum(position.rank <= 3 for position in positions),
        top10_count=sum(position.rank <= 10 for position in positions),
        # Public summaries do not claim completion counts that cannot be tied
        # to an eligible Board row. This is a conservative proven lower bound.
        total_vaults_completed=len({position.vault_id for position in positions}),
        best_percentile=None,
    )
    return UserLeaderboardSummaryResponse(
        wallet=wallet,
        stats=stats,
        positions=positions,
    )


def _public_board_unavailable_http_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Public Record Board privacy projection is temporarily unavailable",
    )


# =============================================================================
# Profile Endpoints
# =============================================================================


@router.get("/me", response_model=UserProfilePrivate)
async def get_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UserProfilePrivate:
    """
    Get the current user's complete profile including private fields.

    Returns all profile data plus aggregated statistics.
    """
    return await load_private_user_profile(current_user, user_repo, ride_repo)


@router.get("/me/threshold", response_model=ThresholdResponse)
async def get_my_threshold(
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> ThresholdResponse:
    """Return the private, fail-closed rider Threshold projection."""
    try:
        raw = await ride_repo.get_reward_threshold_rider_projection(
            current_user.user_id
        )
        projection = parse_threshold_rider_projection(raw)
    except Exception as exc:
        _logger.error(
            "[Threshold] Authority projection unavailable for user %s: %s",
            current_user.user_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "threshold_authority_unavailable"},
        ) from exc

    pending = projection.pending_monday
    return ThresholdResponse(
        state=projection.state,
        current_w=projection.current_w,
        established_at=projection.established_at,
        last_raised_at=projection.last_raised_at,
        pending_monday=(
            ThresholdPendingMondayResponse(
                watts=pending.watts,
                effective_at=pending.effective_at,
            )
            if pending is not None
            else None
        ),
        sealing_in_progress=projection.sealing_in_progress,
    )


async def _private_beetle_cards(repo: DatabaseRepository, wallet: str) -> list[dict[str, Any]]:
    try:
        response = await repo._run(
            lambda: repo._client.table("beetle_cards")
            .select("*")
            .eq("wallet", wallet)
            .order("card_type")
            .execute()
        )
    except Exception as exc:
        _logger.debug("[Users] Private profile BeetleCards unavailable: %s", exc)
        return []
    return [dict(row) for row in (getattr(response, "data", None) or [])]


async def _private_unread_count(wallet: str) -> int:
    try:
        notification_repo = create_notification_repository()
        return int(await notification_repo.get_unread_count(wallet))
    except Exception as exc:
        _logger.debug("[Users] Private profile notifications unavailable: %s", exc)
        return 0


@router.get("/me/profile")
async def get_my_profile_bootstrap(
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
    repo: DatabaseRepository = Depends(get_repository),
    vault_repo: VaultRepository = Depends(get_vault_repository),
):
    """One coherent private account/profile object for mobile and portal first paint."""
    profile, beetle_cards, leaderboard, unread_count = await asyncio.gather(
        load_private_user_profile(current_user, user_repo, ride_repo),
        _private_beetle_cards(repo, current_user.wallet),
        _leaderboard_summary_for_wallet(current_user.wallet, vault_repo),
        _private_unread_count(current_user.wallet),
    )
    return {
        "contractVersion": "private_rider_profile.v1",
        "profile": profile.model_dump(mode="json", by_alias=True),
        "beetleCards": {
            "cards": beetle_cards,
            "count": len(beetle_cards),
        },
        "leaderboard": leaderboard.model_dump(mode="json", by_alias=True),
        "notifications": {
            "unreadCount": unread_count,
        },
        "modules": [
            _profile_module("profile", state="present", title="Profile"),
            _profile_module("beetle_cards", state="present" if beetle_cards else "empty", title="BeetleCards", count=len(beetle_cards)),
            _profile_module("leaderboard", state="present" if leaderboard.positions else "empty", title="Leaderboard", count=len(leaderboard.positions)),
            _profile_module("notifications", state="present" if unread_count else "empty", title="Notifications", count=unread_count),
        ],
    }


@router.put("/me", response_model=UserProfilePrivate)
async def update_my_profile(
    updates: UserProfileUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UserProfilePrivate:
    """
    Update the current user's profile.

    Only fields provided in the request body will be updated.
    Username changes are validated for format and availability.
    """
    update_dict = updates.model_dump(exclude_unset=True, mode="json")
    _logger.info(
        "[ProfileUpdate] user_id=%s fields=%s",
        current_user.user_id,
        sorted(update_dict.keys()),
    )

    if "avatar_url" in update_dict:
        raise HTTPException(
            status_code=400,
            detail="Use the avatar upload endpoints to change profile photos.",
        )

    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Get current profile to get user_id for stats
    profile = await user_repo.get_private_user_profile(current_user.wallet)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    user_id = str(profile.get("id"))

    # Validate username only if it's actually changing
    new_username = update_dict.get("username")
    if new_username and new_username.lower() != (profile.get("username") or "").lower():
        available, reason = await user_repo.check_username_available(new_username)
        if not available:
            raise HTTPException(
                status_code=400,
                detail=reason or "Username not available"
            )

    # Perform update (uses wallet, not user_id)
    updated = await user_repo.update_user_profile(current_user.wallet, update_dict)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update profile")
    clear_user_row_cache(user_id)
    updated = await with_signed_avatar_url(updated) or updated

    stats, today_rides = await asyncio.gather(
        user_repo.get_user_stats(user_id),
        ride_repo.get_user_rides_for_date(user_id, date.today()),
    )
    return _build_private_profile_response(updated, stats, today_rides, current_user.wallet)


async def _finish_avatar_cleanup(profile: dict, user_id: str, user_repo: UserRepository, storage: Any) -> None:
    paths = profile.get("avatar_cleanup_storage_paths") or []
    if not paths:
        return
    try:
        for path in paths:
            await storage.delete_photo_files(path)
        if not await user_repo.finish_avatar_cleanup(user_id, paths):
            raise StorageUnavailableError("Avatar cleanup changed concurrently")
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="Avatar storage temporarily unavailable. Please retry.") from None


@router.post("/me/avatar/init", response_model=AvatarUploadInitResponse)
async def avatar_upload_init(
    init_request: AvatarUploadInitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
) -> AvatarUploadInitResponse:
    """Create a signed upload URL for the authenticated rider's avatar."""
    profile = await user_repo.get_private_user_profile(current_user.wallet)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    pending_upload_id = profile.get("avatar_pending_upload_id")
    pending_storage_path = profile.get("avatar_pending_storage_path")
    stale_pending_storage_path = None
    if pending_upload_id and pending_storage_path:
        pending_created_at = _parse_datetime(profile.get("avatar_pending_created_at"))
        pending_expires_at = (
            pending_created_at + timedelta(seconds=AVATAR_SIGNED_URL_EXPIRY_SECONDS)
            if pending_created_at
            else None
        )
        if pending_expires_at is not None and pending_expires_at <= datetime.now(timezone.utc):
            stale_pending_storage_path = pending_storage_path
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An avatar upload is already pending. Complete or delete it before starting another.",
            )

    mime_type = normalize_avatar_mime_type(init_request.mime_type)
    if mime_type not in ALLOWED_AVATAR_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar must be a JPEG, PNG, WebP, HEIC, or HEIF image.",
        )

    upload_id = str(uuid_module.uuid4())
    storage_path = avatar_storage_path(
        current_user.user_id,
        upload_id,
        mime_type,
        init_request.file_name,
    )
    storage = create_file_storage_service()
    await _finish_avatar_cleanup(profile, current_user.user_id, user_repo, storage)
    if stale_pending_storage_path:
        try:
            await storage.delete_photo_files(stale_pending_storage_path)
        except StorageUnavailableError:
            raise HTTPException(status_code=503, detail="Avatar storage temporarily unavailable. Please retry.") from None

    try:
        signed_result = await storage.create_signed_upload_url(storage_path)
    except StorageUnavailableError as exc:
        _logger.error("[AvatarUploadInit] Storage unavailable for user %s: %s", current_user.user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Avatar storage temporarily unavailable. Please retry.",
        ) from exc

    await user_repo.begin_avatar_upload(
        user_id=current_user.user_id,
        upload_id=upload_id,
        storage_path=storage_path,
        file_name=init_request.file_name,
        mime_type=mime_type,
        size_bytes=init_request.file_size,
    )
    clear_user_row_cache(current_user.user_id)

    return AvatarUploadInitResponse(
        upload_id=upload_id,
        signed_url=signed_result["signed_url"],
        expires_in=AVATAR_SIGNED_URL_EXPIRY_SECONDS,
    )


@router.post("/me/avatar/complete", response_model=UserProfilePrivate)
async def avatar_upload_complete(
    complete_request: AvatarUploadCompleteRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UserProfilePrivate:
    """Finalize a direct-to-storage rider avatar upload."""
    profile = await user_repo.get_private_user_profile(current_user.wallet)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile.get("avatar_pending_upload_id") != complete_request.upload_id:
        completed_paths = {"sanitized/" + avatar_storage_path(
            current_user.user_id, complete_request.upload_id, mime
        ) for mime in ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")}
        if profile.get("avatar_storage_path") in completed_paths:
            await _finish_avatar_cleanup(profile, current_user.user_id, user_repo, create_file_storage_service())
            return await load_private_user_profile(current_user, user_repo, ride_repo)
        raise HTTPException(status_code=404, detail="Avatar upload not found")

    storage_path = profile.get("avatar_pending_storage_path")
    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Avatar upload missing storage path",
        )

    storage = create_file_storage_service()
    try:
        photo = await storage.prepare_photo(storage_path, profile["avatar_pending_mime_type"], int(profile.get("avatar_pending_size_bytes") or 0))
    except StorageFileNotFoundError:
        raise HTTPException(status_code=400, detail="Avatar not found in storage. Upload may have failed or expired.") from None
    except InvalidPhotoError as exc:
        _logger.warning("Avatar photo rejected reason=%s exit_code=%s", exc.reason, exc.exit_code)
        raise HTTPException(status_code=400, detail="Avatar must be a JPEG, PNG, WebP, HEIC, or HEIF image.") from None
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="Avatar storage temporarily unavailable. Please retry.") from None

    updated = await user_repo.complete_avatar_upload(
        user_id=current_user.user_id,
        upload_id=complete_request.upload_id,
        storage_path=photo.path,
        size_bytes=photo.size_bytes,
        mime_type=photo.mime_type,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Avatar upload not found")
    clear_user_row_cache(current_user.user_id)
    await _finish_avatar_cleanup(updated, current_user.user_id, user_repo, storage)

    return await load_private_user_profile(current_user, user_repo, ride_repo)


@router.delete("/me/avatar", response_model=UserProfilePrivate)
async def delete_my_avatar(
    current_user: AuthenticatedUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UserProfilePrivate:
    """Remove the authenticated rider's avatar and stop surfacing avatarUrl."""
    profile = await user_repo.get_private_user_profile(current_user.wallet)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    storage_paths = [
        path
        for path in (
            profile.get("avatar_storage_path"),
            profile.get("avatar_pending_storage_path"),
            *(profile.get("avatar_cleanup_storage_paths") or []),
        )
        if isinstance(path, str) and path.strip()
    ]
    if storage_paths:
        storage = create_file_storage_service()
        for storage_path in storage_paths:
            try:
                await storage.delete_photo_files(storage_path)
            except StorageUnavailableError:
                raise HTTPException(status_code=503, detail="Avatar storage temporarily unavailable. Please retry.") from None
    if not await user_repo.delete_avatar(current_user.user_id, expected_profile=profile):
        raise HTTPException(status_code=404, detail="Avatar upload not found")
    clear_user_row_cache(current_user.user_id)

    return await load_private_user_profile(current_user, user_repo, ride_repo)


@router.post("/check-username", response_model=UsernameCheckResponse)
@rate_limit(category="username_check")
async def check_username(
    payload: UsernameCheckRequest,
    request: Request,
    repo: DatabaseRepository = Depends(get_repository),
) -> UsernameCheckResponse:
    """
    Check if a username is available.
    """
    available, reason = await repo.check_username_available(payload.username)
    return UsernameCheckResponse(available=available, reason=reason)


@router.get(
    "/{identifier}",
    response_model=Union[UserProfileOwnerView, UserProfilePublic],
)
async def get_user_profile(
    identifier: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> Union[UserProfileOwnerView, UserProfilePublic]:
    """
    Get a user's public profile by user id, wallet address, or username.

    - User ID: Opaque Boulder Roller user UUID
    - Username: With or without @ prefix (e.g., "@alpha-code-3" or "alpha-code-3")

    Wallet addresses can be used for legacy lookup, but are not returned as
    public display identity.
    """
    # Normalize: strip @ prefix if present
    lookup = identifier.lstrip("@")

    user = await repo.get_user_by_identifier(lookup)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = str(user.get("id"))
    user = await with_signed_avatar_url(user) or user

    privacy = await resolve_profile_visibility(user, current_user, repo=repo)

    # Private profile - return minimal info unless the owner is viewing it.
    if not privacy.can_view:
        return UserProfilePublic(
            id=UUID(user_id),
            wallet=user.get("wallet"),
            rider=_public_rider_for_profile(user, privacy),
            username=user.get("username"),  # Still show username for lookups
            display_name=None,
            bio=None,
            avatar_url=None,
            is_public=False,
            privacy=privacy.to_client_dict(),
            created_at=None,
            total_rides=0,
            total_distance_km=0,
            total_elevation_m=0,
        )

    # Public profile or owner view - return the public profile shell and stats.
    stats = await repo.get_user_stats(user_id)

    profile_fields = {
        "id": UUID(user_id),
        "wallet": user.get("wallet"),
        "rider": _public_rider_for_profile(user, privacy),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "bio": user.get("bio"),
        "avatar_url": user.get("avatar_url"),
        "is_public": user.get("is_public", True),
        "privacy": privacy.to_client_dict(),
        "created_at": _parse_datetime(user.get("created_at")),
        "total_rides": stats.get("total_rides", 0),
        "total_distance_km": stats.get("total_distance_km", 0),
        "total_elevation_m": stats.get("total_elevation_m", 0),
        "follower_count": int(user.get("follower_count") or 0),
        "following_count": int(user.get("following_count") or 0),
    }
    if privacy.is_owner:
        return UserProfileOwnerView(
            **profile_fields,
            total_dung_earned=stats.get("total_dung_earned", 0),
        )
    return UserProfilePublic(
        **profile_fields,
    )


@router.get("/{identifier}/profile")
async def get_public_user_profile_bootstrap(
    identifier: str,
    limit: int = Query(5, ge=1, le=30),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    vault_repo: VaultRepository = Depends(get_vault_repository),
):
    """One coherent public rider profile object for mobile/portal detail screens."""
    profile = await get_user_profile(identifier, current_user, repo)
    public_identifier = profile.username or str(profile.id)
    relationship = (
        profile.rider.viewer_relationship.value
        if profile.rider and hasattr(profile.rider.viewer_relationship, "value")
        else "none"
    )
    is_self = bool(current_user and str(profile.id) == str(current_user.user_id))
    can_view = bool(profile.privacy and profile.privacy.can_view)

    follow_state = None
    if current_user and not is_self:
        is_following = bool(profile.privacy and profile.privacy.is_follower)
        is_followed_by = await repo.get_follow(str(profile.id), current_user.user_id)
        follow_state = {
            "isFollowing": is_following,
            "isFollowedBy": is_followed_by is not None,
            "isMutualFollow": is_following and is_followed_by is not None,
        }

    recent_rides = {"is_public": profile.is_public, "rides": [], "count": 0, "privacy": profile.privacy}
    beetle_cards = {"is_public": profile.is_public, "cards": [], "count": 0, "privacy": profile.privacy}
    leaderboard = None
    leaderboard_unavailable = False

    if can_view and profile.is_public:
        async def load_recent_rides() -> dict[str, Any]:
            try:
                return await get_public_user_recent_rides(
                    public_identifier,
                    limit=limit,
                    current_user=current_user,
                    repo=repo,
                )
            except HTTPException as exc:
                if exc.status_code != 501:
                    raise
                return recent_rides

        async def load_beetle_cards() -> dict[str, Any]:
            try:
                return await get_public_user_beetle_cards(
                    public_identifier,
                    current_user=current_user,
                    repo=repo,
                )
            except HTTPException as exc:
                if exc.status_code != 501:
                    raise
                return beetle_cards

        async def load_leaderboard():
            nonlocal leaderboard_unavailable
            try:
                return await _public_leaderboard_summary_for_wallet(
                    profile.wallet,
                    vault_repo,
                )
            except Exception as exc:
                leaderboard_unavailable = True
                _logger.debug("[Users] Public rider profile leaderboard unavailable: %s", exc)
                return None

        recent_rides, beetle_cards, leaderboard = await asyncio.gather(
            load_recent_rides(),
            load_beetle_cards(),
            load_leaderboard(),
        )

    capabilities = {
        **viewer_capabilities_dict(
            can_view=can_view,
            can_follow=bool(current_user and not is_self and profile.is_public),
            can_share=bool(profile.is_public),
            can_report=bool(current_user and not is_self),
            can_open_scan=bool(profile.is_public),
        ),
        "viewerRelationship": relationship,
    }
    modules = [
        _profile_module(
            "profile",
            state="present" if can_view else "hidden",
            title="Profile",
            reason=profile.privacy.reason if profile.privacy else None,
        ),
        _profile_module(
            "follow",
            state="present" if current_user and not is_self else "unavailable",
            title="Follow state",
            reason="self" if is_self else ("signed_out" if not current_user else None),
        ),
        _profile_module(
            "recent_rides",
            state=(
                "hidden"
                if not can_view
                else "present"
                if recent_rides.get("count", 0) > 0
                else "empty"
            ),
            title="Recent rides",
            reason=None if can_view else (profile.privacy.reason if profile.privacy else "private"),
            count=recent_rides.get("count", 0),
        ),
        _profile_module(
            "beetle_cards",
            state=(
                "hidden"
                if not can_view
                else "present"
                if beetle_cards.get("count", 0) > 0
                else "empty"
            ),
            title="BeetleCards",
            reason=None if can_view else (profile.privacy.reason if profile.privacy else "private"),
            count=beetle_cards.get("count", 0),
        ),
        _profile_module(
            "leaderboard",
            state=(
                "hidden"
                if not can_view
                else "unavailable"
                if leaderboard_unavailable
                else "present"
                if leaderboard and leaderboard.positions
                else "empty"
            ),
            title="Leaderboard",
            reason=(
                "privacy_projection_unavailable"
                if leaderboard_unavailable
                else None
                if can_view
                else (profile.privacy.reason if profile.privacy else "private")
            ),
            count=len(leaderboard.positions) if leaderboard else 0,
        ),
    ]

    return {
        "contractVersion": "public_rider_profile.v1",
        "rider": profile.rider.model_dump(mode="json", by_alias=True) if profile.rider else None,
        "profile": profile.model_dump(mode="json", by_alias=True),
        "privacy": profile.privacy.model_dump(mode="json", by_alias=True) if profile.privacy else None,
        "viewerCapabilities": capabilities,
        "modules": modules,
        "followState": follow_state,
        "recentRides": recent_rides,
        "beetleCards": beetle_cards,
        "leaderboard": leaderboard.model_dump(mode="json", by_alias=True) if leaderboard else None,
    }


@router.get("/{identifier}/recent-rides")
async def get_public_user_recent_rides(
    identifier: str,
    limit: int = Query(10, ge=1, le=25),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Return public recent rides for a rider profile without leaking private rides."""
    user = await repo.get_user_by_identifier(identifier.lstrip("@"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_privacy = await resolve_profile_visibility(user, current_user, repo=repo)
    viewer_id = viewer_user_id(current_user)
    if not profile_privacy.can_view:
        return {
            "is_public": False,
            "rides": [],
            "count": 0,
            "privacy": profile_privacy.to_client_dict(),
        }

    get_recent = getattr(repo, "get_public_user_recent_rides", None)
    if not get_recent:
        raise HTTPException(status_code=501, detail="Recent rides unavailable")
    try:
        if profile_privacy.is_owner:
            rides = await repo.list_rides_for_user(str(user["id"]))
        elif viewer_id and profile_privacy.is_follower:
            get_feed_rides = getattr(repo, "get_feed_rides", None)
            rides = (
                await get_feed_rides([str(user["id"])], limit=limit)
                if get_feed_rides
                else await get_recent(str(user["id"]), limit=limit)
            )
        else:
            rides = await get_recent(str(user["id"]), limit=limit)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="Recent rides unavailable") from exc
    media_by_ride = await _public_recent_media_by_ride(
        repo,
        [str(ride.get("id")) for ride in rides if ride.get("id")],
    )
    # Local import avoids a routes-module import cycle during app startup.
    from .rides import _route_preview_points_for_record

    summaries = []
    for ride in rides:
        ride_privacy = await resolve_ride_visibility(
            ride,
            current_user,
            repo=repo,
            owner_profile=user,
        )
        if not ride_privacy.can_view:
            continue
        ride_id = str(ride.get("id") or "")
        preview_points, preview_zones = await _route_preview_points_for_record(
            ride,
            ride_privacy,
            repo,
        )
        ride = {
            **ride,
            "privacy": ride_privacy.to_client_dict(),
            "_media": media_by_ride.get(ride_id, []),
            "_route_preview_points": preview_points,
            "_route_preview_zones": preview_zones,
        }
        summaries.append(_public_ride_summary(ride))
        if len(summaries) >= limit:
            break
    return {
        "is_public": user.get("is_public", True),
        "rides": summaries,
        "count": len(summaries),
        "privacy": profile_privacy.to_client_dict(),
    }


@router.get("/{identifier}/beetle-cards")
async def get_public_user_beetle_cards(
    identifier: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Return public BeetleCard summaries for rider profile surfaces."""
    user = await repo.get_user_by_identifier(identifier.lstrip("@"))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    profile_privacy = await resolve_profile_visibility(user, current_user, repo=repo)
    if not profile_privacy.can_view:
        return {
            "is_public": False,
            "cards": [],
            "count": 0,
            "privacy": profile_privacy.to_client_dict(),
        }

    get_cards = getattr(repo, "get_public_beetle_cards_for_wallet", None)
    if not get_cards:
        raise HTTPException(status_code=501, detail="Beetle cards unavailable")
    try:
        cards = await get_cards(str(user.get("wallet") or ""))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="Beetle cards unavailable") from exc
    cards = [
        {key: value for key, value in dict(card).items() if key not in {"wallet", "ownerWallet", "owner_wallet"}}
        for card in cards
    ]
    return {
        "is_public": user.get("is_public", True),
        "cards": cards,
        "count": len(cards),
        "privacy": profile_privacy.to_client_dict(),
    }


@router.get("/me/achievements")
async def get_my_achievements(
    current_user: AuthenticatedUser = Depends(get_current_user),
    achievements_repo: AchievementRepository = Depends(get_achievement_repository),
):
    """Return the current user's recent achievements."""
    achievements = await achievements_repo.get_user_achievements(
        current_user.user_id, limit=50
    )
    return {"achievements": achievements}


# =============================================================================
# Session Management Endpoints
# =============================================================================


@router.get("/me/sessions", response_model=SessionsListResponse)
async def list_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> SessionsListResponse:
    """
    List all active sessions for the current user.

    Each session shows device info, location hints, and timestamps.
    The current session is marked with is_current=True.
    """
    current_hash = current_user.session_token_hash

    # Use AuthRepository for session management
    auth_repo = create_auth_repository()
    sessions_data = await auth_repo.list_user_sessions(
        current_user.wallet,
        current_hash,
        current_device_id=current_user.device_id,
    )

    sessions = []
    for s in sessions_data:
        sessions.append(
            SessionInfo(
                id=UUID(str(s.get("id"))),
                device_id=s.get("device_id", ""),
                user_agent=s.get("user_agent"),
                ip_address=s.get("ip_address"),
                location_hint=s.get("location_hint"),
                created_at=_parse_datetime(s.get("created_at")) or datetime.now(timezone.utc),
                last_used_at=_parse_datetime(s.get("last_used_at")),
                is_current=_session_is_current(
                    s,
                    current_hash=current_hash,
                    current_device_id=current_user.device_id,
                ),
            )
        )

    return SessionsListResponse(sessions=sessions)


@router.delete("/me/sessions/{session_id}", response_model=RevokeSessionsResponse)
async def revoke_session(
    session_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> RevokeSessionsResponse:
    """
    Revoke a specific session by ID.

    The user will be logged out on that device.
    Cannot revoke the current session (use /auth/logout instead).
    """
    # Use AuthRepository for session revocation with reason tracking
    auth_repo = create_auth_repository()

    # Revoke with reason for notification
    revoked_session = await auth_repo.revoke_session_with_reason(
        session_id=str(session_id),
        wallet=current_user.wallet,
        reason="logged_out_other_device",
    )

    if not revoked_session:
        raise HTTPException(status_code=404, detail="Session not found or already revoked")

    # Send notification to the revoked session's device
    try:
        notification_service = create_notification_service()
        await notification_service.notify_session_revoked(
            wallet=current_user.wallet,
            session_id=str(session_id),
            reason="logged_out_other_device",
            revoked_by_device=None,  # Could add current device_id if available
        )
    except Exception as e:
        _logger.warning(f"[Users] Failed to send session revoked notification: {e}")

    return RevokeSessionsResponse(status="revoked", count=1)


@router.delete("/me/sessions", response_model=RevokeSessionsResponse)
async def revoke_all_other_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> RevokeSessionsResponse:
    """
    Revoke all sessions except the current one.

    Useful for "Log out everywhere else" functionality.
    The current session remains active.
    """
    current_hash = current_user.session_token_hash
    if not current_hash and current_user.device_id == "unknown":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current session could not be identified")

    # Use AuthRepository for session revocation with reason tracking
    auth_repo = create_auth_repository()

    if current_hash:
        revoked_sessions = await auth_repo.revoke_all_other_sessions_with_reason(
            wallet=current_user.wallet,
            current_token_hash=current_hash,
            reason="logged_out_other_device",
        )
    else:
        sessions_data = await auth_repo.list_user_sessions(current_user.wallet, None)
        revoked_sessions = []
        for session in sessions_data:
            if str(session.get("device_id") or "") == str(current_user.device_id):
                continue
            revoked = await auth_repo.revoke_session_with_reason(
                session_id=str(session.get("id")),
                wallet=current_user.wallet,
                reason="logged_out_other_device",
            )
            if revoked:
                revoked_sessions.append(revoked)

    # Send notifications to all revoked sessions
    if revoked_sessions:
        try:
            notification_service = create_notification_service()
            for session in revoked_sessions:
                await notification_service.notify_session_revoked(
                    wallet=current_user.wallet,
                    session_id=session.get("id", "unknown"),
                    reason="logged_out_other_device",
                    revoked_by_device=None,  # Could add current device_id
                )
        except Exception as e:
            _logger.warning(f"[Users] Failed to send session revoked notifications: {e}")

    return RevokeSessionsResponse(status="revoked", count=len(revoked_sessions))


# =============================================================================
# Leaderboard Summary Endpoints
# =============================================================================


@router.get("/me/climbs", response_model=RiddenClimbsResponse)
async def get_my_ridden_climbs(
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repository),
) -> RiddenClimbsResponse:
    """Every canon climb the rider has confirmed completions on — Your
    Climbs. Receipt-confirmed evidence only; sorted by last ridden."""
    rows = await vault_repo.get_user_ridden_climbs(current_user.wallet)
    climbs = [
        RiddenClimb(
            canon_climb_id=row.get("canon_climb_id"),
            vault_id=row.get("vault_id"),
            name=row.get("name"),
            attempts=int(row.get("attempts") or 0),
            best_time_seconds=row.get("best_time_seconds"),
            last_ridden_at=_parse_datetime(row.get("last_ridden_at")),
            length_m=row.get("length_m"),
            avg_gradient_pct=row.get("avg_gradient_pct"),
        )
        for row in rows
    ]
    return RiddenClimbsResponse(climbs=climbs)


@router.get("/me/leaderboard-positions", response_model=UserLeaderboardSummaryResponse)
async def get_my_leaderboard_positions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repository),
) -> UserLeaderboardSummaryResponse:
    """
    Get the current user's leaderboard positions across all vaults.

    Returns:
    - Total positions (how many top-10s)
    - KOM count
    - Podium count (top 3)
    - List of all positions with vault details
    """
    return await _leaderboard_summary_for_wallet(current_user.wallet, vault_repo)


@router.get("/{wallet}/leaderboard-positions", response_model=UserLeaderboardSummaryResponse)
async def get_user_leaderboard_positions(
    wallet: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    vault_repo: VaultRepository = Depends(get_vault_repository),
) -> UserLeaderboardSummaryResponse:
    """
    Get a user's leaderboard positions across all vaults.

    Returns:
    - Total positions (how many top-10s)
    - KOM count
    - Podium count (top 3)
    - List of all positions with vault details
    """
    target = await repo.get_user_by_identifier(wallet)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    privacy = await resolve_profile_visibility(target, current_user)
    if not privacy.can_view or target.get("is_public") is False:
        raise HTTPException(status_code=404, detail="Leaderboard not found")

    try:
        return await _public_leaderboard_summary_for_wallet(
            str(target.get("wallet") or wallet),
            vault_repo,
        )
    except PublicRecordBoardPrivacyUnavailable as exc:
        raise _public_board_unavailable_http_exception() from exc
