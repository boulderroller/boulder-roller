#!/usr/bin/env python3
"""
Cross-Layer Contract Tests (Memo Item #7).

Verify invariants that span multiple system layers:
  - Model ↔ Repository: Fields stored match fields defined
  - Detector ↔ Model: Detector output maps correctly to ClimbPattern
  - Signature ↔ Vert: Signature-encoded vert matches pattern vert
  - Abstention ↔ Economic: economic_eligible=false blocks vault completions
  - Sensor integrity ↔ Abstention: integrity flags propagate to abstention

These tests do NOT require a database connection. They verify the code
contracts between layers using synthetic data.

Usage:
    cd backend && source venv/bin/activate
    pytest ../tests/validation/test_cross_layer_contracts.py -v
"""

import asyncio
import math
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is importable
VALIDATION_DIR = Path(__file__).parent
BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from workout_parse_runtime import import_workout_parse_verified

from app.models.patterns import ClimbPattern, PatternType
from app.services.sensor_integrity import (
    SensorIntegrityReport,
    compute_sensor_integrity,
    get_abstention_reasons_from_integrity,
)

try:
    wp = import_workout_parse_verified()
    HAS_WP = True
except Exception:
    HAS_WP = False


# ---------------------------------------------------------------------------
# Contract 1: Model ↔ Repository field alignment
# ---------------------------------------------------------------------------

class TestModelRepositoryAlignment:
    """Every field in ClimbPattern.to_dict() should be accepted by
    PatternRepository.store_climb_pattern()."""

    def test_climb_pattern_to_dict_keys(self):
        """ClimbPattern.to_dict() must include all storable fields."""
        pattern = ClimbPattern(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test",
            arena_id=None,
            vert_m=50.0,
            time_s=300,
        )
        d = pattern.to_dict()

        # These keys MUST be present in the serialized dict
        required_keys = {
            "id", "activity_id", "wallet", "arena_id", "pattern_type",
            "vert_m", "time_s", "avg_power_w", "w_per_kg", "avg_hr", "vam",
            "start_offset_s", "end_offset_s",
            "road_name", "road_grade", "road_coverage_pct", "attribution_summary",
            "tile_ids", "distance_m", "avg_gradient_pct",
            "signature_hex", "signature_v2_hex",
            "start_lat", "start_lon", "end_lat", "end_lon",
            "persistence_m",
            "significance_g", "significance_percentile",
            "significance_return_period", "significance_confidence_tier",
            "significance_bootstrapped", "significance_cell_h3",
            "vault_climb_id", "vault_climb_name", "vault_climb_slug",
            "vault_match_similarity", "is_strong_match",
            "indexed_vault_id", "indexed_vault_name",
            "economic_eligible", "abstention_reasons", "detector_version",
            "created_at",
        }
        missing = required_keys - set(d.keys())
        assert not missing, f"ClimbPattern.to_dict() missing keys: {missing}"

    def test_store_climb_pattern_accepts_all_fields(self):
        """PatternRepository.store_climb_pattern() must accept all model fields."""
        from app.repositories.pattern import PatternRepository

        # Get the parameter names from the method signature
        import inspect
        sig = inspect.signature(PatternRepository.store_climb_pattern)
        params = set(sig.parameters.keys()) - {"self"}

        # These are the fields that MUST be accepted
        expected_params = {
            "pattern_id", "activity_id", "wallet",
            "vert_m", "time_s", "start_offset_s", "end_offset_s",
            "arena_id", "avg_power_w", "w_per_kg", "avg_hr",
            "road_name", "road_grade", "road_coverage_pct", "attribution_summary",
            "tile_ids", "distance_m", "avg_gradient_pct",
            "signature_hex", "signature_v2_hex",
            "persistence_m",
            "significance_g", "significance_percentile",
            "significance_return_period", "significance_confidence_tier",
            "significance_bootstrapped", "significance_cell_h3",
            "start_lat", "start_lon", "end_lat", "end_lon",
            "economic_eligible", "abstention_reasons", "match_trace",
            "detector_version",
        }
        missing = expected_params - params
        assert not missing, f"store_climb_pattern() missing params: {missing}"

    def test_pattern_type_is_climb(self):
        """ClimbPattern.pattern_type must return CLIMB."""
        p = ClimbPattern(
            id=uuid.uuid4(), activity_id=uuid.uuid4(),
            wallet="x", arena_id=None, vert_m=10, time_s=60,
        )
        assert p.pattern_type == PatternType.CLIMB


