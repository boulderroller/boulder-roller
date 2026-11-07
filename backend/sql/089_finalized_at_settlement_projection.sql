-- ============================================================================
-- finalized_at settlement projection
-- ============================================================================
-- BACKEND_TRUTHS §3.3: finalized_at is the time a ride's settlement week became
-- immutable on-chain. The backend must not fabricate it from wall-clock time.
-- The chain event projection is the source; SQL propagates that projection to
-- legacy queue rows and ride rows for user-facing "earnings locked" state.
-- ============================================================================

-- Some local/dev schemas briefly created indexed_epoch_distributions.finalized_at
-- as a plain writable column. Drop that drift before reinstalling it as a
-- generated chain-derived column. Existing values are intentionally discarded:
-- the only canonical source is block_time from EpochRewardsDistributed.
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ NULL;

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ NULL;

ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS on_chain_tx TEXT,
    ADD COLUMN IF NOT EXISTS on_chain_tx_error TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'indexed_epoch_distributions'
          AND column_name = 'finalized_at'
          AND is_generated = 'NEVER'
    ) THEN
        ALTER TABLE indexed_epoch_distributions DROP COLUMN finalized_at;
    END IF;
END $$;

ALTER TABLE indexed_epoch_distributions
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ
    GENERATED ALWAYS AS (
        CASE WHEN block_time IS NOT NULL
             THEN to_timestamp(block_time)
             ELSE NULL
        END
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_indexed_epoch_distributions_finalized_at
    ON indexed_epoch_distributions(finalized_at DESC)
    WHERE finalized_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_vault_completions_activity_onchain
    ON vault_completions(activity_id, vault_signature, completed_at)
    WHERE on_chain_tx IS NOT NULL;

COMMENT ON COLUMN indexed_epoch_distributions.finalized_at IS
    'BACKEND_TRUTHS §3.3 / §7.3. Settlement finalization time derived from '
    'the on-chain EpochRewardsDistributed block_time. GENERATED ALWAYS — not '
    'backend-writable.';

CREATE OR REPLACE FUNCTION br_settlement_week(p_completed_at TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT FLOOR((EXTRACT(EPOCH FROM p_completed_at) - 1704020400) / 604800)::BIGINT;
$$;

COMMENT ON FUNCTION br_settlement_week(TIMESTAMPTZ) IS
    'Protocol settlement-week calculation: Sunday 12:00 UTC anchor '
    '(1704020400), seven-day cadence. Mirrors on-chain Vault::current_epoch.';

CREATE OR REPLACE FUNCTION br_refresh_ride_finalized_at(p_activity_id TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
BEGIN
    IF p_activity_id IS NULL OR p_activity_id = '' THEN
        RETURN;
    END IF;

    WITH chain_completions AS (
        SELECT
            iv.id AS vault_id,
            br_settlement_week(vc.completed_at) AS settlement_week
        FROM vault_completions vc
        JOIN indexed_vaults iv
          ON iv.signature_hex = vc.vault_signature
        WHERE vc.activity_id = p_activity_id
          AND vc.on_chain_tx IS NOT NULL
          AND vc.completed_at IS NOT NULL
    ),
    completion_settlements AS (
        SELECT
            cc.vault_id,
            cc.settlement_week,
            MIN(ied.finalized_at) AS finalized_at
        FROM chain_completions cc
        LEFT JOIN indexed_epoch_distributions ied
          ON ied.vault_id = cc.vault_id
         AND ied.epoch = cc.settlement_week
         AND ied.finalized_at IS NOT NULL
        GROUP BY cc.vault_id, cc.settlement_week
    )
    SELECT
        CASE
            WHEN COUNT(*) > 0 AND COUNT(finalized_at) = COUNT(*)
                THEN MAX(finalized_at)
            ELSE NULL
        END
    INTO v_finalized_at
    FROM completion_settlements;

    UPDATE rides
    SET finalized_at = v_finalized_at
    WHERE id::TEXT = p_activity_id
      AND finalized_at IS DISTINCT FROM v_finalized_at;
END;
$$;

COMMENT ON FUNCTION br_refresh_ride_finalized_at(TEXT) IS
    'Refresh rides.finalized_at from indexed_epoch_distributions. A ride locks '
    'only after every chain-recorded vault completion for that ride has an '
    'observed settlement event. NULL is honest pending state.';

CREATE OR REPLACE FUNCTION br_sync_epoch_distribution_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    v_finalized_at := COALESCE(
        NEW.finalized_at,
        CASE WHEN NEW.block_time IS NOT NULL THEN to_timestamp(NEW.block_time) ELSE NULL END
    );

    IF v_finalized_at IS NULL THEN
        RETURN NEW;
    END IF;

    UPDATE epoch_distributions ed
    SET finalized_at = v_finalized_at
    FROM indexed_vaults iv
    WHERE iv.id = NEW.vault_id
      AND ed.epoch::BIGINT = NEW.epoch
      AND (
          ed.vault_id::BIGINT = NEW.vault_id
          OR ed.vault_signature = iv.signature_hex
      )
      AND ed.finalized_at IS DISTINCT FROM v_finalized_at;

    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM vault_completions vc
        JOIN indexed_vaults iv
          ON iv.signature_hex = vc.vault_signature
        WHERE iv.id = NEW.vault_id
          AND br_settlement_week(vc.completed_at) = NEW.epoch
          AND vc.on_chain_tx IS NOT NULL
    LOOP
        PERFORM br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION br_sync_epoch_distribution_finalized_at() IS
    'After an EpochRewardsDistributed projection lands, propagate its '
    'chain-derived finalized_at to downstream read models.';

DROP TRIGGER IF EXISTS br_indexed_epoch_distribution_finalized_at_trigger
    ON indexed_epoch_distributions;

CREATE TRIGGER br_indexed_epoch_distribution_finalized_at_trigger
AFTER INSERT OR UPDATE ON indexed_epoch_distributions
FOR EACH ROW
EXECUTE FUNCTION br_sync_epoch_distribution_finalized_at();

CREATE OR REPLACE FUNCTION br_sync_vault_completion_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM br_refresh_ride_finalized_at(NEW.activity_id);
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION br_sync_vault_completion_finalized_at() IS
    'When a chain-recorded vault completion is inserted or corrected, refresh '
    'the parent ride finalization from already-indexed settlement events.';

DROP TRIGGER IF EXISTS br_vault_completion_finalized_at_trigger
    ON vault_completions;

CREATE TRIGGER br_vault_completion_finalized_at_trigger
AFTER INSERT OR UPDATE OF activity_id, completed_at, vault_signature, on_chain_tx
ON vault_completions
FOR EACH ROW
WHEN (NEW.on_chain_tx IS NOT NULL)
EXECUTE FUNCTION br_sync_vault_completion_finalized_at();
