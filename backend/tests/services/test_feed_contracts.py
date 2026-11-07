from __future__ import annotations

from math import cos, pi, sin
from types import SimpleNamespace

import pytest

from app.feed_contracts import (
    MAX_ROUTE_PREVIEW_POINTS,
    ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_CAP_M,
    build_activity_feed_event,
    build_route_preview,
    build_ride_feed_event,
    feed_cursor,
    infer_activity_event_type,
    ride_event_type,
)
from app.routes.feed import _route_preview_points_for_feed
from app.services.ride_privacy import RidePrivacyPolicy, project_route_points


def test_ride_feed_event_exposes_canonical_shape() -> None:
    event = build_ride_feed_event(
        {
            "id": "ride-1",
            "user_id": "user-1",
            "file_name": "Alpine Loop.fit",
            "processing_status": "completed",
            "started_at": "2026-04-30T12:00:00+00:00",
            "distance_m": 42000,
            "elevation_gain_m": 1200,
            "duration_sec": 7200,
            "dung_minted": 88,
            "cal_earned": 12,
            "visibility": "followers",
            "_route_preview_points": [
                {"latitude": 39.95, "longitude": -75.17},
                {"latitude": 39.96, "longitude": -75.16},
                {"latitude": 39.97, "longitude": -75.15},
            ],
            "location": "Philadelphia, PA",
        },
        {"id": "user-1", "username": "alice", "display_name": "Alice"},
        {"kudosCount": 3, "commentCount": 1, "viewerHasKudos": True},
        {
            "visibility": "followers",
            "canView": True,
            "isOwner": False,
            "isFollower": True,
            "redactGps": True,
            "protocolPublic": False,
            "protocolPublicFields": [],
            "reason": "follower",
        },
    )

    assert event is not None
    assert event["contractVersion"] == "feed.v1"
    assert event["eventType"] == "ride_completed"
    assert event["actor"]["username"] == "alice"
    assert event["target"]["contractVersion"] == "target_action.v1"
    assert event["target"]["type"] == "ride"
    assert event["target"]["id"] == "ride-1"
    assert event["primaryAction"] == "open_ride"
    assert event["viewerCapabilities"]["canComment"] is True
    assert "calEarned" not in event["metadata"]
    assert "dungEarned" not in event["metadata"]
    assert event["metadata"]["privacy"]["reason"] == "follower"
    assert event["metadata"]["routePreview"]["contractVersion"] == "route_preview.v1"
    assert event["metadata"]["routePreview"]["placeLabel"] == "Philadelphia, PA"
    assert event["metadata"]["routePreview"]["pointCount"] == 3
    assert event["metadata"]["routePreview"]["points"][0] == {"x": 0.0, "y": 1.0}


def test_ride_feed_event_keeps_exact_economy_for_owner() -> None:
    event = build_ride_feed_event(
        {
            "id": "ride-owner",
            "user_id": "user-1",
            "file_name": "Owner Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-30T12:00:00+00:00",
            "cal_earned": 12,
            "dung_minted": 88,
            "visibility": "public",
        },
        {"id": "user-1", "username": "alice", "display_name": "Alice"},
        None,
        {
            "visibility": "public",
            "canView": True,
            "isOwner": True,
            "isFollower": False,
            "redactGps": False,
            "protocolPublic": False,
            "protocolPublicFields": [],
            "reason": "owner",
        },
    )

    assert event is not None
    assert event["metadata"]["calEarned"] == 12
    assert event["metadata"]["dungEarned"] == 88


@pytest.mark.parametrize("persisted_cal", [0, 222])
def test_ride_feed_event_suppresses_cal_for_threshold_provisional_hold_parent(
    persisted_cal: int,
) -> None:
    event = build_ride_feed_event(
        {
            "id": "ride-held",
            "user_id": "user-1",
            "file_name": "Held Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-30T12:00:00+00:00",
            "cal_earned": persisted_cal,
            "reward_policy": "threshold_provisional_hold_v1",
            "visibility": "public",
        },
        {"id": "user-1", "username": "alice", "display_name": "Alice"},
        None,
        {
            "visibility": "public",
            "canView": True,
            "isOwner": False,
            "isFollower": False,
            "redactGps": True,
            "protocolPublic": False,
            "protocolPublicFields": [],
            "reason": "public",
        },
    )

    assert event is not None
    assert "calEarned" not in event["metadata"]
    assert "dungEarned" not in event["metadata"]


