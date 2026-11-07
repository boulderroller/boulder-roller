"""Bounded recovery pass for provisional Threshold release work."""

from __future__ import annotations

import logging
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded


logger = logging.getLogger(__name__)


class ThresholdReleaseRecoveryLoop:
    def __init__(
        self,
        *,
        planner: Any,
        coordinator: Any,
        batch_size: int = 25,
    ) -> None:
        self.planner = planner
        self.coordinator = coordinator
        self.batch_size = max(1, int(batch_size))

    async def run_once(self) -> dict[str, int]:
        counts = {
            "planned": 0,
            "planner_reviews": 0,
            "completed": 0,
            "recovery_pending": 0,
            "execution_reviews": 0,
            "planner_errors": 0,
            "execution_errors": 0,
        }
        for _ in range(self.batch_size):
            try:
                outcome = await self.planner.run_once()
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                counts["planner_errors"] += 1
                logger.exception("Threshold release planner item failed in isolation")
                continue
            if outcome.status == "idle":
                break
            if outcome.status == "planned":
                counts["planned"] += 1
            elif outcome.status == "review":
                counts["planner_reviews"] += 1

        for _ in range(self.batch_size):
            try:
                outcome = await self.coordinator.run_once()
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                counts["execution_errors"] += 1
                logger.exception("Threshold release execution item failed in isolation")
                continue
            if outcome.status == "idle":
                break
            if outcome.status == "complete":
                counts["completed"] += 1
            elif outcome.status == "recovery_pending":
                counts["recovery_pending"] += 1
            elif outcome.status == "under_review":
                counts["execution_reviews"] += 1
        return counts
