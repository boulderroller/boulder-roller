-- Project the Community liability reservation and its policy marker from the
-- on-chain DungMintState. Existing rows remain explicitly pre-policy until the
-- upgraded indexer observes the migrated account.

ALTER TABLE public.indexed_supply
    ADD COLUMN IF NOT EXISTS community_reserved NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reservation_policy_version SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.indexed_supply.community_reserved IS
    'Unminted Community DUNG already committed to rider claims and vault carry';
COMMENT ON COLUMN public.indexed_supply.reservation_policy_version IS
    'On-chain DungMintState reservation policy marker; 1 is the full-liability policy';
