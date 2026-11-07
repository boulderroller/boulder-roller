import asyncio
import inspect
from typing import get_type_hints
from uuid import UUID

from app.config import (
    auth_cookie_secure_effective,
    auth_signature_bypass_effective,
    auth_signature_bypass_requested,
    dev_routes_enabled,
    get_app_version,
    get_environment,
    load_auth_settings,
)
from app.main import create_app
from app.routes.dev import _climb_lab_canon_db_publish_enabled
from app.routes.dev_climb_lab import CLIMB_LAB_REVIEW_HTML
from app.routes.health import system_status
from app.routes.interactions import add_comment_to_ride


def test_app_environment_falls_back_to_app_env_and_disables_dev_routes(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "test-refresh-secret")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ENABLE_DEV_ROUTES", raising=False)
    monkeypatch.setenv("AUTH_SIGNATURE_BYPASS", "true")
    get_environment.cache_clear()
    load_auth_settings.cache_clear()

    app = create_app()
    paths = {route.path for route in app.routes}
    status = asyncio.run(system_status())

    assert status.environment == "production"
    assert status.environment_public is True
    assert get_environment() == "production"
    assert status.auth_signature_bypass_requested is True
    assert status.auth_signature_bypass_effective is False
    assert status.auth_cookie_secure is True
    assert status.dev_routes_enabled is False
    assert "/dev/tiles/dashboard" not in paths
    assert "/dev/climb-lab" not in paths


def test_staging_ignores_signature_bypass_and_uses_secure_cookies(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "test-refresh-secret")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_SIGNATURE_BYPASS", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("ENABLE_DEV_ROUTES", "true")
    monkeypatch.setenv("APP_VERSION", "abc123")
    get_environment.cache_clear()
    load_auth_settings.cache_clear()

    settings = load_auth_settings()
    status = asyncio.run(system_status())

    assert auth_signature_bypass_requested() is True
    assert auth_signature_bypass_effective("staging") is False
    assert auth_cookie_secure_effective("staging") is True
    assert dev_routes_enabled("staging") is False
    assert get_app_version() == "abc123"
    assert settings.signature_bypass is False
    assert settings.cookie_secure is True
    assert status.environment == "staging"
    assert status.environment_public is True
    assert status.version == "abc123"
    assert status.auth_signature_bypass_requested is True
    assert status.auth_signature_bypass_effective is False
    assert status.auth_cookie_secure is True
    assert status.dev_routes_enabled is False


def test_development_can_enable_climb_lab_dev_route(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "test-refresh-secret")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("ENABLE_DEV_ROUTES", "true")
    get_environment.cache_clear()
    load_auth_settings.cache_clear()

    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/dev/tiles/dashboard" in paths
    assert "/dev/climb-lab" in paths
    assert "/dev/climb-lab/review" in paths
    assert "/dev/climb-lab/corpus" in paths
    assert "/dev/climb-lab/calibration" in paths
    assert "/dev/climb-lab/elevation-signals" in paths
    assert "/dev/climb-lab/road-graph" in paths
    assert "/dev/climb-lab/road-signals" in paths
    assert "/dev/climb-lab/pipeline-results" in paths
    assert "/dev/climb-lab/nomination-queue" in paths
    assert "/dev/climb-lab/scan-results" in paths
    assert "/dev/climb-lab/review-candidates" in paths
    assert "/dev/climb-lab/review-state" in paths
    assert "/dev/climb-lab/review-candidates/{candidate_id}/map-detail" in paths
    assert "/dev/climb-lab/review-candidates/{candidate_id}/decision" in paths
    assert "/dev/climb-lab/review-candidates/{candidate_id}/actions/{action_id}" in paths


def test_climb_lab_review_map_keeps_line_above_tiles() -> None:
    assert ".leaflet-tile-pane { z-index: 200; }" in CLIMB_LAB_REVIEW_HTML
    assert ".leaflet-overlay-pane { z-index: 400; }" in CLIMB_LAB_REVIEW_HTML
    assert 'color: "#0b0f12"' in CLIMB_LAB_REVIEW_HTML
    assert 'color: "#f3a712"' in CLIMB_LAB_REVIEW_HTML


def test_climb_lab_review_buttons_reenable_after_detail_loads() -> None:
    assert (
        'integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="'
        in CLIMB_LAB_REVIEW_HTML
    )
    assert ".decision-button:disabled { opacity: 0.5; cursor: not-allowed; }" in CLIMB_LAB_REVIEW_HTML
    assert "renderProfile(selectedDetail);\n                setButtonsDisabled(false);" in CLIMB_LAB_REVIEW_HTML
    assert "catch (error) {\n                setButtonsDisabled(true);" in CLIMB_LAB_REVIEW_HTML


def test_climb_lab_canon_db_publish_requires_explicit_dev_flag(monkeypatch) -> None:
    monkeypatch.delenv("CLIMB_LAB_CANON_DB_PUBLISH_ENABLED", raising=False)
    assert _climb_lab_canon_db_publish_enabled() is False

    monkeypatch.setenv("CLIMB_LAB_CANON_DB_PUBLISH_ENABLED", "true")
    assert _climb_lab_canon_db_publish_enabled() is True


def test_auth_settings_default_to_canonical_xyz_siws_origin(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "test-access-secret")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "test-refresh-secret")
    monkeypatch.delenv("AUTH_SIWS_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH_SIWS_URI", raising=False)
    load_auth_settings.cache_clear()

    settings = load_auth_settings()

    assert settings.domain == "app.boulderroller.xyz"
    assert settings.uri == "https://app.boulderroller.xyz"


def test_rate_limit_preserves_uuid_annotations_for_fastapi() -> None:
    ride_id_annotation = get_type_hints(add_comment_to_ride)["ride_id"]
    assert ride_id_annotation is UUID
