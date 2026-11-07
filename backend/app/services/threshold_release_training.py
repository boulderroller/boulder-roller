"""Durable training-load projection for a completed Threshold release."""

from __future__ import annotations

from typing import Any

from ..repositories import RideRepository
from .fitness_analytics import FitnessAnalyticsService, normalize_to_date


class ThresholdReleaseTrainingProjector:
    """Recompute the ride's original training day after terminal release."""

    def __init__(
        self,
        *,
        analytics: FitnessAnalyticsService,
        ride_repository: RideRepository,
    ) -> None:
        self.analytics = analytics
        self.ride_repository = ride_repository

    async def project(self, release: dict[str, Any]) -> None:
        ride_id = str(release.get("ride_id") or "")
        user_id = str(release.get("user_id") or "")
        if not ride_id or not user_id:
            raise RuntimeError("Threshold release projection lacks ride ownership")

        ride = await self.ride_repository.get_ride(ride_id)
        if not ride:
            return
        if str(ride.get("user_id") or "") != user_id:
            raise RuntimeError("Threshold release ride ownership is inconsistent")
        if ride.get("tss") is None or ride.get("threshold_training_kind") != "sealed":
            raise RuntimeError("Threshold release ride training projection is incomplete")

        await self.analytics.update_daily_aggregates(
            user_id,
            normalize_to_date(ride.get("started_at")),
        )
