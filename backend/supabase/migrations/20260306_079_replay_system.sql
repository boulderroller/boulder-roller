-- =============================================================================
-- 079: Replay System Tables
--
-- Implements A5's Deliverables 3 and 4 (Replay Model + Structured Diffing).
-- Enables mass reprocessing of rides through staging tables, scorecard
-- generation, and structured diffing for algorithm upgrade evaluation.
--
-- Creates:
--   1. replay_batches: Tracks mass reprocessing runs
--   2. replay_ride_results: Per-ride staging results (not production)
--   3. ride_diffs: Structured comparison between processing runs
--
-- See: output/A5_VERIFICATION_DATA_PLATFORM_DESIGN.md, Sections 4-5
-- =============================================================================

-- =============================================================================
-- 1. replay_batches: Tracks mass reprocessing runs
-- =============================================================================

CREATE TABLE IF NOT EXISTS replay_batches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope           TEXT NOT NULL,       -- 'ride', 'user', 'epoch', 'mass'
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, promoted, rejected

    -- Version context
    from_version_id INTEGER REFERENCES pipeline_versions(id),  -- version that produced original
    to_version_id   INTEGER REFERENCES pipeline_versions(id),  -- version used for replay

    -- Scope filters
    ride_ids        TEXT[],              -- for scope='ride' or 'mass'
    wallet          TEXT,                -- for scope='user'
    epoch_id        INTEGER,             -- for scope='epoch'

    -- Progress
    total_rides     INTEGER DEFAULT 0,
    completed_rides INTEGER DEFAULT 0,
    failed_rides    INTEGER DEFAULT 0,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    promoted_at     TIMESTAMPTZ,         -- when staging results were promoted to production

    -- Review
    scorecard       JSONB,               -- summary statistics for human review
    reviewed_by     TEXT,                 -- wallet of reviewer
    review_notes    TEXT,

    -- Dry run mode
    dry_run         BOOLEAN NOT NULL DEFAULT false
);

COMMENT ON TABLE replay_batches IS
    'Tracks mass reprocessing runs. Each batch replays rides through a target '
    'pipeline version, storing results in staging tables for review before promotion.';


-- =============================================================================
-- 2. replay_ride_results: Per-ride staging results
-- =============================================================================

CREATE TABLE IF NOT EXISTS replay_ride_results (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        UUID NOT NULL REFERENCES replay_batches(id),
    ride_id         TEXT NOT NULL,

    -- Status
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, completed, failed, promoted
    error           TEXT,

    -- Replayed outputs (staging, not yet promoted)
    metrics         JSONB,               -- TSS, NP, IF, calories, etc.
    climbs          JSONB,               -- Array of detected climbs
    vault_matches   JSONB,               -- Array of vault match results
    economic_delta  JSONB,               -- Points/CAL difference from original

    -- Timing
    processed_at    TIMESTAMPTZ,
    duration_ms     INTEGER,

    UNIQUE(batch_id, ride_id)
);

CREATE INDEX IF NOT EXISTS idx_replay_results_batch ON replay_ride_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_replay_results_status ON replay_ride_results(status) WHERE status = 'pending';

COMMENT ON TABLE replay_ride_results IS
    'Per-ride staging results from replay batches. Results are written here '
    'during replay and only promoted to production tables after human review.';


-- =============================================================================
-- 3. ride_diffs: Structured comparison between processing runs
-- =============================================================================

CREATE TABLE IF NOT EXISTS ride_diffs (
    id              BIGSERIAL PRIMARY KEY,
    ride_id         TEXT NOT NULL,
    batch_id        UUID REFERENCES replay_batches(id),

    -- Versions compared
    old_version_id  INTEGER REFERENCES pipeline_versions(id),
    new_version_id  INTEGER REFERENCES pipeline_versions(id),

    -- Structured diff
    diff            JSONB NOT NULL,      -- Structured diff (metrics, climbs, matches, economics)
    explanation     TEXT,                 -- Plain-English narrative

    -- Significance flags (for fast filtering)
    has_metric_changes  BOOLEAN DEFAULT false,
    has_climb_changes   BOOLEAN DEFAULT false,
    has_match_changes   BOOLEAN DEFAULT false,
    has_economic_changes BOOLEAN DEFAULT false,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ride_diffs_ride ON ride_diffs(ride_id);
CREATE INDEX IF NOT EXISTS idx_ride_diffs_batch ON ride_diffs(batch_id) WHERE batch_id IS NOT NULL;

COMMENT ON TABLE ride_diffs IS
    'Structured diffs produced when a ride is replayed through a different pipeline version. '
    'Used for algorithm upgrade evaluation and dispute resolution.';


-- =============================================================================
-- 4. Helper function: atomically increment batch progress counters
-- =============================================================================

CREATE OR REPLACE FUNCTION increment_replay_progress(
    p_batch_id UUID,
    p_is_success BOOLEAN
) RETURNS VOID AS $$
BEGIN
    IF p_is_success THEN
        UPDATE replay_batches
        SET completed_rides = completed_rides + 1
        WHERE id = p_batch_id;
    ELSE
        UPDATE replay_batches
        SET failed_rides = failed_rides + 1
        WHERE id = p_batch_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
