#!/usr/bin/env python3
"""
Compare climb candidate generators on the validation corpus.

This script is intentionally product-oriented rather than academically precise:
it measures how often each detector path covers the annotated climbs without
exploding into obvious extras.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

from workout_parse_runtime import import_workout_parse_verified

VALIDATION_DIR = Path(__file__).parent
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"
REPO_ROOT = VALIDATION_DIR.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import detect_climbs_with_rust
from app.services.tile_service import TileService

DEFAULT_WEIGHT_KG = 75.0
MIN_DISPLAY_VERT_M = 20.0
EXPECTED_START_TOLERANCE_S = 240
PENDING_ANNOTATION_STATUS = "pending_review"


def scored_expected_rows(expected_rows):
    """Rows with pending review hints should not act as ground truth."""
    return [
        row
        for row in expected_rows
        if row.get("annotation_status") != PENDING_ANNOTATION_STATUS
    ]


def expected_anchor_quality(expected_rows):
    """Describe how strong the human annotations are for this file.

    Start-time anchors let us reason about boundary placement. Vert-only
    anchors are still useful for "some climb exists here" coverage, but they
    cannot distinguish a clean boundary from a lucky same-sized extra.
    """
    if not expected_rows:
        return "negative_control"
    anchored = sum(1 for row in expected_rows if row.get("approx_start_s") is not None)
    if anchored == len(expected_rows):
        return "start_anchored"
    if anchored == 0:
        return "vert_only"
    return "mixed_anchors"


def expected_review_state(expected_rows):
    scored = scored_expected_rows(expected_rows)
    pending = len(expected_rows) - len(scored)
    if pending == 0:
        return "reviewed"
    if not scored:
        return "annotation_pending"
    return "mixed_review"


def parse_fit_to_sample_views(fit_path: Path):
    wp = import_workout_parse_verified()
    activity = wp.parse_file(str(fit_path))
    points = []
    for idx in range(len(activity.time_ms)):
        point = {"timestamp": float(int(activity.time_ms[idx]) / 1000.0)}
        if activity.elevation_m is not None and idx < len(activity.elevation_m):
            point["elevation_m"] = float(activity.elevation_m[idx])
        if activity.lat_e7 is not None and idx < len(activity.lat_e7):
            point["lat"] = float(activity.lat_e7[idx]) / 1e7
            point["lon"] = float(activity.lon_e7[idx]) / 1e7
        if activity.pwr_w is not None and idx < len(activity.pwr_w):
            power_w = int(activity.pwr_w[idx])
            if 0 < power_w < 5000:
                point["power_w"] = power_w
        if activity.hr_bpm is not None and idx < len(activity.hr_bpm):
            hr_bpm = int(activity.hr_bpm[idx])
            if 0 < hr_bpm < 255:
                point["hr_bpm"] = hr_bpm
        points.append(point)

    if not points:
        return [], []

    tile_service = TileService()
    raw_tile_samples = [
        {
            "tile_id": sample.tile_id,
            "t": int(sample.t),
            "lat": sample.lat,
            "lon": sample.lon,
            "elevation_m": sample.elevation_m,
            "power_w": sample.power_w,
            "hr_bpm": sample.hr_bpm,
            "speed_mps": sample.speed_mps,
        }
        for sample in tile_service.get_tile_sequence(
            points,
            resolution=10,
            start_time=points[0]["timestamp"],
        )
    ]
    tile_runs = tile_service.get_tile_run_sequence(
        points,
        resolution=10,
        start_time=points[0]["timestamp"],
    )
    return raw_tile_samples, tile_runs or raw_tile_samples


def display_climbs(climbs):
    return [climb for climb in climbs if climb.vert_m >= MIN_DISPLAY_VERT_M]


def count_expected_matches(climbs, expected_rows):
    unmatched = list(range(len(climbs)))
    matched = 0

    for expected in expected_rows:
        best_idx = None
        best_score = None
        exp_start = expected.get("approx_start_s")
        exp_vert = expected.get("approx_vert_m")

        for idx in unmatched:
            climb = climbs[idx]
            if exp_start is not None:
                start_delta = abs(climb.start_time_offset_s - int(exp_start))
                if start_delta > EXPECTED_START_TOLERANCE_S:
                    continue
                score = start_delta
            elif exp_vert is not None:
                vert_delta = abs(float(climb.vert_m) - float(exp_vert))
                if vert_delta > float(exp_vert) * 0.5:
                    continue
                score = vert_delta
            else:
                continue

            if best_score is None or score < best_score:
                best_idx = idx
                best_score = score

        if best_idx is not None:
            matched += 1
            unmatched.remove(best_idx)

    return matched


def mode_score(climbs, expected_rows):
    shown = display_climbs(climbs)
    scored_rows = scored_expected_rows(expected_rows)
    matched = count_expected_matches(shown, scored_rows)
    review_state = expected_review_state(expected_rows)
    if review_state == "annotation_pending":
        extras = 0
        missed = 0
    else:
        extras = max(0, len(shown) - matched)
        missed = max(0, len(scored_rows) - matched)
    score = matched * 3 - extras - missed * 2
    return {
        "shown": len(shown),
        "matched": matched,
        "extras": extras,
        "missed": missed,
        "pending_annotations": len(expected_rows) - len(scored_rows),
        "score": score,
        "classification": classify_failure(
            shown_count=len(shown),
            expected_count=len(scored_rows),
            matched=matched,
            extras=extras,
            missed=missed,
            review_state=review_state,
        ),
        "anchor_quality": expected_anchor_quality(scored_rows),
        "review_state": review_state,
    }


def classify_failure(
    *,
    shown_count,
    expected_count,
    matched,
    extras,
    missed,
    review_state="reviewed",
):
    """Turn scoreboard numbers into a product-diagnostic bucket."""
    if review_state == "annotation_pending":
        return "annotation_pending"

    if expected_count == 0:
        if shown_count == 0:
            return "clean_negative_control"
        return "negative_control_false_positive"

    if matched == expected_count and extras == 0:
        return "clean_pass"
    if shown_count == 0:
        return "missing_all_expected"
    if missed > 0 and extras > 0:
        return "mixed_boundary_drift"
    if missed > 0:
        return "under_detecting"
    if extras > 0:
        return "over_generating"
    return "unclassified"


def main():
    manifest = json.loads(MANIFEST_PATH.read_text())

    modes: dict[str, Callable[[list[dict], list[dict]], list]] = {
        "persistence": lambda tile_runs, raw_tile_samples: detect_climbs_with_rust(
            tile_runs,
            persistence_candidate_samples=raw_tile_samples,
            algorithm="persistence",
            user_weight_kg=DEFAULT_WEIGHT_KG,
        ),
        "momentum_auto": lambda tile_runs, _raw_tile_samples: detect_climbs_with_rust(
            tile_runs,
            algorithm="momentum",
            terrain="auto",
            user_weight_kg=DEFAULT_WEIGHT_KG,
        ),
        "momentum_hilly": lambda tile_runs, _raw_tile_samples: detect_climbs_with_rust(
            tile_runs,
            algorithm="momentum",
            terrain="hilly",
            user_weight_kg=DEFAULT_WEIGHT_KG,
        ),
        "canonical": lambda tile_runs, _raw_tile_samples: detect_climbs_with_rust(
            tile_runs,
            algorithm="canonical",
            user_weight_kg=DEFAULT_WEIGHT_KG,
        ),
        "canonical_v2": lambda tile_runs, raw_tile_samples: detect_climbs_with_rust(
            tile_runs,
            persistence_candidate_samples=raw_tile_samples,
            algorithm="canonical_v2",
            user_weight_kg=DEFAULT_WEIGHT_KG,
        ),
    }

    totals = {
        name: {
            "shown": 0,
            "matched": 0,
            "extras": 0,
            "missed": 0,
            "score": 0,
            "taxonomy": {},
        }
        for name in modes
    }
    skipped_files: list[dict[str, str]] = []

    print("=" * 78)
    print("CLIMB CANDIDATE GENERATOR COMPARISON")
    print("=" * 78)

    for entry in manifest["files"]:
        fit_path = VALIDATION_DIR / entry["file"]
        if not fit_path.exists():
            continue

        try:
            raw_tile_samples, tile_runs = parse_fit_to_sample_views(fit_path)
        except Exception as exc:
            skipped_files.append({"file": entry["file"], "reason": str(exc)})
            print(f"\n--- {entry['file']} ---")
            print(f"  skipped: {exc}")
            continue
        expected_rows = entry.get("expected_climbs", [])
        scored_rows = scored_expected_rows(expected_rows)
        pending_count = len(expected_rows) - len(scored_rows)
        print(
            f"\n--- {entry['file']} (terrain hint={entry['terrain']}, "
            f"expected={len(scored_rows)}, pending={pending_count}) ---"
        )

        file_scores = {}
        for mode_name, runner in modes.items():
            climbs = runner(tile_runs, raw_tile_samples)
            result = mode_score(climbs, expected_rows)
            file_scores[mode_name] = result
            for key in ("shown", "matched", "extras", "missed", "score"):
                totals[mode_name][key] += result[key]
            taxonomy = totals[mode_name]["taxonomy"]
            taxonomy[result["classification"]] = taxonomy.get(result["classification"], 0) + 1
            print(
                f"  {mode_name:14} shown={result['shown']:2d} "
                f"matched={result['matched']:2d} extras={result['extras']:2d} "
                f"missed={result['missed']:2d} score={result['score']:3d} "
                f"class={result['classification']} anchors={result['anchor_quality']} "
                f"review={result['review_state']}"
            )

        winner = max(file_scores.items(), key=lambda item: item[1]["score"])
        print(f"  winner: {winner[0]}")

    print("\n" + "=" * 78)
    print("TOTALS")
    for mode_name, result in totals.items():
        print(
            f"  {mode_name:14} shown={result['shown']:3d} matched={result['matched']:3d} "
            f"extras={result['extras']:3d} missed={result['missed']:3d} score={result['score']:4d}"
        )
    print("\nFAILURE TAXONOMY")
    for mode_name, result in totals.items():
        taxonomy = ", ".join(
            f"{name}={count}" for name, count in sorted(result["taxonomy"].items())
        )
        print(f"  {mode_name:14} {taxonomy}")
    if skipped_files:
        print("\nSKIPPED FILES")
        for skipped in skipped_files:
            print(f"  {skipped['file']}: {skipped['reason']}")
    print("=" * 78)


if __name__ == "__main__":
    main()
