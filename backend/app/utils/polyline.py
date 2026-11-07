"""
Polyline encoding/decoding for GPS tracks.

Uses the standard polyline algorithm (same as Google Maps) for lat/lon compression,
with a companion format for elevation and timestamps.

GPS Track Format (stored as JSONB in rides.gps_track):
{
    "polyline": str,          # Encoded lat/lon pairs
    "elevations": [int, ...], # Delta-encoded elevation in decimeters
    "timestamps": [int, ...], # Delta-encoded seconds from start
    "distances": [int, ...],  # Delta-encoded distance in meters
    "elevation_missing_ranges": [[start, count], ...], # Optional v2 mask
    "precision": int,         # Polyline precision (default 5 = ~1m accuracy)
    "version": int            # Format version for future compatibility
}

Compression ratios:
- Raw JSON: ~50 bytes/point → 900KB for 18,000 points
- Polyline: ~3 bytes/point → 54KB for 18,000 points (94% smaller)

Performance:
- Rust implementation: 6-20x faster for encoding, 10-30x faster for decoding
- Controlled via USE_RUST_POLYLINE env var (default: true)
"""

from typing import List, Dict, Tuple, Optional
import json
import math
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Rust polyline control - set USE_RUST_POLYLINE=false to disable
USE_RUST_POLYLINE = os.environ.get("USE_RUST_POLYLINE", "true").lower() == "true"

# Try to import Rust implementation
try:
    import workout_parse
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    if USE_RUST_POLYLINE:
        logger.warning("workout_parse not available - polyline will use Python fallback")


def encode_number(num: int) -> str:
    """Encode a single number using polyline algorithm."""
    # Left-shift the number by 1, invert if negative
    sgn_num = num << 1
    if num < 0:
        sgn_num = ~sgn_num

    # Break into 5-bit chunks
    encoded = []
    while sgn_num >= 0x20:
        encoded.append(chr((0x20 | (sgn_num & 0x1f)) + 63))
        sgn_num >>= 5
    encoded.append(chr(sgn_num + 63))

    return ''.join(encoded)


def decode_number(encoded: str, index: int) -> Tuple[int, int]:
    """Decode a single number from polyline string, returning (value, new_index)."""
    result = 0
    shift = 0

    while True:
        b = ord(encoded[index]) - 63
        index += 1
        result |= (b & 0x1f) << shift
        shift += 5
        if b < 0x20:
            break

    # Invert if odd
    if result & 1:
        result = ~result
    result >>= 1

    return result, index


def encode_polyline(points: List[Tuple[float, float]], precision: int = 5) -> str:
    """
    Encode a list of (lat, lon) points to a polyline string.

    Args:
        points: List of (latitude, longitude) tuples
        precision: Number of decimal places (default 5 = ~1m accuracy)

    Returns:
        Encoded polyline string
    """
    if not points:
        return ""

    factor = 10 ** precision
    encoded = []
    prev_lat = 0
    prev_lon = 0

    for lat, lon in points:
        curr_lat = round(lat * factor)
        curr_lon = round(lon * factor)

        encoded.append(encode_number(curr_lat - prev_lat))
        encoded.append(encode_number(curr_lon - prev_lon))

        prev_lat = curr_lat
        prev_lon = curr_lon

    return ''.join(encoded)


def decode_polyline(encoded: str, precision: int = 5) -> List[Tuple[float, float]]:
    """
    Decode a polyline string to a list of (lat, lon) points.

    Args:
        encoded: Polyline string
        precision: Precision used during encoding (default 5)

    Returns:
        List of (latitude, longitude) tuples
    """
    if not encoded:
        return []

    factor = 10 ** precision
    points = []
    index = 0
    lat = 0
    lon = 0

    while index < len(encoded):
        lat_delta, index = decode_number(encoded, index)
        lon_delta, index = decode_number(encoded, index)
        lat += lat_delta
        lon += lon_delta
        points.append((lat / factor, lon / factor))

    return points


def encode_delta_array(values: List[int]) -> List[int]:
    """Delta-encode an array of integers for compact storage."""
    if not values:
        return []

    result = [values[0]]
    for i in range(1, len(values)):
        result.append(values[i] - values[i - 1])
    return result


def decode_delta_array(deltas: List[int]) -> List[int]:
    """Decode a delta-encoded array back to absolute values."""
    if not deltas:
        return []

    result = [deltas[0]]
    for i in range(1, len(deltas)):
        result.append(result[-1] + deltas[i])
    return result


