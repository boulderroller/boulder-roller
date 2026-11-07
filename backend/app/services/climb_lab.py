"""Local-only helpers for the ClimbLab development surface.

The ClimbLab workbench proves data availability, bounded road scans, candidate
review, and canon-ratification readiness without exposing private GPS
coordinates or promoting experimental climb candidates into production flows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib import parse, request


ACTIVITY_EXTENSIONS = {".fit", ".gpx", ".tcx"}
DEFAULT_GARMIN_ACTIVITIES_DIR = Path("/Volumes/GARMIN/Garmin/Activities")
REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_VALIDATION_DIR = REPO_ROOT / "tests" / "validation"
DEFAULT_CLIMB_LAB_REVIEW_STATE_PATH = REPO_ROOT / ".local" / "climb_lab_review_state.json"
_CLIMB_LAB_SUMMARY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_CLIMB_LAB_SCAN_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_CLIMB_LAB_REVIEW_STATE: dict[str, dict[str, Any]] = {}
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_OPEN_TOPO_DATA_ELEVATION_URL = "https://api.opentopodata.org/v1/ned10m"
DEFAULT_OPEN_METEO_ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
CLIMB_LAB_SCAN_PRESETS = {
    "boulder_foothills_north": {
        "label": "Boulder foothills north",
        "description": "A bounded first-pass scan window around north Boulder foothill roads.",
        "bbox": {
            "south": 40.045,
            "west": -105.315,
            "north": 40.075,
            "east": -105.285,
        },
        "default_max_ways": 80,
        "default_max_candidates": 16,
        "default_max_elevation_nodes": 210,
    },
    "philadelphia_manayunk_wall": {
        "label": "Philadelphia: Manayunk Wall",
        "description": "Launch-canon sanity window around Levering Street, Lyceum Avenue, and the Manayunk Wall.",
        "bbox": {
            "south": 40.0185,
            "west": -75.2285,
            "north": 40.0365,
            "east": -75.1965,
        },
        "default_max_ways": 90,
        "default_max_candidates": 18,
        "default_max_elevation_nodes": 240,
    },
    "philadelphia_wissahickon": {
        "label": "Philadelphia: Wissahickon / Roxborough",
        "description": "Launch-canon review window for paved climbs around Wissahickon, Roxborough, and Manayunk approaches.",
        "bbox": {
            "south": 40.015,
            "west": -75.245,
            "north": 40.075,
            "east": -75.175,
        },
        "default_max_ways": 140,
        "default_max_candidates": 28,
        "default_max_elevation_nodes": 360,
    },
}
CLIMB_LAB_REVIEW_ACTIONS = {
    "trim_start": "Move the lower boundary toward the natural start.",
    "trim_finish": "Move the upper boundary toward the natural finish.",
    "merge_through_intersection": "Continue the candidate through the next connected road edge.",
    "suppress": "Hide this candidate from canon ratification until it is explicitly restored.",
    "approve": "Ratify this compiler candidate into canon_climbs v1 when the publish payload is complete.",
}
CLIMB_LAB_REVIEW_DECISIONS = {
    "approve": {
        "state": "approved_for_review",
        "label": "Approved",
        "description": "Tim accepts the line as a canon candidate for the next compiler pass.",
    },
    "needs_work": {
        "state": "needs_work",
        "label": "Needs work",
        "description": "The line is promising, but the boundary, merge, or profile needs another pass.",
    },
    "suppress": {
        "state": "suppressed",
        "label": "Suppress",
        "description": "Do not carry this candidate forward unless it is restored later.",
    },
    "pending": {
        "state": "needs_review",
        "label": "Clear",
        "description": "Remove the saved decision and return the candidate to pending review.",
    },
}
CANON_CONFIDENCE_VALUES = {"needs_review", "low", "medium", "high"}
CANON_REQUIRED_PUBLISH_FIELDS = (
    "compiler_run_mode",
    "candidate_fingerprint",
    "legacy_candidate_fingerprints",
    "display_name",
    "centerline_polyline",
    "centerline_wkt",
    "corridor_wkt",
    "corridor_half_width_m",
    "gate_start_wkt",
    "gate_end_wkt",
    "canonical_profile",
    "length_m",
    "vert_m",
    "avg_gradient_pct",
    "worthiness_score",
    "dem_source",
    "compiler_version",
    "osm_way_refs",
    "corridor_cells",
)


def clear_climb_lab_scan_cache() -> None:
    """Clear ClimbLab's process-local derived summary cache."""
    _CLIMB_LAB_SUMMARY_CACHE.clear()


def _activity_sources() -> list[dict[str, str]]:
    garmin_path = Path(
        os.getenv("CLIMB_LAB_GARMIN_ACTIVITIES_DIR", str(DEFAULT_GARMIN_ACTIVITIES_DIR))
    )
    sources = [
        {
            "id": "garmin_device",
            "label": "Mounted Garmin activities",
            "path": str(garmin_path),
        },
        {
            "id": "repo_validation",
            "label": "Repo validation fixtures",
            "path": str(REPO_VALIDATION_DIR),
        },
    ]

    extra_dirs = os.getenv("CLIMB_LAB_EXTRA_ACTIVITY_DIRS", "")
    for idx, raw_path in enumerate(extra_dirs.split(os.pathsep), start=1):
        path = raw_path.strip()
        if not path:
            continue
        sources.append(
            {
                "id": f"extra_{idx}",
                "label": f"Extra activity directory {idx}",
                "path": path,
            }
        )
    return sources


def _activity_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in ACTIVITY_EXTENSIONS
    )


def _iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _year_from_filename(path: Path) -> str:
    match = re.match(r"(?P<year>19\d{2}|20\d{2})", path.name)
    return match.group("year") if match else "unknown"


def _date_from_filename(path: Path | None) -> str | None:
    if path is None:
        return None
    match = re.match(r"(?P<date>(?:19|20)\d{2}-\d{2}-\d{2})", path.name)
    return match.group("date") if match else None


def _source_summary(*, source_id: str, file_count: int) -> str:
    if file_count == 0:
        return "Available, but no activity files were found here."
    if source_id == "garmin_device":
        return "Mounted device archive. Useful for local climb calibration once map matching exists."
    if source_id == "repo_validation":
        return "Repository fixtures. Useful for repeatable tests and smoke checks."
    return "Extra local corpus source. Useful for expanding calibration coverage."


def _recent_file_payload(files: Iterable[Path], limit: int) -> list[dict[str, Any]]:
    recent = sorted(files, key=lambda path: (path.name, path.stat().st_mtime))[-limit:]
    payload = []
    for path in recent:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        payload.append(
            {
                "name": path.name,
                "extension": path.suffix.lower().lstrip("."),
                "size_bytes": size_bytes,
                "modified_at": _iso_mtime(path),
            }
        )
    return payload


