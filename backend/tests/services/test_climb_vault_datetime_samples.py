from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.climb_vault import ClimbVaultService


def test_get_bounds_from_samples_accepts_datetime_samples() -> None:
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base + timedelta(seconds=offset),
            "lat": 40.0 + idx * 0.001,
            "lon": -75.0 - idx * 0.001,
        }
        for idx, offset in enumerate((0, 10, 20, 30))
    ]
    pattern = SimpleNamespace(start_time_offset_s=10, end_time_offset_s=20)

    bounds = ClimbVaultService(object())._get_bounds_from_samples(samples, pattern)

    assert bounds == (40.001, 40.002, -75.002, -75.001)


@pytest.mark.asyncio
async def test_match_climb_pattern_generates_signature_with_datetime_samples() -> None:
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base + timedelta(seconds=offset),
            "lat": 40.0 + idx * 0.001,
            "lon": -75.0 - idx * 0.001,
            "elevation_m": 100.0 + idx * 4.0,
        }
        for idx, offset in enumerate((0, 10, 20, 30))
    ]
    pattern = SimpleNamespace(
        signature_hex=None,
        tile_ids=[],
        start_time_offset_s=0,
        end_time_offset_s=30,
        vert_m=12.0,
        avg_gradient_pct=5.0,
        distance_m=300.0,
        time_s=30,
    )
    service = ClimbVaultService(object())
    service.find_climbs_in_bounds = AsyncMock(return_value=[])

    matches = await service.match_climb_pattern(pattern, samples)

    assert matches == []
    assert pattern.signature_hex is not None
