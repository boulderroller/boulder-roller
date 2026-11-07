from .services.privacy_logging import scrub_log_text
from dataclasses import dataclass
import logging
from typing import AsyncGenerator, Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request, status

from .config import load_auth_settings
from .repositories import (
    # Legacy (deprecated but still needed for backwards compat)
    DatabaseRepository,
    create_supabase_repository,
    # Domain repositories
    AchievementRepository,
    AuthRepository,
    FitnessRepository,
    LeaderboardRepository,
    PatternRepository,
    RideRepository,
    SegmentRepository,
    TerritoryRepository,
    TileRepository,
    TokenRepository,
    UserRepository,
    VaultRepository,
    # Factories
    create_achievement_repository,
    create_auth_repository,
    create_fitness_repository,
    create_leaderboard_repository,
    create_pattern_repository,
    create_ride_repository,
    create_segment_repository,
    create_territory_repository,
    create_tile_repository,
    create_token_repository,
    create_user_repository,
    create_vault_repository,
)
from .security import verify_access_token
from .solana_client import BoulderRollersClient, get_solana_client as build_solana_client
from .services.strava_service import StravaService, create_strava_service


_logger = logging.getLogger(__name__)


@dataclass
class AuthenticatedUser:
    wallet: str
    user_id: str
    device_id: str
    session_token_hash: Optional[str] = None


_auth_settings = load_auth_settings()


async def get_repository() -> AsyncGenerator[DatabaseRepository, None]:
    """
    Dependency that creates the Supabase-backed repository
    and yields it to FastAPI endpoints.

    DEPRECATED: Use domain-specific repositories instead.
    """
    repo = create_supabase_repository()
    try:
        yield repo
    finally:
        if hasattr(repo, "disconnect"):
            await repo.disconnect()


def get_achievement_repository() -> AchievementRepository:
    """Dependency for achievement operations."""
    return create_achievement_repository()


def get_auth_repository() -> AuthRepository:
    """Dependency for authentication operations."""
    return create_auth_repository()


def get_fitness_repository() -> FitnessRepository:
    """Dependency for fitness/training load operations."""
    return create_fitness_repository()


def get_pattern_repository() -> PatternRepository:
    """Dependency for pattern operations."""
    return create_pattern_repository()


def get_ride_repository() -> RideRepository:
    """Dependency for ride operations."""
    return create_ride_repository()


def get_segment_repository() -> SegmentRepository:
    """Dependency for segment operations."""
    return create_segment_repository()


def get_territory_repository() -> TerritoryRepository:
    """Dependency for territory/map operations."""
    return create_territory_repository()


def get_tile_repository() -> TileRepository:
    """Dependency for tile/territory operations."""
    return create_tile_repository()


def get_token_repository() -> TokenRepository:
    """Dependency for token operations (CAL, DUNG, minting)."""
    return create_token_repository()


def get_user_repository() -> UserRepository:
    """Dependency for user operations."""
    return create_user_repository()


async def read_auth_account_authority(
    user_repo: UserRepository,
    wallet: str,
) -> dict[str, Optional[str]]:
    """Resolve identity and lifecycle state through the combined repository read.

    The compatibility branch exists for lightweight test doubles and older
    repository implementations. Production ``UserRepository`` uses one query.
    """
    combined_reader = getattr(user_repo, "get_auth_account_authority", None)
    if combined_reader:
        return await combined_reader(wallet)

    is_wallet_deleted = getattr(user_repo, "is_wallet_deleted", None)
    if is_wallet_deleted and await is_wallet_deleted(wallet):
        return {"user_id": None, "account_state": "anonymized"}
    get_account_state = getattr(user_repo, "get_account_state", None)
    account_state = await get_account_state(wallet) if get_account_state else None
    return {
        "user_id": await user_repo.get_user_id(wallet),
        "account_state": account_state,
    }


def _translate_auth_lifecycle_error(exc: Exception) -> None:
    message = str(exc).lower()
    if "account_deleted" in message:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "account_deleted",
                    "message": "Account has been deleted",
                }
            },
        ) from exc
    if any(
        marker in message
        for marker in (
            "account_deletion",
            "account_identity_write_fenced",
            "account_user",
            "auth_nonce_write_requires_fingerprint_fence",
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "account_deletion_pending",
                    "message": "Account deletion is in progress",
                }
            },
        ) from exc


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    user_repo: UserRepository = Depends(get_user_repository),
) -> AuthenticatedUser:
    """
    Resolve the bearer token and return the authenticated user (wallet + user_id).
    Supports both Authorization header (Bearer token) and HttpOnly cookies.
    """
    token = None

    # Try Authorization header first
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    # Fall back to HttpOnly cookie if no header
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )

    try:
        claims = verify_access_token(token, _auth_settings.access_token_secret, _auth_settings.audience)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc

    wallet = claims.get("sub")
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )

    try:
        authority = await read_auth_account_authority(user_repo, wallet)
        if not isinstance(authority, dict):
            raise RuntimeError("Auth account authority returned an invalid response")
    except HTTPException:
        raise
    except Exception as exc:
        _translate_auth_lifecycle_error(exc)
        _logger.warning(
            "[Auth] Account authority unavailable for %s: %s",
            "[redacted]",
            scrub_log_text(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "account_authority_unavailable",
                    "message": "Account authority is temporarily unavailable",
                }
            },
        ) from exc
    account_state = authority.get("account_state")
    if account_state in {"deletion_pending", "anonymized"}:
        code = (
            "account_deleted"
            if account_state == "anonymized"
            else "account_deletion_pending"
        )
        message = (
            "Account has been deleted"
            if account_state == "anonymized"
            else "Account deletion is in progress"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": code, "message": message}},
        )

    user_id = authority.get("user_id")
    if not user_id:
        try:
            user_id = await user_repo.create_user(wallet)
        except Exception as exc:
            _translate_auth_lifecycle_error(exc)
            raise

    device_id = claims.get("device_id", "unknown")
    session_token_hash = claims.get("session_token_hash")

    if request is not None:
        request.state.user_id = user_id
        request.state.wallet = wallet

    return AuthenticatedUser(
        wallet=wallet,
        user_id=user_id,
        device_id=device_id,
        session_token_hash=session_token_hash,
    )




async def get_solana_client() -> BoulderRollersClient:
    return build_solana_client()


def get_strava_service() -> StravaService:
    """Dependency for Strava OAuth and import operations."""
    return create_strava_service()


def get_vault_repository() -> VaultRepository:
    """Dependency for vault operations."""
    return create_vault_repository()


async def get_optional_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Optional[AuthenticatedUser]:
    """Like get_current_user but returns None for unauthenticated requests."""
    try:
        return await get_current_user(request, authorization, user_repo)
    except HTTPException:
        return None


async def get_optional_current_user_strict(
    request: Request,
    authorization: Optional[str] = Header(None),
    user_repo: UserRepository = Depends(get_user_repository),
) -> Optional[AuthenticatedUser]:
    """Allow anonymous browsing; preserve auth errors for supplied credentials."""
    if authorization is None:
        return None
    return await get_current_user(request, authorization, user_repo)


def get_leaderboard_repository() -> LeaderboardRepository:
    """Dependency for global leaderboard operations."""
    return create_leaderboard_repository()
