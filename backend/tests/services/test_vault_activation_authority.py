from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.services.vault_activation_service import VaultActivationService
import app.services.vault_activation_service as activation_module


@pytest.fixture(autouse=True)
def _exercise_legacy_verification_units_under_their_original_family(monkeypatch):
    monkeypatch.setattr(activation_module, "PROGRAM_VERSION_FAMILY", "V4-A")


@pytest.mark.asyncio
async def test_v4b_hard_disables_legacy_seed_activate(monkeypatch):
    monkeypatch.setattr(activation_module, "PROGRAM_VERSION_FAMILY", "V4-B")
    service = _service()

    result = await service.seed_and_activate_vault(9, "ab" * 64)

    assert result.success is False
    assert "disabled for V4-B" in (result.error or "")
    service._submit_seed_summary.assert_not_awaited()
    service._submit_leaderboard_seed.assert_not_awaited()
    service._submit_activate.assert_not_awaited()


def _service() -> VaultActivationService:
    authority = Keypair()
    service = VaultActivationService(
        supabase_client=MagicMock(),
        authority_keypair=authority,
        fee_payer_keypair=authority,
        program_id=Pubkey.new_unique(),
    )
    service._update_seeding_status = MagicMock()
    service._update_seeding_failed = MagicMock()
    service._update_seeding_active = MagicMock()
    service._submit_seed_summary = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="seed-tx")
    )
    service._submit_leaderboard_seed = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="board-tx")
    )
    service._submit_activate = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="activate-tx")
    )
    return service


@pytest.mark.asyncio
async def test_inactive_vault_cannot_activate_without_sealed_v2_manifest():
    service = _service()
    service._get_vault = MagicMock(
        return_value={
            "id": 7,
            "name": "Manifestless climb",
            "on_chain_seeding_status": "pending",
            "activation_seed_generation": 0,
        }
    )
    service._get_seed_manifest_v2 = MagicMock(return_value=None)
    service._get_seed_completions = MagicMock(return_value=[])

    result = await service.seed_and_activate_vault(7, "ab" * 64)

    assert result.success is False
    assert "sealed historical seed manifest" in (result.error or "")
    service._submit_seed_summary.assert_not_awaited()
    service._submit_leaderboard_seed.assert_not_awaited()
    service._submit_activate.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_generation_one_vault_is_not_reported_as_verified():
    service = _service()
    service._get_vault = MagicMock(
        return_value={
            "id": 8,
            "name": "Legacy active climb",
            "on_chain_seeding_status": "active",
            "activation_seed_generation": 1,
            "activation_evidence_hash": "cd" * 32,
        }
    )
    service._get_seed_manifest_v2 = MagicMock(return_value=None)

    result = await service.seed_and_activate_vault(8, "ab" * 64)

    assert result.success is False
    assert "legacy activation is not reward-authoritative" in (result.error or "")
    service._submit_seed_summary.assert_not_awaited()
    service._submit_leaderboard_seed.assert_not_awaited()
    service._submit_activate.assert_not_awaited()