def _file_fingerprint(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        resolved = str(path.resolve())
        return (resolved, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (str(path), 0, 0)


def _parser_cache_id(parser: Any) -> str:
    if parser is None:
        return "default"
    return f"custom:{id(parser)}"


def _cached_activity_summary(
    *,
    kind: str,
    path: Path,
    parser: Any,
    params: tuple[Any, ...],
    builder: Any,
) -> dict[str, Any]:
    cache_key = (
        kind,
        _parser_cache_id(parser),
        *_file_fingerprint(path),
        *params,
    )
    cached = _CLIMB_LAB_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        payload = deepcopy(cached)
        payload["cache_status"] = "hit"
        return payload

    payload = builder()
    cache_payload = deepcopy(payload)
    cache_payload.pop("cache_status", None)
    _CLIMB_LAB_SUMMARY_CACHE[cache_key] = cache_payload
    payload["cache_status"] = "miss"
    return payload


def _cache_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(row.get("cache_status", "unknown") for row in rows)
    return {
        "mode": "process_memory",
        "entries": len(_CLIMB_LAB_SUMMARY_CACHE),
        "hits": statuses.get("hit", 0),
        "misses": statuses.get("miss", 0),
        "unknown": statuses.get("unknown", 0),
        "summary": "Process-local cache keyed by file path, mtime, size, parser, and scan parameters.",
    }


def _bounded_limit(limit: int, *, default: int = 18, maximum: int = 60) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def _duration_label(seconds: float | int | None) -> str:
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _float_values(values: Any) -> list[float]:
    if values is None:
        return []
    out: list[float] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > -500:
            out.append(parsed)
    return out


def _naive_positive_gain(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return sum(max(0.0, values[idx + 1] - values[idx]) for idx in range(len(values) - 1))


def _gain_band(gain_m: float) -> str:
    if gain_m >= 600:
        return "large"
    if gain_m >= 250:
        return "calibration"
    if gain_m >= 100:
        return "light"
    return "low"


def _activity_date_from_name(path: Path) -> str | None:
    return _date_from_filename(path)


def _clean_scalar(value: Any, *, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    text = str(value)
    wrapper = re.fullmatch(r'string\("(?P<value>.*)"\)', text)
    if wrapper:
        return wrapper.group("value")
    return text or fallback


def _series_values(values: Any) -> list[float | None]:
    if values is None:
        return []
    out: list[float | None] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if parsed <= -500:
            out.append(None)
            continue
        out.append(parsed)
    return out


def _smoothed(values: list[float | None], *, radius: int = 2) -> list[float | None]:
    smoothed: list[float | None] = []
    for idx in range(len(values)):
        window = [
            value
            for value in values[max(0, idx - radius) : idx + radius + 1]
            if value is not None
        ]
        smoothed.append(sum(window) / len(window) if window else None)
    return smoothed


def _offset_label(start_ms: float | None, offset_ms: float | None) -> str:
    if start_ms is None or offset_ms is None:
        return "unknown"
    return _duration_label(max(0, (offset_ms - start_ms) / 1000))


def _signal_confidence(*, gain_m: float, distance_m: float, avg_grade_pct: float) -> str:
    if gain_m >= 120 and distance_m >= 1000 and avg_grade_pct >= 4:
        return "high"
    if gain_m >= 60 and distance_m >= 600 and avg_grade_pct >= 3:
        return "medium"
    return "exploratory"


RIDEABLE_OSM_HIGHWAYS = {
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "cycleway",
    "living_street",
}

ROAD_SCAN_OSM_HIGHWAYS = {
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "cycleway",
    "service",
    "living_street",
}

NON_RIDEABLE_OSM_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "footway",
    "steps",
    "pedestrian",
    "construction",
    "proposed",
}


def _slug(value: Any) -> str:
    text = str(value or "edge").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return slug or "edge"


def _tags(item: dict[str, Any]) -> dict[str, Any]:
    tags = item.get("tags")
    return tags if isinstance(tags, dict) else {}


def _way_highway(way: dict[str, Any]) -> str:
    return str(_tags(way).get("highway") or way.get("highway") or "").strip().lower()


def _way_name(way: dict[str, Any]) -> str | None:
    name = _tags(way).get("name") or way.get("name")
    if name is None:
        return None
    cleaned = str(name).strip()
    return cleaned or None


def _is_rideable_named_way(way: dict[str, Any]) -> bool:
    highway = _way_highway(way)
    if highway in NON_RIDEABLE_OSM_HIGHWAYS:
        return False
    return bool(_way_name(way) and highway in RIDEABLE_OSM_HIGHWAYS)


def _node_id(value: Any) -> str:
    return str(value)


def _node_name(node: dict[str, Any], node_id: str) -> str:
    name = _tags(node).get("name") or node.get("name")
    return str(name).strip() if name else f"node:{node_id}"


def _node_refs(way: dict[str, Any]) -> list[str]:
    raw_refs = way.get("nodes") or way.get("node_refs") or []
    return [_node_id(ref) for ref in raw_refs if ref is not None]


def _node_lat_lon(node: dict[str, Any]) -> tuple[float, float] | None:
    lat = node.get("lat")
    lon = node.get("lon")
    if lat is None:
        lat = node.get("latitude")
    if lon is None:
        lon = node.get("longitude")
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    radius_m = 6_371_000
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    h = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * radius_m * asin(sqrt(h))


def _segment_distance_m(
    *,
    first_node: dict[str, Any],
    second_node: dict[str, Any],
) -> float:
    first_lat_lon = _node_lat_lon(first_node)
    second_lat_lon = _node_lat_lon(second_node)
    if first_lat_lon is None or second_lat_lon is None:
        return 0.0
    return _haversine_m(first_lat_lon, second_lat_lon)


def _node_elevation_m(node: dict[str, Any]) -> float | None:
    elevation = node.get("elevation_m")
    if elevation is None:
        elevation = _tags(node).get("ele")
    try:
        return float(elevation)
    except (TypeError, ValueError):
        return None


def _edge_samples_for_nodes(
    node_ids: list[str],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    distance_m = 0.0
    previous_node: dict[str, Any] | None = None
    for idx, node_id in enumerate(node_ids):
        node = nodes_by_id[node_id]
        if previous_node is not None:
            distance_m += _segment_distance_m(
                first_node=previous_node,
                second_node=node,
            )
        elevation_m = _node_elevation_m(node)
        sample: dict[str, float] = {"distance_m": round(distance_m, 1)}
        if elevation_m is not None:
            sample["elevation_m"] = round(elevation_m, 1)
        samples.append(sample)
        previous_node = node
        if idx == len(node_ids) - 1 and len(samples) == 1:
            samples[0]["distance_m"] = 0.0
    return samples


def _split_positions_for_way(
    node_refs: list[str],
    split_node_ids: set[str],
) -> list[int]:
    positions = {0, len(node_refs) - 1}
    for idx, node_id in enumerate(node_refs):
        if node_id in split_node_ids:
            positions.add(idx)
    return sorted(positions)


def build_climb_lab_road_graph_edges(
    graph: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize OSM-like ways into intersection-to-intersection road edges."""
    nodes_by_id = {
        _node_id(node.get("id")): node
        for node in graph.get("nodes", [])
        if node.get("id") is not None
    }
    rideable_ways = [
        way
        for way in graph.get("ways", [])
        if _is_rideable_named_way(way)
        and len([node_id for node_id in _node_refs(way) if node_id in nodes_by_id]) >= 2
    ]
    node_usage = Counter(
        node_id
        for way in rideable_ways
        for node_id in set(_node_refs(way))
        if node_id in nodes_by_id
    )
    split_node_ids = {node_id for node_id, count in node_usage.items() if count > 1}

    edges: list[dict[str, Any]] = []
    for way in rideable_ways:
        road_name = _way_name(way)
        if road_name is None:
            continue
        refs = [node_id for node_id in _node_refs(way) if node_id in nodes_by_id]
        split_positions = _split_positions_for_way(refs, split_node_ids)
        part_idx = 1
        for start_pos, end_pos in zip(split_positions, split_positions[1:]):
            segment_node_ids = refs[start_pos : end_pos + 1]
            if len(segment_node_ids) < 2:
                continue
            samples = _edge_samples_for_nodes(segment_node_ids, nodes_by_id)
            distance_m = samples[-1]["distance_m"] if samples else 0.0
            if distance_m <= 0:
                continue
            start_node_id = segment_node_ids[0]
            end_node_id = segment_node_ids[-1]
            source_way_id = str(way.get("id") or f"way-{len(edges) + 1}")
            edges.append(
                {
                    "edge_id": f"{_slug(road_name)}-{_slug(source_way_id)}-{part_idx}",
                    "source_way_id": source_way_id,
                    "road_name": road_name,
                    "highway": _way_highway(way),
                    "from_intersection": _node_name(nodes_by_id[start_node_id], start_node_id),
                    "to_intersection": _node_name(nodes_by_id[end_node_id], end_node_id),
                    "from_node_id": start_node_id,
                    "to_node_id": end_node_id,
                    "node_count": len(segment_node_ids),
                    "distance_m": round(distance_m, 1),
                    "samples": samples,
                    "elevation_profile_status": (
                        "ready"
                        if all("elevation_m" in sample for sample in samples)
                        else "missing"
                    ),
                }
            )
            part_idx += 1
    return edges


def _redacted_road_graph_edge(edge: dict[str, Any]) -> dict[str, Any]:
    samples = edge.get("samples") or []
    return {
        "edge_id": edge.get("edge_id"),
        "source_way_id": edge.get("source_way_id"),
        "road_name": edge.get("road_name"),
        "highway": edge.get("highway"),
        "from_intersection": edge.get("from_intersection"),
        "to_intersection": edge.get("to_intersection"),
        "node_count": edge.get("node_count"),
        "distance_m": edge.get("distance_m"),
        "profile_sample_count": len(samples),
        "sample_distances_m": [sample.get("distance_m") for sample in samples],
        "elevation_profile_status": edge.get("elevation_profile_status"),
    }


def _fixture_osm_like_road_graph() -> dict[str, Any]:
    return {
        "source": "fixture_osm_like_road_graph",
        "nodes": [
            {"id": "creek", "name": "Creek Road", "lat": 40.0, "lon": -105.0, "elevation_m": 1580},
            {"id": "linden-mid-1", "lat": 40.0, "lon": -104.998, "elevation_m": 1610},
            {"id": "switchback", "name": "Switchback Lane", "lat": 40.0, "lon": -104.996, "elevation_m": 1665},
            {"id": "switchback-side", "lat": 40.001, "lon": -104.996, "elevation_m": 1667},
            {"id": "linden-mid-2", "lat": 40.0, "lon": -104.994, "elevation_m": 1698},
            {"id": "ridgecrest", "name": "Ridgecrest Road", "lat": 40.0, "lon": -104.992, "elevation_m": 1732},
            {"id": "canyon-mid", "lat": 40.001, "lon": -104.991, "elevation_m": 1760},
            {"id": "water-tank", "name": "Water Tank", "lat": 40.002, "lon": -104.99, "elevation_m": 1776},
            {"id": "ridge-west", "lat": 39.999, "lon": -104.993, "elevation_m": 1735},
            {"id": "ridge-east", "lat": 40.001, "lon": -104.991, "elevation_m": 1736},
            {"id": "service-dead-end", "lat": 40.003, "lon": -104.99, "elevation_m": 1780},
        ],
        "ways": [
            {
                "id": "way-linden",
                "tags": {"highway": "residential", "name": "Linden Drive"},
                "nodes": ["creek", "linden-mid-1", "switchback", "linden-mid-2", "ridgecrest"],
            },
            {
                "id": "way-ridgecrest",
                "tags": {"highway": "residential", "name": "Ridgecrest Road"},
                "nodes": ["ridge-west", "ridgecrest", "ridge-east"],
            },
            {
                "id": "way-switchback",
                "tags": {"highway": "residential", "name": "Switchback Lane"},
                "nodes": ["switchback", "switchback-side"],
            },
            {
                "id": "way-canyon",
                "tags": {"highway": "residential", "name": "Canyon Spur"},
                "nodes": ["ridgecrest", "canyon-mid", "water-tank"],
            },
            {
                "id": "way-unnamed",
                "tags": {"highway": "service"},
                "nodes": ["water-tank", "service-dead-end"],
            },
            {
                "id": "way-steps",
                "tags": {"highway": "steps", "name": "Trail Steps"},
                "nodes": ["ridge-east", "service-dead-end"],
            },
        ],
    }


def build_climb_lab_road_graph_summary() -> dict[str, Any]:
    graph = _fixture_osm_like_road_graph()
    edges = build_climb_lab_road_graph_edges(graph)
    redacted_edges = [_redacted_road_graph_edge(edge) for edge in edges]
    intersections = sorted(
        {
            value
            for edge in redacted_edges
            for value in (edge.get("from_intersection"), edge.get("to_intersection"))
            if value
        }
    )
    ready_edges = [
        edge
        for edge in redacted_edges
        if edge.get("elevation_profile_status") == "ready"
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": graph["source"],
        "privacy_mode": "no_coordinates_no_raw_trace",
        "model": "osm_like_intersection_edge_graph_v0",
        "guardrails": [
            "Road graph input is a fixture in this slice.",
            "Endpoint output redacts coordinate fields and raw geometry.",
            "Edges are candidate inputs only; they are not official climbs.",
        ],
        "totals": {
            "nodes": len(graph["nodes"]),
            "ways": len(graph["ways"]),
            "normalized_edges": len(redacted_edges),
            "intersections": len(intersections),
            "elevation_ready_edges": len(ready_edges),
        },
        "intersections": intersections,
        "edges": redacted_edges,
    }


def _scan_preset(preset_id: str) -> dict[str, Any]:
    return CLIMB_LAB_SCAN_PRESETS.get(preset_id) or CLIMB_LAB_SCAN_PRESETS[
        "boulder_foothills_north"
    ]


def _bounded_scan_limit(value: int, *, default: int, maximum: int) -> int:
    if value <= 0:
        return default
    return min(value, maximum)


def _overpass_query_for_preset(preset: dict[str, Any]) -> str:
    bbox = preset["bbox"]
    return (
        "[out:json][timeout:20];"
        f"way[\"highway\"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});"
        "out body;>;out skel qt;"
    )


def _fetch_overpass_payload(preset: dict[str, Any], *, timeout_s: int = 30) -> dict[str, Any]:
    endpoint = os.getenv("CLIMB_LAB_OVERPASS_URL", DEFAULT_OVERPASS_URL)
    query = parse.urlencode({"data": _overpass_query_for_preset(preset)})
    req = request.Request(
        f"{endpoint}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "BoulderRoller-ClimbLab/0.1 (local dev scan)",
        },
    )
    with request.urlopen(req, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _local_overpass_cache_path(preset_id: str) -> Path:
    override = os.getenv("CLIMB_LAB_OVERPASS_CACHE_PATH")
    if override:
        return Path(override)
    return Path(f"/tmp/climb-lab-overpass-{preset_id.replace('_', '-')}.json")


def _load_local_overpass_cache(preset_id: str) -> dict[str, Any] | None:
    path = _local_overpass_cache_path(preset_id)
    if not path.exists() or not path.is_file():
        return None
    return json.loads(path.read_text())


def _is_scan_road_way(way: dict[str, Any]) -> bool:
    return _is_rideable_named_way(way) and _way_highway(way) in ROAD_SCAN_OSM_HIGHWAYS


def _way_refs_in_graph(
    way: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    return [node_id for node_id in _node_refs(way) if node_id in nodes_by_id]


def _way_geometry_metrics(
    way: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    refs = _way_refs_in_graph(way, nodes_by_id)
    distance_m = 0.0
    lats: list[float] = []
    lons: list[float] = []
    for node_id in refs:
        lat_lon = _node_lat_lon(nodes_by_id[node_id])
        if lat_lon is None:
            continue
        lats.append(lat_lon[0])
        lons.append(lat_lon[1])
    for first_id, second_id in zip(refs, refs[1:]):
        first_lat_lon = _node_lat_lon(nodes_by_id[first_id])
        second_lat_lon = _node_lat_lon(nodes_by_id[second_id])
        if first_lat_lon is not None and second_lat_lon is not None:
            distance_m += _haversine_m(first_lat_lon, second_lat_lon)
    east_west_span = max(lons) - min(lons) if lons else 0.0
    north_south_span = max(lats) - min(lats) if lats else 0.0
    return {
        "distance_m": distance_m,
        "east_west_span": abs(east_west_span),
        "north_south_span": abs(north_south_span),
    }


def _scan_way_score(
    way: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> float:
    metrics = _way_geometry_metrics(way, nodes_by_id)
    highway_weight = {
        "primary": 1.45,
        "secondary": 1.4,
        "tertiary": 1.35,
        "unclassified": 1.15,
        "residential": 1.1,
        "living_street": 1.0,
        "cycleway": 1.0,
        "service": 0.9,
    }.get(_way_highway(way), 0.85)
    orientation_bonus = 1 + min(
        1.6,
        metrics["east_west_span"] / max(metrics["north_south_span"], 0.00001),
    )
    return metrics["distance_m"] * highway_weight * orientation_bonus


def _rank_scan_ways(
    ways: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    scan_road_ways = [way for way in ways if _is_scan_road_way(way)]
    candidate_ways = scan_road_ways or [way for way in ways if _is_rideable_named_way(way)]
    return sorted(
        candidate_ways,
        key=lambda way: (_scan_way_score(way, nodes_by_id), _way_name(way) or ""),
        reverse=True,
    )


def _simplified_scan_refs_by_way(
    selected_ways: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    *,
    max_elevation_nodes: int,
) -> dict[str, list[str]]:
    original_refs_by_way = {
        str(way.get("id")): _way_refs_in_graph(way, nodes_by_id)
        for way in selected_ways
        if way.get("id") is not None
    }
    node_usage = Counter(
        node_id
        for refs in original_refs_by_way.values()
        for node_id in set(refs)
    )
    split_node_ids = {node_id for node_id, count in node_usage.items() if count > 1}
    required_refs_by_way: dict[str, list[str]] = {}
    selected_node_ids: set[str] = set()
    for way in selected_ways:
        way_id = str(way.get("id"))
        refs = original_refs_by_way.get(way_id) or []
        required_refs = [
            node_id
            for idx, node_id in enumerate(refs)
            if idx == 0 or idx == len(refs) - 1 or node_id in split_node_ids
        ]
        if len(required_refs) < 2:
            required_refs = refs[:2]
        required_refs_by_way[way_id] = required_refs
        selected_node_ids.update(required_refs)

    if len(selected_node_ids) >= max_elevation_nodes:
        return {
            way_id: [node_id for node_id in refs if node_id in selected_node_ids]
            for way_id, refs in original_refs_by_way.items()
        }

    for way in selected_ways:
        way_id = str(way.get("id"))
        refs = original_refs_by_way.get(way_id) or []
        if len(refs) <= 2:
            continue
        target_samples = min(8, max(2, round(len(refs) / 18)))
        stride = max(1, len(refs) // target_samples)
        for node_id in refs[::stride]:
            if len(selected_node_ids) >= max_elevation_nodes:
                break
            selected_node_ids.add(node_id)
        if len(selected_node_ids) >= max_elevation_nodes:
            break

    refs_by_way: dict[str, list[str]] = {}
    for way_id, refs in original_refs_by_way.items():
        simplified_refs = [node_id for node_id in refs if node_id in selected_node_ids]
        if len(simplified_refs) >= 2:
            refs_by_way[way_id] = simplified_refs
    return refs_by_way


def _overpass_payload_to_graph(
    payload: dict[str, Any],
    *,
    max_ways: int,
    max_elevation_nodes: int,
) -> dict[str, Any]:
    nodes_by_id = {
        str(element.get("id")): {
            "id": str(element.get("id")),
            "lat": element.get("lat"),
            "lon": element.get("lon"),
            "tags": element.get("tags") or {},
        }
        for element in payload.get("elements", [])
        if element.get("type") == "node" and element.get("id") is not None
    }
    ways = [
        {
            "id": str(element.get("id")),
            "tags": element.get("tags") or {},
            "nodes": [str(node_id) for node_id in element.get("nodes") or []],
        }
        for element in payload.get("elements", [])
        if element.get("type") == "way" and element.get("id") is not None
    ]
    rideable_ways = [way for way in ways if _is_rideable_named_way(way)]
    scan_road_ways = [way for way in rideable_ways if _is_scan_road_way(way)]
    selected_ways = _rank_scan_ways(ways, nodes_by_id)[:max_ways]
    refs_by_way = _simplified_scan_refs_by_way(
        selected_ways,
        nodes_by_id,
        max_elevation_nodes=max_elevation_nodes,
    )
    selected_ways = [
        {**way, "nodes": refs_by_way.get(str(way.get("id")), [])}
        for way in selected_ways
        if len(refs_by_way.get(str(way.get("id")), [])) >= 2
    ]
    referenced_node_ids = {
        node_id
        for way in selected_ways
        for node_id in way.get("nodes") or []
        if node_id in nodes_by_id
    }
    return {
        "source": "overpass_osm_live",
        "nodes": [nodes_by_id[node_id] for node_id in sorted(referenced_node_ids)],
        "ways": selected_ways,
        "source_counts": {
            "elements": len(payload.get("elements", [])),
            "ways": len(ways),
            "nodes": len(nodes_by_id),
            "rideable_named_ways": len(rideable_ways),
            "scan_road_ways": len(scan_road_ways),
            "selected_ways": len(selected_ways),
            "selected_elevation_nodes": len(referenced_node_ids),
            "max_elevation_nodes": max_elevation_nodes,
            "selection_strategy": "ranked_named_roads_simplified_to_elevation_budget",
        },
    }


def _node_lat_lon_for_scan(node: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return float(node["lat"]), float(node["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def _local_elevation_cache_path() -> Path:
    override = os.getenv("CLIMB_LAB_ELEVATION_CACHE_PATH")
    if override:
        return Path(override)
    return Path("/tmp/climb-lab-elevations-by-osm-node.json")


def _load_local_elevation_cache() -> dict[str, float]:
    path = _local_elevation_cache_path()
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    elevations: dict[str, float] = {}
    for node_id, elevation in payload.items():
        try:
            elevations[str(node_id)] = float(elevation)
        except (TypeError, ValueError):
            continue
    return elevations


def _write_local_elevation_cache(elevations_by_node_id: dict[str, float]) -> None:
    path = _local_elevation_cache_path()
    path.write_text(
        json.dumps(
            {node_id: round(float(elevation), 3) for node_id, elevation in sorted(elevations_by_node_id.items())},
            sort_keys=True,
        )
    )


def _scan_elevation_rows(nodes: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    return [
        (str(node["id"]), lat_lon[0], lat_lon[1])
        for node in nodes
        if node.get("id") is not None
        for lat_lon in [_node_lat_lon_for_scan(node)]
        if lat_lon is not None
    ]


def _fetch_open_topodata_elevations(
    rows: list[tuple[str, float, float]],
    *,
    timeout_s: int = 20,
    chunk_size: int = 80,
) -> dict[str, float]:
    endpoint = os.getenv("CLIMB_LAB_OPEN_TOPO_DATA_URL", DEFAULT_OPEN_TOPO_DATA_ELEVATION_URL)
    elevations: dict[str, float] = {}
    for idx in range(0, len(rows), chunk_size):
        chunk = rows[idx : idx + chunk_size]
        if not chunk:
            continue
        query = parse.urlencode(
            {"locations": "|".join(f"{row[1]},{row[2]}" for row in chunk)}
        )
        req = request.Request(
            f"{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "BoulderRoller-ClimbLab/0.1 (local dev scan)",
            },
        )
        with request.urlopen(req, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") not in {None, "OK"}:
            raise ValueError(f"OpenTopoData elevation status {payload.get('status')}")
        for (node_id, _lat, _lon), result in zip(chunk, payload.get("results") or []):
            try:
                elevation = float(result["elevation"])
            except (KeyError, TypeError, ValueError):
                continue
            elevations[node_id] = elevation
        if idx + chunk_size < len(rows):
            time.sleep(0.15)
    return elevations


def _fetch_open_meteo_elevations(
    nodes: list[dict[str, Any]],
    *,
    timeout_s: int = 20,
    chunk_size: int = 80,
) -> dict[str, float]:
    endpoint = os.getenv("CLIMB_LAB_ELEVATION_URL", DEFAULT_OPEN_METEO_ELEVATION_URL)
    rows = _scan_elevation_rows(nodes)
    elevations: dict[str, float] = {}
    for idx in range(0, len(rows), chunk_size):
        chunk = rows[idx : idx + chunk_size]
        if not chunk:
            continue
        query = parse.urlencode(
            {
                "latitude": ",".join(str(row[1]) for row in chunk),
                "longitude": ",".join(str(row[2]) for row in chunk),
            }
        )
        req = request.Request(
            f"{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "BoulderRoller-ClimbLab/0.1 (local dev scan)",
            },
        )
        with request.urlopen(req, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for (node_id, _lat, _lon), elevation in zip(chunk, payload.get("elevation") or []):
            try:
                elevations[node_id] = float(elevation)
            except (TypeError, ValueError):
                continue
        if idx + chunk_size < len(rows):
            time.sleep(0.15)
    return elevations


def _fetch_scan_elevations(nodes: list[dict[str, Any]]) -> tuple[dict[str, float], str]:
    rows = _scan_elevation_rows(nodes)
    cached = _load_local_elevation_cache()
    elevations = {
        node_id: cached[node_id]
        for node_id, _lat, _lon in rows
        if node_id in cached
    }
    missing_rows = [row for row in rows if row[0] not in elevations]
    if not missing_rows:
        return elevations, "local_elevation_cache"

    try:
        fresh = _fetch_open_topodata_elevations(missing_rows)
        provider = "open_topodata_ned10m"
    except Exception:
        fresh = _fetch_open_meteo_elevations(
            [
                {"id": node_id, "lat": lat, "lon": lon}
                for node_id, lat, lon in missing_rows
            ]
        )
        provider = "open_meteo_elevation_api"

    elevations.update(fresh)
    if fresh:
        cached.update(fresh)
        _write_local_elevation_cache(cached)
    if len(elevations) > len(fresh):
        provider = f"{provider}+local_elevation_cache"
    return elevations, provider


def _attach_elevations_to_graph(
    graph: dict[str, Any],
    elevations_by_node_id: dict[str, float],
) -> dict[str, Any]:
    nodes = []
    for node in graph.get("nodes", []):
        next_node = dict(node)
        elevation = elevations_by_node_id.get(str(node.get("id")))
        if elevation is not None:
            next_node["elevation_m"] = round(float(elevation), 1)
        nodes.append(next_node)
    return {**graph, "nodes": nodes}


def _scan_endpoint_label(
    *,
    node: dict[str, Any],
    other_node: dict[str, Any],
    node_usage: Counter[str],
    node_id: str,
) -> str | None:
    named = _node_name(node, node_id)
    if not named.startswith("node:"):
        return named
    node_lat_lon = _node_lat_lon(node)
    other_lat_lon = _node_lat_lon(other_node)
    if node_lat_lon is None or other_lat_lon is None:
        return None
    lat_delta = node_lat_lon[0] - other_lat_lon[0]
    lon_delta = node_lat_lon[1] - other_lat_lon[1]
    if abs(lon_delta) >= abs(lat_delta):
        direction = "west" if lon_delta < 0 else "east"
    else:
        direction = "north" if lat_delta > 0 else "south"
    elevation = _node_elevation_m(node)
    other_elevation = _node_elevation_m(other_node)
    height = ""
    if elevation is not None and other_elevation is not None:
        elevation_delta = elevation - other_elevation
        if abs(elevation_delta) >= 5:
            height = " upper" if elevation_delta > 0 else " lower"
    endpoint_type = "junction" if node_usage[node_id] > 1 else "end"
    return f"{direction}{height} {endpoint_type}"


def _label_scan_edge_endpoints(
    edges: list[dict[str, Any]],
    graph: dict[str, Any],
) -> list[dict[str, Any]]:
    nodes_by_id = {
        _node_id(node.get("id")): node
        for node in graph.get("nodes", [])
        if node.get("id") is not None
    }
    node_usage = Counter(
        node_id
        for way in graph.get("ways", [])
        for node_id in set(_node_refs(way))
        if node_id in nodes_by_id
    )
    labeled_edges: list[dict[str, Any]] = []
    for edge in edges:
        from_node_id = str(edge.get("from_node_id"))
        to_node_id = str(edge.get("to_node_id"))
        from_node = nodes_by_id.get(from_node_id)
        to_node = nodes_by_id.get(to_node_id)
        if from_node is None or to_node is None:
            labeled_edges.append(edge)
            continue
        from_label = _scan_endpoint_label(
            node=from_node,
            other_node=to_node,
            node_usage=node_usage,
            node_id=from_node_id,
        )
        to_label = _scan_endpoint_label(
            node=to_node,
            other_node=from_node,
            node_usage=node_usage,
            node_id=to_node_id,
        )
        next_edge = dict(edge)
        if from_label:
            next_edge["from_intersection"] = from_label
        if to_label:
            next_edge["to_intersection"] = to_label
        labeled_edges.append(next_edge)
    return labeled_edges


def _candidate_pipeline_from_edges(
    *,
    edges: list[dict[str, Any]],
    source: str,
    model: str,
    pipeline_status: str,
    guardrails: list[str],
    extra_totals: dict[str, Any] | None = None,
    area_label: str | None = None,
    source_provider: str | None = None,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    signals = [
        score_road_edge_climb_signal(edge, direction=direction)
        for edge in edges
        for direction in ("forward", "reverse")
    ]
    climb_bearing = [signal for signal in signals if signal["is_climb_bearing"]]
    candidate_strings = string_road_edge_signals(signals)
    candidates = _materialize_pipeline_candidates(
        signals=signals,
        candidate_strings=candidate_strings,
    )
    if max_candidates is not None:
        candidates = candidates[:max_candidates]
    total_gain_m = round(sum(float(candidate.get("gain_m") or 0) for candidate in candidates), 1)
    top_candidate = candidates[0] if candidates else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": source,
        "area_label": area_label,
        "source_provider": source_provider,
        "privacy_mode": "no_coordinates_no_raw_trace",
        "model": model,
        "pipeline_status": pipeline_status,
        "guardrails": guardrails,
        "stages": [
            {
                "id": "road_graph",
                "label": "Road graph",
                "status": "complete",
                "result": f"{len(edges)} road edges normalized",
            },
            {
                "id": "edge_signal",
                "label": "Directed edge signal",
                "status": "complete",
                "result": f"{len(climb_bearing)} climb-bearing directed edges",
            },
            {
                "id": "climb_stringing",
                "label": "Climb stringing",
                "status": "complete",
                "result": f"{len(candidate_strings)} multi-edge strings",
            },
            {
                "id": "candidate_materialization",
                "label": "Candidate materialization",
                "status": "complete",
                "result": f"{len(candidates)} lab candidates",
            },
        ],
        "totals": {
            **(extra_totals or {}),
            "road_edges": len(edges),
            "directed_edges_scored": len(signals),
            "climb_bearing_edges": len(climb_bearing),
            "candidate_strings": len(candidate_strings),
            "candidate_climbs": len(candidates),
            "promoted_climbs": 0,
            "total_candidate_gain_m": total_gain_m,
            "top_candidate_gain_m": top_candidate.get("gain_m") if top_candidate else 0,
        },
        "top_candidate_id": top_candidate.get("candidate_id") if top_candidate else None,
        "candidates": candidates,
    }


def _edge_confidence(*, gain_m: float, climb_pct: float, avg_grade_pct: float) -> str:
    if gain_m >= 80 and climb_pct >= 45 and avg_grade_pct >= 4:
        return "high"
    if gain_m >= 45 and climb_pct >= 35 and avg_grade_pct >= 3:
        return "medium"
    return "exploratory"


def _edge_signal_band(
    *,
    gain_m: float,
    climb_pct: float,
    avg_grade_pct: float,
    min_gain_m: float,
    min_avg_grade_pct: float,
    min_climb_pct: float,
) -> str:
    if (
        gain_m >= min_gain_m
        and avg_grade_pct >= min_avg_grade_pct
        and climb_pct >= min_climb_pct
    ):
        return "climb_bearing"
    if gain_m >= min_gain_m * 0.65 and avg_grade_pct >= min_avg_grade_pct * 0.8:
        return "watch"
    return "low"


def _edge_profile(edge: dict[str, Any], *, direction: str) -> list[tuple[float, float]]:
    samples = edge.get("samples") or []
    profile = []
    for sample in samples:
        try:
            distance_m = float(sample["distance_m"])
            elevation_m = float(sample["elevation_m"])
        except (KeyError, TypeError, ValueError):
            continue
        profile.append((distance_m, elevation_m))
    profile.sort(key=lambda row: row[0])
    if direction != "reverse" or len(profile) < 2:
        return profile
    total_distance = max(distance for distance, _elevation in profile)
    return [
        (round(total_distance - distance, 6), elevation)
        for distance, elevation in reversed(profile)
    ]


def _best_uphill_span(
    profile: list[tuple[float, float]],
) -> tuple[float, float, float, float] | None:
    if len(profile) < 2:
        return None
    low_distance, low_elevation = profile[0]
    best: tuple[float, float, float, float] | None = None
    best_gain = 0.0
    for distance, elevation in profile[1:]:
        if elevation < low_elevation:
            low_distance, low_elevation = distance, elevation
            continue
        gain_m = elevation - low_elevation
        span_m = distance - low_distance
        if span_m <= 0:
            continue
        avg_grade_pct = (gain_m / span_m) * 100
        if gain_m > best_gain:
            best_gain = gain_m
            best = (low_distance, distance, gain_m, avg_grade_pct)
    return best


def score_road_edge_climb_signal(
    edge: dict[str, Any],
    *,
    direction: str = "forward",
    min_gain_m: float = 35,
    min_avg_grade_pct: float = 2.5,
    min_climb_pct: float = 35,
) -> dict[str, Any]:
    """Score one directed road edge without returning raw geometry."""
    profile = _edge_profile(edge, direction=direction)
    total_distance_m = (
        max((distance for distance, _elevation in profile), default=0.0)
        if profile
        else float(edge.get("distance_m") or 0)
    )
    start_intersection = edge.get("from_intersection")
    end_intersection = edge.get("to_intersection")
    if direction == "reverse":
        start_intersection, end_intersection = end_intersection, start_intersection

    span = _best_uphill_span(profile)
    if span is None or total_distance_m <= 0:
        return {
            "edge_id": edge.get("edge_id"),
            "road_name": edge.get("road_name"),
            "direction": direction,
            "from_intersection": start_intersection,
            "to_intersection": end_intersection,
            "distance_m": round(total_distance_m, 1),
            "climb_start_pct": None,
            "climb_end_pct": None,
            "climb_pct": 0,
            "gain_m": 0,
            "avg_grade_pct": 0,
            "signal_band": "low",
            "confidence": "none",
            "is_climb_bearing": False,
            "reasons": ["insufficient_edge_profile"],
        }

    start_m, end_m, gain_m, avg_grade_pct = span
    span_m = max(0.0, end_m - start_m)
    climb_pct = (span_m / total_distance_m) * 100
    signal_band = _edge_signal_band(
        gain_m=gain_m,
        climb_pct=climb_pct,
        avg_grade_pct=avg_grade_pct,
        min_gain_m=min_gain_m,
        min_avg_grade_pct=min_avg_grade_pct,
        min_climb_pct=min_climb_pct,
    )
    reasons = [
        f"{round(climb_pct)}pct_of_edge_climbing",
        f"{round(gain_m)}m_gain",
        f"{round(avg_grade_pct, 1)}pct_grade",
    ]
    if signal_band == "climb_bearing":
        reasons.append("passes_edge_climb_threshold")

    return {
        "edge_id": edge.get("edge_id"),
        "road_name": edge.get("road_name"),
        "direction": direction,
        "from_intersection": start_intersection,
        "to_intersection": end_intersection,
        "distance_m": round(total_distance_m, 1),
        "climb_start_pct": round((start_m / total_distance_m) * 100, 1),
        "climb_end_pct": round((end_m / total_distance_m) * 100, 1),
        "climb_pct": round(climb_pct, 1),
        "gain_m": round(gain_m, 1),
        "avg_grade_pct": round(avg_grade_pct, 1),
        "signal_band": signal_band,
        "confidence": _edge_confidence(
            gain_m=gain_m,
            climb_pct=climb_pct,
            avg_grade_pct=avg_grade_pct,
        )
        if signal_band != "low"
        else "none",
        "is_climb_bearing": signal_band == "climb_bearing",
        "reasons": reasons,
    }


def _can_string_edges(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if not previous.get("is_climb_bearing") or not current.get("is_climb_bearing"):
        return False
    if previous.get("to_intersection") != current.get("from_intersection"):
        return False
    previous_name = previous.get("road_name")
    current_name = current.get("road_name")
    return bool(previous_name and current_name and previous_name == current_name)


def string_road_edge_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """String adjacent climb-bearing directed edges into candidate chains."""
    ordered = [
        signal
        for signal in signals
        if signal.get("direction") == "forward" and signal.get("is_climb_bearing")
    ]
    chains: list[list[dict[str, Any]]] = []
    current_chain: list[dict[str, Any]] = []
    for signal in ordered:
        if not current_chain:
            current_chain = [signal]
            continue
        if _can_string_edges(current_chain[-1], signal):
            current_chain.append(signal)
            continue
        chains.append(current_chain)
        current_chain = [signal]
    if current_chain:
        chains.append(current_chain)

    candidate_strings = []
    for idx, chain in enumerate(chains, start=1):
        if len(chain) < 2:
            continue
        distance_m = sum(float(edge.get("distance_m") or 0) for edge in chain)
        gain_m = sum(float(edge.get("gain_m") or 0) for edge in chain)
        avg_grade_pct = (gain_m / distance_m) * 100 if distance_m > 0 else 0
        road_names = []
        for edge in chain:
            road_name = edge.get("road_name")
            if road_name and road_name not in road_names:
                road_names.append(road_name)
        candidate_strings.append(
            {
                "string_id": f"fixture-string-{idx}",
                "edge_ids": [edge["edge_id"] for edge in chain],
                "road_names": road_names,
                "from_intersection": chain[0].get("from_intersection"),
                "to_intersection": chain[-1].get("to_intersection"),
                "edge_count": len(chain),
                "distance_m": round(distance_m, 1),
                "gain_m": round(gain_m, 1),
                "avg_grade_pct": round(avg_grade_pct, 1),
                "confidence": _edge_confidence(
                    gain_m=gain_m,
                    climb_pct=100,
                    avg_grade_pct=avg_grade_pct,
                ),
                "reasons": [
                    "adjacent_intersection_edges",
                    "same_road_name_continuity",
                    "all_edges_climb_bearing",
                ],
            }
        )
    return candidate_strings


def _fixture_road_edges() -> list[dict[str, Any]]:
    return build_climb_lab_road_graph_edges(_fixture_osm_like_road_graph())


def build_climb_lab_road_edge_signal_summary() -> dict[str, Any]:
    edges = _fixture_road_edges()
    signals = [
        score_road_edge_climb_signal(edge, direction=direction)
        for edge in edges
        for direction in ("forward", "reverse")
    ]
    climb_bearing = [signal for signal in signals if signal["is_climb_bearing"]]
    candidate_strings = string_road_edge_signals(signals)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": "fixture_osm_like_road_graph",
        "privacy_mode": "no_coordinates_no_raw_trace",
        "model": "directed_intersection_edge_signal_v0",
        "guardrails": [
            "Road-edge profiles come from the fixture road graph in this slice.",
            "No coordinate fields, GPS track, or raw point arrays are returned.",
            "Candidate strings stay inside ClimbLab and are not official climbs.",
        ],
        "thresholds": {
            "min_gain_m": 35,
            "min_avg_grade_pct": 2.5,
            "min_climb_pct": 35,
        },
        "totals": {
            "fixture_edges": len(edges),
            "directed_edges_scored": len(signals),
            "climb_bearing_edges": len(climb_bearing),
            "candidate_strings": len(candidate_strings),
            "total_climb_bearing_gain_m": round(
                sum(float(signal.get("gain_m") or 0) for signal in climb_bearing),
                1,
            ),
        },
        "signals": signals,
        "candidate_strings": candidate_strings,
    }


def _candidate_from_string(candidate: dict[str, Any], *, rank: int) -> dict[str, Any]:
    road_name = " / ".join(candidate.get("road_names") or []) or "Unnamed climb"
    start = candidate.get("from_intersection") or "unknown start"
    finish = candidate.get("to_intersection") or "unknown finish"
    confidence = candidate.get("confidence") or "exploratory"
    return {
        "candidate_id": f"climblab-{rank}-{_slug(road_name)}-{_slug(start)}-{_slug(finish)}",
        "status": "lab_candidate",
        "candidate_type": "strung_road_edges",
        "display_name": f"{road_name}: {start} to {finish}",
        "road_names": candidate.get("road_names") or [],
        "from_intersection": start,
        "to_intersection": finish,
        "edge_ids": candidate.get("edge_ids") or [],
        "edge_count": candidate.get("edge_count") or 0,
        "distance_m": candidate.get("distance_m") or 0,
        "gain_m": candidate.get("gain_m") or 0,
        "avg_grade_pct": candidate.get("avg_grade_pct") or 0,
        "confidence": confidence,
        "review_priority": "high" if confidence == "high" else "normal",
        "result": "candidate_climb_ready_for_review",
        "reasons": [
            *(candidate.get("reasons") or []),
            "materialized_from_pipeline_string",
        ],
        "next_review_actions": [
            "open_candidate",
            "trim_start",
            "trim_finish",
            "split_or_merge",
            "suppress",
            "approve_for_fixture_export",
        ],
    }


def _candidate_from_single_edge(signal: dict[str, Any], *, rank: int) -> dict[str, Any]:
    road_name = signal.get("road_name") or "Unnamed climb"
    start = signal.get("from_intersection") or "unknown start"
    finish = signal.get("to_intersection") or "unknown finish"
    confidence = signal.get("confidence") or "exploratory"
    return {
        "candidate_id": f"climblab-{rank}-{_slug(road_name)}-{_slug(start)}-{_slug(finish)}",
        "status": "lab_candidate",
        "candidate_type": "single_road_edge",
        "display_name": f"{road_name}: {start} to {finish}",
        "road_names": [road_name],
        "from_intersection": start,
        "to_intersection": finish,
        "edge_ids": [signal.get("edge_id")],
        "edge_count": 1,
        "distance_m": signal.get("distance_m") or 0,
        "gain_m": signal.get("gain_m") or 0,
        "avg_grade_pct": signal.get("avg_grade_pct") or 0,
        "confidence": confidence,
        "review_priority": "normal" if confidence in {"high", "medium"} else "low",
        "result": "candidate_climb_ready_for_review",
        "reasons": [
            *(signal.get("reasons") or []),
            "materialized_from_single_climb_bearing_edge",
        ],
        "next_review_actions": [
            "open_candidate",
            "trim_start",
            "trim_finish",
            "merge_through_next_intersection",
            "suppress",
            "approve_for_fixture_export",
        ],
    }


def _materialize_pipeline_candidates(
    *,
    signals: list[dict[str, Any]],
    candidate_strings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = [
        _candidate_from_string(candidate, rank=idx)
        for idx, candidate in enumerate(candidate_strings, start=1)
    ]
    consumed_edges = {
        edge_id
        for candidate in candidate_strings
        for edge_id in candidate.get("edge_ids") or []
    }
    standalone_signals = [
        signal
        for signal in signals
        if signal.get("direction") == "forward"
        and signal.get("is_climb_bearing")
        and signal.get("edge_id") not in consumed_edges
    ]
    next_rank = len(candidates) + 1
    for offset, signal in enumerate(standalone_signals):
        candidates.append(_candidate_from_single_edge(signal, rank=next_rank + offset))
    return sorted(
        candidates,
        key=lambda candidate: (
            float(candidate.get("gain_m") or 0),
            float(candidate.get("distance_m") or 0),
        ),
        reverse=True,
    )


def _candidate_id(candidate: dict[str, Any]) -> str:
    explicit = candidate.get("candidate_id")
    if explicit:
        return str(explicit)
    fingerprint = str(candidate.get("candidate_fingerprint") or "").strip()
    if fingerprint:
        return f"canon-{fingerprint[:16]}"
    display_name = candidate.get("display_name") or candidate.get("route_name") or "candidate"
    return f"climblab-{_slug(display_name)}"


def _route_names(candidate: dict[str, Any]) -> list[str]:
    road_names = candidate.get("road_names")
    if isinstance(road_names, list) and road_names:
        return [str(name) for name in road_names if name]
    route_name = candidate.get("route_name")
    if route_name:
        return [str(route_name)]
    display_name = candidate.get("display_name")
    if display_name:
        return [str(display_name).split(":")[0]]
    return []


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    route_names = _route_names(candidate)
    route_key = "|".join(_slug(name) for name in route_names if _slug(name))
    if not route_key:
        route_key = _slug(
            str(candidate.get("display_name") or candidate.get("route_name") or "")
        )
    way_refs = []
    for raw_ref in candidate.get("osm_way_refs") or []:
        try:
            way_refs.append(int(raw_ref))
        except (TypeError, ValueError):
            continue
    way_ref_hash = None
    if way_refs:
        digest = hashlib.sha256(
            ",".join(str(ref) for ref in way_refs).encode("utf-8")
        ).hexdigest()
        way_ref_hash = digest[:16]
    return {
        "route_key": route_key or None,
        "way_ref_hash": way_ref_hash,
        "way_ref_count": len(way_refs),
    }


def _legacy_candidate_fingerprints(candidate: dict[str, Any]) -> list[str]:
    current = str(candidate.get("candidate_fingerprint") or "").strip()
    fingerprints = []
    for raw_fingerprint in candidate.get("legacy_candidate_fingerprints") or []:
        fingerprint = str(raw_fingerprint).strip()
        if fingerprint and fingerprint != current and fingerprint not in fingerprints:
            fingerprints.append(fingerprint)
    return fingerprints


def _candidate_profile_hash(candidate: dict[str, Any]) -> str | None:
    explicit = str(candidate.get("canonical_profile_hash") or "").strip()
    if explicit:
        return explicit
    provenance = candidate.get("provenance")
    if not isinstance(provenance, dict):
        return None
    profile_hash = provenance.get("canonical_profile_hash")
    if not isinstance(profile_hash, dict):
        return None
    value = str(profile_hash.get("value") or "").strip()
    return value or None


def _review_record_candidate_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = record.get("candidate")
    if isinstance(snapshot, dict):
        return snapshot
    return record


def _review_record_identity(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = _review_record_candidate_snapshot(record)
    stored_identity = snapshot.get("candidate_identity")
    if isinstance(stored_identity, dict):
        return {
            "route_key": stored_identity.get("route_key"),
            "way_ref_hash": stored_identity.get("way_ref_hash"),
            "way_ref_count": int(stored_identity.get("way_ref_count") or 0),
        }
    return _candidate_identity(snapshot)


def _candidate_identity_matches(candidate: dict[str, Any], record: dict[str, Any]) -> bool:
    current = _candidate_identity(candidate)
    previous = _review_record_identity(record)
    if (
        current.get("way_ref_hash")
        and previous.get("way_ref_hash")
        and current["way_ref_hash"] == previous["way_ref_hash"]
    ):
        return True
    if (
        current.get("route_key")
        and previous.get("route_key")
        and current["route_key"] == previous["route_key"]
    ):
        return True
    return False


def _metric_delta(
    candidate: dict[str, Any],
    snapshot: dict[str, Any],
    current_keys: tuple[str, ...],
    previous_keys: tuple[str, ...],
) -> float:
    current = _candidate_metric(candidate, *current_keys)
    previous = _candidate_metric(snapshot, *previous_keys)
    return abs(current - previous)


def _candidate_boundary_changed(candidate: dict[str, Any], record: dict[str, Any]) -> bool:
    snapshot = _review_record_candidate_snapshot(record)
    if candidate.get("candidate_fingerprint") and snapshot.get("candidate_fingerprint"):
        if candidate.get("candidate_fingerprint") != snapshot.get(
            "candidate_fingerprint"
        ):
            return True
    current_profile_hash = _candidate_profile_hash(candidate)
    previous_profile_hash = _candidate_profile_hash(snapshot)
    if (
        current_profile_hash
        and previous_profile_hash
        and current_profile_hash != previous_profile_hash
    ):
        return True
    if (
        _metric_delta(
            candidate,
            snapshot,
            ("length_m", "distance_m"),
            ("length_m", "distance_m"),
        )
        > 5
    ):
        return True
    if (
        _metric_delta(candidate, snapshot, ("vert_m", "gain_m"), ("vert_m", "gain_m"))
        > 1
    ):
        return True
    current_samples = len(candidate.get("canonical_profile") or [])
    previous_samples = int(snapshot.get("canonical_profile_sample_count") or 0)
    return bool(current_samples and previous_samples and current_samples != previous_samples)


def _candidate_review_carry_payload(
    *,
    status: str,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "requires_recheck": status in {"boundary_changed", "new"},
    }
    if record:
        payload.update(
            {
                "source_candidate_id": record.get("candidate_id"),
                "source_decision": record.get("decision"),
                "source_state": record.get("state"),
                "source_updated_at": record.get("updated_at"),
            }
        )
    return payload


def _find_carried_review_record(
    candidate: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    legacy_fingerprints = set(_legacy_candidate_fingerprints(candidate))
    lineage_matches = [
        record
        for record in records.values()
        if str(
            _review_record_candidate_snapshot(record).get("candidate_fingerprint")
            or ""
        )
        in legacy_fingerprints
    ]
    if legacy_fingerprints:
        return lineage_matches[0] if len(lineage_matches) == 1 else None

    identity_matches = [
        record
        for record in records.values()
        if str(record.get("decision") or "pending") != "pending"
        and _candidate_identity_matches(candidate, record)
    ]
    return identity_matches[0] if len(identity_matches) == 1 else None


def _review_queue_sort_key(candidate: dict[str, Any]) -> tuple[int, float, float, str]:
    carry_status = str((candidate.get("review_carry") or {}).get("status") or "new")
    review_state = str(candidate.get("review_state") or "needs_review")
    if review_state in {"needs_work", "needs_boundary_edit", "needs_merge_review"}:
        tier = 0
    elif carry_status == "boundary_changed":
        tier = 1
    elif carry_status == "new":
        tier = 2
    elif review_state == "needs_review":
        tier = 3
    else:
        tier = 4
    return (
        tier,
        -_candidate_metric(candidate, "worthiness_score"),
        -_candidate_metric(candidate, "gain_m", "vert_m"),
        str(candidate.get("display_name") or ""),
    )


def _candidate_in_next_review_queue(candidate: dict[str, Any]) -> bool:
    review_state = str(candidate.get("review_state") or "needs_review")
    carry = candidate.get("review_carry") or {}
    return bool(carry.get("requires_recheck")) or review_state in {
        "needs_review",
        "needs_work",
        "needs_boundary_edit",
        "needs_merge_review",
    }


def _candidate_metric(
    candidate: dict[str, Any],
    *keys: str,
    default: float = 0.0,
) -> float:
    for key in keys:
        value = candidate.get(key)
        if value is None:
            continue
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            continue
    return default


def _canon_confidence(value: Any) -> str:
    confidence = str(value or "needs_review").strip().lower()
    return confidence if confidence in CANON_CONFIDENCE_VALUES else "needs_review"


def _missing_canon_publish_fields(candidate: dict[str, Any] | None) -> list[str]:
    if not candidate:
        return list(CANON_REQUIRED_PUBLISH_FIELDS)
    missing: list[str] = []
    for field in CANON_REQUIRED_PUBLISH_FIELDS:
        value = candidate.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    if candidate.get("compiler_run_mode") not in {None, "", "applied"}:
        missing.append("compiler_run_mode=applied")
    return missing


def _canon_publish_ready(candidate: dict[str, Any] | None) -> bool:
    return not _missing_canon_publish_fields(candidate)


def _canon_publish_preview(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return the canon_climbs v1 row shape without emitting raw geometry."""
    missing_fields = _missing_canon_publish_fields(candidate)
    publish_status = (
        "ready_for_canon_climbs_v1_insert"
        if not missing_fields
        else "blocked_missing_canon_publish_payload"
    )
    return {
        "target_table": "canon_climbs",
        "status": "ratified",
        "version": 1,
        "source": "climblab_ratification",
        "source_candidate_id": _candidate_id(candidate),
        "display_name": candidate.get("display_name"),
        "road_names": _route_names(candidate),
        "gate_start_label": candidate.get("from_intersection"),
        "gate_end_label": candidate.get("to_intersection"),
        "length_m": _candidate_metric(candidate, "length_m", "distance_m"),
        "vert_m": _candidate_metric(candidate, "vert_m", "gain_m"),
        "avg_gradient_pct": _candidate_metric(candidate, "avg_gradient_pct", "avg_grade_pct"),
        "confidence": _canon_confidence(candidate.get("confidence")),
        "worthiness_score": _candidate_metric(
            candidate,
            "worthiness_score",
            default=1.0 if candidate.get("review_priority") == "high" else 0.0,
        ),
        "odbl_provenance": (
            "ready"
            if candidate.get("osm_way_refs")
            else "missing_osm_way_refs"
        ),
        "geometry_status": (
            "ready"
            if not missing_fields
            else "missing_centerline_corridor_or_gate_geometry"
        ),
        "publish_status": publish_status,
        "missing_fields": missing_fields,
        "corridor_cell_count": len(candidate.get("corridor_cells") or []),
        "canonical_profile_sample_count": len(candidate.get("canonical_profile") or []),
    }


def _review_action_payload(action_id: str) -> dict[str, str]:
    return {
        "id": action_id,
        "label": action_id.replace("_", " "),
        "description": CLIMB_LAB_REVIEW_ACTIONS[action_id],
    }


def _review_decision_payload(decision_id: str) -> dict[str, str]:
    decision = CLIMB_LAB_REVIEW_DECISIONS[decision_id]
    return {
        "id": decision_id,
        "state": decision["state"],
        "label": decision["label"],
        "description": decision["description"],
    }


def _climb_lab_review_state_path(state_path: str | Path | None = None) -> Path:
    configured_path = state_path or os.getenv(
        "CLIMB_LAB_REVIEW_STATE_PATH",
        str(DEFAULT_CLIMB_LAB_REVIEW_STATE_PATH),
    )
    return Path(configured_path).expanduser()


def _empty_climb_lab_review_state_document() -> dict[str, Any]:
    return {
        "version": 1,
        "scope": "local_dev_only",
        "model": "climb_lab_review_state_v1",
        "updated_at": None,
        "candidates": {},
    }


def _normal_review_state(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {
            "state": "needs_review",
            "action": None,
            "decision": "pending",
            "decision_label": "Pending",
            "note": None,
            "updated_at": None,
        }
    decision_id = str(record.get("decision") or record.get("action") or "pending")
    decision = CLIMB_LAB_REVIEW_DECISIONS.get(decision_id)
    return {
        "state": record.get("state") or (decision or {}).get("state") or "needs_review",
        "action": record.get("action"),
        "decision": decision_id,
        "decision_label": record.get("decision_label")
        or (decision or {}).get("label")
        or decision_id.replace("_", " "),
        "note": record.get("note"),
        "updated_at": record.get("updated_at"),
    }


def _normalize_climb_lab_review_state_document(document: dict[str, Any]) -> dict[str, Any]:
    normalized = _empty_climb_lab_review_state_document()
    normalized.update(
        {
            "version": int(document.get("version") or 1),
            "scope": str(document.get("scope") or "local_dev_only"),
            "model": str(document.get("model") or "climb_lab_review_state_v1"),
            "updated_at": document.get("updated_at"),
        }
    )
    candidates: dict[str, dict[str, Any]] = {}
    for raw_candidate_id, raw_record in (document.get("candidates") or {}).items():
        if not isinstance(raw_record, dict):
            continue
        candidate_id = str(raw_candidate_id)
        candidates[candidate_id] = {
            **raw_record,
            "candidate_id": str(raw_record.get("candidate_id") or candidate_id),
            **_normal_review_state(raw_record),
        }
    normalized["candidates"] = candidates
    return normalized


def load_climb_lab_review_state(
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load persisted dev-only ClimbLab review decisions."""
    path = _climb_lab_review_state_path(state_path)
    if not path.exists():
        document = _empty_climb_lab_review_state_document()
    else:
        document = json.loads(path.read_text())
        if not isinstance(document, dict):
            document = _empty_climb_lab_review_state_document()
    normalized = _normalize_climb_lab_review_state_document(document)
    _CLIMB_LAB_REVIEW_STATE.clear()
    _CLIMB_LAB_REVIEW_STATE.update(deepcopy(normalized.get("candidates") or {}))
    return normalized


def _write_climb_lab_review_state(
    document: dict[str, Any],
    *,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    path = _climb_lab_review_state_path(state_path)
    normalized = _normalize_climb_lab_review_state_document(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)
    _CLIMB_LAB_REVIEW_STATE.clear()
    _CLIMB_LAB_REVIEW_STATE.update(deepcopy(normalized.get("candidates") or {}))
    return normalized


def clear_climb_lab_review_state(*, remove_file: bool = False) -> None:
    """Clear process-local review state, and optionally remove the persisted file."""
    _CLIMB_LAB_REVIEW_STATE.clear()
    if not remove_file:
        return
    path = _climb_lab_review_state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _persist_climb_lab_review_record(
    candidate_id: str,
    record: dict[str, Any] | None,
    *,
    state_path: str | Path | None = None,
) -> dict[str, Any]:
    document = load_climb_lab_review_state(state_path)
    candidates = document.setdefault("candidates", {})
    if record is None:
        candidates.pop(candidate_id, None)
        _CLIMB_LAB_REVIEW_STATE.pop(candidate_id, None)
    else:
        candidates[candidate_id] = record
        _CLIMB_LAB_REVIEW_STATE[candidate_id] = record
    document["updated_at"] = datetime.now(timezone.utc).isoformat()
    return _write_climb_lab_review_state(document, state_path=state_path)


def _candidate_review_state_for_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_id = _candidate_id(candidate)
    records = load_climb_lab_review_state().get("candidates", {})
    persisted = records.get(candidate_id) or _CLIMB_LAB_REVIEW_STATE.get(candidate_id)
    if persisted:
        state = _normal_review_state(persisted)
        state["carry"] = _candidate_review_carry_payload(
            status=(
                "boundary_changed"
                if _candidate_boundary_changed(candidate, persisted)
                else "stable"
            ),
            record=persisted,
        )
        return state

    carried = _find_carried_review_record(candidate, records)
    if carried:
        state = _normal_review_state(carried)
        state["carry"] = _candidate_review_carry_payload(
            status=(
                "boundary_changed"
                if _candidate_boundary_changed(candidate, carried)
                else "stable"
            ),
            record=carried,
        )
        return state

    state = _normal_review_state(None)
    state["carry"] = _candidate_review_carry_payload(status="new")
    return state


def _safe_candidate_review_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "candidate_id": _candidate_id(candidate),
        "status": candidate.get("status") or "lab_candidate",
        "candidate_type": candidate.get("candidate_type") or "compiled_canon_candidate",
        "display_name": candidate.get("display_name") or candidate.get("route_name") or "Unnamed climb",
        "road_names": _route_names(candidate),
        "from_intersection": candidate.get("from_intersection"),
        "to_intersection": candidate.get("to_intersection"),
        "edge_count": candidate.get("edge_count"),
        "distance_m": _candidate_metric(candidate, "distance_m", "length_m"),
        "gain_m": _candidate_metric(candidate, "gain_m", "vert_m"),
        "avg_grade_pct": _candidate_metric(candidate, "avg_grade_pct", "avg_gradient_pct"),
        "max_gradient_pct": candidate.get("max_gradient_pct"),
        "worthiness_score": _candidate_metric(candidate, "worthiness_score"),
        "confidence": _canon_confidence(candidate.get("confidence")),
        "review_priority": candidate.get("review_priority") or "normal",
        "result": candidate.get("result") or "candidate_climb_ready_for_review",
        "reasons": candidate.get("reasons") or [],
        "next_review_actions": candidate.get("next_review_actions") or [],
    }
    if candidate.get("edge_ids"):
        payload["edge_ids"] = candidate.get("edge_ids")
    if candidate.get("compiler_version"):
        payload["compiler_version"] = candidate.get("compiler_version")
    if candidate.get("dem_source"):
        payload["dem_source"] = candidate.get("dem_source")
    if candidate.get("low_confidence_flags"):
        payload["low_confidence_flags"] = candidate.get("low_confidence_flags")
    if candidate.get("candidate_fingerprint"):
        payload["candidate_fingerprint"] = candidate.get("candidate_fingerprint")
    if candidate.get("legacy_candidate_fingerprints"):
        payload["legacy_candidate_fingerprints"] = _legacy_candidate_fingerprints(
            candidate
        )
    profile_hash = _candidate_profile_hash(candidate)
    if profile_hash:
        payload["canonical_profile_hash"] = profile_hash
    payload["candidate_identity"] = _candidate_identity(candidate)
    osm_way_refs = candidate.get("osm_way_refs") or []
    corridor_cells = candidate.get("corridor_cells") or []
    canonical_profile = candidate.get("canonical_profile") or []
    payload["osm_way_ref_count"] = len(osm_way_refs)
    payload["corridor_cell_count"] = len(corridor_cells)
    payload["canonical_profile_sample_count"] = len(canonical_profile)
    return payload


def _candidate_review_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    safe_candidate = _safe_candidate_review_fields(candidate)
    state = _candidate_review_state_for_candidate(candidate)
    return {
        **safe_candidate,
        "review_state": state["state"],
        "review_action": state.get("action"),
        "review_decision": state.get("decision"),
        "review_decision_label": state.get("decision_label"),
        "review_note": state.get("note"),
        "review_updated_at": state.get("updated_at"),
        "review_carry": state.get("carry"),
        "review_decisions": [
            _review_decision_payload(decision_id)
            for decision_id in (
                "approve",
                "needs_work",
                "suppress",
                "pending",
            )
        ],
        "review_actions": [
            _review_action_payload(action_id)
            for action_id in (
                "trim_start",
                "trim_finish",
                "merge_through_intersection",
                "suppress",
                "approve",
            )
        ],
        "canon_publish_preview": _canon_publish_preview(candidate),
    }


def _review_priority_for_compiler_candidate(candidate: dict[str, Any]) -> str:
    confidence = _canon_confidence(candidate.get("confidence"))
    worthiness = _candidate_metric(candidate, "worthiness_score")
    if confidence == "high" or worthiness >= 80:
        return "high"
    if confidence == "medium" or worthiness >= 40:
        return "normal"
    return "low"


def _compiler_review_candidate(candidate: dict[str, Any], *, rank: int) -> dict[str, Any]:
    next_candidate = dict(candidate)
    display_name = str(
        next_candidate.get("display_name")
        or next_candidate.get("route_name")
        or f"Compiled climb {rank}"
    )
    next_candidate["candidate_id"] = _candidate_id(next_candidate)
    next_candidate["status"] = "lab_candidate"
    next_candidate["candidate_type"] = "compiled_canon_candidate"
    next_candidate["display_name"] = display_name
    next_candidate["road_names"] = _route_names(next_candidate)
    next_candidate["from_intersection"] = next_candidate.get("from_intersection") or "start gate"
    next_candidate["to_intersection"] = next_candidate.get("to_intersection") or "finish gate"
    next_candidate["distance_m"] = _candidate_metric(next_candidate, "distance_m", "length_m")
    next_candidate["gain_m"] = _candidate_metric(next_candidate, "gain_m", "vert_m")
    next_candidate["avg_grade_pct"] = _candidate_metric(
        next_candidate,
        "avg_grade_pct",
        "avg_gradient_pct",
    )
    next_candidate["review_priority"] = _review_priority_for_compiler_candidate(next_candidate)
    next_candidate["result"] = "compiler_candidate_ready_for_canon_review"
    next_candidate["reasons"] = [
        *(next_candidate.get("reasons") or []),
        "compiled_from_osm_road_graph_and_local_dem",
        "has_schema_publish_payload",
    ]
    next_candidate["next_review_actions"] = [
        "open_candidate",
        "trim_start",
        "trim_finish",
        "merge_through_intersection",
        "suppress",
        "approve",
    ]
    return next_candidate


def build_climb_lab_compiler_candidate_summary(
    compiler_report: dict[str, Any],
    *,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Normalize a canon compiler JSON report into ClimbLab review candidates."""
    run_metadata = compiler_report.get("ratified_boundaries")
    if not isinstance(run_metadata, dict):
        run_metadata = {}
    compiler_run_mode = str(run_metadata.get("mode") or "unknown")
    candidates = [
        _compiler_review_candidate(
            {**candidate, "compiler_run_mode": compiler_run_mode},
            rank=idx,
        )
        for idx, candidate in enumerate(compiler_report.get("candidates") or [], start=1)
        if isinstance(candidate, dict)
    ]
    ready_candidates = [
        candidate
        for candidate in candidates
        if _canon_publish_ready(candidate)
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": "canon_compile_report",
        "area_label": source_label or "Compiled canon candidates",
        "privacy_mode": "internal_payload_redacted_at_review_surface",
        "model": "canon_compiler_candidates_v0",
        "pipeline_status": (
            "compiler_report_loaded"
            if compiler_run_mode == "applied"
            else "diagnostic_report_loaded_non_publishable"
        ),
        "compiler_run": {
            "mode": compiler_run_mode,
            "model": run_metadata.get("model"),
        },
        "guardrails": [
            "Compiler report payloads may contain geometry and are only passed through internal service code.",
            "The review API redacts WKT, polylines, raw coordinates, and profile arrays.",
            "Approve publishes only candidates with complete canon_climbs and corridor-cell fields.",
        ],
        "totals": {
            "candidate_climbs": len(candidates),
            "publish_ready_candidates": len(ready_candidates),
        },
        "candidates": candidates,
    }


def load_climb_lab_compiler_candidate_summary(
    report_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load an optional local compiler report configured for ClimbLab review."""
    configured_path = report_path or os.getenv("CLIMB_LAB_CANON_COMPILE_REPORT_PATH")
    if not configured_path:
        return None
    path = Path(configured_path).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"ClimbLab compiler report not found: {path}")
    report = json.loads(path.read_text())
    return build_climb_lab_compiler_candidate_summary(
        report,
        source_label=path.name,
    )


def find_climb_lab_review_candidate(
    source_summary: dict[str, Any] | None,
    candidate_id: str,
) -> dict[str, Any] | None:
    """Find an internal review candidate by its stable review id."""
    if not source_summary:
        return None
    for candidate in source_summary.get("candidates") or []:
        if _candidate_id(candidate) == candidate_id:
            return candidate
    return None


def record_climb_lab_review_decision(
    *,
    candidate_id: str,
    decision: str,
    note: str | None = None,
    candidate: dict[str, Any] | None = None,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    """Persist a reversible ClimbLab review decision without publishing canon rows."""
    candidate_id = str(candidate_id).strip()
    decision_id = str(decision).strip().lower()
    if not candidate_id:
        return {
            "status": "rejected",
            "reason": "missing_candidate_id",
            "allowed_decisions": sorted(CLIMB_LAB_REVIEW_DECISIONS),
        }
    if decision_id not in CLIMB_LAB_REVIEW_DECISIONS:
        return {
            "status": "rejected",
            "reason": "unknown_review_decision",
            "candidate_id": candidate_id,
            "allowed_decisions": sorted(CLIMB_LAB_REVIEW_DECISIONS),
        }

    updated_at = datetime.now(timezone.utc).isoformat()
    decision_spec = CLIMB_LAB_REVIEW_DECISIONS[decision_id]
    cleaned_note = note.strip() if isinstance(note, str) and note.strip() else None
    if decision_id == "pending":
        _persist_climb_lab_review_record(candidate_id, None)
        response = {
            "status": "recorded",
            "scope": "local_dev_only",
            "candidate_id": candidate_id,
            "review_state": "needs_review",
            "decision": "pending",
            "decision_label": "Pending",
            "updated_at": updated_at,
            "note": None,
        }
    else:
        record = {
            "candidate_id": candidate_id,
            "state": decision_spec["state"],
            "action": None,
            "decision": decision_id,
            "decision_label": decision_spec["label"],
            "note": cleaned_note,
            "reviewed_by": reviewed_by or "climb_lab_dev",
            "updated_at": updated_at,
        }
        if candidate is not None:
            record["candidate"] = _safe_candidate_review_fields(candidate)
        _persist_climb_lab_review_record(candidate_id, record)
        response = {
            "status": "recorded",
            "scope": "local_dev_only",
            "candidate_id": candidate_id,
            "review_state": record["state"],
            "decision": decision_id,
            "decision_label": decision_spec["label"],
            "updated_at": updated_at,
            "note": cleaned_note,
        }
    if candidate is not None:
        response["candidate"] = _candidate_review_payload(candidate)
    return response


def build_climb_lab_review_candidate_map_detail(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Return single-candidate map/profile detail for local review.

    The review queue remains geometry-redacted. This detail payload is scoped to
    one selected public OSM compiler candidate and omits WKT, corridor polygons,
    raw trace data, and profile point coordinates.
    """
    profile = []
    for point in candidate.get("canonical_profile") or []:
        try:
            profile.append(
                {
                    "dist_m": round(float(point["dist_m"]), 2),
                    "elev_m": round(float(point["elev_m"]), 2),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    centerline_polyline = candidate.get("centerline_polyline")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "privacy_mode": "single_candidate_public_osm_geometry_no_raw_trace",
        "candidate": _candidate_review_payload(candidate),
        "geometry": {
            "status": "ready" if centerline_polyline else "missing_centerline_polyline",
            "encoding": "google_polyline",
            "centerline_polyline": centerline_polyline,
        },
        "profile": {
            "status": "ready" if len(profile) >= 2 else "missing_profile",
            "sample_count": len(profile),
            "points": profile,
        },
    }


def build_climb_lab_candidate_review_summary(
    scan_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the dev-only canon ratification review surface payload."""
    source_summary = scan_summary or build_climb_lab_candidate_pipeline_summary()
    candidates = [
        _candidate_review_payload(candidate)
        for candidate in source_summary.get("candidates") or []
    ]
    candidates = sorted(candidates, key=_review_queue_sort_key)
    next_review_candidate_ids = [
        str(candidate["candidate_id"])
        for candidate in candidates
        if _candidate_in_next_review_queue(candidate)
    ]
    approved = [
        candidate
        for candidate in candidates
        if candidate.get("review_state")
        in {"approved_for_review", "approved_for_canon_climbs_v1"}
    ]
    approved_for_publish = [
        candidate
        for candidate in candidates
        if candidate.get("review_state") == "approved_for_canon_climbs_v1"
    ]
    needs_work = [
        candidate
        for candidate in candidates
        if candidate.get("review_state")
        in {"needs_work", "needs_boundary_edit", "needs_merge_review"}
    ]
    suppressed = [
        candidate
        for candidate in candidates
        if candidate.get("review_state") == "suppressed"
    ]
    pending = [
        candidate
        for candidate in candidates
        if candidate.get("review_state") == "needs_review"
    ]
    carry_counts = Counter(
        str((candidate.get("review_carry") or {}).get("status") or "unknown")
        for candidate in candidates
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": source_summary.get("source"),
        "area_label": source_summary.get("area_label"),
        "privacy_mode": "no_coordinates_no_raw_trace",
        "model": "canon_ratification_review_surface_v0",
        "pipeline_status": "review_ready",
        "schema_status": "canon_schema_v1_available",
        "guardrails": [
            "Candidate review is dev-only and gated behind ENABLE_DEV_ROUTES.",
            "Review payloads include road labels and derived metrics, not raw coordinates or geometry.",
            "In-lab decisions persist to local review state; separate publish actions insert only complete canon payloads.",
        ],
        "publish_contract": {
            "target_table": "canon_climbs",
            "initial_status": "ratified",
            "initial_version": 1,
            "schema_gate": "boulderroller-v2-4crx.8",
        },
        "review_queue": {
            "strategy": "needs_work_then_boundary_changed_then_new_by_calibrated_worthiness",
            "candidate_count": len(next_review_candidate_ids),
            "candidate_ids": next_review_candidate_ids,
        },
        "totals": {
            "candidate_climbs": len(candidates),
            "reviewable_candidates": len(candidates) - len(suppressed),
            "approved_for_review": len(approved),
            "approved_for_canon_climbs_v1": len(approved_for_publish),
            "needs_work": len(needs_work),
            "suppressed": len(suppressed),
            "pending": len(pending),
            "new_candidates": carry_counts["new"],
            "boundary_changed_candidates": carry_counts["boundary_changed"],
            "stable_carried_candidates": carry_counts["stable"],
            "next_recheck_candidates": carry_counts["new"] + carry_counts["boundary_changed"],
            "publish_ready_candidates": sum(
                1
                for candidate in candidates
                if candidate.get("canon_publish_preview", {}).get("publish_status")
                == "ready_for_canon_climbs_v1_insert"
            ),
        },
        "candidates": candidates,
    }


def build_climb_lab_review_state_summary() -> dict[str, Any]:
    """Return the persisted local review decisions for agent/backend inspection."""
    document = load_climb_lab_review_state()
    records = sorted(
        document.get("candidates", {}).values(),
        key=lambda record: str(record.get("updated_at") or ""),
        reverse=True,
    )
    state_counts = Counter(str(record.get("state") or "needs_review") for record in records)
    decision_counts = Counter(str(record.get("decision") or "pending") for record in records)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "model": document.get("model") or "climb_lab_review_state_v1",
        "state_file": str(_climb_lab_review_state_path()),
        "privacy_mode": "review_decisions_no_geometry_no_raw_trace",
        "guardrails": [
            "This file is a local ratification aid and is not a production canon table.",
            "Candidate snapshots include review labels and metrics, not raw geometry, WKT, or profile arrays.",
            "Approval here means accepted for review follow-up; it does not publish canon rows.",
        ],
        "decision_options": [
            _review_decision_payload(decision_id)
            for decision_id in ("approve", "needs_work", "suppress", "pending")
        ],
        "totals": {
            "recorded_decisions": len(records),
            "approved_for_review": state_counts["approved_for_review"],
            "needs_work": state_counts["needs_work"],
            "suppressed": state_counts["suppressed"],
            "pending_records": decision_counts["pending"],
        },
        "decisions": records,
    }


def build_canon_climb_publish_payload(
    candidate: dict[str, Any] | None,
    *,
    ratified_by: str | None = None,
    ratified_at: str | None = None,
) -> dict[str, Any]:
    """Build a schema-ready canon_climbs publish payload from a compiler candidate."""
    from .canon_climb_publisher import strip_local_compiler_profiles

    missing_fields = _missing_canon_publish_fields(candidate)
    if missing_fields:
        raise ValueError(
            "candidate is missing canon publish fields: "
            + ", ".join(missing_fields)
        )
    assert candidate is not None
    reviewed_at = ratified_at or datetime.now(timezone.utc).isoformat()
    climb = {
        "candidate_fingerprint": str(candidate["candidate_fingerprint"]),
        "legacy_candidate_fingerprints": _legacy_candidate_fingerprints(candidate),
        "display_name": str(candidate["display_name"]),
        "route_name": candidate.get("route_name"),
        "direction": str(candidate.get("direction") or "ascending"),
        "centerline_polyline": str(candidate["centerline_polyline"]),
        "centerline_wkt": str(candidate["centerline_wkt"]),
        "corridor_wkt": str(candidate["corridor_wkt"]),
        "corridor_half_width_m": float(candidate["corridor_half_width_m"]),
        "gate_start_wkt": str(candidate["gate_start_wkt"]),
        "gate_end_wkt": str(candidate["gate_end_wkt"]),
        "canonical_profile": candidate["canonical_profile"],
        "length_m": _candidate_metric(candidate, "length_m"),
        "vert_m": _candidate_metric(candidate, "vert_m"),
        "avg_gradient_pct": _candidate_metric(candidate, "avg_gradient_pct"),
        "max_gradient_pct": candidate.get("max_gradient_pct"),
        "worthiness_score": _candidate_metric(candidate, "worthiness_score"),
        "confidence": _canon_confidence(candidate.get("confidence")),
        "dem_source": str(candidate["dem_source"]),
        "compiler_version": str(candidate["compiler_version"]),
        "osm_way_refs": [int(ref) for ref in candidate.get("osm_way_refs") or []],
        "odbl_source": str(candidate.get("odbl_source") or "OpenStreetMap contributors"),
        "odbl_extract_at": candidate.get("odbl_extract_at"),
        "provenance": candidate.get("provenance") or {},
        "low_confidence_flags": [
            str(flag)
            for flag in candidate.get("low_confidence_flags") or []
        ],
        "ratified_by": ratified_by,
        "ratified_at": reviewed_at,
    }
    corridor_cells = [
        {
            "h3_resolution": int(cell.get("h3_resolution") or 10),
            "tile_id": str(cell["tile_id"]),
            "coverage_role": str(cell.get("coverage_role") or "corridor"),
        }
        for cell in candidate.get("corridor_cells") or []
        if cell.get("tile_id")
    ]
    if not corridor_cells:
        raise ValueError("candidate is missing valid canon corridor cells")
    return {
        "candidate_id": _candidate_id(candidate),
        "compiler_run_mode": str(candidate["compiler_run_mode"]),
        "target_table": "canon_climbs",
        "target_version": 1,
        "climb": strip_local_compiler_profiles(climb),
        "corridor_cells": corridor_cells,
    }


def apply_climb_lab_review_action(
    *,
    candidate_id: str,
    action_id: str,
    note: str | None = None,
    candidate: dict[str, Any] | None = None,
    publisher: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ratified_by: str | None = None,
) -> dict[str, Any]:
    """Record a process-local ClimbLab review action for dev workflow checks."""
    if action_id not in CLIMB_LAB_REVIEW_ACTIONS:
        return {
            "status": "rejected",
            "reason": "unknown_review_action",
            "candidate_id": candidate_id,
            "allowed_actions": sorted(CLIMB_LAB_REVIEW_ACTIONS),
        }

    state_by_action = {
        "trim_start": "needs_boundary_edit",
        "trim_finish": "needs_boundary_edit",
        "merge_through_intersection": "needs_merge_review",
        "suppress": "suppressed",
        "approve": "approved_for_canon_climbs_v1",
    }
    updated_at = datetime.now(timezone.utc).isoformat()
    publish_payload: dict[str, Any] | None = None
    publish_result: dict[str, Any] | None = None
    publish_status: str | None = None
    missing_fields: list[str] = []

    if action_id == "approve":
        missing_fields = _missing_canon_publish_fields(candidate)
        if missing_fields:
            publish_status = "blocked_missing_canon_publish_payload"
        else:
            publish_payload = build_canon_climb_publish_payload(
                candidate,
                ratified_by=ratified_by,
                ratified_at=updated_at,
            )
            if publisher is not None:
                publish_result = publisher(publish_payload)
                publish_status = "published_to_canon_climbs_v1"
            else:
                publish_status = "ready_for_canon_climbs_v1_insert"

    review_state = {
        "state": state_by_action[action_id],
        "action": action_id,
        "decision": action_id,
        "decision_label": action_id.replace("_", " "),
        "note": note,
        "updated_at": updated_at,
    }
    if candidate is not None:
        review_state["candidate"] = _safe_candidate_review_fields(candidate)
    _persist_climb_lab_review_record(candidate_id, review_state)
    response: dict[str, Any] = {
        "status": "recorded",
        "scope": "local_dev_only",
        "candidate_id": candidate_id,
        "review_state": review_state["state"],
        "action": action_id,
        "updated_at": updated_at,
        "note": note,
    }
    if action_id == "approve":
        response["publish_status"] = publish_status
        response["target_table"] = "canon_climbs"
        response["target_version"] = 1
        response["missing_fields"] = missing_fields
        if publish_payload is not None:
            response["publish_payload"] = {
                "candidate_fingerprint": publish_payload["climb"]["candidate_fingerprint"],
                "display_name": publish_payload["climb"]["display_name"],
                "version": publish_payload["target_version"],
                "status": "ratified",
                "corridor_cell_count": len(publish_payload["corridor_cells"]),
            }
        if publish_result is not None:
            response["publish_result"] = publish_result
    return response


def build_climb_lab_candidate_pipeline_summary() -> dict[str, Any]:
    """Run the current ClimbLab fixture pipeline into candidate climb results."""
    graph = _fixture_osm_like_road_graph()
    edges = build_climb_lab_road_graph_edges(graph)
    return _candidate_pipeline_from_edges(
        edges=edges,
        source=graph["source"],
        model="road_graph_to_candidate_climbs_pipeline_v0",
        pipeline_status="produced_fixture_candidates",
        guardrails=[
            "Pipeline results are ClimbLab-only and are not official Boulder Roller climbs.",
            "No coordinate fields, raw geometry, GPS tracks, or raw point arrays are returned.",
            "Review actions describe future lab decisions; they do not promote candidates.",
        ],
    )


def _scan_error_payload(
    *,
    preset_id: str,
    preset: dict[str, Any],
    error: Exception,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "source": "overpass_osm_live",
        "area_label": preset.get("label"),
        "source_provider": "overpass_api",
        "privacy_mode": "no_coordinates_no_raw_trace",
        "model": "bounded_real_area_candidate_scan_v0",
        "pipeline_status": "scan_fetch_error",
        "preset_id": preset_id,
        "guardrails": [
            "Live scan failed before candidate materialization.",
            "No coordinate fields, raw geometry, GPS tracks, or raw point arrays are returned.",
            "No candidates are promoted from this error payload.",
        ],
        "error": f"{type(error).__name__}: {error}",
        "stages": [],
        "totals": {
            "road_edges": 0,
            "directed_edges_scored": 0,
            "climb_bearing_edges": 0,
            "candidate_strings": 0,
            "candidate_climbs": 0,
            "promoted_climbs": 0,
            "total_candidate_gain_m": 0,
            "top_candidate_gain_m": 0,
        },
        "top_candidate_id": None,
        "candidates": [],
    }


def build_climb_lab_bounded_scan_summary(
    *,
    preset_id: str = "boulder_foothills_north",
    max_ways: int = 0,
    max_candidates: int = 0,
    max_elevation_nodes: int = 0,
    overpass_payload: dict[str, Any] | None = None,
    elevation_lookup: Any = None,
) -> dict[str, Any]:
    """Run a bounded real-area scan through the ClimbLab candidate pipeline."""
    preset = _scan_preset(preset_id)
    max_ways = _bounded_scan_limit(
        max_ways,
        default=int(preset.get("default_max_ways") or 80),
        maximum=160,
    )
    max_candidates = _bounded_scan_limit(
        max_candidates,
        default=int(preset.get("default_max_candidates") or 16),
        maximum=40,
    )
    max_elevation_nodes = _bounded_scan_limit(
        max_elevation_nodes,
        default=int(preset.get("default_max_elevation_nodes") or 210),
        maximum=500,
    )
    cache_key = ("bounded_scan", preset_id, max_ways, max_candidates, max_elevation_nodes)
    if overpass_payload is None and elevation_lookup is None and cache_key in _CLIMB_LAB_SCAN_CACHE:
        payload = deepcopy(_CLIMB_LAB_SCAN_CACHE[cache_key])
        payload["cache_status"] = "hit"
        return payload

    fetch_status = "fixture" if overpass_payload is not None else "live_overpass"
    try:
        if overpass_payload is not None:
            raw_payload = overpass_payload
        else:
            try:
                raw_payload = _fetch_overpass_payload(preset)
            except Exception:
                cached_payload = _load_local_overpass_cache(preset_id)
                if cached_payload is None:
                    raise
                raw_payload = cached_payload
                fetch_status = "local_overpass_cache"
        graph = _overpass_payload_to_graph(
            raw_payload,
            max_ways=max_ways,
            max_elevation_nodes=max_elevation_nodes,
        )
        if elevation_lookup is not None:
            elevations = elevation_lookup(graph.get("nodes", []))
            elevation_status = "fixture"
        else:
            elevations, elevation_status = _fetch_scan_elevations(graph.get("nodes", []))
        graph = _attach_elevations_to_graph(graph, elevations)
        edges = _label_scan_edge_endpoints(
            build_climb_lab_road_graph_edges(graph),
            graph,
        )
        source_counts = graph.get("source_counts") or {}
        summary = _candidate_pipeline_from_edges(
            edges=edges,
            source=graph.get("source") or "overpass_osm_live",
            area_label=preset.get("label"),
            source_provider=f"overpass_api + {elevation_status}",
            model="bounded_real_area_candidate_scan_v0",
            pipeline_status="produced_bounded_scan_candidates",
            max_candidates=max_candidates,
            extra_totals={
                "preset_id": preset_id,
                "source_elements": source_counts.get("elements", 0),
                "source_ways": source_counts.get("ways", 0),
                "source_nodes": source_counts.get("nodes", 0),
                "rideable_named_ways": source_counts.get("rideable_named_ways", 0),
                "scan_road_ways": source_counts.get("scan_road_ways", 0),
                "selected_ways": source_counts.get("selected_ways", 0),
                "selected_elevation_nodes": source_counts.get("selected_elevation_nodes", 0),
                "elevation_attached_nodes": len(elevations),
                "max_ways": max_ways,
                "max_candidates": max_candidates,
                "max_elevation_nodes": max_elevation_nodes,
                "fetch_status": fetch_status,
                "elevation_status": elevation_status,
                "selection_strategy": source_counts.get("selection_strategy"),
            },
            guardrails=[
                "Live scan results are ClimbLab-only and are not official Boulder Roller climbs.",
                "The scan is bounded by a named preset and caps selected ways/candidates.",
                "No coordinate fields, raw geometry, GPS tracks, or raw point arrays are returned.",
            ],
        )
        summary["preset_id"] = preset_id
        summary["preset_description"] = preset.get("description")
        summary["cache_status"] = "miss" if overpass_payload is None else "fixture"
        summary["fetch_status"] = fetch_status
    except Exception as exc:
        summary = _scan_error_payload(preset_id=preset_id, preset=preset, error=exc)

    if overpass_payload is None and elevation_lookup is None:
        cache_payload = deepcopy(summary)
        cache_payload.pop("cache_status", None)
        _CLIMB_LAB_SCAN_CACHE[cache_key] = cache_payload
    return summary


def _build_elevation_signal(
    *,
    ride_name: str,
    ride_date: str | None,
    rank: int,
    start_idx: int,
    end_idx: int,
    elevation: list[float | None],
    distance: list[float | None],
    time_ms: list[float | None],
) -> dict[str, Any] | None:
    if end_idx <= start_idx:
        return None
    start_elevation = elevation[start_idx]
    end_elevation = elevation[end_idx]
    start_distance = distance[start_idx]
    end_distance = distance[end_idx]
    if (
        start_elevation is None
        or end_elevation is None
        or start_distance is None
        or end_distance is None
    ):
        return None
    gain_m = end_elevation - start_elevation
    distance_m = end_distance - start_distance
    if gain_m <= 0 or distance_m <= 0:
        return None
    avg_grade_pct = (gain_m / distance_m) * 100
    ride_distance_m = max(value for value in distance if value is not None) if distance else 0
    ride_start_ms = next((value for value in time_ms if value is not None), None)
    start_time = time_ms[start_idx] if start_idx < len(time_ms) else None
    end_time = time_ms[end_idx] if end_idx < len(time_ms) else None
    duration_s = (
        max(0, (end_time - start_time) / 1000)
        if start_time is not None and end_time is not None
        else 0
    )

    return {
        "signal_id": f"{ride_name}:signal-{rank}",
        "rank": rank,
        "ride_file": ride_name,
        "activity_date": ride_date,
        "start_pct": round((start_distance / ride_distance_m) * 100, 1)
        if ride_distance_m > 0
        else None,
        "end_pct": round((end_distance / ride_distance_m) * 100, 1)
        if ride_distance_m > 0
        else None,
        "start_offset_label": _offset_label(ride_start_ms, start_time),
        "end_offset_label": _offset_label(ride_start_ms, end_time),
        "duration_label": _duration_label(duration_s),
        "distance_m": round(distance_m, 1),
        "gain_m": round(gain_m, 1),
        "avg_grade_pct": round(avg_grade_pct, 1),
        "gain_band": _gain_band(gain_m),
        "confidence": _signal_confidence(
            gain_m=gain_m,
            distance_m=distance_m,
            avg_grade_pct=avg_grade_pct,
        ),
        "reason": "Sustained uphill interval from ride elevation and distance series.",
    }


def detect_elevation_signals(
    activity: Any,
    *,
    ride_name: str = "activity",
    ride_date: str | None = None,
    min_gain_m: float = 45,
    min_distance_m: float = 300,
    min_avg_grade_pct: float = 2,
    max_descent_gap_m: float = 8,
    max_signals: int = 5,
) -> list[dict[str, Any]]:
    """Detect derived uphill intervals without returning coordinates or samples."""
    elevation = _smoothed(_series_values(getattr(activity, "elevation_m", None)))
    distance = _series_values(getattr(activity, "dist_m", None))
    time_ms = _series_values(getattr(activity, "time_ms", None))
    sample_count = min(len(elevation), len(distance), len(time_ms))
    if sample_count < 2:
        return []
    elevation = elevation[:sample_count]
    distance = distance[:sample_count]
    time_ms = time_ms[:sample_count]

    raw_candidates: list[tuple[int, int, float, float, float]] = []
    low_idx: int | None = None
    peak_idx: int | None = None
    for idx in range(sample_count):
        elev = elevation[idx]
        dist = distance[idx]
        if elev is None or dist is None:
            continue
        if low_idx is None or elevation[low_idx] is None:
            low_idx = idx
            peak_idx = idx
            continue
        if peak_idx is None or elevation[peak_idx] is None:
            peak_idx = idx
        if elev < (elevation[low_idx] or elev):
            low_idx = idx
            peak_idx = idx
            continue
        if elev > (elevation[peak_idx] or elev):
            peak_idx = idx
        peak_elev = elevation[peak_idx] or elev
        if peak_idx > low_idx and peak_elev - elev > max_descent_gap_m:
            start_dist = distance[low_idx]
            end_dist = distance[peak_idx]
            start_elev = elevation[low_idx]
            end_elev = elevation[peak_idx]
            if (
                start_dist is not None
                and end_dist is not None
                and start_elev is not None
                and end_elev is not None
            ):
                gain_m = end_elev - start_elev
                distance_m = end_dist - start_dist
                grade = (gain_m / distance_m) * 100 if distance_m > 0 else 0
                if (
                    gain_m >= min_gain_m
                    and distance_m >= min_distance_m
                    and grade >= min_avg_grade_pct
                ):
                    raw_candidates.append((low_idx, peak_idx, gain_m, distance_m, grade))
            low_idx = idx
            peak_idx = idx

    if low_idx is not None and peak_idx is not None and peak_idx > low_idx:
        start_dist = distance[low_idx]
        end_dist = distance[peak_idx]
        start_elev = elevation[low_idx]
        end_elev = elevation[peak_idx]
        if (
            start_dist is not None
            and end_dist is not None
            and start_elev is not None
            and end_elev is not None
        ):
            gain_m = end_elev - start_elev
            distance_m = end_dist - start_dist
            grade = (gain_m / distance_m) * 100 if distance_m > 0 else 0
            if (
                gain_m >= min_gain_m
                and distance_m >= min_distance_m
                and grade >= min_avg_grade_pct
            ):
                raw_candidates.append((low_idx, peak_idx, gain_m, distance_m, grade))

    ranked = sorted(
        raw_candidates,
        key=lambda row: (row[2], row[3], row[4]),
        reverse=True,
    )[:max_signals]
    signals = []
    for rank, (start_idx, end_idx, _gain, _distance, _grade) in enumerate(ranked, start=1):
        signal = _build_elevation_signal(
            ride_name=ride_name,
            ride_date=ride_date,
            rank=rank,
            start_idx=start_idx,
            end_idx=end_idx,
            elevation=elevation,
            distance=distance,
            time_ms=time_ms,
        )
        if signal is not None:
            signals.append(signal)
    return signals


def _parse_with_workout_parse(path: Path) -> Any:
    import workout_parse as wp

    return wp.parse_file(str(path))


def summarize_activity_file(path: str | Path, *, parser: Any = None) -> dict[str, Any]:
    """Parse one activity file into privacy-preserving calibration metadata."""
    activity_path = Path(path)
    parser = parser or _parse_with_workout_parse

    base: dict[str, Any] = {
        "name": activity_path.name,
        "extension": activity_path.suffix.lower().lstrip("."),
        "activity_date": _activity_date_from_name(activity_path),
        "modified_at": _iso_mtime(activity_path),
        "privacy_mode": "no_coordinates",
    }
    try:
        base["size_bytes"] = activity_path.stat().st_size
    except OSError:
        base["size_bytes"] = 0

    try:
        activity = parser(activity_path)
    except Exception as exc:
        return {
            **base,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    time_ms = getattr(activity, "time_ms", None)
    sample_count = len(time_ms) if time_ms is not None else 0
    duration_s = float(getattr(activity, "total_elapsed_s", 0) or 0)
    lat_e7 = getattr(activity, "lat_e7", None)
    lon_e7 = getattr(activity, "lon_e7", None)
    elevation_values = _float_values(getattr(activity, "elevation_m", None))
    power_values = getattr(activity, "pwr_w", None)
    hr_values = getattr(activity, "hr_bpm", None)
    gain_m = _naive_positive_gain(elevation_values)
    elevation_min = min(elevation_values) if elevation_values else None
    elevation_max = max(elevation_values) if elevation_values else None
    has_gps = (
        lat_e7 is not None
        and lon_e7 is not None
        and len(lat_e7) > 0
        and len(lon_e7) > 0
    )
    has_elevation = len(elevation_values) > 0
    has_power = power_values is not None and len(power_values) > 0
    has_hr = hr_values is not None and len(hr_values) > 0
    gain_band = _gain_band(gain_m)

    return {
        **base,
        "status": "parsed",
        "sport": _clean_scalar(getattr(activity, "sport", None)),
        "sample_count": sample_count,
        "duration_s": round(duration_s),
        "duration_label": _duration_label(duration_s),
        "has_gps": has_gps,
        "has_elevation": has_elevation,
        "has_power": has_power,
        "has_hr": has_hr,
        "elevation_min_m": round(elevation_min, 1) if elevation_min is not None else None,
        "elevation_max_m": round(elevation_max, 1) if elevation_max is not None else None,
        "naive_gain_m": round(gain_m, 1),
        "gain_band": gain_band,
        "calibration_use": (
            "Good climb calibration candidate"
            if gain_band in {"large", "calibration"}
            else "Lower climb signal; useful as contrast"
        ),
    }


def _source_by_id(source_id: str) -> dict[str, str] | None:
    for source in _activity_sources():
        if source["id"] == source_id:
            return source
    return None


def build_climb_lab_calibration_inventory(
    *,
    source_id: str = "garmin_device",
    limit: int = 18,
    offset: int = 0,
    parser: Any = None,
) -> dict[str, Any]:
    source = _source_by_id(source_id)
    if source is None:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "local_dev_only",
            "privacy_mode": "no_coordinates",
            "source_id": source_id,
            "source_label": "Unknown source",
            "source_path": None,
            "available": False,
            "error": "Unknown ClimbLab source.",
            "totals": {
                "files_considered": 0,
                "rides_returned": 0,
                "parsed": 0,
                "errors": 0,
                "with_gps": 0,
                "with_elevation": 0,
                "gain_candidates": 0,
                "naive_gain_m": 0,
            },
            "rides": [],
        }

    directory = Path(source["path"])
    files = list(reversed(_activity_files(directory)))
    limit = _bounded_limit(limit)
    offset = max(0, offset)
    selected = files[offset : offset + limit]
    rides = [
        _cached_activity_summary(
            kind="calibration",
            path=path,
            parser=parser,
            params=(),
            builder=lambda path=path: summarize_activity_file(path, parser=parser),
        )
        for path in selected
    ]
    parsed = [ride for ride in rides if ride.get("status") == "parsed"]
    errors = [ride for ride in rides if ride.get("status") != "parsed"]
    gain_candidates = [
        ride
        for ride in parsed
        if float(ride.get("naive_gain_m") or 0) >= 250
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "privacy_mode": "no_coordinates",
        "source_id": source_id,
        "source_label": source["label"],
        "source_path": str(directory),
        "available": directory.exists() and directory.is_dir(),
        "limit": limit,
        "offset": offset,
        "guardrails": [
            "No latitude, longitude, GPS track, or raw samples are returned.",
            "Each ride summary is derived locally from mounted files.",
            "Calibration signal does not create official climb matches.",
        ],
        "cache": _cache_payload(rides),
        "totals": {
            "files_considered": len(files),
            "rides_returned": len(rides),
            "parsed": len(parsed),
            "errors": len(errors),
            "with_gps": sum(1 for ride in parsed if ride.get("has_gps")),
            "with_elevation": sum(1 for ride in parsed if ride.get("has_elevation")),
            "gain_candidates": len(gain_candidates),
            "naive_gain_m": round(sum(float(ride.get("naive_gain_m") or 0) for ride in parsed), 1),
        },
        "rides": rides,
    }


def summarize_activity_elevation_signals(
    path: str | Path,
    *,
    parser: Any = None,
    max_signals: int = 5,
    min_gain_m: float = 45,
) -> dict[str, Any]:
    """Parse one activity file into derived climb-like elevation signals."""
    activity_path = Path(path)
    parser = parser or _parse_with_workout_parse
    base: dict[str, Any] = {
        "name": activity_path.name,
        "extension": activity_path.suffix.lower().lstrip("."),
        "activity_date": _activity_date_from_name(activity_path),
        "modified_at": _iso_mtime(activity_path),
        "privacy_mode": "no_coordinates_no_raw_trace",
    }
    try:
        activity = parser(activity_path)
    except Exception as exc:
        return {
            **base,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "signals": [],
        }

    distance_values = _float_values(getattr(activity, "dist_m", None))
    signals = detect_elevation_signals(
        activity,
        ride_name=activity_path.name,
        ride_date=_activity_date_from_name(activity_path),
        min_gain_m=min_gain_m,
        max_signals=max_signals,
    )
    return {
        **base,
        "status": "parsed",
        "sport": _clean_scalar(getattr(activity, "sport", None)),
        "distance_m": round(max(distance_values), 1) if distance_values else 0,
        "signal_count": len(signals),
        "top_gain_m": max((signal["gain_m"] for signal in signals), default=0),
        "signals": signals,
    }


def build_climb_lab_elevation_signal_summary(
    *,
    source_id: str = "garmin_device",
    file_limit: int = 18,
    signal_limit: int = 24,
    min_gain_m: float = 45,
    parser: Any = None,
) -> dict[str, Any]:
    source = _source_by_id(source_id)
    if source is None:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "local_dev_only",
            "privacy_mode": "no_coordinates_no_raw_trace",
            "source_id": source_id,
            "source_label": "Unknown source",
            "source_path": None,
            "available": False,
            "error": "Unknown ClimbLab source.",
            "totals": {
                "files_considered": 0,
                "files_scanned": 0,
                "parsed": 0,
                "errors": 0,
                "rides_with_signals": 0,
                "signals_returned": 0,
                "top_gain_m": 0,
                "total_signal_gain_m": 0,
            },
            "rides": [],
            "signals": [],
        }

    directory = Path(source["path"])
    files = list(reversed(_activity_files(directory)))
    file_limit = _bounded_limit(file_limit, default=18, maximum=80)
    signal_limit = _bounded_limit(signal_limit, default=24, maximum=80)
    selected = files[:file_limit]
    per_ride_signal_limit = 5
    rides = [
        _cached_activity_summary(
            kind="elevation_signals",
            path=path,
            parser=parser,
            params=(per_ride_signal_limit, min_gain_m),
            builder=lambda path=path: summarize_activity_elevation_signals(
                path,
                parser=parser,
                max_signals=per_ride_signal_limit,
                min_gain_m=min_gain_m,
            ),
        )
        for path in selected
    ]
    parsed = [ride for ride in rides if ride.get("status") == "parsed"]
    errors = [ride for ride in rides if ride.get("status") != "parsed"]
    all_signals = [
        signal
        for ride in parsed
        for signal in ride.get("signals", [])
    ]
    top_signals = sorted(
        all_signals,
        key=lambda signal: (
            float(signal.get("gain_m") or 0),
            float(signal.get("distance_m") or 0),
            float(signal.get("avg_grade_pct") or 0),
        ),
        reverse=True,
    )[:signal_limit]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "privacy_mode": "no_coordinates_no_raw_trace",
        "source_id": source_id,
        "source_label": source["label"],
        "source_path": str(directory),
        "available": directory.exists() and directory.is_dir(),
        "file_limit": file_limit,
        "signal_limit": signal_limit,
        "min_gain_m": min_gain_m,
        "guardrails": [
            "Signals are derived from elevation, distance, and time only.",
            "No coordinate fields, GPS track, or raw point arrays are returned.",
            "Elevation signals are not official Boulder Roller climbs.",
        ],
        "cache": _cache_payload(rides),
        "totals": {
            "files_considered": len(files),
            "files_scanned": len(rides),
            "parsed": len(parsed),
            "errors": len(errors),
            "rides_with_signals": sum(1 for ride in parsed if ride.get("signal_count", 0) > 0),
            "signals_returned": len(top_signals),
            "top_gain_m": max((signal["gain_m"] for signal in top_signals), default=0),
            "total_signal_gain_m": round(
                sum(float(signal.get("gain_m") or 0) for signal in top_signals),
                1,
            ),
        },
        "rides": rides,
        "signals": top_signals,
    }


def summarize_activity_directory(
    *,
    source_id: str,
    label: str,
    path: str | Path,
    recent_limit: int = 8,
) -> dict[str, Any]:
    directory = Path(path)
    files = _activity_files(directory)
    extension_counts = Counter(path.suffix.lower().lstrip(".") for path in files)
    year_counts = Counter(_year_from_filename(path) for path in files)
    total_bytes = 0
    readable_files = []
    for activity_path in files:
        try:
            total_bytes += activity_path.stat().st_size
            readable_files.append(activity_path)
        except OSError:
            continue
    first_file = files[0] if files else None
    last_file = files[-1] if files else None

    return {
        "id": source_id,
        "label": label,
        "path": str(directory),
        "available": directory.exists() and directory.is_dir(),
        "privacy_mode": "metadata_only",
        "file_count": len(files),
        "total_bytes": total_bytes,
        "summary": _source_summary(source_id=source_id, file_count=len(files)),
        "extensions": dict(sorted(extension_counts.items())),
        "years": dict(sorted(year_counts.items())),
        "date_range": {
            "start": _date_from_filename(first_file),
            "end": _date_from_filename(last_file),
        },
        "first_file": first_file.name if first_file else None,
        "last_file": last_file.name if last_file else None,
        "recent_files": _recent_file_payload(readable_files, recent_limit),
    }


def build_climb_lab_corpus_summary() -> dict[str, Any]:
    sources = [
        summarize_activity_directory(
            source_id=source["id"],
            label=source["label"],
            path=source["path"],
        )
        for source in _activity_sources()
    ]
    available_sources = [source for source in sources if source["available"]]
    active_sources = [source for source in available_sources if source["file_count"] > 0]
    total_files = sum(source["file_count"] for source in active_sources)
    total_bytes = sum(source["total_bytes"] for source in active_sources)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_dev_only",
        "privacy_mode": "metadata_only",
        "candidate_layer_status": "road_graph_scaffolded",
        "totals": {
            "available_sources": len(available_sources),
            "active_sources": len(active_sources),
            "configured_sources": len(sources),
            "activity_files": total_files,
            "total_bytes": total_bytes,
        },
        "guardrails": [
            "No GPS coordinates are emitted by this endpoint.",
            "No ride files are copied, uploaded, or modified.",
            "ClimbLab candidates are not official Boulder Roller climbs.",
            "This surface is gated behind ENABLE_DEV_ROUTES.",
        ],
        "pipeline": [
            {
                "id": "road_graph",
                "label": "Road graph",
                "status": "scaffolded",
                "summary": "Normalize roads into directed intersection-to-intersection edges.",
                "plain_language": "Build the map skeleton.",
                "decision": "Which roads and turns can a rider actually use?",
            },
            {
                "id": "elevation_attachment",
                "label": "Elevation attachment",
                "status": "planned",
                "summary": "Sample DEM elevation along each directed edge.",
                "plain_language": "Put the terrain on the roads.",
                "decision": "Where does the land create a climb-like event?",
            },
            {
                "id": "edge_climb_signal",
                "label": "Edge climb signal",
                "status": "scaffolded",
                "summary": "Score each edge for climb-bearing direction, gain, grade, and continuity.",
                "plain_language": "Mark the road pieces carrying climb signal.",
                "decision": "Which direction and section actually feels uphill?",
            },
            {
                "id": "climb_stringing",
                "label": "Climb stringing",
                "status": "planned",
                "summary": "Connect climb-bearing edges through intersections into candidate climb strings.",
                "plain_language": "Join road pieces into possible climbs.",
                "decision": "Should this keep going through the intersection?",
            },
            {
                "id": "garmin_calibration",
                "label": "Garmin calibration",
                "status": "scaffolded",
                "summary": "Use local activity traces later to validate natural starts, finishes, and continuations.",
                "plain_language": "Check candidates against real riding.",
                "decision": "Do actual rides confirm or contradict the terrain guess?",
            },
            {
                "id": "expert_review",
                "label": "Expert review",
                "status": "planned",
                "summary": "Expose split, merge, trim, suppress, and approve decisions in the lab.",
                "plain_language": "Turn machine candidates into beautiful climb objects.",
                "decision": "What would a serious local rider recognize?",
            },
        ],
        "sources": sources,
    }
