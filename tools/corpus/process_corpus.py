#!/usr/bin/env python3
"""
Batch-process a Strava export corpus through the V2 climb detection pipeline.

Produces a SQLite database with all rides, climbs, terrain cells, and signatures
for offline development without needing the full web stack.

Usage:
    cd backend && source venv/bin/activate
    python ../tools/corpus/process_corpus.py /path/to/export_440100/activities

Options:
    --db PATH          Output SQLite path (default: corpus.db in script dir)
    --workers N        Thread pool size (default: CPU count)
    --limit N          Process only first N files (for testing)
    --rides-only       Skip climb detection (just parse + metrics)
    --ftp N            FTP for TSS calculation (default: 250)
    --weight N         Rider weight in kg (default: 75)
    --resume           Skip files already in the DB
    --csv PATH         Also read Strava activities.csv for metadata enrichment
    --v1               Also run V1 adaptive detector for comparison
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── workout_parse import ─────────────────────────────────────────────

try:
    import workout_parse as wp
except ImportError:
    print("ERROR: workout_parse not available. Build it first:")
    print("  cd workout-parse && cargo build --release && maturin develop")
    sys.exit(1)


# ── Schema ───────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS rides (
    activity_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_format TEXT,          -- fit, gpx, tcx
    sport TEXT,
    device TEXT,
    started_at_ms INTEGER,
    duration_s REAL,
    moving_time_s REAL,
    distance_m REAL,
    elevation_gain_m REAL,
    avg_power_w REAL,
    max_power_w REAL,
    normalized_power_w REAL,
    tss REAL,
    intensity_factor REAL,
    kcals REAL,
    avg_hr_bpm REAL,
    max_hr_bpm REAL,
    avg_speed_mps REAL,
    max_speed_mps REAL,
    avg_cadence_rpm REAL,
    n_samples INTEGER,
    has_gps BOOLEAN,
    has_elevation BOOLEAN,
    has_power BOOLEAN,
    has_hr BOOLEAN,
    elev_min_m REAL,
    elev_max_m REAL,
    terrain_class TEXT,
    terrain_confidence REAL,
    -- Strava CSV enrichment
    strava_name TEXT,
    strava_type TEXT,
    strava_date TEXT,
    strava_elev_gain REAL,
    strava_distance REAL,
    parse_error TEXT,
    processed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS climbs_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL REFERENCES rides(activity_id),
    ordinal INTEGER,           -- climb index within ride
    vert_m REAL,
    time_s INTEGER,
    distance_m REAL,
    avg_gradient_pct REAL,
    persistence REAL,
    is_essential BOOLEAN,
    birth_elev REAL,
    death_elev REAL,
    avg_power_w REAL,
    avg_hr REAL,
    birth_idx INTEGER,
    death_idx INTEGER,
    effort_start_idx INTEGER,
    effort_end_idx INTEGER,
    signature_v1_hex TEXT,
    signature_v2_hex TEXT,
    n_tiles INTEGER,
    start_lat REAL,
    start_lon REAL,
    end_lat REAL,
    end_lon REAL,
    h3_anchor TEXT             -- res-5 H3 cell at midpoint
);

CREATE TABLE IF NOT EXISTS climbs_v1 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id TEXT NOT NULL REFERENCES rides(activity_id),
    terrain_mode TEXT,         -- auto, flat, rolling, etc.
    ordinal INTEGER,
    vert_m REAL,
    time_s INTEGER,
    distance_m REAL,
    avg_gradient_pct REAL,
    avg_power_w REAL,
    avg_hr INTEGER,
    start_offset_s INTEGER,
    end_offset_s INTEGER,
    signature_hex TEXT,
    vam REAL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS h3_cells (
    h3_index TEXT NOT NULL,
    activity_id TEXT NOT NULL REFERENCES rides(activity_id),
    visit_order INTEGER,
    PRIMARY KEY (h3_index, activity_id)
);

CREATE TABLE IF NOT EXISTS signatures (
    signature_hex TEXT PRIMARY KEY,
    version INTEGER,           -- 1 or 2
    first_seen_activity TEXT,
    n_occurrences INTEGER DEFAULT 1,
    avg_vert_m REAL,
    avg_gradient_pct REAL,
    avg_persistence REAL,
    representative_lat REAL,
    representative_lon REAL,
    h3_anchor TEXT
);

CREATE TABLE IF NOT EXISTS corpus_stats (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_climbs_v2_activity ON climbs_v2(activity_id);
CREATE INDEX IF NOT EXISTS idx_climbs_v2_sig ON climbs_v2(signature_v2_hex);
CREATE INDEX IF NOT EXISTS idx_climbs_v2_vert ON climbs_v2(vert_m DESC);
CREATE INDEX IF NOT EXISTS idx_climbs_v2_persistence ON climbs_v2(persistence DESC);
CREATE INDEX IF NOT EXISTS idx_climbs_v1_activity ON climbs_v1(activity_id);
CREATE INDEX IF NOT EXISTS idx_h3_activity ON h3_cells(activity_id);
CREATE INDEX IF NOT EXISTS idx_h3_index ON h3_cells(h3_index);
CREATE INDEX IF NOT EXISTS idx_rides_terrain ON rides(terrain_class);
CREATE INDEX IF NOT EXISTS idx_rides_elev ON rides(elevation_gain_m DESC);
"""


