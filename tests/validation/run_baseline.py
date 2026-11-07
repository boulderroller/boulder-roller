#!/usr/bin/env python3
"""
Phase 0: Run v1 climb detector on validation FIT files and record baseline.

Usage:
    cd backend && source venv/bin/activate
    python ../tests/validation/run_baseline.py

Outputs:
    tests/validation/baseline_v1.json  -- full v1 detection results per file per terrain
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

VALIDATION_DIR = Path(__file__).parent
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"
BASELINE_PATH = VALIDATION_DIR / "baseline_v1.json"

TERRAIN_MODES = ["auto", "flat", "rolling", "hilly", "mountainous", "urban_hills"]
DEFAULT_WEIGHT_KG = 75.0


def parse_fit_to_tile_samples(fit_path: str):
    """Parse a FIT file and convert to tile_samples dicts for detect_climbs_adaptive."""
    import workout_parse as wp

    activity = wp.parse_file(fit_path)
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
        samples.append(s)

    meta = {
        "samples": n,
        "duration_s": activity.total_elapsed_s,
        "sport": str(activity.sport),
        "has_gps": activity.lat_e7 is not None and len(activity.lat_e7) > 0,
        "has_elevation": activity.elevation_m is not None and len(activity.elevation_m) > 0,
        "has_power": activity.pwr_w is not None and len(activity.pwr_w) > 0,
        "has_hr": activity.hr_bpm is not None and len(activity.hr_bpm) > 0,
    }

    if activity.elevation_m is not None and len(activity.elevation_m) > 0:
        elev = [float(e) for e in activity.elevation_m if e > -500]
        meta["elev_min_m"] = min(elev)
        meta["elev_max_m"] = max(elev)
        meta["elev_gain_naive_m"] = round(sum(max(0, elev[i + 1] - elev[i]) for i in range(len(elev) - 1)), 1)

    return samples, meta


def run_detection(tile_samples, terrain: str):
    """Run v1 climb detection for a given terrain mode."""
    import workout_parse as wp

    climbs = wp.detect_climbs_adaptive(
        tile_samples=tile_samples,
        terrain=terrain,
        user_weight_kg=DEFAULT_WEIGHT_KG,
        algorithm="momentum",
        generate_signatures=True,
    )

    results = []
    for c in climbs:
        results.append({
            "vert_m": round(c.vert_m, 1),
            "time_s": c.time_s,
            "avg_gradient_pct": round(c.avg_gradient_pct, 1) if c.avg_gradient_pct else None,
            "distance_m": round(c.distance_m, 0) if c.distance_m else None,
            "vam": round(c.vert_m / c.time_s * 3600, 0) if c.time_s > 0 else 0,
            "start_offset_s": c.start_time_offset_s,
            "end_offset_s": c.end_time_offset_s,
            "signature_hex": c.signature_hex,
            "avg_power_w": round(c.avg_power_w, 1) if c.avg_power_w else None,
            "avg_hr": c.avg_hr,
        })
    return results


def main():
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    baseline = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "detector": "v1_momentum",
        "weight_kg": DEFAULT_WEIGHT_KG,
        "terrain_modes": TERRAIN_MODES,
        "files": [],
    }

    for entry in manifest["files"]:
        fit_path = str(VALIDATION_DIR / entry["file"])
        print(f"\n{'='*60}")
        print(f"Processing: {entry['file']}")
        print(f"  Terrain hint: {entry['terrain']}")

        if not os.path.exists(fit_path):
            print(f"  SKIP: file not found")
            continue

        tile_samples, meta = parse_fit_to_tile_samples(fit_path)
        print(f"  Samples: {meta['samples']}, Duration: {meta['duration_s']}s")
        if "elev_gain_naive_m" in meta:
            print(f"  Elevation: {meta['elev_min_m']:.0f}-{meta['elev_max_m']:.0f}m, Gain: {meta['elev_gain_naive_m']:.0f}m")

        file_result = {
            "file": entry["file"],
            "meta": meta,
            "expected_climb_count": len(entry["expected_climbs"]),
            "detections": {},
        }

        for terrain in TERRAIN_MODES:
            climbs = run_detection(tile_samples, terrain)
            file_result["detections"][terrain] = {
                "count": len(climbs),
                "climbs": climbs,
            }
            print(f"  terrain={terrain}: {len(climbs)} climb(s)")

        # Summary: how does v1 do against ground truth?
        expected = len(entry["expected_climbs"])
        auto_count = file_result["detections"]["auto"]["count"]
        hint_count = file_result["detections"][entry["terrain"]]["count"]
        hilly_count = file_result["detections"]["hilly"]["count"]

        file_result["summary"] = {
            "expected": expected,
            "auto_detected": auto_count,
            "terrain_hint_detected": hint_count,
            "hilly_default_detected": hilly_count,
            "auto_gap": expected - auto_count,
            "notes": [],
        }

        if auto_count == 0 and expected > 0:
            file_result["summary"]["notes"].append(
                "CRITICAL: terrain=auto finds 0 climbs despite known climbs — discrete classification gap"
            )
        if auto_count < expected:
            file_result["summary"]["notes"].append(
                f"auto misses {expected - auto_count} expected climb(s)"
            )

        baseline["files"].append(file_result)
        print(f"  Summary: expected={expected}, auto={auto_count}, "
              f"hint({entry['terrain']})={hint_count}, hilly={hilly_count}")

    # Global summary
    total_expected = sum(f["summary"]["expected"] for f in baseline["files"])
    total_auto = sum(f["summary"]["auto_detected"] for f in baseline["files"])
    total_hilly = sum(f["summary"]["hilly_default_detected"] for f in baseline["files"])

    baseline["global_summary"] = {
        "total_files": len(baseline["files"]),
        "total_expected_climbs": total_expected,
        "total_auto_detected": total_auto,
        "total_hilly_detected": total_hilly,
        "auto_recall": round(total_auto / total_expected, 3) if total_expected > 0 else 0,
        "hilly_recall": round(total_hilly / total_expected, 3) if total_expected > 0 else 0,
    }

    with open(BASELINE_PATH, "w") as f:
        json.dump(baseline, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Baseline written to: {BASELINE_PATH}")
    print(f"  Files: {baseline['global_summary']['total_files']}")
    print(f"  Expected climbs: {total_expected}")
    print(f"  Auto recall: {baseline['global_summary']['auto_recall']}")
    print(f"  Hilly recall: {baseline['global_summary']['hilly_recall']}")


if __name__ == "__main__":
    main()
