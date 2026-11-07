import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - safety in case dependency missing
    load_dotenv = None


def _patch_httpx_proxy_keyword() -> None:
    """Shim gotrue's proxy handling for httpx>=0.24 which expects 'proxies'."""
    try:
        import httpx
        from gotrue._sync import gotrue_base_api
    except Exception:
        return

    original_sync_client = getattr(gotrue_base_api, "SyncClient", None)
    if original_sync_client is None:
        return

    # Avoid double patching
    if getattr(original_sync_client, "__name__", "") == "_ProxyCompatibleClient":
        return

    class _ProxyCompatibleClient(httpx.Client):  # type: ignore[misc]
        def __init__(self, *args, proxy=None, **kwargs):
            if proxy is not None and "proxies" not in kwargs:
                kwargs["proxies"] = proxy
            super().__init__(*args, **kwargs)

    gotrue_base_api.SyncClient = _ProxyCompatibleClient  # type: ignore[attr-defined]


_patch_httpx_proxy_keyword()


@dataclass
class SupabaseSettings:
    url: Optional[str] = None
    service_role_key: Optional[str] = None

    @property
    def service_key(self) -> Optional[str]:
        return self.service_role_key


@dataclass
class AuthSettings:
    access_token_secret: str
    refresh_token_secret: str
    audience: str
    access_token_minutes: int
    refresh_token_days: int
    nonce_ttl_seconds: int
    signature_bypass: bool
    domain: str = "app.boulderroller.xyz"
    uri: str = "https://app.boulderroller.xyz"
    chain: str = "solana"
    intent: str = "login"
    # Cookie settings for HttpOnly token storage
    cookie_domain: Optional[str] = None  # None = current domain only
    cookie_secure: bool = True  # Require HTTPS (disable for localhost dev)
    cookie_samesite: str = "lax"  # "lax" allows top-level navigations, "strict" is more restrictive
    # Invite code enforcement - require valid invite code for new signups
    require_invite_code: bool = True
    invite_code_secret: str = ""
    cohort_admission_required: bool = False


@dataclass
class PrivySettings:
    """Privy authentication settings."""
    app_id: Optional[str] = None
    verification_key: Optional[str] = None
    enabled: bool = False


@dataclass
class StravaSettings:
    """Strava OAuth and API settings."""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    webhook_callback_url: Optional[str] = None
    enabled: bool = False
    sync_enabled: bool = False


@dataclass(frozen=True)
class GeocoderSettings:
    """Launch-scoped Nominatim-compatible place-search settings."""

    enabled: bool = False
    search_url: str = ""


def _load_env_file() -> None:
    """Load environment variables from the backend .env file if available."""
    if load_dotenv is None:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path, override=False)


@lru_cache(maxsize=1)
def load_supabase_settings() -> Optional[SupabaseSettings]:
    _load_env_file()
    settings = SupabaseSettings()
    settings.url = settings.url or os.getenv("SUPABASE_URL")
    service_key = settings.service_role_key or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    settings.service_role_key = service_key
    if not settings.url or not settings.service_role_key:
        return None
    return settings


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_environment(default: str = "production") -> str:
    _load_env_file()
    raw_value = os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or default
    normalized = raw_value.strip().lower()
    aliases = {
        "prod": "production",
        "production": "production",
        "stage": "staging",
        "staging": "staging",
        "test": "test",
        "testing": "test",
        "dev": "development",
        "development": "development",
        "local": "development",
    }
    return aliases.get(normalized, normalized or default)


def is_production_environment() -> bool:
    return get_environment() == "production"


def is_public_environment(environment: Optional[str] = None) -> bool:
    env = environment or get_environment()
    return env in {"staging", "production"}


def auth_signature_bypass_requested() -> bool:
    _load_env_file()
    return _parse_bool(os.getenv("AUTH_SIGNATURE_BYPASS"), default=False)


def auth_signature_bypass_effective(environment: Optional[str] = None) -> bool:
    env = environment or get_environment()
    if is_public_environment(env):
        return False
    return auth_signature_bypass_requested() or env == "development"


def auth_cookie_secure_effective(environment: Optional[str] = None) -> bool:
    _load_env_file()
    env = environment or get_environment()
    return is_public_environment(env) or _parse_bool(os.getenv("AUTH_COOKIE_SECURE"), default=False)


def dev_routes_enabled(environment: Optional[str] = None) -> bool:
    _load_env_file()
    env = environment or get_environment()
    return not is_public_environment(env) and _parse_bool(os.getenv("ENABLE_DEV_ROUTES"), default=False)


