from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import AuthenticatedUser
from app.routes import feed as feed_routes
from app.routes import users as user_routes


class Dumpable:
    def __init__(self, payload: dict):
        self.payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, *args, **kwargs) -> dict:
        return dict(self.payload)


@pytest.mark.asyncio
async def test_home_popular_climbs_projects_exact_active_cal() -> None:
    query = MagicMock()
    for method_name in ("select", "order", "limit"):
        getattr(query, method_name).return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": 7,
                "name": "Exact Hill",
                "signature_hex": "ab" * 32,
                "vert_m": 125,
                "total_completions": 9,
            }
        ]
    )
    client = MagicMock()
    client.from_.return_value = query

    async def _run(callback):
        return callback()

    repo = SimpleNamespace(client=client, _run=_run)
    totals_repo = SimpleNamespace(
        get_vault_stake_totals=AsyncMock(
            return_value={
                7: {
                    "total_cal_staked": 9_007_199_254_740_993,
                    "total_lp_tokens": 0,
                }
            }
        )
    )

    with patch.object(
        feed_routes,
        "VaultRepository",
        return_value=totals_repo,
        create=True,
    ):
        climbs = await feed_routes._home_popular_climbs(repo, 6)

    assert climbs[0]["staked"] == "9007199.254740993"
    assert climbs[0]["stakedBaseUnits"] == "9007199254740993"
    totals_repo.get_vault_stake_totals.assert_awaited_once_with([7])


@pytest.mark.asyncio
async def test_home_feed_contract_bundles_feed_and_sidecars_for_first_paint():
    with (
        patch.object(
            feed_routes,
            "get_global_feed",
            new=AsyncMock(return_value={"contractVersion": "feed.v1", "activities": [{"id": "activity-1"}]}),
        ),
        patch.object(feed_routes, "_home_suggested_riders", new=AsyncMock(return_value=[])),
        patch.object(feed_routes, "_home_popular_climbs", new=AsyncMock(return_value=[{"id": "climb-1"}])),
        patch.object(feed_routes, "_home_achievements", new=AsyncMock(return_value=[])),
        patch.object(feed_routes, "_home_unread_count", new=AsyncMock(return_value=0)),
    ):
        response = await feed_routes.get_home_feed(
            limit=10,
            before=None,
            scope="global",
            sidecar_limit=4,
            current_user=None,
            repo=MagicMock(),
            achievements_repo=MagicMock(),
        )

    assert response["contractVersion"] == "feed_home.v1"
    assert response["scope"] == "global"
    assert response["viewer"]["authenticated"] is False
    assert response["feed"]["activities"][0]["id"] == "activity-1"
    assert response["popularClimbs"] == [{"id": "climb-1"}]
    assert response["socialCounts"] == {"followerCount": 0, "followingCount": 0}


@pytest.mark.asyncio
async def test_private_profile_bootstrap_contract_bundles_account_modules():
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")
    leaderboard = Dumpable({"positions": [{"vaultId": 7}], "summary": {"rank": 3}})
    profile = Dumpable({"id": "user-1", "wallet": "wallet-1", "username": "rider"})

    with (
        patch.object(user_routes, "load_private_user_profile", new=AsyncMock(return_value=profile)),
        patch.object(user_routes, "_private_beetle_cards", new=AsyncMock(return_value=[{"card_type": "climb"}])),
        patch.object(user_routes, "_leaderboard_summary_for_wallet", new=AsyncMock(return_value=leaderboard)),
        patch.object(user_routes, "_private_unread_count", new=AsyncMock(return_value=5)),
    ):
        response = await user_routes.get_my_profile_bootstrap(
            current_user=current_user,
            user_repo=MagicMock(),
            ride_repo=MagicMock(),
            repo=MagicMock(),
            vault_repo=MagicMock(),
        )

    assert response["contractVersion"] == "private_rider_profile.v1"
    assert response["profile"]["username"] == "rider"
    assert response["beetleCards"]["count"] == 1
    assert response["leaderboard"]["positions"] == [{"vaultId": 7}]
    assert response["notifications"]["unreadCount"] == 5
    assert [module["id"] for module in response["modules"]] == [
        "profile",
        "beetle_cards",
        "leaderboard",
        "notifications",
    ]
