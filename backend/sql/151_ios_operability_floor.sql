-- 151: iOS operability floor — crash ingest + push machinery to the key
-- boundary (boulderroller-v2-k7387; iOS halves under odmi6.8 / odmi6.14).
--
-- Three tables:
--   * ios_diagnostics        — MetricKit diagnostic envelopes POSTed by the
--                              app for later offline symbolication against
--                              archived dSYMs (self-hosted, $0 — no SaaS).
--                              Payload is Apple's diagnostic JSON: call
--                              stacks and device/OS metadata only; no
--                              location, no ride payloads.
--   * mobile_push_devices    — one row per app install (device_id), holding
--                              the current APNs token. Replaceable by
--                              re-registration; deleted on sign-out.
--   * mobile_push_deliveries — exactly-once ledger for the send worker: one
--                              row per notification it has handled, in
--                              dry_run or real mode. UNIQUE(notification_id)
--                              is the idempotency guard.

CREATE TABLE IF NOT EXISTS ios_diagnostics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet TEXT NOT NULL,
    device_id TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    diagnostic_type TEXT NOT NULL,
    captured_at TIMESTAMPTZ,
    app_version TEXT,
    build_number TEXT,
    os_version TEXT,
    device_model TEXT,
    payload JSONB NOT NULL,
    payload_bytes INTEGER NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ios_diagnostics_received
    ON ios_diagnostics(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_ios_diagnostics_type
    ON ios_diagnostics(diagnostic_type, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_ios_diagnostics_build
    ON ios_diagnostics(build_number, received_at DESC);

CREATE TABLE IF NOT EXISTS mobile_push_devices (
    device_id TEXT PRIMARY KEY,
    wallet TEXT NOT NULL,
    apns_token TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('sandbox', 'production')),
    app_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mobile_push_devices_wallet
    ON mobile_push_devices(wallet);

CREATE TABLE IF NOT EXISTS mobile_push_deliveries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notification_id UUID NOT NULL UNIQUE,
    wallet TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('settlement', 'displacement')),
    mode TEXT NOT NULL CHECK (mode IN ('dry_run', 'sent', 'no_devices', 'failed')),
    device_count INTEGER NOT NULL DEFAULT 0,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mobile_push_deliveries_created
    ON mobile_push_deliveries(created_at DESC);
