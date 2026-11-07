from __future__ import annotations

import importlib
import inspect
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from solders.hash import Hash

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser

routes_pkg = ModuleType("app.routes")
routes_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "app" / "routes")]
routes_module = sys.modules.setdefault("app.routes", routes_pkg)
setattr(sys.modules["app"], "routes", routes_module)
admin_routes = importlib.import_module("app.routes.admin")
vault_routes = importlib.import_module("app.routes.vaults")

V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)


def _make_repo():
    client = MagicMock()
    rpc_call = MagicMock()
    rpc_call.execute.return_value = SimpleNamespace(data=True)
    client.rpc.return_value = rpc_call

    table_call = MagicMock()
    table_call.upsert.return_value = table_call
    table_call.insert.return_value = table_call
    table_call.execute.return_value = SimpleNamespace(data=[{}])
    client.table.return_value = table_call

    return SimpleNamespace(client=client)


def _make_source_repo(rows):
    client = MagicMock()
    query = MagicMock()
    for method_name in ("select", "eq", "order", "range"):
        getattr(query, method_name).return_value = query
    query.execute.return_value = SimpleNamespace(data=rows)
    client.table.return_value = query
    return SimpleNamespace(client=client)


class _FilteringSourceQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def order(self, _column):
        return self

    def range(self, _start, _end):
        return self

    def execute(self):
        rows = [
            row
            for row in self._rows
            if all(row.get(column) == value for column, value in self._filters)
        ]
        return SimpleNamespace(data=rows)


def _make_filtering_source_repo(rows):
    query = _FilteringSourceQuery(rows)
    client = MagicMock()
    client.table.return_value = query
    return SimpleNamespace(client=client), query


def _make_vault_repo():
    vault_repo = MagicMock()
    vault_repo.get_vault_by_signature = AsyncMock(return_value=None)
    vault_repo.stage_confirmed_vault_creation = AsyncMock(
        return_value={
            "job_id": "job-staged-vault",
            "projection_ready": False,
            "chain_slot": None,
        }
    )
    return vault_repo


def _make_build_result(
    *,
    transaction: str = "dGVzdA==",
    blockhash: str = str(Hash.default()),
    last_valid_block_height: int = 123,
    message: str = "prepared",
    vault_id: int | None = None,
    pda: str | None = None,
):
    return SimpleNamespace(
        transaction=transaction,
        blockhash=blockhash,
        last_valid_block_height=last_valid_block_height,
        message=message,
        vault_id=vault_id,
        pda=pda,
    )


def _make_signed_tx(signature: str = "prepared-signature"):
    return SimpleNamespace(
        message=SimpleNamespace(recent_blockhash=Hash.default()),
        signatures=[signature],
    )


def _sealed_custody(amount: int):
    return SimpleNamespace(
        sealed=True,
        status="sealed",
        recorded_lp_tokens=amount,
        amount_base_units=amount,
        token_account="position-lp-pda",
    )


def _reward_grade_source(vault_request):
    return {
        "id": str(uuid4()),
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "start_lat": 39.9500,
        "start_lon": -75.1600,
        "end_lat": 39.9550,
        "end_lon": -75.1600,
        "vert_m": vault_request.vert_m,
        "distance_m": vault_request.distance_m,
        "avg_gradient_pct": vault_request.avg_gradient_pct,
        "economic_eligible": True,
    }


async def _call_create_vault(vault_request, current_user, vault_repo, repo):
    create_impl = getattr(vault_routes.create_vault, "__wrapped__", vault_routes.create_vault)
    params = inspect.signature(create_impl).parameters
    kwargs = {
        "current_user": current_user,
        "vault_repo": vault_repo,
        "repo": repo,
    }
    if "vault_request" in params:
        kwargs["vault_request"] = vault_request
    else:
        kwargs["request"] = vault_request
    if "request" in params and "vault_request" in params:
        kwargs["request"] = None
    with patch.object(
        vault_routes,
        "_resolve_reward_grade_vault_source",
        new=AsyncMock(return_value=_reward_grade_source(vault_request)),
    ):
        return await create_impl(**kwargs)


async def _call_prepare_create_vault(vault_request, current_user, vault_repo, repo):
    prepare_impl = getattr(vault_routes.prepare_create_vault, "__wrapped__", vault_routes.prepare_create_vault)
    params = inspect.signature(prepare_impl).parameters
    kwargs = {
        "current_user": current_user,
        "vault_repo": vault_repo,
        "repo": repo,
    }
    if "vault_request" in params:
        kwargs["vault_request"] = vault_request
    else:
        kwargs["request"] = vault_request
    if "request" in params and "vault_request" in params:
        kwargs["request"] = None
    with patch.object(
        vault_routes,
        "_resolve_reward_grade_vault_source",
        new=AsyncMock(return_value=_reward_grade_source(vault_request)),
    ):
        return await prepare_impl(**kwargs)


async def _call_stake_in_vault(vault_id, stake_request, current_user, vault_repo, repo):
    stake_impl = getattr(vault_routes.stake_in_vault, "__wrapped__", vault_routes.stake_in_vault)
    return await stake_impl(
        vault_id=vault_id,
        stake_request=stake_request,
        request=None,
        current_user=current_user,
        vault_repo=vault_repo,
        repo=repo,
    )


async def _call_unstake_from_vault(vault_id, unstake_request, current_user, vault_repo, repo):
    unstake_impl = getattr(vault_routes.unstake_from_vault, "__wrapped__", vault_routes.unstake_from_vault)
    return await unstake_impl(
        vault_id=vault_id,
        unstake_request=unstake_request,
        request=None,
        current_user=current_user,
        vault_repo=vault_repo,
        repo=repo,
    )


async def _call_prepare_unstake_from_vault(
    vault_id,
    unstake_request,
    current_user,
    vault_repo,
    repo,
):
    prepare_impl = getattr(
        vault_routes.prepare_unstake_from_vault,
        "__wrapped__",
        vault_routes.prepare_unstake_from_vault,
    )
    return await prepare_impl(
        vault_id=vault_id,
        unstake_request=unstake_request,
        request=None,
        current_user=current_user,
        vault_repo=vault_repo,
        repo=repo,
    )


