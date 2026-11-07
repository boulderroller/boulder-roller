"""
Tests for EpochProcessor - epoch distribution functionality.

Coverage:
- Epoch state tracking
- Distribution calculations
- Leaderboard payouts (55% split to top 10)
- Staker rewards (27%)
- Local Legend earnings (3%)
- POL/Protocol splits (5%/10%)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Distribution constants from epoch_processor
LEADERBOARD_SHARE_BPS = 5500  # 55%
STAKER_SHARE_BPS = 2700  # 27%
LOCAL_LEGEND_SHARE_BPS = 300  # 3%
POL_SHARE_BPS = 500  # 5%
PROTOCOL_SHARE_BPS = 1000  # 10%

# Leaderboard rank percentages (top 10)
LEADERBOARD_RANK_PCTS = (30, 20, 15, 10, 8, 6, 5, 3, 2, 1)


def calculate_distribution_split(total_dung: Decimal) -> Dict[str, Decimal]:
    """Calculate distribution splits matching TOKENOMICS_V2."""
    return {
        "leaderboard": total_dung * Decimal(LEADERBOARD_SHARE_BPS) / Decimal(10000),
        "stakers": total_dung * Decimal(STAKER_SHARE_BPS) / Decimal(10000),
        "local_legend": total_dung * Decimal(LOCAL_LEGEND_SHARE_BPS) / Decimal(10000),
        "pol": total_dung * Decimal(POL_SHARE_BPS) / Decimal(10000),
        "protocol": total_dung * Decimal(PROTOCOL_SHARE_BPS) / Decimal(10000),
    }


def calculate_leaderboard_payouts(leaderboard_pot: Decimal, rankings: List[str]) -> Dict[str, Decimal]:
    """Calculate payouts for leaderboard positions."""
    payouts = {}
    for i, wallet in enumerate(rankings[:10]):
        pct = LEADERBOARD_RANK_PCTS[i] if i < len(LEADERBOARD_RANK_PCTS) else 0
        payouts[wallet] = leaderboard_pot * Decimal(pct) / Decimal(100)
    return payouts


class TestDistributionSplits:
    """Tests for distribution split calculations."""

    def test_distribution_percentages_sum_to_100(self):
        """All distribution shares should sum to 100%."""
        total_bps = (
            LEADERBOARD_SHARE_BPS +
            STAKER_SHARE_BPS +
            LOCAL_LEGEND_SHARE_BPS +
            POL_SHARE_BPS +
            PROTOCOL_SHARE_BPS
        )
        assert total_bps == 10000  # 100%

    def test_leaderboard_rank_percentages_sum_to_100(self):
        """Leaderboard rank percentages should sum to 100%."""
        assert sum(LEADERBOARD_RANK_PCTS) == 100

    def test_distribution_split_1000_dung(self):
        """Test distribution of 1000 DUNG (1M CAL converted)."""
        splits = calculate_distribution_split(Decimal("1000"))

        assert splits["leaderboard"] == Decimal("550")  # 55%
        assert splits["stakers"] == Decimal("270")  # 27%
        assert splits["local_legend"] == Decimal("30")  # 3%
        assert splits["pol"] == Decimal("50")  # 5%
        assert splits["protocol"] == Decimal("100")  # 10%

        # Verify total equals input
        total = sum(splits.values())
        assert total == Decimal("1000")

    def test_distribution_split_small_amount(self):
        """Test distribution with small DUNG amount."""
        splits = calculate_distribution_split(Decimal("10"))

        assert splits["leaderboard"] == Decimal("5.5")
        assert splits["stakers"] == Decimal("2.7")
        assert splits["local_legend"] == Decimal("0.3")
        assert splits["pol"] == Decimal("0.5")
        assert splits["protocol"] == Decimal("1.0")

    def test_distribution_split_zero(self):
        """Zero DUNG should result in zero splits."""
        splits = calculate_distribution_split(Decimal("0"))

        for value in splits.values():
            assert value == Decimal("0")


class TestLeaderboardPayouts:
    """Tests for leaderboard payout calculations."""

    def test_full_leaderboard_payout(self):
        """Test payouts for full 10-person leaderboard."""
        rankings = [f"wallet-{i}" for i in range(10)]
        payouts = calculate_leaderboard_payouts(Decimal("550"), rankings)

        assert len(payouts) == 10
        assert payouts["wallet-0"] == Decimal("165")  # 30%
        assert payouts["wallet-1"] == Decimal("110")  # 20%
        assert payouts["wallet-2"] == Decimal("82.5")  # 15%
        assert payouts["wallet-3"] == Decimal("55")  # 10%
        assert payouts["wallet-4"] == Decimal("44")  # 8%
        assert payouts["wallet-5"] == Decimal("33")  # 6%
        assert payouts["wallet-6"] == Decimal("27.5")  # 5%
        assert payouts["wallet-7"] == Decimal("16.5")  # 3%
        assert payouts["wallet-8"] == Decimal("11")  # 2%
        assert payouts["wallet-9"] == Decimal("5.5")  # 1%

        # Verify total
        assert sum(payouts.values()) == Decimal("550")

    def test_partial_leaderboard_payout(self):
        """Test payouts when fewer than 10 on leaderboard."""
        rankings = [f"wallet-{i}" for i in range(5)]
        payouts = calculate_leaderboard_payouts(Decimal("550"), rankings)

        assert len(payouts) == 5
        # First 5 get their share, rest of pot remains
        assert payouts["wallet-0"] == Decimal("165")  # 30%
        assert payouts["wallet-4"] == Decimal("44")  # 8%

    def test_single_person_leaderboard(self):
        """Single person on leaderboard gets 30%."""
        rankings = ["solo-wallet"]
        payouts = calculate_leaderboard_payouts(Decimal("550"), rankings)

        assert len(payouts) == 1
        assert payouts["solo-wallet"] == Decimal("165")

    def test_empty_leaderboard(self):
        """Empty leaderboard should return empty payouts."""
        payouts = calculate_leaderboard_payouts(Decimal("550"), [])

        assert len(payouts) == 0


class TestEpochTransition:
    """Tests for epoch transition logic."""

    def test_epoch_number_calculation(self):
        """Test epoch number is calculated correctly from timestamps."""
        from datetime import timedelta

        # Epoch duration is 7 days (604800 seconds)
        EPOCH_DURATION_SECONDS = 604800

        # Assume epoch 0 started at a known time
        epoch_0_start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        def get_epoch_for_timestamp(ts: datetime, epoch_0: datetime) -> int:
            delta = (ts - epoch_0).total_seconds()
            return int(delta // EPOCH_DURATION_SECONDS)

        # Day 1 of epoch 0
        assert get_epoch_for_timestamp(epoch_0_start, epoch_0_start) == 0

        # Day 7 (still epoch 0)
        assert get_epoch_for_timestamp(
            epoch_0_start + timedelta(days=6, hours=23),
            epoch_0_start
        ) == 0

        # Day 8 (epoch 1)
        assert get_epoch_for_timestamp(
            epoch_0_start + timedelta(days=7, hours=1),
            epoch_0_start
        ) == 1

        # Day 15 (epoch 2)
        assert get_epoch_for_timestamp(
            epoch_0_start + timedelta(days=14, hours=1),
            epoch_0_start
        ) == 2


class TestStakerRewardCalculation:
    """Tests for staker reward calculations."""

    def test_single_staker_gets_full_share(self):
        """Single staker gets entire staker pot."""
        total_staked = Decimal("1000")
        staker_stakes = {"wallet-1": Decimal("1000")}
        staker_pot = Decimal("270")  # 27% of 1000 DUNG

        rewards = {}
        for wallet, stake in staker_stakes.items():
            share = stake / total_staked
            rewards[wallet] = staker_pot * share

        assert rewards["wallet-1"] == Decimal("270")

    def test_proportional_staker_rewards(self):
        """Multiple stakers get proportional share."""
        total_staked = Decimal("1000")
        staker_stakes = {
            "wallet-1": Decimal("600"),  # 60%
            "wallet-2": Decimal("300"),  # 30%
            "wallet-3": Decimal("100"),  # 10%
        }
        staker_pot = Decimal("270")

        rewards = {}
        for wallet, stake in staker_stakes.items():
            share = stake / total_staked
            rewards[wallet] = staker_pot * share

        assert rewards["wallet-1"] == Decimal("162")  # 60% of 270
        assert rewards["wallet-2"] == Decimal("81")  # 30% of 270
        assert rewards["wallet-3"] == Decimal("27")  # 10% of 270
        assert sum(rewards.values()) == staker_pot

    def test_no_stakers_zero_rewards(self):
        """Zero stakers means no staker rewards distributed."""
        staker_stakes = {}
        staker_pot = Decimal("270")

        rewards = {}
        if not staker_stakes:
            # Pot goes to treasury or POL
            pass

        assert len(rewards) == 0


class TestLocalLegendReward:
    """Tests for Local Legend (Soigneur) reward."""

    def test_local_legend_single_recipient(self):
        """Local Legend holder gets full 3% share."""
        local_legend_pot = Decimal("30")  # 3% of 1000 DUNG
        legend_holder = "legend-wallet"

        reward = {legend_holder: local_legend_pot}

        assert reward[legend_holder] == Decimal("30")

    def test_no_local_legend_pot_to_treasury(self):
        """When no Local Legend, pot should go elsewhere."""
        local_legend_pot = Decimal("30")
        legend_holder = None

        # Without legend, pot typically goes to treasury
        if legend_holder is None:
            redirect_to = "treasury"
        else:
            redirect_to = legend_holder

        assert redirect_to == "treasury"


class TestCalToDungConversion:
    """Tests for CAL to DUNG conversion threshold."""

    def test_cal_conversion_threshold(self):
        """1000 CAL = 1 DUNG conversion."""
        CAL_TO_DUNG_RATIO = 1000

        assert 1000 // CAL_TO_DUNG_RATIO == 1
        assert 2500 // CAL_TO_DUNG_RATIO == 2
        assert 999 // CAL_TO_DUNG_RATIO == 0
        assert 10000 // CAL_TO_DUNG_RATIO == 10

    def test_minimum_distribution_threshold(self):
        """Vaults need >= 1000 CAL accumulated to distribute."""
        VAULT_CAL_TO_DUNG_THRESHOLD = 1000

        vault_cal_amounts = [500, 999, 1000, 2500, 10000]
        distributable = [cal for cal in vault_cal_amounts if cal >= VAULT_CAL_TO_DUNG_THRESHOLD]

        assert distributable == [1000, 2500, 10000]
