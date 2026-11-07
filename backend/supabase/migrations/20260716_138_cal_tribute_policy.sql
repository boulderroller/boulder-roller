-- Ratified fixed-budget CAL tribute policy and climb-window power evidence.
--
-- Historical completed plans remain byte-for-byte frozen. Nonterminal plans
-- without this policy enter review instead of being reinterpreted.

-- Parser V5 preserves V4 source, canonical-field, and geographic matching
-- semantics while binding the authoritative climb-window power metrics used
-- by this tribute policy. Older pipeline rows remain immutable replay sources.
DO $$
DECLARE
    v_template public.pipeline_versions%ROWTYPE;
    v_existing public.pipeline_versions%ROWTYPE;
    v_conflict_count INTEGER;
    v_v5_id INTEGER;
BEGIN
    SELECT count(*) INTO v_conflict_count
    FROM public.pipeline_versions
    WHERE parser_version = '5-ftp-v1'
       OR ride_parser_version = 5;

    IF v_conflict_count > 1 THEN
        RAISE EXCEPTION 'multiple parser V5 pipeline provenance rows exist';
    END IF;

    SELECT * INTO v_existing
    FROM public.pipeline_versions
    WHERE parser_version = '5-ftp-v1'
       OR ride_parser_version = 5
    ORDER BY id DESC
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.parser_version IS DISTINCT FROM '5-ftp-v1'
           OR v_existing.ride_parser_version IS DISTINCT FROM 5
           OR v_existing.detector_algorithm IS DISTINCT FROM 'canonical_v2'
           OR v_existing.detector_version IS DISTINCT FROM '2.0.0'
           OR v_existing.detector_params_hash IS DISTINCT FROM
              'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2'
           OR v_existing.sig_format_version IS DISTINCT FROM 'v2'
           OR v_existing.sig_match_version IS DISTINCT FROM
              'dct6-h3r7-geometry25-oriented150-sim090'
           OR v_existing.economics_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR v_existing.policy_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR btrim(v_existing.git_commit) IS DISTINCT FROM
              '73bfee87359b0573014c16674e36ae6639a0276f' THEN
            RAISE EXCEPTION 'parser V5 pipeline provenance conflict';
        END IF;
        IF v_existing.deactivated_at IS NOT NULL THEN
            RAISE EXCEPTION
                'parser V5 pipeline version is inactive and cannot be reactivated';
        END IF;
        v_v5_id := v_existing.id;
    ELSE
        SELECT * INTO v_template
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY activated_at DESC, id DESC
        LIMIT 1;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'cannot register parser V5 without active V4 provenance';
        END IF;
        IF v_template.parser_version IS DISTINCT FROM '4-ftp-v1'
           OR v_template.ride_parser_version IS DISTINCT FROM 4
           OR v_template.detector_algorithm IS DISTINCT FROM 'canonical_v2'
           OR v_template.detector_version IS DISTINCT FROM '2.0.0'
           OR v_template.detector_params_hash IS DISTINCT FROM
              'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2'
           OR v_template.sig_format_version IS DISTINCT FROM 'v2'
           OR v_template.sig_match_version IS DISTINCT FROM
              'dct6-h3r7-geometry25-oriented150-sim090'
           OR v_template.economics_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR v_template.policy_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR btrim(v_template.git_commit) IS DISTINCT FROM
              'bb7604ddc0af3f983d0a21191bf27bddfa463e80' THEN
            RAISE EXCEPTION 'parser V5 requires the exact active V4 authority';
        END IF;

        UPDATE public.pipeline_versions
        SET deactivated_at = now()
        WHERE deactivated_at IS NULL;

        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version,
            detector_params_hash, sig_format_version, sig_match_version,
            economics_version, integrity_version, git_commit, activated_at,
            deactivated_at, notes, ride_parser_version, policy_version
        ) VALUES (
            '5-ftp-v1', 'canonical_v2', '2.0.0',
            'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2',
            'v2', 'dct6-h3r7-geometry25-oriented150-sim090',
            'ride_effort_policy_2026_07_14_ftp_v1',
            v_template.integrity_version,
            '73bfee87359b0573014c16674e36ae6639a0276f',
            now(), NULL,
            'Parser V5: V4 canonical climb authority plus canonical climb-window power metrics.',
            5, 'ride_effort_policy_2026_07_14_ftp_v1'
        ) RETURNING id INTO v_v5_id;
    END IF;

    UPDATE public.pipeline_versions
    SET deactivated_at = now()
    WHERE deactivated_at IS NULL AND id <> v_v5_id;