async def _call_harvest_vault_rewards(vault_id, harvest_request, current_user, vault_repo, repo):
    harvest_impl = getattr(vault_routes.harvest_vault_rewards, "__wrapped__", vault_routes.harvest_vault_rewards)
    return await harvest_impl(
        vault_id=vault_id,
        request=None,
        harvest_request=harvest_request,
        current_user=current_user,
        vault_repo=vault_repo,
        repo=repo,
    )


async def _call_get_vault_pending_rewards(vault_id, current_user, vault_repo):
    pending_impl = getattr(
        vault_routes.get_vault_pending_rewards,
        "__wrapped__",
        vault_routes.get_vault_pending_rewards,
    )
    return await pending_impl(
        vault_id=vault_id,
        current_user=current_user,
        vault_repo=vault_repo,
    )


@pytest.mark.asyncio
async def test_vault_source_resolution_rejects_cross_geography_v1_ambiguity():
    base = {
        "wallet": "WalletSource",
        "signature_hex": "ab" * 64,
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "vert_m": 120.0,
        "distance_m": 2000.0,
        "avg_gradient_pct": 6.0,
        "economic_eligible": True,
        "created_at": "2026-07-01T00:00:00Z",
    }
    repo = _make_source_repo(
        [
            {
                **base,
                "id": str(uuid4()),
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
            },
            {
                **base,
                "id": str(uuid4()),
                "start_lat": 32.2200,
                "start_lon": -110.9700,
                "end_lat": 32.2250,
                "end_lon": -110.9700,
            },
        ]
    )

    def endpoint_match(**kwargs):
        if kwargs["query_start"] != kwargs["candidate_start"]:
            return None
        return SimpleNamespace(similarity=1.0)

    with (
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=endpoint_match,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await vault_routes._resolve_reward_grade_vault_source(
            repo=repo,
            wallet="WalletSource",
            signature_hex="ab" * 64,
        )

    assert exc_info.value.status_code == 409
    assert "more than one location" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_vault_source_resolution_checks_v1_collisions_across_wallets():
    base = {
        "signature_hex": "ab" * 64,
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "vert_m": 120.0,
        "distance_m": 2000.0,
        "avg_gradient_pct": 6.0,
        "economic_eligible": True,
        "created_at": "2026-07-01T00:00:00Z",
    }
    repo, query = _make_filtering_source_repo(
        [
            {
                **base,
                "id": str(uuid4()),
                "wallet": "WalletSource",
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
            },
            {
                **base,
                "id": str(uuid4()),
                "wallet": "WalletElsewhere",
                "start_lat": 32.2200,
                "start_lon": -110.9700,
                "end_lat": 32.2250,
                "end_lon": -110.9700,
            },
        ]
    )

    def endpoint_match(**kwargs):
        if kwargs["query_start"] != kwargs["candidate_start"]:
            return None
        return SimpleNamespace(similarity=1.0)

    with (
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=endpoint_match,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await vault_routes._resolve_reward_grade_vault_source(
            repo=repo,
            wallet="WalletSource",
            signature_hex="ab" * 64,
        )

    assert exc_info.value.status_code == 409
    assert "more than one location" in str(exc_info.value.detail)
    assert ("wallet", "WalletSource") not in query._filters


@pytest.mark.asyncio
async def test_vault_source_resolution_requires_v2_evidence():
    repo = _make_source_repo(
        [
            {
                "id": str(uuid4()),
                "wallet": "WalletSource",
                "signature_hex": "ab" * 64,
                "signature_v2_hex": None,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                "vert_m": 120.0,
                "distance_m": 2000.0,
                "avg_gradient_pct": 6.0,
                "economic_eligible": True,
                "created_at": "2026-07-01T00:00:00Z",
            }
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await vault_routes._resolve_reward_grade_vault_source(
            repo=repo,
            wallet="WalletSource",
            signature_hex="ab" * 64,
        )

    assert exc_info.value.status_code == 422
    assert "canonical v2" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_create_vault_rejects_unsupported_payment_method():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="Wallet111111111111111111111111111111111",
        user_id="user-1",
        device_id="device-1",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="ab" * 64,
        name="Morning Climb",
        vert_m=540,
        distance_m=6300,
        avg_gradient_pct=8.5,
        payment_method="cal",
    )

    with pytest.raises(HTTPException) as exc_info:
        await _call_create_vault(vault_request, current_user, vault_repo, repo)

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        assert "arbitrary-signature Vault creation is disabled" in str(
            exc_info.value.detail
        )
    else:
        assert exc_info.value.status_code == 400
        assert "Invalid payment method" in str(exc_info.value.detail)
    repo.client.rpc.assert_not_called()
    vault_repo.stage_confirmed_vault_creation.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_create_vault_returns_wallet_signed_transaction_post_tge():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPrep22222222222222222222222222222",
        user_id="user-prep",
        device_id="device-prep",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="cd" * 64,
        name="Evening Climb",
        vert_m=620,
        distance_m=7100,
        avg_gradient_pct=8.7,
        payment_method="dung",
    )
    builder = MagicMock()
    builder.build_create_vault_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="cHJlcGFyZWQ=",
            message="Create vault",
            vault_id=12,
            pda="vault-pda-12",
        )
    )

    with patch.object(vault_routes, "get_tx_builder", return_value=builder):
        if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
            with pytest.raises(HTTPException) as exc_info:
                await _call_prepare_create_vault(
                    vault_request, current_user, vault_repo, repo
                )
        else:
            response = await _call_prepare_create_vault(
                vault_request, current_user, vault_repo, repo
            )

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        builder.build_create_vault_tx.assert_not_awaited()
        return

    assert response.transaction == "cHJlcGFyZWQ="
    assert response.vault_id == 12
    assert response.pda == "vault-pda-12"
    builder.build_create_vault_tx.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_create_vault_returns_wallet_signed_transaction_post_tge_cal_usdc():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="WalletPrepUsdc2222222222222222222222222",
        user_id="user-prep-usdc",
        device_id="device-prep-usdc",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="ce" * 64,
        name="USDC Climb",
        vert_m=620,
        distance_m=7100,
        avg_gradient_pct=8.7,
        payment_method="cal_usdc",
    )
    builder = MagicMock()
    builder.build_create_vault_with_usdc_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="dXNkYy1wcmVw",
            message="Create vault with USDC",
            vault_id=18,
            pda="vault-pda-18",
        )
    )

    with patch.object(vault_routes, "get_tx_builder", return_value=builder):
        if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
            with pytest.raises(HTTPException) as exc_info:
                await _call_prepare_create_vault(
                    vault_request, current_user, vault_repo, repo
                )
        else:
            response = await _call_prepare_create_vault(
                vault_request, current_user, vault_repo, repo
            )

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        builder.build_create_vault_with_usdc_tx.assert_not_awaited()
        return

    assert response.transaction == "dXNkYy1wcmVw"
    assert response.vault_id == 18
    assert response.pda == "vault-pda-18"
    builder.build_create_vault_with_usdc_tx.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_vault_queues_replay_post_tge_wallet_signed_dung():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="Wallet222222222222222222222222222222222",
        user_id="user-2",
        device_id="device-2",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="cd" * 64,
        name="Evening Climb",
        vert_m=620,
        distance_m=7100,
        avg_gradient_pct=8.7,
        payment_method="dung",
        signed_transaction="c2lnbmVkLXR4",
        prepared_vault_id=12,
        last_valid_block_height=123,
        client_request_id="create-dung-12",
    )
    config = SimpleNamespace(program_id="Program222", dung_mint_address="DungMint222")
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_create_vault_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="ZXhwZWN0ZWQ=",
            message="Create vault",
            vault_id=12,
            pda="vault-pda-12",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-post-tge-12")
    vault_repo.stage_confirmed_vault_creation.return_value = {
        "job_id": "job-post-tge",
        "projection_ready": False,
        "chain_slot": None,
    }

    with (
        patch.object(vault_routes.solana_direct, "load_default_config", return_value=config),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
            with pytest.raises(HTTPException) as exc_info:
                await _call_create_vault(
                    vault_request, current_user, vault_repo, repo
                )
        else:
            response = await _call_create_vault(
                vault_request, current_user, vault_repo, repo
            )

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        builder.build_create_vault_tx.assert_not_awaited()
        builder.submit_signed_transaction.assert_not_awaited()
        vault_repo.stage_confirmed_vault_creation.assert_not_awaited()
        return

    assert response.vault_id == 12
    assert response.operation_id and response.operation_id.startswith("br-op-")
    assert response.confirmation_status == "confirmed"
    assert response.projection_status == "pending"
    assert response.rider_state == "Pending"
    assert "Historical replay queued." in response.message
    repo.client.rpc.assert_not_called()
    vault_repo.stage_confirmed_vault_creation.assert_awaited_once()
    create_kwargs = vault_repo.stage_confirmed_vault_creation.await_args.kwargs
    assert create_kwargs["signature_v2_hex"] == V2_SIGNATURE_HEX
    assert create_kwargs["start_lat"] == 39.9500
    assert create_kwargs["end_lat"] == 39.9550
    assert create_kwargs["create_tx_signature"] == "tx-post-tge-12"
    assert create_kwargs["source_climb_id"]
    assert create_kwargs["operation_id"] == response.operation_id
    builder.submit_signed_transaction.assert_awaited_once_with(
        "c2lnbmVkLXR4",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "create_vault"
    ]
    assert operation_rows[-1]["operation_id"] == response.operation_id
    assert operation_rows[-1]["authority_model"] == "wallet_boundary"
    assert operation_rows[-1]["metadata"]["adapter"] == "wallet_boundary_fallback"
    assert operation_rows[-1]["metadata"]["boundary_fallback"] == "true"
    assert operation_rows[-1]["confirmation_status"] == "confirmed"
    # The atomic handoff RPC owns the pending transition. The route must not
    # issue a later Python ledger write that could regress an indexer update.
    assert operation_rows[-1]["projection_status"] == "not_started"
    assert operation_rows[-1]["rider_state"] == "Delayed"
    assert operation_rows[-1]["tx_signature"] == "tx-post-tge-12"


@pytest.mark.asyncio
async def test_create_vault_queues_replay_post_tge_wallet_signed_cal_usdc():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="WalletUsdc22222222222222222222222222222",
        user_id="user-usdc-2",
        device_id="device-usdc-2",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="de" * 64,
        name="USDC Evening Climb",
        vert_m=650,
        distance_m=7300,
        avg_gradient_pct=8.9,
        payment_method="cal_usdc",
        signed_transaction="dXNkYy1zaWduZWQtdHg=",
        prepared_vault_id=22,
        last_valid_block_height=123,
        client_request_id="create-usdc-22",
    )
    config = SimpleNamespace(program_id="ProgramUsdc222", dung_mint_address="DungMintUsdc222")
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_create_vault_with_usdc_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="ZXhwZWN0ZWQtdXNkYw==",
            message="Create vault with USDC",
            vault_id=22,
            pda="vault-pda-22",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-post-tge-usdc-22")
    vault_repo.stage_confirmed_vault_creation.return_value = {
        "job_id": "job-post-tge-usdc",
        "projection_ready": True,
        "chain_slot": 220,
    }

    with (
        patch.object(vault_routes.solana_direct, "load_default_config", return_value=config),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
            with pytest.raises(HTTPException) as exc_info:
                await _call_create_vault(
                    vault_request, current_user, vault_repo, repo
                )
        else:
            response = await _call_create_vault(
                vault_request, current_user, vault_repo, repo
            )

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        builder.build_create_vault_with_usdc_tx.assert_not_awaited()
        builder.submit_signed_transaction.assert_not_awaited()
        vault_repo.stage_confirmed_vault_creation.assert_not_awaited()
        return

    assert response.vault_id == 22
    assert response.operation_id and response.operation_id.startswith("br-op-")
    assert response.confirmation_status == "confirmed"
    assert response.projection_status == "recorded"
    assert response.rider_state is None
    assert "Historical replay queued." in response.message
    assert "CAL+USDC" in response.message
    repo.client.rpc.assert_not_called()
    vault_repo.stage_confirmed_vault_creation.assert_awaited_once()
    builder.submit_signed_transaction.assert_awaited_once_with(
        "dXNkYy1zaWduZWQtdHg=",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "create_vault"
    ]
    assert operation_rows[-1]["operation_id"] == response.operation_id
    assert operation_rows[-1]["asset"] == "CAL+USDC"
    assert operation_rows[-1]["reference_type"] == "vault"
    assert operation_rows[-1]["reference_id"] == "22"


@pytest.mark.asyncio
async def test_create_vault_returns_pending_when_local_persistence_fails_after_submit():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.stage_confirmed_vault_creation = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )
    current_user = AuthenticatedUser(
        wallet="WalletPending2222222222222222222222222222",
        user_id="user-pending",
        device_id="device-pending",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="ac" * 64,
        name="Pending Climb",
        vert_m=620,
        distance_m=7100,
        avg_gradient_pct=8.7,
        payment_method="dung",
        signed_transaction="cGVuZGluZy10eA==",
        prepared_vault_id=32,
        last_valid_block_height=123,
        client_request_id="create-pending-32",
    )
    config = SimpleNamespace(program_id="ProgramPending222", dung_mint_address="DungMintPending222")
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_create_vault_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="ZXhwZWN0ZWQtcGVuZGluZw==",
            message="Create vault",
            vault_id=32,
            pda="vault-pda-32",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-submitted-32")

    with (
        patch.object(vault_routes.solana_direct, "load_default_config", return_value=config),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
            with pytest.raises(HTTPException) as exc_info:
                await _call_create_vault(
                    vault_request, current_user, vault_repo, repo
                )
        else:
            response = await _call_create_vault(
                vault_request, current_user, vault_repo, repo
            )

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        builder.build_create_vault_tx.assert_not_awaited()
        builder.submit_signed_transaction.assert_not_awaited()
        vault_repo.stage_confirmed_vault_creation.assert_not_awaited()
        return

    assert response.vault_id == 32
    assert response.tx_signature == "tx-submitted-32"
    assert response.projection_status == "delayed"
    assert response.rider_state == "Delayed"
    assert response.operation_id.startswith("br-op-")
    assert "do not retry" in response.message
    assert "transaction submitted" not in response.message
    vault_repo.stage_confirmed_vault_creation.assert_awaited_once()
    builder.submit_signed_transaction.assert_awaited_once_with(
        "cGVuZGluZy10eA==",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "create_vault"
    ]
    assert operation_rows[-1]["projection_status"] == "delayed"
    assert operation_rows[-1]["rider_state"] == "Delayed"
    assert operation_rows[-1]["failure_reason"] == "database unavailable"


@pytest.mark.asyncio
async def test_create_vault_operation_insert_failure_blocks_submission():
    repo = _make_repo()
    repo.client.table.return_value.execute.side_effect = RuntimeError("ledger unavailable")
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="WalletLedgerBlocked222222222222222222",
        user_id="user-ledger-blocked",
        device_id="device-ledger-blocked",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="bc" * 64,
        name="Ledger Blocked Climb",
        vert_m=620,
        distance_m=7100,
        avg_gradient_pct=8.7,
        payment_method="dung",
        signed_transaction="bGVkZ2VyLWJsb2NrZWQtdHg=",
        prepared_vault_id=33,
        last_valid_block_height=123,
        client_request_id="create-ledger-blocked-33",
    )
    config = SimpleNamespace(program_id="ProgramLedgerBlocked", dung_mint_address="DungMintLedgerBlocked")
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_create_vault_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="ZXhwZWN0ZWQtbGVkZ2VyLWJsb2NrZWQ=",
            message="Create vault",
            vault_id=33,
            pda="vault-pda-33",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-should-not-submit")

    with (
        patch.object(vault_routes.solana_direct, "load_default_config", return_value=config),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_create_vault(vault_request, current_user, vault_repo, repo)

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        assert "arbitrary-signature Vault creation is disabled" in str(
            exc_info.value.detail
        )
        builder.build_create_vault_tx.assert_not_awaited()
    else:
        assert exc_info.value.status_code == 503
        assert "could not prepare this action" in str(exc_info.value.detail)
    builder.submit_signed_transaction.assert_not_awaited()
    vault_repo.stage_confirmed_vault_creation.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_create_vault_rejects_unsupported_payment_method():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    current_user = AuthenticatedUser(
        wallet="Wallet333333333333333333333333333333333",
        user_id="user-3",
        device_id="device-3",
    )
    vault_request = vault_routes.CreateVaultRequest(
        signature_hex="ef" * 64,
        name="Tier Gate Climb",
        vert_m=410,
        distance_m=4900,
        avg_gradient_pct=8.3,
        payment_method="cal",
    )

    with pytest.raises(HTTPException) as exc_info:
        await _call_prepare_create_vault(vault_request, current_user, vault_repo, repo)

    if vault_routes.PROGRAM_VERSION_FAMILY == "V4-B":
        assert exc_info.value.status_code == 410
        assert "arbitrary-signature Vault creation is disabled" in str(
            exc_info.value.detail
        )
    else:
        assert exc_info.value.status_code == 400
        assert "currently only available for 'dung' or 'cal_usdc'" in str(
            exc_info.value.detail
        )
    repo.client.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_stake_rejects_legacy_generation_before_building():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 1,
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletLegacyPrepare22222222222222222222",
        user_id="user-legacy-prepare",
        device_id="device-legacy-prepare",
    )
    builder = MagicMock()
    builder.build_stake_tx = AsyncMock(return_value=_make_build_result())
    prepare_impl = getattr(
        vault_routes.prepare_stake_in_vault,
        "__wrapped__",
        vault_routes.prepare_stake_in_vault,
    )

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        pytest.raises(HTTPException) as exc_info,
    ):
        await prepare_impl(
            vault_id=12,
            stake_request=vault_routes.StakeRequest(cal_amount=250),
            request=None,
            current_user=current_user,
            vault_repo=vault_repo,
            repo=repo,
        )

    assert exc_info.value.status_code == 409
    assert "Withdraw CAL" in str(exc_info.value.detail)
    builder.build_stake_tx.assert_not_awaited()


