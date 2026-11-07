"""Local storage fixtures exercise the real read, privacy and route projection."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.routes import climbs
from backend.tests.repositories.test_climb_effort_reads import Client, Query, evidence_for
from backend.tests.routes.test_climb_effort_api import CLIMB_ID, OWNER, OTHER, effort

V2 = str(UUID(int=222))
FAMILY = str(UUID(int=333))


class BoardQuery(Query):
    def in_(self, key, values):
        if self.table == "rides" and key == "id":
            for value in values:
                UUID(value)  # Match the real rides UUID column, including detached patterns.
        return super().in_(key, values)

    def eq(self, key, value):
        self.client.filters.append((self.table, key, value))
        if key == "match_trace->>registry_id":
            self.rows = [r for r in self.rows if r.get("match_trace", {}).get("registry_id") == value]
            return self
        return super().eq(key, value)


class BoardClient(Client):
    def __init__(self, tables):
        super().__init__(tables)
        self.filters = []

    def from_(self, table):
        return BoardQuery(self, table)


def storage(rows, *, legacy=False):
    tables = {"canon_climbs": [
        dict(id=CLIMB_ID, canon_id=FAMILY, version=1, display_name="Test hill", status="retired"),
        dict(id=V2, canon_id=FAMILY, version=2, display_name="Test hill", status="ratified"),
    ], "climb_efforts": [], "patterns_climb": [], "rides": [], "canon_traversal_evidence": []}
    for index, original in enumerate(rows):
        row = deepcopy(original)
        row["id"] = str(UUID(int=index + 100))
        # Real evidence/privacy projection, including legacy GPS, with no network.
        tables["canon_traversal_evidence"].append(evidence_for(
            row, range(0, 401, 10), ride_id=str(UUID(int=index + 1000))))
        row["ride"].update(rider=row["rider"], started_at="2026-10-21T00:00:00+00:00")
        tables["rides"].append(row["ride"])
        tables["patterns_climb"].append(dict(
            id=row["id"], activity_id=row["ride_id"], time_s=row["time_s"],
            start_offset_s=row["start_offset_s"], end_offset_s=row["end_offset_s"],
            detector_version="canon_traversal_v1", avg_power_w=275, w_per_kg=3.5,
            match_trace={"registry_id": row["climb_id"], "canon_version": row["canon_version"],
                         "gate_crossings": {"start_time_s_raw": row["start_offset_s"],
                                            "finish_time_s_raw": row["end_offset_s"]}}))
        if not legacy:
            tables["climb_efforts"].append(row)
    return BoardClient(tables)


def rider(user_id, time_s=100, **changes):
    row = effort(user_id=user_id, time_s=time_s, end_offset_s=10 + time_s, **changes)
    row["rider"].update(id=user_id, wallet=f"wallet-{user_id}", username=user_id)
    row["ride"]["user_id"] = user_id
    return row


@pytest.fixture(autouse=True)
def inactive_runtime(monkeypatch):
    monkeypatch.setattr(climbs, "load_canon_climb_runtime_states", lambda **kw: {})


async def board(client, viewer=None, climb_id=CLIMB_ID, window=None):
    args = dict(climb_id=climb_id, repo=SimpleNamespace(client=client), current_user=viewer)
    return await (climbs.get_climb_window_leaderboard(**args, window=window) if window
                  else climbs.get_climb_leaderboard(**args))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_best_per_rider_ties_contract_and_exact_version(legacy):
    client = storage([rider("a", 120), rider("a", 100), rider("b", 100), rider("c", 150),
                      rider("v2", 80, climb_id=V2, canon_version=2)], legacy=legacy)
    result = await board(client)
    assert [e["best_time_seconds"] for e in result["entries"]] == [100, 100, 150]
    assert [e["competition_rank"] for e in result["entries"]] == [1, 1, 3]
    assert [e["tie_size"] for e in result["entries"]] == [2, 2, 1]
    assert result["source"] == "rides" and result["truth_source"] == "projected"
    assert result["vault_id"] is None and result["kom_holder"] is None and result["kom_time_s"] is None
    assert all(e["place_source"] == "rides" and e["vault_signature"] is None for e in result["entries"])
    assert all(e["ride_id"] for e in result["entries"])
    assert all((e["effort_id"] is None) == legacy for e in result["entries"])
    second = await board(client, climb_id=V2)
    assert [e["user_id"] for e in second["entries"]] == ["v2"]
    assert second["earlier_version_id"] == CLIMB_ID
    assert ("patterns_climb", "match_trace->>registry_id", CLIMB_ID) in client.filters


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("target,key,value", [
    ("rider", "is_public", False), ("ride", "visibility", "followers"),
    ("ride", "visibility", "private"), ("ride", "hide_from_leaderboards", True),
    ("ride", "moderation_state", "hidden"), ("rider", "moderation_state", "removed"),
    ("rider", "account_state", "deletion_pending"), ("ride", "map_visibility", "hide_entire"),
    ("ride", "processing_status", "failed"), ("ride", "processing_status", "processing"),
    ("ride", "map_visibility", None), ("ride", "hide_from_leaderboards", None),
])
async def test_privacy_matrix(legacy, target, key, value):
    row = rider("owner")
    row[target][key] = value
    client = storage([row], legacy=legacy)
    # Public standings and pinned rows use the existing vault public-owner rule.
    for viewer in (None, OTHER, OWNER):
        result = await board(client, viewer)
        assert result["entries"] == [] and result["viewer_entry"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_zone_and_endpoint_span_hidden(legacy):
    client = storage([rider("owner")], legacy=legacy)
    client.tables["privacy_zones"] = [dict(id="zone", user_id="owner", latitude=40.015, longitude=-75, radius_m=400)]
    assert (await board(client))["entries"] == []
    client.tables["privacy_zones"] = []
    for row in client.tables["rides"] + [e["ride"] for e in client.tables["climb_efforts"]]:
        row.update(map_visibility="hide_start_end", map_hide_start_m=1000, map_hide_end_m=0)
    assert (await board(client))["entries"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_measured_power_and_wkg_consent(legacy):
    client = storage([rider("owner")], legacy=legacy)
    public = (await board(client))["entries"][0]
    assert public["power_kind"] == "measured" and public["avg_power_w"] == (275 if legacy else 300)
    assert "w_per_kg" not in public
    assert (await board(client, OWNER))["viewer_entry"]["w_per_kg"] == (3.5 if legacy else 4)
    for row in client.tables["rides"] + [e["ride"] for e in client.tables["climb_efforts"]]:
        row["rider"]["share_wkg"] = True
    assert "w_per_kg" in (await board(client, OTHER))["entries"][0]


@pytest.mark.asyncio
async def test_estimate_never_falls_back_to_legacy_measured_watts_or_wkg():
    row = rider("owner", power_kind="estimated", estimated_power_w=280,
                estimated_power_range_w=[250, 310])
    row["metrics"].update(power_kind="estimated", estimated_power_w=280, estimated_power_range_w=[250, 310])
    client = storage([row])
    result = (await board(client, OWNER))["viewer_entry"]
    assert result["power_kind"] == "estimated" and result["avg_power_w"] is None
    assert result["estimated_power_w"] == 280 and result["estimated_power_range_w"] == [250, 310]
    assert "w_per_kg" not in result


@pytest.mark.asyncio
async def test_pin_own_best_beyond_ten_and_skip_faster_private_attempt():
    private = rider("owner", 70)
    private["ride"]["visibility"] = "private"
    client = storage([private, rider("owner", 130), *[rider(f"r{i}", 80+i) for i in range(11)]])
    result = await board(client, OWNER)
    assert len(result["entries"]) == 10
    assert result["viewer_entry"]["rank"] == 12 and result["viewer_entry"]["best_time_seconds"] == 130
    assert result["viewer_entry"]["place_source"] == "rides"
    assert (await board(client))["viewer_entry"] is None


@pytest.mark.asyncio
async def test_empty_and_no_invented_earlier_version():
    client = storage([])
    client.tables["canon_climbs"] = client.tables["canon_climbs"][1:]
    result = await board(client, climb_id=V2)
    assert result["entries"] == [] and result["source"] == "rides"
    assert result["earlier_version_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_existing_today_and_year_windows(legacy, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(climbs, "datetime", Clock)
    client = storage([rider("today"), rider("year"), rider("old")], legacy=legacy)
    dates = ["2026-10-21T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2025-12-31T00:00:00+00:00"]
    for row, date in zip(client.tables["rides"], dates):
        row["started_at"] = date
    for row, date in zip(client.tables["climb_efforts"], dates):
        row["achieved_at"] = date
    assert [e["user_id"] for e in (await board(client, window="today"))["entries"]] == ["today"]
    assert {e["user_id"] for e in (await board(client, window="year"))["entries"]} == {"today", "year"}


@pytest.mark.asyncio
async def test_legacy_discovery_and_noncanonical_patterns_are_not_times():
    client = storage([rider("a"), rider("b")], legacy=True)
    client.tables["patterns_climb"][0]["match_trace"]["authority"] = "discovery_only"
    client.tables["patterns_climb"][1]["detector_version"] = "canonical"
    assert (await board(client))["entries"] == []


@pytest.mark.asyncio
async def test_storage_failure_is_unavailable_not_empty(monkeypatch):
    client = storage([])
    original = client.from_
    def fail(table):
        if table == "patterns_climb":
            raise RuntimeError("offline storage failure")
        return original(table)
    monkeypatch.setattr(client, "from_", fail)
    with pytest.raises(HTTPException) as error:
        await board(client)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_denied_effort_never_falls_back_to_public_legacy_gps():
    client = storage([rider("owner")])
    client.tables["canon_traversal_evidence"] = []
    assert (await board(client, OWNER))["entries"] == []
    # The same legacy path is readable only when no stored effort exists.
    client.tables["climb_efforts"] = []
    assert len((await board(client))["entries"]) == 1


@pytest.mark.asyncio
async def test_detached_legacy_pattern_does_not_break_other_riders():
    client = storage([rider("deleted"), rider("public")], legacy=True)
    client.tables["patterns_climb"][0]["activity_id"] = f"anonymous:{UUID(int=9)}"
    assert [e["user_id"] for e in (await board(client))["entries"]] == ["public"]


@pytest.mark.asyncio
async def test_mixed_pages_preserve_second_page_best_and_deduplicate():
    from app.repositories.climb_effort import ClimbEffortRepository
    # Exercise storage paging without manufacturing 501 copies of GPS evidence.
    client = storage([rider("owner")])
    stored, pattern = client.tables["climb_efforts"][0], client.tables["patterns_climb"][0]
    client.tables["climb_efforts"] = [dict(stored, id=str(UUID(int=100 + i)), time_s=200) for i in range(501)]
    client.tables["patterns_climb"] = [dict(pattern, id=str(UUID(int=100 + i)), time_s=200) for i in range(501)]
    client.tables["patterns_climb"].append(dict(pattern, id=str(UUID(int=999)), time_s=100))
    result = await ClimbEffortRepository(client).rides_efforts(CLIMB_ID)
    assert len(result) == 502 and len({r["id"] for r in result}) == 502
    pinned = (await board(client, OWNER))["viewer_entry"]
    assert pinned["best_time_seconds"] == 100 and pinned["effort_id"] is None


@pytest.mark.asyncio
async def test_active_vault_does_not_read_rides(monkeypatch):
    from backend.tests.routes.test_climb_leaderboard_privacy import _Client, CLIMB_ID as ACTIVE_ID
    client = _Client()
    monkeypatch.setattr(climbs, "load_canon_climb_runtime_states", lambda **kw: {str(ACTIVE_ID): "active"})
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    monkeypatch.setattr(climbs, "project_public_record_board", lambda *a, **kw:
                        PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None))
    original = client.from_
    def forbid(table):
        assert table not in {"patterns_climb", "climb_efforts"}
        return original(table)
    monkeypatch.setattr(client, "from_", forbid)
    result = await board(client, climb_id=str(ACTIVE_ID))
    assert result["source"] == "onchain" and result["vault_id"] == 44 and result["entries"] == []
