from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from app.services import nats_consumer
from app.services.strava_service import (
    StravaAPIError,
    StravaConnection,
    StravaRevocationError,
    StravaService,
)


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers or {}})
        return self.response


class _FakeRateLimiter:
    def update_from_headers(self, _headers: dict) -> None:
        return None


class _FakeMsg:
    def __init__(self) -> None:
        self.acked = False
        self.naks: list[int | None] = []

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: int | None = None) -> None:
        self.naks.append(delay)


def _response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_body or {},
        request=httpx.Request("GET", "https://www.strava.com/api/v3/athlete"),
    )


def _connection() -> StravaConnection:
    return StravaConnection(
        id=uuid4(),
        wallet="Wallet1111111111111111111111111111111111",
        strava_athlete_id=12345,
        athlete_username="rider",
        athlete_firstname="Test",
        athlete_lastname="Rider",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="activity:read_all",
        connected_at=datetime.now(timezone.utc),
        last_sync_at=None,
        is_active=True,
    )


def _enabled_service() -> StravaService:
    service = StravaService.__new__(StravaService)
    service.settings = SimpleNamespace(enabled=True, sync_enabled=True)
    return service


@pytest.mark.asyncio
async def test_confirm_external_revocation_ignores_unconfirmed_webhook(monkeypatch) -> None:
    client = _FakeAsyncClient(_response(200, {"id": 12345}))
    service = _enabled_service()
    service._handle_external_revocation = AsyncMock()
    service._record_request_metric = Mock()

    monkeypatch.setattr("app.services.strava_service.httpx.AsyncClient", lambda: client)
    monkeypatch.setattr(
        "app.services.strava_service.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )

    revoked = await service.confirm_external_revocation(_connection())

    assert revoked is False
    service._handle_external_revocation.assert_not_awaited()
    assert client.calls[0]["headers"]["Authorization"] == "Bearer access-token"


@pytest.mark.asyncio
async def test_confirm_external_revocation_marks_revoked_after_strava_rejects_token(monkeypatch) -> None:
    client = _FakeAsyncClient(_response(401))
    service = _enabled_service()
    service._handle_external_revocation = AsyncMock()
    service._record_request_metric = Mock()

    monkeypatch.setattr("app.services.strava_service.httpx.AsyncClient", lambda: client)
    monkeypatch.setattr(
        "app.services.strava_service.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )

    connection = _connection()
    revoked = await service.confirm_external_revocation(connection)

    assert revoked is True
    service._handle_external_revocation.assert_awaited_once_with(connection)


@pytest.mark.asyncio
async def test_confirm_external_revocation_uses_existing_refresh_failure_signal() -> None:
    service = _enabled_service()
    service.ensure_valid_token = AsyncMock(side_effect=StravaRevocationError("revoked"))

    revoked = await service.confirm_external_revocation(_connection())

    assert revoked is True


@pytest.mark.asyncio
async def test_confirm_external_revocation_retries_transient_verification_errors(monkeypatch) -> None:
    client = _FakeAsyncClient(_response(503))
    service = _enabled_service()
    service._record_request_metric = Mock()

    monkeypatch.setattr("app.services.strava_service.httpx.AsyncClient", lambda: client)
    monkeypatch.setattr(
        "app.services.strava_service.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )

    with pytest.raises(StravaAPIError):
        await service.confirm_external_revocation(_connection())


@pytest.mark.asyncio
async def test_deauthorize_webhook_confirms_before_ack(monkeypatch) -> None:
    connection = SimpleNamespace(strava_athlete_id=12345)

    class FakeStravaService:
        def __init__(self) -> None:
            self.confirm_external_revocation = AsyncMock(return_value=True)

        def get_connection_by_athlete_id(self, athlete_id: int):
            assert athlete_id == 12345
            return connection

    fake_service = FakeStravaService()
    monkeypatch.setattr(
        "app.services.strava_service.StravaService",
        lambda: fake_service,
    )

    msg = _FakeMsg()
    await nats_consumer._handle_strava_webhook(
        msg,
        {
            "object_type": "athlete",
            "aspect_type": "deauthorize",
            "owner_id": 12345,
            "object_id": 12345,
        },
    )

    assert msg.acked is True
    assert msg.naks == []
    fake_service.confirm_external_revocation.assert_awaited_once_with(connection)


@pytest.mark.asyncio
async def test_deauthorize_webhook_does_not_disable_unconfirmed_connection(monkeypatch) -> None:
    connection = SimpleNamespace(strava_athlete_id=12345)

    class FakeStravaService:
        def __init__(self) -> None:
            self.confirm_external_revocation = AsyncMock(return_value=False)

        def get_connection_by_athlete_id(self, athlete_id: int):
            assert athlete_id == 12345
            return connection

    fake_service = FakeStravaService()
    monkeypatch.setattr(
        "app.services.strava_service.StravaService",
        lambda: fake_service,
    )

    msg = _FakeMsg()
    await nats_consumer._handle_strava_webhook(
        msg,
        {
            "object_type": "athlete",
            "aspect_type": "deauthorize",
            "owner_id": 12345,
            "object_id": 12345,
        },
    )

    assert msg.acked is True
    assert msg.naks == []
    fake_service.confirm_external_revocation.assert_awaited_once_with(connection)
