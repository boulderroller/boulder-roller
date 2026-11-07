"""
Notification Service

Centralized notification creation for different events:
- leaderboard_entered / kom_achieved (handled by NotificationRepository)
- login_from_new_device
- tier_unlocked
- session_revoked

This service provides higher-level methods that create notifications
with appropriate titles, messages, and metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..repositories import NotificationRepository, create_notification_repository

logger = logging.getLogger(__name__)


# =============================================================================
# NOTIFICATION TYPES
# =============================================================================

class NotificationType:
    """Notification type constants."""
    # Leaderboard notifications (handled by NotificationRepository)
    LEADERBOARD_ENTERED = "leaderboard_entered"
    KOM_ACHIEVED = "kom_achieved"
    LEADERBOARD_BUMPED = "leaderboard_bumped"
    RANK_CHANGED = "rank_changed"
    PAYOUT_RECEIVED = "payout_received"
    STAKE_PAYOUT = "stake_payout"
    LEGEND_PAYOUT = "legend_payout"

    # Security notifications
    LOGIN_NEW_DEVICE = "login_new_device"
    SESSION_REVOKED = "session_revoked"

    # Progression notifications
    TIER_UNLOCKED = "tier_unlocked"

    # Ride notifications
    RIDE_COMPLETED = "ride_completed"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"


# =============================================================================
# NOTIFICATION SERVICE
# =============================================================================

class NotificationService:
    """
    Service for creating notifications with appropriate content.

    This service wraps the NotificationRepository and provides
    higher-level methods for specific notification scenarios.
    """

    def __init__(self, notification_repo: Optional[NotificationRepository] = None):
        self.notification_repo = notification_repo or create_notification_repository()

    # =========================================================================
    # SECURITY NOTIFICATIONS
    # =========================================================================

    async def notify_login_from_new_device(
        self,
        wallet: str,
        device_id: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        location: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a notification when user logs in from a new device.

        Args:
            wallet: User's wallet address
            device_id: Unique device identifier
            user_agent: Browser/app user agent string
            ip_address: Login IP address (optional)
            location: Geo-location from IP (optional)

        Returns:
            Notification UUID or None if creation failed
        """
        # Parse user agent for friendly device info
        device_info = _parse_user_agent(user_agent)
        login_time = datetime.now(timezone.utc).isoformat()

        title = "New device login"
        message = f"Your account was accessed from a new device"
        if device_info:
            message = f"Your account was accessed from {device_info}"

        metadata = {
            "device_id": device_id,
            "device_info": device_info,
            "user_agent": user_agent,
            "login_time": login_time,
        }
        if ip_address:
            metadata["ip_address"] = ip_address
        if location:
            metadata["location"] = location
            message += f" in {location}"

        try:
            notification_id = await self.notification_repo.create_event_notification(
                wallet=wallet,
                notification_type=NotificationType.LOGIN_NEW_DEVICE,
                title=title,
                message=message,
                metadata=metadata,
                target_type="device",
                target_id=device_id,
            )
            if notification_id:
                logger.info(
                    f"[NotificationService] Created login_new_device notification "
                    f"for [redacted]... device={device_id[:8]}..."
                )
            return notification_id
        except Exception as e:
            logger.error(f"[NotificationService] Failed to create login notification: {e}")
            return None

    async def notify_session_revoked(
        self,
        wallet: str,
        session_id: str,
        reason: str,
        revoked_by_device: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a notification when a session is revoked.

        Args:
            wallet: User's wallet address
            session_id: ID of the revoked session
            reason: Revocation reason:
                    "logged_out_other_device", "password_changed",
                    "admin_action", "session_expired"
            revoked_by_device: Device ID that initiated revocation (if applicable)

        Returns:
            Notification UUID or None if creation failed
        """
        reason_messages = {
            "logged_out_other_device": "You were logged out from another device",
            "password_changed": "You were logged out due to a security update",
            "admin_action": "Your session was terminated by an administrator",
            "session_expired": "Your session has expired",
        }

        title = "Session ended"
        message = reason_messages.get(reason, "Your session was terminated")

        metadata = {
            "session_id": session_id,
            "reason": reason,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }
        if revoked_by_device:
            metadata["revoked_by_device"] = revoked_by_device

        try:
            notification_id = await self.notification_repo.create_event_notification(
                wallet=wallet,
                notification_type=NotificationType.SESSION_REVOKED,
                title=title,
                message=message,
                metadata=metadata,
                target_type="session",
                target_id=session_id,
            )
            if notification_id:
                logger.info(
                    f"[NotificationService] Created session_revoked notification "
                    f"for [redacted]... reason={reason}"
                )
            return notification_id
        except Exception as e:
            logger.error(f"[NotificationService] Failed to create session revoked notification: {e}")
            return None

    # =========================================================================
    # PROGRESSION NOTIFICATIONS
    # =========================================================================

    async def notify_tier_unlocked(
        self,
        wallet: str,
        new_tier: str,
        vaults_unlocked: int,
        previous_tier: Optional[str] = None,
        lifetime_points: Optional[float] = None,
    ) -> Optional[str]:
        """
        Create a notification when user crosses a tier threshold.

        Args:
            wallet: User's wallet address
            new_tier: Name of the new tier (e.g., "Bronze", "Silver", "Gold")
            vaults_unlocked: Number of vaults now unlocked
            previous_tier: Previous tier name (optional)
            lifetime_points: Current lifetime points (optional)

        Returns:
            Notification UUID or None if creation failed
        """
        title = f"{new_tier} tier unlocked!"
        if vaults_unlocked > 0:
            message = (
                f"Congratulations! You've reached {new_tier} tier. "
                "Vault creation is now unlocked and your vault privileges have improved."
            )
        else:
            message = f"Congratulations! You've reached {new_tier} tier."

        metadata = {
            "new_tier": new_tier,
            "vaults_unlocked": vaults_unlocked,
            "unlocked_at": datetime.now(timezone.utc).isoformat(),
        }
        if previous_tier:
            metadata["previous_tier"] = previous_tier
        if lifetime_points is not None:
            metadata["lifetime_points"] = lifetime_points

        try:
            notification_id = await self.notification_repo.create_event_notification(
                wallet=wallet,
                notification_type=NotificationType.TIER_UNLOCKED,
                title=title,
                message=message,
                metadata=metadata,
                target_type="profile",
                target_id=wallet,
            )
            if notification_id:
                logger.info(
                    f"[NotificationService] Created tier_unlocked notification "
                    f"for [redacted]... tier={new_tier}"
                )
            return notification_id
        except Exception as e:
            logger.error(f"[NotificationService] Failed to create tier notification: {e}")
            return None



# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _parse_user_agent(user_agent: Optional[str]) -> str:
    """
    Parse user agent string into a human-readable device description.

    Returns something like "Chrome on Windows" or "Safari on iPhone".
    """
    if not user_agent:
        return "Unknown device"

    ua_lower = user_agent.lower()

    # Detect OS
    if "iphone" in ua_lower:
        os_name = "iPhone"
    elif "ipad" in ua_lower:
        os_name = "iPad"
    elif "android" in ua_lower:
        os_name = "Android"
    elif "mac" in ua_lower:
        os_name = "Mac"
    elif "windows" in ua_lower:
        os_name = "Windows"
    elif "linux" in ua_lower:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"

    # Detect browser
    if "chrome" in ua_lower and "edg" not in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "Safari"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    elif "brave" in ua_lower:
        browser = "Brave"
    else:
        browser = "Browser"

    return f"{browser} on {os_name}"



# =============================================================================
# FACTORY
# =============================================================================

def create_notification_service() -> NotificationService:
    """Create a NotificationService instance."""
    return NotificationService()
