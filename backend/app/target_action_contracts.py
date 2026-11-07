"""Canonical public target, action, and viewer capability contracts."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


TARGET_ACTION_CONTRACT_VERSION = "target_action.v1"
VIEWER_CAPABILITIES_CONTRACT_VERSION = "viewer_capabilities.v1"


class TargetType(str, Enum):
    rider = "rider"
    ride = "ride"
    climb = "climb"
    record_board = "record_board"
    local_legend = "local_legend"
    proof = "proof"
    scan_tx = "scan_tx"
    scan_account = "scan_account"
    report = "report"
    comment = "comment"
    ride_media = "ride_media"
    feed_event = "feed_event"


class PrimaryAction(str, Enum):
    open_rider = "open_rider"
    open_ride = "open_ride"
    open_climb = "open_climb"
    open_scan = "open_scan"
    open_report = "open_report"
    open_comment = "open_comment"
    open_feed_event = "open_feed_event"
    unavailable = "unavailable"


TARGET_TYPE_ALIASES: dict[str, TargetType] = {
    "user": TargetType.rider,
    "profile": TargetType.rider,
    "rider": TargetType.rider,
    "ride": TargetType.ride,
    "activity": TargetType.ride,
    "activities": TargetType.ride,
    "vault": TargetType.climb,
    "segment": TargetType.climb,
    "climb": TargetType.climb,
    "leaderboard": TargetType.record_board,
    "recordboard": TargetType.record_board,
    "record_board": TargetType.record_board,
    "legend": TargetType.local_legend,
    "locallegend": TargetType.local_legend,
    "local_legend": TargetType.local_legend,
    "proof": TargetType.proof,
    "scan_tx": TargetType.scan_tx,
    "transaction": TargetType.scan_tx,
    "tx": TargetType.scan_tx,
    "scan_account": TargetType.scan_account,
    "account": TargetType.scan_account,
    "report": TargetType.report,
    "comment": TargetType.comment,
    "ride_media": TargetType.ride_media,
    "ride-media": TargetType.ride_media,
    "photo": TargetType.ride_media,
    "media": TargetType.ride_media,
    "feed_event": TargetType.feed_event,
    "feed": TargetType.feed_event,
    "settlement": TargetType.feed_event,
    "device": TargetType.feed_event,
    "session": TargetType.feed_event,
    "connected_app": TargetType.feed_event,
    "connected-app": TargetType.feed_event,
    "integration": TargetType.feed_event,
}


class TargetRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contract_version: str = Field(default=TARGET_ACTION_CONTRACT_VERSION, alias="contractVersion")
    type: TargetType
    id: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ViewerCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contract_version: str = Field(default=VIEWER_CAPABILITIES_CONTRACT_VERSION, alias="contractVersion")
    can_view: bool = Field(default=True, alias="canView")
    can_follow: bool = Field(default=False, alias="canFollow")
    can_kudos: bool = Field(default=False, alias="canKudos")
    can_comment: bool = Field(default=False, alias="canComment")
    can_share: bool = Field(default=False, alias="canShare")
    can_report: bool = Field(default=False, alias="canReport")
    can_edit: bool = Field(default=False, alias="canEdit")
    can_open_proof: bool = Field(default=False, alias="canOpenProof")
    can_open_scan: bool = Field(default=False, alias="canOpenScan")


def normalize_target_type(value: Any) -> Optional[TargetType]:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return None
    return TARGET_TYPE_ALIASES.get(normalized)


def primary_action_for_target(target_type: Any) -> PrimaryAction:
    normalized = normalize_target_type(target_type)
    if normalized == TargetType.rider:
        return PrimaryAction.open_rider
    if normalized in {TargetType.ride, TargetType.ride_media}:
        return PrimaryAction.open_ride
    if normalized in {TargetType.climb, TargetType.record_board, TargetType.local_legend}:
        return PrimaryAction.open_climb
    if normalized in {TargetType.proof, TargetType.scan_tx, TargetType.scan_account}:
        return PrimaryAction.open_scan
    if normalized == TargetType.report:
        return PrimaryAction.open_report
    if normalized == TargetType.comment:
        return PrimaryAction.open_comment
    if normalized == TargetType.feed_event:
        return PrimaryAction.open_feed_event
    return PrimaryAction.unavailable


def target_ref(
    target_type: Any,
    target_id: Any = None,
    *,
    label: Optional[str] = None,
    source: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[TargetRef]:
    normalized = normalize_target_type(target_type)
    if not normalized:
        return None
    return TargetRef(
        type=normalized,
        id=str(target_id) if target_id is not None else None,
        label=label,
        source=source,
        metadata=metadata or {},
    )


def target_ref_dict(
    target_type: Any,
    target_id: Any = None,
    *,
    label: Optional[str] = None,
    source: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    ref = target_ref(target_type, target_id, label=label, source=source, metadata=metadata)
    return ref.model_dump(mode="json", by_alias=True) if ref else None


def viewer_capabilities(
    *,
    can_view: bool = True,
    can_follow: bool = False,
    can_kudos: bool = False,
    can_comment: bool = False,
    can_share: bool = False,
    can_report: bool = False,
    can_edit: bool = False,
    can_open_proof: bool = False,
    can_open_scan: bool = False,
) -> ViewerCapabilities:
    return ViewerCapabilities(
        can_view=can_view,
        can_follow=can_follow and can_view,
        can_kudos=can_kudos and can_view,
        can_comment=can_comment and can_view,
        can_share=can_share and can_view,
        can_report=can_report and can_view,
        can_edit=can_edit and can_view,
        can_open_proof=can_open_proof and can_view,
        can_open_scan=can_open_scan and can_view,
    )


def viewer_capabilities_dict(**kwargs: Any) -> dict[str, Any]:
    return viewer_capabilities(**kwargs).model_dump(mode="json", by_alias=True)


def capabilities_for_target(
    target_type: Any,
    *,
    can_view: bool = True,
    authenticated: bool = False,
    is_owner: bool = False,
    comments_enabled: bool = True,
    can_follow: bool = False,
    can_report: bool = False,
    can_share: bool = True,
    has_scan_target: bool = False,
) -> dict[str, Any]:
    normalized = normalize_target_type(target_type)
    return viewer_capabilities_dict(
        can_view=can_view,
        can_follow=bool(can_follow and authenticated and not is_owner and normalized == TargetType.rider),
        can_kudos=bool(authenticated and not is_owner and normalized == TargetType.ride),
        can_comment=bool(authenticated and comments_enabled and normalized == TargetType.ride),
        can_share=bool(can_share and normalized in {
            TargetType.rider,
            TargetType.ride,
            TargetType.climb,
            TargetType.record_board,
            TargetType.local_legend,
            TargetType.proof,
            TargetType.scan_tx,
            TargetType.scan_account,
        }),
        can_report=bool(can_report and authenticated and not is_owner and normalized in {
            TargetType.rider,
            TargetType.ride,
            TargetType.comment,
            TargetType.ride_media,
        }),
        can_edit=bool(is_owner and normalized in {TargetType.rider, TargetType.ride, TargetType.comment, TargetType.ride_media}),
        can_open_proof=bool(normalized in {TargetType.ride, TargetType.ride_media, TargetType.proof}),
        can_open_scan=bool(has_scan_target or normalized in {TargetType.proof, TargetType.scan_tx, TargetType.scan_account}),
    )
