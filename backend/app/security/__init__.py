"""Security utilities for BoulderRollers backend."""

from .token import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from .siws import build_siws_message, verify_siws_signature
from .privy import (
    verify_privy_token,
    extract_wallet_from_claims,
    fetch_privy_user,
    extract_wallet_from_user,
    get_user_identity,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "hash_refresh_token",
    "verify_access_token",
    "verify_refresh_token",
    "build_siws_message",
    "verify_siws_signature",
    "verify_privy_token",
    "extract_wallet_from_claims",
    "fetch_privy_user",
    "extract_wallet_from_user",
    "get_user_identity",
]
