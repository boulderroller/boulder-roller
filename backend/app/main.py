import asyncio
import logging
import os
import re
import warnings

import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

logger = logging.getLogger(__name__)


from .services.privacy_logging import scrub_log_text
from .process_security import protect_process_environment
from .services.sentry_privacy import scrub_sentry_event as _scrub_sensitive_sentry_request_body

# Existing response validation policy; outbound Sentry filtering covers all paths.
_SENSITIVE_ERROR_RESPONSE_PATH = re.compile(
    r"(?:^|/)(?:auth/(?:invite/validate|verify|privy/verify)|admin/access(?:/.*)?|geocoding/search|privacy/zones(?:/.*)?)$"
)

from .config import (
    auth_signature_bypass_requested,
    dev_routes_enabled,
    get_environment,
    load_auth_settings,
)

# Initialize Sentry for error tracking
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    environment = get_environment()
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=environment,
        # Set sample rate for performance monitoring (adjust as needed)
        traces_sample_rate=0.1 if environment == "production" else 1.0,
        # Enable profiling for performance insights
        profiles_sample_rate=0.1 if environment == "production" else 1.0,
        # Outbound diagnostics are restricted again by both hooks below.
        send_default_pii=False,
        before_send=_scrub_sensitive_sentry_request_body,
        before_send_transaction=_scrub_sensitive_sentry_request_body,
    )
    logger.info("Sentry error tracking initialized")

from .repositories import get_supabase_client
from .middleware.client_contract import ClientContractMiddleware
from .middleware.emergency_check import EmergencyCheckMiddleware
from .middleware.metrics import MetricsMiddleware
from .routes import (
    admin,
    admin_platform,
    admin_significance,
    analytics,
    auth,
    balance_operations,
    beetles,
    cal,
    climbs,
    dev,
    distributions,
    feed,
    geocoding,
    compliance,
    interactions,
    health,
    links,
    mint,
    metadata,
    mobile,
    notifications,
    portfolio,
    stage1,
    proofs,
    privacy,
    rides,
    search,
    social,
    staking,
    strava,
    territory,
    users,
    public_previews,
    vaults,
    waitlist,
)


def _is_missing_schema_migrations_error(exc: Exception) -> bool:
    text = str(exc)
    return (
        "schema_migrations" in text
        and (
            "PGRST205" in text
            or "Could not find the table" in text
            or "schema cache" in text
        )
    )


