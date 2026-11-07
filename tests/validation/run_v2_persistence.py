#!/usr/bin/env python3
"""
Phase 1 validation: Run v2 persistence detector on validation FIT files.

Usage:
    cd backend && source venv/bin/activate
    python ../tests/validation/run_v2_persistence.py

Compares results against manifest ground truth and v1 baseline.
"""

import json
import os
import sys
from pathlib import Path

from workout_parse_runtime import import_workout_parse_verified

VALIDATION_DIR = Path(__file__).parent
MANIFEST_PATH = VALIDATION_DIR / "manifest.json"
BASELINE_PATH = VALIDATION_DIR / "baseline_v1.json"
DEFAULT_WEIGHT_KG = 75.0


def parse_fit_to_tile_samples(fit_path: str):
    """Parse a FIT file and convert to tile_samples dicts."""
    wp = import_workout_parse_verified()
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

    return samples


def main():
    wp = import_workout_parse_verified()

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    # Load v1 baseline for comparison
    v1_baseline = {}
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH) as f:
            bl = json.load(f)
            for entry in bl.get("files", []):
                v1_baseline[entry["file"]] = entry

    print("=" * 70)
    print("CLIMB DETECTION V2 (PERSISTENCE) — VALIDATION RUN")
    print("=" * 70)
    print()

    total_expected = 0
    total_v2_found = 0
    total_v1_auto = 0
    all_climbs = []
    sig_v2_count = 0
    sig_v1_count = 0

    for file_entry in manifest["files"]:
        filename = file_entry["file"]
        fit_path = str(VALIDATION_DIR / filename)
        expected_climbs = file_entry.get("expected_climbs", [])
        n_expected = len(expected_climbs)
        total_expected += n_expected

        if not os.path.exists(fit_path):
            print(f"  SKIP {filename} (not found)")
            continue

        print(f"--- {filename} (terrain={file_entry['terrain']}) ---")
        print(f"  Expected climbs: {n_expected}")

        try:
            samples = parse_fit_to_tile_samples(fit_path)
            climbs = wp.detect_climbs_persistence(samples, user_weight_kg=DEFAULT_WEIGHT_KG)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        total_v2_found += len(climbs)
        for c in climbs:
            if c.signature_v2_hex:
                sig_v2_count += 1
            if c.signature_v1_hex:
                sig_v1_count += 1

        # v1 comparison
        v1_auto_count = 0
        v1_hilly_count = 0
        if filename in v1_baseline:
            for mode_result in v1_baseline[filename].get("terrain_modes", []):
                if mode_result["terrain"] == "auto":
                    v1_auto_count = mode_result["climbs_found"]
                if mode_result["terrain"] == "hilly":
                    v1_hilly_count = mode_result["climbs_found"]
        total_v1_auto += v1_auto_count

        print(f"  v2 persistence: {len(climbs)} climbs")
        print(f"  v1 auto:        {v1_auto_count} climbs")
        print(f"  v1 hilly:       {v1_hilly_count} climbs")

        # Only print significant climbs (vert > 20m) to keep output readable
        sig_climbs = [c for c in climbs if c.vert_m >= 20]
        print(f"  Significant (≥20m): {len(sig_climbs)} climbs")
        for j, c in enumerate(sig_climbs):
            ess = " [ESS]" if c.is_essential else ""
            sig = " v2✓" if c.signature_v2_hex else ""
            print(
                f"    vert={c.vert_m:.1f}m  "
                f"persist={c.persistence:.1f}m  "
                f"time={c.time_s}s  "
                f"grad={c.avg_gradient_pct:.1f}%{ess}{sig}"
            )

        # Annotate matches against expected
        if expected_climbs:
            print("  Ground-truth matching:")
            for ec in expected_climbs:
                name = ec["name"]
                exp_vert = ec.get("approx_vert_m")
                exp_start = ec.get("approx_start_s")
                # Simple nearest-match: find v2 climb closest in vert
                best_match = None
                best_delta = float("inf")
                for c in climbs:
                    if exp_vert:
                        delta = abs(c.vert_m - exp_vert)
                        if delta < best_delta:
                            best_delta = delta
                            best_match = c
                if best_match and best_delta < exp_vert * 0.5:
                    print(
                        f"    ✓ {name} (expected ~{exp_vert}m) → "
                        f"matched {best_match.vert_m:.1f}m (Δ={best_delta:.1f}m)"
                    )
                else:
                    print(f"    ✗ {name} (expected ~{exp_vert}m) → NO MATCH")
        print()

    print("=" * 70)
    print("SUMMARY")
    print(f"  Total expected climbs: {total_expected}")
    print(f"  v2 persistence found:  {total_v2_found}")
    print(f"  v1 auto found:         {total_v1_auto}")
    if total_expected > 0:
        print(f"  v2/expected ratio:     {total_v2_found / total_expected:.2f}")

    # Signature coverage
    print(f"  v1 signatures:         {sig_v1_count}/{total_v2_found}")
    print(f"  v2 signatures:         {sig_v2_count}/{total_v2_found}")
    print("=" * 70)


if __name__ == "__main__":
    main()
