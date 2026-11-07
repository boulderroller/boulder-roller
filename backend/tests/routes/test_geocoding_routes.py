from __future__ import annotations

import asyncio
import json
import os
from typing import Any

# Route dependencies load auth settings at import time.
os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app.dependencies import AuthenticatedUser, get_current_user
from app.config import GeocoderSettings
from app.main import _scrub_sensitive_sentry_request_body
from app.rate_limits_config import RATE_LIMITS
from app.routes import geocoding as geocoding_route
from app.routes.geocoding import get_geocoding_service, router
from app.services.geocoding import GeocodingUnavailable


class FakeGeocodingService:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str) -> dict[str, Any]:
        self.queries.append(query)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


class CaptureSentryTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            event = item.get_event()
            if event is not None:
                self.events.append(event)


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        wallet="ViewerWallet11111111111111111111111111111",
        user_id="viewer-user",
        device_id="device-1",
    )


def _app(service: FakeGeocodingService, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/geocoding")
    app.dependency_overrides[get_geocoding_service] = lambda: service

    if authenticated:
        app.dependency_overrides[get_current_user] = _user
    else:
        async def reject_user() -> None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
            )

        app.dependency_overrides[get_current_user] = reject_user
    return app


def _available_response() -> dict[str, Any]:
    return {
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
            "text": "\u00a9 OpenStreetMap contributors",
            "url": "https://www.openstreetmap.org/copyright",
        },
        "provider": "nominatim",
        "cached": False,
    }


