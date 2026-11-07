import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from redis import Redis
from celery.exceptions import SoftTimeLimitExceeded

from .celery_app import celery_app
from .config import load_strava_settings
from .metrics import (
    CELERY_QUEUE_DEPTH,
    CELERY_TASK_DURATION,
    CELERY_TASK_RUNS,
    KPI_CAL_AIRDROPS,
    KPI_DUNG_MINTED,
    KPI_RIDE_PROCESSED,
    RIDE_PHASE_DURATION,
    RIDE_PHASE_RUNS,
    record_strava_api_request,
    record_strava_webhook_event,
    record_strava_webhook_ignored,
    set_strava_last_webhook_event,
)
from .repositories import create_supabase_repository, create_ride_repository, create_fitness_repository
from .services.provider_imports import requeue_pending_provider_ride
from .services.ride_ingest import RideIngestJob, enqueue_ride_ingest
from .services.ride_processor import RideProcessor

logger = logging.getLogger(__name__)

CAL_AIRDROP_AMOUNT = 2500
_redis_client: Optional[Redis] = None

# Multi-phase processing feature flag
# Set RIDE_PROCESSING_PHASED=true to enable phased processing
PHASED_PROCESSING_ENABLED = os.getenv("RIDE_PROCESSING_PHASED", "true").lower() == "true"


def _phase2_retry_countdown(task_self) -> int:
    """Bound exponential Phase 2 retry delay to the task's retry budget."""
    configured_max = max(0, int(task_self.max_retries or 0))
    retries = max(0, int(getattr(task_self.request, "retries", 0) or 0))
    return min(30 * (2 ** min(retries, configured_max)), 300)


def _get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = Redis.from_url(redis_url)
    return _redis_client


def _update_queue_depth() -> None:
    queue_name = os.getenv("CELERY_QUEUE_NAME", "celery")
    try:
        depth = _get_redis_client().llen(queue_name)
    except Exception as exc:
        logger.warning("Failed to read Celery queue depth: %s", exc)
        return
    CELERY_QUEUE_DEPTH.labels(queue=queue_name).set(depth)


if os.getenv("CELERY_METRICS_PORT"):
    _update_queue_depth()


async def _run_account_deletion(request_id: str):
    from .compliance_repository import ComplianceRepository
    from .services.account_deletion import execute_account_deletion
    from .services.account_deletion_factory import (
        build_account_deletion_authority_reader,
    )
    from .services.file_storage import create_file_storage_service

    repository = ComplianceRepository()
    reader = build_account_deletion_authority_reader(repository)
    return await execute_account_deletion(
        request_id,
        repository=repository,
        preflight_reader=reader,
        storage=create_file_storage_service(),
    )


async def _list_recoverable_account_deletions() -> list[str]:
    from .compliance_repository import ComplianceRepository

    return await ComplianceRepository().list_recoverable_deletion_requests(limit=100)


@celery_app.task(
    name="app.tasks.process_account_deletion",
    soft_time_limit=240,
    time_limit=270,
)
def process_account_deletion(request_id: str):
    """Run one durable, lease-fenced deletion request."""
    import asyncio

    outcome = asyncio.run(_run_account_deletion(request_id))
    return {
        "request_id": outcome.request_id,
        "status": outcome.status.value,
        "blockers": [blocker.as_dict() for blocker in outcome.blockers],
        "failure_code": outcome.failure_code,
    }


@celery_app.task(name="app.tasks.recover_account_deletions")
def recover_account_deletions():
    """Requeue durable requests whose prior worker never completed its lease."""
    import asyncio

    request_ids = asyncio.run(_list_recoverable_account_deletions())
    for request_id in request_ids:
        process_account_deletion.delay(request_id=request_id)
    return {"queued": len(request_ids)}


@celery_app.task(bind=True, max_retries=3)
def process_ride_upload(
    self,
    ride_id: str,
    file_type: str,
    user_id: str,
    file_path: Optional[str] = None,
    file_data_b64: Optional[str] = None,
    user_weight_kg: float = 75.0,
    user_ftp_w: int = 200,
):
    """
    Background task to process uploaded ride file.

    Supports two processing modes:
    - PHASED (default): Multi-phase progressive loading (Strava-style)
      Phase 1: Parse, metrics, streams, GPS (<5s) -> metrics_ready
      Phase 2: Tiles, patterns, vaults, leaderboards (30-60s) -> enriched
      Phase 3: CAL, achievements, on-chain (background) -> completed

    - LEGACY: Monolithic processing (all at once)

    Supports two file input modes:
    - file_path: Download from Supabase Storage (preferred, lightweight queue)
    - file_data_b64: Legacy mode with inline base64 content
    """
    import asyncio
    import base64
    from .services.file_storage import create_file_storage_service

    # Check if phased processing is enabled
    if PHASED_PROCESSING_ENABLED:
        logger.info(f"[Task] Using PHASED processing for ride {ride_id}")
        return _process_ride_phased(
            self,
            ride_id=ride_id,
            file_type=file_type,
            user_id=user_id,
            file_path=file_path,
            file_data_b64=file_data_b64,
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )

    # Legacy monolithic processing
    logger.info(f"[Task] Using LEGACY (monolithic) processing for ride {ride_id}")

    async def _process():
        nonlocal file_data_b64

        raw_file_bytes = None

        # Download from storage if file_path provided
        if file_path and not file_data_b64:
            logger.info(f"[Task] Downloading file from storage: [redacted]")
            storage = create_file_storage_service()
            try:
                raw_file_bytes = await storage.download_ride_file(file_path)
                logger.info(f"[Task] Downloaded {len(raw_file_bytes)} bytes from storage")
            except Exception as e:
                logger.error(f"[Task] Failed to download from storage: {e}")
                raise

        # Encode to base64 only if we have raw bytes but no base64 yet
        # (needed as fallback when Rust parser is not available)
        if raw_file_bytes is not None and not file_data_b64:
            file_data_b64 = base64.b64encode(raw_file_bytes).decode("utf-8")

        if not file_data_b64 and raw_file_bytes is None:
            raise ValueError("Either file_path or file_data_b64 must be provided")

        processor = RideProcessor()
        return await processor.process_ride(
            ride_id=UUID(ride_id),
            file_data_b64=file_data_b64 or "",
            file_type=file_type,
            user_id=UUID(user_id),
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
            file_bytes=raw_file_bytes,
        )

    task_name = "process_ride_upload"
    start = time.perf_counter()
    _update_queue_depth()
    try:
        result = asyncio.run(_process())
        outcome_status = str(result.get("status") or "completed")
        metric_status = "success" if outcome_status == "completed" else outcome_status
        CELERY_TASK_RUNS.labels(task=task_name, status=metric_status).inc()
        RIDE_PHASE_RUNS.labels(phase="legacy", status=metric_status).inc()
        RIDE_PHASE_DURATION.labels(phase="legacy").observe(time.perf_counter() - start)
        KPI_RIDE_PROCESSED.labels(status=metric_status).inc()
        dung_reward = float(result.get("dung_reward") or 0)
        if dung_reward > 0:
            KPI_DUNG_MINTED.labels(source="ride").inc(dung_reward)
        return {**result, "ride_id": ride_id}
    except Exception as exc:  # pragma: no cover - worker retries
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        RIDE_PHASE_RUNS.labels(phase="legacy", status="error").inc()
        RIDE_PHASE_DURATION.labels(phase="legacy").observe(time.perf_counter() - start)
        KPI_RIDE_PROCESSED.labels(status="error").inc()
        asyncio.run(_mark_failed(ride_id, str(exc)))
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


