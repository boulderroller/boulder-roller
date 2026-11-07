from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

import app.routes.climbs as climb_routes
from app.services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    PublicRecordBoardProjection,
)


CLIMB_ID = UUID("11111111-1111-1111-1111-111111111111")


class _Query:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = [dict(row) for row in rows]

    def select(self, _columns: str) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._rows = [
            row for row in self._rows if str(row.get(column)) == str(value)
        ]
        return self

    def in_(self, column: str, values: list[Any]) -> "_Query":
        allowed = {str(value) for value in values}
        self._rows = [
            row for row in self._rows if str(row.get(column)) in allowed
        ]
        return self

    def limit(self, limit: int) -> "_Query":
        self._rows = self._rows[:limit]
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._rows)


class _Client:
    def __init__(self) -> None:
        self.tables = {
            "canon_climbs": [
                {
                    "id": str(CLIMB_ID),
                    "display_name": "Privacy Hill",
                    "status": "ratified",
                }
            ],
            "indexed_climbs": [
                {
                    "pda": "climb-pda",
                    "canon_climb_id": str(CLIMB_ID),
                    "vault_pda": "vault-pda",
                    "quarantined": False,
                }
            ],
            "indexed_vaults": [
                {
                    "id": 44,
                    "pda": "vault-pda",
                    "name": "Privacy Hill",
                    "signature_hex": "ab" * 64,
                    "kom_holder": "private-winner",
                    "kom_time_s": 60,
                    "climb_pda": "climb-pda",
                    "canon_binding_status": "active",
                }
            ],
            "indexed_leaderboards": [
                {
                    "vault_id": 44,
                    "entries": [
                        {
                            "user": "private-winner",
                            "time_s": 60,
                            "recorded_at": 1000,
                        },
                        {
                            "user": "public-second",
                            "time_s": 70,
                            "recorded_at": 2000,
                        },
                    ],
                }
            ],
        }

    def from_(self, table: str) -> _Query:
        return _Query(self.tables.get(table, []))


@pytest.mark.asyncio
async def test_canonical_route_uses_privacy_projection_without_reranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    monkeypatch.setattr(
        climb_routes,
        "load_canon_climb_runtime_states",
        lambda **_kwargs: {str(CLIMB_ID): "active"},
    )
    projected_second = {
        "user": "public-second",
        "time_s": 70,
        "recorded_at": 2000,
        "position": 2,
        "rank": 2,
        "tie_size": 1,
        "is_tied": False,
    }
    calls: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    def _projector(
        _client: Any,
        *,
        vault_row: dict[str, Any],
        raw_entries: list[dict[str, Any]],
    ) -> PublicRecordBoardProjection:
        calls.append((dict(vault_row), [dict(entry) for entry in raw_entries]))
        return PublicRecordBoardProjection(
            entries=[projected_second],
            kom_holder=None,
            kom_time_s=None,
        )

    monkeypatch.setattr(
        climb_routes,
        "project_public_record_board",
        _projector,
        raising=False,
    )

    response = await climb_routes.get_climb_leaderboard(
        climb_id=str(CLIMB_ID),
        repo=SimpleNamespace(client=client),
    )

    assert len(calls) == 1
    assert calls[0][0]["pda"] == "vault-pda"
    assert [entry["wallet"] for entry in response["entries"]] == ["public-second"]
    assert response["entries"][0]["position"] == 2
    assert response["entries"][0]["rank"] == 2
    assert response["kom_holder"] is None
    assert response["kom_time_s"] is None
    assert response["truth_source"] == "projected"


@pytest.mark.asyncio
async def test_canonical_route_returns_503_when_privacy_projection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    monkeypatch.setattr(
        climb_routes,
        "load_canon_climb_runtime_states",
        lambda **_kwargs: {str(CLIMB_ID): "active"},
    )

    def _unavailable(*_args: Any, **_kwargs: Any) -> PublicRecordBoardProjection:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    monkeypatch.setattr(
        climb_routes,
        "project_public_record_board",
        _unavailable,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await climb_routes.get_climb_leaderboard(
            climb_id=str(CLIMB_ID),
            repo=SimpleNamespace(client=client),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Public Record Board privacy projection is temporarily unavailable"
    )


@pytest.mark.asyncio
async def test_legacy_segment_route_uses_same_privacy_projection_without_refill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    projected_second = {
        "user": "public-second",
        "time_s": 70,
        "recorded_at": 2000,
        "position": 2,
        "rank": 2,
        "tie_size": 1,
        "is_tied": False,
    }
    calls: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []

    def _projector(
        _client: Any,
        *,
        vault_row: dict[str, Any],
        raw_entries: list[dict[str, Any]],
    ) -> PublicRecordBoardProjection:
        calls.append((dict(vault_row), [dict(entry) for entry in raw_entries]))
        return PublicRecordBoardProjection(
            entries=[projected_second],
            kom_holder=None,
            kom_time_s=None,
        )

    monkeypatch.setattr(
        climb_routes,
        "project_public_record_board",
        _projector,
        raising=False,
    )

    response = await climb_routes.get_climb_leaderboard(
        climb_id="44",
        request=SimpleNamespace(
            url=SimpleNamespace(path="/segments/44/leaderboard")
        ),
        repo=SimpleNamespace(client=client),
    )

    assert len(calls) == 1
    assert calls[0][0]["pda"] == "vault-pda"
    assert [entry["wallet"] for entry in response["entries"]] == ["public-second"]
    assert response["entries"][0]["position"] == 2
    assert response["entries"][0]["rank"] == 2
    assert response["kom_holder"] is None
    assert response["kom_time_s"] is None
    assert response["truth_source"] == "projected"


@pytest.mark.asyncio
async def test_legacy_segment_route_fails_closed_when_privacy_projection_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()

    def _unavailable(*_args: Any, **_kwargs: Any) -> PublicRecordBoardProjection:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    monkeypatch.setattr(
        climb_routes,
        "project_public_record_board",
        _unavailable,
        raising=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await climb_routes.get_climb_leaderboard(
            climb_id="44",
            request=SimpleNamespace(
                url=SimpleNamespace(path="/segments/44/leaderboard")
            ),
            repo=SimpleNamespace(client=client),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Public Record Board privacy projection is temporarily unavailable"
    )
