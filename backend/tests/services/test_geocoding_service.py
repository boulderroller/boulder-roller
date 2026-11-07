from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sentry_sdk

from app.config import GeocoderSettings
from app.services.geocoding import (
    GEOCODER_ATTRIBUTION_TEXT,
    GEOCODER_ATTRIBUTION_URL,
    GEOCODER_PROVIDER,
    GEOCODER_REFERER,
    GEOCODER_USER_AGENT,
    GeocodingCacheUnavailable,
    GeocodingQueryError,
    GeocodingService,
    GeocodingUnavailable,
    MemoryGeocodingCache,
    SharedGeocodingCache,
    geocoding_cache_key,
    normalize_geocoding_query,
)


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def wall_time(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        *,
        status_error: bool = False,
        json_error: bool = False,
        yield_once: bool = False,
    ) -> None:
        self.payload = payload
        self.status_error = status_error
        self.json_error = json_error
        self.yield_once = yield_once

    def raise_for_status(self) -> None:
        if self.status_error:
            request = httpx.Request("GET", "https://provider.invalid/search")
            response = httpx.Response(502, request=request)
            raise httpx.HTTPStatusError("provider failed", request=request, response=response)

    def json(self) -> Any:
        if self.json_error:
            raise ValueError("not json")
        return self.payload


class FakeClient:
    def __init__(
        self,
        responses: list[FakeResponse | Exception],
        calls: list[dict[str, Any]],
        clock: FakeClock,
    ) -> None:
        self.responses = responses
        self.calls = calls
        self.clock = clock

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "params": params,
                "headers": headers,
                "started_at": self.clock.monotonic(),
                "sentry_current_span": sentry_sdk.get_current_scope().span,
                "sentry_isolation_span": sentry_sdk.get_isolation_scope().span,
            }
        )
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome.yield_once:
            # Cooperatively let an equivalent request reach the service lock.
            # This advances no clock and performs no real wait.
            await asyncio.sleep(0)
        return outcome


class FakeClientFactory:
    def __init__(self, responses: list[FakeResponse | Exception], clock: FakeClock) -> None:
        self.responses = responses
        self.clock = clock
        self.calls: list[dict[str, Any]] = []
        self.client_options: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FakeClient:
        self.client_options.append(kwargs)
        return FakeClient(self.responses, self.calls, self.clock)


def _settings(*, enabled: bool = True) -> GeocoderSettings:
    return GeocoderSettings(
        enabled=enabled,
        search_url="https://geo.example.test/nominatim/search",
    )


def _service(
    responses: list[FakeResponse | Exception],
    *,
    clock: FakeClock | None = None,
) -> tuple[GeocodingService, FakeClientFactory, FakeClock]:
    fake_clock = clock or FakeClock()
    factory = FakeClientFactory(responses, fake_clock)
    cache = MemoryGeocodingCache(
        ttl_seconds=24 * 60 * 60,
        max_entries=32,
        wall_time=fake_clock.wall_time,
    )
    return (
        GeocodingService(
            settings=_settings(),
            cache=cache,
            client_factory=factory,
            monotonic=fake_clock.monotonic,
            sleep=fake_clock.sleep,
        ),
        factory,
        fake_clock,
    )


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Ridge   Avenue  ", "Ridge Avenue"),
        ("Cafe\u0301\u3000Road", "Caf\u00e9 Road"),
    ],
)
def test_normalize_geocoding_query_nfkc_and_collapses_whitespace(
    raw: str,
    normalized: str,
) -> None:
    assert normalize_geocoding_query(raw) == normalized


@pytest.mark.parametrize("raw", ["", "  a ", "x" * 121])
def test_normalize_geocoding_query_rejects_out_of_bounds(raw: str) -> None:
    with pytest.raises(GeocodingQueryError):
        normalize_geocoding_query(raw)


def test_cache_key_hashes_provider_and_normalized_query_without_query_text() -> None:
    raw = "  Private Home Address  "
    normalized = normalize_geocoding_query(raw)

    key = geocoding_cache_key(
        "https://geo.example.test/nominatim/search",
        normalized,
    )

    assert key.startswith("v1.")
    assert len(key) == len("v1.") + 64
    assert "Private" not in key
    assert normalized not in key
    assert normalized.casefold() not in key
    assert key == geocoding_cache_key(
        "https://geo.example.test/nominatim/search",
        normalized.swapcase(),
    )
    assert key != geocoding_cache_key(
        "https://other.example.test/nominatim/search",
        normalized,
    )


