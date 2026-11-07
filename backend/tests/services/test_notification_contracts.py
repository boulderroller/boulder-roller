from __future__ import annotations

from app.notification_contracts import (
    NOTIFICATION_CONTRACT_VERSION,
    build_notification_insert,
    default_notification_preferences,
    notification_is_suppressed,
    notification_preference_keys,
    normalize_notification_event_type,
    serialize_notification,
)


def test_notification_type_aliases_normalize_to_product_events() -> None:
    assert normalize_notification_event_type("comment").value == "comment_created"
    assert normalize_notification_event_type("new_follower").value == "follow_created"
    assert normalize_notification_event_type("kudos").value == "kudos_created"
    assert normalize_notification_event_type("rank_moved").value == "record_rank_moved"


def test_notification_vocabulary_covers_durable_product_events() -> None:
    expected = {
        "comment_created",
        "follow_created",
        "ride_finalized",
        "ride_failed",
        "record_rank_moved",
        "local_legend_moved",
        "report_resolved",
        "proof_updated",
        "settlement_finalized",
    }

    assert {
        normalize_notification_event_type(event_type).value
        for event_type in expected
    } == expected


def test_build_notification_insert_canonicalizes_legacy_social_type() -> None:
    payload = build_notification_insert(
        user_id="user-1",
        wallet="wallet-1",
        notification_type="new_follower",
        title="New follower",
        message="alice followed you",
        data={"follower_id": "alice-id"},
        actor_id="alice-id",
        target_type="user",
        target_id="alice-id",
        dedupe_key="follow:user-1:alice-id",
    )

    assert payload["schema_version"] == NOTIFICATION_CONTRACT_VERSION
    assert payload["notification_type"] == "follow_created"
    assert payload["event_type"] == "follow_created"
    assert payload["actor_id"] == "alice-id"
    assert payload["target_type"] == "user"
    assert payload["target_id"] == "alice-id"
    assert payload["delivery_status"] == "in_app_delivered"
    assert payload["delivery_channels"] == ["in_app"]
    assert payload["metadata"]["follower_id"] == "alice-id"


def test_serialize_notification_exposes_inbox_contract() -> None:
    event = serialize_notification({
        "id": "notification-1",
        "notification_type": "comment",
        "title": "New comment",
        "message": "Nice ride",
        "data": {"ride_id": "ride-1", "comment_id": "comment-1"},
        "actor_id": "user-2",
        "target_type": "ride",
        "target_id": "ride-1",
        "read": False,
        "created_at": "2026-04-30T12:00:00+00:00",
    })

    assert event["contractVersion"] == NOTIFICATION_CONTRACT_VERSION
    assert event["notificationType"] == "comment_created"
    assert event["legacyType"] == "comment"
    assert event["eventType"] == "comment_created"
    assert event["actor"] == {
        "contractVersion": "public_rider_ref.v1",
        "id": "user-2",
        "username": None,
        "displayName": None,
        "avatarUrl": None,
        "isPublic": None,
        "viewerRelationship": "none",
    }
    assert event["target"]["contractVersion"] == "target_action.v1"
    assert event["target"]["type"] == "ride"
    assert event["target"]["id"] == "ride-1"
    assert event["primaryAction"] == "open_ride"
    assert event["viewerCapabilities"]["canShare"] is True
    assert event["actionUrl"] == "/rides/ride-1"
    assert event["deliveryStatus"] == "in_app_delivered"
    assert event["deliveryChannels"] == ["in_app"]


def test_climb_notification_targets_prefer_routeable_vault_ids() -> None:
    signature = "a" * 64
    event = serialize_notification({
        "id": "notification-1",
        "notification_type": "rank_moved",
        "title": "Record Board updated",
        "target_type": "record_board",
        "target_id": signature,
        "metadata": {
            "vault_id": 7,
            "vault_signature": signature,
        },
        "created_at": "2026-04-30T12:00:00+00:00",
    })

    assert event["target"]["type"] == "record_board"
    assert event["target"]["id"] == "7"
    assert event["primaryAction"] == "open_climb"
    assert event["actionUrl"] == "/climbs/7"


def test_climb_notification_drops_vault_signature_only_dead_links() -> None:
    signature = "a" * 64
    event = serialize_notification({
        "id": "notification-1",
        "notification_type": "rank_moved",
        "title": "Record Board updated",
        "target_type": "record_board",
        "target_id": signature,
        "metadata": {
            "vault_signature": signature,
        },
        "created_at": "2026-04-30T12:00:00+00:00",
    })

    assert event["target"] is None
    assert event["primaryAction"] == "unavailable"
    assert event["actionUrl"] is None


def test_system_notification_targets_remain_actionable_in_inbox() -> None:
    event = serialize_notification({
        "id": "notification-1",
        "notification_type": "settlement_finalized",
        "title": "Settlement finalized",
        "target_type": "settlement",
        "target_id": "7:116",
        "created_at": "2026-04-30T12:00:00+00:00",
    })

    assert event["target"]["type"] == "feed_event"
    assert event["target"]["id"] == "7:116"
    assert event["primaryAction"] == "open_feed_event"
    assert event["actionUrl"] == "/notifications?eventId=7:116"


def test_notification_preferences_suppress_group_and_granular_events() -> None:
    assert notification_preference_keys("follow_created") == (
        "follow_created",
        "new_follower",
        "social_activity",
    )
    assert notification_is_suppressed("follow_created", {"social_activity": False})
    assert notification_is_suppressed("comment_created", {"comment_created": False})
    assert notification_is_suppressed("ride_completed", {"in_app_enabled": False})
    assert not notification_is_suppressed("comment_created", default_notification_preferences())
