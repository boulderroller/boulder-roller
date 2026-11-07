#!/usr/bin/env python3
"""
Truth Audit: Run the full truth infrastructure against the corpus.

Answers:
  1. What's the real abstention rate across 46,758 climbs?
  2. Which abstention triggers fire most often?
  3. Are there terrain-dependent quality patterns?
  4. Where are the hard negatives for vault matching?
  5. What does the sensor quality landscape look like?

Usage:
    cd backend && source venv/bin/activate
    python ../tools/corpus/truth_audit.py
    python ../tools/corpus/truth_audit.py --section all
    python ../tools/corpus/truth_audit.py --section abstention
    python ../tools/corpus/truth_audit.py --section hard-negatives
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

DB_PATH = str(Path(__file__).parent / "corpus.db")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Section 1: Simulated Abstention Audit
# ---------------------------------------------------------------------------

def audit_abstention(conn: sqlite3.Connection):
    """Simulate abstention evaluation across all corpus climbs."""
    print("\n" + "=" * 70)
    print("  ABSTENTION AUDIT")
    print("=" * 70)

    # Fetch all significant climbs with their ride metadata
    rows = conn.execute("""
        SELECT
            c.id, c.activity_id, c.vert_m, c.time_s, c.distance_m,
            c.avg_gradient_pct, c.persistence, c.is_essential,
            c.signature_v2_hex, c.start_lat, c.start_lon,
            c.end_lat, c.end_lon,
            r.has_gps, r.has_elevation, r.has_power, r.has_hr,
            r.n_samples, r.elev_min_m, r.elev_max_m, r.terrain_class,
            r.duration_s
        FROM climbs_v2 c
        JOIN rides r ON c.activity_id = r.activity_id
        WHERE c.vert_m >= 5
    """).fetchall()

    total = len(rows)
    significant = sum(1 for r in rows if r["vert_m"] >= 20)

    # Simulate abstention for each climb
    reason_counter = Counter()
    abstained_count = 0
    abstained_significant = 0
    terrain_abstention = defaultdict(lambda: {"total": 0, "abstained": 0})

    for row in rows:
        reasons = []
        terrain = row["terrain_class"] or "unknown"
        terrain_abstention[terrain]["total"] += 1

        # 1. GPS check (ride-level)
        if not row["has_gps"]:
            reasons.append("SENSOR:no_gps")

        # 2. Climb-level GPS
        if row["start_lat"] is None or row["start_lat"] == 0:
            reasons.append("CLIMB_SENSOR:no_start_gps")

        # 3. Elevation plausibility (ride-level)
        if row["elev_max_m"] and row["elev_max_m"] > 5500:
            reasons.append("SENSOR:elev_implausible_high")
        if row["elev_min_m"] and row["elev_min_m"] < -500:
            reasons.append("SENSOR:elev_implausible_low")

        # 4. No elevation data
        if not row["has_elevation"]:
            reasons.append("SENSOR:no_elevation")

        # 5. VAM sanity
        if row["time_s"] and row["time_s"] > 0:
            vam = (row["vert_m"] / row["time_s"]) * 3600
            if vam > 2000:
                reasons.append("CLIMB_SENSOR:high_vam")

        # 6. Signature integrity
        if not row["signature_v2_hex"]:
            reasons.append("SIGNATURE:no_v2_sig")

        # 7. Distance sanity
        if row["distance_m"] is None or row["distance_m"] == 0:
            reasons.append("CLIMB_SENSOR:zero_distance")

        # 8. Gradient sanity
        if row["avg_gradient_pct"] is not None and row["avg_gradient_pct"] > 45:
            reasons.append("CLIMB_SENSOR:impossible_gradient")

        # 9. Sparse ride (< 50 samples for a ride)
        if row["n_samples"] and row["n_samples"] < 50:
            reasons.append("SENSOR:sparse_ride")

        if reasons:
            abstained_count += 1
            if row["vert_m"] >= 20:
                abstained_significant += 1
            terrain_abstention[terrain]["abstained"] += 1
            for r in reasons:
                reason_counter[r] += 1

    # Results
    print(f"\n  Total climbs (>=5m):       {total:>8,d}")
    print(f"  Significant (>=20m):       {significant:>8,d}")
    print(f"  Abstained (all):           {abstained_count:>8,d}  ({abstained_count/total*100:.1f}%)")
    print(f"  Abstained (significant):   {abstained_significant:>8,d}  ({abstained_significant/significant*100:.1f}%)" if significant else "")
    print(f"  Eligible (all):            {total - abstained_count:>8,d}  ({(total-abstained_count)/total*100:.1f}%)")

    print(f"\n  TRIGGER FREQUENCY (top reasons)")
    for reason, count in reason_counter.most_common(20):
        pct = count / total * 100
        bar = "#" * int(pct)
        print(f"    {reason:40s} {count:>6d}  ({pct:5.1f}%) {bar}")

    print(f"\n  ABSTENTION BY TERRAIN")
    for terrain in sorted(terrain_abstention.keys()):
        data = terrain_abstention[terrain]
        rate = data["abstained"] / data["total"] * 100 if data["total"] > 0 else 0
        print(f"    {terrain:15s} {data['total']:>6d} climbs  {data['abstained']:>5d} abstained  ({rate:5.1f}%)")

    return {
        "total_climbs": total,
        "significant_climbs": significant,
        "abstained_all": abstained_count,
        "abstained_significant": abstained_significant,
        "abstention_rate_all": round(abstained_count / total * 100, 1),
        "abstention_rate_significant": round(abstained_significant / significant * 100, 1) if significant else 0,
        "top_reasons": reason_counter.most_common(10),
    }


# ---------------------------------------------------------------------------
# Section 2: Sensor Quality Landscape
# ---------------------------------------------------------------------------

def audit_sensor_quality(conn: sqlite3.Connection):
    """Analyze sensor data quality across the corpus."""
    print("\n" + "=" * 70)
    print("  SENSOR QUALITY LANDSCAPE")
    print("=" * 70)

    # Ride-level sensor coverage
    rides = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN has_gps THEN 1 ELSE 0 END) as gps,
            SUM(CASE WHEN has_elevation THEN 1 ELSE 0 END) as elev,
            SUM(CASE WHEN has_power THEN 1 ELSE 0 END) as power,
            SUM(CASE WHEN has_hr THEN 1 ELSE 0 END) as hr,
            AVG(n_samples) as avg_samples,
            MIN(n_samples) as min_samples,
            MAX(n_samples) as max_samples
        FROM rides WHERE parse_error IS NULL
    """).fetchone()

    total = rides["total"]
    print(f"\n  RIDE-LEVEL SENSOR COVERAGE ({total} rides)")
    print(f"    GPS:       {rides['gps']:>5d}  ({rides['gps']/total*100:.1f}%)")
    print(f"    Elevation: {rides['elev']:>5d}  ({rides['elev']/total*100:.1f}%)")
    print(f"    Power:     {rides['power']:>5d}  ({rides['power']/total*100:.1f}%)")
    print(f"    HR:        {rides['hr']:>5d}  ({rides['hr']/total*100:.1f}%)")
    print(f"    Samples:   avg={rides['avg_samples']:.0f}  min={rides['min_samples']}  max={rides['max_samples']}")

    # Elevation plausibility
    print(f"\n  ELEVATION PLAUSIBILITY")
    outliers = conn.execute("""
        SELECT filename, elev_min_m, elev_max_m, terrain_class, strava_name
        FROM rides WHERE elev_max_m > 5500 OR elev_min_m < -500
    """).fetchall()
    print(f"    Implausible rides: {len(outliers)}")
    for o in outliers:
        name = (o["strava_name"] or o["filename"])[:40]
        print(f"      {name:40s} min={o['elev_min_m']:.0f}m max={o['elev_max_m']:.0f}m ({o['terrain_class']})")

    # Sampling rate distribution
    print(f"\n  SAMPLING RATE DISTRIBUTION")
    sampling = conn.execute("""
        SELECT
            CASE
                WHEN duration_s > 0 AND n_samples > 0 THEN n_samples / duration_s
                ELSE 0
            END as hz,
            COUNT(*) as n
        FROM rides WHERE parse_error IS NULL AND duration_s > 60
        GROUP BY CASE
            WHEN n_samples/duration_s < 0.1 THEN '<0.1Hz'
            WHEN n_samples/duration_s < 0.2 THEN '0.1-0.2Hz'
            WHEN n_samples/duration_s < 0.5 THEN '0.2-0.5Hz'
            WHEN n_samples/duration_s < 1.0 THEN '0.5-1.0Hz'
            ELSE '1.0Hz+'
        END
    """).fetchall()

    # Do the bucketing in Python for clarity
    buckets = {"<0.1Hz": 0, "0.1-0.2Hz": 0, "0.2-0.5Hz": 0, "0.5-1.0Hz": 0, "1.0Hz+": 0}
    for row in conn.execute("""
        SELECT n_samples * 1.0 / duration_s as hz
        FROM rides WHERE parse_error IS NULL AND duration_s > 60 AND n_samples > 0
    """):
        hz = row[0]
        if hz < 0.1:
            buckets["<0.1Hz"] += 1
        elif hz < 0.2:
            buckets["0.1-0.2Hz"] += 1
        elif hz < 0.5:
            buckets["0.2-0.5Hz"] += 1
        elif hz < 1.0:
            buckets["0.5-1.0Hz"] += 1
        else:
            buckets["1.0Hz+"] += 1

    for label, count in buckets.items():
        pct = count / total * 100
        bar = "#" * int(pct / 2)
        print(f"    {label:12s} {count:>5d} rides  ({pct:5.1f}%) {bar}")

    # Climb-level GPS coverage
    print(f"\n  CLIMB-LEVEL GPS COVERAGE")
    gps_stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN start_lat IS NOT NULL AND start_lat != 0 THEN 1 ELSE 0 END) as has_gps,
            SUM(CASE WHEN start_lat IS NULL OR start_lat = 0 THEN 1 ELSE 0 END) as no_gps
        FROM climbs_v2 WHERE vert_m >= 20
    """).fetchone()
    print(f"    Significant climbs:      {gps_stats['total']:>6d}")
    print(f"    With GPS start point:    {gps_stats['has_gps']:>6d}  ({gps_stats['has_gps']/gps_stats['total']*100:.1f}%)")
    print(f"    Without GPS:             {gps_stats['no_gps']:>6d}  ({gps_stats['no_gps']/gps_stats['total']*100:.1f}%)")

    # Terrain-specific quality
    print(f"\n  SENSOR QUALITY BY TERRAIN")
    for row in conn.execute("""
        SELECT
            terrain_class,
            COUNT(*) as n,
            AVG(CASE WHEN has_gps THEN 1.0 ELSE 0.0 END) as gps_rate,
            AVG(CASE WHEN has_power THEN 1.0 ELSE 0.0 END) as power_rate,
            AVG(n_samples) as avg_samples,
            AVG(elev_max_m - elev_min_m) as avg_elev_range
        FROM rides WHERE parse_error IS NULL AND terrain_class IS NOT NULL
        GROUP BY terrain_class ORDER BY n DESC
    """):
        print(f"    {row['terrain_class']:15s} {row['n']:>5d} rides  "
              f"GPS={row['gps_rate']*100:.0f}%  Power={row['power_rate']*100:.0f}%  "
              f"avg_samples={row['avg_samples']:.0f}  elev_range={row['avg_elev_range']:.0f}m")


# ---------------------------------------------------------------------------
# Section 3: Hard Negatives (same area, different climb)
# ---------------------------------------------------------------------------

def audit_hard_negatives(conn: sqlite3.Connection):
    """Find same-H3-cell climb pairs that should NOT match vaults."""
    print("\n" + "=" * 70)
    print("  HARD NEGATIVE ANALYSIS")
    print("=" * 70)

    # Find H3 anchors with multiple distinct signatures
    print(f"\n  H3 CELLS WITH MULTIPLE DISTINCT CLIMBS")
    multi_sig = conn.execute("""
        SELECT h3_anchor, COUNT(DISTINCT signature_v2_hex) as n_sigs,
               COUNT(*) as n_climbs,
               AVG(vert_m) as avg_vert,
               MIN(vert_m) as min_vert, MAX(vert_m) as max_vert
        FROM climbs_v2
        WHERE vert_m >= 20 AND h3_anchor IS NOT NULL AND signature_v2_hex IS NOT NULL
        GROUP BY h3_anchor
        HAVING COUNT(DISTINCT signature_v2_hex) > 1
        ORDER BY COUNT(DISTINCT signature_v2_hex) DESC
        LIMIT 30
    """).fetchall()

    total_cells = conn.execute(
        "SELECT COUNT(DISTINCT h3_anchor) FROM climbs_v2 WHERE vert_m >= 20 AND h3_anchor IS NOT NULL"
    ).fetchone()[0]
    multi_cells = len(multi_sig)

    print(f"    Total H3 anchor cells:        {total_cells:>6d}")
    print(f"    Cells with >1 distinct climb:  {multi_cells:>6d}  ({multi_cells/total_cells*100:.1f}%)")
    print()
    print(f"    {'h3_anchor':>16s} {'sigs':>5s} {'climbs':>6s} {'avg_vert':>9s} {'min':>6s} {'max':>6s}")
    for row in multi_sig[:20]:
        print(f"    {row['h3_anchor']:>16s} {row['n_sigs']:>5d} {row['n_climbs']:>6d} "
              f"{row['avg_vert']:>8.1f}m {row['min_vert']:>5.0f}m {row['max_vert']:>5.0f}m")

    # Hard negative pairs: same H3 anchor, different signature, similar vert
    print(f"\n  HARD NEGATIVE PAIRS (same area, similar vert, different signature)")
    print(f"  These would be false positives if matched by proximity alone.")
    hard_negs = conn.execute("""
        WITH ranked AS (
            SELECT h3_anchor, signature_v2_hex, vert_m, avg_gradient_pct,
                   start_lat, start_lon, activity_id,
                   ROW_NUMBER() OVER (PARTITION BY h3_anchor, signature_v2_hex ORDER BY vert_m DESC) as rn
            FROM climbs_v2
            WHERE vert_m >= 20 AND h3_anchor IS NOT NULL AND signature_v2_hex IS NOT NULL
        )
        SELECT a.h3_anchor,
               a.signature_v2_hex as sig_a, b.signature_v2_hex as sig_b,
               a.vert_m as vert_a, b.vert_m as vert_b,
               a.avg_gradient_pct as grad_a, b.avg_gradient_pct as grad_b,
               a.start_lat as lat_a, a.start_lon as lon_a,
               b.start_lat as lat_b, b.start_lon as lon_b
        FROM ranked a
        JOIN ranked b ON a.h3_anchor = b.h3_anchor
            AND a.signature_v2_hex < b.signature_v2_hex
            AND a.rn = 1 AND b.rn = 1
        WHERE ABS(a.vert_m - b.vert_m) / a.vert_m < 0.30  -- within 30% vert
        ORDER BY a.vert_m DESC
        LIMIT 30
    """).fetchall()

    total_hard_negs = conn.execute("""
        WITH ranked AS (
            SELECT h3_anchor, signature_v2_hex, vert_m,
                   ROW_NUMBER() OVER (PARTITION BY h3_anchor, signature_v2_hex ORDER BY vert_m DESC) as rn
            FROM climbs_v2
            WHERE vert_m >= 20 AND h3_anchor IS NOT NULL AND signature_v2_hex IS NOT NULL
        )
        SELECT COUNT(*)
        FROM ranked a
        JOIN ranked b ON a.h3_anchor = b.h3_anchor
            AND a.signature_v2_hex < b.signature_v2_hex
            AND a.rn = 1 AND b.rn = 1
        WHERE ABS(a.vert_m - b.vert_m) / a.vert_m < 0.30
    """).fetchone()[0]

    print(f"\n    Total hard negative pairs: {total_hard_negs}")
    if hard_negs:
        print(f"\n    {'h3':>16s} {'vert_A':>7s} {'grad_A':>7s} {'vert_B':>7s} {'grad_B':>7s} {'vert_diff':>10s}")
        for row in hard_negs[:15]:
            diff_pct = abs(row["vert_a"] - row["vert_b"]) / row["vert_a"] * 100
            print(f"    {row['h3_anchor']:>16s} {row['vert_a']:>6.1f}m {row['grad_a'] or 0:>6.1f}% "
                  f"{row['vert_b']:>6.1f}m {row['grad_b'] or 0:>6.1f}%  {diff_pct:>8.1f}%")

    # GPS proximity of hard negatives (how close are the start points?)
    if hard_negs:
        print(f"\n  GPS PROXIMITY OF HARD NEGATIVES")
        print(f"  If start points are close AND vert is similar, only signatures distinguish them.")
        close_count = 0
        far_count = 0
        for row in hard_negs:
            if (row["lat_a"] and row["lat_b"] and row["lon_a"] and row["lon_b"]
                    and row["lat_a"] != 0 and row["lat_b"] != 0):
                dist = _haversine_m(row["lat_a"], row["lon_a"], row["lat_b"], row["lon_b"])
                if dist < 500:
                    close_count += 1
                else:
                    far_count += 1
        print(f"    Start points < 500m apart: {close_count}")
        print(f"    Start points > 500m apart: {far_count}")
        if close_count > 0:
            print(f"    --> {close_count} pairs require DCT signature differentiation (GPS can't help)")


# ---------------------------------------------------------------------------
# Section 4: Signature Collision Landscape
# ---------------------------------------------------------------------------

def audit_signatures(conn: sqlite3.Connection):
    """Analyze signature uniqueness and collision landscape."""
    print("\n" + "=" * 70)
    print("  SIGNATURE LANDSCAPE")
    print("=" * 70)

    total_sigs = conn.execute(
        "SELECT COUNT(*) FROM signatures WHERE version = 2"
    ).fetchone()[0]
    repeated = conn.execute(
        "SELECT COUNT(*) FROM signatures WHERE version = 2 AND n_occurrences > 1"
    ).fetchone()[0]
    singleton = total_sigs - repeated

    print(f"\n  V2 SIGNATURE STATISTICS")
    print(f"    Total unique signatures:  {total_sigs:>8,d}")
    print(f"    Singletons (seen once):   {singleton:>8,d}  ({singleton/total_sigs*100:.1f}%)")
    print(f"    Repeated (seen >1x):      {repeated:>8,d}  ({repeated/total_sigs*100:.1f}%)")

    # Occurrence distribution
    print(f"\n  OCCURRENCE DISTRIBUTION")
    occ_dist = conn.execute("""
        SELECT n_occurrences, COUNT(*) as n_sigs
        FROM signatures WHERE version = 2
        GROUP BY n_occurrences ORDER BY n_occurrences
    """).fetchall()
    for row in occ_dist:
        pct = row["n_sigs"] / total_sigs * 100
        bar = "#" * min(50, int(pct))
        print(f"    seen {row['n_occurrences']:>2d}x: {row['n_sigs']:>6d} sigs  ({pct:5.1f}%) {bar}")

    # Most-repeated = most-ridden climbs (potential vault candidates)
    print(f"\n  TOP VAULT CANDIDATES (most-repeated climbs)")
    print(f"    {'sig':>16s} {'rides':>5s} {'avg_vert':>9s} {'avg_grad':>9s} {'avg_persist':>11s} {'h3':>16s}")
    for row in conn.execute("""
        SELECT signature_hex, n_occurrences, avg_vert_m, avg_gradient_pct,
               avg_persistence, h3_anchor
        FROM signatures WHERE version = 2
        ORDER BY n_occurrences DESC LIMIT 15
    """):
        sig = row["signature_hex"][:16] if row["signature_hex"] else "?"
        print(f"    {sig} {row['n_occurrences']:>5d}  {row['avg_vert_m']:>8.1f}m "
              f"{row['avg_gradient_pct'] or 0:>8.1f}%  {row['avg_persistence'] or 0:>10.1f}m "
              f"{row['h3_anchor'] or '':>16s}")


# ---------------------------------------------------------------------------
# Section 5: Economic Impact Analysis
# ---------------------------------------------------------------------------

def audit_economic_impact(conn: sqlite3.Connection):
    """What would the economy look like with current abstention rates?"""
    print("\n" + "=" * 70)
    print("  ECONOMIC IMPACT ANALYSIS")
    print("=" * 70)

    # Total vertical gain that would be eligible for CAL tribute
    total_vert = conn.execute(
        "SELECT SUM(vert_m) FROM climbs_v2 WHERE vert_m >= 20"
    ).fetchone()[0] or 0

    # Vert from climbs that would be abstained
    abstained_vert = conn.execute("""
        SELECT SUM(c.vert_m) FROM climbs_v2 c
        JOIN rides r ON c.activity_id = r.activity_id
        WHERE c.vert_m >= 20 AND (
            NOT r.has_gps
            OR c.start_lat IS NULL OR c.start_lat = 0
            OR c.signature_v2_hex IS NULL
            OR r.elev_max_m > 5500
            OR (c.time_s > 0 AND (c.vert_m / c.time_s * 3600) > 2000)
        )
    """).fetchone()[0] or 0

    eligible_vert = total_vert - abstained_vert

    print(f"\n  VERTICAL GAIN ECONOMICS")
    print(f"    Total significant vert:   {total_vert:>12,.0f}m")
    print(f"    Eligible vert:            {eligible_vert:>12,.0f}m  ({eligible_vert/total_vert*100:.1f}%)")
    print(f"    Abstained vert:           {abstained_vert:>12,.0f}m  ({abstained_vert/total_vert*100:.1f}%)")

    # Simulated CAL from eligible vert (10m = 1 CAL)
    total_cal = int(total_vert / 10)
    eligible_cal = int(eligible_vert / 10)
    print(f"\n  SIMULATED CAL (1 CAL per 10m)")
    print(f"    Total CAL (no abstention):  {total_cal:>10,d}")
    print(f"    Eligible CAL:               {eligible_cal:>10,d}")
    print(f"    CAL preserved by abstention: {total_cal - eligible_cal:>10,d}")

    # Vault coverage: what % of eligible climbs could match a vault?
    # (climbs with repeated signatures = potential vault matches)
    matchable = conn.execute("""
        SELECT COUNT(*) FROM climbs_v2 c
        JOIN signatures s ON c.signature_v2_hex = s.signature_hex AND s.version = 2
        WHERE c.vert_m >= 20 AND s.n_occurrences > 1
    """).fetchone()[0]

    sig_climbs = conn.execute(
        "SELECT COUNT(*) FROM climbs_v2 WHERE vert_m >= 20 AND signature_v2_hex IS NOT NULL"
    ).fetchone()[0]

    print(f"\n  VAULT MATCHABILITY")
    print(f"    Climbs with repeated sigs:  {matchable:>8,d} ({matchable/sig_climbs*100:.1f}% of significant)")
    print(f"    These could match a vault if one were created for that signature.")

    # Distribution of rides per vault candidate
    print(f"\n  RIDES PER VAULT CANDIDATE (top 10)")
    for row in conn.execute("""
        SELECT s.signature_hex, s.n_occurrences as rides,
               s.avg_vert_m, s.h3_anchor,
               COUNT(DISTINCT c.activity_id) as unique_rides
        FROM signatures s
        JOIN climbs_v2 c ON c.signature_v2_hex = s.signature_hex
        WHERE s.version = 2 AND s.n_occurrences > 1 AND c.vert_m >= 20
        GROUP BY s.signature_hex
        ORDER BY s.n_occurrences DESC
        LIMIT 10
    """):
        sig = row["signature_hex"][:16]
        print(f"    {sig}  {row['rides']:>3d} rides  vert={row['avg_vert_m']:.0f}m  "
              f"unique_rides={row['unique_rides']}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SECTIONS = {
    "abstention": audit_abstention,
    "sensors": audit_sensor_quality,
    "hard-negatives": audit_hard_negatives,
    "signatures": audit_signatures,
    "economic": audit_economic_impact,
}


def main():
    parser = argparse.ArgumentParser(description="Truth audit against corpus")
    parser.add_argument("--db", default=DB_PATH, help="Path to corpus.db")
    parser.add_argument("--section", default="all",
                        choices=["all"] + list(SECTIONS.keys()),
                        help="Which section to run")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        sys.exit(1)

    conn = connect(str(db_path))

    print(f"\n  Corpus: {db_path}")
    total_rides = conn.execute("SELECT COUNT(*) FROM rides").fetchone()[0]
    total_climbs = conn.execute("SELECT COUNT(*) FROM climbs_v2").fetchone()[0]
    print(f"  Rides: {total_rides:,d}  Climbs: {total_climbs:,d}")

    if args.section == "all":
        for name, fn in SECTIONS.items():
            fn(conn)
    else:
        SECTIONS[args.section](conn)

    conn.close()
    print()


if __name__ == "__main__":
    main()
