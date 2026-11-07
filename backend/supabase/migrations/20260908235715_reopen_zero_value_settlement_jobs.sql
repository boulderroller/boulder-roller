-- H1 companion: recover unsigned plans that skipped an open week. No new states,
-- cursor rewinds, economic signatures, or changes to the original run evidence.
ALTER TABLE public.settlement_jobs
    ADD COLUMN IF NOT EXISTS open_week_recovery_evidence JSONB;

CREATE OR REPLACE FUNCTION public.br_reopen_zero_value_settlement_jobs(
    p_latest_finalizable_week TEXT,
    p_scope_evidence JSONB,
    p_jobs JSONB
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
AS $$
DECLARE
    v_cursor NUMERIC;
    v_latest NUMERIC := public.br_parse_u64_text(p_latest_finalizable_week, 'latest');
    v_count NUMERIC := public.br_parse_u64_text(p_scope_evidence->>'counter_count', 'counter');
    v_input JSONB;
    v_job public.settlement_jobs%ROWTYPE;
    v_week NUMERIC;
    v_id NUMERIC;
    v_field TEXT;
    v_changed INTEGER := 0;
BEGIN
    IF p_scope_evidence->>'commitment' IS DISTINCT FROM 'finalized'
       OR public.br_parse_u64_text(p_scope_evidence->>'source_slot_min', 'source_slot_min') > public.br_parse_u64_text(p_scope_evidence->>'source_slot_max', 'source_slot_max')
       OR jsonb_typeof(p_jobs) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_jobs) <> v_count
       OR (SELECT count(DISTINCT j->>'vault_id') FROM jsonb_array_elements(p_jobs) j) <> v_count THEN
        RAISE EXCEPTION 'recovery requires complete finalized VaultCounter scope';
    END IF;
    SELECT last_materialized_week INTO STRICT v_cursor
    FROM public.settlement_planning_state WHERE id = 1 AND bootstrap_state = 'initialized'
    FOR UPDATE;
    FOR v_input IN SELECT value FROM jsonb_array_elements(p_jobs) LOOP
        v_id := public.br_parse_u64_text(v_input->>'vault_id', 'vault_id');
        v_week := public.br_parse_u64_text(v_input->>'expected_pre_open_week', 'open_week');
        IF v_id >= v_count OR v_input->>'auto_roll_from_empty' IS DISTINCT FROM 'false'
           OR public.br_parse_u64_text(v_input->'raw_snapshot'->>'id', 'snapshot id') <> v_id
           OR public.br_parse_u64_text(v_input->'raw_snapshot'->>'open_settlement_week', 'snapshot week') <> v_week
           OR v_input->>'state' NOT IN ('ready', 'precondition_pending') THEN
            RAISE EXCEPTION 'invalid open-week recovery job';
        END IF;
        IF v_week > least(v_cursor, v_latest) THEN CONTINUE; END IF;
        SELECT * INTO v_job FROM public.settlement_jobs
        WHERE vault_id = v_id AND settlement_week = v_week
          AND source_kind = 'authoritative' AND NOT legacy_evidence_only
        FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'missing historical open-week job for vault %, week %', v_id, v_week; END IF;
        IF v_job.state NOT IN ('skipped_empty', 'blocked') THEN CONTINUE; END IF;
        -- Never turn an attempted/leased/signed economic plan into a new send.
        IF v_job.attempt_count <> 0 OR v_job.preparation_attempt_count <> 0
           OR v_job.prepared_tx_signature IS NOT NULL OR v_job.tx_signature IS NOT NULL
           OR v_job.submit_started_at IS NOT NULL OR v_job.lease_token IS NOT NULL
           OR v_job.precondition_intent IS NOT NULL OR v_job.precondition_result IS NOT NULL
           OR EXISTS (SELECT 1 FROM public.settlement_attempts WHERE job_id = v_job.id)
           OR EXISTS (SELECT 1 FROM public.settlement_notification_outbox WHERE job_id = v_job.id)
           OR (v_job.state = 'blocked' AND coalesce(v_job.blocked_reason, '') NOT LIKE 'vault open week %cannot safely reach planned week %') THEN
            CONTINUE;
        END IF;
        IF v_job.vault_signature IS DISTINCT FROM v_input->>'vault_signature' THEN
            RAISE EXCEPTION 'open-week recovery Vault identity changed';
        END IF;
        FOREACH v_field IN ARRAY ARRAY['pending_rewards','cal_tribute_accumulated',
            'pending_rewards_next_week','cal_tribute_accumulated_next','carry_record_royalty',
            'carry_stakers','carry_local_legend','carry_pol','carry_treasury'] LOOP
            IF public.br_parse_u64_text(v_input->>v_field, v_field)
               <> public.br_parse_u64_text(v_input->'raw_snapshot'->>v_field, v_field) THEN
                RAISE EXCEPTION 'recovery amount does not match snapshot';
            END IF;
        END LOOP;
        UPDATE public.settlement_jobs SET
            open_week_recovery_evidence = jsonb_build_object(
                'prior_job', to_jsonb(v_job), 'scope', p_scope_evidence,
                'latest_finalizable_week', p_latest_finalizable_week),
            state = v_input->>'state', skip_reason = NULL, blocked_reason = NULL,
            expected_pre_open_week = v_week, auto_roll_from_empty = FALSE,
            cal_to_convert = (v_input->>'cal_to_convert')::NUMERIC,
            dung_to_mint = (v_input->>'dung_to_mint')::NUMERIC,
            current_week_value = (v_input->>'current_week_value')::NUMERIC,
            next_week_value = (v_input->>'next_week_value')::NUMERIC,
            pending_rewards = (v_input->>'pending_rewards')::NUMERIC,
            cal_tribute_accumulated = (v_input->>'cal_tribute_accumulated')::NUMERIC,
            pending_rewards_next_week = (v_input->>'pending_rewards_next_week')::NUMERIC,
            cal_tribute_accumulated_next = (v_input->>'cal_tribute_accumulated_next')::NUMERIC,
            carry_record_royalty = (v_input->>'carry_record_royalty')::NUMERIC,
            carry_stakers = (v_input->>'carry_stakers')::NUMERIC,
            carry_local_legend = (v_input->>'carry_local_legend')::NUMERIC,
            carry_pol = (v_input->>'carry_pol')::NUMERIC,
            carry_treasury = (v_input->>'carry_treasury')::NUMERIC,
            raw_snapshot = v_input->'raw_snapshot', updated_at = now()
        WHERE id = v_job.id;
        PERFORM public.br_refresh_settlement_run(v_job.run_id);
        v_changed := v_changed + 1;
    END LOOP;
    RETURN v_changed;
END;
$$;
REVOKE ALL ON FUNCTION public.br_reopen_zero_value_settlement_jobs(TEXT, JSONB, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.br_reopen_zero_value_settlement_jobs(TEXT, JSONB, JSONB) TO service_role;
