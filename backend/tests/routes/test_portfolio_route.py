from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from solders.hash import Hash

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser
from app.services.tx_builder import BuildTxResult

routes_pkg = ModuleType("app.routes")
routes_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "app" / "routes")]
sys.modules.setdefault("app.routes", routes_pkg)
portfolio_routes = importlib.import_module("app.routes.portfolio")


def _make_repo():
    return SimpleNamespace(
        client=MagicMock(),
        get_token_balances=AsyncMock(return_value={"dung": 42}),
        get_user_state=AsyncMock(return_value={"cal_balance": 1234}),
        get_user_claims=AsyncMock(return_value=[]),
    )


def _dung_source(
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


def _balance_token_source(
    *,
    amount: int,
    asset: str,
    mint: str,
    token_account: str,
    status: str = "live",
    exists: bool = True,
    slot: int = 124,
):
    return SimpleNamespace(
        amount_base_units=amount,
        source="rider_balance_token_pda",
        status=status,
        exists=exists,
        token_account=token_account,
        mint=mint,
        slot=slot,
        asset=asset,
    )


def _balance_snapshot(
    *,
    status: str = "active",
    source_status: str = "live",
    initialized: bool = True,
    cal_amount: int = 7_500_000_000,
    usdc_amount: int = 25_000_000,
    cal_status: str = "live",
    usdc_status: str = "live",
    harvest_fee_bps: int = 500,
    exit_fee_bps: int = 50,
):
    return SimpleNamespace(
        header=SimpleNamespace(
            initialized=initialized,
            status=status if initialized else None,
            source="rider_balance_header_pda",
            source_status=source_status,
            account="RiderBalanceHeaderPdaDefault",
            authority_model="app_balance" if initialized else None,
            policy_hash="00" * 32 if initialized else None,
            delegate_authority=None,
            last_authority_rotation_at=1_720_000_000 if initialized else None,
            revoked_at=1_720_000_100 if status == "revoked" else 0 if initialized else None,
            slot=124,
        ),
        cal=_balance_token_source(
            amount=cal_amount if cal_status != "unavailable" else 0,
            asset="CAL",
            mint="CalMintDefault",
            token_account="BalanceCalPdaDefault",
            status=cal_status,
            exists=cal_status == "live",
        ),
        usdc=_balance_token_source(
            amount=usdc_amount if usdc_status != "unavailable" else 0,
            asset="USDC",
            mint="UsdcMintDefault",
            token_account="BalanceUsdcPdaDefault",
            status=usdc_status,
            exists=usdc_status == "live",
        ),
        program_config_account="ProgramConfigPdaDefault",
        program_config_slot=124,
        harvest_fee_bps=harvest_fee_bps,
        exit_fee_bps=exit_fee_bps,
    )


@pytest.fixture(autouse=True)
def _patch_exact_dung_sources():
    with (
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_dung_balance_source",
            new=AsyncMock(
                return_value=_dung_source(
                    amount=42_000_000_000,
                    source="spl_wallet_ata",
                    token_account="WalletDungAtaDefault",
                )
            ),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_balance_dung_balance_source",
            new=AsyncMock(
                return_value=_dung_source(
                    amount=42_000_000_000,
                    source="rider_balance_token_pda",
                    token_account="BalanceDungPdaDefault",
                )
            ),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(return_value=_balance_snapshot()),
        ),
    ):
        yield


async def _call_get_portfolio(current_user, repo):
    route_impl = getattr(portfolio_routes.get_portfolio, "__wrapped__", portfolio_routes.get_portfolio)
    params = inspect.signature(route_impl).parameters
    kwargs = {
        "current_user": current_user,
        "repo": repo,
    }
    if "request" in params:
        kwargs["request"] = None
    return await route_impl(**kwargs)


async def _call_get_portfolio_snapshot(current_user, repo):
    route_impl = getattr(
        portfolio_routes.get_portfolio_snapshot,
        "__wrapped__",
        portfolio_routes.get_portfolio_snapshot,
    )
    return await route_impl(
        limit=25,
        offset=0,
        current_user=current_user,
        repo=repo,
    )


