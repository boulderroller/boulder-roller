"""Serialization parity tests for instruction builders.

Validates that the Python instruction builders produce data and account lists
that exactly match the on-chain Anchor structs.
Any drift here means chain writes silently corrupt or fail.
"""

import hashlib
import struct

import pytest
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta
from solders.pubkey import Pubkey

from app.solana_direct import (
    make_admin_seed_vault_completion_summary_ix,
    make_admin_replace_vault_leaderboard_ix,
    make_admin_activate_vault_ix,
    make_deactivate_local_legend_ix,
    make_elect_local_legend_ix,
    make_admin_backfill_vault_activation_ix,
    make_configure_usdc_payment_ix,
    make_configure_balance_vault_authority_ix,
    make_create_vault_ix,
    make_create_vault_with_usdc_ix,
    make_deposit_cal_from_balance_ix,
    make_restore_balance_vault_lp_custody_ix,
    make_restore_vault_lp_custody_ix,
    make_revoke_balance_vault_authority_ix,
    make_initialize_rider_balance_ix,
    make_initialize_rider_balance_token_ix,
    make_initialize_vault_position_lp_ix,
    make_set_rider_balance_status_ix,
    make_spl_transfer_checked_ix,
    make_stake_cal_in_vault_ix,
    make_unstake_cal_from_vault_ix,
    make_withdraw_cal_to_balance_ix,
    make_withdraw_to_wallet_ix,
    make_harvest_rewards_ix,
    make_collect_stake_rewards_for_ix,
    _derive_vault_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_activation_pda,
    _derive_vault_counter_pda,
    _derive_local_legend_pda,
    _derive_vault_stake_pda,
    _derive_vault_position_lp_pda,
    _derive_vault_lp_mint_pda,
    _derive_vault_cal_escrow_pda,
    _derive_program_config_pda,
    _derive_rider_balance_auth_pda,
    _derive_balance_vault_authority_pda,
    _derive_rider_balance_pda,
    _derive_rider_balance_token_pda,
    _derive_dung_mint_state_pda,
    _derive_dung_mint_auth_pda,
    _derive_ata,
)
from app.services.balance_vault_operation_authority import (
    BalanceVaultOperationKind,
    build_balance_vault_operation_authorization,
)
from app.services.vault_completion_evidence import build_vault_completion_evidence_hash

PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
SYS_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
AUTHORITY = Pubkey.from_string("3boUdoGfS1QMJ9pGQhZGNj8n7w1M3YDnL2a1tDk9K1aR")
USER = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
VAULT_ID = 42
ATTESTATION_HASH = hashlib.sha256(b"test_evidence").digest()
DUNG_MINT = Pubkey.from_string("CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk")
TREASURY = Pubkey.from_string("9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP")


class TestPdaDerivation:
    """Verify PDA seeds match Anchor seed constants."""

    def test_vault_pda_seeds(self):
        """Seeds: [b'vault', vault_id as le u64]."""
        pda, bump = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        # Verify by re-deriving manually
        expected, expected_bump = Pubkey.find_program_address(
            [b"vault", struct.pack("<Q", VAULT_ID)], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump

    def test_vault_leaderboard_pda_seeds(self):
        """Seeds: [b'vault_leaderboard', vault_id as le u64]."""
        pda, bump = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
        expected, expected_bump = Pubkey.find_program_address(
            [b"vault_leaderboard", struct.pack("<Q", VAULT_ID)], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump

    def test_vault_activation_pda_seeds(self):
        """Seeds: [b'vault_activation', vault_id as le u64]."""
        pda, bump = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        expected, expected_bump = Pubkey.find_program_address(
            [b"vault_activation", struct.pack("<Q", VAULT_ID)], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump

    def test_program_config_pda_seeds(self):
        """Seeds: [b'program_config']."""
        pda, bump = _derive_program_config_pda(PROGRAM_ID)
        expected, expected_bump = Pubkey.find_program_address(
            [b"program_config"], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump


class TestCanonicalEvidenceHash:
    """Verify canonical vault-completion evidence hash byte layout."""

    def test_canonical_format(self):
        """Replay and live callers must use the same domain-separated layout."""
        wallet = "3boUdoGfS1QMJ9pGQhZGNj8n7w1M3YDnL2a1tDk9K1aR"
        vault_id = 42
        sig_hex = "ab" * 64  # 128 hex chars = 64 bytes
        time_s = 1234

        expected = build_vault_completion_evidence_hash(
            wallet=wallet,
            vault_id=vault_id,
            activity_id="ride-123",
            completed_at=1_713_456_789,
            time_s=time_s,
            signature_hash=hashlib.sha256(bytes.fromhex(sig_hex)).digest(),
        )

        assert len(expected) == 32
        assert expected == build_vault_completion_evidence_hash(
            wallet=wallet,
            vault_id=vault_id,
            activity_id="ride-123",
            completed_at=1_713_456_789,
            time_s=time_s,
            signature_hash=hashlib.sha256(bytes.fromhex(sig_hex)).digest(),
        )

    def test_different_inputs_produce_different_hashes(self):
        """Changing any field must produce a different hash."""
        kwargs = {
            "wallet": USER,
            "vault_id": 42,
            "activity_id": "ride-123",
            "completed_at": 1_713_456_789,
            "time_s": 100,
            "signature_hash": hashlib.sha256(b"sig").digest(),
        }
        base_hash = build_vault_completion_evidence_hash(**kwargs)

        variants = [
            {**kwargs, "wallet": AUTHORITY},
            {**kwargs, "vault_id": 43},
            {**kwargs, "activity_id": "ride-124"},
            {**kwargs, "completed_at": 1_713_456_790},
            {**kwargs, "time_s": 101},
            {**kwargs, "signature_hash": hashlib.sha256(b"sig2").digest()},
        ]
        for variant in variants:
            assert build_vault_completion_evidence_hash(**variant) != base_hash


class TestAdminSeedVaultCompletionSummary:
    """Verify admin_seed_vault_completion_summary instruction builder."""

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:admin_seed_vault_completion_summary").digest()[:8]
        ix = make_admin_seed_vault_completion_summary_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            total_completions=100,
            best_time_s=3600,
            best_time_holder=USER,
            program_id=PROGRAM_ID,
        )
        assert ix.data[:8] == expected

    def test_data_layout(self):
        """Data: disc(8) + total_completions(u64,8) + best_time_s(u32,4) + holder(Pubkey,32) = 52."""
        ix = make_admin_seed_vault_completion_summary_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            total_completions=100,
            best_time_s=3600,
            best_time_holder=USER,
            program_id=PROGRAM_ID,
        )
        assert len(ix.data) == 52, f"Expected 52 bytes, got {len(ix.data)}"

        total = struct.unpack_from("<Q", ix.data, 8)[0]
        time_s = struct.unpack_from("<I", ix.data, 16)[0]
        holder = Pubkey.from_bytes(ix.data[20:52])

        assert total == 100
        assert time_s == 3600
        assert holder == USER

    def test_four_accounts(self):
        """AdminSeedVaultCompletionSummary: vault, vault_activation, program_config, authority."""
        ix = make_admin_seed_vault_completion_summary_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            total_completions=100,
            best_time_s=3600,
            best_time_holder=USER,
            program_id=PROGRAM_ID,
        )
        assert len(ix.accounts) == 4, f"Expected 4 accounts, got {len(ix.accounts)}"

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].pubkey == activation_pda
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[2].pubkey == config_pda
        assert ix.accounts[2].is_writable is False
        assert ix.accounts[3].pubkey == AUTHORITY
        assert ix.accounts[3].is_signer is True
        assert ix.accounts[3].is_writable is True