# ── Helpers ──────────────────────────────────────────────────────────

@dataclass
class RideResult:
    activity_id: str
    filename: str
    ride_row: dict
    climbs_v2: list = field(default_factory=list)
    climbs_v1: list = field(default_factory=list)
    h3_cells: list = field(default_factory=list)
    error: Optional[str] = None


def activity_id_from_filename(filename: str) -> str:
    """Extract activity ID from Strava export filename like '10041981689.fit.gz'."""
    return Path(filename).name.split(".")[0]


def parse_and_process(filepath: str, ftp: int, weight_kg: float, run_v1: bool) -> RideResult:
    """Parse a single ride file and detect climbs. Thread-safe (Rust releases GIL)."""
    filename = os.path.basename(filepath)
    activity_id = activity_id_from_filename(filename)

    # Determine format
    lower = filename.lower()
    if ".fit" in lower:
        file_format = "fit"
    elif ".gpx" in lower:
        file_format = "gpx"
    elif ".tcx" in lower:
        file_format = "tcx"
    else:
        file_format = "unknown"

    result = RideResult(
        activity_id=activity_id,
        filename=filename,
        ride_row={"activity_id": activity_id, "filename": filename, "file_format": file_format},
    )

    try:
        # Parse
        activity = wp.parse_file(filepath)
        n = len(activity.time_ms)
        if n == 0:
            result.error = "empty activity (0 samples)"
            result.ride_row["parse_error"] = result.error
            return result

        # Metrics
        metrics = wp.compute_metrics(activity, ftp)

        result.ride_row.update({
            "sport": str(activity.sport) if activity.sport else None,
            "device": str(activity.device_name) if activity.device_name else None,
            "started_at_ms": int(activity.started_at_ms) if activity.started_at_ms else None,
            "duration_s": metrics.duration_s,
            "moving_time_s": metrics.moving_time_s,
            "distance_m": metrics.distance_m,
            "elevation_gain_m": metrics.elevation_gain_m,
            "avg_power_w": metrics.avg_power_w,
            "max_power_w": metrics.max_power_w,
            "normalized_power_w": metrics.normalized_power_w,
            "tss": metrics.tss,
            "intensity_factor": metrics.intensity_factor,
            "kcals": metrics.kcals,
            "avg_hr_bpm": metrics.avg_hr_bpm,
            "max_hr_bpm": metrics.max_hr_bpm,
            "avg_speed_mps": metrics.avg_speed_mps,
            "max_speed_mps": metrics.max_speed_mps,
            "avg_cadence_rpm": metrics.avg_cadence_rpm,
            "n_samples": n,
            "has_gps": activity.lat_e7 is not None and len(activity.lat_e7) > 0,
            "has_elevation": activity.elevation_m is not None and len(activity.elevation_m) > 0,
            "has_power": activity.pwr_w is not None and len(activity.pwr_w) > 0,
            "has_hr": activity.hr_bpm is not None and len(activity.hr_bpm) > 0,
        })

        # Elevation stats: use Rust-computed gain (SMA-21 smoothed, matches Strava)
        if metrics.elevation_gain_m and metrics.elevation_gain_m > 0:
            result.ride_row["elevation_gain_m"] = metrics.elevation_gain_m
        if activity.elevation_m is not None and len(activity.elevation_m) > 0:
            elev = [float(e) for e in activity.elevation_m if e > -500]
            if elev:
                result.ride_row["elev_min_m"] = min(elev)
                result.ride_row["elev_max_m"] = max(elev)

        # H3 tiles (compute early so they can be included in tile_samples)
        h3_strs = None
        if activity.lat_e7 is not None and len(activity.lat_e7) > 0:
            try:
                h3_strs = wp.get_h3_strings(activity.lat_e7, activity.lon_e7, 10)
                for i, h in enumerate(h3_strs):
                    result.h3_cells.append({"h3_index": h, "activity_id": activity_id, "visit_order": i})
            except Exception:
                pass

        # Terrain classification
        try:
            samples = _to_tile_samples(activity, h3_strs)
            tc = wp.classify_terrain(samples)
            if tc:
                result.ride_row["terrain_class"] = tc.class_name
                result.ride_row["terrain_confidence"] = tc.confidence
        except Exception:
            pass

        # V2 climb detection (persistence)
        if activity.elevation_m is not None and len(activity.elevation_m) > 0:
            samples = _to_tile_samples(activity, h3_strs)
            try:
                climbs = wp.detect_climbs_persistence(samples, user_weight_kg=weight_kg)
                for i, c in enumerate(climbs):
                    row = {
                        "activity_id": activity_id,
                        "ordinal": i,
                        "vert_m": c.vert_m,
                        "time_s": c.time_s,
                        "distance_m": c.distance_m,
                        "avg_gradient_pct": c.avg_gradient_pct,
                        "persistence": c.persistence,
                        "is_essential": c.is_essential,
                        "birth_elev": c.birth_elev,
                        "death_elev": c.death_elev,
                        "avg_power_w": c.avg_power_w,
                        "avg_hr": c.avg_hr,
                        "birth_idx": c.birth_idx,
                        "death_idx": c.death_idx,
                        "effort_start_idx": c.effort_start_idx,
                        "effort_end_idx": c.effort_end_idx,
                        "signature_v1_hex": c.signature_v1_hex,
                        "signature_v2_hex": c.signature_v2_hex,
                        "n_tiles": len(c.tile_ids) if c.tile_ids else 0,
                    }
                    # Extract start/end GPS (validate to reject FIT SDK sentinels
                    # like -214.748° from INT32_MIN and Null Island 0,0)
                    if activity.lat_e7 is not None:
                        si, ei = c.effort_start_idx or 0, c.effort_end_idx or (n - 1)
                        si = min(si, len(activity.lat_e7) - 1)
                        ei = min(ei, len(activity.lat_e7) - 1)
                        slat = float(activity.lat_e7[si]) / 1e7
                        slon = float(activity.lon_e7[si]) / 1e7
                        elat = float(activity.lat_e7[ei]) / 1e7
                        elon = float(activity.lon_e7[ei]) / 1e7
                        if abs(slat) <= 90 and abs(slon) <= 180 and not (slat == 0 and slon == 0):
                            row["start_lat"] = slat
                            row["start_lon"] = slon
                        if abs(elat) <= 90 and abs(elon) <= 180 and not (elat == 0 and elon == 0):
                            row["end_lat"] = elat
                            row["end_lon"] = elon
                        # H3 anchor at midpoint
                        mi = (si + ei) // 2
                        try:
                            mid_cells = wp.get_h3_strings(
                                activity.lat_e7[mi : mi + 1],
                                activity.lon_e7[mi : mi + 1],
                                5,
                            )
                            if mid_cells:
                                row["h3_anchor"] = mid_cells[0]
                        except Exception:
                            pass
                    result.climbs_v2.append(row)
            except Exception as e:
                result.ride_row["parse_error"] = f"v2 detect failed: {e}"

        # V1 climb detection (optional comparison)
        if run_v1 and activity.elevation_m is not None and len(activity.elevation_m) > 0:
            samples = _to_tile_samples(activity, h3_strs)
            for terrain in ["auto", "hilly"]:
                try:
                    v1_climbs = wp.detect_climbs_adaptive(
                        tile_samples=samples,
                        terrain=terrain,
                        user_weight_kg=weight_kg,
                        algorithm="momentum",
                        generate_signatures=True,
                    )
                    for i, c in enumerate(v1_climbs):
                        result.climbs_v1.append({
                            "activity_id": activity_id,
                            "terrain_mode": terrain,
                            "ordinal": i,
                            "vert_m": round(c.vert_m, 1),
                            "time_s": c.time_s,
                            "distance_m": round(c.distance_m, 0) if c.distance_m else None,
                            "avg_gradient_pct": round(c.avg_gradient_pct, 1) if c.avg_gradient_pct else None,
                            "avg_power_w": round(c.avg_power_w, 1) if c.avg_power_w else None,
                            "avg_hr": c.avg_hr,
                            "start_offset_s": c.start_time_offset_s,
                            "end_offset_s": c.end_time_offset_s,
                            "signature_hex": c.signature_hex,
                            "vam": round(c.vert_m / c.time_s * 3600, 0) if c.time_s > 0 else 0,
                            "category": c.category if hasattr(c, "category") else None,
                        })
                except Exception:
                    pass

    except Exception as e:
        result.error = str(e)
        result.ride_row["parse_error"] = str(e)

    return result


