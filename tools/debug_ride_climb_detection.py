#!/usr/bin/env python3
"""
Debug climb detection for a ride file or stored ride.

Usage examples:

  PYTHONPATH=backend backend/venv/bin/python tools/debug_ride_climb_detection.py \
    --file /tmp/corey.fit --file-type fit

  PYTHONPATH=backend backend/venv/bin/python tools/debug_ride_climb_detection.py \
    --ride-id 86af057a-e841-4671-8955-70c8fbdab17c --output /tmp/report.json
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import psycopg2
import workout_parse as wp

from app.services.patterns.climb import ClimbPatternDetector, classify_terrain
from app.services.tile_service import TileService

try:
    from app.services.workout_parse_adapter import parse_ride_file_bytes_rust

    _HAS_RUST_PARSER = True
except ImportError:
    _HAS_RUST_PARSER = False
    parse_ride_file_bytes_rust = None

from app.services.ride_parser import parse_ride_file
from app.services.file_storage import create_file_storage_service


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


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _summarize_v2_climb(climb: Any) -> dict[str, Any]:
    return {
        "vert_m": round(float(getattr(climb, "vert_m", 0.0)), 1),
        "time_s": int(getattr(climb, "time_s", 0) or 0),
        "distance_m": round(float(getattr(climb, "distance_m", 0.0)), 1),
        "avg_gradient_pct": round(float(getattr(climb, "avg_gradient_pct", 0.0)), 2),
        "persistence_m": round(float(getattr(climb, "persistence", 0.0)), 2),
        "start_s": int(getattr(climb, "start_time_offset_s", 0) or 0),
        "end_s": int(getattr(climb, "end_time_offset_s", 0) or 0),
    }


def _summarize_debug_climb(climb: Any) -> dict[str, Any]:
    return {
        "vert_m": round(float(getattr(climb, "vert_m", 0.0)), 1),
        "time_s": int(getattr(climb, "time_s", 0) or 0),
        "distance_m": round(float(getattr(climb, "distance_m", 0.0) or 0.0), 1),
        "avg_gradient_pct": round(float(getattr(climb, "avg_gradient_pct", 0.0) or 0.0), 2),
        "start_s": int(getattr(climb, "start_time_offset_s", 0) or 0),
        "end_s": int(getattr(climb, "end_time_offset_s", 0) or 0),
    }


def _summarize_rejected(segment: Any) -> dict[str, Any]:
    data = segment.to_dict()
    return {
        "start_time_s": data["start_time_s"],
        "end_time_s": data["end_time_s"],
        "vert_m": data["vert_m"],
        "time_s": data["time_s"],
        "vam": data["vam"],
        "avg_gradient_pct": data["avg_gradient_pct"],
        "rejection_reason": data["rejection_reason"],
        "rejection_details": data["rejection_details"],
    }


def _load_via_backend_parser(file_bytes: bytes, file_type: str) -> tuple[Any, str]:
    if _HAS_RUST_PARSER and parse_ride_file_bytes_rust is not None:
        return parse_ride_file_bytes_rust(file_bytes, file_type), "rust"
    file_data_b64 = base64.b64encode(file_bytes).decode("utf-8")
    return parse_ride_file(file_data_b64, file_type), "python"


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


def _points_to_raw_samples(points: list[dict[str, Any]], start_time: Any) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for point in points:
        samples.append(
            {
                "t": int(max(0, (point["timestamp"] - start_time).total_seconds())),
                "lat": point["lat"],
                "lon": point["lon"],
                "elevation_m": point["elevation_m"],
                "power_w": point["power_w"],
                "hr_bpm": point["hr_bpm"],
                "speed_mps": point["speed_mps"],
            }
        )
    return samples


def _count_large_climbs(climbs: list[dict[str, Any]], threshold_m: float = 50.0) -> int:
    return sum(1 for climb in climbs if climb["vert_m"] >= threshold_m)


def _run_debug_matrix(raw_samples: list[dict[str, Any]], tile_runs: list[dict[str, Any]]) -> dict[str, Any]:
    raw_v2 = [_summarize_v2_climb(c) for c in wp.detect_climbs_persistence(raw_samples, user_weight_kg=75.0)]
    run_v2 = [_summarize_v2_climb(c) for c in wp.detect_climbs_persistence(tile_runs, user_weight_kg=75.0)]

    raw_legacy, raw_legacy_rejected = ClimbPatternDetector(algorithm="legacy").detect_all_with_debug(
        raw_samples,
        user_weight_kg=75.0,
    )
    raw_momentum, raw_momentum_rejected = ClimbPatternDetector(algorithm="momentum").detect_all_with_debug(
        raw_samples,
        user_weight_kg=75.0,
    )
    run_legacy, run_legacy_rejected = ClimbPatternDetector(algorithm="legacy").detect_all_with_debug(
        tile_runs,
        user_weight_kg=75.0,
    )
    run_momentum, run_momentum_rejected = ClimbPatternDetector(algorithm="momentum").detect_all_with_debug(
        tile_runs,
        user_weight_kg=75.0,
    )

    return {
        "raw": {
            "terrain": classify_terrain(raw_samples),
            "persistence": {
                "count": len(raw_v2),
                "large_count_ge_50m": _count_large_climbs(raw_v2),
                "climbs": raw_v2,
            },
            "legacy": {
                "count": len(raw_legacy),
                "climbs": [_summarize_debug_climb(c) for c in raw_legacy],
                "rejected": [_summarize_rejected(r) for r in raw_legacy_rejected[:10]],
            },
            "momentum": {
                "count": len(raw_momentum),
                "climbs": [_summarize_debug_climb(c) for c in raw_momentum],
                "rejected": [_summarize_rejected(r) for r in raw_momentum_rejected[:10]],
            },
        },
        "tile_runs": {
            "terrain": classify_terrain(tile_runs),
            "persistence": {
                "count": len(run_v2),
                "large_count_ge_50m": _count_large_climbs(run_v2),
                "climbs": run_v2,
            },
            "legacy": {
                "count": len(run_legacy),
                "climbs": [_summarize_debug_climb(c) for c in run_legacy],
                "rejected": [_summarize_rejected(r) for r in run_legacy_rejected[:10]],
            },
            "momentum": {
                "count": len(run_momentum),
                "climbs": [_summarize_debug_climb(c) for c in run_momentum],
                "rejected": [_summarize_rejected(r) for r in run_momentum_rejected[:10]],
            },
        },
    }


def _get_db_connection() -> Any:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for --ride-id")
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
    storage = create_file_storage_service()
    return await storage.download_ride_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug climb detection for a ride")
    parser.add_argument("--ride-id", help="Ride UUID to fetch from the database and storage")
    parser.add_argument("--file", help="Local FIT/GPX/TCX file path")
    parser.add_argument("--file-type", default="fit", help="File type for --file (default: fit)")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()

    if not args.ride_id and not args.file:
        parser.error("Provide either --ride-id or --file")

    if args.ride_id and args.file:
        parser.error("Use either --ride-id or --file, not both")

    ride_meta: Optional[RideMeta] = None
    file_bytes: bytes
    file_type = args.file_type

    if args.ride_id:
        ride_meta = _fetch_ride_meta(args.ride_id)
        if not ride_meta.raw_file_path:
            raise RuntimeError(f"Ride {args.ride_id} has no raw_file_path")
        file_type = ride_meta.file_type
        file_bytes = asyncio.run(_download_storage_file(ride_meta.raw_file_path))
    else:
        file_path = Path(args.file)
        file_bytes = file_path.read_bytes()

    parsed_ride, parser_mode = _load_via_backend_parser(file_bytes, file_type)
    points = _records_to_points(parsed_ride)
    raw_samples = _points_to_raw_samples(points, parsed_ride.started_at)
    tile_runs = TileService().get_tile_run_sequence(
        points=points,
        resolution=10,
        start_time=parsed_ride.started_at,
    )

    report = {
        "ride": asdict(ride_meta) if ride_meta else None,
        "parser_mode": parser_mode,
        "sample_counts": {
            "records": len(parsed_ride.records),
            "points_with_gps": len(points),
            "raw_samples": len(raw_samples),
            "tile_runs": len(tile_runs),
            "raw_with_elevation": sum(1 for sample in raw_samples if sample.get("elevation_m") is not None),
            "tile_runs_with_elevation": sum(1 for sample in tile_runs if sample.get("elevation_m") is not None),
        },
        "tile_run_examples": {
            "first": tile_runs[0] if tile_runs else None,
            "last": tile_runs[-1] if tile_runs else None,
        },
        "matrix": _run_debug_matrix(raw_samples, tile_runs),
    }

    matrix = report["matrix"]
    print(json.dumps(
        {
            "ride": report["ride"],
            "parser_mode": parser_mode,
            "sample_counts": report["sample_counts"],
            "summary": {
                "raw_persistence": matrix["raw"]["persistence"]["count"],
                "tile_runs_persistence": matrix["tile_runs"]["persistence"]["count"],
                "raw_momentum": matrix["raw"]["momentum"]["count"],
                "tile_runs_momentum": matrix["tile_runs"]["momentum"]["count"],
                "raw_legacy": matrix["raw"]["legacy"]["count"],
                "tile_runs_legacy": matrix["tile_runs"]["legacy"]["count"],
            },
        },
        indent=2,
        default=_json_default,
    ))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, default=_json_default) + "\n")
        print(f"wrote_report={output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