async def _call_prepare_balance_add_funds(current_user, payload):
    route_impl = getattr(
        portfolio_routes.prepare_balance_add_funds,
        "__wrapped__",
        portfolio_routes.prepare_balance_add_funds,
    )
    return await route_impl(payload=payload, current_user=current_user)


async def _call_prepare_balance_withdraw_to_wallet(current_user, payload):
    route_impl = getattr(
        portfolio_routes.prepare_balance_withdraw_to_wallet,
        "__wrapped__",
        portfolio_routes.prepare_balance_withdraw_to_wallet,
    )
    return await route_impl(payload=payload, current_user=current_user)


async def _call_submit_balance_add_funds(current_user, repo, payload):
    route_impl = getattr(
        portfolio_routes.submit_balance_add_funds,
        "__wrapped__",
        portfolio_routes.submit_balance_add_funds,
    )
    return await route_impl(payload=payload, current_user=current_user, repo=repo)


async def _call_submit_balance_withdraw_to_wallet(current_user, repo, payload):
    route_impl = getattr(
        portfolio_routes.submit_balance_withdraw_to_wallet,
        "__wrapped__",
        portfolio_routes.submit_balance_withdraw_to_wallet,
    )
    return await route_impl(payload=payload, current_user=current_user, repo=repo)


@pytest.mark.asyncio
async def test_portfolio_defaults_cal_to_zero_when_chain_balance_fails():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio11111111111111111111111111",
        user_id="user-portfolio-points",
        device_id="device-portfolio-points",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[{"vault_id": 9}])

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(portfolio_routes.solana_direct, "get_wallet_cal_balance_source", new=AsyncMock(side_effect=RuntimeError("rpc down"))) as cal_mock,
    ):
        response = await _call_get_portfolio(current_user, repo)

    assert response["cal_balance"] == "0"
    assert response["cal_balance_base_units"] == "0"
    assert response["dung_balance"] == "42"
    assert response["dung_balance_base_units"] == "42000000000"
    assert response["staked_positions"][0]["vault_id"] == 9
    assert response["staked_positions"][0]["cal_deposited_base_units"] == "0"
    assert response["contractVersion"] == "portfolio.v5"
    assert response["harvest_fee_bps"] == "500"
    assert response["exit_fee_bps"] == "50"
    assert response["freshness"]["chainStatus"] == "unavailable"
    assert response["balance_lifecycle"]["projection_status"] == "recorded"
    assert response["balance_lifecycle"]["can_add_funds"]
    repo.get_user_state.assert_not_awaited()
    cal_mock.assert_awaited_once_with(current_user.wallet)


@pytest.mark.asyncio
async def test_portfolio_reads_spl_cal_post_tge():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio22222222222222222222222222",
        user_id="user-portfolio-tge",
        device_id="device-portfolio-tge",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=4_321_000_000_000, status="live", exists=True, slot=123)),
        ) as cal_mock,
    ):
        response = await _call_get_portfolio(current_user, repo)

    assert response["cal_balance"] == "4321"
    assert response["cal_balance_base_units"] == "4321000000000"
    assert response["freshness"]["chainStatus"] == "live"
    assert response["freshness"]["balanceLifecycleSource"] == "rider_balance_header_pda"
    assert response["balance_lifecycle"]["source"] == "rider_balance_header_pda"
    assert response["balance_lifecycle"]["projection_status"] == "recorded"
    assert response["balance_lifecycle"]["rider_headline"] == "Boulder Roller Balance"
    assert [asset["asset"] for asset in response["balance_lifecycle"]["assets"]] == ["CAL", "USDC", "DUNG"]
    assert response["balance_lifecycle"]["assets"][0]["rider_state"] == "Available"
    assert response["balance_lifecycle"]["assets"][0]["balance_base_units"] == "7500000000"
    assert response["balance_lifecycle"]["assets"][0]["source"] == "rider_balance_token_pda"
    assert response["balance_lifecycle"]["assets"][0]["source_status"] == "live"
    assert response["balance_lifecycle"]["assets"][1]["balance_base_units"] == "25000000"
    assert response["balance_lifecycle"]["assets"][1]["rider_state"] == "Available"
    assert response["balance_lifecycle"]["can_add_funds"]
    assert response["balance_lifecycle"]["setup_steps"] == ()
    assert response["balance_lifecycle"]["source"] == "rider_balance_header_pda"
    assert response["balance_lifecycle"]["source_status"] == "live"
    assert response["balance_lifecycle"]["account"] == "RiderBalanceHeaderPdaDefault"
    assert response["balance_lifecycle"]["slot"] == 124
    repo.get_user_state.assert_not_awaited()
    cal_mock.assert_awaited_once_with(current_user.wallet)


