-- Migration: 054_leaderboard_flagging.sql
-- Description: Leaderboard flagging and dispute system for Local Legend curation
-- Date: 2025-01-26
--
-- Per FRESHEST_SPEC: Local Legend can "flag suspicious completions for community tribunal"
-- This implements the flagging infrastructure for leaderboard entries.

-- =============================================================================
-- ADD FLAG COLUMNS TO VAULT_LEADERBOARDS
-- =============================================================================

ALTER TABLE vault_leaderboards
    ADD COLUMN IF NOT EXISTS flagged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS flagged_by TEXT,
    ADD COLUMN IF NOT EXISTS flag_reason TEXT,
    ADD COLUMN IF NOT EXISTS flag_status TEXT DEFAULT NULL;

-- flag_status values: NULL (not flagged), 'pending_review', 'upheld', 'dismissed'
COMMENT ON COLUMN vault_leaderboards.flagged_at IS 'When this entry was flagged for review';
COMMENT ON COLUMN vault_leaderboards.flagged_by IS 'Wallet that flagged this entry (Local Legend or admin)';
COMMENT ON COLUMN vault_leaderboards.flag_reason IS 'Reason provided for flagging';
COMMENT ON COLUMN vault_leaderboards.flag_status IS 'NULL=not flagged, pending_review, upheld, dismissed';

-- =============================================================================
-- LEADERBOARD DISPUTES TABLE
-- Full history of flagging and resolution
-- =============================================================================

CREATE TABLE IF NOT EXISTS leaderboard_disputes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    disputed_wallet TEXT NOT NULL,
    disputed_rank INTEGER NOT NULL,
    disputed_time_seconds INTEGER NOT NULL,

    -- Flag details
    flagged_by TEXT NOT NULL,
    flag_reason TEXT NOT NULL,
    flag_category TEXT NOT NULL DEFAULT 'other',  -- impossible_time, suspected_cheating, data_error, other
    evidence_notes TEXT,

    -- Resolution
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, under_review, upheld, dismissed
    resolved_by TEXT,
    resolution_notes TEXT,
    resolved_at TIMESTAMPTZ,

    -- If upheld, what action was taken
    action_taken TEXT,  -- entry_removed, time_adjusted, warning_issued, no_action

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Constraints
    CONSTRAINT chk_dispute_category CHECK (
        flag_category IN ('impossible_time', 'suspected_cheating', 'data_error', 'other')
    ),
    CONSTRAINT chk_dispute_status CHECK (
        status IN ('pending', 'under_review', 'upheld', 'dismissed')
    ),
    CONSTRAINT chk_dispute_action CHECK (
        action_taken IS NULL OR action_taken IN ('entry_removed', 'time_adjusted', 'warning_issued', 'no_action')
    )
);

