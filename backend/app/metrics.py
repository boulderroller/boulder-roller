"""Shared Prometheus metrics for API and worker processes.

This module uses safe_* helpers to prevent duplicate registration errors
when modules are re-imported (e.g., during pytest collection).
"""

from prometheus_client import Counter, Gauge, Histogram, REGISTRY


def _get_or_create_metric(metric_class, name, description, labelnames=None, **kwargs):
    """Get an existing metric or create a new one.

    Prevents 'Duplicated timeseries in CollectorRegistry' errors when
    modules are imported multiple times (common in pytest).
    """
    # Check if metric already exists in registry
    for collector in list(REGISTRY._names_to_collectors.values()):
        if hasattr(collector, '_name') and collector._name == name:
            return collector

    # Create new metric
    if labelnames:
        return metric_class(name, description, labelnames, **kwargs)
    return metric_class(name, description, **kwargs)


def safe_counter(name, description, labelnames=None):
    """Create a Counter, reusing existing if already registered."""
    return _get_or_create_metric(Counter, name, description, labelnames)


def safe_gauge(name, description, labelnames=None):
    """Create a Gauge, reusing existing if already registered."""
    return _get_or_create_metric(Gauge, name, description, labelnames)


def safe_histogram(name, description, labelnames=None, buckets=None):
    """Create a Histogram, reusing existing if already registered."""
    kwargs = {}
    if buckets:
        kwargs['buckets'] = buckets
    return _get_or_create_metric(Histogram, name, description, labelnames, **kwargs)


