"""Canonical link.v1 contracts for share and deep-link targets."""
from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional
from urllib.parse import quote, urlparse

from .target_action_contracts import (
    capabilities_for_target,
    primary_action_for_target,
    target_ref_dict,
)


LINK_CONTRACT_VERSION = "link.v1"
DEFAULT_WEB_ORIGIN = "https://boulderroller.app"
DEFAULT_SCAN_ORIGIN = "https://scan.boulderroller.xyz"


class LinkTargetType(str, Enum):
    rider = "rider"
    ride = "ride"
    climb = "climb"
    record_board = "record_board"
    local_legend = "local_legend"
    proof = "proof"
    scan_tx = "scan_tx"
    scan_account = "scan_account"
    report = "report"


class LinkAccessStatus(str, Enum):
    resolved = "resolved"
    forbidden = "forbidden"
    missing = "missing"


PATH_ALIASES: dict[str, LinkTargetType] = {
    "rider": LinkTargetType.rider,
    "riders": LinkTargetType.rider,
    "ride": LinkTargetType.ride,
    "rides": LinkTargetType.ride,
    "activities": LinkTargetType.ride,
    "climb": LinkTargetType.climb,
    "climbs": LinkTargetType.climb,
    "segment": LinkTargetType.climb,
    "segments": LinkTargetType.climb,
    "proof": LinkTargetType.proof,
    "proofs": LinkTargetType.proof,
    "tx": LinkTargetType.scan_tx,
    "account": LinkTargetType.scan_account,
    "report": LinkTargetType.report,
    "reports": LinkTargetType.report,
}


def web_origin() -> str:
    return os.getenv("BOULDERROLLER_WEB_URL", DEFAULT_WEB_ORIGIN).rstrip("/")


def scan_origin() -> str:
    return os.getenv("BOULDERSCAN_URL", DEFAULT_SCAN_ORIGIN).rstrip("/")


def normalize_link_target_type(value: Any) -> Optional[LinkTargetType]:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"leaderboard", "recordboard", "record_board"}:
        return LinkTargetType.record_board
    if normalized in {"legend", "locallegend", "local_legend"}:
        return LinkTargetType.local_legend
    try:
        return LinkTargetType(normalized)
    except ValueError:
        return None


def parse_link_target(url_or_path: str) -> Optional[tuple[LinkTargetType, str]]:
    parsed = urlparse(url_or_path)
    path = parsed.path if parsed.scheme or parsed.netloc else url_or_path
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return None

    head = parts[0].lower()
    if head == "scan" and len(parts) >= 3:
        if parts[1].lower() == "tx":
            return LinkTargetType.scan_tx, parts[2]
        if parts[1].lower() == "account":
            return LinkTargetType.scan_account, parts[2]

    target_type = PATH_ALIASES.get(head)
    if not target_type or len(parts) < 2:
        return None

    target_id = parts[1]
    if target_type == LinkTargetType.climb and len(parts) >= 3:
        tail = parts[2].lower()
        if tail in {"leaderboard", "record-board", "record_board"}:
            return LinkTargetType.record_board, target_id
        if tail in {"local-legend", "local_legend", "legend"}:
            return LinkTargetType.local_legend, target_id
    return target_type, target_id


def canonical_web_path(target_type: LinkTargetType, target_id: str) -> str:
    encoded_id = quote(str(target_id), safe="")
    if target_type == LinkTargetType.rider:
        return f"/riders/{target_id}"
    if target_type == LinkTargetType.ride:
        return f"/rides/{target_id}"
    if target_type == LinkTargetType.climb:
        return f"/climbs/{target_id}"
    if target_type == LinkTargetType.record_board:
        return f"/climbs/{target_id}/leaderboard"
    if target_type == LinkTargetType.local_legend:
        return f"/climbs/{target_id}/local-legend"
    if target_type == LinkTargetType.proof:
        return f"/notifications?proofId={encoded_id}"
    if target_type == LinkTargetType.scan_tx:
        return f"/notifications?scanTx={encoded_id}"
    if target_type == LinkTargetType.scan_account:
        return f"/notifications?scanAccount={encoded_id}"
    if target_type == LinkTargetType.report:
        return f"/notifications?reportId={encoded_id}"
    raise ValueError(f"Unsupported link target type: {target_type}")


