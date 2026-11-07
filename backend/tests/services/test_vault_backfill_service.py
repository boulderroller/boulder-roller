from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import app.services.backfill_service as backfill_module

from app.services.backfill_service import (
    ClimbMatch,
    VaultBackfillService,
    enqueue_vault_backfill_job,
    get_pending_backfill_jobs,
)


V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)


@pytest.fixture(autouse=True)
def _exercise_legacy_backfill_units_under_their_original_family(monkeypatch):
    monkeypatch.setattr(backfill_module, "PROGRAM_VERSION_FAMILY", "V4-A")


@pytest.mark.asyncio
async def test_v4b_hard_disables_detector_backfill_before_any_database_write(monkeypatch):
    monkeypatch.setattr(backfill_module, "PROGRAM_VERSION_FAMILY", "V4-B")
    client = MagicMock()
    result = await VaultBackfillService(client).backfill_vault(7, "ab" * 64)

    assert result.status == "failed"
    assert "disabled for V4-B" in (result.error or "")
    client.rpc.assert_not_called()
    client.from_.assert_not_called()


@pytest.mark.asyncio
async def test_process_completion_refuses_receiptless_projection():
    service = VaultBackfillService(MagicMock())
    service._vault_repo = MagicMock()
    service._vault_repo.record_completion = AsyncMock(return_value={"id": "completion-1", "validated": True})
    service._vault_repo.update_leaderboard = AsyncMock()

    completed_at = datetime(2025, 5, 1, 12, 30, tzinfo=timezone.utc)
    climb = ClimbMatch(
        pattern_id=uuid4(),
        activity_id=uuid4(),
        wallet="Wallet111111111111111111111111111111111",
        time_s=812,
        vert_m=542.0,
        signature_hex="ab" * 64,
        avg_power_w=301.4,
        completed_at=completed_at,
        similarity=1.0,
    )

    with pytest.raises(RuntimeError, match="receipt-less historical completions"):
        await service.process_completion("ab" * 64, climb)

    service._vault_repo.record_completion.assert_not_awaited()
    service._vault_repo.update_leaderboard.assert_not_called()


@pytest.mark.asyncio
async def test_nonempty_backfill_requires_sealed_manifest_before_projection():
    client = MagicMock()
    start_rpc = MagicMock()
    start_rpc.execute.return_value = SimpleNamespace(data=True)
    complete_rpc = MagicMock()
    complete_rpc.execute.return_value = SimpleNamespace(data=True)
    client.rpc.side_effect = lambda name, payload: {
        "start_backfill_job": start_rpc,
        "complete_backfill_job": complete_rpc,
    }[name]

    service = VaultBackfillService(client)
    service._get_vault = AsyncMock(
        return_value={
            "id": 7,
            "signature_hex": "cd" * 64,
            "vert_m": 550.0,
            "avg_gradient_pct": 6.8,
            "signature_version": 2,
            "signature_v2_hex": V2_SIGNATURE_HEX,
            "start_lat": 39.9500,
            "start_lon": -75.1600,
            "end_lat": 39.9550,
            "end_lon": -75.1600,
        }
    )

    existing_activity_id = uuid4()
    new_activity_id = uuid4()
    matches = [
        ClimbMatch(
            pattern_id=uuid4(),
            activity_id=existing_activity_id,
            wallet="WalletExisting",
            time_s=900,
            vert_m=550.0,
            signature_hex="cd" * 64,
            avg_power_w=250.0,
            completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            similarity=1.0,
        ),
        ClimbMatch(
            pattern_id=uuid4(),
            activity_id=new_activity_id,
            wallet="WalletNew",
            time_s=870,
            vert_m=550.0,
            signature_hex="cd" * 64,
            avg_power_w=275.0,
            completed_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            similarity=1.0,
        ),
    ]
    service.find_matching_climbs = AsyncMock(return_value=matches)
    service._get_existing_activity_ids = AsyncMock(return_value={str(existing_activity_id)})
    service.process_completion = AsyncMock(return_value=(True, False))

    fail_rpc = MagicMock()
    fail_rpc.execute.return_value = SimpleNamespace(data=True)
    client.rpc.side_effect = lambda name, payload: {
        "start_backfill_job": start_rpc,
        "complete_backfill_job": complete_rpc,
        "fail_backfill_job": fail_rpc,
    }[name]

    result = await service.backfill_vault(7, "cd" * 64, job_id="job-7")

    assert result.status == "failed"
    assert "sealed generation-2 seed manifest" in (result.error or "")
    service._get_existing_activity_ids.assert_not_awaited()
    service.process_completion.assert_not_awaited()
    complete_rpc.execute.assert_not_called()
    fail_rpc.execute.assert_called_once()


