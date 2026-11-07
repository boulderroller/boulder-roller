from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.threshold_runtime import (
    ThresholdRuntime,
    create_threshold_release_recovery_loop,
)


@pytest.mark.asyncio
async def test_runtime_runs_both_passes_immediately_and_stops_cleanly() -> None:
    seal_ran = asyncio.Event()
    release_ran = asyncio.Event()

    async def seal_once():
        seal_ran.set()
        return 2

    async def recover_once():
        release_ran.set()
        return {"completed": 1}

    runtime = ThresholdRuntime(
        sealer_repository=SimpleNamespace(
            seal_due_reward_threshold_promotions=seal_once
        ),
        release_recovery=SimpleNamespace(run_once=recover_once),
        seal_interval_seconds=60,
        release_interval_seconds=15,
    )

    await runtime.start()
    tasks = runtime.tasks
    await asyncio.wait_for(seal_ran.wait(), timeout=1)
    await asyncio.wait_for(release_ran.wait(), timeout=1)
    assert {task.get_name() for task in tasks} == {
        "threshold-seal-runtime",
        "threshold-release-runtime",
    }

    await runtime.stop()
    assert runtime.tasks == ()
    assert all(task.done() for task in tasks)


@pytest.mark.asyncio
async def test_failed_pass_is_isolated_and_the_next_pass_runs() -> None:
    second_pass = asyncio.Event()
    attempts = 0

    async def flaky_seal():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary sealer failure")
        second_pass.set()
        return 1

    runtime = ThresholdRuntime(
        sealer_repository=SimpleNamespace(
            seal_due_reward_threshold_promotions=flaky_seal
        ),
        release_recovery=SimpleNamespace(run_once=AsyncMock(return_value={})),
        seal_interval_seconds=0.001,
        release_interval_seconds=60,
    )
    await runtime.start()
    await asyncio.wait_for(second_pass.wait(), timeout=1)
    await runtime.stop()

    assert attempts >= 2


@pytest.mark.asyncio
async def test_pass_timeout_cancels_blocking_work_without_killing_loop() -> None:
    operation_cancelled = asyncio.Event()
    retry_sleep_reached = asyncio.Event()

    async def blocking_operation():
        try:
            await asyncio.Event().wait()
        finally:
            operation_cancelled.set()

    async def controlled_sleep(_seconds: float):
        retry_sleep_reached.set()
        await asyncio.Event().wait()

    runtime = ThresholdRuntime(
        sealer_repository=SimpleNamespace(),
        release_recovery=SimpleNamespace(),
        pass_timeout_seconds=0.01,
        sleep=controlled_sleep,
    )
    task = asyncio.create_task(
        runtime._run_loop(
            name="test",
            operation=blocking_operation,
            interval_seconds=1,
        )
    )
    await asyncio.wait_for(retry_sleep_reached.wait(), timeout=1)
    assert operation_cancelled.is_set()
    assert task.done() is False
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_release_factory_shares_one_repository_and_executor() -> None:
    repository = MagicMock()
    ride_repository = MagicMock()
    fitness_repository = MagicMock()
    executor = MagicMock()
    with (
        patch(
            "app.repositories.create_ride_economic_repository",
            return_value=repository,
        ),
        patch(
            "app.services.threshold_release_executor.ThresholdReleaseExecutor",
            return_value=executor,
        ),
        patch(
            "app.repositories.create_ride_repository",
            return_value=ride_repository,
        ),
        patch(
            "app.repositories.create_fitness_repository",
            return_value=fitness_repository,
        ),
    ):
        recovery = create_threshold_release_recovery_loop(7)

    assert recovery.batch_size == 7
    assert recovery.planner.repository is repository
    assert recovery.coordinator.repository is repository
    assert recovery.planner.executor is executor
    assert recovery.coordinator.executor is executor
    assert recovery.coordinator.training_projector.ride_repository is ride_repository


@pytest.mark.asyncio
async def test_api_lifespan_starts_and_stops_threshold_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "a" * 64)
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "b" * 64)
    from app import main

    runtime = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    nats_client = SimpleNamespace(connect=AsyncMock())
    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setenv("ENABLE_EPOCH_PROCESSOR", "false")
    monkeypatch.setenv("ENABLE_NATS_RIDE_CONSUMER", "false")
    monkeypatch.setenv("ENABLE_THRESHOLD_RUNTIME", "true")

    with (
        patch.object(main, "get_supabase_client", return_value=MagicMock()),
        patch.object(main, "check_migration_status", new=AsyncMock()),
        patch(
            "app.services.vault_indexer.get_vault_signature_cache",
            return_value=SimpleNamespace(load=AsyncMock(return_value=0)),
        ),
        patch(
            "app.services.pattern_engine.get_climb_frequency_map",
            return_value=SimpleNamespace(load=AsyncMock(return_value=0)),
        ),
        patch(
            "app.services.threshold_runtime.create_threshold_runtime",
            return_value=runtime,
        ),
        patch(
            "app.services.nats_client.get_nats_client",
            return_value=nats_client,
        ),
        patch("app.services.nats_consumer.stop_consumer", new=AsyncMock()),
        patch("app.db_pool.close_pool", new=AsyncMock()),
    ):
        async with main.lifespan(app):
            runtime.start.assert_awaited_once_with()
            assert app.state.threshold_runtime is runtime

    runtime.stop.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_api_lifespan_fails_closed_when_threshold_runtime_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "a" * 64)
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "b" * 64)
    from app import main

    app = SimpleNamespace(state=SimpleNamespace())
    monkeypatch.setenv("ENABLE_EPOCH_PROCESSOR", "false")
    monkeypatch.setenv("ENABLE_NATS_RIDE_CONSUMER", "false")
    monkeypatch.setenv("ENABLE_THRESHOLD_RUNTIME", "true")

    with (
        patch.object(main, "get_supabase_client", return_value=MagicMock()),
        patch.object(main, "check_migration_status", new=AsyncMock()),
        patch(
            "app.services.vault_indexer.get_vault_signature_cache",
            return_value=SimpleNamespace(load=AsyncMock(return_value=0)),
        ),
        patch(
            "app.services.pattern_engine.get_climb_frequency_map",
            return_value=SimpleNamespace(load=AsyncMock(return_value=0)),
        ),
        patch(
            "app.services.threshold_runtime.create_threshold_runtime",
            side_effect=RuntimeError("runtime unavailable"),
        ),
        patch(
            "app.services.nats_client.get_nats_client",
            return_value=SimpleNamespace(connect=AsyncMock()),
        ),
        patch("app.services.nats_consumer.stop_consumer", new=AsyncMock()),
        patch("app.db_pool.close_pool", new=AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="runtime unavailable"):
            async with main.lifespan(app):
                pytest.fail("lifespan must not become healthy without Threshold runtime")