@pytest.mark.asyncio
async def test_stake_rejects_legacy_generation_before_balance_or_submit():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 1,
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletLegacyStake222222222222222222222",
        user_id="user-legacy-stake",
        device_id="device-legacy-stake",
    )

    with (
        patch.object(vault_routes, "_require_balance_rollout_action"),
        patch.object(
            vault_routes.solana_direct,
            "get_cal_balance",
            new=AsyncMock(return_value=1_000),
        ) as balance_mock,
        pytest.raises(HTTPException) as exc_info,
    ):
        await _call_stake_in_vault(
            12,
            vault_routes.StakeRequest(cal_amount=250),
            current_user,
            vault_repo,
            repo,
        )

    assert exc_info.value.status_code == 409
    assert "Withdraw CAL" in str(exc_info.value.detail)
    balance_mock.assert_not_awaited()
    repo.client.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_stake_without_signed_transaction_never_uses_staker_secret(monkeypatch):
    monkeypatch.setenv("SOLANA_STAKER_SECRET", "[1,2,3]")
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 2,
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletStakeNoSecret2222222222222222222",
        user_id="user-stake-no-secret",
        device_id="device-stake-no-secret",
    )
    stake_request = vault_routes.StakeRequest(cal_amount=250)

    with (
        patch.object(vault_routes.solana_direct, "get_cal_balance", new=AsyncMock(return_value=1_000)),
        patch.object(vault_routes.solana_direct, "_load_keypair", side_effect=AssertionError("server-held key used")) as load_mock,
        patch.object(vault_routes.solana_direct, "send_stake_cal_in_vault", new=AsyncMock()) as send_mock,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_stake_in_vault(12, stake_request, current_user, vault_repo, repo)

    assert exc_info.value.status_code == 503
    assert "prepared wallet-signed transaction" in str(exc_info.value.detail)
    load_mock.assert_not_called()
    send_mock.assert_not_awaited()
    repo.client.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_unstake_without_signed_transaction_never_uses_staker_secret(monkeypatch):
    monkeypatch.setenv("SOLANA_STAKER_PATH", "/tmp/not-used.json")
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 1,
        }
    )
    vault_repo.unstake_cal = AsyncMock()
    current_user = AuthenticatedUser(
        wallet="WalletUnstakeNoSecret2222222222222222",
        user_id="user-unstake-no-secret",
        device_id="device-unstake-no-secret",
    )
    unstake_request = vault_routes.UnstakeRequest(withdraw_all=True)

    with (
        patch.object(vault_routes.solana_direct, "_load_keypair", side_effect=AssertionError("server-held key used")) as load_mock,
        patch.object(vault_routes.solana_direct, "send_unstake_cal_from_vault", new=AsyncMock()) as send_mock,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_unstake_from_vault(12, unstake_request, current_user, vault_repo, repo)

    assert exc_info.value.status_code == 503
    assert "prepared wallet-signed transaction" in str(exc_info.value.detail)
    load_mock.assert_not_called()
    send_mock.assert_not_awaited()
    vault_repo.unstake_cal.assert_not_awaited()


def test_unstake_exact_request_contract_rejects_lossy_or_ambiguous_inputs():
    exact = vault_routes.UnstakeRequest(lp_amount_base_units="9007199254740993")
    assert exact.lp_amount_base_units == "9007199254740993"
    assert exact.withdraw_all is False

    withdraw_all = vault_routes.UnstakeRequest(withdraw_all=True)
    assert withdraw_all.lp_amount_base_units is None
    assert withdraw_all.withdraw_all is True

    u64_max = str((1 << 64) - 1)
    assert vault_routes.UnstakeRequest(
        lp_amount_base_units=u64_max
    ).lp_amount_base_units == u64_max

    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(lp_amount_base_units=9007199254740993)
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(lp_amount_base_units=str(1 << 64))
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(lp_amount_base_units="0")
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(withdraw_all=1)
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(withdraw_all="true")
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest()
    with pytest.raises(ValidationError):
        vault_routes.UnstakeRequest(
            lp_amount_base_units="1",
            withdraw_all=True,
        )


@pytest.mark.asyncio
async def test_prepare_unstake_withdraw_all_reads_every_onchain_lp_base_unit():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletExactUnstake222222222222222222222",
        user_id="user-exact-unstake",
        device_id="device-exact-unstake",
    )
    unstake_request = vault_routes.UnstakeRequest(withdraw_all=True)
    builder = MagicMock()
    builder.build_unstake_tx = AsyncMock(return_value=_make_build_result())

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(return_value={"lp_tokens": 9_007_199_254_740_993}),
        ) as read_stake,
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(9_007_199_254_740_993)),
        ),
    ):
        await _call_prepare_unstake_from_vault(
            12,
            unstake_request,
            current_user,
            vault_repo,
            repo,
        )

    read_stake.assert_awaited_once()
    builder.build_unstake_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        vault_id=12,
        lp_amount=9_007_199_254_740_993,
        collect_rewards=False,
    )


