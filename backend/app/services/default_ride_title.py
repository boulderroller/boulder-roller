"""Default ride titles, generated once at processing time.

Feature: boulderroller-v2-g0o24. The Tim-ratified fallback-title shape
(2026-08-11) previously lived identically in two thin clients
(``web/portal/src/lib/rideTitle.ts`` and iOS ``Format.displayRideTitle``).
This module is now the canonical formula; the client helpers remain only as
legacy-null fallbacks for rides processed before this landed.

Shape (byte-identical to the client helpers for the same inputs):

* place known -> ``"{placeLabel first component} Ride"``
* else local-start-hour bucket -> ``4-11 Morning / 11-14 Lunch /
  14-17 Afternoon / 17-21 Evening / else Night`` + ``" Ride"``
* missing/invalid start time -> hour 12 (``"Lunch Ride"``), matching the
  clients' explicit default.

LOCAL TIME DERIVATION (documented decision, 2026-08-11): the parser exposes no
device-local timestamp, so the offset comes from the ride's start coordinates.
Inside the product envelope (lat 24..50, lon -85..-67 — generous America/
New_York longitudes; Philadelphia is the product) the ride clock is
``America/New_York`` via zoneinfo, DST-correct. Other GPS starts use solar
time (``round(lon / 15)`` hours), an explicit approximation. No GPS at all
(trainer files) buckets by UTC. Titles remain rider-editable; this never
overwrites a non-null title.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

PRODUCT_ENVELOPE_MIN_LAT = 24.0
PRODUCT_ENVELOPE_MAX_LAT = 50.0
PRODUCT_ENVELOPE_MIN_LON = -85.0
PRODUCT_ENVELOPE_MAX_LON = -67.0
PRODUCT_TIMEZONE = "America/New_York"

_PLACE_KEYS = (
    "place_label",
    "placeLabel",
    "location",
    "region",
    "city",
    "start_city",
    "startCity",
)


def place_label_for_ride(ride_row: Mapping[str, Any]) -> Optional[str]:
    """The single place-label source chain shared with route previews."""

    diagnostics = ride_row.get("import_diagnostics")
    sources = [ride_row]
    if isinstance(diagnostics, Mapping):
        sources.append(diagnostics)
    for source in sources:
        for key in _PLACE_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def time_bucket_for_hour(hour: int) -> str:
    if 4 <= hour < 11:
        return "Morning"
    if 11 <= hour < 14:
        return "Lunch"
    if 14 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 21:
        return "Evening"
    return "Night"


def local_start_hour(
    started_at: Optional[datetime],
    start_lat: Optional[float],
    start_lon: Optional[float],
) -> int:
    """Local hour of day for bucketing; 12 when the start time is unknown."""

    if started_at is None:
        return 12
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    has_coordinates = (
        start_lat is not None
        and start_lon is not None
        and -90 <= start_lat <= 90
        and -180 <= start_lon <= 180
    )
    if has_coordinates:
        if (
            PRODUCT_ENVELOPE_MIN_LAT <= start_lat <= PRODUCT_ENVELOPE_MAX_LAT
            and PRODUCT_ENVELOPE_MIN_LON <= start_lon <= PRODUCT_ENVELOPE_MAX_LON
        ):
            try:
                from zoneinfo import ZoneInfo

                return started_at.astimezone(ZoneInfo(PRODUCT_TIMEZONE)).hour
            except Exception:
                logger.warning(
                    "[RideTitle] %s unavailable; falling back to solar offset",
                    PRODUCT_TIMEZONE,
                )
        offset_hours = max(-12, min(14, round(start_lon / 15.0)))
        return (started_at.astimezone(timezone.utc) + timedelta(hours=offset_hours)).hour
    return started_at.astimezone(timezone.utc).hour


def default_ride_title(
    place_label: Optional[str],
    started_at: Optional[datetime],
    start_lat: Optional[float],
    start_lon: Optional[float],
) -> str:
    """The ratified fallback shape. Never returns an empty string."""

    if place_label:
        first_component = place_label.split(",")[0].strip()
        if first_component:
            return f"{first_component} Ride"
    hour = local_start_hour(started_at, start_lat, start_lon)
    return f"{time_bucket_for_hour(hour)} Ride"
