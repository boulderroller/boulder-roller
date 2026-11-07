-- boulderroller-v2-u4ic5: stop finalized out-of-scope vault retries and
-- durably back off transient evidence reads. No columns, payout math, claim
-- ordering, lease ownership, or confirmation rules change.

CREATE INDEX IF NOT EXISTS idx_settlement_reconciliations_job_latest
    ON public.settlement_reconciliations (job_id, created_at DESC, id DESC);

-- Read the floor without granting access to the runs table or changing claims.
CREATE OR REPLACE FUNCTION public.br_get_settlement_reconciliation_slot_floor(
    p_job_id UUID, p_lease_token UUID
) RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_floor NUMERIC(39, 0);
BEGIN
    SELECT coalesce(r.source_slot_max, 0) INTO v_floor
    FROM public.settlement_jobs j
    JOIN public.settlement_week_runs r ON r.id = j.run_id
    WHERE j.id = p_job_id AND j.state = 'reconciling'
      AND j.lease_token = p_lease_token;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement reconciliation floor fence was lost for job %', p_job_id;
    END IF;
    RETURN v_floor::TEXT;
END;
$$;

REVOKE ALL ON FUNCTION public.br_get_settlement_reconciliation_slot_floor(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.br_get_settlement_reconciliation_slot_floor(UUID, UUID)
    TO service_role;

CREATE OR REPLACE FUNCTION public.br_finish_settlement_reconciliation(
    p_job_id UUID,
    p_lease_token UUID,
    p_decision TEXT,
    p_evidence JSONB,
    p_signature_state TEXT,
    p_chain_commitment TEXT,
    p_observed_open_week TEXT DEFAULT NULL,
    p_indexed_tx_signature TEXT DEFAULT NULL,
    p_indexed_signature_finalized BOOLEAN DEFAULT FALSE,
    p_recovered_tx_signature TEXT DEFAULT NULL,
    p_error TEXT DEFAULT NULL,
    p_retry_seconds INTEGER DEFAULT 60
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_job public.settlement_jobs%ROWTYPE;
    v_open_week NUMERIC(39, 0) := CASE WHEN p_observed_open_week IS NULL THEN NULL
        ELSE public.br_parse_u64_text(p_observed_open_week, 'observed_open_week') END;
    v_signature TEXT;
    v_total_distributed NUMERIC(39, 0);
    v_absent_vault BOOLEAN;
    v_absence_slot_floor NUMERIC(39, 0);
    v_previous_evidence JSONB;
BEGIN
    IF p_decision NOT IN (
        'ready', 'confirmed', 'advanced_unproven', 'retry_wait', 'reconciling', 'blocked'
    ) THEN
        RAISE EXCEPTION 'invalid settlement reconciliation decision %', p_decision;
    END IF;
    IF p_signature_state NOT IN (
        'absent', 'pending', 'confirmed', 'finalized', 'failed', 'unknown'
    ) THEN
        RAISE EXCEPTION 'invalid settlement signature state %', p_signature_state;
    END IF;
    IF pg_catalog.jsonb_typeof(coalesce(p_evidence, '{}'::JSONB)) <> 'object' THEN
        RAISE EXCEPTION 'settlement reconciliation evidence must be a JSON object';
    END IF;

    SELECT * INTO v_job FROM public.settlement_jobs
    WHERE id = p_job_id AND state = 'reconciling' AND lease_token = p_lease_token
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement reconciliation fence was lost for job %', p_job_id;
    END IF;

    -- Absence is a review stop, including for formerly repairable jobs.
    -- Require the same finalized counter evidence as the chain reader.
    v_absent_vault := p_decision = 'blocked'
        AND p_evidence->>'absent_vault_counter_count' IS NOT NULL;
    IF v_absent_vault THEN
        -- Re-read authoritative state, not the caller's cached floor. Hold the
        -- run lock (also used by br_refresh_settlement_run) through the decision
        -- so concurrent legacy-run promotion cannot advance the floor behind it.
        SELECT coalesce(r.source_slot_max, 0) INTO STRICT v_absence_slot_floor
        FROM public.settlement_week_runs r WHERE r.id = v_job.run_id
        FOR UPDATE;
    END IF;
    IF v_absent_vault AND (
        p_chain_commitment IS DISTINCT FROM 'finalized'
        OR v_open_week IS NOT NULL
        OR p_evidence->>'read_error' IS NOT NULL
        OR v_job.vault_id IS NULL
        OR v_job.vault_id < public.br_parse_u64_text(
            p_evidence->>'absent_vault_counter_count', 'absent vault counter count'
        )
        OR coalesce(public.br_parse_u64_text(
            p_evidence->>'source_slot', 'absence source slot'
        ), 0) <= v_absence_slot_floor
    ) THEN
        RAISE EXCEPTION 'absent vault decision lacks finalized out-of-scope evidence';
    END IF;

    -- Submission attempt_count does not count reconciliation reads. Keep the
    -- previous transient delay in the existing evidence log, under this job's
    -- row lock, so retries survive restarts without touching submission fences.
    IF p_decision = 'reconciling'
       AND p_evidence->>'transient_read_failure' = 'true' THEN
        SELECT r.evidence INTO v_previous_evidence
        FROM public.settlement_reconciliations r
        WHERE r.job_id = p_job_id
        ORDER BY r.created_at DESC, r.id DESC
        LIMIT 1;
        p_retry_seconds := least(3600, greatest(60, p_retry_seconds));
        IF v_previous_evidence->>'transient_read_failure' = 'true' THEN
            p_retry_seconds := greatest(p_retry_seconds, least(3600, 2 * least(3600, greatest(30,
                coalesce((v_previous_evidence->>'retry_seconds')::INTEGER, 30)
            ))));
        END IF;
        p_evidence := p_evidence || pg_catalog.jsonb_build_object(
            'retry_seconds', p_retry_seconds
        );
    END IF;

    IF p_decision = 'confirmed' AND (
        p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week <= v_job.settlement_week
        OR NOT (
            p_signature_state = 'finalized'
            OR (
                p_indexed_signature_finalized
                AND coalesce(p_indexed_tx_signature, '') <> ''
            )
        )
    ) THEN
        RAISE EXCEPTION 'confirmed settlement decision lacks finalized matching chain evidence';
    END IF;
    IF p_decision = 'advanced_unproven' AND (
        p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week <= v_job.settlement_week
    ) THEN
        RAISE EXCEPTION 'advanced settlement closure lacks finalized vault evidence';
    END IF;
    IF p_decision IN ('ready', 'retry_wait') AND (
        v_job.legacy_evidence_only
        OR p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week NOT IN (v_job.expected_pre_open_week, v_job.settlement_week)
        OR p_signature_state NOT IN ('absent', 'failed')
        OR p_indexed_tx_signature IS NOT NULL
        OR v_job.last_error_class = 'deterministic_submit'
    ) THEN
        RAISE EXCEPTION 'settlement resend decision is not supported by finalized no-effect evidence';
    END IF;
    IF p_decision = 'ready'
       AND v_job.last_error_class IS DISTINCT FROM 'retry_recheck_required' THEN
        RAISE EXCEPTION 'settlement resend requires a fresh delayed reconciliation';
    END IF;

    v_signature := CASE
        WHEN p_decision = 'confirmed'
         AND p_indexed_signature_finalized
         AND coalesce(p_indexed_tx_signature, '') <> ''
            THEN p_indexed_tx_signature
        WHEN p_decision = 'confirmed' AND p_signature_state = 'finalized'
            THEN coalesce(
                p_recovered_tx_signature,
                v_job.tx_signature,
                v_job.prepared_tx_signature,
                p_indexed_tx_signature
            )
        ELSE coalesce(
            v_job.tx_signature,
            v_job.prepared_tx_signature,
            p_indexed_tx_signature,
            p_recovered_tx_signature
        )
    END;
    INSERT INTO public.settlement_reconciliations (
        job_id, lease_token, decision, signature_state, chain_commitment,
        observed_open_week, indexed_tx_signature, indexed_signature_finalized,
        recovered_tx_signature, evidence, error_message
    ) VALUES (
        p_job_id, p_lease_token, p_decision, p_signature_state,
        p_chain_commitment, v_open_week, p_indexed_tx_signature,
        p_indexed_signature_finalized, p_recovered_tx_signature,
        coalesce(p_evidence, '{}'::JSONB), p_error
    );

    UPDATE public.settlement_jobs
    SET state = p_decision, tx_signature = v_signature,
        terminal_evidence_quality = CASE
            WHEN p_decision = 'confirmed' AND p_indexed_signature_finalized
                THEN 'finalized_indexed_distribution'
            WHEN p_decision = 'confirmed' THEN 'finalized_signature_and_vault'
            WHEN p_decision = 'advanced_unproven' THEN 'finalized_vault_advanced_unproven'
            ELSE terminal_evidence_quality
        END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = NULL,
        next_reconcile_at = CASE WHEN p_decision IN ('retry_wait', 'reconciling')
            THEN pg_catalog.now() + pg_catalog.make_interval(
                secs => greatest(p_retry_seconds, 1)
            ) ELSE NULL END,
        confirmed_at = CASE WHEN p_decision IN ('confirmed', 'advanced_unproven')
            THEN pg_catalog.now() ELSE confirmed_at END,
        blocked_reason = CASE WHEN p_decision = 'blocked' THEN p_error
            WHEN p_decision = 'ready' THEN NULL ELSE blocked_reason END,
        last_error_class = CASE
            WHEN v_absent_vault THEN 'vault_absent_finalized'
            WHEN p_decision IN ('confirmed', 'advanced_unproven', 'ready') THEN NULL
            WHEN p_decision = 'retry_wait' THEN 'retry_recheck_required'
            WHEN p_decision = 'reconciling' THEN last_error_class
            ELSE coalesce(last_error_class, 'reconciliation_blocked')
        END,
        last_error = CASE WHEN p_decision IN ('confirmed', 'advanced_unproven', 'ready')
            THEN NULL ELSE coalesce(p_error, last_error) END,
        updated_at = pg_catalog.now()
    WHERE id = p_job_id AND lease_token = p_lease_token;

    IF p_decision = 'confirmed' THEN
        IF coalesce(v_signature, '') = '' THEN
            RAISE EXCEPTION 'confirmed settlement has no finalized transaction signature';
        END IF;
        IF p_indexed_signature_finalized
           AND p_evidence->'indexed_distribution'->>'total_distributed' IS NOT NULL THEN
            v_total_distributed := public.br_parse_u64_text(
                p_evidence->'indexed_distribution'->>'total_distributed',
                'indexed total_distributed'
            );
        END IF;
        INSERT INTO public.settlement_notification_outbox (
            job_id, vault_id, vault_signature, settlement_week,
            raw_pending_dung, total_distributed, tx_signature
        ) VALUES (
            v_job.id, v_job.vault_id, v_job.vault_signature,
            v_job.settlement_week, v_job.dung_to_mint,
            v_total_distributed, v_signature
        ) ON CONFLICT (job_id) DO NOTHING;
    END IF;

    IF p_decision = 'confirmed' AND v_job.legacy_distribution_id IS NOT NULL
       AND pg_catalog.to_regclass('public.epoch_distributions') IS NOT NULL THEN
        EXECUTE 'UPDATE public.epoch_distributions '
            'SET status = ''completed'', tx_signature = COALESCE(tx_signature, $1), '
            'processed_at = COALESCE(processed_at, now()), error_message = NULL '
            'WHERE id = $2'
        USING v_signature, v_job.legacy_distribution_id;
    END IF;

    PERFORM public.br_refresh_settlement_run(v_job.run_id);
    RETURN TRUE;
END;
$$;

REVOKE ALL ON FUNCTION public.br_finish_settlement_reconciliation(
    UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.br_finish_settlement_reconciliation(
    UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, TEXT, INTEGER
) TO service_role;
