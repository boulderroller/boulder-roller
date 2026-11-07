from typing import Any, List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..dependencies import AuthenticatedUser, get_current_user, get_optional_current_user_strict, get_repository
from ..middleware.rate_limiter import rate_limit
from ..moderation_contracts import ALLOWED_REPORT_STATUSES, ALLOWED_RESOLUTION_ACTIONS, serialize_social_report
from ..repositories import DatabaseRepository
from ..avatar_media_contracts import with_signed_avatar_url
from ..rider_identity_contracts import public_rider_ref, public_rider_ref_dict
from ..schemas import UserProfilePublic
from ..services.privacy_resolver import resolve_profile_visibility
from .admin import require_admin
from .notifications import create_notification
from .rides import check_ride_access

router = APIRouter()
moderation_router = APIRouter(prefix="/admin/moderation", tags=["moderation"])


class SocialReportCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_type: str = Field(validation_alias=AliasChoices("target_type", "targetType"))
    target_id: UUID = Field(validation_alias=AliasChoices("target_id", "targetId"))
    reason: str
    details: Optional[str] = None


class SocialReportResolve(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: str
    action: Optional[str] = None
    resolution_note: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("resolution_note", "resolutionNote"),
    )
    reporter_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("reporter_message", "reporterMessage"),
    )


def _clean_report_text(value: Optional[str], *, field: str, max_length: int) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        if field == "reason":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Report reason cannot be empty",
            )
        return None
    if len(cleaned) > max_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Report {field} is too long",
        )
    return cleaned


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truncated_wallet(value: Any) -> str:
    wallet = str(value or "")
    return f"{wallet[:4]}...{wallet[-4:]}" if len(wallet) > 8 else wallet


async def _public_social_profile(user: dict[str, Any]) -> UserProfilePublic:
    privacy = await resolve_profile_visibility(user, None)
    can_view = privacy.can_view
    row = dict(user)

    if can_view:
        row = await with_signed_avatar_url(row) or row
    else:
        row["display_name"] = None
        row["bio"] = None
        row["avatar_url"] = None

    is_public = bool(can_view and row.get("is_public", True) is not False)
    return UserProfilePublic(
        id=UUID(str(row.get("id"))),
        wallet=str(row.get("wallet") or "") if can_view else _truncated_wallet(row.get("wallet")),
        rider=public_rider_ref(row, is_public=is_public),
        username=row.get("username"),
        display_name=row.get("display_name") if can_view else None,
        bio=row.get("bio") if can_view else None,
        avatar_url=row.get("avatar_url") if can_view else None,
        is_public=is_public,
        privacy=privacy.to_client_dict(),
        created_at=row.get("created_at"),
        total_rides=_int_value(row.get("total_rides")),
        total_distance_km=float(row.get("total_distance_km") or 0),
        total_elevation_m=float(row.get("total_elevation_m") or 0),
        follower_count=_int_value(row.get("follower_count")),
        following_count=_int_value(row.get("following_count")),
    )


async def _public_social_profiles(users: list[dict[str, Any]]) -> list[UserProfilePublic]:
    return [await _public_social_profile(user) for user in users]


async def _require_profile_list_access(user_id: UUID, current_user: Optional[AuthenticatedUser], repo: DatabaseRepository) -> None:
    profile = await repo.get_user_by_id(str(user_id))
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    privacy = await resolve_profile_visibility(profile, current_user, repo=repo)
    if not privacy.can_view:
        raise HTTPException(status_code=404, detail="User not found")


