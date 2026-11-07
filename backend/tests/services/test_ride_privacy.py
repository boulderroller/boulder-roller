from __future__ import annotations

import math

import pytest

from backend.app.services.public_record_board_privacy import route_span_is_public
from backend.app.services.ride_privacy import (
    ALLOWED_MAP_HIDE_DISTANCES_M,
    VALID_MAP_VISIBILITIES,
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    project_route_points,
    resolve_policy,
    strip_hidden_point_details,
)


def _route() -> list[dict[str, object]]:
    # At the equator each longitude step is about 111.2 meters.
    return [
        {
            "latitude": 0.0,
            "longitude": index / 1000,
            "timestamp": f"2026-08-02T10:00:0{index}Z",
        }
        for index in range(6)
    ]


def _redacted_indexes(points: list[dict[str, object]]) -> list[int]:
    return [index for index, point in enumerate(points) if point.get("redacted") is True]


def test_policy_is_strict_and_serializes_storage_and_client_contracts() -> None:
    assert VALID_MAP_VISIBILITIES == {"show_all", "hide_start_end", "hide_entire"}
    assert ALLOWED_MAP_HIDE_DISTANCES_M == {0, 200, 400, 800, 1600}

    policy = RidePrivacyPolicy.from_values(
        visibility="followers",
        map_visibility="hide_start_end",
        map_hide_start_m=400,
        map_hide_end_m=800,
    )

    assert policy.to_storage_dict() == {
        "visibility": "followers",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 400,
        "map_hide_end_m": 800,
    }
    assert policy.to_client_dict() == {
        "visibility": "followers",
        "mapVisibility": "hide_start_end",
        "mapHideStartM": 400,
        "mapHideEndM": 800,
    }

    for invalid in (
        {
            "visibility": "friends",
            "map_visibility": "show_all",
            "map_hide_start_m": 0,
            "map_hide_end_m": 0,
        },
        {
            "visibility": "public",
            "map_visibility": "full",
            "map_hide_start_m": 0,
            "map_hide_end_m": 0,
        },
        {
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 50,
            "map_hide_end_m": 200,
        },
        {
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 0,
            "map_hide_end_m": 200,
        },
        {
            "visibility": None,
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
        },
    ):
        with pytest.raises(PrivacySettingsUnavailable):
            RidePrivacyPolicy.from_values(**invalid)


def test_resolve_policy_merges_explicit_overrides_without_silent_defaults() -> None:
    defaults = {
        "default_ride_visibility": "public",
        "default_map_visibility": "hide_start_end",
        "default_map_hide_start_m": 200,
        "default_map_hide_end_m": 200,
    }

    assert resolve_policy(defaults, {"visibility": "private"}).to_storage_dict() == {
        "visibility": "private",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 200,
        "map_hide_end_m": 200,
    }

    with pytest.raises(PrivacySettingsUnavailable):
        resolve_policy({"default_ride_visibility": "public"})


def test_endpoint_hiding_uses_cumulative_route_distance_and_preserves_gaps() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_start_end",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )

    projected = project_route_points(_route(), policy)

    assert len(projected) == 6
    assert _redacted_indexes(projected) == [0, 1, 4, 5]
    assert projected[0]["latitude"] is None
    assert projected[1]["longitude"] is None
    assert projected[2]["longitude"] == pytest.approx(0.002)
    assert projected[3]["longitude"] == pytest.approx(0.003)
    assert projected[4]["timestamp"] == "2026-08-02T10:00:04Z"


def test_privacy_zone_masks_an_interior_span_without_reconnecting_it() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )

    projected = project_route_points(
        _route(),
        policy,
        privacy_zones=(
            {"latitude": 0.0, "longitude": 0.003, "radius_m": 200},
        ),
    )

    assert _redacted_indexes(projected) == [2, 3, 4]
    assert projected[1]["longitude"] == pytest.approx(0.001)
    assert projected[5]["longitude"] == pytest.approx(0.005)
    assert [point["timestamp"] for point in projected] == [
        f"2026-08-02T10:00:0{index}Z" for index in range(6)
    ]


