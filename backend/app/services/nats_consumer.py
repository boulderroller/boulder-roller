"""
NATS JetStream consumer for ride processing events and Strava webhooks.

Subscribes to rides.events.> and strava.events.> and processes them.
Also runs a periodic stale-ride cleanup loop (replaces Celery beat task).

This consumer handles the canonical ride-processing queue. Celery/Redis
are no longer required.

Run standalone:
    python -m app.services.nats_consumer

Or import and start within the FastAPI lifespan:
    from .nats_consumer import start_consumer, stop_consumer
"""
from __future__ import annotations

from .privacy_logging import scrub_log_text
import asyncio
import base64
import json
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..config import load_strava_settings
from .nats_client import get_nats_client, close_nats_client

logger = logging.getLogger(__name__)

# Consumer configuration
SUBSCRIBE_SUBJECT = "rides.events.>"
QUEUE_GROUP = "ride-workers"
DURABLE_NAME = "ride-workers"

# Strava webhook consumer configuration
STRAVA_SUBSCRIBE_SUBJECT = "strava.events.>"
STRAVA_QUEUE_GROUP = "strava-workers"
STRAVA_DURABLE_NAME = "strava-workers"

# Stale ride cleanup interval (seconds)
STALE_CLEANUP_INTERVAL = 600  # 10 minutes
# Renew at one-third of JetStream's default 30-second AckWait.
UPLOADED_ACK_HEARTBEAT_INTERVAL_S = 10.0
UPLOADED_ACK_HEARTBEAT_TASK_NAME = "nats-uploaded-ride-heartbeat"

# Module-level RideProcessor instance (lazy-initialized once)
_processor = None

# Background task handle for stale ride cleanup
_stale_cleanup_task: asyncio.Task | None = None
_ride_economic_recovery_task: asyncio.Task | None = None
_training_runtime = None


class _UploadedRideMessage:
    """Keep a long JetStream delivery alive until its terminal ACK or NAK."""

    def __init__(self, msg) -> None:
        self._msg = msg
        self._heartbeat_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat(),
                name=UPLOADED_ACK_HEARTBEAT_TASK_NAME,
            )

    async def stop(self) -> None:
        task = self._heartbeat_task
        if task is None:
            return
        self._heartbeat_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def ack(self) -> None:
        await self.stop()
        await self._msg.ack()

    async def nak(self, *args, **kwargs) -> None:
        await self.stop()
        await self._msg.nak(*args, **kwargs)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(UPLOADED_ACK_HEARTBEAT_INTERVAL_S)
            try:
                await self._msg.in_progress()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "[NATSConsumer] Failed to extend uploaded ride AckWait: %s",
                    exc,
                )


def _get_processor():
    """Return a module-level RideProcessor singleton (lazy init)."""
    global _processor
    if _processor is None:
        from .ride_processor import RideProcessor
        _processor = RideProcessor()
        logger.info("[NATSConsumer] RideProcessor initialized")
    return _processor


def _create_ride_economic_recovery_loop():
    from .ride_economic_recovery import RideEconomicRecoveryLoop

    processor = _get_processor()
    return RideEconomicRecoveryLoop(
        repository=processor.ride_economic_repository,
        coordinator_factory=lambda: processor.ride_economic_coordinator,
        terminal_projector_factory=lambda: processor.ride_economic_terminal_projector,
    )


async def _mark_ride_failed(ride_id: str, error_message: str) -> bool:
    """Persist terminal ingest failure for jobs that cannot reach RideProcessor."""
    try:
        from ..repositories import create_ride_repository

        ride_repo = create_ride_repository()
        await ride_repo.update_ride_status(
            UUID(ride_id),
            "failed",
            error_message=error_message,
        )
        return True
    except Exception as exc:
        logger.error(
            f"[NATSConsumer] Failed to mark ride {ride_id} as failed: {exc}",
            exc_info=True,
        )
        return False