@pytest.mark.asyncio
async def test_prepare_unstake_with_pending_rewards_composes_collect():
    """Withdraw is one Balance action: pending DUNG forces the composed
    collect-before-unstake transaction (protocol rule: collect first)."""
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletExactUnstake222222222222222222222",
        user_id="user-exact-unstake",
        device_id="device-exact-unstake",
    )
    unstake_request = vault_routes.UnstakeRequest(withdraw_all=True)
    builder = MagicMock()
    builder.build_unstake_tx = AsyncMock(return_value=_make_build_result())

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(
                return_value={
                    "lp_tokens": 9_007_199_254_740_993,
                    "rewards_earned": 12_345_000_000,
                }
            ),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(9_007_199_254_740_993)),
        ),
    ):
        await _call_prepare_unstake_from_vault(
            12,
            unstake_request,
            current_user,
            vault_repo,
            repo,
        )

    builder.build_unstake_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        vault_id=12,
        lp_amount=9_007_199_254_740_993,
        collect_rewards=True,
    )


@pytest.mark.asyncio
async def test_prepare_unstake_rejects_exact_base_unit_overdraw_before_building():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletExactOverdraw22222222222222222222",
        user_id="user-exact-overdraw",
        device_id="device-exact-overdraw",
    )
    unstake_request = vault_routes.UnstakeRequest(lp_amount_base_units="101")
    builder = MagicMock()
    builder.build_unstake_tx = AsyncMock()

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(return_value={"lp_tokens": 100}),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(100)),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_prepare_unstake_from_vault(
                12,
                unstake_request,
                current_user,
                vault_repo,
                repo,
            )

    assert exc_info.value.status_code == 400
    assert "Insufficient LP" in str(exc_info.value.detail)
    builder.build_unstake_tx.assert_not_awaited()


