import logging
import inspect
import re
import time
from collections import defaultdict
from functools import wraps
from typing import Optional, Tuple, get_type_hints

from fastapi import HTTPException, Request

from ..config import is_public_environment
from ..rate_limits_config import RATE_LIMITS, RATE_LIMIT_MULTIPLIER, RateLimitConfig
from ..utils import get_client_ip

logger = logging.getLogger(__name__)

_NATS_KV_KEY_RE = re.compile(r"[^A-Za-z0-9_.=/\-]")


def _sanitize_nats_kv_key(key: str) -> str:
    """Return a JetStream KV-safe key while preserving readable rate scopes."""
    sanitized = _NATS_KV_KEY_RE.sub("_", key).strip(".")
    return sanitized or "ratelimit"


class RateLimiter:
    """Rate limiter backed by NATS KV with in-memory fallback.

    Uses fixed-window counters stored in a NATS JetStream KV bucket.
    Falls back to in-memory sliding window when NATS is unavailable.
    """

    KV_BUCKET = "RATE_LIMITS"

    def __init__(self) -> None:
        self._kv = None
        self._kv_init_attempted = False
        self._fallback_counts: dict[str, list[float]] = defaultdict(list)

    def reset_fallback(self) -> None:
        """Clear in-memory fallback counts. Useful for tests."""
        self._fallback_counts.clear()

    def _check_fallback(self, key: str, limit: int, window_seconds: int) -> bool:
        """In-memory sliding window rate check. Returns True if allowed."""
        now = time.time()
        window_start = now - window_seconds
        timestamps = self._fallback_counts[key]
        self._fallback_counts[key] = [t for t in timestamps if t > window_start]
        if len(self._fallback_counts[key]) >= limit:
            return False
        self._fallback_counts[key].append(now)
        return True

    async def _increment_kv_counter(self, kv_key: str) -> int:
        """Increment a JetStream KV counter with optimistic concurrency."""
        if self._kv is None:
            raise RuntimeError("NATS KV is not initialized")

        for _attempt in range(5):
            try:
                entry = await self._kv.get(kv_key)
                count = int(entry.value.decode()) if entry and entry.value else 0
                revision = getattr(entry, "revision", None)
            except Exception:
                count = 0
                revision = None

            next_count = count + 1
            encoded = str(next_count).encode()
            try:
                if revision is None and hasattr(self._kv, "create"):
                    await self._kv.create(kv_key, encoded)
                elif revision is not None and hasattr(self._kv, "update"):
                    await self._kv.update(kv_key, encoded, last=revision)
                else:
                    await self._kv.put(kv_key, encoded)
                return next_count
            except Exception as exc:
                message = str(exc).lower()
                if any(token in message for token in ("wrong last", "wronglast", "exists", "revision")):
                    continue
                raise

        raise RuntimeError("NATS KV counter update conflicted repeatedly")

    async def _ensure_kv(self) -> None:
        """Lazily initialize the NATS KV bucket."""
        if self._kv is not None or self._kv_init_attempted:
            return

        self._kv_init_attempted = True
        try:
            from ..services.nats_client import get_nats_client
            client = get_nats_client()
            await client.connect()

            js = client._js
            try:
                self._kv = await js.key_value(self.KV_BUCKET)
            except Exception:
                # Bucket doesn't exist yet, create it
                self._kv = await js.create_key_value(
                    bucket=self.KV_BUCKET,
                    ttl=3600,  # Default TTL: 1 hour (longest window we track)
                )
            logger.info("[RateLimiter] NATS KV bucket '%s' ready", self.KV_BUCKET)
        except Exception as exc:
            logger.warning("[RateLimiter] NATS KV unavailable, using in-memory fallback: %s", exc)
            self._kv = None

    async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
        """
        Check if request is within rate limit using fixed-window counters.
        Returns: (allowed, remaining, reset_time)
        """
        await self._ensure_kv()

        now = int(time.time())
        window_id = now // window_seconds
        kv_key = _sanitize_nats_kv_key(f"{key}.w{window_id}")
        reset_time = (window_id + 1) * window_seconds

        if self._kv is None:
            if is_public_environment():
                logger.error("[RateLimiter] NATS KV unavailable in public environment; failing closed")
                return False, 0, reset_time
            # Fallback to in-memory
            allowed = self._check_fallback(key, limit, window_seconds)
            remaining = max(0, limit - len(self._fallback_counts.get(key, [])))
            return allowed, remaining, reset_time

        try:
            count = await self._increment_kv_counter(kv_key)
        except Exception as exc:
            logger.warning("[RateLimiter] NATS KV counter failed, using fallback: %s", exc)
            if is_public_environment():
                logger.error("[RateLimiter] NATS KV counter failed in public environment; failing closed")
                return False, 0, reset_time
            allowed = self._check_fallback(key, limit, window_seconds)
            remaining = max(0, limit - len(self._fallback_counts.get(key, [])))
            return allowed, remaining, reset_time

        allowed = count <= limit
        remaining = max(0, limit - count)
        return allowed, remaining, reset_time

    async def check_burst(self, key: str, burst_limit: int) -> bool:
        """Check burst limit (requests per second)."""
        await self._ensure_kv()

        now = int(time.time())
        burst_key = _sanitize_nats_kv_key(f"{key}.burst.{now}")

        if self._kv is None:
            if is_public_environment():
                logger.error("[RateLimiter] NATS KV unavailable in public environment; failing closed burst check")
                return False
            return self._check_fallback(f"{key}:burst", burst_limit, 1)

        try:
            count = await self._increment_kv_counter(burst_key)
        except Exception as exc:
            logger.warning("[RateLimiter] NATS KV burst counter failed, using fallback: %s", exc)
            if is_public_environment():
                logger.error("[RateLimiter] NATS KV burst counter failed in public environment; failing closed")
                return False
            return self._check_fallback(f"{key}:burst", burst_limit, 1)

        return count <= burst_limit


