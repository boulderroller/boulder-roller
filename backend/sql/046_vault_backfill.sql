-- Migration: 046_vault_backfill.sql
-- Description: Add backfill tracking to indexed_vaults for historical ride matching
-- Date: 2025-01-26
--
-- When a new vault is created/indexed, the leaderboard starts EMPTY even though
-- many users may have already ridden that climb. This migration adds tracking
-- fields to support backfilling historical rides into new vaults.

-- =============================================================================
-- BACKFILL TRACKING COLUMNS
-- =============================================================================

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS backfill_status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS backfill_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS backfill_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS backfill_completions_found INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS backfill_error TEXT;

-- Index for finding vaults needing backfill
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_backfill_status
ON indexed_vaults(backfill_status)
WHERE backfill_status IN ('pending', 'in_progress');

-- =============================================================================
-- ADD SIGNATURE_HEX TO PATTERNS_CLIMB IF NOT EXISTS
-- Required for matching climbs to vaults
-- =============================================================================

ALTER TABLE patterns_climb
    ADD COLUMN IF NOT EXISTS signature_hex TEXT;

-- Index for signature matching during backfill
CREATE INDEX IF NOT EXISTS idx_patterns_climb_signature
ON patterns_climb(signature_hex)
WHERE signature_hex IS NOT NULL;

-- =============================================================================
-- BACKFILL QUEUE TABLE
-- Track individual backfill jobs for retry/monitoring
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id BIGINT NOT NULL REFERENCES indexed_vaults(id),
    vault_signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued, processing, completed, failed
    priority INTEGER NOT NULL DEFAULT 0,     -- Higher = process first

    -- Progress tracking
    total_candidates INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    matched_count INTEGER DEFAULT 0,
    leaderboard_updates INTEGER DEFAULT 0,

    -- Error handling
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Ensure one job per vault
    UNIQUE (vault_id)
);

CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status
ON vault_backfill_jobs(status, priority DESC, created_at)
WHERE status IN ('queued', 'processing');

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to queue a backfill job (idempotent)
CREATE OR REPLACE FUNCTION queue_vault_backfill(
    p_vault_id BIGINT,
    p_vault_signature TEXT,
    p_priority INTEGER DEFAULT 0
) RETURNS UUID AS $$
DECLARE
    job_id UUID;
BEGIN
    -- Insert new job or return existing
    INSERT INTO vault_backfill_jobs (vault_id, vault_signature, priority)
    VALUES (p_vault_id, p_vault_signature, p_priority)
    ON CONFLICT (vault_id) DO UPDATE SET
        priority = GREATEST(vault_backfill_jobs.priority, p_priority),
        -- Re-queue failed jobs
        status = CASE
            WHEN vault_backfill_jobs.status = 'failed'
                 AND vault_backfill_jobs.retry_count < vault_backfill_jobs.max_retries
            THEN 'queued'
            ELSE vault_backfill_jobs.status
        END
    RETURNING id INTO job_id;

    -- Mark vault as pending backfill
    UPDATE indexed_vaults
    SET backfill_status = 'pending'
    WHERE id = p_vault_id AND backfill_status IS NULL;

    RETURN job_id;
END;
$$ LANGUAGE plpgsql;

-- Function to mark job as started
CREATE OR REPLACE FUNCTION start_backfill_job(
    p_job_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_vault_id BIGINT;
BEGIN
    UPDATE vault_backfill_jobs
    SET status = 'processing',
        started_at = now(),
        retry_count = retry_count + 1
    WHERE id = p_job_id AND status IN ('queued', 'failed')
    RETURNING vault_id INTO v_vault_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Update vault status
    UPDATE indexed_vaults
    SET backfill_status = 'in_progress',
        backfill_started_at = now(),
        backfill_error = NULL
    WHERE id = v_vault_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to mark job as completed
CREATE OR REPLACE FUNCTION complete_backfill_job(
    p_job_id UUID,
    p_matched_count INTEGER,
    p_leaderboard_updates INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_vault_id BIGINT;
BEGIN
    UPDATE vault_backfill_jobs
    SET status = 'completed',
        completed_at = now(),
        matched_count = p_matched_count,
        leaderboard_updates = p_leaderboard_updates
    WHERE id = p_job_id
    RETURNING vault_id INTO v_vault_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Update vault status
    UPDATE indexed_vaults
    SET backfill_status = 'completed',
        backfill_completed_at = now(),
        backfill_completions_found = p_matched_count
    WHERE id = v_vault_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to mark job as failed
CREATE OR REPLACE FUNCTION fail_backfill_job(
    p_job_id UUID,
    p_error TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_vault_id BIGINT;
    v_retry_count INTEGER;
    v_max_retries INTEGER;
BEGIN
    SELECT vault_id, retry_count, max_retries
    INTO v_vault_id, v_retry_count, v_max_retries
    FROM vault_backfill_jobs
    WHERE id = p_job_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Update job status
    UPDATE vault_backfill_jobs
    SET status = CASE
            WHEN v_retry_count >= v_max_retries THEN 'failed'
            ELSE 'queued'  -- Will retry
        END,
        error_message = p_error
    WHERE id = p_job_id;

    -- Update vault status
    UPDATE indexed_vaults
    SET backfill_status = CASE
            WHEN v_retry_count >= v_max_retries THEN 'failed'
            ELSE 'pending'
        END,
        backfill_error = p_error
    WHERE id = v_vault_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON COLUMN indexed_vaults.backfill_status IS
'Backfill status: pending, in_progress, completed, failed';

COMMENT ON COLUMN indexed_vaults.backfill_completions_found IS
'Number of historical completions found during backfill';

COMMENT ON TABLE vault_backfill_jobs IS
'Queue of vault backfill jobs with progress tracking';

COMMENT ON FUNCTION queue_vault_backfill IS
'Queue a vault for historical ride backfill (idempotent)';