@pytest.mark.asyncio
async def test_prepare_unstake_rejects_unsealed_position_before_building():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletCustodyReview2222222222222222222",
        user_id="user-custody-review",
        device_id="device-custody-review",
    )
    builder = MagicMock()
    builder.build_unstake_tx = AsyncMock()
    mismatch = SimpleNamespace(
        sealed=False,
        status="amount_mismatch",
        recorded_lp_tokens=100,
        amount_base_units=99,
        token_account="position-lp-pda",
    )

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(return_value={"lp_tokens": 100}),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=mismatch),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_prepare_unstake_from_vault(
                12,
                vault_routes.UnstakeRequest(withdraw_all=True),
                current_user,
                vault_repo,
                repo,
            )

    assert exc_info.value.status_code == 409
    assert "needs review" in str(exc_info.value.detail)
    builder.build_unstake_tx.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stake_result", "stake_error", "expected_status", "expected_detail"),
    [
        (None, None, 400, "No active LP position"),
        (None, RuntimeError("RPC unavailable"), 503, "Could not load on-chain LP position"),
    ],
)
async def test_prepare_unstake_distinguishes_missing_from_unavailable_chain_position(
    stake_result,
    stake_error,
    expected_status,
    expected_detail,
):
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletExactUnavailable22222222222222222",
        user_id="user-exact-unavailable",
        device_id="device-exact-unavailable",
    )
    unstake_request = vault_routes.UnstakeRequest(withdraw_all=True)
    read_stake = AsyncMock(return_value=stake_result)
    if stake_error is not None:
        read_stake.side_effect = stake_error

    with patch.object(
        vault_routes.solana_direct,
        "get_vault_stake_account",
        new=read_stake,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await _call_prepare_unstake_from_vault(
                12,
                unstake_request,
                current_user,
                vault_repo,
                repo,
            )

    assert exc_info.value.status_code == expected_status
    assert expected_detail in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stake_returns_pending_when_projection_fails_after_submit():
    repo = _make_repo()
    repo.client.rpc.return_value.execute.side_effect = RuntimeError("projection unavailable")
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 2,
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletStakePending2222222222222222222222",
        user_id="user-stake-pending",
        device_id="device-stake-pending",
    )
    stake_request = vault_routes.StakeRequest(
        cal_amount=250,
        signed_transaction="c3Rha2UtcGVuZGluZw==",
        last_valid_block_height=123,
        client_request_id="stake-pending-12",
    )
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_stake_tx = AsyncMock(return_value=_make_build_result(transaction="ZXhwZWN0ZWQtc3Rha2U="))
    builder.submit_signed_transaction = AsyncMock(return_value="tx-stake-submitted")

    with (
        patch.object(vault_routes.solana_direct, "get_cal_balance", new=AsyncMock(return_value=1_000)),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        response = await _call_stake_in_vault(12, stake_request, current_user, vault_repo, repo)

    assert response.tx_signature == "tx-stake-submitted"
    assert response.projection_status == "delayed"
    assert response.rider_state == "Delayed"
    assert response.operation_id.startswith("br-op-")
    assert response.stake is None
    assert response.cal_staked == "250"
    assert response.cal_staked_base_units == "250000000000"
    assert "do not retry" in response.message
    assert "transaction submitted" not in response.message
    builder.submit_signed_transaction.assert_awaited_once_with(
        "c3Rha2UtcGVuZGluZw==",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "deposit_cal"
    ]
    assert operation_rows[-1]["projection_status"] == "delayed"
    assert operation_rows[-1]["rider_state"] == "Delayed"
    assert operation_rows[-1]["failure_reason"] == "projection unavailable"
    assert operation_rows[-1]["metadata"]["adapter"] == "wallet_boundary_fallback"
    assert operation_rows[-1]["metadata"]["boundary_fallback"] == "true"


@pytest.mark.asyncio
async def test_stake_response_uses_exact_indexed_amounts_without_legacy_fallback():
    repo = _make_repo()
    repo.client.rpc.return_value.execute.return_value = SimpleNamespace(
        data=[{"stake_id": "stake-12"}]
    )
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Exact Climb",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 2,
        }
    )
    vault_repo.get_wallet_stake = AsyncMock(
        return_value={
            "id": "stake-indexed-12",
            "vault_signature": "cd" * 64,
            "wallet": "WalletStakeExact22222222222222222222222",
            "cal_staked": "9007199254740993",
            "lp_tokens": "9007199254740993",
        }
    )
    vault_repo.get_vault_total_stake = AsyncMock(
        return_value={
            "total_cal_staked": "18446744073709551615",
            "total_lp_tokens": "9007199254740993",
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletStakeExact22222222222222222222222",
        user_id="user-stake-exact",
        device_id="device-stake-exact",
    )
    stake_request = vault_routes.StakeRequest(
        cal_amount=250,
        signed_transaction="c3Rha2UtZXhhY3Q=",
        last_valid_block_height=123,
        client_request_id="stake-exact-12",
    )
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_stake_tx = AsyncMock(
        return_value=_make_build_result(transaction="ZXhwZWN0ZWQtc3Rha2U=")
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-stake-exact")

    with (
        patch.object(
            vault_routes.solana_direct,
            "get_cal_balance",
            new=AsyncMock(return_value=1_000),
        ),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes,
            "_decode_signed_transaction_or_400",
            return_value=signed_tx,
        ),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
    ):
        response = await _call_stake_in_vault(
            12,
            stake_request,
            current_user,
            vault_repo,
            repo,
        )

    assert response.cal_staked == "250"
    assert response.cal_staked_base_units == "250000000000"
    assert response.stake.cal_staked == "9007199.254740993"
    assert response.stake.cal_staked_base_units == "9007199254740993"
    assert response.total_position == "9007199.254740993"
    assert response.total_position_base_units == "9007199254740993"
    assert response.new_total_staked == "18446744073.709551615"
    assert response.new_total_staked_base_units == "18446744073709551615"
    assert response.lp_tokens_received is None
    assert all(
        table_call.args != ("vault_stakes",)
        for table_call in repo.client.table.call_args_list
    )


@pytest.mark.asyncio
async def test_unstake_returns_pending_when_projection_fails_after_submit():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    vault_repo.unstake_cal = AsyncMock(side_effect=ValueError("projection unavailable"))
    current_user = AuthenticatedUser(
        wallet="WalletUnstakePending222222222222222222",
        user_id="user-unstake-pending",
        device_id="device-unstake-pending",
    )
    unstake_request = vault_routes.UnstakeRequest(
        lp_amount_base_units="100000000000",
        signed_transaction="dW5zdGFrZS1wZW5kaW5n",
        last_valid_block_height=123,
        client_request_id="unstake-pending-12",
    )
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_unstake_tx = AsyncMock(return_value=_make_build_result(transaction="ZXhwZWN0ZWQtdW5zdGFrZQ=="))
    builder.submit_signed_transaction = AsyncMock(return_value="tx-unstake-submitted")

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(vault_routes, "_decode_signed_transaction_or_400", return_value=signed_tx),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(return_value={"lp_tokens": 100_000_000_000}),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(100_000_000_000)),
        ),
    ):
        response = await _call_unstake_from_vault(12, unstake_request, current_user, vault_repo, repo)

    assert response.tx_signature == "tx-unstake-submitted"
    assert response.projection_status == "delayed"
    assert response.rider_state == "Delayed"
    assert response.operation_id.startswith("br-op-")
    assert response.lp_burned == "100"
    assert response.lp_burned_base_units == "100000000000"
    assert response.cal_returned is None
    assert response.cal_returned_base_units is None
    assert "do not retry" in response.message
    assert "transaction submitted" not in response.message
    builder.submit_signed_transaction.assert_awaited_once_with(
        "dW5zdGFrZS1wZW5kaW5n",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "withdraw_cal"
    ]
    assert operation_rows[-1]["projection_status"] == "delayed"
    assert operation_rows[-1]["rider_state"] == "Delayed"
    assert operation_rows[-1]["failure_reason"] == "projection unavailable"
    assert operation_rows[-1]["metadata"]["adapter"] == "wallet_boundary_fallback"
    assert operation_rows[-1]["metadata"]["boundary_fallback"] == "true"


