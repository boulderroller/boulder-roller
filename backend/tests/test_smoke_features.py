"""Smoke tests for the 5 workstreams deployed 2026-03-03.

Tests hit the actual staging API at api.boulderroller.xyz.
Run with: pytest backend/tests/test_smoke_features.py -v
"""
import os

import pytest
import httpx

API_BASE = os.getenv("SMOKE_TEST_API")

pytestmark = pytest.mark.skipif(
    not API_BASE,
    reason="Set SMOKE_TEST_API to run deployed smoke tests explicitly.",
)


# ============================================================================
# WS1: React Query — frontend-only, no backend smoke tests needed
# ============================================================================


# ============================================================================
# WS2: Notifications
# ============================================================================

class TestNotifications:
    """Smoke tests for notification endpoints."""

    def test_notifications_requires_auth(self):
        r = httpx.get(f"{API_BASE}/notifications")
        assert r.status_code == 401

    def test_notification_preferences_requires_auth(self):
        r = httpx.get(f"{API_BASE}/notifications/preferences")
        assert r.status_code == 401

    def test_mark_all_read_requires_auth(self):
        r = httpx.post(f"{API_BASE}/notifications/read-all")
        assert r.status_code == 401


# ============================================================================
# WS3: Territory Map
# ============================================================================

class TestTerritory:
    """Smoke tests for territory endpoints."""

    def test_territory_tiles_requires_auth(self):
        r = httpx.get(f"{API_BASE}/territory/tiles")
        assert r.status_code == 401

    def test_territory_stats_requires_auth(self):
        r = httpx.get(f"{API_BASE}/territory/stats")
        assert r.status_code == 401

    def test_territory_heatmap_requires_auth(self):
        r = httpx.get(f"{API_BASE}/territory/heatmap")
        assert r.status_code == 401

    def test_vaults_list_returns_data(self):
        """Vaults endpoint returns data with lat/lon fields."""
        r = httpx.get(f"{API_BASE}/vaults?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert "vaults" in data
        if data["vaults"]:
            v = data["vaults"][0]
            assert "start_lat" in v
            assert "start_lon" in v
            assert "name" in v
            assert "vert_m" in v

    def test_vaults_rejects_overlimit(self):
        """Vaults endpoint rejects limit > 100."""
        r = httpx.get(f"{API_BASE}/vaults?limit=500")
        assert r.status_code == 422


# ============================================================================
# WS4: Stale Ride Cleanup
# ============================================================================

class TestStaleCleanup:
    """Smoke tests for stale ride cleanup."""

    def test_cleanup_stale_endpoint_requires_auth(self):
        r = httpx.post(f"{API_BASE}/rides/cleanup-stale")
        assert r.status_code == 401

    def test_cleanup_stale_admin_requires_auth(self):
        r = httpx.post(f"{API_BASE}/rides/cleanup-stale?admin=true")
        assert r.status_code == 401


# ============================================================================
# WS5A: Strava Bug Fixes
# ============================================================================

class TestStravaEndpoints:
    """Smoke tests for Strava endpoints."""

    def test_strava_connection_requires_auth(self):
        r = httpx.get(f"{API_BASE}/strava/connection")
        assert r.status_code == 401

    def test_strava_disconnect_requires_auth(self):
        r = httpx.delete(f"{API_BASE}/strava/connection")
        assert r.status_code == 401


# ============================================================================
# WS5B: Rate Limiter — internal, tested via webhook flow
# ============================================================================


# ============================================================================
# WS5C: Webhooks
# ============================================================================

class TestStravaWebhooks:
    """Smoke tests for Strava webhook endpoints."""

    def test_webhook_validation_rejects_bad_token(self):
        """GET /strava/webhook rejects invalid verify token."""
        r = httpx.get(
            f"{API_BASE}/strava/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "test_challenge_123",
            },
        )
        assert r.status_code == 403

    def test_webhook_validation_rejects_missing_params(self):
        """GET /strava/webhook rejects missing params."""
        r = httpx.get(f"{API_BASE}/strava/webhook")
        assert r.status_code in (400, 422)

    def test_webhook_event_rejects_bad_subscription(self):
        """POST /strava/webhook rejects unknown subscription."""
        r = httpx.post(
            f"{API_BASE}/strava/webhook",
            json={
                "aspect_type": "create",
                "event_time": 1234567890,
                "object_id": 999999,
                "object_type": "activity",
                "owner_id": 999999,
                "subscription_id": 0,
                "updates": {},
            },
        )
        # Should either reject or accept (200 to not anger Strava)
        assert r.status_code in (200, 400, 403)


# ============================================================================
# WS5D: Backfill
# ============================================================================

class TestStravaBackfill:
    """Smoke tests for Strava backfill endpoints."""

    def test_backfill_status_requires_auth(self):
        r = httpx.get(f"{API_BASE}/strava/backfill/status")
        assert r.status_code == 401

    def test_admin_subscription_requires_auth(self):
        r = httpx.get(f"{API_BASE}/admin/strava/subscription")
        assert r.status_code == 401


# ============================================================================
# Health baseline
# ============================================================================

class TestHealth:
    """Baseline health checks."""

    def test_api_health(self):
        r = httpx.get(f"{API_BASE}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_openapi_docs_load(self):
        r = httpx.get(f"{API_BASE}/docs")
        assert r.status_code == 200
