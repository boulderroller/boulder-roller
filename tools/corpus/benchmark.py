#!/usr/bin/env python3
"""
Corpus Benchmark Scorecard Generator (Tier 3).

Reads the frozen corpus.db and produces a machine-comparable JSON scorecard
with detection, signature, quality, and terrain metrics. Supports delta
comparison against a previous scorecard to detect drift.

Usage:
    # Generate scorecard
    python tools/corpus/benchmark.py

    # Generate and compare to previous
    python tools/corpus/benchmark.py --compare-to scorecards/2026-02-25.json

    # Save scorecard to file
    python tools/corpus/benchmark.py --output scorecards/2026-02-27.json

    # Use alternate DB
    python tools/corpus/benchmark.py --db tools/corpus/corpus_pre_quality_filters.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = str(Path(__file__).parent / "corpus.db")
SCORECARD_DIR = Path(__file__).parent / "scorecards"

# Hard quality gates — if any of these fail, the benchmark FAILS.
QUALITY_GATES = {
    "zero_distance_count": 0,
    "impossible_vam_count": 0,
    "sub_5m_count": 0,
}

# Drift thresholds — deltas above these on key metrics require justification.
DRIFT_THRESHOLD_PCT = 5.0


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_workout_parse_version() -> str:
    try:
        import workout_parse as wp
        return getattr(wp, "__version__", "unknown")
    except ImportError:
        return "not_installed"


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def compute_detection_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Core climb detection metrics."""
    row = conn.execute("""
        SELECT
            COUNT(*) as total_climbs,
            SUM(CASE WHEN vert_m >= 20 THEN 1 ELSE 0 END) as significant_climbs,
            SUM(CASE WHEN is_essential THEN 1 ELSE 0 END) as essential_count,
            AVG(vert_m) as mean_vert_m,
            SUM(CASE WHEN vert_m < 5 THEN 1 ELSE 0 END) as sub_5m_count,
            SUM(CASE WHEN distance_m IS NULL OR distance_m = 0 THEN 1 ELSE 0 END) as zero_distance_count,
            MAX(vert_m) as max_vert_m,
            MIN(vert_m) as min_vert_m
        FROM climbs_v2
    """).fetchone()

    total = row["total_climbs"]
    significant = row["significant_climbs"]

    # Median and percentiles via subquery
    median_row = conn.execute("""
        SELECT vert_m FROM climbs_v2 ORDER BY vert_m
        LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM climbs_v2)
    """).fetchone()

    p95_row = conn.execute("""
        SELECT vert_m FROM climbs_v2 ORDER BY vert_m
        LIMIT 1 OFFSET (SELECT CAST(COUNT(*) * 0.95 AS INTEGER) FROM climbs_v2)
    """).fetchone()

    # Impossible VAM check (>2500 m/hr)
    vam_row = conn.execute("""
        SELECT COUNT(*) as n FROM climbs_v2
        WHERE time_s > 0 AND (vert_m / time_s * 3600) > 2500
    """).fetchone()

    # Max climbs per single ride
    max_per_ride = conn.execute("""
        SELECT MAX(cnt) FROM (
            SELECT COUNT(*) as cnt FROM climbs_v2 GROUP BY activity_id
        )
    """).fetchone()[0]

    # Essential percentage (of significant climbs)
    essential_of_significant = conn.execute("""
        SELECT SUM(CASE WHEN is_essential THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
        FROM climbs_v2 WHERE vert_m >= 20
    """).fetchone()[0] or 0.0

    return {
        "total_climbs": total,
        "significant_climbs": significant,
        "essential_count": row["essential_count"],
        "essential_pct": round(essential_of_significant, 1),
        "mean_vert_m": round(row["mean_vert_m"], 1) if row["mean_vert_m"] else 0,
        "median_vert_m": round(median_row["vert_m"], 1) if median_row else 0,
        "p95_vert_m": round(p95_row["vert_m"], 1) if p95_row else 0,
        "max_vert_m": round(row["max_vert_m"], 1) if row["max_vert_m"] else 0,
        "min_vert_m": round(row["min_vert_m"], 1) if row["min_vert_m"] else 0,
        "zero_distance_count": row["zero_distance_count"],
        "impossible_vam_count": vam_row["n"],
        "sub_5m_count": row["sub_5m_count"],
        "max_climbs_per_ride": max_per_ride or 0,
    }


