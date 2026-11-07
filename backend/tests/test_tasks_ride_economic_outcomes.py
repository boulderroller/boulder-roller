from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app import tasks
from app.celery_app import celery_app


@pytest.mark.parametrize("status", ["recovery_pending", "under_review"])
def test_legacy_task_preserves_nonterminal_processor_outcome(status: str) -> None:
    ride_id = str(uuid4())
    user_id = str(uuid4())
    processor = MagicMock()
    processor.process_ride = AsyncMock(
        return_value={
            "status": status,
            "ride_id": ride_id,
            "cal_earned": 0,
            "durable_checkpoint": False,
            "economic_state": "planned",
            "error": "economic checkpoint unavailable",
        }
    )

    with (
        patch.object(tasks, "PHASED_PROCESSING_ENABLED", False),
        patch.object(tasks, "RideProcessor", return_value=processor),
        patch.object(tasks, "_update_queue_depth"),
    ):
        result = tasks.process_ride_upload.run(
            ride_id=ride_id,
            file_type="fit",
            user_id=user_id,
            file_data_b64="ZmFrZQ==",
        )

    assert result["status"] == status
    assert result["durable_checkpoint"] is False
    assert result["economic_state"] == "planned"
    assert result["error"] == "economic checkpoint unavailable"


def test_phase2_task_retries_transient_freeze_failure_without_queueing_phase3() -> None:
    ride_id = str(uuid4())
    user_id = str(uuid4())
    processor = MagicMock()
    processor.process_phase2_enrichment = AsyncMock(
        return_value={
            "status": "phase2_failed",
            "ride_id": ride_id,
            "error": "freeze_ride_economic_plan: database unavailable",
            "duration_ms": 12,
        }
    )
    retry_signal = RuntimeError("phase2 retry scheduled")

    with (
        patch.object(tasks, "RideProcessor", return_value=processor),
        patch.object(tasks, "_update_queue_depth"),
        patch.object(tasks.process_ride_phase3, "delay") as phase3_delay,
        patch.object(
            tasks.process_ride_phase2,
            "retry",
            return_value=retry_signal,
        ) as retry,
    ):
        with pytest.raises(RuntimeError, match="phase2 retry scheduled"):
            tasks.process_ride_phase2.run(ride_id=ride_id, user_id=user_id)

    retry.assert_called_once()
    assert "freeze_ride_economic_plan" in str(retry.call_args.kwargs["exc"])
    assert retry.call_args.kwargs["countdown"] == 30
    assert retry.call_args.kwargs["max_retries"] == 2
    phase3_delay.assert_not_called()


def test_phase2_task_retries_raised_processor_failure() -> None:
    ride_id = str(uuid4())
    user_id = str(uuid4())
    processor = MagicMock()
    processor.process_phase2_enrichment = AsyncMock(
        side_effect=RuntimeError("transient phase2 exception")
    )
    retry_signal = RuntimeError("phase2 retry scheduled")

    with (
        patch.object(tasks, "RideProcessor", return_value=processor),
        patch.object(tasks, "_update_queue_depth"),
        patch.object(tasks.process_ride_phase3, "delay") as phase3_delay,
        patch.object(
            tasks.process_ride_phase2,
            "retry",
            return_value=retry_signal,
        ) as retry,
    ):
        with pytest.raises(RuntimeError, match="phase2 retry scheduled"):
            tasks.process_ride_phase2.run(ride_id=ride_id, user_id=user_id)

    retry.assert_called_once()
    assert "transient phase2 exception" in str(retry.call_args.kwargs["exc"])
    assert retry.call_args.kwargs["countdown"] == 30
    assert retry.call_args.kwargs["max_retries"] == 2
    phase3_delay.assert_not_called()


