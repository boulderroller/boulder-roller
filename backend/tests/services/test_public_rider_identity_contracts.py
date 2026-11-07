from __future__ import annotations

from app.feed_contracts import build_activity_feed_event, build_ride_feed_event
from app.notification_contracts import serialize_notification
from app.rider_identity_contracts import public_rider_ref_dict, rider_route_identifier


def test_public_rider_ref_excludes_wallet_identity() -> None:
    rider = public_rider_ref_dict({
        "id": "user-1",
        "wallet": "WalletAAAA111111111111111111111111111111",
        "username": "@tim",
        "display_name": "Tim",
        "avatar_url": "https://example.test/tim.png",
        "is_public": True,
    })

    assert rider == {
        "contractVersion": "public_rider_ref.v1",
        "id": "user-1",
        "username": "tim",
        "displayName": "Tim",
        "avatarUrl": "https://example.test/tim.png",
        "isPublic": True,
        "viewerRelationship": "none",
    }
    assert "wallet" not in rider


def test_private_public_rider_ref_redacts_display_and_avatar() -> None:
    rider = public_rider_ref_dict(
        {
            "id": "user-1",
            "username": "tim",
            "display_name": "Tim",
            "avatar_url": "https://example.test/signed-avatar",
        },
        is_public=False,
    )

    assert rider["username"] == "tim"
    assert rider["displayName"] is None
    assert rider["avatarUrl"] is None
    assert rider["isPublic"] is False


def test_public_rider_route_identifier_prefers_username_then_user_id() -> None:
    assert rider_route_identifier({"id": "user-1", "wallet": "wallet-1", "username": "tim"}) == "tim"
    assert rider_route_identifier({"id": "user-1", "wallet": "wallet-1"}) == "user-1"


def test_feed_actors_use_public_rider_ref() -> None:
    event = build_ride_feed_event(
        {
            "id": "ride-1",
            "user_id": "user-1",
            "processing_status": "completed",
            "started_at": "2026-05-03T12:00:00+00:00",
        },
        {
            "id": "user-1",
            "wallet": "WalletAAAA111111111111111111111111111111",
            "username": "tim",
        },
        None,
        {"visibility": "public", "canView": True, "redactGps": True},
    )

    assert event is not None
    assert event["actor"]["contractVersion"] == "public_rider_ref.v1"
    assert event["actor"]["id"] == "user-1"
    assert event["actor"]["username"] == "tim"
    assert "wallet" not in event["actor"]
    assert event["user"] == event["actor"]


def test_legacy_activity_actors_use_public_rider_ref() -> None:
    event = build_activity_feed_event(
        {
            "id": "activity-1",
            "user_id": "user-1",
            "activity_type": "follow",
            "target_type": "user",
            "target_id": "user-2",
            "created_at": "2026-05-03T12:00:00+00:00",
        },
        {"id": "user-1", "wallet": "wallet-1", "display_name": "Tim"},
    )

    assert event["actor"]["displayName"] == "Tim"
    assert "wallet" not in event["actor"]


def test_notification_actor_uses_public_rider_ref() -> None:
    event = serialize_notification({
        "id": "notification-1",
        "notification_type": "follow_created",
        "actor_id": "user-1",
        "target_type": "user",
        "target_id": "user-1",
        "metadata": {
            "actor_username": "tim",
            "actor_wallet": "WalletAAAA111111111111111111111111111111",
        },
        "created_at": "2026-05-03T12:00:00+00:00",
    })

    assert event["actor"]["id"] == "user-1"
    assert event["actor"]["username"] == "tim"
    assert "wallet" not in event["actor"]
