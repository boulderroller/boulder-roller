-- Training reading surfaces only. Never updates economic TSS, pay, plans,
-- rewards or authority. Existing migrations and parser semantics stay frozen.
-- A terminal replay row reopens only on a Training engine bump or a change to
-- the ride's stored inputs. A parser fix or a file restored at the same path
-- does not reopen it: bump the engine version or run the backfill with
-- --force-terminal.
BEGIN;
-- The rides trigger below must not queue every ride update behind a long
-- transaction during deploy; fail fast and stop the deploy instead.
SET LOCAL lock_timeout = '5s';

CREATE FUNCTION public.training_counted_statuses()
RETURNS TEXT[] LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
    SELECT ARRAY['metrics_ready','enriched','completed','under_review']::text[];
$$;
REVOKE ALL ON FUNCTION public.training_counted_statuses() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.training_counted_statuses() TO service_role;

-- NULL means retryable; otherwise this is the engine that recorded a permanent
-- refusal. Keep its error, attempt count and due time intact (including rollback).
ALTER TABLE public.training_replay_state ADD COLUMN terminal_engine_version INTEGER
    CHECK (terminal_engine_version > 0);

-- The 13 October census has 46 completed missing originals and one ParseError.
-- Failed rides stay inert under the status rule; generic APIError is not evidence
-- of a date conflict. Never delete or rewrite a ride, metric or replay receipt.
-- One-UPDATE reverse: UPDATE public.training_replay_state SET terminal_engine_version=NULL WHERE terminal_engine_version=2;
UPDATE public.training_replay_state s SET terminal_engine_version=2
FROM public.rides r WHERE r.id=s.ride_id AND r.processing_status='completed'
    AND s.error_class IN ('missing_original','FileNotFoundError','ParseError','training_date_conflict');

-- Reopen on actual scoring-input edits or a return to eligibility. No timer or
-- repair scan: updates that cannot alter the outcome leave the marker alone.
CREATE FUNCTION public.reopen_training_replay_on_input_change() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF NEW.raw_file_path IS DISTINCT FROM OLD.raw_file_path
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
       OR NEW.file_type IS DISTINCT FROM OLD.file_type
       OR (NEW.processing_status = ANY(public.training_counted_statuses())
           AND NOT coalesce(OLD.processing_status = ANY(public.training_counted_statuses()),false)) THEN
        UPDATE public.training_replay_state SET terminal_engine_version=NULL,next_attempt_at=now()
        WHERE ride_id=NEW.id AND terminal_engine_version IS NOT NULL;
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.reopen_training_replay_on_input_change() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER training_replay_input_change AFTER UPDATE OF raw_file_path,started_at,file_type,processing_status
ON public.rides FOR EACH ROW EXECUTE FUNCTION public.reopen_training_replay_on_input_change();

-- Replace the old signatures, rather than leave ambiguous PostgREST overloads.
-- Defaults keep existing callers valid during the migration-first deployment.
DROP FUNCTION public.claim_training_replay(INTEGER,TIMESTAMPTZ,UUID[]);
DROP FUNCTION public.finish_training_replay(UUID,UUID,TEXT);


