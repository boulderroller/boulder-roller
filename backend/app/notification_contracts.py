"""Canonical notification.v1 contracts.

The inbox is a product contract, not a table dump. These helpers normalize
legacy social/leaderboard rows into one stable shape that portal and mobile can
render while push/email delivery remains a later transport concern.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Sequence

from pydantic import BaseModel

from .rider_identity_contracts import PublicRiderRef, public_rider_ref_dict
from .target_action_contracts import (
    TargetRef,
    TargetType,
    capabilities_for_target,
    normalize_target_type,
    primary_action_for_target,
    target_ref_dict,
)


NOTIFICATION_CONTRACT_VERSION = "notification.v1"
DEFAULT_DELIVERY_CHANNELS = ["in_app"]
DEFAULT_DELIVERY_STATUS = "in_app_delivered"


class NotificationEventType(str, Enum):
    comment_created = "comment_created"
    follow_created = "follow_created"
    kudos_created = "kudos_created"
    ride_completed = "ride_completed"
    ride_finalized = "ride_finalized"
    ride_failed = "ride_failed"
    leaderboard_entered = "leaderboard_entered"
    leaderboard_bumped = "leaderboard_bumped"
    record_rank_moved = "record_rank_moved"
    rank_changed = "rank_changed"
    kom_achieved = "kom_achieved"
    local_legend_moved = "local_legend_moved"
    achievement_unlocked = "achievement_unlocked"
    payout_received = "payout_received"
    stake_payout = "stake_payout"
    legend_payout = "legend_payout"
    report_resolved = "report_resolved"
    proof_updated = "proof_updated"
    settlement_finalized = "settlement_finalized"
    tier_unlocked = "tier_unlocked"
    login_new_device = "login_new_device"
    session_revoked = "session_revoked"
    strava_revoked = "strava_revoked"
    system = "system"


class NotificationActor(PublicRiderRef):
    pass


class NotificationTarget(TargetRef):
    pass


NOTIFICATION_TYPE_ALIASES: dict[str, NotificationEventType] = {
    "new_follower": NotificationEventType.follow_created,
    "follow": NotificationEventType.follow_created,
    "comment": NotificationEventType.comment_created,
    "kudos": NotificationEventType.kudos_created,
    "like": NotificationEventType.kudos_created,
    "kom_beaten": NotificationEventType.record_rank_moved,
    "rank_moved": NotificationEventType.record_rank_moved,
    "local_legend": NotificationEventType.local_legend_moved,
    "report": NotificationEventType.report_resolved,
    "settlement": NotificationEventType.settlement_finalized,
    "proof": NotificationEventType.proof_updated,
}

EVENT_PREFERENCE_KEYS: dict[NotificationEventType, tuple[str, ...]] = {
    NotificationEventType.comment_created: ("comment_created", "social_activity"),
    NotificationEventType.follow_created: ("follow_created", "new_follower", "social_activity"),
    NotificationEventType.kudos_created: ("kudos_created", "social_activity"),
    NotificationEventType.ride_completed: ("ride_completed", "ride_updates"),
    NotificationEventType.ride_finalized: ("ride_finalized", "ride_completed", "ride_updates"),
    NotificationEventType.ride_failed: ("ride_failed", "ride_updates"),
    NotificationEventType.leaderboard_entered: ("leaderboard_entered", "leaderboard_updates"),
    NotificationEventType.leaderboard_bumped: ("leaderboard_bumped", "leaderboard_updates"),
    NotificationEventType.record_rank_moved: ("record_rank_moved", "rank_changed", "leaderboard_updates"),
    NotificationEventType.rank_changed: ("rank_changed", "leaderboard_updates"),
    NotificationEventType.kom_achieved: ("kom_achieved", "kom_beaten", "leaderboard_updates"),
    NotificationEventType.local_legend_moved: ("local_legend_moved", "leaderboard_updates"),
    NotificationEventType.achievement_unlocked: ("achievement_unlocked", "social_activity"),
    NotificationEventType.payout_received: ("payout_received", "payout_alerts"),
    NotificationEventType.stake_payout: ("stake_payout", "staking_reward", "payout_alerts"),
    NotificationEventType.legend_payout: ("legend_payout", "payout_alerts"),
    NotificationEventType.report_resolved: ("report_resolved", "system_announcements"),
    NotificationEventType.proof_updated: ("proof_updated", "system_announcements"),
    NotificationEventType.settlement_finalized: (
        "settlement_finalized",
        "payout_alerts",
        "system_announcements",
    ),
    NotificationEventType.tier_unlocked: ("tier_unlocked", "achievement_unlocked", "social_activity"),
    NotificationEventType.login_new_device: ("login_new_device", "security_alerts"),
    NotificationEventType.session_revoked: ("session_revoked", "security_alerts"),
    NotificationEventType.strava_revoked: ("strava_revoked", "connected_app_alerts"),
    NotificationEventType.system: ("system_announcements",),
}


def default_notification_preferences() -> dict[str, bool]:
    return {
        "email_enabled": True,
        "push_enabled": True,
        "in_app_enabled": True,
        "new_follower": True,
        "ride_completed": True,
        "achievement_unlocked": True,
        "kom_beaten": True,
        "staking_reward": True,
        "social_activity": True,
        "leaderboard_updates": True,
        "payout_alerts": True,
        "system_announcements": True,
        "security_alerts": True,
        "connected_app_alerts": True,
        "ride_updates": True,
        "follow_created": True,
        "comment_created": True,
        "kudos_created": True,
        "ride_finalized": True,
        "ride_failed": True,
        "leaderboard_entered": True,
        "leaderboard_bumped": True,
        "rank_changed": True,
        "record_rank_moved": True,
        "kom_achieved": True,
        "local_legend_moved": True,
        "payout_received": True,
        "stake_payout": True,
        "legend_payout": True,
        "report_resolved": True,
        "proof_updated": True,
        "settlement_finalized": True,
        "tier_unlocked": True,
        "login_new_device": True,
        "session_revoked": True,
        "strava_revoked": True,
    }


def parse_notification_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def notification_datetime_iso(value: Any) -> str:
    parsed = parse_notification_datetime(value) or datetime.now(timezone.utc)
    return parsed.isoformat()


def optional_notification_datetime_iso(value: Any) -> Optional[str]:
    parsed = parse_notification_datetime(value)
    return parsed.isoformat() if parsed else None


def normalize_notification_event_type(value: Any) -> NotificationEventType:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return NotificationEventType.system
    if normalized in NOTIFICATION_TYPE_ALIASES:
        return NOTIFICATION_TYPE_ALIASES[normalized]
    try:
        return NotificationEventType(normalized)
    except ValueError:
        return NotificationEventType.system


def notification_preference_keys(event_type: Any) -> tuple[str, ...]:
    normalized = normalize_notification_event_type(event_type)
    return EVENT_PREFERENCE_KEYS.get(normalized, (normalized.value,))


def notification_is_suppressed(event_type: Any, preferences: Optional[dict[str, Any]]) -> bool:
    if not preferences:
        return False
    if preferences.get("in_app_enabled") is False:
        return True
    for key in notification_preference_keys(event_type):
        if preferences.get(key) is False:
            return True
    return False


def capture_board_transition(snapshot: dict[str, Any], wallet: str) -> dict[str, Any]:
    """Freeze a recipient's places from the supplied event-time board pair."""
    revision = snapshot.get("revision")
    climb_id = snapshot.get("climbId")
    occurred_at = parse_notification_datetime(snapshot.get("occurredAt"))
    if (
        not isinstance(revision, str) or not revision.strip()
        or not isinstance(climb_id, str) or not climb_id.strip()
        or occurred_at is None
    ):
        raise ValueError("Board snapshot requires revision, climbId and occurredAt")

    def place(key: str) -> Optional[int]:
        entries = snapshot.get(key)
        if not isinstance(entries, list):
            raise ValueError("Board snapshot requires before and after populations")
        seen_wallets: set[str] = set()
        result = None
        for entry in entries:
            rider = entry.get("wallet")
            rank = entry.get("place")
            if (
                not isinstance(rider, str) or not rider
                or type(rank) is not int or rank < 1 or rider in seen_wallets
            ):
                raise ValueError("Invalid board snapshot entry")
            seen_wallets.add(rider)
            if rider == wallet:
                result = rank
        return result

    return {
        "revision": revision,
        "occurredAt": snapshot["occurredAt"],
        "climbId": climb_id,
        "beforePlace": place("before"),
        "afterPlace": place("after"),
    }


