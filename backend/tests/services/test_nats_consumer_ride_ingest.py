from __future__ import annotations

import asyncio
import base64
import json
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest


def test_nats_recovery_factory_wires_processor_terminal_projector() -> None:
    from app.services import nats_consumer

    processor = MagicMock()
    with patch.object(nats_consumer, "_get_processor", return_value=processor):
        recovery = nats_consumer._create_ride_economic_recovery_loop()

    assert recovery.repository is processor.ride_economic_repository
    assert recovery.coordinator_factory() is processor.ride_economic_coordinator
    assert (
        recovery.terminal_projector_factory()
        is processor.ride_economic_terminal_projector
    )

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

from app.services import nats_consumer
from app.services.file_storage import FileNotFoundError as RideFileNotFoundError
from app.services.file_storage import StorageUnavailableError
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy


class FakeNatsMessage:
    def __init__(self, subject: str, payload: dict | None = None) -> None:
        self.subject = subject
        self.data = json.dumps(payload or {}).encode("utf-8")
        self.ack = AsyncMock()
        self.nak = AsyncMock()
        self.in_progress = AsyncMock()


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers: dict | None = None) -> httpx.Response:
        return self.response


class _FakeRateLimiter:
    async def wait_for_capacity(self, **_kwargs) -> bool:
        return True

    def update_from_headers(self, _headers: dict) -> None:
        return None


def _uploaded_payload(
    *,
    ride_id: str | None = None,
    user_id: str | None = None,
    file_path: str = "rides/user/ride.fit",
) -> dict:
    return {
        "ride_id": ride_id or str(uuid4()),
        "user_id": user_id or str(uuid4()),
        "wallet": "wallet-1",
        "file_type": "fit",
        "file_path": file_path,
        "user_weight_kg": 72.5,
        "source": "manual_upload_direct",
    }


def _privacy_policy() -> RidePrivacyPolicy:
    return RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_start_end",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )


@pytest.mark.asyncio
async def test_uploaded_message_downloads_file_and_runs_phased_ride_processor() -> None:
    raw_file_bytes = b"fake-fit-bytes"
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=raw_file_bytes)

    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(return_value={"status": "metrics_ready"})
    processor.process_phase2_enrichment = AsyncMock(return_value={"status": "enriched"})
    processor.process_phase3_rewards = AsyncMock(return_value={"status": "completed", "cal_earned": 102})

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
    ):
        await nats_consumer._handle_message(msg)

    storage.download_ride_file.assert_awaited_once_with(payload["file_path"])
    processor.process_phase1_core.assert_awaited_once()
    process_kwargs = processor.process_phase1_core.await_args.kwargs
    assert process_kwargs["ride_id"] == UUID(payload["ride_id"])
    assert process_kwargs["user_id"] == UUID(payload["user_id"])
    assert process_kwargs["file_type"] == "fit"
    assert process_kwargs["file_data_b64"] == base64.b64encode(raw_file_bytes).decode("utf-8")
    assert process_kwargs["file_bytes"] == raw_file_bytes
    assert process_kwargs["user_weight_kg"] == 72.5
    assert "user_ftp_w" not in process_kwargs
    processor.process_phase2_enrichment.assert_awaited_once_with(
        ride_id=UUID(payload["ride_id"]),
        user_id=UUID(payload["user_id"]),
        user_weight_kg=72.5,
    )
    processor.process_phase3_rewards.assert_awaited_once_with(
        ride_id=UUID(payload["ride_id"]),
        user_id=UUID(payload["user_id"]),
    )
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase2_status", "terminal_action"),
    (("enriched", "ack"), ("phase2_failed", "nak")),
)
async def test_slow_uploaded_delivery_heartbeats_until_terminal_ack_or_nak(
    phase2_status: str,
    terminal_action: str,
) -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    events: list[str] = []
    msg.in_progress.side_effect = lambda: events.append("in_progress")
    msg.ack.side_effect = lambda: events.append("ack")
    msg.nak.side_effect = lambda **_kwargs: events.append("nak")
    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=b"fake-fit-bytes")

    async def slow_phase1(**_kwargs):
        await asyncio.sleep(0.035)
        return {"status": "metrics_ready"}

    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(side_effect=slow_phase1)
    processor.process_phase2_enrichment = AsyncMock(
        return_value={"status": phase2_status, "error": "retry phase 2"}
    )
    processor.process_phase3_rewards = AsyncMock(
        return_value={"status": "completed", "cal_earned": 102}
    )

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
        patch.object(nats_consumer, "UPLOADED_ACK_HEARTBEAT_INTERVAL_S", 0.005),
    ):
        await nats_consumer._handle_message(msg)

    assert msg.in_progress.await_count >= 3
    assert events[-1] == terminal_action
    assert not any(
        task.get_name() == nats_consumer.UPLOADED_ACK_HEARTBEAT_TASK_NAME
        and not task.done()
        for task in asyncio.all_tasks()
    )
    if terminal_action == "ack":
        msg.ack.assert_awaited_once_with()
        msg.nak.assert_not_awaited()
    else:
        msg.ack.assert_not_awaited()
        msg.nak.assert_awaited_once_with(delay=30)


