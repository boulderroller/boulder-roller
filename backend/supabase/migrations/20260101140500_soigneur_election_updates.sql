-- Update Local Legend (Soigneur) election logic
-- - Add deterministic tie-breaker (earliest completion)
-- - Remove runner-up storage from elections
-- - Allow inactive seat claims by next-highest completion leader

DROP FUNCTION IF EXISTS claim_inactive_seat(TEXT, TEXT);
DROP FUNCTION IF EXISTS elect_swanny(TEXT, INTEGER);
DROP FUNCTION IF EXISTS get_vault_completion_counts(TEXT, TIMESTAMPTZ, TIMESTAMPTZ);

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
