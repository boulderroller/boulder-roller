"""Patterns endpoint canon climbId emission (boulderroller-v2-nrbu5).

The ride-sheet climb dead-end: canon identity previously reached clients only
through vaultMatch.vaultClimbId, which requires an authoritative completion.
The patterns endpoint now emits ``climbId`` (canon registry row UUID) wherever
the stored pattern IS an authoritative canon traversal — independent of
completion state, authority only, never similarity.

Red-first record: on pre-change code ``authoritative_canon_climb_id`` does not
exist and the endpoint emits no ``climbId``; every test here fails.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.routes.rides import get_ride_patterns
from app.services.canon_traversal import authoritative_canon_climb_id

REGISTRY_ID = str(uuid4())


@pytest.fixture(autouse=True)
def no_stored_efforts(monkeypatch):
    monkeypatch.setattr("app.routes.rides.ClimbEffortRepository", lambda _: SimpleNamespace(
        get_efforts=AsyncMock(return_value=[]), recorded_power_rides=AsyncMock(return_value=set()),
    ))


def _canon_pattern(**overrides):
    pattern = {
        "id": str(uuid4()),
        "vert_m": 55.0,
        "time_s": 240,
        "detector_version": "canon_traversal_v1",
        "match_trace": {
            "trace_version": "canon_traversal_trace_v1",
            "canon_id": str(uuid4()),
            "registry_id": REGISTRY_ID,
        },
    }
    pattern.update(overrides)
    return pattern


def _detector_pattern():
    return {
        "id": str(uuid4()),
        "vert_m": 30.0,
        "time_s": 180,
        "detector_version": "canonical_v2",
        "match_trace": {
            "authority": "discovery_only",
            "canon_traversal_required": True,
            "non_authoritative_detector_claim": {"registry_id": str(uuid4())},
        },
    }


class TestAuthoritativeCanonClimbId:
    def test_canon_traversal_row_yields_registry_uuid(self):
        assert authoritative_canon_climb_id(_canon_pattern()) == REGISTRY_ID

    def test_detector_row_yields_nothing_even_with_stripped_claim(self):
        assert authoritative_canon_climb_id(_detector_pattern()) is None

    def test_discovery_only_authority_is_refused(self):
        row = _canon_pattern()
        row["match_trace"]["authority"] = "discovery_only"
        assert authoritative_canon_climb_id(row) is None

    def test_json_string_trace_is_parsed(self):
        row = _canon_pattern()
        row["match_trace"] = json.dumps(row["match_trace"])
        assert authoritative_canon_climb_id(row) == REGISTRY_ID

    def test_malformed_trace_or_uuid_fails_closed(self):
        assert authoritative_canon_climb_id(_canon_pattern(match_trace="{broken")) is None
        assert authoritative_canon_climb_id(_canon_pattern(match_trace=None)) is None
        row = _canon_pattern()
        row["match_trace"]["registry_id"] = "not-a-uuid"
        assert authoritative_canon_climb_id(row) is None
        row = _canon_pattern()
        del row["match_trace"]["registry_id"]
        assert authoritative_canon_climb_id(row) is None


@pytest.mark.asyncio
async def test_patterns_endpoint_emits_climb_id_for_canon_bound_patterns_only():
    ride_id = str(uuid4())
    user_id = str(uuid4())
    ride = {
        "id": ride_id,
        "user_id": user_id,
        "visibility": "public",
        "processing_status": "enriched",
    }
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value=ride)
    repo.get_patterns_for_activity = AsyncMock(
        return_value={
            "climb_patterns": [_canon_pattern(), _detector_pattern()],
            "steady_pattern": None,
            "exploration_pattern": None,
        }
    )
    current_user = AuthenticatedUser(wallet="w1", user_id=user_id, device_id="d1")

    decision = MagicMock()
    decision.redact_gps = False
    with patch("app.routes.rides.resolve_ride_visibility", AsyncMock(return_value=decision)), patch(
        "app.routes.rides.check_ride_access", AsyncMock(return_value=decision)
    ), patch("app.routes.rides._fetch_pattern_vault_matches", return_value={}):
        response = await get_ride_patterns(
            ride_id=ride_id, current_user=current_user, repo=repo
        )

    climbs = response["patterns"]["climb_patterns"]
    assert climbs[0]["climbId"] == REGISTRY_ID
    assert "climbId" not in climbs[1]
    # No completion-backed vaultMatch existed: the canon binding alone is
    # enough for the climb sheet to deep-link a pattern-only ride.
    assert "vaultMatch" not in climbs[0] or climbs[0]["vaultMatch"] is None


@pytest.mark.asyncio
async def test_climb_id_survives_privacy_redaction():
    ride_id = str(uuid4())
    ride = {
        "id": ride_id,
        "user_id": str(uuid4()),
        "visibility": "public",
        "processing_status": "enriched",
    }
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value=ride)
    repo.get_patterns_for_activity = AsyncMock(
        return_value={
            "climb_patterns": [_canon_pattern()],
            "steady_pattern": None,
            "exploration_pattern": None,
        }
    )

    decision = MagicMock()
    decision.redact_gps = True
    with patch("app.routes.rides.resolve_ride_visibility", AsyncMock(return_value=decision)), patch(
        "app.routes.rides.check_ride_access", AsyncMock(return_value=decision)
    ), patch("app.routes.rides._fetch_pattern_vault_matches", return_value={}):
        response = await get_ride_patterns(
            ride_id=ride_id, current_user=None, repo=repo
        )

    climb = response["patterns"]["climb_patterns"][0]
    assert climb["climbId"] == REGISTRY_ID
    # The redactor still strips route-reconstruction fields for non-owners.
    assert "match_trace" not in climb