@pytest.mark.asyncio
async def test_cancelled_uploaded_delivery_stops_heartbeat_task() -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=b"fake-fit-bytes")
    blocked = asyncio.Event()

    async def blocked_phase1(**_kwargs):
        await blocked.wait()
        return {"status": "metrics_ready"}

    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(side_effect=blocked_phase1)

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
        patch.object(nats_consumer, "UPLOADED_ACK_HEARTBEAT_INTERVAL_S", 0.005),
    ):
        delivery = asyncio.create_task(nats_consumer._handle_message(msg))
        for _ in range(20):
            if msg.in_progress.await_count >= 2:
                break
            await asyncio.sleep(0.005)
        assert msg.in_progress.await_count >= 2
        delivery.cancel()
        with pytest.raises(asyncio.CancelledError):
            await delivery

    assert not any(
        task.get_name() == nats_consumer.UPLOADED_ACK_HEARTBEAT_TASK_NAME
        and not task.done()
        for task in asyncio.all_tasks()
    )
    msg.ack.assert_not_awaited()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_message_phase2_failure_does_not_run_phase3_or_ack() -> None:
    raw_file_bytes = b"fake-fit-bytes"
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=raw_file_bytes)

    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(return_value={"status": "metrics_ready"})
    processor.process_phase2_enrichment = AsyncMock(
        return_value={"status": "phase2_failed", "error": "vault match unavailable"}
    )
    processor.process_phase3_rewards = AsyncMock()

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
    ):
        await nats_consumer._handle_message(msg)

    processor.process_phase3_rewards.assert_not_awaited()
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=30)


@pytest.mark.asyncio
async def test_uploaded_message_acks_a_phase2_failure_that_cannot_succeed_on_retry() -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=b"fake-fit-bytes")
    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(return_value={"status": "metrics_ready"})
    # Phase 2 already marked the ride failed; a redelivery reads the same registry.
    processor.process_phase2_enrichment = AsyncMock(return_value={
        "status": "phase2_failed", "retryable": False,
        "error": "detect_and_store_patterns: canon registry defect: ratified canon has no corridor cells",
    })
    processor.process_phase3_rewards = AsyncMock()

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
    ):
        await nats_consumer._handle_message(msg)

    processor.process_phase3_rewards.assert_not_awaited()
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["recovery_pending", "under_review"])
async def test_uploaded_message_checkpoint_persistence_failure_naks(
    status: str,
) -> None:
    raw_file_bytes = b"fake-fit-bytes"
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=raw_file_bytes)

    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(return_value={"status": "metrics_ready"})
    processor.process_phase2_enrichment = AsyncMock(return_value={"status": "enriched"})
    processor.process_phase3_rewards = AsyncMock(
        return_value={
            "status": status,
            "durable_checkpoint": False,
            "error": "mark_review checkpoint write failed",
        }
    )

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
    ):
        await nats_consumer._handle_message(msg)

    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=30)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["recovery_pending", "under_review"])
