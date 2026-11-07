"""
Privy JWT verification for social login authentication.

Privy issues JWTs when users authenticate via social login (Google, Apple, Email).
We verify these tokens using the verification key from our Privy dashboard.

See: https://docs.privy.io/guide/server/authorization/verification
"""
from __future__ import annotations

import base64
import time
from typing import Optional

import httpx
import jwt
from jwt import PyJWKClient

from ..config import load_privy_settings

# JWKS cache with TTL (keys rotate, so we refresh periodically)
_jwks_client: Optional[PyJWKClient] = None
_jwks_client_created_at: float = 0
_jwks_app_id: Optional[str] = None
JWKS_CACHE_TTL_SECONDS = 300  # 5 minutes


def get_jwks_url(app_id: str) -> str:
    """Build the JWKS URL for a Privy app."""
    return f"https://auth.privy.io/api/v1/apps/{app_id}/jwks.json"


def get_jwks_client() -> PyJWKClient:
    """
    Get or create the JWKS client for Privy with TTL-based refresh.

    Keys are cached for 5 minutes, then refreshed to handle key rotation.
    Also handles app_id changes (e.g., switching environments).
    """
    global _jwks_client, _jwks_client_created_at, _jwks_app_id

    settings = load_privy_settings()
    if not settings.app_id:
        raise ValueError("PRIVY_APP_ID not configured")

    current_time = time.time()
    cache_expired = (current_time - _jwks_client_created_at) > JWKS_CACHE_TTL_SECONDS
    app_id_changed = _jwks_app_id != settings.app_id

    if _jwks_client is None or cache_expired or app_id_changed:
        jwks_url = get_jwks_url(settings.app_id)
        _jwks_client = PyJWKClient(jwks_url)
        _jwks_client_created_at = current_time
        _jwks_app_id = settings.app_id

    return _jwks_client


def verify_privy_token(token: str) -> dict:
    """
    Verify a Privy access token and return its claims.

    The token is verified using Privy's public keys (JWKS).
    We validate:
    - Signature using the public key
    - Expiration time
    - Issuer (privy.io)
    - Audience (our app ID)

    Args:
        token: The Privy access token to verify

    Returns:
        dict: The verified token claims

    Raises:
        ValueError: If token verification fails
    """
    settings = load_privy_settings()
    if not settings.enabled:
        raise ValueError("Privy authentication is not configured")

    try:
        # Get the signing key from JWKS
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        # Verify and decode the token
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            issuer="privy.io",
            audience=settings.app_id,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            }
        )

        return claims

    except jwt.ExpiredSignatureError:
        raise ValueError("Privy token has expired")
    except jwt.InvalidIssuerError:
        raise ValueError("Invalid Privy token issuer")
    except jwt.InvalidAudienceError:
        raise ValueError("Invalid Privy token audience")
    except jwt.PyJWTError as e:
        raise ValueError(f"Privy token verification failed: {e}")


def fetch_privy_user(user_id: str) -> dict:
    """
    Fetch a user's full profile from the Privy server API using the app secret.

    Privy access tokens are minimal session proofs (`sid`, `iss`, `iat`, `aud`,
    `sub`, `exp`) — they do NOT contain `linked_accounts`. To authorize actions
    that depend on the user's wallets or linked accounts, the backend must
    look them up via the Privy server API.

    Raises:
        ValueError: if the Privy API returns an error or the user is not found.
    """
    settings = load_privy_settings()
    if not settings.enabled:
        raise ValueError("Privy authentication is not configured")

    # Privy uses Basic auth: base64(app_id:app_secret)
    # PRIVY_VERIFICATION_KEY env var actually holds the app secret.
    credentials = f"{settings.app_id}:{settings.verification_key}".encode()
    basic = base64.b64encode(credentials).decode()

    url = f"https://auth.privy.io/api/v1/users/{user_id}"
    headers = {
        "privy-app-id": settings.app_id,
        "Authorization": f"Basic {basic}",
        "Accept": "application/json",
    }

    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        raise ValueError(f"Privy API request failed: {exc}") from exc

    if response.status_code == 404:
        raise ValueError(f"Privy user {user_id!r} not found")
    if response.status_code >= 400:
        raise ValueError(
            f"Privy API returned {response.status_code}: {response.text[:200]}"
        )
    return response.json()


def extract_wallet_from_user(user: dict) -> Optional[str]:
    """
    Extract the Solana wallet address from a Privy user object returned by
    the server API. Prefers an embedded (Privy-managed) Solana wallet, falls
    back to any linked Solana wallet.
    """
    linked_accounts = user.get("linked_accounts", [])

    # 1) Embedded Solana wallet created by Privy for social-login users
    for account in linked_accounts:
        if (
            account.get("type") == "wallet"
            and account.get("chain_type") == "solana"
            and account.get("wallet_client_type") == "privy"
        ):
            address = account.get("address")
            if address:
                return address

    # 2) Any linked Solana wallet
    for account in linked_accounts:
        if account.get("type") == "wallet" and account.get("chain_type") == "solana":
            address = account.get("address")
            if address:
                return address

    return None


def extract_wallet_from_claims(claims: dict) -> Optional[str]:
    """
    Extract the Solana wallet address from Privy token claims.

    Privy stores linked accounts in the 'linked_accounts' claim.
    We look for a Solana wallet in this list.

    Args:
        claims: The verified Privy token claims

    Returns:
        The Solana wallet address or None if not found
    """
    linked_accounts = claims.get("linked_accounts", [])

    for account in linked_accounts:
        # Look for Solana wallet
        if account.get("type") == "wallet" and account.get("chain_type") == "solana":
            return account.get("address")

    # Also check for embedded wallet
    for account in linked_accounts:
        if account.get("type") == "wallet" and account.get("wallet_client") == "privy":
            # Privy embedded wallets can be EVM or Solana
            if account.get("chain_type") == "solana":
                return account.get("address")

    return None


def get_user_identity(claims: dict) -> dict:
    """
    Extract user identity information from Privy claims.

    Args:
        claims: The verified Privy token claims

    Returns:
        dict with user identity fields (email, name, etc.)
    """
    linked_accounts = claims.get("linked_accounts", [])
    identity = {
        "privy_id": claims.get("sub"),
        "email": None,
        "name": None,
        "google_id": None,
        "apple_id": None,
    }

    for account in linked_accounts:
        account_type = account.get("type")

        if account_type == "email":
            identity["email"] = account.get("address")

        elif account_type == "google_oauth":
            identity["google_id"] = account.get("subject")
            identity["email"] = identity["email"] or account.get("email")
            identity["name"] = identity["name"] or account.get("name")

        elif account_type == "apple_oauth":
            identity["apple_id"] = account.get("subject")
            identity["email"] = identity["email"] or account.get("email")

    return identity
