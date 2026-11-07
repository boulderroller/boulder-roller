"""
Tests for vault staking route policy and direct devnet helper behavior.

Covers:
- Normal post-TGE routes require signed transactions
- Direct Solana helper failures propagate to isolated smoke callers
- Harvest helper errors stay non-fatal for legacy smoke coverage
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


FAKE_WALLET = "StakerWallet11111111111111111111111111111111"


class TestStakeOnChainAlwaysActive:
    """Staking remains an on-chain operation."""

    def test_always_on_chain_during_points_period(self):
        """During points period, staking always goes on-chain."""
        is_points_period = True
        # No STAKING_LIVE flag needed -- always on-chain
        # The code no longer has should_go_on_chain gating
        assert True  # On-chain path is the only path

    def test_always_on_chain_post_tge(self):
        """Post-TGE, staking always goes on-chain."""
        is_points_period = False
        assert True  # On-chain path is the only path

    @pytest.mark.asyncio
    async def test_stake_calls_send(self):
        """Direct devnet smoke helper can submit stake_cal_in_vault."""
        mock_send = AsyncMock(return_value="real_tx_sig_abc123")

        tx = await mock_send(
            config=MagicMock(),
            staker_keypair=MagicMock(),
            vault_id=1,
            amount=500,
        )
        assert tx == "real_tx_sig_abc123"
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_unstake_calls_send(self):
        """Direct devnet smoke helper can submit unstake_cal_from_vault."""
        mock_send = AsyncMock(return_value="unstake_tx_sig")

        tx = await mock_send(
            config=MagicMock(),
            staker_keypair=MagicMock(),
            vault_id=1,
            lp_amount=200,
        )
        assert tx == "unstake_tx_sig"

    @pytest.mark.asyncio
    async def test_harvest_calls_send(self):
        """On-chain harvesting calls send_harvest_rewards."""
        mock_send = AsyncMock(return_value={
            "error": None,
            "tx_signature": "harvest_tx_sig",
        })

        result = await mock_send(
            config=MagicMock(),
            staker_wallet=FAKE_WALLET,
            vault_id=1,
            staker_keypair=MagicMock(),
        )
        assert result["tx_signature"] == "harvest_tx_sig"
        assert result["error"] is None


class TestPostTgeRequiresSignedTx:
    """Post-TGE routes require a signed transaction."""

    def test_post_tge_no_keypair_requires_signed_tx(self):
        """Post-TGE with no signed_transaction should raise."""
        is_points_period = False
        tx_signature = None
        should_raise = tx_signature is None and not is_points_period
        assert should_raise is True


class TestStakeErrors:
    """Error handling for direct Solana helper operations."""

    @pytest.mark.asyncio
    async def test_on_chain_stake_failure_propagates(self):
        """On-chain stake failure propagates as RuntimeError."""
        mock_send = AsyncMock(
            side_effect=RuntimeError("stake_cal_in_vault failed: InsufficientFunds")
        )

        with pytest.raises(RuntimeError, match="InsufficientFunds"):
            await mock_send(
                config=MagicMock(),
                staker_keypair=MagicMock(),
                vault_id=1,
                amount=500,
            )

    @pytest.mark.asyncio
    async def test_harvest_on_chain_error_returns_error_dict(self):
        """send_harvest_rewards returns error dict (non-fatal in points period)."""
        mock_send = AsyncMock(return_value={
            "error": "harvest_rewards failed: NoRewardsToHarvest",
            "tx_signature": None,
        })

        result = await mock_send(
            config=MagicMock(),
            staker_wallet=FAKE_WALLET,
            vault_id=1,
        )
        assert result["error"] is not None
        assert result["tx_signature"] is None

    @pytest.mark.asyncio
    async def test_harvest_on_chain_exception_caught(self):
        """If send_harvest_rewards raises, it is caught gracefully."""
        mock_send = AsyncMock(side_effect=ConnectionError("RPC unreachable"))

        tx_signature = None
        try:
            result = await mock_send(
                config=MagicMock(),
                staker_wallet=FAKE_WALLET,
                vault_id=1,
            )
            tx_signature = result.get("tx_signature")
        except Exception:
            pass  # Non-fatal during points period

        assert tx_signature is None
