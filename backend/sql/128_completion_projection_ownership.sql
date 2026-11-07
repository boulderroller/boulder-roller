-- Retire backend writes to the chain-owned Vault completion total.
--
-- `vault_completions` remains backend-local, idempotent evidence. The
-- finalized TypeScript account projection is the sole writer of
-- `indexed_vaults.total_completions`, together with its `chain_slot`.

CREATE OR REPLACE FUNCTION public.record_vault_completion_projection(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_activity_id TEXT,
    p_time_seconds INTEGER DEFAULT NULL,
    p_completed_at TIMESTAMPTZ DEFAULT now(),
    p_validated BOOLEAN DEFAULT true,
    p_validation_notes TEXT DEFAULT NULL,
    p_cal_tribute NUMERIC DEFAULT 0
) RETURNS TABLE(inserted BOOLEAN, completion JSONB)
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_row public.vault_completions%ROWTYPE;
BEGIN
    INSERT INTO public.vault_completions (
        vault_signature,
        wallet,
        activity_id,
        time_seconds,
        completed_at,
        validated,
        validation_notes,
        cal_tribute,
        best_time_seconds,
        best_time_achieved_at,
        total_completions
    ) VALUES (
        p_vault_signature,
        p_wallet,
        p_activity_id,
        p_time_seconds,
        p_completed_at,
        p_validated,
        p_validation_notes,
        COALESCE(p_cal_tribute, 0),
        p_time_seconds,
        CASE WHEN p_time_seconds IS NOT NULL THEN p_completed_at ELSE NULL END,
        1
    )
    ON CONFLICT (vault_signature, activity_id) DO NOTHING
    RETURNING * INTO v_row;

    IF FOUND THEN
        RETURN QUERY SELECT true, to_jsonb(v_row);
        RETURN;
    END IF;

    SELECT *
    INTO v_row
    FROM public.vault_completions
    WHERE vault_signature = p_vault_signature
      AND activity_id = p_activity_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'vault completion projection missing after conflict: vault_signature=%, activity_id=%',
            p_vault_signature,
            p_activity_id;
    END IF;

    RETURN QUERY SELECT false, to_jsonb(v_row);
END;
$$;

COMMENT ON FUNCTION public.record_vault_completion_projection(
    TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ, BOOLEAN, TEXT, NUMERIC
) IS
'Idempotently records backend-local vault completion evidence without mutating chain-owned indexed Vault state.';

CREATE OR REPLACE FUNCTION public.reconcile_confirmed_vault_completion(
    p_ride_id UUID,
    p_lease_owner UUID,
    p_step_index INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_plan public.ride_economic_plans%ROWTYPE;
    v_step public.ride_economic_completion_steps%ROWTYPE;
    v_completion JSONB;
BEGIN
    SELECT * INTO v_plan FROM public.ride_economic_plans
    WHERE ride_id = p_ride_id
      AND state = 'cal_confirmed'
      AND lease_owner = p_lease_owner
      AND lease_expires_at > clock_timestamp();
    IF NOT FOUND THEN RETURN NULL; END IF;

    SELECT * INTO v_step FROM public.ride_economic_completion_steps
    WHERE ride_id = p_ride_id
      AND step_index = p_step_index
      AND state IN ('confirmed', 'projected')
      AND chain_confirmed_at IS NOT NULL;
    IF NOT FOUND THEN RETURN NULL; END IF;

    INSERT INTO public.vault_completions AS target (
        vault_signature, wallet, activity_id, time_seconds, completed_at,
        validated, validation_notes, cal_tribute, best_time_seconds,
        best_time_achieved_at, total_completions, on_chain_tx,
        on_chain_tx_error, chain_confirmation_status, completion_receipt_pda,
        completion_evidence_hash, chain_confirmed_at
    ) VALUES (
        v_step.vault_signature, v_plan.wallet, p_ride_id::TEXT,
        v_step.completion_time_s, v_step.completed_at, true, NULL,
        v_step.exact_tribute_base_units, v_step.completion_time_s,
        v_step.completed_at, 1, v_step.actual_tx_signature, NULL, 'confirmed',
        v_step.expected_receipt_pda, v_step.completion_evidence_hash,
        v_step.chain_confirmed_at
    )
    ON CONFLICT (vault_signature, activity_id) DO UPDATE SET
        wallet = EXCLUDED.wallet,
        time_seconds = EXCLUDED.time_seconds,
        completed_at = EXCLUDED.completed_at,
        validated = true,
        validation_notes = NULL,
        cal_tribute = EXCLUDED.cal_tribute,
        best_time_seconds = CASE
            WHEN target.best_time_seconds IS NULL
                THEN EXCLUDED.best_time_seconds
            ELSE LEAST(target.best_time_seconds, EXCLUDED.best_time_seconds)
        END,
        best_time_achieved_at = CASE
            WHEN target.best_time_seconds IS NULL
              OR EXCLUDED.best_time_seconds < target.best_time_seconds
                THEN EXCLUDED.completed_at
            ELSE target.best_time_achieved_at
        END,
        on_chain_tx = EXCLUDED.on_chain_tx,
        on_chain_tx_error = NULL,
        chain_confirmation_status = 'confirmed',
        completion_receipt_pda = EXCLUDED.completion_receipt_pda,
        completion_evidence_hash = EXCLUDED.completion_evidence_hash,
        chain_confirmed_at = EXCLUDED.chain_confirmed_at
    RETURNING to_jsonb(target) INTO v_completion;

    RETURN v_completion;
END;
$$;

COMMENT ON FUNCTION public.reconcile_confirmed_vault_completion(
    UUID, UUID, INTEGER
) IS
'Reconciles confirmed completion evidence without mutating chain-owned indexed Vault state.';

REVOKE ALL ON FUNCTION public.record_vault_completion_projection(
    TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ, BOOLEAN, TEXT, NUMERIC
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_vault_completion_projection(
    TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ, BOOLEAN, TEXT, NUMERIC
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_vault_completion_projection(
    TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ, BOOLEAN, TEXT, NUMERIC
) TO service_role;

REVOKE ALL ON FUNCTION public.reconcile_confirmed_vault_completion(
    UUID, UUID, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reconcile_confirmed_vault_completion(
    UUID, UUID, INTEGER
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_confirmed_vault_completion(
    UUID, UUID, INTEGER
) TO service_role;

CREATE OR REPLACE FUNCTION public.increment_vault_completions(
    p_signature_hex TEXT
) RETURNS VOID
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    RETURN;
END;
$$;

COMMENT ON FUNCTION public.increment_vault_completions(TEXT) IS
'Retired no-op rollout tombstone. Chain-owned Vault totals are projected only by the finalized TypeScript indexer.';

REVOKE ALL ON FUNCTION public.increment_vault_completions(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.increment_vault_completions(TEXT)
    FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.increment_vault_completions(TEXT)
    TO service_role;
