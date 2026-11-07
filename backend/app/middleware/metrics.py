"""Prometheus metrics middleware for tracking HTTP request metrics."""

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

# Import safe metric helpers to prevent duplicate registration errors
from ..metrics import safe_counter, safe_histogram

# Metrics (using safe helpers to prevent duplicate registration in pytest)
REQUEST_COUNT = safe_counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = safe_histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

REQUESTS_IN_PROGRESS = safe_counter(
    "http_requests_in_progress",
    "HTTP requests currently in progress",
    ["method", "endpoint"]
)


def normalize_path(path: str) -> str:
    """Normalize path to prevent high cardinality metrics.

    Replaces dynamic path segments (UUIDs, IDs) with placeholders.
    """
    parts = path.split("/")
    normalized = []
    for part in parts:
        # Skip empty parts
        if not part:
            continue
        # Replace UUIDs (36 char with hyphens)
        if len(part) == 36 and part.count("-") == 4:
            normalized.append("{id}")
        # Replace numeric IDs
        elif part.isdigit():
            normalized.append("{id}")
        # Replace wallet addresses (base58, typically 32-44 chars)
        elif len(part) >= 32 and len(part) <= 44 and part.isalnum():
            normalized.append("{wallet}")
        else:
            normalized.append(part)
    return "/" + "/".join(normalized)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to track Prometheus metrics for all HTTP requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics endpoint to avoid self-referential tracking
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        path = normalize_path(request.url.path)

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            status = "500"
            raise
        finally:
            duration = time.perf_counter() - start_time
            REQUEST_COUNT.labels(method=method, endpoint=path, status=status).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=path).observe(duration)

        return response


def get_metrics() -> StarletteResponse:
    """Generate Prometheus metrics response."""
    return StarletteResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
