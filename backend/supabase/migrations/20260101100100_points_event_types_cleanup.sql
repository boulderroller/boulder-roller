-- Cleanup points event types: points are ONLY for earning and TGE conversion
-- Remove vault creation, staking, and deprecated swanny event types

-- Update constraint to only allow earning + TGE conversion events
ALTER TABLE points_events DROP CONSTRAINT IF EXISTS chk_points_event_type;
ALTER TABLE points_events
    ADD CONSTRAINT chk_points_event_type
    CHECK (event_type IN (
        'TSS_EARN',              -- Ride upload (1 pt per TSS)
        'VAULT_COMPLETION',      -- Bonus for completing vault climb
        'LEADERBOARD_PAYOUT',    -- Epoch distribution (top 10)
        'LOCAL_LEGEND_EARNINGS', -- Epoch distribution (3%)
        'REFERRAL_BONUS',        -- Referral rewards
        'TGE_CONVERT',           -- Points → DUNG conversion
        'ADMIN_ADJUST'           -- Manual correction
    ));

-- Migrate any old SWANNY_EARNINGS to LOCAL_LEGEND_EARNINGS
UPDATE points_events
SET event_type = 'LOCAL_LEGEND_EARNINGS'
WHERE event_type = 'SWANNY_EARNINGS';

-- Update wallet_points columns to remove staking/creation tracking
-- These were never used since points aren't spent
COMMENT ON COLUMN wallet_points.points_from_creation IS 'Deprecated: vault creation costs CAL, not points';
COMMENT ON COLUMN wallet_points.points_from_staking IS 'Deprecated: staking uses DUNG post-TGE, not points';