def compute_signature_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Signature generation and uniqueness metrics."""
    unique_v2 = conn.execute(
        "SELECT COUNT(*) FROM signatures WHERE version = 2"
    ).fetchone()[0]

    significant_with_sig = conn.execute("""
        SELECT COUNT(*) FROM climbs_v2
        WHERE vert_m >= 20 AND signature_v2_hex IS NOT NULL
    """).fetchone()[0]

    total_significant = conn.execute(
        "SELECT COUNT(*) FROM climbs_v2 WHERE vert_m >= 20"
    ).fetchone()[0]

    sig_coverage = (significant_with_sig / total_significant * 100) if total_significant > 0 else 0

    # Repeated signatures (same climb ridden multiple times)
    repeated = conn.execute(
        "SELECT COUNT(*) FROM signatures WHERE version = 2 AND n_occurrences > 1"
    ).fetchone()[0]

    most_repeated = conn.execute(
        "SELECT MAX(n_occurrences) FROM signatures WHERE version = 2"
    ).fetchone()[0] or 0

    return {
        "unique_v2_signatures": unique_v2,
        "signature_coverage_pct": round(sig_coverage, 1),
        "repeated_signatures": repeated,
        "most_repeated_count": most_repeated,
    }


def compute_quality_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Data quality and sensor integrity metrics."""
    # GPS coverage across rides
    gps_row = conn.execute("""
        SELECT
            SUM(CASE WHEN has_gps THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as gps_pct,
            SUM(CASE WHEN has_elevation THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as elev_pct,
            SUM(CASE WHEN has_power THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as power_pct,
            SUM(CASE WHEN has_hr THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as hr_pct
        FROM rides
    """).fetchone()

    # Rides with parse errors
    error_count = conn.execute(
        "SELECT COUNT(*) FROM rides WHERE parse_error IS NOT NULL"
    ).fetchone()[0]

    total_rides = conn.execute("SELECT COUNT(*) FROM rides").fetchone()[0]

    # Climbs with GPS coordinates
    climbs_with_gps = conn.execute("""
        SELECT COUNT(*) FROM climbs_v2
        WHERE start_lat IS NOT NULL AND start_lat != 0
    """).fetchone()[0]

    total_climbs = conn.execute("SELECT COUNT(*) FROM climbs_v2").fetchone()[0]

    # Elevation plausibility
    elev_outliers = conn.execute("""
        SELECT COUNT(*) FROM rides
        WHERE elev_max_m > 5500 OR elev_min_m < -500
    """).fetchone()[0]

    return {
        "total_rides": total_rides,
        "gps_coverage_pct": round(gps_row["gps_pct"], 1),
        "elevation_coverage_pct": round(gps_row["elev_pct"], 1),
        "power_coverage_pct": round(gps_row["power_pct"], 1),
        "hr_coverage_pct": round(gps_row["hr_pct"], 1),
        "parse_error_count": error_count,
        "parse_error_pct": round(error_count / total_rides * 100, 2) if total_rides else 0,
        "climbs_with_gps_pct": round(climbs_with_gps / total_climbs * 100, 1) if total_climbs else 0,
        "elevation_outlier_rides": elev_outliers,
    }