async def _validate_report_target(
    *,
    repo: DatabaseRepository,
    current_user: AuthenticatedUser,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    normalized_type = target_type.strip().lower()
    if normalized_type == "ride":
        ride = await repo.get_ride(target_id)
        if not ride:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
        await check_ride_access(ride, current_user, level="read", repo=repo)
        return {}

    if normalized_type == "ride_media":
        get_media = getattr(repo, "get_ride_media", None)
        media = await get_media(target_id) if get_media else None
        if not media:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride photo not found")
        if media.get("user_id") == current_user.user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot report your own ride photo")
        ride = await repo.get_ride(str(media.get("ride_id")))
        if not ride:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
        await check_ride_access(ride, current_user, level="read", repo=repo)
        return {
            "rideId": str(media.get("ride_id")),
            "mediaId": target_id,
        }

    if normalized_type == "comment":
        get_comment = getattr(repo, "get_comment", None)
        existing = await get_comment(target_id) if get_comment else None
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        if existing.get("targetType") == "ride" and existing.get("targetId"):
            ride = await repo.get_ride(str(existing["targetId"]))
            if not ride:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
            await check_ride_access(ride, current_user, level="read", repo=repo)
        return {}

    if normalized_type == "user":
        if target_id == current_user.user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot report yourself")
        target = await repo.get_user_by_id(target_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return {}

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Unsupported report target type",
    )


@router.post("/follow/{user_id}")
@rate_limit(category="social")
async def follow_user(
    user_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Follow another user."""
    if str(user_id) == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself",
        )

    target = await repo.get_user_by_id(str(user_id))
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    existing = await repo.get_follow(current_user.user_id, str(user_id))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already following this user",
        )

    await repo.create_follow(current_user.user_id, str(user_id))

    # Notify the followed user
    follower_display = getattr(current_user, "username", None) or current_user.wallet[:8]
    await create_notification(
        repo=repo,
        user_id=str(user_id),
        notification_type="follow_created",
        title="New follower",
        message=f"@{follower_display} started following you",
        data={"follower_id": current_user.user_id},
        actor_id=current_user.user_id,
        target_type="user",
        target_id=current_user.user_id,
    )

    return {"status": "followed", "following_id": str(user_id)}


@router.delete("/follow/{user_id}")
@rate_limit(category="social")
async def unfollow_user(
    user_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Unfollow a user."""
    deleted = await repo.delete_follow(current_user.user_id, str(user_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not following this user",
        )
    return {"status": "unfollowed", "unfollowed_id": str(user_id)}


@router.get("/followers/{user_id}", response_model=List[UserProfilePublic])
@rate_limit(category="social")
async def get_followers(
    user_id: UUID,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user_strict),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get list of users following the specified user."""
    await _require_profile_list_access(user_id, current_user, repo)
    followers = await repo.get_followers(str(user_id), limit=limit, offset=offset)
    return await _public_social_profiles(followers)


@router.get("/following/{user_id}", response_model=List[UserProfilePublic])
@rate_limit(category="social")
async def get_following(
    user_id: UUID,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user_strict),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get list of users the specified user is following."""
    await _require_profile_list_access(user_id, current_user, repo)
    following = await repo.get_following(str(user_id), limit=limit, offset=offset)
    return await _public_social_profiles(following)


@router.get("/is-following/{user_id}")
@rate_limit(category="social")
async def check_is_following(
    user_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Check if current user is following the specified user.

    Also returns whether it's a mutual follow (both users follow each other).
    """
    is_following = await repo.get_follow(current_user.user_id, str(user_id))
    is_followed_by = await repo.get_follow(str(user_id), current_user.user_id)

    return {
        "is_following": is_following is not None,
        "is_followed_by": is_followed_by is not None,
        "is_mutual_follow": is_following is not None and is_followed_by is not None,
    }


@router.get("/suggested")
@rate_limit(category="social")
async def get_suggested_riders(
    request: Request,
    limit: int = 10,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get suggested riders to follow.

    Suggestions based on:
    - Active users the current user doesn't follow
    - Users with the most rides (active community members)
    """
    # Get IDs of users already followed
    following_ids = await repo.get_following_ids(current_user.user_id)
    following_ids_set = set(following_ids) if following_ids else set()
    following_ids_set.add(current_user.user_id)  # Exclude self

    # Get active users with the most rides (who we're not following)
    result = await repo._run(
        lambda: repo._client.table("users")
        .select("id, wallet, username, display_name, avatar_url, avatar_storage_path, is_public")
        .neq("id", current_user.user_id)
        .eq("is_public", True)
        .order("created_at", desc=True)
        .limit(limit * 3)  # Get extra to filter
        .execute()
    )

    users = result.data or []

    # Filter out already-followed users
    suggestions = []
    for user in users:
        if user.get("id") not in following_ids_set:
            privacy = await resolve_profile_visibility(user, current_user)
            if not privacy.can_view:
                continue
            user = await with_signed_avatar_url(user) or user
            suggestions.append({
                "id": user.get("id"),
                "username": user.get("username"),
                "displayName": user.get("display_name"),
                "avatarUrl": user.get("avatar_url"),
                "rider": public_rider_ref_dict(user, is_public=True),
            })
            if len(suggestions) >= limit:
                break

    return {"suggestions": suggestions, "count": len(suggestions)}


@router.post("/reports")
@rate_limit(category="social_report")
async def report_social_content(
    report: SocialReportCreate,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Report ride, comment, or rider content for moderation review."""
    target_type = report.target_type.strip().lower()
    target_id = str(report.target_id)
    target_metadata = await _validate_report_target(
        repo=repo,
        current_user=current_user,
        target_type=target_type,
        target_id=target_id,
    )

    create_report = getattr(repo, "create_social_report", None)
    if not create_report:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable")

    try:
        created = await create_report(
            reporter_id=current_user.user_id,
            target_type=target_type,
            target_id=target_id,
            reason=_clean_report_text(report.reason, field="reason", max_length=80) or "other",
            details=_clean_report_text(report.details, field="details", max_length=2000),
            moderation_metadata=target_metadata,
        )
        return serialize_social_report(created)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable") from exc


@router.get("/reports/me")
@rate_limit(category="general")
async def get_my_social_reports(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Reporter-visible report history without leaking internal moderation notes."""
    list_reports = getattr(repo, "list_user_social_reports", None)
    if not list_reports:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable")
    try:
        reports = await list_reports(reporter_id=current_user.user_id, limit=limit, offset=offset)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable") from exc
    return {"reports": [serialize_social_report(report) for report in reports], "count": len(reports)}


@router.get("/reports/{report_id}")
@rate_limit(category="general")
async def get_my_social_report(
    report_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Reporter-visible report detail without internal moderation notes."""
    get_report = getattr(repo, "get_social_report_for_reporter", None)
    if not get_report:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable")
    try:
        report = await get_report(report_id=str(report_id), reporter_id=current_user.user_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable") from exc
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return serialize_social_report(report)


@moderation_router.get("/reports")
@rate_limit(category="general")
async def get_moderation_reports(
    request: Request,
    report_status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Admin moderation queue for reported social content."""
    list_reports = getattr(repo, "list_social_reports", None)
    if not list_reports:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable")
    try:
        reports = await list_reports(status=report_status, limit=limit, offset=offset)
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable") from exc
    return {"reports": [serialize_social_report(report) for report in reports], "count": len(reports)}


@moderation_router.patch("/reports/{report_id}")
@rate_limit(category="general")
async def resolve_moderation_report(
    report_id: UUID,
    update: SocialReportResolve,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Resolve or dismiss a social report."""
    if update.status not in ALLOWED_REPORT_STATUSES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid report status")
    if update.action is not None and update.action not in ALLOWED_RESOLUTION_ACTIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid moderation action")
    resolve_report = getattr(repo, "resolve_social_report", None)
    if not resolve_report:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable")
    admin_id, _role = admin_ctx
    try:
        resolution_note = _clean_report_text(update.resolution_note, field="resolution note", max_length=2000)
        reporter_message = _clean_report_text(update.reporter_message, field="reporter message", max_length=500)
        try:
            resolved = await resolve_report(
                report_id=str(report_id),
                reviewer_id=str(admin_id),
                status=update.status,
                resolution_note=resolution_note,
                resolution_action=update.action,
                reporter_message=reporter_message,
            )
        except TypeError as type_error:
            if "unexpected keyword" not in str(type_error):
                raise
            resolved = await resolve_report(
                report_id=str(report_id),
                reviewer_id=str(admin_id),
                status=update.status,
                resolution_note=resolution_note,
            )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Reports unavailable") from exc
    if not resolved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if resolved.get("status") in {"resolved", "dismissed"} and resolved.get("reporterId"):
        await create_notification(
            repo=repo,
            user_id=str(resolved["reporterId"]),
            notification_type="report_resolved",
            title="Report reviewed",
            message=resolved.get("reporterMessage") or "Your report was reviewed.",
            data={
                "report_id": str(report_id),
                "target_type": resolved.get("targetType"),
                "target_id": resolved.get("targetId"),
                "reporter_outcome": resolved.get("reporterOutcome"),
                "resolution_action": resolved.get("resolutionAction"),
            },
            actor_id=str(admin_id),
            target_type="report",
            target_id=str(report_id),
            dedupe_key=f"report_resolved:{report_id}:{resolved.get('status')}",
        )
    return serialize_social_report(resolved)