class TestHarvestRewardsInstruction:
    """Verify harvest_rewards builder matches the Anchor account layout."""

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:harvest_rewards").digest()[:8]
        ix = make_harvest_rewards_ix(
            staker=USER,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )
        assert ix.data == expected

    def test_account_order_matches_anchor(self):
        ix = make_harvest_rewards_ix(
            staker=USER,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, VAULT_ID, PROGRAM_ID)
        vault_activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        staker_dung_ata = _derive_ata(USER, DUNG_MINT)
        dung_mint_state_pda, _ = _derive_dung_mint_state_pda(PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        dung_mint_auth_pda, _ = _derive_dung_mint_auth_pda(PROGRAM_ID)

        assert len(ix.accounts) == 11
        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[1].pubkey == vault_stake_pda
        assert ix.accounts[2].pubkey == vault_activation_pda
        assert ix.accounts[3].pubkey == USER
        assert ix.accounts[4].pubkey == DUNG_MINT
        assert ix.accounts[5].pubkey == staker_dung_ata
        assert ix.accounts[6].pubkey == TREASURY
        assert ix.accounts[7].pubkey == dung_mint_state_pda
        assert ix.accounts[8].pubkey == config_pda
        assert ix.accounts[9].pubkey == dung_mint_auth_pda

    def test_signer_and_writable_flags(self):
        ix = make_harvest_rewards_ix(
            staker=USER,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[2].is_writable is False
        assert ix.accounts[3].is_signer is True
        assert ix.accounts[3].is_writable is True
        assert ix.accounts[4].is_writable is True
        assert ix.accounts[5].is_writable is True
        assert ix.accounts[6].is_writable is True
        assert ix.accounts[7].is_writable is True
        assert ix.accounts[8].is_writable is False
        assert ix.accounts[9].is_writable is False


class TestCollectStakeRewardsForInstruction:
    """Verify collect_stake_rewards_for matches the Anchor account layout."""

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:collect_stake_rewards_for").digest()[:8]
        ix = make_collect_stake_rewards_for_ix(
            staker=USER,
            payer=AUTHORITY,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )
        assert ix.data == expected

    def test_account_order_matches_anchor(self):
        ix = make_collect_stake_rewards_for_ix(
            staker=USER,
            payer=AUTHORITY,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, VAULT_ID, PROGRAM_ID)
        vault_activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        staker_dung_ata = _derive_ata(USER, DUNG_MINT)
        dung_mint_state_pda, _ = _derive_dung_mint_state_pda(PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        dung_mint_auth_pda, _ = _derive_dung_mint_auth_pda(PROGRAM_ID)

        assert len(ix.accounts) == 12
        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[1].pubkey == vault_stake_pda
        assert ix.accounts[2].pubkey == vault_activation_pda
        assert ix.accounts[3].pubkey == USER
        assert ix.accounts[4].pubkey == AUTHORITY
        assert ix.accounts[5].pubkey == DUNG_MINT
        assert ix.accounts[6].pubkey == staker_dung_ata
        assert ix.accounts[7].pubkey == TREASURY
        assert ix.accounts[8].pubkey == dung_mint_state_pda
        assert ix.accounts[9].pubkey == config_pda
        assert ix.accounts[10].pubkey == dung_mint_auth_pda
        assert ix.accounts[11].pubkey == TOKEN_PROGRAM

    def test_signer_and_writable_flags(self):
        ix = make_collect_stake_rewards_for_ix(
            staker=USER,
            payer=AUTHORITY,
            vault_id=VAULT_ID,
            protocol_treasury=TREASURY,
            dung_mint=DUNG_MINT,
            program_id=PROGRAM_ID,
        )
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[2].is_writable is False
        assert ix.accounts[3].is_signer is False
        assert ix.accounts[3].is_writable is False
        assert ix.accounts[4].is_signer is True
        assert ix.accounts[4].is_writable is True
        assert ix.accounts[5].is_writable is True
        assert ix.accounts[6].is_writable is True
        assert ix.accounts[7].is_writable is True
        assert ix.accounts[8].is_writable is True
        assert ix.accounts[9].is_writable is False
        assert ix.accounts[10].is_writable is False
        assert ix.accounts[11].is_writable is False


class TestAdminReplaceVaultLeaderboard:
    """Verify admin_replace_vault_leaderboard instruction builder."""

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:admin_replace_vault_leaderboard").digest()[:8]
        ix = make_admin_replace_vault_leaderboard_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            entries=[(USER, 3600, 1700000000)],
            program_id=PROGRAM_ID,
        )
        assert ix.data[:8] == expected

    def test_data_layout_single_entry(self):
        """Data: disc(8) + vec_len(u32,4) + N*(Pubkey(32)+time_s(u32,4)+recorded_at(i64,8))."""
        entries = [(USER, 3600, 1700000000)]
        ix = make_admin_replace_vault_leaderboard_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            entries=entries,
            program_id=PROGRAM_ID,
        )
        # 8 + 4 + 1*(32+4+8) = 56
        assert len(ix.data) == 56, f"Expected 56 bytes, got {len(ix.data)}"

        vec_len = struct.unpack_from("<I", ix.data, 8)[0]
        assert vec_len == 1

        user_pk = Pubkey.from_bytes(ix.data[12:44])
        time_s = struct.unpack_from("<I", ix.data, 44)[0]
        recorded_at = struct.unpack_from("<q", ix.data, 48)[0]

        assert user_pk == USER
        assert time_s == 3600
        assert recorded_at == 1700000000

    def test_data_layout_multiple_entries(self):
        """Verify correct serialization with 3 entries."""
        user2 = Pubkey.from_string("11111111111111111111111111111112")
        user3 = Pubkey.from_string("11111111111111111111111111111113")
        entries = [
            (USER, 3600, 1700000000),
            (user2, 3700, 1700000100),
            (user3, 3800, 1700000200),
        ]
        ix = make_admin_replace_vault_leaderboard_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            entries=entries,
            program_id=PROGRAM_ID,
        )
        # 8 + 4 + 3*(32+4+8) = 144
        assert len(ix.data) == 144, f"Expected 144 bytes, got {len(ix.data)}"
        vec_len = struct.unpack_from("<I", ix.data, 8)[0]
        assert vec_len == 3

    def test_six_accounts(self):
        """AdminReplaceVaultLeaderboard: vault, leaderboard, activation, config, authority, system."""
        ix = make_admin_replace_vault_leaderboard_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            entries=[(USER, 3600, 1700000000)],
            program_id=PROGRAM_ID,
        )
        assert len(ix.accounts) == 6, f"Expected 6 accounts, got {len(ix.accounts)}"

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        leaderboard_pda, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
        activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[1].pubkey == leaderboard_pda
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[2].pubkey == activation_pda
        assert ix.accounts[2].is_writable is True
        assert ix.accounts[3].pubkey == config_pda
        assert ix.accounts[3].is_writable is False
        assert ix.accounts[4].pubkey == AUTHORITY
        assert ix.accounts[4].is_signer is True
        assert ix.accounts[5].pubkey == SYS_PROGRAM