async def test_uploaded_message_acks_only_durable_noncomplete_outcomes(
    status: str,
) -> None:
    raw_file_bytes = b"fake-fit-bytes"
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    storage = MagicMock()
    storage.download_ride_file = AsyncMock(return_value=raw_file_bytes)
    processor = MagicMock()
    processor.process_phase1_core = AsyncMock(return_value={"status": "metrics_ready"})
    processor.process_phase2_enrichment = AsyncMock(return_value={"status": "enriched"})
    processor.process_phase3_rewards = AsyncMock(
        return_value={
            "status": status,
            "durable_checkpoint": True,
            "economic_state": "attestation_confirmed",
        }
    )

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor", return_value=processor),
    ):
        await nats_consumer._handle_message(msg)

    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_message_with_missing_required_fields_acks_without_processing() -> None:
    msg = FakeNatsMessage(
        "rides.events.uploaded",
        {"ride_id": str(uuid4()), "user_id": str(uuid4())},
    )

    with patch("app.services.nats_consumer._get_processor") as get_processor:
        await nats_consumer._handle_message(msg)

    get_processor.assert_not_called()
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_message_with_invalid_uuid_acks_without_poisoning_consumer() -> None:
    msg = FakeNatsMessage(
        "rides.events.uploaded",
        _uploaded_payload(ride_id="not-a-uuid"),
    )

    with patch("app.services.nats_consumer._get_processor") as get_processor:
        await nats_consumer._handle_message(msg)

    get_processor.assert_not_called()
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_message_marks_missing_storage_file_failed_and_acks() -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(
        side_effect=RideFileNotFoundError("storage object missing")
    )
    ride_repo = MagicMock()
    ride_repo.update_ride_status = AsyncMock()

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.repositories.create_ride_repository", return_value=ride_repo),
        patch("app.services.nats_consumer._get_processor") as get_processor,
    ):
        await nats_consumer._handle_message(msg)

    storage.download_ride_file.assert_awaited_once_with(payload["file_path"])
    ride_repo.update_ride_status.assert_awaited_once_with(
        UUID(payload["ride_id"]),
        "failed",
        error_message=f"Uploaded ride file missing from storage: {payload['file_path']}",
    )
    get_processor.assert_not_called()
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploaded_message_retries_missing_file_when_failure_state_cannot_persist() -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(
        side_effect=RideFileNotFoundError("storage object missing")
    )
    ride_repo = MagicMock()
    ride_repo.update_ride_status = AsyncMock(side_effect=RuntimeError("db unavailable"))

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.repositories.create_ride_repository", return_value=ride_repo),
        patch("app.services.nats_consumer._get_processor") as get_processor,
    ):
        await nats_consumer._handle_message(msg)

    get_processor.assert_not_called()
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=30)


@pytest.mark.asyncio
async def test_uploaded_message_retries_transient_storage_failure() -> None:
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)

    storage = MagicMock()
    storage.download_ride_file = AsyncMock(
        side_effect=StorageUnavailableError("storage unavailable")
    )

    with (
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch("app.services.nats_consumer._get_processor") as get_processor,
    ):
        await nats_consumer._handle_message(msg)

    get_processor.assert_not_called()
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=30)


