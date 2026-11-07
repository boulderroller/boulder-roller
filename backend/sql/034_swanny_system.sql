-- Migration: 034_swanny_system.sql
-- Description: Swanny seats - 3 per vault, 1000 DUNG lock, moderation duties
-- Date: 2024-12-24

-- =============================================================================
-- SWANNY SEATS
-- 3 seats per vault with locked stake and moderation duties
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_seats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    seat_number INTEGER NOT NULL CHECK (seat_number >= 1 AND seat_number <= 3),
    wallet TEXT NOT NULL,
    -- Points locked (testing period: 1,000,000 pts = 1000 DUNG equiv)
    points_locked NUMERIC NOT NULL DEFAULT 1000000,
    -- DUNG locked (post-TGE, populated at conversion)
    dung_locked NUMERIC,
    -- Lock period
    locked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unlock_at TIMESTAMPTZ NOT NULL,
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,
    -- TGE conversion tracking
    converted_at TIMESTAMPTZ,
    -- Constraints
    UNIQUE (vault_signature, seat_number),
    UNIQUE (vault_signature, wallet)
);

CREATE INDEX IF NOT EXISTS idx_swanny_vault ON swanny_seats(vault_signature);
CREATE INDEX IF NOT EXISTS idx_swanny_wallet ON swanny_seats(wallet);
CREATE INDEX IF NOT EXISTS idx_swanny_active ON swanny_seats(vault_signature) WHERE is_active = true;

COMMENT ON TABLE swanny_seats IS '3 moderation seats per vault with locked stake';
COMMENT ON COLUMN swanny_seats.seat_number IS '1-3, first-come-first-served';
COMMENT ON COLUMN swanny_seats.points_locked IS '1M points = 1000 DUNG equivalent during testing';
COMMENT ON COLUMN swanny_seats.unlock_at IS '30 days from lock by default';

