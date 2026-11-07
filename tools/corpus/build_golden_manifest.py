#!/usr/bin/env python3
"""
Build a seed manifest for manual benchmark curation from a Strava export.

This script does not try to create final ground truth. It creates a compact,
reviewable subset from a large export so the team can annotate the right rides
instead of browsing thousands of files manually.

Usage:
    python tools/corpus/build_golden_manifest.py \
      /Users/gabetemp/Downloads/export_440100 \
      --corpus-db tools/corpus/export_440100.db \
      --output /tmp/export_440100_seed_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


CYCLING_TYPES = {
    "ride",
    "virtualride",
    "ebikeride",
    "gravelride",
    "handcycle",
}

SUPPORTED_SUFFIXES = (
    ".fit",
    ".fit.gz",
    ".gpx",
    ".gpx.gz",
    ".tcx",
    ".tcx.gz",
)


@dataclass
class ManifestEntry:
    activity_id: str
    relative_path: str
    file_format: str
    activity_type: str
    activity_date: Optional[str]
    activity_name: Optional[str]
    distance_m: Optional[float]
    elevation_gain_m: Optional[float]
    terrain_bucket: str
    source_bucket: str
    corpus_terrain_class: Optional[str]
    corpus_significant_climbs: Optional[int]
    corpus_total_climbs: Optional[int]
    has_power: Optional[bool]
    has_hr: Optional[bool]
    role: str
    tags: list[str]
    annotation_status: str = "todo"
    notes: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a seed benchmark manifest from a Strava export")
    parser.add_argument("export_root", help="Path to the Strava export root directory")
    parser.add_argument("--output", required=True, help="Where to write the JSON manifest")
    parser.add_argument(
        "--corpus-db",
        default=None,
        help="Optional SQLite corpus DB from tools/corpus/process_corpus.py for enrichment",
    )
    parser.add_argument(
        "--max-per-bucket",
        type=int,
        default=6,
        help="Maximum rides to keep per terrain/source bucket (default: 6)",
    )
    return parser.parse_args()


def normalize_file_format(filename: str) -> str:
    lower = filename.lower()
    if ".fit" in lower:
        return "fit"
    if ".gpx" in lower:
        return "gpx"
    if ".tcx" in lower:
        return "tcx"
    return "unknown"


def normalize_activity_type(raw: str) -> str:
    return (raw or "").strip()


def is_supported_cycling_entry(row: Dict[str, str]) -> bool:
    activity_type = normalize_activity_type(row.get("Activity Type", ""))
    if activity_type.replace(" ", "").lower() not in CYCLING_TYPES:
        return False

    filename = (row.get("Filename") or "").strip()
    if not filename:
        return False

    filename_lower = filename.lower()
    return any(filename_lower.endswith(suffix) for suffix in SUPPORTED_SUFFIXES)


def terrain_bucket_from_elevation(elevation_gain_m: Optional[float]) -> str:
    if elevation_gain_m is None:
        return "unknown"
    if elevation_gain_m < 100:
        return "flat"
    if elevation_gain_m < 500:
        return "rolling"
    if elevation_gain_m < 1200:
        return "hilly"
    return "mountainous"


def parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def read_corpus_index(db_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    if not db_path:
        return {}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                r.activity_id,
                r.terrain_class,
                r.has_power,
                r.has_hr,
                COUNT(c.id) AS total_climbs,
                SUM(CASE WHEN c.vert_m >= 20 THEN 1 ELSE 0 END) AS significant_climbs
            FROM rides r
            LEFT JOIN climbs_v2 c ON c.activity_id = r.activity_id
            GROUP BY
                r.activity_id,
                r.terrain_class,
                r.has_power,
                r.has_hr
            """
        ).fetchall()
    finally:
        conn.close()

    index: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        index[row["activity_id"]] = {
            "terrain_class": row["terrain_class"],
            "has_power": bool(row["has_power"]) if row["has_power"] is not None else None,
            "has_hr": bool(row["has_hr"]) if row["has_hr"] is not None else None,
            "total_climbs": int(row["total_climbs"] or 0),
            "significant_climbs": int(row["significant_climbs"] or 0),
        }
    return index


