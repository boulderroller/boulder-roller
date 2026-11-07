"""Live API scheduler for Threshold sealing and held-ride release recovery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional


logger = logging.getLogger(__name__)

SEAL_INTERVAL_SECONDS = 60.0
RELEASE_INTERVAL_SECONDS = 15.0
PASS_TIMEOUT_SECONDS = 240.0


def create_threshold_release_recovery_loop(batch_size: int = 25) -> Any:
    """Build one shared repository/executor pair for both release stages."""
    from ..repositories import (
        create_fitness_repository,
        create_ride_economic_repository,
        create_ride_repository,
    )
    from .fitness_analytics import FitnessAnalyticsService
    from .threshold_release_coordinator import ThresholdReleaseCoordinator
    from .threshold_release_executor import ThresholdReleaseExecutor
    from .threshold_release_planner import ThresholdReleasePlanner
    from .threshold_release_recovery import ThresholdReleaseRecoveryLoop
    from .threshold_release_training import ThresholdReleaseTrainingProjector

    repository = create_ride_economic_repository()
    ride_repository = create_ride_repository()
    executor = ThresholdReleaseExecutor()
    return ThresholdReleaseRecoveryLoop(
        planner=ThresholdReleasePlanner(
            repository=repository,
            executor=executor,
        ),
        coordinator=ThresholdReleaseCoordinator(
            repository=repository,
            executor=executor,
            training_projector=ThresholdReleaseTrainingProjector(
                analytics=FitnessAnalyticsService(
                    create_fitness_repository(),
                    ride_repository,
                ),
                ride_repository=ride_repository,
            ),
        ),
        batch_size=batch_size,
    )


class ThresholdRuntime:
    """Run non-overlapping Threshold passes inside the deployed API process."""

    def __init__(
        self,
        *,
        sealer_repository: Any,
        release_recovery: Any,
        seal_interval_seconds: float = SEAL_INTERVAL_SECONDS,
        release_interval_seconds: float = RELEASE_INTERVAL_SECONDS,
        pass_timeout_seconds: float = PASS_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.sealer_repository = sealer_repository
        self.release_recovery = release_recovery
        self.seal_interval_seconds = max(0.001, float(seal_interval_seconds))
        self.release_interval_seconds = max(
            0.001, float(release_interval_seconds)
        )
        self.pass_timeout_seconds = max(0.001, float(pass_timeout_seconds))
        self._sleep = sleep
        self._seal_task: Optional[asyncio.Task[None]] = None
        self._release_task: Optional[asyncio.Task[None]] = None

    @property
    def tasks(self) -> tuple[asyncio.Task[None], ...]:
        return tuple(
            task
            for task in (self._seal_task, self._release_task)
            if task is not None
        )

    async def start(self) -> None:
        if self.tasks:
            raise RuntimeError("Threshold runtime is already started")
        self._seal_task = asyncio.create_task(
            self._run_loop(
                name="seal",
                operation=self.sealer_repository.seal_due_reward_threshold_promotions,
                interval_seconds=self.seal_interval_seconds,
            ),
            name="threshold-seal-runtime",
        )
        self._release_task = asyncio.create_task(
            self._run_loop(
                name="release",
                operation=self.release_recovery.run_once,
                interval_seconds=self.release_interval_seconds,
            ),
            name="threshold-release-runtime",
        )

    async def stop(self) -> None:
        tasks = self.tasks
        self._seal_task = None
        self._release_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_loop(
        self,
        *,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        interval_seconds: float,
    ) -> None:
        while True:
            try:
                result = await asyncio.wait_for(
                    operation(), timeout=self.pass_timeout_seconds
                )
                logger.info("Threshold %s pass completed: %s", name, result)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.error(
                    "Threshold %s pass exceeded %.0f seconds; retrying next interval",
                    name,
                    self.pass_timeout_seconds,
                )
            except Exception:
                logger.exception(
                    "Threshold %s pass failed; retrying next interval", name
                )
            await self._sleep(interval_seconds)


def create_threshold_runtime(*, batch_size: int = 25) -> ThresholdRuntime:
    from ..repositories import create_ride_repository

    return ThresholdRuntime(
        sealer_repository=create_ride_repository(),
        release_recovery=create_threshold_release_recovery_loop(batch_size),
    )
