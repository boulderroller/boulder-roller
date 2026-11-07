"""Canonical ride hash symmetry gate.

This is the executable guard for the RideAttestation primitive: the shared
fixture vectors must stay byte-identical across workout-parse, backend, and
mobile. If parser-version semantics drift, this gate fails before economic
attestations can silently split.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import workout_parse as wp

from app.services.workout_parse_adapter import compute_ride_identity_bytes_rust


REPO_ROOT = Path(__file__).resolve().parents[4]
V1_VECTORS_PATH = REPO_ROOT / "tests" / "fixtures" / "canonical_ride_v1_vectors.json"
V5_VECTORS_PATH = REPO_ROOT / "tests" / "fixtures" / "canonical_ride_v5_vectors.json"
CROSS_FORMAT_VECTORS_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "canonical_cross_format_v2_vectors.json"
)


def _vectors(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_backend_workout_parse_v1_reference_gpx_matches_shared_vector() -> None:
    """Reference GPX source file -> workout-parse -> backend identity."""
    vectors = _vectors(V1_VECTORS_PATH)
    reference = vectors["vectors"]["reference_gpx_file"]
    source_path = REPO_ROOT / reference["source_path"]
    file_bytes = source_path.read_bytes()

    ride_hash, parser_version = compute_ride_identity_bytes_rust(
        file_bytes=file_bytes,
        file_type=reference["file_type"],
        parser_version=vectors["parser_version"],
    )

    activity = wp.parse_file_bytes(
        file_bytes, reference["file_type"], parser_version=vectors["parser_version"]
    )
    canonical_json = wp.canonicalize_ride(
        activity,
        parser_version=parser_version,
    ).decode("utf-8")

    assert parser_version == vectors["parser_version"]
    assert canonical_json == reference["canonical_json"]
    assert ride_hash.hex() == reference["ride_hash"]


def test_backend_workout_parse_v5_reference_gpx_matches_current_vector() -> None:
    vectors = _vectors(V5_VECTORS_PATH)
    reference = vectors["vectors"]["reference_gpx_file"]
    file_bytes = (REPO_ROOT / reference["source_path"]).read_bytes()

    ride_hash, parser_version = compute_ride_identity_bytes_rust(
        file_bytes=file_bytes,
        file_type=reference["file_type"],
    )
    activity = wp.parse_file_bytes(file_bytes, reference["file_type"])
    canonical_json = wp.canonicalize_ride(activity).decode("utf-8")

    assert wp.CURRENT_PARSER_VERSION == vectors["parser_version"]
    assert parser_version == vectors["parser_version"]
    assert canonical_json == reference["canonical_json"]
    assert ride_hash.hex() == reference["ride_hash"]


def test_cross_format_v2_source_bytes_match_rust_and_backend_goldens() -> None:
    """FIT, GPX, and TCX raw bytes each retain their documented streams."""
    vectors = _vectors(CROSS_FORMAT_VECTORS_PATH)

    for file_type, vector in vectors["vectors"].items():
        raw = (REPO_ROOT / vector["source_path"]).read_bytes()
        if vector["source_encoding"] == "base64":
            raw = base64.b64decode(raw)

        activity = wp.parse_file_bytes(
            raw, vector["file_type"], parser_version=vectors["parser_version"]
        )
        canonical_json = wp.canonicalize_ride(
            activity, parser_version=vectors["parser_version"]
        ).decode("utf-8")
        ride_hash, parser_version = compute_ride_identity_bytes_rust(
            raw, vector["file_type"], vectors["parser_version"]
        )

        assert canonical_json == vector["canonical_json"], file_type
        assert ride_hash.hex() == vector["ride_hash"], file_type
        assert parser_version == vectors["parser_version"]


def test_workout_parse_unknown_parser_version_fails_closed() -> None:
    """Unsupported parser versions must error, never silently downgrade."""
    vectors = _vectors(V5_VECTORS_PATH)
    reference = vectors["vectors"]["reference_gpx_file"]
    source_path = REPO_ROOT / reference["source_path"]
    activity = wp.parse_file_bytes(source_path.read_bytes(), reference["file_type"])

    with pytest.raises(Exception, match="unsupported canonicalization parser_version"):
        wp.hash_canonical_ride(
            activity,
            parser_version=vectors["unsupported_parser_version"],
        )

    with pytest.raises(Exception, match="unsupported parser_version"):
        wp.parse_file_bytes(
            source_path.read_bytes(),
            reference["file_type"],
            parser_version=vectors["unsupported_parser_version"],
        )
