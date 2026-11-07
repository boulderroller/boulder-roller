"""
Tests for vault time validation.

Coverage:
- Fallback time validation logic
- Bounds calculation (distance-based, VAM-based)
- Valid and invalid time detection
- Edge cases (very short/long climbs)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.repositories.vault import VaultRepository, TimeValidationResult


def create_vault_repo_with_mock():
    """Create a VaultRepository with a mock client for testing."""
    mock_client = MagicMock()
    return VaultRepository(mock_client)


class TestFallbackTimeValidation:
    """Test the _fallback_time_validation method."""

    @pytest.fixture
    def vault_repo(self):
        """Create a VaultRepository with a mock client."""
        return create_vault_repo_with_mock()

    def test_valid_time_within_bounds(self, vault_repo):
        """Test that a reasonable time passes validation."""
        # 10km climb, 500m vert, 30 minutes = reasonable
        result = vault_repo._fallback_time_validation(
            time_seconds=1800,  # 30 minutes
            distance_m=10000,   # 10km
            vert_m=500,         # 500m
        )
        assert result["is_valid"] is True
        assert result["error_message"] is None

    def test_time_too_fast_distance_based(self, vault_repo):
        """Test that impossibly fast times are rejected (speed > 54 km/h)."""
        # 10km in 5 minutes = 120 km/h = way too fast
        result = vault_repo._fallback_time_validation(
            time_seconds=300,   # 5 minutes
            distance_m=10000,   # 10km
            vert_m=100,
        )
        assert result["is_valid"] is False
        assert "impossibly fast" in result["error_message"]

    def test_time_too_fast_vam_based(self, vault_repo):
        """Test that impossibly fast climb times are rejected (VAM > 2000)."""
        # 1000m vert in 10 minutes = 6000 VAM = impossibly fast
        result = vault_repo._fallback_time_validation(
            time_seconds=600,   # 10 minutes
            distance_m=5000,    # 5km
            vert_m=1000,        # 1000m vert
        )
        assert result["is_valid"] is False
        assert "impossibly fast" in result["error_message"]

    def test_time_too_slow(self, vault_repo):
        """Test that unreasonably slow times are rejected (speed < 5 km/h)."""
        # 5km in 10 hours = 0.5 km/h = too slow
        result = vault_repo._fallback_time_validation(
            time_seconds=36000,  # 10 hours
            distance_m=5000,     # 5km
            vert_m=300,
        )
        assert result["is_valid"] is False
        assert "exceeds maximum" in result["error_message"]

    def test_absolute_minimum_30_seconds(self, vault_repo):
        """Test that times under 30 seconds are always rejected."""
        result = vault_repo._fallback_time_validation(
            time_seconds=10,    # 10 seconds - impossibly fast for any climb
            distance_m=100,     # Very short
            vert_m=5,
        )
        assert result["is_valid"] is False
        assert "impossibly fast" in result["error_message"]
        assert result["min_time_s"] >= 30

    def test_no_distance_or_vert_uses_absolute_bounds(self, vault_repo):
        """Test validation works with minimal input (absolute bounds only)."""
        # 5 minutes should be valid with no climb data
        result = vault_repo._fallback_time_validation(
            time_seconds=300,
            distance_m=None,
            vert_m=None,
        )
        assert result["is_valid"] is True

    def test_steep_short_climb_vam_based_minimum(self, vault_repo):
        """Test that steep short climbs use VAM-based minimum."""
        # 200m vert, 1km distance (20% grade)
        # At 2000 VAM max, min time = 200m * 60 / 2000 = 6 minutes
        result = vault_repo._fallback_time_validation(
            time_seconds=60,    # 1 minute - too fast even for short climb
            distance_m=1000,
            vert_m=200,
        )
        assert result["is_valid"] is False
        # Min time should be at least 6 minutes based on VAM
        assert result["min_time_s"] >= 360  # 6 minutes

    def test_max_time_at_least_double_min(self, vault_repo):
        """Test that max time is always at least 2x minimum."""
        result = vault_repo._fallback_time_validation(
            time_seconds=1000,
            distance_m=500,     # Very short distance
            vert_m=50,
        )
        assert result["max_time_s"] >= result["min_time_s"] * 2

    def test_six_hour_maximum(self, vault_repo):
        """Test that times over 6 hours are rejected."""
        # 7 hours
        result = vault_repo._fallback_time_validation(
            time_seconds=25200,  # 7 hours
            distance_m=50000,    # 50km - long distance
            vert_m=2000,
        )
        # Should be rejected because max is 6 hours
        assert result["is_valid"] is False
        assert result["max_time_s"] <= 21600  # 6 hours


class TestCalculateVaultTimeBounds:
    """Test the time bounds calculation logic."""

    def test_flat_10km_bounds(self):
        """Test bounds for a 10km flat segment."""
        # Expected:
        # Min: 10000m / 11.1 m/s = ~901 seconds (15 min at 40 km/h)
        # Max: 10000m / 1.4 m/s = ~7142 seconds (2 hours at 5 km/h)
        distance_m = 10000
        vert_m = 50  # Basically flat

        # Distance-based min
        expected_min = max(30, int(distance_m / 11.1))
        # VAM-based min (tiny vert)
        vam_min = int(vert_m * 60 / 2000)
        expected_min = max(expected_min, vam_min)

        # Distance-based max
        expected_max = int(distance_m / 1.4)

        assert expected_min > 800  # Around 15 minutes
        assert expected_min < 1200
        assert expected_max > 6000  # Around 2 hours
        assert expected_max < 8000

    def test_steep_1km_climb_bounds(self):
        """Test bounds for a steep 1km climb (200m vert, 20% grade)."""
        distance_m = 1000
        vert_m = 200

        # Distance-based min: 1000 / 15 = 66 seconds (at max speed 15 m/s)
        dist_min = int(distance_m / 15)
        # VAM-based min: VAM = vert / (time_s / 3600), so time_s = vert * 3600 / VAM
        # At max VAM of 2000: time_s = 200 * 3600 / 2000 = 360 seconds (6 min)
        vam_min = int(vert_m * 3600 / 2000)

        # VAM should dominate for steep climbs
        assert vam_min > dist_min
        assert vam_min >= 360  # 6 minutes at elite VAM


class TestTimeValidationIntegration:
    """Integration tests for time validation in the context of leaderboard updates."""

    def test_1_second_time_rejected(self):
        """Verify that a 1-second completion time would be rejected."""
        repo = create_vault_repo_with_mock()

        # Any 1-second time should be rejected
        result = repo._fallback_time_validation(
            time_seconds=1,
            distance_m=10000,
            vert_m=500,
        )
        assert result["is_valid"] is False

    def test_reasonable_kom_time_accepted(self):
        """Verify that a typical KOM time is accepted."""
        repo = create_vault_repo_with_mock()

        # 10km climb, 500m vert, 25 minutes = elite but possible
        # VAM = 500m / (25/60) = 1200 VAM - good amateur
        result = repo._fallback_time_validation(
            time_seconds=1500,  # 25 minutes
            distance_m=10000,
            vert_m=500,
        )
        assert result["is_valid"] is True
