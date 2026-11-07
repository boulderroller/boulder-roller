from __future__ import annotations

from app.feed_contracts import build_activity_feed_event, build_ride_feed_event
from app.link_contracts import LinkTargetType, build_resolved_link, parse_link_target
from app.moderation_contracts import serialize_social_report
from app.notification_contracts import serialize_notification
from app.target_action_contracts import (
    capabilities_for_target,
    normalize_target_type,
    primary_action_for_target,
    target_ref_dict,
)


def test_target_refs_normalize_legacy_names() -> None:
    assert normalize_target_type("user").value == "rider"
    assert normalize_target_type("local-legend").value == "local_legend"
    assert normalize_target_type("settlement").value == "feed_event"
    assert normalize_target_type("connected-app").value == "feed_event"
    assert target_ref_dict("user", "user-1") == {
        "contractVersion": "target_action.v1",
        "type": "rider",
        "id": "user-1",
        "label": None,
        "source": None,
        "metadata": {},
    }
    assert primary_action_for_target("scan_tx").value == "open_scan"
    assert primary_action_for_target("session").value == "open_feed_event"


def test_viewer_capabilities_are_truthful_when_view_is_forbidden() -> None:
    capabilities = capabilities_for_target(
        "ride",
        can_view=False,
        authenticated=True,
        can_report=True,
        can_share=True,
        has_scan_target=True,
    )

    assert capabilities["canView"] is False
    assert capabilities["canKudos"] is False
    assert capabilities["canShare"] is False
    assert capabilities["canReport"] is False
    assert capabilities["canOpenScan"] is False


def test_feed_notification_link_and_report_emit_target_action_capabilities() -> None:
    ride_event = build_ride_feed_event(
        {
            "id": "ride-1",
            "user_id": "user-1",
            "processing_status": "completed",
            "started_at": "2026-05-03T12:00:00+00:00",
            "comments_enabled": True,
        },
        {"id": "user-1", "username": "tim"},
        {"kudosCount": 0, "commentCount": 0},
        {"visibility": "public", "canView": True, "isOwner": False},
    )
    activity_event = build_activity_feed_event(
        {
            "id": "activity-1",
            "activity_type": "follow",
            "target_type": "user",
            "target_id": "user-2",
            "created_at": "2026-05-03T12:00:00+00:00",
        },
        {"id": "user-1", "username": "tim"},
    )
    notification = serialize_notification({
        "id": "notification-1",
        "notification_type": "report_resolved",
        "target_type": "report",
        "target_id": "report-1",
        "metadata": {},
        "created_at": "2026-05-03T12:00:00+00:00",
    })
    link = build_resolved_link(
        target_type=LinkTargetType.scan_tx,
        target_id="tx-1",
        title="Transaction",
        description="Transaction on BoulderScan.",
        scan_state="recorded",
        scan_targets=[],
    )
    report = serialize_social_report({
        "id": "report-1",
        "targetType": "user",
        "targetId": "user-2",
        "status": "open",
    })

    assert ride_event is not None
    assert ride_event["target"]["type"] == "ride"
    assert ride_event["primaryAction"] == "open_ride"
    assert ride_event["viewerCapabilities"]["canComment"] is True
    assert activity_event["target"]["type"] == "rider"
    assert activity_event["primaryAction"] == "open_rider"
    assert notification["target"]["type"] == "report"
    assert notification["primaryAction"] == "open_report"
    assert link["target"]["type"] == "scan_tx"
    assert link["primaryAction"] == "open_scan"
    assert link["viewerCapabilities"]["canOpenScan"] is True
    assert report["target"]["type"] == "rider"
    assert report["primaryAction"] == "open_rider"


def test_link_contract_accepts_report_targets() -> None:
    assert parse_link_target("/reports/report-1") == (LinkTargetType.report, "report-1")
