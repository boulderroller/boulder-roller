from __future__ import annotations

import importlib
import inspect
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser

routes_pkg = ModuleType("app.routes")
routes_pkg.__path__ = [str(Path(__file__).resolve().parents[2] / "app" / "routes")]
sys.modules.setdefault("app.routes", routes_pkg)
distribution_routes = importlib.import_module("app.routes.distributions")


class _FakeTable:
    def __init__(self, table: str, table_data: dict[str, list[dict]], counts: dict[str, int]):
        self._table = table
        self._table_data = table_data
        self._counts = counts

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(
            data=self._table_data.get(self._table, []),
            count=self._counts.get(self._table),
        )


class _FakeClient:
    def __init__(self, table_data: dict[str, list[dict]], counts: dict[str, int] | None = None):
        self._table_data = table_data
        self._counts = counts or {}

    def table(self, table: str):
        return _FakeTable(table, self._table_data, self._counts)


def _make_repo(table_data: dict[str, list[dict]], counts: dict[str, int] | None = None):
    return SimpleNamespace(client=_FakeClient(table_data, counts))


async def _call_get_my_distributions(current_user, repo, **kwargs):
    impl = getattr(distribution_routes.get_my_distributions, "__wrapped__", distribution_routes.get_my_distributions)
    params = inspect.signature(impl).parameters
    call_kwargs = {
        "current_user": current_user,
        "repo": repo,
        "limit": kwargs.get("limit", 50),
        "offset": kwargs.get("offset", 0),
    }
    return await impl(**{k: v for k, v in call_kwargs.items() if k in params})


async def _call_get_vault_distribution_history(vault_id: int, repo, **kwargs):
    impl = getattr(
        distribution_routes.get_vault_distribution_history,
        "__wrapped__",
        distribution_routes.get_vault_distribution_history,
    )
    params = inspect.signature(impl).parameters
    call_kwargs = {
        "vault_id": vault_id,
        "repo": repo,
        "limit": kwargs.get("limit", 20),
    }
    return await impl(**{k: v for k, v in call_kwargs.items() if k in params})


@pytest.mark.asyncio
async def test_get_my_distributions_reads_indexed_staker_allocations():
    current_user = AuthenticatedUser(
        wallet="Wallet111111111111111111111111111111111",
        user_id="user-1",
        device_id="device-1",
    )
    repo = _make_repo(
        {
            "indexed_staker_allocations": [
                {
                    "tx_signature": "sig-1",
                    "event_index": 0,
                    "vault_id": 12,
                    "epoch": 14,
                    "amount": "420000000000",
                    "block_time": 1700007200,
                }
            ],
            "indexed_vaults": [
                {
                    "id": 12,
                    "signature_hex": "ab" * 64,
                    "carry_record_royalty": "100",
                    "carry_stakers": "200",
                    "carry_local_legend": "300",
                    "carry_pol": "400",
                    "carry_treasury": "500",
                }
            ],
            "indexed_epoch_distributions": [
                {
                    "vault_id": 12,
                    "epoch": 14,
                    "total_distributed": "4200000000000",
                    "leaderboard_distributed": "2310000000000",
                    "staker_distributed": "1260000000000",
                    "local_legend_distributed": "126000000000",
                    "pol_distributed": "210000000000",
                    "protocol_distributed": "294000000000",
                    "block_time": 1700007200,
                }
            ],
        },
        counts={"indexed_staker_allocations": 1},
    )

    response = await _call_get_my_distributions(current_user, repo)

    assert response.receipt_count == 1
    assert response.distribution_count == 1
    assert response.distributions[0].distribution_id == "v4a:12:14"
    assert response.distributions[0].staker_amount == "1260"
    assert response.distributions[0].staker_amount_base_units == "1260000000000"
    assert response.distributions[0].current_carry.record_royalty == "0.0000001"
    assert response.distributions[0].current_carry.stakers == "0.0000002"
    assert response.distributions[0].current_carry.local_legend == "0.0000003"
    assert response.distributions[0].current_carry.pol == "0.0000004"
    assert response.distributions[0].current_carry.treasury == "0.0000005"
    assert response.distributions[0].current_carry.total == "0.0000015"
    assert response.distributions[0].receipts[0].receipt_type == "STAKER"
    assert response.distributions[0].receipts[0].tx_signature == "sig-1"


