from __future__ import annotations

import ipaddress
from typing import Optional

from fastapi import Request


def _normalize_ip(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    candidate = value.strip().strip('"').strip("'")
    if not candidate:
        return None

    if candidate.lower() == "unknown":
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]

    if ":" in candidate and candidate.count(":") == 1 and "." in candidate:
        host, port = candidate.rsplit(":", 1)
        if port.isdigit():
            candidate = host

    return candidate or None


def _is_proxy_hop(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return value in {"localhost", "caddy", "api", "127.0.0.1"}

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
    )


def _extract_forwarded_ip(request: Request) -> Optional[str]:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    candidates = [
        candidate
        for raw_ip in forwarded_for.split(",")
        if (candidate := _normalize_ip(raw_ip))
    ]
    for candidate in reversed(candidates):
        if not _is_proxy_hop(candidate):
            return candidate
    if candidates:
        return candidates[-1]

    return _normalize_ip(request.headers.get("x-real-ip"))


def get_client_ip(request: Request) -> str:
    direct_ip = _normalize_ip(request.client.host if request.client else None)
    forwarded_ip = _extract_forwarded_ip(request)

    if forwarded_ip and (not direct_ip or _is_proxy_hop(direct_ip)):
        return forwarded_ip

    if direct_ip:
        return direct_ip

    if forwarded_ip:
        return forwarded_ip

    return "unknown"