# Supabase request metrics (app-level DB calls).
SUPABASE_REQUESTS_IN_FLIGHT = safe_gauge(
    "supabase_requests_in_flight",
    "Supabase requests in flight",
)
SUPABASE_REQUEST_DURATION = safe_histogram(
    "supabase_request_duration_seconds",
    "Supabase request duration in seconds",
    ["operation"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
SUPABASE_REQUEST_ERRORS = safe_counter(
    "supabase_request_errors_total",
    "Supabase request errors",
    ["operation"],
)

# Celery worker metrics.
CELERY_TASK_RUNS = safe_counter(
    "celery_task_runs_total",
    "Celery task runs",
    ["task", "status"],
)
CELERY_TASK_DURATION = safe_histogram(
    "celery_task_duration_seconds",
    "Celery task duration in seconds",
    ["task"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)
CELERY_QUEUE_DEPTH = safe_gauge(
    "celery_queue_depth",
    "Celery queue depth",
    ["queue"],
)

# Ride processing phase metrics.
RIDE_PHASE_RUNS = safe_counter(
    "ride_phase_runs_total",
    "Ride processing phase runs",
    ["phase", "status"],
)
RIDE_PHASE_DURATION = safe_histogram(
    "ride_phase_duration_seconds",
    "Ride processing phase duration in seconds",
    ["phase"],
    buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# Solana RPC metrics.
SOLANA_RPC_CALLS = safe_counter(
    "solana_rpc_calls_total",
    "Solana RPC calls",
    ["method"],
)
SOLANA_RPC_ERRORS = safe_counter(
    "solana_rpc_errors_total",
    "Solana RPC errors",
    ["method"],
)
SOLANA_RPC_LATENCY = safe_histogram(
    "solana_rpc_latency_seconds",
    "Solana RPC latency in seconds",
    ["method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0),
)

# Solana wallet balance monitoring.
SOLANA_PAYER_BALANCE_SOL = safe_gauge(
    "solana_payer_balance_sol",
    "SOL balance of the payer wallet, read at most every 15 minutes on scrape",
)
# 0 until the first successful read, so alert rules can tell an unread gauge
# from an empty wallet.
SOLANA_PAYER_BALANCE_CHECKED = safe_gauge(
    "solana_payer_balance_checked_timestamp_seconds",
    "Unix time of the last successful payer balance read",
)

# Product KPI metrics.
KPI_RIDE_UPLOADS = safe_counter(
    "kpi_ride_uploads_total",
    "Ride uploads",
    ["status"],
)
KPI_RIDE_PROCESSED = safe_counter(
    "kpi_ride_processed_total",
    "Ride processing runs",
    ["status"],
)
KPI_DUNG_MINTED = safe_counter(
    "kpi_dung_minted_total",
    "DUNG minted",
    ["source"],
)
KPI_STAKES = safe_counter(
    "kpi_stakes_total",
    "Stake events",
    ["status"],
)
KPI_UNSTAKES = safe_counter(
    "kpi_unstakes_total",
    "Unstake events",
    ["status"],
)
KPI_LOGINS = safe_counter(
    "kpi_logins_total",
    "Successful logins",
)
KPI_USERS_CREATED = safe_counter(
    "kpi_users_created_total",
    "Users created",
)
KPI_CAL_AIRDROPS = safe_counter(
    "kpi_cal_airdrops_total",
    "CAL airdrops processed",
)

# Auth entry funnel metrics.
AUTH_FUNNEL_EVENTS = safe_counter(
    "auth_funnel_events_total",
    "Auth funnel events by stage/result",
    ["stage", "result"],
)
AUTH_FUNNEL_STAGE_DURATION = safe_histogram(
    "auth_funnel_stage_duration_seconds",
    "Auth funnel stage duration in seconds",
    ["stage"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Frontend RUM/web-vitals metrics.
WEB_VITAL_SAMPLES = safe_counter(
    "web_vital_samples_total",
    "Web vital samples ingested from frontend clients",
    ["metric", "route", "device", "rating"],
)
WEB_VITAL_VALUE_MS = safe_histogram(
    "web_vital_value_ms",
    "Web vital values in milliseconds (non-CLS metrics)",
    ["metric", "route", "device"],
    buckets=(50, 100, 200, 400, 800, 1200, 1800, 2500, 4000, 8000, 12000, 20000),
)
WEB_VITAL_CLS_VALUE = safe_histogram(
    "web_vital_cls_value",
    "Web CLS values",
    ["route", "device"],
    buckets=(0.01, 0.03, 0.05, 0.08, 0.1, 0.15, 0.25, 0.4, 0.6, 1.0),
)

# Strava integration metrics.
STRAVA_API_REQUESTS = safe_counter(
    "strava_api_requests_total",
    "Outbound Strava API requests",
    ["endpoint", "method", "status"],
)
STRAVA_API_REQUEST_DURATION = safe_histogram(
    "strava_api_request_duration_seconds",
    "Outbound Strava API request duration in seconds",
    ["endpoint", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0),
)
STRAVA_RATE_USAGE = safe_gauge(
    "strava_rate_usage",
    "Current Strava API usage by window",
    ["window"],
)
STRAVA_RATE_LIMIT = safe_gauge(
    "strava_rate_limit",
    "Current Strava API rate limit by window",
    ["window"],
)
STRAVA_RATE_BLOCKED = safe_counter(
    "strava_rate_blocked_total",
    "Strava API requests blocked by rate limiter",
    ["priority", "window"],
)
STRAVA_TOKEN_REFRESH = safe_counter(
    "strava_token_refresh_total",
    "Strava token refresh attempts",
    ["status"],
)
STRAVA_WEBHOOK_EVENTS = safe_counter(
    "strava_webhook_events_total",
    "Strava webhook events by object, aspect, and status",
    ["object_type", "aspect_type", "status"],
)
STRAVA_WEBHOOK_IGNORED = safe_counter(
    "strava_webhook_ignored_total",
    "Ignored Strava webhook events",
    ["reason"],
)
STRAVA_SUBSCRIPTION_ACTIVE = safe_gauge(
    "strava_subscription_active",
    "Whether an active Strava webhook subscription is present",
)
STRAVA_CONNECTIONS_ACTIVE = safe_gauge(
    "strava_connections_active",
    "Number of active Strava connections",
)
STRAVA_BACKFILL_CONNECTIONS = safe_gauge(
    "strava_backfill_connections",
    "Active Strava connections by backfill status",
    ["status"],
)
STRAVA_LAST_WEBHOOK_EVENT = safe_gauge(
    "strava_last_webhook_event_timestamp",
    "Unix timestamp of the most recent accepted Strava webhook event",
)


def record_strava_api_request(
    endpoint: str,
    method: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record an outbound Strava API request."""
    status = str(status_code)
    STRAVA_API_REQUESTS.labels(endpoint=endpoint, method=method, status=status).inc()
    STRAVA_API_REQUEST_DURATION.labels(endpoint=endpoint, method=method).observe(duration_seconds)


def set_strava_rate_state(
    usage_15min: int,
    limit_15min: int,
    usage_daily: int,
    limit_daily: int,
) -> None:
    """Publish the current Strava rate state."""
    STRAVA_RATE_USAGE.labels(window="15m").set(usage_15min)
    STRAVA_RATE_USAGE.labels(window="daily").set(usage_daily)
    STRAVA_RATE_LIMIT.labels(window="15m").set(limit_15min)
    STRAVA_RATE_LIMIT.labels(window="daily").set(limit_daily)


def record_strava_rate_blocked(priority: str, window: str) -> None:
    """Count a Strava request blocked by local quota controls."""
    STRAVA_RATE_BLOCKED.labels(priority=priority, window=window).inc()


def record_strava_token_refresh(status: str) -> None:
    """Count a Strava token refresh attempt."""
    STRAVA_TOKEN_REFRESH.labels(status=status).inc()


def record_strava_webhook_event(object_type: str, aspect_type: str, status: str) -> None:
    """Count a Strava webhook event."""
    STRAVA_WEBHOOK_EVENTS.labels(
        object_type=object_type or "unknown",
        aspect_type=aspect_type or "unknown",
        status=status,
    ).inc()


def record_strava_webhook_ignored(reason: str) -> None:
    """Count an ignored Strava webhook event."""
    STRAVA_WEBHOOK_IGNORED.labels(reason=reason).inc()


def set_strava_subscription_active(active: bool) -> None:
    """Publish whether a webhook subscription is active."""
    STRAVA_SUBSCRIPTION_ACTIVE.set(1 if active else 0)


def set_strava_connection_state(active_connections: int, backfill_counts: dict[str, int]) -> None:
    """Publish current Strava connection and backfill counts."""
    STRAVA_CONNECTIONS_ACTIVE.set(active_connections)
    for status, count in backfill_counts.items():
        STRAVA_BACKFILL_CONNECTIONS.labels(status=status).set(count)


def set_strava_last_webhook_event(timestamp_seconds: float) -> None:
    """Publish the most recent accepted Strava webhook timestamp."""
    STRAVA_LAST_WEBHOOK_EVENT.set(timestamp_seconds)


def record_auth_funnel_event(stage: str, result: str) -> None:
    """Count an auth-entry funnel event."""
    AUTH_FUNNEL_EVENTS.labels(stage=stage, result=result).inc()


def observe_auth_funnel_stage(stage: str, duration_seconds: float) -> None:
    """Record auth-entry stage execution duration."""
    AUTH_FUNNEL_STAGE_DURATION.labels(stage=stage).observe(duration_seconds)