def compute_terrain_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Terrain classification distribution."""
    terrain = {}
    for row in conn.execute("""
        SELECT terrain_class, COUNT(*) as n
        FROM rides WHERE terrain_class IS NOT NULL
        GROUP BY terrain_class ORDER BY n DESC
    """):
        terrain[row["terrain_class"]] = row["n"]

    unclassified = conn.execute(
        "SELECT COUNT(*) FROM rides WHERE terrain_class IS NULL"
    ).fetchone()[0]

    # Climbs per terrain class
    climbs_by_terrain = {}
    for row in conn.execute("""
        SELECT r.terrain_class, COUNT(*) as n, AVG(c.vert_m) as avg_vert
        FROM climbs_v2 c JOIN rides r ON c.activity_id = r.activity_id
        WHERE r.terrain_class IS NOT NULL AND c.vert_m >= 20
        GROUP BY r.terrain_class
    """):
        climbs_by_terrain[row["terrain_class"]] = {
            "significant_climbs": row["n"],
            "avg_vert_m": round(row["avg_vert"], 1),
        }

    return {
        "rides_by_terrain": terrain,
        "unclassified_rides": unclassified,
        "significant_climbs_by_terrain": climbs_by_terrain,
    }


def compute_persistence_metrics(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Persistence-specific metrics (topological properties)."""
    row = conn.execute("""
        SELECT
            AVG(persistence) as avg_persistence,
            MIN(persistence) as min_persistence,
            MAX(persistence) as max_persistence
        FROM climbs_v2 WHERE vert_m >= 20
    """).fetchone()

    median_p = conn.execute("""
        SELECT persistence FROM climbs_v2 WHERE vert_m >= 20
        ORDER BY persistence
        LIMIT 1 OFFSET (
            SELECT COUNT(*)/2 FROM climbs_v2 WHERE vert_m >= 20
        )
    """).fetchone()

    # Persistence vs vert correlation (should be high)
    corr_row = conn.execute("""
        SELECT
            AVG(persistence * vert_m) - AVG(persistence) * AVG(vert_m) as cov,
            AVG(persistence * persistence) - AVG(persistence) * AVG(persistence) as var_p,
            AVG(vert_m * vert_m) - AVG(vert_m) * AVG(vert_m) as var_v
        FROM climbs_v2 WHERE vert_m >= 20
    """).fetchone()

    import math
    denom = math.sqrt(corr_row["var_p"] * corr_row["var_v"]) if corr_row["var_p"] and corr_row["var_v"] else 1
    correlation = corr_row["cov"] / denom if denom > 0 else 0

    return {
        "avg_persistence_m": round(row["avg_persistence"], 1) if row["avg_persistence"] else 0,
        "median_persistence_m": round(median_p["persistence"], 1) if median_p else 0,
        "min_persistence_m": round(row["min_persistence"], 1) if row["min_persistence"] else 0,
        "max_persistence_m": round(row["max_persistence"], 1) if row["max_persistence"] else 0,
        "persistence_vert_correlation": round(correlation, 3),
    }


# ---------------------------------------------------------------------------
# Scorecard assembly
# ---------------------------------------------------------------------------