def test_post_search_returns_typed_geocoding_v1_contract() -> None:
    service = FakeGeocodingService(response=_available_response())

    with TestClient(_app(service)) as client:
        response = client.post(
            "/geocoding/search",
            json={"query": "Ridge Avenue"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "contractVersion": "geocoding.v1",
        "state": "available",
        "results": [
            {
                "displayName": "Ridge Avenue, Philadelphia, Pennsylvania",
                "latitude": 40.02741,
                "longitude": -75.22419,
            }
        ],
        "attribution": {
            "text": "\u00a9 OpenStreetMap contributors",
            "url": "https://www.openstreetmap.org/copyright",
        },
        "provider": "nominatim",
        "cached": False,
    }
    assert service.queries == ["Ridge Avenue"]


def test_geocoding_has_a_low_dedicated_rate_budget() -> None:
    config = RATE_LIMITS["geocoding"]

    assert config.requests_per_minute == 10
    assert config.requests_per_hour == 60
    assert config.burst_limit == 1


@pytest.mark.asyncio
async def test_cold_concurrent_dependency_calls_share_one_service(monkeypatch) -> None:
    monkeypatch.setattr(geocoding_route, "_geocoding_service", None, raising=False)
    monkeypatch.setattr(
        geocoding_route,
        "_geocoding_service_lock",
        None,
        raising=False,
    )

    settings_calls = 0

    def settings() -> GeocoderSettings:
        nonlocal settings_calls
        settings_calls += 1
        return GeocoderSettings(enabled=False, search_url="")

    monkeypatch.setattr(
        geocoding_route,
        "load_geocoder_settings",
        settings,
    )
    monkeypatch.setattr(
        geocoding_route,
        "SharedGeocodingCache",
        lambda: object(),
    )

    services = await asyncio.gather(
        *(get_geocoding_service() for _ in range(16))
    )
    assert services[0] is services[1]
    assert all(service is services[0] for service in services)
    assert settings_calls == 1


def test_search_is_post_only() -> None:
    service = FakeGeocodingService(response=_available_response())

    with TestClient(_app(service)) as client:
        response = client.get("/geocoding/search", params={"q": "Ridge Avenue"})

    assert response.status_code == 405
    assert service.queries == []


def test_search_requires_authenticated_user() -> None:
    service = FakeGeocodingService(response=_available_response())

    with TestClient(_app(service, authenticated=False)) as client:
        response = client.post(
            "/geocoding/search",
            json={"query": "Ridge Avenue"},
        )

    assert response.status_code == 401
    assert service.queries == []


def test_invalid_normalized_query_is_422_without_echoing_query() -> None:
    service = FakeGeocodingService(response=_available_response())

    with TestClient(_app(service)) as client:
        response = client.post("/geocoding/search", json={"query": "  x "})

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_place_query"}}
    assert "  x " not in response.text
    assert service.queries == []


def test_upstream_failure_is_honest_generic_503() -> None:
    service = FakeGeocodingService(
        error=GeocodingUnavailable("provider leaked q=private home address")
    )

    with TestClient(_app(service)) as client:
        response = client.post(
            "/geocoding/search",
            json={"query": "private home address"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "place_search_unavailable"}
    }
    assert "private home address" not in response.text
    assert "provider leaked" not in response.text


def test_unhandled_error_never_emits_place_query_or_referer_to_sentry() -> None:
    raw_query = "Private Home Address 123"
    encoded_query = "Private%20Home%20Address%20123"
    service = FakeGeocodingService(
        error=RuntimeError(f"unexpected failure for {raw_query}")
    )
    transport = CaptureSentryTransport()
    previous_client = sentry_sdk.get_client()
    sentry_client = sentry_sdk.Client(
        dsn="https://public@example.com/1",
        transport=transport,
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=_scrub_sensitive_sentry_request_body,
        before_send_transaction=_scrub_sensitive_sentry_request_body,
    )
    sentry_sdk.get_global_scope().set_client(sentry_client)

    try:
        with TestClient(_app(service), raise_server_exceptions=False) as client:
            response = client.post(
                "/geocoding/search",
                json={"query": raw_query},
                headers={
                    "referer": (
                        "https://app.boulderroller.xyz/climbs"
                        f"?search={encoded_query}"
                    )
                },
            )
        sentry_client.flush(timeout=2)
    finally:
        sentry_client.close()
        sentry_sdk.get_global_scope().set_client(previous_client)

    assert response.status_code == 500
    assert transport.events
    serialized_events = json.dumps(transport.events)
    assert raw_query not in serialized_events
    assert encoded_query not in serialized_events
    for event in transport.events:
        request = event.get("request", {})
        assert "data" not in request
        assert "headers" not in request
        assert "query_string" not in request


def test_sentry_scrub_also_covers_privacy_zone_coordinates_and_labels() -> None:
    private_label = "Private home"
    private_latitude = "40.123456"
    private_longitude = "-75.654321"
    event = {
        "request": {
            "url": "https://api.boulderroller.xyz/privacy/zones?source=settings",
            "query_string": "source=settings",
            "headers": {
                "Referer": "https://app.boulderroller.xyz/settings/privacy",
            },
            "data": {
                "label": private_label,
                "latitude": private_latitude,
                "longitude": private_longitude,
            },
        },
        "exception": {
            "values": [
                {
                    "value": f"failed for {private_label}",
                    "stacktrace": {
                        "frames": [
                            {
                                "vars": {
                                    "label": private_label,
                                    "latitude": private_latitude,
                                    "longitude": private_longitude,
                                }
                            }
                        ]
                    },
                }
            ]
        },
    }

    scrubbed = _scrub_sensitive_sentry_request_body(event, {})
    serialized_event = json.dumps(scrubbed)

    assert private_label not in serialized_event
    assert private_latitude not in serialized_event
    assert private_longitude not in serialized_event
    assert scrubbed["request"]["url"] == (
        "https://api.boulderroller.xyz/privacy/zones"
    )


def test_sentry_scrub_also_removes_bodies_on_other_routes() -> None:
    event = {
        "request": {
            "url": "https://api.boulderroller.xyz/status",
            "data": {"diagnostic": "keep"},
        }
    }

    result = _scrub_sensitive_sentry_request_body(event, {})
    assert result["request"]["url"] == event["request"]["url"]
    assert "data" not in result["request"]