def test_ride_feed_event_excludes_database_noise_statuses() -> None:
    assert ride_event_type({"processing_status": "pending"}) is None
    assert ride_event_type({"processing_status": "uploading"}) is None
    assert ride_event_type({"processing_status": "failed"}) is None
    assert ride_event_type({"processing_status": "under_review"}).value == "ride_under_review"


def test_route_preview_reports_redacted_gps_without_inventing_route() -> None:
    preview = build_route_preview(
        [
            {"latitude": None, "longitude": None, "redacted": True},
            {"latitude": None, "longitude": None, "redacted": True},
        ],
        source="server_gps",
        place_label="Private zone",
        privacy={"redactGps": True},
    )

    assert preview is not None
    assert preview["points"] == []
    assert preview["fallbackReason"] == "privacy_redacted"
    assert preview["privacy"]["redactedGps"] is True


def test_route_preview_keeps_visible_runs_separate_across_a_privacy_zone() -> None:
    preview = build_route_preview(
        [
            {"latitude": 39.9500, "longitude": -75.1700},
            {"latitude": 39.9510, "longitude": -75.1690},
            {"latitude": None, "longitude": None, "redacted": True},
            {"latitude": None, "longitude": None, "redacted": True},
            {"latitude": 39.9540, "longitude": -75.1660},
            {"latitude": 39.9550, "longitude": -75.1650},
        ],
        source="server_gps",
        place_label="Philadelphia",
        privacy={"redactGps": True},
    )

    assert preview is not None
    assert preview["points"] == []
    assert len(preview["segments"]) == 2
    assert [len(segment) for segment in preview["segments"]] == [2, 2]
    assert preview["segments"][0][-1] != preview["segments"][1][0]
    assert preview["fallbackReason"] is None


def test_route_preview_simplification_never_draws_an_edge_through_a_privacy_zone() -> None:
    """The zone edge law survives simplification (bead boulderroller-v2-zudgp):
    simplification may connect non-adjacent recorded points, but every emitted
    vertex is an original recorded point outside the zone, runs are never
    bridged, and — with the viewer's zones passed — no drawn edge intersects a
    zone (the same `_segment_intersects_zone` law the projection enforces)."""
    meters_per_degree = 111_195.0
    route_radius_m = 200.1
    route_radius_degrees = route_radius_m / meters_per_degree
    zone = {"latitude": 0.0, "longitude": 0.0, "radius_m": 200}
    points = [
        {
            "latitude": route_radius_degrees * sin((2 * pi * index) / 1_000),
            "longitude": route_radius_degrees * cos((2 * pi * index) / 1_000),
        }
        for index in range(1_001)
    ]
    # A distant outward tail widens the preview bounds. The serializer must not
    # quantize the otherwise-safe circle edges back through the private zone.
    points.append({"latitude": 0.0, "longitude": 0.1})
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    projected = project_route_points(points, policy, privacy_zones=[zone])
    assert not any(point.get("redacted") is True for point in projected)

    preview = build_route_preview(
        projected,
        source="server_gps",
        privacy={"redactGps": False},
        privacy_zones=[zone],
    )

    assert preview is not None
    assert preview["segments"]
    # Simplified, not bead-fragmented: the circle stays one continuous run.
    assert len(preview["segments"]) == 1
    assert len(preview["segments"][0]) >= 8
    bounds = preview["bounds"]
    lat_span = bounds["maxLat"] - bounds["minLat"]
    lon_span = bounds["maxLon"] - bounds["minLon"]
    originals = {
        (round(point["latitude"], 6), round(point["longitude"], 6))
        for point in projected
    }
    for segment in preview["segments"]:
        restored = [
            {
                "latitude": bounds["maxLat"] - point["y"] * lat_span,
                "longitude": bounds["minLon"] + point["x"] * lon_span,
            }
            for point in segment
        ]
        # Law 1: emitted vertices are original recorded points (and therefore
        # remain outside the zone — the projection already proved them clean).
        for point in restored:
            key = (round(point["latitude"], 6), round(point["longitude"], 6))
            assert key in originals
        checked = project_route_points(restored, policy, privacy_zones=[zone])
        assert not any(point.get("redacted") is True for point in checked)
        # Law 3: no drawn edge comes closer to the zone center than
        # (radius − tolerance cap).
        floor_m = zone["radius_m"] - ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_CAP_M
        for start, end in zip(restored, restored[1:]):
            assert _segment_distance_to_origin_m(start, end) >= floor_m


