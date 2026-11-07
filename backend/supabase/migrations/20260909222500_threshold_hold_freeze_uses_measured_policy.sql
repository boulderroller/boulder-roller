-- Threshold-hold plans must freeze under the ratified measured Climb-TSS policy.
--
-- 155 renamed the then-current two-argument freeze to
-- freeze_ride_economic_plan_without_threshold_hold_atomicity and made the
-- three-argument Threshold-hold wrapper delegate to it. 157 then rewrote only
-- public.freeze_ride_economic_plan(p_plan, p_steps) for
-- cal_tribute_segment_tss_v2, so every held rider's zero-CAL parent plan still
-- hit the retired fixed-10% gate and failed with
-- "new ride economic plans require ratified CAL tribute policy". No plan was
-- ever frozen through that path; nothing stored changes here. The wrapper now
-- delegates to the current two-argument function. Its own binding checks are
-- unchanged.
CREATE OR REPLACE FUNCTION public.freeze_ride_economic_plan(
    p_plan JSONB,
    p_steps JSONB,
    p_threshold_hold JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_plan JSONB;
BEGIN
    IF p_threshold_hold IS NULL THEN
        RAISE EXCEPTION 'Threshold hold evidence is required';
    END IF;
    IF p_plan->>'reward_policy' IS DISTINCT FROM
        'threshold_provisional_hold_v1'
       OR public.require_ride_economic_uint(
            p_plan->'exact_cal_base_units',
            'exact_cal_base_units',
            18446744073709551615
          ) <> 0
       OR pg_catalog.jsonb_array_length(p_steps) <> 0 THEN
        RAISE EXCEPTION
            'Threshold hold requires one immutable zero-CAL parent plan';
    END IF;
    IF NOT (p_threshold_hold ? 'ride_id')
       OR NOT (p_threshold_hold ? 'user_id')
       OR NOT (p_threshold_hold ? 'ride_started_at')
       OR NOT (p_threshold_hold ? 'admission_plan_evidence_hash_hex')
       OR (p_threshold_hold->>'ride_id')::UUID IS DISTINCT FROM
            (p_plan->>'ride_id')::UUID
       OR (p_threshold_hold->>'user_id')::UUID IS DISTINCT FROM
            (p_plan->>'user_id')::UUID
       OR (p_threshold_hold->>'ride_started_at')::TIMESTAMPTZ IS DISTINCT FROM
            (p_plan->>'started_at')::TIMESTAMPTZ
       OR pg_catalog.decode(
            p_threshold_hold->>'admission_plan_evidence_hash_hex', 'hex'
          ) IS DISTINCT FROM pg_catalog.decode(
            p_plan->>'plan_evidence_hash_hex', 'hex'
          ) THEN
        RAISE EXCEPTION
            'Threshold hold evidence does not bind zero parent plan';
    END IF;

    -- The current policy-bearing freeze (157: cal_tribute_segment_tss_v2),
    -- not the retired fixed-10% function 155 renamed.
    v_plan := public.freeze_ride_economic_plan(p_plan, p_steps);

    IF (v_plan->>'ride_id')::UUID IS DISTINCT FROM
            (p_threshold_hold->>'ride_id')::UUID
       OR (v_plan->>'user_id')::UUID IS DISTINCT FROM
            (p_threshold_hold->>'user_id')::UUID
       OR pg_catalog.decode(v_plan->>'plan_evidence_hash_hex', 'hex')
            IS DISTINCT FROM pg_catalog.decode(
                p_threshold_hold->>'admission_plan_evidence_hash_hex', 'hex'
            ) THEN
        RAISE EXCEPTION
            'Frozen zero parent does not match Threshold hold evidence';
    END IF;

    PERFORM public.register_reward_threshold_provisional_hold(
        p_threshold_hold || pg_catalog.jsonb_build_object(
            'held_at', v_plan->'created_at'
        )
    );
    RETURN public.get_ride_economic_plan((p_plan->>'ride_id')::UUID);
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB) TO service_role;
