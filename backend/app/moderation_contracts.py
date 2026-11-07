"""Canonical moderation.v1 report and action contracts."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from .target_action_contracts import (
    capabilities_for_target,
    primary_action_for_target,
    target_ref_dict,
)


MODERATION_CONTRACT_VERSION = "moderation.v1"


class ReportStatus(str, Enum):
    open = "open"
    reviewing = "reviewing"
    resolved = "resolved"
    dismissed = "dismissed"


class ModerationActionType(str, Enum):
    review_started = "review_started"
    leave_visible = "leave_visible"
    hide = "hide"
    remove = "remove"
    unsupported = "unsupported"


ALLOWED_REPORT_STATUSES = {status.value for status in ReportStatus}
ALLOWED_RESOLUTION_ACTIONS = {action.value for action in ModerationActionType}


def normalize_resolution_action(value: Optional[str], status: str) -> ModerationActionType:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in ALLOWED_RESOLUTION_ACTIONS:
        return ModerationActionType(normalized)
    if status == ReportStatus.reviewing.value:
        return ModerationActionType.review_started
    if status in {ReportStatus.resolved.value, ReportStatus.dismissed.value}:
        return ModerationActionType.leave_visible
    return ModerationActionType.unsupported


def action_application_status(action: ModerationActionType) -> str:
    if action == ModerationActionType.unsupported:
        return "unsupported"
    return "applied"


def reporter_outcome_for(status: str, action: ModerationActionType) -> Optional[str]:
    if status == ReportStatus.resolved.value:
        if action == ModerationActionType.hide:
            return "hidden"
        if action == ModerationActionType.remove:
            return "removed"
        return "resolved"
    if status == ReportStatus.dismissed.value:
        return "dismissed"
    if status == ReportStatus.reviewing.value:
        return "reviewing"
    return None


def reporter_message_for(status: str, action: ModerationActionType) -> Optional[str]:
    if status == ReportStatus.reviewing.value:
        return "Your report is being reviewed."
    if status == ReportStatus.dismissed.value:
        return "Your report was reviewed and dismissed."
    if status == ReportStatus.resolved.value:
        if action in {ModerationActionType.hide, ModerationActionType.remove}:
            return "Your report was reviewed and action was taken."
        return "Your report was reviewed and resolved."
    return None


def normalize_action_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "reportId": row.get("report_id") or row.get("reportId"),
        "actorId": row.get("actor_id") or row.get("actorId"),
        "actionType": row.get("action_type") or row.get("actionType"),
        "actionStatus": row.get("action_status") or row.get("actionStatus"),
        "targetType": row.get("target_type") or row.get("targetType"),
        "targetId": row.get("target_id") or row.get("targetId"),
        "note": row.get("note"),
        "metadata": row.get("metadata") or {},
        "createdAt": row.get("created_at") or row.get("createdAt"),
    }


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _metadata_first(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value is not None:
            return value
    return None


def public_report_target_type(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return "rider" if normalized == "user" else normalized


def serialize_social_report(row: dict[str, Any]) -> dict[str, Any]:
    target_type = public_report_target_type(_first(row, "targetType", "target_type"))
    target_id = _first(row, "targetId", "target_id")
    moderation_metadata = _first(row, "moderationMetadata", "moderation_metadata")
    if not isinstance(moderation_metadata, dict):
        moderation_metadata = {}
    target_metadata = {
        "reportId": _first(row, "id"),
        "status": _first(row, "status"),
    }
    if target_type == "ride_media":
        ride_id = _metadata_first(moderation_metadata, "rideId", "ride_id")
        media_id = _metadata_first(moderation_metadata, "mediaId", "media_id") or target_id
        if ride_id:
            target_metadata["rideId"] = ride_id
        if media_id:
            target_metadata["mediaId"] = media_id
    report = dict(row)
    report["contractVersion"] = MODERATION_CONTRACT_VERSION
    report["target"] = target_ref_dict(
        target_type,
        target_id,
        source="moderation.report",
        metadata=target_metadata,
    )
    report["primaryAction"] = primary_action_for_target(target_type).value
    report["viewerCapabilities"] = capabilities_for_target(
        target_type,
        can_view=True,
        authenticated=True,
        can_report=False,
        can_share=False,
    )
    return report
