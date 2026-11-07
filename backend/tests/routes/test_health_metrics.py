from __future__ import annotations

import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.config import get_environment
from app.routes.health import _bearer_token, require_metrics_access, system_status


def test_bearer_token_parser_rejects_non_bearer_headers() -> None:
    assert _bearer_token(None) is None
    assert _bearer_token("Basic abc") is None
    assert _bearer_token("Bearer secret") == "secret"


@pytest.mark.asyncio
async def test_system_status_exposes_balance_rollout_state(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "collect_dung")
    monkeypatch.setenv("BALANCE_ROLLOUT_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", "ops")
    get_environment.cache_clear()

    response = await system_status()

    assert response.environment == "production"
    assert response.balance_rollout.stage == "collect_dung"
    assert response.balance_rollout.enabled_actions == ["collect_dung"]
    assert response.balance_rollout.enforced
    assert response.balance_rollout.order_valid


@pytest.mark.asyncio
async def test_metrics_access_accepts_prometheus_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    access = await require_metrics_access(
        authorization="Bearer metrics-secret",
        x_prometheus_token=None,
        current_user=None,
    )

    assert access == "prometheus"


@pytest.mark.asyncio
async def test_metrics_access_accepts_prometheus_header_token(monkeypatch) -> None:
    monkeypatch.setenv("PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    access = await require_metrics_access(
        authorization=None,
        x_prometheus_token="metrics-secret",
        current_user=None,
    )

    assert access == "prometheus"


@pytest.mark.asyncio
async def test_metrics_access_rejects_missing_token_without_user(monkeypatch) -> None:
    monkeypatch.setenv("PROMETHEUS_METRICS_TOKEN", "metrics-secret")

    with pytest.raises(HTTPException) as exc:
        await require_metrics_access(
            authorization=None,
            x_prometheus_token=None,
            current_user=None,
        )

    assert exc.value.status_code == 401