CREATE OR REPLACE FUNCTION public.claim_training_replay(p_limit INTEGER DEFAULT 10,p_startup_cutoff TIMESTAMPTZ DEFAULT NULL,p_excluded_ids UUID[] DEFAULT '{}',p_engine_version INTEGER DEFAULT 2)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_rows JSONB; v_row RECORD;
BEGIN
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 THEN RAISE EXCEPTION 'invalid training batch size'; END IF;
    IF p_engine_version IS NULL OR p_engine_version < 1 THEN RAISE EXCEPTION 'invalid training engine version'; END IF;
    PERFORM pg_advisory_xact_lock(166, 1);
    v_rows := '[]'::jsonb;
    FOR v_row IN SELECT r.* FROM public.rides r JOIN public.users u ON u.id=r.user_id
        LEFT JOIN public.training_replay_state s ON s.ride_id=r.id
        LEFT JOIN public.training_pay_attempts a ON a.ride_id=r.id
        WHERE u.account_state='active'
        AND r.processing_status = ANY(public.training_counted_statuses())
        AND NOT r.id=ANY(p_excluded_ids)
        AND NOT public.training_has_payment_lease(r.id)
        AND (public.training_payment_idle(r.id) OR
            (p_startup_cutoff IS NOT NULL
             AND r.processing_status = ANY(public.training_counted_statuses())
             AND (r.phase1_completed_at IS NOT NULL OR
                  (r.processing_status = 'completed' AND a.ride_id IS NOT NULL))
             AND coalesce(greatest(r.phase1_completed_at,r.phase2_completed_at,r.phase3_completed_at),'-infinity'::timestamptz)<p_startup_cutoff
             AND (a.ride_id IS NULL OR a.started_at<p_startup_cutoff)))
        AND ((s.terminal_engine_version IS NULL AND coalesce(s.next_attempt_at,'-infinity'::timestamptz) <= now())
             OR s.terminal_engine_version < p_engine_version)
        AND coalesce((r.training_metrics->>'engine_version')::int,0)<=p_engine_version
        AND (r.training_metrics IS NULL OR coalesce((r.training_metrics->>'engine_version')::int,0)<p_engine_version
            OR (r.training_metrics->>'local_date' IS NULL AND u.training_settings_history->-1->'settings'->>'timezone' IS NOT NULL)
            OR r.training_error IS NOT NULL OR s.error_class IS NOT NULL OR EXISTS (SELECT 1 FROM public.patterns_climb p
                WHERE p.activity_id=r.id AND NOT coalesce(r.training_metrics->'climbs','{}'::jsonb) ? p.id::text))
        ORDER BY coalesce(s.next_attempt_at,'-infinity'::timestamptz),r.started_at,r.id LIMIT p_limit
    LOOP
        PERFORM 1 FROM public.users WHERE id=v_row.user_id AND account_state='active' FOR UPDATE;
        IF NOT FOUND THEN CONTINUE; END IF;
        SELECT r.* INTO v_row FROM public.rides r WHERE r.id=v_row.id FOR UPDATE;
        -- Recheck after the owner/ride locks: status, inputs or a replay receipt
        -- may have changed while this claim was waiting.
        IF NOT (v_row.processing_status = ANY(public.training_counted_statuses()))
           OR public.training_has_payment_lease(v_row.id)
           OR coalesce((v_row.training_metrics->>'engine_version')::int,0)>p_engine_version
           OR EXISTS (SELECT 1 FROM public.training_replay_state s WHERE s.ride_id=v_row.id
               AND (s.terminal_engine_version >= p_engine_version
                    OR (s.terminal_engine_version IS NULL AND s.next_attempt_at > now())))
        THEN CONTINUE; END IF;
        -- A new attempt could have begun while we waited on the owner lock.
        IF NOT public.training_payment_idle(v_row.id) THEN
            INSERT INTO public.training_pay_attempts(ride_id,token,active,phase1_completed_at,phase2_completed_at,phase3_completed_at)
                SELECT r.id,gen_random_uuid(),false,r.phase1_completed_at,r.phase2_completed_at,r.phase3_completed_at
                FROM public.rides r LEFT JOIN public.training_pay_attempts a ON a.ride_id=r.id
                WHERE r.id=v_row.id AND p_startup_cutoff IS NOT NULL
                AND r.processing_status = ANY(public.training_counted_statuses())
                AND (r.phase1_completed_at IS NOT NULL OR
                     (r.processing_status = 'completed' AND a.ride_id IS NOT NULL))
                AND coalesce(greatest(r.phase1_completed_at,r.phase2_completed_at,r.phase3_completed_at),'-infinity'::timestamptz)<p_startup_cutoff
                AND NOT public.training_has_payment_lease(r.id)
            ON CONFLICT(ride_id) DO UPDATE SET active=false,
                phase1_completed_at=excluded.phase1_completed_at,phase2_completed_at=excluded.phase2_completed_at,
                phase3_completed_at=excluded.phase3_completed_at
            WHERE public.training_pay_attempts.started_at<p_startup_cutoff;
        END IF;
        IF NOT public.training_payment_idle(v_row.id) THEN CONTINUE; END IF;
        INSERT INTO public.training_replay_state(ride_id,attempts,next_attempt_at)
            VALUES(v_row.id,1,now()+interval '10 minutes')
            ON CONFLICT(ride_id) DO UPDATE SET attempts=public.training_replay_state.attempts+1,
                next_attempt_at=excluded.next_attempt_at,terminal_engine_version=NULL;
        v_rows := v_rows || jsonb_build_array(jsonb_build_object('id',v_row.id,'user_id',v_row.user_id,
            'processing_status',v_row.processing_status,'started_at',v_row.started_at,'raw_file_path',v_row.raw_file_path,'file_type',to_jsonb(v_row)->'file_type',
            'training_metrics',v_row.training_metrics,'training_error',v_row.training_error));
    END LOOP;
    RETURN v_rows;