END;
$$;

ALTER TABLE public.ride_economic_plans
    ADD COLUMN IF NOT EXISTS tribute_policy_version TEXT,
    ADD COLUMN IF NOT EXISTS exact_tribute_budget_base_units NUMERIC(20, 0);

ALTER TABLE public.ride_economic_completion_steps
    DROP CONSTRAINT IF EXISTS ride_economic_completion_steps_intensity_bps_check;

ALTER TABLE public.ride_economic_completion_steps
    ADD COLUMN IF NOT EXISTS segment_start_offset_s BIGINT,
    ADD COLUMN IF NOT EXISTS segment_end_offset_s BIGINT,
    ADD COLUMN IF NOT EXISTS segment_np_w INTEGER,
    ADD COLUMN IF NOT EXISTS segment_power_sample_count BIGINT,
    ADD COLUMN IF NOT EXISTS segment_power_coverage_bps INTEGER,
    ADD COLUMN IF NOT EXISTS segment_power_metrics_version TEXT,
    ADD COLUMN IF NOT EXISTS tribute_weight NUMERIC(20, 0);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_plans'::regclass
          AND conname = 'ride_economic_plans_tribute_policy_check'
    ) THEN
        ALTER TABLE public.ride_economic_plans
            ADD CONSTRAINT ride_economic_plans_tribute_policy_check CHECK (
                (
                    tribute_policy_version IS NULL
                    AND exact_tribute_budget_base_units IS NULL
                )
                OR (
                    tribute_policy_version =
                        'cal_tribute_segment_np_fixed_10pct_v1'
                    AND parser_version = 5
                    AND exact_tribute_budget_base_units BETWEEN
                        0 AND 18446744073709551615::NUMERIC
                    AND exact_tribute_budget_base_units =
                        trunc(exact_cal_base_units * 1000 / 10000)
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_completion_steps'::regclass
          AND conname = 'ride_economic_steps_intensity_bps_check'
    ) THEN
        ALTER TABLE public.ride_economic_completion_steps
            ADD CONSTRAINT ride_economic_steps_intensity_bps_check
            CHECK (intensity_bps BETWEEN 0 AND 13107000);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_completion_steps'::regclass
          AND conname = 'ride_economic_steps_tribute_power_check'
    ) THEN
        ALTER TABLE public.ride_economic_completion_steps
            ADD CONSTRAINT ride_economic_steps_tribute_power_check CHECK (
                (
                    segment_power_metrics_version IS NULL
                    AND segment_start_offset_s IS NULL
                    AND segment_end_offset_s IS NULL
                    AND segment_np_w IS NULL
                    AND segment_power_sample_count IS NULL
                    AND segment_power_coverage_bps IS NULL
                    AND tribute_weight IS NULL
                )
                OR (
                    segment_power_metrics_version =
                        'workout_parse_metrics_v1'
                    AND segment_start_offset_s BETWEEN 0 AND 4294967295
                    AND segment_end_offset_s BETWEEN
                        segment_start_offset_s AND 4294967295
                    AND (
                        segment_np_w IS NULL
                        OR segment_np_w BETWEEN 0 AND 65535
                    )
                    AND segment_power_sample_count BETWEEN 0 AND 4294967295
                    AND segment_power_coverage_bps BETWEEN 0 AND 10000
                    AND tribute_weight BETWEEN
                        0 AND 18446744073709551615::NUMERIC
                    AND tribute_weight =
                        completion_time_s * COALESCE(segment_np_w, 0)
                    AND (
                        (
                            segment_power_sample_count >= 30
                            AND segment_power_coverage_bps >= 5000
                        )
                        OR segment_np_w IS NULL
                    )
                )
            );
    END IF;
END;
$$;
COMMENT ON COLUMN public.ride_economic_plans.tribute_policy_version IS
    'Frozen CAL tribute allocation policy; NULL only for historical plans.';
COMMENT ON COLUMN public.ride_economic_plans.exact_tribute_budget_base_units IS
    'floor(exact CAL * 1000 / 10000), distributed only across positive eligible climb weights.';
COMMENT ON COLUMN public.ride_economic_completion_steps.segment_np_w IS
    'Canonical climb-window NP; NULL when power evidence is missing or insufficient.';
COMMENT ON COLUMN public.ride_economic_completion_steps.tribute_weight IS
    'Exact completion_time_s * segment_np_w allocation weight.';

