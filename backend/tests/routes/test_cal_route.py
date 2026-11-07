from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.dependencies import AuthenticatedUser
from app.routes import cal as cal_routes


@pytest.mark.asyncio
async def test_cal_route_returns_exact_human_and_base_unit_strings() -> None:
    current_user = AuthenticatedUser(
        wallet="WalletCalExact111111111111111111111111",
        user_id="user-cal-exact",
        device_id="device-cal-exact",
    )

    with patch(
        "app.solana_direct.get_cal_balance_base_units",
        new=AsyncMock(return_value=9_007_199_254_740_993),
    ):
        response = await cal_routes.get_cal_onchain(
            current_user=current_user,
            repo=SimpleNamespace(),
        )

    assert response.calBalance == "9007199.254740993"
    assert response.calBalanceBaseUnits == "9007199254740993"
    assert response.canMintToday is False
