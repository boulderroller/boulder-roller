#!/usr/bin/env python3
"""
Analyze a processed corpus SQLite database.

Usage:
    python tools/corpus/analyze_corpus.py [--db PATH]

Commands (interactive or via --cmd):
    stats           - Overall corpus statistics
    terrain         - Terrain classification breakdown
    climbs          - Climb size distribution
    signatures      - Most-repeated signatures (same climb ridden multiple times)
    hotspots        - Most-visited H3 cells
    monsters        - Biggest climbs detected
    comparison      - V1 vs V2 detector comparison (if --v1 was used)
    flat-noise      - Check false positives on flat terrain rides
    query SQL       - Run arbitrary SQL
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "corpus.db")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_stats(conn):
    print("\n=== CORPUS STATS ===")
    for row in conn.execute("SELECT key, value FROM corpus_stats ORDER BY key"):
        print(f"  {row['key']:40s} {row['value']}")

    print("\n=== RIDE SUMMARY ===")
    row = conn.execute("""
        SELECT
            COUNT(*) as n,
            SUM(CASE WHEN has_power THEN 1 ELSE 0 END) as power,
            SUM(CASE WHEN has_gps THEN 1 ELSE 0 END) as gps,
            SUM(CASE WHEN has_elevation THEN 1 ELSE 0 END) as elev,
            SUM(CASE WHEN has_hr THEN 1 ELSE 0 END) as hr,
            SUM(CASE WHEN parse_error IS NOT NULL THEN 1 ELSE 0 END) as errors,
            AVG(n_samples) as avg_samples,
            AVG(duration_s) as avg_duration,
            SUM(distance_m)/1000 as total_km
        FROM rides
    """).fetchone()
    print(f"  Rides:     {row['n']}")
    print(f"  Power:     {row['power']} ({row['power']/row['n']*100:.0f}%)")
    print(f"  GPS:       {row['gps']} ({row['gps']/row['n']*100:.0f}%)")
    print(f"  Elevation: {row['elev']} ({row['elev']/row['n']*100:.0f}%)")
    print(f"  HR:        {row['hr']} ({row['hr']/row['n']*100:.0f}%)")
    print(f"  Errors:    {row['errors']}")
    print(f"  Avg samples/ride:   {row['avg_samples']:.0f}")
    print(f"  Avg duration:       {row['avg_duration']/60:.0f} min")
    print(f"  Total distance:     {row['total_km']:,.0f} km")


def cmd_terrain(conn):
    print("\n=== TERRAIN CLASSIFICATION ===")
    for row in conn.execute("""
        SELECT terrain_class, COUNT(*) as n,
               AVG(elevation_gain_m) as avg_gain,
               AVG(elev_max_m - elev_min_m) as avg_range
        FROM rides WHERE terrain_class IS NOT NULL
        GROUP BY terrain_class ORDER BY n DESC
    """):
        print(f"  {row['terrain_class']:15s}  {row['n']:5d} rides  avg_gain={row['avg_gain']:.0f}m  avg_range={row['avg_range']:.0f}m")

    print("\n  Unclassified:", conn.execute("SELECT COUNT(*) FROM rides WHERE terrain_class IS NULL").fetchone()[0])


def cmd_climbs(conn):
    print("\n=== CLIMB SIZE DISTRIBUTION (V2) ===")
    buckets = [
        ("Noise (<10m)", 0, 10),
        ("Minor (10-20m)", 10, 20),
        ("Small (20-50m)", 20, 50),
        ("Medium (50-100m)", 50, 100),
        ("Significant (100-200m)", 100, 200),
        ("Large (200-500m)", 200, 500),
        ("Major (500-1000m)", 500, 1000),
        ("Epic (>1000m)", 1000, 99999),
    ]
    total = conn.execute("SELECT COUNT(*) FROM climbs_v2").fetchone()[0]
    print(f"  Total V2 climbs: {total}")
    for label, lo, hi in buckets:
        row = conn.execute(
            "SELECT COUNT(*), AVG(persistence), AVG(avg_gradient_pct) FROM climbs_v2 WHERE vert_m >= ? AND vert_m < ?",
            (lo, hi),
        ).fetchone()
        n = row[0]
        pct = n / total * 100 if total > 0 else 0
        bar = "#" * int(pct / 2)
        p = f"p={row[1]:.1f}m" if row[1] else ""
        g = f"g={row[2]:.1f}%" if row[2] else ""
        print(f"  {label:25s} {n:6d} ({pct:5.1f}%) {bar:30s} {p} {g}")

    print("\n=== ESSENTIAL vs MERGE CLIMBS ===")
    for row in conn.execute("""
        SELECT is_essential, COUNT(*), AVG(vert_m), AVG(persistence)
        FROM climbs_v2 GROUP BY is_essential
    """):
        kind = "essential" if row[0] else "merge"
        print(f"  {kind:10s}  n={row[1]:6d}  avg_vert={row[2]:.1f}m  avg_persist={row[3]:.1f}m")


def cmd_signatures(conn):
    print("\n=== MOST-REPEATED SIGNATURES (same climb, multiple rides) ===")
    print(f"  {'sig':16s} {'rides':>5s} {'avg_vert':>9s} {'avg_grad':>9s} {'avg_persist':>11s} {'h3':>16s}")
    for row in conn.execute("""
        SELECT signature_hex, n_occurrences, avg_vert_m, avg_gradient_pct, avg_persistence, h3_anchor
        FROM signatures WHERE version=2
        ORDER BY n_occurrences DESC LIMIT 30
    """):
        sig = row['signature_hex'][:16] if row['signature_hex'] else "?"
        print(f"  {sig} {row['n_occurrences']:5d}  {row['avg_vert_m']:8.1f}m {row['avg_gradient_pct'] or 0:8.1f}%  {row['avg_persistence'] or 0:10.1f}m  {row['h3_anchor'] or '':>16s}")

    total_sigs = conn.execute("SELECT COUNT(*) FROM signatures WHERE version=2").fetchone()[0]
    repeated = conn.execute("SELECT COUNT(*) FROM signatures WHERE version=2 AND n_occurrences > 1").fetchone()[0]
    print(f"\n  Total unique v2 sigs: {total_sigs}")
    print(f"  Repeated (>1 ride):   {repeated} ({repeated/total_sigs*100:.1f}%)" if total_sigs > 0 else "")


def cmd_hotspots(conn):
    print("\n=== MOST-VISITED H3 CELLS ===")
    print(f"  {'h3_index':>18s} {'rides':>6s}")
    for row in conn.execute("""
        SELECT h3_index, COUNT(DISTINCT activity_id) as rides
        FROM h3_cells GROUP BY h3_index
        ORDER BY rides DESC LIMIT 30
    """):
        print(f"  {row['h3_index']:>18s} {row['rides']:6d}")

    total_cells = conn.execute("SELECT COUNT(DISTINCT h3_index) FROM h3_cells").fetchone()[0]
    print(f"\n  Total unique H3 cells: {total_cells}")


def cmd_monsters(conn):
    print("\n=== BIGGEST CLIMBS DETECTED ===")
    print(f"  {'vert':>7s} {'persist':>8s} {'grad':>6s} {'time':>6s} {'power':>6s} {'ess':>4s} {'activity':>14s} {'strava_name':>30s}")
    for row in conn.execute("""
        SELECT c.vert_m, c.persistence, c.avg_gradient_pct, c.time_s, c.avg_power_w,
               c.is_essential, c.activity_id, r.strava_name
        FROM climbs_v2 c JOIN rides r ON c.activity_id = r.activity_id
        WHERE c.vert_m >= 20
        ORDER BY c.vert_m DESC LIMIT 40
    """):
        ess = "ESS" if row['is_essential'] else ""
        name = (row['strava_name'] or "")[:30]
        pwr = f"{row['avg_power_w']:.0f}W" if row['avg_power_w'] else ""
        print(f"  {row['vert_m']:7.1f}m {row['persistence']:7.1f}m {row['avg_gradient_pct']:5.1f}% {row['time_s']:5d}s {pwr:>6s} {ess:>4s} {row['activity_id']:>14s} {name}")


def cmd_flat_noise(conn):
    print("\n=== FALSE POSITIVES ON FLAT TERRAIN ===")
    row = conn.execute("""
        SELECT COUNT(*) FROM climbs_v2 c
        JOIN rides r ON c.activity_id = r.activity_id
        WHERE r.terrain_class = 'flat' AND c.vert_m >= 20
    """).fetchone()
    print(f"  Significant climbs (≥20m) on flat rides: {row[0]}")

    for row in conn.execute("""
        SELECT c.vert_m, c.persistence, c.avg_gradient_pct, c.is_essential, r.strava_name, c.activity_id
        FROM climbs_v2 c JOIN rides r ON c.activity_id = r.activity_id
        WHERE r.terrain_class = 'flat' AND c.vert_m >= 20
        ORDER BY c.vert_m DESC LIMIT 20
    """):
        ess = "ESS" if row['is_essential'] else "merge"
        name = (row['strava_name'] or "")[:40]
        print(f"  {row['vert_m']:6.1f}m  p={row['persistence']:.1f}m  g={row['avg_gradient_pct']:.1f}%  {ess:5s}  {name}  ({row['activity_id']})")


def cmd_comparison(conn):
    # Check if V1 data exists
    v1_count = conn.execute("SELECT COUNT(*) FROM climbs_v1").fetchone()[0]
    if v1_count == 0:
        print("\n  No V1 data. Re-run corpus processor with --v1 flag.")
        return

    print("\n=== V1 vs V2 COMPARISON ===")
    v2_count = conn.execute("SELECT COUNT(*) FROM climbs_v2 WHERE vert_m >= 20").fetchone()[0]
    v1_auto = conn.execute("SELECT COUNT(*) FROM climbs_v1 WHERE terrain_mode='auto'").fetchone()[0]
    v1_hilly = conn.execute("SELECT COUNT(*) FROM climbs_v1 WHERE terrain_mode='hilly'").fetchone()[0]
    print(f"  V2 significant (≥20m):  {v2_count}")
    print(f"  V1 auto:                {v1_auto}")
    print(f"  V1 hilly:               {v1_hilly}")


def cmd_query(conn, sql):
    try:
        rows = conn.execute(sql).fetchall()
        if not rows:
            print("  (no rows)")
            return
        keys = rows[0].keys()
        print("  " + " | ".join(keys))
        print("  " + "-" * (sum(len(k) + 3 for k in keys)))
        for row in rows[:100]:
            print("  " + " | ".join(str(row[k]) for k in keys))
        if len(rows) > 100:
            print(f"  ... ({len(rows)} total rows, showing first 100)")
    except Exception as e:
        print(f"  ERROR: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--cmd", nargs="*", help="Command to run (non-interactive)")
    args = parser.parse_args()

    conn = connect(args.db)

    if args.cmd:
        cmd_name = args.cmd[0]
        dispatch(conn, cmd_name, " ".join(args.cmd[1:]) if len(args.cmd) > 1 else "")
        conn.close()
        return

    # Interactive mode
    print(f"Corpus DB: {args.db}")
    print(f"Commands: stats, terrain, climbs, signatures, hotspots, monsters, flat-noise, comparison, query <SQL>")
    print(f"Type 'all' for full report, 'q' to quit.\n")

    while True:
        try:
            line = input("corpus> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line == "q":
            break
        if line == "all":
            for cmd in [cmd_stats, cmd_terrain, cmd_climbs, cmd_signatures, cmd_hotspots, cmd_monsters, cmd_flat_noise]:
                cmd(conn)
            continue
        parts = line.split(None, 1)
        dispatch(conn, parts[0], parts[1] if len(parts) > 1 else "")

    conn.close()


def dispatch(conn, cmd_name, rest):
    cmds = {
        "stats": lambda: cmd_stats(conn),
        "terrain": lambda: cmd_terrain(conn),
        "climbs": lambda: cmd_climbs(conn),
        "signatures": lambda: cmd_signatures(conn),
        "hotspots": lambda: cmd_hotspots(conn),
        "monsters": lambda: cmd_monsters(conn),
        "flat-noise": lambda: cmd_flat_noise(conn),
        "comparison": lambda: cmd_comparison(conn),
        "query": lambda: cmd_query(conn, rest),
    }
    fn = cmds.get(cmd_name)
    if fn:
        fn()
    else:
        print(f"  Unknown command: {cmd_name}")


if __name__ == "__main__":
    main()