@pytest.mark.asyncio
async def test_unstake_withdraw_all_submits_and_reports_fractional_lp_exactly():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    vault_repo.unstake_cal = AsyncMock(
        return_value={"lp_burned": "1.23456789", "cal_returned": "1.22"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletUnstakeExact22222222222222222222",
        user_id="user-unstake-exact",
        device_id="device-unstake-exact",
    )
    unstake_request = vault_routes.UnstakeRequest(
        withdraw_all=True,
        signed_transaction="dW5zdGFrZS1leGFjdA==",
        last_valid_block_height=123,
        client_request_id="unstake-exact-12",
    )
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_unstake_tx = AsyncMock(
        return_value=_make_build_result(transaction="ZXhwZWN0ZWQtdW5zdGFrZQ==")
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-unstake-exact")

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes,
            "_decode_signed_transaction_or_400",
            return_value=signed_tx,
        ),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(return_value={"lp_tokens": 1_234_567_890}),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(1_234_567_890)),
        ),
    ):
        response = await _call_unstake_from_vault(
            12,
            unstake_request,
            current_user,
            vault_repo,
            repo,
        )

    builder.build_unstake_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        vault_id=12,
        lp_amount=1_234_567_890,
        blockhash=signed_tx.message.recent_blockhash,
        collect_rewards=False,
    )
    vault_repo.unstake_cal.assert_awaited_once_with(
        vault_signature="cd" * 64,
        wallet=current_user.wallet,
        lp_amount="1.23456789",
    )
    assert response.lp_burned == "1.23456789"
    assert response.lp_burned_base_units == "1234567890"
    assert response.cal_returned is None
    assert response.cal_returned_base_units is None
    assert response.tx_signature == "tx-unstake-exact"
    # No pending rewards -> nothing was composed and nothing is reported.
    assert response.dung_collected is None
    assert response.dung_collected_base_units is None
    assert response.dung_collected_total_base_units is None
    assert response.dung_collect_fee_base_units is None


