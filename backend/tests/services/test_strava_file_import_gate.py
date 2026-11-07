from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

from app import config
from app import tasks as celery_tasks
from app.config import StravaSettings
from app.routes import strava as strava_routes
from app.services import nats_consumer
from app.services import strava_monitoring
from app.services.strava_monitoring import _health_status
from app.services.strava_service import StravaNotConfiguredError, StravaService


class _WebhookRequest:
    async def json(self) -> dict:
        return {
            "object_type": "activity",
            "aspect_type": "create",
            "owner_id": 123,
            "object_id": 456,
            "subscription_id": 333340,
        }


class _NatsMessage:
    def __init__(self) -> None:
        self.subject = "strava.events.webhook"
        self.data = json.dumps(
            {
                "object_type": "activity",
                "aspect_type": "create",
                "owner_id": 123,
                "object_id": 456,
            }
        ).encode("utf-8")
        self.acked = False
        self.naks: list[int | None] = []

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: int | None = None) -> None:
        self.naks.append(delay)


def _settings(*, sync_enabled: bool) -> StravaSettings:
    return StravaSettings(
        client_id="123",
        client_secret="secret",
        enabled=True,
        sync_enabled=sync_enabled,
    )


def test_strava_sync_is_fail_closed_unless_explicitly_enabled(monkeypatch) -> None:
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    monkeypatch.delenv("STRAVA_SYNC_ENABLED", raising=False)
    config.load_strava_settings.cache_clear()

    assert config.load_strava_settings().sync_enabled is False

    monkeypatch.setenv("STRAVA_SYNC_ENABLED", "true")
    config.load_strava_settings.cache_clear()
    assert config.load_strava_settings().sync_enabled is True
    config.load_strava_settings.cache_clear()


def test_rider_sync_routes_return_file_import_only_error(monkeypatch) -> None:
    monkeypatch.setattr(
        strava_routes,
        "load_strava_settings",
        lambda: _settings(sync_enabled=False),
    )

    with pytest.raises(strava_routes.StravaError) as excinfo:
        strava_routes._require_strava_sync_enabled()

    assert excinfo.value.status_code == 410
    assert excinfo.value.detail["error"]["code"] == "strava_file_import_only"


@pytest.mark.asyncio
async def test_service_rejects_fresh_tokens_when_sync_is_retired() -> None:
    service = StravaService(db=object(), settings=_settings(sync_enabled=False))
    connection = SimpleNamespace(
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        wallet="wallet-1",
    )

    with pytest.raises(StravaNotConfiguredError, match="file-import-only"):
        await service.ensure_valid_token(connection)


@pytest.mark.asyncio
async def test_disabled_webhook_is_acked_without_database_or_nats_work(monkeypatch) -> None:
    monkeypatch.setattr(
        strava_routes,
        "load_strava_settings",
        lambda: _settings(sync_enabled=False),
    )
    monkeypatch.setattr(
        strava_routes,
        "get_supabase_client",
        lambda: (_ for _ in ()).throw(AssertionError("database should not be read")),
    )

    result = await strava_routes.strava_webhook_event(_WebhookRequest())

    assert result == {"status": "ignored", "reason": "file_import_only"}


@pytest.mark.asyncio
async def test_disabled_consumer_acks_residual_strava_messages_without_processing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        nats_consumer,
        "load_strava_settings",
        lambda: _settings(sync_enabled=False),
    )
    monkeypatch.setattr(
        nats_consumer,
        "_handle_strava_webhook",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("webhook payload should not be processed")
        ),
    )
    msg = _NatsMessage()

    await nats_consumer._handle_strava_message(msg)

    assert msg.acked is True
    assert msg.naks == []


def test_file_import_only_health_is_green_only_after_cutover_is_empty() -> None:
    assert _health_status(
        provider_configured=False,
        sync_enabled=False,
        subscription_active=False,
        active_connections=0,
        alerts=[],
    ) == "HEALTHY"
    assert _health_status(
        provider_configured=True,
        sync_enabled=False,
        subscription_active=True,
        active_connections=0,
        alerts=["Webhook subscription remains active."],
    ) == "WARNING"


@pytest.mark.asyncio
async def test_file_import_only_health_warns_when_cutover_state_cannot_be_read(
    monkeypatch,
) -> None:
    gauge_updates: list[str] = []

    class _BrokenDatabase:
        def table(self, _name: str):
            raise RuntimeError("database unavailable")

    class _RateLimiter:
        def snapshot(self) -> dict:
            return {
                "storage": "memory",
                "limit_15min": 0,
                "usage_15min": 0,
                "limit_daily": 0,
                "usage_daily": 0,
            }

    monkeypatch.setattr(
        strava_monitoring,
        "load_strava_settings",
        lambda: _settings(sync_enabled=False),
    )
    monkeypatch.setattr(
        strava_monitoring,
        "get_supabase_client",
        lambda: _BrokenDatabase(),
    )
    monkeypatch.setattr(
        strava_monitoring,
        "get_strava_rate_limiter",
        lambda: _RateLimiter(),
    )
    monkeypatch.setattr(
        strava_monitoring,
        "set_strava_subscription_active",
        lambda _active: gauge_updates.append("subscription"),
    )
    monkeypatch.setattr(
        strava_monitoring,
        "set_strava_connection_state",
        lambda **_kwargs: gauge_updates.append("connections"),
    )

    snapshot = await strava_monitoring.get_strava_health_snapshot()

    assert snapshot["health_status"] == "WARNING"
    assert snapshot["state_verified"] is False
    assert "Unable to verify Strava cutover state." in snapshot["alerts"]
    assert gauge_updates == []


def test_disabled_legacy_celery_strava_tasks_stop_before_queue_or_provider_work(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        celery_tasks,
        "load_strava_settings",
        lambda: _settings(sync_enabled=False),
        raising=False,
    )
    monkeypatch.setattr(
        celery_tasks,
        "_update_queue_depth",
        lambda: (_ for _ in ()).throw(
            AssertionError("disabled Strava tasks must not touch queue infrastructure")
        ),
    )

    webhook_result = celery_tasks.process_strava_webhook_event.run(
        object_type="activity",
        aspect_type="create",
        owner_id=123,
        object_id=456,
    )
    history_result = celery_tasks.backfill_strava_history.run(
        connection_id="00000000-0000-0000-0000-000000000001"
    )
    catchup_result = celery_tasks.backfill_strava_incomplete.run()

    assert webhook_result == {"action": "ignored", "reason": "file_import_only"}
    assert history_result == {"status": "skipped", "reason": "file_import_only"}
    assert catchup_result == {"queued": 0, "reason": "file_import_only"}
