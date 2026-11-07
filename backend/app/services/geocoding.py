"""Bounded, provider-safe place search for the launch climbs map.

The portal only calls this service after an explicit rider submit. Provider
requests stay behind the backend so headers, caching, pacing, and failures have
one enforceable policy boundary.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    Iterator,
    Optional,
    Protocol,
)
from urllib.parse import urlsplit

import httpx
import sentry_sdk

from ..config import GeocoderSettings, is_public_environment


logger = logging.getLogger(__name__)

# httpx/httpcore log complete request URLs at lower levels. Because the place
# query is a GET parameter, enforce a privacy floor before any client exists.
for _transport_logger_name in ("httpx", "httpcore"):
    _transport_logger = logging.getLogger(_transport_logger_name)
    if _transport_logger.level < logging.WARNING:
        _transport_logger.setLevel(logging.WARNING)

GEOCODER_PROVIDER = "nominatim"
GEOCODER_USER_AGENT = "BoulderRoller/1.0 (+https://boulderroller.xyz)"
GEOCODER_REFERER = "https://app.boulderroller.xyz/climbs"
GEOCODER_ATTRIBUTION_TEXT = "© OpenStreetMap contributors"
GEOCODER_ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"

GEOCODER_QUERY_MIN_LENGTH = 3
GEOCODER_QUERY_MAX_LENGTH = 120
GEOCODER_RESULT_LIMIT = 5
GEOCODER_HTTP_TIMEOUT_SECONDS = 5.0
GEOCODER_CACHE_TTL_SECONDS = 24 * 60 * 60
GEOCODER_CACHE_RETRY_SECONDS = 5.0
GEOCODER_UPSTREAM_START_INTERVAL_SECONDS = 1.05


class GeocodingQueryError(ValueError):
    """The submitted query cannot be sent to the provider."""


class GeocodingUnavailable(RuntimeError):
    """Place search cannot return an honest provider-backed result."""


class GeocodingCacheUnavailable(GeocodingUnavailable):
    """The required shared cache is unavailable in a public environment."""


class GeocodingCache(Protocol):
    async def get(self, key: str) -> Optional[list[dict[str, Any]]]: ...

    async def set(self, key: str, results: list[dict[str, Any]]) -> None: ...


def normalize_geocoding_query(value: str) -> str:
    """NFKC-normalize and collapse Unicode whitespace within launch bounds."""
    if not isinstance(value, str):
        raise GeocodingQueryError("invalid query")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    if not GEOCODER_QUERY_MIN_LENGTH <= len(normalized) <= GEOCODER_QUERY_MAX_LENGTH:
        raise GeocodingQueryError("invalid query")
    return normalized


def geocoding_cache_key(search_url: str, normalized_query: str) -> str:
    """Return an opaque KV-safe key; query text never appears in cache keys."""
    material = f"{search_url}\0{normalized_query.casefold()}".encode("utf-8")
    return f"v1.{hashlib.sha256(material).hexdigest()}"


@contextmanager
def _without_sentry_http_query_span() -> Iterator[None]:
    """Detach the query-bearing HTTPX call from request tracing scopes."""
    isolation_scope_factory = getattr(sentry_sdk, "isolation_scope", None)
    current_scope_getter = getattr(sentry_sdk, "get_current_scope", None)
    if isolation_scope_factory is not None and current_scope_getter is not None:
        with isolation_scope_factory() as isolation_scope:
            isolation_scope.span = None
            current_scope_getter().span = None
            yield
        return

    # Compatibility for sentry-sdk 1.x, which is still allowed by the repo's
    # lower dependency bound and uses one pushed Hub scope for active spans.
    with sentry_sdk.push_scope() as legacy_scope:
        legacy_scope.span = None
        yield


class MemoryGeocodingCache:
    """Bounded TTL/LRU fallback for non-public and focused-test runtimes."""

    def __init__(
        self,
        *,
        ttl_seconds: int = GEOCODER_CACHE_TTL_SECONDS,
        max_entries: int = 512,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._wall_time = wall_time
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    async def get(self, key: str) -> Optional[list[dict[str, Any]]]:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, encoded = entry
        if expires_at <= self._wall_time():
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        payload = json.loads(encoded.decode("utf-8"))
        return payload["results"]

    async def set(self, key: str, results: list[dict[str, Any]]) -> None:
        encoded = json.dumps(
            {"results": results},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self._entries[key] = (self._wall_time() + self._ttl_seconds, encoded)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class SharedGeocodingCache:
    """NATS KV cache with a non-public bounded in-memory fallback."""

    KV_BUCKET = "GEOCODER_CACHE"

    def __init__(
        self,
        *,
        public_environment: Optional[bool] = None,
        kv_loader: Optional[Callable[[], Awaitable[Any]]] = None,
        fallback: Optional[MemoryGeocodingCache] = None,
        monotonic: Callable[[], float] = time.monotonic,
        retry_seconds: float = GEOCODER_CACHE_RETRY_SECONDS,
    ) -> None:
        self._public_environment = (
            is_public_environment()
            if public_environment is None
            else public_environment
        )
        self._kv_loader = kv_loader or self._connect_kv
        self._fallback = fallback or MemoryGeocodingCache()
        self._monotonic = monotonic
        self._retry_seconds = max(1.0, retry_seconds)
        self._kv: Any = None
        self._kv_init_lock: Optional[asyncio.Lock] = None
        self._next_kv_retry_at = 0.0

    async def _connect_kv(self) -> Any:
        from .nats_client import get_nats_client

        client = get_nats_client()
        await client.connect()
        js = client._js
        if js is None:
            raise RuntimeError("NATS JetStream is unavailable")
        try:
            return await js.key_value(self.KV_BUCKET)
        except Exception:
            return await js.create_key_value(
                bucket=self.KV_BUCKET,
                ttl=GEOCODER_CACHE_TTL_SECONDS,
            )

    async def _ensure_kv(self) -> Any:
        if self._kv is not None:
            return self._kv

        if self._kv_init_lock is None:
            self._kv_init_lock = asyncio.Lock()
        async with self._kv_init_lock:
            if self._kv is not None:
                return self._kv

            now = self._monotonic()
            if now >= self._next_kv_retry_at:
                try:
                    loaded_kv = await self._kv_loader()
                    if loaded_kv is None:
                        raise RuntimeError("NATS KV loader returned no cache")
                    self._kv = loaded_kv
                    self._next_kv_retry_at = 0.0
                except Exception:
                    # Never include exception text: provider/cache clients can
                    # carry request context, while raw place queries must not
                    # enter logs. A short cooldown permits transient recovery.
                    logger.warning("[Geocoding] shared cache initialization failed")
                    self._kv = None
                    self._next_kv_retry_at = now + self._retry_seconds

        if self._kv is None and self._public_environment:
            raise GeocodingCacheUnavailable("shared geocoding cache unavailable")
        return self._kv

    @staticmethod
    def _is_missing_key_error(exc: Exception) -> bool:
        return exc.__class__.__name__ in {
            "KeyDeletedError",
            "KeyNotFoundError",
            "NotFoundError",
        }

    async def get(self, key: str) -> Optional[list[dict[str, Any]]]:
        kv = await self._ensure_kv()
        if kv is None:
            return await self._fallback.get(key)

        try:
            entry = await kv.get(key)
        except Exception as exc:
            if self._is_missing_key_error(exc):
                return None
            logger.warning("[Geocoding] shared cache read failed")
            if self._public_environment:
                raise GeocodingCacheUnavailable(
                    "shared geocoding cache unavailable"
                ) from None
            return await self._fallback.get(key)

        if entry is None or not getattr(entry, "value", None):
            return None
        try:
            payload = json.loads(entry.value.decode("utf-8"))
            results = payload["results"]
            if not isinstance(results, list):
                raise ValueError("invalid cached results")
            return results
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("[Geocoding] shared cache entry was invalid")
            if self._public_environment:
                raise GeocodingCacheUnavailable(
                    "shared geocoding cache unavailable"
                ) from None
            return None

    async def set(self, key: str, results: list[dict[str, Any]]) -> None:
        kv = await self._ensure_kv()
        if kv is None:
            await self._fallback.set(key, results)
            return

        encoded = json.dumps(
            {"results": results},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            await kv.put(key, encoded)
        except Exception:
            logger.warning("[Geocoding] shared cache write failed")
            if self._public_environment:
                raise GeocodingCacheUnavailable(
                    "shared geocoding cache unavailable"
                ) from None
            await self._fallback.set(key, results)


class GeocodingService:
    """Nominatim-compatible search with bounded cache, validation, and pacing."""

    def __init__(
        self,
        *,
        settings: GeocoderSettings,
        cache: GeocodingCache,
        client_factory: Callable[..., AsyncContextManager[Any]] = httpx.AsyncClient,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        public_environment: Optional[bool] = None,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._client_factory = client_factory
        self._monotonic = monotonic
        self._sleep = sleep
        self._public_environment = (
            is_public_environment()
            if public_environment is None
            else public_environment
        )
        self._upstream_lock: Optional[asyncio.Lock] = None
        self._last_upstream_started_at: Optional[float] = None

    def _search_url(self) -> str:
        search_url = self._settings.search_url.strip()
        try:
            parsed = urlsplit(search_url)
        except (TypeError, ValueError):
            # Treat malformed provider configuration like any other disabled
            # provider. Never expose parser details as an unhandled 500.
            raise GeocodingUnavailable("geocoding provider disabled") from None
        allowed_schemes = {"https"} if self._public_environment else {"http", "https"}
        if (
            not self._settings.enabled
            or parsed.scheme not in allowed_schemes
            or not parsed.netloc
        ):
            raise GeocodingUnavailable("geocoding provider disabled")
        return search_url

    @staticmethod
    def _response(
        results: list[dict[str, Any]],
        *,
        cached: bool,
    ) -> dict[str, Any]:
        return {
            "contract_version": "geocoding.v1",
            "state": "available",
            "results": results,
            "attribution": {
                "text": GEOCODER_ATTRIBUTION_TEXT,
                "url": GEOCODER_ATTRIBUTION_URL,
            },
            "provider": GEOCODER_PROVIDER,
            "cached": cached,
        }

    @staticmethod
    def _coordinate(value: Any, *, minimum: float, maximum: float) -> float:
        if isinstance(value, bool):
            raise ValueError("invalid coordinate")
        coordinate = float(value)
        if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
            raise ValueError("invalid coordinate")
        return coordinate

    @classmethod
    def _validate_upstream_results(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list) or len(payload) > GEOCODER_RESULT_LIMIT:
            raise ValueError("invalid geocoding payload")

        results: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("invalid geocoding result")
            display_name = item.get("display_name")
            if not isinstance(display_name, str):
                raise ValueError("invalid display name")
            display_name = " ".join(display_name.strip().split())
            if not display_name or len(display_name) > 512:
                raise ValueError("invalid display name")
            results.append(
                {
                    "display_name": display_name,
                    "latitude": cls._coordinate(
                        item.get("lat"),
                        minimum=-90,
                        maximum=90,
                    ),
                    "longitude": cls._coordinate(
                        item.get("lon"),
                        minimum=-180,
                        maximum=180,
                    ),
                }
            )
        return results

    @classmethod
    def _validate_cached_results(
        cls,
        payload: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, list) or len(payload) > GEOCODER_RESULT_LIMIT:
            raise ValueError("invalid cached geocoding payload")
        results: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("invalid cached geocoding result")
            display_name = item.get("display_name")
            if not isinstance(display_name, str):
                raise ValueError("invalid cached display name")
            display_name = " ".join(display_name.strip().split())
            if not display_name or len(display_name) > 512:
                raise ValueError("invalid cached display name")
            results.append(
                {
                    "display_name": display_name,
                    "latitude": cls._coordinate(
                        item.get("latitude"),
                        minimum=-90,
                        maximum=90,
                    ),
                    "longitude": cls._coordinate(
                        item.get("longitude"),
                        minimum=-180,
                        maximum=180,
                    ),
                }
            )
        return results

    async def _cached_results(
        self,
        cache_key: str,
    ) -> Optional[list[dict[str, Any]]]:
        try:
            cached = await self._cache.get(cache_key)
            if cached is None:
                return None
            return self._validate_cached_results(cached)
        except GeocodingCacheUnavailable:
            raise
        except Exception:
            logger.warning("[Geocoding] cached response validation failed")
            raise GeocodingUnavailable("geocoding cache invalid") from None

    async def _start_upstream_request(self, search_url: str, query: str) -> Any:
        now = self._monotonic()
        if self._last_upstream_started_at is not None:
            elapsed = now - self._last_upstream_started_at
            remaining = GEOCODER_UPSTREAM_START_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                await self._sleep(remaining)

        # This process-local clock/lock is sufficient only for the current
        # launch topology: one uvicorn process in one container/replica. A
        # second worker or replica requires distributed start scheduling before
        # geocoding can stay enabled.
        self._last_upstream_started_at = self._monotonic()
        async with self._client_factory(
            timeout=GEOCODER_HTTP_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            # Sentry's default HTTPX integration records the full HTTP query
            # on a child span. Fork and clear both active span scopes for this
            # call so the place query cannot attach to request telemetry.
            with _without_sentry_http_query_span():
                response = await client.get(
                    search_url,
                    params={
                        "q": query,
                        "format": "jsonv2",
                        "limit": GEOCODER_RESULT_LIMIT,
                    },
                    headers={
                        "Accept": "application/json",
                        "User-Agent": GEOCODER_USER_AGENT,
                        "Referer": GEOCODER_REFERER,
                    },
                )
            response.raise_for_status()
            return response.json()

    async def search(self, raw_query: str) -> dict[str, Any]:
        search_url = self._search_url()
        query = normalize_geocoding_query(raw_query)
        cache_key = geocoding_cache_key(search_url, query)

        cached = await self._cached_results(cache_key)
        if cached is not None:
            return self._response(cached, cached=True)

        # Serialize the provider boundary and recheck after acquiring the lock:
        # equivalent concurrent submissions collapse to one upstream request.
        if self._upstream_lock is None:
            self._upstream_lock = asyncio.Lock()
        async with self._upstream_lock:
            cached = await self._cached_results(cache_key)
            if cached is not None:
                return self._response(cached, cached=True)

            try:
                payload = await self._start_upstream_request(search_url, query)
                results = self._validate_upstream_results(payload)
            except (httpx.HTTPError, OverflowError, TypeError, ValueError):
                # Do not log exception or URL text; both can contain the query.
                logger.warning("[Geocoding] upstream search failed")
                raise GeocodingUnavailable("geocoding provider unavailable") from None

            await self._cache.set(cache_key, results)
            return self._response(results, cached=False)