def generate_scorecard(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Generate the full benchmark scorecard."""
    return {
        "version": "benchmark-v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "detector": "persistence",
        "workout_parse_version": get_workout_parse_version(),
        "commit": get_git_commit(),
        "corpus_db": str(Path(conn.execute("PRAGMA database_list").fetchone()[2]).name),
        "metrics": {
            "detection": compute_detection_metrics(conn),
            "signatures": compute_signature_metrics(conn),
            "quality": compute_quality_metrics(conn),
            "terrain": compute_terrain_metrics(conn),
            "persistence": compute_persistence_metrics(conn),
        },
        "quality_gates": {},
    }


def check_quality_gates(scorecard: Dict) -> List[str]:
    """Check hard quality gates. Returns list of failures."""
    failures = []
    detection = scorecard["metrics"]["detection"]

    for key, expected in QUALITY_GATES.items():
        actual = detection.get(key, -1)
        if actual != expected:
            failures.append(f"GATE FAILED: {key} = {actual} (expected {expected})")

    scorecard["quality_gates"] = {
        "passed": len(failures) == 0,
        "checks": {k: detection.get(k, -1) == v for k, v in QUALITY_GATES.items()},
        "failures": failures,
    }

    return failures


# ---------------------------------------------------------------------------
# Delta comparison
# ---------------------------------------------------------------------------

def compute_delta(
    current: Dict[str, Any],
    previous: Dict[str, Any],
) -> Dict[str, str]:
    """Compare two scorecards and return deltas as human-readable strings."""
    delta = {}

    # Flatten nested metrics for comparison
    def flatten(d, prefix=""):
        flat = {}
        for k, v in d.items():
            key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                flat.update(flatten(v, f"{key}."))
            elif isinstance(v, (int, float)):
                flat[key] = v
        return flat

    curr_flat = flatten(current.get("metrics", {}))
    prev_flat = flatten(previous.get("metrics", {}))

    for key in sorted(set(curr_flat) | set(prev_flat)):
        c = curr_flat.get(key)
        p = prev_flat.get(key)

        if c is None or p is None:
            if c is not None:
                delta[key] = f"NEW: {c}"
            elif p is not None:
                delta[key] = f"REMOVED (was {p})"
            continue

        if p == 0:
            if c == 0:
                delta[key] = "0 (unchanged)"
            else:
                delta[key] = f"0 -> {c} (NEW)"
            continue

        diff = c - p
        pct = (diff / abs(p)) * 100

        if abs(pct) < 0.01:
            continue  # Skip unchanged metrics

        sign = "+" if diff > 0 else ""
        delta[key] = f"{sign}{diff} ({sign}{pct:.1f}%)"

    return delta


def find_drift_warnings(delta: Dict[str, str]) -> List[str]:
    """Find metrics that drifted beyond the threshold."""
    warnings = []
    for key, desc in delta.items():
        # Parse percentage from delta string
        if "%" in desc:
            try:
                pct_str = desc.split("(")[1].rstrip("%)")
                pct = abs(float(pct_str))
                if pct >= DRIFT_THRESHOLD_PCT:
                    warnings.append(f"DRIFT: {key}: {desc}")
            except (IndexError, ValueError):
                pass
    return warnings


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_scorecard(scorecard: Dict, delta: Optional[Dict] = None):
    """Print scorecard in human-readable format."""
    print("=" * 70)
    print("  CORPUS BENCHMARK SCORECARD")
    print("=" * 70)
    print(f"  Timestamp:  {scorecard['timestamp']}")
    print(f"  Detector:   {scorecard['detector']}")
    print(f"  Commit:     {scorecard['commit']}")
    print(f"  Corpus:     {scorecard['corpus_db']}")
    print()

    det = scorecard["metrics"]["detection"]
    print("  DETECTION METRICS")
    print(f"    total_climbs:           {det['total_climbs']:>8,d}")
    print(f"    significant_climbs:     {det['significant_climbs']:>8,d}")
    print(f"    essential_count:        {det['essential_count']:>8,d}  ({det['essential_pct']:.1f}% of significant)")
    print(f"    median_vert_m:          {det['median_vert_m']:>8.1f}")
    print(f"    p95_vert_m:             {det['p95_vert_m']:>8.1f}")
    print(f"    max_vert_m:             {det['max_vert_m']:>8.1f}")
    print(f"    max_climbs_per_ride:    {det['max_climbs_per_ride']:>8d}")
    print()
    gate_pass = "PASS" if scorecard["quality_gates"].get("passed", False) else "FAIL"
    print(f"  QUALITY GATES [{gate_pass}]")
    print(f"    zero_distance_count:    {det['zero_distance_count']:>8d}  {'OK' if det['zero_distance_count'] == 0 else 'FAIL'}")
    print(f"    impossible_vam_count:   {det['impossible_vam_count']:>8d}  {'OK' if det['impossible_vam_count'] == 0 else 'FAIL'}")
    print(f"    sub_5m_count:           {det['sub_5m_count']:>8d}  {'OK' if det['sub_5m_count'] == 0 else 'FAIL'}")
    print()

    sig = scorecard["metrics"]["signatures"]
    print("  SIGNATURE METRICS")
    print(f"    unique_v2_signatures:   {sig['unique_v2_signatures']:>8,d}")
    print(f"    signature_coverage_pct: {sig['signature_coverage_pct']:>8.1f}%")
    print(f"    repeated_signatures:    {sig['repeated_signatures']:>8,d}")
    print(f"    most_repeated_count:    {sig['most_repeated_count']:>8d}")
    print()

    qual = scorecard["metrics"]["quality"]
    print("  DATA QUALITY")
    print(f"    total_rides:            {qual['total_rides']:>8,d}")
    print(f"    gps_coverage_pct:       {qual['gps_coverage_pct']:>8.1f}%")
    print(f"    elevation_coverage_pct: {qual['elevation_coverage_pct']:>8.1f}%")
    print(f"    power_coverage_pct:     {qual['power_coverage_pct']:>8.1f}%")
    print(f"    hr_coverage_pct:        {qual['hr_coverage_pct']:>8.1f}%")
    print(f"    parse_error_count:      {qual['parse_error_count']:>8d}  ({qual['parse_error_pct']:.1f}%)")
    print(f"    climbs_with_gps_pct:    {qual['climbs_with_gps_pct']:>8.1f}%")
    print(f"    elevation_outliers:     {qual['elevation_outlier_rides']:>8d}")
    print()

    pers = scorecard["metrics"]["persistence"]
    print("  PERSISTENCE METRICS")
    print(f"    avg_persistence_m:      {pers['avg_persistence_m']:>8.1f}")
    print(f"    median_persistence_m:   {pers['median_persistence_m']:>8.1f}")
    print(f"    max_persistence_m:      {pers['max_persistence_m']:>8.1f}")
    print(f"    vert_correlation:       {pers['persistence_vert_correlation']:>8.3f}")
    print()

    terr = scorecard["metrics"]["terrain"]
    print("  TERRAIN DISTRIBUTION")
    for t_class, count in terr.get("rides_by_terrain", {}).items():
        sig_data = terr.get("significant_climbs_by_terrain", {}).get(t_class, {})
        sig_count = sig_data.get("significant_climbs", 0)
        avg_v = sig_data.get("avg_vert_m", 0)
        print(f"    {t_class:15s} {count:>5d} rides  {sig_count:>6d} sig climbs  avg={avg_v:.0f}m")
    print(f"    {'unclassified':15s} {terr.get('unclassified_rides', 0):>5d} rides")
    print()

    if delta:
        drift_warnings = find_drift_warnings(delta)
        if drift_warnings:
            print("  DRIFT WARNINGS (>= 5% change)")
            for w in drift_warnings:
                print(f"    {w}")
            print()

        # Show all non-trivial deltas
        non_trivial = {k: v for k, v in delta.items() if "unchanged" not in v}
        if non_trivial:
            print("  DELTAS FROM PREVIOUS")
            for key, desc in sorted(non_trivial.items()):
                print(f"    {key:45s} {desc}")
            print()

    # Final verdict
    gates = scorecard["quality_gates"]
    if gates.get("passed"):
        print("  VERDICT: PASS (all quality gates passed)")
    else:
        print("  VERDICT: FAIL")
        for f in gates.get("failures", []):
            print(f"    {f}")

    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate corpus benchmark scorecard (Tier 3)"
    )
    parser.add_argument("--db", default=DB_PATH, help="Path to corpus.db")
    parser.add_argument("--output", "-o", help="Save scorecard JSON to file")
    parser.add_argument("--compare-to", help="Previous scorecard JSON for delta comparison")
    parser.add_argument("--json", action="store_true", help="Output JSON only (no human-readable)")
    args = parser.parse_args()

    # Check DB exists
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Corpus database not found: {db_path}", file=sys.stderr)
        print("Run process_corpus.py first to generate corpus.db", file=sys.stderr)
        sys.exit(1)

    conn = connect(str(db_path))

    # Generate scorecard
    scorecard = generate_scorecard(conn)
    failures = check_quality_gates(scorecard)

    conn.close()

    # Load previous scorecard for comparison
    delta = None
    if args.compare_to:
        prev_path = Path(args.compare_to)
        if prev_path.exists():
            with open(prev_path) as f:
                previous = json.load(f)
            delta = compute_delta(scorecard, previous)
            scorecard["delta_from_previous"] = delta
            scorecard["compared_to"] = str(prev_path)
        else:
            print(f"WARNING: Previous scorecard not found: {prev_path}", file=sys.stderr)

    # Output
    if args.json:
        print(json.dumps(scorecard, indent=2))
    else:
        print_scorecard(scorecard, delta)

    # Save to file
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(scorecard, f, indent=2)
        print(f"\nScorecard saved to: {output_path}")

    # Auto-save to scorecards/ with timestamp
    SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    auto_path = SCORECARD_DIR / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    with open(auto_path, "w") as f:
        json.dump(scorecard, f, indent=2)

    # Also save as "latest" for easy comparison
    latest_path = SCORECARD_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(scorecard, f, indent=2)

    if not args.json:
        print(f"Auto-saved to: {auto_path}")
        print(f"Latest link:   {latest_path}")

    # Exit code: 1 if quality gates failed
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
