from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

import app.routes.users as user_routes
import app.routes.vaults as vault_routes
from app.dependencies import AuthenticatedUser
from app.services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    PublicRecordBoardProjection,
)


PRIVATE_WINNER = {
    "user": "private-winner",
    "time_s": 60,
    "recorded_at": 1_700_000_000,
}
PUBLIC_SECOND = {
    "user": "public-second",
    "time_s": 70,
    "recorded_at": 1_700_000_100,
    "position": 2,
    "rank": 2,
    "tie_size": 1,
    "is_tied": False,
}


def _vault() -> dict[str, Any]:
    return {
        "id": 44,
        "signature_hex": "ab" * 32,
        "signature_hash_hex": "cd" * 32,
        "name": "Privacy Hill",
        "vert_m": 120,
        "distance_m": 1800,
        "avg_gradient_pct": 6.7,
        "total_completions": 4,
        "total_staked": 0,
        "kom_holder": "private-winner",
        "kom_time_s": 60,
        "minter": "Minter111",
        "pda": "vault-pda",
        "on_chain_seeding_status": "active",
    }


class _UserRepo:
    async def get_public_user_identity(self, wallet: str) -> dict[str, Any] | None:
        if wallet != "public-second":
            return None
        return {
            "id": "public-second-user",
            "wallet": wallet,
            "username": "public_second",
            "display_name": "Public Second",
            "avatar_url": None,
            "is_public": True,
        }


