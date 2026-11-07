from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..notification_contracts import (
    NOTIFICATION_CONTRACT_VERSION,
    default_notification_preferences,
    notification_is_suppressed,
    serialize_notification,
)
from ..repositories import DatabaseRepository, NotificationRepository, create_notification_repository

router = APIRouter()


class NotificationPreferences(BaseModel):
    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    new_follower: Optional[bool] = None
    ride_completed: Optional[bool] = None
    achievement_unlocked: Optional[bool] = None
    kom_beaten: Optional[bool] = None
    staking_reward: Optional[bool] = None
    social_activity: Optional[bool] = None
    leaderboard_updates: Optional[bool] = None
    payout_alerts: Optional[bool] = None
    system_announcements: Optional[bool] = None
    security_alerts: Optional[bool] = None
    connected_app_alerts: Optional[bool] = None
    ride_updates: Optional[bool] = None
    follow_created: Optional[bool] = None
    comment_created: Optional[bool] = None
    kudos_created: Optional[bool] = None
    ride_finalized: Optional[bool] = None
    ride_failed: Optional[bool] = None
    leaderboard_entered: Optional[bool] = None
    leaderboard_bumped: Optional[bool] = None
    rank_changed: Optional[bool] = None
    record_rank_moved: Optional[bool] = None
    kom_achieved: Optional[bool] = None
    local_legend_moved: Optional[bool] = None
    payout_received: Optional[bool] = None
    stake_payout: Optional[bool] = None
    legend_payout: Optional[bool] = None
    report_resolved: Optional[bool] = None
    proof_updated: Optional[bool] = None
    settlement_finalized: Optional[bool] = None
    tier_unlocked: Optional[bool] = None
    login_new_device: Optional[bool] = None
    session_revoked: Optional[bool] = None
    strava_revoked: Optional[bool] = None


def get_notification_repository() -> NotificationRepository:
    """Dependency for notification operations."""
    return create_notification_repository()


@router.get("")
async def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repository),
):
    """Get user's notifications (wallet-based for leaderboard notifications)."""
    from .health import stage1_ui_live
    exclude_stage1 = not await stage1_ui_live()
    notifications = await repo.get_wallet_notifications(
        wallet=current_user.wallet,
        limit=limit,
        unread_only=unread_only,
        exclude_stage1=exclude_stage1,
    )
    unread_count = await repo.get_unread_count(current_user.wallet, exclude_stage1=exclude_stage1)
    return {
        "contractVersion": NOTIFICATION_CONTRACT_VERSION,
        "notifications": [serialize_notification(dict(notification)) for notification in notifications],
        "unread_count": unread_count,
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repository),
):
    """Mark a notification as read."""
    success = await repo.mark_read(
        notification_id=str(notification_id), wallet=current_user.wallet
    )
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "read"}


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: NotificationRepository = Depends(get_notification_repository),
):
    """Mark all notifications as read."""
    count = await repo.mark_all_read(current_user.wallet)
    return {"status": "read", "count": count}


@router.get("/preferences")
async def get_notification_preferences(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get user's notification preferences."""
    prefs = await repo.get_notification_preferences(current_user.user_id)
    return prefs or default_notification_preferences()


@router.put("/preferences")
async def update_notification_preferences(
    preferences: NotificationPreferences,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Update user's notification preferences."""
    updated = await repo.upsert_notification_preferences(
        user_id=current_user.user_id,
        preferences=preferences.model_dump(exclude_none=True),
    )
    return updated


async def create_notification(
    repo: DatabaseRepository,
    user_id: str,
    notification_type: str,
    title: str,
    message: Optional[str] = None,
    data: Optional[dict] = None,
    *,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
    delivery_channels: Optional[Sequence[str]] = None,
    dedupe_key: Optional[str] = None,
):
    """
    Create a notification, respecting user preferences when available.
    """
    prefs = await repo.get_notification_preferences(user_id)
    if notification_is_suppressed(notification_type, prefs):
        return None

    try:
        notification = await repo.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            occurred_at=occurred_at,
            delivery_channels=delivery_channels,
            dedupe_key=dedupe_key,
        )
    except TypeError as exc:
        if "unexpected keyword" not in str(exc):
            raise
        notification = await repo.create_notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
        )
    return notification