@pytest.mark.asyncio
async def test_unstake_with_pending_rewards_composes_collect_and_reports_it():
    """One Balance action: the submit path verifies the composed transaction
    and the response reports the collected DUNG next to the withdraw."""
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    vault_repo.unstake_cal = AsyncMock(
        return_value={"lp_burned": "1.23456789", "cal_returned": "1.22"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletUnstakeExact22222222222222222222",
        user_id="user-unstake-exact",
        device_id="device-unstake-exact",
    )
    unstake_request = vault_routes.UnstakeRequest(
        withdraw_all=True,
        signed_transaction="dW5zdGFrZS1leGFjdA==",
        last_valid_block_height=123,
        client_request_id="unstake-exact-12",
    )
    builder = MagicMock()
    signed_tx = _make_signed_tx()
    builder.build_unstake_tx = AsyncMock(
        return_value=_make_build_result(transaction="ZXhwZWN0ZWQtdW5zdGFrZQ==")
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-unstake-composed")

    with (
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
        patch.object(
            vault_routes,
            "_decode_signed_transaction_or_400",
            return_value=signed_tx,
        ),
        patch.object(vault_routes, "_assert_signed_transaction_matches"),
        patch.object(
            vault_routes, "_get_harvest_fee_bps", new=AsyncMock(return_value=Decimal("500"))
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_stake_account",
            new=AsyncMock(
                return_value={
                    "lp_tokens": 1_234_567_890,
                    "rewards_earned": "1001",
                }
            ),
        ),
        patch.object(
            vault_routes.solana_direct,
            "get_vault_lp_custody_observation",
            new=AsyncMock(return_value=_sealed_custody(1_234_567_890)),
        ),
    ):
        response = await _call_unstake_from_vault(
            12,
            unstake_request,
            current_user,
            vault_repo,
            repo,
        )

    builder.build_unstake_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        vault_id=12,
        lp_amount=1_234_567_890,
        blockhash=signed_tx.message.recent_blockhash,
        collect_rewards=True,
    )
    assert response.tx_signature == "tx-unstake-composed"
    assert response.dung_collected_total_base_units == "1001"
    assert response.dung_collect_fee_base_units == "50"
    assert response.dung_collected_base_units == "951"
    assert response.dung_collected == "0.000000951"


@pytest.mark.asyncio
async def test_collect_dung_without_signed_transaction_preserves_permissionless_request_id():
    repo = _make_repo()
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={"id": 12, "signature_hex": "cd" * 64, "name": "Evening Climb"}
    )
    current_user = AuthenticatedUser(
        wallet="WalletCollectDung22222222222222222222",
        user_id="user-collect-dung",
        device_id="device-collect-dung",
    )
    builder = MagicMock()
    builder.fee_payer.pubkey.return_value = "fee-payer-12"
    builder.build_harvest_tx = AsyncMock(
        return_value=_make_build_result(
            transaction="Y29sbGVjdC1kdW5n",
            pda="DungWalletAta222",
        )
    )
    builder.submit_signed_transaction = AsyncMock(return_value="tx-collect-dung")
    request = vault_routes.HarvestRequest(client_request_id="collect-native-12")

    with (
        patch.object(
            vault_routes,
            "_get_onchain_claimable_stake_rewards",
            new=AsyncMock(return_value=({"id": 12}, {"rewards_earned": "1001"})),
        ),
        patch.object(vault_routes, "_get_harvest_fee_bps", new=AsyncMock(return_value=Decimal("500"))),
        patch.object(vault_routes, "get_tx_builder", return_value=builder),
    ):
        response = await _call_harvest_vault_rewards(12, request, current_user, vault_repo, repo)

    assert response.tx_signature == "tx-collect-dung"
    assert response.operation_id.startswith("br-op-")
    assert response.confirmation_status == "confirmed"
    assert response.rider_state == "Collected"
    assert response.message == "Collect DUNG complete."
    assert response.total_harvested == "0.000001001"
    assert response.total_harvested_base_units == "1001"
    assert response.fee_amount == "0.00000005"
    assert response.fee_amount_base_units == "50"
    assert response.net_received == "0.000000951"
    assert response.net_received_base_units == "951"
    assert response.destination_token_account == "DungWalletAta222"
    assert response.destination_type == "spl_wallet_ata"
    builder.build_harvest_tx.assert_awaited_once_with(
        user_wallet=current_user.wallet,
        vault_id=12,
    )
    builder.submit_signed_transaction.assert_awaited_once_with(
        "Y29sbGVjdC1kdW5n",
        last_valid_block_height=123,
    )
    operation_rows = [
        call.args[0]
        for call in repo.client.table.return_value.upsert.call_args_list
        if call.args and call.args[0].get("action_type") == "collect_dung"
    ]
    assert operation_rows[-1]["operation_id"] == response.operation_id
    assert operation_rows[-1]["metadata"]["client_request_id"] == "collect-native-12"
    assert operation_rows[-1]["authority_model"] == "permissionless_for_rider"
    assert operation_rows[-1]["fee_payer"] == "fee-payer-12"
    assert operation_rows[-1]["metadata"]["adapter"] == "collect_stake_rewards_for"
    assert operation_rows[-1]["metadata"]["boundary_fallback"] == "false"
    assert operation_rows[-1]["destination"] == "DungWalletAta222"
    assert operation_rows[-1]["metadata"]["destination_type"] == "spl_wallet_ata"
    assert operation_rows[-1]["metadata"]["destination_owner"] == current_user.wallet
    assert operation_rows[-1]["projection_status"] == "recorded"


