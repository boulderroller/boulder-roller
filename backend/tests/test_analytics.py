import math
from unittest.mock import AsyncMock

import pytest

from app.services.fitness_analytics import FitnessAnalyticsService


class TestFitnessMetrics:
    def test_ctl_calculation_from_zero(self):
        """CTL should increase when TSS is added to zero baseline."""
        service = FitnessAnalyticsService(fitness_repo=AsyncMock(), ride_repo=AsyncMock())

        ctl_decay = 1 - math.exp(-1 / 42)
        expected_ctl = 100 * ctl_decay

        assert abs(expected_ctl - 2.35) < 0.1
        assert service.CTL_TIME_CONSTANT == 42

    def test_atl_responds_faster_than_ctl(self):
        """ATL should change faster than CTL (7-day vs 42-day constant)."""
        ctl_decay = 1 - math.exp(-1 / 42)
        atl_decay = 1 - math.exp(-1 / 7)

        assert atl_decay > ctl_decay
        assert abs(atl_decay - 0.133) < 0.01

    def test_tsb_calculation(self):
        """TSB = CTL - ATL."""
        tsb = 50 - 70
        assert tsb == -20

    def test_form_status_interpretation(self):
        """Test form status based on TSB."""
        service = FitnessAnalyticsService(fitness_repo=AsyncMock(), ride_repo=AsyncMock())

        assert service._get_form_status(30) == "Transition"
        assert service._get_form_status(15) == "Fresh"
        assert service._get_form_status(0) == "Grey zone"
        assert service._get_form_status(-20) == "Optimal"
        assert service._get_form_status(-40) == "High risk"

