"""Default ride title generation (boulderroller-v2-g0o24).

The backend is the canonical home of the Tim-ratified fallback-title shape.
These vectors mirror the client helpers (portal ``displayRideTitle`` /
iOS ``Format.displayRideTitle``) byte for byte so the three implementations
can never drift silently.

Red-first record: the module under test did not exist on pre-change main.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.default_ride_title import (
    default_ride_title,
    local_start_hour,
    place_label_for_ride,
    time_bucket_for_hour,
)

PHILLY = (40.0021, -75.2096)


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_place_first_component_wins():
    assert (
        default_ride_title("Manayunk, Philadelphia, PA", _utc("2026-08-11T22:30:00"), *PHILLY)
        == "Manayunk Ride"
    )


def test_blank_place_falls_through_to_time_bucket():
    title = default_ride_title("   ", _utc("2026-08-11T22:30:00"), *PHILLY)
    assert title == "Evening Ride"  # 18:30 EDT
    title = default_ride_title(" , Philadelphia", _utc("2026-08-11T22:30:00"), *PHILLY)
    assert title == "Evening Ride"  # empty first component


@pytest.mark.parametrize(
    ("hour", "bucket"),
    [
        (3, "Night"),
        (4, "Morning"),
        (10, "Morning"),
        (11, "Lunch"),
        (13, "Lunch"),
        (14, "Afternoon"),
        (16, "Afternoon"),
        (17, "Evening"),
        (20, "Evening"),
        (21, "Night"),
        (0, "Night"),
    ],
)
def test_bucket_boundaries_match_ratified_shape(hour, bucket):
    assert time_bucket_for_hour(hour) == bucket


def test_philadelphia_uses_civil_time_not_solar():
    # 15:10Z on a summer date = 11:10 EDT (Lunch). Solar time for -75.2 would
    # be ~10:09 (Morning) — this asserts America/New_York with DST applies.
    assert default_ride_title(None, _utc("2026-08-11T15:10:00"), *PHILLY) == "Lunch Ride"


def test_philadelphia_winter_offset_is_est():
    # 22:30Z in January = 17:30 EST -> Evening (EDT would say 18:30, same
    # bucket; 09:30Z = 04:30 EST -> Morning while EDT 05:30 is also Morning —
    # use 01:59Z = 20:59 EST Evening vs 21:59 EDT Night to split the zones).
    assert default_ride_title(None, _utc("2026-01-15T01:59:00"), *PHILLY) == "Evening Ride"


def test_non_product_region_uses_solar_offset():
    # Tokyo-ish start (35.68N 139.77E): round(139.77/15) = +9h. 05:00Z -> 14:00.
    assert (
        default_ride_title(None, _utc("2026-08-11T05:00:00"), 35.68, 139.77)
        == "Afternoon Ride"
    )


def test_no_gps_buckets_by_utc():
    assert default_ride_title(None, _utc("2026-08-11T12:00:00"), None, None) == "Lunch Ride"
    assert default_ride_title(None, _utc("2026-08-11T02:00:00"), None, None) == "Night Ride"


def test_missing_start_time_matches_client_default_hour_12():
    assert default_ride_title(None, None, *PHILLY) == "Lunch Ride"
    assert local_start_hour(None, *PHILLY) == 12


def test_naive_datetime_is_treated_as_utc():
    naive = datetime(2026, 8, 11, 15, 10, 0)
    assert local_start_hour(naive, *PHILLY) == 11  # 11:10 EDT


def test_place_label_chain_matches_route_preview_sources():
    assert place_label_for_ride({"location": " Manayunk "}) == "Manayunk"
    assert place_label_for_ride({"region": "Philadelphia"}) == "Philadelphia"
    assert (
        place_label_for_ride({"import_diagnostics": {"start_city": "Conshohocken"}})
        == "Conshohocken"
    )
    assert place_label_for_ride({"import_diagnostics": {"city": ""}}) is None
    assert place_label_for_ride({}) is None