CREATE OR REPLACE FUNCTION public.br_enforce_cal_tribute_plan_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.tribute_policy_version IS NOT NULL
       AND (
            NEW.tribute_policy_version IS DISTINCT FROM
                OLD.tribute_policy_version
            OR NEW.exact_tribute_budget_base_units IS DISTINCT FROM
                OLD.exact_tribute_budget_base_units
       ) THEN
        RAISE EXCEPTION 'frozen CAL tribute policy cannot be changed';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ride_economic_plan_cal_tribute_immutable
    ON public.ride_economic_plans;
CREATE TRIGGER trg_ride_economic_plan_cal_tribute_immutable
    BEFORE UPDATE ON public.ride_economic_plans
    FOR EACH ROW
    EXECUTE FUNCTION public.br_enforce_cal_tribute_plan_immutability();

CREATE OR REPLACE FUNCTION public.br_enforce_cal_tribute_step_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.segment_power_metrics_version IS NOT NULL
       AND (
            NEW.segment_start_offset_s IS DISTINCT FROM
                OLD.segment_start_offset_s
            OR NEW.segment_end_offset_s IS DISTINCT FROM
                OLD.segment_end_offset_s
            OR NEW.segment_np_w IS DISTINCT FROM OLD.segment_np_w
            OR NEW.segment_power_sample_count IS DISTINCT FROM
                OLD.segment_power_sample_count
            OR NEW.segment_power_coverage_bps IS DISTINCT FROM
                OLD.segment_power_coverage_bps
            OR NEW.segment_power_metrics_version IS DISTINCT FROM
                OLD.segment_power_metrics_version
            OR NEW.tribute_weight IS DISTINCT FROM OLD.tribute_weight
            OR NEW.intensity_bps IS DISTINCT FROM OLD.intensity_bps
            OR NEW.exact_tribute_base_units IS DISTINCT FROM
                OLD.exact_tribute_base_units
       ) THEN
        RAISE EXCEPTION 'frozen CAL tribute step evidence cannot be changed';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ride_economic_step_cal_tribute_immutable
    ON public.ride_economic_completion_steps;
CREATE TRIGGER trg_ride_economic_step_cal_tribute_immutable
    BEFORE UPDATE ON public.ride_economic_completion_steps
    FOR EACH ROW
    EXECUTE FUNCTION public.br_enforce_cal_tribute_step_immutability();

DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_ride_economic_plan_unreviewed_without_cal_tribute_policy(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION
            public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
            RENAME TO
                freeze_ride_economic_plan_unreviewed_without_cal_tribute_policy;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_unreviewed_without_cal_tribute_policy(
        JSONB, JSONB
    )
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
BEGIN
    PERFORM
        public.freeze_ride_economic_plan_unreviewed_without_cal_tribute_policy(
            p_plan,
            p_steps
        );

    UPDATE public.ride_economic_plans AS plan
    SET tribute_policy_version = p_plan->>'tribute_policy_version',
        exact_tribute_budget_base_units =
            public.require_ride_economic_uint(
                p_plan->'exact_tribute_budget_base_units',
                'exact_tribute_budget_base_units',
                18446744073709551615
            )
    WHERE plan.ride_id = v_ride_id
      AND plan.tribute_policy_version IS NULL;

    UPDATE public.ride_economic_completion_steps AS target
    SET segment_start_offset_s = public.require_ride_economic_uint(
            source.step->'segment_start_offset_s',
            'segment_start_offset_s',
            4294967295
        )::BIGINT,
        segment_end_offset_s = public.require_ride_economic_uint(
            source.step->'segment_end_offset_s',
            'segment_end_offset_s',
            4294967295
        )::BIGINT,
        segment_np_w = CASE
            WHEN source.step->'segment_np_w' IS NULL
              OR jsonb_typeof(source.step->'segment_np_w') = 'null'
                THEN NULL
            ELSE public.require_ride_economic_uint(
                source.step->'segment_np_w',
                'segment_np_w',
                65535
            )::INTEGER
        END,
        segment_power_sample_count = public.require_ride_economic_uint(
            source.step->'segment_power_sample_count',
            'segment_power_sample_count',
            4294967295
        )::BIGINT,
        segment_power_coverage_bps = public.require_ride_economic_uint(
            source.step->'segment_power_coverage_bps',
            'segment_power_coverage_bps',
            10000
        )::INTEGER,
        segment_power_metrics_version =
            source.step->>'segment_power_metrics_version',
        tribute_weight = public.require_ride_economic_uint(
            source.step->'tribute_weight',
            'tribute_weight',
            18446744073709551615
        )
    FROM jsonb_array_elements(p_steps) AS source(step)
    WHERE target.ride_id = v_ride_id
      AND target.step_index = public.require_ride_economic_uint(
            source.step->'step_index',
            'step_index',
            2147483647
          )::INTEGER
      AND target.segment_power_metrics_version IS NULL;

    RETURN public.get_ride_economic_plan(v_ride_id);
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_ride_economic_plan_without_cal_tribute_policy(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_without_cal_tribute_policy;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_without_cal_tribute_policy(JSONB, JSONB)
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
    v_submitted_budget NUMERIC;
    v_ftp_w NUMERIC;
    v_time_s NUMERIC;
    v_np_w NUMERIC;
    v_sample_count NUMERIC;
    v_coverage_bps NUMERIC;
    v_weight NUMERIC;
    v_expected_weight NUMERIC;
    v_intensity_bps NUMERIC;
    v_expected_intensity_bps NUMERIC;
    v_total_weight NUMERIC := 0;
    v_expected_total NUMERIC := 0;
    v_plan_total NUMERIC;
    v_duplicate_vaults BIGINT;
    v_allocation_mismatches BIGINT;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_ride_id::TEXT, 0)
    );

    SELECT * INTO v_existing
    FROM public.ride_economic_plans AS plan
    WHERE plan.ride_id = v_ride_id
    FOR UPDATE;

    IF FOUND AND v_existing.tribute_policy_version IS NULL THEN
        RETURN public.freeze_ride_economic_plan_without_cal_tribute_policy(
            p_plan,
            p_steps
        );
    END IF;

    IF jsonb_typeof(p_steps) <> 'array' THEN
        RAISE EXCEPTION 'ride economic completion steps must be an array';
    END IF;
    IF p_plan->>'tribute_policy_version' IS DISTINCT FROM
        'cal_tribute_segment_np_fixed_10pct_v1' THEN
        RAISE EXCEPTION 'new ride economic plans require ratified CAL tribute policy';
    END IF;
    IF public.require_ride_economic_uint(
        p_plan->'parser_version',
        'parser_version',
        4294967295
    ) <> 5 THEN
        RAISE EXCEPTION 'new CAL tribute plans require parser V5 authority';
    END IF;

    v_cal := public.require_ride_economic_uint(
        p_plan->'exact_cal_base_units',
        'exact_cal_base_units',
        18446744073709551615
    );
    v_budget := trunc(v_cal * 1000 / 10000);
    v_submitted_budget := public.require_ride_economic_uint(
        p_plan->'exact_tribute_budget_base_units',
        'exact_tribute_budget_base_units',
        18446744073709551615
    );
    IF v_submitted_budget <> v_budget THEN
        RAISE EXCEPTION 'frozen CAL tribute budget is not exact ten percent';
    END IF;

    v_ftp_w := public.require_ride_economic_uint(
        p_plan->'reward_ftp_w',
        'reward_ftp_w',
        65535
    );
    IF v_ftp_w NOT BETWEEN 50 AND 500 THEN
        RAISE EXCEPTION 'immutable reward FTP must be between 50 and 500 watts';
    END IF;

    FOR v_step IN SELECT value FROM jsonb_array_elements(p_steps)
    LOOP
        IF v_step->>'segment_power_metrics_version' IS DISTINCT FROM
            'workout_parse_metrics_v1' THEN
            RAISE EXCEPTION 'unsupported climb-window power metrics version';
        END IF;

        v_time_s := public.require_ride_economic_uint(
            v_step->'completion_time_s',
            'completion_time_s',
            4294967295
        );
        PERFORM public.require_ride_economic_uint(
            v_step->'segment_start_offset_s',
            'segment_start_offset_s',
            4294967295
        );
        IF public.require_ride_economic_uint(
            v_step->'segment_end_offset_s',
            'segment_end_offset_s',
            4294967295
        ) < public.require_ride_economic_uint(
            v_step->'segment_start_offset_s',
            'segment_start_offset_s',
            4294967295
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
        v_np_w := CASE
            WHEN v_step->'segment_np_w' IS NULL
              OR jsonb_typeof(v_step->'segment_np_w') = 'null'
                THEN NULL
            ELSE public.require_ride_economic_uint(
                v_step->'segment_np_w',
                'segment_np_w',
                65535
            )
        END;
        IF (v_sample_count < 30 OR v_coverage_bps < 5000)
           AND v_np_w IS NOT NULL THEN
            RAISE EXCEPTION 'insufficient segment power cannot authorize tribute';
        END IF;

        v_weight := public.require_ride_economic_uint(
            v_step->'tribute_weight',
            'tribute_weight',
            18446744073709551615
        );
        v_expected_weight := v_time_s * COALESCE(v_np_w, 0);
        IF v_weight <> v_expected_weight THEN
            RAISE EXCEPTION
                'frozen tribute weight does not match time and segment NP';
        END IF;

        v_intensity_bps := public.require_ride_economic_uint(
            v_step->'intensity_bps',
            'intensity_bps',
            13107000
        );
        v_expected_intensity_bps := CASE
            WHEN v_np_w IS NULL THEN 0
            ELSE trunc(v_np_w * 10000 / v_ftp_w)
        END;
        IF v_intensity_bps <> v_expected_intensity_bps THEN
            RAISE EXCEPTION
                'frozen intensity does not use immutable reward FTP';
        END IF;

        PERFORM public.require_ride_economic_uint(
            v_step->'exact_tribute_base_units',
            'exact_tribute_base_units',
            18446744073709551615
        );
        v_total_weight := v_total_weight + v_weight;
    END LOOP;

    SELECT
        count(*) - count(DISTINCT public.require_ride_economic_uint(
            source.step->'vault_id',
            'vault_id',
            18446744073709551615
        ))
    INTO v_duplicate_vaults
    FROM jsonb_array_elements(p_steps) AS source(step);
    IF v_duplicate_vaults <> 0 THEN
        RAISE EXCEPTION 'duplicate Vault in frozen CAL tribute allocation';
    END IF;

    WITH parsed AS (
        SELECT
            public.require_ride_economic_uint(
                source.step->'vault_id',
                'vault_id',
                18446744073709551615
            ) AS vault_id,
            public.require_ride_economic_uint(
                source.step->'tribute_weight',
                'tribute_weight',
                18446744073709551615
            ) AS weight,
            public.require_ride_economic_uint(
                source.step->'exact_tribute_base_units',
                'exact_tribute_base_units',
                18446744073709551615
            ) AS tribute
        FROM jsonb_array_elements(p_steps) AS source(step)
    ),
    base AS (
        SELECT
            parsed.*,
            CASE WHEN v_total_weight = 0 THEN 0
                ELSE trunc(parsed.weight * v_budget / v_total_weight)
            END AS base_share,
            CASE WHEN v_total_weight = 0 THEN 0
                ELSE mod(parsed.weight * v_budget, v_total_weight)
            END AS remainder
        FROM parsed
    ),
    ranked AS (
        SELECT
            base.*,
            row_number() OVER (
                ORDER BY base.remainder DESC, base.vault_id ASC
            ) - 1 AS remainder_rank,
            sum(base.base_share) OVER () AS base_total
        FROM base
    ),
    allocated AS (
        SELECT
            ranked.*,
            CASE WHEN v_total_weight = 0 THEN 0
                ELSE ranked.base_share
                    + CASE
                        WHEN ranked.remainder_rank <
                            v_budget - ranked.base_total
                        THEN 1 ELSE 0
                      END
            END AS expected_tribute
        FROM ranked
    )
    SELECT
        count(*) FILTER (
            WHERE allocated.tribute <> allocated.expected_tribute
        ),
        COALESCE(sum(allocated.expected_tribute), 0)
    INTO v_allocation_mismatches, v_expected_total
    FROM allocated;

    IF v_allocation_mismatches <> 0 THEN
        RAISE EXCEPTION
            'frozen tribute does not match deterministic fixed-budget allocation';
    END IF;

    v_plan_total := public.require_ride_economic_uint(
        p_plan->'exact_tribute_base_units',
        'exact_tribute_base_units',
        340282366920938463463374607431768211455
    );
    IF v_plan_total <> v_expected_total THEN
        RAISE EXCEPTION
            'ride economic tribute total does not match fixed-budget steps';
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

DO $$
DECLARE
    v_ride_id UUID;
BEGIN
    FOR v_ride_id IN
        SELECT plan.ride_id
        FROM public.ride_economic_plans AS plan
        WHERE plan.tribute_policy_version IS NULL
          AND plan.state NOT IN ('complete', 'review', 'rejected')
    LOOP
        PERFORM public.enter_ride_economic_review(
            v_ride_id,
            NULL,
            false,
            'legacy_cal_tribute_policy_cutover',
            'migration:cal_tribute_policy',
            jsonb_build_object(
                'version', 1,
                'kind', 'legacy_cal_tribute_policy',
                'operation', 'fixed_budget_cutover',
                'message',
                    'pending legacy plan lacks ratified tribute budget and power evidence',
                'observed_at', clock_timestamp()
            )
        );
    END LOOP;
END;
$$;
