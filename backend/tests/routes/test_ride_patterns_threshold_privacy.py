"""Other riders never receive a ratio against the rider's Threshold (pvrwy).

The steady pattern's ``intensity_index`` is NP / FTP. Its ``np_power_w`` is
public like average power, so a non-owner response carrying both publishes the
rider's Threshold (FTP = NP / IF). Ratios against FTP or Threshold reach the
ride's owner alone; NP and average power stay public.

These tests run the real visibility decision (``check_ride_access`` and
``resolve_ride_visibility``); only storage and the vault-match lookup are
stubbed.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import (
    AuthenticatedUser,
    get_optional_current_user,
    get_repository,
)
from app.routes import rides

OWNER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
RIDE_ID = "66666666-6666-4666-8666-666666666666"
STEADY_ID = "77777777-7777-4777-8777-777777777777"

OWNER = AuthenticatedUser(user_id=OWNER_ID, wallet="owner-wallet", device_id="d1")
OTHER = AuthenticatedUser(user_id=OTHER_ID, wallet="other-wallet", device_id="d2")

# Key fragments that name a ratio against, or a value scaled by, FTP/Threshold.
THRESHOLD_RELATIVE_FRAGMENTS = ("intensity", "tss", "ftp", "threshold", "zone")


def _ride(*, visibility: str) -> dict[str, Any]:
    return {
        "id": RIDE_ID,
        "user_id": OWNER_ID,
        "visibility": visibility,
        "map_visibility": "show_all",
        "map_hide_start_m": 0,
        "map_hide_end_m": 0,
        "moderation_state": "visible",
        "processing_status": "completed",
    }


def _patterns() -> dict[str, Any]:
    return {
        "climb_patterns": [],
        "steady_pattern": {
            "id": STEADY_ID,
            "duration_s": 3600,
            "avg_power_w": 210.0,
            "np_power_w": 225.0,
            "avg_hr": 150,
            # 225 W NP at a 250 W Threshold.
            "intensity_index": 0.9,
            "variability_index": 1.07,
            "start_offset_s": 0,
            "end_offset_s": 3600,
        },
        "exploration_pattern": None,
    }


def _threshold_relative_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            name = str(key).lower()
            if name == "load" or any(part in name for part in THRESHOLD_RELATIVE_FRAGMENTS):
                found.append(here)
            found.extend(_threshold_relative_keys(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_threshold_relative_keys(item, f"{path}[{index}]"))
    return found


@pytest.fixture
def read_patterns(monkeypatch) -> Iterator[Any]:
    state: dict[str, Any] = {"ride": _ride(visibility="public"), "follows": False}
    repo = MagicMock()
    # Fresh rows on every request: the endpoint reshapes them in place.
    repo.get_ride = AsyncMock(side_effect=lambda _ride_id: dict(state["ride"]))
    repo.get_patterns_for_activity = AsyncMock(side_effect=lambda _ride_id: _patterns())
    repo.get_follow = AsyncMock(
        side_effect=lambda viewer, owner: {"id": "follow"} if state["follows"] else None
    )
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *args: {})

    app = FastAPI()
    app.include_router(rides.router, prefix="/rides")
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_optional_current_user] = lambda: state["viewer"]
    client = TestClient(app)

    def read(
        viewer: Optional[AuthenticatedUser],
        *,
        visibility: str = "public",
        follows: bool = False,
    ) -> dict[str, Any]:
        state.update(viewer=viewer, ride=_ride(visibility=visibility), follows=follows)
        response = client.get(f"/rides/{RIDE_ID}/patterns")
        assert response.status_code == 200, response.text
        return response.json()

    yield read


def test_owner_reads_the_steady_intensity_index(read_patterns):
    steady = read_patterns(OWNER)["patterns"]["steady_pattern"]

    assert steady["intensity_index"] == 0.9
    assert steady["np_power_w"] == 225.0


@pytest.mark.parametrize(
    "viewer,visibility,follows",
    [
        pytest.param(None, "public", False, id="signed-out-public"),
        pytest.param(OTHER, "public", False, id="other-rider-public"),
        pytest.param(OTHER, "followers", True, id="follower-followers-only"),
    ],
)
def test_non_owner_never_receives_a_threshold_ratio(read_patterns, viewer, visibility, follows):
    body = read_patterns(viewer, visibility=visibility, follows=follows)
    steady = body["patterns"]["steady_pattern"]

    assert steady["id"] == STEADY_ID
    assert _threshold_relative_keys(body) == []


@pytest.mark.parametrize("viewer", [OWNER, OTHER, None], ids=["owner", "other", "signed-out"])
def test_np_and_average_power_are_the_same_for_every_viewer(read_patterns, viewer):
    steady = read_patterns(viewer)["patterns"]["steady_pattern"]

    assert steady["np_power_w"] == 225.0
    assert steady["avg_power_w"] == 210.0
    # NP / average power uses no Threshold, so it stays public.
    assert steady["variability_index"] == 1.07
