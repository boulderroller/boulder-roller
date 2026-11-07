-- Migration: 035_swanny_local_legend.sql
-- Description: Simplify swanny to single rotating "Local Legend" seat per vault
-- Date: 2024-12-26
--
-- Changes from 034:
-- - 3 seats → 1 seat per vault
-- - Lock 1000 DUNG → No lock required
-- - First-come-first-served → Most completions wins
-- - 30-day lock → 2-month rotation (8 epochs)
-- - 10% split 3 ways → 3% to single winner

-- =============================================================================
-- VAULT COMPLETIONS TABLE (tracks completions for Local Legend elections)
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_completions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    wallet TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    time_seconds INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vault_signature, activity_id)
);

CREATE INDEX IF NOT EXISTS idx_vault_completions_vault ON vault_completions(vault_signature);
CREATE INDEX IF NOT EXISTS idx_vault_completions_wallet ON vault_completions(wallet);
CREATE INDEX IF NOT EXISTS idx_vault_completions_time ON vault_completions(completed_at);

COMMENT ON TABLE vault_completions IS 'Tracks each time a wallet completes a vault (used for Local Legend elections)';

-- Function to increment vault completions count on indexed_vaults
CREATE OR REPLACE FUNCTION increment_vault_completions(
    p_signature_hex TEXT
) RETURNS VOID AS $$
BEGIN
    UPDATE indexed_vaults
    SET total_completions = COALESCE(total_completions, 0) + 1
    WHERE signature_hex = p_signature_hex;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- DROP OLD FUNCTIONS (will recreate with new logic)
-- =============================================================================

DROP FUNCTION IF EXISTS claim_swanny_seat(TEXT, TEXT);
DROP FUNCTION IF EXISTS release_swanny_seat(UUID);
DROP FUNCTION IF EXISTS get_vault_swanny_count(TEXT);
DROP FUNCTION IF EXISTS get_vault_swannys(TEXT);

-- =============================================================================
-- MODIFY SWANNY_SEATS TABLE
-- Keep existing data but restructure for Local Legend model
-- =============================================================================

-- Add new columns
ALTER TABLE swanny_seats
    ADD COLUMN IF NOT EXISTS elected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS term_ends_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completion_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS election_period INTEGER;

-- Make old lock columns nullable (no longer required)
ALTER TABLE swanny_seats
    ALTER COLUMN points_locked DROP NOT NULL,
    ALTER COLUMN unlock_at DROP NOT NULL;

-- Set defaults for new columns on existing rows
UPDATE swanny_seats
SET elected_at = locked_at,
    term_ends_at = COALESCE(unlock_at, locked_at + INTERVAL '60 days'),
    election_period = 1
WHERE elected_at IS NULL;

-- Drop old constraints
ALTER TABLE swanny_seats DROP CONSTRAINT IF EXISTS swanny_seats_seat_number_check;
DROP INDEX IF EXISTS idx_swanny_active;

-- Create new constraint: only 1 active seat per vault
CREATE UNIQUE INDEX IF NOT EXISTS idx_swanny_one_per_vault
    ON swanny_seats(vault_signature)
    WHERE is_active = true;

-- Update comments
COMMENT ON TABLE swanny_seats IS 'Single "Local Legend" curator seat per vault - most completions wins';
COMMENT ON COLUMN swanny_seats.seat_number IS 'Deprecated: Always 1 now';
COMMENT ON COLUMN swanny_seats.points_locked IS 'Deprecated: No lock required in Local Legend model';
COMMENT ON COLUMN swanny_seats.elected_at IS 'When this wallet won the election';
COMMENT ON COLUMN swanny_seats.term_ends_at IS '2 months (8 epochs) from election';
COMMENT ON COLUMN swanny_seats.completion_count IS 'Number of completions that won the election';
COMMENT ON COLUMN swanny_seats.election_period IS 'Which 2-month period this election was for';

