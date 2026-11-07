#!/usr/bin/env python3
"""
Adversarial Test Suite (Benchmark Tier 4).

Synthetic degenerate inputs designed to break the climb detector and
sensor integrity layer. Every test verifies:
  - No crash, no panic, no NaN in output
  - Detector produces 0 climbs (correct abstention) or reasonable climbs
  - Sensor integrity correctly flags bad data

Categories from BENCHMARK_V1.md:
  1. GPS sentinel flood
  2. Long pause (8 hrs)
  3. Barometric spike
  4. Sparse points (phone GPS)
  5. Zero elevation
  6. Null power
  7. Duplicate timestamps
  8. Max duration boundary
  9. Micro climb spam
  10. Single massive climb

Usage:
    cd backend && source venv/bin/activate
    pytest ../tests/validation/adversarial/ -v
"""

import math
import sys
import uuid
from pathlib import Path

import pytest

# Ensure backend is importable
BACKEND_DIR = Path(__file__).parent.parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    import workout_parse as wp
    HAS_WP = True
except ImportError:
    HAS_WP = False

from app.services.sensor_integrity import (
    SensorIntegrityReport,
    compute_sensor_integrity,
    get_abstention_reasons_from_integrity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_samples(n, dt=1, base_elev=100.0, lat=40.0, lon=-75.0, **overrides):
    """Generate n tile samples with optional overrides per sample."""
    samples = []
    for i in range(n):
        s = {
            "t": i * dt,
            "tile_id": f"8a2a1072{i:04x}fff",
            "lat": lat + i * 0.0001 if lat is not None else None,
            "lon": lon + i * 0.0001 if lon is not None else None,
            "elevation_m": base_elev,
        }
        s.update(overrides)
        samples.append(s)
    return samples


def to_samples(elevations, dt=5, lat=40.0, lon=-75.0):
    """Convert elevation list to tile sample dicts with GPS."""
    samples = []
    for i, e in enumerate(elevations):
        s = {
            "t": i * dt,
            "elevation_m": e,
        }
        if lat is not None:
            s["lat"] = lat + i * 0.0001
            s["lon"] = lon + i * 0.0001
        samples.append(s)
    return samples


def assert_no_nan(climbs):
    """Assert no NaN values in any climb attribute."""
    for c in climbs:
        assert not math.isnan(c.vert_m), f"NaN vert_m in climb"
        if c.distance_m is not None:
            assert not math.isnan(c.distance_m), f"NaN distance_m"
        if c.avg_gradient_pct is not None:
            assert not math.isnan(c.avg_gradient_pct), f"NaN avg_gradient_pct"
        if c.persistence is not None:
            assert not math.isnan(c.persistence), f"NaN persistence"


# ---------------------------------------------------------------------------
# 1. GPS Sentinel Flood
# ---------------------------------------------------------------------------

class TestGPSSentinelFlood:
    """FIT files can contain INT32_MIN/1e7 = -214.748 as GPS sentinel values.
    These must be rejected, not used for distance calculations."""

    def test_sensor_integrity_rejects_sentinels(self):
        """Sensor integrity should report 0% GPS coverage for sentinel-only data."""
        samples = []
        for i in range(100):
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": -214.748,  # FIT sentinel
                "lon": -214.748,
                "elevation_m": 100.0,
            })
        report = compute_sensor_integrity(samples)
        assert report.gps_coverage == 0.0, "Sentinel GPS should not count as valid"
        reasons = get_abstention_reasons_from_integrity(report)
        assert any("gps_coverage" in r for r in reasons)

    def test_null_island_rejected(self):
        """Null Island (0,0) should be treated as invalid GPS."""
        samples = []
        for i in range(100):
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": 0.0,
                "lon": 0.0,
                "elevation_m": 100.0,
            })
        report = compute_sensor_integrity(samples)
        assert report.gps_coverage == 0.0, "Null Island should not count as valid GPS"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_detector_handles_no_gps(self):
        """Detector should still find climbs from elevation even without GPS."""
        profile = [100.0] * 50 + [100.0 + i * 0.5 for i in range(100)] + [150.0] * 50
        samples = to_samples(profile, lat=None, lon=None)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        # Should find the 50m climb even without GPS
        sig = [c for c in climbs if c.vert_m >= 30]
        assert len(sig) >= 1, "Should detect climb even without GPS"


# ---------------------------------------------------------------------------
# 2. Long Pause (8 Hours)
# ---------------------------------------------------------------------------