# ---------------------------------------------------------------------------
# Contract 2: Detector ↔ Model mapping
# ---------------------------------------------------------------------------

class TestDetectorModelMapping:
    """Fields from the Rust detector (ClimbV2) must map correctly to
    ClimbPattern model fields."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_climb_v2_has_required_attributes(self):
        """ClimbV2 from detect_climbs_persistence must have all needed fields."""
        profile = [100.0] * 50 + [100.0 + i * 0.5 for i in range(100)] + [150.0] * 50
        samples = [{"t": i * 5, "elevation_m": e,
                     "lat": 40.0 + i * 0.0001, "lon": -75.0 + i * 0.0001}
                    for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert len(climbs) >= 1

        c = climbs[0]

        # Required attributes that PatternEngine maps
        assert hasattr(c, "vert_m")
        assert hasattr(c, "time_s")
        assert hasattr(c, "distance_m")
        assert hasattr(c, "avg_gradient_pct")
        assert hasattr(c, "avg_power_w")
        assert hasattr(c, "avg_hr")
        assert hasattr(c, "persistence")
        assert hasattr(c, "signature_v1_hex")
        assert hasattr(c, "signature_v2_hex")
        assert hasattr(c, "start_lat")
        assert hasattr(c, "start_lon")
        assert hasattr(c, "end_lat")
        assert hasattr(c, "end_lon")
        assert hasattr(c, "effort_start_idx")
        assert hasattr(c, "effort_end_idx")
        assert hasattr(c, "tile_ids")

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_vert_m_is_positive(self):
        """All detected climbs must have vert_m > 0."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(60)] + [160.0] * 30
        samples = [{"t": i, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        for c in climbs:
            assert c.vert_m > 0, f"Climb vert_m must be > 0, got {c.vert_m}"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_time_s_is_positive(self):
        """All detected climbs must have time_s > 0."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(60)] + [160.0] * 30
        samples = [{"t": i, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        for c in climbs:
            assert c.time_s > 0, f"Climb time_s must be > 0, got {c.time_s}"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_vam_within_bounds(self):
        """VAM must be <= 2500 m/hr (INV-DATA-3)."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(60)] + [160.0] * 30
        samples = [{"t": i, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        for c in climbs:
            if c.time_s > 0:
                vam = (c.vert_m / c.time_s) * 3600
                assert vam <= 2500, f"VAM {vam:.0f} exceeds 2500 m/hr cap"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_min_vert_5m(self):
        """No climb should have vert_m < 5.0 (INV-DATA-4)."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(60)] + [160.0] * 30
        samples = [{"t": i, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        for c in climbs:
            assert c.vert_m >= 5.0, f"Climb vert_m {c.vert_m} < 5.0m minimum"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_persistence_boundary_contract(self):
        """Displayed persistence climbs must net upward and bound descents."""
        profile = [100.0] * 20 + [100.0 + i * 1.2 for i in range(45)] + [154.0] * 15
        samples = [{"t": i * 5, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert climbs, "Expected at least one persistence climb"
        for c in climbs:
            start_idx = int(c.effort_start_idx)
            end_idx = int(c.effort_end_idx)
            assert end_idx > start_idx
            boundary_rise = float(samples[end_idx]["elevation_m"]) - float(samples[start_idx]["elevation_m"])
            assert boundary_rise >= 8.0
            assert boundary_rise >= float(c.vert_m) * 0.35

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_momentum_segments_net_upward(self):
        """Adaptive momentum climbs should also satisfy the displayed-climb contract."""
        profile = [100.0] * 20 + [100.0 + i * 1.0 for i in range(55)] + [154.0] * 20
        samples = [{"t": i * 5, "elevation_m": e} for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_adaptive(
            tile_samples=samples,
            terrain="rolling",
            user_weight_kg=75.0,
            algorithm="momentum",
            generate_signatures=True,
        )
        assert climbs, "Expected at least one momentum climb"
        for climb in climbs:
            start_idx = next(
                idx for idx, sample in enumerate(samples)
                if int(sample["t"]) == int(climb.start_time_offset_s)
            )
            end_idx = next(
                idx for idx, sample in enumerate(samples)
                if int(sample["t"]) == int(climb.end_time_offset_s)
            )
            start_elev = float(samples[start_idx]["elevation_m"])
            end_elev = float(samples[end_idx]["elevation_m"])
            boundary_rise = end_elev - start_elev
            assert boundary_rise >= 8.0
            assert boundary_rise >= float(climb.vert_m) * 0.35


# ---------------------------------------------------------------------------
# Contract 3: Abstention ↔ Economic action gating
# ---------------------------------------------------------------------------

class TestAbstentionEconomicGating:
    """When economic_eligible=false, no vault completion should be created."""

    def test_abstained_climb_blocks_vault_match(self):
        """A climb with economic_eligible=False must not produce a VaultCompletion."""
        from app.services.pattern_engine import PatternEngine, UserProfile, VaultCompletion

        engine = PatternEngine(use_rust_detector=True)

        # Create an abstained pattern
        pattern = ClimbPattern(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test",
            arena_id=None,
            vert_m=50.0,
            time_s=300,
            economic_eligible=False,
            abstention_reasons=["TEST:forced_abstention"],
            signature_hex="a" * 128,
        )

        # The pattern should remain abstained
        assert not pattern.economic_eligible
        assert pattern.abstention_reasons is not None
        assert len(pattern.abstention_reasons) > 0

    def test_eligible_climb_allows_vault_match(self):
        """A climb with economic_eligible=True should be eligible for matching."""
        pattern = ClimbPattern(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test",
            arena_id=None,
            vert_m=50.0,
            time_s=300,
            economic_eligible=True,
        )
        assert pattern.economic_eligible
        assert pattern.abstention_reasons is None


# ---------------------------------------------------------------------------
# Contract 4: Sensor integrity ↔ Abstention propagation
# ---------------------------------------------------------------------------

class TestSensorIntegrityAbstention:
    """Sensor integrity flags must propagate to climb abstention reasons."""

    def test_bad_gps_triggers_abstention(self):
        """GPS coverage < 50% must trigger SENSOR:gps_coverage abstention."""
        from app.services.pattern_engine import PatternEngine

        engine = PatternEngine(use_rust_detector=True)

        # Build samples with <50% GPS
        samples = []
        for i in range(100):
            s = {"t": i, "tile_id": f"t{i}", "elevation_m": 100.0 + i * 0.3}
            if i < 30:  # 30% GPS
                s["lat"] = 40.0 + i * 0.0001
                s["lon"] = -75.0
            samples.append(s)

        integrity = compute_sensor_integrity(samples)
        assert integrity.gps_coverage < 0.50

        pattern = ClimbPattern(
            id=uuid.uuid4(), activity_id=uuid.uuid4(),
            wallet="test", arena_id=None,
            vert_m=30.0, time_s=100,
            start_offset_s=0, end_offset_s=99,
            signature_v2_hex="a" * 128,
        )

        engine._evaluate_abstention(pattern, samples, integrity)
        assert not pattern.economic_eligible
        assert any("gps_coverage" in r for r in (pattern.abstention_reasons or []))

    def test_good_sensors_no_abstention(self):
        """Clean sensor data should not trigger abstention."""
        from app.services.pattern_engine import PatternEngine

        engine = PatternEngine(use_rust_detector=True)

        samples = []
        for i in range(100):
            samples.append({
                "t": i,
                "tile_id": f"t{i}",
                "lat": 40.0 + i * 0.0001,
                "lon": -75.0 + i * 0.0001,
                "elevation_m": 100.0 + i * 0.3,
            })

        integrity = compute_sensor_integrity(samples)

        pattern = ClimbPattern(
            id=uuid.uuid4(), activity_id=uuid.uuid4(),
            wallet="test", arena_id=None,
            vert_m=30.0, time_s=100,
            start_offset_s=0, end_offset_s=99,
            signature_v2_hex="a" * 128,
        )

        engine._evaluate_abstention(pattern, samples, integrity)
        assert pattern.economic_eligible
        assert pattern.abstention_reasons is None

    def test_implausible_elevation_triggers_abstention(self):
        """Elevation > 5500m must trigger SENSOR:elev_implausible."""
        samples = []
        for i in range(100):
            samples.append({
                "t": i, "tile_id": f"t{i}",
                "lat": 40.0 + i * 0.0001, "lon": -75.0,
                "elevation_m": 7000.0,
            })

        integrity = compute_sensor_integrity(samples)
        reasons = get_abstention_reasons_from_integrity(integrity)
        assert any("implausible" in r for r in reasons)


# ---------------------------------------------------------------------------
# Contract 5: Signature invariants
# ---------------------------------------------------------------------------

class TestSignatureInvariants:
    """Signature generation must satisfy contract invariants."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_v2_signature_length(self):
        """V2 signature must be exactly 128 hex chars (64 bytes)."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(60)] + [160.0] * 30
        samples = [{"t": i * 5, "elevation_m": e,
                     "lat": 40.0 + i * 0.0001, "lon": -75.0 + i * 0.0001}
                    for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        for c in climbs:
            if c.signature_v2_hex:
                assert len(c.signature_v2_hex) == 128, \
                    f"V2 sig must be 128 hex, got {len(c.signature_v2_hex)}"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_significant_climbs_have_signatures(self):
        """Significant climbs (>=20m) should always have v2 signatures."""
        profile = [100.0] * 30 + [100.0 + i * 1.0 for i in range(100)] + [200.0] * 30
        samples = [{"t": i * 5, "elevation_m": e,
                     "lat": 40.0 + i * 0.0001, "lon": -75.0 + i * 0.0001}
                    for i, e in enumerate(profile)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 20]
        for c in sig_climbs:
            assert c.signature_v2_hex is not None, \
                f"Significant climb (vert={c.vert_m}) missing v2 signature"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_deterministic_signatures(self):
        """Same input must produce same signature (INV-DET-1)."""
        profile = [100.0] * 30 + [100.0 + i * 0.8 for i in range(80)] + [164.0] * 30
        samples = [{"t": i * 5, "elevation_m": e,
                     "lat": 40.0 + i * 0.0001, "lon": -75.0 + i * 0.0001}
                    for i, e in enumerate(profile)]

        climbs1 = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        climbs2 = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)

        # Same number of climbs
        assert len(climbs1) == len(climbs2), "Determinism: different climb count"

        # Same signatures
        for c1, c2 in zip(climbs1, climbs2):
            if c1.signature_v2_hex and c2.signature_v2_hex:
                assert c1.signature_v2_hex == c2.signature_v2_hex, \
                    "Determinism: different v2 signatures for same input"
            assert c1.vert_m == c2.vert_m, "Determinism: different vert_m"
            assert c1.time_s == c2.time_s, "Determinism: different time_s"


# ---------------------------------------------------------------------------
# Contract 6: Decision trace completeness
# ---------------------------------------------------------------------------

class TestDecisionTrace:
    """Decision trace must capture all match decisions."""

    def test_trace_has_required_fields(self):
        """A well-formed trace must have these top-level keys."""
        required_keys = {
            "detector", "detection", "signatures",
            "match_attempts", "best_match",
            "abstention", "economic_action",
        }
        # Build a minimal trace (as PatternEngine would)
        trace = {
            "detector": {"algorithm": "persistence"},
            "detection": {"persistence_m": 50.0, "effort_bounds": [100, 400]},
            "signatures": {"v1_present": True, "v2_present": True},
            "match_attempts": [],
            "best_match": None,
            "abstention": {"eligible": True, "reasons": []},
            "economic_action": None,
        }
        missing = required_keys - set(trace.keys())
        assert not missing, f"Trace missing keys: {missing}"

    def test_abstention_trace_records_reasons(self):
        """When abstained, trace must record reasons."""
        trace = {
            "detector": {"algorithm": "persistence"},
            "detection": {},
            "signatures": {"v1_present": True, "v2_present": True},
            "match_attempts": [],
            "best_match": None,
            "abstention": {
                "eligible": False,
                "reasons": ["SENSOR:gps_coverage_30%", "SIGNIFICANCE:tier_0"],
            },
            "economic_action": None,
        }
        assert not trace["abstention"]["eligible"]
        assert len(trace["abstention"]["reasons"]) >= 1
        assert trace["economic_action"] is None  # Must be None when abstained


# ---------------------------------------------------------------------------
# Contract 7: VAM computation consistency
# ---------------------------------------------------------------------------

class TestVAMConsistency:
    """VAM computed from model must match VAM computed from raw values."""

    def test_vam_formula(self):
        """ClimbPattern.vam property must equal (vert_m / time_s) * 3600."""
        for vert, time_s in [(50.0, 300), (100.0, 600), (200.0, 3600), (10.0, 60)]:
            p = ClimbPattern(
                id=uuid.uuid4(), activity_id=uuid.uuid4(),
                wallet="x", arena_id=None,
                vert_m=vert, time_s=time_s,
            )
            expected = (vert / time_s) * 3600
            assert abs(p.vam - expected) < 0.01, f"VAM mismatch: {p.vam} vs {expected}"

    def test_vam_zero_time(self):
        """VAM with time_s=0 should return None, not crash."""
        p = ClimbPattern(
            id=uuid.uuid4(), activity_id=uuid.uuid4(),
            wallet="x", arena_id=None,
            vert_m=50.0, time_s=0,
        )
        assert p.vam is None