def _segment_distance_to_origin_m(start: dict, end: dict) -> float:
    """Meters from the (0, 0) zone center to the [start, end] chord, sampled
    densely (local equirectangular frame near the equator)."""
    meters_per_degree = 111_195.0
    best = float("inf")
    steps = 200
    for step in range(steps + 1):
        t = step / steps
        lat = start["latitude"] + t * (end["latitude"] - start["latitude"])
        lon = start["longitude"] + t * (end["longitude"] - start["longitude"])
        distance = ((lat * meters_per_degree) ** 2 + (lon * meters_per_degree) ** 2) ** 0.5
        best = min(best, distance)
    return best


def test_route_preview_keeps_long_credible_tracks_continuous() -> None:
    """The dotted-route regression: a credible ~20 mph track longer than the
    preview budget must render as one continuous run of original vertices,
    never as disconnected 2-point bead fragments."""
    meters_per_degree = 111_195.0
    points = []
    for index in range(5_000):
        # A gently winding 1 Hz ride at ~9 m/s (about 20 mph).
        along_m = index * 9.0
        swing_m = 120.0 * sin(index / 90.0)
        points.append(
            {
                "latitude": 39.95 + along_m / meters_per_degree,
                "longitude": -75.17 + swing_m / (meters_per_degree * cos(39.95 * pi / 180)),
                "timestamp": index,
            }
        )

    preview = build_route_preview(
        points,
        source="server_gps",
        privacy={"redactGps": False},
    )

    assert preview is not None
    assert preview["fallbackReason"] is None
    assert len(preview["segments"]) == 1
    segment = preview["segments"][0]
    assert len(segment) >= 8
    assert len(segment) <= MAX_ROUTE_PREVIEW_POINTS
    # Continuity, not beads: the run keeps interior vertices.
    assert len(segment) > 2


def test_route_preview_severs_only_the_implausible_edge() -> None:
    """A single implausible jump breaks the line at that edge; the credible
    remainder of the ride still renders (no preview-wide quarantine)."""
    preview = build_route_preview(
        [
            {"latitude": 39.9500, "longitude": -75.1700, "timestamp": 0},
            {"latitude": 39.9505, "longitude": -75.1698, "timestamp": 10},
            # Teleport: ~500 m in one second.
            {"latitude": 39.9550, "longitude": -75.1690, "timestamp": 11},
            {"latitude": 39.9555, "longitude": -75.1688, "timestamp": 21},
        ],
        source="server_gps",
        place_label="Fairmount Park",
        privacy={"redactGps": False},
    )

    assert preview is not None
    assert preview["fallbackReason"] is None
    assert len(preview["segments"]) == 2
    assert [len(segment) for segment in preview["segments"]] == [2, 2]
    # The severed edge is never drawn: the runs do not share a vertex.
    assert preview["segments"][0][-1] != preview["segments"][1][0]


def test_route_preview_quarantines_geometry_with_no_credible_edge() -> None:
    """The preview-wide fallback survives only for tracks where severing the
    implausible edges leaves nothing drawable at all."""
    preview = build_route_preview(
        [
            {"latitude": 39.9996786, "longitude": -75.196894, "timestamp": 0},
            {"latitude": 40.0040749, "longitude": -75.1978819, "timestamp": 1},
            {"latitude": 40.0090749, "longitude": -75.1998819, "timestamp": 2},
        ],
        source="server_gps",
        place_label="Fairmount Park",
        privacy={"redactGps": False},
    )

    assert preview is not None
    assert preview["points"] == []
    assert preview["segments"] == []
    assert preview["pointCount"] == 3
    assert preview["fallbackReason"] == "implausible_geometry"
    assert preview["placeLabel"] == "Fairmount Park"


