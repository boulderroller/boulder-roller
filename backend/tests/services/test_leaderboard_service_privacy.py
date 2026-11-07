from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from app.services.leaderboard_service import (
    LeaderboardMetric,
    LeaderboardPeriod,
    LeaderboardService,
    _profile_allows_public_leaderboard,
    _ride_allows_public_leaderboard,
)


class _Query:
    def __init__(self, client: "_Client", table: str) -> None:
        self._client = client
        self._table = table
        self._rows = deepcopy(client.tables.get(table, []))

    @property
    def not_(self) -> "_Query":
        return self

    def select(self, _columns: str, **_kwargs: Any) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._rows = [row for row in self._rows if str(row.get(column)) == str(value)]
        return self

    def in_(self, column: str, values: list[Any]) -> "_Query":
        allowed = {str(value) for value in values}
        self._rows = [row for row in self._rows if str(row.get(column)) in allowed]
        return self

    def is_(self, column: str, value: str) -> "_Query":
        if value == "null":
            self._rows = [row for row in self._rows if row.get(column) is not None]
        return self

    def gt(self, column: str, value: Any) -> "_Query":
        self._rows = [
            row
            for row in self._rows
            if row.get(column) is not None and row[column] > value
        ]
        return self

    def gte(self, column: str, value: Any) -> "_Query":
        self._rows = [
            row
            for row in self._rows
            if row.get(column) is not None and row[column] >= value
        ]
        return self

    def order(self, column: str, *, desc: bool = False) -> "_Query":
        self._rows.sort(key=lambda row: row.get(column) or 0, reverse=desc)
        return self

    def limit(self, limit: int) -> "_Query":
        self._rows = self._rows[:limit]
        return self

    def execute(self) -> SimpleNamespace:
        if self._table in self._client.unavailable_tables:
            return SimpleNamespace(data=None)
        return SimpleNamespace(data=deepcopy(self._rows))


class _Client:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.unavailable_tables: set[str] = set()

    def table(self, table: str) -> _Query:
        return _Query(self, table)


class _Repo:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._client = _Client(tables)

    async def _run(self, operation):
        return operation()


def _route_points() -> list[dict[str, Any]]:
    return [
        {
            "latitude": 40.0,
            "longitude": -75.0 + index * 0.001,
            "timestamp": index * 10,
        }
        for index in range(11)
    ]


def _tables(
    *,
    patterns: list[dict[str, Any]],
    map_visibility: str = "hide_start_end",
    map_hide_start_m: int = 200,
    map_hide_end_m: int = 200,
    zones: Optional[list[dict[str, Any]]] = None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "patterns_climb": patterns,
        "rides": [
            {
                "id": "ride-1",
                "user_id": "user-1",
                "visibility": "public",
                "map_visibility": map_visibility,
                "map_hide_start_m": map_hide_start_m,
                "map_hide_end_m": map_hide_end_m,
                "hide_from_leaderboards": False,
                "moderation_state": "visible",
                "gps_track": _route_points(),
            }
        ],
        "users": [
            {
                "id": "user-1",
                "wallet": "wallet-1",
                "is_public": True,
                "moderation_state": "visible",
                "username": "Rider",
            }
        ],
        "privacy_zones": zones or [],
    }


def _pattern(
    pattern_id: str,
    *,
    start_offset_s: int,
    end_offset_s: int,
    w_per_kg: float,
) -> dict[str, Any]:
    return {
        "id": pattern_id,
        "activity_id": "ride-1",
        "wallet": "wallet-1",
        "vert_m": 50,
        "time_s": end_offset_s - start_offset_s,
        "w_per_kg": w_per_kg,
        "avg_power_w": 300,
        "start_offset_s": start_offset_s,
        "end_offset_s": end_offset_s,
        "created_at": "2026-08-02T12:00:00+00:00",
    }


