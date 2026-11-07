-- Circulating DUNG is the canonical SPL mint supply. DungMintState.total_burned
-- remains protocol-burn telemetry and cannot observe holder-initiated SPL burns.

ALTER TABLE public.indexed_supply
    ADD COLUMN IF NOT EXISTS spl_mint_supply NUMERIC,
    ADD COLUMN IF NOT EXISTS spl_mint_supply_slot BIGINT,
    ADD COLUMN IF NOT EXISTS spl_mint_supply_indexed_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'indexed_supply_spl_mint_supply_u64'
          AND conrelid = 'public.indexed_supply'::regclass
    ) THEN
        ALTER TABLE public.indexed_supply
            ADD CONSTRAINT indexed_supply_spl_mint_supply_u64
            CHECK (
                spl_mint_supply IS NULL
                OR (
                    spl_mint_supply >= 0
                    AND spl_mint_supply <= 18446744073709551615
                    AND scale(spl_mint_supply) = 0
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'indexed_supply_spl_mint_observation_complete'
          AND conrelid = 'public.indexed_supply'::regclass
    ) THEN
        ALTER TABLE public.indexed_supply
            ADD CONSTRAINT indexed_supply_spl_mint_observation_complete
            CHECK (
                (
                    spl_mint_supply IS NULL
                    AND spl_mint_supply_slot IS NULL
                    AND spl_mint_supply_indexed_at IS NULL
                )
                OR (
                    spl_mint_supply IS NOT NULL
                    AND spl_mint_supply_slot IS NOT NULL
                    AND spl_mint_supply_slot >= 0
                    AND spl_mint_supply_indexed_at IS NOT NULL
                )
            );
    END IF;
END
$$;

COMMENT ON COLUMN public.indexed_supply.total_burned IS
    'DUNG burned by Boulder Roller instructions since protocol burn accounting activated; not circulating-supply authority';
COMMENT ON COLUMN public.indexed_supply.spl_mint_supply IS
    'Canonical circulating DUNG base units read from the SPL mint account';
COMMENT ON COLUMN public.indexed_supply.spl_mint_supply_slot IS
    'Finalized Solana slot that authorized spl_mint_supply';
COMMENT ON COLUMN public.indexed_supply.spl_mint_supply_indexed_at IS
    'Indexer observation time for the canonical SPL mint supply';
COMMENT ON COLUMN public.indexed_supply.circulating IS
    'Legacy derived value total_minted - total_burned; not circulating-supply authority';
