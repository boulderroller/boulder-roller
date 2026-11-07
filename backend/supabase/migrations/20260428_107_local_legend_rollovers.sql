-- Track backend-submitted Local Legend rollover transactions so the settlement
-- scheduler can be idempotent across cron/admin retries.

CREATE TABLE IF NOT EXISTS local_legend_rollovers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id BIGINT NOT NULL,
    vault_signature TEXT NOT NULL,
    term_start_epoch BIGINT NOT NULL,
    term_end_epoch BIGINT NOT NULL,
    previous_holder TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('elected', 'dormant')),
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'failed')),
    winner TEXT,
    winner_completions INTEGER NOT NULL DEFAULT 0,
    runner_up TEXT,
    runner_up_completions INTEGER NOT NULL DEFAULT 0,
    tx_signature TEXT,
    error_message TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vault_id, term_end_epoch)
);

CREATE INDEX IF NOT EXISTS idx_local_legend_rollovers_status
    ON local_legend_rollovers(status, term_end_epoch);

COMMENT ON TABLE local_legend_rollovers IS
    'Audit/idempotency table for backend-submitted Local Legend rollover transactions.';