@pytest.mark.asyncio
async def test_backfill_vault_returns_skipped_when_job_already_claimed():
    client = MagicMock()
    start_rpc = MagicMock()
    start_rpc.execute.return_value = SimpleNamespace(data=False)
    client.rpc.return_value = start_rpc

    service = VaultBackfillService(client)
    service._get_vault = AsyncMock()

    result = await service.backfill_vault(11, "ef" * 64, job_id="job-11")

    assert result.status == "skipped"
    assert result.matched_count == 0
    assert result.leaderboard_updates == 0
    service._get_vault.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_without_v2_evidence_fails_before_activation():
    service = VaultBackfillService(MagicMock())
    service._get_vault = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "ab" * 64,
            "minter": "WalletMissingIdentity",
            "vert_m": 120.0,
            "signature_v2_hex": None,
            "start_lat": 39.9500,
            "start_lon": -75.1600,
            "end_lat": 39.9550,
            "end_lon": -75.1600,
        }
    )
    service.find_matching_climbs = AsyncMock()
    service._trigger_vault_activation = AsyncMock()
    service._update_vault_backfill_status = MagicMock()
    service._update_vault_backfill_failed = MagicMock()

    result = await service.backfill_vault(12, "ab" * 64)

    assert result.status == "failed"
    assert "evidence" in (result.error or "")
    service.find_matching_climbs.assert_not_awaited()
    service._trigger_vault_activation.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_bootstraps_unambiguous_v2_identity_before_matching():
    client = MagicMock()
    service = VaultBackfillService(client)
    vault = {
        "id": 14,
        "signature_hex": "ab" * 64,
        "minter": "WalletVaultCreator",
        "vert_m": 120.0,
        "signature_version": 1,
        "signature_v2_hex": None,
        "start_lat": None,
        "start_lon": None,
        "end_lat": None,
        "end_lon": None,
    }
    identity_patch = {
        "signature_version": 2,
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "start_lat": 39.9500,
        "start_lon": -75.1600,
        "end_lat": 39.9550,
        "end_lon": -75.1600,
    }
    identity = SimpleNamespace(
        as_indexed_vault_patch=MagicMock(return_value=identity_patch)
    )
    service._get_vault = AsyncMock(return_value=vault)
    service.find_matching_climbs = AsyncMock(return_value=[])
    service._get_existing_activity_ids = AsyncMock(return_value=set())
    service._trigger_vault_activation = AsyncMock()
    service._update_vault_backfill_status = MagicMock()
    service._update_vault_backfill_completed = MagicMock()
    service._update_vault_backfill_failed = MagicMock()

    with patch(
        "app.services.backfill_service.reconcile_indexed_vault_reward_identity",
        return_value=identity,
    ) as reconcile:
        result = await service.backfill_vault(14, "ab" * 64)

    assert result.status == "completed"
    reconcile.assert_called_once_with(client=client, vault=vault, apply=True)
    service.find_matching_climbs.assert_awaited_once_with(
        vault_signature_v2_hex=V2_SIGNATURE_HEX,
        vault_start=(39.9500, -75.1600),
        vault_end=(39.9550, -75.1600),
    )
    service._trigger_vault_activation.assert_awaited_once()


@pytest.mark.asyncio
async def test_backfill_rejects_v1_key_that_does_not_match_indexed_vault():
    service = VaultBackfillService(MagicMock())
    service._get_vault = AsyncMock(
        return_value={
            "id": 15,
            "signature_hex": "cd" * 64,
            "signature_version": 2,
            "signature_v2_hex": V2_SIGNATURE_HEX,
            "start_lat": 39.9500,
            "start_lon": -75.1600,
            "end_lat": 39.9550,
            "end_lon": -75.1600,
        }
    )
    service.find_matching_climbs = AsyncMock()
    service._trigger_vault_activation = AsyncMock()
    service._update_vault_backfill_status = MagicMock()
    service._update_vault_backfill_failed = MagicMock()

    result = await service.backfill_vault(15, "ab" * 64)

    assert result.status == "failed"
    assert "does not match indexed vault" in (result.error or "")
    service.find_matching_climbs.assert_not_awaited()
    service._trigger_vault_activation.assert_not_awaited()


@pytest.mark.asyncio
async def test_historical_v1_exact_match_cannot_create_backfill_completion():
    client = MagicMock()
    query = MagicMock()
    for method_name in (
        "select",
        "eq",
        "gte",
        "lte",
        "order",
        "range",
    ):
        getattr(query, method_name).return_value = query
    query.not_.is_.return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": str(uuid4()),
                "activity_id": str(uuid4()),
                "wallet": "WalletLegacy",
                "time_s": 800,
                "vert_m": 120.0,
                "signature_hex": "ab" * 64,
                "signature_v2_hex": None,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                "avg_power_w": 250.0,
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
    )
    client.from_.return_value = query
    service = VaultBackfillService(client)

    with patch(
        "app.services.backfill_service.match_reward_grade_v2",
        return_value=SimpleNamespace(similarity=1.0),
    ):
        matches = await service.find_matching_climbs(
            vault_signature_v2_hex=V2_SIGNATURE_HEX,
            vault_start=(39.9500, -75.1600),
            vault_end=(39.9550, -75.1600),
        )

    assert matches == []
    query.range.assert_called_once_with(0, 999)
    query.gte.assert_not_called()
    query.lte.assert_not_called()


