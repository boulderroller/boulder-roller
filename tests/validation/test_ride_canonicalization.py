#!/usr/bin/env python3
"""
Ride canonicalization validation vectors.

Usage:
    cd backend && source venv/bin/activate
    pytest ../tests/validation/test_ride_canonicalization.py -v
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


VALIDATION_DIR = Path(__file__).parent
REPO_ROOT = VALIDATION_DIR.parent.parent
FIXTURE_PATH = REPO_ROOT / "workout-parse" / "tests" / "fixtures" / "canonical_v1_reference.gpx"
CURRENT_VECTOR_PATH = REPO_ROOT / "tests" / "fixtures" / "canonical_ride_v5_vectors.json"

if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from workout_parse_runtime import import_workout_parse_verified


EXPECTED_CANONICAL_JSON = (
    '{"parser_version":1,"samples":['
    '{"cadence_rpm":81,"dist_dm":null,"elev_dm":16005,"hr_bpm":141,'
    '"lat_e6":40123457,"lon_e6":-105123457,"power_w":205,"sec_offset":0,"speed_cms":null},'
    '{"cadence_rpm":85,"dist_dm":null,"elev_dm":16010,"hr_bpm":145,'
    '"lat_e6":40123460,"lon_e6":-105123460,"power_w":220,"sec_offset":1,"speed_cms":null},'
    '{"cadence_rpm":null,"dist_dm":null,"elev_dm":null,"hr_bpm":null,'
    '"lat_e6":null,"lon_e6":null,"power_w":null,"sec_offset":2,"speed_cms":null},'
    '{"cadence_rpm":null,"dist_dm":null,"elev_dm":15995,"hr_bpm":null,'
    '"lat_e6":40123470,"lon_e6":-105123470,"power_w":null,"sec_offset":3,"speed_cms":null}'
    '],"sport":"cycling","started_at_ms":1577836800000}'
)
EXPECTED_RIDE_HASH = "429a9a50c7fea255f284379e7e05b34c1fbb6fe64f90cd9415fb6a3232de33aa"


def test_reference_gpx_vector():
    wp = import_workout_parse_verified()
    activity = wp.parse_file_bytes(
        FIXTURE_PATH.read_bytes(), "gpx", parser_version=1
    )

    canonical = bytes(wp.canonicalize_ride(activity, parser_version=1))
    canonical_json = canonical.decode("utf-8")
    ride_hash = wp.hash_canonical_ride(activity, parser_version=1)

    assert canonical_json == EXPECTED_CANONICAL_JSON
    assert ride_hash == EXPECTED_RIDE_HASH
    assert ride_hash == hashlib.sha256(canonical).hexdigest()


def test_parser_version_constant_exported_and_used_as_default():
    wp = import_workout_parse_verified()
    activity = wp.parse_file_bytes(FIXTURE_PATH.read_bytes(), "gpx")
    fixture = json.loads(CURRENT_VECTOR_PATH.read_text(encoding="utf-8"))
    current_vector = fixture["vectors"]["reference_gpx_file"]

    assert wp.PARSER_VERSION_V1 == 1
    assert wp.PARSER_VERSION_V2 == 2
    assert wp.PARSER_VERSION_V3 == 3
    assert wp.PARSER_VERSION_V4 == 4
    assert wp.PARSER_VERSION_V5 == 5
    assert wp.CURRENT_PARSER_VERSION == 5
    canonical = bytes(wp.canonicalize_ride(activity))
    ride_hash = wp.hash_canonical_ride(activity)
    assert canonical == bytes(
        wp.canonicalize_ride(activity, parser_version=wp.CURRENT_PARSER_VERSION)
    )
    assert ride_hash == wp.hash_canonical_ride(
        activity, parser_version=wp.CURRENT_PARSER_VERSION
    )
    assert canonical.decode("utf-8") == current_vector["canonical_json"]
    assert ride_hash == current_vector["ride_hash"]
    assert ride_hash == hashlib.sha256(canonical).hexdigest()