@pytest.mark.asyncio
async def test_pending_dung_uses_exact_base_units_and_protocol_fee_floor():
    vault_repo = _make_vault_repo()
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 12,
            "signature_hex": "cd" * 64,
            "name": "Evening Climb",
            "last_distribution_epoch": 22,
        }
    )
    current_user = AuthenticatedUser(
        wallet="WalletPendingDung22222222222222222222",
        user_id="user-pending-dung",
        device_id="device-pending-dung",
    )

    with (
        patch.object(
            vault_routes,
            "_get_onchain_vault_position",
            new=AsyncMock(return_value=(
                object(),
                {"id": 12, "total_cal_staked": "2003"},
                {"rewards_earned": "1001", "lp_tokens": "1001"},
                SimpleNamespace(sealed=True, lp_supply_base_units=2000),
            )),
        ),
        patch.object(vault_routes, "_get_harvest_fee_bps", new=AsyncMock(return_value=Decimal("500"))),
        patch.object(vault_routes, "_get_exit_fee_bps", new=AsyncMock(return_value=Decimal("50"))),
    ):
        response = await _call_get_vault_pending_rewards(12, current_user, vault_repo)

    assert response.pending_rewards[0].amount == "0.000001001"
    assert response.pending_rewards[0].amount_base_units == "1001"
    assert response.total_pending == "0.000001001"
    assert response.total_pending_base_units == "1001"
    assert response.fee_estimate == "0.00000005"
    assert response.fee_estimate_base_units == "50"
    assert response.net_estimate == "0.000000951"
    assert response.net_estimate_base_units == "951"
    assert response.harvest_fee_bps == "500"
    assert response.exit_fee_bps == "50"
    assert response.lp_tokens_base_units == "1001"
    assert response.withdrawal_amount_base_units == "1002"
    assert response.withdrawal_fee_base_units == "5"
    assert response.withdrawal_net_base_units == "997"


@pytest.mark.asyncio
async def test_harvest_fee_reader_preserves_configured_zero():
    with (
        patch.object(
            vault_routes.solana_direct,
            "get_program_config_account",
            new=AsyncMock(return_value={"harvest_fee_bps": 0}),
        ),
        patch.object(vault_routes.solana_direct, "load_default_config", return_value=object()),
    ):
        fee_bps = await vault_routes._get_harvest_fee_bps()

    assert fee_bps == Decimal("0")


@pytest.mark.asyncio
async def test_record_completion_route_is_retired():
    vault_repo = _make_vault_repo()
    repo = _make_repo()
    current_user = AuthenticatedUser(
        wallet="WalletRetired333333333333333333333333333",
        user_id="user-retired",
        device_id="device-retired",
    )
    request = vault_routes.RecordCompletionRequest(
        activity_id="activity-1",
        time_seconds=1234,
    )

    record_impl = getattr(vault_routes.record_completion, "__wrapped__", vault_routes.record_completion)

    with pytest.raises(HTTPException) as exc_info:
        await record_impl(
            vault_id=9,
            request=request,
            current_user=current_user,
            vault_repo=vault_repo,
            repo=repo,
        )

    assert exc_info.value.status_code == 410
    vault_repo.get_vault_by_id.assert_not_called()


@pytest.mark.asyncio
async def test_admin_trigger_vault_backfill_is_retired_for_v4b():
    enqueue_mock = AsyncMock(return_value="job-admin")
    with patch.object(admin_routes, "enqueue_vault_backfill_job", new=enqueue_mock):
        with pytest.raises(HTTPException) as exc_info:
            await admin_routes.trigger_vault_backfill.__wrapped__(
                vault_id=21,
                request=SimpleNamespace(client=None, headers={}),
                body=admin_routes.BackfillRequest(priority=42),
                admin_ctx=(uuid4(), "admin"),
                repo=SimpleNamespace(client=MagicMock()),
            )

    assert exc_info.value.status_code == 410
    assert "canon traversal" in str(exc_info.value.detail)
    enqueue_mock.assert_not_awaited()