-- =============================================================================
-- SWANNY ELECTIONS TABLE
-- Track election history and results
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_elections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    election_period INTEGER NOT NULL,
    -- Election window
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    -- Winner
    winner_wallet TEXT,
    winner_completions INTEGER,
    -- Runner-up (for early claim if winner inactive)
    runner_up_wallet TEXT,
    runner_up_completions INTEGER,
    -- Metadata
    total_completions INTEGER NOT NULL DEFAULT 0,
    unique_riders INTEGER NOT NULL DEFAULT 0,
    -- Timestamps
    election_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints
    UNIQUE (vault_signature, election_period)
);

CREATE INDEX IF NOT EXISTS idx_swanny_elections_vault ON swanny_elections(vault_signature);
CREATE INDEX IF NOT EXISTS idx_swanny_elections_winner ON swanny_elections(winner_wallet);
CREATE INDEX IF NOT EXISTS idx_swanny_elections_period ON swanny_elections(election_period DESC);

COMMENT ON TABLE swanny_elections IS 'Historical record of Local Legend elections';
COMMENT ON COLUMN swanny_elections.election_period IS 'Sequential period number (1, 2, 3...)';
COMMENT ON COLUMN swanny_elections.runner_up_wallet IS 'Deprecated (no longer written)';

-- =============================================================================
-- SWANNY INACTIVITY TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_inactivity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seat_id UUID NOT NULL REFERENCES swanny_seats(id),
    -- Pending tasks not completed
    pending_photo_approvals INTEGER NOT NULL DEFAULT 0,
    pending_flag_reviews INTEGER NOT NULL DEFAULT 0,
    -- Inactivity tracking
    last_action_at TIMESTAMPTZ,
    inactive_since TIMESTAMPTZ,
    -- Claim by next-highest completion leader
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swanny_inactivity_seat ON swanny_inactivity(seat_id);
CREATE INDEX IF NOT EXISTS idx_swanny_inactivity_inactive ON swanny_inactivity(inactive_since)
    WHERE inactive_since IS NOT NULL;

COMMENT ON TABLE swanny_inactivity IS 'Track swanny task completion and inactivity';
COMMENT ON COLUMN swanny_inactivity.inactive_since IS 'Set when 2+ weeks without action on pending tasks';

-- =============================================================================
-- UPDATE SWANNY CONFIG
-- =============================================================================

ALTER TABLE swanny_config
    ADD COLUMN IF NOT EXISTS rotation_epochs INTEGER NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS share_bps INTEGER NOT NULL DEFAULT 300,
    ADD COLUMN IF NOT EXISTS inactivity_weeks INTEGER NOT NULL DEFAULT 2;

-- Update config values
UPDATE swanny_config SET
    seats_per_vault = 1,
    lock_amount_dung = 0,
    lock_duration_days = 0,
    rotation_epochs = 8,
    share_bps = 300,
    inactivity_weeks = 2,
    updated_at = now()
WHERE id = 1;

