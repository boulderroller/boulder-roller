-- Persist ride-level effort evidence and economy policy.
--
-- These fields separate estimated route effort from rewardable and tributable
-- CAL so clients and background phases do not infer economic truth from TSS.

ALTER TABLE rides
  ADD COLUMN IF NOT EXISTS effort_evidence_tier TEXT,
  ADD COLUMN IF NOT EXISTS reward_policy TEXT,
  ADD COLUMN IF NOT EXISTS estimated_cal INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS rewardable_cal INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS tributable_cal INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_rides_effort_evidence_tier
  ON rides(effort_evidence_tier)
  WHERE effort_evidence_tier IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rides_reward_policy
  ON rides(reward_policy)
  WHERE reward_policy IS NOT NULL;

COMMENT ON COLUMN rides.effort_evidence_tier IS
  'Best available effort evidence for this ride: route_only, sensor_supported, power_verified, or manual_review.';
COMMENT ON COLUMN rides.reward_policy IS
  'Economy policy for this ride: rewardable, estimated_only, manual_review, or not_counted.';
COMMENT ON COLUMN rides.estimated_cal IS
  'Display CAL estimated from ride TSS, including route-only estimates that are not rewardable.';
COMMENT ON COLUMN rides.rewardable_cal IS
  'Display CAL allowed to be credited/minted for this ride.';
COMMENT ON COLUMN rides.tributable_cal IS
  'Display CAL allowed to flow into climb/vault tribute for this ride.';