class TestAdminActivateVault:
    """Verify admin_activate_vault instruction builder."""

    def _build_ix(self):
        return make_admin_activate_vault_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            total_completions=100,
            kom_holder=USER,
            kom_time_s=3600,
            kom_recorded_at=1700000000,
            seed_generation=2,
            seed_cutoff_at=1700000000,
            matched_users=12,
            matched_completions=100,
            evidence_hash=ATTESTATION_HASH,
            program_id=PROGRAM_ID,
        )

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:admin_activate_vault").digest()[:8]
        ix = self._build_ix()
        assert ix.data[:8] == expected

    def test_data_layout(self):
        """Data: disc(8) + activation audit/finalization args (112) = 120."""
        ix = self._build_ix()
        assert len(ix.data) == 120, f"Expected 120 bytes, got {len(ix.data)}"

        vault_id = struct.unpack_from("<Q", ix.data, 8)[0]
        total = struct.unpack_from("<Q", ix.data, 16)[0]
        holder = Pubkey.from_bytes(ix.data[24:56])
        kom_time_s = struct.unpack_from("<I", ix.data, 56)[0]
        kom_recorded_at = struct.unpack_from("<q", ix.data, 60)[0]
        seed_generation = struct.unpack_from("<I", ix.data, 68)[0]
        seed_cutoff_at = struct.unpack_from("<q", ix.data, 72)[0]
        matched_users = struct.unpack_from("<I", ix.data, 80)[0]
        matched_completions = struct.unpack_from("<I", ix.data, 84)[0]
        evidence_hash = ix.data[88:120]

        assert vault_id == VAULT_ID
        assert total == 100
        assert holder == USER
        assert kom_time_s == 3600
        assert kom_recorded_at == 1700000000
        assert seed_generation == 2
        assert seed_cutoff_at == 1700000000
        assert matched_users == 12
        assert matched_completions == 100
        assert evidence_hash == ATTESTATION_HASH

    def test_four_accounts(self):
        """AdminActivateVault: vault, vault_activation, program_config, authority."""
        ix = self._build_ix()
        assert len(ix.accounts) == 4, f"Expected 4 accounts, got {len(ix.accounts)}"

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].pubkey == activation_pda
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[2].pubkey == config_pda
        assert ix.accounts[2].is_writable is False
        assert ix.accounts[3].pubkey == AUTHORITY
        assert ix.accounts[3].is_signer is True
        assert ix.accounts[3].is_writable is True


class TestAdminBackfillVaultActivation:
    """Verify admin_backfill_vault_activation instruction builder."""

    def test_discriminator(self):
        expected = hashlib.sha256(b"global:admin_backfill_vault_activation").digest()[:8]
        ix = make_admin_backfill_vault_activation_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            program_id=PROGRAM_ID,
        )
        assert ix.data[:8] == expected

    def test_data_layout_vault_id_arg(self):
        """admin_backfill_vault_activation takes vault_id (u64) — 16 bytes total."""
        ix = make_admin_backfill_vault_activation_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            program_id=PROGRAM_ID,
        )
        assert len(ix.data) == 16, f"Expected 16 bytes, got {len(ix.data)}"
        vault_id_bytes = struct.unpack("<Q", ix.data[8:16])[0]
        assert vault_id_bytes == VAULT_ID

    def test_five_accounts(self):
        """AdminBackfillVaultActivation: vault, vault_activation (init), program_config, authority, system_program."""
        ix = make_admin_backfill_vault_activation_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            program_id=PROGRAM_ID,
        )
        assert len(ix.accounts) == 5, f"Expected 5 accounts, got {len(ix.accounts)}"

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        # [0] vault (read-only)
        assert ix.accounts[0].pubkey == vault_pda
        assert ix.accounts[0].is_writable is False
        # [1] vault_activation (init → writable)
        assert ix.accounts[1].pubkey == activation_pda
        assert ix.accounts[1].is_writable is True
        # [2] program_config (read-only)
        assert ix.accounts[2].pubkey == config_pda
        assert ix.accounts[2].is_writable is False
        # [3] authority (signer + payer → writable)
        assert ix.accounts[3].pubkey == AUTHORITY
        assert ix.accounts[3].is_signer is True
        assert ix.accounts[3].is_writable is True
        # [4] system_program
        assert ix.accounts[4].pubkey == SYS_PROGRAM
        assert ix.accounts[4].is_signer is False
        assert ix.accounts[4].is_writable is False