class TestLongPause:
    """Device left running overnight mid-ride. Creates a massive time gap
    that could inflate climb duration or create fake patterns."""

    def _make_pause_samples(self):
        """100 samples, 8-hour gap, 100 more samples."""
        samples = []
        # Pre-pause: gentle climb
        for i in range(100):
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": 40.0 + i * 0.0001,
                "lon": -75.0 + i * 0.0001,
                "elevation_m": 100.0 + i * 0.3,
            })
        # Post-pause: flat riding (8 hours = 28800s later)
        for i in range(100):
            samples.append({
                "t": 28900 + i,
                "tile_id": f"tile_{100 + i}",
                "lat": 40.01 + i * 0.0001,
                "lon": -75.01 + i * 0.0001,
                "elevation_m": 130.0,
            })
        return samples

    def test_sensor_integrity_flags_gap(self):
        """8-hour gap should flag gap_ratio and max_gap."""
        samples = self._make_pause_samples()
        report = compute_sensor_integrity(samples)
        assert report.max_gap_s > 28000
        assert report.gap_ratio > 0.30
        assert any("gap_ratio" in f for f in report.flags)
        reasons = get_abstention_reasons_from_integrity(report)
        assert any("gap_ratio" in r for r in reasons)

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_detector_no_crash(self):
        """Detector should not crash on 8-hour gap.

        A detector may either suppress the climb entirely or return a display
        candidate, but the sensor integrity layer must make the stream
        economically ineligible. The key invariant is: no crash, no NaN, no
        panic, and no rewardable climb from an 8-hour recording gap.
        """
        samples = self._make_pause_samples()
        report = compute_sensor_integrity(samples)
        reasons = get_abstention_reasons_from_integrity(report)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        assert any("gap_ratio" in r for r in reasons)


# ---------------------------------------------------------------------------
# 3. Barometric Spike
# ---------------------------------------------------------------------------

class TestBarometricSpike:
    """Single-sample 500m elevation spike in an otherwise flat profile.
    Corrupt barometric data from pressure changes (airplane flyover, tunnel)."""

    def _make_spike_samples(self):
        samples = []
        for i in range(200):
            elev = 100.0
            if i == 100:
                elev = 600.0  # 500m spike for 1 sample
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": 40.0 + i * 0.0001,
                "lon": -75.0 + i * 0.0001,
                "elevation_m": elev,
            })
        return samples

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_spike_not_significant_climb(self):
        """A 1-sample 500m spike should NOT produce a significant climb."""
        samples = self._make_spike_samples()
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        # No single-sample event should be a significant climb
        for c in climbs:
            if c.vert_m >= 400:
                # If detected as a spike climb, it should be very short duration
                assert c.time_s <= 5, f"Spike climb vert={c.vert_m} with time={c.time_s}s is suspicious"

    def test_extreme_barometric_flagged(self):
        """Elevation > 5500m should be flagged as implausible."""
        samples = []
        for i in range(100):
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": 40.0 + i * 0.0001,
                "lon": -75.0 + i * 0.0001,
                "elevation_m": 6000.0,  # Corrupt
            })
        report = compute_sensor_integrity(samples)
        assert not report.elev_plausible
        reasons = get_abstention_reasons_from_integrity(report)
        assert any("implausible" in r for r in reasons)


# ---------------------------------------------------------------------------
# 4. Sparse Points (Phone GPS)
# ---------------------------------------------------------------------------

class TestSparsePoints:
    """Phone GPS recording at 1 sample per 30s. This can cause distance
    inflation from interpolation and poor gradient estimates."""

    def _make_sparse_samples(self, n=50, dt=30):
        """50 samples at 30s intervals = 25 min ride."""
        samples = []
        for i in range(n):
            samples.append({
                "t": i * dt,
                "tile_id": f"tile_{i}",
                "lat": 40.0 + i * 0.001,
                "lon": -75.0 + i * 0.001,
                "elevation_m": 100.0 + i * 2.0,  # Gradual climb
            })
        return samples

    def test_sensor_integrity_flags_sparse(self):
        """Sparse sampling (0.033 Hz) should be flagged."""
        samples = self._make_sparse_samples()
        report = compute_sensor_integrity(samples)
        assert report.median_interval_s >= 30
        assert any("sparse" in f for f in report.flags)

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_detector_handles_sparse(self):
        """Detector should not crash on sparse data.

        Sparse phone samples are not reward-grade evidence. Suppression is
        acceptable; if a detector returns a climb, downstream sensor integrity
        must still abstain it before economics.
        """
        samples = self._make_sparse_samples()
        report = compute_sensor_integrity(samples)
        reasons = get_abstention_reasons_from_integrity(report)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        assert any("sparse" in f for f in report.flags)
        assert "EFFORT:route_estimate_only" in reasons

        from app.models.patterns import ClimbPattern
        from app.services.pattern_engine import PatternEngine

        pattern = ClimbPattern(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test",
            arena_id=None,
            vert_m=80.0,
            time_s=600,
            start_offset_s=0,
            end_offset_s=samples[-1]["t"],
            signature_v2_hex="a" * 128,
        )
        PatternEngine(use_rust_detector=False)._evaluate_abstention(pattern, samples, report)
        assert pattern.economic_eligible is False
        assert any("sparse_sampling" in r for r in (pattern.abstention_reasons or []))


