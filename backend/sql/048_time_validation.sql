-- Migration: 048_time_validation.sql
-- Description: Add time validation for leaderboard entries
-- Date: 2025-01-26
--
-- Problem: Times are accepted without validation - could submit impossibly fast
-- times (1 second) or unreasonably slow times.
--
-- Solution: Add validation bounds to indexed_vaults and validate times before
-- accepting leaderboard entries.

-- =============================================================================
-- ADD VALIDATION COLUMNS TO INDEXED_VAULTS
-- =============================================================================

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS min_valid_time_s INTEGER,
    ADD COLUMN IF NOT EXISTS max_valid_time_s INTEGER,
    ADD COLUMN IF NOT EXISTS validation_enabled BOOLEAN DEFAULT true;

COMMENT ON COLUMN indexed_vaults.min_valid_time_s IS 'Minimum reasonable completion time in seconds';
COMMENT ON COLUMN indexed_vaults.max_valid_time_s IS 'Maximum reasonable completion time in seconds';
COMMENT ON COLUMN indexed_vaults.validation_enabled IS 'Whether time validation is enforced for this vault';

-- =============================================================================
-- ADD VALIDATION COLUMN TO VAULT_COMPLETIONS
-- =============================================================================

ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS validated BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS validation_override BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS validation_notes TEXT;

COMMENT ON COLUMN vault_completions.validated IS 'Whether the time passed validation checks';
COMMENT ON COLUMN vault_completions.validation_override IS 'Admin override for exceptional cases';
COMMENT ON COLUMN vault_completions.validation_notes IS 'Notes about validation failure or override reason';

-- =============================================================================
-- FUNCTION: CALCULATE REASONABLE TIME BOUNDS
-- =============================================================================

CREATE OR REPLACE FUNCTION calculate_vault_time_bounds(
    p_distance_m INTEGER,
    p_vert_m DOUBLE PRECISION
) RETURNS TABLE(min_time_s INTEGER, max_time_s INTEGER) AS $$
DECLARE
    -- Min time: fastest reasonable completion
    -- - Distance-based: max 40 km/h (11.1 m/s) average for flat/descent
    -- - VAM-based: max 2000 VAM (elite climber) for vertical
    distance_min_time INTEGER;
    vam_min_time INTEGER;

    -- Max time: slowest reasonable completion
    -- - Distance-based: min 5 km/h (1.4 m/s) average walking pace
    -- - 6 hours absolute max for any climb
    distance_max_time INTEGER;
BEGIN
    -- Calculate distance-based minimum (40 km/h = 11.1 m/s)
    distance_min_time := GREATEST(30, (p_distance_m / 11.1)::INTEGER);

    -- Calculate VAM-based minimum (2000 VAM = 2000m/hour)
    -- VAM = vert_m / (time_min / 3600), so time_min = vert_m * 3600 / VAM
    IF p_vert_m > 0 THEN
        vam_min_time := CEIL(p_vert_m * 3600 / 2000)::INTEGER;
    ELSE
        vam_min_time := 0;
    END IF;

    -- Calculate distance-based maximum (5 km/h = 1.4 m/s walking pace)
    distance_max_time := (p_distance_m / 1.4)::INTEGER;

    RETURN QUERY SELECT
        -- Min: take the slower (larger) of distance or VAM-based calculation
        -- This ensures steep short climbs get appropriate minimums
        GREATEST(30, distance_min_time, vam_min_time) AS min_time_s,

        -- Max: 6 hours (21600s) or distance-based, whichever is less
        -- Also ensure max is at least 2x the minimum for short climbs
        GREATEST(
            GREATEST(30, distance_min_time, vam_min_time) * 2,
            LEAST(21600, distance_max_time)
        ) AS max_time_s;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_vault_time_bounds IS
'Calculate reasonable time bounds for vault completions based on distance and vertical gain.
Uses 40 km/h max speed, 2000 VAM max climbing rate, 5 km/h min speed, 6hr max duration.';

-- =============================================================================
-- UPDATE EXISTING VAULTS WITH CALCULATED BOUNDS
-- =============================================================================