class TestLocalLegendElectionInstructions:
    """Verify Local Legend election instruction builders."""

    def test_elect_local_legend_layout(self):
        expected = hashlib.sha256(b"global:elect_local_legend").digest()[:8]
        runner_up = TREASURY
        ix = make_elect_local_legend_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            winner=USER,
            winner_completions=7,
            runner_up=runner_up,
            runner_up_completions=3,
            term_start_epoch=18,
            program_id=PROGRAM_ID,
        )

        assert ix.data[:8] == expected
        assert struct.unpack_from("<I", ix.data, 8)[0] == 7
        assert ix.data[12:44] == bytes(runner_up)
        assert struct.unpack_from("<I", ix.data, 44)[0] == 3
        assert struct.unpack_from("<Q", ix.data, 48)[0] == 18
        assert len(ix.data) == 56

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        legend_pda, _ = _derive_local_legend_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        assert [account.pubkey for account in ix.accounts] == [
            vault_pda,
            legend_pda,
            USER,
            config_pda,
            AUTHORITY,
            SYS_PROGRAM,
        ]
        assert ix.accounts[0].is_writable is False
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[4].is_signer is True

    def test_deactivate_local_legend_layout(self):
        expected = hashlib.sha256(b"global:deactivate_local_legend").digest()[:8]
        ix = make_deactivate_local_legend_ix(
            authority=AUTHORITY,
            vault_id=VAULT_ID,
            term_start_epoch=18,
            program_id=PROGRAM_ID,
        )

        assert ix.data == expected + struct.pack("<Q", 18)

        vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
        legend_pda, _ = _derive_local_legend_pda(VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        assert [account.pubkey for account in ix.accounts] == [
            vault_pda,
            legend_pda,
            config_pda,
            AUTHORITY,
        ]
        assert ix.accounts[0].is_writable is False
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[3].is_signer is True


# --- Vault creation instruction builders ---

# Shared test fixtures for vault creation tests
VAULT_COUNTER_PDA, _ = _derive_vault_counter_pda(PROGRAM_ID)
NEXT_VAULT_ID = 7  # simulated next vault ID from counter
VAULT_PDA, _ = _derive_vault_pda(NEXT_VAULT_ID, PROGRAM_ID)
LOCAL_LEGEND_PDA, _ = _derive_local_legend_pda(NEXT_VAULT_ID, PROGRAM_ID)
VAULT_ACTIVATION_PDA, _ = _derive_vault_activation_pda(NEXT_VAULT_ID, PROGRAM_ID)
TEST_SIGNATURE = bytes(range(64))  # deterministic 64-byte signature
TEST_NAME = "Test Climb"
TEST_VERT_M = 1560  # 156m * 10
TEST_DISTANCE_M = 3200
TEST_AVG_GRADIENT = 840  # 8.4% * 100
TEST_STAKE_AMOUNT = 5_000_000_000
OPERATION_AUTHORITY = TREASURY
OPERATION_GENERATION = 3
OPERATION_NONCE = 7
OPERATION_EXPIRES_AT = 1_800_000_000
BALANCE_VAULT_POLICY_HASH = hashlib.sha256(b"br:test:balance-vault-policy").digest()

TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSVAR_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
DUNG_MINT = Pubkey.from_string("AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn")
CAL_MINT = Pubkey.from_string("4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh")
USDC_MINT = Pubkey.from_string("Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr")
VAULT_CREATION_USDC = 2_000_000
CREATOR_DUNG_ATA = Pubkey.from_string("Ag6YsS8GTTDYF2DUWuet1SBu3ZcoThjK8Dym7BoWdZfx")
CREATOR_CAL_ATA = Pubkey.from_string("2cGfPzq3GX7VEAqRZkLGG27Cb4wBV4VQfQDvWopA8s5P")
CREATOR_USDC_ATA = Pubkey.from_string("C6VyKQvJd8FrdT5s3Sse2j4HuPMLp7tNTcL3yp7Di3xx")
PROTOCOL_USDC_ATA = Pubkey.from_string("BR6wS9qSxd4nBVmA2juZ4bY2mZ3oY1oXJupvcvRMLm9r")
CLIMB_PDA = Pubkey.new_unique()
VAULT_LEADERBOARD_PDA, _ = _derive_vault_leaderboard_pda(
    NEXT_VAULT_ID,
    PROGRAM_ID,
)
VAULT_LP_MINT_PDA, _ = _derive_vault_lp_mint_pda(NEXT_VAULT_ID, PROGRAM_ID)
VAULT_CAL_ESCROW_PDA, _ = _derive_vault_cal_escrow_pda(NEXT_VAULT_ID, PROGRAM_ID)
VAULT_POSITION_LP_PDA, _ = _derive_vault_position_lp_pda(
    USER,
    NEXT_VAULT_ID,
    PROGRAM_ID,
)
STAKER_VAULT_LP_ATA = _derive_ata(USER, VAULT_LP_MINT_PDA)
STAKER_CAL_ATA = _derive_ata(USER, CAL_MINT)
RIDER_BALANCE_PDA, _ = _derive_rider_balance_pda(USER, PROGRAM_ID)
RIDER_BALANCE_AUTH_PDA, _ = _derive_rider_balance_auth_pda(USER, PROGRAM_ID)
BALANCE_VAULT_AUTHORITY_PDA, _ = _derive_balance_vault_authority_pda(USER, PROGRAM_ID)
RIDER_BALANCE_CAL_TOKEN_PDA, _ = _derive_rider_balance_token_pda(
    USER,
    CAL_MINT,
    PROGRAM_ID,
)
RIDER_BALANCE_LP_TOKEN_PDA, _ = _derive_rider_balance_token_pda(
    USER,
    VAULT_LP_MINT_PDA,
    PROGRAM_ID,
)
RIDER_BALANCE_USDC_TOKEN_PDA, _ = _derive_rider_balance_token_pda(
    USER,
    USDC_MINT,
    PROGRAM_ID,
)
RIDER_BALANCE_DUNG_TOKEN_PDA, _ = _derive_rider_balance_token_pda(
    USER,
    DUNG_MINT,
    PROGRAM_ID,
)


def _operation_authorization(
    kind: BalanceVaultOperationKind,
    primary_amount: int,
    secondary_amount: int = 0,
):
    return build_balance_vault_operation_authorization(
        program_id=PROGRAM_ID,
        rider=USER,
        operation_authority=OPERATION_AUTHORITY,
        kind=kind,
        vault_id=NEXT_VAULT_ID,
        primary_amount=primary_amount,
        secondary_amount=secondary_amount,
        generation=OPERATION_GENERATION,
        nonce=OPERATION_NONCE,
        expires_at=OPERATION_EXPIRES_AT,
    )


def _build_create_vault_ix():
    """Helper to build a CreateVault (DUNG burn) instruction with standard params."""
    return make_create_vault_ix(
        sponsor_authority=AUTHORITY,
        creator=AUTHORITY,
        creator_dung_account=CREATOR_DUNG_ATA,
        dung_mint=DUNG_MINT,
        vault_counter_pda=VAULT_COUNTER_PDA,
        vault_pda=VAULT_PDA,
        climb_pda=CLIMB_PDA,
        vault_leaderboard_pda=VAULT_LEADERBOARD_PDA,
        local_legend_pda=LOCAL_LEGEND_PDA,
        vault_activation_pda=VAULT_ACTIVATION_PDA,
        program_id=PROGRAM_ID,
    )


def _build_create_vault_with_usdc_ix():
    """Helper to build a CreateVaultWithUsdc instruction with standard params."""
    return make_create_vault_with_usdc_ix(
        sponsor_authority=AUTHORITY,
        creator=USER,
        creator_cal_account=CREATOR_CAL_ATA,
        cal_mint=CAL_MINT,
        creator_usdc_account=CREATOR_USDC_ATA,
        protocol_usdc_account=PROTOCOL_USDC_ATA,
        vault_counter_pda=VAULT_COUNTER_PDA,
        vault_pda=VAULT_PDA,
        climb_pda=CLIMB_PDA,
        vault_leaderboard_pda=VAULT_LEADERBOARD_PDA,
        local_legend_pda=LOCAL_LEGEND_PDA,
        vault_activation_pda=VAULT_ACTIVATION_PDA,
        program_id=PROGRAM_ID,
    )


def _build_stake_ix():
    """Helper to build a sponsored StakeCalInVault instruction with standard params."""
    return make_stake_cal_in_vault_ix(
        sponsor_authority=AUTHORITY,
        staker=USER,
        vault_id=NEXT_VAULT_ID,
        amount=TEST_STAKE_AMOUNT,
        cal_mint=CAL_MINT,
        program_id=PROGRAM_ID,
    )


def _build_unstake_ix():
    return make_unstake_cal_from_vault_ix(
        staker=USER,
        vault_id=NEXT_VAULT_ID,
        lp_amount=TEST_STAKE_AMOUNT,
        cal_mint=CAL_MINT,
        program_id=PROGRAM_ID,
    )


def _build_deposit_cal_from_balance_ix():
    return make_deposit_cal_from_balance_ix(
        sponsor_authority=AUTHORITY,
        rider=USER,
        operation_authority=OPERATION_AUTHORITY,
        vault_id=NEXT_VAULT_ID,
        amount=TEST_STAKE_AMOUNT,
        authorization=_operation_authorization(
            BalanceVaultOperationKind.DEPOSIT_CAL,
            TEST_STAKE_AMOUNT,
        ),
        cal_mint=CAL_MINT,
        program_id=PROGRAM_ID,
    )


def _build_withdraw_cal_to_balance_ix():
    return make_withdraw_cal_to_balance_ix(
        rider=USER,
        operation_authority=OPERATION_AUTHORITY,
        vault_id=NEXT_VAULT_ID,
        lp_amount=TEST_STAKE_AMOUNT,
        authorization=_operation_authorization(
            BalanceVaultOperationKind.WITHDRAW_CAL,
            TEST_STAKE_AMOUNT,
        ),
        cal_mint=CAL_MINT,
        program_id=PROGRAM_ID,
    )


class TestVaultCreationPdaSeeds:
    """Verify the PDA seeds every vault creation path derives."""

    def test_pda_seeds_local_legend(self):
        """LocalLegend PDA seeds: [b'local_legend', vault_id as le u64]."""
        pda, bump = _derive_local_legend_pda(NEXT_VAULT_ID, PROGRAM_ID)
        expected, expected_bump = Pubkey.find_program_address(
            [b"local_legend", struct.pack("<Q", NEXT_VAULT_ID)], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump

    def test_pda_seeds_vault_counter(self):
        """VaultCounter PDA seeds: [b'vault_counter']."""
        pda, bump = _derive_vault_counter_pda(PROGRAM_ID)
        expected, expected_bump = Pubkey.find_program_address(
            [b"vault_counter"], PROGRAM_ID
        )
        assert pda == expected
        assert bump == expected_bump


class TestCreateVault:
    """Verify create_vault (DUNG burn) instruction matches Anchor CreateVault struct."""

    def test_discriminator(self):
        """Anchor discriminator = SHA256('global:create_vault')[:8]."""
        expected = hashlib.sha256(b"global:create_vault").digest()[:8]
        ix = _build_create_vault_ix()
        assert ix.data[:8] == expected

    def test_data_layout(self):
        """The DUNG constructor has no client identity arguments."""
        ix = _build_create_vault_ix()
        assert len(ix.data) == 8

    def test_fourteen_accounts(self):
        """CreateVault includes the mutable DUNG burn-accounting state."""
        ix = _build_create_vault_ix()
        assert len(ix.accounts) == 14

    def test_account_order_matches_anchor(self):
        """Account order must match Anchor CreateVault struct field order exactly."""
        ix = _build_create_vault_ix()
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        dung_mint_state_pda, _ = _derive_dung_mint_state_pda(PROGRAM_ID)

        assert ix.accounts[0].pubkey == VAULT_COUNTER_PDA, "accounts[0] should be vault_counter"
        assert ix.accounts[1].pubkey == VAULT_PDA, "accounts[1] should be vault"
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_COUNTER_PDA,
            VAULT_PDA,
            CLIMB_PDA,
            VAULT_LEADERBOARD_PDA,
            LOCAL_LEGEND_PDA,
            VAULT_ACTIVATION_PDA,
            AUTHORITY,
            AUTHORITY,
            dung_mint_state_pda,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
            config_pda,
            DUNG_MINT,
            CREATOR_DUNG_ATA,
        ]

    def test_account_mutability_flags(self):
        """Verify writable/signer flags match Anchor constraints."""
        ix = _build_create_vault_ix()

        # vault_counter: mut, not signer
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[0].is_signer is False
        # vault: init (writable), not signer
        assert ix.accounts[1].is_writable is True
        assert ix.accounts[1].is_signer is False
        assert all(ix.accounts[index].is_writable for index in range(0, 9))
        assert ix.accounts[6].is_signer is True
        assert ix.accounts[7].is_signer is True
        assert ix.accounts[9].is_writable is False
        assert ix.accounts[10].is_writable is False
        assert ix.accounts[11].is_writable is False
        assert ix.accounts[12].is_writable is True
        assert ix.accounts[13].is_writable is True


class TestCreateVaultWithUsdc:
    """Verify create_vault_with_usdc instruction matches Anchor CreateVaultWithUsdc."""

    def test_fifteen_accounts(self):
        ix = _build_create_vault_with_usdc_ix()
        assert len(ix.accounts) == 15

    def test_account_order_matches_anchor(self):
        ix = _build_create_vault_with_usdc_ix()
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert ix.accounts[0].pubkey == VAULT_COUNTER_PDA
        assert ix.accounts[1].pubkey == VAULT_PDA
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_COUNTER_PDA,
            VAULT_PDA,
            CLIMB_PDA,
            VAULT_LEADERBOARD_PDA,
            LOCAL_LEGEND_PDA,
            VAULT_ACTIVATION_PDA,
            AUTHORITY,
            USER,
            CREATOR_CAL_ATA,
            PROTOCOL_USDC_ATA,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
            CAL_MINT,
            config_pda,
            CREATOR_USDC_ATA,
        ]