# ---------------------------------------------------------------------------
# 5. Zero Elevation
# ---------------------------------------------------------------------------

class TestZeroElevation:
    """All elevation_m = 0 (possible from indoor trainers or broken sensors).
    Should not cause division by zero or NaN gradients."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_zero_elevation_no_climbs(self):
        """Zero elevation should produce zero climbs, no crashes."""
        samples = to_samples([0.0] * 200)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        sig = [c for c in climbs if c.vert_m >= 5]
        assert len(sig) == 0, "Zero elevation should have 0 climbs"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_null_elevation_no_crash(self):
        """Missing elevation_m should not crash."""
        samples = [{"t": i, "lat": 40.0 + i * 0.0001, "lon": -75.0} for i in range(100)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        assert len(climbs) == 0, "No elevation data should produce 0 climbs"


# ---------------------------------------------------------------------------
# 6. Null Power
# ---------------------------------------------------------------------------

class TestNullPower:
    """No power data at all. Should not crash w_per_kg calculations."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_no_power_no_crash(self):
        """Climb detection without any power data should work fine."""
        profile = [100.0] * 50 + [100.0 + i * 0.5 for i in range(100)] + [150.0] * 50
        samples = to_samples(profile)
        # No power_w in samples
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        sig = [c for c in climbs if c.vert_m >= 30]
        assert len(sig) >= 1
        # avg_power_w should be None, not NaN
        for c in sig:
            assert c.avg_power_w is None or not math.isnan(c.avg_power_w)

    def test_sensor_integrity_zero_power_coverage(self):
        """Sensor integrity should report 0% power coverage."""
        samples = make_samples(100)
        # No power_w key
        report = compute_sensor_integrity(samples)
        assert report.power_coverage == 0.0


# ---------------------------------------------------------------------------
# 7. Duplicate Timestamps
# ---------------------------------------------------------------------------

class TestDuplicateTimestamps:
    """Multiple samples at t=0. Could cause division by zero in time deltas."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_all_same_timestamp(self):
        """All samples at t=0 should not crash."""
        samples = [{"t": 0, "elevation_m": 100.0 + i * 0.5} for i in range(100)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)

    def test_sensor_integrity_all_same_t(self):
        """All samples at t=0: regularity should still compute without crash."""
        samples = [{"t": 0, "tile_id": f"t{i}", "elevation_m": 100.0,
                     "lat": 40.0, "lon": -75.0} for i in range(50)]
        report = compute_sensor_integrity(samples)
        # Should not crash, gap_ratio should be 0 (no time range)
        assert report.sample_count == 50


# ---------------------------------------------------------------------------
# 8. Max Duration Boundary
# ---------------------------------------------------------------------------

class TestMaxDuration:
    """Activity exceeding 48 hours (172800 seconds). INV-DATA-6."""

    def _make_long_samples(self, duration_s=180000, interval=60):
        """50-hour activity at 1-minute intervals."""
        samples = []
        t = 0
        i = 0
        while t < duration_s:
            samples.append({
                "t": t,
                "tile_id": f"tile_{i}",
                "lat": 40.0 + (i % 1000) * 0.0001,
                "lon": -75.0 + (i % 1000) * 0.0001,
                "elevation_m": 100.0 + (t % 3600) * 0.01,
            })
            t += interval
            i += 1
        return samples

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_long_duration_no_crash(self):
        """50-hour activity should not crash the detector."""
        samples = self._make_long_samples()
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)

    def test_sensor_integrity_long_ride(self):
        """Long ride should still compute integrity."""
        samples = self._make_long_samples(duration_s=50000, interval=60)
        report = compute_sensor_integrity(samples)
        assert report.integrity_score > 0


# ---------------------------------------------------------------------------
# 9. Micro Climb Spam
# ---------------------------------------------------------------------------

class TestMicroClimbSpam:
    """100 x 3m oscillations. Tests noise gate (tau = 3.0m Gumbel EVT).
    Should produce 0 significant climbs, not 100."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_micro_oscillations_filtered(self):
        """100 x 3m oscillations should produce 0 significant climbs."""
        profile = []
        for i in range(100):
            # 3m oscillation: up 3, down 3
            for j in range(10):
                profile.append(100.0 + j * 0.3)
            for j in range(10):
                profile.append(103.0 - j * 0.3)

        samples = to_samples(profile)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        sig = [c for c in climbs if c.vert_m >= 10]
        assert len(sig) == 0, f"Micro oscillations should not produce significant climbs, got {len(sig)}"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_sub_noise_gate_filtered(self):
        """Oscillations below the 3m noise gate should produce 0 climbs."""
        profile = []
        for i in range(500):
            profile.append(100.0 + 2.5 * math.sin(i * 0.1))  # 2.5m amplitude

        samples = to_samples(profile)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        assert len(climbs) == 0, f"Sub-noise-gate oscillations should produce 0 climbs, got {len(climbs)}"


