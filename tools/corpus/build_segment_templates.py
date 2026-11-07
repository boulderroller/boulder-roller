#!/usr/bin/env python3
"""
Build GPS segment templates from the golden corpus.

For each unique Strava climb segment that has been matched >= 3 times across rides,
extract the best-quality GPS polyline and store it as a SegmentTemplate in the
`segment_templates` table of golden_corpus.db.

These templates are used by the GPS template matching system (Path H) to recover
climb detections that elevation-based detection misses.

Usage:
    python tools/corpus/build_segment_templates.py                    # Build all
    python tools/corpus/build_segment_templates.py --min-occurrences 5  # Stricter filter
    python tools/corpus/build_segment_templates.py --dry-run           # Preview only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"

# Only build templates for segments that are actual climbs
MIN_ELEV_DIFF = 25.0  # meters
MIN_AVG_GRADE = 2.0  # percent
MIN_OCCURRENCES = 3  # minimum times the segment appears across rides
MIN_POLYLINE_POINTS = 10  # need enough GPS resolution to form a corridor


def init_template_table(conn: sqlite3.Connection) -> None:
    """Create the segment_templates table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS segment_templates (
            segment_id INTEGER PRIMARY KEY,
            segment_name TEXT,
            expected_vert_m REAL,
            expected_grade_pct REAL,
            expected_distance_m REAL,
            polyline_json TEXT,
            bbox_min_lat REAL,
            bbox_max_lat REAL,
            bbox_min_lon REAL,
            bbox_max_lon REAL,
            source_activity_id TEXT,
            point_count INTEGER,
            occurrence_count INTEGER
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_templates_vert
        ON segment_templates(expected_vert_m DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_templates_bbox
        ON segment_templates(bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon)
    """)
    conn.commit()


def find_eligible_segments(
    conn: sqlite3.Connection,
    min_elev: float = MIN_ELEV_DIFF,
    min_grade: float = MIN_AVG_GRADE,
    min_occurrences: int = MIN_OCCURRENCES,
) -> List[Dict]:
    """
    Find segments eligible for template creation.

    Returns list of dicts with segment_id, segment_name, avg elevation_diff,
    avg average_grade, avg distance_m, and the count of rides containing that segment.
    """
    rows = conn.execute("""
        SELECT
            s.segment_id,
            s.segment_name,
            AVG(s.elevation_diff) AS avg_elev_diff,
            AVG(s.average_grade) AS avg_grade,
            AVG(s.distance_m) AS avg_distance_m,
            COUNT(DISTINCT s.activity_id) AS ride_count
        FROM strava_segment_efforts s
        JOIN activity_streams a ON s.activity_id = a.activity_id
        WHERE s.is_climb = 1
              AND s.elevation_diff >= ?
              AND s.average_grade >= ?
        GROUP BY s.segment_id
        HAVING ride_count >= ?
        ORDER BY ride_count DESC, avg_elev_diff DESC
    """, (min_elev, min_grade, min_occurrences)).fetchall()

    return [
        {
            "segment_id": r[0],
            "segment_name": r[1],
            "avg_elev_diff": r[2],
            "avg_grade": r[3],
            "avg_distance_m": r[4],
            "ride_count": r[5],
        }
        for r in rows
    ]


def find_best_effort_for_segment(
    conn: sqlite3.Connection,
    segment_id: int,
) -> Optional[Dict]:
    """
    Find the ride with the best GPS quality for a given segment.

    "Best quality" = most samples in the segment's index range.
    Returns dict with activity_id, start_index, end_index, and quality info,
    or None if no suitable effort found.
    """
    # Get all efforts for this segment that have cached streams
    efforts = conn.execute("""
        SELECT s.activity_id, s.start_index, s.end_index,
               s.elevation_diff, s.average_grade, s.distance_m
        FROM strava_segment_efforts s
        JOIN activity_streams a ON s.activity_id = a.activity_id
        WHERE s.segment_id = ?
              AND s.start_index IS NOT NULL
              AND s.end_index IS NOT NULL
              AND s.end_index > s.start_index
        ORDER BY (s.end_index - s.start_index) DESC
    """, (segment_id,)).fetchall()

    if not efforts:
        return None

    best_effort = None
    best_quality = 0

    for effort in efforts:
        activity_id = effort[0]
        start_idx = effort[1]
        end_idx = effort[2]

        # Load streams for this activity
        cached = conn.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if not cached:
            continue

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}
        except (json.JSONDecodeError, KeyError):
            continue

        latlng = streams.get("latlng", [])
        altitude = streams.get("altitude", [])

        # Quality = number of valid GPS points in the segment range
        valid_gps = 0
        for i in range(start_idx, min(end_idx + 1, len(latlng))):
            if i < len(latlng) and latlng[i] and len(latlng[i]) == 2:
                lat, lon = latlng[i]
                if lat != 0.0 or lon != 0.0:  # Not null island
                    valid_gps += 1

        if valid_gps > best_quality:
            best_quality = valid_gps
            best_effort = {
                "activity_id": activity_id,
                "start_index": start_idx,
                "end_index": end_idx,
                "elevation_diff": effort[3],
                "average_grade": effort[4],
                "distance_m": effort[5],
                "valid_gps_points": valid_gps,
            }

    return best_effort


def extract_polyline(
    conn: sqlite3.Connection,
    activity_id: str,
    start_index: int,
    end_index: int,
) -> Optional[List[Tuple[float, float]]]:
    """
    Extract the GPS polyline from a ride's cached streams for a segment range.

    Returns list of (lat, lon) tuples, or None if extraction fails.
    """
    cached = conn.execute(
        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not cached:
        return None

    try:
        raw = json.loads(cached[0])
        streams = {s["type"]: s["data"] for s in raw}
    except (json.JSONDecodeError, KeyError):
        return None

    latlng = streams.get("latlng", [])
    if not latlng:
        return None

    polyline: List[Tuple[float, float]] = []
    for i in range(start_index, min(end_index + 1, len(latlng))):
        if i < len(latlng) and latlng[i] and len(latlng[i]) == 2:
            lat, lon = latlng[i][0], latlng[i][1]
            # Skip null island and invalid GPS
            if (lat == 0.0 and lon == 0.0) or abs(lat) > 90 or abs(lon) > 180:
                continue
            polyline.append((lat, lon))

    return polyline if len(polyline) >= MIN_POLYLINE_POINTS else None


def compute_bbox(
    polyline: List[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """Compute (min_lat, max_lat, min_lon, max_lon) for a polyline."""
    lats = [p[0] for p in polyline]
    lons = [p[1] for p in polyline]
    return min(lats), max(lats), min(lons), max(lons)


def main():
    parser = argparse.ArgumentParser(description="Build segment templates from golden corpus")
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--min-occurrences", type=int, default=MIN_OCCURRENCES,
                        help="Min rides a segment must appear in")
    parser.add_argument("--min-elev", type=float, default=MIN_ELEV_DIFF,
                        help="Min elevation diff (m) for a segment to be a climb")
    parser.add_argument("--min-grade", type=float, default=MIN_AVG_GRADE,
                        help="Min average grade (%%) for a segment to be a climb")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview eligible segments without building")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and rebuild the template table")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    if args.rebuild:
        conn.execute("DROP TABLE IF EXISTS segment_templates")
        conn.commit()
        print("Dropped existing segment_templates table.")

    init_template_table(conn)

    print(f"Finding eligible segments (min_occ={args.min_occurrences}, "
          f"min_elev={args.min_elev}m, min_grade={args.min_grade}%)...")
    segments = find_eligible_segments(
        conn,
        min_elev=args.min_elev,
        min_grade=args.min_grade,
        min_occurrences=args.min_occurrences,
    )
    print(f"  Found {len(segments)} eligible segments")

    if args.dry_run:
        print("\nDry run — preview of eligible segments:")
        for seg in segments[:30]:
            print(f"  seg={seg['segment_id']:>10d}  rides={seg['ride_count']:3d}  "
                  f"elev={seg['avg_elev_diff']:5.1f}m  grade={seg['avg_grade']:4.1f}%  "
                  f"{seg['segment_name']}")
        if len(segments) > 30:
            print(f"  ... and {len(segments) - 30} more")
        return

    built = 0
    skipped = 0
    failed = 0

    for idx, seg in enumerate(segments):
        segment_id = seg["segment_id"]

        # Find the best ride to extract the polyline from
        best = find_best_effort_for_segment(conn, segment_id)
        if best is None:
            skipped += 1
            continue

        # Extract the GPS polyline
        polyline = extract_polyline(
            conn,
            best["activity_id"],
            best["start_index"],
            best["end_index"],
        )
        if polyline is None:
            failed += 1
            continue

        # Compute bounding box
        min_lat, max_lat, min_lon, max_lon = compute_bbox(polyline)

        # Store the template
        polyline_json = json.dumps(polyline)
        conn.execute("""
            INSERT OR REPLACE INTO segment_templates
            (segment_id, segment_name, expected_vert_m, expected_grade_pct,
             expected_distance_m, polyline_json, bbox_min_lat, bbox_max_lat,
             bbox_min_lon, bbox_max_lon, source_activity_id, point_count,
             occurrence_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            segment_id,
            seg["segment_name"],
            seg["avg_elev_diff"],
            seg["avg_grade"],
            seg["avg_distance_m"],
            polyline_json,
            min_lat, max_lat, min_lon, max_lon,
            best["activity_id"],
            len(polyline),
            seg["ride_count"],
        ))

        built += 1

        if (idx + 1) % 50 == 0 or idx == len(segments) - 1:
            conn.commit()
            print(f"  [{idx+1}/{len(segments)}] built={built} skipped={skipped} failed={failed}")

    conn.commit()

    # Summary
    total = conn.execute("SELECT COUNT(*) FROM segment_templates").fetchone()[0]
    avg_points = conn.execute("SELECT AVG(point_count) FROM segment_templates").fetchone()[0] or 0
    avg_vert = conn.execute("SELECT AVG(expected_vert_m) FROM segment_templates").fetchone()[0] or 0
    total_occ = conn.execute("SELECT SUM(occurrence_count) FROM segment_templates").fetchone()[0] or 0

    print(f"\n{'='*60}")
    print(f"SEGMENT TEMPLATE BUILD SUMMARY")
    print(f"{'='*60}")
    print(f"Eligible segments:       {len(segments)}")
    print(f"Templates built:         {built}")
    print(f"Skipped (no effort):     {skipped}")
    print(f"Failed (bad GPS):        {failed}")
    print(f"Total in table:          {total}")
    print(f"Avg polyline points:     {avg_points:.0f}")
    print(f"Avg expected vert:       {avg_vert:.1f}m")
    print(f"Total ride occurrences:  {total_occ}")
    print(f"Database:                {args.db}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
