from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

fake_nats = types.ModuleType("nats")
fake_nats.connect = AsyncMock()
fake_nats.js = types.SimpleNamespace(
    errors=types.SimpleNamespace(NotFoundError=Exception),
)
fake_nats_aio = types.ModuleType("nats.aio")
fake_nats_aio_client = types.ModuleType("nats.aio.client")
fake_nats_aio_client.Client = object
fake_nats_js = types.ModuleType("nats.js")
fake_nats_js.JetStreamContext = object

sys.modules.setdefault("nats", fake_nats)
sys.modules.setdefault("nats.aio", fake_nats_aio)
sys.modules.setdefault("nats.aio.client", fake_nats_aio_client)
sys.modules.setdefault("nats.js", fake_nats_js)

from app.services.ride_ingest import RideIngestJob, enqueue_ride_ingest


def _job() -> RideIngestJob:
    return RideIngestJob(
        ride_id="ride-1",
        user_id="user-1",
        wallet="wallet-1",
        file_type="fit",
        file_path="rides/user-1/ride-1.fit",
        user_weight_kg=72.5,
        source="manual_upload_direct",
    )


@pytest.mark.asyncio
async def test_enqueue_ride_ingest_prefers_nats() -> None:
    client = MagicMock()
    client.publish = AsyncMock(return_value=True)

    with patch("app.services.ride_ingest.get_nats_client", return_value=client):
        result = await enqueue_ride_ingest(_job())

    assert result.accepted is True
    assert result.backend == "nats"
    client.publish.assert_awaited_once()
    assert "user_ftp_w" not in client.publish.await_args.args[1]


@pytest.mark.asyncio
async def test_enqueue_ride_ingest_reports_failure_when_nats_unavailable() -> None:
    """When NATS publish fails, the job is rejected (no Celery fallback)."""
    client = MagicMock()
    client.publish = AsyncMock(return_value=False)

    with patch("app.services.ride_ingest.get_nats_client", return_value=client):
        result = await enqueue_ride_ingest(_job())

    assert result.accepted is False
    assert result.backend == "nats"
    assert result.error is not None
