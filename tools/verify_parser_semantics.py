#!/usr/bin/env python3
"""Replay the existing Python vector checks against a fresh local Rust build."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if sys.flags.optimize:
        raise RuntimeError("parser vector verification requires Python assertions")
    expected_version = int(sys.argv[1])
    # Always ask Cargo to check HEAD's inputs. An already installed wheel or an
    # mtime-only freshness check is not proof of the committed implementation.
    for args in (
        ["test", "--locked", "--test", "parser_semantics_vectors"],
        ["build", "--release", "--locked"],
    ):
        subprocess.run(
            ["cargo", *args],
            cwd=REPO_ROOT / "workout-parse",
            env={**os.environ, "PYO3_PYTHON": sys.executable},
            check=True,
        )
    sys.path[:0] = [str(REPO_ROOT / "tests/validation"), str(REPO_ROOT / "backend")]
    from workout_parse_runtime import _install_release_library, import_workout_parse_verified

    _install_release_library()
    wp = import_workout_parse_verified()
    assert wp.CURRENT_PARSER_VERSION == expected_version

    # Call the exact checks, so missing checks and pytest skips cannot turn an
    # unavailable verifier into a successful exemption.
    checks = {
        "tests/validation/test_ride_canonicalization.py": (
            "test_reference_gpx_vector",
            "test_parser_version_constant_exported_and_used_as_default",
        ),
        "backend/tests/truths/alignment/test_ride_hash_symmetry_gate.py": (
            "test_backend_workout_parse_v1_reference_gpx_matches_shared_vector",
            "test_backend_workout_parse_v5_reference_gpx_matches_current_vector",
            "test_cross_format_v2_source_bytes_match_rust_and_backend_goldens",
            "test_workout_parse_unknown_parser_version_fails_closed",
        ),
    }
    for path, names in checks.items():
        namespace = runpy.run_path(str(REPO_ROOT / path))
        for name in names:
            namespace[name]()
            print(f"PASS {name}", flush=True)


if __name__ == "__main__":
    main()