class TestConfigureUsdcPayment:
    """Verify canonical USDC config builder matches Anchor ConfigureUsdcPayment."""

    def test_data_and_account_order(self):
        ix = make_configure_usdc_payment_ix(
            admin=AUTHORITY,
            usdc_mint=USDC_MINT,
            usdc_treasury_token_account=PROTOCOL_USDC_ATA,
            vault_creation_usdc=VAULT_CREATION_USDC,
            program_id=PROGRAM_ID,
        )
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert ix.data == (
            hashlib.sha256(b"global:configure_usdc_payment").digest()[:8]
            + struct.pack("<Q", VAULT_CREATION_USDC)
        )
        assert [account.pubkey for account in ix.accounts] == [
            config_pda,
            AUTHORITY,
            USDC_MINT,
            PROTOCOL_USDC_ATA,
        ]
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].is_signer is True
        assert ix.accounts[1].is_writable is False

    def test_rejects_zero_amount_client_side(self):
        with pytest.raises(ValueError):
            make_configure_usdc_payment_ix(
                admin=AUTHORITY,
                usdc_mint=USDC_MINT,
                usdc_treasury_token_account=PROTOCOL_USDC_ATA,
                vault_creation_usdc=0,
                program_id=PROGRAM_ID,
            )


class TestRiderBalanceBuilders:
    """Verify Boulder Roller Balance app-balance builders match Anchor layouts."""

    def test_rider_balance_pda_seeds(self):
        expected, bump = Pubkey.find_program_address(
            [b"rider_balance", bytes(USER)],
            PROGRAM_ID,
        )
        assert RIDER_BALANCE_PDA == expected
        assert _derive_rider_balance_pda(USER, PROGRAM_ID)[1] == bump

        expected_auth, auth_bump = Pubkey.find_program_address(
            [b"rider_balance_auth", bytes(USER)],
            PROGRAM_ID,
        )
        assert RIDER_BALANCE_AUTH_PDA == expected_auth
        assert _derive_rider_balance_auth_pda(USER, PROGRAM_ID)[1] == auth_bump

        expected_session, session_bump = Pubkey.find_program_address(
            [b"balance_vault_auth", bytes(USER)],
            PROGRAM_ID,
        )
        assert BALANCE_VAULT_AUTHORITY_PDA == expected_session
        assert _derive_balance_vault_authority_pda(USER, PROGRAM_ID)[1] == session_bump

        expected_token, token_bump = Pubkey.find_program_address(
            [b"rider_balance_token", bytes(USER), bytes(CAL_MINT)],
            PROGRAM_ID,
        )
        assert RIDER_BALANCE_CAL_TOKEN_PDA == expected_token
        assert _derive_rider_balance_token_pda(USER, CAL_MINT, PROGRAM_ID)[1] == token_bump

    def test_initialize_rider_balance_account_order(self):
        ix = make_initialize_rider_balance_ix(
            payer=AUTHORITY,
            rider=USER,
            program_id=PROGRAM_ID,
        )
        assert ix.data == hashlib.sha256(b"global:initialize_rider_balance").digest()[:8]
        assert [account.pubkey for account in ix.accounts] == [
            RIDER_BALANCE_PDA,
            USER,
            AUTHORITY,
            SYS_PROGRAM,
        ]
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[1].is_signer is False
        assert ix.accounts[2].is_signer is True
        assert ix.accounts[2].is_writable is True

    def test_initialize_rider_balance_token_account_order(self):
        ix = make_initialize_rider_balance_token_ix(
            payer=AUTHORITY,
            rider=USER,
            mint=CAL_MINT,
            program_id=PROGRAM_ID,
        )
        assert ix.data == hashlib.sha256(b"global:initialize_rider_balance_token").digest()[:8]
        assert [account.pubkey for account in ix.accounts] == [
            RIDER_BALANCE_PDA,
            USER,
            RIDER_BALANCE_AUTH_PDA,
            RIDER_BALANCE_CAL_TOKEN_PDA,
            CAL_MINT,
            AUTHORITY,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
            SYSVAR_RENT,
        ]
        assert ix.accounts[3].is_writable is True
        assert ix.accounts[5].is_signer is True
        assert ix.accounts[5].is_writable is True

    def test_configure_and_revoke_balance_vault_authority_layouts(self):
        configure = make_configure_balance_vault_authority_ix(
            sponsor_authority=AUTHORITY,
            rider=USER,
            operation_authority=OPERATION_AUTHORITY,
            policy_hash=BALANCE_VAULT_POLICY_HASH,
            expires_at=OPERATION_EXPIRES_AT,
            program_id=PROGRAM_ID,
        )
        revoke = make_revoke_balance_vault_authority_ix(
            rider=USER,
            program_id=PROGRAM_ID,
        )

        assert configure.data == (
            hashlib.sha256(b"global:configure_balance_vault_authority").digest()[:8]
            + bytes(OPERATION_AUTHORITY)
            + BALANCE_VAULT_POLICY_HASH
            + struct.pack("<q", OPERATION_EXPIRES_AT)
        )
        assert [account.pubkey for account in configure.accounts] == [
            RIDER_BALANCE_PDA,
            USER,
            BALANCE_VAULT_AUTHORITY_PDA,
            AUTHORITY,
            SYS_PROGRAM,
        ]
        assert configure.accounts[1].is_signer is True
        assert configure.accounts[2].is_writable is True
        assert configure.accounts[3].is_signer is True
        assert revoke.data == hashlib.sha256(
            b"global:revoke_balance_vault_authority"
        ).digest()[:8]
        assert [account.pubkey for account in revoke.accounts] == [
            RIDER_BALANCE_PDA,
            USER,
            BALANCE_VAULT_AUTHORITY_PDA,
        ]
        assert revoke.accounts[1].is_signer is True

    def test_add_funds_transfer_checked_account_order(self):
        ix = make_spl_transfer_checked_ix(
            source=STAKER_CAL_ATA,
            mint=CAL_MINT,
            destination=RIDER_BALANCE_CAL_TOKEN_PDA,
            owner=USER,
            amount=250_000_000,
            decimals=9,
        )

        assert ix.program_id == TOKEN_PROGRAM
        assert ix.data == b"\x0c" + struct.pack("<Q", 250_000_000) + b"\x09"
        assert [account.pubkey for account in ix.accounts] == [
            STAKER_CAL_ATA,
            CAL_MINT,
            RIDER_BALANCE_CAL_TOKEN_PDA,
            USER,
        ]
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[2].is_writable is True
        assert ix.accounts[3].is_signer is True

    def test_withdraw_to_wallet_account_order(self):
        ix = make_withdraw_to_wallet_ix(
            rider=USER,
            mint=DUNG_MINT,
            amount=125_000_000,
            program_id=PROGRAM_ID,
        )
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        rider_dung_ata = _derive_ata(USER, DUNG_MINT)

        assert ix.data[:8] == hashlib.sha256(b"global:withdraw_to_wallet").digest()[:8]
        assert struct.unpack_from("<Q", ix.data, 8)[0] == 125_000_000
        assert [account.pubkey for account in ix.accounts] == [
            RIDER_BALANCE_PDA,
            USER,
            RIDER_BALANCE_AUTH_PDA,
            config_pda,
            RIDER_BALANCE_DUNG_TOKEN_PDA,
            rider_dung_ata,
            DUNG_MINT,
            TOKEN_PROGRAM,
        ]
        assert ix.accounts[1].is_signer is True
        assert ix.accounts[4].is_writable is True
        assert ix.accounts[5].is_writable is True

    def test_set_rider_balance_status_serializes_enum_variant(self):
        ix = make_set_rider_balance_status_ix(
            admin=AUTHORITY,
            rider=USER,
            status=3,
            program_id=PROGRAM_ID,
        )
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        assert ix.data == hashlib.sha256(b"global:set_rider_balance_status").digest()[:8] + b"\x03"
        assert [account.pubkey for account in ix.accounts] == [
            RIDER_BALANCE_PDA,
            config_pda,
            AUTHORITY,
        ]
        assert ix.accounts[0].is_writable is True
        assert ix.accounts[2].is_signer is True
        assert ix.accounts[2].is_writable is False

        with pytest.raises(ValueError):
            make_set_rider_balance_status_ix(
                admin=AUTHORITY,
                rider=USER,
                status=4,
                program_id=PROGRAM_ID,
            )

    def test_deposit_cal_from_balance_account_order(self):
        ix = _build_deposit_cal_from_balance_ix()
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.data[:8] == hashlib.sha256(b"global:deposit_cal_from_balance").digest()[:8]
        assert struct.unpack_from("<Q", ix.data, 8)[0] == TEST_STAKE_AMOUNT
        assert ix.data[16:] == _operation_authorization(
            BalanceVaultOperationKind.DEPOSIT_CAL,
            TEST_STAKE_AMOUNT,
        ).encode()
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            vault_stake_pda,
            VAULT_ACTIVATION_PDA,
            USER,
            RIDER_BALANCE_PDA,
            RIDER_BALANCE_AUTH_PDA,
            BALANCE_VAULT_AUTHORITY_PDA,
            OPERATION_AUTHORITY,
            AUTHORITY,
            config_pda,
            RIDER_BALANCE_CAL_TOKEN_PDA,
            VAULT_CAL_ESCROW_PDA,
            VAULT_LP_MINT_PDA,
            VAULT_POSITION_LP_PDA,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
        ]
        assert len(ix.accounts) == 16
        assert ix.accounts[3].is_signer is False
        assert ix.accounts[6].is_writable is True
        assert ix.accounts[7].is_signer is True
        assert ix.accounts[7].is_writable is False
        assert ix.accounts[8].is_signer is True
        assert ix.accounts[8].is_writable is True
        assert ix.accounts[10].is_writable is True
        assert ix.accounts[13].is_writable is True

    def test_withdraw_cal_to_balance_account_order(self):
        ix = _build_withdraw_cal_to_balance_ix()
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.data[:8] == hashlib.sha256(b"global:withdraw_cal_to_balance").digest()[:8]
        assert struct.unpack_from("<Q", ix.data, 8)[0] == TEST_STAKE_AMOUNT
        assert ix.data[16:] == _operation_authorization(
            BalanceVaultOperationKind.WITHDRAW_CAL,
            TEST_STAKE_AMOUNT,
        ).encode()
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            vault_stake_pda,
            VAULT_ACTIVATION_PDA,
            USER,
            RIDER_BALANCE_PDA,
            RIDER_BALANCE_AUTH_PDA,
            BALANCE_VAULT_AUTHORITY_PDA,
            OPERATION_AUTHORITY,
            config_pda,
            RIDER_BALANCE_CAL_TOKEN_PDA,
            VAULT_CAL_ESCROW_PDA,
            CAL_MINT,
            VAULT_LP_MINT_PDA,
            VAULT_POSITION_LP_PDA,
            TOKEN_PROGRAM,
        ]
        assert len(ix.accounts) == 15
        assert ix.accounts[3].is_signer is False
        assert ix.accounts[6].is_writable is True
        assert ix.accounts[7].is_signer is True
        assert ix.accounts[7].is_writable is False
        assert ix.accounts[9].is_writable is True
        assert ix.accounts[13].is_writable is True


