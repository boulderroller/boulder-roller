from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ..avatar_media_contracts import with_signed_avatar_url
from ..dependencies import AuthenticatedUser, get_current_user, get_optional_current_user, get_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository
from ..rider_identity_contracts import public_rider_ref_dict
from ..services.privacy_resolver import resolve_profile_visibility
from .notifications import create_notification
from .rides import check_ride_access

router = APIRouter(tags=["interactions"])


class CommentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str
    parent_id: Optional[UUID] = Field(
        default=None,
        validation_alias=AliasChoices("parent_id", "parentId"),
    )


class CommentUpdate(BaseModel):
    content: str


def _clean_comment_content(content: str) -> str:
    cleaned = content.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Comment content cannot be empty",
        )
    if len(cleaned) > 2000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Comment content is too long",
        )
    return cleaned


async def _validate_comment_parent(
    repo: DatabaseRepository,
    *,
    parent_id: UUID | None,
    target_type: str,
    target_id: str,
) -> None:
    if parent_id is None:
        return

    get_comment = getattr(repo, "get_comment", None)
    if not get_comment:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Comment replies unavailable",
        )

    parent = await get_comment(str(parent_id))
    if not parent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")

    parent_target_type = parent.get("targetType") or parent.get("target_type")
    parent_target_id = parent.get("targetId") or parent.get("target_id")
    parent_state = parent.get("moderationState") or parent.get("moderation_state") or "visible"
    if (
        parent_target_type != target_type
        or str(parent_target_id) != target_id
        or parent_state != "visible"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")


def _comment_author_row(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": comment.get("userId") or comment.get("user_id"),
        "username": comment.get("username"),
        "display_name": comment.get("displayName") or comment.get("display_name"),
        "avatar_url": comment.get("avatarUrl") or comment.get("avatar_url"),
        "avatar_storage_path": comment.get("avatar_storage_path"),
        "is_public": comment.get("isPublic", comment.get("is_public")),
        "moderation_state": comment.get("authorModerationState") or comment.get("author_moderation_state"),
    }


def _comment_author(comment: dict) -> dict:
    return public_rider_ref_dict(
        {
            "id": comment.get("userId") or comment.get("user_id"),
            "username": comment.get("username"),
            "displayName": comment.get("displayName"),
            "display_name": comment.get("display_name"),
            "avatarUrl": comment.get("avatarUrl"),
            "avatar_url": comment.get("avatar_url"),
        },
        is_public=comment.get("isPublic", comment.get("is_public")),
    )


async def _with_signed_comment_avatar(
    comment: dict,
    current_user: Optional[AuthenticatedUser] = None,
) -> dict:
    author = _comment_author_row(comment)
    privacy = await resolve_profile_visibility(author, current_user)
    out = dict(comment)

    if not privacy.can_view:
        out["displayName"] = None
        out["display_name"] = None
        out["avatarUrl"] = None
        out["avatar_url"] = None
        out["avatar_storage_path"] = None
        out["isPublic"] = False
        out["is_public"] = False
        return out

    signed = await with_signed_avatar_url(author)
    if signed is not None:
        out["avatarUrl"] = signed.get("avatar_url")
        out["avatar_url"] = signed.get("avatar_url")
        out["isPublic"] = author.get("is_public") is not False
        out["is_public"] = author.get("is_public") is not False
    return out


@router.post("/rides/{ride_id}/comments")
@rate_limit(category="social")
async def add_comment_to_ride(
    ride_id: UUID,
    comment: CommentCreate,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Add a comment to a ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    if ride.get("comments_enabled") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Comments are disabled for this ride",
        )

    content = _clean_comment_content(comment.content)
    await _validate_comment_parent(
        repo,
        parent_id=comment.parent_id,
        target_type="ride",
        target_id=str(ride_id),
    )

    created = await repo.create_comment(
        user_id=current_user.user_id,
        target_type="ride",
        target_id=str(ride_id),
        content=content,
        parent_id=str(comment.parent_id) if comment.parent_id else None,
    )

    if ride.get("user_id") and ride["user_id"] != current_user.user_id:
        await create_notification(
            repo=repo,
            user_id=ride["user_id"],
            notification_type="comment_created",
            title="New comment on your ride",
            message=f"{content[:50]}...",
            data={"ride_id": str(ride_id), "comment_id": created.get("id")},
            actor_id=current_user.user_id,
            target_type="ride",
            target_id=str(ride_id),
        )

    created = await _with_signed_comment_avatar(created, current_user)
    created["author"] = _comment_author(created)
    return created


@router.patch("/rides/{ride_id}/comments/{comment_id}")
@rate_limit(category="social")
async def update_ride_comment(
    ride_id: UUID,
    comment_id: UUID,
    update: CommentUpdate,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Update the current user's comment on a readable ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    get_comment = getattr(repo, "get_comment", None)
    existing = await get_comment(str(comment_id)) if get_comment else None
    if not existing or existing.get("targetType") != "ride" or str(existing.get("targetId")) != str(ride_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if existing.get("userId") != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your comment")

    update_comment = getattr(repo, "update_comment", None)
    if not update_comment:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Comment updates unavailable")

    updated = await update_comment(str(comment_id), current_user.user_id, _clean_comment_content(update.content))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    updated = await _with_signed_comment_avatar(updated, current_user)
    updated["author"] = _comment_author(updated)
    return updated


@router.delete("/rides/{ride_id}/comments/{comment_id}")
@rate_limit(category="social")
async def delete_ride_comment(
    ride_id: UUID,
    comment_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Delete the current user's comment on a readable ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    get_comment = getattr(repo, "get_comment", None)
    existing = await get_comment(str(comment_id)) if get_comment else None
    if not existing or existing.get("targetType") != "ride" or str(existing.get("targetId")) != str(ride_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if existing.get("userId") != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your comment")

    delete_comment = getattr(repo, "delete_comment", None)
    if not delete_comment:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Comment deletes unavailable")

    deleted = await delete_comment(str(comment_id), current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return {"status": "comment_deleted", "comment_id": str(comment_id)}


@router.get("/rides/{ride_id}/comments")
@rate_limit(category="social")
async def get_ride_comments(
    ride_id: UUID,
    request: Request,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get all comments for a ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    comments = await repo.get_comments("ride", str(ride_id))
    get_report_summaries = getattr(repo, "get_report_summaries", None)
    if current_user and get_report_summaries and comments:
        summaries = await get_report_summaries(
            "comment",
            [str(comment.get("id")) for comment in comments if comment.get("id")],
            current_user.user_id,
        )
        for comment in comments:
            comment.update(summaries.get(str(comment.get("id")), {}))
    for comment in comments:
        comment.update(await _with_signed_comment_avatar(comment, current_user))
        comment["author"] = _comment_author(comment)
    return {"comments": comments}


@router.get("/rides/{ride_id}/interactions")
@rate_limit(category="social")
async def get_ride_interactions(
    ride_id: UUID,
    request: Request,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get interaction counts and viewer state for a ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    get_summaries = getattr(repo, "get_interaction_summaries", None)
    summaries = await get_summaries(
        "ride",
        [str(ride_id)],
        current_user.user_id if current_user else None,
    ) if get_summaries else {}
    summary = summaries.get(str(ride_id), {})
    return {
        "rideId": str(ride_id),
        "kudosCount": summary.get("kudosCount", 0),
        "commentCount": summary.get("commentCount", 0),
        "viewerHasKudos": summary.get("viewerHasKudos", False),
        "viewerReported": summary.get("viewerReported", False),
        "reportStatus": summary.get("reportStatus"),
        "commentsEnabled": ride.get("comments_enabled", True) is not False,
        "canComment": (ride.get("comments_enabled", True) is not False) and current_user is not None,
    }


@router.post("/rides/{ride_id}/kudos")
@rate_limit(category="social")
async def give_kudos_to_ride(
    ride_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Give kudos to a ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    existing = await repo.get_kudos(current_user.user_id, "ride", str(ride_id))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already gave kudos")

    await repo.create_kudos(current_user.user_id, "ride", str(ride_id))
    await repo.increment_kudos_count("ride", str(ride_id))

    if ride.get("user_id") and ride["user_id"] != current_user.user_id:
        await create_notification(
            repo=repo,
            user_id=ride["user_id"],
            notification_type="kudos_created",
            title="Someone gave you kudos!",
            message="A rider liked your ride",
            data={"ride_id": str(ride_id)},
            actor_id=current_user.user_id,
            target_type="ride",
            target_id=str(ride_id),
        )

    return {"status": "kudos_given"}


@router.delete("/rides/{ride_id}/kudos")
@rate_limit(category="social")
async def remove_kudos_from_ride(
    ride_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Remove kudos from a ride."""
    ride = await repo.get_ride(str(ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    deleted = await repo.delete_kudos(current_user.user_id, "ride", str(ride_id))
    if deleted:
        await repo.decrement_kudos_count("ride", str(ride_id))
    return {"status": "kudos_removed"}