COMMENT ON COLUMN swanny_config.seats_per_vault IS 'Always 1 in Local Legend model';
COMMENT ON COLUMN swanny_config.lock_amount_dung IS 'Deprecated: 0 = no lock required';
COMMENT ON COLUMN swanny_config.rotation_epochs IS '8 epochs = 2 months';
COMMENT ON COLUMN swanny_config.share_bps IS '300 = 3% of distribution';
COMMENT ON COLUMN swanny_config.inactivity_weeks IS 'Weeks without action before seat can be claimed';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get completion counts for a vault over a period
CREATE OR REPLACE FUNCTION get_vault_completion_counts(
    p_vault_signature TEXT,
    p_since TIMESTAMPTZ,
    p_until TIMESTAMPTZ
) RETURNS TABLE (
    wallet TEXT,
    completion_count BIGINT,
    first_completed_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.wallet,
        COUNT(*)::BIGINT as completion_count,
        MIN(vc.completed_at) as first_completed_at
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.completed_at >= p_since
      AND vc.completed_at < p_until
    GROUP BY vc.wallet
    ORDER BY completion_count DESC, first_completed_at ASC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_completion_counts IS 'Get completion counts per wallet for Local Legend election';

-- Run election for a vault
CREATE OR REPLACE FUNCTION elect_swanny(
    p_vault_signature TEXT,
    p_election_period INTEGER DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    config RECORD;
    period_num INTEGER;
    period_start TIMESTAMPTZ;
    period_end TIMESTAMPTZ;
    current_epoch INTEGER;
    period_start_epoch INTEGER;
    period_end_epoch INTEGER;
    -- Epochs run Sunday 12:00 UTC to Sunday 12:00 UTC (per TOKENOMICS_V2.md line 234)
    epoch_anchor BIGINT := 1704020400; -- Sun Dec 31 2023 12:00:00 UTC
    epoch_duration INTEGER := 604800;  -- 7 days in seconds
    winner RECORD;
    election_id UUID;
    seat_id UUID;
    total_comps INTEGER;
    unique_count INTEGER;
BEGIN
    -- Get config
    SELECT * INTO config FROM swanny_config WHERE id = 1;

    -- Determine election period (default to current)
    IF p_election_period IS NULL THEN
        current_epoch := get_current_epoch();
        period_num := (current_epoch / config.rotation_epochs)::INTEGER + 1;
    ELSE
        period_num := p_election_period;
    END IF;

    -- Calculate period window
    period_start_epoch := (period_num - 1) * config.rotation_epochs;
    period_end_epoch := period_start_epoch + config.rotation_epochs;
    period_start := to_timestamp(epoch_anchor + (period_start_epoch * epoch_duration));
    period_end := to_timestamp(epoch_anchor + (period_end_epoch * epoch_duration));

    -- Check if election already run for this period
    IF EXISTS (SELECT 1 FROM swanny_elections WHERE vault_signature = p_vault_signature AND election_period = period_num) THEN
        SELECT id INTO election_id FROM swanny_elections
        WHERE vault_signature = p_vault_signature AND election_period = period_num;
        RETURN election_id;
    END IF;

    -- Get winner (most completions; tie-breaker = earliest completion)
    SELECT wallet, completion_count, first_completed_at INTO winner
    FROM get_vault_completion_counts(p_vault_signature, period_start, period_end)
    LIMIT 1;

    -- Get totals
    SELECT COUNT(*)::INTEGER, COUNT(DISTINCT wallet)::INTEGER
    INTO total_comps, unique_count
    FROM vault_completions
    WHERE vault_signature = p_vault_signature
      AND completed_at >= period_start
      AND completed_at < period_end;

    -- Record election
    INSERT INTO swanny_elections (
        vault_signature, election_period, period_start, period_end,
        winner_wallet, winner_completions,
        total_completions, unique_riders
    ) VALUES (
        p_vault_signature, period_num, period_start, period_end,
        winner.wallet, winner.completion_count,
        total_comps, unique_count
    ) RETURNING id INTO election_id;

    -- Deactivate previous seat if exists
    UPDATE swanny_seats
    SET is_active = false
    WHERE vault_signature = p_vault_signature AND is_active = true;

    -- Create new seat for winner (if there is one)
    IF winner.wallet IS NOT NULL THEN
        INSERT INTO swanny_seats (
            vault_signature, seat_number, wallet,
            points_locked, unlock_at,
            elected_at, term_ends_at, completion_count, election_period,
            is_active
        ) VALUES (
            p_vault_signature, 1, winner.wallet,
            0, NULL,
            now(), period_end, winner.completion_count, period_num,
            true
        ) RETURNING id INTO seat_id;

        -- Initialize inactivity tracking
        INSERT INTO swanny_inactivity (seat_id, last_action_at)
        VALUES (seat_id, now());
    END IF;

    RETURN election_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION elect_swanny IS 'Run Local Legend election - most completions wins, earliest completion breaks ties';

-- Get current swanny for a vault
CREATE OR REPLACE FUNCTION get_vault_swanny(
    p_vault_signature TEXT
) RETURNS TABLE (
    seat_id UUID,
    wallet TEXT,
    elected_at TIMESTAMPTZ,
    term_ends_at TIMESTAMPTZ,
    completion_count INTEGER,
    election_period INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.wallet, s.elected_at, s.term_ends_at, s.completion_count, s.election_period
    FROM swanny_seats s
    WHERE s.vault_signature = p_vault_signature AND s.is_active = true
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_swanny IS 'Get current Local Legend for a vault';

-- Check and mark inactive swannys
CREATE OR REPLACE FUNCTION check_swanny_inactivity(
    p_seat_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    config RECORD;
    inactivity RECORD;
    pending_tasks INTEGER;
BEGIN
    SELECT * INTO config FROM swanny_config WHERE id = 1;
    SELECT * INTO inactivity FROM swanny_inactivity WHERE seat_id = p_seat_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Count pending tasks
    pending_tasks := inactivity.pending_photo_approvals + inactivity.pending_flag_reviews;

    -- If pending tasks and no action in X weeks, mark inactive
    IF pending_tasks > 0 AND
       inactivity.last_action_at < (now() - (config.inactivity_weeks || ' weeks')::INTERVAL) THEN

        UPDATE swanny_inactivity
        SET inactive_since = COALESCE(inactive_since, now()),
            updated_at = now()
        WHERE seat_id = p_seat_id;

        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION check_swanny_inactivity IS 'Check if swanny is inactive due to ignored tasks';

-- Claim inactive seat (next-highest completion leader can take over)
CREATE OR REPLACE FUNCTION claim_inactive_seat(
    p_vault_signature TEXT,
    p_claimer_wallet TEXT
) RETURNS UUID AS $$
DECLARE
    config RECORD;
    current_seat RECORD;
    election RECORD;
    candidate RECORD;
    new_seat_id UUID;
    period_start TIMESTAMPTZ;
    period_end TIMESTAMPTZ;
    period_start_epoch INTEGER;
    period_end_epoch INTEGER;
    -- Epochs run Sunday 12:00 UTC to Sunday 12:00 UTC (per TOKENOMICS_V2.md line 234)
    epoch_anchor BIGINT := 1704020400; -- Sun Dec 31 2023 12:00:00 UTC
    epoch_duration INTEGER := 604800;  -- 7 days in seconds
BEGIN
    -- Get config
    SELECT * INTO config FROM swanny_config WHERE id = 1;

    -- Get current active seat
    SELECT s.*, si.inactive_since
    INTO current_seat
    FROM swanny_seats s
    JOIN swanny_inactivity si ON si.seat_id = s.id
    WHERE s.vault_signature = p_vault_signature AND s.is_active = true;

    IF NOT FOUND OR current_seat.inactive_since IS NULL THEN
        RETURN NULL; -- No inactive seat to claim
    END IF;

    -- Get election window (fallback to computed window)
    SELECT period_start, period_end INTO election
    FROM swanny_elections
    WHERE vault_signature = p_vault_signature AND election_period = current_seat.election_period;

    IF NOT FOUND THEN
        period_start_epoch := (current_seat.election_period - 1) * config.rotation_epochs;
        period_end_epoch := period_start_epoch + config.rotation_epochs;
        period_start := to_timestamp(epoch_anchor + (period_start_epoch * epoch_duration));
        period_end := to_timestamp(epoch_anchor + (period_end_epoch * epoch_duration));
    ELSE
        period_start := election.period_start;
        period_end := election.period_end;
    END IF;

    -- Validate claimer is next-highest completion leader for the period
    SELECT wallet, completion_count, first_completed_at INTO candidate
    FROM get_vault_completion_counts(p_vault_signature, period_start, period_end)
    WHERE wallet != current_seat.wallet
    ORDER BY completion_count DESC, first_completed_at ASC
    LIMIT 1;

    IF candidate.wallet IS NULL OR candidate.wallet != p_claimer_wallet THEN
        RETURN NULL; -- Only the next-highest rider can claim
    END IF;

    -- Record the claim
    UPDATE swanny_inactivity
    SET claimed_by = p_claimer_wallet, claimed_at = now(), updated_at = now()
    WHERE seat_id = current_seat.id;

    -- Deactivate old seat
    UPDATE swanny_seats SET is_active = false WHERE id = current_seat.id;

    -- Create new seat for claimer
    INSERT INTO swanny_seats (
        vault_signature, seat_number, wallet,
        points_locked, unlock_at,
        elected_at, term_ends_at, completion_count, election_period,
        is_active
    ) VALUES (
        p_vault_signature, 1, p_claimer_wallet,
        0, NULL,
        now(), current_seat.term_ends_at, candidate.completion_count, current_seat.election_period,
        true
    ) RETURNING id INTO new_seat_id;

    -- Initialize inactivity tracking
    INSERT INTO swanny_inactivity (seat_id, last_action_at)
    VALUES (new_seat_id, now());

    RETURN new_seat_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_inactive_seat IS 'Next-highest completion leader can claim seat if current holder is inactive';

-- Update action recording to track activity
CREATE OR REPLACE FUNCTION record_swanny_action(
    p_seat_id UUID,
    p_action_type TEXT,
    p_target_type TEXT,
    p_target_id TEXT,
    p_reason TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    action_id UUID;
BEGIN
    -- Verify seat is active
    IF NOT EXISTS (SELECT 1 FROM swanny_seats WHERE id = p_seat_id AND is_active = true) THEN
        RETURN NULL;
    END IF;

    -- Create action
    INSERT INTO swanny_actions (seat_id, action_type, target_type, target_id, reason)
    VALUES (p_seat_id, p_action_type, p_target_type, p_target_id, p_reason)
    RETURNING id INTO action_id;

    -- Update activity timestamp and clear inactive status
    UPDATE swanny_inactivity
    SET last_action_at = now(),
        inactive_since = NULL,
        updated_at = now()
    WHERE seat_id = p_seat_id;

    -- Decrement pending count based on action type
    IF p_action_type = 'APPROVE_PHOTO' OR p_action_type = 'REJECT_PHOTO' THEN
        UPDATE swanny_inactivity
        SET pending_photo_approvals = GREATEST(0, pending_photo_approvals - 1)
        WHERE seat_id = p_seat_id;
    ELSIF p_action_type = 'FLAG_COMPLETION' OR p_action_type = 'VERIFY_EFFORT' THEN
        UPDATE swanny_inactivity
        SET pending_flag_reviews = GREATEST(0, pending_flag_reviews - 1)
        WHERE seat_id = p_seat_id;
    END IF;

    RETURN action_id;
END;
$$ LANGUAGE plpgsql;

-- Add new action types
ALTER TABLE swanny_actions DROP CONSTRAINT IF EXISTS chk_swanny_action_type;
ALTER TABLE swanny_actions
    ADD CONSTRAINT chk_swanny_action_type
    CHECK (action_type IN (
        'FLAG_COMPLETION',    -- Flag suspicious completion
        'VERIFY_EFFORT',      -- Verify bio/effort data
        'DISPUTE',            -- Dispute another action
        'APPROVE_PHOTO',      -- Approve vault cover photo
        'REJECT_PHOTO',       -- Reject vault cover photo
        'APPROVE_VAULT',      -- Approve vault metadata
        'REPORT_USER',        -- Report suspicious user
        'FEATURE_VAULT'       -- Recommend vault for featuring
    ));

-- =============================================================================
-- UPDATE DISTRIBUTION CONFIG
-- =============================================================================

UPDATE vault_distribution_config SET
    leaderboard_share_bps = 5500,
    staker_share_bps = 2700,
    local_legend_share_bps = 300,
    pol_share_bps = 500,
    protocol_fee_bps = 1000,
    updated_at = now()
WHERE id = 1;

-- =============================================================================
-- SUMMARY VIEW
-- =============================================================================

CREATE OR REPLACE VIEW v_vault_local_legends AS
SELECT
    s.vault_signature,
    s.wallet as legend_wallet,
    s.completion_count,
    s.elected_at,
    s.term_ends_at,
    s.election_period,
    e.total_completions as period_total_completions,
    e.unique_riders as period_unique_riders,
    i.last_action_at,
    i.inactive_since,
    CASE
        WHEN i.inactive_since IS NOT NULL THEN 'INACTIVE'
        WHEN s.term_ends_at < now() THEN 'TERM_ENDED'
        ELSE 'ACTIVE'
    END as status
FROM swanny_seats s
LEFT JOIN swanny_elections e ON e.vault_signature = s.vault_signature
    AND e.election_period = s.election_period
LEFT JOIN swanny_inactivity i ON i.seat_id = s.id
WHERE s.is_active = true;

COMMENT ON VIEW v_vault_local_legends IS 'Current Local Legend status for all vaults';
