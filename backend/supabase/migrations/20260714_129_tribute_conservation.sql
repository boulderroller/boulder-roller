-- Reject any frozen ride plan whose aggregate climb tribute exceeds the
-- exact CAL earned by that ride. The application normally normalizes first;
-- this boundary prevents direct RPC callers from bypassing conservation.

CREATE OR REPLACE FUNCTION public.freeze_ride_economic_plan(
    p_plan JSONB,
    p_steps JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride_id UUID := (p_plan->>'ride_id')::UUID;
    v_existing public.ride_economic_plans%ROWTYPE;
    v_observed_hash BYTEA;
    v_step JSONB;
    v_cal_budget NUMERIC(20, 0);
    v_plan_tribute NUMERIC(39, 0);
    v_step_tribute NUMERIC(39, 0) := 0;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_ride_id::TEXT, 0)
    );
    SELECT * INTO v_existing
    FROM public.ride_economic_plans
    WHERE ride_id = v_ride_id
    FOR UPDATE;

    IF NOT FOUND THEN
        IF jsonb_typeof(p_steps) <> 'array' THEN
            RAISE EXCEPTION 'ride economic completion steps must be an array';
        END IF;

        v_cal_budget := public.require_ride_economic_uint(
            p_plan->'exact_cal_base_units',
            'exact_cal_base_units',
            18446744073709551615
        );
        v_plan_tribute := public.require_ride_economic_uint(
            p_plan->'exact_tribute_base_units',
            'exact_tribute_base_units',
            340282366920938463463374607431768211455
        );
        FOR v_step IN SELECT value FROM jsonb_array_elements(p_steps)
        LOOP
            v_step_tribute := v_step_tribute + public.require_ride_economic_uint(
                v_step->'exact_tribute_base_units',
                'exact_tribute_base_units',
                18446744073709551615
            );
        END LOOP;
        IF v_step_tribute <> v_plan_tribute THEN
            RAISE EXCEPTION 'ride economic tribute total does not match frozen steps';
        END IF;
        IF v_step_tribute > v_cal_budget THEN
            RAISE EXCEPTION 'aggregate tribute exceeds exact CAL budget';
        END IF;

        RETURN public.freeze_ride_economic_plan_unreviewed(p_plan, p_steps);
    END IF;

    v_observed_hash := decode(
        lower(p_plan->>'plan_evidence_hash_hex'),
        'hex'
    );
    IF v_existing.plan_evidence_hash <> v_observed_hash THEN
        INSERT INTO public.ride_economic_plan_audits (
            ride_id, event_type, state_at_observation,
            frozen_evidence_hash, observed_evidence_hash, details
        ) VALUES (
            v_ride_id,
            CASE WHEN v_existing.state IN ('complete', 'rejected')
                THEN 'completed_plan_evidence_mismatch'
                ELSE 'nonterminal_plan_evidence_mismatch'
            END,
            v_existing.state,
            v_existing.plan_evidence_hash,
            v_observed_hash,
            jsonb_build_object(
                'reason', 'replay supplied a different frozen economic plan'
            )
        ) ON CONFLICT DO NOTHING;

        IF v_existing.state NOT IN ('complete', 'review', 'rejected') THEN
            PERFORM public.enter_ride_economic_review(
                v_ride_id,
                NULL,
                false,
                'frozen_plan_evidence_mismatch',
                'service:freeze_ride_economic_plan',
                jsonb_build_object(
                    'version', 1,
                    'kind', 'frozen_plan_evidence_mismatch',
                    'operation', 'freeze_plan',
                    'message',
                        'replay supplied a different frozen economic plan',
                    'frozen_plan_evidence_hash_hex',
                        encode(v_existing.plan_evidence_hash, 'hex'),
                    'observed_plan_evidence_hash_hex',
                        encode(v_observed_hash, 'hex'),
                    'observed_at', clock_timestamp()
                )
            );
        END IF;
    END IF;
    RETURN public.get_ride_economic_plan(v_ride_id);
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    TO service_role;
