"""App→API version contract enforcement (L3.08, bead boulderroller-v2-f4acp.2.8).

Native clients declare the wire contract they speak (``X-BR-Contract``) and
their platform/build (``X-BR-Client``, e.g. ``ios/214``). Requests without
the headers — portal, curl, older clients — pass untouched; the contract is
additive. A client that *does* declare an unsupported contract, or a build
below the configured floor, receives the typed upgrade refusal that the iOS
error taxonomy maps to its stale-client class (never retryable).

The rider-facing sentence for that state is a Tim copy slot; the wire
carries only the machine code.
"""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

CONTRACT_HEADER = "X-BR-Contract"
CLIENT_HEADER = "X-BR-Client"

SUPPORTED_CLIENT_CONTRACTS = {"client.v1"}

# Paths that must stay reachable for any build (probes, upgrade guidance).
EXEMPT_PATHS = ("/health", "/status", "/metrics")

UPGRADE_REQUIRED_BODY = {"detail": {"code": "upgrade_required"}}


def minimum_supported_build(platform: str) -> int:
    """Operator-set build floor per platform; 0 (default) allows every build.

    Raising ``BR_MIN_SUPPORTED_IOS_BUILD`` is the forced-upgrade lever
    (L3.05); it must only be changed under that bead's operator authority.
    """
    key = f"BR_MIN_SUPPORTED_{platform.upper()}_BUILD"
    try:
        return int(os.getenv(key, "0"))
    except ValueError:
        return 0


def parse_client(value: str) -> tuple[str, int] | None:
    """``ios/214`` -> ("ios", 214); malformed values parse as None."""
    parts = value.split("/", 1)
    if len(parts) != 2 or not parts[0]:
        return None
    try:
        return parts[0].lower(), int(parts[1])
    except ValueError:
        return None


def contract_refusal(request: Request) -> JSONResponse | None:
    """The pure decision, exposed for tests: refuse or pass."""
    path = request.url.path or ""
    if path.startswith(EXEMPT_PATHS):
        return None

    contract = request.headers.get(CONTRACT_HEADER)
    if contract is not None and contract not in SUPPORTED_CLIENT_CONTRACTS:
        return JSONResponse(status_code=426, content=UPGRADE_REQUIRED_BODY)

    client = request.headers.get(CLIENT_HEADER)
    if client is not None:
        parsed = parse_client(client)
        if parsed is not None:
            platform, build = parsed
            floor = minimum_supported_build(platform)
            if floor > 0 and build < floor:
                return JSONResponse(status_code=426, content=UPGRADE_REQUIRED_BODY)
    return None


class ClientContractMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        refusal = contract_refusal(request)
        if refusal is not None:
            return refusal
        return await call_next(request)
