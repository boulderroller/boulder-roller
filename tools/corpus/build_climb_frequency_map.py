#!/usr/bin/env python3
"""
Build a climb tile frequency map from golden corpus detection results.

For each matched detection in the corpus, computes the H3 tile at resolution 8
(~460m hexagons) from the segment's GPS coordinates and builds a frequency table.

This table acts as a Bayesian prior for the climb chooser: if many different rides
have had climbs detected starting at the same H3 tile, that tile is almost certainly
the base of a real climb.

The frequency map is stored in the `climb_tile_frequency` table in golden_corpus.db.

Usage:
    python tools/corpus/build_climb_frequency_map.py                              # All matched results
    python tools/corpus/build_climb_frequency_map.py --run-id <id>                # Specific run
    python tools/corpus/build_climb_frequency_map.py --history-only               # Only pre-2022 rides (for temporal split)
    python tools/corpus/build_climb_frequency_map.py --min-confidence corroborated  # Only cross-family corroborated
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import h3
except ImportError:
    print("ERROR: h3 library required. Install with: pip install h3", file=sys.stderr)
    sys.exit(1)

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
H3_RESOLUTION = 8  # ~460m hexagons — appropriate for "same general location"


def create_frequency_table(conn: sqlite3.Connection) -> None:
    """Create or reset the climb_tile_frequency table."""
    conn.execute("DROP TABLE IF EXISTS climb_tile_frequency")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS climb_tile_frequency (
            h3_tile TEXT PRIMARY KEY,
            detection_count INTEGER,
            unique_segments INTEGER,
            unique_activities INTEGER,
            avg_vert_m REAL,
            avg_grade_pct REAL
        )
    """)
    conn.commit()


def get_latest_canonical_v2_run_id(conn: sqlite3.Connection) -> Optional[str]:
    """Get the most recent canonical_v2 run ID."""
    row = conn.execute("""
        SELECT run_id FROM detection_runs
        WHERE algorithm = 'canonical_v2'
        ORDER BY created_at DESC LIMIT 1
    """).fetchone()
    return row[0] if row else None


def _get_corroborated_pairs(conn: sqlite3.Connection) -> set:
    """Find (activity_id, segment_id) pairs matched by both momentum and persistence families.

    Cross-family corroboration means the detection was confirmed by two independent
    algorithms, making it much less likely to be a false positive. This prevents
    single-family false positives from bootstrapping the frequency map.

    A "momentum family" algorithm is any run whose algorithm name contains "momentum"
    or "canonical" (which internally uses momentum). A "persistence family" is any run
    whose algorithm name contains "persistence".
    """
    query = """
        SELECT dr.activity_id, dr.segment_id
        FROM detection_results dr
        JOIN detection_runs drun ON dr.run_id = drun.run_id
        WHERE dr.result_type = 'matched'
        GROUP BY dr.activity_id, dr.segment_id
        HAVING
            SUM(CASE WHEN drun.algorithm LIKE '%momentum%'
                       OR drun.algorithm LIKE '%canonical%' THEN 1 ELSE 0 END) > 0
            AND
            SUM(CASE WHEN drun.algorithm LIKE '%persistence%' THEN 1 ELSE 0 END) > 0
    """
    rows = conn.execute(query).fetchall()
    return {(r[0], r[1]) for r in rows}


