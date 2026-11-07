-- Clarify the ratified same-week staker remainder semantics without rewriting
-- historical migrations that originally described the locked amount as carry.

ALTER TABLE public.indexed_vaults
    ADD COLUMN IF NOT EXISTS staker_remainder_policy_version SMALLINT
        NOT NULL DEFAULT 0
        CHECK (staker_remainder_policy_version BETWEEN 0 AND 255);

COMMENT ON COLUMN indexed_vaults.staker_remainder_policy_version IS
    'Projected on-chain carry interpretation: 0 means unmarked legacy carry awaiting Leaderboard pool cutover; 1 means carry_stakers is already-unlocked staker pro-rata integer dust.';

COMMENT ON COLUMN indexed_vaults.carry_stakers IS
    'Interpret with staker_remainder_policy_version: 0 is unmarked legacy carry awaiting Leaderboard pool cutover; 1 is already-unlocked staker pro-rata integer dust awaiting a future allocation and never an input to the participation curve.';

COMMENT ON COLUMN indexed_epoch_distributions.locked_staker_amount IS
    'Staker amount governed by the settlement policy event: paired StakerRemainderPolicyApplied rows mean same-week Leaderboard pool reallocation; historical unmarked rows mean locked staker carry.';

COMMENT ON COLUMN epoch_distributions.locked_staker_amount IS
    'Staker amount governed by the settlement policy event: paired StakerRemainderPolicyApplied rows mean same-week Leaderboard pool reallocation; historical unmarked rows mean locked staker carry.';

COMMENT ON COLUMN vault_distributions.locked_staker_amount IS
    'Staker amount governed by the settlement policy event: paired StakerRemainderPolicyApplied rows mean same-week Leaderboard pool reallocation; historical unmarked rows mean locked staker carry.';

NOTIFY pgrst, 'reload schema';