def _finite_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _ranges_from_indices(indices: List[int]) -> List[List[int]]:
    if not indices:
        return []

    ranges: List[List[int]] = []
    start = prev = indices[0]
    for idx in indices[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        ranges.append([start, prev - start + 1])
        start = prev = idx
    ranges.append([start, prev - start + 1])
    return ranges


def _expand_missing_ranges(ranges: object, point_count: int) -> set[int]:
    missing: set[int] = set()
    if not isinstance(ranges, list):
        return missing

    for raw_range in ranges:
        if not isinstance(raw_range, (list, tuple)) or len(raw_range) < 2:
            continue
        try:
            start = int(raw_range[0])
            count = int(raw_range[1])
        except (TypeError, ValueError):
            continue
        if start < 0 or count <= 0:
            continue
        end = min(point_count, start + count)
        missing.update(range(start, end))
    return missing


def _encode_gps_track_python(
    points: List[Dict],
    precision: int = 5,
) -> Dict:
    """
    Python implementation of GPS track encoding.

    Args:
        points: List of GPS point dicts with keys:
            - latitude: float
            - longitude: float
            - elevation_m: Optional[float]
            - timestamp: Optional[str or int]
            - distance_m: Optional[float]
            - sequence_num: Optional[int]
        precision: Polyline precision (default 5)

    Returns:
        Compact track dict ready for JSONB storage
    """
    if not points:
        return {
            "polyline": "",
            "elevations": [],
            "timestamps": [],
            "distances": [],
            "precision": precision,
            "version": 2,
        }

    # Sort by sequence_num if available
    if "sequence_num" in points[0]:
        points = sorted(points, key=lambda p: p.get("sequence_num", 0))

    # Extract coordinates
    coords = [(p["latitude"], p["longitude"]) for p in points]
    polyline = encode_polyline(coords, precision)

    # Extract elevations (convert to decimeters for integer storage)
    elevations = []
    missing_elevation_indices = []
    for i, p in enumerate(points):
        elev = _finite_float(p.get("elevation_m"))
        if elev is None:
            elevations.append(0)  # placeholder masked by elevation_missing_ranges
            missing_elevation_indices.append(i)
        else:
            elevations.append(round(elev * 10))  # decimeters

    # Extract timestamps as seconds from start
    timestamps = []
    start_time = None
    for p in points:
        ts = p.get("timestamp")
        if ts is not None:
            # Handle both int seconds and ISO string
            if isinstance(ts, int):
                sec = ts
            elif isinstance(ts, str):
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if start_time is None:
                        start_time = dt
                    sec = int((dt - start_time).total_seconds())
                except:
                    sec = len(timestamps)
            else:
                sec = len(timestamps)
            timestamps.append(sec)
        else:
            timestamps.append(len(timestamps))  # Use index as fallback

    # Extract distances (meters as integers)
    distances = []
    for p in points:
        dist = p.get("distance_m")
        if dist is not None:
            distances.append(round(dist))
        else:
            distances.append(0)

    encoded = {
        "polyline": polyline,
        "elevations": encode_delta_array(elevations),
        "timestamps": encode_delta_array(timestamps),
        "distances": encode_delta_array(distances),
        "precision": precision,
        "version": 2,
    }
    missing_ranges = _ranges_from_indices(missing_elevation_indices)
    if missing_ranges:
        encoded["elevation_missing_ranges"] = missing_ranges
    return encoded


def _decode_gps_track_python(track: Dict) -> List[Dict]:
    """
    Python implementation of GPS track decoding.

    Args:
        track: Compact track dict from encode_gps_track

    Returns:
        List of GPS point dicts
    """
    if not track or not track.get("polyline"):
        return []

    precision = track.get("precision", 5)
    coords = decode_polyline(track["polyline"], precision)

    elevations = decode_delta_array(track.get("elevations", []))
    timestamps = decode_delta_array(track.get("timestamps", []))
    distances = decode_delta_array(track.get("distances", []))
    missing_elevation_indices = _expand_missing_ranges(
        track.get("elevation_missing_ranges"),
        len(coords),
    )

    # Pad arrays if shorter than coords
    while len(elevations) < len(coords):
        elevations.append(0)
    while len(timestamps) < len(coords):
        timestamps.append(len(timestamps))
    while len(distances) < len(coords):
        distances.append(0)

    points = []
    for i, (lat, lon) in enumerate(coords):
        # Handle elevation - stored in decimeters, convert back to meters
        # Note: elevation can be 0 (sea level) or negative (below sea level)
        elev_dm = elevations[i] if i < len(elevations) else None
        elev_m = None if i in missing_elevation_indices else (
            elev_dm / 10.0 if elev_dm is not None else None
        )

        # Handle distance - can be 0 at the start of the ride
        dist_m = distances[i] if i < len(distances) else None

        points.append({
            "sequence_num": i,
            "latitude": lat,
            "longitude": lon,
            "elevation_m": elev_m,
            "timestamp": timestamps[i] if i < len(timestamps) else i,
            "distance_m": dist_m,
        })

    return points


def _to_legacy_timestamp(value: object, fallback: int) -> int:
    """Normalize legacy timestamp values to a numeric offset in seconds."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return fallback
        # Numeric string
        try:
            return int(float(raw))
        except ValueError:
            pass
        # ISO timestamp string - use Unix seconds as a stable numeric fallback.
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return fallback
    return fallback


def _normalize_legacy_points(raw_points: List[Dict]) -> List[Dict]:
    """Normalize pre-polyline GPS formats into the canonical point schema."""
    normalized: List[Dict] = []
    for i, point in enumerate(raw_points):
        if not isinstance(point, dict):
            continue
        lat = point.get("latitude", point.get("lat"))
        lon = point.get("longitude", point.get("lon", point.get("lng")))
        if lat is None or lon is None:
            continue

        elev = _finite_float(point.get("elevation_m", point.get("elevation", point.get("ele"))))
        dist = point.get("distance_m", point.get("distance", point.get("dist_m")))
        ts = _to_legacy_timestamp(point.get("timestamp", point.get("t")), i)
        seq_raw = point.get("sequence_num", point.get("sequenceNum", i))
        try:
            seq = int(seq_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            seq = i

        normalized.append({
            "sequence_num": seq,
            "latitude": float(lat),
            "longitude": float(lon),
            "elevation_m": elev,
            "timestamp": ts,
            "distance_m": float(dist) if isinstance(dist, (int, float)) else None,
        })

    return normalized


def estimate_size(points: List[Dict]) -> Dict[str, int]:
    """
    Estimate storage sizes for comparison.

    Returns:
        Dict with 'raw_bytes' and 'encoded_bytes'
    """
    # Raw JSON size
    raw = json.dumps(points)
    raw_bytes = len(raw.encode('utf-8'))

    # Encoded size (always use Python for consistency in size estimation)
    encoded = _encode_gps_track_python(points)
    encoded_json = json.dumps(encoded)
    encoded_bytes = len(encoded_json.encode('utf-8'))

    return {
        "raw_bytes": raw_bytes,
        "encoded_bytes": encoded_bytes,
        "compression_ratio": round(encoded_bytes / raw_bytes, 3) if raw_bytes else 0,
        "savings_pct": round((1 - encoded_bytes / raw_bytes) * 100, 1) if raw_bytes else 0,
    }


# =============================================================================
# Public API - delegates to Rust when enabled, Python fallback otherwise
# =============================================================================

def encode_gps_track(points: List[Dict], precision: int = 5) -> Dict:
    """
    Encode a full GPS track to compact format.

    Uses Rust implementation when USE_RUST_POLYLINE=true (default).
    Falls back to Python if Rust module unavailable.

    Args:
        points: List of GPS point dicts with keys:
            - latitude: float
            - longitude: float
            - elevation_m: Optional[float]
            - timestamp: Optional[str or int] (Rust handles both)
            - distance_m: Optional[float]
            - sequence_num: Optional[int]
        precision: Polyline precision (default 5)

    Returns:
        Compact track dict ready for JSONB storage
    """
    if USE_RUST_POLYLINE and RUST_AVAILABLE:
        return workout_parse.py_encode_gps_track(points, precision)
    return _encode_gps_track_python(points, precision)


def decode_gps_track(track: Dict) -> List[Dict]:
    """
    Decode a compact GPS track back to full point dicts.

    Always uses Python implementation - native dict creation is faster
    than PyO3 cross-language overhead for many small objects.

    Args:
        track: Compact track dict from encode_gps_track

    Returns:
        List of GPS point dicts
    """
    # Backwards compatibility for legacy formats stored before polyline encoding.
    if isinstance(track, list):
        return _normalize_legacy_points(track)
    if isinstance(track, dict) and "polyline" not in track:
        if isinstance(track.get("points"), list):
            return _normalize_legacy_points(track["points"])
        if isinstance(track.get("gps_track"), list):
            return _normalize_legacy_points(track["gps_track"])
        if "latitude" in track or "lat" in track:
            return _normalize_legacy_points([track])
        return []

    # Python is faster for decode due to native dict creation
    # (Rust PyO3 overhead is ~16x slower for 18k dicts)
    return _decode_gps_track_python(track)