END $$;

CREATE FUNCTION public.finish_training_replay(p_ride_id UUID,p_user_id UUID,p_error_class TEXT,
    p_engine_version INTEGER DEFAULT 2,p_scoring_inputs JSONB DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides; v_same_inputs BOOLEAN; v_terminal INTEGER;
BEGIN
    IF p_engine_version IS NULL OR p_engine_version < 1 THEN RAISE EXCEPTION 'invalid training engine version'; END IF;
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    SELECT * INTO v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    -- A file/date edit during parsing must not terminalize the replacement input.
    -- NULL supports pre-168 clients during migration-first rollout.
    v_same_inputs := p_scoring_inputs IS NULL OR (
        v_ride.raw_file_path IS NOT DISTINCT FROM p_scoring_inputs->>'raw_file_path'
        AND v_ride.started_at IS NOT DISTINCT FROM (p_scoring_inputs->>'started_at')::timestamptz
        AND v_ride.file_type IS NOT DISTINCT FROM p_scoring_inputs->>'file_type');
    -- A delayed result must not replace a newer input's failure or shorten a
    -- newer engine's terminal fence. Its original claim lease can expire normally.
    IF NOT v_same_inputs OR EXISTS (SELECT 1 FROM public.training_replay_state
        WHERE ride_id=p_ride_id AND terminal_engine_version > p_engine_version)
    THEN RETURN; END IF;
    IF p_error_class IS NULL THEN
        -- Preserve the row while resetting retry history, as successful deletion
        -- did in 166: the next rescore's first transient failure still waits 30m.
        UPDATE public.training_replay_state SET attempts=0,error_class=NULL,terminal_engine_version=NULL,
            next_attempt_at=now() WHERE ride_id=p_ride_id;
    ELSE
        v_terminal := CASE WHEN p_error_class IN
            ('missing_original','FileNotFoundError','ParseError','training_date_conflict') THEN p_engine_version END;
        INSERT INTO public.training_replay_state(ride_id,attempts,next_attempt_at,error_class,terminal_engine_version)
        VALUES(p_ride_id,1,now()+interval '15 minutes',p_error_class,v_terminal)
        ON CONFLICT(ride_id) DO UPDATE SET error_class=excluded.error_class,
            terminal_engine_version=excluded.terminal_engine_version,
            next_attempt_at=now()+least(interval '24 hours',interval '15 minutes' *
                power(2,least(public.training_replay_state.attempts,7)));
    END IF;
END $$;
REVOKE ALL ON FUNCTION public.claim_training_replay(INTEGER,TIMESTAMPTZ,UUID[],INTEGER),
    public.finish_training_replay(UUID,UUID,TEXT,INTEGER,JSONB) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_training_replay(INTEGER,TIMESTAMPTZ,UUID[],INTEGER),
    public.finish_training_replay(UUID,UUID,TEXT,INTEGER,JSONB) TO service_role;


-- Eligibility applies before any new snapshot and to every history input.

CREATE OR REPLACE FUNCTION public.bind_ride_training_inputs(p_ride_id UUID, p_user_id UUID,
    p_started_at TIMESTAMPTZ, p_evidence JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides; v_settings JSONB; v_threshold JSONB;
    v_180 NUMERIC; v_420 NUMERIC; v_900 NUMERIC; v_cp NUMERIC;
    v_hr20 NUMERIC; v_max_hr NUMERIC; v_inputs JSONB; v_missing INTEGER; v_zone TEXT;
    v_offset INTEGER; v_zone_basis TEXT; v_local_date DATE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text, 166));
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    SELECT * INTO STRICT v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
    IF NOT (v_ride.processing_status = ANY(public.training_counted_statuses())) THEN
        RAISE EXCEPTION 'training ride ineligible';
    END IF;
    IF NOT public.training_payment_idle(p_ride_id) THEN RAISE EXCEPTION 'training payment attempt active'; END IF;
    IF v_ride.training_inputs IS NOT NULL THEN RETURN v_ride.training_inputs; END IF;
    IF p_started_at IS NULL OR (v_ride.processing_status <> 'processing'
        AND v_ride.started_at IS DISTINCT FROM p_started_at) THEN
        RAISE EXCEPTION 'training date conflict';
    END IF;
    SELECT count(*) INTO v_missing FROM public.rides r WHERE r.user_id=p_user_id
        AND r.processing_status = ANY(public.training_counted_statuses())
        AND (r.started_at,r.id)<(p_started_at,p_ride_id) AND r.training_evidence IS NULL;
    SELECT item->'settings' INTO v_settings FROM public.users u,
        LATERAL jsonb_array_elements(u.training_settings_history) item
        WHERE u.id=p_user_id AND (item->>'effective_at')::timestamptz <= p_started_at
        ORDER BY (item->>'effective_at')::timestamptz DESC LIMIT 1;
    SELECT jsonb_build_object('value', a.ftp_w, 'estimate', false,
        'basis', 'ios_threshold', 'authority_id', a.id, 'effective_at', a.effective_at)
        INTO v_threshold FROM public.reward_ftp_authorities a
        WHERE a.user_id=p_user_id AND a.effective_at <= p_started_at
          AND a.source='derived_eftp' AND a.verified_by='derived-threshold-v1'
        ORDER BY a.effective_at DESC, a.verified_at DESC, a.id DESC LIMIT 1;
    SELECT max((e->>'best_180s_w')::numeric), max((e->>'best_420s_w')::numeric),
           max((e->>'best_900s_w')::numeric), max((e->>'best_20m_hr_bpm')::numeric),
           max((e->>'max_hr_bpm')::numeric)
      INTO v_180, v_420, v_900, v_hr20, v_max_hr FROM (
        SELECT r.training_evidence e FROM public.rides r WHERE r.user_id=p_user_id
        AND r.processing_status = ANY(public.training_counted_statuses())
          AND (r.started_at,r.id)<(p_started_at,p_ride_id)
          AND r.training_evidence IS NOT NULL
        UNION ALL SELECT p_evidence
      ) evidence;
    IF v_threshold IS NULL THEN
        SELECT cp_w INTO v_cp FROM public.derive_reward_threshold_cp(v_180,v_420,v_900);
        IF v_cp BETWEEN 50 AND 500 AND public.reward_threshold_fit_is_plausible(v_180,v_420,v_900) THEN
            v_threshold := jsonb_build_object('value', round(v_cp), 'estimate', true,
                'basis', 'threshold_cp_3_7_15_v1', 'anchors_w', jsonb_build_array(v_180,v_420,v_900));
        END IF;
    END IF;
    v_zone := v_settings->>'timezone';
    IF v_zone IS NOT NULL AND coalesce(v_settings->>'timezone_source','rider') <> 'inferred' THEN
        v_zone_basis := 'rider';
        v_local_date := (p_started_at AT TIME ZONE v_zone)::date;
    ELSIF p_evidence->>'utc_offset_s' IS NOT NULL THEN
        v_zone := NULL;
        v_offset := (p_evidence->>'utc_offset_s')::integer;
        IF v_offset NOT BETWEEN -43200 AND 50400 THEN RAISE EXCEPTION 'invalid device UTC offset'; END IF;
        v_zone_basis := 'device';
        v_local_date := ((p_started_at AT TIME ZONE 'UTC') + make_interval(secs => v_offset))::date;
    ELSIF p_evidence->>'timezone' IS NOT NULL THEN
        v_zone := p_evidence->>'timezone';
        v_zone_basis := 'start_position';
        v_local_date := (p_started_at AT TIME ZONE v_zone)::date;
    ELSIF v_zone IS NOT NULL THEN
        v_zone_basis := 'inferred';
        v_local_date := (p_started_at AT TIME ZONE v_zone)::date;
    END IF;
    v_inputs := jsonb_build_object('contract_version', 1, 'started_at', p_started_at,
        'timezone', v_zone, 'timezone_basis', v_zone_basis, 'utc_offset_s', v_offset,
        'local_date', v_local_date,
        'threshold', v_threshold, 'settings', coalesce(v_settings,'{}'::jsonb),
        'history_complete', v_missing=0, 'missing_history_count', v_missing,
        'best_20m_hr_bpm', v_hr20, 'observed_max_hr_bpm', v_max_hr);
    UPDATE public.rides SET training_inputs=v_inputs, training_evidence=p_evidence WHERE id=p_ride_id;
    RETURN v_inputs;
