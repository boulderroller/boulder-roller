"""Truthful rider weight contract after manual FTP removal."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.repositories.user import UserRepository
from app.repositories_legacy import SupabaseRepository
from app.routes.users import _build_private_profile_response
from app.schemas import UserProfileUpdate


def _profile_row(**overrides):
    row = {
        "id": str(uuid4()),
        "wallet": "wallet-1",
        "username": "tim",
        "display_name": "Tim",
        "is_public": True,
        "preferred_units": "metric",
        "theme_id": "hoo-breddin",
        "is_dark_mode": True,
        "rider_type": "climber",
    }
    row.update(overrides)
    return row


class TestPrivateProfileAbsence:
    def test_never_entered_physiology_reads_absent_not_fabricated(self):
        response = _build_private_profile_response(_profile_row(), {}, [], "wallet-1")
        assert response.weight_kg is None
        assert response.weight_kg_source is None
        assert "ftp_w" not in response.model_dump()
        assert "ftp_w_source" not in response.model_dump()

    def test_real_values_round_trip_with_provenance(self):
        response = _build_private_profile_response(
            _profile_row(
                weight_kg=81.4,
                weight_kg_source="derived",
            ),
            {},
            [],
            "wallet-1",
        )
        assert response.weight_kg == 81.4
        assert response.weight_kg_source == "derived"
        assert "ftp_w" not in response.model_dump()

    def test_zero_is_not_treated_as_absence(self):
        # Guard the falsy trap: 0 would have been swallowed by `or 200`.
        response = _build_private_profile_response(_profile_row(weight_kg=0), {}, [], "wallet-1")
        assert response.weight_kg == 0.0

    def test_private_profile_omits_legacy_total_tss_even_when_stats_contains_it(self):
        response = _build_private_profile_response(
            _profile_row(),
            {"total_tss": 777},
            [],
            "wallet-1",
        )

        assert "total_tss" not in response.model_dump()
        assert "total_tss" not in response.model_json_schema()["properties"]

    @pytest.mark.parametrize("payload", [{"ftp_w": 245}, {"ftpW": 245}])
    def test_legacy_manual_ftp_input_is_ignored_for_one_client_generation(self, payload):
        update = UserProfileUpdate.model_validate(payload)
        assert update.model_dump(exclude_unset=True) == {}

    @pytest.mark.parametrize(
        "payload", [{"unit_preference": "imperial"}, {"unitPreference": "imperial"}]
    )
    def test_legacy_unit_key_does_not_fail_the_whole_profile_update(self, payload):
        update = UserProfileUpdate.model_validate(payload)
        assert update.model_dump(exclude_unset=True) == {}


def _repo_with_capture():
    repo = UserRepository.__new__(UserRepository)
    captured = {}

    table = MagicMock()

    def _update(payload):
        captured["payload"] = payload
        chain = MagicMock()
        chain.eq.return_value.execute.return_value = MagicMock(data=[{}])
        return chain

    table.update.side_effect = _update
    client = MagicMock()
    client.table.return_value = table
    repo._client = client

    async def _run(fn):
        return fn()

    repo._run = _run
    repo.get_profile_setup_state = AsyncMock(return_value=None)
    repo.get_private_user_profile = AsyncMock(return_value={})
    return repo, captured


class TestExplicitClearPersists:
    @pytest.mark.asyncio
    async def test_admission_profile_does_not_depend_on_threshold_authority(self):
        repo = UserRepository.__new__(UserRepository)
        repo._fetch_user_row_by_wallet = AsyncMock(
            return_value={
                "id": "user-1",
                "wallet": "wallet-1",
                "weight_kg": 81.4,
            }
        )

        profile = await repo.get_user_profile("wallet-1")

        assert profile == {
            "id": "user-1",
            "wallet": "wallet-1",
            "weight_kg": 81.4,
        }
        repo._fetch_user_row_by_wallet.assert_awaited_once_with(
            "wallet-1",
            "id, wallet, email, created_at, weight_kg",
        )

    @pytest.mark.asyncio
    async def test_manual_entry_stamps_manual_source(self):
        repo, captured = _repo_with_capture()
        await repo.update_user_profile("wallet-1", {"weight_kg": 81.4})
        payload = captured["payload"]
        assert payload["weight_kg"] == 81.4
        assert payload["weight_kg_source"] == "manual"

    @pytest.mark.asyncio
    async def test_other_none_fields_are_still_dropped(self):
        # Partial-update semantics stay intact for non-physiology fields.
        repo, captured = _repo_with_capture()
        await repo.update_user_profile(
            "wallet-1", {"bio": None, "location": None, "weight_kg": 80}
        )
        payload = captured["payload"]
        assert "bio" not in payload
        assert "location" not in payload
        assert payload["weight_kg"] == 80

    @pytest.mark.asyncio
    async def test_repository_rejects_manual_ftp_even_if_called_directly(self):
        repo, _ = _repo_with_capture()
        with pytest.raises(ValueError):
            await repo.update_user_profile("wallet-1", {"ftp_w": 250})

    @pytest.mark.asyncio
    async def test_legacy_repository_also_rejects_manual_ftp(self):
        repo = SupabaseRepository.__new__(SupabaseRepository)
        with pytest.raises(ValueError):
            await repo.update_user_profile("wallet-1", {"ftp_w": 250})
