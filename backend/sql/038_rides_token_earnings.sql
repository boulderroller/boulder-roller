-- Add CAL and points earned columns to rides table
-- During points period: cal_earned and points_earned are populated
-- Post-TGE: dung_minted is populated (existing column)

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS cal_earned INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS points_earned INTEGER DEFAULT 0;

-- Index for querying by earnings
CREATE INDEX IF NOT EXISTS idx_rides_cal_earned ON rides(cal_earned) WHERE cal_earned > 0;
CREATE INDEX IF NOT EXISTS idx_rides_points_earned ON rides(points_earned) WHERE points_earned > 0;

-- Comments
COMMENT ON COLUMN rides.cal_earned IS 'CAL tokens earned from this ride (1 TSS = 1 CAL during points period)';
COMMENT ON COLUMN rides.points_earned IS 'Points earned from this ride (1 TSS = 1 point during points period)';