def test_ride_feed_event_does_not_decode_raw_gps_when_privacy_redacts() -> None:
    event = build_ride_feed_event(
        {
            "id": "ride-privacy",
            "user_id": "user-1",
            "processing_status": "completed",
            "started_at": "2026-04-20T10:00:00Z",
            "gps_track": [
                {"latitude": 39.95, "longitude": -75.17},
                {"latitude": 39.96, "longitude": -75.16},
            ],
        },
        {"id": "user-1", "username": "alice"},
        None,
        {"visibility": "public", "canView": True, "redactGps": True},
    )

    assert event is not None
    assert event["metadata"]["routePreview"]["points"] == []
    assert event["metadata"]["routePreview"]["fallbackReason"] == "privacy_redacted"


@pytest.mark.asyncio
async def test_feed_route_preview_redacts_coordinates_even_without_privacy_zones() -> None:
    class EmptyPrivacyZoneRepo:
        async def _run(self, _func):
            return SimpleNamespace(data=[])

    projected = await _route_preview_points_for_feed(
        {
            "id": "ride-privacy",
            "user_id": "user-1",
            "gps_track": [
                {"latitude": 39.95, "longitude": -75.17},
                {"latitude": 39.96, "longitude": -75.16},
            ],
        },
        {
            "visibility": "public",
            "redactGps": True,
            "mapVisibility": "hide_entire",
            "mapHideStartM": 0,
            "mapHideEndM": 0,
        },
        EmptyPrivacyZoneRepo(),  # type: ignore[arg-type]
    )

    assert projected is not None
    points, zones = projected
    assert zones == []
    assert len(points) == 2
    assert all(point["latitude"] is None for point in points)
    assert all(point["longitude"] is None for point in points)
    assert all(point["redacted"] is True for point in points)


def test_legacy_activity_maps_to_feed_event_contract() -> None:
    event = build_activity_feed_event(
        {
            "id": "activity-1",
            "user_id": "actor-1",
            "activity_type": "local_legend",
            "target_type": "climb",
            "target_id": "climb-1",
            "title": "Local Legend changed hands",
            "metadata": {"climbId": "climb-1"},
            "created_at": "2026-04-30T12:10:00+00:00",
        },
        {"id": "actor-1", "display_name": "Rider"},
    )

    assert event["eventType"] == "local_legend_moved"
    assert event["actor"]["displayName"] == "Rider"
    assert event["target"]["type"] == "climb"
    assert event["target"]["id"] == "climb-1"
    assert event["primaryAction"] == "open_climb"
    assert event["metadata"] == {"climbId": "climb-1"}


def test_legacy_activity_strips_nested_exact_economy_for_non_owner() -> None:
    activity = {
        "id": "activity-economy",
        "user_id": "actor-1",
        "activity_type": "ride",
        "target_type": "ride",
        "target_id": "ride-1",
        "title": "Ride",
        "metadata": {
            "calEarned": 42,
            "dung_minted": 9,
            "receipt": {"cal_tribute": 4, "rank": 2},
        },
        "created_at": "2026-04-30T12:10:00+00:00",
    }

    public_event = build_activity_feed_event(activity, {"id": "actor-1"})
    owner_event = build_activity_feed_event(
        activity,
        {"id": "actor-1"},
        is_owner=True,
    )

    assert "calEarned" not in public_event["metadata"]
    assert "dung_minted" not in public_event["metadata"]
    assert "cal_tribute" not in public_event["metadata"]["receipt"]
    assert public_event["metadata"]["receipt"]["rank"] == 2
    assert owner_event["metadata"]["calEarned"] == 42
    assert owner_event["metadata"]["dung_minted"] == 9
    assert owner_event["metadata"]["receipt"]["cal_tribute"] == 4


def test_feed_cursor_uses_last_event_occurrence_time() -> None:
    assert feed_cursor([]) is None
    assert feed_cursor([
        {"occurredAt": "2026-04-30T12:10:00+00:00"},
        {"occurredAt": "2026-04-30T12:00:00+00:00"},
    ]) == "2026-04-30T12:00:00+00:00"


def test_feed_event_type_vocabulary_covers_core_product_organs() -> None:
    expected = {
        "ride": "ride_completed",
        "climb": "climb_completed",
        "record_rank_moved": "record_rank_moved",
        "local_legend": "local_legend_moved",
        "achievement": "achievement_unlocked",
        "comment": "comment_created",
        "follow": "follow_created",
        "report": "report_resolved",
    }

    assert {
        key: infer_activity_event_type(key).value
        for key in expected
    } == expected
