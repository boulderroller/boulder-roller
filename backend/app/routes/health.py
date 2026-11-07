import logging
import asyncio
import hmac
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from starlette.responses import Response

from ..schemas import (
    HealthResponse,
    MobileCapabilities,
    SolBalanceResponse,
    StatusResponse,
)
from ..middleware.metrics import get_metrics
from ..config import (
    auth_cookie_secure_effective,
    auth_signature_bypass_effective,
    auth_signature_bypass_requested,
    dev_routes_enabled,
    get_app_version,
    get_environment,
    is_public_environment,
    load_auth_settings,
)
from ..dependencies import AuthenticatedUser, get_optional_current_user
from ..services.balance_production_rollout import get_balance_production_rollout
from ..services.strava_monitoring import refresh_strava_monitoring_gauges
from .admin import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# SOL balance cache: (balance_sol, wallet_pubkey, timestamp)
_sol_balance_cache: Dict[str, Any] = {}
_SOL_CACHE_TTL_SECONDS = 60  # Cache for 60 seconds
_SOL_ALERT_THRESHOLD = 0.5  # Alert when below 0.5 SOL
# Prometheus scrapes every 10 s. One RPC read per 15 minutes keeps the payer
# gauge current without spending the provider's monthly credits, and a failed
# read waits 5 minutes before the next try.
_SOL_SCRAPE_MAX_AGE_SECONDS = 900
_SOL_SCRAPE_RETRY_SECONDS = 300
_SOL_SCRAPE_RPC_TIMEOUT_SECONDS = 3
_sol_scrape_failed_at = 0.0


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Lightweight liveness check with no dependencies (no DB, no external calls)."""
    return HealthResponse(status="ok")


@router.get("/health/chain", tags=["monitoring"])
async def chain_health() -> Dict[str, Any]:
    """Read-only cutover readiness, independent of the liveness endpoint."""
    from ..solana_direct import get_program_config_account, load_readonly_config
    from ..program_compatibility import STAGE1_PROGRAM_VERSIONS

    try:
        config = await get_program_config_account(load_readonly_config())
        if config is None:
            raise ValueError("ProgramConfig is missing")
        return {
            "status": "ok",
            "program_version": config["program_version"],
            "stage1": "available" if config["program_version"] in STAGE1_PROGRAM_VERSIONS else "not available on this network",
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


async def require_metrics_access(
    authorization: Optional[str] = Header(default=None),
    x_prometheus_token: Optional[str] = Header(default=None),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    """Allow Prometheus token scrapes without making /metrics public."""
    expected = (os.getenv("PROMETHEUS_METRICS_TOKEN") or "").strip()
    presented = (x_prometheus_token or _bearer_token(authorization) or "").strip()
    if expected and presented and hmac.compare_digest(presented, expected):
        return "prometheus"
    if current_user:
        return await require_admin(current_user)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Metrics access required")


@router.get("/health/db", response_model=HealthResponse)
async def database_health() -> HealthResponse:
    """Database health check via direct asyncpg (avoids Supabase REST egress)."""
    try:
        from ..db_pool import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return HealthResponse(status="ok")
    except Exception as e:
        logger.warning("asyncpg health check failed, trying Supabase REST fallback: %s", e)
        # Fallback to Supabase REST if asyncpg is not configured
        try:
            from ..repositories import get_supabase_client
            import asyncio
            client = get_supabase_client()
            await asyncio.to_thread(
                lambda: client.table("users").select("id").limit(1).execute()
            )
            return HealthResponse(status="ok")
        except Exception as e2:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database connectivity check failed: {e2}",
            )


@router.get("/metrics", tags=["monitoring"])
async def metrics(_metrics_ctx=Depends(require_metrics_access)) -> Response:
    """Prometheus metrics endpoint."""
    await refresh_strava_monitoring_gauges()
    await _refresh_payer_balance_gauge()
    return get_metrics()


@router.get("/status", response_model=StatusResponse, tags=["monitoring"])
async def system_status() -> StatusResponse:
    """
    System status endpoint for frontend feature flags.

    Returns environment info and feature flags like stub mode.
    This endpoint is public (no auth required) so the frontend
    can show appropriate warnings before/during login.
    """
    environment = get_environment()
    solana_stub = _parse_bool(os.getenv("SOLANA_STUB"), default=False)
    version = get_app_version()

    return StatusResponse(
        environment=environment,
        environment_public=is_public_environment(environment),
        invite_required=load_auth_settings().require_invite_code,
        cohort_admission_required=load_auth_settings().cohort_admission_required,
        solana_stub_mode=solana_stub,
        version=version,
        auth_signature_bypass_requested=auth_signature_bypass_requested(),
        auth_signature_bypass_effective=auth_signature_bypass_effective(environment),
        auth_cookie_secure=auth_cookie_secure_effective(environment),
        dev_routes_enabled=dev_routes_enabled(environment),
        balance_rollout=get_balance_production_rollout(environment=environment).as_dict(),
        mobile_capabilities=get_mobile_capabilities(),
        stage1=await stage1_availability(),
    )


async def stage1_ui_live() -> bool:
    return (await stage1_availability())["live"]


async def stage1_availability():
    from ..services.stage1_availability import availability
    return await availability()


def get_mobile_capabilities() -> MobileCapabilities:
    """Each allowlisted capability reads its own env lever; default available.

    Only the exact value ``false`` disables — a typo can never silently
    kill a capability.
    """
    def enabled(name: str) -> bool:
        return os.getenv(f"BR_MOBILE_CAP_{name}", "true").strip().lower() != "false"

    return MobileCapabilities(
        ride_upload=enabled("RIDE_UPLOAD"),
        push_registration=enabled("PUSH_REGISTRATION"),
        profile_writes=enabled("PROFILE_WRITES"),
    )


async def _get_payer_pubkey() -> Optional[str]:
    """Get the configured fee payer wallet's base58 pubkey."""
    try:
        from ..solana_direct import load_fee_payer_keypair

        return str(load_fee_payer_keypair().pubkey())
    except Exception:
        return None