@pytest.mark.asyncio
async def test_distribution_amounts_are_exact_and_unit_explicit():
    current_user = AuthenticatedUser(
        wallet="WalletExact11111111111111111111111111111",
        user_id="user-exact",
        device_id="device-exact",
    )
    repo = _make_repo(
        {
            "indexed_staker_allocations": [
                {
                    "tx_signature": "sig-exact",
                    "event_index": 0,
                    "vault_id": 31,
                    "epoch": 22,
                    "amount": "9007199254740993",
                    "block_time": 1700007200,
                }
            ],
            "indexed_vaults": [
                {
                    "id": 31,
                    "signature_hex": "31" * 64,
                    "carry_record_royalty": "1",
                    "carry_stakers": "100000000",
                    "carry_local_legend": "0",
                    "carry_pol": "0",
                    "carry_treasury": "0",
                }
            ],
            "indexed_epoch_distributions": [
                {
                    "vault_id": 31,
                    "epoch": 22,
                    "total_distributed": "9007199254740993",
                    "leaderboard_distributed": "340000000000",
                    "staker_distributed": "9007199254740993",
                    "local_legend_distributed": "1",
                    "pol_distributed": "0",
                    "protocol_distributed": "0",
                    "block_time": 1700007200,
                }
            ],
        },
        counts={"indexed_staker_allocations": 1},
    )

    response = await _call_get_my_distributions(current_user, repo)
    group = response.distributions[0]

    assert group.leaderboard_amount == "340"
    assert group.leaderboard_amount_base_units == "340000000000"
    assert group.staker_amount == "9007199.254740993"
    assert group.staker_amount_base_units == "9007199254740993"
    assert group.current_carry.record_royalty == "0.000000001"
    assert group.current_carry.record_royalty_base_units == "1"
    assert group.current_carry.total == "0.100000001"
    assert group.current_carry.total_base_units == "100000001"
    assert group.receipts[0].amount == "9007199.254740993"
    assert group.receipts[0].amount_base_units == "9007199254740993"


# ---------------------------------------------------------------------------
# BACKEND_TRUTHS §3.3 — `finalized_at` surfaces on distribution responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_my_distributions_surfaces_finalized_at_from_chain_projection():
    """The `/distributions/my` response must expose `finalized_at` derived
    from the chain-projection row. When the projection carries a populated
    `finalized_at` (generated from EpochRewardsDistributed block_time),
    surface it on the DistributionGroup so downstream UIs can enforce
    BACKEND_TRUTHS §3.3 (earnings locked)."""
    current_user = AuthenticatedUser(
        wallet="Wallet222222222222222222222222222222222",
        user_id="user-2",
        device_id="device-2",
    )
    repo = _make_repo(
        {
            "indexed_staker_allocations": [
                {
                    "tx_signature": "sig-2",
                    "event_index": 0,
                    "vault_id": 13,
                    "epoch": 15,
                    "amount": "210000000000",
                    "block_time": 1700100000,
                }
            ],
            "indexed_vaults": [
                {"id": 13, "signature_hex": "cd" * 64}
            ],
            "indexed_epoch_distributions": [
                {
                    "vault_id": 13,
                    "epoch": 15,
                    "total_distributed": "2100000000000",
                    "leaderboard_distributed": "1155000000000",
                    "staker_distributed": "567000000000",
                    "local_legend_distributed": "63000000000",
                    "pol_distributed": "105000000000",
                    "protocol_distributed": "210000000000",
                    "block_time": 1700100000,
                    # Chain-derived generated column populated by migration.
                    "finalized_at": "2026-04-13T13:00:00+00:00",
                }
            ],
        },
        counts={"indexed_staker_allocations": 1},
    )

    response = await _call_get_my_distributions(current_user, repo)
    assert response.distribution_count == 1
    assert response.distributions[0].finalized_at == "2026-04-13T13:00:00+00:00"


