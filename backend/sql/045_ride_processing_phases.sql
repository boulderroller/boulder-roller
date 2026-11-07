-- Migration: 045_ride_processing_phases
-- Purpose: Multi-phase ride processing pipeline (Strava-style progressive loading)
--
-- Phase 1: Core Processing (<5 seconds) - Parse, metrics, streams, GPS
-- Phase 2: Enrichment (30-60 seconds) - Tiles, patterns, vaults, leaderboards
-- Phase 3: Rewards (background) - Points/CAL, achievements, on-chain operations
--
-- Status progression: pending -> processing -> metrics_ready -> enriched -> completed
-- Each phase can fail independently without blocking earlier phases.

-- ============================================================================
-- Add phase completion timestamps
-- ============================================================================

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS phase1_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS phase2_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS phase3_completed_at TIMESTAMPTZ;

-- ============================================================================
-- Add phase-specific error tracking
-- ============================================================================

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS phase1_error TEXT,
    ADD COLUMN IF NOT EXISTS phase2_error TEXT,
    ADD COLUMN IF NOT EXISTS phase3_error TEXT;

-- ============================================================================
-- Add processing timing for monitoring
-- ============================================================================

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS phase1_duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS phase2_duration_ms INTEGER,
    ADD COLUMN IF NOT EXISTS phase3_duration_ms INTEGER;

-- ============================================================================
-- Comment on new status values
-- ============================================================================

COMMENT ON COLUMN rides.processing_status IS 'Processing status: pending, processing, metrics_ready, enriched, completed, failed';

COMMENT ON COLUMN rides.phase1_completed_at IS 'When Phase 1 (parse, metrics, streams, GPS) completed';
COMMENT ON COLUMN rides.phase2_completed_at IS 'When Phase 2 (tiles, patterns, vaults, leaderboards) completed';
COMMENT ON COLUMN rides.phase3_completed_at IS 'When Phase 3 (points, achievements, on-chain) completed';

COMMENT ON COLUMN rides.phase1_error IS 'Error message if Phase 1 failed';
COMMENT ON COLUMN rides.phase2_error IS 'Error message if Phase 2 failed';
COMMENT ON COLUMN rides.phase3_error IS 'Error message if Phase 3 failed';

COMMENT ON COLUMN rides.phase1_duration_ms IS 'Phase 1 processing duration in milliseconds';
COMMENT ON COLUMN rides.phase2_duration_ms IS 'Phase 2 processing duration in milliseconds';
COMMENT ON COLUMN rides.phase3_duration_ms IS 'Phase 3 processing duration in milliseconds';

-- ============================================================================
-- Index for finding rides by processing status
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_rides_processing_status ON rides(processing_status);
CREATE INDEX IF NOT EXISTS idx_rides_user_processing_status ON rides(user_id, processing_status);

-- ============================================================================
-- Function to update phase status atomically
-- ============================================================================

CREATE OR REPLACE FUNCTION update_ride_phase_status(
    p_ride_id UUID,
    p_phase INTEGER,  -- 1, 2, or 3
    p_success BOOLEAN,
    p_error_message TEXT DEFAULT NULL,
    p_duration_ms INTEGER DEFAULT NULL
)
RETURNS VOID AS $$
DECLARE
    v_new_status TEXT;
BEGIN
    CASE p_phase
        WHEN 1 THEN
            IF p_success THEN
                UPDATE rides SET
                    processing_status = 'metrics_ready',
                    phase1_completed_at = NOW(),
                    phase1_duration_ms = p_duration_ms,
                    phase1_error = NULL
                WHERE id = p_ride_id;
            ELSE
                UPDATE rides SET
                    processing_status = 'failed',
                    phase1_error = p_error_message,
                    error_message = p_error_message
                WHERE id = p_ride_id;
            END IF;

        WHEN 2 THEN
            IF p_success THEN
                UPDATE rides SET
                    processing_status = 'enriched',
                    phase2_completed_at = NOW(),
                    phase2_duration_ms = p_duration_ms,
                    phase2_error = NULL
                WHERE id = p_ride_id;
            ELSE
                -- Phase 2 failure doesn't change overall status from metrics_ready
                -- Users can still see their ride with metrics
                UPDATE rides SET
                    phase2_error = p_error_message,
                    phase2_duration_ms = p_duration_ms
                WHERE id = p_ride_id;
            END IF;

        WHEN 3 THEN
            IF p_success THEN
                UPDATE rides SET
                    processing_status = 'completed',
                    phase3_completed_at = NOW(),
                    phase3_duration_ms = p_duration_ms,
                    phase3_error = NULL
                WHERE id = p_ride_id;
            ELSE
                -- Phase 3 failure doesn't change overall status from enriched
                -- Users can still see patterns and leaderboards
                UPDATE rides SET
                    phase3_error = p_error_message,
                    phase3_duration_ms = p_duration_ms
                WHERE id = p_ride_id;
            END IF;
    END CASE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_ride_phase_status IS 'Atomically update ride processing phase status';

-- ============================================================================
-- Function to get processing progress summary
-- ============================================================================

CREATE OR REPLACE FUNCTION get_ride_processing_progress(p_ride_id UUID)
RETURNS TABLE(
    ride_id UUID,
    status TEXT,
    phase1_status TEXT,
    phase2_status TEXT,
    phase3_status TEXT,
    total_duration_ms INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.id AS ride_id,
        r.processing_status AS status,
        CASE
            WHEN r.phase1_completed_at IS NOT NULL THEN 'completed'
            WHEN r.phase1_error IS NOT NULL THEN 'failed'
            WHEN r.processing_status = 'processing' THEN 'in_progress'
            ELSE 'pending'
        END AS phase1_status,
        CASE
            WHEN r.phase2_completed_at IS NOT NULL THEN 'completed'
            WHEN r.phase2_error IS NOT NULL THEN 'failed'
            WHEN r.phase1_completed_at IS NOT NULL AND r.phase2_completed_at IS NULL THEN 'in_progress'
            ELSE 'pending'
        END AS phase2_status,
        CASE
            WHEN r.phase3_completed_at IS NOT NULL THEN 'completed'
            WHEN r.phase3_error IS NOT NULL THEN 'failed'
            WHEN r.phase2_completed_at IS NOT NULL AND r.phase3_completed_at IS NULL THEN 'in_progress'
            ELSE 'pending'
        END AS phase3_status,
        COALESCE(r.phase1_duration_ms, 0) + COALESCE(r.phase2_duration_ms, 0) + COALESCE(r.phase3_duration_ms, 0) AS total_duration_ms
    FROM rides r
    WHERE r.id = p_ride_id;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_ride_processing_progress IS 'Get detailed processing progress for a ride';