def _process_ride_phased(
    task_self,
    ride_id: str,
    file_type: str,
    user_id: str,
    file_path: Optional[str] = None,
    file_data_b64: Optional[str] = None,
    user_weight_kg: float = 75.0,
    user_ftp_w: int = 200,
):
    """
    Phased processing entry point.

    Runs Phase 1 synchronously, then queues Phase 2 and 3 as separate tasks.
    This allows users to see their ride within ~5 seconds.
    """
    import asyncio
    import base64
    from .services.file_storage import create_file_storage_service

    task_name = "process_ride_phase1"
    start = time.perf_counter()
    _update_queue_depth()

    async def _run_phase1():
        nonlocal file_data_b64

        raw_file_bytes = None

        # Download from storage if file_path provided
        if file_path and not file_data_b64:
            logger.info(f"[Phase1] Downloading file from storage: [redacted]")
            storage = create_file_storage_service()
            try:
                raw_file_bytes = await storage.download_ride_file(file_path)
                logger.info(f"[Phase1] Downloaded {len(raw_file_bytes)} bytes from storage")
            except Exception as e:
                logger.error(f"[Phase1] Failed to download from storage: {e}")
                raise

        # Encode to base64 only if we have raw bytes but no base64 yet
        # (needed as fallback when Rust parser is not available)
        if raw_file_bytes is not None and not file_data_b64:
            file_data_b64 = base64.b64encode(raw_file_bytes).decode("utf-8")

        if not file_data_b64 and raw_file_bytes is None:
            raise ValueError("Either file_path or file_data_b64 must be provided")

        processor = RideProcessor()
        return await processor.process_phase1_core(
            ride_id=UUID(ride_id),
            file_data_b64=file_data_b64 or "",
            file_type=file_type,
            user_id=UUID(user_id),
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
            file_bytes=raw_file_bytes,
        )

    try:
        result = asyncio.run(_run_phase1())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        RIDE_PHASE_RUNS.labels(phase="1", status="success").inc()
        duration_ms = result.get("duration_ms")
        if duration_ms:
            RIDE_PHASE_DURATION.labels(phase="1").observe(duration_ms / 1000)

        # Queue Phase 2 (enrichment)
        logger.info(f"[Phase1] Completed, queueing Phase 2 for ride {ride_id}")
        process_ride_phase2.delay(
            ride_id=ride_id,
            user_id=user_id,
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )

        return {
            "status": "metrics_ready",
            "ride_id": ride_id,
            "metrics": result.get("metrics"),
            "duration_ms": result.get("duration_ms"),
        }

    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        RIDE_PHASE_RUNS.labels(phase="1", status="error").inc()
        RIDE_PHASE_DURATION.labels(phase="1").observe(time.perf_counter() - start)
        KPI_RIDE_PROCESSED.labels(status="error").inc()
        asyncio.run(_mark_failed(ride_id, str(exc)))
        raise task_self.retry(exc=exc, countdown=60)

    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=2)
def process_ride_phase2(
    self,
    ride_id: str,
    user_id: str,
    user_weight_kg: float = 75.0,
    user_ftp_w: int = 200,
):
    """
    Phase 2: Enrichment (Target: 30-60 seconds)

    - Tile projection (H3)
    - Pattern detection (Climb, Steady, Exploration)
    - Vault signature matching
    - Leaderboard updates
    - Set status = enriched

    After completion, queues Phase 3 for rewards processing.
    """
    import asyncio

    task_name = "process_ride_phase2"
    start = time.perf_counter()
    _update_queue_depth()

    async def _run_phase2():
        processor = RideProcessor()
        return await processor.process_phase2_enrichment(
            ride_id=UUID(ride_id),
            user_id=UUID(user_id),
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )

    try:
        result = asyncio.run(_run_phase2())
        phase2_status = str(result.get("status") or "phase2_failed")
        if phase2_status != "enriched":
            raise RuntimeError(
                f"Phase 2 returned {phase2_status}: "
                f"{result.get('error') or 'economic plan was not frozen'}"
            )

        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        RIDE_PHASE_RUNS.labels(phase="2", status="success").inc()
        duration_ms = result.get("duration_ms")
        if duration_ms:
            RIDE_PHASE_DURATION.labels(phase="2").observe(duration_ms / 1000)

        # Queue Phase 3 (rewards)
        logger.info(f"[Phase2] Completed, queueing Phase 3 for ride {ride_id}")
        process_ride_phase3.delay(
            ride_id=ride_id,
            user_id=user_id,
        )

        return {
            "status": result.get("status", "enriched"),
            "ride_id": ride_id,
            "patterns": result.get("patterns"),
            "tiles_explored": result.get("tiles_explored"),
            "duration_ms": result.get("duration_ms"),
        }

    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        RIDE_PHASE_RUNS.labels(phase="2", status="error").inc()
        RIDE_PHASE_DURATION.labels(phase="2").observe(time.perf_counter() - start)
        logger.error(f"[Phase2] Failed for ride {ride_id}: {exc}")
        # Phase 3 and plan recovery cannot proceed until Phase 2 freezes a plan.
        raise self.retry(
            exc=exc,
            countdown=_phase2_retry_countdown(self),
            max_retries=self.max_retries,
        )

    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


