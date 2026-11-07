#!/usr/bin/env python3
"""
Mine corpus rides where persistence starts later than the product baseline.

This focuses on the "shoulder into steeper core" miss class:
- canonical shows a plausible climb earlier
- persistence either misses it or snaps to a later inner core

Example:
  python3 tools/corpus/find_shoulder_cases.py \
    --db tools/corpus/corpus.db \
    --export-root /Users/gabetemp/Downloads/export_440100/activities \
    --render-top 3
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
VALIDATION_DIR = REPO_ROOT / "tests" / "validation"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "review_climb.py"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from app.services.patterns.climb import detect_climbs_with_rust  # noqa: E402
from compare_candidate_generators import display_climbs, parse_fit_to_sample_views  # noqa: E402


@dataclass
class MissingCase:
    canonical_start_s: int
    canonical_end_s: int
    canonical_vert_m: float
    persistence_start_s: int | None
    persistence_end_s: int | None
    persistence_vert_m: float | None
    overlap_s: int
    start_delay_s: int | None


@dataclass
class ShoulderCase:
    filename: str
    terrain_class: str
    strava_name: str
    distance_km: float
    elevation_gain_m: float
    persistence_shown: int
    canonical_shown: int
    undercount: int
    max_start_delay_s: int
    score: int
    misses: list[MissingCase]
    review_path: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine shoulder/core misses from the local corpus.")
    parser.add_argument("--db", default="tools/corpus/corpus.db", help="Path to the corpus SQLite DB")
    parser.add_argument(
        "--export-root",
        required=True,
        help="Path to the Strava export activities directory",
    )
    parser.add_argument("--limit", type=int, default=12, help="Max number of cases to print")
    parser.add_argument(
        "--render-top",
        type=int,
        default=0,
        help="Render climb-review HTMLs for the top N cases",
    )
    parser.add_argument(
        "--min-start-delay-s",
        type=int,
        default=120,
        help="Minimum persistence-vs-canonical start delay to count as a shoulder miss",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path",
    )
    return parser.parse_args()


def overlap_seconds(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    return max(0, hi - lo)


def best_persistence_match(canonical_climb, persistence_climbs: Sequence):
    best = None
    for persistence in persistence_climbs:
        overlap = overlap_seconds(
            canonical_climb.start_time_offset_s,
            canonical_climb.end_time_offset_s,
            persistence.start_time_offset_s,
            persistence.end_time_offset_s,
        )
        start_gap = abs(canonical_climb.start_time_offset_s - persistence.start_time_offset_s)
        score = (overlap, -start_gap)
        if best is None or score > best[0]:
            best = (score, persistence)
    return None if best is None else best[1]


def case_misses(canonical_climbs: Sequence, persistence_climbs: Sequence, min_start_delay_s: int) -> list[MissingCase]:
    misses: list[MissingCase] = []
    for canonical in canonical_climbs:
        persistence = best_persistence_match(canonical, persistence_climbs)
        if persistence is None:
            misses.append(
                MissingCase(
                    canonical_start_s=canonical.start_time_offset_s,
                    canonical_end_s=canonical.end_time_offset_s,
                    canonical_vert_m=round(float(canonical.vert_m), 1),
                    persistence_start_s=None,
                    persistence_end_s=None,
                    persistence_vert_m=None,
                    overlap_s=0,
                    start_delay_s=None,
                )
            )
            continue

        overlap = overlap_seconds(
            canonical.start_time_offset_s,
            canonical.end_time_offset_s,
            persistence.start_time_offset_s,
            persistence.end_time_offset_s,
        )
        start_delay = persistence.start_time_offset_s - canonical.start_time_offset_s
        if overlap == 0 or start_delay > min_start_delay_s:
            misses.append(
                MissingCase(
                    canonical_start_s=canonical.start_time_offset_s,
                    canonical_end_s=canonical.end_time_offset_s,
                    canonical_vert_m=round(float(canonical.vert_m), 1),
                    persistence_start_s=persistence.start_time_offset_s,
                    persistence_end_s=persistence.end_time_offset_s,
                    persistence_vert_m=round(float(persistence.vert_m), 1),
                    overlap_s=overlap,
                    start_delay_s=start_delay,
                )
            )
    return misses


def render_review(target_path: Path) -> str | None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REVIEW_SCRIPT),
            str(target_path),
            "--terrain",
            "rolling",
            "--no-open",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("Report ready: "):
            return line.removeprefix("Report ready: ").strip()
    return None


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    export_root = Path(args.export_root)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT filename, terrain_class, COALESCE(strava_name, '') AS strava_name,
               distance_m, elevation_gain_m
        FROM rides
        WHERE terrain_class IN ('rolling', 'urban_hills', 'hilly')
          AND parse_error IS NULL
          AND file_format = 'fit'
          AND distance_m BETWEEN 25000 AND 70000
          AND elevation_gain_m BETWEEN 250 AND 900
        ORDER BY elevation_gain_m ASC, distance_m ASC
        """
    ).fetchall()

    results: list[ShoulderCase] = []
    for row in rows:
        fit_path = export_root / row["filename"]
        if not fit_path.exists():
            continue

        try:
            raw_tile_samples, tile_runs = parse_fit_to_sample_views(fit_path)
            persistence = display_climbs(
                detect_climbs_with_rust(
                    tile_runs,
                    persistence_candidate_samples=raw_tile_samples,
                    algorithm="persistence",
                    user_weight_kg=75.0,
                )
            )
            canonical = display_climbs(
                detect_climbs_with_rust(
                    tile_runs,
                    algorithm="canonical",
                    user_weight_kg=75.0,
                )
            )
        except Exception:
            continue

        if len(canonical) < 2:
            continue

        misses = case_misses(canonical, persistence, args.min_start_delay_s)
        if not misses:
            continue

        start_delays = [miss.start_delay_s or 0 for miss in misses]
        undercount = max(0, len(canonical) - len(persistence))
        score = undercount * 300 + sum(max(delay, args.min_start_delay_s) for delay in start_delays)
        results.append(
            ShoulderCase(
                filename=row["filename"],
                terrain_class=row["terrain_class"],
                strava_name=row["strava_name"],
                distance_km=round(float(row["distance_m"]) / 1000.0, 1),
                elevation_gain_m=round(float(row["elevation_gain_m"]), 1),
                persistence_shown=len(persistence),
                canonical_shown=len(canonical),
                undercount=undercount,
                max_start_delay_s=max(start_delays) if start_delays else 0,
                score=score,
                misses=misses[:3],
            )
        )

    results.sort(key=lambda case: (-case.score, -case.undercount, -case.max_start_delay_s, case.filename))
    top_cases = results[: args.limit]

    if args.render_top > 0:
        for case in top_cases[: args.render_top]:
            case.review_path = render_review(export_root / case.filename)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps([asdict(case) for case in top_cases], indent=2) + "\n")

    print(json.dumps([asdict(case) for case in top_cases], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
