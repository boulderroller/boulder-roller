from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.metrics import SOLANA_PAYER_BALANCE_CHECKED, SOLANA_PAYER_BALANCE_SOL
from app.routes import health

WALLET = "9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP"


@pytest.fixture
def payer(monkeypatch):
    clock = {"now": 1_800_000_000.0}
    reads: list[tuple[str, float]] = []
    state = {"lamports": 7_377_500_000, "fail": False}

    async def query(wallet: str, timeout_s: float) -> int:
        reads.append((wallet, timeout_s))
        if state["fail"]:
            raise RuntimeError("rpc down")
        return state["lamports"]

    async def pubkey() -> str:
        return WALLET

    monkeypatch.setattr(health.time, "time", lambda: clock["now"])
    monkeypatch.setattr(health, "_query_payer_balance_lamports", query)
    monkeypatch.setattr(health, "_get_payer_pubkey", pubkey)
    monkeypatch.setattr(health, "_sol_balance_cache", {})
    monkeypatch.setattr(health, "_sol_scrape_failed_at", 0.0)
    SOLANA_PAYER_BALANCE_SOL.set(0)
    SOLANA_PAYER_BALANCE_CHECKED.set(0)
    return clock, reads, state


@pytest.mark.asyncio
async def test_scrape_reads_the_payer_balance_once_per_fifteen_minutes(payer) -> None:
    clock, reads, _ = payer

    await health._refresh_payer_balance_gauge()
    assert reads == [(WALLET, 3)]
    assert SOLANA_PAYER_BALANCE_SOL._value.get() == pytest.approx(7.3775)
    assert SOLANA_PAYER_BALANCE_CHECKED._value.get() == clock["now"]

    clock["now"] += 899
    await health._refresh_payer_balance_gauge()
    assert len(reads) == 1

    clock["now"] += 1
    await health._refresh_payer_balance_gauge()
    assert len(reads) == 2


@pytest.mark.asyncio
async def test_failed_read_keeps_the_last_gauges_and_waits_before_retrying(payer) -> None:
    clock, reads, state = payer
    await health._refresh_payer_balance_gauge()
    checked = SOLANA_PAYER_BALANCE_CHECKED._value.get()

    state["fail"] = True
    clock["now"] += 900
    await health._refresh_payer_balance_gauge()
    clock["now"] += 299
    await health._refresh_payer_balance_gauge()

    assert len(reads) == 2
    assert SOLANA_PAYER_BALANCE_SOL._value.get() == pytest.approx(7.3775)
    assert SOLANA_PAYER_BALANCE_CHECKED._value.get() == checked

    state["fail"] = False
    clock["now"] += 1
    await health._refresh_payer_balance_gauge()
    assert len(reads) == 3
    assert SOLANA_PAYER_BALANCE_CHECKED._value.get() == clock["now"]


@pytest.mark.asyncio
async def test_admin_balance_route_keeps_its_cache_and_errors(payer, monkeypatch) -> None:
    clock, reads, state = payer

    first = await health.sol_balance(_admin_ctx=None)
    again = await health.sol_balance(_admin_ctx=None)
    assert (first.balance_sol, first.cached, first.alert) == (7.3775, False, False)
    assert again.cached and len(reads) == 1
    assert reads[0][1] == 10

    state["fail"] = True
    clock["now"] += 60
    with pytest.raises(HTTPException) as failed:
        await health.sol_balance(_admin_ctx=None)
    assert (failed.value.status_code, failed.value.detail) == (503, "Failed to query Solana RPC")

    async def no_wallet() -> None:
        return None

    monkeypatch.setattr(health, "_get_payer_pubkey", no_wallet)
    with pytest.raises(HTTPException) as missing:
        await health.sol_balance(_admin_ctx=None)
    assert missing.value.detail == "Fee payer wallet not configured"