def test_phase3_task_preserves_recovery_checkpoint_fields() -> None:
    ride_id = str(uuid4())
    user_id = str(uuid4())
    processor = MagicMock()
    processor.process_phase3_rewards = AsyncMock(
        return_value={
            "status": "recovery_pending",
            "ride_id": ride_id,
            "duration_ms": 15,
            "durable_checkpoint": True,
            "economic_state": "attestation_confirmed",
            "error": "completion RPC unavailable",
        }
    )

    with (
        patch.object(tasks, "RideProcessor", return_value=processor),
        patch.object(tasks, "_update_queue_depth"),
    ):
        result = tasks.process_ride_phase3.run(ride_id=ride_id, user_id=user_id)

    assert result["status"] == "recovery_pending"
    assert result["durable_checkpoint"] is True
    assert result["economic_state"] == "attestation_confirmed"
    assert result["error"] == "completion RPC unavailable"


def test_celery_worker_mode_has_periodic_frozen_plan_recovery() -> None:
    schedule = celery_app.conf.get("beat_schedule", {})
    assert schedule["recover-ride-economics-every-15-sec"] == {
        "task": "app.tasks.recover_ride_economics",
        "schedule": 15.0,
    }
    assert hasattr(tasks, "recover_ride_economics")


def test_celery_worker_mode_has_periodic_threshold_release_recovery() -> None:
    schedule = celery_app.conf["beat_schedule"]
    assert schedule["recover-threshold-releases-every-15-sec"] == {
        "task": "app.tasks.recover_threshold_releases",
        "schedule": 15.0,
    }
    assert tasks.recover_threshold_releases.soft_time_limit == 240
    assert tasks.recover_threshold_releases.time_limit == 270
    assert hasattr(tasks, "recover_threshold_releases")
    assert schedule["seal-reward-threshold-mondays-every-minute"] == {
        "task": "app.tasks.seal_reward_threshold_promotions",
        "schedule": 60.0,
    }


def test_threshold_release_soft_limit_never_claims_a_durable_checkpoint() -> None:
    recovery = MagicMock()
    recovery.run_once = AsyncMock(side_effect=SoftTimeLimitExceeded())

    with patch.object(
        tasks,
        "_create_threshold_release_recovery_loop",
        return_value=recovery,
    ):
        result = tasks.recover_threshold_releases.run(limit=7)

    assert result == {
        "status": "soft_time_limit",
        "durable_checkpoint": False,
    }


def test_threshold_release_recovery_factory_wires_dedicated_executor() -> None:
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
        recovery = tasks._create_threshold_release_recovery_loop(7)

    assert recovery.batch_size == 7
    assert recovery.planner.repository is repository
    assert recovery.planner.executor is executor
    assert recovery.coordinator.repository is repository
    assert recovery.coordinator.executor is executor
    assert recovery.coordinator.training_projector.ride_repository is ride_repository


def test_threshold_sealer_task_uses_private_repository_rpc() -> None:
    repository = MagicMock()
    repository.seal_due_reward_threshold_promotions = AsyncMock(return_value=2)

    with patch.object(tasks, "create_ride_repository", return_value=repository):
        result = tasks.seal_reward_threshold_promotions.run()

    assert result == {"sealed": 2}
    repository.seal_due_reward_threshold_promotions.assert_awaited_once_with()


def test_celery_recovery_factory_wires_terminal_projector() -> None:
    economic_repository = MagicMock()
    ride_repository = MagicMock()
    notification_repository = MagicMock()

    with (
        patch(
            "app.repositories.create_ride_economic_repository",
            return_value=economic_repository,
        ),
        patch(
            "app.repositories.create_ride_repository",
            return_value=ride_repository,
        ),
        patch(
            "app.repositories.create_notification_repository",
            return_value=notification_repository,
        ),
        patch("app.services.ride_executor.RideExecutor", return_value=MagicMock()),
    ):
        recovery = tasks._create_ride_economic_recovery_loop(7)

    assert recovery.repository is economic_repository
    assert recovery.batch_size == 7
    projector = recovery.terminal_projector_factory()
    assert projector.economic_repository is economic_repository
    assert projector.ride_repository is ride_repository
    assert projector.notification_repository is notification_repository