async def check_migration_status(supabase) -> None:
    """Check if database migrations are up to date (non-blocking warning only)."""
    import os

    try:
        # Query the Supabase migrations table for the latest applied migration
        result = await asyncio.to_thread(
            lambda: supabase.table("schema_migrations")
            .select("version")
            .order("version", desc=True)
            .limit(1)
            .execute()
        )

        latest_db_version = None
        if result.data:
            latest_db_version = result.data[0].get("version")

        # Find the latest migration file in the codebase
        migrations_dir = os.path.join(
            os.path.dirname(__file__), "..", "supabase", "migrations"
        )
        migrations_dir = os.path.normpath(migrations_dir)

        if os.path.isdir(migrations_dir):
            migration_files = [
                f for f in os.listdir(migrations_dir)
                if f.endswith(".sql") and f[0].isdigit()
            ]
            if migration_files:
                # Migration files are named like 20260101214800_description.sql
                # The version is the timestamp prefix
                latest_file = sorted(migration_files)[-1]
                latest_file_version = latest_file.split("_")[0]

                if latest_db_version:
                    if latest_file_version > latest_db_version:
                        logger.warning(
                            f"Database migrations may be outdated! "
                            f"Latest in DB: {latest_db_version}, "
                            f"Latest in codebase: {latest_file_version} ({latest_file})"
                        )
                    else:
                        logger.info(
                            f"Database migrations up to date (version: {latest_db_version})"
                        )
                else:
                    logger.warning(
                        "No migrations found in schema_migrations table. "
                        "Database may not be initialized."
                    )
        else:
            logger.debug(f"Migrations directory not found: {migrations_dir}")

    except Exception as e:
        if _is_missing_schema_migrations_error(e):
            logger.info(
                "schema_migrations table is not present; skipping legacy migration status check"
            )
            return
        # Don't block startup on migration check failures
        logger.warning(f"Could not verify migration status (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    protect_process_environment()
    # Startup
    logger.info("Starting BoulderRollers API...")
    supabase = get_supabase_client()

    # Check migration status (non-blocking)
    await check_migration_status(supabase)

    logger.info(
        "Legacy Python vault writer retired; TypeScript indexer is the "
        "authoritative chain-read service"
    )

    # The API no longer owns chain indexing, but ride processing still needs a
    # local read cache of the indexer-owned vault projection for GPS matching.
    try:
        from .services.vault_indexer import get_vault_signature_cache

        vault_cache_count = await get_vault_signature_cache().load(supabase)
        logger.info(
            "Vault signature cache loaded from indexed_vaults: %d vaults",
            vault_cache_count,
        )
    except Exception as e:
        logger.warning(f"Failed to load vault signature cache (non-fatal): {e}")

    # Load climb frequency map for H12 Bayesian prior (non-blocking)
    try:
        from .services.pattern_engine import get_climb_frequency_map
        freq_map = get_climb_frequency_map()
        count = await freq_map.load(supabase)
        logger.info(f"Climb frequency map loaded: {count} distinct res-8 tiles")
    except Exception as e:
        logger.warning(f"Failed to load climb frequency map (non-fatal): {e}")

    enable_epoch_processor = os.getenv(
        "ENABLE_EPOCH_PROCESSOR",
        "true",
    ).lower() in ("1", "true", "yes")

    # Start epoch processor background task unless explicitly disabled. Smoke
    # gates drive targeted settlement directly and must not start a second
    # catch-up worker inside the TestClient lifespan.
    if enable_epoch_processor:
        try:
            from .services.epoch_processor import start_epoch_processor
            epoch_task = await start_epoch_processor(supabase)
            app.state.epoch_task = epoch_task
            logger.info("Epoch processor background task started")
        except Exception as e:
            logger.warning(f"Failed to start epoch processor (non-fatal): {e}")
    else:
        logger.warning("Epoch processor background task disabled by ENABLE_EPOCH_PROCESSOR")

    enable_threshold_runtime = os.getenv(
        "ENABLE_THRESHOLD_RUNTIME", "true"
    ).lower() in ("1", "true", "yes")
    if enable_threshold_runtime:
        try:
            from .services.threshold_runtime import create_threshold_runtime

            threshold_runtime = create_threshold_runtime()
            await threshold_runtime.start()
            app.state.threshold_runtime = threshold_runtime
            logger.info("Threshold seal and held-ride release runtime started")
        except Exception:
            logger.exception(
                "Threshold runtime failed to start; refusing a healthy API "
                "without automatic sealing and held-ride release recovery"
            )
            raise
    else:
        logger.warning(
            "Threshold runtime disabled by ENABLE_THRESHOLD_RUNTIME; "
            "sealing and held-ride releases will not converge automatically"
        )

    # Mobile push send worker (boulderroller-v2-k7387): feature-flagged OFF
    # by default until the APNs p8 exists; dry-run mode logs instead of
    # sending. Two categories only — settlement and displacement.
    try:
        from .services.mobile_push import push_worker_enabled, start_mobile_push_worker
        if push_worker_enabled():
            app.state.mobile_push_task = await start_mobile_push_worker()
            logger.info("Mobile push worker started")
        else:
            logger.info("Mobile push worker disabled by MOBILE_PUSH_WORKER_ENABLED")
    except Exception as e:
        logger.warning(f"Failed to start mobile push worker (non-fatal): {e}")

    # Connect NATS JetStream client (best-effort, non-blocking)
    try:
        from .services.nats_client import get_nats_client
        nats_client = get_nats_client()
        await nats_client.connect()
        app.state.nats_client = nats_client
        logger.info("NATS JetStream client connected")
    except Exception as e:
        logger.warning(f"Failed to connect NATS client (non-fatal): {e}")

    enable_nats_ride_consumer = os.getenv(
        "ENABLE_NATS_RIDE_CONSUMER",
        os.getenv("USE_NATS_PROCESSING", "true"),
    ).lower() in ("1", "true", "yes")

    # Start the NATS ride-processing consumer (also handles Strava webhooks
    # and stale-ride cleanup) unless explicitly disabled.
    if enable_nats_ride_consumer:
        try:
            from .services.nats_consumer import start_consumer
            await start_consumer()
            logger.info("NATS consumer started (rides + strava webhooks + stale cleanup)")
        except Exception as e:
            logger.warning(f"Failed to start NATS consumer (non-fatal): {e}")
    else:
        logger.warning(
            "NATS ride processing consumer disabled; no ride processing will occur"
        )

    yield

    # Shutdown
    logger.info("Shutting down BoulderRollers API...")
    if hasattr(app.state, "threshold_runtime"):
        await app.state.threshold_runtime.stop()
    if hasattr(app.state, "epoch_task"):
        app.state.epoch_task.cancel()
        try:
            await app.state.epoch_task
        except asyncio.CancelledError:
            pass
    # Stop NATS consumer/cleanup loop and close the singleton connection.
    try:
        from .services.nats_consumer import stop_consumer
        await stop_consumer()
        logger.info("NATS consumer and JetStream client stopped")
    except Exception as e:
        logger.warning(f"Error stopping NATS consumer/client: {e}")

    # Close shared asyncpg pool
    try:
        from .db_pool import close_pool
        await close_pool()
    except Exception as e:
        logger.warning(f"Error closing asyncpg pool: {e}")


def create_app() -> FastAPI:
    app = FastAPI(title="BoulderRollers API", version="0.1.0", lifespan=lifespan)

    # CORS configuration
    environment = get_environment()
    base_origins = [
        # Canonical product origin
        "https://app.boulderroller.xyz",
        # Foundation/marketing origins
        "https://boulderroller.xyz",
        "https://www.boulderroller.xyz",
        # Local development
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:4173",
        "http://localhost:4174",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:4174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ]
    extra_origins = [
        origin.strip()
        for origin in os.getenv("CORS_EXTRA_ORIGINS", "").split(",")
        if origin.strip()
    ]
    allowed_origins = base_origins + extra_origins
    allow_origin_regex = os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip() or None

    def is_origin_allowed(origin: str) -> bool:
        if origin in allowed_origins:
            return True
        if allow_origin_regex and re.fullmatch(allow_origin_regex, origin):
            return True
        return False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=allow_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # Keep origins constrained, but accept arbitrary requested headers so
        # browser-added tracing/observability metadata doesn't break preflight.
        allow_headers=["*"],
    )

    app.add_middleware(EmergencyCheckMiddleware)
    # Declared-contract enforcement runs inside metrics so refusals are
    # counted; requests without the headers pass untouched (L3.08).
    app.add_middleware(ClientContractMiddleware)
    app.add_middleware(MetricsMiddleware)

    auth_settings = load_auth_settings()
    if auth_settings.signature_bypass:
        warnings.warn("⚠️ AUTH_SIGNATURE_BYPASS is enabled! This should NEVER be used in production.")
    elif auth_signature_bypass_requested():
        logger.warning("AUTH_SIGNATURE_BYPASS was requested but is ignored in %s.", environment)

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(
        balance_operations.router,
        prefix="/balance/operations",
        tags=["balance-operations"],
    )
    app.include_router(distributions.router, prefix="/distributions", tags=["distributions"])
    app.include_router(social.router, prefix="/social", tags=["social"])
    app.include_router(social.moderation_router, tags=["moderation"])
    app.include_router(feed.router, prefix="/feed", tags=["feed"])
    app.include_router(geocoding.router, prefix="/geocoding", tags=["geocoding"])
    app.include_router(search.router, prefix="/search", tags=["search"])
    app.include_router(mobile.router)  # Crash-diagnostic ingest + push devices
    app.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
    app.include_router(links.router, prefix="/links", tags=["links"])
    app.include_router(interactions.router, tags=["interactions"])
    # routes/leaderboard.py (/leaderboard/climb, /steady, /exploration,
    # /arenas) stays unmounted: its climb board ranked other riders by W/kg,
    # which reveals body weight, and no client calls it.
    # (boulderroller-v2-pvrwy)
    app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
    app.include_router(stage1.router, prefix="/stage1", tags=["stage1"])
    app.include_router(proofs.router, prefix="/proofs", tags=["proofs"])
    app.include_router(rides.router, prefix="/rides", tags=["rides"])
    app.include_router(staking.router, prefix="/staking", tags=["staking"])
    app.include_router(mint.router, prefix="/mint", tags=["mint"])
    # Climbs router: mounted on canonical ``/climbs`` prefix and kept on
    # ``/segments`` as a back-compat alias so existing clients (iOS, portal,
    # bot, smoke scripts) keep working during the rename rollout.
    # Final cutover is tracked under wdvr.8 + 0uv8.
    app.include_router(climbs.router, prefix="/climbs")
    app.include_router(climbs.router, prefix="/segments")
    app.include_router(beetles.router)  # Beetle Cards - soulbound effort NFTs
    app.include_router(cal.router, prefix="/cal", tags=["cal"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
    app.include_router(strava.router, prefix="/strava", tags=["strava"])
    app.include_router(strava.admin_router, tags=["admin-strava"])
    app.include_router(territory.router, prefix="/territory", tags=["territory"])
    from .cohort_admission import PREPARATION_PATHS, require_cohort_admission
    for route in vaults.router.routes:
        if route.path in PREPARATION_PATHS and not any(
            dep.dependency is require_cohort_admission for dep in route.dependencies
        ):
            route.dependencies.append(Depends(require_cohort_admission))
    app.include_router(vaults.router)  # Vault discovery, matching, completions, staking
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(public_previews.router, prefix="/public/previews", tags=["public-previews"])
    app.include_router(privacy.router)  # Privacy zones for GPS redaction
    app.include_router(compliance.router, tags=["compliance"])
    from .routes import admin_access
    app.include_router(admin_access.router)
    app.include_router(admin.router, tags=["admin"])
    app.include_router(admin_platform.router, tags=["admin-platform"])
    app.include_router(admin_significance.router, tags=["admin-significance"])
    app.include_router(waitlist.router)
    app.include_router(health.router)
    app.include_router(metadata.router)
    enable_dev_routes = dev_routes_enabled(environment)
    if enable_dev_routes:
        app.include_router(dev.router)  # Tile dev dashboard
    else:
        logger.info("Dev routes are disabled (environment=%s).", environment)

    @app.exception_handler(RequestValidationError)
    async def access_validation_error(request: Request, exc: RequestValidationError):
        if _SENSITIVE_ERROR_RESPONSE_PATH.search(request.url.path) and (
            request.url.path.startswith('/auth/') or request.url.path.startswith('/admin/access')
        ):
            # Pydantic's input can contain the full malformed body and invite plaintext.
            return JSONResponse(status_code=422, content={'detail': [
                {key: error[key] for key in ('type', 'loc', 'msg') if key in error}
                for error in exc.errors()
            ]})
        return await request_validation_exception_handler(request, exc)

    # Global exception handler to ensure CORS headers on 500 errors
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", scrub_log_text(exc), exc_info=True)
        origin = request.headers.get("origin", "")
        # Check if origin is allowed (must match CORSMiddleware config above)
        cors_origin = origin if is_origin_allowed(origin) else ""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={
                "Access-Control-Allow-Origin": cors_origin,
                "Access-Control-Allow-Credentials": "true",
            } if cors_origin else {}
        )

    return app


app = create_app()
