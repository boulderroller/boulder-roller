-- ============================================================================
-- Exact credited Settlement Flow projection
-- ============================================================================
-- A completion's historical ride week is not necessarily the Settlement Flow
-- that received its tribute. This projection records the exact on-chain flow
-- assignment and keeps rides.finalized_at NULL until every confirmed completion
-- has exact evidence and every positive-tribute flow has a finalized distribution.
-- All-zero rides have no payout finality timestamp and remain NULL.
-- No historical attribution is inferred or backfilled here.
-- ============================================================================

DO $$
BEGIN
    IF pg_catalog.to_regclass('public.indexed_events') IS NOT NULL THEN
        ALTER TABLE public.indexed_events
            ALTER COLUMN vault_id TYPE NUMERIC(20, 0)
            USING vault_id::NUMERIC;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.indexed_climb_completion_flows (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL CHECK (event_index >= 0),
    vault_id NUMERIC(20, 0) NOT NULL
        CHECK (vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC),
    ride_attestation TEXT NOT NULL CHECK (ride_attestation <> ''),
    completion_evidence_hash BYTEA NOT NULL
        CHECK (octet_length(completion_evidence_hash) = 32),
    credited_settlement_week NUMERIC(20, 0) NOT NULL
        CHECK (credited_settlement_week BETWEEN 0 AND 18446744073709551615::NUMERIC),
    cal_tributed NUMERIC(39, 0) NOT NULL
        CHECK (cal_tributed BETWEEN 0 AND 18446744073709551615::NUMERIC),
    slot NUMERIC(39, 0) NOT NULL
        CHECK (slot BETWEEN 0 AND 18446744073709551615::NUMERIC),
    block_time BIGINT CHECK (block_time IS NULL OR block_time >= 0),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_signature, event_index),
    UNIQUE (completion_evidence_hash)
);

CREATE INDEX IF NOT EXISTS idx_climb_completion_flows_vault_week
    ON public.indexed_climb_completion_flows (
        vault_id,
        credited_settlement_week
    );

CREATE INDEX IF NOT EXISTS idx_climb_completion_flows_ride_attestation
    ON public.indexed_climb_completion_flows (ride_attestation);

COMMENT ON TABLE public.indexed_climb_completion_flows IS
    'Immutable chain projection assigning each completion evidence hash to the exact Settlement Flow that received its tribute. The indexer is the only writer.';

CREATE OR REPLACE FUNCTION public.br_enforce_completion_flow_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'immutable completion-flow evidence cannot be deleted';
    END IF;

    IF NEW.tx_signature IS DISTINCT FROM OLD.tx_signature
       OR NEW.event_index IS DISTINCT FROM OLD.event_index
       OR NEW.vault_id IS DISTINCT FROM OLD.vault_id
       OR NEW.ride_attestation IS DISTINCT FROM OLD.ride_attestation
       OR NEW.completion_evidence_hash IS DISTINCT FROM OLD.completion_evidence_hash
       OR NEW.credited_settlement_week IS DISTINCT FROM OLD.credited_settlement_week
       OR NEW.cal_tributed IS DISTINCT FROM OLD.cal_tributed THEN
        RAISE EXCEPTION 'immutable completion-flow evidence cannot be changed';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_completion_flow_immutability
    ON public.indexed_climb_completion_flows;
CREATE TRIGGER br_completion_flow_immutability
BEFORE UPDATE OR DELETE ON public.indexed_climb_completion_flows
FOR EACH ROW
EXECUTE FUNCTION public.br_enforce_completion_flow_immutability();

CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(p_activity_id TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
BEGIN
    IF p_activity_id IS NULL OR p_activity_id = '' THEN
        RETURN;
    END IF;

    WITH confirmed_completions AS (
        SELECT
            vc.completion_evidence_hash,
            iv.id AS vault_id
        FROM public.vault_completions AS vc
        LEFT JOIN public.indexed_vaults AS iv
          ON iv.signature_hex = vc.vault_signature
        WHERE vc.activity_id = p_activity_id
          AND vc.chain_confirmation_status = 'confirmed'
    )
    SELECT CASE
        WHEN COUNT(*) > 0
         AND COUNT(flow.credited_settlement_week) = COUNT(*)
         AND COUNT(*) FILTER (WHERE flow.cal_tributed > 0) > 0
         AND COUNT(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
             = COUNT(*) FILTER (WHERE flow.cal_tributed > 0)
            THEN MAX(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
        ELSE NULL
    END
    INTO v_finalized_at
    FROM confirmed_completions AS completion
    LEFT JOIN public.indexed_climb_completion_flows AS flow
      ON flow.completion_evidence_hash = completion.completion_evidence_hash
     AND flow.vault_id = completion.vault_id
    LEFT JOIN LATERAL (
        SELECT MIN(indexed_distribution.finalized_at) AS finalized_at
        FROM public.indexed_epoch_distributions AS indexed_distribution
        WHERE indexed_distribution.vault_id = flow.vault_id
          AND indexed_distribution.epoch = flow.credited_settlement_week
          AND indexed_distribution.finalized_at IS NOT NULL
    ) AS distribution ON true;

    UPDATE public.rides
    SET finalized_at = v_finalized_at
    WHERE id::TEXT = p_activity_id
      AND finalized_at IS DISTINCT FROM v_finalized_at;
END;
$$;

COMMENT ON FUNCTION public.br_refresh_ride_finalized_at(TEXT) IS
    'Derives rides.finalized_at only when every confirmed completion has exact flow evidence and every positive-tribute flow has finalized. All-zero rides and historical rows without evidence remain NULL.';

CREATE OR REPLACE FUNCTION public.br_refresh_distribution_dependents(
    p_vault_id BIGINT,
    p_epoch BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    SELECT MIN(distribution.finalized_at)
    INTO v_finalized_at
    FROM public.indexed_epoch_distributions AS distribution
    WHERE distribution.vault_id = p_vault_id
      AND distribution.epoch = p_epoch
      AND distribution.finalized_at IS NOT NULL;

    -- Preserve the legacy queue projection while the chain event remains the
    -- source of its finalization timestamp. Removal or correction clears stale
    -- finality when no matching chain distribution remains.
    UPDATE public.epoch_distributions AS legacy_distribution
    SET finalized_at = v_finalized_at
    WHERE legacy_distribution.epoch::BIGINT = p_epoch
      AND (
          legacy_distribution.vault_id::BIGINT = p_vault_id
          OR EXISTS (
              SELECT 1
              FROM public.indexed_vaults AS indexed_vault
              WHERE indexed_vault.id = p_vault_id
                AND legacy_distribution.vault_signature = indexed_vault.signature_hex
          )
      )
      AND legacy_distribution.finalized_at IS DISTINCT FROM v_finalized_at;

    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM public.indexed_climb_completion_flows AS flow
        JOIN public.indexed_vaults AS iv
          ON iv.id = flow.vault_id
        JOIN public.vault_completions AS vc
          ON vc.completion_evidence_hash = flow.completion_evidence_hash
         AND vc.vault_signature = iv.signature_hex
        WHERE flow.vault_id = p_vault_id
          AND flow.credited_settlement_week = p_epoch
          AND vc.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;

END;
$$;

CREATE OR REPLACE FUNCTION public.br_sync_epoch_distribution_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP <> 'DELETE' THEN
        PERFORM public.br_refresh_distribution_dependents(NEW.vault_id, NEW.epoch);
    END IF;

    IF TG_OP = 'DELETE' THEN
        PERFORM public.br_refresh_distribution_dependents(OLD.vault_id, OLD.epoch);
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE'
       AND (
           OLD.vault_id IS DISTINCT FROM NEW.vault_id
           OR OLD.epoch IS DISTINCT FROM NEW.epoch
       ) THEN
        PERFORM public.br_refresh_distribution_dependents(OLD.vault_id, OLD.epoch);
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.br_sync_epoch_distribution_finalized_at() IS
    'Refreshes legacy and ride projections when an exact credited Settlement Flow distribution is indexed.';

DROP TRIGGER IF EXISTS br_indexed_epoch_distribution_finalized_at_trigger
    ON public.indexed_epoch_distributions;
CREATE TRIGGER br_indexed_epoch_distribution_finalized_at_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.indexed_epoch_distributions
FOR EACH ROW
EXECUTE FUNCTION public.br_sync_epoch_distribution_finalized_at();

CREATE OR REPLACE FUNCTION public.br_sync_completion_flow_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_activity_id TEXT;
BEGIN
    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM public.indexed_vaults AS iv
        JOIN public.vault_completions AS vc
          ON vc.vault_signature = iv.signature_hex
        WHERE iv.id = NEW.vault_id
          AND vc.completion_evidence_hash = NEW.completion_evidence_hash
          AND vc.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.br_sync_completion_flow_finalized_at() IS
    'Refreshes matching rides when immutable exact credited-flow evidence arrives after a confirmed completion.';

DROP TRIGGER IF EXISTS br_completion_flow_finalized_at_trigger
    ON public.indexed_climb_completion_flows;
CREATE TRIGGER br_completion_flow_finalized_at_trigger
AFTER INSERT OR UPDATE ON public.indexed_climb_completion_flows
FOR EACH ROW
EXECUTE FUNCTION public.br_sync_completion_flow_finalized_at();

CREATE OR REPLACE FUNCTION public.br_sync_vault_completion_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM public.br_refresh_ride_finalized_at(OLD.activity_id);
        RETURN OLD;
    END IF;

    PERFORM public.br_refresh_ride_finalized_at(NEW.activity_id);

    IF TG_OP = 'UPDATE'
       AND OLD.activity_id IS DISTINCT FROM NEW.activity_id THEN
        PERFORM public.br_refresh_ride_finalized_at(OLD.activity_id);
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.br_sync_vault_completion_finalized_at() IS
    'Refreshes ride finalization whenever confirmed-completion membership or exact evidence matching can change.';

DROP TRIGGER IF EXISTS br_vault_completion_finalized_at_trigger
    ON public.vault_completions;
CREATE TRIGGER br_vault_completion_finalized_at_trigger
AFTER INSERT OR UPDATE OR DELETE ON public.vault_completions
FOR EACH ROW
EXECUTE FUNCTION public.br_sync_vault_completion_finalized_at();

-- Replace any historical-week finalization already written by the superseded
-- projection. Exact evidence may restore it later through the normal triggers;
-- absent evidence remains honestly pending.
DO $$
DECLARE
    v_activity_id TEXT;
BEGIN
    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM public.vault_completions AS vc
        WHERE vc.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
END;
$$;
