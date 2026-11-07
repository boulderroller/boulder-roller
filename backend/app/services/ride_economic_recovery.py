"""Background recovery loop for durably checkpointed ride economics."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional
from uuid import UUID

from ..repositories.ride_economic import RideEconomicRepository

logger = logging.getLogger(__name__)


class RideEconomicRecoveryLoop:
    """Resume due plans directly from their immutable coordinator state."""

    def __init__(
        self,
        *,
        repository: RideEconomicRepository,
        coordinator_factory: Callable[[], Any],
        terminal_projector_factory: Optional[Callable[[], Any]] = None,
        interval_seconds: int = 15,
        batch_size: int = 25,
    ) -> None:
        self.repository = repository
        self.coordinator_factory = coordinator_factory
        self.terminal_projector_factory = terminal_projector_factory
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size

    async def run_once(self) -> int:
        plans = await self.repository.list_recoverable_plans(limit=self.batch_size)
        resumed = 0
        for plan in plans:
            try:
                ride_id = UUID(str(plan["ride_id"]))
                outcome = await self.coordinator_factory().execute(ride_id)
                if (
                    outcome.status == "complete"
                    and self.terminal_projector_factory is not None
                ):
                    await self.terminal_projector_factory().project(ride_id)
                resumed += 1
            except Exception:
                logger.exception(
                    "Ride economic recovery failed for ride %s",
                    plan.get("ride_id"),
                )
        return resumed

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ride economic recovery poll failed")
            await asyncio.sleep(self.interval_seconds)