@pytest.mark.asyncio
async def test_get_my_distributions_finalized_at_empty_when_chain_event_not_yet_observed():
    """NULL/empty `finalized_at` means the chain event has not yet been
    projected. Backend must never fabricate a value — an empty string is
    the honest signal. BACKEND_TRUTHS §3.3 / §4.3 (Projected Truth)."""
    current_user = AuthenticatedUser(
        wallet="Wallet333333333333333333333333333333333",
        user_id="user-3",
        device_id="device-3",
    )
    repo = _make_repo(
        {
            "indexed_staker_allocations": [
                {
                    "tx_signature": "sig-3",
                    "event_index": 0,
                    "vault_id": 14,
                    "epoch": 16,
                    "amount": "100000000000",
                    "block_time": 0,
                }
            ],
            "indexed_vaults": [
                {"id": 14, "signature_hex": "ef" * 64}
            ],
            "indexed_epoch_distributions": [
                {
                    "vault_id": 14,
                    "epoch": 16,
                    "total_distributed": "1000000000000",
                    "leaderboard_distributed": "0",
                    "staker_distributed": "0",
                    "local_legend_distributed": "0",
                    "pol_distributed": "0",
                    "protocol_distributed": "0",
                    "block_time": None,
                    "finalized_at": None,
                }
            ],
        },
        counts={"indexed_staker_allocations": 1},
    )

    response = await _call_get_my_distributions(current_user, repo)
    assert response.distributions[0].finalized_at == ""


@pytest.mark.asyncio
async def test_vault_distribution_history_surfaces_finalized_at():
    """`/distributions/vault/{id}` surfaces `finalized_at` on each summary,
    sourced from the chain-projection generated column."""
    repo = _make_repo(
        {
            "indexed_vaults": [
                {
                    "id": 20,
                    "signature_hex": "aa" * 64,
                    "name": "Saturday Climb",
                    "carry_record_royalty": "11",
                    "carry_stakers": "22",
                    "carry_local_legend": "33",
                    "carry_pol": "44",
                    "carry_treasury": "55",
                }
            ],
            "indexed_epoch_distributions": [
                {
                    "tx_signature": "sig-epoch-20",
                    "event_index": 0,
                    "epoch": 20,
                    "total_distributed": "1000000000000",
                    "leaderboard_distributed": "550000000000",
                    "staker_distributed": "270000000000",
                    "local_legend_distributed": "30000000000",
                    "pol_distributed": "50000000000",
                    "protocol_distributed": "100000000000",
                    "block_time": 1700200000,
                    "finalized_at": "2026-04-20T13:06:40+00:00",
                    "staker_count": 3,
                    "unlock_pct": 50,
                    "locked_staker_amount": "100000000000",
                }
            ],
        }
    )

    response = await _call_get_vault_distribution_history(20, repo)
    assert response.distribution_count == 1
    assert response.distributions[0].finalized_at == "2026-04-20T13:06:40+00:00"
    assert response.current_carry.record_royalty == "0.000000011"
    assert response.current_carry.stakers == "0.000000022"
    assert response.current_carry.local_legend == "0.000000033"
    assert response.current_carry.pol == "0.000000044"
    assert response.current_carry.treasury == "0.000000055"
    assert response.current_carry.total == "0.000000165"


