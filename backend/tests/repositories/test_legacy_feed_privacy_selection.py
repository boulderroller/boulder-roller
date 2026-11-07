from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.repositories_legacy import SupabaseRepository
from app.routes.feed import _route_preview_points_for_feed
from app.services.privacy_resolver import resolve_ride_visibility


class _RideSelectionQuery:
    def __init__(self, ride: dict[str, Any]) -> None:
        self.ride = ride
        self.selection = ""

    def select(self, selection: str) -> "_RideSelectionQuery":
        self.selection = selection
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_RideSelectionQuery":
        return self

    def neq(self, *_args: Any, **_kwargs: Any) -> "_RideSelectionQuery":
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> "_RideSelectionQuery":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_RideSelectionQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_RideSelectionQuery":
        return self

    def execute(self) -> SimpleNamespace:
        selected_fields = {
            field.strip()
            for field in self.selection.split(",")
            if field.strip()
        }
        return SimpleNamespace(
            data=[
                {
                    key: value
                    for key, value in self.ride.items()
                    if key in selected_fields
                }
            ]
        )


class _RideSelectionClient:
    def __init__(self, ride: dict[str, Any]) -> None:
        self.query = _RideSelectionQuery(ride)

    def table(self, name: str) -> _RideSelectionQuery:
        assert name == "rides"
        return self.query


class _PrivacyZoneQuery:
    def select(self, *_args: Any, **_kwargs: Any) -> "_PrivacyZoneQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_PrivacyZoneQuery":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=[])


class _NoPrivacyZoneRepo:
    def __init__(self) -> None:
        self._client = SimpleNamespace(table=lambda _name: _PrivacyZoneQuery())

    async def _run(self, func: Any) -> Any:
        return func()


class _ActivitySelectionQuery:
    deployed_columns = {
        "id",
        "user_id",
        "activity_type",
        "title",
        "description",
        "target_type",
        "target_id",
        "metadata",
        "created_at",
        "occurred_at",
        "event_type",
        "actor_id",
        "visibility",
        "schema_version",
        "kudos_count",
    }

    def select(self, selection: str) -> "_ActivitySelectionQuery":
        selected = {field.strip() for field in selection.split(",") if field.strip()}
        unknown = selected - self.deployed_columns
        assert not unknown, f"Following feed selected undeployed activity columns: {sorted(unknown)}"
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=[])


class _ActivitySelectionClient:
    def table(self, name: str) -> _ActivitySelectionQuery:
        assert name == "activities"
        return _ActivitySelectionQuery()


@pytest.mark.asyncio
async def test_following_feed_legacy_activity_query_uses_deployed_columns() -> None:
    repo = SupabaseRepository(_ActivitySelectionClient())  # type: ignore[arg-type]

    assert await repo.get_feed_activities(["followed-user"], limit=15) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query_name",
    ("global", "following", "public_profile"),
)
async def test_feed_queries_retain_valid_endpoint_map_projection(query_name: str) -> None:
    ride = {
        "id": "ride-hide-endpoints",
        "user_id": "owner-user",
        "file_name": "Endpoint privacy.gpx",
        "processing_status": "completed",
        "started_at": "2026-08-02T12:00:00Z",
        "created_at": "2026-08-02T12:00:00Z",
        "visibility": "public",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 200,
        "map_hide_end_m": 200,
        "moderation_state": "visible",
        "gps_track": [
            {"latitude": 40.000, "longitude": -75.000},
            {"latitude": 40.003, "longitude": -75.000},
            {"latitude": 40.006, "longitude": -75.000},
            {"latitude": 40.009, "longitude": -75.000},
            {"latitude": 40.012, "longitude": -75.000},
        ],
    }
    client = _RideSelectionClient(ride)
    repo = SupabaseRepository(client)  # type: ignore[arg-type]

    if query_name == "global":
        rows = await repo.get_global_rides(limit=5)
    elif query_name == "following":
        rows = await repo.get_feed_rides(["owner-user"], limit=5)
    else:
        rows = await repo.get_public_user_recent_rides("owner-user", limit=5)

    selected_ride = rows[0]
    decision = await resolve_ride_visibility(
        selected_ride,
        None,
        owner_profile={"id": "owner-user", "moderation_state": "visible"},
    )
    projected = await _route_preview_points_for_feed(
        selected_ride,
        decision.to_client_dict(),
        _NoPrivacyZoneRepo(),  # type: ignore[arg-type]
    )

    assert decision.map_visibility == "hide_start_end"
    assert decision.map_hide_start_m == 200
    assert decision.map_hide_end_m == 200
    assert projected is not None
    projected_points, _projected_zones = projected
    assert [point.get("redacted", False) for point in projected_points] == [
        True,
        False,
        False,
        False,
        True,
    ]


class _ActivitySelectionQuery:
    deployed_columns = {
        "id",
        "user_id",
        "activity_type",
        "title",
        "description",
        "target_type",
        "target_id",
        "metadata",
        "created_at",
        "occurred_at",
        "event_type",
        "actor_id",
        "visibility",
        "schema_version",
        "kudos_count",
    }

    def select(self, selection: str) -> "_ActivitySelectionQuery":
        selected = {field.strip() for field in selection.split(",") if field.strip()}
        unknown = selected - self.deployed_columns
        assert not unknown, f"Following feed selected undeployed activity columns: {sorted(unknown)}"
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_ActivitySelectionQuery":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=[])


class _ActivitySelectionClient:
    def table(self, name: str) -> _ActivitySelectionQuery:
        assert name == "activities"
        return _ActivitySelectionQuery()


@pytest.mark.asyncio
async def test_following_feed_legacy_activity_query_uses_deployed_columns() -> None:
    repo = SupabaseRepository(_ActivitySelectionClient())  # type: ignore[arg-type]

    assert await repo.get_feed_activities(["followed-user"], limit=15) == []
