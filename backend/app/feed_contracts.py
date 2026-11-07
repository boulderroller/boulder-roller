"""Canonical feed.v1 event contracts.

The feed is a product contract, not a dump of rows. These helpers keep legacy
activity rows and ride projections behind one stable event shape that clients
can render without knowing which table produced the item.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import atan2, cos, isfinite, radians, sin, sqrt
from typing import Any, Optional

from pydantic import BaseModel

from .rider_identity_contracts import PublicRiderRef, public_rider_ref_dict
from .services.ride_privacy import _segment_intersects_zone, _validated_zones
from .target_action_contracts import (
    TargetRef,
    capabilities_for_target,
    primary_action_for_target,
    target_ref_dict,
)


FEED_CONTRACT_VERSION = "feed.v1"
ROUTE_PREVIEW_CONTRACT_VERSION = "route_preview.v1"
RIDE_FEED_STATUSES = {"metrics_ready", "enriched", "completed", "under_review"}
NON_OWNER_ECONOMY_KEYS = {
    "cal",
    "calearned",
    "dung",
    "dungearned",
    "dungminted",
    "estimatedcal",
    "rewardablecal",
    "tributablecal",
    "caltribute",
    "caltributebaseunits",
    "exactcalbaseunits",
    "exacttributebaseunits",
    "ridecalbaseunits",
    "tributebudgetbaseunits",
    "everythingbetweenbaseunits",
    "totalcalearned",
    "totaldungearned",
}
# Preview size budget (points across all runs). Soft: fidelity is
# truth-bounded, so a preview may exceed it rather than exceed the
# simplification tolerance cap below (see _simplify_route_runs).
MAX_ROUTE_PREVIEW_POINTS = 320
MAX_ROUTE_IMPLIED_SPEED_MPS = 50.0
MIN_ROUTE_JUMP_DISTANCE_M = 25.0
# Bounded-deviation simplification (route rendering unification, bead
# boulderroller-v2-zudgp). Escalate through the ladder until the preview fits
# the budget; never simplify beyond the cap. Mirrors the iOS render-side
# ZoomRouteSimplifier: original recorded vertices only, per visible run.
ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_LADDER_M = (2.0, 4.0, 8.0, 16.0, 32.0)
ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_CAP_M = 32.0


class FeedEventType(str, Enum):
    ride_completed = "ride_completed"
    ride_under_review = "ride_under_review"
    climb_completed = "climb_completed"
    record_rank_moved = "record_rank_moved"
    local_legend_moved = "local_legend_moved"
    achievement_unlocked = "achievement_unlocked"
    comment_created = "comment_created"
    follow_created = "follow_created"
    report_resolved = "report_resolved"
    social = "social"


class FeedActor(PublicRiderRef):
    pass


class FeedTarget(TargetRef):
    pass


def parse_feed_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def feed_datetime_iso(value: Any) -> str:
    parsed = parse_feed_datetime(value) or datetime.now(timezone.utc)
    return parsed.isoformat()


def feed_cursor(events: list[dict[str, Any]]) -> Optional[str]:
    if not events:
        return None
    return events[-1].get("occurredAt") or events[-1].get("createdAt")


def _without_exact_economy(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_exact_economy(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _without_exact_economy(item)
        for key, item in value.items()
        if "".join(character for character in str(key).lower() if character.isalnum())
        not in NON_OWNER_ECONOMY_KEYS
    }


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _point_lat_lon(point: dict[str, Any]) -> Optional[tuple[float, float]]:
    lat = _finite_float(point.get("latitude", point.get("lat")))
    lon = _finite_float(point.get("longitude", point.get("lon")))
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _point_timestamp_seconds(point: dict[str, Any]) -> Optional[float]:
    value = point.get("timestamp", point.get("time", point.get("t")))
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    if isinstance(value, (int, float)):
        return float(value) if isfinite(float(value)) else None
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed_number = float(raw)
        except ValueError:
            parsed_number = None
        if parsed_number is not None:
            return parsed_number if isfinite(parsed_number) else None
        parsed_dt = parse_feed_datetime(raw)
        return parsed_dt.timestamp() if parsed_dt is not None else None
    return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    r_lat1 = radians(lat1)
    r_lat2 = radians(lat2)
    a = sin(d_lat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(d_lon / 2) ** 2
    a = min(1.0, max(0.0, a))
    return earth_radius_m * 2 * atan2(sqrt(a), sqrt(1 - a))


def _edge_is_implausible(
    prev: tuple[float, float, Optional[float]],
    curr: tuple[float, float, Optional[float]],
) -> bool:
    """One recorded edge fails credibility when its implied speed is not a
    bicycle's. Short jumps are never judged: GPS noise at rest must not sever
    a stationary rider's line."""
    prev_ts, curr_ts = prev[2], curr[2]
    if prev_ts is None or curr_ts is None:
        return False
    dist_m = _haversine_m(prev[0], prev[1], curr[0], curr[1])
    if dist_m < MIN_ROUTE_JUMP_DISTANCE_M:
        return False
    dt_s = curr_ts - prev_ts
    if dt_s <= 0:
        return True
    return dist_m / dt_s > MAX_ROUTE_IMPLIED_SPEED_MPS