@pytest.mark.asyncio
async def test_search_normalizes_and_caches_casefold_equivalent_query() -> None:
    service, factory, _clock = _service(
        [
            FakeResponse(
                [
                    {
                        "display_name": "Ridge Avenue, Philadelphia, Pennsylvania",
                        "lat": "40.02741",
                        "lon": "-75.22419",
                    }
                ]
            )
        ]
    )

    first = await service.search("  RIDGE\u3000Avenue ")
    second = await service.search("ridge avenue")

    assert first == {
        "contract_version": "geocoding.v1",
        "state": "available",
        "results": [
            {
                "display_name": "Ridge Avenue, Philadelphia, Pennsylvania",
                "latitude": 40.02741,
                "longitude": -75.22419,
            }
        ],
        "attribution": {
            "text": GEOCODER_ATTRIBUTION_TEXT,
            "url": GEOCODER_ATTRIBUTION_URL,
        },
        "provider": GEOCODER_PROVIDER,
        "cached": False,
    }
    assert second["results"] == first["results"]
    assert second["cached"] is True
    assert len(factory.calls) == 1
    assert factory.calls[0]["url"] == "https://geo.example.test/nominatim/search"
    assert factory.calls[0]["params"] == {
        "q": "RIDGE Avenue",
        "format": "jsonv2",
        "limit": 5,
    }
    assert factory.calls[0]["headers"] == {
        "Accept": "application/json",
        "User-Agent": GEOCODER_USER_AGENT,
        "Referer": GEOCODER_REFERER,
    }
    assert factory.client_options == [
        {"timeout": 5.0, "follow_redirects": False}
    ]


@pytest.mark.asyncio
async def test_search_caches_successful_empty_results() -> None:
    service, factory, _clock = _service([FakeResponse([])])

    first = await service.search("No Such Hill")
    second = await service.search("no such hill")

    assert first["results"] == []
    assert first["cached"] is False
    assert second["results"] == []
    assert second["cached"] is True
    assert len(factory.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_equivalent_queries_coalesce_after_cache_recheck_in_lock() -> None:
    service, factory, _clock = _service([FakeResponse([], yield_once=True)])

    first, second = await asyncio.gather(
        service.search("Ridge Avenue"),
        service.search("  ridge avenue  "),
    )

    assert len(factory.calls) == 1
    assert sorted([first["cached"], second["cached"]]) == [False, True]


@pytest.mark.asyncio
async def test_upstream_request_starts_are_serialized_and_spaced_without_real_sleep() -> None:
    clock = FakeClock(value=10.0)
    service, factory, _clock = _service(
        [FakeResponse([]), FakeResponse([])],
        clock=clock,
    )

    await service.search("First Hill")
    await service.search("Second Hill")

    assert [call["started_at"] for call in factory.calls] == [10.0, 11.05]
    assert clock.sleeps == [pytest.approx(1.05)]


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": "mapping"},
        [{"display_name": "Missing coordinates"}],
        [{"display_name": "Bad latitude", "lat": "91", "lon": "-75"}],
        [{"display_name": "Bad longitude", "lat": "40", "lon": "181"}],
        [{"display_name": "Not finite", "lat": "nan", "lon": "-75"}],
        [{"display_name": "", "lat": "40", "lon": "-75"}],
    ],
)
@pytest.mark.asyncio
async def test_search_rejects_malformed_upstream_payload(payload: Any) -> None:
    service, _factory, _clock = _service([FakeResponse(payload)])

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")


@pytest.mark.parametrize(
    "outcome",
    [
        FakeResponse(status_error=True),
        FakeResponse(json_error=True),
        httpx.ReadTimeout("provider timed out"),
    ],
)
@pytest.mark.asyncio
async def test_search_maps_upstream_failures_to_unavailable(
    outcome: FakeResponse | Exception,
) -> None:
    service, _factory, _clock = _service([outcome])

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")


