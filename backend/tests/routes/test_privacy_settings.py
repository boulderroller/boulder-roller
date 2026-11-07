from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi import HTTPException

from app.dependencies import AuthenticatedUser
from app.routes.privacy import (
    PrivacySettingsUpdate,
    get_privacy_settings,
    update_privacy_settings,
)


class FakePrivacySettingsRepo:
    def __init__(self) -> None:
        self.user = {
            "id": "user-1",
            "wallet": "wallet-1",
            "is_public": True,
            "default_ride_visibility": "public",
            "default_map_visibility": "hide_start_end",
            "default_map_hide_start_m": 200,
            "default_map_hide_end_m": 200,
        }
        self.privacy_zone_count = 2
        self.updated_payloads: list[dict[str, Any]] = []

    async def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        return dict(self.user) if user_id == self.user["id"] else None

    async def update_user_profile(self, wallet: str, updates: dict[str, Any]) -> Optional[dict[str, Any]]:
        if wallet != self.user["wallet"]:
            return None
        self.updated_payloads.append(dict(updates))
        self.user.update(updates)
        return dict(self.user)

    async def count_privacy_zones(self, user_id: str) -> int:
        assert user_id == self.user["id"]
        return self.privacy_zone_count


@pytest.fixture
def current_user() -> AuthenticatedUser:
    return AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")


@pytest.mark.asyncio
async def test_privacy_settings_returns_quiet_defaults(current_user: AuthenticatedUser) -> None:
    repo = FakePrivacySettingsRepo()

    response = await get_privacy_settings(
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response.contract_version == "privacy.v2"
    assert response.profile_visibility == "public"
    assert response.default_ride_visibility == "public"
    assert response.default_map_visibility == "hide_start_end"
    assert response.default_map_hide_start_m == 200
    assert response.default_map_hide_end_m == 200
    assert response.defaults_apply_to == "future_rides"
    assert response.provider_privacy_inherited is False
    assert response.privacy_zone_count == 2
    assert response.privacy_zones_loaded is True
    assert response.ride_override_mode == "optional"
    assert "ride_hash_hex" in response.protocol_public_fields


@pytest.mark.asyncio
async def test_privacy_settings_updates_profile_and_default_ride_visibility(
    current_user: AuthenticatedUser,
) -> None:
    repo = FakePrivacySettingsRepo()
    payload = PrivacySettingsUpdate.model_validate({
        "isPublic": False,
        "defaultRideVisibility": "followers",
        "defaultMapVisibility": "show_all",
        "defaultMapHideStartM": 0,
        "defaultMapHideEndM": 0,
    })

    response = await update_privacy_settings(
        payload=payload,
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )

    assert repo.updated_payloads == [{
        "is_public": False,
        "default_ride_visibility": "followers",
        "default_map_visibility": "show_all",
        "default_map_hide_start_m": 0,
        "default_map_hide_end_m": 0,
    }]
    assert response.profile_visibility == "private"
    assert response.default_ride_visibility == "followers"
    assert response.default_map_visibility == "show_all"


@pytest.mark.asyncio
async def test_privacy_settings_rejects_empty_update(current_user: AuthenticatedUser) -> None:
    repo = FakePrivacySettingsRepo()

    with pytest.raises(HTTPException) as exc:
        await update_privacy_settings(
            payload=PrivacySettingsUpdate(),
            current_user=current_user,
            repo=repo,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 400
    assert repo.updated_payloads == []


@pytest.mark.asyncio
async def test_privacy_settings_fails_closed_when_map_defaults_are_incomplete(
    current_user: AuthenticatedUser,
) -> None:
    repo = FakePrivacySettingsRepo()
    repo.user.pop("default_map_visibility")

    with pytest.raises(HTTPException) as exc:
        await get_privacy_settings(
            current_user=current_user,
            repo=repo,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 503
