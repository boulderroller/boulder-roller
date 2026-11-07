-- Repair exact Settlement Week projection identifier composition.
--
-- indexed_epoch_distributions uses NUMERIC u64 columns. Migrations 120 and 125
-- installed this helper with BIGINT arguments, so its trigger could not resolve
-- the function for NUMERIC NEW/OLD values and replay rolled back.
CREATE OR REPLACE FUNCTION public.br_refresh_distribution_dependents(
    p_vault_id NUMERIC,
    p_epoch NUMERIC
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    IF p_vault_id IS NULL
       OR p_vault_id <> trunc(p_vault_id)
       OR p_vault_id NOT BETWEEN 0 AND 18446744073709551615::NUMERIC THEN
        RAISE EXCEPTION 'vault_id must be an unsigned u64 integer'
            USING ERRCODE = '22003';
    END IF;
    IF p_epoch IS NULL
       OR p_epoch <> trunc(p_epoch)
       OR p_epoch NOT BETWEEN 0 AND 18446744073709551615::NUMERIC THEN
        RAISE EXCEPTION 'epoch must be an unsigned u64 integer'
            USING ERRCODE = '22003';
    END IF;

    SELECT MIN(distribution.finalized_at)
    INTO v_finalized_at
    FROM public.indexed_epoch_distributions AS distribution
    WHERE distribution.vault_id = p_vault_id
      AND distribution.epoch = p_epoch
      AND distribution.finalized_at IS NOT NULL;

    UPDATE public.epoch_distributions AS legacy_distribution
    SET finalized_at = v_finalized_at
    WHERE legacy_distribution.epoch::NUMERIC = p_epoch
      AND (
          legacy_distribution.vault_id::NUMERIC = p_vault_id
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
         AND vc.completion_evidence_version = 2
         AND flow.completion_evidence_version = 2
         AND vc.cal_tribute = flow.cal_tributed
        WHERE flow.vault_id = p_vault_id
          AND flow.credited_settlement_week = p_epoch
          AND vc.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
END;
$$;

COMMENT ON FUNCTION public.br_refresh_distribution_dependents(NUMERIC, NUMERIC) IS
    'Refreshes exact Settlement Week dependents using full-width u64 NUMERIC vault and week identifiers.';

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
    'Refreshes legacy and ride projections through the exact NUMERIC Settlement Week helper.';

DROP FUNCTION IF EXISTS public.br_refresh_distribution_dependents(BIGINT, BIGINT);

