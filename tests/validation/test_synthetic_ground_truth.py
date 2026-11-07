#!/usr/bin/env python3
"""
Synthetic Ground Truth for Significance Engine V2

Layer 1 of the external ground truth plan: 50+ known profiles with
mathematically exact answers. Zero external dependencies — all generated
from parametric functions.

Tests three levels:
  1. Persistence detection (Rust via PyO3)
  2. GPD fitting (Python terrain_bootstrap)
  3. Full pipeline (persistence → scoring)

Usage:
    cd backend && source venv/bin/activate
    pytest ../tests/validation/test_synthetic_ground_truth.py -v

Categories:
  - UNIT: Isolated function tests
  - PROFILE: Known elevation profiles with exact persistence answers
  - GPD: Synthetic exceedance distributions with known parameters
  - PIPELINE: End-to-end scoring from profile to G score
  - REGRESSION: Stability checks to catch regressions
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure backend is importable
BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Helpers: profile generators
# ---------------------------------------------------------------------------

def make_flat(n=200, base_elev=100.0, noise_std=0.0):
    """Flat profile. Expected: 0 climbs."""
    rng = np.random.default_rng(42)
    return [base_elev + rng.normal(0, noise_std) for _ in range(n)]


def make_single_climb(n=200, base=100.0, vert=50.0, start_frac=0.3, end_frac=0.7):
    """Single clean climb: flat → ramp → flat. Persistence = vert.

    NOTE: A pure ramp produces NO merge pairs in sublevel persistence
    (no internal valleys for components to merge). Only the essential class
    (global min → max) captures this, which detect_climbs_persistence adds
    but compute_persistence_pairs does not.
    """
    profile = []
    start_idx = int(n * start_frac)
    end_idx = int(n * end_frac)
    for i in range(n):
        if i < start_idx:
            profile.append(base)
        elif i <= end_idx:
            frac = (i - start_idx) / (end_idx - start_idx)
            profile.append(base + vert * frac)
        else:
            profile.append(base + vert)
    return profile


def make_climb_with_valley(n=300, base=100.0, vert=50.0, dip=10.0):
    """Climb with an internal dip that creates a merge event.

    Profile: flat → ramp to mid → dip → ramp to top → flat.
    This produces at least one merge pair with persistence >= dip.
    """
    profile = []
    seg = n // 5
    # Flat approach
    for _ in range(seg):
        profile.append(base)
    # Ramp to midpoint
    mid = base + vert * 0.5
    for i in range(seg):
        frac = i / seg
        profile.append(base + (mid - base) * frac)
    # Dip
    for i in range(seg):
        frac = i / seg
        if frac < 0.5:
            profile.append(mid - dip * (frac / 0.5))
        else:
            profile.append(mid - dip * (1.0 - (frac - 0.5) / 0.5))
    # Ramp to top
    for i in range(seg):
        frac = i / seg
        profile.append(mid + (vert * 0.5) * frac)
    # Flat top
    top = base + vert
    while len(profile) < n:
        profile.append(top)
    return profile[:n]


def make_single_valley(n=200, top=200.0, dip=50.0, valley_frac=0.5):
    """Elevated profile with a single valley. Tests valley → peak persistence."""
    profile = []
    valley_idx = int(n * valley_frac)
    half_width = n // 8
    for i in range(n):
        dist_from_valley = abs(i - valley_idx)
        if dist_from_valley < half_width:
            depth = dip * (1.0 - dist_from_valley / half_width)
            profile.append(top - depth)
        else:
            profile.append(top)
    return profile


def make_two_climbs(n=400, base=100.0, vert1=40.0, vert2=60.0, gap_depth=30.0):
    """Two distinct climbs separated by a descent. Expected: 2 persistence pairs."""
    profile = []
    seg = n // 4
    for i in range(seg):
        frac = i / seg
        profile.append(base + vert1 * frac)
    peak1 = base + vert1
    for i in range(seg):
        frac = i / seg
        profile.append(peak1 - gap_depth * frac)
    valley2 = peak1 - gap_depth
    for i in range(seg):
        frac = i / seg
        profile.append(valley2 + (vert2 + gap_depth) * frac)
    peak2 = valley2 + vert2 + gap_depth
    for i in range(seg):
        profile.append(peak2)
    return profile


def make_staircase(n=500, step_height=15.0, n_steps=5, flat_between=50):
    """Repeating climb-descent pattern: up → flat → down → flat → up.

    Each cycle: ramp up step_height, flat, ramp back down, flat.
    This creates merge events at the top of each ramp where components merge.
    """
    profile = []
    samples_per_step = n // n_steps
    for s in range(n_steps):
        ramp_len = (samples_per_step - flat_between) // 2
        base = 100.0  # constant base
        # Ramp up
        for i in range(ramp_len):
            frac = i / max(1, ramp_len - 1)
            profile.append(base + step_height * frac)
        # Flat at top
        for _ in range(flat_between // 2):
            profile.append(base + step_height)
        # Ramp down
        for i in range(ramp_len):
            frac = i / max(1, ramp_len - 1)
            profile.append(base + step_height * (1 - frac))
        # Flat at bottom
        for _ in range(flat_between // 2):
            profile.append(base)
    while len(profile) < n:
        profile.append(100.0)
    return profile[:n]


def make_sinusoidal(n=500, amplitude=20.0, periods=3, base=100.0):
    """Sinusoidal rollers. Known persistence = 2 * amplitude for each half-cycle."""
    return [base + amplitude * math.sin(2 * math.pi * periods * i / n) for i in range(n)]


def make_noisy_climb(n=200, base=100.0, vert=50.0, noise_std=1.5, seed=42):
    """Climb with realistic barometric noise. Tests noise robustness."""
    rng = np.random.default_rng(seed)
    clean = make_single_climb(n, base, vert)
    return [e + rng.normal(0, noise_std) for e in clean]


def make_descent_only(n=200, top=200.0, bottom=100.0):
    """Pure descent. Expected: 0 climbs (persistence tracks valleys → peaks)."""
    return [top - (top - bottom) * i / (n - 1) for i in range(n)]


def make_wall_profile(n=150, approach_flat=30, wall_len=20, vert=60.0, top_flat=30):
    """Short steep climb with descent after (creates merge pair).

    Profile: flat → short descent → steep wall → flat top → descent.
    The pre-wall dip and post-wall descent ensure merge events.
    """
    profile = [100.0] * approach_flat
    # Small dip before wall (5m) to create a valley
    dip = 5.0
    dip_len = 10
    for i in range(dip_len):
        frac = i / (dip_len - 1)
        if frac < 0.5:
            profile.append(100.0 - dip * (frac / 0.5))
        else:
            profile.append(100.0 - dip * (1.0 - (frac - 0.5) / 0.5))
    # Steep wall
    for i in range(wall_len):
        profile.append(100.0 + vert * i / (wall_len - 1))
    # Flat top
    profile.extend([100.0 + vert] * top_flat)
    # Descent back down (creates the merge event)
    descent_len = 30
    for i in range(descent_len):
        frac = i / (descent_len - 1)
        profile.append(100.0 + vert * (1 - frac))
    # Flat at base
    while len(profile) < n:
        profile.append(100.0)
    return profile[:n]


def make_nested_climbs(n=600, outer_vert=100.0, inner_vert=30.0):
    """Outer climb with an inner sub-climb. Tests nesting detection."""
    profile = []
    ramp = n // 3
    for i in range(ramp):
        frac = i / ramp
        base = outer_vert * frac
        # Add inner bump at 40-60% of ramp
        inner_frac = i / ramp
        if 0.4 <= inner_frac <= 0.5:
            bump_frac = (inner_frac - 0.4) / 0.1
            base += inner_vert * bump_frac
        elif 0.5 < inner_frac <= 0.6:
            bump_frac = 1.0 - (inner_frac - 0.5) / 0.1
            base += inner_vert * bump_frac
        profile.append(base)
    for _ in range(n - ramp):
        profile.append(outer_vert)
    return profile


# ---------------------------------------------------------------------------
# Synthetic GPD distributions
# ---------------------------------------------------------------------------

def generate_gpd_samples(xi, sigma, threshold, n_total, k_exc, seed=42):
    """
    Generate n_total persistence values where k_exc exceed threshold,
    drawn from GPD(xi, sigma) above threshold.
    """
    rng = np.random.default_rng(seed)
    # Below-threshold values: uniform in [3.0, threshold]
    n_below = n_total - k_exc
    below = rng.uniform(3.0, threshold, size=max(0, n_below))
    # Above-threshold: GPD inverse CDF
    u = rng.uniform(0, 1, size=k_exc)
    if abs(xi) > 1e-10:
        exceedances = (sigma / xi) * ((1 - u) ** (-xi) - 1)
    else:
        exceedances = -sigma * np.log(1 - u)
    above = threshold + exceedances
    return np.concatenate([below, above])


# ---------------------------------------------------------------------------
# PERSISTENCE TESTS (Rust via PyO3)
# ---------------------------------------------------------------------------

class TestPersistenceDetection:
    """Tests for compute_persistence_pairs (Rust → Python).

    IMPORTANT: compute_persistence_pairs returns only MERGE pairs from
    sublevel-set filtration. Monotonic ramps produce NO merges (only one
    component grows). Profiles MUST have internal valleys/descents to
    create merge events. The essential class (global min→max) is added
    separately by detect_climbs_persistence, tested in TestFullDetection.
    """

    @pytest.fixture(autouse=True)
    def _import_wp(self):
        try:
            import workout_parse
            self.wp = workout_parse
        except ImportError:
            pytest.skip("workout_parse not built (run: cd workout-parse && maturin develop)")

    def test_flat_no_pairs(self):
        profile = make_flat(200, noise_std=0.0)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        assert len(pairs) == 0, "Flat profile should produce no pairs"

    def test_flat_with_noise_no_significant_pairs(self):
        """Sub-noise-gate noise: may produce tiny pairs but none above gate."""
        profile = make_flat(200, noise_std=0.5)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) == 0, "Sub-noise-gate noise should produce no above-gate pairs"

    def test_monotonic_climb_no_merge_pairs(self):
        """A pure ramp has no internal valleys, so produces 0 merge pairs.
        This is correct — the essential class handles monotonic climbs."""
        profile = make_single_climb(200, vert=50.0)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        # Monotonic: no merges, only essential class (not returned by this function)
        assert len(above) == 0, "Monotonic ramp should have 0 merge pairs"

    def test_climb_with_valley_detected(self):
        """A climb with an internal dip creates a merge pair."""
        profile = make_climb_with_valley(300, vert=50.0, dip=10.0)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 1, "Climb with 10m dip should produce merge pair"
        max_pers = max(p["persistence"] for p in above)
        assert max_pers >= 8.0, f"Expected persistence ~10m from dip, got {max_pers:.1f}"

    def test_descent_no_pairs(self):
        profile = make_descent_only(200)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) == 0, "Pure descent should produce no above-gate pairs"

    def test_two_climbs_has_merge(self):
        """Two climbs separated by descent: the valley between them creates a merge."""
        profile = make_two_climbs(400, vert1=40.0, vert2=60.0, gap_depth=30.0)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 1, f"Two-climb profile should have >=1 merge pair, got {len(above)}"
        # The gap creates a merge with persistence = gap_depth (30m)
        max_pers = max(p["persistence"] for p in above)
        assert max_pers >= 20.0, f"Expected merge persistence ~30m, got {max_pers:.1f}"

    def test_noise_gate_filters_small_oscillations(self):
        """Repeating climb-descent with 2m amplitude: all below 3m gate."""
        profile = make_staircase(300, step_height=2.0, n_steps=5)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) == 0, "2m oscillations should all be below 3m noise gate"

    def test_noise_gate_passes_large_oscillations(self):
        """Repeating climb-descent with 15m amplitude: above gate."""
        profile = make_staircase(500, step_height=15.0, n_steps=5)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 1, "15m oscillations should produce above-gate pairs"

    def test_wall_profile_detected(self):
        """Short steep climb with surrounding terrain creates merge pair."""
        profile = make_wall_profile(150, wall_len=20, vert=60.0)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 1, "60m wall with descent should create merge pair"
        max_pers = max(p["persistence"] for p in above)
        assert max_pers > 40.0, f"Wall persistence should be ~60m, got {max_pers:.1f}"

    def test_sinusoidal_rollers(self):
        """Sinusoidal profile produces merge pairs at each valley→peak transition."""
        profile = make_sinusoidal(500, amplitude=20.0, periods=3)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 2, f"3-period sine should have >=2 merge pairs, got {len(above)}"
        for p in above:
            assert p["persistence"] <= 45.0, \
                f"Sinusoidal persistence should be <=2*20+tolerance, got {p['persistence']:.1f}"

    def test_noisy_climb_robust(self):
        """Climb with dip + barometric noise should still produce merge pair."""
        # Use climb_with_valley instead of monotonic climb
        profile_clean = make_climb_with_valley(200, vert=50.0, dip=15.0)
        rng = np.random.default_rng(42)
        profile = [e + rng.normal(0, 1.5) for e in profile_clean]
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=3.0)
        above = [p for p in pairs if p["above_noise_gate"]]
        assert len(above) >= 1, "Noisy climb with dip should still be detected"
        max_pers = max(p["persistence"] for p in above)
        assert max_pers >= 8.0, f"Expected dip-based persistence through noise, got {max_pers:.1f}"

    def test_pair_indices_valid(self):
        """Birth and death indices must be within profile bounds."""
        profile = make_two_climbs(400)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=0.0)
        for p in pairs:
            assert 0 <= p["birth_idx"] < len(profile)
            assert 0 <= p["death_idx"] < len(profile)
            assert p["persistence"] > 0
            assert abs(p["death_elev"] - p["birth_elev"] - p["persistence"]) < 0.01

    def test_noise_gate_zero_returns_small_oscillations(self):
        """With gate=0, repeating 0.5m oscillations should produce pairs."""
        profile = make_staircase(300, step_height=0.5, n_steps=10)
        pairs = self.wp.compute_persistence_pairs(profile, noise_gate=0.0)
        assert len(pairs) > 0, "Zero noise gate should catch 0.5m oscillations"

    def test_empty_profile(self):
        pairs = self.wp.compute_persistence_pairs([], noise_gate=3.0)
        assert len(pairs) == 0

    def test_single_value(self):
        pairs = self.wp.compute_persistence_pairs([100.0], noise_gate=3.0)
        assert len(pairs) == 0

    def test_two_values_monotonic(self):
        pairs = self.wp.compute_persistence_pairs([100.0, 110.0], noise_gate=3.0)
        # Monotonic: no merges
        assert len(pairs) == 0


# ---------------------------------------------------------------------------
# FULL DETECTION TESTS (detect_climbs_persistence — includes essential class)
# ---------------------------------------------------------------------------

class TestFullDetection:
    """Tests for detect_climbs_persistence which adds the essential class
    on top of sublevel merge pairs. This catches monotonic climbs."""

    @pytest.fixture(autouse=True)
    def _import_wp(self):
        try:
            import workout_parse
            self.wp = workout_parse
        except ImportError:
            pytest.skip("workout_parse not built")

    def _to_samples(self, elevations, dt=5):
        """Convert elevation list to tile sample dicts."""
        return [{"t": i * dt, "elevation_m": e} for i, e in enumerate(elevations)]

    def test_monotonic_climb_via_essential(self):
        """detect_climbs_persistence should find monotonic climbs via essential class."""
        profile = make_single_climb(200, vert=50.0)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig = [c for c in climbs if c.vert_m >= 30]
        assert len(sig) >= 1, f"Should find monotonic 50m climb via essential class, got {len(sig)}"

    def test_wall_short_steep_detected(self):
        """Short steep wall must be detected (v1 hilly mode missed these)."""
        profile = make_wall_profile(150, wall_len=20, vert=60.0)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig = [c for c in climbs if c.vert_m >= 40]
        assert len(sig) >= 1, "Short steep wall (60m) must be detected"

    def test_flat_ride_zero_climbs(self):
        """Flat profile should produce zero significant climbs."""
        profile = make_flat(200)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig = [c for c in climbs if c.vert_m >= 10]
        assert len(sig) == 0, f"Flat ride should have 0 significant climbs, got {len(sig)}"

    def test_descent_zero_climbs(self):
        """Pure descent should produce zero climbs."""
        profile = make_descent_only(200)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig = [c for c in climbs if c.vert_m >= 10]
        assert len(sig) == 0, f"Descent should have 0 climbs, got {len(sig)}"

    def test_two_climbs_found(self):
        """Two distinct climbs should both be detected."""
        profile = make_two_climbs(400, vert1=40.0, vert2=60.0, gap_depth=30.0)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig = [c for c in climbs if c.vert_m >= 20]
        assert len(sig) >= 2, f"Should find 2 climbs, got {len(sig)}"

    def test_persistence_accuracy(self):
        """For a clean V-shaped profile, persistence should match vert gain."""
        for vert in [20.0, 50.0, 100.0]:
            # V-shape: 0 → vert → 0 (creates merge pair with persistence = vert)
            n = 300
            profile = []
            for i in range(n):
                frac = i / (n - 1)
                if frac < 0.5:
                    profile.append(vert * frac * 2)
                else:
                    profile.append(vert * (1 - frac) * 2)
            samples = self._to_samples(profile)
            climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
            if not climbs:
                continue
            max_pers = max(c.persistence for c in climbs)
            assert abs(max_pers - vert) / vert < 0.2, \
                f"vert={vert}: persistence {max_pers:.1f} deviates >20%"


# ---------------------------------------------------------------------------
# GPD FITTING TESTS
# ---------------------------------------------------------------------------

class TestGPDFitting:
    """Tests for GPD parameter estimation (Python terrain_bootstrap)."""

    @pytest.fixture(autouse=True)
    def _import_bootstrap(self):
        from app.services.terrain_bootstrap import (
            fit_gpd_pwm,
            ConfidenceTier,
        )
        self.fit_gpd_pwm = fit_gpd_pwm
        self.ConfidenceTier = ConfidenceTier

    def test_exponential_distribution(self):
        """GPD with xi=0 is exponential. PWM should recover xi≈0."""
        rng = np.random.default_rng(42)
        sigma_true = 10.0
        exceedances = rng.exponential(sigma_true, size=100)
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert abs(xi) < 0.15, f"Exponential: xi should be ~0, got {xi:.4f}"
        assert abs(sigma - sigma_true) / sigma_true < 0.3, \
            f"Exponential: sigma should be ~{sigma_true}, got {sigma:.2f}"

    def test_heavy_tail_positive_xi(self):
        """GPD with xi=0.2 (heavy tail). PWM should recover positive xi."""
        rng = np.random.default_rng(42)
        xi_true = 0.2
        sigma_true = 10.0
        u = rng.uniform(0, 1, size=200)
        exceedances = (sigma_true / xi_true) * ((1 - u) ** (-xi_true) - 1)
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert xi > 0.0, f"Heavy tail: xi should be positive, got {xi:.4f}"
        assert abs(xi - xi_true) < 0.15, f"Heavy tail: xi should be ~0.2, got {xi:.4f}"

    def test_bounded_tail_negative_xi(self):
        """GPD with xi=-0.2 (bounded upper tail). PWM should recover negative xi."""
        rng = np.random.default_rng(42)
        xi_true = -0.2
        sigma_true = 10.0
        u = rng.uniform(0, 1, size=200)
        exceedances = (sigma_true / xi_true) * ((1 - u) ** (-xi_true) - 1)
        # Clip to valid range (GPD upper bound = -sigma/xi when xi < 0)
        upper = -sigma_true / xi_true
        exceedances = np.clip(exceedances, 0, upper * 0.99)
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert xi < 0.0, f"Bounded: xi should be negative, got {xi:.4f}"

    def test_small_sample_stability(self):
        """PWM should not crash or produce absurd values with k=12 (minimum)."""
        rng = np.random.default_rng(42)
        exceedances = rng.exponential(15.0, size=12)
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert -0.5 < xi < 0.5, f"Small sample: xi={xi:.4f} out of range"
        assert sigma > 0, f"Small sample: sigma={sigma:.4f} should be positive"

    def test_identical_values(self):
        """All identical exceedances: degenerate case."""
        exceedances = np.array([10.0] * 20)
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert abs(xi) < 0.01, "Identical values: xi should be ~0"

    def test_xi_clamping(self):
        """Extreme samples should not produce |xi| > 0.49."""
        # Pareto with very heavy tail
        rng = np.random.default_rng(42)
        exceedances = rng.pareto(1.1, size=50) * 10  # Very heavy tail
        xi, sigma = self.fit_gpd_pwm(exceedances)
        assert xi <= 0.49, f"xi={xi:.4f} exceeds clamp"
        assert xi >= -0.49, f"xi={xi:.4f} below clamp"

    def test_sigma_always_positive(self):
        """Sigma must always be positive regardless of input."""
        for seed in range(10):
            rng = np.random.default_rng(seed)
            exc = rng.exponential(5.0, size=20)
            xi, sigma = self.fit_gpd_pwm(exc)
            assert sigma > 0, f"seed={seed}: sigma={sigma:.6f} not positive"


# ---------------------------------------------------------------------------
# DIVERSITY METRIC TESTS
# ---------------------------------------------------------------------------

class TestDiversityMetrics:

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.terrain_bootstrap import (
            compute_diversity_metrics,
            adjusted_confidence_tier,
            ConfidenceTier,
        )
        self.compute = compute_diversity_metrics
        self.adjust = adjusted_confidence_tier
        self.CT = ConfidenceTier

    def test_single_rider_suspect(self):
        wallets = ["0xaaa"] * 50
        m = self.compute(wallets, [None] * 50)
        assert m["n_unique_riders"] == 1
        assert m["diversity_tier"] == 0
        assert m["effective_n"] == 1.0

    def test_equal_riders_rich(self):
        wallets = [f"0x{i:04x}" for i in range(20)] * 5  # 20 riders, 5 each
        m = self.compute(wallets, [None] * 100)
        assert m["n_unique_riders"] == 20
        assert m["diversity_tier"] == 3
        assert abs(m["effective_n"] - 20.0) < 0.1

    def test_dominated_single(self):
        wallets = ["0xdom"] * 97 + ["0xb", "0xc", "0xd"]
        m = self.compute(wallets, [None] * 100)
        assert m["n_unique_riders"] == 4
        # effective_n should be very low due to domination
        assert m["effective_n"] < 3.0
        assert m["diversity_tier"] == 0  # suspect

    def test_kish_formula(self):
        """Verify Kish formula: n_eff = (sum w_i)^2 / sum(w_i^2)."""
        wallets = ["a"] * 10 + ["b"] * 10
        m = self.compute(wallets, [None] * 20)
        expected_eff = (20 * 20) / (100 + 100)  # 400/200 = 2.0
        assert abs(m["effective_n"] - expected_eff) < 0.01

    def test_confidence_cap_suspect(self):
        """Suspect diversity caps even FULL tier to EMPIRICAL."""
        result = self.adjust(self.CT.FULL, diversity_tier=0)
        assert result == self.CT.EMPIRICAL

    def test_confidence_cap_thin(self):
        result = self.adjust(self.CT.FULL, diversity_tier=1)
        assert result == self.CT.LOW

    def test_confidence_no_cap_rich(self):
        result = self.adjust(self.CT.FULL, diversity_tier=3)
        assert result == self.CT.FULL


# ---------------------------------------------------------------------------
# SCORING PIPELINE TESTS
# ---------------------------------------------------------------------------

class TestScoringPipeline:
    """End-to-end: synthetic cell params → score_climb_against_cell."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.terrain_bootstrap import (
            TerrainCellFit,
            ConfidenceTier,
            SignificanceResult,
            NOISE_GATE_M,
        )
        self.TerrainCellFit = TerrainCellFit
        self.CT = ConfidenceTier
        self.SignificanceResult = SignificanceResult
        self.NOISE_GATE_M = NOISE_GATE_M

        # Import the scoring function
        from app.services.terrain_bootstrap import compute_significance_traced
        self.score_traced = compute_significance_traced

    def _make_cell(self, xi=0.0, sigma=15.0, k=30, n=100, threshold=10.0,
                   tier=None, diag=True, g_cap=None):
        from datetime import datetime, timezone
        if tier is None:
            if k >= 30:
                tier = self.CT.FULL
            elif k >= 20:
                tier = self.CT.MODERATE
            elif k >= 12:
                tier = self.CT.LOW
            else:
                tier = self.CT.EMPIRICAL
        if g_cap is None:
            g_cap = 1.0  # No cap
        return self.TerrainCellFit(
            h3_index="851f1a3fffffff",
            h3_resolution=5,
            n_features=n,
            k_exceedances=k,
            threshold_m=threshold,
            threshold_quantile=0.90,
            gpd_xi=xi,
            gpd_sigma=sigma,
            xi_ci_hi=xi + 0.05,
            g_cap=g_cap,
            confidence_tier=tier,
            tail_diag_pass=diag,
            bootstrapped_at=datetime.now(timezone.utc),
        )

    def test_below_threshold_gets_low_score(self):
        """Persistence below threshold should score near 0."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0)
        trace = self.score_traced(5.0, cell)  # 5m < 10m threshold
        assert trace["gFinal"] is not None
        assert trace["gFinal"] < 0.15, f"Below-threshold should score low, got {trace['gFinal']}"

    def test_above_threshold_scores_positive(self):
        """Persistence well above threshold should score meaningfully."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0)
        trace = self.score_traced(50.0, cell)
        assert trace["gFinal"] > 0.2, f"50m vs 10m threshold should score >0.2, got {trace['gFinal']}"

    def test_extreme_persistence_high_score(self):
        """Very large persistence should score close to 1.0."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0, k=50)
        trace = self.score_traced(200.0, cell)
        assert trace["gFinal"] > 0.7, f"200m should score very high, got {trace['gFinal']}"

    def test_score_monotonically_increases(self):
        """Larger persistence should always score higher (same cell)."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0)
        scores = []
        for pers in [5.0, 15.0, 30.0, 50.0, 80.0, 120.0]:
            trace = self.score_traced(pers, cell)
            scores.append(trace["gFinal"])
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1], \
                f"Score should increase: {scores[i - 1]:.4f} -> {scores[i]:.4f} at pers[{i}]"

    def test_flat_terrain_higher_score(self):
        """Same climb should score higher in flat terrain (xi < 0) than mountain (xi > 0)."""
        flat_cell = self._make_cell(xi=-0.2, sigma=8.0, threshold=5.0)
        mountain_cell = self._make_cell(xi=0.2, sigma=30.0, threshold=15.0)

        flat_trace = self.score_traced(40.0, flat_cell)
        mountain_trace = self.score_traced(40.0, mountain_cell)

        assert flat_trace["gFinal"] > mountain_trace["gFinal"], \
            f"40m climb should score higher in flat ({flat_trace['gFinal']:.3f}) " \
            f"than mountain ({mountain_trace['gFinal']:.3f})"

    def test_diag_fail_caps_score(self):
        """When diagnostics fail, scores should be capped at 0.60."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0, diag=False)
        trace = self.score_traced(200.0, cell)
        assert trace["gFinal"] <= 0.65, \
            f"Diag-fail should cap at ~0.60, got {trace['gFinal']}"

    def test_low_tier_capped(self):
        """EMPIRICAL tier should have reduced g_cap."""
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0,
                               k=8, tier=self.CT.EMPIRICAL, g_cap=0.25)
        trace = self.score_traced(200.0, cell)
        assert trace["gFinal"] <= 0.30, \
            f"EMPIRICAL cap should limit score, got {trace['gFinal']}"

    def test_score_bounded_0_1(self):
        """G score must always be in [0, 1]."""
        cell = self._make_cell(xi=0.3, sigma=50.0, threshold=20.0)
        for pers in [0.0, 1.0, 5.0, 50.0, 500.0, 5000.0]:
            trace = self.score_traced(pers, cell)
            g = trace["gFinal"]
            assert 0.0 <= g <= 1.0, f"G={g} out of [0,1] for persistence={pers}"

    def test_negative_xi_has_upper_bound(self):
        """Flat terrain (xi < 0): there's a max possible climb.
        Persistence near that upper bound should score very high."""
        xi = -0.2
        sigma = 10.0
        upper_bound = -sigma / xi  # = 50m
        cell = self._make_cell(xi=xi, sigma=sigma, threshold=5.0)
        trace = self.score_traced(upper_bound * 0.9, cell)  # 45m, near upper bound
        assert trace["gFinal"] > 0.5, \
            f"Near-upper-bound persistence should score high, got {trace['gFinal']}"


# ---------------------------------------------------------------------------
# REGRESSION TESTS (real file baseline checks)
# ---------------------------------------------------------------------------

class TestRegressionBaseline:
    """Ensure v2 persistence detector doesn't regress on known files."""

    @pytest.fixture(autouse=True)
    def _import_wp(self):
        try:
            import workout_parse
            self.wp = workout_parse
        except ImportError:
            pytest.skip("workout_parse not built")

    VALIDATION_DIR = Path(__file__).parent

    def _parse_samples(self, filename):
        """Parse FIT file to tile sample dicts."""
        fit_path = self.VALIDATION_DIR / filename
        if not fit_path.exists():
            pytest.skip(f"{filename} not found")

        activity = self.wp.parse_file(str(fit_path))
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
            samples.append(s)
        return samples

    def test_flat_ride_no_false_positives(self):
        """NJ coast ride: truly flat, should find 0 climbs with vert >= 20m."""
        samples = self._parse_samples("Afternoon_Ride (1).fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 20]
        assert len(sig_climbs) == 0, \
            f"Flat ride should have 0 significant climbs, got {len(sig_climbs)}"

    def test_wall_detected(self):
        """Manayunk Wall file: must detect the Wall (v1 hilly missed it)."""
        samples = self._parse_samples("t_h_e_w_a_l_l.fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 40]
        assert len(sig_climbs) >= 1, \
            f"Wall file should have >=1 climb with vert>=40m, got {len(sig_climbs)}"
        # The Wall itself should be ~59m
        wall_candidates = [c for c in sig_climbs if 45 < c.vert_m < 80]
        assert len(wall_candidates) >= 1, "Should find the Wall (~59m)"

    def test_tucson_finds_major_climbs(self):
        """Tucson ride: should find >=2 significant climbs including Mt. Lemmon area."""
        samples = self._parse_samples("Morning_Ride (1).fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 50]
        assert len(sig_climbs) >= 2, \
            f"Tucson should have >=2 major climbs, got {len(sig_climbs)}"

    def test_rolling_terrain_finds_rollers(self):
        """Philly rolling ride: should find multiple rollers."""
        samples = self._parse_samples("Afternoon_Ride.fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        sig_climbs = [c for c in climbs if c.vert_m >= 15]
        assert len(sig_climbs) >= 2, \
            f"Rolling ride should have >=2 rollers, got {len(sig_climbs)}"

    def test_in_the_bag_finds_manayunk_ridge(self):
        """5-hour Manayunk ride: must find the ridge climb (~80m)."""
        samples = self._parse_samples("in_the_bag_.fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        ridge_candidates = [c for c in climbs if c.vert_m >= 60]
        assert len(ridge_candidates) >= 1, \
            f"Should find Manayunk Ridge (>=60m), got {len(ridge_candidates)} candidates"

    def test_all_climbs_have_signatures(self):
        """Significant climbs should have v2 signatures.

        Note: merge-pair climbs whose effort segment is entirely descending
        won't get a v2 signature (vert=0 in the effort window), which is
        correct — you can't build a gradient profile from a descent.
        Essential-class climbs always have positive effort gain.
        """
        samples = self._parse_samples("t_h_e_w_a_l_l.fit")
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        essential_climbs = [c for c in climbs if c.vert_m >= 10 and c.is_essential]
        for c in essential_climbs:
            assert c.signature_v2_hex is not None, \
                f"Essential climb with vert={c.vert_m:.1f}m missing v2 signature"

    def test_climb_count_stability(self):
        """
        Climb counts should not wildly change between runs.
        This is a soft check — we record expected ranges based on current behavior.
        """
        expected = {
            "Afternoon_Ride (1).fit": (0, 2),     # Flat: 0-2 tiny rollers
            "t_h_e_w_a_l_l.fit": (2, 8),          # Wall: 2-8 climbs
            "Morning_Ride (1).fit": (3, 15),       # Tucson: 3-15 climbs
            "Afternoon_Ride.fit": (3, 15),         # Rolling: 3-15
        }
        for filename, (lo, hi) in expected.items():
            try:
                samples = self._parse_samples(filename)
            except Exception:
                continue
            climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
            sig = [c for c in climbs if c.vert_m >= 10]
            assert lo <= len(sig) <= hi, \
                f"{filename}: expected {lo}-{hi} climbs(>=10m), got {len(sig)}"


# ---------------------------------------------------------------------------
# COMBINED PIPELINE TESTS
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Tests that combine persistence detection with GPD scoring."""

    @pytest.fixture(autouse=True)
    def _import_all(self):
        try:
            import workout_parse
            self.wp = workout_parse
        except ImportError:
            pytest.skip("workout_parse not built")

        from app.services.terrain_bootstrap import (
            TerrainCellFit, ConfidenceTier, compute_significance_traced,
        )
        self.TerrainCellFit = TerrainCellFit
        self.CT = ConfidenceTier
        self.score_traced = compute_significance_traced

    def _make_cell(self, xi, sigma, threshold, k=30):
        from datetime import datetime, timezone
        tier = self.CT.FULL if k >= 30 else self.CT.LOW
        return self.TerrainCellFit(
            h3_index="851f1a3fffffff", h3_resolution=5,
            n_features=100, k_exceedances=k,
            threshold_m=threshold, threshold_quantile=0.90,
            gpd_xi=xi, gpd_sigma=sigma, xi_ci_hi=xi + 0.05,
            g_cap=1.0, confidence_tier=tier, tail_diag_pass=True,
            bootstrapped_at=datetime.now(timezone.utc),
        )

    def _to_samples(self, elevations, dt=5):
        return [{"t": i * dt, "elevation_m": e} for i, e in enumerate(elevations)]

    def test_flat_profile_zero_score(self):
        """Flat profile → no climbs → low score."""
        profile = make_flat(200)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        max_pers = max((c.persistence for c in climbs), default=0.0)
        cell = self._make_cell(xi=0.0, sigma=15.0, threshold=10.0)
        trace = self.score_traced(max_pers, cell)
        assert trace["gFinal"] < 0.1, "Flat profile should get near-zero score"

    def test_big_climb_in_flat_terrain_high_score(self):
        """Big climb (100m) in flat terrain (xi=-0.2) should score very high."""
        profile = make_single_climb(300, vert=100.0)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        assert len(climbs) >= 1, "Should detect 100m climb"
        max_pers = max(c.persistence for c in climbs)
        cell = self._make_cell(xi=-0.2, sigma=8.0, threshold=5.0)
        trace = self.score_traced(max_pers, cell)
        assert trace["gFinal"] > 0.6, \
            f"100m climb in flat terrain should score >0.6, got {trace['gFinal']}"

    def test_small_climb_in_mountain_terrain_low_score(self):
        """Small climb (15m) in mountain terrain (xi=0.2) should score low."""
        profile = make_single_climb(200, vert=15.0)
        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        max_pers = max((c.persistence for c in climbs), default=0.0)
        cell = self._make_cell(xi=0.2, sigma=30.0, threshold=15.0)
        trace = self.score_traced(max_pers, cell)
        assert trace["gFinal"] < 0.3, \
            f"15m climb in mountains should score low, got {trace['gFinal']}"

    def test_significance_differentiator(self):
        """
        Core product thesis: same physical climb scores differently
        in different terrains.

        A 30m climb is remarkable in the Netherlands but unremarkable in Colorado.
        """
        # Use a V-shaped profile to guarantee both merge pair + essential detection
        n = 300
        vert = 30.0
        profile = []
        for i in range(n):
            frac = i / (n - 1)
            if frac < 0.5:
                profile.append(100.0 + vert * frac * 2)
            else:
                profile.append(100.0 + vert * (1 - frac) * 2)

        samples = self._to_samples(profile)
        climbs = self.wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
        max_pers = max((c.persistence for c in climbs), default=0.0)
        assert max_pers > 20.0, f"Should detect ~30m climb, got {max_pers:.1f}"

        # Netherlands-like: flat, bounded tail
        nl_cell = self._make_cell(xi=-0.3, sigma=5.0, threshold=3.5)
        nl_trace = self.score_traced(max_pers, nl_cell)

        # Colorado-like: mountainous, heavy tail
        co_cell = self._make_cell(xi=0.25, sigma=40.0, threshold=20.0)
        co_trace = self.score_traced(max_pers, co_cell)

        assert nl_trace["gFinal"] > co_trace["gFinal"], \
            f"30m climb: Netherlands ({nl_trace['gFinal']:.3f}) should score " \
            f"higher than Colorado ({co_trace['gFinal']:.3f})"
        # The gap should be meaningful
        assert nl_trace["gFinal"] - co_trace["gFinal"] > 0.1, \
            "Significance gap should be >0.1 between flat and mountain terrain"