def get_app_version() -> Optional[str]:
    _load_env_file()
    for key in ("APP_VERSION", "GIT_SHA", "COMMIT_SHA", "SOURCE_COMMIT"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip()
    return None


@lru_cache(maxsize=1)
def load_auth_settings() -> AuthSettings:
    _load_env_file()
    access_secret = os.getenv("ACCESS_TOKEN_SECRET") or os.getenv("JWT_SECRET")
    refresh_secret = os.getenv("REFRESH_TOKEN_SECRET") or os.getenv("JWT_SECRET")
    if not access_secret or not refresh_secret:
        raise RuntimeError("Auth configuration missing ACCESS_TOKEN_SECRET or REFRESH_TOKEN_SECRET")

    invite_secret = os.getenv("INVITE_CODE_SECRET")
    if not invite_secret:
        import logging
        logging.getLogger(__name__).warning(
            "INVITE_CODE_SECRET is unset; using REFRESH_TOKEN_SECRET for invite HMAC"
        )
        invite_secret = refresh_secret

    audience = os.getenv("AUTH_AUDIENCE", "boulderrollers")
    access_minutes = _parse_int(os.getenv("AUTH_ACCESS_TOKEN_MINUTES"), 15)
    refresh_days = _parse_int(os.getenv("AUTH_REFRESH_TOKEN_DAYS"), 14)
    nonce_ttl = _parse_int(os.getenv("AUTH_NONCE_TTL_SECONDS"), 300)
    siws_domain = os.getenv("AUTH_SIWS_DOMAIN", "app.boulderroller.xyz")
    siws_uri = os.getenv("AUTH_SIWS_URI", "https://app.boulderroller.xyz")
    siws_chain = os.getenv("AUTH_SIWS_CHAIN", "solana")
    siws_intent = os.getenv("AUTH_SIWS_INTENT", "login")
    environment = get_environment()

    # SECURITY: Never allow signature bypass on public environments, even if
    # explicitly set. Local development keeps the old convenience behavior.
    signature_bypass = auth_signature_bypass_effective(environment)

    # Cookie settings - secure defaults for publicly hosted environments
    cookie_domain = os.getenv("AUTH_COOKIE_DOMAIN")  # None = current domain
    cookie_secure = auth_cookie_secure_effective(environment)
    cookie_samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax")

    # Invite code enforcement - default ON for production, configurable for dev
    require_invite_code = _parse_bool(os.getenv("REQUIRE_INVITE_CODE") or None, default=(environment == "production"))

    return AuthSettings(
        access_token_secret=access_secret,
        refresh_token_secret=refresh_secret,
        audience=audience,
        access_token_minutes=access_minutes,
        refresh_token_days=refresh_days,
        nonce_ttl_seconds=nonce_ttl,
        signature_bypass=signature_bypass,
        domain=siws_domain,
        uri=siws_uri,
        chain=siws_chain,
        intent=siws_intent,
        cookie_domain=cookie_domain,
        cookie_secure=cookie_secure,
        cookie_samesite=cookie_samesite,
        require_invite_code=require_invite_code,
        invite_code_secret=invite_secret,
        cohort_admission_required=_parse_bool(os.getenv("COHORT_ADMISSION_REQUIRED"), default=False),
    )


@lru_cache(maxsize=1)
def load_privy_settings() -> PrivySettings:
    """Load Privy authentication settings from environment."""
    _load_env_file()
    app_id = os.getenv("PRIVY_APP_ID")
    verification_key = os.getenv("PRIVY_VERIFICATION_KEY")
    enabled = bool(app_id and verification_key)
    return PrivySettings(
        app_id=app_id,
        verification_key=verification_key,
        enabled=enabled,
    )


@lru_cache(maxsize=1)
def load_strava_settings() -> StravaSettings:
    """Load Strava OAuth settings from environment."""
    _load_env_file()
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    redirect_uri = os.getenv("STRAVA_REDIRECT_URI")
    webhook_verify_token = os.getenv("STRAVA_WEBHOOK_VERIFY_TOKEN")
    webhook_callback_url = os.getenv("STRAVA_WEBHOOK_CALLBACK_URL")
    enabled = bool(client_id and client_secret)
    sync_enabled = enabled and _parse_bool(
        os.getenv("STRAVA_SYNC_ENABLED"),
        default=False,
    )
    return StravaSettings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        webhook_verify_token=webhook_verify_token,
        webhook_callback_url=webhook_callback_url,
        enabled=enabled,
        sync_enabled=sync_enabled,
    )


@lru_cache(maxsize=1)
def load_geocoder_settings() -> GeocoderSettings:
    """Load the fail-closed geocoder provider configuration."""
    _load_env_file()
    return GeocoderSettings(
        enabled=_parse_bool(os.getenv("GEOCODER_ENABLED"), default=False),
        search_url=(os.getenv("GEOCODER_SEARCH_URL") or "").strip(),
    )
