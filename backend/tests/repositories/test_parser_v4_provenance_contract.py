from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUST_CANONICALIZE = REPO_ROOT / "workout-parse/src/canonicalize.rs"
RUST_BINDINGS = REPO_ROOT / "workout-parse/src/lib.rs"
MOBILE_CANONICALIZE = REPO_ROOT / "mobile/src/lib/canonicalize.ts"
VECTOR = REPO_ROOT / "tests/fixtures/canonical_ride_v4_vectors.json"
CANONICAL_SQL = REPO_ROOT / "backend/sql/127_parser_v4_climb_authority.sql"
SUPABASE_SQL = (
    REPO_ROOT
    / "backend/supabase/migrations/20260715_135_parser_v4_climb_authority.sql"
)

IMPLEMENTATION_COMMIT = "bb7604ddc0af3f983d0a21191bf27bddfa463e80"
DETECTOR_PARAMS_HASH = (
    "a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2"
)
DETECTOR_PARAMS = {
    "candidate_ambiguity_policy": "abstain",
    "canonical_signature_smoothing_window_samples": 5,
    "dct_match_coeffs": 6,
    "endpoint_max_distance_m": 150,
    "geometry_tolerance": 0.25,
    "h3_match_max_grid_distance": 3,
    "h3_match_resolution": 7,
    "h3_undefined_policy": "reject",
    "native_match_threshold": 0.08,
    "native_probable_match_threshold": 0.15,
    "null_island_policy": "reject",
    "oriented_endpoints_required": True,
    "osm_reward_dependency": False,
    "reward_min_similarity": 0.9,
    "sample_space": "timestamped_finite_elevation_stable_time_order",
    "signature_format_version": 2,
    "v1_reward_fallback": False,
}


def test_v4_remains_replayable_while_v5_is_explicit_current() -> None:
    rust = RUST_CANONICALIZE.read_text(encoding="utf-8")
    bindings = RUST_BINDINGS.read_text(encoding="utf-8")
    mobile = MOBILE_CANONICALIZE.read_text(encoding="utf-8")

    assert "pub const PARSER_VERSION_V4: u32 = 4;" in rust
    assert "pub const PARSER_VERSION_V5: u32 = 5;" in rust
    assert "CURRENT_PARSER_VERSION: u32 = PARSER_VERSION_V5;" in rust
    assert "export const PARSER_VERSION_V4 = 4;" in mobile
    assert "export const PARSER_VERSION_V5 = 5;" in mobile
    assert "CURRENT_PARSER_VERSION = PARSER_VERSION_V5;" in mobile

    for version in (1, 2, 3, 4, 5):
        assert f"PARSER_VERSION_V{version}" in rust
        assert f"PARSER_VERSION_V{version}" in mobile
        assert (
            f'm.add("PARSER_VERSION_V{version}", PARSER_VERSION_V{version})?;'
            in bindings
        )


def test_v4_fixture_is_new_exact_provenance_without_mutating_v3() -> None:
    fixture = json.loads(VECTOR.read_text(encoding="utf-8"))
    assert fixture["parser_version"] == 4

    expected_hashes = {
        "rust_sample_activity": (
            "80a4190c9817eb9cd73cc8abcc8de151355d53a3dfb29487a60d7f192d4f7387"
        ),
        "reference_gpx_file": (
            "8c9ec4fba817ad09c45f1e56e5e8917bc4656c673c39062901da14c524b4af00"
        ),
    }
    for name, expected_hash in expected_hashes.items():
        vector = fixture["vectors"][name]
        canonical = vector["canonical_json"].encode("utf-8")
        assert json.loads(canonical)["parser_version"] == 4
        assert hashlib.sha256(canonical).hexdigest() == expected_hash
        assert vector["ride_hash"] == expected_hash

    v3 = json.loads(
        (REPO_ROOT / "tests/fixtures/canonical_ride_v3_vectors.json").read_text(
            encoding="utf-8"
        )
    )
    assert v3["parser_version"] == 3
    for name, v4_vector in fixture["vectors"].items():
        v3_vector = v3["vectors"][name]
        v4_canonical = json.loads(v4_vector["canonical_json"])
        v4_canonical["parser_version"] = 3
        assert v4_canonical == json.loads(v3_vector["canonical_json"])
        for source_key in ("activity", "file_type", "source_path"):
            assert v4_vector.get(source_key) == v3_vector.get(source_key)
    assert (
        v3["vectors"]["rust_sample_activity"]["ride_hash"]
        == "d2f44353315fe41c0005a41bfdb3584edf8e7bf3d377b690f41024c390bb6a01"
    )


def test_v4_pipeline_registration_is_exact_idempotent_and_mirrored() -> None:
    canonical = CANONICAL_SQL.read_text(encoding="utf-8")
    supabase = SUPABASE_SQL.read_text(encoding="utf-8")
    assert canonical == supabase

    detector_params_json = json.dumps(
        DETECTOR_PARAMS, sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(detector_params_json.encode("utf-8")).hexdigest() == (
        DETECTOR_PARAMS_HASH
    )
    assert f"'{detector_params_json}'::JSONB" in canonical

    assert "'4-ftp-v1'" in canonical
    assert "ride_parser_version IS DISTINCT FROM 4" in canonical
    assert f"'{IMPLEMENTATION_COMMIT}'" in canonical
    assert f"'{DETECTOR_PARAMS_HASH}'" in canonical
    assert "'canonical_v2'" in canonical
    assert "'2.0.0'" in canonical
    assert "'dct6-h3r7-geometry25-oriented150-sim090'" in canonical
    assert "'ride_effort_policy_2026_07_14_ftp_v1'" in canonical
    assert "inactive and cannot be reactivated" in canonical
    assert "WHERE deactivated_at IS NULL AND id <> v_v4_id" in canonical