def load_export_rows(export_root: Path) -> list[Dict[str, Any]]:
    csv_path = export_root / "activities.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"activities.csv not found under {export_root}")

    rows: list[Dict[str, Any]] = []
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not is_supported_cycling_entry(row):
                continue

            relative_path = (row.get("Filename") or "").strip()
            full_path = export_root / relative_path
            if not full_path.exists():
                continue

            elevation_gain_m = parse_optional_float(row.get("Elevation Gain"))
            distance_m = parse_optional_float(row.get("Distance"))
            rows.append(
                {
                    "activity_id": (row.get("Activity ID") or "").strip(),
                    "relative_path": relative_path,
                    "activity_type": normalize_activity_type(row.get("Activity Type", "")),
                    "activity_date": (row.get("Activity Date") or "").strip() or None,
                    "activity_name": (row.get("Activity Name") or "").strip() or None,
                    "distance_m": distance_m,
                    "elevation_gain_m": elevation_gain_m,
                    "file_format": normalize_file_format(relative_path),
                    "terrain_bucket": terrain_bucket_from_elevation(elevation_gain_m),
                }
            )
    return rows


def seed_selection(rows: Iterable[Dict[str, Any]], corpus_index: Dict[str, Dict[str, Any]], max_per_bucket: int) -> list[ManifestEntry]:
    by_activity = {
        row["activity_id"]: row
        for row in rows
        if row.get("activity_id")
    }
    selected: Dict[str, ManifestEntry] = {}

    def build_entry(row: Dict[str, Any]) -> ManifestEntry:
        activity_id = row["activity_id"]
        terrain_bucket = row["terrain_bucket"]
        source_bucket = f"source:{row['file_format']}"
        meta = corpus_index.get(activity_id, {})
        tags = [
            f"terrain:{terrain_bucket}",
            source_bucket,
            f"type:{row['activity_type'].lower()}",
        ]
        if meta.get("terrain_class"):
            tags.append(f"corpus-terrain:{meta['terrain_class']}")
        if meta.get("has_power"):
            tags.append("sensor:power")
        if meta.get("has_hr"):
            tags.append("sensor:hr")
        significant_climbs = meta.get("significant_climbs")
        if significant_climbs == 0:
            tags.append("candidate:negative_control")
        elif (significant_climbs or 0) >= 8:
            tags.append("candidate:climb_dense")

        return ManifestEntry(
            activity_id=activity_id,
            relative_path=row["relative_path"],
            file_format=row["file_format"],
            activity_type=row["activity_type"],
            activity_date=row["activity_date"],
            activity_name=row["activity_name"],
            distance_m=row["distance_m"],
            elevation_gain_m=row["elevation_gain_m"],
            terrain_bucket=terrain_bucket,
            source_bucket=source_bucket,
            corpus_terrain_class=meta.get("terrain_class"),
            corpus_significant_climbs=significant_climbs,
            corpus_total_climbs=meta.get("total_climbs"),
            has_power=meta.get("has_power"),
            has_hr=meta.get("has_hr"),
            role="candidate",
            tags=sorted(tags),
        )

    def take_rows(candidates: Iterable[Dict[str, Any]], limit: int) -> None:
        for row in candidates:
            activity_id = row["activity_id"]
            if activity_id in selected:
                continue
            selected[activity_id] = build_entry(row)
            if len(selected) >= current_target[0]:
                break

    def sort_for_terrain(bucket: str, row: Dict[str, Any]) -> tuple:
        meta = corpus_index.get(row["activity_id"], {})
        significant = meta.get("significant_climbs")
        elevation = row.get("elevation_gain_m") or 0.0
        distance = row.get("distance_m") or 0.0
        if bucket == "flat":
            return (
                significant not in (None, 0),
                elevation,
                -distance,
                row["activity_id"],
            )
        if bucket == "unknown":
            return (
                significant not in (None, 0),
                -distance,
                row["activity_id"],
            )
        return (
            -(significant or 0),
            -elevation,
            -distance,
            row["activity_id"],
        )

    terrain_caps = {
        "flat": max_per_bucket,
        "rolling": max_per_bucket,
        "hilly": max_per_bucket,
        "mountainous": max_per_bucket,
        "unknown": max(2, max_per_bucket // 3),
    }
    source_cap = max(2, max_per_bucket // 2)
    negative_cap = max(3, max_per_bucket // 2)

    current_target = [0]

    # 1. Terrain-balanced selection.
    for bucket, limit in terrain_caps.items():
        current_target[0] = len(selected) + limit
        candidates = sorted(
            (row for row in by_activity.values() if row["terrain_bucket"] == bucket),
            key=lambda row, bucket=bucket: sort_for_terrain(bucket, row),
        )
        take_rows(candidates, limit)

    # 2. Source-format parity.
    for file_format in ("fit", "gpx", "tcx"):
        current_target[0] = len(selected) + source_cap
        candidates = sorted(
            (row for row in by_activity.values() if row["file_format"] == file_format),
            key=lambda row: (
                row["terrain_bucket"] == "unknown",
                -(corpus_index.get(row["activity_id"], {}).get("significant_climbs") or 0),
                -(row.get("elevation_gain_m") or 0.0),
                -(row.get("distance_m") or 0.0),
                row["activity_id"],
            ),
        )
        take_rows(candidates, source_cap)

    # 3. Explicit negative controls.
    current_target[0] = len(selected) + negative_cap
    negative_candidates = sorted(
        by_activity.values(),
        key=lambda row: (
            (corpus_index.get(row["activity_id"], {}).get("significant_climbs") or 0) != 0,
            row["terrain_bucket"] != "flat",
            row.get("elevation_gain_m") or 0.0,
            -(row.get("distance_m") or 0.0),
            row["activity_id"],
        ),
    )
    take_rows(negative_candidates, negative_cap)

    entries = list(selected.values())
    entries.sort(key=lambda entry: (entry.terrain_bucket, entry.file_format, -(entry.elevation_gain_m or 0.0), entry.activity_id))
    return entries


def build_manifest(export_root: Path, corpus_db: Optional[str], max_per_bucket: int) -> Dict[str, Any]:
    rows = load_export_rows(export_root)
    corpus_index = read_corpus_index(corpus_db)
    entries = seed_selection(rows, corpus_index, max_per_bucket)

    summary = {
        "total_cycling_files_seen": len(rows),
        "seed_entries": len(entries),
        "terrain_buckets": defaultdict(int),
        "source_formats": defaultdict(int),
    }

    for entry in entries:
        summary["terrain_buckets"][entry.terrain_bucket] += 1
        summary["source_formats"][entry.file_format] += 1

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": "Seed manifest for manual benchmark curation from a Strava export.",
        "source": {
            "export_root": str(export_root),
            "activities_csv": str(export_root / "activities.csv"),
            "corpus_db": corpus_db,
        },
        "selection_policy": {
            "max_per_bucket": max_per_bucket,
            "terrain_buckets": {
                "flat": "<100m elev gain",
                "rolling": "100-499m elev gain",
                "hilly": "500-1199m elev gain",
                "mountainous": ">=1200m elev gain",
            },
            "notes": [
                "This manifest is a starting point for manual annotation.",
                "Keep a mix of negative controls, rolling, hilly, mountainous, and source-format cases.",
                "Do not treat seed entries as ground truth until they are reviewed.",
            ],
        },
        "summary": {
            "total_cycling_files_seen": summary["total_cycling_files_seen"],
            "seed_entries": summary["seed_entries"],
            "terrain_buckets": dict(summary["terrain_buckets"]),
            "source_formats": dict(summary["source_formats"]),
        },
        "entries": [asdict(entry) for entry in entries],
    }


def main() -> int:
    args = parse_args()
    export_root = Path(args.export_root).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    manifest = build_manifest(export_root, args.corpus_db, args.max_per_bucket)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(
        json.dumps(
            {
                "output": str(output_path),
                "seed_entries": manifest["summary"]["seed_entries"],
                "terrain_buckets": manifest["summary"]["terrain_buckets"],
                "source_formats": manifest["summary"]["source_formats"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
