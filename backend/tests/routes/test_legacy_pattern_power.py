"""Local synthetic evidence for hyo46; no rider files or remote services."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tests.routes.test_climb_effort_api import effort, OWNER, OTHER, EFFORT_ID


@pytest.mark.parametrize("detector", ["canon_traversal_v1", "template_match:canonical_v2"])
def test_direct_sample_average_lineage(detector):
    from app.services.climb_effort_reads import legacy_pattern_power
    result = legacy_pattern_power({"processing_status": "completed"}, {
        "id": EFFORT_ID, "detector_version": detector, "avg_power_w": 301.25, "w_per_kg": 4.01,
    })
    assert result == {"power_kind": "measured", "avg_power_w": 301.25, "w_per_kg": 4.01}


@pytest.mark.parametrize("recorded_stream", [False, True])
def test_mutable_detector_marker_needs_independent_recorded_power(recorded_stream):
    from app.services.climb_effort_reads import legacy_pattern_power
    ride = {"processing_status": "completed"}
    pattern = {"id": EFFORT_ID, "detector_version": "canonical_v2", "avg_power_w": 301.25}
    assert legacy_pattern_power(ride, pattern) == {}
    if not recorded_stream:
        ride.update(metrics_version="workout_parse_metrics_v1", power_sample_count=120)
    assert legacy_pattern_power(ride, pattern, recorded_stream=recorded_stream) == {
        "power_kind": "measured", "avg_power_w": 301.25,
    }


def test_training_span_takes_precedence_and_does_not_resurrect_absent_power():
    from app.services.climb_effort_reads import legacy_pattern_power
    read = {"basis": "training_engine_span", "avg_power_w": 287.5, "w_per_kg": 3.8}
    ride = {"processing_status": "completed", "training_metrics": {"climbs": {EFFORT_ID: read}}}
    pattern = {"id": EFFORT_ID, "detector_version": "canon_traversal_v1", "avg_power_w": 999}
    assert legacy_pattern_power(ride, pattern)["avg_power_w"] == 287.5
    read["avg_power_w"] = None
    assert legacy_pattern_power(ride, pattern) == {}


@pytest.mark.parametrize("changes", [
    {}, {"detector_version": "future"}, {"detector_version": "template_match:future"},
    {"power_kind": "estimated"}, {"power_kind": "measured"},
    {"detector_version": "canon_traversal_v1", "avg_power_w": float("nan")},
    {"detector_version": "canon_traversal_v1", "avg_power_w": -1},
])
def test_unknown_or_invalid_legacy_watts_are_absent(changes):
    from app.services.climb_effort_reads import legacy_pattern_power
    assert legacy_pattern_power({"processing_status": "completed"}, {
        "id": EFFORT_ID, "avg_power_w": 999, "w_per_kg": 99, **changes,
    }) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("viewer,share", [(OWNER, False), (OTHER, False), (OTHER, True), (None, True)])
async def test_patterns_use_effort_power_and_same_audience_projection(monkeypatch, viewer, share):
    from app.routes import rides
    row = effort()
    row["rider"]["share_wkg"] = share
    row["metrics"].update(power_zone_tops_w=[100], power_zone_s=[60], max_power_w=450)
    pattern = {"id": EFFORT_ID, "time_s": 100, "vert_m": 30, "avg_power_w": 999, "w_per_kg": 99}
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]), public_span=AsyncMock(return_value=True))
    monkeypatch.setattr(rides, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *_: {})
    repo = SimpleNamespace(client=object(), get_ride=AsyncMock(return_value=row["ride"]),
        get_user_by_id=AsyncMock(return_value=row["rider"]),
        get_patterns_for_activity=AsyncMock(return_value={"climb_patterns": [pattern]}))
    result = await rides.get_ride_patterns("ride", current_user=viewer, repo=repo)
    power = result["patterns"]["climb_patterns"][0]
    assert power["avg_power_w"] == 300 and power["power_kind"] == "measured"
    assert power["max_power_w"] == 450
    assert ("w_per_kg" in power) == (viewer == OWNER or share)
    for key in ("threshold", "intensity_factor", "load", "power_zone_s", "power_zone_tops_w"):
        assert (key in power) == (viewer == OWNER)
    fake.get_efforts.assert_awaited_once_with([EFFORT_ID])


@pytest.mark.asyncio
async def test_denied_effort_cannot_fall_back_to_legacy_watts(monkeypatch):
    from app.routes import rides
    row = effort()
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]), public_span=AsyncMock(return_value=False))
    monkeypatch.setattr(rides, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *_: {})
    repo = SimpleNamespace(client=object(), get_ride=AsyncMock(return_value=row["ride"]),
        get_user_by_id=AsyncMock(return_value=row["rider"]),
        get_patterns_for_activity=AsyncMock(return_value={"climb_patterns": [{
            "id": EFFORT_ID, "time_s": 100, "vert_m": 30, "detector_version": "canon_traversal_v1",
            "avg_power_w": 999, "w_per_kg": 99,
        }]}))
    result = await rides.get_ride_patterns("ride", current_user=OTHER, repo=repo)
    power = result["patterns"]["climb_patterns"][0]
    assert all(key not in power for key in ("power_kind", "avg_power_w", "w_per_kg"))


@pytest.mark.asyncio
async def test_unavailable_effort_authority_keeps_climbs_and_drops_all_power(monkeypatch):
    from app.routes import rides
    row = effort()
    fake = SimpleNamespace(get_efforts=AsyncMock(side_effect=RuntimeError("store down")))
    monkeypatch.setattr(rides, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *_: {})
    repo = SimpleNamespace(client=object(), get_ride=AsyncMock(return_value=row["ride"]),
        get_user_by_id=AsyncMock(return_value=row["rider"]),
        get_patterns_for_activity=AsyncMock(return_value={"climb_patterns": [{
            "id": EFFORT_ID, "time_s": 100, "vert_m": 30, "detector_version": "canon_traversal_v1",
            "avg_power_w": 999, "w_per_kg": 99, "power_kind": "measured",
        }]}))
    result = await rides.get_ride_patterns("ride", current_user=OWNER, repo=repo)
    climbs = result["patterns"]["climb_patterns"]
    assert len(climbs) == 1 and climbs[0]["time_s"] == 100
    assert all(key not in climbs[0] for key in ("power_kind", "avg_power_w", "w_per_kg", "estimated_power_w"))


@pytest.mark.asyncio
@pytest.mark.parametrize("change,visible", [
    ({}, True), ({"visibility": "followers"}, False), ({"visibility": "private"}, False),
    ({"map_visibility": "hide_entire"}, False), ({"is_public": False}, False),
    ({"account_state": "deletion_pending"}, False),
])
async def test_board_ride_link_follows_fresh_visibility(change, visible):
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    row = effort()
    for key, value in change.items():
        (row["rider"] if key in {"is_public", "account_state"} else row["ride"])[key] = value
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]),
                           public_span=AsyncMock(return_value=row["ride"]["map_visibility"] != "hide_entire"))
    projection = PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100}], kom_holder=None, kom_time_s=None,
        effort_ids={OWNER.wallet: EFFORT_ID})
    rows, _ = await enrich_board(repo, projection, vault_signature="sig")
    assert bool(rows) is visible
    if visible:
        assert rows[0].ride_id == "ride"


def test_preview_carries_only_server_authorized_visible_links():
    from app.public_preview_contracts import build_public_record_board
    row = {"rank": 1, "username": "rider", "effort_id": EFFORT_ID, "ride_id": "ride"}
    result = build_public_record_board({"entries": [row]})["entries"][0]
    assert result["effortId"] == EFFORT_ID and result["rideId"] == "ride"
    row["identity_hidden"] = True
    hidden = build_public_record_board({"entries": [row]})["entries"][0]
    assert "rideId" not in hidden and "effortId" not in hidden


@pytest.mark.asyncio
async def test_preview_receives_public_identity_and_link_from_actual_board_projection():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from app.public_preview_contracts import build_public_record_board
    row = effort()
    row["rider"].update(username="public-rider", display_name="Public Rider", avatar_storage_path="private/path")
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]), public_span=AsyncMock(return_value=True))
    projection = PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100}], kom_holder=None, kom_time_s=None,
        effort_ids={OWNER.wallet: EFFORT_ID})
    entries, _ = await enrich_board(repo, projection, vault_signature="sig")
    preview = build_public_record_board({"entries": [entry.model_dump() for entry in entries]})
    result = preview["entries"][0]
    assert result["rideId"] == row["ride_id"] and result["effortId"] == EFFORT_ID
    assert result["rider"]["username"] == "public-rider"
    assert "private/path" not in str(preview)


@pytest.mark.asyncio
@pytest.mark.parametrize("viewer,visibility,follows,span,account,profile,allowed", [
    (None, "public", False, True, "active", True, True),
    (OWNER, "private", False, False, "active", False, True),
    (OTHER, "private", True, True, "active", True, False),
    (OTHER, "followers", True, True, "active", True, True),
    (OTHER, "followers", False, True, "active", True, False),
    (OTHER, "public", False, False, "active", True, False),
    (OTHER, "public", False, True, "active", False, True),
    (OWNER, "public", False, True, "deletion_pending", True, False),
])
async def test_pattern_effort_audience_matrix(viewer, visibility, follows, span, account, profile, allowed):
    from app.services.climb_effort_reads import pattern_power
    row = effort()
    row["ride"]["visibility"] = visibility
    row["rider"].update(account_state=account, is_public=profile)
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]),
                           get_follow=AsyncMock(return_value=follows), public_span=AsyncMock(return_value=span))
    result = await pattern_power(fake, row["ride"], [{"id": EFFORT_ID}], viewer)
    assert bool(result[EFFORT_ID]) is allowed


@pytest.mark.asyncio
async def test_estimated_pattern_keeps_estimate_and_never_legacy_measured_or_wkg():
    from app.services.climb_effort_reads import pattern_power
    row = effort()
    row["metrics"].update(power_kind="estimated", estimated_power_w=219.7,
        estimated_power_range_w=[200, 240], power_estimate_basis="canon_profile_standard_mass_75_plus_8")
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]))
    result = (await pattern_power(fake, row["ride"], [{"id": EFFORT_ID}], OWNER))[EFFORT_ID]
    assert result["power_kind"] == "estimated" and result["estimated_power_w"] == 219.7
    assert result["estimated_power_range_w"] == [200, 240]
    assert "avg_power_w" not in result and "w_per_kg" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("account,moderation,visible", [
    ("active", "visible", True), ("deletion_pending", "visible", False), ("active", "hidden", False),
])
async def test_legacy_pattern_respects_owner_account_and_moderation(account, moderation, visible):
    from app.services.climb_effort_reads import pattern_power
    row = effort()
    row["rider"].update(account_state=account, moderation_state=moderation)
    pattern = {"id": EFFORT_ID, "avg_power_w": 300, "detector_version": "canon_traversal_v1"}
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[]), recorded_power_rides=AsyncMock(return_value=set()))
    result = await pattern_power(fake, row["ride"], [pattern], OTHER, rider=row["rider"])
    assert bool(result[EFFORT_ID]) is visible


@pytest.mark.asyncio
async def test_mismatched_or_invalid_effort_does_not_use_legacy_power():
    from app.services.climb_effort_reads import pattern_power
    row = effort()
    ride = deepcopy(row["ride"])
    row["ride_id"] = "wrong-ride"
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]))
    pattern = {"id": EFFORT_ID, "avg_power_w": 999, "detector_version": "canon_traversal_v1"}
    assert (await pattern_power(fake, ride, [pattern], OWNER))[EFFORT_ID] == {}
    row["ride_id"] = ride["id"]
    row["metrics"]["power_kind"] = "unknown"
    with pytest.raises(ValueError):
        await pattern_power(fake, ride, [pattern], OWNER)


@pytest.mark.asyncio
@pytest.mark.parametrize("share,known", [(False, True), (True, True), (True, False)])
async def test_legacy_board_uses_exact_pattern_provenance_without_inventing_an_effort(share, known):
    from app.repositories.climb_effort import ClimbEffortRepository
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from app.utils.polyline import encode_gps_track
    from backend.tests.repositories.test_climb_effort_reads import Client
    row = effort()
    ride_id = "33333333-3333-4333-8333-333333333333"
    ride = {**row["ride"], "id": ride_id, "rider": {**row["rider"], "share_wkg": share},
        "gps_track": encode_gps_track([{"latitude": 40 + t * .0001, "longitude": -75, "timestamp": t}
                                        for t in range(0, 121, 10)])}
    pattern = {"id": EFFORT_ID, "activity_id": ride_id, "time_s": 100,
        "start_offset_s": 10, "end_offset_s": 110, "avg_power_w": 301.25, "w_per_kg": 4.01,
        "detector_version": "canon_traversal_v1" if known else None}
    client = Client({"rides": [ride], "patterns_climb": [pattern]})
    projection = PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100, "recorded_at": 1000}],
        kom_holder=None, kom_time_s=None, effort_ids={OWNER.wallet: EFFORT_ID}, ride_ids={OWNER.wallet: ride_id})
    rows, _ = await enrich_board(ClimbEffortRepository(client), projection, vault_signature="sig")
    assert len(rows) == 1 and rows[0].best_time_seconds == 100
    assert rows[0].power_kind == ("measured" if known else None)
    assert rows[0].w_per_kg == (4.01 if known and share else None)
    assert rows[0].effort_id is None and rows[0].ride_id is None
    assert rows[0].achieved_at == "1970-01-01T00:16:40+00:00"
    ride["rider"]["account_state"] = "deletion_pending"
    assert (await enrich_board(ClimbEffortRepository(client), projection, vault_signature="sig"))[0] == []
    ride["rider"]["account_state"] = "active"
    ride["map_visibility"] = "hide_entire"
    assert (await enrich_board(ClimbEffortRepository(client), projection, vault_signature="sig"))[0] == []
    ride["map_visibility"] = "show_all"
    projection.ride_ids[OWNER.wallet] = "wrong-ride"
    assert (await enrich_board(ClimbEffortRepository(client), projection, vault_signature="sig"))[0] == []
