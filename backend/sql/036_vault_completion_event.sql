-- Migration: 036_vault_completion_event.sql
-- Description: Add VAULT_COMPLETION event type for points_events
-- Date: 2025-12-29

-- =============================================================================
-- UPDATE POINTS_EVENTS CONSTRAINT
-- Add VAULT_COMPLETION event type for recording vault climb completions
-- =============================================================================

-- Drop existing constraint
ALTER TABLE points_events DROP CONSTRAINT IF EXISTS chk_points_event_type;

-- Recreate with VAULT_COMPLETION added
ALTER TABLE points_events ADD CONSTRAINT chk_points_event_type
    CHECK (event_type IN (
        'TSS_EARN',           -- Ride upload (1 pt per TSS)
        'VAULT_CREATE',       -- Creating a vault (-50,000 pts)
        'VAULT_COMPLETION',   -- Completing a vault climb (NEW)
        'STAKE_DEPOSIT',      -- Staking into vault
        'STAKE_WITHDRAW',     -- Unstaking from vault
        'LEADERBOARD_PAYOUT', -- Weekly leaderboard distribution
        'SWANNY_LOCK',        -- Deprecated: v1 swanny lock
        'SWANNY_UNLOCK',      -- Deprecated: v1 swanny unlock
        'SWANNY_ELECTION',    -- Won Local Legend election
        'SWANNY_EARNINGS',    -- Epoch distribution to Local Legend
        'REFERRAL_BONUS',     -- Referral reward
        'TGE_CONVERT',        -- TGE conversion adjustment
        'ADMIN_ADJUST'        -- Manual admin adjustment
    ));

COMMENT ON CONSTRAINT chk_points_event_type ON points_events IS
    'Valid event types for points changes. VAULT_COMPLETION added in 036.';