class TestInitializeVaultPositionLp:
    def test_account_order_matches_anchor(self):
        ix = make_initialize_vault_position_lp_ix(
            sponsor_authority=AUTHORITY,
            rider=USER,
            vault_id=NEXT_VAULT_ID,
            program_id=PROGRAM_ID,
        )
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.data == hashlib.sha256(
            b"global:initialize_vault_position_lp"
        ).digest()[:8]
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            USER,
            vault_stake_pda,
            VAULT_LP_MINT_PDA,
            VAULT_POSITION_LP_PDA,
            AUTHORITY,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
        ]
        assert ix.accounts[5].is_signer is True
        assert ix.accounts[4].is_writable is True


class TestStakeCalInVault:
    """Verify sponsored stake instruction matches Anchor StakeCalInVault."""

    def test_data_layout(self):
        ix = _build_stake_ix()
        expected = hashlib.sha256(b"global:stake_cal_in_vault").digest()[:8]
        assert ix.data[:8] == expected
        assert struct.unpack_from("<Q", ix.data, 8)[0] == TEST_STAKE_AMOUNT

    def test_twelve_accounts(self):
        ix = _build_stake_ix()
        assert len(ix.accounts) == 12, f"Expected 12 accounts, got {len(ix.accounts)}"

    def test_account_order_matches_anchor(self):
        ix = _build_stake_ix()
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.accounts[0].pubkey == VAULT_PDA
        assert ix.accounts[1].pubkey == vault_stake_pda
        assert ix.accounts[2].pubkey == VAULT_ACTIVATION_PDA
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)
        assert ix.accounts[3].pubkey == config_pda
        assert ix.accounts[4].pubkey == AUTHORITY
        assert ix.accounts[5].pubkey == USER
        assert ix.accounts[6].pubkey == STAKER_CAL_ATA
        assert ix.accounts[7].pubkey == VAULT_CAL_ESCROW_PDA
        assert ix.accounts[8].pubkey == VAULT_LP_MINT_PDA
        assert ix.accounts[9].pubkey == VAULT_POSITION_LP_PDA
        assert ix.accounts[10].pubkey == TOKEN_PROGRAM
        assert ix.accounts[11].pubkey == SYS_PROGRAM