class _VaultRepo:
    def __init__(self) -> None:
        self.client = object()
        self.vault = _vault()
        self.raw_entries = [
            PRIVATE_WINNER,
            {
                key: value
                for key, value in PUBLIC_SECOND.items()
                if key not in {"position", "rank", "tie_size", "is_tied"}
            },
        ]

    async def get_vault_by_id(self, vault_id: int) -> dict[str, Any] | None:
        return dict(self.vault) if vault_id == 44 else None

    async def get_vault_record_board_entries(
        self, vault_id: int
    ) -> list[dict[str, Any]]:
        assert vault_id == 44
        return [dict(entry) for entry in self.raw_entries]

    async def get_vault_detail(self, vault_signature: str) -> dict[str, Any]:
        assert vault_signature == self.vault["signature_hex"]
        return {
            **self.vault,
            "leaderboard": [
                {
                    "position": 1,
                    "rank": 1,
                    "competition_rank": 1,
                    "tie_size": 1,
                    "is_tied": False,
                    "wallet": "private-winner",
                    "best_time_seconds": 60,
                },
                {
                    "position": 2,
                    "rank": 2,
                    "competition_rank": 2,
                    "tie_size": 1,
                    "is_tied": False,
                    "wallet": "public-second",
                    "best_time_seconds": 70,
                },
            ],
            "total_cal_staked": 0,
            "total_lp_tokens": 0,
            "local_legend": None,
        }

    async def get_vault_leaderboard(
        self, vault_signature: str
    ) -> list[dict[str, Any]]:
        return (await self.get_vault_detail(vault_signature))["leaderboard"]

    async def count_vaults(self, **_kwargs: Any) -> int:
        return 1

    async def list_vaults(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [dict(self.vault)]

    async def get_vault_stake_totals(
        self, vault_ids: list[int]
    ) -> dict[int, dict[str, int]]:
        assert vault_ids == [44]
        return {44: {"total_cal_staked": 0, "total_lp_tokens": 0}}

    async def get_user_leaderboard_positions(
        self, wallet: str
    ) -> list[dict[str, Any]]:
        assert wallet == "public-second"
        return [
            {
                "vault_id": 44,
                "canon_climb_id": None,
                "vault_name": "Privacy Hill",
                "vault_signature": self.vault["signature_hex"],
                # Deliberately stale/unfiltered RPC values. The public response
                # must derive its seat from the filtered immutable Board.
                "rank": 1,
                "best_time_seconds": 60,
                "is_kom": True,
                "total_riders": 99,
                "percentile": 1,
                "last_achieved_at": "2026-01-01T00:00:00Z",
            }
        ]

    async def get_user_leaderboard_stats(self, wallet: str) -> dict[str, Any]:
        assert wallet == "public-second"
        return {
            "total_positions": 99,
            "kom_count": 99,
            "podium_count": 99,
            "top10_count": 99,
            "total_vaults_completed": 99,
            "best_percentile": 1,
        }


def _public_projection(*_args: Any, **_kwargs: Any) -> PublicRecordBoardProjection:
    return PublicRecordBoardProjection(
        entries=[dict(PUBLIC_SECOND)],
        kom_holder=None,
        kom_time_s=None,
    )


@pytest.mark.asyncio
async def test_legacy_vault_leaderboard_filters_rows_without_reranking_or_kom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _VaultRepo()
    monkeypatch.setattr(
        vault_routes,
        "project_public_record_board",
        _public_projection,
        raising=False,
    )

    board = await vault_routes.get_vault_leaderboard(
        vault_id=44,
        vault_repo=repo,  # type: ignore[arg-type]
        user_repo=_UserRepo(),  # type: ignore[arg-type]
    )

    assert [entry.wallet for entry in board.entries] == ["public-second"]
    assert board.entries[0].position == 2
    assert board.entries[0].rank == 2
    assert board.entries[0].achieved_at == "2023-11-14T22:15:00+00:00"
    assert board.kom_holder is None
    assert board.kom_time_s is None


@pytest.mark.asyncio
async def test_legacy_vault_detail_uses_the_same_filtered_board(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _VaultRepo()
    monkeypatch.setattr(
        vault_routes,
        "project_public_record_board",
        _public_projection,
        raising=False,
    )

    detail = await vault_routes.get_vault(
        vault_id=44,
        vault_repo=repo,  # type: ignore[arg-type]
        user_repo=_UserRepo(),  # type: ignore[arg-type]
    )

    assert [entry.wallet for entry in detail.leaderboard] == ["public-second"]
    assert detail.leaderboard[0].rank == 2
    assert detail.leaderboard[0].achieved_at == "2023-11-14T22:15:00+00:00"
    assert detail.kom_holder is None
    assert detail.kom_time_s is None


@pytest.mark.asyncio
async def test_vault_list_omits_unverified_kom_summary() -> None:
    repo = _VaultRepo()

    response = await vault_routes.list_vaults(
        limit=50,
        offset=0,
        min_vert=None,
        minter=None,
        search=None,
        order_by="total_completions",
        vault_repo=repo,  # type: ignore[arg-type]
    )

    assert response.vaults[0].kom_holder is None
    assert response.vaults[0].kom_time_s is None


@pytest.mark.asyncio
async def test_public_rider_positions_derive_filtered_board_seat_and_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _VaultRepo()
    monkeypatch.setattr(
        user_routes,
        "project_public_record_board",
        _public_projection,
        raising=False,
    )
    target_repo = SimpleNamespace(
        get_user_by_identifier=AsyncMock(
            return_value={
                "id": "public-second-user",
                "wallet": "public-second",
                "is_public": True,
                "moderation_state": "visible",
            }
        )
    )

    response = await user_routes.get_user_leaderboard_positions(
        wallet="public-second",
        current_user=AuthenticatedUser(
            wallet="viewer",
            user_id="viewer-user",
            device_id="viewer-device",
        ),
        repo=target_repo,  # type: ignore[arg-type]
        vault_repo=repo,  # type: ignore[arg-type]
    )

    assert len(response.positions) == 1
    assert response.positions[0].rank == 2
    assert response.positions[0].best_time_seconds == 70
    assert response.positions[0].is_kom is False
    assert response.positions[0].total_riders == 1
    assert response.positions[0].percentile is None
    assert response.stats.total_positions == 1
    assert response.stats.kom_count == 0
    assert response.stats.podium_count == 1
    assert response.stats.top10_count == 1
    assert response.stats.total_vaults_completed == 1
    assert response.stats.best_percentile is None


@pytest.mark.asyncio
async def test_public_board_routes_fail_closed_when_projection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _VaultRepo()

    def _unavailable(*_args: Any, **_kwargs: Any) -> PublicRecordBoardProjection:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    monkeypatch.setattr(
        vault_routes,
        "project_public_record_board",
        _unavailable,
        raising=False,
    )
    monkeypatch.setattr(
        user_routes,
        "project_public_record_board",
        _unavailable,
        raising=False,
    )

    with pytest.raises(HTTPException) as vault_exc:
        await vault_routes.get_vault_leaderboard(
            vault_id=44,
            vault_repo=repo,  # type: ignore[arg-type]
            user_repo=_UserRepo(),  # type: ignore[arg-type]
        )
    assert vault_exc.value.status_code == 503

    target_repo = SimpleNamespace(
        get_user_by_identifier=AsyncMock(
            return_value={
                "id": "public-second-user",
                "wallet": "public-second",
                "is_public": True,
                "moderation_state": "visible",
            }
        )
    )
    with pytest.raises(HTTPException) as profile_exc:
        await user_routes.get_user_leaderboard_positions(
            wallet="public-second",
            current_user=AuthenticatedUser(
                wallet="viewer",
                user_id="viewer-user",
                device_id="viewer-device",
            ),
            repo=target_repo,  # type: ignore[arg-type]
            vault_repo=repo,  # type: ignore[arg-type]
        )
    assert profile_exc.value.status_code == 503


@pytest.mark.asyncio
async def test_owner_only_positions_keep_private_summary_path() -> None:
    repo = _VaultRepo()

    response = await user_routes.get_my_leaderboard_positions(
        current_user=AuthenticatedUser(
            wallet="public-second",
            user_id="public-second-user",
            device_id="owner-device",
        ),
        vault_repo=repo,  # type: ignore[arg-type]
    )

    assert response.positions[0].rank == 1
    assert response.positions[0].is_kom is True
    assert response.stats.total_positions == 99