def build_frequency_map(
    conn: sqlite3.Connection,
    *,
    run_id: Optional[str] = None,
    history_only: bool = False,
    corroborated_only: bool = False,
) -> Dict[str, Dict]:
    """Build the frequency map from matched detection results.

    For each matched detection, we get the GPS coordinates at the segment's
    start_index from the cached activity streams, compute the H3 tile at
    resolution 8, and accumulate counts.

    Args:
        conn: SQLite connection to golden_corpus.db
        run_id: Specific run_id to use. If None, uses all matched results.
        history_only: If True, only use rides from before 2022 (temporal split).
        corroborated_only: If True, only count detections where both momentum and
            persistence families matched the same (activity_id, segment_id). This
            prevents false positives from a single detector family from inflating
            the frequency map.

    Returns:
        Dict mapping H3 tile -> {count, segments, activities, vert_sum, grade_sum}
    """
    # Pre-compute corroborated pairs if filtering is enabled
    corroborated_pairs: Optional[set] = None
    if corroborated_only:
        corroborated_pairs = _get_corroborated_pairs(conn)
        print(f"Cross-family corroborated pairs: {len(corroborated_pairs)}")

    # Build the query for matched results with segment info
    where_clauses = ["dr.result_type = 'matched'"]
    params: list = []

    if run_id:
        where_clauses.append("dr.run_id = ?")
        params.append(run_id)

    if history_only:
        where_clauses.append("r.start_date < '2022-01-01'")

    where_sql = " AND ".join(where_clauses)

    # Get all matched results with segment start_index and activity_id
    query = f"""
        SELECT DISTINCT
            dr.activity_id,
            dr.segment_id,
            sse.start_index,
            dr.seg_elev_diff,
            dr.seg_avg_grade
        FROM detection_results dr
        JOIN strava_segment_efforts sse
            ON dr.activity_id = sse.activity_id AND dr.segment_id = sse.segment_id
        LEFT JOIN rides r ON dr.activity_id = r.activity_id
        WHERE {where_sql}
    """

    rows = conn.execute(query, params).fetchall()
    print(f"Found {len(rows)} matched segment efforts to process")

    # Cache for loaded streams
    stream_cache: Dict[str, Optional[Dict]] = {}
    tile_data: Dict[str, Dict] = defaultdict(
        lambda: {"count": 0, "segments": set(), "activities": set(), "vert_sum": 0.0, "grade_sum": 0.0}
    )

    skipped_no_stream = 0
    skipped_no_gps = 0
    skipped_no_corroboration = 0
    processed = 0

    for activity_id, segment_id, start_index, elev_diff, avg_grade in rows:
        # Skip detections without cross-family corroboration if filtering is on
        if corroborated_pairs is not None and (activity_id, segment_id) not in corroborated_pairs:
            skipped_no_corroboration += 1
            continue
        # Load streams if not cached
        if activity_id not in stream_cache:
            cached = conn.execute(
                "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
                (activity_id,)
            ).fetchone()
            if cached:
                try:
                    raw = json.loads(cached[0])
                    stream_cache[activity_id] = {s["type"]: s["data"] for s in raw}
                except (json.JSONDecodeError, KeyError):
                    stream_cache[activity_id] = None
            else:
                stream_cache[activity_id] = None

        streams = stream_cache[activity_id]
        if streams is None:
            skipped_no_stream += 1
            continue

        latlng = streams.get("latlng", [])
        if not latlng or start_index >= len(latlng):
            skipped_no_gps += 1
            continue

        lat, lon = latlng[start_index]
        if lat == 0.0 and lon == 0.0:
            skipped_no_gps += 1
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            skipped_no_gps += 1
            continue

        # Compute H3 tile at resolution 8
        tile = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)

        tile_data[tile]["count"] += 1
        tile_data[tile]["segments"].add(segment_id)
        tile_data[tile]["activities"].add(activity_id)
        tile_data[tile]["vert_sum"] += float(elev_diff or 0)
        tile_data[tile]["grade_sum"] += float(avg_grade or 0)
        processed += 1

    skip_parts = [f"{skipped_no_stream} (no streams)", f"{skipped_no_gps} (no GPS)"]
    if corroborated_pairs is not None:
        skip_parts.append(f"{skipped_no_corroboration} (no cross-family corroboration)")
    print(f"Processed {processed} results, skipped {', '.join(skip_parts)}")
    print(f"Unique H3 tiles: {len(tile_data)}")

    return dict(tile_data)