class TestUnstakeCalFromVault:
    def test_account_order_matches_anchor(self):
        ix = _build_unstake_ix()
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)
        config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

        assert len(ix.accounts) == 11
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            vault_stake_pda,
            VAULT_ACTIVATION_PDA,
            config_pda,
            USER,
            STAKER_CAL_ATA,
            VAULT_CAL_ESCROW_PDA,
            CAL_MINT,
            VAULT_LP_MINT_PDA,
            VAULT_POSITION_LP_PDA,
            TOKEN_PROGRAM,
        ]


class TestRestoreVaultLpCustody:
    def test_wallet_source_account_order_matches_anchor(self):
        ix = make_restore_vault_lp_custody_ix(
            sponsor_authority=AUTHORITY,
            rider=USER,
            source_authority=USER,
            source_lp_account=STAKER_VAULT_LP_ATA,
            vault_id=NEXT_VAULT_ID,
            amount=TEST_STAKE_AMOUNT,
            program_id=PROGRAM_ID,
        )
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.data[:8] == hashlib.sha256(
            b"global:restore_vault_lp_custody"
        ).digest()[:8]
        assert struct.unpack_from("<Q", ix.data, 8)[0] == TEST_STAKE_AMOUNT
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            vault_stake_pda,
            USER,
            VAULT_LP_MINT_PDA,
            USER,
            STAKER_VAULT_LP_ATA,
            VAULT_POSITION_LP_PDA,
            AUTHORITY,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
        ]
        assert ix.accounts[4].is_signer is True
        assert ix.accounts[7].is_signer is True

    def test_balance_source_account_order_matches_anchor(self):
        ix = make_restore_balance_vault_lp_custody_ix(
            sponsor_authority=AUTHORITY,
            rider=USER,
            vault_id=NEXT_VAULT_ID,
            amount=TEST_STAKE_AMOUNT,
            program_id=PROGRAM_ID,
        )
        vault_stake_pda, _ = _derive_vault_stake_pda(USER, NEXT_VAULT_ID, PROGRAM_ID)

        assert ix.data[:8] == hashlib.sha256(
            b"global:restore_balance_vault_lp_custody"
        ).digest()[:8]
        assert struct.unpack_from("<Q", ix.data, 8)[0] == TEST_STAKE_AMOUNT
        assert [account.pubkey for account in ix.accounts] == [
            VAULT_PDA,
            vault_stake_pda,
            USER,
            RIDER_BALANCE_AUTH_PDA,
            VAULT_LP_MINT_PDA,
            RIDER_BALANCE_LP_TOKEN_PDA,
            VAULT_POSITION_LP_PDA,
            AUTHORITY,
            TOKEN_PROGRAM,
            SYS_PROGRAM,
        ]
        assert ix.accounts[7].is_signer is True
        assert sum(account.is_signer for account in ix.accounts) == 1

    @pytest.mark.parametrize(
        "builder",
        [make_restore_vault_lp_custody_ix, make_restore_balance_vault_lp_custody_ix],
    )
    def test_rejects_zero_amount(self, builder):
        kwargs = {
            "sponsor_authority": AUTHORITY,
            "rider": USER,
            "vault_id": NEXT_VAULT_ID,
            "amount": 0,
            "program_id": PROGRAM_ID,
        }
        if builder is make_restore_vault_lp_custody_ix:
            kwargs.update(
                source_authority=USER,
                source_lp_account=STAKER_VAULT_LP_ATA,
            )
        with pytest.raises(ValueError, match="amount must be positive"):
            builder(**kwargs)
