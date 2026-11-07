-- ============================================================================
-- Live LP Position Indexes
--
-- VaultStake.cal_staked is remaining deposited-principal basis. It can floor
-- to zero while lp_tokens remains redeemable, so current-position reads and
-- their supporting indexes must use positive LP rather than positive basis.
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_indexed_stakes_user_live_lp
    ON public.indexed_stakes (user_pubkey)
    WHERE lp_tokens > 0;

CREATE INDEX IF NOT EXISTS idx_indexed_stakes_vault_live_lp
    ON public.indexed_stakes (vault_id)
    WHERE lp_tokens > 0;

COMMENT ON INDEX public.idx_indexed_stakes_user_live_lp IS
    'Current rider positions keyed by redeemable VaultStake LP.';

COMMENT ON INDEX public.idx_indexed_stakes_vault_live_lp IS
    'Current Vault positions keyed by redeemable VaultStake LP.';