@pytest.mark.asyncio
async def test_portfolio_preserves_atomic_cal_units_in_balance_lifecycle():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioExact2222222222222222222",
        user_id="user-portfolio-exact",
        device_id="device-portfolio-exact",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=100_000_000_001, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(
                return_value=_balance_snapshot(cal_amount=9_007_199_254_740_993),
            ),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    cal_asset = next(
        asset
        for asset in response["balance_lifecycle"]["assets"]
        if asset["asset"] == "CAL"
    )
    assert response["cal_balance"] == "100.000000001"
    assert response["cal_balance_base_units"] == "100000000001"
    assert cal_asset["balance_base_units"] == "9007199254740993"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_status", "expected_blocker"),
    (
        ("locked", "account_locked"),
        ("recovering", "account_recovering"),
        ("revoked", "account_revoked"),
    ),
)
async def test_portfolio_uses_decoded_balance_header_status(
    header_status: str,
    expected_blocker: str,
) -> None:
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioHeaderStates222222222222",
        user_id="user-portfolio-header-state",
        device_id="device-portfolio-header-state",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=55_000_000_000, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(return_value=_balance_snapshot(status=header_status)),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    plan = response["balance_lifecycle"]
    assert plan["status"] == header_status
    assert expected_blocker in plan["blockers"]
    assert not plan["can_add_funds"]
    assert not plan["can_withdraw_to_wallet"]


@pytest.mark.asyncio
async def test_portfolio_keeps_missing_balance_accounts_distinct_from_unavailable_reads() -> None:
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioBalanceMissing22222222222",
        user_id="user-portfolio-balance-missing",
        device_id="device-portfolio-balance-missing",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])
    missing = _balance_snapshot(
        initialized=False,
        source_status="not_initialized",
        cal_amount=0,
        usdc_amount=0,
        cal_status="not_initialized",
        usdc_status="not_initialized",
    )

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=55_000_000_000, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(return_value=missing),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    missing_plan = response["balance_lifecycle"]
    assert missing_plan["source_status"] == "not_initialized"
    assert missing_plan["projection_status"] == "recorded"
    assert missing_plan["assets"][0]["balance_base_units"] == "0"
    assert missing_plan["assets"][0]["source_status"] == "not_initialized"
    assert "rider_balance_required" in missing_plan["blockers"]

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=55_000_000_000, status="live", exists=True, slot=123)),
        ),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(side_effect=RuntimeError("rpc down")),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    unavailable_plan = response["balance_lifecycle"]
    assert unavailable_plan["source_status"] == "unavailable"
    assert unavailable_plan["projection_status"] == "delayed"
    assert unavailable_plan["assets"][0]["balance_base_units"] is None
    assert unavailable_plan["assets"][0]["source_status"] == "unavailable"
    assert "chain_state_unavailable" in unavailable_plan["blockers"]
    assert "rider_balance_required" not in unavailable_plan["blockers"]


@pytest.mark.asyncio
async def test_portfolio_preserves_one_base_unit_wallet_dung_and_ignores_indexed_history():
    repo = _make_repo()
    repo.get_token_balances = AsyncMock(return_value={"dung": 999_999})
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioDungDust222222222222222",
        user_id="user-portfolio-dung-dust",
        device_id="device-portfolio-dung-dust",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])

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
            new=AsyncMock(
                return_value=_dung_source(
                    amount=1,
                    source="spl_wallet_ata",
                    token_account="WalletDungDustAta",
                )
            ),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    assert response["dung_balance"] == "0.000000001"
    assert response["dung_balance_base_units"] == "1"
    assert response["wallet_dung"]["token_account"] == "WalletDungDustAta"
    assert response["balance_dung"]["amount_base_units"] == "42000000000"
    repo.get_token_balances.assert_not_awaited()


