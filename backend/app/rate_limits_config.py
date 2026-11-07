from dataclasses import dataclass
from typing import Dict
import os


@dataclass
class RateLimitConfig:
    """Rate limit configuration per endpoint category."""

    requests_per_minute: int
    requests_per_hour: int
    burst_limit: int  # Max requests in 1 second


RATE_LIMIT_MULTIPLIER = float(os.getenv("RATE_LIMIT_MULTIPLIER", "1.0"))

# Default limits by endpoint category
RATE_LIMITS: Dict[str, RateLimitConfig] = {
    # Owner-signed Stage 1 prepare/submit share one budget across all actions.
    "stage1_actions": RateLimitConfig(10, 100, 3),
    # Proof discovery can fan out to chain reads, even without signing.
    "stage1_claims": RateLimitConfig(12, 120, 2),
    # Auth endpoints (prevent brute force)
    "auth": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=60,
        burst_limit=3,
    ),
    # Token operations (prevent spam)
    "token_mint": RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=30,
        burst_limit=2,
    ),
    # Staking operations (prevent manipulation)
    "staking": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=100,
        burst_limit=3,
    ),
    # Vault creation (expensive writes, but should not share budget with staking)
    "vault_creation": RateLimitConfig(
        requests_per_minute=12,
        requests_per_hour=60,
        burst_limit=4,
    ),
    # Ride uploads (prevent abuse)
    "ride_upload": RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=50,
        burst_limit=2,
    ),
    # Public landing-page signup.
    "waitlist": RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=30,
        burst_limit=2,
    ),
    # Public search fans out across rider, ride, and climb tables.
    "search": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=300,
        burst_limit=5,
    ),
    # Authenticated place search is provider-bound and deliberately sparse.
    "geocoding": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=60,
        burst_limit=1,
    ),
    # Username availability checks are public and enumeration-sensitive.
    "username_check": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=80,
        burst_limit=3,
    ),
    # Analytics endpoints (expensive aggregates)
    "analytics": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=300,
        burst_limit=6,
    ),
    # Leaderboards (frequent reads)
    "leaderboard": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        burst_limit=10,
    ),
    # General API (normal usage)
    "general": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        burst_limit=10,
    ),
    # Client telemetry/RUM batches (high volume, low risk)
    "telemetry": RateLimitConfig(
        requests_per_minute=120,
        requests_per_hour=5000,
        burst_limit=20,
    ),
    # Mobile crash-diagnostic ingest + push device registration
    # (boulderroller-v2-k7387): rare, bursty on app foreground, size-capped
    # in the route — keep the budget tight.
    "mobile_diagnostics": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=120,
        burst_limit=3,
    ),
    # Social actions (prevent spam)
    "social": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=500,
        burst_limit=5,
    ),
    # Social report writes are low-volume safety actions.
    "social_report": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=80,
        burst_limit=3,
    ),
    # Strava integration (OAuth + imports)
    "strava": RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=200,
        burst_limit=4,
    ),
}