def _to_tile_samples(activity, h3_strings=None) -> list:
    """Convert ParsedActivity to tile_samples dicts."""
    n = len(activity.time_ms)
    start_ms = activity.time_ms[0]
    samples = []
    for i in range(n):
        s = {"t": int((activity.time_ms[i] - start_ms) / 1000)}
        if activity.elevation_m is not None and i < len(activity.elevation_m):
            s["elevation_m"] = float(activity.elevation_m[i])
        if activity.lat_e7 is not None and i < len(activity.lat_e7):
            s["lat"] = float(activity.lat_e7[i]) / 1e7
            s["lon"] = float(activity.lon_e7[i]) / 1e7
        if activity.pwr_w is not None and i < len(activity.pwr_w):
            pw = int(activity.pwr_w[i])
            if 0 < pw < 5000:
                s["power_w"] = pw
        if activity.hr_bpm is not None and i < len(activity.hr_bpm):
            hr = int(activity.hr_bpm[i])
            if 0 < hr < 255:
                s["hr_bpm"] = hr
        if h3_strings is not None and i < len(h3_strings):
            s["tile_id"] = h3_strings[i]
        samples.append(s)
    return samples


# ── DB writes ────────────────────────────────────────────────────────

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def write_result(conn: sqlite3.Connection, result: RideResult):
    """Write a single ride's results to SQLite."""
    row = result.ride_row
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_names = ",".join(cols)
    conn.execute(
        f"INSERT OR REPLACE INTO rides ({col_names}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )

    # Delete old climbs before re-inserting (prevents duplication on re-runs)
    conn.execute("DELETE FROM climbs_v2 WHERE activity_id=?", (result.activity_id,))
    conn.execute("DELETE FROM climbs_v1 WHERE activity_id=?", (result.activity_id,))

    for climb in result.climbs_v2:
        cols = list(climb.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        conn.execute(
            f"INSERT INTO climbs_v2 ({col_names}) VALUES ({placeholders})",
            [climb.get(c) for c in cols],
        )

    for climb in result.climbs_v1:
        cols = list(climb.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_names = ",".join(cols)
        conn.execute(
            f"INSERT INTO climbs_v1 ({col_names}) VALUES ({placeholders})",
            [climb.get(c) for c in cols],
        )

    # Batch insert H3 cells
    if result.h3_cells:
        conn.executemany(
            "INSERT OR IGNORE INTO h3_cells (h3_index, activity_id, visit_order) VALUES (?,?,?)",
            [(c["h3_index"], c["activity_id"], c["visit_order"]) for c in result.h3_cells],
        )

    # Update signature dedup table
    for climb in result.climbs_v2:
        sig = climb.get("signature_v2_hex")
        if not sig:
            continue
        existing = conn.execute("SELECT n_occurrences, avg_vert_m FROM signatures WHERE signature_hex=?", (sig,)).fetchone()
        if existing:
            n = existing[0] + 1
            avg_v = (existing[1] * existing[0] + (climb.get("vert_m") or 0)) / n
            conn.execute(
                "UPDATE signatures SET n_occurrences=?, avg_vert_m=? WHERE signature_hex=?",
                (n, avg_v, sig),
            )
        else:
            conn.execute(
                "INSERT INTO signatures (signature_hex, version, first_seen_activity, n_occurrences, avg_vert_m, avg_gradient_pct, avg_persistence, representative_lat, representative_lon, h3_anchor) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sig, 2, result.activity_id, 1, climb.get("vert_m"), climb.get("avg_gradient_pct"), climb.get("persistence"), climb.get("start_lat"), climb.get("start_lon"), climb.get("h3_anchor")),
            )


def enrich_from_csv(conn: sqlite3.Connection, csv_path: str):
    """Enrich ride rows with Strava metadata from activities.csv."""
    import csv

    count = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("Activity ID", "").strip()
            if not aid:
                continue
            conn.execute(
                "UPDATE rides SET strava_name=?, strava_type=?, strava_date=?, strava_elev_gain=?, strava_distance=? WHERE activity_id=?",
                (
                    row.get("Activity Name"),
                    row.get("Activity Type"),
                    row.get("Activity Date"),
                    float(row["Elevation Gain"]) if row.get("Elevation Gain") else None,
                    float(row["Distance"]) if row.get("Distance") else None,
                    aid,
                ),
            )
            count += 1
    conn.commit()
    return count


def write_corpus_stats(conn: sqlite3.Connection, elapsed_s: float):
    """Write aggregate stats to corpus_stats table."""
    stats = {}

    for key, query in [
        ("total_rides", "SELECT COUNT(*) FROM rides"),
        ("total_rides_with_power", "SELECT COUNT(*) FROM rides WHERE has_power=1"),
        ("total_rides_with_gps", "SELECT COUNT(*) FROM rides WHERE has_gps=1"),
        ("total_rides_with_elevation", "SELECT COUNT(*) FROM rides WHERE has_elevation=1"),
        ("total_distance_km", "SELECT COALESCE(SUM(distance_m)/1000, 0) FROM rides"),
        ("total_elevation_m", "SELECT COALESCE(SUM(elevation_gain_m), 0) FROM rides"),
        ("total_climbs_v2", "SELECT COUNT(*) FROM climbs_v2"),
        ("total_climbs_v2_significant", "SELECT COUNT(*) FROM climbs_v2 WHERE vert_m >= 20"),
        ("total_unique_signatures_v2", "SELECT COUNT(DISTINCT signature_v2_hex) FROM climbs_v2 WHERE signature_v2_hex IS NOT NULL"),
        ("total_unique_h3_cells", "SELECT COUNT(DISTINCT h3_index) FROM h3_cells"),
        ("total_parse_errors", "SELECT COUNT(*) FROM rides WHERE parse_error IS NOT NULL"),
        ("terrain_flat", "SELECT COUNT(*) FROM rides WHERE terrain_class='flat'"),
        ("terrain_rolling", "SELECT COUNT(*) FROM rides WHERE terrain_class='rolling'"),
        ("terrain_hilly", "SELECT COUNT(*) FROM rides WHERE terrain_class='hilly'"),
        ("terrain_mountainous", "SELECT COUNT(*) FROM rides WHERE terrain_class='mountainous'"),
    ]:
        row = conn.execute(query).fetchone()
        stats[key] = str(row[0]) if row else "0"

    stats["processing_time_s"] = f"{elapsed_s:.1f}"

    for k, v in stats.items():
        conn.execute("INSERT OR REPLACE INTO corpus_stats (key, value) VALUES (?,?)", (k, v))
    conn.commit()
    return stats


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Process Strava export corpus through V2 climb detection")
    parser.add_argument("activities_dir", help="Path to activities/ directory from Strava export")
    parser.add_argument("--db", default=None, help="Output SQLite path (default: tools/corpus/corpus.db)")
    parser.add_argument("--workers", type=int, default=None, help="Thread pool size (default: CPU count)")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N files")
    parser.add_argument("--rides-only", action="store_true", help="Skip climb detection")
    parser.add_argument("--ftp", type=int, default=250, help="FTP for TSS (default: 250)")
    parser.add_argument("--weight", type=float, default=75.0, help="Rider weight kg (default: 75)")
    parser.add_argument("--resume", action="store_true", help="Skip files already in DB")
    parser.add_argument("--csv", default=None, help="Path to activities.csv for metadata enrichment")
    parser.add_argument("--v1", action="store_true", help="Also run V1 detector for comparison")
    args = parser.parse_args()

    activities_dir = Path(args.activities_dir)
    if not activities_dir.is_dir():
        print(f"ERROR: {activities_dir} is not a directory")
        sys.exit(1)

    db_path = args.db or str(Path(__file__).parent / "corpus.db")
    workers = args.workers or min(os.cpu_count() or 4, 6)

    # Discover files
    all_files = sorted(activities_dir.iterdir())
    ride_files = [
        f for f in all_files
        if f.name.endswith((".fit", ".fit.gz", ".gpx", ".gpx.gz", ".tcx", ".tcx.gz"))
        and not f.name.startswith(".")
    ]

    if args.limit:
        ride_files = ride_files[: args.limit]

    print(f"Corpus: {len(ride_files)} ride files in {activities_dir}")
    print(f"Output: {db_path}")
    print(f"Workers: {workers}, FTP: {args.ftp}W, Weight: {args.weight}kg")
    if args.v1:
        print(f"V1 comparison: enabled (auto + hilly)")
    print()

    # Init DB
    conn = init_db(db_path)

    # Resume support
    if args.resume:
        existing = set(
            row[0] for row in conn.execute("SELECT activity_id FROM rides").fetchall()
        )
        before = len(ride_files)
        ride_files = [f for f in ride_files if activity_id_from_filename(f.name) not in existing]
        print(f"Resume: {before - len(ride_files)} already processed, {len(ride_files)} remaining")

    if not ride_files:
        print("Nothing to process.")
        # Still write stats and enrich
        if args.csv:
            enrich_from_csv(conn, args.csv)
        conn.close()
        return

    # Process
    t0 = time.time()
    done = 0
    errors = 0
    total_climbs = 0
    batch = []
    batch_size = 50  # commit every N rides

    def flush_batch():
        nonlocal batch
        for r in batch:
            write_result(conn, r)
        conn.commit()
        batch = []

    file_timeout = 120  # seconds per file

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(parse_and_process, str(f), args.ftp, args.weight, args.v1): f
            for f in ride_files
        }

        for future in as_completed(futures):
            filepath = futures[future]
            try:
                result = future.result(timeout=file_timeout)
            except TimeoutError:
                errors += 1
                done += 1
                print(f"\r  TIMEOUT: {filepath.name} (>{file_timeout}s)")
                continue
            except Exception as e:
                errors += 1
                done += 1
                print(f"\r  CRASH: {filepath.name}: {e}")
                continue

            done += 1
            if result.error:
                errors += 1

            n_climbs = len(result.climbs_v2)
            total_climbs += n_climbs
            batch.append(result)

            if len(batch) >= batch_size:
                flush_batch()

            # Progress
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(ride_files) - done) / rate if rate > 0 else 0
            err_pct = errors / done * 100 if done > 0 else 0
            print(
                f"\r  [{done}/{len(ride_files)}] "
                f"{rate:.1f} rides/s | "
                f"{total_climbs} climbs | "
                f"{errors} errors ({err_pct:.1f}%) | "
                f"ETA {eta:.0f}s   ",
                end="",
                flush=True,
            )

    # Flush remaining
    flush_batch()
    elapsed = time.time() - t0
    print()
    print()

    # Enrich from CSV
    if args.csv:
        csv_path = args.csv
        if not os.path.exists(csv_path):
            # Try relative to activities dir parent
            csv_path = str(activities_dir.parent / "activities.csv")
        if os.path.exists(csv_path):
            n_enriched = enrich_from_csv(conn, csv_path)
            print(f"Enriched {n_enriched} rides from activities.csv")
        else:
            print(f"WARNING: CSV not found at {args.csv}")

    # Stats
    stats = write_corpus_stats(conn, elapsed)
    conn.close()

    print()
    print("=" * 60)
    print("CORPUS PROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Rides processed:    {stats['total_rides']}")
    print(f"  Parse errors:       {stats['total_parse_errors']}")
    print(f"  Distance:           {float(stats['total_distance_km']):,.0f} km")
    print(f"  Elevation:          {float(stats['total_elevation_m']):,.0f} m")
    print(f"  V2 climbs:          {stats['total_climbs_v2']}")
    print(f"  Significant (≥20m): {stats['total_climbs_v2_significant']}")
    print(f"  Unique V2 sigs:     {stats['total_unique_signatures_v2']}")
    print(f"  Unique H3 cells:    {stats['total_unique_h3_cells']}")
    print(f"  Terrain: flat={stats['terrain_flat']} rolling={stats['terrain_rolling']} hilly={stats['terrain_hilly']} mountainous={stats['terrain_mountainous']}")
    print(f"  Time:               {elapsed:.1f}s ({float(stats['total_rides'])/elapsed:.1f} rides/s)")
    print(f"  DB:                 {db_path}")


if __name__ == "__main__":
    main()