def _split_run_at_implausible_edges(
    run: list[tuple[float, float, Optional[float]]],
) -> list[list[tuple[float, float, Optional[float]]]]:
    """Credibility is judged per recorded edge, matching the client render
    policy (iOS RouteRenderPolicy): an implausible edge breaks the line there
    and is never drawn, while every credible stretch of the same ride still
    renders. A single GPS glitch no longer deletes the whole preview."""
    if len(run) < 2:
        return [run]
    pieces: list[list[tuple[float, float, Optional[float]]]] = []
    current = [run[0]]
    for prev, curr in zip(run, run[1:]):
        if _edge_is_implausible(prev, curr):
            pieces.append(current)
            current = [curr]
        else:
            current.append(curr)
    pieces.append(current)
    return pieces


def _visible_route_runs(
    points: list[dict[str, Any]],
) -> list[list[tuple[float, float, Optional[float]]]]:
    """Keep invalid or redacted points as hard boundaries between visible runs."""
    runs: list[list[tuple[float, float, Optional[float]]]] = []
    current: list[tuple[float, float, Optional[float]]] = []
    for point in points:
        lat_lon = None if point.get("redacted") is True else _point_lat_lon(point)
        if lat_lon is None:
            if current:
                runs.append(current)
                current = []
            continue
        current.append((lat_lon[0], lat_lon[1], _point_timestamp_seconds(point)))
    if current:
        runs.append(current)
    return runs


