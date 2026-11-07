"""Server-only invite digests; plaintext must never reach persistence or logs."""
import hashlib
import hmac
import re
from .config import load_auth_settings


def hash_invite_code(code: str) -> str:
    settings = load_auth_settings()
    secret = settings.invite_code_secret or settings.refresh_token_secret
    return hmac.new(secret.encode(), code.strip().lower().encode(), hashlib.sha256).hexdigest()


def invite_cookie(code: str) -> str:
    digest = hash_invite_code(code)
    signature = _cookie_signature(digest)
    return f"{digest}.{signature}"


def _cookie_signature(digest: str) -> str:
    settings = load_auth_settings()
    key = settings.invite_code_secret or settings.refresh_token_secret
    return hmac.new(key.encode(), f"invite-cookie:{digest}".encode(), hashlib.sha256).hexdigest()


def read_invite_cookie(value: str) -> str:
    digest, separator, signature = value.partition(".")
    if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", value) or not hmac.compare_digest(signature, _cookie_signature(digest)):
        return ""
    return digest