rate_limiter = RateLimiter()


def _preserve_fastapi_signature(wrapper, func) -> None:
    """Preserve the wrapped endpoint signature with resolved annotations."""
    try:
        signature = inspect.signature(func)
        resolved_hints = get_type_hints(func, globalns=func.__globals__, include_extras=True)
        parameters = [
            parameter.replace(annotation=resolved_hints.get(name, parameter.annotation))
            for name, parameter in signature.parameters.items()
        ]
        wrapper.__signature__ = inspect.Signature(
            parameters=parameters,
            return_annotation=resolved_hints.get("return", signature.return_annotation),
        )
        wrapper.__annotations__ = resolved_hints
    except Exception:
        wrapper.__signature__ = inspect.signature(func)
        wrapper.__annotations__ = getattr(func, "__annotations__", {}).copy()


def _apply_multiplier(config: RateLimitConfig) -> RateLimitConfig:
    factor = RATE_LIMIT_MULTIPLIER if RATE_LIMIT_MULTIPLIER > 0 else 1.0
    return RateLimitConfig(
        requests_per_minute=max(1, int(config.requests_per_minute * factor)),
        requests_per_hour=max(1, int(config.requests_per_hour * factor)),
        burst_limit=max(1, int(config.burst_limit * factor)),
    )


def rate_limit(category: str = "general"):
    """Decorator for rate-limited endpoints."""
    config = _apply_multiplier(RATE_LIMITS.get(category, RATE_LIMITS["general"]))

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                return await func(*args, **kwargs)

            identifier = None
            user_id = getattr(request.state, "user_id", None)
            if user_id:
                identifier = f"user:{user_id}"
            else:
                client_ip = get_client_ip(request)
                identifier = f"ip:{client_ip}"

            base_key = f"ratelimit.{category}.{identifier}"

            try:
                if not await rate_limiter.check_burst(base_key, config.burst_limit):
                    raise HTTPException(
                        status_code=429,
                        detail="Too many requests. Please slow down.",
                        headers={"Retry-After": "1"},
                    )

                allowed_minute, _, reset_minute = await rate_limiter.check_rate_limit(
                    f"{base_key}.minute",
                    config.requests_per_minute,
                    60,
                )
                if not allowed_minute:
                    retry_after = max(1, reset_minute - int(time.time()))
                    raise HTTPException(
                        status_code=429,
                        detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                        headers={
                            "X-RateLimit-Limit": str(config.requests_per_minute),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(reset_minute),
                            "Retry-After": str(retry_after),
                        },
                    )

                allowed_hour, _, reset_hour = await rate_limiter.check_rate_limit(
                    f"{base_key}.hour",
                    config.requests_per_hour,
                    3600,
                )
                if not allowed_hour:
                    retry_after = max(1, reset_hour - int(time.time()))
                    raise HTTPException(
                        status_code=429,
                        detail="Hourly rate limit exceeded. Please try again later.",
                        headers={
                            "X-RateLimit-Limit": str(config.requests_per_hour),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str(reset_hour),
                            "Retry-After": str(retry_after),
                        },
                    )
            except HTTPException:
                raise
            except Exception as exc:
                logger.warning("Rate limiter unavailable, using in-memory fallback: %s", exc)
                if not rate_limiter._check_fallback(f"fallback:{base_key}:minute", config.requests_per_minute, 60):
                    raise HTTPException(
                        status_code=429,
                        detail="Rate limit exceeded (degraded mode). Please try again later.",
                        headers={"Retry-After": "60"},
                    )

            return await func(*args, **kwargs)

        _preserve_fastapi_signature(wrapper, func)
        return wrapper

    return decorator