@pytest.mark.asyncio
async def test_ride_timestamp_lookup_failure_blocks_historical_seed():
    client = MagicMock()
    query = MagicMock()
    query.select.return_value = query
    query.in_.return_value = query
    query.execute.side_effect = RuntimeError("rides lookup unavailable")
    client.from_.return_value = query
    service = VaultBackfillService(client)

    with pytest.raises(RuntimeError, match="rides lookup unavailable"):
        await service._get_activity_completion_times([str(uuid4())])


@pytest.mark.asyncio
async def test_economically_ineligible_historical_climb_cannot_backfill():
    client = MagicMock()
    query = MagicMock()
    for method_name in (
        "select",
        "eq",
        "gte",
        "lte",
        "order",
        "range",
    ):
        getattr(query, method_name).return_value = query
    query.not_.is_.return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": str(uuid4()),
                "activity_id": str(uuid4()),
                "wallet": "WalletIneligible",
                "time_s": 800,
                "vert_m": 120.0,
                "signature_hex": "ab" * 64,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                "avg_power_w": 250.0,
                "economic_eligible": False,
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
    )
    client.from_.return_value = query
    service = VaultBackfillService(client)

    with patch(
        "app.services.backfill_service.match_reward_grade_v2",
        return_value=SimpleNamespace(similarity=1.0),
    ):
        matches = await service.find_matching_climbs(
            vault_signature_v2_hex=V2_SIGNATURE_HEX,
            vault_start=(39.9500, -75.1600),
            vault_end=(39.9550, -75.1600),
        )

    assert matches == []
    query.eq.assert_any_call("economic_eligible", True)


@pytest.mark.asyncio
async def test_completion_write_failure_marks_backfill_failed_and_blocks_activation():
    service = VaultBackfillService(MagicMock())
    service._get_vault = AsyncMock(
        return_value={
            "id": 13,
            "signature_hex": "ab" * 64,
            "vert_m": 120.0,
            "signature_version": 2,
            "signature_v2_hex": V2_SIGNATURE_HEX,
            "start_lat": 39.9500,
            "start_lon": -75.1600,
            "end_lat": 39.9550,
            "end_lon": -75.1600,
        }
    )
    match = ClimbMatch(
        pattern_id=uuid4(),
        activity_id=uuid4(),
        wallet="WalletWriteFailure",
        time_s=800,
        vert_m=120.0,
        signature_hex="ab" * 64,
        avg_power_w=250.0,
        completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        similarity=1.0,
    )
    service.find_matching_climbs = AsyncMock(return_value=[match])
    service._get_existing_activity_ids = AsyncMock(return_value=set())
    service.process_completion = AsyncMock(side_effect=RuntimeError("database unavailable"))
    service._trigger_vault_activation = AsyncMock()
    service._update_vault_backfill_status = MagicMock()
    service._update_vault_backfill_completed = MagicMock()
    service._update_vault_backfill_failed = MagicMock()

    result = await service.backfill_vault(13, "ab" * 64)

    assert result.status == "failed"
    assert "sealed generation-2 seed manifest" in (result.error or "")
    service._update_vault_backfill_completed.assert_not_called()
    service._trigger_vault_activation.assert_not_awaited()


@pytest.mark.asyncio
async def test_enqueue_vault_backfill_job_dispatches_immediately():
    delay = MagicMock()
    fake_tasks_module = SimpleNamespace(
        backfill_vault_leaderboard=SimpleNamespace(delay=delay)
    )

    with (
        patch("app.services.backfill_service.queue_vault_backfill", new=AsyncMock(return_value="job-42")) as queue_mock,
        patch.dict(sys.modules, {"app.tasks": fake_tasks_module}),
    ):
        job_id = await enqueue_vault_backfill_job(
            supabase_client=MagicMock(),
            vault_id=42,
            vault_signature="12" * 64,
            priority=100,
        )

    assert job_id == "job-42"
    queue_mock.assert_awaited_once_with(
        supabase_client=ANY,
        vault_id=42,
        vault_signature="12" * 64,
        priority=100,
    )
    delay.assert_called_once_with(vault_id=42, vault_signature="12" * 64, job_id="job-42")


@pytest.mark.asyncio
async def test_get_pending_backfill_jobs_reconciles_before_reading_ready_jobs():
    client = MagicMock()
    ready_jobs = [
        {
            "id": "job-42",
            "vault_id": 42,
            "vault_signature": "12" * 64,
            "priority": 100,
        }
    ]
    rpc_result = MagicMock()
    rpc_result.execute.return_value = SimpleNamespace(data=ready_jobs)
    client.rpc.return_value = rpc_result

    jobs = await get_pending_backfill_jobs(client, limit=7)

    assert jobs == ready_jobs
    client.rpc.assert_called_once_with(
        "get_ready_vault_backfill_jobs",
        {"p_limit": 7},
    )
