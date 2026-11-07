from ..services.privacy_logging import scrub_log_text
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response, status

from ..cohort_admission import AdmissionRepository, get_admission_repository
from ..invite_security import hash_invite_code, invite_cookie, read_invite_cookie
from ..config import get_environment, load_auth_settings
from ..dependencies import (
    AuthenticatedUser,
    get_auth_repository,
    get_optional_current_user,
    get_ride_repository,
    get_user_repository,
    read_auth_account_authority,
)
from ..middleware.rate_limiter import rate_limit
from ..metrics import KPI_LOGINS, observe_auth_funnel_stage, record_auth_funnel_event
from ..repositories import AuthRepository, RideRepository, UserRepository, get_supabase_client
from ..schemas import (
    AuthBootstrapResponse,
    InviteValidateRequest,
    InviteValidateResponse,
    LogoutRequest,
    NonceRequest,
    NonceResponse,
    OnboardingStateResponse,
    PrivyVerifyRequest,
    RefreshRequest,
    RefreshResponse,
    VerifyRequest,
    VerifyResponse,
)
from ..security import (
    build_siws_message,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_access_token,
    verify_refresh_token,
    verify_siws_signature,
    verify_privy_token,
    extract_wallet_from_claims,
    fetch_privy_user,
    extract_wallet_from_user,
)
from ..config import load_privy_settings
from ..services.notification_service import create_notification_service
from ..utils import get_client_ip
from .users import load_private_user_profile

router = APIRouter()
auth_settings = load_auth_settings()

import logging
_logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail={"error": {"code": code, "message": message}})


def _raise_account_deletion_authority_error(exc: Exception) -> None:
    """Translate database lifecycle fences into stable authentication refusals."""
    message = str(exc).lower()
    if "account_deleted" in message:
        raise AuthError(
            "account_deleted",
            "Account has been deleted",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc
    if any(
        code in message
        for code in (
            "account_deletion_pending",
            "account_deletion_write_fenced",
            "account_identity_write_fenced",
            "account_user_write_fenced",
            "account_user_create_requires_fingerprint_fence",
            "auth_nonce_write_requires_fingerprint_fence",
        )
    ):
        raise AuthError(
            "account_deletion_pending",
            "Account deletion is in progress",
            status.HTTP_401_UNAUTHORIZED,
        ) from exc


async def _read_active_auth_user_id(
    user_repo: UserRepository,
    wallet: str,
) -> Optional[str]:
    try:
        authority = await read_auth_account_authority(user_repo, wallet)
    except AuthError:
        raise
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise AuthError(
            "account_authority_unavailable",
            "Account authority is temporarily unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    account_state = authority.get("account_state")
    if account_state == "anonymized":
        raise AuthError(
            "account_deleted",
            "Account has been deleted",
            status.HTTP_401_UNAUTHORIZED,
        )
    if account_state == "deletion_pending":
        raise AuthError(
            "account_deletion_pending",
            "Account deletion is in progress",
            status.HTTP_401_UNAUTHORIZED,
        )
    return authority.get("user_id")


def _profile_value(profile: Any, field: str) -> Any:
    if profile is None:
        return None
    if isinstance(profile, dict):
        return profile.get(field)
    return getattr(profile, field, None)


def _profile_has_field(profile: Any, field: str) -> bool:
    if profile is None:
        return False
    if isinstance(profile, dict):
        return field in profile
    return hasattr(profile, field)


def _needs_profile_setup(profile: Any) -> bool:
    """Return whether first-run setup is incomplete.

    The explicit completion timestamp is the source of truth. A username fallback
    only exists so code can roll out safely while the migration is being applied.
    """
    if not profile:
        return True
    if _profile_has_field(profile, "profile_setup_completed_at"):
        return not bool(_profile_value(profile, "profile_setup_completed_at"))
    username = _profile_value(profile, "username")
    return not bool(isinstance(username, str) and username.strip())


REFRESH_ROTATION_GRACE_SECONDS = 30


def _is_recent_refresh_rotation(record: dict[str, Any], revoked_at: datetime) -> bool:
    reason = str(record.get("revocation_reason") or "")
    if reason != "rotated":
        return False
    now = datetime.now(timezone.utc)
    if revoked_at.tzinfo is None:
        revoked_at = revoked_at.replace(tzinfo=timezone.utc)
    return now - revoked_at <= timedelta(seconds=REFRESH_ROTATION_GRACE_SECONDS)


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
) -> None:
    """Set HttpOnly cookies for authentication tokens."""
    # Calculate max_age in seconds
    now = datetime.now(timezone.utc)
    access_max_age = int((access_expires_at - now).total_seconds())
    refresh_max_age = int((refresh_expires_at - now).total_seconds())

    # Access token cookie - shorter lived, sent with all requests
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=access_max_age,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
        domain=auth_settings.cookie_domain,
        path="/",
    )

    # Refresh token cookie - longer lived, only sent to /auth endpoints
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=refresh_max_age,
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
        domain=auth_settings.cookie_domain,
        path="/auth",  # Only send to auth endpoints for refresh
    )