def app_url_for_path(path: str) -> str:
    return f"boulderroller://{path.lstrip('/')}"


def scan_url(target_type: LinkTargetType, target_id: str) -> Optional[str]:
    if target_type == LinkTargetType.scan_tx:
        return f"{scan_origin()}/tx/{target_id}"
    if target_type == LinkTargetType.scan_account:
        return f"{scan_origin()}/account/{target_id}"
    return None


def build_resolved_link(
    *,
    target_type: LinkTargetType,
    target_id: str,
    title: str,
    description: str,
    status: LinkAccessStatus = LinkAccessStatus.resolved,
    can_view: bool = True,
    reason: str = "public",
    protocol_public: bool = False,
    metadata: Optional[dict[str, Any]] = None,
    scan_state: Optional[str] = None,
    scan_targets: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    web_path = canonical_web_path(target_type, target_id)
    canonical_url = f"{web_origin()}{web_path}"
    external_scan_url = scan_url(target_type, target_id)
    share_url = external_scan_url or canonical_url
    has_scan_target = bool(external_scan_url or scan_targets)
    return {
        "contractVersion": LINK_CONTRACT_VERSION,
        "status": status.value,
        "target": target_ref_dict(target_type.value, target_id, source="link.resolve"),
        "primaryAction": primary_action_for_target(target_type.value).value,
        "webPath": web_path,
        "canonicalUrl": canonical_url,
        "appUrl": app_url_for_path(web_path),
        "externalUrl": external_scan_url,
        "title": title,
        "description": description,
        "access": {
            "canView": can_view,
            "reason": reason,
            "protocolPublic": protocol_public,
            "requiresAuth": status == LinkAccessStatus.forbidden,
        },
        "viewerCapabilities": capabilities_for_target(
            target_type.value,
            can_view=can_view,
            authenticated=True,
            can_share=can_view,
            has_scan_target=has_scan_target,
        ),
        "metadata": metadata or {},
        "scanState": scan_state,
        "scanTargets": scan_targets or [],
        "share": {
            "title": title,
            "text": description,
            "url": share_url,
        },
        "openGraph": {
            "title": title,
            "description": description,
            "url": share_url,
            "type": "profile" if target_type == LinkTargetType.rider else "article",
        },
    }


def link_schema() -> dict[str, Any]:
    return {
        "contractVersion": LINK_CONTRACT_VERSION,
        "webOrigin": web_origin(),
        "scanOrigin": scan_origin(),
        "scanContractVersion": "scan.v1",
        "targets": [
            {"type": "rider", "webPathTemplate": "/riders/:identifier", "aliases": ["/rider/:identifier"]},
            {"type": "ride", "webPathTemplate": "/rides/:rideId", "aliases": ["/ride/:rideId", "/activities/:rideId"]},
            {"type": "climb", "webPathTemplate": "/climbs/:climbId", "aliases": ["/climb/:climbId", "/segments/:climbId"]},
            {"type": "record_board", "webPathTemplate": "/climbs/:climbId/leaderboard", "aliases": []},
            {"type": "local_legend", "webPathTemplate": "/climbs/:climbId/local-legend", "aliases": []},
            {"type": "proof", "webPathTemplate": "/notifications?proofId=:proofId", "aliases": ["/proof/:proofId", "/proofs/:proofId"]},
            {"type": "scan_tx", "webPathTemplate": "/notifications?scanTx=:signature", "aliases": ["/tx/:signature", "/scan/tx/:signature"]},
            {"type": "scan_account", "webPathTemplate": "/notifications?scanAccount=:pubkey", "aliases": ["/account/:pubkey", "/scan/account/:pubkey"]},
            {"type": "report", "webPathTemplate": "/notifications?reportId=:reportId", "aliases": ["/reports/:reportId", "/settings/reports/:reportId"]},
        ],
    }