def _perpendicular_distance_m(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Meters from a point to the [start, end] segment (equirectangular local
    projection — the same math as the iOS ZoomRouteSimplifier)."""
    reference_latitude = radians((start[0] + end[0] + point[0]) / 3)
    meters_per_degree_latitude = 111_132.92
    meters_per_degree_longitude = 111_412.84 * cos(reference_latitude)
    sx = start[1] * meters_per_degree_longitude
    sy = start[0] * meters_per_degree_latitude
    ex = end[1] * meters_per_degree_longitude
    ey = end[0] * meters_per_degree_latitude
    px = point[1] * meters_per_degree_longitude
    py = point[0] * meters_per_degree_latitude
    dx = ex - sx
    dy = ey - sy
    denominator = dx * dx + dy * dy
    if denominator <= 0:
        return sqrt((px - sx) ** 2 + (py - sy) ** 2)
    t = min(1.0, max(0.0, ((px - sx) * dx + (py - sy) * dy) / denominator))
    nearest_x = sx + t * dx
    nearest_y = sy + t * dy
    return sqrt((px - nearest_x) ** 2 + (py - nearest_y) ** 2)


def _rdp_simplify_indices(
    run: list[tuple[float, float]],
    tolerance_m: float,
) -> list[int]:
    """Ramer-Douglas-Peucker over one visible run, returning the kept
    original indices. Iterative (recorded runs reach tens of thousands of
    points); selects original vertices only."""
    if len(run) <= 2 or tolerance_m <= 0:
        return list(range(len(run)))
    keep = {0, len(run) - 1}
    stack: list[tuple[int, int]] = [(0, len(run) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        farthest_index = -1
        farthest_distance = 0.0
        for index in range(first + 1, last):
            distance = _perpendicular_distance_m(run[index], run[first], run[last])
            if distance > farthest_distance:
                farthest_distance = distance
                farthest_index = index
        if farthest_index >= 0 and farthest_distance > tolerance_m:
            keep.add(farthest_index)
            stack.append((first, farthest_index))
            stack.append((farthest_index, last))
    return sorted(keep)


def _zone_safe_indices(
    run: list[tuple[float, float]],
    indices: list[int],
    zones: list[tuple[float, float, float]],
) -> list[int]:
    """Restore original vertices until no drawn edge crosses a saved privacy
    zone — the exact edge law `project_route_points` enforces on recorded
    tracks, applied to the simplified polyline. Bisection terminates at
    original adjacent edges, which the privacy projection already proved
    clean inside a visible run."""
    if not zones:
        return indices
    result = list(indices)
    position = 0
    while position < len(result) - 1:
        start_index, end_index = result[position], result[position + 1]
        if end_index - start_index > 1 and any(
            _segment_intersects_zone(run[start_index], run[end_index], zone)
            for zone in zones
        ):
            result.insert(position + 1, (start_index + end_index) // 2)
            continue
        position += 1
    return result


def _simplify_route_runs(
    runs: list[list[tuple[float, float]]],
    zones: list[tuple[float, float, float]],
) -> list[list[tuple[float, float]]]:
    """Bound preview size with bounded-deviation simplification.

    Laws, in order:
    1. Every emitted vertex is an original recorded point — never an
       interpolated one.
    2. Run boundaries (privacy redactions, start/end trims, severed
       implausible edges) are never bridged: a hidden gap is never closed.
    3. No drawn edge crosses a saved privacy zone. Simplified edges are
       re-checked against the same `_segment_intersects_zone` predicate the
       privacy projection applies to recorded edges; crossing edges are
       refined back toward original vertices until clean. Callers guarding a
       non-owner viewer pass the viewer's zones; owner surfaces have nothing
       to hide from the rider and pass none.
    4. Away from zones, the drawn line deviates from the recorded path by at
       most the tolerance that admitted it, hard-capped at
       ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_CAP_M.
    5. Fidelity is truth-bounded: when the cap (or zone refinement) cannot
       reach the size budget, the preview exceeds MAX_ROUTE_PREVIEW_POINTS
       rather than break laws 1–4.

    This replaced the earlier isolated-edge sampler, which drew a credible
    ride as disconnected 2-point bead fragments (the dotted-route bug, bead
    boulderroller-v2-zudgp).
    """
    visible_runs = [run for run in runs if len(run) >= 2]
    total_points = sum(len(run) for run in visible_runs)
    if total_points <= MAX_ROUTE_PREVIEW_POINTS:
        return visible_runs

    simplified = visible_runs
    for tolerance_m in ROUTE_PREVIEW_SIMPLIFY_TOLERANCE_LADDER_M:
        simplified = [
            [
                run[index]
                for index in _zone_safe_indices(
                    run,
                    _rdp_simplify_indices(run, tolerance_m),
                    zones,
                )
            ]
            for run in visible_runs
        ]
        if sum(len(run) for run in simplified) <= MAX_ROUTE_PREVIEW_POINTS:
            return simplified
    return simplified


def _place_label_from_ride(ride: dict[str, Any]) -> Optional[str]:
    metadata = ride.get("metadata") if isinstance(ride.get("metadata"), dict) else {}
    diagnostics = ride.get("import_diagnostics") if isinstance(ride.get("import_diagnostics"), dict) else {}
    for source in (ride, metadata, diagnostics):
        for key in ("place_label", "placeLabel", "location", "region", "city", "start_city", "startCity"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def build_route_preview(
    points: list[dict[str, Any]],
    *,
    source: str,
    place_label: Optional[str] = None,
    privacy: Optional[dict[str, Any]] = None,
    privacy_zones: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """Build the route_preview.v1 contract from privacy-projected points.

    `privacy_zones` are the zones the caller's projection already applied —
    pass them wherever a non-owner can see the preview so simplification
    keeps the projection's no-edge-through-a-zone law. Owner-only surfaces
    and canon geometry omit them.
    """
    if not points:
        return None

    route_runs = _visible_route_runs(points)
    route_points = [point for run in route_runs for point in run]
    coords = [(lat, lon) for lat, lon, _timestamp in route_points]
    if len(coords) < 2:
        return {
            "contractVersion": ROUTE_PREVIEW_CONTRACT_VERSION,
            "source": source,
            "points": [],
            "segments": [],
            "pointCount": 0,
            "placeLabel": place_label,
            "fallbackReason": "privacy_redacted" if len(points) >= 2 else "missing_gps",
            "privacy": {
                "redactedGps": bool((privacy or {}).get("redactGps")),
            },
        }

    had_visible_runs = any(len(run) >= 2 for run in route_runs)
    credible_runs = [
        piece
        for run in route_runs
        for piece in _split_run_at_implausible_edges(run)
    ]
    drawable_runs = [run for run in credible_runs if len(run) >= 2]
    if not drawable_runs:
        return {
            "contractVersion": ROUTE_PREVIEW_CONTRACT_VERSION,
            "source": source,
            "points": [],
            "segments": [],
            "pointCount": len(coords),
            "placeLabel": place_label,
            "fallbackReason": (
                "implausible_geometry"
                if had_visible_runs
                else "privacy_redacted"
                if bool((privacy or {}).get("redactGps"))
                else "missing_gps"
            ),
            "privacy": {
                "redactedGps": bool((privacy or {}).get("redactGps")),
            },
        }

    lats = [lat for lat, _lon in coords]
    lons = [lon for _lat, lon in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_span = max(max_lat - min_lat, 0.00001)
    lon_span = max(max_lon - min_lon, 0.00001)

    sampled_runs = _simplify_route_runs(
        [
            [(lat, lon) for lat, lon, _timestamp in run]
            for run in drawable_runs
        ],
        _validated_zones(privacy_zones or []),
    )
    normalized_segments = [
        [
            {
                "x": round((lon - min_lon) / lon_span, 12),
                "y": round(1 - ((lat - min_lat) / lat_span), 12),
            }
            for lat, lon in run
        ]
        for run in sampled_runs
    ]
    # Keep the legacy field only when it represents one continuous line. Old
    # clients safely show no route for an interior redaction instead of drawing
    # a shortcut across it; segment-aware clients render every visible run.
    normalized = normalized_segments[0] if len(normalized_segments) == 1 else []

    return {
        "contractVersion": ROUTE_PREVIEW_CONTRACT_VERSION,
        "source": source,
        "points": normalized,
        "segments": normalized_segments,
        "pointCount": len(coords),
        "bounds": {
            "minLat": round(min_lat, 9),
            "minLon": round(min_lon, 9),
            "maxLat": round(max_lat, 9),
            "maxLon": round(max_lon, 9),
        },
        "placeLabel": place_label,
        "fallbackReason": None,
        "privacy": {
            "redactedGps": bool((privacy or {}).get("redactGps")),
        },
    }


def _ride_route_preview(ride: dict[str, Any], privacy: dict[str, Any]) -> Optional[dict[str, Any]]:
    points = ride.get("_route_preview_points")
    if points is None:
        gps_track = ride.get("gps_track")
        if gps_track:
            try:
                from .utils.polyline import decode_gps_track
                decoded_points = decode_gps_track(gps_track)
            except Exception:
                decoded_points = []
            if privacy.get("redactGps"):
                points = [
                    {**point, "latitude": None, "longitude": None, "redacted": True}
                    for point in decoded_points
                ]
            else:
                points = decoded_points
    if not isinstance(points, list):
        return None
    return build_route_preview(
        points,
        source="server_gps",
        place_label=_place_label_from_ride(ride),
        privacy=privacy,
        privacy_zones=ride.get("_route_preview_zones") or [],
    )


def infer_activity_event_type(activity_type: Any, target_type: Any = None) -> FeedEventType:
    normalized = str(activity_type or "").strip().lower()
    target = str(target_type or "").strip().lower()
    if normalized in {"follow", "follow_created", "new_follower"}:
        return FeedEventType.follow_created
    if normalized in {"comment", "comment_created"}:
        return FeedEventType.comment_created
    if normalized in {"achievement", "achievement_unlocked"}:
        return FeedEventType.achievement_unlocked
    if normalized in {"record", "record_rank_moved", "rank_moved"}:
        return FeedEventType.record_rank_moved
    if normalized in {"local_legend", "local_legend_moved"}:
        return FeedEventType.local_legend_moved
    if normalized in {"climb", "climb_completed"} or target == "climb":
        return FeedEventType.climb_completed
    if normalized in {"report", "report_resolved"}:
        return FeedEventType.report_resolved
    if normalized in {"ride", "ride_completed"} or target == "ride":
        return FeedEventType.ride_completed
    return FeedEventType.social


def ride_event_type(ride: dict[str, Any]) -> Optional[FeedEventType]:
    status = str(ride.get("processing_status") or "pending")
    if status == "under_review":
        return FeedEventType.ride_under_review
    if status in RIDE_FEED_STATUSES:
        return FeedEventType.ride_completed
    return None


def build_ride_feed_event(
    ride: dict[str, Any],
    user: Optional[dict[str, Any]],
    interactions: Optional[dict[str, Any]],
    privacy: dict[str, Any],
) -> Optional[dict[str, Any]]:
    event_type = ride_event_type(ride)
    if event_type is None:
        return None

    # rides.title (processing default or rider edit) wins; legacy untitled
    # rides keep the filename-stem fallback.
    ride_title = ride.get("title")
    if isinstance(ride_title, str) and ride_title.strip():
        title = ride_title.strip()
    else:
        file_name = ride.get("file_name", "")
        title = file_name.rsplit(".", 1)[0] if file_name else "Ride"
    occurred_at = feed_datetime_iso(ride.get("started_at") or ride.get("created_at"))
    actor = public_rider_ref_dict(user, fallback_id=ride.get("user_id"))

    threshold_state = ride.get("_threshold_economy_state")
    if threshold_state is None:
        threshold_state = ride.get("threshold_economy_state")
    if ride.get("reward_policy") == "threshold_provisional_hold_v1":
        cal_earned = (
            ride.get("_threshold_released_cal", ride.get("cal_earned"))
            if threshold_state == "counted"
            else None
        )
    else:
        cal_earned = ride.get("cal_earned")

    metadata = {
        "distanceM": ride.get("distance_m"),
        "elevationM": ride.get("elevation_gain_m"),
        # DEM-corrected climbing total (projection); null = dash, never zero.
        "elevationCorrectedM": ride.get("elevation_corrected_gain_m"),
        "durationS": ride.get("duration_sec"),
        "status": ride.get("processing_status"),
        "kudosCount": (interactions or {}).get("kudosCount", 0),
        "commentCount": (interactions or {}).get("commentCount", 0),
        "viewerHasKudos": (interactions or {}).get("viewerHasKudos", False),
        "viewerReported": (interactions or {}).get("viewerReported", False),
        "reportStatus": (interactions or {}).get("reportStatus"),
        "visibility": ride.get("visibility") or "public",
        "privacy": privacy,
    }
    if privacy.get("isOwner") is True:
        metadata["dungEarned"] = ride.get("dung_minted")
        metadata["calEarned"] = cal_earned
    if threshold_state in {"held", "counted", "lapsed", "review", "not_counted"}:
        metadata["thresholdEconomyState"] = threshold_state
    media = ride.get("_media") if isinstance(ride.get("_media"), list) else []
    visible_media = [
        item for item in media
        if isinstance(item, dict) and item.get("url")
    ]
    if visible_media:
        metadata["media"] = visible_media
        cover = next((item for item in visible_media if item.get("role") == "cover"), None)
        metadata["primaryMedia"] = cover or visible_media[0]
    route_preview = _ride_route_preview(ride, privacy)
    if route_preview:
        metadata["routePreview"] = route_preview

    target = target_ref_dict("ride", ride.get("id"), label=title, source="feed.ride")
    return {
        "contractVersion": FEED_CONTRACT_VERSION,
        "id": str(ride.get("id")),
        "type": "ride",
        "eventType": event_type.value,
        "title": title,
        "createdAt": occurred_at,
        "occurredAt": occurred_at,
        "status": ride.get("processing_status"),
        "actor": actor,
        "user": actor,
        "target": target,
        "primaryAction": primary_action_for_target("ride").value,
        "viewerCapabilities": capabilities_for_target(
            "ride",
            can_view=True,
            authenticated=interactions is not None,
            is_owner=bool(privacy.get("isOwner")),
            comments_enabled=ride.get("comments_enabled", True) is not False,
            can_report=True,
            can_share=True,
            has_scan_target=True,
        ),
        "metadata": metadata,
        "privacy": privacy,
    }


def build_activity_feed_event(
    activity: dict[str, Any],
    user: Optional[dict[str, Any]],
    *,
    is_owner: bool = False,
) -> dict[str, Any]:
    event_type = infer_activity_event_type(
        activity.get("event_type") or activity.get("activity_type"),
        activity.get("target_type"),
    )
    occurred_at = feed_datetime_iso(activity.get("occurred_at") or activity.get("created_at"))
    actor = public_rider_ref_dict(user, fallback_id=activity.get("user_id"))
    target_type = activity.get("target_type") or event_type.value.split("_", 1)[0]
    target = target_ref_dict(
        target_type,
        activity.get("target_id"),
        label=activity.get("title"),
        source="feed.activity",
    )
    metadata = dict(activity.get("metadata") or {})
    if not is_owner:
        metadata = _without_exact_economy(metadata)

    return {
        "contractVersion": FEED_CONTRACT_VERSION,
        "id": str(activity.get("id")),
        "type": str(target_type or "activity"),
        "eventType": event_type.value,
        "title": activity.get("title") or event_type.value.replace("_", " ").title(),
        "createdAt": occurred_at,
        "occurredAt": occurred_at,
        "actor": actor,
        "user": actor,
        "target": target,
        "primaryAction": primary_action_for_target(target_type).value,
        "viewerCapabilities": capabilities_for_target(
            target_type,
            can_view=True,
            authenticated=True,
            can_report=True,
            can_share=True,
            has_scan_target=str(target_type or "").lower() in {"proof", "scan_tx", "scan_account"},
        ),
        "metadata": metadata,
    }
