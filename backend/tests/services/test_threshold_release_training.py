from __future__ import annotations

import pytest

from app.services.threshold_release_training import ThresholdReleaseTrainingProjector


class MissingRideRepository:
    async def get_ride(self, ride_id: str):
        return None


class RecordingAnalytics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def update_daily_aggregates(self, user_id: str, ride_date: object) -> None:
        self.calls.append((user_id, ride_date))


@pytest.mark.asyncio
async def test_deleted_product_ride_does_not_block_release_completion() -> None:
    analytics = RecordingAnalytics()
    projector = ThresholdReleaseTrainingProjector(
        analytics=analytics,
        ride_repository=MissingRideRepository(),
    )

    await projector.project(
        {
            "ride_id": "33333333-3333-4333-8333-333333333333",
            "user_id": "44444444-4444-4444-8444-444444444444",
        }
    )

    assert analytics.calls == []
