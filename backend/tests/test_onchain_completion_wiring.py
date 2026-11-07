"""Tests for on-chain vault completion wiring in ride_processor.

Validates authority separation, activation gating, canonical evidence hashing,
and receipt-backed completion ordering.
"""

import hashlib
import inspect
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    DirectConfig,
    resolve_backend_authority,
    _unique_signers,
)
from app.services import ride_economic_plan_builder
from app.services.climb_economy_processor import (
    ClimbEconomyProcessor,
    is_vault_live_for_completion,
)
from app.services.vault_completion_evidence import build_vault_completion_evidence_hash


# =========================================================================
# Fixtures
# =========================================================================

PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
PAYER = Keypair()
BACKEND_AUTHORITY = Keypair()

USER_WALLET = "Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"
VAULT_ID = 42
COMPLETION_TIME_S = 600
COMPLETED_AT = 1_713_456_789
SIG_HEX = "ab" * 64  # 128 hex chars = 64 bytes


def make_config(separate_authority: bool = False) -> DirectConfig:
    """Build a DirectConfig with optional separate backend authority."""
    return DirectConfig(
        rpc_url="https://api.devnet.solana.com",
        program_id=PROGRAM_ID,
        payer=PAYER,
        backend_authority=BACKEND_AUTHORITY if separate_authority else None,
    )


# =========================================================================
# Test: Authority signer fix
# =========================================================================


class TestAuthoritySigner:
    """Verify separated backend-authority signer resolution."""

    def test_resolve_with_separate_authority(self):
        """When backend_authority is set, resolve returns it."""
        config = make_config(separate_authority=True)
        resolved = resolve_backend_authority(config)
        assert resolved.pubkey() == BACKEND_AUTHORITY.pubkey()

    def test_resolve_fallback_to_payer(self):
        """When backend_authority is None, resolve returns payer."""
        config = make_config(separate_authority=False)
        resolved = resolve_backend_authority(config)
        assert resolved.pubkey() == PAYER.pubkey()

    def test_unique_signers_deduplicates(self):
        """When payer == authority, only one signer in list."""
        config = make_config(separate_authority=False)
        authority = resolve_backend_authority(config)
        signers = _unique_signers(config.payer, authority)
        assert len(signers) == 1

    def test_unique_signers_keeps_both(self):
        """When payer != authority, both signers in list."""
        config = make_config(separate_authority=True)
        authority = resolve_backend_authority(config)
        signers = _unique_signers(config.payer, authority)
        assert len(signers) == 2

# =========================================================================
# Test: Attestation hash canonical format
# =========================================================================


class TestAttestationHash:
    """Verify evidence hash format matches across callers."""

    def test_canonical_format(self):
        """Frozen byte layout: domain + wallet + vault + ride id + time + signature hash."""
        h = build_vault_completion_evidence_hash(
            wallet=USER_WALLET,
            vault_id=VAULT_ID,
            activity_id="ride-123",
            completed_at=COMPLETED_AT,
            time_s=COMPLETION_TIME_S,
            signature_hash=hashlib.sha256(bytes.fromhex(SIG_HEX)).digest(),
        )

        assert len(h) == 32
        assert h == build_vault_completion_evidence_hash(
            wallet=USER_WALLET,
            vault_id=VAULT_ID,
            activity_id="ride-123",
            completed_at=COMPLETED_AT,
            time_s=COMPLETION_TIME_S,
            signature_hash=hashlib.sha256(bytes.fromhex(SIG_HEX)).digest(),
        )

    def test_different_time_produces_different_hash(self):
        """Changing time_s changes the hash."""
        base = build_vault_completion_evidence_hash(
            wallet=USER_WALLET,
            vault_id=VAULT_ID,
            activity_id="ride-123",
            completed_at=COMPLETED_AT,
            time_s=600,
            signature_hash=hashlib.sha256(bytes.fromhex(SIG_HEX)).digest(),
        )
        alt = build_vault_completion_evidence_hash(
            wallet=USER_WALLET,
            vault_id=VAULT_ID,
            activity_id="ride-123",
            completed_at=COMPLETED_AT,
            time_s=601,
            signature_hash=hashlib.sha256(bytes.fromhex(SIG_HEX)).digest(),
        )
        assert base != alt


# =========================================================================
# Test: Gate logic (on_chain_seeding_status)
# =========================================================================


