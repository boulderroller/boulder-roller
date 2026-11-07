-- Add Settlement Week snapshot projections without relabeling legacy data.
-- The old columns remain as provenance for accounts/events written before the
-- on-chain snapshot layout was activated.

ALTER TABLE public.indexed_stakes
    ADD COLUMN IF NOT EXISTS pending_effective_week_plus_one BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS effective_lp_tokens NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pending_lp_tokens NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE public.indexed_staker_allocations
    ADD COLUMN IF NOT EXISTS snapshot_epoch BIGINT;

UPDATE public.indexed_staker_allocations
SET snapshot_epoch = epoch
WHERE snapshot_epoch IS NULL;

COMMENT ON COLUMN public.indexed_stakes.eligible_from_epoch IS
    'Legacy pre-snapshot eligibility week; zero after an account is projected in the weekly snapshot layout';
COMMENT ON COLUMN public.indexed_stakes.user_reward_per_token_paid IS
    'Legacy pre-snapshot Synthetix slot retained only for projection compatibility';
COMMENT ON COLUMN public.indexed_stakes.amount IS
    'Legacy pre-snapshot amount slot retained only for projection compatibility';
COMMENT ON COLUMN public.indexed_stakes.effective_lp_tokens IS
    'LP weight frozen for the oldest unsettled Settlement Week';
COMMENT ON COLUMN public.indexed_stakes.pending_lp_tokens IS
    'Full LP weight target when the pending effective week begins';
COMMENT ON COLUMN public.indexed_stakes.pending_effective_week_plus_one IS
    'Zero when no stake transition is pending; otherwise effective Settlement Week plus one';
COMMENT ON COLUMN public.indexed_staker_allocations.snapshot_epoch IS
    'Settlement Week whose frozen LP snapshot produced this allocation; backfilled from epoch';
