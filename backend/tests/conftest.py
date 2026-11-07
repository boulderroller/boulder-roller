"""Pytest configuration for backend tests."""
import os

import pytest

# Set test environment before importing app modules
# This enables signature bypass for testing
os.environ["ENVIRONMENT"] = "test"
os.environ["AUTH_SIGNATURE_BYPASS"] = "true"
# Raise rate limits for testing (no Redis available in CI)
os.environ["RATE_LIMIT_MULTIPLIER"] = "100"
# NATS-backed rate limiting should fail fast to the in-memory fallback in tests.
os.environ["NATS_ENABLED"] = "false"
# Ensure Privy auth path is enabled deterministically in tests.
os.environ.setdefault("PRIVY_APP_ID", "test-privy-app-id")
os.environ.setdefault("PRIVY_VERIFICATION_KEY", "test-privy-verification-key")

# Clear any cached settings so they reload with test config
from app.config import get_environment, load_auth_settings, load_privy_settings
get_environment.cache_clear()
load_auth_settings.cache_clear()
load_privy_settings.cache_clear()

from app.middleware.rate_limiter import rate_limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear in-memory rate limiter state between tests so the fallback doesn't bleed across tests."""
    get_environment.cache_clear()
    load_auth_settings.cache_clear()
    load_privy_settings.cache_clear()
    rate_limiter.reset_fallback()
    yield
    get_environment.cache_clear()
    load_auth_settings.cache_clear()
    load_privy_settings.cache_clear()
    rate_limiter.reset_fallback()