-- =============================================================================
-- SWANNY ACTIONS (MODERATION LOG)
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seat_id UUID NOT NULL REFERENCES swanny_seats(id),
    action_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    reason TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    resolution TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add constraints
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_swanny_action_type'
    ) THEN
        ALTER TABLE swanny_actions
            ADD CONSTRAINT chk_swanny_action_type
            CHECK (action_type IN (
                'FLAG_COMPLETION',    -- Flag suspicious completion
                'VERIFY_EFFORT',      -- Verify bio/effort data
                'DISPUTE',            -- Dispute another action
                'APPROVE_VAULT',      -- Approve vault metadata
                'REPORT_USER'         -- Report suspicious user
            ));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_swanny_target_type'
    ) THEN
        ALTER TABLE swanny_actions
            ADD CONSTRAINT chk_swanny_target_type
            CHECK (target_type IN ('completion', 'user', 'vault', 'activity', 'photo'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_swanny_actions_seat ON swanny_actions(seat_id);
CREATE INDEX IF NOT EXISTS idx_swanny_actions_target ON swanny_actions(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_swanny_actions_pending ON swanny_actions(created_at) WHERE resolved_at IS NULL;

COMMENT ON TABLE swanny_actions IS 'Moderation actions taken by swanny seat holders';
COMMENT ON COLUMN swanny_actions.resolution IS 'Outcome: UPHELD, DISMISSED, ESCALATED';

-- =============================================================================
-- SWANNY EARNINGS
-- Distribution earnings per epoch
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_earnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seat_id UUID NOT NULL REFERENCES swanny_seats(id),
    distribution_id UUID REFERENCES vault_distributions(id),
    epoch INTEGER NOT NULL,
    amount NUMERIC NOT NULL,
    is_points_period BOOLEAN NOT NULL DEFAULT true,
    earned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swanny_earnings_seat ON swanny_earnings(seat_id);
CREATE INDEX IF NOT EXISTS idx_swanny_earnings_epoch ON swanny_earnings(epoch);

COMMENT ON TABLE swanny_earnings IS 'Distribution earnings for swanny seat holders';

-- =============================================================================
-- SWANNY CONFIG
-- =============================================================================

CREATE TABLE IF NOT EXISTS swanny_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Lock requirements
    lock_amount_dung NUMERIC NOT NULL DEFAULT 1000,
    lock_duration_days INTEGER NOT NULL DEFAULT 30,
    -- Seat limits
    seats_per_vault INTEGER NOT NULL DEFAULT 3,
    -- Action limits
    max_pending_actions_per_seat INTEGER NOT NULL DEFAULT 5,
    -- Updated
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO swanny_config (id) VALUES (1) ON CONFLICT DO NOTHING;

COMMENT ON TABLE swanny_config IS 'Singleton config for swanny system parameters';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to claim a swanny seat
CREATE OR REPLACE FUNCTION claim_swanny_seat(
    p_vault_signature TEXT,
    p_wallet TEXT
) RETURNS UUID AS $$
DECLARE
    next_seat INTEGER;
    lock_points NUMERIC;
    lock_days INTEGER;
    seat_id UUID;
BEGIN
    -- Get config
    SELECT lock_amount_dung * get_points_per_dung(), lock_duration_days
    INTO lock_points, lock_days
    FROM swanny_config WHERE id = 1;

    -- Check if wallet already has a seat in this vault
    IF EXISTS (SELECT 1 FROM swanny_seats WHERE vault_signature = p_vault_signature AND wallet = p_wallet AND is_active = true) THEN
        RETURN NULL; -- Already has seat
    END IF;

    -- Find next available seat
    SELECT MIN(s.seat_number) INTO next_seat
    FROM generate_series(1, 3) AS s(seat_number)
    LEFT JOIN swanny_seats ON swanny_seats.vault_signature = p_vault_signature
        AND swanny_seats.seat_number = s.seat_number
        AND swanny_seats.is_active = true
    WHERE swanny_seats.id IS NULL;

    IF next_seat IS NULL THEN
        RETURN NULL; -- All seats taken
    END IF;

    -- Check wallet has enough points
    IF (SELECT total_points FROM wallet_points WHERE wallet = p_wallet) < lock_points THEN
        RETURN NULL; -- Insufficient points
    END IF;

    -- Create seat
    INSERT INTO swanny_seats (vault_signature, seat_number, wallet, points_locked, unlock_at)
    VALUES (p_vault_signature, next_seat, p_wallet, lock_points, now() + (lock_days || ' days')::INTERVAL)
    RETURNING id INTO seat_id;

    -- Lock points
    PERFORM add_points(p_wallet, -lock_points, 'SWANNY_LOCK', 'swanny_seat', seat_id::TEXT);

    RETURN seat_id;
END;
$$ LANGUAGE plpgsql;

-- Function to release a swanny seat
CREATE OR REPLACE FUNCTION release_swanny_seat(
    p_seat_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    seat RECORD;
BEGIN
    SELECT * INTO seat FROM swanny_seats WHERE id = p_seat_id AND is_active = true;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Check if lock period has passed
    IF seat.unlock_at > now() THEN
        RETURN FALSE; -- Still locked
    END IF;

    -- Deactivate seat
    UPDATE swanny_seats SET is_active = false WHERE id = p_seat_id;

    -- Return locked points
    PERFORM add_points(seat.wallet, seat.points_locked, 'SWANNY_UNLOCK', 'swanny_seat', p_seat_id::TEXT);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to count active swanny seats for a vault
CREATE OR REPLACE FUNCTION get_vault_swanny_count(
    p_vault_signature TEXT
) RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)
        FROM swanny_seats
        WHERE vault_signature = p_vault_signature AND is_active = true
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get swanny seat holders for a vault
CREATE OR REPLACE FUNCTION get_vault_swannys(
    p_vault_signature TEXT
) RETURNS TABLE (
    seat_id UUID,
    seat_number INTEGER,
    wallet TEXT,
    points_locked NUMERIC,
    locked_at TIMESTAMPTZ,
    unlock_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT s.id, s.seat_number, s.wallet, s.points_locked, s.locked_at, s.unlock_at
    FROM swanny_seats s
    WHERE s.vault_signature = p_vault_signature AND s.is_active = true
    ORDER BY s.seat_number;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to record swanny action
CREATE OR REPLACE FUNCTION record_swanny_action(
    p_seat_id UUID,
    p_action_type TEXT,
    p_target_type TEXT,
    p_target_id TEXT,
    p_reason TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    action_id UUID;
    pending_count INTEGER;
    max_pending INTEGER;
BEGIN
    -- Verify seat is active
    IF NOT EXISTS (SELECT 1 FROM swanny_seats WHERE id = p_seat_id AND is_active = true) THEN
        RETURN NULL;
    END IF;

    -- Check pending action limit
    SELECT max_pending_actions_per_seat INTO max_pending FROM swanny_config WHERE id = 1;
    SELECT COUNT(*) INTO pending_count
    FROM swanny_actions
    WHERE seat_id = p_seat_id AND resolved_at IS NULL;

    IF pending_count >= max_pending THEN
        RETURN NULL; -- Too many pending actions
    END IF;

    -- Create action
    INSERT INTO swanny_actions (seat_id, action_type, target_type, target_id, reason)
    VALUES (p_seat_id, p_action_type, p_target_type, p_target_id, p_reason)
    RETURNING id INTO action_id;

    RETURN action_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_swanny_seat IS 'Claim an available swanny seat with point lock';
COMMENT ON FUNCTION release_swanny_seat IS 'Release a swanny seat after lock period';
COMMENT ON FUNCTION record_swanny_action IS 'Record a moderation action from a swanny';
