from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from app import tasks
from app.services.account_deletion import (
    AccountDeletionExecutionResult,
    DeletionExecutionStatus,
)


def test_account_deletion_task_returns_durable_worker_outcome() -> None:
    outcome = AccountDeletionExecutionResult(
        request_id="request-1",
        status=DeletionExecutionStatus.NEEDS_SUPPORT,
    )
    with patch.object(tasks, "_run_account_deletion", AsyncMock(return_value=outcome)):
        result = tasks.process_account_deletion.run(request_id="request-1")

    assert result == {
        "request_id": "request-1",
        "status": "needs_support",
        "blockers": [],
        "failure_code": None,
    }


def test_recovery_scan_requeues_every_durable_candidate() -> None:
    with (
        patch.object(
            tasks,
            "_list_recoverable_account_deletions",
            AsyncMock(return_value=["request-1", "request-2"]),
        ),
        patch.object(tasks.process_account_deletion, "delay", Mock()) as enqueue,
    ):
        result = tasks.recover_account_deletions.run()

    assert result == {"queued": 2}
    assert [call.kwargs for call in enqueue.call_args_list] == [
        {"request_id": "request-1"},
        {"request_id": "request-2"},
    ]


def test_recovery_task_is_present_in_celery_beat() -> None:
    schedule = tasks.celery_app.conf["beat_schedule"]

    assert schedule["recover-account-deletions-every-minute"] == {
        "task": "app.tasks.recover_account_deletions",
        "schedule": 60.0,
    }


def test_account_deletion_worker_limits_expire_before_its_lease() -> None:
    assert tasks.process_account_deletion.soft_time_limit == 240
    assert tasks.process_account_deletion.time_limit == 270
    assert tasks.process_account_deletion.time_limit < 300


@pytest.mark.asyncio
async def test_worker_uses_the_shared_account_deletion_authority_builder() -> None:
    reader = object()
    repository = object()
    storage = object()
    outcome = AccountDeletionExecutionResult(
        request_id="request-1",
        status=DeletionExecutionStatus.NEEDS_SUPPORT,
    )
    with (
        patch(
            "app.compliance_repository.ComplianceRepository",
            return_value=repository,
        ),
        patch(
            "app.services.account_deletion_factory.build_account_deletion_authority_reader",
            return_value=reader,
        ) as build_reader,
        patch(
            "app.services.account_deletion.execute_account_deletion",
            AsyncMock(return_value=outcome),
        ) as execute,
        patch(
            "app.services.file_storage.create_file_storage_service",
            return_value=storage,
        ),
    ):
        result = await tasks._run_account_deletion("request-1")

    assert result is outcome
    build_reader.assert_called_once_with(repository)
    execute.assert_awaited_once_with(
        "request-1",
        repository=repository,
        preflight_reader=reader,
        storage=storage,
    )
