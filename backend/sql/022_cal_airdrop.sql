-- Add next_cal_airdrop column for automatic CAL distribution
-- CAL airdrops happen 24 hours after last mint, processed by Celery cron

ALTER TABLE public.user_state
ADD COLUMN IF NOT EXISTS next_cal_airdrop TIMESTAMPTZ;

-- Backfill: For existing users with last_cal_mint, set next_cal_airdrop to last_cal_mint + 24h
UPDATE public.user_state
SET next_cal_airdrop = last_cal_mint + INTERVAL '24 hours'
WHERE last_cal_mint IS NOT NULL
  AND next_cal_airdrop IS NULL;

-- For users who never minted, set it to now (they'll get their first airdrop soon)
UPDATE public.user_state
SET next_cal_airdrop = NOW()
WHERE next_cal_airdrop IS NULL;

-- Create index for efficient query by airdrop time
CREATE INDEX IF NOT EXISTS idx_user_state_next_cal_airdrop
ON public.user_state (next_cal_airdrop)
WHERE next_cal_airdrop IS NOT NULL;

COMMENT ON COLUMN public.user_state.next_cal_airdrop IS 'When this user will receive their next automatic CAL airdrop (24h after last)';