@pytest.mark.asyncio
async def test_portfolio_normalizes_indexed_stake_amounts_without_float_boundaries():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioStakeExact22222222222222",
        user_id="user-portfolio-stake-exact",
        device_id="device-portfolio-stake-exact",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(
        return_value=[
            {
                "vault_id": 9,
                "cal_staked": "9007199254740993",
                "lp_tokens": "9007199254740993",
                "rewards_earned": "1000000001",
            }
        ]
    )

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=100_000_000_000, status="live", exists=True, slot=123)),
        ),
    ):
        response = await _call_get_portfolio(current_user, repo)

    position = response["staked_positions"][0]
    assert position["cal_deposited"] == "9007199.254740993"
    assert position["cal_deposited_base_units"] == "9007199254740993"
    assert position["dung_ready"] is None
    assert position["dung_ready_base_units"] is None
    assert position["cal_staked"] == "9007199254740993"
    assert position["lp_tokens"] == "9007199254740993"
    assert position["rewards_earned"] == "1000000001"
    assert response["total_staked"] == "9007199.254740993"
    assert response["total_staked_base_units"] == "9007199254740993"
    assert response["weekly_yield"] == "1.000000001"
    assert response["weekly_yield_base_units"] == "1000000001"


@pytest.mark.asyncio
async def test_portfolio_snapshot_returns_balances_and_receipts_in_one_contract():
    repo = _make_repo()
    repo.get_user_claims = AsyncMock(return_value=[{"amount_staked": "5", "earned_dung": "2"}])
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio33333333333333333333333333",
        user_id="user-portfolio-snapshot",
        device_id="device-portfolio-snapshot",
    )
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(
        return_value=[
            {
                "vault_id": 11,
                "cal_staked": "5000000000",
                "lp_tokens": "5000000000",
                "rewards_earned": "2000000000",
            }
        ]
    )

    distributions = SimpleNamespace(
        distribution_count=1,
        receipt_count=2,
        model_dump=MagicMock(
            return_value={
                "distributions": [{"distribution_id": "v4a:11:7"}],
                "distribution_count": 1,
                "receipt_count": 2,
                "limit": 25,
                "offset": 0,
            }
        ),
    )

    with (
        patch.object(portfolio_routes, "VaultRepository", return_value=vault_repo),
        patch.object(
            portfolio_routes.solana_direct,
            "get_wallet_cal_balance_source",
            new=AsyncMock(return_value=SimpleNamespace(amount_base_units=100_000_000_000, status="live", exists=True, slot=123)),
        ),
        patch.object(portfolio_routes, "get_my_distributions", new=AsyncMock(return_value=distributions)),
    ):
        response = await _call_get_portfolio_snapshot(current_user, repo)

    assert response["contractVersion"] == "portfolio_snapshot.v4"
    assert response["portfolio"]["cal_balance"] == "100"
    assert response["portfolio"]["cal_balance_base_units"] == "100000000000"
    assert response["portfolio"]["staked_positions"][0]["vault_id"] == 11
    assert response["portfolio"]["staked_positions"][0]["cal_deposited_base_units"] == "5000000000"
    assert response["portfolio"]["total_staked"] == "5"
    assert response["portfolio"]["total_staked_base_units"] == "5000000000"
    assert response["portfolio"]["weekly_yield"] == "2"
    assert response["portfolio"]["weekly_yield_base_units"] == "2000000000"
    assert response["portfolio"]["balance_lifecycle"]["projection_status"] == "recorded"
    assert response["distributions"]["distribution_count"] == 1
    assert response["freshness"]["distributionCount"] == 1
    assert response["freshness"]["receiptCount"] == 2


