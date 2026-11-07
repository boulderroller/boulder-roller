from types import SimpleNamespace
from unittest.mock import patch

from solders.pubkey import Pubkey

from app.solana_direct import (
    _decode_anchor_vault_account,
    _decode_anchor_vault_stake_account,
    _stake_requires_settlement_account,
)


def _vault_fields(**overrides):
    fields = {
        "id": 12,
        "signature": bytes([1]) * 64,
        "signatureHash": bytes([2]) * 32,
        "minter": Pubkey.default(),
        "mintEpoch": 1,
        "rightsExpiresEpoch": 99,
        "komHolder": Pubkey.default(),
        "komTimeS": 161,
        "komSetEpoch": 2,
        "name": b"Test Vault" + (b"\x00" * 54),
        "calTributeAccumulated": 100,
        "calTributeAccumulatedNext": 25,
        "totalCalBurned": 10,
        "totalDungEmitted": 20,
        "totalCompletions": 3,
        "totalCalStaked": 400,
        "stakerCount": 5,
        "rewardPerTokenStored": 999,
        "lastUpdateTime": 888,
        "rewardRate": 777,
        "pendingRewards": 600,
        "pendingRewardsNextWeek": 700,
        "openSettlementWeek": 8,
        "carryRecordRoyalty": 9,
        "carryStakers": 10,
        "carryLocalLegend": 11,
        "carryPol": 12,
        "carryTreasury": 13,
        "totalStaked": 400,
        "lastDistributionEpoch": 7,
        "vertM": 9886,
        "distanceM": 6136,
        "avgGradientPct": 1611,
        "createdAt": 1713456789,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_decode_anchor_vault_exposes_canonical_rewards_not_synthetix_slots():
    coder = SimpleNamespace(
        parse=lambda _data: SimpleNamespace(name="Vault", data=_vault_fields())
    )

    with patch("app.solana_direct._get_boulder_accounts_coder", return_value=coder):
        decoded = _decode_anchor_vault_account(b"ignored", Pubkey.default())

    assert decoded["pending_rewards"] == 600
    assert decoded["pending_rewards_next_week"] == 700
    assert decoded["carry_record_royalty"] == 9
    assert decoded["carry_stakers"] == 10
    assert decoded["carry_local_legend"] == 11
    assert decoded["carry_pol"] == 12
    assert decoded["carry_treasury"] == 13
    assert "reward_per_token_stored" not in decoded
    assert "last_update_time" not in decoded
    assert "reward_rate" not in decoded


def test_decode_anchor_vault_stake_exposes_weekly_lp_snapshot_state():
    fields = SimpleNamespace(
        user=Pubkey.default(),
        vaultId=12,
        calStaked=400,
        lpTokens=350,
        stakedAt=1713456789,
        pendingEffectiveWeekPlusOne=10,
        effectiveLpTokens=300,
        rewardsEarned=25,
        pendingLpTokens=350,
        bump=254,
    )
    coder = SimpleNamespace(
        parse=lambda _data: SimpleNamespace(name="VaultStake", data=fields)
    )

    with patch("app.solana_direct._get_boulder_accounts_coder", return_value=coder):
        decoded = _decode_anchor_vault_stake_account(b"ignored", Pubkey.default())

    assert decoded["effective_lp_tokens"] == 300
    assert decoded["pending_lp_tokens"] == 350
    assert decoded["pending_effective_week_plus_one"] == 10
    assert decoded["eligible_from_epoch"] == 0
    assert decoded["snapshot_layout"] == "weekly"
    assert decoded["bump"] == 254
    assert "user_reward_per_token_paid" not in decoded
    assert "amount" not in decoded


def test_decode_anchor_vault_stake_preserves_legacy_eligibility_provenance():
    fields = SimpleNamespace(
        user=Pubkey.default(),
        vaultId=12,
        calStaked=100,
        lpTokens=100,
        stakedAt=1713456789,
        pendingEffectiveWeekPlusOne=9,
        effectiveLpTokens=0,
        rewardsEarned=25,
        pendingLpTokens=0,
        bump=254,
    )
    coder = SimpleNamespace(
        parse=lambda _data: SimpleNamespace(name="VaultStake", data=fields)
    )

    with patch("app.solana_direct._get_boulder_accounts_coder", return_value=coder):
        decoded = _decode_anchor_vault_stake_account(b"ignored", Pubkey.default())

    assert decoded["snapshot_layout"] == "legacy"
    assert decoded["eligible_from_epoch"] == 9
    assert decoded["pending_effective_week_plus_one"] == 0
    assert decoded["effective_lp_tokens"] == 0
    assert decoded["pending_lp_tokens"] == 0
    assert decoded["bump"] == 254


def test_settlement_inventory_keeps_snapshot_tombstones_but_drops_inert_accounts():
    assert _stake_requires_settlement_account(
        {
            "lp_tokens": 0,
            "effective_lp_tokens": 100,
            "pending_lp_tokens": 0,
        }
    )
    assert _stake_requires_settlement_account(
        {
            "lp_tokens": 100,
            "effective_lp_tokens": 0,
            "pending_lp_tokens": 100,
        }
    )
    assert not _stake_requires_settlement_account(
        {
            "lp_tokens": 0,
            "effective_lp_tokens": 0,
            "pending_lp_tokens": 0,
        }
    )
