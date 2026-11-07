-- Training reading surfaces only. Never updates economic TSS or authority.
BEGIN;
ALTER TABLE public.rides
    ADD COLUMN training_inputs JSONB,
    ADD COLUMN training_evidence JSONB,
    ADD COLUMN training_metrics JSONB,
    ADD COLUMN training_error TEXT;
ALTER TABLE public.users ADD COLUMN training_settings_history JSONB NOT NULL DEFAULT '[]';

-- Independent of ride UPDATE guards: a rejected legacy row must not starve
-- subsequent rides, even when writing its diagnostic to rides also fails.
CREATE TABLE public.training_replay_state (
    ride_id UUID PRIMARY KEY REFERENCES public.rides(id) ON DELETE CASCADE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_class TEXT
);
ALTER TABLE public.training_replay_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.training_replay_state FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.training_replay_state TO service_role;

-- Read-side attempt receipts survive successful replay. They never change pay
-- status, ACK/NAK, retry policy, plans, rewards or authority.
CREATE TABLE public.training_pay_attempts (
    ride_id UUID PRIMARY KEY REFERENCES public.rides(id) ON DELETE CASCADE,
    token UUID NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    active BOOLEAN NOT NULL,
    phase1_completed_at TIMESTAMPTZ,
    phase2_completed_at TIMESTAMPTZ,
    phase3_completed_at TIMESTAMPTZ
);
ALTER TABLE public.training_pay_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.training_pay_attempts FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.training_pay_attempts TO service_role;

CREATE FUNCTION public.training_has_payment_lease(p_ride_id UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.ride_economic_plans
        WHERE ride_id=p_ride_id AND lease_expires_at > now())
    OR EXISTS (SELECT 1 FROM public.reward_threshold_release_item_claims c
        JOIN public.reward_threshold_release_batch_items i ON i.id=c.batch_item_id
        JOIN public.reward_threshold_provisional_holds h ON h.id=i.hold_id
        WHERE h.ride_id=p_ride_id AND c.lease_expires_at > now()
          AND c.consumed_snapshot_id IS NULL AND c.terminal_disposition IS NULL)
    OR EXISTS (SELECT 1 FROM public.reward_threshold_release_executions e
        JOIN public.reward_threshold_release_snapshots s ON s.id=e.snapshot_id
        WHERE s.ride_id=p_ride_id AND e.lease_expires_at > now());
$$;

