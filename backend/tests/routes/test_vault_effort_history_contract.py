import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

from app.dependencies import AuthenticatedUser
from app.routes.vaults import get_my_vault_effort_history


@pytest.mark.asyncio
async def test_my_climb_results_preserve_attempt_count_and_ride_destination() -> None:
    user = AuthenticatedUser(
        wallet="RiderWallet111111111111111111111111111",
        user_id="rider-1",
        device_id="device-1",
    )
    repository = SimpleNamespace(
        get_vault_by_id=AsyncMock(
            return_value={
                "id": 42,
                "name": "Barren Hill Road",
                "signature_hex": "ab" * 32,
            }
        ),
        get_user_vault_effort_history=AsyncMock(
            return_value=[
                {
                    "id": "completion-1",
                    "rideId": "ride-1",
                    "timeSeconds": 2275,
                    "avgPowerW": 242,
                    "achievedAt": "2026-08-14T11:05:00+00:00",
                    "isPR": True,
                    "improvement": 18,
                    "attemptCount": 6,
                }
            ]
        ),
    )

    response = await get_my_vault_effort_history(
        vault_id=42,
        limit=50,
        current_user=user,
        vault_repo=repository,
    )
    payload = response.model_dump()

    assert payload["totalCount"] == 6
    assert payload["bestTimeSeconds"] == 2275
    assert payload["efforts"][0]["rideId"] == "ride-1"