def test_public_leaderboard_excludes_opted_out_and_non_public_rides() -> None:
    assert _ride_allows_public_leaderboard({
        "visibility": "public",
        "hide_from_leaderboards": False,
        "moderation_state": "visible",
    })
    assert not _ride_allows_public_leaderboard({
        "visibility": "public",
        "hide_from_leaderboards": True,
        "moderation_state": "visible",
    })
    assert not _ride_allows_public_leaderboard({
        "visibility": "followers",
        "hide_from_leaderboards": False,
        "moderation_state": "visible",
    })
    assert not _ride_allows_public_leaderboard({
        "visibility": "public",
        "hide_from_leaderboards": False,
        "moderation_state": "hidden",
    })
    assert not _ride_allows_public_leaderboard({
        "hide_from_leaderboards": False,
        "moderation_state": "visible",
    })
    assert not _ride_allows_public_leaderboard({
        "visibility": "public",
        "moderation_state": "visible",
    })
    assert not _ride_allows_public_leaderboard({
        "visibility": "public",
        "hide_from_leaderboards": False,
    })


def test_public_leaderboard_excludes_private_or_moderated_profiles() -> None:
    assert _profile_allows_public_leaderboard({
        "is_public": True,
        "moderation_state": "visible",
    })
    assert not _profile_allows_public_leaderboard({
        "is_public": False,
        "moderation_state": "visible",
    })
    assert not _profile_allows_public_leaderboard({
        "is_public": True,
        "moderation_state": "removed",
    })
    assert not _profile_allows_public_leaderboard({
        "moderation_state": "visible",
    })
    assert not _profile_allows_public_leaderboard({
        "is_public": True,
    })


@pytest.mark.asyncio
async def test_climb_leaderboard_excludes_hidden_endpoint_span_but_keeps_visible_span() -> None:
    repo = _Repo(
        _tables(
            patterns=[
                _pattern("hidden-start", start_offset_s=0, end_offset_s=10, w_per_kg=5.0),
                _pattern("visible-middle", start_offset_s=30, end_offset_s=40, w_per_kg=4.0),
            ]
        )
    )
    response = await LeaderboardService(repo).get_climb_leaderboard(
        metric=LeaderboardMetric.W_PER_KG,
        period=LeaderboardPeriod.ALL_TIME,
    )

    assert [entry.pattern_id for entry in response.entries] == ["visible-middle"]
    assert response.total_count == 1


@pytest.mark.asyncio
async def test_climb_leaderboard_excludes_span_intersecting_privacy_zone() -> None:
    repo = _Repo(
        _tables(
            patterns=[
                _pattern("zoned", start_offset_s=20, end_offset_s=40, w_per_kg=5.0),
            ],
            map_visibility="show_all",
            map_hide_start_m=0,
            map_hide_end_m=0,
            zones=[
                {
                    "user_id": "user-1",
                    "latitude": 40.0,
                    "longitude": -74.997,
                    "radius_m": 200,
                }
            ],
        )
    )
    response = await LeaderboardService(repo).get_climb_leaderboard(
        metric=LeaderboardMetric.W_PER_KG,
        period=LeaderboardPeriod.ALL_TIME,
    )

    assert response.entries == []
    assert response.total_count == 0


@pytest.mark.asyncio
async def test_public_leaderboard_does_not_reuse_entry_after_ride_becomes_private() -> None:
    repo = _Repo(
        _tables(
            patterns=[
                _pattern("visible-middle", start_offset_s=30, end_offset_s=40, w_per_kg=4.0),
            ]
        )
    )
    service = LeaderboardService(repo)
    first = await service.get_climb_leaderboard(
        metric=LeaderboardMetric.W_PER_KG,
        period=LeaderboardPeriod.ALL_TIME,
    )
    assert [entry.pattern_id for entry in first.entries] == ["visible-middle"]

    repo._client.tables["rides"][0]["visibility"] = "private"
    second = await service.get_climb_leaderboard(
        metric=LeaderboardMetric.W_PER_KG,
        period=LeaderboardPeriod.ALL_TIME,
    )

    assert second.entries == []
    assert second.total_count == 0


@pytest.mark.asyncio
async def test_public_leaderboard_reports_unavailable_privacy_query_instead_of_empty_success(
) -> None:
    repo = _Repo(
        _tables(
            patterns=[
                _pattern("visible-middle", start_offset_s=30, end_offset_s=40, w_per_kg=4.0),
            ]
        )
    )
    repo._client.unavailable_tables.add("rides")

    with pytest.raises(RuntimeError, match="public leaderboard privacy projection unavailable"):
        await LeaderboardService(repo).get_climb_leaderboard(
            metric=LeaderboardMetric.W_PER_KG,
            period=LeaderboardPeriod.ALL_TIME,
        )