END $$;

CREATE OR REPLACE FUNCTION public.store_ride_training_metrics(p_ride_id UUID, p_user_id UUID,
    p_inputs JSONB, p_metrics JSONB, p_evidence JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides; v_zone TEXT; v_zone_source TEXT;
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    SELECT * INTO STRICT v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
    IF NOT (v_ride.processing_status = ANY(public.training_counted_statuses())) THEN
        RAISE EXCEPTION 'training ride ineligible';
    END IF;
    IF NOT public.training_payment_idle(p_ride_id) THEN RAISE EXCEPTION 'training payment attempt active'; END IF;
    IF v_ride.training_inputs IS DISTINCT FROM p_inputs THEN
        RAISE EXCEPTION 'training input snapshot conflict';
    END IF;
    IF (p_metrics->>'engine_version')::integer IS NULL THEN RAISE EXCEPTION 'training version required'; END IF;
    IF (v_ride.training_metrics->>'engine_version')::integer > (p_metrics->>'engine_version')::integer THEN
        RAISE EXCEPTION 'training version regression';
    END IF;
    IF v_ride.training_metrics->>'local_date' IS NOT NULL THEN
        -- Replays and later preference changes cannot move a frozen date.
        p_metrics := p_metrics || jsonb_build_object(
            'local_date',v_ride.training_metrics->'local_date',
            'timezone',v_ride.training_metrics->'timezone',
            'timezone_basis',v_ride.training_metrics->'timezone_basis',
            'utc_offset_s',v_ride.training_metrics->'utc_offset_s');
    ELSIF p_metrics->>'local_date' IS NULL THEN
        SELECT training_settings_history->-1->'settings'->>'timezone',
            training_settings_history->-1->'settings'->>'timezone_source' INTO v_zone,v_zone_source
            FROM public.users WHERE id=p_user_id;
        IF v_zone IS NOT NULL THEN
            p_metrics := p_metrics || jsonb_build_object(
                'local_date',((p_inputs->>'started_at')::timestamptz AT TIME ZONE v_zone)::date,
                'timezone',v_zone,'timezone_basis',CASE WHEN v_zone_source='inferred'
                    THEN 'inferred_after_score' ELSE 'rider_setting_after_score' END,'utc_offset_s',NULL);
        END IF;
    END IF;
    IF v_ride.training_metrics IS DISTINCT FROM p_metrics OR v_ride.training_evidence IS DISTINCT FROM p_evidence OR v_ride.training_error IS NOT NULL THEN
        UPDATE public.rides SET training_metrics=p_metrics, training_evidence=p_evidence, training_error=NULL WHERE id=p_ride_id;
    END IF;
    RETURN p_metrics;
END $$;

CREATE OR REPLACE FUNCTION public.current_training_threshold(p_user_id UUID, p_as_of TIMESTAMPTZ)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_threshold JSONB; v_180 NUMERIC; v_420 NUMERIC; v_900 NUMERIC; v_cp NUMERIC;
BEGIN
    SELECT jsonb_build_object('value', a.ftp_w, 'estimate', false, 'basis', 'ios_threshold', 'authority_id', a.id)
    INTO v_threshold FROM public.reward_ftp_authorities a WHERE a.user_id=p_user_id
      AND a.effective_at<=p_as_of AND a.source='derived_eftp' AND a.verified_by='derived-threshold-v1'
    ORDER BY a.effective_at DESC, a.verified_at DESC, a.id DESC LIMIT 1;
    IF v_threshold IS NOT NULL THEN RETURN v_threshold; END IF;
    SELECT max((training_evidence->>'best_180s_w')::numeric),
           max((training_evidence->>'best_420s_w')::numeric),
           max((training_evidence->>'best_900s_w')::numeric)
    INTO v_180,v_420,v_900 FROM public.rides WHERE user_id=p_user_id AND started_at<=p_as_of
      AND processing_status = ANY(public.training_counted_statuses())
      AND training_evidence IS NOT NULL;
    SELECT cp_w INTO v_cp FROM public.derive_reward_threshold_cp(v_180,v_420,v_900);
    IF v_cp BETWEEN 50 AND 500 AND public.reward_threshold_fit_is_plausible(v_180,v_420,v_900) THEN
        RETURN jsonb_build_object('value',round(v_cp),'estimate',true,'basis','threshold_cp_3_7_15_v1');
    END IF;
    RETURN NULL;
END $$;

COMMIT;
