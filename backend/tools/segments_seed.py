#!/usr/bin/env python3
"""Seed the segments table from a GeoJSON file."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable

from shapely.geometry import LineString, shape
from shapely.ops import transform
import pyproj

from app.config import load_supabase_settings
from app.supabase_client import create_backend_supabase_client

Transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def compute_length_m(geometry: LineString) -> float:
    projected = transform(Transformer.transform, geometry)
    return float(projected.length)


def derive_segment_row(feature: Dict[str, Any]) -> Dict[str, Any]:
    geom_obj = shape(feature["geometry"])
    if not isinstance(geom_obj, LineString):
        raise ValueError("Only LineString geometries are supported")

    props = feature.get("properties", {})
    length_m = float(props.get("length_m") or compute_length_m(geom_obj))
    elev_gain = props.get("elev_gain_m")
    if elev_gain is None:
        elev_gain = props.get("elevation_gain")
    elev_gain_m = float(elev_gain) if elev_gain is not None else 0.0

    avg_grade = props.get("avg_grade")
    if avg_grade is None and length_m > 0:
        avg_grade = elev_gain_m / length_m
    avg_grade = float(avg_grade) if avg_grade is not None else None

    difficulty = int(props.get("difficulty", 1))
    verified = bool(props.get("verified", False))
    created_by = props.get("created_by")

    segment_id = props.get("id") or str(uuid.uuid4())

    return {
        "id": segment_id,
        "name": props.get("name", f"Segment {segment_id[:8]}")
        .strip(),
        "geom": f"SRID=4326;{geom_obj.wkt}",
        "length_m": length_m,
        "elev_gain_m": elev_gain_m,
        "avg_grade": avg_grade,
        "difficulty": difficulty,
        "verified": verified,
        "created_by": created_by,
    }


def load_features(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("GeoJSON must contain a FeatureCollection")
    return features


def seed_segments(path: Path, truncate: bool = False) -> None:
    settings = load_supabase_settings()
    if not settings:
        raise RuntimeError("Supabase configuration missing: set SUPABASE_URL and service role key")

    client = create_backend_supabase_client(settings.url, settings.service_key)

    if truncate:
        client.table("segments").delete().neq("id", "null").execute()

    rows = [derive_segment_row(feature) for feature in load_features(path)]
    if not rows:
        print("No segments found in GeoJSON; nothing to insert")
        return

    response = client.table("segments").upsert(rows, on_conflict="id").execute()
    inserted = len(response.data) if getattr(response, "data", None) else len(rows)
    print(f"Seeded {inserted} segments from {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Supabase segments from GeoJSON")
    parser.add_argument("geojson", type=Path, help="Path to segments GeoJSON file")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing segments before inserting new ones",
    )
    args = parser.parse_args()
    seed_segments(args.geojson, truncate=args.truncate)


if __name__ == "__main__":
    main()