def _normalize_invite_code(code: str) -> str:
    return code.strip().lower()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _dev_invite_codes() -> set[str]:
    codes_env = os.getenv("INVITE_CODES", "")
    return {_normalize_invite_code(code) for code in codes_env.split(",") if code.strip()}


def _is_dev_invite_code(code: str, *, already_hashed: bool = False) -> bool:
    if get_environment() == "production":
        return False
    candidates = _dev_invite_codes()
    if already_hashed:
        candidates = {hash_invite_code(candidate) for candidate in candidates}
    return code in candidates


def _invite_rpc_result(
    result: Any,
    fallback_message: str,
) -> tuple[bool, str, Optional[str]]:
    if result.data and len(result.data) > 0:
        row = result.data[0]
        return (
            row.get("valid", False),
            row.get("message", "Unknown error"),
            row.get("code_id"),
        )
    return (False, fallback_message, None)


async def _consume_invite_code_for_signup(
    code: str,
    wallet: str,
    ip_address: Optional[str],
    user_agent: Optional[str],
    email: Optional[str] = None,
    already_hashed: bool = False,
) -> tuple[bool, str, Optional[str]]:
    """
    Consume an invite code for a specific signup wallet.

    This is intentionally separate from pre-auth invite checks: checking tells
    the UI whether the code can be used, while this function records usage only
    after the canonical wallet is known.
    """
    normalized_code = _normalize_invite_code(code)
    try:
        supabase = get_supabase_client()
        result = supabase.rpc(
            "consume_invite_code",
            {
                "p_code": normalized_code if already_hashed else hash_invite_code(normalized_code),
                "p_wallet": wallet,
                "p_ip_address": ip_address,
                "p_user_agent": user_agent,
                "p_email": email,
            }
        ).execute()
        return _invite_rpc_result(result, "Invite consumption failed")
    except Exception as e:
        _raise_account_deletion_authority_error(e)
        _logger.error("Invite code consumption failed")
        if _is_dev_invite_code(normalized_code, already_hashed=already_hashed):
            return (True, "Invite code consumed (dev mode)", None)
        return (False, "Invite service unavailable", None)


def _set_invite_cookie(response: Response, invite_code: str) -> None:
    """Persist checked invite code in an HttpOnly cookie until sign-in completes."""
    response.set_cookie(
        key="invite_code",
        value=invite_cookie(invite_code),
        max_age=15 * 60,  # 15 minutes
        httponly=True,
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
        domain=auth_settings.cookie_domain,
        path="/auth",
    )


def _clear_invite_cookie(response: Response) -> None:
    response.delete_cookie(
        key="invite_code",
        domain=auth_settings.cookie_domain,
        path="/auth",
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key="access_token",
        domain=auth_settings.cookie_domain,
        path="/",
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
    )
    response.delete_cookie(
        key="refresh_token",
        domain=auth_settings.cookie_domain,
        path="/auth",
        secure=auth_settings.cookie_secure,
        samesite=auth_settings.cookie_samesite,
    )


@router.post("/nonce", response_model=NonceResponse)
@rate_limit(category="auth")
async def issue_nonce(
    request: Request,
    payload: NonceRequest = Body(...),
    auth_repo: AuthRepository = Depends(get_auth_repository),
) -> NonceResponse:
    stage_started = time.perf_counter()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=auth_settings.nonce_ttl_seconds)
    nonce = secrets.token_urlsafe(32)
    try:
        record = await auth_repo.save_nonce(
            wallet=payload.wallet,
            nonce=nonce,
            issued_at=issued_at,
            expires_at=expires_at,
            device_id=str(payload.device_id),
        )
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise
    issued = _parse_datetime(record.get("issued_at")) or issued_at
    expires = _parse_datetime(record.get("expires_at")) or expires_at
    final_nonce = record.get("nonce", nonce)

    # Build the full SIWS message for client to sign
    message = build_siws_message(
        payload.wallet,
        final_nonce,
        issued,
        expires,
        domain=auth_settings.domain,
        uri=auth_settings.uri,
        chain=auth_settings.chain,
        intent=auth_settings.intent,
    )

    record_auth_funnel_event("nonce_issue", "success")
    observe_auth_funnel_stage("nonce_issue", time.perf_counter() - stage_started)
    return NonceResponse(nonce=final_nonce, message=message, issued_at=issued, expires_at=expires)


