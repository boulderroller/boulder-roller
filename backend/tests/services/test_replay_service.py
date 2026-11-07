from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.replay_service import ReplayService


def _build_replay_client(batch_row):
    client = MagicMock()
    table = client.table.return_value
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = (
        [] if batch_row is None else [batch_row]
    )
    return client, table


def _replay_client_without_profile_snapshot():
    client = MagicMock()
    execute = (
        client.table.return_value.select.return_value.eq.return_value.eq.return_value
        .order.return_value.limit.return_value.execute
    )
    execute.return_value = MagicMock(data=[])
    return client


@pytest.mark.asyncio
async def test_promote_batch_raises_for_missing_batch():
    client, _table = _build_replay_client(None)
    service = ReplayService(client)

    with pytest.raises(ValueError, match="not found"):
        await service.promote_batch("batch-1", reviewed_by="admin@example.com")


@pytest.mark.asyncio
async def test_promote_batch_raises_for_dry_run_batch():
    client, _table = _build_replay_client(
        {"id": "batch-1", "status": "completed", "dry_run": True}
    )
    service = ReplayService(client)

    with pytest.raises(ValueError, match="dry-run"):
        await service.promote_batch("batch-1", reviewed_by="admin@example.com")


@pytest.mark.asyncio
async def test_promote_batch_is_disabled_without_mutating_state():
    client, table = _build_replay_client(
        {"id": "batch-1", "status": "completed", "dry_run": False}
    )
    service = ReplayService(client)

    with pytest.raises(NotImplementedError, match="disabled"):
        await service.promote_batch("batch-1", reviewed_by="admin@example.com")

    table.update.assert_not_called()


@pytest.mark.asyncio
async def test_replay_fallback_reads_the_derived_threshold_authority_directly():
    user_repo = MagicMock()
    user_repo.get_user_by_id = AsyncMock(
        return_value={"id": "user-1", "wallet": "wallet-1", "weight_kg": 81.4}
    )
    ride_repo = MagicMock()
    ride_repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 245,
                "kind": "sealed",
                "provisional": False,
            },
        }
    )
    service = ReplayService(_replay_client_without_profile_snapshot())

    with patch(
        "app.services.replay_service.create_user_repository",
        return_value=user_repo,
    ), patch(
        "app.services.replay_service.create_ride_repository",
        return_value=ride_repo,
    ):
        weight, threshold = await service._get_profile_snapshot(
            "ride-1", user_id="user-1"
        )

    assert weight == 81.4
    assert threshold == 245
    ride_repo.get_reward_threshold_rider_projection.assert_awaited_once_with("user-1")


@pytest.mark.asyncio
async def test_replay_fallback_rejects_the_nonpaying_network_placeholder():
    user_repo = MagicMock()
    user_repo.get_user_by_id = AsyncMock(
        return_value={"id": "user-1", "wallet": "wallet-1", "weight_kg": 81.4}
    )
    ride_repo = MagicMock()
    ride_repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "establishing",
            "current_w": None,
            "established_at": None,
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 200,
                "kind": "network_placeholder",
                "provisional": True,
            },
        }
    )
    service = ReplayService(_replay_client_without_profile_snapshot())

    with patch(
        "app.services.replay_service.create_user_repository",
        return_value=user_repo,
    ), patch(
        "app.services.replay_service.create_ride_repository",
        return_value=ride_repo,
    ), pytest.raises(RuntimeError, match="established derived Threshold"):
        await service._get_profile_snapshot("ride-1", user_id="user-1")