def store_frequency_map(conn: sqlite3.Connection, tile_data: Dict[str, Dict]) -> None:
    """Store the frequency map in the database."""
    create_frequency_table(conn)

    for tile, data in tile_data.items():
        count = data["count"]
        unique_segments = len(data["segments"])
        unique_activities = len(data["activities"])
        avg_vert = data["vert_sum"] / count if count > 0 else 0
        avg_grade = data["grade_sum"] / count if count > 0 else 0

        conn.execute("""
            INSERT OR REPLACE INTO climb_tile_frequency
            (h3_tile, detection_count, unique_segments, unique_activities, avg_vert_m, avg_grade_pct)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (tile, count, unique_segments, unique_activities, round(avg_vert, 1), round(avg_grade, 1)))

    conn.commit()


def load_frequency_map(conn: sqlite3.Connection) -> Dict[str, int]:
    """Load frequency map from the database as a simple tile -> count dict.

    This is the format expected by the chooser's H12 heuristic.
    """
    rows = conn.execute("SELECT h3_tile, detection_count FROM climb_tile_frequency").fetchall()
    return {row[0]: row[1] for row in rows}


def print_stats(tile_data: Dict[str, Dict]) -> None:
    """Print frequency map statistics."""
    if not tile_data:
        print("No data to report.")
        return

    counts = [d["count"] for d in tile_data.values()]
    counts_sorted = sorted(counts, reverse=True)

    print(f"\n=== Climb Tile Frequency Map Stats ===")
    print(f"Total unique H3 tiles: {len(tile_data)}")
    print(f"Total detection events: {sum(counts)}")
    print(f"Max count per tile: {max(counts)}")
    print(f"Min count per tile: {min(counts)}")
    print(f"Mean count per tile: {sum(counts) / len(counts):.1f}")

    # Distribution
    brackets = [(1, 1), (2, 4), (5, 9), (10, 19), (20, 49), (50, float("inf"))]
    print(f"\nDistribution:")
    for lo, hi in brackets:
        n = sum(1 for c in counts if lo <= c <= hi)
        label = f"{lo}" if lo == hi else f"{lo}-{int(hi)}" if hi < float("inf") else f"{lo}+"
        print(f"  {label:>6s} detections: {n:4d} tiles ({100*n/len(counts):5.1f}%)")

    # Top 20 tiles
    top_tiles = sorted(tile_data.items(), key=lambda x: x[1]["count"], reverse=True)[:20]
    print(f"\nTop 20 tiles:")
    for tile, data in top_tiles:
        print(f"  {tile}: {data['count']:3d} detections, "
              f"{len(data['segments']):2d} segments, "
              f"{len(data['activities']):3d} activities, "
              f"avg vert={data['vert_sum']/data['count']:.0f}m, "
              f"avg grade={data['grade_sum']/data['count']:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Build climb tile frequency map")
    parser.add_argument("--db", default=str(GOLDEN_DB))
    parser.add_argument("--run-id", type=str, default=None,
                        help="Specific detection run ID to use. Default: all matched results.")
    parser.add_argument("--history-only", action="store_true",
                        help="Only use pre-2022 rides (temporal split for honest evaluation)")
    parser.add_argument("--min-confidence", type=str, default=None,
                        choices=["corroborated"],
                        help="Only count detections meeting a minimum confidence level. "
                             "'corroborated' requires both momentum and persistence families "
                             "to have matched the same (activity, segment) pair. This prevents "
                             "false positives from a single detector from inflating the "
                             "frequency map (audit RED H12-decay).")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")

    if args.run_id:
        print(f"Building frequency map from run_id: {args.run_id}")
    else:
        print("Building frequency map from ALL matched detection results")

    if args.history_only:
        print("  (restricted to pre-2022 history rides)")

    corroborated_only = args.min_confidence == "corroborated"
    if corroborated_only:
        print("  (filtering to cross-family corroborated detections only)")

    tile_data = build_frequency_map(
        conn,
        run_id=args.run_id,
        history_only=args.history_only,
        corroborated_only=corroborated_only,
    )

    store_frequency_map(conn, tile_data)
    print_stats(tile_data)

    # Verify round-trip
    loaded = load_frequency_map(conn)
    print(f"\nVerification: loaded {len(loaded)} tiles from database")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