@pytest.mark.asyncio
async def test_prepare_balance_add_funds_returns_wallet_boundary_action():
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio44444444444444444444444444",
        user_id="user-portfolio-add-funds",
        device_id="device-portfolio-add-funds",
    )
    payload = portfolio_routes.BalanceAddFundsPrepareRequest(
        asset="cal",
        amount_base_units="250000000",
    )
    builder = MagicMock()
    builder.build_add_funds_to_balance_tx = AsyncMock(
        return_value=BuildTxResult(
            transaction="prepared-balance-transfer",
            blockhash="blockhash-123",
            last_valid_block_height=99,
            message="Add CAL to Boulder Roller Balance",
            pda="RiderBalanceCalTokenPda",
        )
    )

    with patch.object(portfolio_routes, "get_tx_builder", return_value=builder):
        response = await _call_prepare_balance_add_funds(current_user, payload)

    assert response["contractVersion"] == "portfolio_balance_action.v2"
    assert response["action_type"] == "add_funds"
    assert response["rider_label"] == "Add funds"
    assert response["asset"] == "CAL"
    assert response["rider_state"] == "Pending"
    assert response["rider_detail"] == "Confirm in wallet to continue."
    assert response["next_step"] == "confirm_wallet"
    assert response["prepared_transaction"]["pda"] == "RiderBalanceCalTokenPda"
    builder.build_add_funds_to_balance_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        asset="CAL",
        amount=250_000_000,
        blockhash=None,
    )


@pytest.mark.asyncio
async def test_prepare_balance_action_fails_closed_on_locked_header() -> None:
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioLocked4444444444444444444",
        user_id="user-portfolio-locked",
        device_id="device-portfolio-locked",
    )
    payload = portfolio_routes.BalanceAddFundsPrepareRequest(
        asset="CAL",
        amount_base_units="250000000",
    )
    builder = MagicMock()
    builder.build_add_funds_to_balance_tx = AsyncMock()

    with (
        patch.object(portfolio_routes, "get_tx_builder", return_value=builder),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(return_value=_balance_snapshot(status="locked")),
        ),
    ):
        response = await _call_prepare_balance_add_funds(current_user, payload)

    assert response["rider_state"] == "Needs setup"
    assert response["next_step"] == "finish_setup"
    assert "account_locked" in response["blockers"]
    builder.build_add_funds_to_balance_tx.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_balance_action_keeps_amount_above_js_safe_integer_exact():
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioExact4444444444444444444",
        user_id="user-portfolio-exact-action",
        device_id="device-portfolio-exact-action",
    )
    payload = portfolio_routes.BalanceAddFundsPrepareRequest(
        asset="CAL",
        amount_base_units="9007199254740993",
    )
    builder = MagicMock()
    builder.build_add_funds_to_balance_tx = AsyncMock(
        return_value=BuildTxResult(
            transaction="prepared-exact-transfer",
            blockhash="blockhash-exact",
            last_valid_block_height=101,
            message="Add exact CAL to Boulder Roller Balance",
            pda="RiderBalanceExactCalTokenPda",
        )
    )

    with patch.object(portfolio_routes, "get_tx_builder", return_value=builder):
        response = await _call_prepare_balance_add_funds(current_user, payload)

    assert response["amount_base_units"] == "9007199254740993"
    builder.build_add_funds_to_balance_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        asset="CAL",
        amount=9007199254740993,
        blockhash=None,
    )


def test_balance_action_rejects_json_number_amounts() -> None:
    with pytest.raises(ValidationError, match="must be a decimal string"):
        portfolio_routes.BalanceAddFundsPrepareRequest(
            asset="CAL",
            amount_base_units=9_007_199_254_740_993,
        )


@pytest.mark.asyncio
async def test_prepare_balance_add_funds_respects_production_rollout_gate():
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioGate44444444444444444444444",
        user_id="user-portfolio-add-funds-gate",
        device_id="device-portfolio-add-funds-gate",
    )
    payload = portfolio_routes.BalanceAddFundsPrepareRequest(
        asset="cal",
        amount_base_units="250000000",
    )

    with patch.object(portfolio_routes, "is_balance_action_enabled", return_value=False):
        with pytest.raises(HTTPException) as exc:
            await _call_prepare_balance_add_funds(current_user, payload)

    assert exc.value.status_code == 503
    assert exc.value.detail == "This Balance action is not open yet."


