#!/usr/bin/env python3
"""
Parameter sweep tool for canonical_v2 chooser weights.

Splits the expensive detector work (Phase 1) from the cheap chooser
scoring (Phase 2) so we can explore parameter combinations in seconds
rather than hours.

Phase 1 (--cache-proposals): Run momentum + persistence detectors on
  all scorable rides and cache every proposal into golden_corpus.db.
  This is the slow part (~10 min, run once).  Use --rebuild to drop
  and recreate the cached_proposals table (needed when detector or
  terrain set changes).

Phase 2 (--sweep): Re-run the chooser logic with different parameter
  values against the cached proposals.  Pure Python arithmetic.

  7 sweep axes (6,480 combinations at ~0.15s/combo = ~16 min):
    Base:      SSP (6), RSS (5), RTG (2), PST (4)   = 240
    Heuristic: H3V (3), H9D (3), H4I (3)            = x27
                                                       ------
                                                       6,480

  The chooser mirrors production _choose_canonical_v2_climbs exactly:
    - Multi-terrain candidate merging (iter 10)
    - Cluster-based scoring with H2/H3/H4/H9 heuristic bonuses
    - Persistence rescue path with RTG gate + RSS surplus
    - Momentum terrains: auto, hilly, urban_hills, rolling

Usage:
    # Phase 1: Cache proposals (slow, ~10 min)
    python tools/corpus/parameter_sweep.py --cache-proposals

    # Rebuild cache (needed after terrain set change or new heuristics)
    python tools/corpus/parameter_sweep.py --cache-proposals --rebuild

    # Phase 2: Run sweep (fast, ~16 min for 6,480 combos)
    python tools/corpus/parameter_sweep.py --sweep

    # Both phases
    python tools/corpus/parameter_sweep.py --cache-proposals --sweep

    # Use a sample for development
    python tools/corpus/parameter_sweep.py --cache-proposals --sweep --sample 100
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from uuid import uuid4

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import (
    CANONICAL_V2_MIN_SCORE,
    CANONICAL_V2_SINGLE_SOURCE_PENALTY,
    TERRAIN_NOTABLE_GRADIENT,
    TERRAIN_NOTABLE_VERT,
    ClimbCandidate,
    ClimbPattern,
    RideQualityProfile,
    _build_climb_candidates,
    _candidate_confidence,
    _candidate_family,
    _candidate_fragmentation_penalty,
    _candidate_quality_penalty,
    _candidate_source_prior,
    _candidates_corroborate,
    _climb_strength_score,
    _cluster_canonical_v2_candidates,
    _h2_power_confirmation_bonus,
    _h3_terrain_context_bonus,
    _h4_intensity_bonus,
    _h9_roller_filter_bonus,
    _h10_isolation_bonus,
    _h12_frequency_prior_bonus,
    _run_canonical_momentum_sweep,
    _run_rust_detector,
    _score_canonical_v2_momentum_set,
    _score_climb_candidate,
    _should_prefer_persistence_override,
    classify_terrain,
)
from app.services.patterns.climb_profile import build_ride_climb_profile
from app.services.tile_service import TileService

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
GOLDEN_FREQ_DB = Path(__file__).parent / "golden_corpus_freq.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Phase 1: Cache detector proposals
# ---------------------------------------------------------------------------

CACHED_PROPOSALS_DDL = """
CREATE TABLE IF NOT EXISTS cached_proposals (
    activity_id TEXT NOT NULL,
    proposal_type TEXT NOT NULL,
    climb_index INTEGER NOT NULL,
    start_s INTEGER,
    end_s INTEGER,
    vert_m REAL,
    gradient_pct REAL,
    distance_m REAL,
    time_s INTEGER,
    persistence_value REAL,
    avg_power_w REAL,
    avg_hr INTEGER,
    -- ride-level context
    terrain_class TEXT,
    integrity_score REAL,
    sparse_sampling INTEGER,
    degraded_elevation INTEGER,
    degraded_gps INTEGER,
    gps_jump_count INTEGER,
    -- ride-level aggregates for heuristics
    ride_total_gain_m REAL,
    ride_avg_power_w REAL,
    -- quality profile JSON (full)
    quality_json TEXT,
    PRIMARY KEY (activity_id, proposal_type, climb_index)
);
"""


def streams_to_tile_data(streams: Dict) -> Tuple[list, list]:
    """Convert Strava streams to tile samples and tile runs."""
    points = []
    for i, t in enumerate(streams.get("time", [])):
        point = {"timestamp": float(t)}
        if "altitude" in streams and i < len(streams["altitude"]):
            point["elevation_m"] = streams["altitude"][i]
        if "latlng" in streams and i < len(streams["latlng"]):
            point["lat"] = streams["latlng"][i][0]
            point["lon"] = streams["latlng"][i][1]
        if "watts" in streams and i < len(streams["watts"]):
            pw = streams["watts"][i]
            if pw and 0 < pw < 5000:
                point["power_w"] = pw
        if "heartrate" in streams and i < len(streams["heartrate"]):
            hr = streams["heartrate"][i]
            if hr and 0 < hr < 255:
                point["hr_bpm"] = hr
        points.append(point)

    if not points:
        return [], []

    ts = TileService()
    tile_samples = [
        {
            "tile_id": s.tile_id,
            "t": int(s.t),
            "lat": s.lat,
            "lon": s.lon,
            "elevation_m": s.elevation_m,
            "power_w": s.power_w,
            "hr_bpm": s.hr_bpm,
            "speed_mps": s.speed_mps,
        }
        for s in ts.get_tile_sequence(points, resolution=10, start_time=0)
    ]
    tile_runs = ts.get_tile_run_sequence(points, resolution=10, start_time=0)
    return tile_samples, tile_runs or tile_samples


def _get_scorable_activity_ids(conn: sqlite3.Connection, sample: int = 0) -> List[str]:
    """Get activity IDs with cached streams and enough climb segments."""
    rows = conn.execute(
        """SELECT r.activity_id
           FROM rides r
           JOIN strava_segment_efforts s
             ON r.activity_id = s.activity_id AND s.is_climb = 1
           JOIN activity_streams a ON r.activity_id = a.activity_id
           WHERE s.elevation_diff >= ? AND s.average_grade >= ?
           GROUP BY r.activity_id
           HAVING COUNT(s.id) >= 3
           ORDER BY r.elevation_gain_m DESC""",
        (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
    ).fetchall()
    activity_ids = [r[0] for r in rows]
    if sample > 0:
        activity_ids = activity_ids[:sample]
    return activity_ids


def _get_split_activity_ids(
    conn: sqlite3.Connection, split: str, sample: int = 0
) -> List[str]:
    """Get scorable activity IDs filtered by train/eval split."""
    rows = conn.execute(
        """SELECT r.activity_id
           FROM rides r
           JOIN strava_segment_efforts s
             ON r.activity_id = s.activity_id AND s.is_climb = 1
           JOIN activity_streams a ON r.activity_id = a.activity_id
           JOIN ride_split rs ON r.activity_id = rs.activity_id
           WHERE s.elevation_diff >= ? AND s.average_grade >= ?
             AND rs.split = ?
           GROUP BY r.activity_id
           HAVING COUNT(s.id) >= 3
           ORDER BY r.elevation_gain_m DESC""",
        (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT, split),
    ).fetchall()
    activity_ids = [r[0] for r in rows]
    if sample > 0:
        activity_ids = activity_ids[:sample]
    return activity_ids


def _load_frequency_map(db_path: str, split_conn: Optional[sqlite3.Connection] = None, split: Optional[str] = None) -> Optional[Dict[str, int]]:
    """Load climb frequency map for H12 heuristic.

    If split is specified, filters the frequency map to only include tiles
    derived from rides in the given split (avoids information leakage from
    eval set into train-set tuning).

    Args:
        db_path: Path to golden corpus DB.
        split_conn: Connection with ride_split table.
        split: If set, only include tiles from rides in this split.
    """
    freq_db = Path(db_path).parent / "golden_corpus_freq.db"
    if not freq_db.exists():
        # Try main DB
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            rows = conn.execute(
                "SELECT h3_tile, detection_count FROM climb_tile_frequency"
            ).fetchall()
            conn.close()
            if rows:
                return {r[0]: r[1] for r in rows}
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass
        return None

    try:
        freq_conn = sqlite3.connect(str(freq_db), timeout=5)
        rows = freq_conn.execute(
            "SELECT h3_tile, detection_count FROM climb_tile_frequency"
        ).fetchall()
        freq_conn.close()
        if not rows:
            return None
        freq_map = {r[0]: r[1] for r in rows}
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return None

    # If no split filtering requested, return full map
    if not split or not split_conn:
        return freq_map

    # Filter: only keep tiles that appear in rides from the specified split.
    # We rebuild frequencies from detection_results joined with ride_split.
    # This prevents eval-set detection history from leaking into train-set tuning.
    try:
        # Check if detection_results table exists
        table_check = split_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='detection_results'"
        ).fetchone()
        if not table_check:
            print(f"  Warning: detection_results table not found; using full frequency map")
            return freq_map

        # Get activity_ids in the target split
        split_aids = set()
        for row in split_conn.execute(
            "SELECT activity_id FROM ride_split WHERE split = ?", (split,)
        ):
            split_aids.add(row[0])

        # Get all matched detections from the split's rides and rebuild tile counts
        # using the same H3 resolution 8 approach as build_climb_frequency_map.py
        try:
            import h3

            matched_rows = split_conn.execute("""
                SELECT dr.activity_id, sse.start_index
                FROM detection_results dr
                JOIN strava_segment_efforts sse
                    ON dr.activity_id = sse.activity_id AND dr.segment_id = sse.segment_id
                WHERE dr.result_type = 'matched'
            """).fetchall()

            # Build a cache of stream GPS data
            stream_cache: Dict[str, Optional[List]] = {}
            filtered_map: Dict[str, int] = defaultdict(int)

            for activity_id, start_index in matched_rows:
                if activity_id not in split_aids:
                    continue

                if activity_id not in stream_cache:
                    cached = split_conn.execute(
                        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
                        (activity_id,),
                    ).fetchone()
                    if cached:
                        try:
                            raw = json.loads(cached[0])
                            streams = {s["type"]: s["data"] for s in raw}
                            stream_cache[activity_id] = streams.get("latlng", [])
                        except Exception:
                            stream_cache[activity_id] = None
                    else:
                        stream_cache[activity_id] = None

                latlng = stream_cache[activity_id]
                if not latlng or start_index >= len(latlng):
                    continue

                lat, lon = latlng[start_index]
                if lat == 0.0 and lon == 0.0:
                    continue
                if abs(lat) > 90 or abs(lon) > 180:
                    continue

                tile = h3.latlng_to_cell(lat, lon, 8)
                filtered_map[tile] += 1

            print(f"  H12 frequency map: {len(filtered_map)} tiles from {split} rides "
                  f"(full map: {len(freq_map)} tiles)")
            return dict(filtered_map) if filtered_map else freq_map

        except ImportError:
            print("  Warning: h3 not available; using full frequency map")
            return freq_map

    except Exception as exc:
        print(f"  Warning: frequency map filtering failed ({exc}); using full map")
        return freq_map


def _compute_ride_total_gain_m(tile_samples: List[Dict]) -> float:
    """Compute total elevation gain from tile samples using SMA(21) smoothing."""
    elevations = [s.get("elevation_m") for s in tile_samples if s.get("elevation_m") is not None]
    if len(elevations) < 2:
        return 0.0
    # SMA(21) to match production elevation gain calculation
    window = min(21, len(elevations))
    half = window // 2
    smoothed = []
    for i in range(len(elevations)):
        lo = max(0, i - half)
        hi = min(len(elevations), i + half + 1)
        smoothed.append(sum(elevations[lo:hi]) / (hi - lo))
    total_gain = 0.0
    for i in range(1, len(smoothed)):
        delta = smoothed[i] - smoothed[i - 1]
        if delta > 0:
            total_gain += delta
    return total_gain


def _compute_ride_avg_power_w(tile_samples: List[Dict]) -> Optional[float]:
    """Compute ride-average power from tile samples."""
    powers = [s["power_w"] for s in tile_samples if s.get("power_w") and s["power_w"] > 0]
    if not powers:
        return None
    return sum(powers) / len(powers)


def cache_proposals(db_path: str, sample: int = 0, rebuild: bool = False) -> None:
    """Phase 1: Run detectors and cache all proposals.

    Args:
        db_path: Path to golden corpus database.
        sample: Only process first N rides (0 = all).
        rebuild: Drop and recreate cached_proposals table.
    """
    import workout_parse as wp

    conn = sqlite3.connect(db_path)

    if rebuild:
        print("  --rebuild: Dropping cached_proposals table")
        conn.execute("DROP TABLE IF EXISTS cached_proposals")
        conn.commit()

    conn.execute(CACHED_PROPOSALS_DDL)
    conn.commit()

    activity_ids = _get_scorable_activity_ids(conn, sample)
    print(f"Phase 1: Caching proposals for {len(activity_ids)} rides")

    already_cached = set()
    for row in conn.execute("SELECT DISTINCT activity_id FROM cached_proposals"):
        already_cached.add(row[0])

    to_process = [aid for aid in activity_ids if aid not in already_cached]
    print(f"  Already cached: {len(already_cached)}, to process: {len(to_process)}")

    errors = 0
    t0 = time.time()

    for idx, activity_id in enumerate(to_process):
        if (idx + 1) % 25 == 0 or idx == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / max(1, elapsed)
            remaining = (len(to_process) - idx - 1) / max(0.01, rate)
            print(
                f"  [{idx + 1}/{len(to_process)}] "
                f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)"
            )

        cached = conn.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        if not cached:
            continue

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}
            tile_samples, tile_runs = streams_to_tile_data(streams)
            if not tile_samples:
                continue

            # Compute ride quality profile
            ride_quality = RideQualityProfile.from_tile_samples(tile_samples)
            terrain_info = classify_terrain(tile_samples)
            terrain_class = terrain_info.get("class") if terrain_info else None

            quality_json = json.dumps(ride_quality.to_dict())

            # Compute ride-level aggregates for heuristics
            ride_total_gain_m = _compute_ride_total_gain_m(tile_samples)
            ride_avg_power_w = _compute_ride_avg_power_w(tile_samples)

            # Run momentum sweep across all terrains (full-resolution tile_samples)
            terrain_results, best_terrain, _ = _run_canonical_momentum_sweep(
                wp,
                tile_samples=tile_samples,
                config_overrides=None,
                arena_tiles=None,
                user_weight_kg=75.0,
                generate_signatures=True,
            )

            rows_to_insert = []

            # Store momentum proposals per terrain
            for terrain_name, climbs in terrain_results.items():
                proposal_type = f"momentum:{terrain_name}"
                for ci, climb in enumerate(climbs):
                    rows_to_insert.append((
                        activity_id,
                        proposal_type,
                        ci,
                        climb.start_time_offset_s,
                        climb.end_time_offset_s,
                        climb.vert_m,
                        climb.avg_gradient_pct,
                        climb.distance_m,
                        climb.time_s,
                        None,  # persistence_value
                        climb.avg_power_w,
                        climb.avg_hr,
                        terrain_class,
                        ride_quality.integrity_score,
                        1 if ride_quality.sparse_sampling else 0,
                        1 if ride_quality.degraded_elevation else 0,
                        1 if ride_quality.degraded_gps else 0,
                        ride_quality.gps_jump_count,
                        ride_total_gain_m,
                        ride_avg_power_w,
                        quality_json,
                    ))

            # Run persistence detector (full-resolution tile_samples)
            try:
                persistence_climbs = _run_rust_detector(
                    wp,
                    tile_samples=tile_samples,
                    persistence_candidate_samples=tile_samples,
                    terrain="auto",
                    config_overrides=None,
                    arena_tiles=None,
                    user_weight_kg=75.0,
                    algorithm="persistence",
                    generate_signatures=True,
                )
                for ci, climb in enumerate(persistence_climbs):
                    rows_to_insert.append((
                        activity_id,
                        "persistence",
                        ci,
                        climb.start_time_offset_s,
                        climb.end_time_offset_s,
                        climb.vert_m,
                        climb.avg_gradient_pct,
                        climb.distance_m,
                        climb.time_s,
                        climb.persistence,
                        climb.avg_power_w,
                        climb.avg_hr,
                        terrain_class,
                        ride_quality.integrity_score,
                        1 if ride_quality.sparse_sampling else 0,
                        1 if ride_quality.degraded_elevation else 0,
                        1 if ride_quality.degraded_gps else 0,
                        ride_quality.gps_jump_count,
                        ride_total_gain_m,
                        ride_avg_power_w,
                        quality_json,
                    ))
            except Exception as exc:
                # Persistence can fail on some rides; momentum still valid
                pass

            if rows_to_insert:
                conn.executemany(
                    """INSERT OR REPLACE INTO cached_proposals
                       (activity_id, proposal_type, climb_index,
                        start_s, end_s, vert_m, gradient_pct, distance_m, time_s,
                        persistence_value, avg_power_w, avg_hr,
                        terrain_class, integrity_score, sparse_sampling,
                        degraded_elevation, degraded_gps, gps_jump_count,
                        ride_total_gain_m, ride_avg_power_w,
                        quality_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows_to_insert,
                )
                conn.commit()

        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"    ERROR on {activity_id}: {exc}")

    elapsed = time.time() - t0
    total_proposals = conn.execute("SELECT COUNT(*) FROM cached_proposals").fetchone()[0]
    distinct_rides = conn.execute(
        "SELECT COUNT(DISTINCT activity_id) FROM cached_proposals"
    ).fetchone()[0]
    print(
        f"\nPhase 1 complete in {elapsed:.0f}s: "
        f"{distinct_rides} rides, {total_proposals} proposals, {errors} errors"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Phase 2: Sweep chooser parameters
# ---------------------------------------------------------------------------

SWEEP_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS sweep_results (
    sweep_id TEXT,
    single_source_penalty REAL,
    rescue_score_surplus REAL,
    rescue_terrain_gate INTEGER,
    persistence_strong_threshold REAL,
    h3_terrain_vert_multiplier REAL,
    h9_roller_duration_cutoff INTEGER,
    h4_intensity_threshold INTEGER,
    precision REAL,
    recall REAL,
    f1 REAL,
    matched INTEGER,
    missed INTEGER,
    extras INTEGER,
    total_segments INTEGER,
    total_detected INTEGER,
    PRIMARY KEY (sweep_id, single_source_penalty, rescue_score_surplus,
                 rescue_terrain_gate, persistence_strong_threshold,
                 h3_terrain_vert_multiplier, h9_roller_duration_cutoff,
                 h4_intensity_threshold)
);
"""

# Segment ground truth (loaded once)

@dataclass
class SegmentEffort:
    segment_id: int
    segment_name: str
    start_index: int
    end_index: int
    elevation_diff: float
    average_grade: float
    start_time_s: int = 0
    end_time_s: int = 0


@dataclass
class CachedProposal:
    """A single cached detector proposal."""
    activity_id: str
    proposal_type: str
    climb_index: int
    start_s: int
    end_s: int
    vert_m: float
    gradient_pct: float
    distance_m: float
    time_s: int
    persistence_value: Optional[float]
    avg_power_w: Optional[float]
    avg_hr: Optional[int]


@dataclass
class RideCache:
    """All cached data for a single ride."""
    activity_id: str
    momentum_proposals: Dict[str, List[CachedProposal]]  # terrain -> proposals
    persistence_proposals: List[CachedProposal]
    ride_quality: RideQualityProfile
    segments: List[SegmentEffort]
    time_array: List[int]
    terrain_class: Optional[str] = None
    ride_total_gain_m: Optional[float] = None
    ride_avg_power_w: Optional[float] = None
    tile_samples: Optional[List[Dict]] = None  # Full tile_samples for H10 isolation bonus


def _proposal_to_climb(p: CachedProposal) -> ClimbPattern:
    """Convert a cached proposal to a ClimbPattern for scoring."""
    climb = ClimbPattern(
        vert_m=p.vert_m,
        time_s=p.time_s,
        avg_power_w=p.avg_power_w,
        avg_hr=p.avg_hr,
        start_time_offset_s=p.start_s,
        end_time_offset_s=p.end_s,
        avg_gradient_pct=p.gradient_pct,
        distance_m=p.distance_m,
    )
    climb.persistence = p.persistence_value
    return climb


def _overlap_ratio(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(max(1, a_end - a_start), max(1, b_end - b_start))
    return overlap / shorter


def _dedup_segments(segments: List[SegmentEffort]) -> List[SegmentEffort]:
    """Dedup overlapping segments, keep highest elevation from each group."""
    groups: List[List[SegmentEffort]] = []
    for seg in sorted(segments, key=lambda s: s.start_index):
        placed = False
        for group in groups:
            for existing in group:
                overlap = max(
                    0,
                    min(seg.end_index, existing.end_index)
                    - max(seg.start_index, existing.start_index),
                )
                shorter = min(
                    max(1, seg.end_index - seg.start_index),
                    max(1, existing.end_index - existing.start_index),
                )
                if overlap / shorter >= OVERLAP_THRESHOLD:
                    group.append(seg)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([seg])
    return [max(g, key=lambda s: s.elevation_diff) for g in groups]


def _load_all_ride_caches(
    conn: sqlite3.Connection, activity_ids: List[str]
) -> List[RideCache]:
    """Load all ride data from DB into memory for fast sweep iteration."""
    ride_caches: List[RideCache] = []
    aid_set = set(activity_ids)

    # Load all proposals
    proposals_by_ride: Dict[str, List[CachedProposal]] = defaultdict(list)
    for row in conn.execute(
        """SELECT activity_id, proposal_type, climb_index,
                  start_s, end_s, vert_m, gradient_pct, distance_m, time_s,
                  persistence_value, avg_power_w, avg_hr, quality_json
           FROM cached_proposals
           ORDER BY activity_id, proposal_type, climb_index"""
    ):
        if row[0] not in aid_set:
            continue
        p = CachedProposal(
            activity_id=row[0],
            proposal_type=row[1],
            climb_index=row[2],
            start_s=row[3] or 0,
            end_s=row[4] or 0,
            vert_m=row[5] or 0.0,
            gradient_pct=row[6] or 0.0,
            distance_m=row[7] or 0.0,
            time_s=row[8] or 0,
            persistence_value=row[9],
            avg_power_w=row[10],
            avg_hr=int(row[11]) if row[11] is not None else None,
        )
        proposals_by_ride[row[0]].append(p)

    # Load quality profiles and ride-level metadata (one per ride, from the first proposal)
    quality_by_ride: Dict[str, RideQualityProfile] = {}
    terrain_by_ride: Dict[str, Optional[str]] = {}
    total_gain_by_ride: Dict[str, Optional[float]] = {}
    avg_power_by_ride: Dict[str, Optional[float]] = {}
    for row in conn.execute(
        """SELECT DISTINCT activity_id, quality_json,
                  integrity_score, sparse_sampling, degraded_elevation,
                  degraded_gps, gps_jump_count, terrain_class,
                  ride_total_gain_m, ride_avg_power_w
           FROM cached_proposals"""
    ):
        if row[0] not in aid_set or row[0] in quality_by_ride:
            continue
        terrain_by_ride[row[0]] = row[7]
        total_gain_by_ride[row[0]] = float(row[8]) if row[8] is not None else None
        avg_power_by_ride[row[0]] = float(row[9]) if row[9] is not None else None
        if row[1]:
            qd = json.loads(row[1])
            quality_by_ride[row[0]] = RideQualityProfile(
                source_class=qd.get("source_class", "native_dense"),
                integrity_score=qd.get("integrity_score", float(row[2] or 0.95)),
                gps_coverage=qd.get("gps_coverage", 1.0),
                elev_coverage=qd.get("elev_coverage", 1.0),
                median_interval_s=qd.get("median_interval_s", 1.0),
                sampling_regularity=qd.get("sampling_regularity", 1.0),
                gap_ratio=qd.get("gap_ratio", 0.0),
                gps_jump_count=qd.get("gps_jump_count", int(row[6] or 0)),
                sparse_sampling=bool(qd.get("sparse_sampling", row[3])),
                degraded_gps=bool(qd.get("degraded_gps", row[5])),
                degraded_elevation=bool(qd.get("degraded_elevation", row[4])),
                flags=qd.get("flags", []),
            )
        else:
            quality_by_ride[row[0]] = RideQualityProfile(
                source_class="native_dense",
                integrity_score=float(row[2] or 0.95),
                gps_coverage=1.0,
                elev_coverage=1.0,
                median_interval_s=1.0,
                sampling_regularity=1.0,
                gap_ratio=0.0,
                gps_jump_count=int(row[6] or 0),
                sparse_sampling=bool(row[3]),
                degraded_gps=bool(row[5]),
                degraded_elevation=bool(row[4]),
            )

    # Load segments and time arrays
    segments_by_ride: Dict[str, List[SegmentEffort]] = defaultdict(list)
    for row in conn.execute(
        """SELECT activity_id, segment_id, segment_name,
                  start_index, end_index, elevation_diff, average_grade
           FROM strava_segment_efforts
           WHERE is_climb = 1
             AND elevation_diff >= ? AND average_grade >= ?
           ORDER BY activity_id, start_index""",
        (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
    ):
        if row[0] not in aid_set:
            continue
        segments_by_ride[row[0]].append(
            SegmentEffort(
                segment_id=row[1],
                segment_name=row[2],
                start_index=row[3],
                end_index=row[4],
                elevation_diff=row[5],
                average_grade=row[6],
            )
        )

    # Load time arrays and optionally tile_samples from cached streams.
    # Tile_samples are needed for H10 isolation bonus but expensive to compute
    # (~10 min for 500 rides). When tile_samples aren't loaded, H10 returns 0.0.
    # Set SWEEP_LOAD_TILE_SAMPLES=1 to enable (default: off for speed).
    load_tile_samples = os.environ.get("SWEEP_LOAD_TILE_SAMPLES", "0") == "1"
    time_arrays_by_ride: Dict[str, List[int]] = {}
    tile_samples_by_ride: Dict[str, List[Dict]] = {}
    ts_loaded = 0
    for row in conn.execute(
        "SELECT activity_id, streams_json FROM activity_streams"
    ):
        if row[0] not in aid_set:
            continue
        try:
            raw = json.loads(row[1])
            streams = {s["type"]: s["data"] for s in raw}
            time_arrays_by_ride[row[0]] = streams.get("time", [])
            if load_tile_samples:
                # Convert streams to tile_samples for H10 isolation bonus
                ts, _ = streams_to_tile_data(streams)
                if ts:
                    tile_samples_by_ride[row[0]] = ts
                    ts_loaded += 1
        except Exception:
            pass
    if load_tile_samples:
        print(f"  Loaded tile_samples for {ts_loaded} rides (H10 enabled)")

    # Assemble RideCache objects
    for activity_id in activity_ids:
        if activity_id not in proposals_by_ride:
            continue
        if activity_id not in segments_by_ride:
            continue
        if activity_id not in quality_by_ride:
            continue
        if activity_id not in time_arrays_by_ride:
            continue

        proposals = proposals_by_ride[activity_id]
        momentum_proposals: Dict[str, List[CachedProposal]] = defaultdict(list)
        persistence_proposals: List[CachedProposal] = []

        for p in proposals:
            if p.proposal_type.startswith("momentum:"):
                terrain = p.proposal_type.split(":", 1)[1]
                momentum_proposals[terrain].append(p)
            elif p.proposal_type == "persistence":
                persistence_proposals.append(p)

        # Convert segment indices to time offsets
        time_array = time_arrays_by_ride[activity_id]
        segments = _dedup_segments(segments_by_ride[activity_id])
        for seg in segments:
            seg.start_time_s = (
                time_array[seg.start_index]
                if seg.start_index < len(time_array)
                else 0
            )
            seg.end_time_s = (
                time_array[seg.end_index]
                if seg.end_index < len(time_array)
                else 0
            )

        ride_caches.append(
            RideCache(
                activity_id=activity_id,
                momentum_proposals=dict(momentum_proposals),
                persistence_proposals=persistence_proposals,
                ride_quality=quality_by_ride[activity_id],
                segments=segments,
                time_array=time_array,
                terrain_class=terrain_by_ride.get(activity_id),
                ride_total_gain_m=total_gain_by_ride.get(activity_id),
                ride_avg_power_w=avg_power_by_ride.get(activity_id),
                tile_samples=tile_samples_by_ride.get(activity_id),
            )
        )

    return ride_caches


# ---------------------------------------------------------------------------
# Parameterized scoring helpers for heuristics
# ---------------------------------------------------------------------------


def _h3_terrain_context_bonus_parameterized(
    climb: ClimbPattern,
    terrain_class: Optional[str],
    ride_total_gain_m: Optional[float],
    *,
    vert_multiplier: float,
) -> float:
    """H3 bonus with parameterized vert multiplier for the 'standout' tier.

    The ``vert_multiplier`` controls the threshold at which a climb is
    considered a standout relative to its terrain (default production: 2.0).
    See docs/DETECTOR_PARAMS.md for canonical values.
    """
    if terrain_class is None:
        return 0.0

    notable_vert = TERRAIN_NOTABLE_VERT.get(terrain_class, 40.0)
    notable_gradient = TERRAIN_NOTABLE_GRADIENT.get(terrain_class, 4.0)
    gradient = climb.avg_gradient_pct or 0.0

    bonus = 0.0

    # Vert relative to terrain — parameterized standout multiplier
    if climb.vert_m >= notable_vert * vert_multiplier:
        bonus += 2.0
    elif climb.vert_m >= notable_vert * 1.5:
        bonus += 1.0
    elif climb.vert_m >= notable_vert:
        bonus += 0.5
    elif climb.vert_m < notable_vert * 0.5:
        bonus -= 1.0

    # Gradient relative to terrain
    if gradient >= notable_gradient * 2.0:
        bonus += 1.0
    elif gradient >= notable_gradient:
        bonus += 0.25
    elif gradient < notable_gradient * 0.5 and terrain_class in ("hilly", "mountainous"):
        bonus -= 0.75

    # Vert fraction of ride total
    if ride_total_gain_m and ride_total_gain_m > 0:
        vert_fraction = climb.vert_m / ride_total_gain_m
        if vert_fraction >= 0.15:
            bonus += 0.75
        elif vert_fraction >= 0.05:
            bonus += 0.25

    return max(-3.0, min(3.0, bonus))


def _h4_intensity_bonus_parameterized(
    climb: ClimbPattern,
    *,
    intensity_threshold: int,
) -> float:
    """H4 intensity bonus with parameterized top-tier threshold.

    The ``intensity_threshold`` controls what intensity = distance * gradient^2
    value qualifies for the top bonus tier (default production: 50000).
    """
    gradient = climb.avg_gradient_pct or 0.0
    time_s = climb.time_s
    distance_m = climb.distance_m or 0.0

    intensity = distance_m * (gradient ** 2)

    bonus = 0.0

    # Intensity tiers — top tier parameterized
    if intensity >= intensity_threshold:
        bonus += 2.0
    elif intensity >= intensity_threshold * 0.4:  # mid tier scales proportionally
        bonus += 1.0
    elif intensity >= intensity_threshold * 0.16:  # low tier
        bonus += 0.5

    # Steep punch bonus (unchanged)
    if gradient >= 10.0 and 30 <= time_s <= 300:
        bonus += 1.0
    elif gradient >= 7.0 and 60 <= time_s <= 600:
        bonus += 0.5

    return min(3.0, bonus)


def _h9_roller_filter_bonus_parameterized(
    climb: ClimbPattern,
    *,
    duration_cutoff: int,
) -> float:
    """H9 roller filter with parameterized duration cutoff.

    The ``duration_cutoff`` controls the boundary between "short roller"
    and "probably a climb" (default production: 90 seconds).
    See docs/DETECTOR_PARAMS.md for canonical values.
    """
    gradient = climb.avg_gradient_pct or 0.0
    time_s = climb.time_s

    # Sub-cutoff: must be very steep to qualify as a climb
    if time_s < duration_cutoff:
        if gradient >= 12.0:
            return 0.0    # Very steep punch — allow
        elif gradient >= 8.0:
            return -0.5   # Steep but short — mild penalty
        else:
            return -2.0   # Short and not steep — roller

    # Over 2x cutoff: probably a climb regardless of gradient
    if time_s >= duration_cutoff * 2:
        return 0.0

    # Gray zone (cutoff to 2*cutoff): use gradient as discriminator
    if gradient >= 6.0:
        return 0.0    # Steep enough
    elif gradient >= 4.0:
        return -0.5   # Borderline
    else:
        return -1.5   # Low gradient, short duration = roller


# ---------------------------------------------------------------------------
# Parameterized chooser (mirrors _choose_canonical_v2_climbs)
# ---------------------------------------------------------------------------


def _score_candidate_parameterized(
    candidate: ClimbCandidate,
    *,
    single_source_penalty: float,
    persistence_strong_threshold: float,
    h3_terrain_vert_multiplier: float,
    h9_roller_duration_cutoff: int,
    h4_intensity_threshold: int,
    tile_samples: Optional[List[Dict]] = None,
    frequency_map: Optional[Dict[str, int]] = None,
) -> Tuple[float, List[str]]:
    """
    Score a climb candidate using the production scoring functions but
    with parameterized thresholds for the sweep axes.

    Mirrors _score_climb_candidate exactly (including H2/H3/H4/H9),
    except threshold constants and heuristic thresholds use sweep
    parameters instead of hard-coded values.
    """
    reasons: List[str] = []

    strength = _climb_strength_score(candidate.climb)
    if strength > 0:
        reasons.append("strong_effort")

    # Source prior — persistence gets its own handling with sweep param
    if candidate.source == "persistence":
        source_prior = 0.15
        if (
            candidate.climb.persistence is not None
            and candidate.climb.persistence >= persistence_strong_threshold
        ):
            source_prior += 0.35
    else:
        source_prior = _candidate_source_prior(candidate.source, candidate.climb)
    if source_prior > 0:
        reasons.append(f"source:{candidate.source}")

    support_bonus = 0.0
    if candidate.corroborating_families:
        support_bonus += 1.5 * len(candidate.corroborating_families)
        reasons.append("cross_family_corroboration")
    elif candidate.corroborating_sources:
        support_bonus += 0.5
        reasons.append("same_family_corroboration")

    fragmentation_penalty = _candidate_fragmentation_penalty(candidate.climb)
    if (
        candidate.corroborating_families
        and candidate.climb.vert_m >= 100.0
        and fragmentation_penalty > 0
    ):
        fragmentation_penalty *= 0.3
        reasons.append("corroborated_highvert_frag_discount")
    if fragmentation_penalty > 0:
        reasons.append("fragmentation_penalty")

    quality_penalty = _candidate_quality_penalty(
        candidate.climb, candidate.ride_quality
    )
    if quality_penalty > 0.75:
        reasons.append(f"quality:{candidate.ride_quality.source_class}")

    # --- Heuristic bonuses (H2, H3, H4, H9) ---
    h3_bonus = _h3_terrain_context_bonus_parameterized(
        candidate.climb,
        candidate.terrain_class,
        candidate.ride_total_gain_m,
        vert_multiplier=h3_terrain_vert_multiplier,
    )
    if h3_bonus != 0:
        reasons.append(f"h3_terrain:{h3_bonus:+.1f}")

    h4_bonus = _h4_intensity_bonus_parameterized(
        candidate.climb,
        intensity_threshold=h4_intensity_threshold,
    )
    if h4_bonus != 0:
        reasons.append(f"h4_intensity:{h4_bonus:+.1f}")

    h9_bonus = _h9_roller_filter_bonus_parameterized(
        candidate.climb,
        duration_cutoff=h9_roller_duration_cutoff,
    )
    if h9_bonus != 0:
        reasons.append(f"h9_roller:{h9_bonus:+.1f}")

    h2_bonus = _h2_power_confirmation_bonus(candidate.climb, candidate.ride_avg_power_w)
    if h2_bonus != 0:
        reasons.append(f"h2_power:{h2_bonus:+.1f}")

    h10_bonus = _h10_isolation_bonus(candidate.climb, tile_samples)
    if h10_bonus != 0:
        reasons.append(f"h10_isolation:{h10_bonus:+.1f}")

    h12_bonus = _h12_frequency_prior_bonus(candidate.climb, frequency_map)
    if h12_bonus != 0:
        reasons.append(f"h12_frequency:{h12_bonus:+.1f}")

    total = (
        strength + source_prior + support_bonus
        + h3_bonus + h4_bonus + h9_bonus + h2_bonus + h10_bonus + h12_bonus
        - fragmentation_penalty - quality_penalty
    )

    # Threshold computation — matches production logic:
    # persistence family gets NO single-source penalty (independent family)
    # momentum-only gets the full penalty
    threshold = CANONICAL_V2_MIN_SCORE
    if not candidate.corroborating_families:
        if candidate.family == "persistence":
            pass  # Persistence is an independent detection family — no penalty
        else:
            threshold += single_source_penalty

    if candidate.ride_quality.sparse_sampling:
        threshold += 0.5
    if candidate.ride_quality.degraded_elevation and candidate.climb.vert_m < 35.0:
        threshold += 0.25

    candidate.base_score = strength
    candidate.acceptance_threshold = threshold
    return total, reasons


def _chooser_with_params(
    ride: RideCache,
    *,
    single_source_penalty: float,
    rescue_score_surplus: float,
    rescue_terrain_gate: int,
    persistence_strong_threshold: float,
    h3_terrain_vert_multiplier: float,
    h9_roller_duration_cutoff: int,
    h4_intensity_threshold: int,
    frequency_map: Optional[Dict[str, int]] = None,
) -> List[ClimbPattern]:
    """
    Parameterized chooser that mirrors _choose_canonical_v2_climbs.

    Uses the multi-terrain candidate merging and cluster-based scoring
    approach from production, with parameterized threshold behavior and
    heuristic bonuses.
    """
    ride_quality = ride.ride_quality

    if not ride.momentum_proposals:
        return []

    # Convert cached proposals to ClimbPatterns
    momentum_results: Dict[str, List[ClimbPattern]] = {}
    for terrain_name, proposals in ride.momentum_proposals.items():
        momentum_results[terrain_name] = [_proposal_to_climb(p) for p in proposals]

    persistence_climbs = [_proposal_to_climb(p) for p in ride.persistence_proposals]

    # Build candidates from ALL terrains (not just the best — matches production iter 10)
    all_momentum_candidates: List[ClimbCandidate] = []
    for terrain_name, climbs in momentum_results.items():
        candidates = _build_climb_candidates(
            climbs,
            source=f"momentum:{terrain_name}",
            ride_quality=ride_quality,
            terrain_class=ride.terrain_class,
            ride_total_gain_m=ride.ride_total_gain_m,
            ride_avg_power_w=ride.ride_avg_power_w,
        )
        all_momentum_candidates.extend(candidates)

    persistence_candidates = _build_climb_candidates(
        persistence_climbs,
        source="persistence",
        ride_quality=ride_quality,
        terrain_class=ride.terrain_class,
        ride_total_gain_m=ride.ride_total_gain_m,
        ride_avg_power_w=ride.ride_avg_power_w,
    )

    # Cluster overlapping candidates from all sources (production approach)
    clusters = _cluster_canonical_v2_candidates(
        all_momentum_candidates + persistence_candidates
    )

    selected: List[ClimbPattern] = []
    used_persistence_ids: Set[int] = set()

    heuristic_kwargs = dict(
        single_source_penalty=single_source_penalty,
        persistence_strong_threshold=persistence_strong_threshold,
        h3_terrain_vert_multiplier=h3_terrain_vert_multiplier,
        h9_roller_duration_cutoff=h9_roller_duration_cutoff,
        h4_intensity_threshold=h4_intensity_threshold,
        tile_samples=ride.tile_samples,
        frequency_map=frequency_map,
    )

    for cluster in clusters:
        # Collect all unique sources and families in this cluster
        cluster_sources = {c.source for c in cluster}
        cluster_families = {c.family for c in cluster}

        # Score each candidate with full cluster context
        best_candidate: Optional[ClimbCandidate] = None
        for candidate in cluster:
            other_sources = sorted(cluster_sources - {candidate.source})
            other_families = sorted(cluster_families - {candidate.family})
            candidate.corroborating_sources = other_sources
            candidate.corroborating_families = other_families
            candidate.total_score, candidate.reasons = _score_candidate_parameterized(
                candidate, **heuristic_kwargs
            )

            if best_candidate is None or candidate.total_score > best_candidate.total_score:
                best_candidate = candidate

        # Check persistence override
        for candidate in cluster:
            if candidate.family == "persistence" and best_candidate.family == "momentum":
                if _should_prefer_persistence_override(best_candidate, candidate):
                    best_candidate = candidate

        # Track which persistence candidates were part of this cluster
        for candidate in cluster:
            if candidate.family == "persistence":
                used_persistence_ids.add(id(candidate))

        if best_candidate.total_score < best_candidate.acceptance_threshold:
            # Cluster rejected — release persistence candidates for rescue path
            for candidate in cluster:
                if candidate.family == "persistence":
                    used_persistence_ids.discard(id(candidate))
            continue

        chosen = best_candidate.climb
        chosen.detector_mode = f"canonical_v2:{best_candidate.source}"
        selected.append(chosen)

    # Safety-net rescue: persistence candidates not placed in any cluster,
    # or released from rejected clusters, evaluated standalone
    for candidate in persistence_candidates:
        if id(candidate) in used_persistence_ids:
            continue
        # Check if this candidate already overlaps a selected climb
        if any(_candidates_corroborate(candidate.climb, s) for s in selected):
            continue
        corroborating_terrains = sorted(
            terrain_name
            for terrain_name, climbs in momentum_results.items()
            if any(_candidates_corroborate(candidate.climb, climb) for climb in climbs)
        )
        if len(corroborating_terrains) < rescue_terrain_gate:
            continue

        candidate.corroborating_sources = [f"momentum:{terrain}" for terrain in corroborating_terrains]
        candidate.corroborating_families = ["momentum"]
        candidate.total_score, candidate.reasons = _score_candidate_parameterized(
            candidate, **heuristic_kwargs
        )
        if candidate.total_score < candidate.acceptance_threshold + rescue_score_surplus:
            continue

        chosen = candidate.climb
        chosen.detector_mode = "canonical_v2:persistence"
        selected.append(chosen)

    return sorted(selected, key=lambda climb: climb.start_time_offset_s)


def _score_ride_with_params(
    ride: RideCache,
    *,
    single_source_penalty: float,
    rescue_score_surplus: float,
    rescue_terrain_gate: int,
    persistence_strong_threshold: float,
    h3_terrain_vert_multiplier: float,
    h9_roller_duration_cutoff: int,
    h4_intensity_threshold: int,
    frequency_map: Optional[Dict[str, int]] = None,
) -> Tuple[int, int, int]:
    """Run parameterized chooser on a ride and score against ground truth.

    Returns: (matched, missed, extras)
    """
    accepted = _chooser_with_params(
        ride,
        single_source_penalty=single_source_penalty,
        rescue_score_surplus=rescue_score_surplus,
        rescue_terrain_gate=rescue_terrain_gate,
        persistence_strong_threshold=persistence_strong_threshold,
        h3_terrain_vert_multiplier=h3_terrain_vert_multiplier,
        h9_roller_duration_cutoff=h9_roller_duration_cutoff,
        h4_intensity_threshold=h4_intensity_threshold,
        frequency_map=frequency_map,
    )

    # Fallback to best-terrain momentum if chooser returned nothing
    # (mirrors detect_climbs_with_rust behavior)
    if not accepted and ride.momentum_proposals:
        momentum_results: Dict[str, List[ClimbPattern]] = {}
        persistence_climbs: List[ClimbPattern] = []
        for terrain_name, proposals in ride.momentum_proposals.items():
            momentum_results[terrain_name] = [_proposal_to_climb(p) for p in proposals]
        persistence_climbs = [_proposal_to_climb(p) for p in ride.persistence_proposals]
        best_terrain = max(
            momentum_results,
            key=lambda tn: _score_canonical_v2_momentum_set(
                momentum_results[tn],
                persistence_climbs=persistence_climbs,
                ride_quality=ride.ride_quality,
            ),
        )
        accepted = momentum_results[best_terrain]

    # Filter to shown climbs (same as score_golden_corpus.py)
    detected = [
        c for c in accepted if c.vert_m >= MIN_DETECT_VERT_M
    ]

    # Match against Strava segments (same greedy algorithm as score_golden_corpus.py)
    used_detections: Set[int] = set()
    matched = 0

    for seg in ride.segments:
        best_idx = None
        best_overlap = 0.0

        for di, det in enumerate(detected):
            if di in used_detections:
                continue
            ovl = _overlap_ratio(
                seg.start_time_s,
                seg.end_time_s,
                det.start_time_offset_s,
                det.end_time_offset_s,
            )
            if ovl >= OVERLAP_THRESHOLD and ovl > best_overlap:
                best_idx = di
                best_overlap = ovl

        if best_idx is not None:
            matched += 1
            used_detections.add(best_idx)

    extras = len(detected) - len(used_detections)
    missed = len(ride.segments) - matched

    return matched, missed, extras


def run_sweep(db_path: str, sample: int = 0, split: Optional[str] = None) -> None:
    """Phase 2: Sweep chooser parameters against cached proposals.

    Args:
        db_path: Path to golden corpus DB.
        sample: Only use first N rides (0 = all).
        split: If set ('train' or 'eval'), only use rides in this split.
    """
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # Read-only is fine for loading cached proposals

    # Create sweep_results table if DB is writable (skip if locked)
    _sweep_results_writable = False
    try:
        conn.execute("DROP TABLE IF EXISTS sweep_results")
        conn.execute(SWEEP_RESULTS_DDL)
        conn.commit()
        _sweep_results_writable = True
    except sqlite3.OperationalError:
        print("  Warning: DB write-locked; sweep results will only be written to CSV")

    if split:
        # Verify ride_split table exists
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ride_split'"
        ).fetchone()
        if not table_check:
            print("ERROR: ride_split table not found. Run create_holdout_split.py first.")
            conn.close()
            return
        activity_ids = _get_split_activity_ids(conn, split, sample)
        print(f"Phase 2: Using {split} split ({len(activity_ids)} rides)")
    else:
        activity_ids = _get_scorable_activity_ids(conn, sample)

    # Filter to only those with cached proposals
    cached_aids = set()
    for row in conn.execute("SELECT DISTINCT activity_id FROM cached_proposals"):
        cached_aids.add(row[0])
    activity_ids = [aid for aid in activity_ids if aid in cached_aids]

    print(f"Phase 2: Loading ride data for {len(activity_ids)} rides...")
    t0 = time.time()
    ride_caches = _load_all_ride_caches(conn, activity_ids)
    load_time = time.time() - t0
    print(f"  Loaded {len(ride_caches)} rides in {load_time:.1f}s")

    # Filter rides that actually have segments
    ride_caches = [r for r in ride_caches if r.segments]
    print(f"  Rides with ground truth segments: {len(ride_caches)}")

    # Load frequency map for H12 heuristic (filtered to split if applicable)
    frequency_map = _load_frequency_map(
        db_path,
        split_conn=conn if split else None,
        split=split,
    )
    if frequency_map:
        print(f"  H12 frequency map loaded: {len(frequency_map)} tiles")
    else:
        print("  No frequency map found — H12 heuristic will be neutral")

    # Count rides with tile_samples for H10
    h10_count = sum(1 for r in ride_caches if r.tile_samples)
    print(f"  Rides with tile_samples for H10: {h10_count}/{len(ride_caches)}")

    # Parameter grid — base axes (4) + heuristic axes (3)
    # Updated for full-resolution tile_samples recalibration
    single_source_penalties = [0.0, 0.15, 0.25, 0.50, 0.75]
    rescue_score_surpluses = [0.0, 0.50, 1.0]
    rescue_terrain_gates = [1, 2]
    persistence_strong_thresholds = [15.0, 25.0, 50.0]
    # Heuristic axes
    h3_terrain_vert_multipliers = [2.0, 3.0, 4.0]
    h9_roller_duration_cutoffs = [45, 60, 90]
    h4_intensity_thresholds = [20000, 30000, 50000]

    combos = list(
        itertools.product(
            single_source_penalties,
            rescue_score_surpluses,
            rescue_terrain_gates,
            persistence_strong_thresholds,
            h3_terrain_vert_multipliers,
            h9_roller_duration_cutoffs,
            h4_intensity_thresholds,
        )
    )
    print(f"  Parameter combinations: {len(combos)}")
    est_time_s = len(combos) * 0.15
    print(f"  Estimated time: ~{est_time_s / 60:.0f} minutes (at 0.15s/combo)")

    sweep_id = str(uuid4())[:8]
    print(f"  Sweep ID: {sweep_id}")
    if split:
        print(f"  Split: {split}")
    print()

    results: List[Dict] = []
    t0 = time.time()

    for combo_idx, (ssp, rss, rtg, pst, h3vm, h9dc, h4it) in enumerate(combos):
        if (combo_idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (combo_idx + 1) / max(1, elapsed)
            remaining = (len(combos) - combo_idx - 1) / max(0.01, rate)
            print(
                f"  [{combo_idx + 1}/{len(combos)}] "
                f"({elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining)"
            )

        total_matched = 0
        total_missed = 0
        total_extras = 0

        for ride in ride_caches:
            m, mi, ex = _score_ride_with_params(
                ride,
                single_source_penalty=ssp,
                rescue_score_surplus=rss,
                rescue_terrain_gate=rtg,
                persistence_strong_threshold=pst,
                h3_terrain_vert_multiplier=h3vm,
                h9_roller_duration_cutoff=h9dc,
                h4_intensity_threshold=h4it,
                frequency_map=frequency_map,
            )
            total_matched += m
            total_missed += mi
            total_extras += ex

        total_expected = total_matched + total_missed
        total_detected = total_matched + total_extras
        precision = total_matched / total_detected if total_detected > 0 else 1.0
        recall = total_matched / total_expected if total_expected > 0 else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        row = {
            "sweep_id": sweep_id,
            "single_source_penalty": ssp,
            "rescue_score_surplus": rss,
            "rescue_terrain_gate": rtg,
            "persistence_strong_threshold": pst,
            "h3_terrain_vert_multiplier": h3vm,
            "h9_roller_duration_cutoff": h9dc,
            "h4_intensity_threshold": h4it,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "matched": total_matched,
            "missed": total_missed,
            "extras": total_extras,
            "total_segments": total_expected,
            "total_detected": total_detected,
        }
        results.append(row)

        if _sweep_results_writable:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO sweep_results
                       (sweep_id, single_source_penalty, rescue_score_surplus,
                        rescue_terrain_gate, persistence_strong_threshold,
                        h3_terrain_vert_multiplier, h9_roller_duration_cutoff,
                        h4_intensity_threshold,
                        precision, recall, f1, matched, missed, extras,
                        total_segments, total_detected)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sweep_id,
                        ssp,
                        rss,
                        rtg,
                        pst,
                        h3vm,
                        h9dc,
                        h4it,
                        round(precision, 6),
                        round(recall, 6),
                        round(f1, 6),
                        total_matched,
                        total_missed,
                        total_extras,
                        total_expected,
                        total_detected,
                    ),
                )
            except sqlite3.OperationalError:
                _sweep_results_writable = False

    if _sweep_results_writable:
        try:
            conn.commit()
        except sqlite3.OperationalError:
            pass
    elapsed = time.time() - t0
    print(f"Sweep complete in {elapsed:.1f}s ({len(combos)} combos, {elapsed/len(combos):.2f}s/combo)")

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print()
    _print_report(results, split=split)
    _write_csv(results, sweep_id)

    conn.close()


def _fmt_row(r: Dict) -> str:
    """Format a single result row for the report table."""
    return (
        f"  {r['single_source_penalty']:5.2f}  {r['rescue_score_surplus']:5.2f}  "
        f"{r['rescue_terrain_gate']:3d}  {r['persistence_strong_threshold']:5.1f}  "
        f"{r['h3_terrain_vert_multiplier']:4.1f}  {r['h9_roller_duration_cutoff']:3d}  "
        f"{r['h4_intensity_threshold']:6d}  "
        f"{r['precision']:6.3f}  {r['recall']:6.3f}  {r['f1']:6.3f}  "
        f"{r['matched']:5d}  {r['missed']:5d}  {r['extras']:5d}"
    )


def _print_report(results: List[Dict], split: Optional[str] = None) -> None:
    """Print sweep results summary."""
    sep = "=" * 120
    header = (
        f"  {'SSP':>5s}  {'RSS':>5s}  {'RTG':>3s}  {'PST':>5s}  "
        f"{'H3V':>4s}  {'H9D':>3s}  {'H4I':>6s}  "
        f"{'P':>6s}  {'R':>6s}  {'F1':>6s}  "
        f"{'match':>5s}  {'miss':>5s}  {'extra':>5s}"
    )

    split_label = f" ({split} set)" if split else ""

    # 1. Top 10 by F1
    print(sep)
    print(f"TOP 10 COMBINATIONS BY F1{split_label}")
    print(sep)
    by_f1 = sorted(results, key=lambda r: r["f1"], reverse=True)
    print(header)
    for r in by_f1[:10]:
        print(_fmt_row(r))

    # 2. Top 10 by recall (with P >= 75%)
    print()
    print(sep)
    print(f"TOP 10 COMBINATIONS BY RECALL (with precision >= 75%){split_label}")
    print(sep)
    high_p = [r for r in results if r["precision"] >= 0.75]
    by_recall = sorted(high_p, key=lambda r: r["recall"], reverse=True)
    print(header)
    for r in by_recall[:10]:
        print(_fmt_row(r))
    if not by_recall:
        print("  (no combinations meet precision >= 75%)")

    # 3. Pareto frontier
    print()
    print(sep)
    print(f"PARETO FRONTIER (no other combo has BOTH higher P and higher R){split_label}")
    print(sep)
    pareto = _compute_pareto(results)
    print(header)
    for r in pareto:
        print(_fmt_row(r))

    # 4. Current production baseline
    # Production defaults — see docs/DETECTOR_PARAMS.md for canonical values
    # SSP=0.75, RSS=0.50, RTG=1, PST=25, H3V=2.0, H9D=90, H4I=50000
    print()
    print(sep)
    print(f"CURRENT PRODUCTION BASELINE (SSP=0.75, RSS=0.50, RTG=1, PST=25, H3V=2.0, H9D=90, H4I=50000){split_label}")
    print(sep)
    baseline = [
        r
        for r in results
        if (
            r["single_source_penalty"] == 0.75
            and r["rescue_score_surplus"] == 0.50
            and r["rescue_terrain_gate"] == 1
            and r["persistence_strong_threshold"] == 25.0
            and r["h3_terrain_vert_multiplier"] == 2.0
            and r["h9_roller_duration_cutoff"] == 90
            and r["h4_intensity_threshold"] == 50000
        )
    ]
    if baseline:
        r = baseline[0]
        print(
            f"  P={r['precision']:.3f}  R={r['recall']:.3f}  F1={r['f1']:.3f}  "
            f"matched={r['matched']}  missed={r['missed']}  extras={r['extras']}"
        )
    else:
        print("  (not found in sweep grid -- closest production params not included?)")

    # 5. Parameter shift analysis
    print()
    print(sep)
    print("PARAMETER SHIFT ANALYSIS")
    print(sep)
    if by_f1:
        best = by_f1[0]
        print(f"  Best F1 combo:  SSP={best['single_source_penalty']:.2f}  "
              f"RSS={best['rescue_score_surplus']:.2f}  "
              f"RTG={best['rescue_terrain_gate']}  "
              f"PST={best['persistence_strong_threshold']:.0f}  "
              f"H3V={best['h3_terrain_vert_multiplier']:.1f}  "
              f"H9D={best['h9_roller_duration_cutoff']}  "
              f"H4I={best['h4_intensity_threshold']}")
        print(f"  Production:     SSP=0.75  RSS=0.50  RTG=1  PST=25  H3V=2.0  H9D=90  H4I=50000")
        shifts = []
        if best["single_source_penalty"] != 0.75:
            shifts.append(f"SSP shifted from 0.75 to {best['single_source_penalty']:.2f}")
        if best["rescue_score_surplus"] != 0.50:
            shifts.append(f"RSS shifted from 0.50 to {best['rescue_score_surplus']:.2f}")
        if best["rescue_terrain_gate"] != 1:
            shifts.append(f"RTG shifted from 1 to {best['rescue_terrain_gate']}")
        if best["persistence_strong_threshold"] != 25.0:
            shifts.append(f"PST shifted from 25 to {best['persistence_strong_threshold']:.0f}")
        if best["h3_terrain_vert_multiplier"] != 2.0:
            shifts.append(f"H3V shifted from 2.0 to {best['h3_terrain_vert_multiplier']:.1f}")
        if best["h9_roller_duration_cutoff"] != 90:
            shifts.append(f"H9D shifted from 90 to {best['h9_roller_duration_cutoff']}")
        if best["h4_intensity_threshold"] != 50000:
            shifts.append(f"H4I shifted from 50000 to {best['h4_intensity_threshold']}")
        if shifts:
            for s in shifts:
                print(f"  * {s}")
        else:
            print("  (no shifts from production defaults)")

    print()


def _compute_pareto(results: List[Dict]) -> List[Dict]:
    """Compute the Pareto frontier: points where no other point dominates on both P and R."""
    pareto = []
    for r in results:
        dominated = False
        for other in results:
            if (
                other["precision"] > r["precision"]
                and other["recall"] > r["recall"]
            ):
                dominated = True
                break
        if not dominated:
            pareto.append(r)

    # Sort by recall ascending for readability
    return sorted(pareto, key=lambda r: r["recall"])


def _write_csv(results: List[Dict], sweep_id: str) -> None:
    """Write full results to CSV for heatmap analysis."""
    csv_path = Path(__file__).parent / f"sweep_results_{sweep_id}.csv"
    fieldnames = [
        "single_source_penalty",
        "rescue_score_surplus",
        "rescue_terrain_gate",
        "persistence_strong_threshold",
        "h3_terrain_vert_multiplier",
        "h9_roller_duration_cutoff",
        "h4_intensity_threshold",
        "precision",
        "recall",
        "f1",
        "matched",
        "missed",
        "extras",
        "total_segments",
        "total_detected",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r[k] for k in fieldnames})
    print(f"Full results written to {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Parameter sweep for canonical_v2 chooser weights"
    )
    parser.add_argument(
        "--db", default=str(GOLDEN_DB), help="Golden corpus DB path"
    )
    parser.add_argument(
        "--cache-proposals",
        action="store_true",
        help="Phase 1: Run detectors and cache proposals (slow)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Drop and rebuild cached_proposals table (use with --cache-proposals)",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Phase 2: Sweep chooser parameters (fast)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Use only the first N rides (0 = all)",
    )
    parser.add_argument(
        "--split",
        type=str,
        default=None,
        choices=["train", "eval"],
        help="Only sweep on rides in this split (requires ride_split table)",
    )
    args = parser.parse_args()

    if not args.cache_proposals and not args.sweep:
        parser.print_help()
        print("\nSpecify --cache-proposals, --sweep, or both.")
        return

    if args.cache_proposals:
        cache_proposals(args.db, sample=args.sample, rebuild=args.rebuild)

    if args.sweep:
        run_sweep(args.db, sample=args.sample, split=args.split)


if __name__ == "__main__":
    main()