def test_finalized_at_iso_prefers_generated_column_over_block_time():
    """When both `finalized_at` (chain-generated) and `block_time` (unix
    seconds) are present, prefer the generated column — it's the canonical
    timestamp. When only block_time is present (legacy queue path), derive
    from it. When neither is present, return empty string (honest pending)."""
    helper = distribution_routes._finalized_at_iso

    # Generated column present — use it verbatim.
    assert helper({"finalized_at": "2026-04-13T13:00:00+00:00", "block_time": 1700000000}) == "2026-04-13T13:00:00+00:00"

    # Only block_time present — derive ISO.
    iso = helper({"block_time": 1700000000})
    assert iso.startswith("2023-")  # Nov 2023 per unix ts, string surface OK.

    # Neither present — empty string (pending).
    assert helper({}) == ""
    assert helper({"finalized_at": None, "block_time": None}) == ""
    assert helper({"finalized_at": None, "block_time": 0}) == ""


@pytest.mark.asyncio
async def test_get_vault_distribution_history_reads_indexed_epoch_distributions():
    repo = _make_repo(
        {
            "indexed_vaults": [
                {
                    "id": 12,
                    "signature_hex": "ab" * 64,
                    "name": "Morning Climb",
                }
            ],
            "indexed_epoch_distributions": [
                {
                    "tx_signature": "sig-epoch-14",
                    "event_index": 0,
                    "epoch": 14,
                    "total_distributed": "4200000000000",
                    "leaderboard_distributed": "2310000000000",
                    "staker_distributed": "1260000000000",
                    "local_legend_distributed": "126000000000",
                    "pol_distributed": "210000000000",
                    "protocol_distributed": "294000000000",
                    "block_time": 1700007200,
                    "staker_count": 4,
                    "unlock_pct": 70,
                    "locked_staker_amount": "540000000000",
                }
            ],
        }
    )

    response = await _call_get_vault_distribution_history(12, repo)

    assert response.vault_id == 12
    assert response.distribution_count == 1
    assert response.distributions[0].distribution_id == "sig-epoch-14:0"
    assert response.distributions[0].total_amount == "4200"
    assert response.distributions[0].total_amount_base_units == "4200000000000"
    assert response.distributions[0].staker_count == 4
    assert response.distributions[0].unlock_pct == 70
    assert response.distributions[0].locked_staker_amount == "540"
    assert response.distributions[0].locked_staker_amount_base_units == "540000000000"


@pytest.mark.asyncio
async def test_current_epoch_uses_indexed_clock_and_real_monday_boundary(monkeypatch):
    from app.settlement_clock import (
        SETTLEMENT_CLOCK_VERSION_V2,
        SETTLEMENT_WEEK_DURATION_SECONDS,
        SETTLEMENT_WEEK_V2_ANCHOR,
    )

    transition_week = 200
    cutover = SETTLEMENT_WEEK_V2_ANCHOR + (
        transition_week * SETTLEMENT_WEEK_DURATION_SECONDS
    )
    now = cutover + SETTLEMENT_WEEK_DURATION_SECONDS + 60
    monkeypatch.setattr(distribution_routes.time, "time", lambda: now)
    repo = _make_repo(
        {
            "indexed_program_config": [
                {
                    "settlement_clock_version": SETTLEMENT_CLOCK_VERSION_V2,
                    "settlement_clock_v2_starts_at": cutover,
                    "chain_slot": 123,
                }
            ]
        }
    )

    response = await distribution_routes.get_current_epoch_info(repo=repo)

    assert response.settlement_week == transition_week + 1
    assert response.current_epoch == response.settlement_week
    assert response.starts_at.endswith("12:00:00+00:00")
    assert response.ends_at.endswith("12:00:00+00:00")
    assert response.ends_at.startswith("2027-")
    assert response.duration_seconds == SETTLEMENT_WEEK_DURATION_SECONDS
    assert response.is_transition_week is False


@pytest.mark.asyncio
async def test_current_epoch_fails_closed_without_indexed_clock():
    with pytest.raises(Exception) as exc_info:
        await distribution_routes.get_current_epoch_info(repo=_make_repo({}))

    assert getattr(exc_info.value, "status_code", None) == 503
