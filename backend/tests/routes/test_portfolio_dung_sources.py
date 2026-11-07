from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser

portfolio_routes = importlib.import_module("app.routes.portfolio")


def _source(
    *,
    amount: int,
    source: str,
    token_account: str,
    status: str = "live",
    exists: bool = True,
    slot: int = 123,
):
    return SimpleNamespace(
        amount_base_units=amount,
        source=source,
        token_account=token_account,
        status=status,
        exists=exists,
        slot=slot,
    )


def _balance_snapshot():
    missing_cal = _source(
        amount=0,
        source="rider_balance_token_pda",
        token_account="BalanceCalPda",
        status="not_initialized",
        exists=False,
    )
    missing_cal.mint = "CalMint"
    missing_usdc = _source(
        amount=0,
        source="rider_balance_token_pda",
        token_account="BalanceUsdcPda",
        status="not_initialized",
        exists=False,
    )
    missing_usdc.mint = "UsdcMint"
    return SimpleNamespace(
        header=SimpleNamespace(
            initialized=True,
            status="active",
            source="rider_balance_header_pda",
            source_status="live",
            account="RiderBalanceHeaderPda",
            authority_model="app_balance",
            policy_hash="00" * 32,
            delegate_authority=None,
            last_authority_rotation_at=1_720_000_000,
            revoked_at=0,
            slot=123,
        ),
        cal=missing_cal,
        usdc=missing_usdc,
        program_config_account="ProgramConfigPda",
        program_config_slot=123,
    )


@pytest.fixture(autouse=True)
def _patch_balance_snapshot():
    with patch.object(
        portfolio_routes.solana_direct,
        "get_rider_balance_account_snapshot",
        new=AsyncMock(return_value=_balance_snapshot()),
    ):
        yield


def _repo():
    return SimpleNamespace(
        client=MagicMock(),
        get_token_balances=AsyncMock(return_value={"dung": 999_999}),
        get_user_claims=AsyncMock(return_value=[]),
    )


@pytest.mark.asyncio
async def test_portfolio_keeps_wallet_and_balance_dung_separate() -> None:
    repo = _repo()
    rider = AuthenticatedUser(
        wallet="WalletPortfolioDungSources22222222222222",
        user_id="user-dung-sources",
        device_id="device-dung-sources",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])
    wallet_source = _source(
        amount=1,
        source="spl_wallet_ata",
        token_account="WalletDungAta111",
        slot=456,
    )
    balance_source = _source(
        amount=42,
        source="rider_balance_token_pda",
        token_account="BalanceDungPda222",
        slot=457,
    )

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=0, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_dung_balance_source",
            new=AsyncMock(return_value=wallet_source),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_balance_dung_balance_source",
            new=AsyncMock(return_value=balance_source),
        ),
    ):
        response = await portfolio_routes._load_portfolio_core(rider, repo)

    assert response["contractVersion"] == "portfolio.v5"
    assert response["dung_balance"] == "0.000000001"
    assert response["dung_balance_base_units"] == "1"
    assert response["wallet_dung"] == {
        "amount": "0.000000001",
        "amount_base_units": "1",
        "source": "spl_wallet_ata",
        "status": "live",
        "token_account": "WalletDungAta111",
        "slot": 456,
    }
    assert response["balance_dung"] == {
        "amount": "0.000000042",
        "amount_base_units": "42",
        "source": "rider_balance_token_pda",
        "status": "live",
        "token_account": "BalanceDungPda222",
        "slot": 457,
    }
    dung_asset = next(
        asset
        for asset in response["balance_lifecycle"]["assets"]
        if asset["asset"] == "DUNG"
    )
    assert dung_asset["balance_base_units"] == "42"
    assert dung_asset["token_account"] == "BalanceDungPda222"
    repo.get_token_balances.assert_not_awaited()


@pytest.mark.asyncio
async def test_portfolio_never_serializes_unavailable_wallet_dung_as_zero() -> None:
    repo = _repo()
    rider = AuthenticatedUser(
        wallet="WalletPortfolioDungUnavailable2222222222",
        user_id="user-dung-unavailable",
        device_id="device-dung-unavailable",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])
    balance_source = _source(
        amount=0,
        source="rider_balance_token_pda",
        token_account="BalanceDungPdaMissing",
        status="not_initialized",
        exists=False,
        slot=900,
    )

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=0, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_dung_balance_source",
            new=AsyncMock(side_effect=RuntimeError("rpc down")),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_balance_dung_balance_source",
            new=AsyncMock(return_value=balance_source),
        ),
    ):
        response = await portfolio_routes._load_portfolio_core(rider, repo)

    assert response["dung_balance"] is None
    assert response["dung_balance_base_units"] is None
    assert response["wallet_dung"]["amount"] is None
    assert response["wallet_dung"]["amount_base_units"] is None
    assert response["wallet_dung"]["status"] == "unavailable"
    assert response["balance_dung"]["amount_base_units"] == "0"
    assert response["balance_dung"]["status"] == "not_initialized"
    assert response["freshness"]["chainStatus"] == "unavailable"
    assert response["freshness"]["walletDungStatus"] == "unavailable"
    assert response["freshness"]["balanceDungStatus"] == "not_initialized"
