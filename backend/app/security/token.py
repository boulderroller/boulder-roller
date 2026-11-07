from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import hashlib
import uuid

import jwt


def _create_token(
    subject: str,
    secret: str,
    audience: str,
    expires_delta: timedelta,
    scope: str,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": str(uuid.uuid4()),
        "scope": scope,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm="HS256")


def _verify_token(token: str, secret: str, audience: str, scope: str) -> Dict[str, Any]:
    payload = jwt.decode(token, secret, algorithms=["HS256"], audience=audience)
    if payload.get("scope") != scope:
        raise jwt.InvalidTokenError("Invalid token scope")
    return payload


def create_access_token(
    subject: str,
    secret: str,
    audience: str,
    minutes: int,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    return _create_token(subject, secret, audience, timedelta(minutes=minutes), "access", extra_claims)


def verify_access_token(token: str, secret: str, audience: str) -> Dict[str, Any]:
    return _verify_token(token, secret, audience, "access")


def create_refresh_token(
    subject: str,
    secret: str,
    audience: str,
    days: int,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    return _create_token(subject, secret, audience, timedelta(days=days), "refresh", extra_claims)


def verify_refresh_token(token: str, secret: str, audience: str) -> Dict[str, Any]:
    return _verify_token(token, secret, audience, "refresh")


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