@router.post("/verify", response_model=VerifyResponse)
@rate_limit(category="auth")
async def verify_signature(
    request: Request,
    response: Response,
    payload: VerifyRequest = Body(...),
    auth_repo: AuthRepository = Depends(get_auth_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> VerifyResponse:
    stage_started = time.perf_counter()
    record = await auth_repo.get_nonce(payload.nonce)
    if record is None:
        raise AuthError("nonce_not_found", "Nonce not found", status.HTTP_400_BAD_REQUEST)

    expected_wallet = record.get("wallet")
    if expected_wallet != payload.wallet:
        raise AuthError("nonce_wallet_mismatch", "Nonce wallet mismatch", status.HTTP_400_BAD_REQUEST)

    expected_device = record.get("device_id")
    if expected_device and expected_device != str(payload.device_id):
        raise AuthError("device_mismatch", "Device mismatch", status.HTTP_400_BAD_REQUEST)

    if record.get("used_at") is not None:
        raise AuthError("nonce_used", "Nonce already used", status.HTTP_400_BAD_REQUEST)

    expires_at = _parse_datetime(record.get("expires_at"))
    if not expires_at or expires_at < datetime.now(timezone.utc):
        raise AuthError("nonce_expired", "Nonce expired", status.HTTP_400_BAD_REQUEST)

    issued_at = _parse_datetime(record.get("issued_at"))
    if issued_at is None:
        issued_at = datetime.now(timezone.utc)

    message = build_siws_message(
        payload.wallet,
        payload.nonce,
        issued_at,
        expires_at,
        domain=auth_settings.domain,
        uri=auth_settings.uri,
        chain=auth_settings.chain,
        intent=auth_settings.intent,
    )
    if not auth_settings.signature_bypass:
        try:
            verify_siws_signature(payload.wallet, payload.signature, message)
        except ValueError as exc:  # pragma: no cover - signature mismatch
            raise AuthError("signature_invalid", str(exc), status.HTTP_401_UNAUTHORIZED) from exc

    try:
        nonce_consumed = await auth_repo.consume_nonce(
            uuid.UUID(record["id"]),
            payload.wallet,
        )
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise
    if not nonce_consumed:
        raise AuthError("nonce_used", "Nonce already used", status.HTTP_400_BAD_REQUEST)

    # Check if this wallet already exists (returning user vs new signup)
    existing_user_id = await _read_active_auth_user_id(user_repo, payload.wallet)
    linked_wallet_user_id = await auth_repo.get_identity_user_id(
        provider="wallet",
        provider_subject=payload.wallet,
    )
    if existing_user_id and linked_wallet_user_id and existing_user_id != linked_wallet_user_id:
        raise AuthError(
            "identity_conflict",
            "Wallet identity is linked to another user",
            status.HTTP_409_CONFLICT,
        )
    existing_user_id = existing_user_id or linked_wallet_user_id
    is_new_user = existing_user_id is None

    # Enforce invite code for NEW users only (returning users don't need it)
    if is_new_user and auth_settings.require_invite_code:
        invite_code = payload.invite_code or request.cookies.get("invite_code")
        if not invite_code:
            raise AuthError(
                "invite_required",
                "Invite code required for new signups",
                status.HTTP_403_FORBIDDEN
            )

        ip_address = get_client_ip(request)
        user_agent = request.headers.get("user-agent")

        is_valid, message, code_id = await _consume_invite_code_for_signup(
            code=invite_code if payload.invite_code else read_invite_cookie(invite_code),
            wallet=payload.wallet,
            ip_address=ip_address,
            user_agent=user_agent,
            already_hashed=not bool(payload.invite_code),
        )

        if not is_valid:
            raise AuthError(
                "invite_invalid",
                message,
                status.HTTP_403_FORBIDDEN
            )

        _logger.info("[Auth] Signup invite accepted invite_id=%s", code_id)

    try:
        user_id = existing_user_id or await user_repo.create_user(payload.wallet)
        await auth_repo.link_wallet_identity(user_id=user_id, wallet=payload.wallet)
    except ValueError as exc:
        raise AuthError(
            "identity_conflict",
            "Wallet identity is linked to another user",
            status.HTTP_409_CONFLICT,
        ) from exc
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise

    access_expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.access_token_minutes)
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(days=auth_settings.refresh_token_days)

    refresh_token = create_refresh_token(
        subject=payload.wallet,
        secret=auth_settings.refresh_token_secret,
        audience=auth_settings.audience,
        days=auth_settings.refresh_token_days,
        extra_claims={"device_id": str(payload.device_id), "auth_method": "wallet"},
    )
    token_hash = hash_refresh_token(refresh_token)
    access_token = create_access_token(
        subject=payload.wallet,
        secret=auth_settings.access_token_secret,
        audience=auth_settings.audience,
        minutes=auth_settings.access_token_minutes,
        extra_claims={
            "device_id": str(payload.device_id),
            "auth_method": "wallet",
            "session_token_hash": token_hash,
        },
    )
    user_agent = request.headers.get("user-agent")

    # Check if this is a new device for this wallet (before storing token)
    is_new_device = not await auth_repo.is_device_known(payload.wallet, str(payload.device_id))

    try:
        await auth_repo.store_refresh_token(
            wallet=payload.wallet,
            device_id=str(payload.device_id),
            token_hash=token_hash,
            expires_at=refresh_expires_at,
            user_agent=user_agent,
        )
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise

    # Send notification for new device login (only for existing users, not new signups)
    if is_new_device and not is_new_user:
        try:
            notification_service = create_notification_service()
            ip_address = get_client_ip(request)
            await notification_service.notify_login_from_new_device(
                wallet=payload.wallet,
                device_id=str(payload.device_id),
                user_agent=user_agent,
                ip_address=ip_address,
            )
        except Exception as e:
            _logger.warning("[Auth] Failed to send new device notification error=%s", scrub_log_text(e))

    # Seed CAL for new users if no user_state exists
    existing_state = await user_repo.get_user_state(user_id)
    if not existing_state:
        now = datetime.now(timezone.utc)
        await user_repo.update_user_state(
            user_id,
            {
                "cal_balance": 2500.0,
                "cal_earned_today": 0.0,
                "last_cal_mint": now.isoformat(),
                "next_cal_airdrop": (now + timedelta(hours=24)).isoformat(),
            },
        )

    KPI_LOGINS.inc()

    # Set HttpOnly cookies for secure token storage
    _set_auth_cookies(response, access_token, refresh_token, access_expires_at, refresh_expires_at)
    _clear_invite_cookie(response)

    record_auth_funnel_event("verify_wallet", "success")
    observe_auth_funnel_stage("verify_wallet", time.perf_counter() - stage_started)
    return VerifyResponse(
        user_id=uuid.UUID(user_id),
        wallet=payload.wallet,
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at,
    )


@router.post("/privy/verify", response_model=VerifyResponse)
@rate_limit(category="auth")
async def verify_privy(
    request: Request,
    response: Response,
    payload: PrivyVerifyRequest = Body(...),
    auth_repo: AuthRepository = Depends(get_auth_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> VerifyResponse:
    """
    Verify a Privy access token and issue our own JWT tokens.

    This endpoint is used when users authenticate via Privy (social login).
    We verify the Privy token, extract the wallet address, and issue our tokens.
    """
    stage_started = time.perf_counter()
    privy_settings = load_privy_settings()
    if not privy_settings.enabled:
        record_auth_funnel_event("verify_privy", "privy_disabled")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_disabled", "Privy authentication is not enabled", status.HTTP_503_SERVICE_UNAVAILABLE)

    # Verify the Privy token
    try:
        claims = verify_privy_token(payload.privy_token)
    except ValueError as exc:
        record_auth_funnel_event("verify_privy", "privy_invalid")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_invalid", str(exc), status.HTTP_401_UNAUTHORIZED) from exc

    # Privy access tokens are minimal session proofs and do NOT contain
    # `linked_accounts` — they only have `sid`, `iss`, `iat`, `aud`, `sub`, `exp`.
    # To resolve the wallet and email we must call Privy's server API with the
    # app secret and the `sub` claim as the user ID.
    sub = claims.get("sub")
    if not sub:
        record_auth_funnel_event("verify_privy", "privy_invalid")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_invalid", "Privy token missing subject", status.HTTP_401_UNAUTHORIZED)
    try:
        privy_user = fetch_privy_user(sub)
    except ValueError as exc:
        _logger.warning("[Auth] Failed to fetch Privy user error=%s", scrub_log_text(exc))
        record_auth_funnel_event("verify_privy", "privy_no_wallet")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_no_wallet", f"Unable to resolve Privy user: {exc}", status.HTTP_400_BAD_REQUEST) from exc

    token_wallet = extract_wallet_from_user(privy_user)
    if not token_wallet:
        record_auth_funnel_event("verify_privy", "privy_no_wallet")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_no_wallet", "No Solana wallet linked to Privy user", status.HTTP_400_BAD_REQUEST)

    # Extract email from the Privy user (best-effort) so the backend can
    # dedupe / recover accounts by email later. Privy stores emails either as
    # a top-level `linked_accounts[type=email]` entry (OTP login) or nested in
    # an OAuth account (Google/Apple).
    privy_email: Optional[str] = None
    for account in privy_user.get("linked_accounts", []):
        if account.get("type") == "email" and account.get("address"):
            privy_email = account["address"]
            break
    if not privy_email:
        for account in privy_user.get("linked_accounts", []):
            if account.get("type") in ("google_oauth", "apple_oauth") and account.get("email"):
                privy_email = account["email"]
                break

    if token_wallet.lower() != payload.wallet.lower():
        record_auth_funnel_event("verify_privy", "privy_wallet_mismatch")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError("privy_wallet_mismatch", "Wallet address mismatch", status.HTTP_400_BAD_REQUEST)

    privy_subject = sub

    # Deterministic identity resolution:
    # 1) wallet user
    # 2) privy subject user
    # 3) conflict if they point to different users
    wallet_user_id = await _read_active_auth_user_id(user_repo, payload.wallet)
    privy_user_id = await auth_repo.get_identity_user_id(provider="privy", provider_subject=privy_subject)

    if wallet_user_id and privy_user_id and wallet_user_id != privy_user_id:
        _logger.warning(
            "[Auth] Identity conflict wallet_user_id=%s privy_user_id=%s",
            wallet_user_id,
            privy_user_id,
        )
        record_auth_funnel_event("verify_privy", "identity_conflict")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError(
            "identity_conflict",
            "Privy identity is linked to another wallet user",
            status.HTTP_409_CONFLICT,
        )

    existing_user_id = wallet_user_id or privy_user_id
    is_new_user = existing_user_id is None

    # Enforce invite code for NEW users only (returning users don't need it)
    if is_new_user and auth_settings.require_invite_code:
        invite_code = payload.invite_code or request.cookies.get("invite_code")
        if not invite_code:
            raise AuthError(
                "invite_required",
                "Invite code required for new signups",
                status.HTTP_403_FORBIDDEN
            )

        ip_address = get_client_ip(request)
        user_agent = request.headers.get("user-agent")

        is_valid, message, code_id = await _consume_invite_code_for_signup(
            code=invite_code if payload.invite_code else read_invite_cookie(invite_code),
            wallet=payload.wallet,
            ip_address=ip_address,
            user_agent=user_agent,
            email=privy_email,
            already_hashed=not bool(payload.invite_code),
        )

        if not is_valid:
            raise AuthError(
                "invite_invalid",
                message,
                status.HTTP_403_FORBIDDEN
            )

        _logger.info("[Auth] Privy signup invite accepted invite_id=%s", code_id)

    # Create or get user. Pass email to new users so `users.email` is populated
    # from the start. For returning users whose email slot is empty (e.g. rows
    # created before this fix landed), backfill it now.
    try:
        if existing_user_id:
            user_id = existing_user_id
            if privy_email:
                try:
                    existing_profile = await user_repo.get_user_profile(payload.wallet)
                    if existing_profile and not existing_profile.get("email"):
                        await user_repo.update_user_profile(
                            payload.wallet,
                            {"email": privy_email},
                        )
                except Exception as exc:
                    _raise_account_deletion_authority_error(exc)
                    _logger.warning(
                        '[Auth] Privy email backfill failed user_id=%s error_type=%s',
                        user_id,
                        scrub_log_text(exc),
                    )
        else:
            user_id = await user_repo.create_user(payload.wallet, email=privy_email)
        await auth_repo.link_wallet_identity(user_id=user_id, wallet=payload.wallet)
        await auth_repo.link_privy_identity(
            user_id=user_id,
            privy_subject=privy_subject,
            wallet=payload.wallet,
            metadata={"issuer": claims.get("iss"), "aud": claims.get("aud")},
        )
    except ValueError as exc:
        record_auth_funnel_event("verify_privy", "identity_conflict")
        observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
        raise AuthError(
            "identity_conflict",
            "Privy identity is linked to another user",
            status.HTTP_409_CONFLICT,
        ) from exc
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise

    # Issue our tokens
    access_expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.access_token_minutes)
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(days=auth_settings.refresh_token_days)

    refresh_token = create_refresh_token(
        subject=payload.wallet,
        secret=auth_settings.refresh_token_secret,
        audience=auth_settings.audience,
        days=auth_settings.refresh_token_days,
        extra_claims={"device_id": str(payload.device_id), "auth_method": "privy"},
    )
    token_hash = hash_refresh_token(refresh_token)
    access_token = create_access_token(
        subject=payload.wallet,
        secret=auth_settings.access_token_secret,
        audience=auth_settings.audience,
        minutes=auth_settings.access_token_minutes,
        extra_claims={
            "device_id": str(payload.device_id),
            "auth_method": "privy",
            "session_token_hash": token_hash,
        },
    )
    user_agent = request.headers.get("user-agent")

    # Check if this is a new device for this wallet (before storing token)
    is_new_device = not await auth_repo.is_device_known(payload.wallet, str(payload.device_id))

    try:
        await auth_repo.store_refresh_token(
            wallet=payload.wallet,
            device_id=str(payload.device_id),
            token_hash=token_hash,
            expires_at=refresh_expires_at,
            user_agent=user_agent,
        )
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise

    # Send notification for new device login (only for existing users, not new signups)
    if is_new_device and not is_new_user:
        try:
            notification_service = create_notification_service()
            ip_address = get_client_ip(request)
            await notification_service.notify_login_from_new_device(
                wallet=payload.wallet,
                device_id=str(payload.device_id),
                user_agent=user_agent,
                ip_address=ip_address,
            )
        except Exception as e:
            _logger.warning("[Auth] Failed to send new device notification error=%s", scrub_log_text(e))

    # Seed CAL for new users
    existing_state = await user_repo.get_user_state(user_id)
    if not existing_state:
        now = datetime.now(timezone.utc)
        await user_repo.update_user_state(
            user_id,
            {
                "cal_balance": 2500.0,
                "cal_earned_today": 0.0,
                "last_cal_mint": now.isoformat(),
                "next_cal_airdrop": (now + timedelta(hours=24)).isoformat(),
            },
        )

    KPI_LOGINS.inc()

    # Set HttpOnly cookies for secure token storage
    _set_auth_cookies(response, access_token, refresh_token, access_expires_at, refresh_expires_at)
    _clear_invite_cookie(response)

    record_auth_funnel_event("verify_privy", "success")
    observe_auth_funnel_stage("verify_privy", time.perf_counter() - stage_started)
    return VerifyResponse(
        user_id=uuid.UUID(user_id),
        wallet=payload.wallet,
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at,
    )


@router.post("/refresh", response_model=RefreshResponse)
@rate_limit(category="auth")
async def refresh_tokens(
    request: Request,
    response: Response,
    payload: RefreshRequest = Body(...),
    auth_repo: AuthRepository = Depends(get_auth_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> RefreshResponse:
    stage_started = time.perf_counter()
    # Accept refresh token from cookie (web browsers) or request body (mobile apps).
    refresh_token = (
        request.cookies.get("refresh_token")  # 1. Cookie (web browsers)
        or payload.refresh_token               # 2. Request body (mobile apps)
    )
    if not refresh_token:
        record_auth_funnel_event("refresh", "refresh_missing")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_missing", "No refresh token provided", status.HTTP_401_UNAUTHORIZED)

    try:
        claims = verify_refresh_token(
            refresh_token,
            auth_settings.refresh_token_secret,
            auth_settings.audience,
        )
    except jwt.PyJWTError as exc:
        record_auth_funnel_event("refresh", "refresh_invalid")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_invalid", "Invalid refresh token", status.HTTP_401_UNAUTHORIZED) from exc

    wallet = claims.get("sub")
    if not wallet:
        record_auth_funnel_event("refresh", "refresh_invalid")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_invalid", "Invalid refresh token", status.HTTP_401_UNAUTHORIZED)

    active_user_id = await _read_active_auth_user_id(user_repo, wallet)
    if not active_user_id:
        # Verification may create a user behind the database fingerprint fence,
        # but refresh must never mint a new session for a missing identity. This
        # also fails closed if tombstone authority is temporarily unavailable
        # while a best-effort refresh-token row survives account deletion.
        record_auth_funnel_event("refresh", "account_identity_unavailable")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError(
            "account_identity_unavailable",
            "Account identity is unavailable",
            status.HTTP_401_UNAUTHORIZED,
        )

    token_hash = hash_refresh_token(refresh_token)
    record = await auth_repo.get_refresh_token(token_hash)
    if not record:
        # Valid JWT but absent from the store is suspicious, but not proof of
        # replay. Older code deleted rows on rotation, so blind all-session
        # revocation here can punish benign clients.
        record_auth_funnel_event("refresh", "refresh_unknown")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError(
            "refresh_unknown",
            "Refresh token is not recognized",
            status.HTTP_401_UNAUTHORIZED,
        )

    if record.get("wallet") != wallet or record.get("device_id") != str(payload.device_id):
        record_auth_funnel_event("refresh", "refresh_mismatch")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_mismatch", "Refresh token mismatch", status.HTTP_401_UNAUTHORIZED)

    revoked_at = _parse_datetime(record.get("revoked_at"))
    if revoked_at is not None:
        if _is_recent_refresh_rotation(record, revoked_at):
            record_auth_funnel_event("refresh", "refresh_rotated")
            observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
            raise AuthError(
                "refresh_rotated",
                "Refresh token was already rotated; retry with the latest session cookie",
                status.HTTP_409_CONFLICT,
            )
        if record.get("revocation_reason") == "rotated":
            await auth_repo.revoke_all_sessions(
                wallet=wallet,
                include_current=True,
                current_token_hash=token_hash,
                reason="refresh_reuse_detected",
            )
            record_auth_funnel_event("refresh", "refresh_reuse_detected")
            observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
            raise AuthError(
                "refresh_reuse_detected",
                "Refresh token reuse detected; sessions revoked",
                status.HTTP_401_UNAUTHORIZED,
            )
        record_auth_funnel_event("refresh", "refresh_revoked")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_revoked", "Refresh token revoked", status.HTTP_401_UNAUTHORIZED)

    expires_at = _parse_datetime(record.get("expires_at"))
    if not expires_at or expires_at < datetime.now(timezone.utc):
        record_auth_funnel_event("refresh", "refresh_expired")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_expired", "Refresh token expired", status.HTTP_401_UNAUTHORIZED)

    access_expires_at = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.access_token_minutes)
    refresh_expires_at = datetime.now(timezone.utc) + timedelta(days=auth_settings.refresh_token_days)

    new_refresh_token = create_refresh_token(
        wallet,
        auth_settings.refresh_token_secret,
        auth_settings.audience,
        auth_settings.refresh_token_days,
        extra_claims={
            "device_id": str(payload.device_id),
            **({"auth_method": claims.get("auth_method")} if claims.get("auth_method") else {}),
        },
    )
    new_hash = hash_refresh_token(new_refresh_token)
    access_token = create_access_token(
        wallet,
        auth_settings.access_token_secret,
        auth_settings.audience,
        auth_settings.access_token_minutes,
        extra_claims={
            "device_id": str(payload.device_id),
            "session_token_hash": new_hash,
            **({"auth_method": claims.get("auth_method")} if claims.get("auth_method") else {}),
        },
    )
    user_agent = request.headers.get("user-agent")
    try:
        rotated = await auth_repo.rotate_refresh_token(
            old_token_hash=token_hash,
            new_token_hash=new_hash,
            wallet=wallet,
            device_id=str(payload.device_id),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            rotated_at=datetime.now(timezone.utc),
        )
    except Exception as exc:
        _raise_account_deletion_authority_error(exc)
        raise
    if not rotated:
        latest = await auth_repo.get_refresh_token(token_hash)
        latest_revoked_at = _parse_datetime((latest or {}).get("revoked_at"))
        if latest and latest_revoked_at and _is_recent_refresh_rotation(latest, latest_revoked_at):
            record_auth_funnel_event("refresh", "refresh_rotated")
            observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
            raise AuthError(
                "refresh_rotated",
                "Refresh token was already rotated; retry with the latest session cookie",
                status.HTTP_409_CONFLICT,
            )
        record_auth_funnel_event("refresh", "refresh_revoked")
        observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
        raise AuthError("refresh_revoked", "Refresh token revoked", status.HTTP_401_UNAUTHORIZED)

    # Set HttpOnly cookies for secure token storage
    _set_auth_cookies(response, access_token, new_refresh_token, access_expires_at, refresh_expires_at)

    record_auth_funnel_event("refresh", "success")
    observe_auth_funnel_stage("refresh", time.perf_counter() - stage_started)
    return RefreshResponse(
        wallet=wallet,
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=new_refresh_token,
        refresh_expires_at=refresh_expires_at,
    )


@router.post("/logout")
@rate_limit(category="auth")
async def logout(
    request: Request,
    response: Response,
    payload: Optional[LogoutRequest] = Body(default=None),
    auth_repo: AuthRepository = Depends(get_auth_repository),
) -> dict[str, str]:
    """Revoke current refresh session and clear auth cookies."""
    stage_started = time.perf_counter()
    # Accept refresh token from cookie (web browsers) or request body (mobile apps).
    refresh_token = (
        request.cookies.get("refresh_token")
        or (payload.refresh_token if payload else None)
    )
    if refresh_token:
        try:
            claims = verify_refresh_token(
                refresh_token,
                auth_settings.refresh_token_secret,
                auth_settings.audience,
            )
            wallet = claims.get("sub")
            if wallet:
                token_hash = hash_refresh_token(refresh_token)
                record = await auth_repo.get_refresh_token(token_hash)
                if record and record.get("wallet") == wallet:
                    if payload and str(payload.device_id) != str(record.get("device_id")):
                        raise AuthError("logout_device_mismatch", "Device mismatch", status.HTTP_401_UNAUTHORIZED)
                    await auth_repo.revoke_refresh_token(token_hash, datetime.now(timezone.utc), reason="logged_out")
        except jwt.PyJWTError:
            pass

    _clear_auth_cookies(response)
    _clear_invite_cookie(response)
    record_auth_funnel_event("logout", "success")
    observe_auth_funnel_stage("logout", time.perf_counter() - stage_started)
    return {"status": "logged_out"}


@router.get("/onboarding/state", response_model=OnboardingStateResponse)
@rate_limit(category="auth")
async def onboarding_state(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
) -> OnboardingStateResponse:
    """Server-owned onboarding/session state for deterministic entry flow."""
    invite_validated = bool(read_invite_cookie(request.cookies.get("invite_code", "")))
    access_token = request.cookies.get("access_token")

    if not access_token:
        return OnboardingStateResponse(
            authenticated=False,
            invite_required=auth_settings.require_invite_code,
            invite_validated=invite_validated,
            needs_profile_setup=False,
            auth_method_hint=None,
        )

    try:
        claims = verify_access_token(
            access_token,
            auth_settings.access_token_secret,
            auth_settings.audience,
        )
    except jwt.PyJWTError:
        return OnboardingStateResponse(
            authenticated=False,
            invite_required=auth_settings.require_invite_code,
            invite_validated=invite_validated,
            needs_profile_setup=False,
            auth_method_hint=None,
        )

    wallet = claims.get("sub")
    if not wallet:
        return OnboardingStateResponse(
            authenticated=False,
            invite_required=auth_settings.require_invite_code,
            invite_validated=invite_validated,
            needs_profile_setup=False,
            auth_method_hint=None,
        )

    try:
        profile = await user_repo.get_profile_setup_state(wallet)
    except Exception as exc:
        _logger.warning("[Auth] onboarding_state profile lookup failed error=%s", scrub_log_text(exc))
        profile = None

    return OnboardingStateResponse(
        authenticated=True,
        invite_required=auth_settings.require_invite_code,
        invite_validated=invite_validated,
        needs_profile_setup=_needs_profile_setup(profile),
        auth_method_hint=claims.get("auth_method") or "wallet",
    )


@router.get("/bootstrap", response_model=AuthBootstrapResponse)
@rate_limit(category="auth")
async def auth_bootstrap(
    request: Request,
    admission_repo: AdmissionRepository = Depends(get_admission_repository),
    authorization: Optional[str] = Header(default=None),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> AuthBootstrapResponse:
    """Return deterministic startup bootstrap state in one request."""
    invite_validated = bool(read_invite_cookie(request.cookies.get("invite_code", "")))

    if current_user is None:
        return AuthBootstrapResponse(
            authenticated=False,
            invite_required=auth_settings.require_invite_code,
            cohort_admission_required=auth_settings.cohort_admission_required,
            invite_validated=invite_validated,
            needs_profile_setup=False,
            auth_method_hint=None,
            user=None,
            points_config=None,
        )

    auth_method_hint = "wallet"
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("access_token")

    if token:
        try:
            claims = verify_access_token(
                token,
                auth_settings.access_token_secret,
                auth_settings.audience,
            )
            auth_method_hint = claims.get("auth_method") or "wallet"
        except jwt.PyJWTError:
            auth_method_hint = "wallet"

    profile = None
    try:
        profile = await load_private_user_profile(
            current_user=current_user,
            user_repo=user_repo,
            ride_repo=ride_repo,
        )
    except Exception as exc:
        _logger.warning(
            "[Auth] bootstrap profile fetch failed for %s: %s",
            current_user.user_id,
            scrub_log_text(exc),
        )

    setup_state = None
    try:
        setup_state = await user_repo.get_profile_setup_state(current_user.wallet)
    except Exception as exc:
        _logger.warning(
            "[Auth] bootstrap setup-state fetch failed for %s: %s",
            current_user.user_id,
            scrub_log_text(exc),
        )

    cohort_admitted = await admission_repo.is_admitted(current_user.user_id)
    return AuthBootstrapResponse(
        authenticated=True,
        cohort_admitted=cohort_admitted,
        invite_required=auth_settings.require_invite_code,
            cohort_admission_required=auth_settings.cohort_admission_required,
        invite_validated=invite_validated,
        needs_profile_setup=_needs_profile_setup(setup_state),
        auth_method_hint=auth_method_hint,
        user=profile,
    )


@router.post("/invite/clear")
@rate_limit(category="auth")
async def clear_invite_state(response: Response) -> dict[str, str]:
    _clear_invite_cookie(response)
    record_auth_funnel_event("invite_clear", "success")
    return {"status": "cleared"}


@router.post("/invite/validate", response_model=InviteValidateResponse)
@rate_limit(category="auth")
async def validate_invite_code(
    response: Response,
    payload: InviteValidateRequest = Body(...),
) -> InviteValidateResponse:
    """
    Check an invite code server-side without consuming it.

    This endpoint is safe to call before a wallet exists. Invite usage is
    recorded only by `/auth/verify` or `/auth/privy/verify`, once the final
    signup wallet is known.

    In non-production environments, falls back to accepting known alpha codes
    if Supabase is unavailable (e.g. local dev without DB credentials).
    """
    stage_started = time.perf_counter()
    code = _normalize_invite_code(payload.code) if payload.code else ""

    # Dev/local fallback: accept known alpha codes without hitting Supabase
    try:
        supabase = get_supabase_client()
    except Exception as exc:
        _logger.warning('[Auth] Invite validation supabase unavailable error=%s', scrub_log_text(exc))
        supabase = None

    if supabase is None:
        if _is_dev_invite_code(code):
            _set_invite_cookie(response, code)
            record_auth_funnel_event("invite_validate", "valid")
            observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
            return InviteValidateResponse(valid=True, message="Invite code valid (dev mode)", code_id=None)
        _clear_invite_cookie(response)
        record_auth_funnel_event("invite_validate", "service_unavailable")
        observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
        return InviteValidateResponse(
            valid=False,
            message="Validation service unavailable",
            code_id=None,
        )

    try:
        result = supabase.rpc(
            "check_invite_code",
            {
                "p_code": hash_invite_code(code),
            }
        ).execute()

        if result.data and len(result.data) > 0:
            row = result.data[0]
            is_valid = row.get("valid", False)
            if is_valid:
                _set_invite_cookie(response, code)
                record_auth_funnel_event("invite_validate", "valid")
            else:
                _clear_invite_cookie(response)
                record_auth_funnel_event("invite_validate", "invalid")
            observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
            return InviteValidateResponse(
                valid=is_valid,
                message=row.get("message", "Unknown error"),
                code_id=row.get("code_id"),
            )
        else:
            _clear_invite_cookie(response)
            record_auth_funnel_event("invite_validate", "error")
            observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
            return InviteValidateResponse(
                valid=False,
                message="Failed to validate invite code",
                code_id=None,
            )

    except Exception as e:
        _logger.error("Invite code validation failed")
        # In dev, fall back to known codes if DB is unreachable
        if _is_dev_invite_code(code):
            _set_invite_cookie(response, code)
            record_auth_funnel_event("invite_validate", "valid")
            observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
            return InviteValidateResponse(valid=True, message="Invite code valid (dev fallback)", code_id=None)
        _clear_invite_cookie(response)
        record_auth_funnel_event("invite_validate", "service_unavailable")
        observe_auth_funnel_stage("invite_validate", time.perf_counter() - stage_started)
        return InviteValidateResponse(
            valid=False,
            message="Validation service unavailable",
            code_id=None,
        )


def _wallet_from_authorization(header: Optional[str]) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise AuthError("missing_authorization", "Authorization header missing", status.HTTP_401_UNAUTHORIZED)
    token = header.split(" ", 1)[1].strip()
    try:
        claims = verify_access_token(token, auth_settings.access_token_secret, auth_settings.audience)
    except jwt.PyJWTError as exc:
        raise AuthError("access_invalid", "Invalid access token", status.HTTP_401_UNAUTHORIZED) from exc
    wallet = claims.get("sub")
    if not wallet:
        raise AuthError("access_invalid", "Invalid access token", status.HTTP_401_UNAUTHORIZED)
    return wallet


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None