UPDATE indexed_vaults v
SET (min_valid_time_s, max_valid_time_s) = (
    SELECT min_time_s, max_time_s
    FROM calculate_vault_time_bounds(v.distance_m, v.vert_m)
)
WHERE min_valid_time_s IS NULL;

-- =============================================================================
-- UPDATE UPDATE_VAULT_LEADERBOARD FUNCTION WITH VALIDATION
-- =============================================================================

CREATE OR REPLACE FUNCTION update_vault_leaderboard(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_completion_id UUID DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_min_time INTEGER;
    v_max_time INTEGER;
    v_validation_enabled BOOLEAN;
    new_rank INTEGER := NULL;
    current RECORD;
    bump_wallet TEXT;
BEGIN
    -- Get validation bounds from indexed_vaults
    SELECT min_valid_time_s, max_valid_time_s, validation_enabled
    INTO v_min_time, v_max_time, v_validation_enabled
    FROM indexed_vaults
    WHERE signature_hex = p_vault_signature;

    -- Validate time if enabled and bounds are set
    IF v_validation_enabled IS NOT FALSE AND v_min_time IS NOT NULL THEN
        IF p_time_seconds < v_min_time THEN
            RAISE EXCEPTION 'Time too fast: % seconds is below minimum % seconds for this vault',
                p_time_seconds, v_min_time
            USING ERRCODE = 'check_violation',
                  HINT = 'The submitted time appears impossibly fast for this climb.';
        END IF;

        IF p_time_seconds > v_max_time THEN
            RAISE EXCEPTION 'Time too slow: % seconds exceeds maximum % seconds for this vault',
                p_time_seconds, v_max_time
            USING ERRCODE = 'check_violation',
                  HINT = 'The submitted time exceeds the maximum allowed for this climb.';
        END IF;
    END IF;

    -- Check if this time qualifies for top 10
    SELECT COUNT(*) + 1 INTO new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND best_time_seconds < p_time_seconds;

    -- If not in top 10, check if we beat existing entry
    IF new_rank > 10 THEN
        -- Check if user has existing entry with worse time
        SELECT rank INTO new_rank
        FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND wallet = p_wallet AND best_time_seconds > p_time_seconds;

        IF new_rank IS NULL THEN
            RETURN NULL; -- No leaderboard change
        END IF;
    END IF;

    -- Remove user's existing entry if they're moving up
    DELETE FROM vault_leaderboards WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Bump everyone below new rank down by 1
    UPDATE vault_leaderboards SET rank = rank + 1
    WHERE vault_signature = p_vault_signature AND rank >= new_rank;

    -- Remove anyone pushed past rank 10
    DELETE FROM vault_leaderboards WHERE vault_signature = p_vault_signature AND rank > 10;

    -- Insert new entry
    INSERT INTO vault_leaderboards (vault_signature, rank, wallet, best_time_seconds, avg_power_w, completion_id, achieved_at)
    VALUES (p_vault_signature, new_rank, p_wallet, p_time_seconds, p_avg_power_w, p_completion_id, now());

    RETURN new_rank;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_leaderboard IS
'Update leaderboard after a completion, validates time against vault bounds.
Returns new rank or NULL if not in top 10. Raises exception if time is invalid.';

-- =============================================================================
-- FUNCTION: VALIDATE CLIMB TIME (callable separately)
-- =============================================================================

CREATE OR REPLACE FUNCTION validate_climb_time(
    p_vault_signature TEXT,
    p_time_seconds INTEGER
) RETURNS TABLE(
    is_valid BOOLEAN,
    error_message TEXT,
    min_time_s INTEGER,
    max_time_s INTEGER
) AS $$
DECLARE
    v_min_time INTEGER;
    v_max_time INTEGER;
    v_validation_enabled BOOLEAN;
BEGIN
    -- Get validation bounds
    SELECT iv.min_valid_time_s, iv.max_valid_time_s, iv.validation_enabled
    INTO v_min_time, v_max_time, v_validation_enabled
    FROM indexed_vaults iv
    WHERE iv.signature_hex = p_vault_signature;

    -- If vault not found or validation disabled, return valid
    IF v_validation_enabled IS FALSE OR v_min_time IS NULL THEN
        RETURN QUERY SELECT true, NULL::TEXT, v_min_time, v_max_time;
        RETURN;
    END IF;

    -- Check bounds
    IF p_time_seconds < v_min_time THEN
        RETURN QUERY SELECT
            false,
            format('Time %s seconds is below minimum %s seconds', p_time_seconds, v_min_time),
            v_min_time,
            v_max_time;
        RETURN;
    END IF;

    IF p_time_seconds > v_max_time THEN
        RETURN QUERY SELECT
            false,
            format('Time %s seconds exceeds maximum %s seconds', p_time_seconds, v_max_time),
            v_min_time,
            v_max_time;
        RETURN;
    END IF;

    -- Time is valid
    RETURN QUERY SELECT true, NULL::TEXT, v_min_time, v_max_time;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION validate_climb_time IS
'Validate a climb time against vault bounds. Returns is_valid, error_message, and bounds.
Use this for pre-validation before calling update_vault_leaderboard.';

-- =============================================================================
-- FUNCTION: UPDATE VAULT TIME BOUNDS
-- =============================================================================

CREATE OR REPLACE FUNCTION update_vault_time_bounds(
    p_signature_hex TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_distance_m INTEGER;
    v_vert_m DOUBLE PRECISION;
    v_min INTEGER;
    v_max INTEGER;
BEGIN
    -- Get vault metrics
    SELECT distance_m, vert_m INTO v_distance_m, v_vert_m
    FROM indexed_vaults
    WHERE signature_hex = p_signature_hex;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Calculate bounds
    SELECT min_time_s, max_time_s INTO v_min, v_max
    FROM calculate_vault_time_bounds(v_distance_m, v_vert_m);

    -- Update vault
    UPDATE indexed_vaults
    SET min_valid_time_s = v_min, max_valid_time_s = v_max
    WHERE signature_hex = p_signature_hex;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_time_bounds IS
'Recalculate and update time bounds for a specific vault.
Call after vault metrics are modified.';

-- =============================================================================
-- TRIGGER: AUTO-CALCULATE BOUNDS ON VAULT INSERT
-- =============================================================================

CREATE OR REPLACE FUNCTION trg_calculate_vault_time_bounds()
RETURNS TRIGGER AS $$
DECLARE
    v_min INTEGER;
    v_max INTEGER;
BEGIN
    -- Calculate bounds for new vault
    SELECT min_time_s, max_time_s INTO v_min, v_max
    FROM calculate_vault_time_bounds(NEW.distance_m, NEW.vert_m);

    NEW.min_valid_time_s := v_min;
    NEW.max_valid_time_s := v_max;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_indexed_vaults_time_bounds ON indexed_vaults;

CREATE TRIGGER trg_indexed_vaults_time_bounds
    BEFORE INSERT OR UPDATE OF distance_m, vert_m ON indexed_vaults
    FOR EACH ROW
    WHEN (NEW.validation_enabled IS DISTINCT FROM FALSE)
    EXECUTE FUNCTION trg_calculate_vault_time_bounds();

COMMENT ON TRIGGER trg_indexed_vaults_time_bounds ON indexed_vaults IS
'Automatically calculate time bounds when vault distance or vertical gain changes';

-- =============================================================================
-- INDEX FOR VALIDATION LOOKUPS
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_vault_completions_validated
    ON vault_completions(vault_signature, validated)
    WHERE validated = false;

COMMENT ON INDEX idx_vault_completions_validated IS
'Index for finding completions that failed validation';

-- =============================================================================
-- VIEW: INVALID COMPLETIONS FOR REVIEW
-- =============================================================================

CREATE OR REPLACE VIEW v_invalid_completions AS
SELECT
    vc.id,
    vc.vault_signature,
    vc.wallet,
    vc.activity_id,
    vc.time_seconds,
    vc.completed_at,
    vc.validation_notes,
    vc.validation_override,
    iv.name as vault_name,
    iv.min_valid_time_s,
    iv.max_valid_time_s,
    iv.vert_m,
    iv.distance_m
FROM vault_completions vc
JOIN indexed_vaults iv ON iv.signature_hex = vc.vault_signature
WHERE vc.validated = false
ORDER BY vc.completed_at DESC;

COMMENT ON VIEW v_invalid_completions IS
'Completions that failed time validation, for admin review';