def _create_ride_economic_recovery_loop(limit: int):
    from .repositories import (
        create_notification_repository,
        create_ride_economic_repository,
        create_ride_repository,
    )
    from .services.ride_economic_coordinator import RideEconomicCoordinator
    from .services.ride_economic_recovery import RideEconomicRecoveryLoop
    from .services.ride_executor import RideExecutor
    from .services.ride_economic_terminal_projector import (
        RideEconomicTerminalProjector,
    )

    repository = create_ride_economic_repository()
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RideExecutor(),
    )
    terminal_projector = RideEconomicTerminalProjector(
        economic_repository=repository,
        ride_repository=create_ride_repository(),
        notification_repository=create_notification_repository(),
    )
    return RideEconomicRecoveryLoop(
        repository=repository,
        coordinator_factory=lambda: coordinator,
        terminal_projector_factory=lambda: terminal_projector,
        batch_size=limit,
    )


@celery_app.task(name="app.tasks.recover_ride_economics")
def recover_ride_economics(limit: int = 25):
    """Run one direct recovery pass over immutable ride-economic plans."""
    import asyncio

    recovery = _create_ride_economic_recovery_loop(limit)
    return {"resumed": asyncio.run(recovery.run_once())}


@celery_app.task(name="app.tasks.seal_reward_threshold_promotions")
def seal_reward_threshold_promotions():
    """Seal due append-only Threshold versions at the Monday boundary."""
    import asyncio

    repository = create_ride_repository()
    sealed = asyncio.run(repository.seal_due_reward_threshold_promotions())
    return {"sealed": sealed}


def _create_threshold_release_recovery_loop(limit: int):
    from .services.threshold_runtime import create_threshold_release_recovery_loop

    return create_threshold_release_recovery_loop(limit)


@celery_app.task(
    name="app.tasks.recover_threshold_releases",
    soft_time_limit=240,
    time_limit=270,
)
def recover_threshold_releases(limit: int = 25):
    """Plan and converge receipt-backed held-ride releases."""
    import asyncio

    recovery = _create_threshold_release_recovery_loop(limit)
    try:
        return asyncio.run(recovery.run_once())
    except SoftTimeLimitExceeded:
        logger.warning("Threshold release recovery stopped at its soft time limit")
        return {"status": "soft_time_limit", "durable_checkpoint": False}


@celery_app.task(bind=True, max_retries=2)
def process_ride_phase3(
    self,
    ride_id: str,
    user_id: str,
):
    """
    Phase 3: Rewards (Background)

    - CAL calculation and awards
    - Achievement detection
    - On-chain operations (CAL credit, vault completion recording)
    - Set status = completed

    This is the final phase. On completion, ride processing is finished.
    """
    import asyncio

    task_name = "process_ride_phase3"
    start = time.perf_counter()
    _update_queue_depth()

    async def _run_phase3():
        processor = RideProcessor()
        return await processor.process_phase3_rewards(
            ride_id=UUID(ride_id),
            user_id=UUID(user_id),
        )

    try:
        result = asyncio.run(_run_phase3())
        phase3_status = str(result.get("status") or "phase3_failed")
        metric_status = "success" if phase3_status == "completed" else phase3_status
        CELERY_TASK_RUNS.labels(task=task_name, status=metric_status).inc()
        RIDE_PHASE_RUNS.labels(phase="3", status=metric_status).inc()
        duration_ms = result.get("duration_ms")
        if duration_ms:
            RIDE_PHASE_DURATION.labels(phase="3").observe(duration_ms / 1000)
        KPI_RIDE_PROCESSED.labels(status=metric_status).inc()

        dung_minted = float(result.get("dung_minted") or 0)
        if dung_minted > 0:
            KPI_DUNG_MINTED.labels(source="ride").inc(dung_minted)

        logger.info(
            "[Phase3] Finished for ride %s with status=%s",
            ride_id,
            phase3_status,
        )

        return {**result, "ride_id": ride_id}

    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        RIDE_PHASE_RUNS.labels(phase="3", status="error").inc()
        RIDE_PHASE_DURATION.labels(phase="3").observe(time.perf_counter() - start)
        logger.error(f"[Phase3] Failed for ride {ride_id}: {exc}")
        # Phase 3 failure doesn't fail the ride - user still has metrics + patterns
        return {
            "status": "phase3_failed",
            "ride_id": ride_id,
            "error": str(exc),
        }

    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


async def _mark_failed(ride_id: str, error: str):
    repo = create_supabase_repository()
    try:
        await repo.update_ride_status(UUID(ride_id), "failed", error_message=error)
    finally:
        if hasattr(repo, "disconnect"):
            await repo.disconnect()


