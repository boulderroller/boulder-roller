#!/usr/bin/env python3
"""
Render a self-contained HTML climb-review report for a ride.

The goal is to make climb validation visual and conversational instead of
forcing manual comparison of console output. The report mirrors the current
product pipeline more closely by default:

- parse ride data
- build tile-run samples when backend helpers are available
- run persistence on the selected sample mode as a research reference
- compare against the canonical detector and expected climbs
- flag persistence segments that look suspicious for product display

Examples:

  python3 tests/validation/render_climb_review.py \
    --validation-file in_the_bag_.fit

  python3 tests/validation/render_climb_review.py \
    --file /tmp/corey.fit \
    --terrain rolling \
    --output /tmp/corey-review.html

  python3 tests/validation/render_climb_review.py \
    --ride-id 1d129d39-f2da-46c0-94d6-73726cb5b536 \
    --terrain rolling \
    --output /tmp/live-ride-review.html
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import html
import io
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VALIDATION_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from workout_parse_runtime import import_workout_parse_verified, runtime_status

wp = import_workout_parse_verified()

try:
    from app.services.patterns.climb import detect_climbs_with_rust
    from app.services.tile_service import TileService
except Exception:
    detect_climbs_with_rust = None
    TileService = None

try:
    import psycopg2
    from app.services.file_storage import create_file_storage_service
    from app.services.ride_parser import parse_ride_file

    try:
        from app.services.workout_parse_adapter import parse_ride_file_bytes_rust
    except Exception:
        parse_ride_file_bytes_rust = None
except Exception:
    psycopg2 = None
    create_file_storage_service = None
    parse_ride_file = None
    parse_ride_file_bytes_rust = None


DEFAULT_WEIGHT_KG = 75.0
DEFAULT_MIN_VERT_M = 20.0
DEFAULT_SAMPLE_MODE = "tile-runs"
DEFAULT_TERRAIN = "manifest"
DEFAULT_EXPECTED_MATCH_TOLERANCE_S = 240
DEFAULT_COMPARISON_MATCH_START_TOLERANCE_S = 180
DEFAULT_COMPARISON_MATCH_OVERLAP_RATIO = 0.35
LOW_GRADE_THRESHOLD_PCT = 2.0
LOW_VAM_THRESHOLD_MHR = 180.0
LONG_DRAG_THRESHOLD_S = 600
WEAK_BOUNDARY_DELTA_FLOOR_M = 8.0
STRONG_OVERLAP_RATIO = 0.6
TERRAIN_OPTIONS = ["auto", "flat", "rolling", "urban_hills", "hilly", "mountainous"]
REVIEW_COLORS = {
    "keeper": "#2e7d32",
    "review": "#b7791f",
    "suspicious": "#b23a3a",
}


@dataclass
class RideMeta:
    ride_id: Optional[str]
    title: Optional[str]
    file_type: str
    raw_file_path: Optional[str]
    raw_file_size_bytes: Optional[int]
    started_at: Optional[str]
    uploaded_at: Optional[str]
    processing_status: Optional[str]
    distance_m: Optional[float]
    elevation_gain_m: Optional[float]
    live_climb_rows: Optional[int]


@dataclass
class LoadedRide:
    ride_label: str
    ride_path: Path
    file_type: str
    source_kind: str
    parser_mode: str
    points: list[dict[str, Any]]
    manifest_entry: Optional[dict[str, Any]]
    ride_meta: Optional[RideMeta]
    temp_path: Optional[Path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render an HTML climb-review report")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--validation-file",
        help="Filename from tests/validation/manifest.json",
    )
    source.add_argument(
        "--file",
        help="Path to a local ride file supported by workout_parse.parse_file()",
    )
    source.add_argument(
        "--ride-id",
        help="Ride UUID to fetch from database + storage for a live review",
    )
    parser.add_argument(
        "--file-type",
        help="Optional file type override for --file or downloaded ride (fit/gpx/tcx)",
    )
    parser.add_argument(
        "--terrain",
        default=DEFAULT_TERRAIN,
        choices=["manifest", *TERRAIN_OPTIONS],
        help=(
            "Optional terrain hint for the supporting momentum sweep. 'manifest' uses the "
            "validation manifest terrain when available, otherwise falls back to auto."
        ),
    )
    parser.add_argument(
        "--sample-mode",
        default=DEFAULT_SAMPLE_MODE,
        choices=["raw", "tile-runs"],
        help="Detector sample mode. tile-runs mirrors the product pipeline when available.",
    )
    parser.add_argument(
        "--output",
        help="Output HTML path (defaults to /tmp/<ride>.climb-review.html)",
    )
    parser.add_argument(
        "--weight-kg",
        type=float,
        default=DEFAULT_WEIGHT_KG,
        help=f"Weight used for detector calls (default: {DEFAULT_WEIGHT_KG})",
    )
    parser.add_argument(
        "--min-vert-m",
        type=float,
        default=DEFAULT_MIN_VERT_M,
        help=f"Minimum vert to show in chart lanes/tables (default: {DEFAULT_MIN_VERT_M})",
    )
    parser.add_argument(
        "--skip-terrain-sweep",
        action="store_true",
        help="Skip running momentum across all terrain presets for the supporting sweep table",
    )
    return parser.parse_args()


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


def infer_file_type(path: Path) -> str:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    for suffix in reversed(suffixes):
        if suffix in {".fit", ".gpx", ".tcx"}:
            return suffix.lstrip(".")
    if path.suffix:
        return path.suffix.lstrip(".").lower()
    return "fit"


def default_output_path(ride_label: str) -> Path:
    stem = ride_label.replace(" ", "_")
    return Path("/tmp") / f"{stem}.climb-review.html"


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _load_via_backend_parser(file_bytes: bytes, file_type: str) -> tuple[Any, str]:
    if parse_ride_file_bytes_rust is not None:
        return parse_ride_file_bytes_rust(file_bytes, file_type), "backend-rust"
    if parse_ride_file is None:
        raise RuntimeError("backend parser helpers are not available")
    file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
    return parse_ride_file(file_data_b64, file_type), "backend-python"


def _records_to_points(parsed_ride: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for rec in parsed_ride.records:
        lat = getattr(rec, "lat", None) or getattr(rec, "latitude", None)
        lon = getattr(rec, "lon", None) or getattr(rec, "longitude", None)
        ts = getattr(rec, "timestamp", None)
        if lat is None or lon is None or ts is None:
            continue
        points.append(
            {
                "timestamp": ts,
                "lat": lat,
                "lon": lon,
                "elevation_m": getattr(rec, "elevation_m", None),
                "power_w": getattr(rec, "power_w", None),
                "hr_bpm": getattr(rec, "heart_rate_bpm", None) or getattr(rec, "hr_bpm", None),
                "speed_mps": getattr(rec, "speed_mps", None),
            }
        )
    points.sort(key=lambda point: point["timestamp"])
    return points


def _activity_to_points(activity: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for idx in range(len(activity.time_ms)):
        if activity.lat_e7 is None or activity.lon_e7 is None:
            continue
        if idx >= len(activity.lat_e7) or idx >= len(activity.lon_e7):
            continue
        lat = float(activity.lat_e7[idx]) / 1e7
        lon = float(activity.lon_e7[idx]) / 1e7
        point: dict[str, Any] = {
            "timestamp": float(int(activity.time_ms[idx]) / 1000.0),
            "lat": lat,
            "lon": lon,
        }
        if activity.elevation_m is not None and idx < len(activity.elevation_m):
            elev = float(activity.elevation_m[idx])
            if elev > -500:
                point["elevation_m"] = elev
        if activity.pwr_w is not None and idx < len(activity.pwr_w):
            power = int(activity.pwr_w[idx])
            if 0 < power < 5000:
                point["power_w"] = power
        if activity.hr_bpm is not None and idx < len(activity.hr_bpm):
            hr = int(activity.hr_bpm[idx])
            if 0 < hr < 255:
                point["hr_bpm"] = hr
        points.append(point)
    return points


def _get_db_connection() -> Any:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for --ride-id")
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not available in this environment")
    return psycopg2.connect(database_url)


def _fetch_ride_meta(ride_id: str) -> RideMeta:
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            select r.id,
                   coalesce(r.file_name, ''),
                   coalesce(r.file_type, 'fit'),
                   r.raw_file_path,
                   r.raw_file_size_bytes,
                   r.started_at,
                   r.uploaded_at,
                   r.processing_status,
                   r.distance_m,
                   r.elevation_gain_m,
                   (
                     select count(*)
                     from patterns_climb pc
                     where pc.activity_id = r.id
                   ) as live_climb_rows
            from rides r
            where r.id = %s
            limit 1
            """,
            (ride_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"Ride not found: {ride_id}")
        return RideMeta(
            ride_id=row[0],
            title=row[1] or None,
            file_type=row[2],
            raw_file_path=row[3],
            raw_file_size_bytes=row[4],
            started_at=row[5].isoformat() if row[5] else None,
            uploaded_at=row[6].isoformat() if row[6] else None,
            processing_status=row[7],
            distance_m=float(row[8]) if row[8] is not None else None,
            elevation_gain_m=float(row[9]) if row[9] is not None else None,
            live_climb_rows=int(row[10]) if row[10] is not None else None,
        )
    finally:
        conn.close()


