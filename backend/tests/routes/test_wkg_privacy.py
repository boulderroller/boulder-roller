"""W/kg needs consent; numeric weight and Threshold detail stay owner-only.

Tim, 19 Oct 2026: a rider's W/kg is shown to others only if that rider opts
in. The default-off privacy.v2 opt-in applies to visible climbs. Average
power in watts stays public. Weight = avg power / W/kg, so any non-owner
response carrying both publishes the rider's body weight.

These tests run the real visibility decision (``check_ride_access`` and
``resolve_ride_visibility``); only storage and the vault-match lookup are
stubbed.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
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
RIDE_ID = "33333333-3333-4333-8333-333333333333"
# A climb whose numbers come from the ride's stored training read.
TRAINED_CLIMB_ID = "44444444-4444-4444-8444-444444444444"
# A climb with no training read: the stored patterns_climb columns pass through.
STORED_CLIMB_ID = "55555555-5555-4555-8555-555555555555"

OWNER = AuthenticatedUser(user_id=OWNER_ID, wallet="owner-wallet", device_id="d1")
OTHER = AuthenticatedUser(user_id=OTHER_ID, wallet="other-wallet", device_id="d2")

# Any key that names W/kg or body weight, in any casing or separator style.
WEIGHT_REVEALING_KEY = re.compile(r"w_?per_?kg|wkg|weight", re.IGNORECASE)


def _ride(*, visibility: str = "public", status: str = "completed") -> dict[str, Any]:
    return {
        "id": RIDE_ID,
        "user_id": OWNER_ID,
        "visibility": visibility,
        "map_visibility": "show_all",
        "map_hide_start_m": 0,
        "map_hide_end_m": 0,
        "moderation_state": "visible",
        "processing_status": status,
        "training_metrics": {
            "climbs": {
                TRAINED_CLIMB_ID: {
                    "avg_power_w": 252.0,
                    "w_per_kg": 3.6,
                    "basis": "training_engine_span",
                    "weight_basis": "retained_pattern_denominator",
                }
            }
        },
    }


def _patterns() -> dict[str, Any]:
    return {
        "climb_patterns": [
            {
                "id": TRAINED_CLIMB_ID,
                "detector_version": "canon_traversal_v1",
                "vert_m": 120.0,
                "time_s": 600,
                "distance_m": 2000.0,
                "avg_gradient_pct": 6.0,
                "avg_power_w": 251.37,
                "w_per_kg": 3.591,
                "weight_kg": 70, "threshold": {"value": 250}, "intensity_factor": 1.2,
                "load": 10, "power_zone_s": [1, 2], "power_zone_tops_w": [100, 200],
                "max_hr_bpm": 180, "percent_of_threshold": 120,
                "start_offset_s": 0,
                "end_offset_s": 600,
            },
            {
                "id": STORED_CLIMB_ID,
                "detector_version": "canon_traversal_v1",
                "vert_m": 80.0,
                "time_s": 420,
                "distance_m": 1400.0,
                "avg_gradient_pct": 5.7,
                "avg_power_w": 240.0,
                "w_per_kg": 3.428,
                "weight_kg": 70, "threshold": {"value": 250}, "intensity_factor": 1.2,
                "load": 10, "power_zone_s": [1, 2], "power_zone_tops_w": [100, 200],
                "max_hr_bpm": 180, "percent_of_threshold": 120,
                "start_offset_s": 900,
                "end_offset_s": 1320,
            },
        ],
        "steady_pattern": None,
        "exploration_pattern": None,
    }


def _weight_revealing_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            if WEIGHT_REVEALING_KEY.search(str(key)):
                found.append(here)
            found.extend(_weight_revealing_keys(item, here))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_weight_revealing_keys(item, f"{path}[{index}]"))
    return found


@pytest.fixture
def read_patterns(monkeypatch) -> Iterator[Any]:
    state: dict[str, Any] = {"ride": _ride(), "follows": False}
    repo = MagicMock()
    # Fresh rows on every request: the endpoint reshapes them in place.
    repo.get_ride = AsyncMock(side_effect=lambda _ride_id: dict(state["ride"]))
    repo.get_user_by_id = AsyncMock(side_effect=lambda _: {
        "id": OWNER_ID, "account_state": "active", "share_wkg": state.get("share_wkg", False),
    })
    repo.get_patterns_for_activity = AsyncMock(side_effect=lambda _ride_id: _patterns())
    repo.get_follow = AsyncMock(
        side_effect=lambda viewer, owner: {"id": "follow"} if state["follows"] else None
    )
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *args: {})
    monkeypatch.setattr(rides, "ClimbEffortRepository", lambda _: SimpleNamespace(
        get_efforts=AsyncMock(return_value=[]), recorded_power_rides=AsyncMock(return_value=set()),
        get_follow=repo.get_follow,
    ))

    app = FastAPI()
    app.include_router(rides.router, prefix="/rides")
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_optional_current_user] = lambda: state["viewer"]
    client = TestClient(app)

    def read(
        viewer: Optional[AuthenticatedUser],
        *,
        visibility: str = "public",
        status: str = "completed",
        follows: bool = False,
        share_wkg: bool = False,
    ) -> dict[str, Any]:
        state.update(
            viewer=viewer,
            share_wkg=share_wkg,
            ride=_ride(visibility=visibility, status=status),
            follows=follows,
        )
        response = client.get(f"/rides/{RIDE_ID}/patterns")
        assert response.status_code == 200, response.text
        return response.json()

    yield read


def _climbs_by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {climb["id"]: climb for climb in body["patterns"]["climb_patterns"]}


def test_owner_reads_wkg_from_training_read_and_stored_pattern(read_patterns):
    climbs = _climbs_by_id(read_patterns(OWNER))

    assert climbs[TRAINED_CLIMB_ID]["w_per_kg"] == 3.6
    assert climbs[TRAINED_CLIMB_ID]["avg_power_w"] == 252.0
    assert climbs[STORED_CLIMB_ID]["w_per_kg"] == 3.428
    assert climbs[STORED_CLIMB_ID]["avg_power_w"] == 240.0


@pytest.mark.parametrize(
    "viewer,visibility,follows",
    [
        pytest.param(None, "public", False, id="signed-out-public"),
        pytest.param(OTHER, "public", False, id="other-rider-public"),
        pytest.param(OTHER, "followers", True, id="follower-followers-only"),
    ],
)
def test_non_owner_never_receives_wkg(read_patterns, viewer, visibility, follows):
    body = read_patterns(viewer, visibility=visibility, follows=follows)
    climbs = _climbs_by_id(body)

    assert set(climbs) == {TRAINED_CLIMB_ID, STORED_CLIMB_ID}
    assert _weight_revealing_keys(body) == []


@pytest.mark.parametrize("viewer", [OWNER, OTHER, None], ids=["owner", "other", "signed-out"])
def test_average_power_in_watts_is_the_same_for_every_viewer(read_patterns, viewer):
    climbs = _climbs_by_id(read_patterns(viewer))

    assert climbs[TRAINED_CLIMB_ID]["avg_power_w"] == 252.0
    assert climbs[STORED_CLIMB_ID]["avg_power_w"] == 240.0


def test_stored_wkg_is_withheld_when_the_ride_has_no_training_read(read_patterns):
    """A ride outside the training population still carries the stored column."""
    owner_climbs = _climbs_by_id(read_patterns(OWNER, status="failed"))
    other_body = read_patterns(OTHER, status="failed")
    other_climbs = _climbs_by_id(other_body)

    assert owner_climbs[TRAINED_CLIMB_ID]["w_per_kg"] == 3.591
    assert owner_climbs[STORED_CLIMB_ID]["w_per_kg"] == 3.428
    assert _weight_revealing_keys(other_body) == []
    assert other_climbs[TRAINED_CLIMB_ID]["avg_power_w"] == 251.37
    assert other_climbs[STORED_CLIMB_ID]["avg_power_w"] == 240.0


def test_legacy_wkg_effort_leaderboard_is_not_mounted():
    """The /leaderboard router ranked other riders by W/kg; nothing calls it."""
    from app.main import create_app

    app = create_app()
    paths = {route.path for route in app.routes}

    assert sorted(
        path for path in paths if path == "/leaderboard" or path.startswith("/leaderboard/")
    ) == []
    assert TestClient(app).get("/leaderboard/climb").status_code == 404
    # The per-Climb Record Boards and the BeetleCard board are separate routes.
    assert "/climbs/{climb_id}/leaderboard" in paths
    assert "/vaults/{vault_id}/leaderboard" in paths
    assert "/beetles/leaderboard/{card_type}" in paths


@pytest.mark.parametrize('viewer', [OTHER, None])
def test_opt_in_shares_wkg_on_visible_ride_climbs_but_never_weight(read_patterns, viewer):
    body = read_patterns(viewer, share_wkg=True)
    climbs = _climbs_by_id(body)
    assert climbs[TRAINED_CLIMB_ID]['w_per_kg'] == 3.6
    assert climbs[STORED_CLIMB_ID]['w_per_kg'] == 3.428
    assert not any('weight' in key.lower() for key in _weight_revealing_keys(body))
    for climb in climbs.values():
        assert not {'threshold', 'intensity_factor', 'load', 'power_zone_s',
                    'power_zone_tops_w', 'max_hr_bpm', 'percent_of_threshold'} & climb.keys()