async def _handle_uploaded(msg, payload: dict) -> None:
    """
    Handle rides.events.uploaded — invoke RideProcessor.

    Required payload keys: ride_id, user_id, file_type, file_path
    Optional: user_weight_kg, wallet
    """
    training_ready = False
    ride_id = payload.get("ride_id")
    user_id = payload.get("user_id")
    file_type = payload.get("file_type", "fit")
    file_path = payload.get("file_path")
    wallet = payload.get("wallet", "unknown")
    user_weight_kg = float(payload.get("user_weight_kg", 75.0))

    if not ride_id or not user_id or not file_path:
        logger.error(
            f"[NATSConsumer] UPLOADED missing required fields: "
            f"ride_id={ride_id} user_id={user_id} file_path=[redacted]"
        )
        # ACK to avoid infinite redelivery of permanently invalid messages
        await msg.ack()
        return

    try:
        ride_uuid = UUID(str(ride_id))
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError) as exc:
        logger.error(
            f"[NATSConsumer] UPLOADED invalid UUID fields: "
            f"ride_id={ride_id} user_id={user_id} error={exc}"
        )
        # Permanent payload defect. ACK to avoid poisoning the durable consumer.
        await msg.ack()
        return

    logger.info(
        f"[NATSConsumer] Processing ride: ride_id={ride_id} wallet=[redacted] "
        f"file_type={file_type} file_path=[redacted]"
    )

    start = time.perf_counter()

    try:
        # Download file from storage
        from .file_storage import (
            FileNotFoundError as RideFileNotFoundError,
            create_file_storage_service,
        )

        storage = create_file_storage_service()
        try:
            raw_file_bytes = await storage.download_ride_file(file_path)
        except RideFileNotFoundError:
            error = f"Uploaded ride file missing from storage: {file_path}"
            logger.error(f"[NATSConsumer] {error}")
            marked_failed = await _mark_ride_failed(str(ride_uuid), error)
            if not marked_failed:
                await msg.nak(delay=30)
                return
            # The job references a file that no longer exists. Retrying cannot fix it.
            await msg.ack()
            return

        logger.info(
            f"[NATSConsumer] Downloaded {len(raw_file_bytes)} bytes for ride {ride_id}"
        )

        # Encode to base64 for the processor (needed as fallback for Python parser)
        file_data_b64 = base64.b64encode(raw_file_bytes).decode("utf-8")

        # Process the ride through the same phase gates used by scheduled workers.
        processor = _get_processor()
        phase1_result = await processor.process_phase1_core(
            ride_id=ride_uuid,
            file_data_b64=file_data_b64,
            file_type=file_type,
            user_id=user_uuid,
            user_weight_kg=user_weight_kg,
            file_bytes=raw_file_bytes,
        )
        if phase1_result.get("status") != "metrics_ready":
            await msg.nak(delay=30)
            return
        phase2_result = await processor.process_phase2_enrichment(
            ride_id=ride_uuid,
            user_id=user_uuid,
            user_weight_kg=user_weight_kg,
        )
        if phase2_result.get("status") != "enriched":
            logger.error(
                "[NATSConsumer] Phase 2 did not persist an economic plan: "
                "ride_id=%s status=%s error=%s",
                ride_id,
                phase2_result.get("status"),
                phase2_result.get("error"),
            )
            if phase2_result.get("retryable") is False:
                # Phase 2 marked the ride failed; a redelivery hits the same defect.
                await msg.ack()
                return
            await msg.nak(delay=30)
            return
        phase3_result = await processor.process_phase3_rewards(
            ride_id=ride_uuid,
            user_id=user_uuid,
        )

        elapsed = time.perf_counter() - start
        logger.info(
            f"[NATSConsumer] Ride processed successfully: ride_id={ride_id} "
            f"wallet=[redacted] elapsed={elapsed:.2f}s "
            f"phase1={phase1_result.get('status')} "
            f"phase2={phase2_result.get('status')} "
            f"phase3={phase3_result.get('status')} "
            f"cal={phase3_result.get('cal_earned')}"
        )

        phase3_status = phase3_result.get("status")
        durable_checkpoint = bool(phase3_result.get("durable_checkpoint"))
        if phase3_status in {"complete", "completed"}:
            await msg.ack()
            training_ready = True
        elif phase3_status in {"recovery_pending", "under_review"} and durable_checkpoint:
            logger.warning(
                "[NATSConsumer] ACKing ride after durable economic checkpoint: "
                "ride_id=%s status=%s state=%s",
                ride_id,
                phase3_status,
                phase3_result.get("economic_state"),
            )
            await msg.ack()
            training_ready = True
        else:
            logger.error(
                "[NATSConsumer] Economic work lacks durable ownership; NAKing: "
                "ride_id=%s status=%s",
                ride_id,
                phase3_status,
            )
            await msg.nak(delay=30)

    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.error(
            f"[NATSConsumer] Ride processing FAILED: ride_id={ride_id} "
            f"wallet=[redacted] elapsed={elapsed:.2f}s error={scrub_log_text(exc)}",
            exc_info=True,
        )
        # NACK with 30s delay for retry
        try:
            await msg.nak(delay=30)
        except Exception as nak_exc:
            logger.error(f"[NATSConsumer] Failed to NACK message: {nak_exc}")

    # Payment phases and their ACK are finished. Only signal the independent
    # replay loop here; a training failure cannot enter the payment NAK path.
    if training_ready and _training_runtime is not None:
        try:
            _training_runtime.wake()
        except Exception as exc:
            logger.warning("Training replay wake failed: %s", type(exc).__name__)


