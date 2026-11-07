import os

from prometheus_client import start_http_server

# MODIFIED BY WORKER A: Provide a lightweight Celery fallback for test environments
try:
    from celery import Celery
except ModuleNotFoundError:
    class _DummyCelery:
        def __init__(self, *args, **kwargs) -> None:
            self.conf = {}

        def task(self, *args, **kwargs):
            def decorator(func):
                # Provide Celery-like delay/apply_async helpers for tests
                def _direct(*f_args, **f_kwargs):
                    return None

                setattr(func, "delay", _direct)
                setattr(func, "apply_async", _direct)
                setattr(func, "soft_time_limit", kwargs.get("soft_time_limit"))
                setattr(func, "time_limit", kwargs.get("time_limit"))
                return func

            return decorator

    Celery = _DummyCelery  # type: ignore

celery_app = Celery(
    "boulder_rollers",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)


def _maybe_start_metrics_server() -> None:
    port_value = os.getenv("CELERY_METRICS_PORT")
    if not port_value:
        return
    try:
        port = int(port_value)
    except ValueError:
        return
    if port <= 0:
        return
    start_http_server(port)


_maybe_start_metrics_server()

if hasattr(celery_app, "conf") and hasattr(celery_app.conf, "update"):
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=300,
        worker_prefetch_multiplier=1,
        imports=["app.tasks"],  # Explicitly import tasks module
        # Celery Beat schedule for periodic tasks
        beat_schedule={
            "process-cal-airdrops-every-5-min": {
                "task": "app.tasks.process_cal_airdrops",
                "schedule": 300.0,  # Every 5 minutes (300 seconds)
            },
            "process-vault-backfills-every-2-min": {
                "task": "app.tasks.process_pending_backfills",
                "schedule": 120.0,  # Every 2 minutes
            },
            "cleanup-stale-rides-every-10-min": {
                "task": "app.tasks.cleanup_stale_rides",
                "schedule": 600.0,  # Every 10 minutes
            },
            "recover-ride-economics-every-15-sec": {
                "task": "app.tasks.recover_ride_economics",
                "schedule": 15.0,
            },
            "recover-account-deletions-every-minute": {
                "task": "app.tasks.recover_account_deletions",
                "schedule": 60.0,
            },
            "recover-threshold-releases-every-15-sec": {
                "task": "app.tasks.recover_threshold_releases",
                "schedule": 15.0,
            },
            "seal-reward-threshold-mondays-every-minute": {
                "task": "app.tasks.seal_reward_threshold_promotions",
                "schedule": 60.0,
            },
        },
    )

    beat_schedule = celery_app.conf.get("beat_schedule", {})

    if os.getenv("ENABLE_LEADERBOARD_SYNC_BEAT", "false").lower() in ("1", "true", "yes", "on"):
        beat_schedule["sync-all-leaderboards-every-30-min"] = {
            "task": "app.tasks.sync_all_leaderboards",
            "schedule": 1800.0,  # Every 30 minutes
        }

    if os.getenv("ENABLE_FITNESS_ROLLUP_BEAT", "false").lower() in ("1", "true", "yes", "on"):
        beat_schedule["recompute-fitness-every-6-hours"] = {
            "task": "app.tasks.recompute_recent_fitness",
            "schedule": 21600.0,  # Every 6 hours
        }

    if os.getenv("ENABLE_STRAVA_BACKFILL_BEAT", "false").lower() in ("1", "true", "yes", "on"):
        beat_schedule["backfill-strava-incomplete-daily"] = {
            "task": "app.tasks.backfill_strava_incomplete",
            "schedule": 86400.0,  # Every 24 hours
        }

    celery_app.conf["beat_schedule"] = beat_schedule


# ── Worker initialization: load VaultSignatureCache once per worker process ──
try:
    from celery.signals import worker_process_init

    @worker_process_init.connect
    def _load_vault_cache_on_worker_start(**kwargs):
        """Load VaultSignatureCache and ClimbFrequencyMap when a Celery worker process starts.

        Without this, the cache singleton stays empty (_loaded=False) and
        PatternEngine.vault matching silently returns no matches.
        """
        import asyncio
        import logging

        _logger = logging.getLogger(__name__)
        try:
            from .repositories import get_supabase_client
            from .services.vault_indexer import get_vault_signature_cache
            from .services.pattern_engine import get_climb_frequency_map

            async def _load():
                client = get_supabase_client()
                cache = get_vault_signature_cache()
                vault_count = await cache.load(client)

                freq_map = get_climb_frequency_map()
                freq_count = await freq_map.load(client)

                return vault_count, freq_count

            vault_count, freq_count = asyncio.run(_load())
            _logger.info(
                f"[WorkerInit] VaultSignatureCache loaded: {vault_count} vaults, "
                f"ClimbFrequencyMap loaded: {freq_count} res-8 tiles"
            )
        except Exception as e:
            _logger.warning(
                f"[WorkerInit] Failed to load caches (non-fatal): {e}"
            )

except ImportError:
    pass  # Celery not installed (test/dummy environment)