@celery_app.task(bind=True, max_retries=2)
def process_cal_airdrops(self):
    """
    Celery task to process automatic CAL airdrops.

    Runs every 5 minutes via Celery Beat.
    Finds users where next_cal_airdrop <= now() and gives them 2500 CAL.
    Sets their next_cal_airdrop to now() + 24 hours.
    """
    import asyncio

    async def _process():
        repo = create_supabase_repository()
        try:
            # Get users due for airdrop (batch of 100)
            users = await repo.get_users_due_for_airdrop(limit=100)

            if not users:
                logger.info("CAL airdrop: No users due for airdrop")
                return {"processed": 0}

            processed = 0
            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue

                try:
                    await repo.process_cal_airdrop(user_id, CAL_AIRDROP_AMOUNT)
                    processed += 1
                    logger.info(f"CAL airdrop: Gave {CAL_AIRDROP_AMOUNT} CAL to user {user_id}")
                except Exception as e:
                    logger.error(f"CAL airdrop: Failed for user {user_id}: {e}")
                    continue

            logger.info(f"CAL airdrop: Processed {processed} users")
            return {"processed": processed}
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    task_name = "process_cal_airdrops"
    start = time.perf_counter()
    _update_queue_depth()
    try:
        result = asyncio.run(_process())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        processed = int(result.get("processed") or 0)
        if processed:
            KPI_CAL_AIRDROPS.inc(processed)
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("CAL airdrop task failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=1)
def recompute_recent_fitness(self, lookback_days: int = 7, max_users: int = 200):
    """
    Periodic task to recompute fitness aggregates for recently active users.

    - Finds users with rides in the last N days
    - Recalculates daily aggregates starting from earliest ride date in window
    - Recomputes CTL/ATL/TSB forward to today
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    from .services.fitness_analytics import FitnessAnalyticsService, normalize_to_date

    task_name = "recompute_recent_fitness"
    start = time.perf_counter()
    _update_queue_depth()

    async def _recompute():
        repo = create_supabase_repository()
        ride_repo = create_ride_repository()
        fitness_repo = create_fitness_repository()
        analytics = FitnessAnalyticsService(fitness_repo, ride_repo)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            response = repo.client.table("rides") \
                .select("user_id, started_at") \
                .gte("started_at", cutoff.isoformat()) \
                .limit(max(1, max_users * 200)) \
                .execute()

            rows = response.data or []
            if not rows:
                return {"processed_users": 0}

            user_min_date: dict[str, datetime.date] = {}
            for row in rows:
                user_id = row.get("user_id")
                started_at = row.get("started_at")
                if not user_id or not started_at:
                    continue
                ride_date = normalize_to_date(started_at)
                prev = user_min_date.get(user_id)
                if prev is None or ride_date < prev:
                    user_min_date[user_id] = ride_date

            processed = 0
            for user_id, min_date in user_min_date.items():
                await analytics.update_daily_aggregates(user_id, min_date)
                processed += 1

            return {"processed_users": processed}
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_recompute())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Fitness recompute task failed")
        raise self.retry(exc=exc, countdown=120)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=2)
def backfill_vault_leaderboard(
    self,
    vault_id: int,
    vault_signature: str,
    job_id: Optional[str] = None,
):
    """
    Background task to backfill a vault's leaderboard from historical ride data.

    Finds all patterns_climb entries matching this vault's signature and:
    1. Records vault_completions for each match
    2. Updates leaderboard if time qualifies for top 10

    This task is triggered automatically when a new vault is indexed,
    or can be triggered manually via admin endpoint.

    Args:
        vault_id: On-chain vault ID
        vault_signature: 64-byte signature hex (128 chars)
        job_id: Optional job ID for tracking progress
    """
    import asyncio
    from .services.backfill_service import VaultBackfillService

    task_name = "backfill_vault_leaderboard"
    start = time.perf_counter()
    _update_queue_depth()

    async def _backfill():
        repo = create_supabase_repository()
        try:
            service = VaultBackfillService(repo.client)
            result = await service.backfill_vault(
                vault_id=vault_id,
                vault_signature=vault_signature,
                job_id=job_id,
            )
            return {
                "status": result.status,
                "vault_id": result.vault_id,
                "matched_count": result.matched_count,
                "leaderboard_updates": result.leaderboard_updates,
                "skipped_existing": result.skipped_existing,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_backfill())
        if result.get("status") in ("completed", "skipped"):
            CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
            logger.info(
                f"[Backfill] Vault {vault_id} complete: "
                f"{result['matched_count']} matches, {result['leaderboard_updates']} leaderboard updates, "
                f"{result.get('skipped_existing', 0)} existing skipped"
            )
        else:
            CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
            logger.error(f"[Backfill] Vault {vault_id} failed: {result.get('error')}")
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception(f"Vault backfill task failed for vault {vault_id}")
        raise self.retry(exc=exc, countdown=120)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=1)
def process_pending_backfills(self, limit: int = 10):
    """
    Process pending vault backfill jobs from the queue.

    This task runs periodically via Celery Beat to process any queued
    backfill jobs. Each job is processed sequentially to avoid
    overwhelming the database.

    Args:
        limit: Maximum number of jobs to process in this run
    """
    import asyncio
    from .services.backfill_service import get_pending_backfill_jobs

    task_name = "process_pending_backfills"
    start = time.perf_counter()
    _update_queue_depth()

    async def _process():
        repo = create_supabase_repository()
        try:
            jobs = await get_pending_backfill_jobs(repo.client, limit=limit)
            if not jobs:
                logger.debug("[Backfill] No pending jobs")
                return {"processed": 0}

            processed = 0
            for job in jobs:
                # Queue individual backfill task for each job
                backfill_vault_leaderboard.delay(
                    vault_id=job["vault_id"],
                    vault_signature=job["vault_signature"],
                    job_id=str(job["id"]),
                )
                processed += 1

            logger.info(f"[Backfill] Queued {processed} backfill jobs")
            return {"processed": processed}
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_process())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Process pending backfills task failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=2)
def sync_leaderboard_to_chain(
    self,
    vault_id: int,
    vault_signature: Optional[str] = None,
    triggered_by: str = "task",
):
    """
    Verify a single vault's projected leaderboard against chain.

    Historical task name kept for queue/back-compat. It does not write DB
    state to chain; it compares the read-layer cache with the authoritative
    on-chain VaultLeaderboard PDA and logs any mismatches.

    Args:
        vault_id: On-chain vault ID
        vault_signature: Optional signature hex (looked up if not provided)
        triggered_by: Who triggered the sync (task, admin, api)
    """
    import asyncio
    from .services.leaderboard_sync_service import LeaderboardSyncService

    task_name = "sync_leaderboard_to_chain"
    start = time.perf_counter()
    _update_queue_depth()

    async def _sync():
        repo = create_supabase_repository()
        try:
            service = LeaderboardSyncService(repo.client)
            result = await service.sync_vault_leaderboard(
                vault_id=vault_id,
                vault_signature=vault_signature,
                sync_type="manual",
                triggered_by=triggered_by,
            )
            return {
                "vault_id": result.vault_id,
                "status": result.status,
                "entries_synced": result.entries_synced,
                "tx_signature": result.tx_signature,
                "error": result.error,
            }
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_sync())
        if result.get("status") in ("synced", "skipped"):
            CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        else:
            CELERY_TASK_RUNS.labels(task=task_name, status="warning").inc()
        logger.info(f"[LeaderboardSync] Vault {vault_id}: {result.get('status')}")
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception(f"Leaderboard sync task failed for vault {vault_id}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=1)
def sync_all_leaderboards(self, epoch: Optional[int] = None):
    """
    Verify all active vault leaderboard projections against chain.

    Historical task name kept for queue/back-compat. This task is optional
    observability only; Settlement Week distribution reads chain state
    directly and never depends on this read-layer check.

    Args:
        epoch: Current epoch number (for logging)
    """
    import asyncio
    from .services.leaderboard_sync_service import LeaderboardSyncService

    task_name = "sync_all_leaderboards"
    start = time.perf_counter()
    _update_queue_depth()

    async def _sync_all():
        repo = create_supabase_repository()
        try:
            service = LeaderboardSyncService(repo.client)
            results = await service.sync_all_active_vaults(epoch=epoch)
            return {
                "total": len(results),
                "synced": sum(1 for r in results if r.status == "synced"),
                "mismatches": sum(1 for r in results if r.status == "mismatch_detected"),
                "failed": sum(1 for r in results if r.status == "failed"),
                "skipped": sum(1 for r in results if r.status == "skipped"),
            }
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_sync_all())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        logger.info(
            f"[LeaderboardVerify] All vaults: {result['synced']} matched, "
            f"{result['mismatches']} mismatches, {result['failed']} failed"
        )
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Verify all leaderboards task failed")
        raise self.retry(exc=exc, countdown=120)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


# =============================================================================
# SIGNATURE BACKFILL TASKS
# =============================================================================


@celery_app.task(name="app.tasks.cleanup_stale_rides")
def cleanup_stale_rides():
    """
    Find and mark stale rides as failed.

    Handles two cases:
    1. Rides stuck in 'processing' or 'pending' for >1 hour
    2. Rides stuck in 'metrics_ready' for >30 minutes (Phase 2 never completed)
    """
    import asyncio
    from datetime import timedelta

    task_name = "cleanup_stale_rides"
    start = time.perf_counter()
    _update_queue_depth()

    async def _cleanup():
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

            logger.info(f"[StaleCleanup] Cleaned up {cleaned} stale rides")
            return {"cleaned": cleaned}
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_cleanup())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Stale ride cleanup task failed")
        return {"cleaned": 0, "error": str(exc)}
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=2)
def backfill_pattern_signatures(self, limit: int = 50, dry_run: bool = False):
    """
    Backfill missing signatures for patterns_climb records.

    Finds patterns without signature_hex and regenerates them from
    activity_tile_samples data using ClimbSignatureGenerator.

    Args:
        limit: Maximum patterns to process in this run
        dry_run: If True, don't actually update, just log what would happen

    Returns:
        Dict with success/failed/skipped counts
    """
    import asyncio
    from .services.patterns.climb_signature import ClimbSignatureGenerator

    task_name = "backfill_pattern_signatures"
    start = time.perf_counter()
    _update_queue_depth()

    async def _process():
        repo = create_supabase_repository()
        generator = ClimbSignatureGenerator()

        try:
            # Get patterns without signatures
            result = repo.client.table("patterns_climb") \
                .select("id, activity_id, start_offset_s, end_offset_s") \
                .is_("signature_hex", "null") \
                .limit(limit) \
                .execute()

            patterns = result.data or []
            logger.info(f"[SignatureBackfill] Found {len(patterns)} patterns without signatures")

            if not patterns:
                return {"processed": 0, "success": 0, "failed": 0, "skipped": 0}

            success = 0
            failed = 0
            skipped = 0

            for pattern in patterns:
                pattern_id = pattern["id"]
                activity_id = pattern["activity_id"]
                start_s = pattern.get("start_offset_s", 0)
                end_s = pattern.get("end_offset_s", 0)

                try:
                    # Get tile samples for this climb's time range
                    samples_result = repo.client.table("activity_tile_samples") \
                        .select("t, elevation_m") \
                        .eq("activity_id", activity_id) \
                        .gte("t", start_s) \
                        .lte("t", end_s) \
                        .order("t") \
                        .execute()

                    # Filter samples with valid elevation
                    samples = [
                        s for s in (samples_result.data or [])
                        if s.get("elevation_m") is not None
                    ]

                    if len(samples) < 5:
                        logger.warning(
                            f"[SignatureBackfill] Pattern {pattern_id}: "
                            f"Not enough samples ({len(samples)}), skipping"
                        )
                        skipped += 1
                        continue

                    # Generate signature
                    elevations = [float(s["elevation_m"]) for s in samples]
                    timestamps = [int(s["t"]) for s in samples]

                    signature = generator.generate(elevations, timestamps)

                    if dry_run:
                        logger.info(
                            f"[SignatureBackfill] [DRY RUN] Would update pattern {pattern_id} "
                            f"with signature {signature.hex[:32]}..."
                        )
                    else:
                        # Update pattern with signature
                        repo.client.table("patterns_climb") \
                            .update({"signature_hex": signature.hex}) \
                            .eq("id", pattern_id) \
                            .execute()

                        logger.info(
                            f"[SignatureBackfill] Updated pattern {pattern_id} "
                            f"with signature {signature.hex[:32]}..."
                        )

                    success += 1

                except Exception as e:
                    logger.error(f"[SignatureBackfill] Pattern {pattern_id} failed: {e}")
                    failed += 1

            return {
                "processed": len(patterns),
                "success": success,
                "failed": failed,
                "skipped": skipped,
                "dry_run": dry_run,
            }
        finally:
            if hasattr(repo, "dispose"):
                await repo.dispose()

    try:
        result = asyncio.run(_process())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        logger.info(f"[SignatureBackfill] Complete: {result}")
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Signature backfill task failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


# =============================================================================
# STRAVA WEBHOOK + BACKFILL TASKS
# =============================================================================


@celery_app.task(bind=True, max_retries=3)
def process_strava_webhook_event(
    self,
    object_type: str,
    aspect_type: str,
    owner_id: int,
    object_id: int,
):
    """
    Process a Strava webhook event asynchronously.

    Handles:
    - activity.create: Download and import the new cycling activity
    - activity.update: Re-fetch metadata (future)
    - activity.delete: Soft-delete the ride (future)
    - athlete.deauthorize: Mark connection inactive
    """
    if not load_strava_settings().sync_enabled:
        logger.info(
            "[StravaWebhook] Ignoring queued event because Strava sync is retired"
        )
        return {"action": "ignored", "reason": "file_import_only"}

    import asyncio
    import uuid as uuid_module
    from .services.strava_service import StravaService
    from .services.strava_rate_limiter import get_strava_rate_limiter, Priority
    from .services.file_storage import create_file_storage_service

    task_name = "process_strava_webhook_event"
    start = time.perf_counter()
    _update_queue_depth()

    async def _process():
        strava = StravaService()

        # Strava webhook POSTs are unsigned. We avoid mutating connection state
        # on athlete.deauthorize events and instead rely on verified API failures
        # during normal Strava access to detect revocations.
        if object_type == "athlete" and aspect_type == "deauthorize":
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored("unsigned_deauthorize")
            logger.warning(
                "[StravaWebhook] Ignoring unsigned athlete.deauthorize event "
                "for athlete %s",
                owner_id,
            )
            return {"action": "ignored", "reason": "unsigned_deauthorize", "owner_id": owner_id}

        # Only process cycling activity creates
        if object_type != "activity" or aspect_type != "create":
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored(f"{object_type}.{aspect_type}")
            logger.info(
                f"[StravaWebhook] Ignoring event: {object_type}.{aspect_type}"
            )
            return {"action": "ignored", "reason": f"{object_type}.{aspect_type}"}

        # Look up connection by athlete ID
        connection = strava.get_connection_by_athlete_id(owner_id)
        if not connection:
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored("no_connection")
            logger.warning(
                f"[StravaWebhook] No active connection for athlete {owner_id}"
            )
            return {"action": "skipped", "reason": "no_connection"}

        # Refresh token if needed
        connection = await strava.ensure_valid_token(connection)

        # Check rate budget (realtime priority)
        rate_limiter = get_strava_rate_limiter()
        if not await rate_limiter.wait_for_capacity(cost=3, priority=Priority.REALTIME, max_wait=30):
            logger.warning("[StravaWebhook] Rate limited, will retry")
            raise self.retry(countdown=60)

        # Check if already imported (dedup)
        imported_ids = strava._get_imported_activity_ids(connection.id)
        if object_id in imported_ids:
            logger.info(f"[StravaWebhook] Activity {object_id} already imported")
            return {"action": "skipped", "reason": "already_imported"}

        # Get activity details to check if it's a cycling activity
        import httpx
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
                    f"[StravaWebhook] Failed to fetch activity {object_id}: "
                    f"{response.status_code}"
                )
                raise Exception(f"Strava API error: {response.status_code}")

            activity = response.json()

        activity_type = activity.get("type", "")
        if activity_type not in ("Ride", "VirtualRide", "EBikeRide"):
            record_strava_webhook_event(object_type, aspect_type, "ignored")
            record_strava_webhook_ignored(f"type={activity_type or 'unknown'}")
            logger.info(
                f"[StravaWebhook] Skipping non-cycling activity {object_id} "
                f"(type={activity_type})"
            )
            return {"action": "skipped", "reason": f"type={activity_type}"}

        from .repositories import create_user_repository
        user_repo = create_user_repository()
        user_id = await user_repo.get_user_id(connection.wallet)
        if not user_id:
            logger.warning(
                f"[StravaWebhook] No user found for wallet [redacted]"
            )
            return {"action": "skipped", "reason": "no_user"}

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
                raise RuntimeError(
                    f"Processing queue unavailable for existing provider ride {existing_provider_ride['id']}: "
                    f"{requeue.error}"
                )
            strava.mark_activity_imported(
                connection_id=connection.id,
                strava_activity_id=object_id,
                activity_id=existing_provider_ride["id"],
            )
            return {"action": "skipped", "reason": "existing_provider_ride"}

        privacy_policy = await ride_repo.resolve_ride_privacy_policy(user_id)

        # Download and process the activity
        file_data, file_type, import_diagnostics = await strava.download_activity_file_with_diagnostics(
            connection, object_id
        )

        # Upload to storage (same storage-first ingest path as manual uploads)
        storage = create_file_storage_service()

        file_hash = storage.compute_file_hash(file_data)

        # Check for duplicate by hash
        existing = await ride_repo.find_ride_by_hash(user_id, file_hash)
        if existing:
            logger.info(
                f"[StravaWebhook] Duplicate file hash for activity {object_id}"
            )
            existing_status = str(existing.get("processing_status") or "")
            if existing_status == "pending":
                ride = await ride_repo.get_ride(str(existing["id"]))
                file_path = (ride or {}).get("raw_file_path")
                pending_file_type = (ride or {}).get("file_type") or file_type
                if not file_path:
                    raise RuntimeError(f"Pending duplicate ride {existing['id']} missing raw_file_path")
                profile = await user_repo.get_user_profile(connection.wallet)
                user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0
                enqueue_result = await enqueue_ride_ingest(
                    RideIngestJob(
                        ride_id=str(existing["id"]),
                        wallet=connection.wallet,
                        user_id=user_id,
                        file_type=pending_file_type,
                        file_path=file_path,
                        user_weight_kg=user_weight,
                        source="strava_webhook_retry",
                        source_id=str(object_id),
                    )
                )
                if not enqueue_result.accepted:
                    raise RuntimeError(f"Processing queue unavailable for pending ride {existing['id']}")
                await ride_repo.update_ride_status(UUID(str(existing["id"])), "processing")
            strava.mark_activity_imported(
                connection_id=connection.id,
                strava_activity_id=object_id,
                activity_id=existing["id"],
            )
            return {"action": "skipped", "reason": "duplicate_hash"}

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
            await ride_repo.update_ride_status(
                UUID(ride_id),
                "pending",
                error_message=enqueue_result.error,
            )
            raise RuntimeError(f"Processing queue unavailable for ride {ride_id}")

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
            f"[StravaWebhook] Imported activity {object_id} as ride {ride_id} "
            f"for wallet [redacted]"
        )
        record_strava_webhook_event(object_type, aspect_type, "imported")
        return {"action": "imported", "ride_id": ride_id}

    try:
        result = asyncio.run(_process())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        record_strava_webhook_event(object_type, aspect_type, "error")
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception(f"Strava webhook processing failed: {exc}")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=5)
def backfill_strava_history(self, connection_id: str):
    """
    Historical backfill: page through all of a user's Strava cycling activities.

    Resumes from backfill_cursor if interrupted. Self-retries on rate limit.
    """
    if not load_strava_settings().sync_enabled:
        logger.info(
            "[StravaBackfill] Skipping queued history job because Strava sync is retired"
        )
        return {"status": "skipped", "reason": "file_import_only"}

    import asyncio
    import uuid as uuid_module
    from .services.strava_service import StravaService
    from .services.strava_rate_limiter import get_strava_rate_limiter, Priority
    from .services.file_storage import create_file_storage_service

    task_name = "backfill_strava_history"
    start = time.perf_counter()
    _update_queue_depth()

    async def _backfill():
        strava = StravaService()
        rate_limiter = get_strava_rate_limiter()
        storage = create_file_storage_service()
        ride_repo = create_ride_repository()

        # Load connection
        result = strava.db.table("strava_connections").select("*").eq(
            "id", connection_id
        ).limit(1).execute()

        if not result.data:
            logger.warning(f"[StravaBackfill] Connection {connection_id} not found")
            return {"status": "error", "reason": "connection_not_found"}

        row = result.data[0]
        if not row.get("is_active"):
            logger.info(f"[StravaBackfill] Connection {connection_id} inactive, skipping")
            return {"status": "skipped", "reason": "inactive"}

        connection = strava._row_to_connection(row)
        connection = await strava.ensure_valid_token(connection)

        # Read cursor (resume point)
        page = max(1, row.get("backfill_cursor", 0) or 1)
        total_synced = row.get("total_activities_synced", 0) or 0

        # Mark backfill as in progress
        strava.db.table("strava_connections").update({
            "backfill_status": "in_progress",
        }).eq("id", connection_id).execute()

        # Get already imported IDs
        imported_ids = strava._get_imported_activity_ids(connection.id)

        from .repositories import create_user_repository
        user_repo = create_user_repository()
        user_id = await user_repo.get_user_id(connection.wallet)
        if not user_id:
            return {"status": "error", "reason": "no_user"}

        privacy_policy = await ride_repo.resolve_ride_privacy_policy(user_id)
        profile = await user_repo.get_user_profile(connection.wallet)
        user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

        imported_this_run = 0
        per_page = 200

        while True:
            # Check rate budget (backfill priority — reserves headroom for realtime)
            if not await rate_limiter.wait_for_capacity(
                cost=1, priority=Priority.BACKFILL, max_wait=10,
            ):
                # Save cursor and retry later
                strava.db.table("strava_connections").update({
                    "backfill_cursor": page,
                    "total_activities_synced": total_synced + imported_this_run,
                }).eq("id", connection_id).execute()

                seconds_until = rate_limiter.seconds_until_15min_reset()
                logger.info(
                    f"[StravaBackfill] Rate limited at page {page}, "
                    f"retrying in {int(seconds_until)}s"
                )
                raise self.retry(countdown=int(seconds_until) + 5)

            # Fetch page of activities
            import httpx
            async with httpx.AsyncClient() as client:
                request_started = time.perf_counter()
                response = await client.get(
                    "https://www.strava.com/api/v3/athlete/activities",
                    headers={"Authorization": f"Bearer {connection.access_token}"},
                    params={"per_page": per_page, "page": page},
                )
                record_strava_api_request(
                    endpoint="athlete_activities",
                    method="GET",
                    status_code=response.status_code,
                    duration_seconds=time.perf_counter() - request_started,
                )
                rate_limiter.update_from_headers(dict(response.headers))

            if response.status_code == 429:
                # Explicit rate limit — save and retry
                strava.db.table("strava_connections").update({
                    "backfill_cursor": page,
                    "total_activities_synced": total_synced + imported_this_run,
                }).eq("id", connection_id).execute()
                raise self.retry(countdown=int(rate_limiter.seconds_until_15min_reset()) + 5)

            if response.status_code != 200:
                logger.error(
                    f"[StravaBackfill] API error: {response.status_code}"
                )
                raise Exception(f"Strava API error: {response.status_code}")

            activities = response.json()
            if not activities:
                # No more activities — backfill complete
                break

            for activity in activities:
                activity_id = activity.get("id")
                activity_type = activity.get("type", "")

                # Skip non-cycling
                if activity_type not in ("Ride", "VirtualRide", "EBikeRide"):
                    continue

                # Skip already imported
                if activity_id in imported_ids:
                    continue

                # Rate check per activity (needs ~3 calls: details + streams + download)
                if not await rate_limiter.wait_for_capacity(
                    cost=3, priority=Priority.BACKFILL, max_wait=10,
                ):
                    strava.db.table("strava_connections").update({
                        "backfill_cursor": page,
                        "total_activities_synced": total_synced + imported_this_run,
                    }).eq("id", connection_id).execute()
                    raise self.retry(
                        countdown=int(rate_limiter.seconds_until_15min_reset()) + 5,
                    )

                try:
                    file_data, file_type, import_diagnostics = await strava.download_activity_file_with_diagnostics(
                        connection, activity_id
                    )

                    file_hash = storage.compute_file_hash(file_data)
                    existing = await ride_repo.find_ride_by_hash(user_id, file_hash)
                    if existing:
                        existing_status = str(existing.get("processing_status") or "")
                        if existing_status == "pending":
                            ride = await ride_repo.get_ride(str(existing["id"]))
                            file_path = (ride or {}).get("raw_file_path")
                            pending_file_type = (ride or {}).get("file_type") or file_type
                            if not file_path:
                                raise RuntimeError(
                                    f"Pending duplicate ride {existing['id']} missing raw_file_path"
                                )
                            enqueue_result = await enqueue_ride_ingest(
                                RideIngestJob(
                                    ride_id=str(existing["id"]),
                                    wallet=connection.wallet,
                                    user_id=user_id,
                                    file_type=pending_file_type,
                                    file_path=file_path,
                                    user_weight_kg=user_weight,
                                    source="strava_backfill_retry",
                                    source_id=str(activity_id),
                                )
                            )
                            if not enqueue_result.accepted:
                                raise RuntimeError(
                                    f"Processing queue unavailable for pending ride {existing['id']}"
                                )
                            await ride_repo.update_ride_status(UUID(str(existing["id"])), "processing")
                        strava.mark_activity_imported(
                            connection_id=connection.id,
                            strava_activity_id=activity_id,
                            activity_id=existing["id"],
                        )
                        imported_ids.add(activity_id)
                        continue

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

                    enqueue_result = await enqueue_ride_ingest(
                        RideIngestJob(
                            ride_id=ride_id,
                            wallet=connection.wallet,
                            user_id=user_id,
                            file_type=file_type,
                            file_path=storage_result.path,
                            user_weight_kg=user_weight,
                            source="strava_backfill",
                            source_id=str(activity_id),
                        )
                    )
                    if not enqueue_result.accepted:
                        await ride_repo.update_ride_status(
                            UUID(ride_id),
                            "pending",
                            error_message=enqueue_result.error,
                        )
                        raise RuntimeError(f"Processing queue unavailable for ride {ride_id}")

                    strava.mark_activity_imported(
                        connection_id=connection.id,
                        strava_activity_id=activity_id,
                        activity_id=ride_id,
                    )
                    imported_ids.add(activity_id)

                    imported_this_run += 1
                    logger.info(
                        f"[StravaBackfill] Imported activity {activity_id} "
                        f"as ride {ride_id} (page {page})"
                    )

                except Exception as e:
                    logger.error(
                        f"[StravaBackfill] Failed to import activity {activity_id}: {e}"
                    )
                    continue

            # Save cursor after each page
            page += 1
            strava.db.table("strava_connections").update({
                "backfill_cursor": page,
                "total_activities_synced": total_synced + imported_this_run,
            }).eq("id", connection_id).execute()

            # If we got fewer than per_page, we've reached the end
            if len(activities) < per_page:
                break

        # Mark complete
        strava.db.table("strava_connections").update({
            "backfill_status": "complete",
            "backfill_cursor": page,
            "total_activities_synced": total_synced + imported_this_run,
        }).eq("id", connection_id).execute()

        logger.info(
            f"[StravaBackfill] Complete for connection {connection_id}: "
            f"{imported_this_run} imported this run"
        )
        return {
            "status": "complete",
            "imported": imported_this_run,
            "total_synced": total_synced + imported_this_run,
        }

    try:
        result = asyncio.run(_backfill())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception(f"Strava backfill task failed: {exc}")
        raise self.retry(exc=exc, countdown=120)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()


@celery_app.task(bind=True, max_retries=1)
def backfill_strava_incomplete(self):
    """
    Daily catch-up: find connections with backfill_status='in_progress' and re-queue them.

    Runs via Celery Beat to recover any interrupted backfills.
    """
    if not load_strava_settings().sync_enabled:
        logger.info(
            "[StravaBackfill] Skipping catch-up scan because Strava sync is retired"
        )
        return {"queued": 0, "reason": "file_import_only"}

    import asyncio
    from .services.strava_service import StravaService

    task_name = "backfill_strava_incomplete"
    start = time.perf_counter()
    _update_queue_depth()

    async def _process():
        strava = StravaService()
        result = strava.db.table("strava_connections").select("id").eq(
            "backfill_status", "in_progress"
        ).eq("is_active", True).execute()

        connections = result.data or []
        queued = 0

        for row in connections:
            backfill_strava_history.apply_async(
                kwargs={"connection_id": row["id"]},
                priority=9,
            )
            queued += 1

        logger.info(f"[StravaBackfill] Re-queued {queued} incomplete backfills")
        return {"queued": queued}

    try:
        result = asyncio.run(_process())
        CELERY_TASK_RUNS.labels(task=task_name, status="success").inc()
        return result
    except Exception as exc:
        CELERY_TASK_RUNS.labels(task=task_name, status="error").inc()
        logger.exception("Strava incomplete backfill check failed")
        raise self.retry(exc=exc, countdown=60)
    finally:
        CELERY_TASK_DURATION.labels(task=task_name).observe(time.perf_counter() - start)
        _update_queue_depth()
