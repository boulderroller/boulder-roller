#!/usr/bin/env python3
"""
Create a reproducible 70/30 train/eval holdout split for the golden corpus.

Problem:
  All 451 scorable rides were used for both tuning and evaluation. The
  reported F1=0.756 is an optimistic ceiling — we have no honest
  out-of-sample numbers.

Solution:
  Tag each scorable ride as "train" or "eval" in a new ride_split table,
  stratified by year so both sets contain rides from every year.

  - Deterministic: seed=42, sorted activity_ids within each year stratum
  - Stratified: ~70/30 per year, so temporal diversity is preserved in both
  - Idempotent: DROP + recreate on each run

Usage:
    cd backend && source venv/bin/activate
    python ../tools/corpus/create_holdout_split.py

    # Custom DB path
    python ../tools/corpus/create_holdout_split.py --db /path/to/golden_corpus.db

    # Different split ratio
    python ../tools/corpus/create_holdout_split.py --train-fraction 0.8
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"

# Same filters used by run_full_comparison.py and score_golden_corpus.py
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_SEGMENTS_PER_RIDE = 3


def get_scorable_rides(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """
    Return (activity_id, start_date) for all scorable rides.

    A ride is "scorable" if it:
    1. Has cached activity_streams
    2. Has >= MIN_SEGMENTS_PER_RIDE climb segment efforts meeting vert/grade filters

    This matches the query in run_full_comparison.py exactly.
    """
    rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.start_date
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= ?
        ORDER BY r.start_date ASC
    """, (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT, MIN_SEGMENTS_PER_RIDE)).fetchall()
    return [(r[0], r[1] or "") for r in rows]


def extract_year(start_date: str) -> str:
    """Extract year from ISO date string (e.g., '2023-01-15T10:30:00Z' -> '2023')."""
    if not start_date or len(start_date) < 4:
        return "unknown"
    return start_date[:4]


def stratified_split(
    rides: List[Tuple[str, str]],
    train_fraction: float,
    seed: int,
) -> Tuple[List[str], List[str]]:
    """
    Split rides into train/eval sets, stratified by year.

    Within each year stratum, activity_ids are sorted (for determinism
    independent of DB ordering) then shuffled with the given seed.
    The first ceil(n * train_fraction) go to train, rest to eval.

    Returns (train_ids, eval_ids).
    """
    by_year: Dict[str, List[str]] = defaultdict(list)
    for activity_id, start_date in rides:
        year = extract_year(start_date)
        by_year[year].append(activity_id)

    rng = random.Random(seed)
    train_ids: List[str] = []
    eval_ids: List[str] = []

    for year in sorted(by_year.keys()):
        ids = sorted(by_year[year])  # Sort for determinism
        rng.shuffle(ids)
        n_train = max(1, round(len(ids) * train_fraction))
        # Ensure at least 1 in eval if there are >= 2 rides in the year
        if len(ids) >= 2 and n_train == len(ids):
            n_train = len(ids) - 1
        train_ids.extend(ids[:n_train])
        eval_ids.extend(ids[n_train:])

    return train_ids, eval_ids


def count_segments(conn: sqlite3.Connection, activity_ids: List[str]) -> int:
    """Count total qualifying segment efforts across a set of rides."""
    if not activity_ids:
        return 0
    placeholders = ",".join("?" for _ in activity_ids)
    row = conn.execute(f"""
        SELECT COUNT(*) FROM strava_segment_efforts
        WHERE activity_id IN ({placeholders})
              AND is_climb = 1
              AND elevation_diff >= ?
              AND average_grade >= ?
    """, (*activity_ids, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchone()
    return row[0] if row else 0


def main():
    parser = argparse.ArgumentParser(
        description="Create reproducible 70/30 train/eval holdout split"
    )
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--train-fraction", type=float, default=0.70,
                        help="Fraction of rides for training (default: 0.70)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility (default: 42)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    # Get all scorable rides
    rides = get_scorable_rides(conn)
    print(f"Scorable rides in corpus: {len(rides)}")
    print(f"Split: {args.train_fraction:.0%} train / {1 - args.train_fraction:.0%} eval")
    print(f"Seed: {args.seed}")
    print()

    if not rides:
        print("ERROR: No scorable rides found. Is the golden_corpus.db populated?")
        sys.exit(1)

    # Stratified split
    train_ids, eval_ids = stratified_split(rides, args.train_fraction, args.seed)

    # Create/recreate the ride_split table
    conn.execute("DROP TABLE IF EXISTS ride_split")
    conn.execute("""
        CREATE TABLE ride_split (
            activity_id TEXT PRIMARY KEY,
            split TEXT NOT NULL CHECK (split IN ('train', 'eval')),
            year TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_ride_split_split ON ride_split(split)")

    # Build a year lookup
    year_lookup = {aid: extract_year(sd) for aid, sd in rides}

    # Insert all assignments
    for aid in train_ids:
        conn.execute(
            "INSERT INTO ride_split (activity_id, split, year) VALUES (?, 'train', ?)",
            (aid, year_lookup.get(aid, "unknown")),
        )
    for aid in eval_ids:
        conn.execute(
            "INSERT INTO ride_split (activity_id, split, year) VALUES (?, 'eval', ?)",
            (aid, year_lookup.get(aid, "unknown")),
        )
    conn.commit()

    # Count segments in each set
    train_segs = count_segments(conn, train_ids)
    eval_segs = count_segments(conn, eval_ids)

    # Report per-year breakdown
    print(f"{'Year':<10s}  {'Train':>6s}  {'Eval':>6s}  {'Total':>6s}  {'Train%':>7s}")
    print("-" * 45)

    by_year_train: Dict[str, int] = defaultdict(int)
    by_year_eval: Dict[str, int] = defaultdict(int)
    for aid in train_ids:
        by_year_train[year_lookup.get(aid, "unknown")] += 1
    for aid in eval_ids:
        by_year_eval[year_lookup.get(aid, "unknown")] += 1

    all_years = sorted(set(list(by_year_train.keys()) + list(by_year_eval.keys())))
    for year in all_years:
        t = by_year_train.get(year, 0)
        e = by_year_eval.get(year, 0)
        total = t + e
        pct = t / total * 100 if total else 0
        print(f"{year:<10s}  {t:>6d}  {e:>6d}  {total:>6d}  {pct:>6.1f}%")

    print("-" * 45)
    total = len(train_ids) + len(eval_ids)
    pct = len(train_ids) / total * 100 if total else 0
    print(f"{'TOTAL':<10s}  {len(train_ids):>6d}  {len(eval_ids):>6d}  {total:>6d}  {pct:>6.1f}%")
    print()

    print(f"Segment efforts:")
    print(f"  Train: {train_segs:,d} segments across {len(train_ids)} rides")
    print(f"  Eval:  {eval_segs:,d} segments across {len(eval_ids)} rides")
    print(f"  Total: {train_segs + eval_segs:,d} segments across {total} rides")
    print()
    print(f"ride_split table created in {args.db}")
    print(f"  SELECT split, COUNT(*) FROM ride_split GROUP BY split;")

    conn.close()


if __name__ == "__main__":
    main()