async def _handle_strava_webhook(msg, payload: dict) -> None:
    """
    Handle strava.events.webhook — process a Strava webhook event.

    This replaces the Celery process_strava_webhook_event task.
    The logic is identical: look up the Strava connection, download the
    activity file, and enqueue it for ride processing via NATS.
    """
    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    owner_id = payload.get("owner_id")
    object_id = payload.get("object_id")

    logger.info(
        f"[NATSConsumer] Strava webhook: {object_type}.{aspect_type} "
        f"owner={owner_id} object={object_id}"
    )

    try:
        # Import lazily to avoid circular imports
        from .strava_service import StravaService
        from .strava_rate_limiter import get_strava_rate_limiter, Priority
        from .file_storage import create_file_storage_service
        from .provider_imports import requeue_pending_provider_ride
        from .ride_ingest import RideIngestJob, enqueue_ride_ingest
        from ..metrics import (
            record_strava_api_request,
            record_strava_webhook_event,
            record_strava_webhook_ignored,
            set_strava_last_webhook_event,
        )
        from ..repositories import create_ride_repository, create_user_repository
        import httpx
        import uuid as uuid_module

        strava = StravaService()

        if object_type == "athlete" and aspect_type == "deauthorize":
            connection = strava.get_connection_by_athlete_id(owner_id)
            if not connection:
                record_strava_webhook_event(object_type, aspect_type, "ignored")
                record_strava_webhook_ignored("deauthorize_no_connection")
                logger.info(
                    "[NATSConsumer] Ignoring deauthorize for unknown athlete %s",
                    owner_id,
                )
                await msg.ack()
                return

            revoked = await strava.confirm_external_revocation(connection)
            if revoked:
                record_strava_webhook_event(object_type, aspect_type, "revoked")
                logger.info(
                    "[NATSConsumer] Confirmed Strava deauthorize for athlete %s",
                    owner_id,
                )
            else:
                record_strava_webhook_event(object_type, aspect_type, "ignored")
                record_strava_webhook_ignored("deauthorize_unconfirmed")
            await msg.ack()
            return

        # Only process cycling activity creates
        if object_type != "activity" or aspect_type != "create":
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored(f"{object_type}.{aspect_type}")
            logger.info(
                f"[NATSConsumer] Ignoring strava event: {object_type}.{aspect_type}"
            )
            await msg.ack()
            return

        # Look up connection by athlete ID
        connection = strava.get_connection_by_athlete_id(owner_id)
        if not connection:
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored("no_connection")
            logger.warning(
                f"[NATSConsumer] No active connection for athlete {owner_id}"
            )
            await msg.ack()
            return

        # Refresh token if needed
        connection = await strava.ensure_valid_token(connection)

        # Check rate budget (realtime priority)
        rate_limiter = get_strava_rate_limiter()
        if not await rate_limiter.wait_for_capacity(cost=3, priority=Priority.REALTIME, max_wait=30):
            logger.warning("[NATSConsumer] Strava rate limited, will retry via NACK")
            await msg.nak(delay=60)
            return

        # Check if already imported (dedup)
        imported_ids = strava._get_imported_activity_ids(connection.id)
        if object_id in imported_ids:
            logger.info(f"[NATSConsumer] Activity {object_id} already imported")
            await msg.ack()
            return

        # Get activity details to check if it's a cycling activity
        async with httpx.AsyncClient() as client:
            request_started = time.perf_counter()
            response = await client.get(
                f"https://www.strava.com/api/v3/activities/{object_id}",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            record_strava_api_request(
                endpoint="activity_detail",
                method="GET",
                status_code=response.status_code,
                duration_seconds=time.perf_counter() - request_started,
            )
            rate_limiter.update_from_headers(dict(response.headers))

            if response.status_code != 200:
                record_strava_webhook_event(object_type, aspect_type, "error")
                logger.error(
                    f"[NATSConsumer] Failed to fetch activity {object_id}: "
                    f"{response.status_code}"
                )
                await msg.nak(delay=60)
                return

            activity = response.json()

        activity_type = activity.get("type", "")
        if activity_type not in ("Ride", "VirtualRide", "EBikeRide"):
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored(f"type={activity_type or 'unknown'}")
            logger.info(
                f"[NATSConsumer] Skipping non-cycling activity {object_id} "
                f"(type={activity_type})"
            )
            await msg.ack()
            return

        user_repo = create_user_repository()
        user_id = await user_repo.get_user_id(connection.wallet)
        if not user_id:
            logger.warning(
                f"[NATSConsumer] No user found for wallet [redacted]"
            )
            await msg.ack()
            return

        ride_repo = create_ride_repository()
        existing_provider_ride = await ride_repo.find_ride_by_import_identity(
            user_id,
            "strava",
            str(object_id),
        )
        if existing_provider_ride:
            requeue = await requeue_pending_provider_ride(
                ride_repo=ride_repo,
                user_repo=user_repo,
                ride=existing_provider_ride,
                wallet=connection.wallet,
                user_id=user_id,
                default_file_type="gpx",
                enqueue_source="strava_webhook_retry",
                source_id=str(object_id),
            )
            if requeue.attempted and not requeue.accepted:
                logger.error(
                    "[NATSConsumer] Existing provider ride %s could not be re-enqueued: %s",
                    existing_provider_ride.get("id"),
                    requeue.error,
                )
                await msg.nak(delay=60)
                return
            strava.mark_activity_imported(
                connection_id=connection.id,
                strava_activity_id=object_id,
                activity_id=existing_provider_ride["id"],
            )
            await msg.ack()
            return

        privacy_policy = await ride_repo.resolve_ride_privacy_policy(user_id)

        # Download and process the activity
        file_data, file_type, import_diagnostics = (
            await strava.download_activity_file_with_diagnostics(connection, object_id)
        )

        # Upload to storage (same storage-first ingest path as manual uploads)
        storage = create_file_storage_service()

        file_hash = storage.compute_file_hash(file_data)

        # Check for duplicate by hash
        existing = await ride_repo.find_ride_by_hash(user_id, file_hash)
        if existing:
            logger.info(
                f"[NATSConsumer] Duplicate file hash for activity {object_id}"
            )
            requeue = await requeue_pending_provider_ride(
                ride_repo=ride_repo,
                user_repo=user_repo,
                ride=existing,
                wallet=connection.wallet,
                user_id=user_id,
                default_file_type=file_type,
                enqueue_source="strava_webhook_retry",
                source_id=str(object_id),
            )
            if requeue.attempted and not requeue.accepted:
                logger.error(
                    "[NATSConsumer] Pending duplicate ride %s could not be re-enqueued: %s",
                    existing["id"],
                    requeue.error,
                )
                await msg.nak(delay=60)
                return
            strava.mark_activity_imported(
                connection_id=connection.id,
                strava_activity_id=object_id,
                activity_id=existing["id"],
            )
            await msg.ack()
            return

        ride_id = str(uuid_module.uuid4())

        storage_result = await storage.upload_ride_file(
            user_id=user_id,
            ride_id=ride_id,
            file_bytes=file_data,
            file_type=file_type,
        )

        await ride_repo.create_ride(
            user_id=user_id,
            ride_id=ride_id,
            status="processing",
            file_type=file_type,
            raw_file_path=storage_result.path,
            raw_file_size_bytes=storage_result.size_bytes,
            file_hash=storage_result.file_hash,
            import_source=import_diagnostics.import_source,
            import_source_id=import_diagnostics.source_activity_id,
            import_diagnostics=import_diagnostics.to_dict(),
            privacy_policy=privacy_policy,
        )

        # Get user profile for processing params
        profile = await user_repo.get_user_profile(connection.wallet)
        user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

        enqueue_result = await enqueue_ride_ingest(
            RideIngestJob(
                ride_id=ride_id,
                wallet=connection.wallet,
                user_id=user_id,
                file_type=file_type,
                file_path=storage_result.path,
                user_weight_kg=user_weight,
                source="strava_webhook",
                source_id=str(object_id),
            )
        )
        if not enqueue_result.accepted:
            from ..repositories import create_supabase_repository
            repo = create_supabase_repository()
            await repo.update_ride_status(
                UUID(ride_id),
                "pending",
                error_message=enqueue_result.error,
            )
            logger.error(f"[NATSConsumer] Processing queue unavailable for ride {ride_id}")
            await msg.nak(delay=60)
            return

        strava.mark_activity_imported(
            connection_id=connection.id,
            strava_activity_id=object_id,
            activity_id=ride_id,
        )

        # Update last_webhook_at
        strava.db.table("strava_connections").update({
            "last_webhook_at": "now()",
        }).eq("id", str(connection.id)).execute()
        set_strava_last_webhook_event(time.time())

        logger.info(
            f"[NATSConsumer] Imported activity {object_id} as ride {ride_id} "
            f"for wallet [redacted]"
        )
        record_strava_webhook_event(object_type, aspect_type, "imported")
        await msg.ack()

    except Exception as exc:
        logger.error(
            f"[NATSConsumer] Strava webhook processing FAILED: "
            f"{object_type}.{aspect_type} owner={owner_id} object={object_id} "
            f"error={exc}",
            exc_info=True,
        )
        try:
            await msg.nak(delay=60)
        except Exception as nak_exc:
            logger.error(f"[NATSConsumer] Failed to NACK strava message: {nak_exc}")


async def _handle_strava_message(msg) -> None:
    """
    Handle an incoming NATS message on the strava.events.> subject.
    """
    subject = msg.subject
    if not load_strava_settings().sync_enabled:
        logger.info(
            "[NATSConsumer] Discarding residual Strava message in file-import-only mode: %s",
            subject,
        )
        await msg.ack()
        return
    try:
        payload = json.loads(msg.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[NATSConsumer] Failed to decode strava message on {subject}: {exc}")
        await msg.ack()
        return

    if subject == "strava.events.webhook":
        await _handle_strava_webhook(msg, payload)
    else:
        logger.info(
            f"[NATSConsumer] Unknown strava subject={subject} "
            f"payload_keys={list(payload.keys())}"
        )
        await msg.ack()


# ---------------------------------------------------------------------------
# Stale ride cleanup (replaces Celery beat cleanup_stale_rides task)
# ---------------------------------------------------------------------------


async def _stale_ride_cleanup_loop() -> None:
    """
    Periodically mark stuck rides as failed.

    Handles two cases:
    1. Rides stuck in 'processing' or 'pending' for >1 hour
    2. Rides stuck in 'metrics_ready' for >30 minutes (Phase 2 never completed)

    Runs every 10 minutes. This replaces the Celery beat
    cleanup-stale-rides-every-10-min schedule.
    """
    logger.info("[StaleCleanup] Background cleanup loop started (interval=%ds)", STALE_CLEANUP_INTERVAL)
    while True:
        await asyncio.sleep(STALE_CLEANUP_INTERVAL)
        try:
            from ..repositories import create_supabase_repository

            repo = create_supabase_repository()
            try:
                now = datetime.now(timezone.utc)
                one_hour_ago = now - timedelta(hours=1)
                thirty_min_ago = now - timedelta(minutes=30)

                cleaned = 0

                # Case 1: processing/pending stuck >1 hour
                result = repo.client.table("rides") \
                    .select("id,processing_status,created_at") \
                    .in_("processing_status", ["processing", "pending"]) \
                    .lt("created_at", one_hour_ago.isoformat()) \
                    .execute()

                stale_rides = result.data or []
                for ride in stale_rides:
                    ride_id = ride["id"]
                    repo.client.table("rides").update({
                        "processing_status": "failed",
                        "error_message": f"Processing timed out ({ride['processing_status']} for >1 hour). Please re-upload.",
                    }).eq("id", ride_id).execute()
                    cleaned += 1
                    logger.info(f"[StaleCleanup] Marked ride {ride_id} as failed (was {ride['processing_status']} >1hr)")

                # Case 2: metrics_ready stuck >30 minutes without Phase 2 completion
                result2 = repo.client.table("rides") \
                    .select("id,phase1_completed_at") \
                    .eq("processing_status", "metrics_ready") \
                    .is_("phase2_completed_at", "null") \
                    .lt("phase1_completed_at", thirty_min_ago.isoformat()) \
                    .execute()

                stale_metrics = result2.data or []
                for ride in stale_metrics:
                    ride_id = ride["id"]
                    repo.client.table("rides").update({
                        "processing_status": "failed",
                        "error_message": "Enrichment timed out (metrics_ready for >30 min). Please re-upload.",
                    }).eq("id", ride_id).execute()
                    cleaned += 1
                    logger.info(f"[StaleCleanup] Marked ride {ride_id} as failed (metrics_ready >30min)")

                if cleaned > 0:
                    logger.info(f"[StaleCleanup] Cleaned up {cleaned} stale rides")
                else:
                    logger.debug("[StaleCleanup] No stale rides found")

            finally:
                if hasattr(repo, "dispose"):
                    await repo.dispose()

        except Exception as e:
            logger.error(f"[StaleCleanup] Error during cleanup: {e}", exc_info=True)


async def _handle_message(msg) -> None:
    """
    Handle an incoming NATS JetStream message.

    Dispatches rides.events.uploaded to RideProcessor.
    All other events are logged as telemetry and ACKed immediately.
    """
    subject = msg.subject
    try:
        payload = json.loads(msg.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[NATSConsumer] Failed to decode message on {subject}: {exc}")
        # ACK malformed messages to avoid infinite redelivery
        await msg.ack()
        return

    ride_id = payload.get("ride_id", "unknown")
    wallet = payload.get("wallet", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Dispatch based on event type
    if subject == "rides.events.uploaded":
        uploaded_msg = _UploadedRideMessage(msg)
        uploaded_msg.start()
        runtime = _training_runtime
        try:
            token = runtime.begin_attempt(payload) if runtime is not None else None
            await _handle_uploaded(uploaded_msg, payload)
        finally:
            await uploaded_msg.stop()
        # This point is after the handler's own ACK/NAK and exception handling.
        # Cancellation leaves an active receipt for the next startup to recover.
        if runtime is not None:
            runtime.finish_attempt(payload, token)
        return

    # --- Telemetry-only handlers (log and ACK) ---

    if subject == "rides.events.metrics_ready":
        logger.info(
            f"[NATSConsumer] METRICS_READY ride_id={ride_id} wallet=[redacted] "
            f"tss={payload.get('tss')} duration_s={payload.get('duration_s')} "
            f"at={timestamp}"
        )

    elif subject == "rides.events.enriched":
        logger.info(
            f"[NATSConsumer] ENRICHED ride_id={ride_id} wallet=[redacted] "
            f"climbs={payload.get('climbs_count')} "
            f"vault_matches={payload.get('vault_matches_count')} "
            f"at={timestamp}"
        )

    elif subject == "rides.events.completed":
        logger.info(
            f"[NATSConsumer] COMPLETED ride_id={ride_id} wallet=[redacted] "
            f"cal={payload.get('cal_earned')} at={timestamp}"
        )

    else:
        logger.info(
            f"[NATSConsumer] UNKNOWN subject={subject} ride_id={ride_id} "
            f"payload_keys={list(payload.keys())} at={timestamp}"
        )

    await msg.ack()


async def start_consumer() -> None:
    """
    Start the NATS consumer. Connects and subscribes to ride events,
    Strava webhook events, and starts the stale-ride cleanup loop.

    This is a long-running coroutine. Call from an asyncio event loop
    or via the standalone entry point below.
    """
    global _stale_cleanup_task, _ride_economic_recovery_task, _training_runtime

    client = get_nats_client()
    await client.connect()

    from .training_runtime import TrainingReplayRuntime
    _training_runtime = TrainingReplayRuntime()
    await _training_runtime.prepare()

    # Ensure STRAVA stream exists (the RIDES stream is created by nats_client)
    try:
        await client._js.find_stream_name_by_subject("strava.events.webhook")
        logger.info("[NATSConsumer] Stream 'STRAVA' already exists")
    except Exception:
        logger.info("[NATSConsumer] Creating stream 'STRAVA'")
        await client._js.add_stream(
            name="STRAVA",
            subjects=["strava.events.>"],
            retention="limits",
            max_age=7 * 24 * 3600,  # 7 days retention
            storage="file",
            num_replicas=1,
            duplicate_window=120,
        )
        logger.info("[NATSConsumer] Stream 'STRAVA' created")

    logger.info(
        f"[NATSConsumer] Starting consumer: "
        f"subject={SUBSCRIBE_SUBJECT} queue={QUEUE_GROUP} durable={DURABLE_NAME}"
    )

    # Subscribe to ride events
    await client.subscribe(
        subject=SUBSCRIBE_SUBJECT,
        queue_group=QUEUE_GROUP,
        handler=_handle_message,
        durable=DURABLE_NAME,
    )

    # Subscribe to Strava webhook events
    await client.subscribe(
        subject=STRAVA_SUBSCRIBE_SUBJECT,
        queue_group=STRAVA_QUEUE_GROUP,
        handler=_handle_strava_message,
        durable=STRAVA_DURABLE_NAME,
    )

    # Start stale ride cleanup background loop
    _stale_cleanup_task = asyncio.create_task(_stale_ride_cleanup_loop())
    recovery = _create_ride_economic_recovery_loop()
    _ride_economic_recovery_task = asyncio.create_task(recovery.run_forever())

    _training_runtime.start()

    logger.info("[NATSConsumer] Consumer running. Waiting for messages...")


async def stop_consumer() -> None:
    """Gracefully stop the NATS consumer, cleanup loop, and close the connection."""
    global _stale_cleanup_task, _ride_economic_recovery_task, _training_runtime

    logger.info("[NATSConsumer] Stopping consumer...")

    if _training_runtime is not None:
        await _training_runtime.stop()
        _training_runtime = None

    # Cancel stale ride cleanup task
    if _stale_cleanup_task is not None:
        _stale_cleanup_task.cancel()
        try:
            await _stale_cleanup_task
        except asyncio.CancelledError:
            pass
        _stale_cleanup_task = None
        logger.info("[NATSConsumer] Stale ride cleanup loop stopped")

    if _ride_economic_recovery_task is not None:
        _ride_economic_recovery_task.cancel()
        try:
            await _ride_economic_recovery_task
        except asyncio.CancelledError:
            pass
        _ride_economic_recovery_task = None
        logger.info("[NATSConsumer] Ride economic recovery loop stopped")

    await close_nats_client()
    logger.info("[NATSConsumer] Consumer stopped.")


async def _run_forever() -> None:
    """Run the consumer until interrupted."""
    await start_consumer()

    # Keep the consumer alive until signaled
    stop_event = asyncio.Event()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    await stop_consumer()


def main() -> None:
    """Entry point for standalone consumer execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("[NATSConsumer] Starting standalone NATS consumer...")
    try:
        asyncio.run(_run_forever())
    except KeyboardInterrupt:
        logger.info("[NATSConsumer] Interrupted, shutting down.")


# Allow running as: python -m app.services.nats_consumer
if __name__ == "__main__":
    main()