@pytest.mark.asyncio
async def test_strava_webhook_requeues_existing_pending_provider_ride_before_download(monkeypatch) -> None:
    activity_id = 12345
    ride_id = uuid4()
    connection_id = uuid4()
    msg = FakeNatsMessage(
        "strava.events.webhook",
        {
            "object_type": "activity",
            "aspect_type": "create",
            "owner_id": 987,
            "object_id": activity_id,
        },
    )

    connection = SimpleNamespace(
        id=connection_id,
        wallet="wallet-1",
        access_token="access-token",
    )
    strava = MagicMock()
    strava.get_connection_by_athlete_id.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.find_ride_by_hash = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_id = AsyncMock(return_value="user-1")
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})

    enqueue = AsyncMock(return_value=SimpleNamespace(accepted=True, error=None))
    response = httpx.Response(
        200,
        json={"type": "Ride"},
        request=httpx.Request("GET", "https://www.strava.com/api/v3/activities/12345"),
    )
    monkeypatch.setattr("app.services.strava_service.StravaService", lambda: strava)
    monkeypatch.setattr(
        "app.services.strava_rate_limiter.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )
    monkeypatch.setattr("app.repositories.create_ride_repository", lambda: ride_repo)
    monkeypatch.setattr("app.repositories.create_user_repository", lambda: user_repo)
    monkeypatch.setattr("app.services.provider_imports.enqueue_ride_ingest", enqueue)
    monkeypatch.setattr("httpx.AsyncClient", lambda: _FakeAsyncClient(response))

    await nats_consumer._handle_strava_webhook(msg, json.loads(msg.data))

    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.find_ride_by_hash.assert_not_awaited()
    ride_repo.resolve_ride_privacy_policy.assert_not_called()
    ride_repo.update_ride_status.assert_awaited_once_with(UUID(str(ride_id)), "processing")
    strava.mark_activity_imported.assert_called_once_with(
        connection_id=connection_id,
        strava_activity_id=activity_id,
        activity_id=str(ride_id),
    )
    enqueue_job = enqueue.await_args.args[0]
    assert enqueue_job.ride_id == str(ride_id)
    assert enqueue_job.source == "strava_webhook_retry"
    assert enqueue_job.source_id == str(activity_id)
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_strava_webhook_resolves_privacy_before_storage(monkeypatch) -> None:
    activity_id = 24680
    connection = SimpleNamespace(
        id=uuid4(),
        wallet="wallet-1",
        access_token="access-token",
    )
    diagnostics = SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": str(activity_id),
        },
    )
    strava = MagicMock()
    strava.get_connection_by_athlete_id.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", diagnostics)
    )

    events: list[str] = []
    policy = _privacy_policy()

    async def resolve_policy(*_args, **_kwargs):
        events.append("privacy_resolved")
        return policy

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(side_effect=resolve_policy)
    ride_repo.create_ride = AsyncMock()

    async def upload_file(**_kwargs):
        events.append("file_stored")
        return SimpleNamespace(
            path="rides/user-1/new.gpx",
            size_bytes=9,
            file_hash="hash-1",
        )

    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"
    storage.upload_ride_file = AsyncMock(side_effect=upload_file)

    user_repo = MagicMock()
    user_repo.get_user_id = AsyncMock(return_value="user-1")
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue = AsyncMock(return_value=SimpleNamespace(accepted=True, error=None))
    response = httpx.Response(
        200,
        json={"type": "Ride"},
        request=httpx.Request("GET", f"https://www.strava.com/api/v3/activities/{activity_id}"),
    )
    msg = FakeNatsMessage(
        "strava.events.webhook",
        {
            "object_type": "activity",
            "aspect_type": "create",
            "owner_id": 987,
            "object_id": activity_id,
        },
    )

    monkeypatch.setattr("app.services.strava_service.StravaService", lambda: strava)
    monkeypatch.setattr(
        "app.services.strava_rate_limiter.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )
    monkeypatch.setattr("app.repositories.create_ride_repository", lambda: ride_repo)
    monkeypatch.setattr("app.repositories.create_user_repository", lambda: user_repo)
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    monkeypatch.setattr("app.services.ride_ingest.enqueue_ride_ingest", enqueue)
    monkeypatch.setattr("httpx.AsyncClient", lambda: _FakeAsyncClient(response))

    await nats_consumer._handle_strava_webhook(msg, json.loads(msg.data))

    assert events == ["privacy_resolved", "file_stored"]
    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with("user-1")
    assert ride_repo.create_ride.await_args.kwargs["privacy_policy"] is policy
    msg.ack.assert_awaited_once_with()
    msg.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_strava_webhook_naks_without_storage_when_privacy_is_unavailable(monkeypatch) -> None:
    activity_id = 13579
    connection = SimpleNamespace(
        id=uuid4(),
        wallet="wallet-1",
        access_token="access-token",
    )
    diagnostics = SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {},
    )
    strava = MagicMock()
    strava.get_connection_by_athlete_id.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", diagnostics)
    )

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    ride_repo.create_ride = AsyncMock()

    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"
    storage.upload_ride_file = AsyncMock()
    user_repo = MagicMock()
    user_repo.get_user_id = AsyncMock(return_value="user-1")
    response = httpx.Response(
        200,
        json={"type": "Ride"},
        request=httpx.Request("GET", f"https://www.strava.com/api/v3/activities/{activity_id}"),
    )
    msg = FakeNatsMessage(
        "strava.events.webhook",
        {
            "object_type": "activity",
            "aspect_type": "create",
            "owner_id": 987,
            "object_id": activity_id,
        },
    )

    monkeypatch.setattr("app.services.strava_service.StravaService", lambda: strava)
    monkeypatch.setattr(
        "app.services.strava_rate_limiter.get_strava_rate_limiter",
        lambda: _FakeRateLimiter(),
    )
    monkeypatch.setattr("app.repositories.create_ride_repository", lambda: ride_repo)
    monkeypatch.setattr("app.repositories.create_user_repository", lambda: user_repo)
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    monkeypatch.setattr("httpx.AsyncClient", lambda: _FakeAsyncClient(response))

    await nats_consumer._handle_strava_webhook(msg, json.loads(msg.data))

    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    storage.upload_ride_file.assert_not_awaited()
    ride_repo.create_ride.assert_not_awaited()
    msg.ack.assert_not_awaited()
    msg.nak.assert_awaited_once_with(delay=60)
