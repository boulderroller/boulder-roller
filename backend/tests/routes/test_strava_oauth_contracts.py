from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.responses import Response

from app.routes.strava import (
    STRAVA_OAUTH_STATE_COOKIE,
    StravaError,
    _validate_strava_oauth_state,
)


def test_strava_oauth_state_requires_exact_nonce_match() -> None:
    response = Response()
    request = SimpleNamespace(cookies={STRAVA_OAUTH_STATE_COOKIE: "wallet-1:nonce-a"})

    with pytest.raises(StravaError) as excinfo:
        _validate_strava_oauth_state(
            request,
            response,
            state="wallet-1:nonce-b",
            wallet="wallet-1",
        )

    assert excinfo.value.detail["error"]["code"] == "invalid_state"


def test_strava_oauth_state_accepts_cookie_backed_nonce_once() -> None:
    response = Response()
    request = SimpleNamespace(cookies={STRAVA_OAUTH_STATE_COOKIE: "wallet-1:nonce-a"})

    _validate_strava_oauth_state(
        request,
        response,
        state="wallet-1:nonce-a",
        wallet="wallet-1",
    )

    assert any(header.lower().startswith("br_strava_oauth_state=") for header in response.headers.getlist("set-cookie"))