@pytest.mark.asyncio
async def test_disabled_provider_fails_before_cache_or_http() -> None:
    clock = FakeClock()
    factory = FakeClientFactory([FakeResponse([])], clock)
    cache = MemoryGeocodingCache(wall_time=clock.wall_time)
    service = GeocodingService(
        settings=_settings(enabled=False),
        cache=cache,
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []
    assert factory.client_options == []


@pytest.mark.asyncio
async def test_public_shared_cache_unavailability_fails_closed() -> None:
    async def unavailable_loader() -> None:
        return None

    clock = FakeClock()
    cache = SharedGeocodingCache(
        public_environment=True,
        kv_loader=unavailable_loader,
    )
    factory = FakeClientFactory([FakeResponse([])], clock)
    service = GeocodingService(
        settings=_settings(),
        cache=cache,
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(GeocodingCacheUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []
    assert factory.client_options == []


@pytest.mark.asyncio
async def test_concurrent_shared_cache_initialization_awaits_one_loader() -> None:
    loader_started = asyncio.Event()
    release_loader = asyncio.Event()
    loader_calls = 0

    class EmptyKV:
        async def get(self, _key: str) -> None:
            return None

    async def loader() -> EmptyKV:
        nonlocal loader_calls
        loader_calls += 1
        loader_started.set()
        await release_loader.wait()
        return EmptyKV()

    cache = SharedGeocodingCache(
        public_environment=True,
        kv_loader=loader,
    )
    first = asyncio.create_task(cache.get("v1.first"))
    await loader_started.wait()
    second = asyncio.create_task(cache.get("v1.second"))
    await asyncio.sleep(0)
    release_loader.set()

    assert await asyncio.gather(first, second) == [None, None]
    assert loader_calls == 1


@pytest.mark.asyncio
async def test_shared_cache_retries_after_bounded_failure_window() -> None:
    clock = FakeClock()
    loader_calls = 0

    class EmptyKV:
        async def get(self, _key: str) -> None:
            return None

    async def recovering_loader() -> EmptyKV | None:
        nonlocal loader_calls
        loader_calls += 1
        return None if loader_calls == 1 else EmptyKV()

    cache = SharedGeocodingCache(
        public_environment=True,
        kv_loader=recovering_loader,
        monotonic=clock.monotonic,
        retry_seconds=5.0,
    )

    with pytest.raises(GeocodingCacheUnavailable):
        await cache.get("v1.retry")
    with pytest.raises(GeocodingCacheUnavailable):
        await cache.get("v1.retry")
    assert loader_calls == 1

    clock.value += 5.0
    assert await cache.get("v1.retry") is None
    assert loader_calls == 2


@pytest.mark.asyncio
async def test_public_malformed_shared_cache_entry_fails_closed_without_http() -> None:
    class MalformedKV:
        async def get(self, _key: str) -> SimpleNamespace:
            return SimpleNamespace(value=b'{"results":{"not":"a-list"}}')

    async def malformed_loader() -> MalformedKV:
        return MalformedKV()

    clock = FakeClock()
    cache = SharedGeocodingCache(
        public_environment=True,
        kv_loader=malformed_loader,
    )
    factory = FakeClientFactory([FakeResponse([])], clock)
    service = GeocodingService(
        settings=_settings(),
        cache=cache,
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(GeocodingCacheUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []
    assert factory.client_options == []


@pytest.mark.parametrize("display_name", ["   ", "x" * 513])
@pytest.mark.asyncio
async def test_cached_display_name_uses_upstream_whitespace_and_length_guards(
    display_name: str,
) -> None:
    class StaticCache:
        async def get(self, _key: str) -> list[dict[str, Any]]:
            return [
                {
                    "display_name": display_name,
                    "latitude": 40.0,
                    "longitude": -75.0,
                }
            ]

        async def set(self, _key: str, _results: list[dict[str, Any]]) -> None:
            raise AssertionError("invalid cache entry must not be replaced in-request")

    clock = FakeClock()
    factory = FakeClientFactory([FakeResponse([])], clock)
    service = GeocodingService(
        settings=_settings(),
        cache=StaticCache(),
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []


def test_query_bearing_http_transport_loggers_are_explicitly_suppressed() -> None:
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


@pytest.mark.asyncio
async def test_public_provider_configuration_requires_https() -> None:
    clock = FakeClock()
    factory = FakeClientFactory([FakeResponse([])], clock)
    cache = MemoryGeocodingCache(wall_time=clock.wall_time)
    service = GeocodingService(
        settings=GeocoderSettings(
            enabled=True,
            search_url="http://geo.example.test/nominatim/search",
        ),
        cache=cache,
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        public_environment=True,
    )

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []
    assert factory.client_options == []


@pytest.mark.asyncio
async def test_malformed_provider_url_fails_as_unavailable_before_cache_or_http() -> None:
    clock = FakeClock()
    factory = FakeClientFactory([FakeResponse([])], clock)
    cache = MemoryGeocodingCache(wall_time=clock.wall_time)
    service = GeocodingService(
        settings=GeocoderSettings(
            enabled=True,
            search_url="https://[malformed-provider/search",
        ),
        cache=cache,
        client_factory=factory,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        public_environment=True,
    )

    with pytest.raises(GeocodingUnavailable):
        await service.search("Ridge Avenue")

    assert factory.calls == []
    assert factory.client_options == []


@pytest.mark.asyncio
async def test_query_bearing_http_call_is_detached_from_sentry_scopes() -> None:
    service, factory, _clock = _service([FakeResponse([])])
    parent_span = object()

    with sentry_sdk.isolation_scope() as isolation:
        isolation.span = parent_span  # type: ignore[assignment]
        sentry_sdk.get_current_scope().span = parent_span  # type: ignore[assignment]
        await service.search("Private Home Address")

    assert factory.calls[0]["sentry_current_span"] is None
    assert factory.calls[0]["sentry_isolation_span"] is None