def test_sparse_segment_crossing_zone_is_split_and_excluded_from_climb_span() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    route = [
        {
            "latitude": 0.0,
            "longitude": -0.003,
            "timestamp": "2026-08-02T10:00:00Z",
        },
        {
            "latitude": 0.0,
            "longitude": 0.003,
            "timestamp": "2026-08-02T10:02:00Z",
        },
    ]

    projected = project_route_points(
        route,
        policy,
        privacy_zones=(
            {"latitude": 0.0, "longitude": 0.0, "radius_m": 200},
        ),
    )

    assert len(projected) == len(route)
    assert _redacted_indexes(projected) == [0, 1]
    assert not route_span_is_public(
        projected,
        start_offset_s=10,
        end_offset_s=110,
    )


def test_segment_touching_zone_boundary_is_redacted_fail_closed() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    # The route follows the equator.  A zone centered exactly one radius north
    # is tangent to that great-circle segment at longitude zero, while both
    # sparse samples remain outside the circle.
    zone_latitude = math.degrees(200 / 6_371_000.0)
    route = [
        {"latitude": 0.0, "longitude": -0.003, "timestamp": 0},
        {"latitude": 0.0, "longitude": 0.003, "timestamp": 120},
    ]

    projected = project_route_points(
        route,
        policy,
        privacy_zones=(
            {
                "latitude": zone_latitude,
                "longitude": 0.0,
                "radius_m": 200,
            },
        ),
    )

    assert _redacted_indexes(projected) == [0, 1]


def test_segment_outside_zone_remains_visible() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    zone_latitude = math.degrees(250 / 6_371_000.0)
    route = [
        {"latitude": 0.0, "longitude": -0.003, "timestamp": 0},
        {"latitude": 0.0, "longitude": 0.003, "timestamp": 120},
    ]

    projected = project_route_points(
        route,
        policy,
        privacy_zones=(
            {
                "latitude": zone_latitude,
                "longitude": 0.0,
                "radius_m": 200,
            },
        ),
    )

    assert projected == route


def test_owner_keeps_full_route_and_hide_entire_fails_closed_for_other_viewers() -> None:
    route = _route()
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_entire",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )

    assert project_route_points(route, policy, is_owner=True) == route

    projected = project_route_points(route, policy)
    assert _redacted_indexes(projected) == list(range(6))
    assert all(point["latitude"] is None for point in projected)
    assert all(point["longitude"] is None for point in projected)


def test_invalid_zone_contract_raises_fail_closed_exception() -> None:
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )

    for invalid_zones in (
        None,
        ({"latitude": 0.0, "longitude": 0.0},),
        ({"latitude": math.nan, "longitude": 0.0, "radius_m": 200},),
    ):
        with pytest.raises(PrivacySettingsUnavailable):
            project_route_points(
                _route(),
                policy,
                privacy_zones=invalid_zones,
            )


def test_hidden_points_leave_the_api_without_elevation_or_time() -> None:
    """The projection keeps timestamps for leaderboard span checks; the public
    response must not. A hidden point keeps only distance and the flag."""
    policy = RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_start_end",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )
    route = [
        {**point, "elevation_m": 30.0 + index, "elevation_corrected_m": 31.0 + index,
         "distance_m": 111.2 * index, "heart_rate": 150}
        for index, point in enumerate(_route())
    ]
    projected = project_route_points(route, policy)
    # The projection itself still carries time (route_span_is_public needs it).
    assert projected[0]["timestamp"] == "2026-08-02T10:00:00Z"

    public = strip_hidden_point_details(projected)

    assert len(public) == len(projected)
    for index in (0, 1, 4, 5):
        hidden = public[index]
        assert hidden["redacted"] is True
        assert hidden["distance_m"] == pytest.approx(111.2 * index)
        for key in ("latitude", "longitude", "timestamp", "elevation_m", "elevation_corrected_m", "heart_rate"):
            assert key in hidden and hidden[key] is None, (index, key)
    for index in (2, 3):
        assert public[index] == projected[index]
    # The input projection is not mutated.
    assert projected[0]["timestamp"] == "2026-08-02T10:00:00Z"


def test_strip_hidden_point_details_keeps_camel_case_distance() -> None:
    public = strip_hidden_point_details([
        {"latitude": None, "longitude": None, "redacted": True, "distanceM": 42.0, "elevationM": 12.0, "timestamp": 5},
    ])
    assert public == [{"latitude": None, "longitude": None, "redacted": True, "distanceM": 42.0, "elevationM": None, "timestamp": None}]