CREATE FUNCTION public.training_payment_idle(p_ride_id UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT NOT public.training_has_payment_lease(p_ride_id) AND EXISTS (
        SELECT 1 FROM public.rides r LEFT JOIN public.training_pay_attempts a ON a.ride_id=r.id
        WHERE r.id=p_ride_id AND (
            (a.ride_id IS NOT NULL AND NOT a.active
             AND r.processing_status IN ('completed','failed','metrics_ready','enriched','under_review')
             AND a.phase1_completed_at IS NOT DISTINCT FROM r.phase1_completed_at
             AND a.phase2_completed_at IS NOT DISTINCT FROM r.phase2_completed_at
             -- Durable economic recovery may finish after the upload ACK.
             AND coalesce(r.phase3_completed_at,'-infinity'::timestamptz)
                 >= coalesce(a.phase3_completed_at,'-infinity'::timestamptz))
            OR (a.ride_id IS NULL AND (r.processing_status IN ('completed','failed') OR
                (r.processing_status='under_review' AND r.phase3_completed_at IS NOT NULL
                 AND r.phase3_completed_at >= coalesce(greatest(r.phase1_completed_at,r.phase2_completed_at),'-infinity'::timestamptz))))
        ));
$$;

CREATE FUNCTION public.set_training_pay_attempt(p_ride_id UUID,p_user_id UUID,p_token UUID,p_finished BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides;
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    SELECT * INTO STRICT v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
    IF p_finished THEN
        UPDATE public.training_pay_attempts SET active=false,
            phase1_completed_at=v_ride.phase1_completed_at,phase2_completed_at=v_ride.phase2_completed_at,
            phase3_completed_at=v_ride.phase3_completed_at WHERE ride_id=p_ride_id AND token=p_token;
    ELSE
        INSERT INTO public.training_pay_attempts(ride_id,token,active) VALUES(p_ride_id,p_token,true)
        ON CONFLICT(ride_id) DO UPDATE SET token=excluded.token,active=true,started_at=clock_timestamp();
    END IF;
END $$;

-- Captured once before NATS subscribes in the deployed single-consumer process.
-- Never refresh this cutoff during a running consumer: it fences legacy/crashed
-- attempts from current work. Live ordinary and held-release leases still veto.
CREATE FUNCTION public.training_replay_startup_cutoff()
RETURNS TIMESTAMPTZ LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$ SELECT clock_timestamp(); $$;
REVOKE ALL ON FUNCTION public.training_has_payment_lease(UUID),public.training_payment_idle(UUID),
    public.set_training_pay_attempt(UUID,UUID,UUID,BOOLEAN),public.training_replay_startup_cutoff() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.training_has_payment_lease(UUID),public.training_payment_idle(UUID),
    public.set_training_pay_attempt(UUID,UUID,UUID,BOOLEAN),public.training_replay_startup_cutoff() TO service_role;

CREATE FUNCTION public.clear_training_retries_on_deletion() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    DELETE FROM public.training_replay_state s USING public.rides r
        WHERE s.ride_id=r.id AND r.user_id=NEW.id;
    DELETE FROM public.training_pay_attempts s USING public.rides r
        WHERE s.ride_id=r.id AND r.user_id=NEW.id;
    RETURN NEW;
END $$;
CREATE TRIGGER clear_training_retries_on_deletion AFTER UPDATE OF account_state ON public.users
FOR EACH ROW WHEN (NEW.account_state <> 'active') EXECUTE FUNCTION public.clear_training_retries_on_deletion();

CREATE FUNCTION public.claim_training_replay(p_limit INTEGER DEFAULT 10,p_startup_cutoff TIMESTAMPTZ DEFAULT NULL,p_excluded_ids UUID[] DEFAULT '{}')
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_rows JSONB; v_row RECORD;
BEGIN
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 THEN RAISE EXCEPTION 'invalid training batch size'; END IF;
    PERFORM pg_advisory_xact_lock(166, 1);
    v_rows := '[]'::jsonb;
    FOR v_row IN SELECT r.* FROM public.rides r JOIN public.users u ON u.id=r.user_id
        LEFT JOIN public.training_replay_state s ON s.ride_id=r.id
        LEFT JOIN public.training_pay_attempts a ON a.ride_id=r.id
        WHERE u.account_state='active'
        AND NOT r.id=ANY(p_excluded_ids)
        AND NOT public.training_has_payment_lease(r.id)
        AND (public.training_payment_idle(r.id) OR
            (p_startup_cutoff IS NOT NULL
             AND r.processing_status IN ('metrics_ready','enriched','under_review','completed','failed')
             AND (r.phase1_completed_at IS NOT NULL OR
                  (r.processing_status IN ('completed','failed') AND a.ride_id IS NOT NULL))
             AND coalesce(greatest(r.phase1_completed_at,r.phase2_completed_at,r.phase3_completed_at),'-infinity'::timestamptz)<p_startup_cutoff
             AND (a.ride_id IS NULL OR a.started_at<p_startup_cutoff)))
        AND coalesce(s.next_attempt_at,'-infinity'::timestamptz) <= now()
        AND coalesce((r.training_metrics->>'engine_version')::int,0)<=2
        AND (r.training_metrics IS NULL OR coalesce((r.training_metrics->>'engine_version')::int,0)<2
            OR (r.training_metrics->>'local_date' IS NULL AND u.training_settings_history->-1->'settings'->>'timezone' IS NOT NULL)
            OR r.training_error IS NOT NULL OR EXISTS (SELECT 1 FROM public.patterns_climb p
                WHERE p.activity_id=r.id AND NOT coalesce(r.training_metrics->'climbs','{}'::jsonb) ? p.id::text))
        ORDER BY coalesce(s.next_attempt_at,'-infinity'::timestamptz),r.started_at,r.id LIMIT p_limit
    LOOP
        PERFORM 1 FROM public.users WHERE id=v_row.user_id AND account_state='active' FOR UPDATE;
        IF NOT FOUND THEN CONTINUE; END IF;
        PERFORM 1 FROM public.rides WHERE id=v_row.id FOR UPDATE;
        -- A new attempt could have begun while we waited on the owner lock.
        IF NOT public.training_payment_idle(v_row.id) THEN
            INSERT INTO public.training_pay_attempts(ride_id,token,active,phase1_completed_at,phase2_completed_at,phase3_completed_at)
                SELECT r.id,gen_random_uuid(),false,r.phase1_completed_at,r.phase2_completed_at,r.phase3_completed_at
                FROM public.rides r LEFT JOIN public.training_pay_attempts a ON a.ride_id=r.id
                WHERE r.id=v_row.id AND p_startup_cutoff IS NOT NULL
                AND r.processing_status IN ('metrics_ready','enriched','under_review','completed','failed')
                AND (r.phase1_completed_at IS NOT NULL OR
                     (r.processing_status IN ('completed','failed') AND a.ride_id IS NOT NULL))
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
                next_attempt_at=excluded.next_attempt_at;
        v_rows := v_rows || jsonb_build_array(jsonb_build_object('id',v_row.id,'user_id',v_row.user_id,
            'started_at',v_row.started_at,'raw_file_path',v_row.raw_file_path,'file_type',to_jsonb(v_row)->'file_type',
            'training_metrics',v_row.training_metrics,'training_error',v_row.training_error));
    END LOOP;
    RETURN v_rows;
END $$;

CREATE FUNCTION public.finish_training_replay(p_ride_id UUID,p_user_id UUID,p_error_class TEXT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND OR NOT EXISTS (SELECT 1 FROM public.rides r
        WHERE r.id=p_ride_id AND r.user_id=p_user_id) THEN
        RAISE EXCEPTION 'training owner unavailable';
    END IF;
    IF p_error_class IS NULL THEN
        DELETE FROM public.training_replay_state WHERE ride_id=p_ride_id;
    ELSE
        INSERT INTO public.training_replay_state(ride_id,attempts,next_attempt_at,error_class)
        VALUES(p_ride_id,1,now()+interval '15 minutes',p_error_class)
        ON CONFLICT(ride_id) DO UPDATE SET error_class=excluded.error_class,
            next_attempt_at=now()+least(interval '24 hours',interval '15 minutes' *
                power(2,least(public.training_replay_state.attempts,7)));
    END IF;
END $$;
REVOKE ALL ON FUNCTION public.claim_training_replay(INTEGER,TIMESTAMPTZ,UUID[]),public.finish_training_replay(UUID,UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.claim_training_replay(INTEGER,TIMESTAMPTZ,UUID[]),public.finish_training_replay(UUID,UUID,TEXT) TO service_role;

CREATE FUNCTION public.append_training_settings(p_user_id UUID, p_settings JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_history JSONB;
BEGIN
    SELECT training_settings_history INTO STRICT v_history FROM public.users
    WHERE id = p_user_id AND account_state = 'active' FOR UPDATE;
    -- Only a timezone patch changes its provenance. Physiology patches retain it.
    IF p_settings ? 'timezone' AND NOT (p_settings ? 'timezone_source') THEN
        p_settings := p_settings || jsonb_build_object('timezone_source',
            CASE WHEN p_settings->>'timezone' IS NOT NULL THEN 'rider' END);
    END IF;
    -- Merge only supplied fields. NULL explicitly clears a setting.
    p_settings := jsonb_strip_nulls(coalesce(v_history->-1->'settings','{}'::jsonb) || p_settings);
    IF (p_settings->>'threshold_hr_bpm')::int > (p_settings->>'max_hr_bpm')::int
        OR (p_settings->>'resting_hr_bpm')::int >= (p_settings->>'threshold_hr_bpm')::int
        OR (p_settings->>'resting_hr_bpm')::int >= (p_settings->>'max_hr_bpm')::int THEN
        RAISE EXCEPTION 'invalid training physiology';
    END IF;
    IF v_history->-1->'settings' = p_settings THEN RETURN v_history->-1; END IF;
    v_history := v_history || jsonb_build_array(jsonb_build_object(
        'effective_at', clock_timestamp(), 'settings', p_settings));
    UPDATE public.users SET training_settings_history = v_history WHERE id = p_user_id;
    RETURN v_history->-1;
END $$;

-- The owner's clients may initialize a missing preference, never replace one.
-- This supplies missing indoor dates without rewriting dated ride snapshots.
CREATE FUNCTION public.initialize_training_timezone(p_user_id UUID, p_timezone TEXT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_history JSONB;
BEGIN
    IF p_timezone IS NULL OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name=p_timezone) THEN
        RAISE EXCEPTION 'invalid training timezone';
    END IF;
    SELECT training_settings_history INTO STRICT v_history FROM public.users
        WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF v_history->-1->'settings'->>'timezone' IS NOT NULL THEN
        RETURN v_history->-1->'settings';
    END IF;
    RETURN public.append_training_settings(p_user_id,jsonb_build_object(
        'timezone',p_timezone,'timezone_source','inferred'))->'settings';
END $$;
REVOKE ALL ON FUNCTION public.initialize_training_timezone(UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.initialize_training_timezone(UUID,TEXT) TO service_role;

-- Existing CP fit is reused, never its admission/sealing/write path.
CREATE FUNCTION public.bind_ride_training_inputs(p_ride_id UUID, p_user_id UUID,
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
    IF NOT public.training_payment_idle(p_ride_id) THEN RAISE EXCEPTION 'training payment attempt active'; END IF;
    IF v_ride.training_inputs IS NOT NULL THEN RETURN v_ride.training_inputs; END IF;
    IF p_started_at IS NULL OR (v_ride.processing_status <> 'processing'
        AND v_ride.started_at IS DISTINCT FROM p_started_at) THEN
        RAISE EXCEPTION 'training date conflict';
    END IF;
    SELECT count(*) INTO v_missing FROM public.rides r WHERE r.user_id=p_user_id
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

CREATE FUNCTION public.store_ride_training_metrics(p_ride_id UUID, p_user_id UUID,
    p_inputs JSONB, p_metrics JSONB, p_evidence JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides; v_zone TEXT; v_zone_source TEXT;
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'training owner unavailable'; END IF;
    SELECT * INTO STRICT v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
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

CREATE FUNCTION public.current_training_threshold(p_user_id UUID, p_as_of TIMESTAMPTZ)
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
      AND training_evidence IS NOT NULL;
    SELECT cp_w INTO v_cp FROM public.derive_reward_threshold_cp(v_180,v_420,v_900);
    IF v_cp BETWEEN 50 AND 500 AND public.reward_threshold_fit_is_plausible(v_180,v_420,v_900) THEN
        RETURN jsonb_build_object('value',round(v_cp),'estimate',true,'basis','threshold_cp_3_7_15_v1');
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.current_training_threshold(UUID,TIMESTAMPTZ) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.current_training_threshold(UUID,TIMESTAMPTZ) TO service_role;

CREATE FUNCTION public.guard_training_inputs() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF OLD.training_inputs IS NOT NULL AND NEW.training_inputs IS DISTINCT FROM OLD.training_inputs THEN
        RAISE EXCEPTION 'training inputs are frozen';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER training_inputs_frozen BEFORE UPDATE ON public.rides
FOR EACH ROW EXECUTE FUNCTION public.guard_training_inputs();

REVOKE ALL ON FUNCTION public.append_training_settings(UUID,JSONB),
    public.bind_ride_training_inputs(UUID,UUID,TIMESTAMPTZ,JSONB),
    public.store_ride_training_metrics(UUID,UUID,JSONB,JSONB,JSONB) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.append_training_settings(UUID,JSONB),
    public.bind_ride_training_inputs(UUID,UUID,TIMESTAMPTZ,JSONB),
    public.store_ride_training_metrics(UUID,UUID,JSONB,JSONB,JSONB) TO service_role;
COMMIT;