class _PayerBalanceUnavailable(Exception):
    """The payer balance could not be read; the message is safe to return."""


async def _query_payer_balance_lamports(wallet_pubkey: str, timeout_s: float) -> int:
    from solana.rpc.async_api import AsyncClient
    from solders.pubkey import Pubkey

    from ..solana_env import solana_rpc_url

    async with AsyncClient(solana_rpc_url(), timeout=timeout_s) as client:
        resp = await client.get_balance(Pubkey.from_string(wallet_pubkey))
    return resp.value


async def _read_payer_balance(
    max_age_s: float, timeout_s: float = 10
) -> tuple[float, str, bool]:
    """Return (balance_sol, wallet, cached), reading the RPC once the cache is older than max_age_s."""
    now = time.time()
    cached_at = _sol_balance_cache.get("cached_at", 0)
    balance = _sol_balance_cache.get("balance_sol")
    wallet = _sol_balance_cache.get("wallet")
    if (
        isinstance(cached_at, (int, float))
        and (now - cached_at) < max_age_s
        and isinstance(balance, (int, float))
        and isinstance(wallet, str)
    ):
        return float(balance), wallet, True

    wallet_pubkey = await _get_payer_pubkey()
    if not wallet_pubkey:
        raise _PayerBalanceUnavailable("Fee payer wallet not configured")
    try:
        lamports = await _query_payer_balance_lamports(wallet_pubkey, timeout_s)
    except Exception as e:
        logger.error("Failed to query SOL balance: %s", e)
        raise _PayerBalanceUnavailable("Failed to query Solana RPC") from e

    balance_sol = lamports / 1_000_000_000  # lamports to SOL
    _sol_balance_cache["balance_sol"] = balance_sol
    _sol_balance_cache["wallet"] = wallet_pubkey
    _sol_balance_cache["cached_at"] = now

    from ..metrics import SOLANA_PAYER_BALANCE_CHECKED, SOLANA_PAYER_BALANCE_SOL
    SOLANA_PAYER_BALANCE_SOL.set(balance_sol)
    SOLANA_PAYER_BALANCE_CHECKED.set(now)

    if balance_sol < _SOL_ALERT_THRESHOLD:
        logger.warning(
            "SOL balance LOW: %.4f SOL (threshold: %.1f SOL) wallet=%s",
            balance_sol, _SOL_ALERT_THRESHOLD, wallet_pubkey,
        )
    return balance_sol, wallet_pubkey, False


async def _refresh_payer_balance_gauge() -> None:
    """Best-effort refresh used before Prometheus scrapes."""
    global _sol_scrape_failed_at
    if time.time() - _sol_scrape_failed_at < _SOL_SCRAPE_RETRY_SECONDS:
        return
    try:
        await _read_payer_balance(
            _SOL_SCRAPE_MAX_AGE_SECONDS, _SOL_SCRAPE_RPC_TIMEOUT_SECONDS
        )
    except _PayerBalanceUnavailable as exc:
        _sol_scrape_failed_at = time.time()
        logger.debug("Skipping payer balance refresh during metrics scrape: %s", exc)


@router.get("/health/sol-balance", response_model=SolBalanceResponse, tags=["monitoring"])
async def sol_balance(_admin_ctx=Depends(require_admin)) -> SolBalanceResponse:
    """
    Check the payer wallet's SOL balance on Solana.

    Returns the balance and an alert flag if it drops below 0.5 SOL.
    Results are cached for 60 seconds to avoid hammering the RPC.
    """
    try:
        balance_sol, wallet, cached = await _read_payer_balance(_SOL_CACHE_TTL_SECONDS)
    except _PayerBalanceUnavailable as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    return SolBalanceResponse(
        balance_sol=round(balance_sol, 4),
        alert=balance_sol < _SOL_ALERT_THRESHOLD,
        wallet=wallet,
        cached=cached,
    )