class TestGateLogic:
    """Test that on-chain call is gated on vault activation status."""

    def _make_indexed_vault(self, status: str = "active") -> dict:
        """Build a minimal indexed_vault dict."""
        return {
            "id": VAULT_ID,
            "name": "Test Climb",
            "signature_hex": SIG_HEX,
            "signature_hash_hex": hashlib.sha256(bytes.fromhex(SIG_HEX)).hexdigest(),
            "on_chain_seeding_status": status,
            "chain_activation_active": status == "active",
            "chain_activation_seed_generation": 2,
            "canon_binding_status": "active" if status == "active" else "pending",
            "canon_activation_status": "finalized" if status == "active" else "confirmed",
            "canon_climb_id": "11111111-1111-1111-1111-111111111111",
            "canon_id": "22222222-2222-2222-2222-222222222222",
            "canon_version": 2,
            "canonical_profile_hash_hex": "ab" * 32,
            "chain_slot": 900,
            "expected_vault_activation_pda": "vault-activation-pda",
            "canon_activation_chain_slot": 900,
            "vault_activation_pda": "vault-activation-pda",
            "vault_activation_is_active": status == "active",
            "vault_activation_seed_generation": 2,
            "vault_activation_seed_completions_written": 0,
            "vault_activation_leaderboard_seeded": status == "active",
            "vault_activation_matched_users": 0,
            "vault_activation_matched_completions": 0,
            "vault_activation_created_at": 100,
            "vault_activation_activated_at": 100,
            "vault_activation_last_seed_at": 100,
            "vault_activation_seed_cutoff_at": 100,
            "vault_activation_evidence_hash": "cd" * 32,
            "constructor_evidence_verified": status == "active",
            "constructor_evidence_hash": "cd" * 32,
            "vault_activation_chain_slot": 900,
            "vert_m": 100.0,
            "distance_m": 1000,
            "avg_gradient_pct": 5.0,
            "minter": USER_WALLET,
            "start_lat": None,
        }

    def test_active_vault_triggers_onchain(self):
        """on_chain_seeding_status='active' should trigger on-chain call."""
        vault = self._make_indexed_vault("active")
        assert is_vault_live_for_completion(vault) is True

    def test_legacy_generation_cannot_trigger_onchain(self):
        """An active generation-1 projection remains read-only."""
        vault = self._make_indexed_vault("active")
        vault["vault_activation_seed_generation"] = 1
        assert is_vault_live_for_completion(vault) is False

    def test_missing_chain_activation_projection_skips_onchain(self):
        """An operational active label cannot replace chain-derived authority."""
        vault = self._make_indexed_vault("active")
        vault.pop("vault_activation_is_active")
        vault.pop("vault_activation_seed_generation")
        assert is_vault_live_for_completion(vault) is False

    def test_pending_vault_skips_onchain(self):
        """on_chain_seeding_status='pending' should skip on-chain call."""
        vault = self._make_indexed_vault("pending")
        assert is_vault_live_for_completion(vault) is False

    def test_seeded_vault_skips_onchain(self):
        """on_chain_seeding_status='seeded' should skip on-chain call."""
        vault = self._make_indexed_vault("seeded")
        assert is_vault_live_for_completion(vault) is False

    def test_failed_vault_skips_onchain(self):
        """on_chain_seeding_status='failed' should skip on-chain call."""
        vault = self._make_indexed_vault("failed")
        assert is_vault_live_for_completion(vault) is False

    def test_none_status_skips_onchain(self):
        """Missing on_chain_seeding_status should skip on-chain call."""
        vault = self._make_indexed_vault("pending")
        vault["on_chain_seeding_status"] = None
        assert is_vault_live_for_completion(vault) is False

    def test_chain_projection_takes_precedence_over_operational_status(self):
        """A backend lifecycle label cannot override chain-derived authority."""
        vault = self._make_indexed_vault("active")
        vault["activation_status"] = "seed_pending"
        assert is_vault_live_for_completion(vault) is True

    def test_live_completion_side_effects_require_a_frozen_plan_after_activation_gate(self):
        """No direct completion write may bypass the frozen economic plan."""
        source = inspect.getsource(ClimbEconomyProcessor.match_climbs_to_vault)
        frozen_plan_error_idx = source.index(
            "direct climb completion economics are disabled"
        )

        assert frozen_plan_error_idx > 0
        assert "self.vault_repo.record_completion(" not in source
        assert "self.ride_executor.record_climb_completion(" not in source

        plan_source = inspect.getsource(ride_economic_plan_builder.build_completion_plan)
        activation_gate_idx = plan_source.index(
            "not is_vault_live_for_completion(indexed_vault)"
        )
        validation_idx = plan_source.index("validate_climb_time(")
        frozen_step_idx = plan_source.index("CompletionStepDraft(")
        assert activation_gate_idx < validation_idx < frozen_step_idx
