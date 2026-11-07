"""Tests that get_cal_balance returns human-readable CAL, not raw lamports.

Regression test for the bug where 1.5 CAL was displayed as 1,500,000,000 CAL
because get_cal_balance() returned raw atomic units (9 decimal places) and
route handlers passed them through without dividing by 10^9.
"""

from __future__ import annotations

import importlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")


class TestGetCalBalanceUnits:
    """get_cal_balance returns human-readable CAL (divided by 10^9)."""

    @pytest.mark.asyncio
    async def test_returns_human_readable_for_whole_cal(self):
        """1_500_000_000 atomic units -> 1.5 CAL."""
        from app.solana_direct import get_cal_balance, CAL_SPL_DECIMALS

        assert CAL_SPL_DECIMALS == 9

        # Mock the RPC call chain
        mock_balance = SimpleNamespace(
            value=SimpleNamespace(amount="1500000000")
        )
        mock_account_info = SimpleNamespace(value=b"\x00" * 165)  # non-None = ATA exists
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_token_account_balance = AsyncMock(return_value=mock_balance)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.solana_direct.AsyncClient", return_value=mock_client):
            result = await get_cal_balance(
                "11111111111111111111111111111111",
                rpc_url="https://api.devnet.solana.com",
                program_id=None,
            )

        assert result == 1.5
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_returns_zero_for_missing_ata(self):
        """Missing ATA returns 0.0, not 0 (int)."""
        from app.solana_direct import get_cal_balance

        mock_account_info = SimpleNamespace(value=None)
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.solana_direct.AsyncClient", return_value=mock_client):
            result = await get_cal_balance(
                "11111111111111111111111111111111",
                rpc_url="https://api.devnet.solana.com",
                program_id=None,
            )

        assert result == 0.0
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_large_balance_not_inflated(self):
        """100 CAL should NOT become 100_000_000_000 (the original bug)."""
        from app.solana_direct import get_cal_balance

        # 100 CAL = 100_000_000_000 atomic units
        mock_balance = SimpleNamespace(
            value=SimpleNamespace(amount="100000000000")
        )
        mock_account_info = SimpleNamespace(value=b"\x00" * 165)
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_token_account_balance = AsyncMock(return_value=mock_balance)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.solana_direct.AsyncClient", return_value=mock_client):
            result = await get_cal_balance(
                "11111111111111111111111111111111",
                rpc_url="https://api.devnet.solana.com",
                program_id=None,
            )

        assert result == 100.0
        # The original bug would have returned 100_000_000_000.0
        assert result < 1_000_000

    @pytest.mark.asyncio
    async def test_fractional_cal_preserved(self):
        """0.000000001 CAL (1 atomic unit) is preserved."""
        from app.solana_direct import get_cal_balance

        mock_balance = SimpleNamespace(
            value=SimpleNamespace(amount="1")
        )
        mock_account_info = SimpleNamespace(value=b"\x00" * 165)
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_token_account_balance = AsyncMock(return_value=mock_balance)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.solana_direct.AsyncClient", return_value=mock_client):
            result = await get_cal_balance(
                "11111111111111111111111111111111",
                rpc_url="https://api.devnet.solana.com",
                program_id=None,
            )

        assert result == 1e-9

    @pytest.mark.asyncio
    async def test_exact_reader_preserves_amount_above_javascript_safe_integer(self):
        from app.solana_direct import get_cal_balance_base_units

        mock_balance = SimpleNamespace(
            value=SimpleNamespace(amount="9007199254740993")
        )
        mock_account_info = SimpleNamespace(value=b"\x00" * 165)
        mock_client = AsyncMock()
        mock_client.get_account_info = AsyncMock(return_value=mock_account_info)
        mock_client.get_token_account_balance = AsyncMock(return_value=mock_balance)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.solana_direct.AsyncClient", return_value=mock_client):
            result = await get_cal_balance_base_units(
                "11111111111111111111111111111111",
                rpc_url="https://api.devnet.solana.com",
                program_id=None,
            )

        assert result == 9_007_199_254_740_993