async def _download_storage_file(path: str) -> bytes:
    if create_file_storage_service is None:
        raise RuntimeError("Storage helpers are not available in this environment")
    storage = create_file_storage_service()
    return await storage.download_ride_file(path)


def resolve_ride_source(args: argparse.Namespace) -> LoadedRide:
    manifest_entry = None
    ride_meta = None
    temp_path = None

    if args.validation_file:
        manifest = load_manifest()
        manifest_entry = next(
            (entry for entry in manifest["files"] if entry["file"] == args.validation_file),
            None,
        )
        if manifest_entry is None:
            raise SystemExit(f"Validation file not found in manifest: {args.validation_file}")
        ride_path = VALIDATION_DIR / args.validation_file
        if not ride_path.exists():
            raise SystemExit(f"Ride file not found: {ride_path}")
        activity = wp.parse_file(str(ride_path))
        points = _activity_to_points(activity)
        return LoadedRide(
            ride_label=ride_path.name,
            ride_path=ride_path,
            file_type=args.file_type or infer_file_type(ride_path),
            source_kind="validation",
            parser_mode="workout-parse",
            points=points,
            manifest_entry=manifest_entry,
            ride_meta=None,
            temp_path=None,
        )

    if args.file:
        ride_path = Path(args.file).expanduser().resolve()
        if not ride_path.exists():
            raise SystemExit(f"Ride file not found: {ride_path}")
        activity = wp.parse_file(str(ride_path))
        points = _activity_to_points(activity)
        return LoadedRide(
            ride_label=ride_path.name,
            ride_path=ride_path,
            file_type=args.file_type or infer_file_type(ride_path),
            source_kind="local-file",
            parser_mode="workout-parse",
            points=points,
            manifest_entry=None,
            ride_meta=None,
            temp_path=None,
        )

    if create_file_storage_service is None or parse_ride_file is None:
        raise SystemExit(
            "--ride-id requires backend storage/parser helpers. Run from the repo environment."
        )

    ride_meta = _fetch_ride_meta(args.ride_id)
    if not ride_meta.raw_file_path:
        raise SystemExit(f"Ride {args.ride_id} has no raw_file_path")
    file_bytes = asyncio.run(_download_storage_file(ride_meta.raw_file_path))
    parsed_ride, parser_mode = _load_via_backend_parser(file_bytes, ride_meta.file_type)
    points = _records_to_points(parsed_ride)
    temp_file = tempfile.NamedTemporaryFile(
        prefix=f"{ride_meta.ride_id or 'ride'}-",
        suffix=f".{ride_meta.file_type}",
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.write(file_bytes)
    temp_file.close()
    return LoadedRide(
        ride_label=ride_meta.title or ride_meta.ride_id or temp_path.name,
        ride_path=temp_path,
        file_type=ride_meta.file_type,
        source_kind="live-ride",
        parser_mode=parser_mode,
        points=points,
        manifest_entry=None,
        ride_meta=ride_meta,
        temp_path=temp_path,
    )


def build_sample_views(
    points: list[dict[str, Any]],
    sample_mode: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    raw_samples: list[dict[str, Any]] = []
    profile_times_s: list[int] = []
    profile_elevs_m: list[float] = []
    duration_s = 0
    start_time_s = None
    if points:
        first_ts = points[0]["timestamp"]
        start_time_s = first_ts.timestamp() if hasattr(first_ts, "timestamp") else float(first_ts)

    for idx, point in enumerate(points):
        ts = point.get("timestamp")
        if ts is None:
            continue
        ts_s = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
        if start_time_s is None:
            start_time_s = ts_s
        t_s = int(max(0, ts_s - start_time_s))
        duration_s = max(duration_s, t_s)
        sample = {
            "t": t_s,
            "lat": point.get("lat"),
            "lon": point.get("lon"),
            "elevation_m": point.get("elevation_m"),
            "power_w": point.get("power_w"),
            "hr_bpm": point.get("hr_bpm"),
            "speed_mps": point.get("speed_mps"),
        }
        raw_samples.append(sample)
        elev = point.get("elevation_m")
        if elev is not None:
            profile_times_s.append(t_s)
            profile_elevs_m.append(float(elev))

    raw_tile_samples: list[dict[str, Any]] = []
    if TileService is not None and points:
        tile_service = TileService()
        raw_tile_samples = [
            {
                "tile_id": sample.tile_id,
                "t": int(sample.t),
                "lat": sample.lat,
                "lon": sample.lon,
                "elevation_m": sample.elevation_m,
                "power_w": sample.power_w,
                "hr_bpm": sample.hr_bpm,
                "speed_mps": sample.speed_mps,
            }
            for sample in tile_service.get_tile_sequence(
                points,
                resolution=10,
                start_time=start_time_s,
            )
        ]

    tile_runs: list[dict[str, Any]] = []
    sample_mode_used = sample_mode
    if sample_mode == "tile-runs":
        if TileService is None:
            sample_mode_used = "raw"
        else:
            tile_runs = TileService().get_tile_run_sequence(
                points=points,
                resolution=10,
                start_time=start_time_s,
            )
            if not tile_runs:
                sample_mode_used = "raw"

    detection_samples = tile_runs if sample_mode_used == "tile-runs" else raw_samples
    meta = {
        "duration_s": duration_s,
        "profile_times_s": profile_times_s,
        "profile_elevs_m": profile_elevs_m,
        "elev_min_m": round(min(profile_elevs_m), 1) if profile_elevs_m else None,
        "elev_max_m": round(max(profile_elevs_m), 1) if profile_elevs_m else None,
        "raw_samples": len(raw_samples),
        "raw_tile_samples": len(raw_tile_samples),
        "tile_runs": len(tile_runs),
        "sample_mode_requested": sample_mode,
        "sample_mode_used": sample_mode_used,
        "detection_samples": len(detection_samples),
        "tile_runs_available": bool(tile_runs),
    }
    return raw_samples, raw_tile_samples, tile_runs, detection_samples, meta


def summarize_persistence(
    climbs: list[Any],
    samples: list[dict[str, Any]],
    min_vert_m: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    shown_rows: list[dict[str, Any]] = []

    for idx, climb in enumerate(climbs, start=1):
        start_idx = int(climb.effort_start_idx)
        end_idx = int(climb.effort_end_idx)
        start_s = int(samples[start_idx]["t"]) if start_idx < len(samples) else 0
        end_s = int(samples[end_idx]["t"]) if end_idx < len(samples) else start_s
        start_elev_m = (
            float(samples[start_idx]["elevation_m"])
            if start_idx < len(samples) and samples[start_idx].get("elevation_m") is not None
            else None
        )
        end_elev_m = (
            float(samples[end_idx]["elevation_m"])
            if end_idx < len(samples) and samples[end_idx].get("elevation_m") is not None
            else None
        )
        boundary_delta_m = (
            round(end_elev_m - start_elev_m, 1)
            if start_elev_m is not None and end_elev_m is not None
            else None
        )
        row = {
            "index": idx,
            "start_s": start_s,
            "end_s": end_s,
            "vert_m": float(climb.vert_m),
            "time_s": int(climb.time_s),
            "distance_m": float(climb.distance_m),
            "avg_gradient_pct": float(climb.avg_gradient_pct),
            "vam": (float(climb.vert_m) / float(climb.time_s) * 3600.0) if int(climb.time_s) > 0 else 0.0,
            "persistence_m": float(climb.persistence),
            "is_essential": bool(climb.is_essential),
            "effort_start_idx": start_idx,
            "effort_end_idx": end_idx,
            "birth_idx": int(climb.birth_idx),
            "death_idx": int(climb.death_idx),
            "start_elev_m": start_elev_m,
            "end_elev_m": end_elev_m,
            "boundary_delta_m": boundary_delta_m,
        }
        all_rows.append(row)
        if row["vert_m"] >= min_vert_m:
            shown_rows.append(row)

    return all_rows, shown_rows


def summarize_display_climbs(climbs: list[Any], min_vert_m: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    shown_rows: list[dict[str, Any]] = []

    for idx, climb in enumerate(climbs, start=1):
        row = {
            "index": idx,
            "start_s": int(climb.start_time_offset_s),
            "end_s": int(climb.end_time_offset_s),
            "vert_m": float(climb.vert_m),
            "time_s": int(climb.time_s),
            "distance_m": float(climb.distance_m or 0.0),
            "avg_gradient_pct": float(climb.avg_gradient_pct or 0.0),
            "vam": (float(climb.vert_m) / float(climb.time_s) * 3600.0) if int(climb.time_s) > 0 else 0.0,
            "signature_hex": getattr(climb, "signature_hex", None),
        }
        all_rows.append(row)
        if row["vert_m"] >= min_vert_m:
            shown_rows.append(row)

    return all_rows, shown_rows


def summarize_expected(manifest_entry: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not manifest_entry:
        return rows
    for idx, climb in enumerate(manifest_entry.get("expected_climbs", []), start=1):
        rows.append(
            {
                "index": idx,
                "name": climb.get("name") or f"Expected {idx}",
                "start_s": climb.get("approx_start_s"),
                "vert_m": climb.get("approx_vert_m"),
                "avg_gradient_pct": climb.get("approx_gradient_pct"),
                "notes": climb.get("notes") or "",
            }
        )
    return rows


def overlap_seconds(first: dict[str, Any], second: dict[str, Any]) -> int:
    return max(0, min(first["end_s"], second["end_s"]) - max(first["start_s"], second["start_s"]))


def resolve_comparison_terrain(
    terrain_arg: str,
    manifest_entry: Optional[dict[str, Any]],
) -> str:
    if terrain_arg != "manifest":
        return terrain_arg
    if manifest_entry and manifest_entry.get("terrain") in TERRAIN_OPTIONS:
        return str(manifest_entry["terrain"])
    return "auto"


def extract_canonical_terrain(climbs: list[Any]) -> str:
    terrains = {
        str(getattr(climb, "detector_mode", "")).rsplit(":", 1)[-1]
        for climb in climbs
        if str(getattr(climb, "detector_mode", "")).startswith(
            ("canonical:momentum:", "canonical_v2:momentum:")
        )
    }
    if len(terrains) == 1:
        return terrains.pop()
    return "auto"


def compute_canonical_result(
    samples: list[dict[str, Any]],
    persistence_candidate_samples: list[dict[str, Any]],
    weight_kg: float,
    min_vert_m: float,
) -> dict[str, Any]:
    if detect_climbs_with_rust is None:
        raise RuntimeError("backend climb detector import unavailable for canonical review")

    climbs = detect_climbs_with_rust(
        samples,
        user_weight_kg=weight_kg,
        algorithm="canonical_v2",
        persistence_candidate_samples=persistence_candidate_samples,
        generate_signatures=True,
    )
    terrain = extract_canonical_terrain(climbs)
    all_rows, shown_rows = summarize_display_climbs(climbs, min_vert_m)
    return {
        "terrain": terrain,
        "label": "canonical_v2" if terrain == "auto" else f"canonical_v2 ({terrain})",
        "all": all_rows,
        "shown": shown_rows,
    }


def compute_momentum_results(
    samples: list[dict[str, Any]],
    selected_terrain: str,
    weight_kg: float,
    min_vert_m: float,
    skip_sweep: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selected_climbs = wp.detect_climbs_adaptive(
        tile_samples=samples,
        terrain=selected_terrain,
        user_weight_kg=weight_kg,
        algorithm="momentum",
        generate_signatures=True,
    )
    selected_all, selected_shown = summarize_display_climbs(selected_climbs, min_vert_m)
    selected_result = {
        "terrain": selected_terrain,
        "label": "momentum" if selected_terrain == "auto" else f"momentum ({selected_terrain})",
        "all": selected_all,
        "shown": selected_shown,
    }

    sweep_rows: list[dict[str, Any]] = []
    if skip_sweep:
        return selected_result, sweep_rows

    for terrain in TERRAIN_OPTIONS:
        climbs = wp.detect_climbs_adaptive(
            tile_samples=samples,
            terrain=terrain,
            user_weight_kg=weight_kg,
            algorithm="momentum",
            generate_signatures=True,
        )
        all_rows, shown_rows = summarize_display_climbs(climbs, min_vert_m)
        sweep_rows.append(
            {
                "terrain": terrain,
                "total": len(all_rows),
                "shown": len(shown_rows),
                "selected": terrain == selected_terrain,
            }
        )

    return selected_result, sweep_rows


def base_strength_score(row: dict[str, Any]) -> int:
    score = 0
    if row["vert_m"] >= 80:
        score += 3
    elif row["vert_m"] >= 50:
        score += 2
    elif row["vert_m"] >= 30:
        score += 1

    if row["avg_gradient_pct"] >= 5.0:
        score += 3
    elif row["avg_gradient_pct"] >= 3.5:
        score += 2
    elif row["avg_gradient_pct"] >= 2.0:
        score += 1

    if row["vam"] >= 700:
        score += 3
    elif row["vam"] >= 400:
        score += 2
    elif row["vam"] >= 250:
        score += 1

    if row["time_s"] >= 1500 and row["avg_gradient_pct"] < LOW_GRADE_THRESHOLD_PCT:
        score -= 2
    elif row["time_s"] >= LONG_DRAG_THRESHOLD_S and row["avg_gradient_pct"] < LOW_GRADE_THRESHOLD_PCT:
        score -= 1

    if row["boundary_delta_m"] is not None and row["boundary_delta_m"] < max(
        WEAK_BOUNDARY_DELTA_FLOOR_M,
        row["vert_m"] * 0.35,
    ):
        score -= 2

    return score


def annotate_persistence_rows(
    persistence_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_with_starts = [row for row in expected_rows if row["start_s"] is not None]

    for row in persistence_rows:
        row["strength_score"] = base_strength_score(row)
        row["flags"] = []

        expected_matches = [
            expected["index"]
            for expected in expected_with_starts
            if abs(int(expected["start_s"]) - row["start_s"]) <= DEFAULT_EXPECTED_MATCH_TOLERANCE_S
        ]
        comparison_matches = []
        for comparison in comparison_rows:
            overlap = overlap_seconds(row, comparison)
            shortest = max(1, min(row["time_s"], comparison["time_s"]))
            if overlap / shortest >= DEFAULT_COMPARISON_MATCH_OVERLAP_RATIO:
                comparison_matches.append(comparison["index"])
                continue
            if abs(comparison["start_s"] - row["start_s"]) <= DEFAULT_COMPARISON_MATCH_START_TOLERANCE_S:
                comparison_matches.append(comparison["index"])

        row["expected_matches"] = expected_matches
        row["comparison_matches"] = sorted(set(comparison_matches))

        if row["avg_gradient_pct"] < LOW_GRADE_THRESHOLD_PCT and row["time_s"] >= LONG_DRAG_THRESHOLD_S:
            row["flags"].append("long low-grade drag")
        if row["vam"] < LOW_VAM_THRESHOLD_MHR and row["time_s"] >= LONG_DRAG_THRESHOLD_S:
            row["flags"].append("low VAM for displayed climb")
        if row["boundary_delta_m"] is not None and row["boundary_delta_m"] < max(
            WEAK_BOUNDARY_DELTA_FLOOR_M,
            row["vert_m"] * 0.35,
        ):
            row["flags"].append("weak start/end net rise")

    for row in persistence_rows:
        overlapping_stronger: list[int] = []
        broad_parent_of: list[int] = []
        for peer in persistence_rows:
            if peer["index"] == row["index"]:
                continue
            overlap = overlap_seconds(row, peer)
            if overlap <= 0:
                continue

            overlap_ratio = overlap / max(1, min(row["time_s"], peer["time_s"]))
            peer_stronger = peer["strength_score"] >= row["strength_score"] + 2
            peer_is_tighter = peer["time_s"] <= row["time_s"]
            if overlap_ratio >= STRONG_OVERLAP_RATIO and peer_stronger and peer_is_tighter:
                overlapping_stronger.append(peer["index"])

            if (
                row["start_s"] <= peer["start_s"]
                and row["end_s"] >= peer["end_s"]
                and row["time_s"] >= max(peer["time_s"] * 1.75, peer["time_s"] + 180)
                and row["avg_gradient_pct"] < LOW_GRADE_THRESHOLD_PCT
                and peer["strength_score"] > row["strength_score"]
            ):
                broad_parent_of.append(peer["index"])

        if broad_parent_of:
            row["flags"].append(
                "broad parent around " + ", ".join(f"#{idx}" for idx in sorted(set(broad_parent_of)))
            )
        elif overlapping_stronger:
            row["flags"].append(
                "overlaps stronger " + ", ".join(f"#{idx}" for idx in sorted(set(overlapping_stronger)))
            )

        corroborated = bool(row["expected_matches"] or row["comparison_matches"])
        has_hard_flag = any(
            flag.startswith("weak start/end") or flag.startswith("broad parent") or flag.startswith("overlaps stronger")
            for flag in row["flags"]
        )
        has_soft_flag = any(
            flag in {"long low-grade drag", "low VAM for displayed climb"}
            for flag in row["flags"]
        )

        if has_hard_flag and not corroborated:
            row["review"] = "suspicious"
        elif has_soft_flag and not corroborated:
            row["review"] = "suspicious"
        elif has_hard_flag or has_soft_flag:
            row["review"] = "review"
        elif row["strength_score"] >= 5 or corroborated:
            row["review"] = "keeper"
        else:
            row["review"] = "review"

        row["review_color"] = REVIEW_COLORS[row["review"]]

    return persistence_rows


def build_review_summary(
    persistence_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    comparison_result: dict[str, Any],
    terrain_sweep: list[dict[str, Any]],
) -> dict[str, Any]:
    keepers = [row for row in persistence_rows if row["review"] == "keeper"]
    review_rows = [row for row in persistence_rows if row["review"] == "review"]
    suspicious = [row for row in persistence_rows if row["review"] == "suspicious"]
    corroborated = [row for row in persistence_rows if row["expected_matches"] or row["comparison_matches"]]

    unmatched_expected = []
    for expected in expected_rows:
        start_s = expected.get("start_s")
        if start_s is None:
            continue
        if not any(abs(row["start_s"] - int(start_s)) <= DEFAULT_EXPECTED_MATCH_TOLERANCE_S for row in persistence_rows):
            unmatched_expected.append(expected)

    lines = [
        (
            f"Persistence is showing {len(persistence_rows)} displayed climbs. "
            f"{len(keepers)} look like likely keepers, {len(review_rows)} need review, "
            f"and {len(suspicious)} look suspicious under current heuristics."
        ),
        (
            f"The comparison baseline ({comparison_result['label']}) shows "
            f"{len(comparison_result['shown'])} displayed climbs, and "
            f"{len(corroborated)} persistence segments line up with canonical or expected anchors."
        ),
    ]
    if unmatched_expected:
        lines.append(
            f"{len(unmatched_expected)} expected climbs are not clearly covered by persistence start markers."
        )

    if terrain_sweep:
        auto_row = next((row for row in terrain_sweep if row["terrain"] == "auto"), None)
        selected_row = next((row for row in terrain_sweep if row["selected"]), None)
        if auto_row and selected_row and auto_row["shown"] != selected_row["shown"]:
            lines.append(
                f"Canonical terrain choice matters here: auto shows {auto_row['shown']} climbs, "
                f"while {selected_row['terrain']} shows {selected_row['shown']}."
            )

    return {
        "keepers": keepers,
        "review_rows": review_rows,
        "suspicious": suspicious,
        "unmatched_expected": unmatched_expected,
        "lines": lines,
    }


def assign_rows(segments: list[dict[str, Any]], gap_s: int = 45) -> list[int]:
    row_ends: list[int] = []
    assignments: list[int] = []
    for segment in sorted(segments, key=lambda item: (item["start_s"], item["end_s"])):
        placed = False
        for row_idx, end_s in enumerate(row_ends):
            if segment["start_s"] > end_s + gap_s:
                row_ends[row_idx] = segment["end_s"]
                assignments.append(row_idx)
                placed = True
                break
        if not placed:
            row_ends.append(segment["end_s"])
            assignments.append(len(row_ends) - 1)
    return assignments


def render_plot_svg(
    ride_name: str,
    profile_times_s: list[int],
    profile_elevs_m: list[float],
    persistence_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    min_vert_m: float,
    comparison_label: str,
) -> str:
    time_minutes = [time_s / 60.0 for time_s in profile_times_s]
    fig, axes = plt.subplots(
        4,
        1,
        figsize=(16, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [5, 1.5, 1.3, 1.0]},
    )
    ax_profile, ax_persistence, ax_comparison, ax_expected = axes

    ax_profile.plot(time_minutes, profile_elevs_m, color="#304f2d", linewidth=1.5)
    for row in persistence_rows:
        ax_profile.axvspan(
            row["start_s"] / 60.0,
            row["end_s"] / 60.0,
            color=row["review_color"],
            alpha=0.12,
        )
    for row in comparison_rows:
        ax_profile.axvspan(
            row["start_s"] / 60.0,
            row["end_s"] / 60.0,
            color="#3d6ea8",
            alpha=0.08,
        )
    for row in expected_rows:
        if row["start_s"] is not None:
            ax_profile.axvline(row["start_s"] / 60.0, color="#2a8a4b", linestyle="--", linewidth=1)

    ax_profile.set_title(f"{ride_name} - climb review", fontsize=14, fontweight="bold")
    ax_profile.set_ylabel("Elevation (m)")
    ax_profile.grid(alpha=0.18)
    ax_profile.legend(
        handles=[
            Line2D([0], [0], color="#304f2d", lw=2, label="elevation profile"),
            Patch(facecolor=REVIEW_COLORS["keeper"], alpha=0.18, label=f"persistence keeper >= {min_vert_m:.0f}m"),
            Patch(facecolor=REVIEW_COLORS["review"], alpha=0.18, label="persistence review"),
            Patch(facecolor=REVIEW_COLORS["suspicious"], alpha=0.18, label="persistence suspicious"),
            Patch(facecolor="#3d6ea8", alpha=0.12, label=comparison_label),
            Line2D([0], [0], color="#2a8a4b", lw=1, linestyle="--", label="expected start"),
        ],
        loc="upper left",
        fontsize=8,
    )

    def draw_segment_lane(
        ax: Any,
        rows: list[dict[str, Any]],
        title: str,
        color_key: str,
        default_color: str,
    ) -> None:
        if not rows:
            ax.text(0.01, 0.5, "no segments shown", transform=ax.transAxes, va="center", ha="left")
            ax.set_ylim(0, 1)
            ax.set_yticks([])
            ax.set_ylabel(title)
            return

        sorted_rows = sorted(rows, key=lambda item: (item["start_s"], item["end_s"]))
        lane_rows = assign_rows(sorted_rows)
        lane_height = 8
        lane_step = 10

        for lane_row, segment in zip(lane_rows, sorted_rows):
            start_min = segment["start_s"] / 60.0
            duration_min = max((segment["end_s"] - segment["start_s"]) / 60.0, 0.05)
            y = lane_row * lane_step
            color = segment.get(color_key, default_color)
            ax.broken_barh(
                [(start_min, duration_min)],
                (y, lane_height),
                facecolors=color,
                alpha=0.85,
            )
            ax.text(
                start_min + duration_min / 2.0,
                y + lane_height / 2.0,
                str(segment["index"]),
                ha="center",
                va="center",
                fontsize=8,
                color="white",
            )

        ax.set_ylim(-1, max(lane_rows) * lane_step + lane_height + 2)
        ax.set_yticks([])
        ax.set_ylabel(title)
        ax.grid(axis="x", alpha=0.12)

    draw_segment_lane(
        ax_persistence,
        persistence_rows,
        "Persistence",
        color_key="review_color",
        default_color=REVIEW_COLORS["review"],
    )
    draw_segment_lane(
        ax_comparison,
        comparison_rows,
        comparison_label,
        color_key="lane_color",
        default_color="#3d6ea8",
    )

    expected_with_starts = [row for row in expected_rows if row["start_s"] is not None]
    if expected_with_starts:
        for idx, row in enumerate(expected_with_starts, start=1):
            y = float(idx)
            x = float(row["start_s"]) / 60.0
            ax_expected.scatter([x], [y], marker="D", color="#2a8a4b", s=42)
            ax_expected.text(x + 0.15, y, str(row["index"]), va="center", ha="left", fontsize=8)
        ax_expected.set_ylim(0.5, len(expected_with_starts) + 0.75)
    else:
        ax_expected.text(
            0.01,
            0.5,
            "no expected start markers available",
            transform=ax_expected.transAxes,
            va="center",
            ha="left",
        )
        ax_expected.set_ylim(0, 1)

    ax_expected.set_ylabel("Expected")
    ax_expected.set_yticks([])
    ax_expected.set_xlabel("Time (minutes)")
    ax_expected.grid(axis="x", alpha=0.12)

    buffer = io.StringIO()
    fig.tight_layout()
    fig.savefig(buffer, format="svg")
    plt.close(fig)
    return buffer.getvalue()


def nearest_route_index(route_samples: list[dict[str, Any]], target_s: int) -> Optional[int]:
    best_idx: Optional[int] = None
    best_delta: Optional[int] = None
    for idx, sample in enumerate(route_samples):
        sample_t = sample.get("t")
        if sample_t is None:
            continue
        delta = abs(int(sample_t) - int(target_s))
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_idx = idx
    return best_idx


def build_route_track(route_samples: list[dict[str, Any]]) -> tuple[list[int], list[float], list[float]]:
    indices: list[int] = []
    xs: list[float] = []
    ys: list[float] = []
    lat_values = [
        float(sample["lat"])
        for sample in route_samples
        if sample.get("lat") is not None and sample.get("lon") is not None
    ]
    if not lat_values:
        return indices, xs, ys

    mean_lat_rad = math.radians(sum(lat_values) / len(lat_values))
    cos_lat = max(math.cos(mean_lat_rad), 0.2)

    for idx, sample in enumerate(route_samples):
        lat = sample.get("lat")
        lon = sample.get("lon")
        if lat is None or lon is None:
            continue
        indices.append(idx)
        xs.append(float(lon) * cos_lat)
        ys.append(float(lat))

    return indices, xs, ys


def route_segment_xy(
    route_samples: list[dict[str, Any]],
    route_x: list[float],
    route_y: list[float],
    sample_indices: list[int],
    start_s: int,
    end_s: int,
) -> tuple[list[float], list[float]]:
    if not route_x or not route_y or not sample_indices:
        return [], []

    start_idx = nearest_route_index(route_samples, start_s)
    end_idx = nearest_route_index(route_samples, end_s)
    if start_idx is None or end_idx is None:
        return [], []
    if end_idx < start_idx:
        start_idx, end_idx = end_idx, start_idx

    xs: list[float] = []
    ys: list[float] = []
    for route_pos, sample_idx in enumerate(sample_indices):
        if start_idx <= sample_idx <= end_idx:
            xs.append(route_x[route_pos])
            ys.append(route_y[route_pos])
    return xs, ys


def render_route_svg(
    ride_name: str,
    route_samples: list[dict[str, Any]],
    persistence_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    comparison_label: str,
) -> Optional[str]:
    sample_indices, route_x, route_y = build_route_track(route_samples)
    if len(route_x) < 2 or len(route_y) < 2:
        return None

    fig, ax = plt.subplots(figsize=(9, 9))
    ax.plot(route_x, route_y, color="#c7cec1", linewidth=1.6, alpha=0.9, zorder=1)

    for row in comparison_rows:
        seg_x, seg_y = route_segment_xy(
            route_samples,
            route_x,
            route_y,
            sample_indices,
            row["start_s"],
            row["end_s"],
        )
        if len(seg_x) >= 2:
            ax.plot(seg_x, seg_y, color="#3d6ea8", linewidth=4.2, alpha=0.35, zorder=2)

    for row in persistence_rows:
        seg_x, seg_y = route_segment_xy(
            route_samples,
            route_x,
            route_y,
            sample_indices,
            row["start_s"],
            row["end_s"],
        )
        if len(seg_x) < 2:
            continue
        ax.plot(seg_x, seg_y, color=row["review_color"], linewidth=3.4, alpha=0.95, zorder=3)
        mid_idx = len(seg_x) // 2
        ax.text(
            seg_x[mid_idx],
            seg_y[mid_idx],
            str(row["index"]),
            fontsize=8,
            ha="center",
            va="center",
            color="white",
            bbox={"boxstyle": "round,pad=0.18", "facecolor": row["review_color"], "edgecolor": "none", "alpha": 0.95},
            zorder=4,
        )

    for row in expected_rows:
        start_s = row.get("start_s")
        if start_s is None:
            continue
        sample_idx = nearest_route_index(route_samples, int(start_s))
        if sample_idx is None:
            continue
        if sample_idx not in sample_indices:
            continue
        route_pos = sample_indices.index(sample_idx)
        ax.scatter(
            [route_x[route_pos]],
            [route_y[route_pos]],
            marker="D",
            color="#2a8a4b",
            s=42,
            zorder=5,
        )
        ax.text(
            route_x[route_pos],
            route_y[route_pos],
            str(row["index"]),
            fontsize=8,
            ha="left",
            va="bottom",
            color="#1f4f2b",
            zorder=6,
        )

    ax.set_title(f"{ride_name} - route review", fontsize=14, fontweight="bold")
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")
    ax.legend(
        handles=[
            Line2D([0], [0], color="#c7cec1", lw=2, label="ride route"),
            Patch(facecolor="#3d6ea8", alpha=0.25, label=comparison_label),
            Patch(facecolor=REVIEW_COLORS["keeper"], alpha=0.75, label="persistence keeper"),
            Patch(facecolor=REVIEW_COLORS["review"], alpha=0.75, label="persistence review"),
            Patch(facecolor=REVIEW_COLORS["suspicious"], alpha=0.75, label="persistence suspicious"),
            Line2D([0], [0], color="#2a8a4b", marker="D", linestyle="None", markersize=6, label="expected start"),
        ],
        loc="upper left",
        fontsize=8,
    )

    buffer = io.StringIO()
    fig.tight_layout()
    fig.savefig(buffer, format="svg")
    plt.close(fig)
    return buffer.getvalue()


def get_extension_status() -> dict[str, Any]:
    status = runtime_status()
    return {
        "package_init": str(Path(wp.__file__).resolve()),
        "extension_path": status["extension_path"],
        "release_lib": status["release_path"],
        "extension_mtime": status["extension_mtime"],
        "release_mtime": status["release_mtime"],
        "is_stale_vs_release": status["is_stale"],
        "stale_reason": status["stale_reason"],
    }


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p class='muted'>No rows to display.</p>"

    thead = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    tbody_rows = []
    for row in rows:
        tbody_rows.append(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        )
    return (
        "<table>"
        f"<thead><tr>{thead}</tr></thead>"
        f"<tbody>{''.join(tbody_rows)}</tbody>"
        "</table>"
    )


def pill(label: str, tone: str) -> str:
    return f"<span class='pill pill-{html.escape(tone)}'>{html.escape(label)}</span>"


def render_html(
    loaded_ride: LoadedRide,
    meta: dict[str, Any],
    persistence_all: list[dict[str, Any]],
    persistence_shown: list[dict[str, Any]],
    comparison_result: dict[str, Any],
    terrain_sweep: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    review_summary: dict[str, Any],
    min_vert_m: float,
    extension_status: dict[str, Any],
    plot_svg: str,
    route_svg: Optional[str],
) -> str:
    manifest_entry = loaded_ride.manifest_entry
    description = manifest_entry.get("description") if manifest_entry else None
    notes = manifest_entry.get("notes") if manifest_entry else None
    missing_expected = [row for row in expected_rows if row["start_s"] is None]
    comparison_rows = comparison_result["shown"]

    summary_rows = [
        ["ride", html.escape(loaded_ride.ride_label)],
        ["source", html.escape(loaded_ride.source_kind)],
        ["parser", html.escape(loaded_ride.parser_mode)],
        ["file type", html.escape(loaded_ride.file_type)],
        ["duration", html.escape(format_duration(meta["duration_s"]))],
        ["elev range", html.escape(f"{meta['elev_min_m']}m to {meta['elev_max_m']}m")],
        ["sample mode", html.escape(meta["sample_mode_used"])],
        ["raw samples", html.escape(str(meta["raw_samples"]))],
        ["raw tile samples", html.escape(str(meta["raw_tile_samples"]))],
        ["tile runs", html.escape(str(meta["tile_runs"]))],
        ["detector samples", html.escape(str(meta["detection_samples"]))],
        ["persistence source", html.escape(str(meta.get("persistence_sample_source", meta["sample_mode_used"])))],
        ["persistence total", html.escape(str(len(persistence_all)))],
        ["persistence shown", html.escape(str(len(persistence_shown)))],
        [f"{comparison_result['label']} shown", html.escape(str(len(comparison_rows)))],
        ["expected climbs", html.escape(str(len(expected_rows)))],
        ["min shown vert", html.escape(f"{min_vert_m:.0f}m")],
    ]
    if loaded_ride.ride_meta and loaded_ride.ride_meta.live_climb_rows is not None:
        summary_rows.append(["live climb rows", html.escape(str(loaded_ride.ride_meta.live_climb_rows))])
    if meta["sample_mode_requested"] != meta["sample_mode_used"]:
        summary_rows.append(
            [
                "sample mode note",
                html.escape(
                    f"Requested {meta['sample_mode_requested']}, fell back to {meta['sample_mode_used']}"
                ),
            ]
        )

    summary_table = render_table(["Field", "Value"], summary_rows)

    terrain_sweep_table = render_table(
        ["Terrain", "Total", "Shown", "Selected"],
        [
            [
                html.escape(row["terrain"]),
                html.escape(str(row["total"])),
                html.escape(str(row["shown"])),
                pill("selected", "info") if row["selected"] else "",
            ]
            for row in terrain_sweep
        ],
    )

    review_lines = "".join(f"<li>{html.escape(line)}</li>" for line in review_summary["lines"])
    suspicious_rows = review_summary["suspicious"][:8]
    suspicious_list = render_table(
        ["#", "Start", "Vert", "Grade", "Flags"],
        [
            [
                str(row["index"]),
                format_duration(row["start_s"]),
                f"{row['vert_m']:.1f}m",
                f"{row['avg_gradient_pct']:.2f}%",
                html.escape(", ".join(row["flags"]) or "none"),
            ]
            for row in suspicious_rows
        ],
    )

    persistence_table = render_table(
        ["#", "Start", "End", "Vert", "Time", "Grade", "VAM", "Boundary", "Review", "Matches", "Flags"],
        [
            [
                str(row["index"]),
                format_duration(row["start_s"]),
                format_duration(row["end_s"]),
                f"{row['vert_m']:.1f}m",
                format_duration(row["time_s"]),
                f"{row['avg_gradient_pct']:.2f}%",
                f"{row['vam']:.0f}",
                html.escape(
                    f"{row['boundary_delta_m']:.1f}m" if row["boundary_delta_m"] is not None else "-"
                ),
                pill(row["review"], row["review"]),
                html.escape(
                    " ".join(
                        filter(
                            None,
                            [
                                (
                                    "E:" + ",".join(str(idx) for idx in row["expected_matches"])
                                    if row["expected_matches"]
                                    else ""
                                ),
                                (
                                    "C:" + ",".join(str(idx) for idx in row["comparison_matches"])
                                    if row["comparison_matches"]
                                    else ""
                                ),
                            ],
                        )
                    )
                    or "-"
                ),
                html.escape(", ".join(row["flags"]) or "-"),
            ]
            for row in persistence_shown
        ],
    )

    comparison_table = render_table(
        ["#", "Start", "End", "Vert", "Time", "Grade", "VAM"],
        [
            [
                str(row["index"]),
                format_duration(row["start_s"]),
                format_duration(row["end_s"]),
                f"{row['vert_m']:.1f}m",
                format_duration(row["time_s"]),
                f"{row['avg_gradient_pct']:.2f}%",
                f"{row['vam']:.0f}",
            ]
            for row in comparison_rows
        ],
    )

    expected_table = render_table(
        ["#", "Name", "Approx Start", "Approx Vert", "Approx Grade", "Notes"],
        [
            [
                str(row["index"]),
                html.escape(row["name"]),
                html.escape(format_duration(row["start_s"]) if row["start_s"] is not None else "-"),
                html.escape(f"{row['vert_m']}m" if row["vert_m"] is not None else "-"),
                html.escape(
                    f"{row['avg_gradient_pct']}%" if row["avg_gradient_pct"] is not None else "-"
                ),
                html.escape(row["notes"]),
            ]
            for row in expected_rows
        ],
    )

    freshness_note = (
        "WARNING: Python extension appears older than target/release build."
        if extension_status["is_stale_vs_release"]
        else "Python extension is not older than the local release build."
    )

    sections = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8' />",
        f"<title>{html.escape(loaded_ride.ride_label)} climb review</title>",
        "<style>",
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #1f2b1f; background: #f5f5ef; }",
        "h1, h2, h3 { margin: 0 0 12px; }",
        "p, li { line-height: 1.5; }",
        ".grid { display: grid; grid-template-columns: minmax(320px, 420px) 1fr; gap: 20px; align-items: start; }",
        ".card { background: white; border: 1px solid #d7dccf; border-radius: 12px; padding: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.04); margin-top: 20px; }",
        ".card:first-child { margin-top: 0; }",
        ".stack { display: grid; gap: 16px; }",
        ".svg-wrap svg { width: 100%; height: auto; }",
        "table { border-collapse: collapse; width: 100%; font-size: 14px; }",
        "th, td { border-bottom: 1px solid #e5e8df; padding: 8px 10px; text-align: left; vertical-align: top; }",
        "th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: #4a5b47; }",
        ".muted { color: #5e6b5c; }",
        ".warning { color: #8b2d2d; font-weight: 600; }",
        ".pill { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }",
        ".pill-keeper { background: rgba(46,125,50,0.12); color: #2e7d32; }",
        ".pill-review { background: rgba(183,121,31,0.12); color: #8a5a16; }",
        ".pill-suspicious { background: rgba(178,58,58,0.12); color: #962c2c; }",
        ".pill-info { background: rgba(61,110,168,0.12); color: #2b5f96; }",
        "code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{html.escape(loaded_ride.ride_label)} climb review</h1>",
        "<div class='muted'>",
        "<p>This report is for human climb review. Canonical is the current prelaunch product detector on the selected sample mode, "
        f"and the comparison baseline is {html.escape(comparison_result['label'])}. "
        "Use the colored persistence lane, the canonical lane, and the review table to decide which segments feel like real climbs.</p>",
        "</div>",
        "<div class='grid'>",
        "<div class='stack'>",
        "<div class='card'>",
        "<h2>Summary</h2>",
        summary_table,
        "</div>",
        "<div class='card'>",
        "<h2>Review Summary</h2>",
        "<ul>",
        review_lines,
        "</ul>",
        suspicious_list,
        "</div>",
        "<div class='card'>",
        "<h2>Terrain Sweep</h2>",
        (
            "<p class='muted'>Momentum counts across all terrain presets. Canonical currently chooses among these terrain views before shipping one displayed set.</p>"
            + terrain_sweep_table
            if terrain_sweep
            else "<p class='muted'>Terrain sweep skipped.</p>"
        ),
        "</div>",
        "<div class='card'>",
        "<h2>Extension</h2>",
        f"<p class=\"{'warning' if extension_status['is_stale_vs_release'] else 'muted'}\">{html.escape(freshness_note)}</p>",
        "<p><strong>package:</strong><br /><code>"
        + html.escape(extension_status["package_init"] or "-")
        + "</code></p>",
        "<p><strong>extension:</strong><br /><code>"
        + html.escape(extension_status["extension_path"] or "-")
        + "</code></p>",
        "<p><strong>release lib:</strong><br /><code>"
        + html.escape(extension_status["release_lib"] or "-")
        + "</code></p>",
        "</div>",
        "</div>",
        "<div class='card svg-wrap'>",
        "<h2>Profile Review</h2>",
        plot_svg,
        "</div>",
        "</div>",
    ]

    if route_svg:
        sections.extend(
            [
                "<div class='card svg-wrap'>",
                "<h2>Route Review</h2>",
                "<p class='muted'>Gray is the full route. Persistence segments are colored by review status, canonical is blue, and expected starts are green diamonds when available.</p>",
                route_svg,
                "</div>",
            ]
        )

    if description or notes:
        sections.extend(
            [
                "<div class='card'>",
                "<h2>Manifest Context</h2>",
                f"<p>{html.escape(description or '')}</p>" if description else "",
                f"<p class='muted'>{html.escape(notes or '')}</p>" if notes else "",
                "</div>",
            ]
        )

    if loaded_ride.ride_meta:
        sections.extend(
            [
                "<div class='card'>",
                "<h2>Live Ride Context</h2>",
                render_table(
                    ["Field", "Value"],
                    [
                        ["ride id", html.escape(str(loaded_ride.ride_meta.ride_id or "-"))],
                        ["status", html.escape(str(loaded_ride.ride_meta.processing_status or "-"))],
                        ["started", html.escape(str(loaded_ride.ride_meta.started_at or "-"))],
                        ["uploaded", html.escape(str(loaded_ride.ride_meta.uploaded_at or "-"))],
                        ["raw file path", html.escape(str(loaded_ride.ride_meta.raw_file_path or "-"))],
                    ],
                ),
                "</div>",
            ]
        )

    if missing_expected:
        sections.extend(
            [
                "<div class='card'>",
                "<h2>Expected Climbs Without Start Markers</h2>",
                "<p class='muted'>These expectations are approximate in the manifest, so they are listed here but not placed on the chart.</p>",
                render_table(
                    ["#", "Name", "Approx Vert", "Approx Grade", "Notes"],
                    [
                        [
                            str(row["index"]),
                            html.escape(row["name"]),
                            html.escape(f"{row['vert_m']}m" if row["vert_m"] is not None else "-"),
                            html.escape(
                                f"{row['avg_gradient_pct']}%" if row["avg_gradient_pct"] is not None else "-"
                            ),
                            html.escape(row["notes"]),
                        ]
                        for row in missing_expected
                    ],
                ),
                "</div>",
            ]
        )

    sections.extend(
        [
            "<div class='card'>",
            "<h2>Persistence Segments Shown</h2>",
            persistence_table,
            "</div>",
            "<div class='card'>",
            f"<h2>{html.escape(comparison_result['label']).title()} Segments Shown</h2>",
            comparison_table,
            "</div>",
            "<div class='card'>",
            "<h2>Expected Climbs</h2>",
            expected_table,
            "</div>",
            "</body>",
            "</html>",
        ]
    )

    return "\n".join(section for section in sections if section)


def main() -> int:
    args = parse_args()
    loaded_ride = resolve_ride_source(args)
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else default_output_path(loaded_ride.ride_label)
    )

    try:
        raw_samples, raw_tile_samples, tile_runs, detection_samples, meta = build_sample_views(
            loaded_ride.points,
            args.sample_mode,
        )
        if not detection_samples:
            raise SystemExit(f"No usable detector samples found for {loaded_ride.ride_label}")

        persistence_samples = raw_tile_samples or detection_samples
        meta["persistence_sample_source"] = (
            "raw-tile-sequence" if raw_tile_samples else meta["sample_mode_used"]
        )
        persistence_climbs = wp.detect_climbs_persistence(
            persistence_samples,
            user_weight_kg=args.weight_kg,
        )
        persistence_all, persistence_shown = summarize_persistence(
            persistence_climbs,
            persistence_samples,
            args.min_vert_m,
        )

        expected_rows = summarize_expected(loaded_ride.manifest_entry)
        canonical_result = compute_canonical_result(
            detection_samples,
            persistence_candidate_samples=persistence_samples,
            weight_kg=args.weight_kg,
            min_vert_m=args.min_vert_m,
        )
        selected_terrain = canonical_result["terrain"]
        if selected_terrain not in TERRAIN_OPTIONS:
            selected_terrain = resolve_comparison_terrain(args.terrain, loaded_ride.manifest_entry)
        _, terrain_sweep = compute_momentum_results(
            detection_samples,
            selected_terrain=selected_terrain,
            weight_kg=args.weight_kg,
            min_vert_m=args.min_vert_m,
            skip_sweep=args.skip_terrain_sweep,
        )
        for row in canonical_result["shown"]:
            row["lane_color"] = "#3d6ea8"

        persistence_shown = annotate_persistence_rows(
            persistence_shown,
            canonical_result["shown"],
            expected_rows,
        )
        review_summary = build_review_summary(
            persistence_shown,
            expected_rows,
            canonical_result,
            terrain_sweep,
        )

        plot_svg = render_plot_svg(
            ride_name=loaded_ride.ride_label,
            profile_times_s=meta["profile_times_s"],
            profile_elevs_m=meta["profile_elevs_m"],
            persistence_rows=persistence_shown,
            comparison_rows=canonical_result["shown"],
            expected_rows=expected_rows,
            min_vert_m=args.min_vert_m,
            comparison_label=canonical_result["label"],
        )
        route_svg = render_route_svg(
            ride_name=loaded_ride.ride_label,
            route_samples=raw_samples,
            persistence_rows=persistence_shown,
            comparison_rows=canonical_result["shown"],
            expected_rows=expected_rows,
            comparison_label=canonical_result["label"],
        )

        report_html = render_html(
            loaded_ride=loaded_ride,
            meta=meta,
            persistence_all=persistence_all,
            persistence_shown=persistence_shown,
            comparison_result=canonical_result,
            terrain_sweep=terrain_sweep,
            expected_rows=expected_rows,
            review_summary=review_summary,
            min_vert_m=args.min_vert_m,
            extension_status=get_extension_status(),
            plot_svg=plot_svg,
            route_svg=route_svg,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_html)
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "ride": loaded_ride.ride_label,
                    "sample_mode_used": meta["sample_mode_used"],
                    "raw_samples": meta["raw_samples"],
                    "tile_runs": meta["tile_runs"],
                    "persistence_total": len(persistence_all),
                    "persistence_shown": len(persistence_shown),
                    "comparison_label": canonical_result["label"],
                    "comparison_total": len(canonical_result["all"]),
                    "comparison_shown": len(canonical_result["shown"]),
                    "expected": len(expected_rows),
                    "suspicious_persistence": len(review_summary["suspicious"]),
                },
                indent=2,
                default=_json_default,
            )
        )
        return 0
    finally:
        if loaded_ride.temp_path and loaded_ride.temp_path.exists():
            loaded_ride.temp_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
