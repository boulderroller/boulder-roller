from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser
from app.routes.vaults import StakeRequest, StakeResponse, get_my_stakes, get_vault, list_vaults


def test_stake_request_rejects_float_coercion_at_the_api_boundary() -> None:
    with pytest.raises(ValidationError):
        StakeRequest(cal_amount=100.0)

    assert StakeRequest(cal_amount=100).cal_amount == 100


def test_stake_response_preserves_exact_cal_amount_pairs() -> None:
    response = StakeResponse(
        vault_signature="ab" * 32,
        cal_staked="9007199.254740993",
        cal_staked_base_units="9007199254740993",
        total_position="9007199.254740993",
        total_position_base_units="9007199254740993",
        new_total_staked="18446744073.709551615",
        new_total_staked_base_units="18446744073709551615",
    )

    dumped = response.model_dump()

    assert dumped["cal_staked"] == "9007199.254740993"
    assert dumped["cal_staked_base_units"] == "9007199254740993"
    assert dumped["total_position"] == "9007199.254740993"
    assert dumped["total_position_base_units"] == "9007199254740993"
    assert dumped["new_total_staked"] == "18446744073.709551615"
    assert dumped["new_total_staked_base_units"] == "18446744073709551615"


@pytest.mark.asyncio
async def test_my_stakes_preserves_exact_cal_and_lp_base_units() -> None:
    current_user = AuthenticatedUser(
        wallet="WalletVaultExact1111111111111111111111",
        user_id="user-vault-exact",
        device_id="device-vault-exact",
    )
    vault_repo = SimpleNamespace(
        get_wallet_stakes=AsyncMock(
            return_value=[
                {
                    "id": "stake-1",
                    "vault_signature": "ab" * 32,
                    "wallet": current_user.wallet,
                    "cal_staked": "9007199254740993",
                    "lp_tokens": "9007199254740993",
                    "staked_at": "2026-07-15T12:00:00+00:00",
                }
            ]
        )
    )

    response = await get_my_stakes(
        current_user=current_user,
        vault_repo=vault_repo,
    )
    dumped = response.model_dump()

    assert dumped["stakes"][0]["cal_staked"] == "9007199.254740993"
    assert dumped["stakes"][0]["cal_staked_base_units"] == "9007199254740993"
    assert dumped["stakes"][0]["lp_tokens"] == "9007199.254740993"
    assert dumped["stakes"][0]["lp_tokens_base_units"] == "9007199254740993"
    assert dumped["total_cal_staked"] == "9007199.254740993"
    assert dumped["total_cal_staked_base_units"] == "9007199254740993"
    assert dumped["total_lp_tokens"] == "9007199.254740993"
    assert dumped["total_lp_tokens_base_units"] == "9007199254740993"


@pytest.mark.asyncio
async def test_vault_list_uses_batched_active_cal_totals() -> None:
    vault_repo = SimpleNamespace(
        count_vaults=AsyncMock(return_value=1),
        list_vaults=AsyncMock(
            return_value=[
                {
                    "id": 7,
                    "signature_hex": "cd" * 32,
                    "name": "Active Hill",
                    "vert_m": 120,
                    "distance_m": 1800,
                    "avg_gradient_pct": 6.7,
                    "total_completions": 4,
                    "total_staked": 999_000_000_000,
                    "kom_holder": None,
                    "kom_time_s": 0,
                    "minter": "Minter111",
                    "on_chain_seeding_status": "active",
                }
            ]
        ),
        get_vault_stake_totals=AsyncMock(
            return_value={
                7: {
                    "total_cal_staked": 1_250_000_000_001,
                    "total_lp_tokens": 1_000_000_000_000,
                }
            }
        ),
    )

    response = await list_vaults(
        limit=50,
        offset=0,
        min_vert=None,
        minter=None,
        search=None,
        order_by="total_completions",
        vault_repo=vault_repo,
    )
    dumped = response.model_dump()

    assert dumped["vaults"][0]["total_staked"] == "1250.000000001"
    assert dumped["vaults"][0]["total_staked_base_units"] == "1250000000001"
    assert dumped["vaults"][0]["total_cal_staked"] == "1250.000000001"
    vault_repo.get_vault_stake_totals.assert_awaited_once_with([7])


@pytest.mark.asyncio
async def test_vault_detail_replaces_deprecated_total_with_active_cal() -> None:
    vault = {
        "id": 7,
        "signature_hex": "cd" * 32,
        "signature_hash_hex": "ef" * 32,
        "name": "Active Hill",
        "vert_m": 120,
        "distance_m": 1800,
        "avg_gradient_pct": 6.7,
        "total_completions": 4,
        "total_staked": 999_000_000_000,
        "kom_holder": None,
        "kom_time_s": 0,
        "minter": "Minter111",
        "pda": "VaultPda111",
        "on_chain_seeding_status": "active",
    }
    vault_repo = SimpleNamespace(
        client=object(),
        get_vault_by_id=AsyncMock(return_value=vault),
        get_vault_record_board_entries=AsyncMock(return_value=[]),
        get_vault_detail=AsyncMock(
            return_value={
                **vault,
                "leaderboard": [],
                "total_cal_staked": 1_250_000_000_001,
                "total_lp_tokens": 1_000_000_000_000,
                "local_legend": None,
            }
        ),
    )

    response = await get_vault(
        vault_id=7,
        vault_repo=vault_repo,
        user_repo=SimpleNamespace(),
    )
    dumped = response.model_dump()

    assert dumped["total_staked"] == "1250.000000001"
    assert dumped["total_staked_base_units"] == "1250000000001"
    assert dumped["total_lp_tokens"] == "1000"
    assert dumped["total_lp_tokens_base_units"] == "1000000000000"