@pytest.mark.asyncio
async def test_prepare_balance_withdraw_to_wallet_returns_wallet_boundary_action():
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio55555555555555555555555555",
        user_id="user-portfolio-withdraw-wallet",
        device_id="device-portfolio-withdraw-wallet",
    )
    payload = portfolio_routes.BalanceWithdrawToWalletPrepareRequest(
        asset="dung",
        amount_base_units="125000000",
    )
    builder = MagicMock()
    builder.build_withdraw_to_wallet_tx = AsyncMock(
        return_value=BuildTxResult(
            transaction="prepared-balance-exit",
            blockhash="blockhash-456",
            last_valid_block_height=100,
            message="Withdraw DUNG to wallet",
            pda="RiderBalanceDungTokenPda",
        )
    )

    with patch.object(portfolio_routes, "get_tx_builder", return_value=builder):
        response = await _call_prepare_balance_withdraw_to_wallet(current_user, payload)

    assert response["contractVersion"] == "portfolio_balance_action.v2"
    assert response["action_type"] == "withdraw_to_wallet"
    assert response["rider_label"] == "Withdraw to wallet"
    assert response["asset"] == "DUNG"
    assert response["rider_state"] == "Pending"
    assert response["rider_detail"] == "Confirm in wallet to continue."
    assert response["next_step"] == "confirm_wallet"
    assert response["prepared_transaction"]["pda"] == "RiderBalanceDungTokenPda"
    builder.build_withdraw_to_wallet_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        asset="DUNG",
        amount=125_000_000,
        blockhash=None,
    )


@pytest.mark.asyncio
async def test_prepare_withdraw_uses_actual_balance_amount_for_insufficiency() -> None:
    current_user = AuthenticatedUser(
        wallet="WalletPortfolioInsufficient555555555555555",
        user_id="user-portfolio-insufficient",
        device_id="device-portfolio-insufficient",
    )
    payload = portfolio_routes.BalanceWithdrawToWalletPrepareRequest(
        asset="CAL",
        amount_base_units="101",
    )
    builder = MagicMock()
    builder.build_withdraw_to_wallet_tx = AsyncMock()

    with (
        patch.object(portfolio_routes, "get_tx_builder", return_value=builder),
        patch.object(
            portfolio_routes.solana_direct,
            "get_rider_balance_account_snapshot",
            new=AsyncMock(return_value=_balance_snapshot(cal_amount=100)),
        ),
    ):
        response = await _call_prepare_balance_withdraw_to_wallet(current_user, payload)

    assert response["rider_state"] == "Needs review"
    assert response["next_step"] == "needs_review"
    assert "insufficient_balance" in response["blockers"]
    builder.build_withdraw_to_wallet_tx.assert_not_awaited()


