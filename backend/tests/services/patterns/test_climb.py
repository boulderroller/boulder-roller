"""
Tests for ClimbPattern detection algorithm.

Test cases cover:
1. Basic climb detection (happy path)
2. No climb scenarios (insufficient vert, too short, etc.)
3. Multiple climb candidates (selection logic)
4. GPS noise handling (smoothing)
5. Arena filtering
6. Edge cases (empty data, single sample, etc.)
"""

import pytest

from app.services.patterns.climb import ClimbPattern, ClimbPatternDetector


class TestClimbPatternDetector:
    """Test suite for ClimbPatternDetector."""

    def test_basic_climb_detection(self):
        """Test detection of a simple sustained climb."""
        detector = ClimbPatternDetector()

        # Simulate a 400m climb over 10 minutes
        samples = []
        for i in range(61):  # 61 samples = ~1 sample/10 sec
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 7),  # ~7m gain per sample = ~420m total
                    "power_w": 250,
                    "hr_bpm": 150,
                }
            )

        pattern = detector.detect(samples)

        assert pattern is not None
        assert pattern.vert_m >= 300  # Meets minimum
        assert pattern.time_s >= 300  # Meets minimum duration
        assert pattern.time_s <= 3600  # Within max duration
        assert pattern.avg_power_w == pytest.approx(250, rel=0.01)
        assert pattern.avg_hr == 150

    def test_no_climb_insufficient_vert(self):
        """Test that insufficient vertical gain returns None."""
        detector = ClimbPatternDetector(vert_min_m=200)

        # Only ~180m climb (below 200m threshold)
        samples = []
        for i in range(61):
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 3),  # ~3m per sample = ~180m total
                }
            )

        pattern = detector.detect(samples)
        assert pattern is None

    def test_no_climb_too_short(self):
        """Test that climbs shorter than time_min_s are rejected."""
        detector = ClimbPatternDetector(time_min_s=300)

        # 400m climb but only 4 minutes (below 5 min threshold)
        samples = []
        for i in range(25):  # 240 seconds
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 16),  # ~400m total
                }
            )

        pattern = detector.detect(samples)
        assert pattern is None

    def test_no_climb_too_much_descent(self):
        """Test that climbs with excessive descents are rejected."""
        detector = ClimbPatternDetector(drop_tolerance_m=30, smoothing_window=1)

        # Climb with several large descents that exceed tolerance
        samples = []
        elevation = 1000
        for i in range(61):
            # Add periodic large descents
            if i % 15 == 10:
                elevation -= 35  # 35m drop exceeds tolerance
            else:
                elevation += 7

            samples.append(
                {"t": i * 10, "tile_id": f"tile_{i}", "elevation_m": elevation}
            )

        pattern = detector.detect(samples)
        # The large drops should prevent detecting a full-length climb
        # It may find a shorter climb between drops, or None
        if pattern is not None:
            # If it finds a pattern, it should be a shorter segment
            assert pattern.time_s < 400  # Significantly less than full 600s duration

    def test_multiple_climbs_selects_best(self):
        """Test that when multiple climbs exist, the best one is selected."""
        detector = ClimbPatternDetector()

        # Create ride with two climbs: 300m and 500m
        samples = []

        # First climb: 300m over 5 minutes
        for i in range(31):
            samples.append(
                {"t": i * 10, "tile_id": f"tile_{i}", "elevation_m": 1000 + (i * 10)}
            )

        # Descent section (forces a new climb segment)
        for i in range(31, 61):
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1300 - ((i - 31) * 2),  # ~58m drop
                }
            )

        # Second climb: 500m over 8 minutes
        for i in range(61, 110):
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1242 + ((i - 61) * 10),
                }
            )

        pattern = detector.detect(samples)

        assert pattern is not None
        # Should select the bigger climb (500m)
        assert pattern.vert_m >= 450  # Close to 500m (allowing for smoothing)

    def test_smoothing_reduces_noise(self):
        """Test that elevation smoothing handles GPS noise."""
        detector = ClimbPatternDetector(smoothing_window=5)

        # Climb with noisy elevation data
        samples = []
        import random

        random.seed(42)  # Reproducible noise
        for i in range(61):
            # Base elevation increases, but add random noise
            base_elevation = 1000 + (i * 7)
            noise = random.uniform(-3, 3)  # +/- 3m noise
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": base_elevation + noise,
                }
            )

        pattern = detector.detect(samples)

        # Should still detect the climb despite noise
        assert pattern is not None
        assert pattern.vert_m >= 300

    def test_arena_filtering(self):
        """Test that arena_tiles parameter filters samples correctly."""
        detector = ClimbPatternDetector(vert_min_m=300)

        # Create climb where only half the tiles are in the Arena
        arena_tiles = {f"tile_{i}" for i in range(0, 30)}  # First 30 tiles

        samples = []
        for i in range(61):
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 7),  # Full climb would be ~420m
                }
            )

        # With arena filtering, should only see first 30 samples (~210m vert)
        pattern = detector.detect(samples, arena_tiles=arena_tiles)

        # Should not detect a climb (only ~210m in Arena, below 300m threshold)
        assert pattern is None

        # Without arena filtering, should detect the full climb
        pattern_no_filter = detector.detect(samples, arena_tiles=None)
        assert pattern_no_filter is not None

    def test_w_per_kg_calculation(self):
        """Test that w/kg is calculated correctly when power and weight provided."""
        detector = ClimbPatternDetector()

        samples = []
        for i in range(61):
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 7),
                    "power_w": 300,  # 300W average
                }
            )

        # 300W / 75kg = 4.0 w/kg
        pattern = detector.detect(samples, user_weight_kg=75.0)

        assert pattern is not None
        assert pattern.w_per_kg == pytest.approx(4.0, rel=0.01)

        # Without weight, should not calculate w/kg
        pattern_no_weight = detector.detect(samples, user_weight_kg=None)
        assert pattern_no_weight.w_per_kg is None

    def test_no_elevation_data(self):
        """Test that samples without elevation return None."""
        detector = ClimbPatternDetector()

        samples = [{"t": i * 10, "tile_id": f"tile_{i}"} for i in range(61)]

        pattern = detector.detect(samples)
        assert pattern is None

    def test_empty_samples(self):
        """Test that empty sample list returns None."""
        detector = ClimbPatternDetector()
        pattern = detector.detect([])
        assert pattern is None

    def test_single_sample(self):
        """Test that single sample returns None."""
        detector = ClimbPatternDetector()
        pattern = detector.detect([{"t": 0, "tile_id": "tile_0", "elevation_m": 1000}])
        assert pattern is None

    def test_custom_thresholds(self):
        """Test that custom thresholds work correctly."""
        # Detector with lower thresholds for shorter climbs
        detector = ClimbPatternDetector(
            vert_min_m=150,  # Lower threshold
            time_min_s=180,  # 3 minutes
            time_max_s=1800,  # 30 minutes
        )

        # 200m climb over 4 minutes (would fail default thresholds)
        samples = []
        for i in range(25):  # 240 seconds
            samples.append(
                {
                    "t": i * 10,
                    "tile_id": f"tile_{i}",
                    "elevation_m": 1000 + (i * 8),  # ~200m total
                }
            )

        pattern = detector.detect(samples)

        # Should detect with custom thresholds
        assert pattern is not None
        assert pattern.vert_m >= 150

    def test_pattern_to_dict(self):
        """Test ClimbPattern serialization to dict."""
        pattern = ClimbPattern(
            vert_m=450.5,
            time_s=600,
            avg_power_w=280.3,
            w_per_kg=3.74,
            avg_hr=155,
            start_time_offset_s=120,
            end_time_offset_s=720,
            arena_id="boulder_north",
        )

        result = pattern.to_dict()

        assert result["vert_m"] == 450.5
        assert result["time_s"] == 600
        assert result["avg_power_w"] == 280.3
        assert result["w_per_kg"] == 3.74
        assert result["avg_hr"] == 155
        assert result["start_time_offset_s"] == 120
        assert result["end_time_offset_s"] == 720
        assert result["arena_id"] == "boulder_north"

    def test_realistic_flagstaff_climb(self):
        """
        Test with realistic data approximating Flagstaff Road climb in Boulder.

        Flagstaff: ~1200ft (366m) over ~4 miles, typically 20-30 minutes.
        """
        detector = ClimbPatternDetector()

        # Simulate 25 minute climb, 366m gain
        duration_s = 1500  # 25 minutes
        samples_count = 150  # ~1 sample per 10 seconds
        vert_gain_m = 366

        samples = []
        for i in range(samples_count):
            samples.append(
                {
                    "t": i * (duration_s // samples_count),
                    "tile_id": f"flagstaff_tile_{i}",
                    "elevation_m": 1650 + (i * (vert_gain_m / samples_count)),
                    "power_w": 240,  # Moderate effort
                    "hr_bpm": 160,
                }
            )

        pattern = detector.detect(samples, user_weight_kg=70.0)

        assert pattern is not None
        assert pattern.vert_m >= 340  # Close to 366m (may trim some)
        assert 1200 <= pattern.time_s <= 1500  # Around 20-25 min
        assert pattern.w_per_kg == pytest.approx(240 / 70, rel=0.05)

    def test_selection_prefers_max_vert_then_min_time(self):
        """Test that selection logic prefers max vert, then min time."""
        detector = ClimbPatternDetector(
            vert_min_m=50,
            time_min_s=60,
            drop_tolerance_m=20,
            smoothing_window=1,
        )

        samples = []

        # Climb 1: +200m over 500s
        for i in range(51):
            samples.append(
                {"t": i * 10, "tile_id": f"tile_a_{i}", "elevation_m": 1000 + (i * 4)}
            )

        # Descent: -40m (forces a new climb segment)
        for j in range(1, 11):
            samples.append(
                {
                    "t": 500 + (j * 10),
                    "tile_id": f"tile_down_{j}",
                    "elevation_m": 1200 - (j * 4),
                }
            )

        # Climb 2: +200m over 400s (same vert, shorter time)
        for k in range(1, 41):
            samples.append(
                {
                    "t": 600 + (k * 10),
                    "tile_id": f"tile_b_{k}",
                    "elevation_m": 1160 + (k * 5),
                }
            )

        pattern = detector.detect(samples)

        assert pattern is not None
        # With trimming, the time may be slightly less than the raw 400s
        assert 380 <= pattern.time_s <= 410
        assert 600 <= pattern.start_time_offset_s <= 620

    def test_drop_tolerance_allows_brief_descents(self):
        """Test that brief descents within tolerance are allowed."""
        detector = ClimbPatternDetector(drop_tolerance_m=30)

        # Climb with small descents throughout
        samples = []
        elevation = 1000
        for i in range(61):
            # Mostly up, occasional small downs
            if i % 10 == 5:
                delta = -5  # Small descent
            else:
                delta = 8  # Upward

            elevation += delta
            samples.append(
                {"t": i * 10, "tile_id": f"tile_{i}", "elevation_m": elevation}
            )

        pattern = detector.detect(samples)

        # Should still detect climb (descents are within tolerance)
        assert pattern is not None
        assert pattern.vert_m >= 300

    def test_detect_all_returns_multiple_climbs(self):
        """detect_all returns multiple distinct climbs when separated by drawdown."""
        detector = ClimbPatternDetector(
            vert_min_m=50,
            time_min_s=60,
            drop_tolerance_m=30,
            smoothing_window=1,
        )

        samples = []

        # Climb 1: +120m over 300s
        for i in range(31):
            samples.append({"t": i * 10, "tile_id": f"tile_{i}", "elevation_m": 1000 + (i * 4)})

        # Gradual descent: -40m in 10 steps of -4m (max single step is small)
        for j in range(1, 11):
            samples.append(
                {
                    "t": 300 + (j * 10),
                    "tile_id": f"tile_down_{j}",
                    "elevation_m": 1120 - (j * 4),
                }
            )

        # Climb 2: +140m over 350s
        for k in range(1, 36):
            samples.append(
                {
                    "t": 400 + (k * 10),
                    "tile_id": f"tile_b_{k}",
                    "elevation_m": 1080 + (k * 4),
                }
            )

        climbs = detector.detect_all(samples)
        assert len(climbs) == 2
        # With trimming, values may be slightly reduced
        assert climbs[0].vert_m >= 100  # ~120m with some trim
        assert 260 <= climbs[0].time_s <= 310
        assert climbs[1].vert_m >= 120  # ~140m with some trim
        assert 300 <= climbs[1].time_s <= 360
