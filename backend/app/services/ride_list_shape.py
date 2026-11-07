"""Compact owner-only relief from stored GPS and frozen economic authority.

No stream reads or economic writes. Distances remain in the ride's coordinate
system so counted intervals align with the same relief at every glyph size.
"""
from bisect import bisect_right
from datetime import datetime
import math
from typing import Any, Optional

from .elevation_correction import decode_correction_profile
from .ride_privacy import haversine_meters


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _interpolate(xs: list[float], ys: list[float], x: float) -> float:
    index = min(max(bisect_right(xs, x) - 1, 0), len(xs) - 2)
    fraction = (x - xs[index]) / (xs[index + 1] - xs[index])
    return ys[index] + fraction * (ys[index + 1] - ys[index])


def _legacy_has_recorded_times(stored: Any) -> bool:
    """Map decoding invents sample-index times; those cannot locate CAL."""
    raw = stored
    if isinstance(raw, dict):
        if isinstance(raw.get("points"), list):
            raw = raw["points"]
        elif isinstance(raw.get("gps_track"), list):
            raw = raw["gps_track"]
        else:
            raw = [raw]
    if not isinstance(raw, list) or not raw:
        return False
    for point in raw:
        if not isinstance(point, dict):
            return False
        value = point.get("timestamp", point.get("t"))
        if _number(value) is not None:
            continue
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            return False
    return True


def prepare_ride_shape_points(ride: dict, points: list[dict]) -> list[dict]:
    """Resolve distance and DEM by original index before any privacy trimming."""
    device_distances = [_number(point.get("distance_m")) for point in points]
    if not any(distance is not None and distance > 0 for distance in device_distances):
        # Older projections omit distance. Derive one axis from their stored
        # coordinates, shared by relief and intervals, without changing totals.
        measured = []
        previous = None
        distance = 0.0
        for point in points:
            lat, lon = _number(point.get("latitude")), _number(point.get("longitude"))
            if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
                return []
            if previous is not None:
                distance += haversine_meters(*previous, lat, lon)
            measured.append({**point, "distance_m": distance})
            previous = (lat, lon)
        points = measured
    stored = ride.get("gps_track")
    packed = stored if isinstance(stored, dict) and "polyline" in stored else None
    corrected = (
        decode_correction_profile(ride.get('elevation_correction_profile'))
        if ride.get('elevation_correction_status') == 'corrected' else []
    )
    prepared = []
    for index, point in enumerate(points):
        distance = _number(point.get('distance_m'))
        elevation = _number(corrected[index]) if index < len(corrected) else None
        if elevation is None:
            if packed is None or index < len(packed.get('elevations') or []):
                elevation = _number(point.get('elevation_m'))
        prepared.append({**point, 'distance_m': distance, 'elevation_m': elevation})
    return prepared


def build_ride_list_shape(ride: dict, points: list[dict], steps: list[dict]) -> dict:
    points = prepare_ride_shape_points(ride, points)
    stored = ride.get("gps_track")
    packed = stored if isinstance(stored, dict) and "polyline" in stored else None
    distances, elevations = [], []
    for point in points:
        distance, elevation = point['distance_m'], point['elevation_m']
        if distance is None or distance < 0 or elevation is None:
            continue
        if distances and distance < distances[-1]:
            return {}  # A reset distance axis cannot locate a climb honestly.
        if distances and distance == distances[-1]:
            continue
        distances.append(distance)
        elevations.append(elevation)
    if len(distances) < 2 or distances[-1] <= 0:
        return {}
    count = min(64, len(distances))
    profile = []
    for index in range(count):
        distance = distances[0] + (distances[-1] - distances[0]) * index / (count - 1)
        profile.append({'distance_m': distance, 'elevation_m': round(_interpolate(distances, elevations, distance), 1)})

    times, route_distances = [], []
    try:
        start = datetime.fromisoformat(str(ride.get('started_at')).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        start = None
    origin = None
    if packed is not None and packed.get("time_origin"):
        try:
            origin = datetime.fromisoformat(str(packed["time_origin"]).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            pass
    for point in points:
        time = _number(point.get('timestamp'))
        distance = _number(point.get('distance_m'))
        if time is None or distance is None:
            continue
        if time > 100_000_000:
            if start is None:
                continue
            time -= start
        elif packed is not None:
            if origin is None or start is None:
                continue
            time += origin - start
        if times and (time <= times[-1] or distance < route_distances[-1]):
            continue
        times.append(time)
        route_distances.append(distance)
    spans = []
    # The decoder pads absent timestamps for map consumers. Those fabricated
    # indexes are not evidence for a frozen climb's time window.
    if packed is not None and len(packed.get("timestamps") or []) != len(points):
        steps = []
    if stored is not None and packed is None and not _legacy_has_recorded_times(stored):
        steps = []
    for step in steps:
        tribute = _number(step.get('exact_tribute_base_units'))
        begin = _number(step.get('segment_start_offset_s'))
        end = _number(step.get('segment_end_offset_s'))
        if (tribute is None or tribute <= 0 or begin is None or end is None
                or end <= begin or len(times) < 2 or begin < times[0] or end > times[-1]):
            continue
        left = _interpolate(times, route_distances, begin)
        right = _interpolate(times, route_distances, end)
        if distances[0] <= left < right <= distances[-1]:
            span = {'start_distance_m': left, 'end_distance_m': right}
            if step.get('pattern_id'):
                span['pattern_id'] = str(step['pattern_id'])
            spans.append(span)
    return {'elevation_profile': profile, 'counted_spans': spans}