@pytest.mark.asyncio
async def test_submit_add_funds_confirms_exact_prepared_expiry_and_client_intent():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio66666666666666666666666666",
        user_id="user-portfolio-submit-add",
        device_id="device-portfolio-submit-add",
    )
    payload = portfolio_routes.BalanceAddFundsSubmitRequest(
        asset="cal",
        amount_base_units="250000000",
        signed_transaction="c2lnbmVkLWFkZA==",
        last_valid_block_height=456,
        client_request_id="add-request-1",
    )
    signed_tx = SimpleNamespace(
        message=SimpleNamespace(recent_blockhash=Hash.default()),
        signatures=["prepared-signature"],
    )
    builder = MagicMock()
    builder.build_add_funds_to_balance_tx = AsyncMock(
        return_value=BuildTxResult(
            transaction="ZXhwZWN0ZWQ=",
            blockhash=str(Hash.default()),
            last_valid_block_height=999,
            message="Add CAL",
            pda="RiderBalanceCalTokenPda",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="prepared-signature")

    with (
        patch.object(portfolio_routes, "get_tx_builder", return_value=builder),
        patch.object(portfolio_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(portfolio_routes, "_assert_signed_transaction_matches"),
    ):
        response = await _call_submit_balance_add_funds(current_user, repo, payload)

    assert response["operation"]["confirmation_status"] == "confirmed"
    assert response["operation"]["metadata"]["client_request_id"] == "add-request-1"
    assert response["operation"]["metadata"]["last_valid_block_height"] == "456"
    builder.submit_signed_transaction.assert_awaited_once_with(
        "c2lnbmVkLWFkZA==",
        last_valid_block_height=456,
    )


@pytest.mark.asyncio
async def test_submit_withdraw_confirms_exact_prepared_expiry():
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPortfolio77777777777777777777777777",
        user_id="user-portfolio-submit-withdraw",
        device_id="device-portfolio-submit-withdraw",
    )
    payload = portfolio_routes.BalanceWithdrawToWalletSubmitRequest(
        asset="dung",
        amount_base_units="125000000",
        signed_transaction="c2lnbmVkLXdpdGhkcmF3",
        last_valid_block_height=789,
        client_request_id="withdraw-request-1",
    )
    signed_tx = SimpleNamespace(
        message=SimpleNamespace(recent_blockhash=Hash.default()),
        signatures=["prepared-signature"],
    )
    builder = MagicMock()
    builder.build_withdraw_to_wallet_tx = AsyncMock(
        return_value=BuildTxResult(
            transaction="ZXhwZWN0ZWQ=",
            blockhash=str(Hash.default()),
            last_valid_block_height=999,
            message="Withdraw DUNG",
            pda="RiderBalanceDungTokenPda",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="prepared-signature")

    with (
        patch.object(portfolio_routes, "get_tx_builder", return_value=builder),
        patch.object(portfolio_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(portfolio_routes, "_assert_signed_transaction_matches"),
    ):
        response = await _call_submit_balance_withdraw_to_wallet(current_user, repo, payload)

    assert response["operation"]["confirmation_status"] == "confirmed"
    assert response["operation"]["metadata"]["last_valid_block_height"] == "789"
    builder.submit_signed_transaction.assert_awaited_once_with(
        "c2lnbmVkLXdpdGhkcmF3",
        last_valid_block_height=789,
    )


@pytest.mark.asyncio
async def test_collection_snapshot_round_trips_without_indexed_reward_inference():
    repo = _make_repo()
    user = AuthenticatedUser(wallet='WalletFixture', user_id='fixture', device_id='fixture')
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[dict(vault_id=1, cal_staked='1', lp_tokens='1', rewards_earned='99000000000')])
    snapshot = dict(revision='slot:7', asOf='2026-09-08T20:00:00Z', coverage=dict(completeness='complete', population='wallet_vault_stakes', observedCount=2, expectedCount=2), positions=[dict(vaultId=1, dungReadyBaseUnits='4250000000'), dict(vaultId=2, dungReadyBaseUnits='800000000')], uncollectedDungBaseUnits='5050000000')
    with patch.object(portfolio_routes, 'VaultRepository', return_value=vault_repo), patch.object(portfolio_routes, 'get_collection_snapshot', new=AsyncMock(return_value=snapshot)), patch.object(portfolio_routes.solana_direct, 'get_wallet_cal_balance_source', new=AsyncMock(return_value=SimpleNamespace(amount_base_units=0, status="live", exists=True, slot=123))):
        response = await _call_get_portfolio(user, repo)
    assert response['collectionSnapshot'] == snapshot
    assert response['staked_positions'][0]['dung_ready_base_units'] == '4250000000'
    assert response['staked_positions'][0]['rewards_earned'] == '99000000000'


@pytest.mark.asyncio
@pytest.mark.parametrize('exists', [True, False])
async def test_portfolio_distinguishes_missing_cal_account_from_live_zero(exists):
    user = AuthenticatedUser(wallet='WalletFixture', user_id='fixture', device_id='fixture')
    vault_repo = MagicMock()
    vault_repo.get_wallet_stakes = AsyncMock(return_value=[])
    source = SimpleNamespace(amount_base_units=0, status='live' if exists else 'not_initialized', exists=exists, slot=17)
    with patch.object(portfolio_routes, 'VaultRepository', return_value=vault_repo), patch.object(portfolio_routes.solana_direct, 'get_wallet_cal_balance_source', new=AsyncMock(return_value=source)):
        response = await _call_get_portfolio(user, _make_repo())
    assert response['cal_balance_base_units'] == '0'
    assert response['freshness']['calStatus'] == source.status
    assert response['freshness']['calAccountExists'] is exists
    assert response['freshness']['calAccountSlot'] == 17