# ---------------------------------------------------------------------------
# 10. Single Massive Climb
# ---------------------------------------------------------------------------

class TestSingleMassiveClimb:
    """3000m continuous gain. Tests overflow in signature encoding and
    gradient clamping. Analogous to climbing Mt. Ventoux x3."""

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_massive_climb_detected(self):
        """3000m climb should be detected without overflow."""
        # 3000m over 6000 samples at 1s = 100 min, avg gradient ~5%
        profile = [100.0 + i * 0.5 for i in range(6000)]
        samples = to_samples(profile, dt=1)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        sig = [c for c in climbs if c.vert_m >= 2000]
        assert len(sig) >= 1, f"Should detect the massive 3000m climb, got {len(sig)} significant"
        # Verify vert is close to expected
        biggest = max(climbs, key=lambda c: c.vert_m)
        assert biggest.vert_m >= 2500, f"Biggest climb only {biggest.vert_m}m, expected ~3000m"

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_massive_climb_has_signature(self):
        """Massive climb should still get a valid signature."""
        profile = [100.0 + i * 0.5 for i in range(6000)]
        samples = to_samples(profile, dt=1)
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 2000]
        if sig_climbs:
            c = sig_climbs[0]
            assert c.signature_v2_hex is not None, "Massive climb should have v2 signature"
            assert len(c.signature_v2_hex) == 128, f"Signature should be 64 bytes (128 hex), got {len(c.signature_v2_hex)}"


# ---------------------------------------------------------------------------
# Bonus: Combined Adversarial Scenarios
# ---------------------------------------------------------------------------

class TestCombinedAdversarial:
    """Multiple adversarial conditions combined."""

    def test_empty_samples(self):
        """Empty sample list should produce valid integrity report."""
        report = compute_sensor_integrity([])
        assert report.sample_count == 0
        assert report.integrity_score == 0.0

    def test_single_sample(self):
        """Single sample should not crash."""
        report = compute_sensor_integrity([{"t": 0, "tile_id": "x"}])
        assert report.sample_count == 1
        assert report.integrity_score == 0.0

    @pytest.mark.skipif(not HAS_WP, reason="workout_parse not built")
    def test_all_none_values(self):
        """Samples with all None values should not crash."""
        samples = [{"t": i} for i in range(50)]
        climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert_no_nan(climbs)
        assert len(climbs) == 0

    def test_negative_elevation(self):
        """Dead Sea elevation (-430m) should be plausible."""
        samples = make_samples(100, base_elev=-430.0)
        report = compute_sensor_integrity(samples)
        assert report.elev_plausible, "Dead Sea elevation should be plausible"
        assert report.elev_min_m == -430.0

    def test_gps_teleportation_and_bad_elev(self):
        """Combined GPS teleportation + bad elevation should compound flags."""
        samples = []
        for i in range(100):
            lat = 40.0 + i * 0.0001
            if i in (25, 50, 75, 90):
                lat += 2.0  # ~222km teleportation
            samples.append({
                "t": i,
                "tile_id": f"tile_{i}",
                "lat": lat,
                "lon": -75.0,
                "elevation_m": 8000.0,  # Implausible
            })
        report = compute_sensor_integrity(samples)
        assert not report.elev_plausible
        assert report.gps_jump_count >= 4
        reasons = get_abstention_reasons_from_integrity(report)
        assert len(reasons) >= 2, f"Should have multiple abstention reasons, got {reasons}"
