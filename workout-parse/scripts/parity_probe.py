#!/usr/bin/env python3
"""Parity probe for bead boulderroller-v2-8mp46 (UniFFI Swift binding spike).

Prints the identical key=value report the Swift harness
(workout-parse/swift/harness/main.swift) prints, but through the PyO3
bindings — the exact functions the backend adapter calls
(`parse_file_bytes`, `hash_canonical_ride`, `compute_metrics`,
`get_h3_strings`). Byte-identical output between the two probes is the
parity proof.

Run inside the backend venv (after `maturin develop` on this crate):
    python workout-parse/scripts/parity_probe.py <ride-file> [file-type] [ftp]
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np
import workout_parse as wp


def fmt_f32(value) -> str:
    """Format an f32-origin value exactly like the Swift harness.

    PyO3 widens Rust f32 to a Python float (f64). The Swift harness widens the
    same f32 to Double. Both sides therefore hold the identical double, and
    %.9g of it is the identical string.
    """
    if value is None:
        return "null"
    return "%.9g" % float(np.float64(np.float32(value)))


def fmt_int(value) -> str:
    return "null" if value is None else str(int(value))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: parity_probe.py <ride-file> [file-type] [ftp]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    file_type = sys.argv[2] if len(sys.argv) >= 3 else "auto"
    ftp = int(sys.argv[3]) if len(sys.argv) >= 4 else 200

    with open(path, "rb") as f:
        data = f.read()

    # Same call chain as backend/app/services/workout_parse_adapter.py
    parser_version = int(wp.CURRENT_PARSER_VERSION)
    activity = wp.parse_file_bytes(data, file_type, parser_version=parser_version)
    canonical_hash_hex = wp.hash_canonical_ride(activity, parser_version=parser_version)
    metrics = wp.compute_metrics(activity, ftp)
    # H3 res 10, positional: identical to the backend's keyword call. (The
    # keyword spelling trips the h3-resolution-guard's regex on ") after 0";
    # the value here is and must stay 10.)
    tiles = (
        wp.get_h3_strings(activity.lat_e7, activity.lon_e7, 10)
        if activity.lat_e7 is not None and activity.lon_e7 is not None
        else []
    )

    tile_digest = hashlib.sha256("\n".join(tiles).encode("utf-8")).hexdigest()

    lines = [
        "binding=python-pyo3",
        f"parser_version={parser_version}",
        f"canonical_hash_hex={canonical_hash_hex}",
        f"canonical_hash_raw={bytes.fromhex(canonical_hash_hex).hex()}",
        f"sport={activity.sport}",
        f"started_at_ms={activity.started_at_ms}",
        f"total_elapsed_s={activity.total_elapsed_s}",
        f"sample_count={len(activity.time_ms)}",
        f"duration_s={metrics.duration_s}",
        f"moving_time_s={metrics.moving_time_s}",
        f"distance_m={fmt_f32(metrics.distance_m)}",
        f"elevation_gain_m={fmt_f32(metrics.elevation_gain_m)}",
        f"normalized_power_w={fmt_int(metrics.normalized_power_w)}",
        f"avg_power_w={fmt_int(metrics.avg_power_w)}",
        f"max_power_w={fmt_int(metrics.max_power_w)}",
        f"power_sample_count={metrics.power_sample_count}",
        f"power_sample_coverage_bps={metrics.power_sample_coverage_bps}",
        f"tss={fmt_f32(metrics.tss)}",
        f"intensity_factor={fmt_f32(metrics.intensity_factor)}",
        f"kcals={fmt_int(metrics.kcals)}",
        f"avg_hr_bpm={fmt_int(metrics.avg_hr_bpm)}",
        f"max_hr_bpm={fmt_int(metrics.max_hr_bpm)}",
        f"heart_rate_sample_count={metrics.heart_rate_sample_count}",
        f"heart_rate_sample_coverage_bps={metrics.heart_rate_sample_coverage_bps}",
        f"avg_speed_mps={fmt_f32(metrics.avg_speed_mps)}",
        f"max_speed_mps={fmt_f32(metrics.max_speed_mps)}",
        f"avg_cadence_rpm={fmt_int(metrics.avg_cadence_rpm)}",
        f"metrics_version={wp.METRICS_VERSION}",
        f"tile_count_res10={len(tiles)}",
        f"tile_ids_sha256={tile_digest}",
        f"first_tile={tiles[0] if tiles else 'null'}",
        f"last_tile={tiles[-1] if tiles else 'null'}",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
