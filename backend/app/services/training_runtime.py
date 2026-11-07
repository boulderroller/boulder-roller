"""Training-only replay owned by the deployed NATS consumer lifecycle."""

import asyncio
import logging
from uuid import UUID, uuid4

from .training_backfill import replay_training_batch, error_class

logger = logging.getLogger(__name__)


class TrainingReplayRuntime:
    def __init__(self, *, interval_s=60, pass_timeout_s=240):
        self.interval_s = interval_s
        self.pass_timeout_s = pass_timeout_s  # below the durable ten-minute lease
        self.task = None
        self._wake = asyncio.Event()
        self.startup_cutoff = None
        self.blocked_rides = set()
        self._latest_attempt = {}
        self._receipt_tasks = set()
        self._receipt_tail = {}
        self._closing = False

    async def prepare(self):
        from ..repositories import create_ride_repository

        try:
            self.startup_cutoff = await asyncio.wait_for(
                create_ride_repository().training_replay_startup_cutoff(), timeout=1
            )
        except Exception as exc:
            # No later cutoff: uploads may have started by then. Normal recorded
            # completions still replay; legacy recovery resumes on a clean boot.
            logger.warning(
                "Training startup boundary unavailable: %s", type(exc).__name__
            )

    def begin_attempt(self, payload):
        if self._closing:
            return None
        try:
            ride_id = str(UUID(str(payload.get("ride_id"))))
            user_id = str(UUID(str(payload.get("user_id"))))
        except (ValueError, TypeError, AttributeError):
            return None  # the existing pay handler ACKs malformed uploads
        self.blocked_rides.add(ride_id)
        token = str(uuid4())
        self._latest_attempt[ride_id] = token
        self._queue_receipt(ride_id, user_id, token, False)
        return token

    def finish_attempt(self, payload, token):
        if token is None or self._closing:
            return
        self._queue_receipt(
            str(UUID(str(payload["ride_id"]))),
            str(UUID(str(payload["user_id"]))),
            token,
            True,
        )

    def _queue_receipt(self, ride_id, user_id, token, finished):
        previous = self._receipt_tail.get(ride_id)
        task = asyncio.create_task(
            self._record_receipt(ride_id, user_id, token, finished, previous),
            name="training-attempt-receipt",
        )
        self._receipt_tail[ride_id] = task
        self._receipt_tasks.add(task)

        def done(task):
            self._receipt_tasks.discard(task)
            if (
                finished
                and not task.cancelled()
                and task.exception() is None
                and task.result()
                and self._receipt_tail.get(ride_id) is task
            ):
                self._receipt_tail.pop(ride_id, None)

        task.add_done_callback(done)

    async def _record_receipt(self, ride_id, user_id, token, finished, previous):
        from ..repositories import create_ride_repository

        try:
            if previous is not None and not await asyncio.shield(previous):
                return False  # a failed/uncertain begin must never become ready
            # Await the actual RPC only in this background task. A coroutine
            # timeout would leave its to_thread database write running out of order.
            await create_ride_repository().set_training_pay_attempt(
                ride_id, user_id, token, finished
            )
            if finished and self._latest_attempt.get(ride_id) == token:
                self.blocked_rides.discard(ride_id)
                self._latest_attempt.pop(ride_id, None)
                self.wake()
            return True
        except Exception as exc:
            logger.warning(
                "Training attempt boundary unavailable: %s", type(exc).__name__
            )
            return False

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="training-replay")

    def wake(self):
        self._wake.set()

    async def stop(self):
        self._closing = True  # uploads still returning cannot enqueue after this
        tasks = list(self._receipt_tasks) + ([self.task] if self.task else [])
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.task = None

    async def _run(self):
        from ..repositories import create_ride_repository

        while True:
            self._wake.clear()
            try:
                # Retry repository initialization too; a transient DB failure
                # must not leave training disabled until the API restarts.
                repo = create_ride_repository()
                repo.training_runtime = self
                await asyncio.wait_for(
                    replay_training_batch(repo, limit=10),
                    timeout=self.pass_timeout_s,
                )
            except BaseException as exc:
                failure = error_class(exc)  # cancellation/process exits escape
                logger.warning("Training replay pass failed: %s", failure)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                pass
