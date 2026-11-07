-- Forward-only measured Climb-TSS CAL tribute.
-- Historical fixed-10% plans remain valid and immutable.

ALTER TABLE public.ride_economic_completion_steps
    ADD COLUMN IF NOT EXISTS segment_np_milliwatts BIGINT,
    ADD COLUMN IF NOT EXISTS segment_np_duration_s BIGINT;

ALTER TABLE public.ride_economic_plans
    DROP CONSTRAINT IF EXISTS ride_economic_plans_tribute_policy_check;

ALTER TABLE public.ride_economic_plans
    ADD CONSTRAINT ride_economic_plans_tribute_policy_check CHECK (
        (
            tribute_policy_version IS NULL
            AND exact_tribute_budget_base_units IS NULL
        )
        OR (
            tribute_policy_version = 'cal_tribute_segment_np_fixed_10pct_v1'
            AND parser_version = 5
            AND exact_tribute_budget_base_units BETWEEN
                0 AND 18446744073709551615::NUMERIC
            AND exact_tribute_budget_base_units =
                pg_catalog.trunc(exact_cal_base_units * 1000 / 10000)
        )
        OR (
            tribute_policy_version = 'cal_tribute_segment_tss_v2'
            AND parser_version = 5
            AND exact_tribute_budget_base_units BETWEEN
                0 AND exact_cal_base_units
        )
    );

ALTER TABLE public.ride_economic_completion_steps
    DROP CONSTRAINT IF EXISTS ride_economic_steps_tribute_power_check;

ALTER TABLE public.ride_economic_completion_steps
    ADD CONSTRAINT ride_economic_steps_tribute_power_check CHECK (
        (
            segment_power_metrics_version IS NULL
            AND segment_start_offset_s IS NULL
            AND segment_end_offset_s IS NULL
            AND segment_np_w IS NULL
            AND segment_np_milliwatts IS NULL
            AND segment_np_duration_s IS NULL
            AND segment_power_sample_count IS NULL
            AND segment_power_coverage_bps IS NULL
            AND tribute_weight IS NULL
        )
        OR (
            segment_power_metrics_version = 'workout_parse_metrics_v1'
            AND segment_start_offset_s BETWEEN 0 AND 4294967295
            AND segment_end_offset_s BETWEEN
                segment_start_offset_s AND 4294967295
            AND (
                segment_np_w IS NULL
                OR segment_np_w BETWEEN 0 AND 65535
            )
            AND segment_power_sample_count BETWEEN 0 AND 4294967295
            AND segment_power_coverage_bps BETWEEN 0 AND 10000
            AND tribute_weight BETWEEN 0 AND 18446744073709551615::NUMERIC
            AND (
                (
                    segment_np_milliwatts IS NULL
                    AND segment_np_duration_s IS NULL
                    AND tribute_weight = completion_time_s
                        * COALESCE(segment_np_w, 0)
                )
                OR (
                    segment_np_duration_s BETWEEN 0 AND 4294967295
                    AND segment_np_duration_s <= completion_time_s
                    AND segment_np_duration_s <=
                        segment_end_offset_s - segment_start_offset_s + 1
                    AND (
                        segment_np_milliwatts IS NULL
                        OR segment_np_milliwatts BETWEEN 0 AND 65535000
                    )
                    AND (segment_np_w IS NULL) =
                        (segment_np_milliwatts IS NULL)
                    AND (
                        segment_np_milliwatts IS NULL
                        OR segment_np_duration_s > 0
                    )
                    AND (
                        segment_np_milliwatts IS NULL
                        OR segment_np_w = pg_catalog.trunc(
                            (segment_np_milliwatts + 500) / 1000
                        )
                    )
                    AND tribute_weight = 0
                )
            )
            AND (
                (
                    segment_power_sample_count >= 30
                    AND segment_power_coverage_bps >= 5000
                )
                OR (
                    segment_np_w IS NULL
                    AND segment_np_milliwatts IS NULL
                )
            )
        )
    );

