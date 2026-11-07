from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import base58
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


MESSAGE_HEADER = "BoulderRollers wants you to sign in"
DEFAULT_MESSAGE_DOMAIN = "app.boulderroller.xyz"
DEFAULT_MESSAGE_URI = "https://app.boulderroller.xyz"
DEFAULT_MESSAGE_CHAIN = "solana"
DEFAULT_MESSAGE_INTENT = "login"


def build_siws_message(
    wallet: str,
    nonce: str,
    issued_at: datetime,
    expires_at: datetime,
    domain: str = DEFAULT_MESSAGE_DOMAIN,
    uri: str = DEFAULT_MESSAGE_URI,
    chain: str = DEFAULT_MESSAGE_CHAIN,
    intent: str = DEFAULT_MESSAGE_INTENT,
) -> str:
    issued_iso = _ensure_timezone(issued_at).isoformat()
    expires_iso = _ensure_timezone(expires_at).isoformat()
    resolved_domain = (domain or DEFAULT_MESSAGE_DOMAIN).strip() or DEFAULT_MESSAGE_DOMAIN
    resolved_uri = (uri or DEFAULT_MESSAGE_URI).strip() or DEFAULT_MESSAGE_URI
    resolved_chain = (chain or DEFAULT_MESSAGE_CHAIN).strip() or DEFAULT_MESSAGE_CHAIN
    resolved_intent = (intent or DEFAULT_MESSAGE_INTENT).strip() or DEFAULT_MESSAGE_INTENT
    return "\n".join(
        [
            MESSAGE_HEADER,
            f"domain: {resolved_domain}",
            f"wallet: {wallet}",
            f"nonce: {nonce}",
            f"issued_at: {issued_iso}",
            f"expires_at: {expires_iso}",
            f"uri: {resolved_uri}",
            f"chain: {resolved_chain}",
            f"intent: {resolved_intent}",
        ]
    )


def verify_siws_signature(wallet: str, signature: str, message: str) -> None:
    try:
        public_key_bytes = base58.b58decode(wallet)
    except ValueError as exc:  # pragma: no cover - invalid base58
        raise ValueError("Invalid wallet public key encoding") from exc

    try:
        signature_bytes = base58.b58decode(signature)
    except ValueError as exc:  # pragma: no cover - invalid base58
        raise ValueError("Invalid signature encoding") from exc

    verify_key = VerifyKey(public_key_bytes)
    try:
        verify_key.verify(message.encode("utf-8"), signature_bytes)
    except BadSignatureError as exc:
        raise ValueError("Invalid SIWS signature") from exc


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