CREATE INDEX IF NOT EXISTS idx_disputes_vault ON leaderboard_disputes(vault_signature, status);
CREATE INDEX IF NOT EXISTS idx_disputes_wallet ON leaderboard_disputes(disputed_wallet);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON leaderboard_disputes(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_disputes_flagged_by ON leaderboard_disputes(flagged_by);

COMMENT ON TABLE leaderboard_disputes IS 'Full history of leaderboard flags and dispute resolutions';
COMMENT ON COLUMN leaderboard_disputes.flag_category IS 'Classification: impossible_time, suspected_cheating, data_error, other';
COMMENT ON COLUMN leaderboard_disputes.action_taken IS 'Resolution action: entry_removed, time_adjusted, warning_issued, no_action';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to flag a leaderboard entry (creates dispute and updates leaderboard)
CREATE OR REPLACE FUNCTION flag_leaderboard_entry(
    p_vault_signature TEXT,
    p_rank INTEGER,
    p_flagged_by TEXT,
    p_reason TEXT,
    p_category TEXT DEFAULT 'other',
    p_evidence_notes TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_disputed_wallet TEXT;
    v_disputed_time INTEGER;
    v_dispute_id UUID;
BEGIN
    -- Validate category
    IF p_category NOT IN ('impossible_time', 'suspected_cheating', 'data_error', 'other') THEN
        RAISE EXCEPTION 'Invalid flag category: %', p_category;
    END IF;

    -- Get the entry being flagged
    SELECT wallet, best_time_seconds
    INTO v_disputed_wallet, v_disputed_time
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND rank = p_rank;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Leaderboard entry not found for vault % rank %', p_vault_signature, p_rank;
    END IF;

    -- Check if already flagged and pending
    IF EXISTS (
        SELECT 1 FROM leaderboard_disputes
        WHERE vault_signature = p_vault_signature
          AND disputed_wallet = v_disputed_wallet
          AND status IN ('pending', 'under_review')
    ) THEN
        RAISE EXCEPTION 'Entry already has a pending dispute';
    END IF;

    -- Create dispute record
    INSERT INTO leaderboard_disputes (
        vault_signature, disputed_wallet, disputed_rank, disputed_time_seconds,
        flagged_by, flag_reason, flag_category, evidence_notes
    ) VALUES (
        p_vault_signature, v_disputed_wallet, p_rank, v_disputed_time,
        p_flagged_by, p_reason, p_category, p_evidence_notes
    )
    RETURNING id INTO v_dispute_id;

    -- Mark the leaderboard entry as flagged
    UPDATE vault_leaderboards
    SET flagged_at = now(),
        flagged_by = p_flagged_by,
        flag_reason = p_reason,
        flag_status = 'pending_review'
    WHERE vault_signature = p_vault_signature AND rank = p_rank;

    RETURN v_dispute_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION flag_leaderboard_entry IS 'Flag a leaderboard entry for review, creating a dispute record';

-- Function to resolve a dispute
CREATE OR REPLACE FUNCTION resolve_dispute(
    p_dispute_id UUID,
    p_resolved_by TEXT,
    p_status TEXT,  -- 'upheld' or 'dismissed'
    p_resolution_notes TEXT,
    p_action TEXT DEFAULT 'no_action'
) RETURNS BOOLEAN AS $$
DECLARE
    v_vault_signature TEXT;
    v_disputed_rank INTEGER;
    v_disputed_wallet TEXT;
BEGIN
    -- Validate status
    IF p_status NOT IN ('upheld', 'dismissed') THEN
        RAISE EXCEPTION 'Invalid resolution status: %. Must be upheld or dismissed', p_status;
    END IF;

    -- Validate action
    IF p_action NOT IN ('entry_removed', 'time_adjusted', 'warning_issued', 'no_action') THEN
        RAISE EXCEPTION 'Invalid action: %', p_action;
    END IF;

    -- Get dispute details
    SELECT vault_signature, disputed_rank, disputed_wallet
    INTO v_vault_signature, v_disputed_rank, v_disputed_wallet
    FROM leaderboard_disputes
    WHERE id = p_dispute_id AND status IN ('pending', 'under_review');

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Dispute not found or already resolved';
    END IF;

    -- Update dispute record
    UPDATE leaderboard_disputes
    SET status = p_status,
        resolved_by = p_resolved_by,
        resolution_notes = p_resolution_notes,
        action_taken = p_action,
        resolved_at = now(),
        updated_at = now()
    WHERE id = p_dispute_id;

    -- Update leaderboard entry flag status
    UPDATE vault_leaderboards
    SET flag_status = p_status
    WHERE vault_signature = v_vault_signature AND wallet = v_disputed_wallet;

    -- If upheld and action is removal, the actual removal should be done separately
    -- by calling remove_leaderboard_entry() to properly rerank remaining entries

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION resolve_dispute IS 'Resolve a dispute as upheld or dismissed';

-- Function to remove a leaderboard entry and rerank
CREATE OR REPLACE FUNCTION remove_leaderboard_entry(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_reason TEXT DEFAULT 'Dispute upheld'
) RETURNS BOOLEAN AS $$
DECLARE
    v_removed_rank INTEGER;
BEGIN
    -- Get the rank of entry being removed
    SELECT rank INTO v_removed_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Delete the entry
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Rerank entries below the removed one
    UPDATE vault_leaderboards
    SET rank = rank - 1
    WHERE vault_signature = p_vault_signature AND rank > v_removed_rank;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION remove_leaderboard_entry IS 'Remove an entry and rerank remaining entries';

-- Function to check if a wallet can flag entries on a vault
CREATE OR REPLACE FUNCTION can_flag_leaderboard(
    p_vault_signature TEXT,
    p_wallet TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    -- Check if user is current Local Legend for this vault
    IF EXISTS (
        SELECT 1 FROM swanny_seats
        WHERE vault_signature = p_vault_signature
          AND wallet = p_wallet
          AND is_active = true
          AND (term_ends_at IS NULL OR term_ends_at > now())
    ) THEN
        RETURN TRUE;
    END IF;

    -- Admin check would be done at the application layer
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION can_flag_leaderboard IS 'Check if wallet is Local Legend and can flag entries';

-- =============================================================================
-- VIEW FOR ACTIVE DISPUTES
-- =============================================================================

CREATE OR REPLACE VIEW v_active_disputes AS
SELECT
    d.id,
    d.vault_signature,
    d.disputed_wallet,
    d.disputed_rank,
    d.disputed_time_seconds,
    d.flagged_by,
    d.flag_reason,
    d.flag_category,
    d.evidence_notes,
    d.status,
    d.created_at,
    iv.name as vault_name,
    iv.vert_m,
    iv.avg_gradient_pct,
    -- Calculate time since flagged
    EXTRACT(EPOCH FROM (now() - d.created_at)) / 3600 as hours_pending
FROM leaderboard_disputes d
JOIN indexed_vaults iv ON iv.signature_hex = d.vault_signature
WHERE d.status IN ('pending', 'under_review')
ORDER BY d.created_at ASC;

COMMENT ON VIEW v_active_disputes IS 'Active disputes awaiting resolution';

-- =============================================================================
-- TRIGGER FOR UPDATED_AT
-- =============================================================================

CREATE OR REPLACE FUNCTION update_dispute_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_dispute_updated_at ON leaderboard_disputes;
CREATE TRIGGER tr_dispute_updated_at
    BEFORE UPDATE ON leaderboard_disputes
    FOR EACH ROW
    EXECUTE FUNCTION update_dispute_updated_at();