COMMENT ON COLUMN public.ride_economic_plans.exact_tribute_budget_base_units IS
    'Policy-versioned tribute total: fixed 10% for v1 history; sum of independently floored measured Climb TSS for v2.';
COMMENT ON COLUMN public.ride_economic_completion_steps.segment_np_milliwatts IS
    'Canonical Climb-window raw NP rounded once to integer milliwatts for measured-TSS verification.';
COMMENT ON COLUMN public.ride_economic_completion_steps.segment_np_duration_s IS
    'Pause-aware NP duration used by the measured Climb-TSS formula.';
COMMENT ON COLUMN public.ride_economic_completion_steps.tribute_weight IS
    'Historical v1 allocation weight; exactly zero for measured-TSS v2 plans.';

CREATE OR REPLACE FUNCTION public.br_enforce_cal_tribute_step_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.segment_power_metrics_version IS NOT NULL
       AND (
            NEW.segment_start_offset_s IS DISTINCT FROM OLD.segment_start_offset_s
            OR NEW.segment_end_offset_s IS DISTINCT FROM OLD.segment_end_offset_s
            OR NEW.segment_np_w IS DISTINCT FROM OLD.segment_np_w
            OR NEW.segment_np_milliwatts IS DISTINCT FROM OLD.segment_np_milliwatts
            OR NEW.segment_np_duration_s IS DISTINCT FROM OLD.segment_np_duration_s
            OR NEW.segment_power_sample_count IS DISTINCT FROM OLD.segment_power_sample_count
            OR NEW.segment_power_coverage_bps IS DISTINCT FROM OLD.segment_power_coverage_bps
            OR NEW.segment_power_metrics_version IS DISTINCT FROM OLD.segment_power_metrics_version
            OR NEW.tribute_weight IS DISTINCT FROM OLD.tribute_weight
            OR NEW.intensity_bps IS DISTINCT FROM OLD.intensity_bps
            OR NEW.exact_tribute_base_units IS DISTINCT FROM OLD.exact_tribute_base_units
       ) THEN
        IF OLD.segment_np_milliwatts IS NULL
           AND OLD.segment_np_duration_s IS NULL
           AND NEW.segment_np_duration_s IS NOT NULL
           AND NEW.tribute_weight = 0
           AND OLD.tribute_weight = OLD.completion_time_s
                * COALESCE(OLD.segment_np_w, 0)
           AND NEW.segment_start_offset_s IS NOT DISTINCT FROM OLD.segment_start_offset_s
           AND NEW.segment_end_offset_s IS NOT DISTINCT FROM OLD.segment_end_offset_s
           AND NEW.segment_np_w IS NOT DISTINCT FROM OLD.segment_np_w
           AND NEW.segment_power_sample_count IS NOT DISTINCT FROM OLD.segment_power_sample_count
           AND NEW.segment_power_coverage_bps IS NOT DISTINCT FROM OLD.segment_power_coverage_bps
           AND NEW.segment_power_metrics_version IS NOT DISTINCT FROM OLD.segment_power_metrics_version
           AND NEW.intensity_bps IS NOT DISTINCT FROM OLD.intensity_bps
           AND NEW.exact_tribute_base_units IS NOT DISTINCT FROM OLD.exact_tribute_base_units
           AND (NEW.segment_np_w IS NULL) =
               (NEW.segment_np_milliwatts IS NULL)
           AND EXISTS (
                SELECT 1
                FROM public.ride_economic_plans AS plan
                WHERE plan.ride_id = OLD.ride_id
                  AND plan.tribute_policy_version =
                    'cal_tribute_segment_tss_v2'
           ) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'frozen CAL tribute step evidence cannot be changed';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_ride_economic_plan_unreviewed_without_segment_tss_v2(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_unreviewed_without_segment_tss_v2;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_unreviewed_without_segment_tss_v2(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.freeze_ride_economic_plan_unreviewed(
    p_plan JSONB,
    p_steps JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride_id UUID := (p_plan->>'ride_id')::UUID;
    v_legacy_steps JSONB := '[]'::JSONB;
    v_step JSONB;
    v_legacy_weight NUMERIC;
BEGIN
    IF p_plan->>'tribute_policy_version' = 'cal_tribute_segment_tss_v2' THEN
        FOR v_step IN
            SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
        LOOP
            v_legacy_weight := public.require_ride_economic_uint(
                v_step->'completion_time_s',
                'completion_time_s',
                4294967295
            ) * CASE
                WHEN v_step->'segment_np_w' IS NULL
                  OR pg_catalog.jsonb_typeof(v_step->'segment_np_w') = 'null'
                    THEN 0
                ELSE public.require_ride_economic_uint(
                    v_step->'segment_np_w',
                    'segment_np_w',
                    65535
                )
            END;
            v_legacy_steps := v_legacy_steps || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_set(
                    v_step,
                    '{tribute_weight}',
                    pg_catalog.to_jsonb(v_legacy_weight)
                )
            );
        END LOOP;
    ELSE
        v_legacy_steps := p_steps;
    END IF;

    PERFORM public.freeze_ride_economic_plan_unreviewed_without_segment_tss_v2(
        p_plan,
        v_legacy_steps
    );

    IF p_plan->>'tribute_policy_version' = 'cal_tribute_segment_tss_v2' THEN
        UPDATE public.ride_economic_completion_steps AS target
        SET segment_np_milliwatts = CASE
                WHEN source.step->'segment_np_milliwatts' IS NULL
                  OR pg_catalog.jsonb_typeof(
                        source.step->'segment_np_milliwatts'
                     ) = 'null'
                    THEN NULL
                ELSE public.require_ride_economic_uint(
                    source.step->'segment_np_milliwatts',
                    'segment_np_milliwatts',
                    65535000
                )::BIGINT
            END,
            segment_np_duration_s = public.require_ride_economic_uint(
                source.step->'segment_np_duration_s',
                'segment_np_duration_s',
                4294967295
            )::BIGINT,
            tribute_weight = 0
        FROM pg_catalog.jsonb_array_elements(p_steps) AS source(step)
        WHERE target.ride_id = v_ride_id
          AND target.step_index = public.require_ride_economic_uint(
                source.step->'step_index',
                'step_index',
                2147483647
              )::INTEGER;
    END IF;

    RETURN public.get_ride_economic_plan(v_ride_id);
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

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
    v_step JSONB;
    v_cal NUMERIC;
    v_budget NUMERIC;
    v_ftp_w NUMERIC;
    v_np_w NUMERIC;
    v_np_mw NUMERIC;
    v_np_duration_s NUMERIC;
    v_sample_count NUMERIC;
    v_coverage_bps NUMERIC;
    v_tribute NUMERIC;
    v_expected_tribute NUMERIC;
    v_intensity_bps NUMERIC;
    v_total_tribute NUMERIC := 0;
    v_duplicate_vaults BIGINT;
    v_overlap_count BIGINT;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_ride_id::TEXT, 0)
    );

    SELECT * INTO v_existing
    FROM public.ride_economic_plans AS plan
    WHERE plan.ride_id = v_ride_id
    FOR UPDATE;

    IF FOUND AND v_existing.tribute_policy_version IS DISTINCT FROM
        'cal_tribute_segment_tss_v2' THEN
        RETURN public.freeze_ride_economic_plan_without_cal_tribute_policy(
            p_plan,
            p_steps
        );
    END IF;

    IF pg_catalog.jsonb_typeof(p_steps) <> 'array' THEN
        RAISE EXCEPTION 'ride economic completion steps must be an array';
    END IF;
    IF p_plan->>'tribute_policy_version' IS DISTINCT FROM
        'cal_tribute_segment_tss_v2' THEN
        RAISE EXCEPTION 'new ride economic plans require measured Climb-TSS policy';
    END IF;
    IF public.require_ride_economic_uint(
        p_plan->'parser_version', 'parser_version', 4294967295
    ) <> 5 THEN
        RAISE EXCEPTION 'new CAL tribute plans require parser V5 authority';
    END IF;

    v_cal := public.require_ride_economic_uint(
        p_plan->'exact_cal_base_units',
        'exact_cal_base_units',
        18446744073709551615
    );
    v_budget := public.require_ride_economic_uint(
        p_plan->'exact_tribute_budget_base_units',
        'exact_tribute_budget_base_units',
        18446744073709551615
    );
    IF v_budget > v_cal THEN
        RAISE EXCEPTION 'measured climb TSS exceeds full attested CAL';
    END IF;

    v_ftp_w := public.require_ride_economic_uint(
        p_plan->'reward_ftp_w', 'reward_ftp_w', 65535
    );
    IF v_ftp_w NOT BETWEEN 50 AND 500 THEN
        RAISE EXCEPTION 'immutable reward FTP must be between 50 and 500 watts';
    END IF;

    FOR v_step IN SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
    LOOP
        IF v_step->>'segment_power_metrics_version' IS DISTINCT FROM
            'workout_parse_metrics_v1' THEN
            RAISE EXCEPTION 'unsupported climb-window power metrics version';
        END IF;
        PERFORM public.require_ride_economic_uint(
            v_step->'completion_time_s', 'completion_time_s', 4294967295
        );
        PERFORM public.require_ride_economic_uint(
            v_step->'segment_start_offset_s', 'segment_start_offset_s', 4294967295
        );
        IF public.require_ride_economic_uint(
            v_step->'segment_end_offset_s', 'segment_end_offset_s', 4294967295
        ) < public.require_ride_economic_uint(
            v_step->'segment_start_offset_s', 'segment_start_offset_s', 4294967295
        ) THEN
            RAISE EXCEPTION 'segment end offset cannot precede its start';
        END IF;

        v_sample_count := public.require_ride_economic_uint(
            v_step->'segment_power_sample_count',
            'segment_power_sample_count',
            4294967295
        );
        v_coverage_bps := public.require_ride_economic_uint(
            v_step->'segment_power_coverage_bps',
            'segment_power_coverage_bps',
            10000
        );
        v_np_duration_s := public.require_ride_economic_uint(
            v_step->'segment_np_duration_s',
            'segment_np_duration_s',
            4294967295
        );
        IF v_np_duration_s > public.require_ride_economic_uint(
                v_step->'completion_time_s', 'completion_time_s', 4294967295
           )
           OR v_np_duration_s >
                public.require_ride_economic_uint(
                    v_step->'segment_end_offset_s',
                    'segment_end_offset_s',
                    4294967295
                )
                - public.require_ride_economic_uint(
                    v_step->'segment_start_offset_s',
                    'segment_start_offset_s',
                    4294967295
                ) + 1 THEN
            RAISE EXCEPTION 'NP duration exceeds climb window';
        END IF;
        v_np_w := CASE
            WHEN v_step->'segment_np_w' IS NULL
              OR pg_catalog.jsonb_typeof(v_step->'segment_np_w') = 'null'
                THEN NULL
            ELSE public.require_ride_economic_uint(
                v_step->'segment_np_w', 'segment_np_w', 65535
            )
        END;
        v_np_mw := CASE
            WHEN v_step->'segment_np_milliwatts' IS NULL
              OR pg_catalog.jsonb_typeof(
                    v_step->'segment_np_milliwatts'
                 ) = 'null'
                THEN NULL
            ELSE public.require_ride_economic_uint(
                v_step->'segment_np_milliwatts',
                'segment_np_milliwatts',
                65535000
            )
        END;
        IF (v_np_w IS NULL) <> (v_np_mw IS NULL) THEN
            RAISE EXCEPTION 'rounded and exact segment NP evidence must agree';
        END IF;
        IF v_np_mw IS NOT NULL AND v_np_duration_s = 0 THEN
            RAISE EXCEPTION 'frozen segment NP requires a positive NP duration';
        END IF;
        IF v_np_mw IS NOT NULL
           AND v_np_w <> pg_catalog.trunc((v_np_mw + 500) / 1000) THEN
            RAISE EXCEPTION 'rounded segment NP does not match frozen milliwatts';
        END IF;
        IF (v_sample_count < 30 OR v_coverage_bps < 5000)
           AND v_np_mw IS NOT NULL THEN
            RAISE EXCEPTION 'insufficient segment power cannot authorize tribute';
        END IF;
        IF public.require_ride_economic_uint(
            v_step->'tribute_weight', 'tribute_weight', 18446744073709551615
        ) <> 0 THEN
            RAISE EXCEPTION 'measured-TSS plans do not use allocation weights';
        END IF;

        v_intensity_bps := public.require_ride_economic_uint(
            v_step->'intensity_bps', 'intensity_bps', 13107000
        );
        IF v_intensity_bps IS DISTINCT FROM (CASE
            WHEN v_np_mw IS NULL THEN 0
            ELSE pg_catalog.trunc(v_np_mw * 10000 / (v_ftp_w * 1000))
        END) THEN
            RAISE EXCEPTION 'frozen intensity does not use immutable reward FTP';
        END IF;

        v_tribute := public.require_ride_economic_uint(
            v_step->'exact_tribute_base_units',
            'exact_tribute_base_units',
            18446744073709551615
        );
        v_expected_tribute := CASE
            WHEN v_np_mw IS NULL OR v_np_mw = 0 OR v_np_duration_s = 0 THEN 0
            ELSE pg_catalog.trunc(
                v_np_duration_s * v_np_mw * v_np_mw
                * 100 * 1000000000
                / (v_ftp_w * v_ftp_w * 1000000 * 3600)
            )
        END;
        IF v_tribute IS DISTINCT FROM v_expected_tribute THEN
            RAISE EXCEPTION 'frozen tribute does not match measured climb TSS';
        END IF;
        v_total_tribute := v_total_tribute + v_tribute;
    END LOOP;

    SELECT count(*) - count(DISTINCT public.require_ride_economic_uint(
        source.step->'vault_id', 'vault_id', 18446744073709551615
    ))
    INTO v_duplicate_vaults
    FROM pg_catalog.jsonb_array_elements(p_steps) AS source(step);
    IF v_duplicate_vaults <> 0 THEN
        RAISE EXCEPTION 'duplicate Vault in frozen CAL tribute plan';
    END IF;

    WITH windows AS (
        SELECT
            public.require_ride_economic_uint(
                source.step->'segment_start_offset_s',
                'segment_start_offset_s',
                4294967295
            ) AS start_s,
            public.require_ride_economic_uint(
                source.step->'segment_end_offset_s',
                'segment_end_offset_s',
                4294967295
            ) AS end_s
        FROM pg_catalog.jsonb_array_elements(p_steps) AS source(step)
    ), ordered AS (
        SELECT start_s, end_s, pg_catalog.lag(end_s) OVER (
            ORDER BY start_s, end_s
        ) AS previous_end_s
        FROM windows
    )
    SELECT count(*) FILTER (WHERE start_s <= previous_end_s)
    INTO v_overlap_count
    FROM ordered;
    IF v_overlap_count <> 0 THEN
        RAISE EXCEPTION 'overlapping eligible climb windows require review';
    END IF;

    IF v_total_tribute <> v_budget THEN
        RAISE EXCEPTION 'exact tribute budget does not equal measured climb sum';
    END IF;
    IF public.require_ride_economic_uint(
        p_plan->'exact_tribute_base_units',
        'exact_tribute_base_units',
        340282366920938463463374607431768211455
    ) <> v_total_tribute THEN
        RAISE EXCEPTION 'ride economic tribute total does not match measured steps';
    END IF;

    RETURN public.freeze_ride_economic_plan_without_cal_tribute_policy(
        p_plan,
        p_steps
    );
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    TO service_role;