def build_notification_insert(
    *,
    user_id: Optional[str] = None,
    wallet: Optional[str] = None,
    notification_type: str,
    title: str,
    message: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    occurred_at: Any = None,
    delivery_status: str = DEFAULT_DELIVERY_STATUS,
    delivery_channels: Optional[Sequence[str]] = None,
    dedupe_key: Optional[str] = None,
    board_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    event_type = normalize_notification_event_type(notification_type)
    payload_metadata = deepcopy(metadata or data or {})
    if event_type == NotificationEventType.leaderboard_bumped and board_snapshot is not None:
        transition = capture_board_transition(board_snapshot, wallet or "")
        payload_metadata["transition"] = transition
        payload_metadata.setdefault("climb_id", transition["climbId"])
        occurred_at = transition["occurredAt"]
    if actor_id:
        payload_metadata.setdefault("actor_id", actor_id)
    if target_type:
        payload_metadata.setdefault("target_type", target_type)
    if target_id:
        payload_metadata.setdefault("target_id", target_id)

    occurred_at_iso = notification_datetime_iso(occurred_at)
    payload: dict[str, Any] = {
        "schema_version": NOTIFICATION_CONTRACT_VERSION,
        "notification_type": event_type.value,
        "event_type": event_type.value,
        "title": title,
        "message": message,
        "data": payload_metadata,
        "metadata": payload_metadata,
        "actor_id": actor_id,
        "target_type": target_type,
        "target_id": str(target_id) if target_id is not None else None,
        "occurred_at": occurred_at_iso,
        "delivery_status": delivery_status,
        "delivery_channels": list(delivery_channels or DEFAULT_DELIVERY_CHANNELS),
    }
    if user_id:
        payload["user_id"] = user_id
    if wallet:
        payload["wallet"] = wallet
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key
    return payload


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = _first(row, "metadata", "data")
    return dict(value) if isinstance(value, dict) else {}


def _metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return value
    return None


_CLIMB_TARGET_TYPES = {
    TargetType.climb,
    TargetType.record_board,
    TargetType.local_legend,
}


def _routeable_climb_target_id(metadata: dict[str, Any], target_id: Any) -> Optional[str]:
    route_id = _metadata_value(metadata, "climb_id", "climbId", "vault_id", "vaultId")
    if route_id is not None:
        return str(route_id)

    signature = _metadata_value(metadata, "vault_signature", "vaultSignature")
    if target_id is not None:
        target_id_text = str(target_id)
        if signature is not None and target_id_text == str(signature):
            return None
        return target_id_text
    return None


def _delivery_channels(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value]
    return list(DEFAULT_DELIVERY_CHANNELS)


def _actor(row: dict[str, Any], metadata: dict[str, Any]) -> Optional[dict[str, Any]]:
    actor = metadata.get("actor")
    if isinstance(actor, dict):
        return NotificationActor(**actor).model_dump(by_alias=True)

    actor_id = (
        _first(row, "actor_id", "actorId")
        or metadata.get("actor_id")
        or metadata.get("actorId")
        or metadata.get("follower_id")
        or metadata.get("followerId")
    )
    if not actor_id:
        return None
    return public_rider_ref_dict({
        "id": str(actor_id),
        "username": metadata.get("actor_username") or metadata.get("actorUsername"),
        "display_name": metadata.get("actor_display_name") or metadata.get("actorDisplayName"),
        "avatar_url": metadata.get("actor_avatar_url") or metadata.get("actorAvatarUrl"),
        "is_public": metadata["actor_is_public"]
        if "actor_is_public" in metadata
        else metadata.get("actorIsPublic"),
    })


def _target(
    row: dict[str, Any],
    metadata: dict[str, Any],
    event_type: NotificationEventType,
) -> Optional[dict[str, Any]]:
    target = metadata.get("target")
    if isinstance(target, dict) and target.get("type"):
        target_metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
        target_id = target.get("id")
        if normalize_target_type(target.get("type")) in _CLIMB_TARGET_TYPES:
            target_id = _routeable_climb_target_id({**metadata, **target_metadata}, target_id)
            if target_id is None:
                return None
        return target_ref_dict(
            target.get("type"),
            target_id,
            label=target.get("label"),
            source=target.get("source") or "notification.metadata",
            metadata=target_metadata or None,
        )

    target_type = _first(row, "target_type", "targetType") or metadata.get("target_type") or metadata.get("targetType")
    target_id = _first(row, "target_id", "targetId") or metadata.get("target_id") or metadata.get("targetId")

    if not target_type:
        if event_type == NotificationEventType.follow_created:
            target_type = "rider"
            target_id = target_id or metadata.get("follower_id") or metadata.get("followerId")
        elif event_type in {NotificationEventType.comment_created, NotificationEventType.kudos_created}:
            target_type = "ride"
            target_id = target_id or metadata.get("ride_id") or metadata.get("rideId")
        elif metadata.get("vault_signature") or metadata.get("vaultSignature"):
            target_type = "climb"
            target_id = _routeable_climb_target_id(metadata, target_id)

    if not target_type:
        return None
    if normalize_target_type(target_type) in _CLIMB_TARGET_TYPES:
        target_id = _routeable_climb_target_id(metadata, target_id)
        if target_id is None:
            return None
    return target_ref_dict(
        target_type,
        target_id,
        source="notification.row",
    )


def _action_url(target: Optional[dict[str, Any]]) -> Optional[str]:
    if not target or not target.get("id"):
        return None
    target_type = target.get("type")
    target_id = target.get("id")
    if target_type == "ride":
        return f"/rides/{target_id}"
    if target_type in {"user", "rider"}:
        return f"/riders/{target_id}"
    if target_type in {"climb", "record_board", "local_legend"}:
        return f"/climbs/{target_id}"
    if target_type == "report":
        return f"/notifications?reportId={target_id}"
    if target_type == "feed_event":
        return f"/notifications?eventId={target_id}"
    if target_type in {"proof", "scan_tx", "scan_account"}:
        return f"/{target_type.replace('_', '/')}/{target_id}"
    return None


def serialize_notification(row: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(row)
    raw_type = _first(row, "event_type", "eventType", "notification_type", "notificationType")
    event_type = normalize_notification_event_type(raw_type)
    legacy_type = _first(row, "notification_type", "notificationType")
    occurred_at = notification_datetime_iso(_first(row, "occurred_at", "occurredAt", "created_at", "createdAt"))
    target = _target(row, metadata, event_type)

    primary_action = primary_action_for_target(target.get("type") if target else None).value
    return {
        "contractVersion": NOTIFICATION_CONTRACT_VERSION,
        "id": str(_first(row, "id") or ""),
        "notificationType": event_type.value,
        "legacyType": str(legacy_type) if legacy_type and str(legacy_type) != event_type.value else None,
        "eventType": event_type.value,
        "title": str(_first(row, "title") or event_type.value.replace("_", " ").title()),
        "message": str(_first(row, "message") or ""),
        "actor": _actor(row, metadata),
        "target": target,
        "primaryAction": primary_action,
        "viewerCapabilities": capabilities_for_target(
            target.get("type") if target else None,
            can_view=True,
            authenticated=True,
            can_report=False,
            can_share=True,
            has_scan_target=primary_action == "open_scan",
        ),
        "metadata": metadata,
        "transition": deepcopy(metadata.get("transition")) if event_type == NotificationEventType.leaderboard_bumped else None,
        "deliveryStatus": str(_first(row, "delivery_status", "deliveryStatus") or DEFAULT_DELIVERY_STATUS),
        "deliveryChannels": _delivery_channels(_first(row, "delivery_channels", "deliveryChannels")),
        "dedupeKey": _first(row, "dedupe_key", "dedupeKey"),
        "vaultSignature": _first(row, "vault_signature", "vaultSignature") or metadata.get("vault_signature") or metadata.get("vaultSignature"),
        "read": bool(_first(row, "read") or False),
        "readAt": optional_notification_datetime_iso(_first(row, "read_at", "readAt")),
        "createdAt": notification_datetime_iso(_first(row, "created_at", "createdAt", "occurred_at", "occurredAt")),
        "occurredAt": occurred_at,
        "actionUrl": _first(row, "action_url", "actionUrl") or metadata.get("action_url") or metadata.get("actionUrl") or _action_url(target),
    }
