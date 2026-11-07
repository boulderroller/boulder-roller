-- Preserve release of already-frozen v1 holds under their original fixed-10%
-- authority. Only v2 hold evidence enters the measured-TSS implementation.
DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_reward_threshold_release_snapshot_without_segment_tss_v2(jsonb,jsonb,uuid)'
    ) IS NULL
       AND to_regprocedure(
        'public.freeze_reward_threshold_release_snapshot(jsonb,jsonb,uuid)'
       ) IS NOT NULL THEN
        ALTER FUNCTION public.freeze_reward_threshold_release_snapshot(
            JSONB, JSONB, UUID
        ) RENAME TO
            freeze_reward_threshold_release_snapshot_without_segment_tss_v2;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_reward_threshold_release_snapshot_without_segment_tss_v2(
        JSONB, JSONB, UUID
    ) FROM PUBLIC, anon, authenticated, service_role;

ALTER TABLE public.reward_threshold_release_snapshots
    DROP CONSTRAINT IF EXISTS reward_threshold_release_snapshots_check;
ALTER TABLE public.reward_threshold_release_snapshots
    DROP CONSTRAINT IF EXISTS reward_threshold_release_snapshots_tribute_policy_check;
ALTER TABLE public.reward_threshold_release_snapshots
    ADD CONSTRAINT reward_threshold_release_snapshots_tribute_policy_check CHECK (
        exact_tribute_budget_base_units BETWEEN
            0 AND 18446744073709551615::NUMERIC
        AND (
            (
                snapshot_evidence->>'domain' =
                    'BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1'
                AND exact_tribute_budget_base_units =
                    pg_catalog.trunc(exact_cal_base_units * 1000 / 10000)
            )
            OR (
                snapshot_evidence->>'domain' =
                    'BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2'
                AND exact_tribute_budget_base_units <= exact_cal_base_units
            )
        )
    );

CREATE OR REPLACE FUNCTION public.freeze_reward_threshold_release_snapshot(
    p_snapshot JSONB,
    p_steps JSONB,
    p_planner_lease_owner UUID
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET timezone = 'UTC'
AS $$
DECLARE
    v_item_id UUID;
    v_snapshot_id UUID;
    v_existing RECORD;
    v_claim RECORD;
    v_item RECORD;
    v_hold RECORD;
    v_admission RECORD;
    v_batch RECORD;
    v_plan RECORD;
    v_authority RECORD;
    v_economic_tss NUMERIC;
    v_total_tss NUMERIC;
    v_exact_cal NUMERIC;
    v_tribute_budget NUMERIC;
    v_snapshot_evidence JSONB;
    v_submitted_snapshot_evidence JSONB;
    v_normalized_submitted_evidence JSONB;
    v_canonical_plan JSONB;
    v_canonical_steps JSONB := '[]'::JSONB;
    v_canonical_step JSONB;
    v_snapshot_hash BYTEA;
    v_submitted_snapshot_hash BYTEA;
    v_step JSONB;
    v_hold_step JSONB;
    v_step_index INTEGER;
    v_expected_step_index INTEGER := 0;
    v_normalize_step_index INTEGER := 0;
    v_pattern_id UUID;
    v_vault_id NUMERIC;
    v_vault_signature TEXT;
    v_time_s NUMERIC;
    v_completed_at TIMESTAMPTZ;
    v_tribute NUMERIC;
    v_segment_np_w NUMERIC;
    v_segment_np_mw NUMERIC;
    v_segment_np_duration_s NUMERIC;
    v_tribute_weight NUMERIC;
    v_intensity_bps NUMERIC;
    v_expected_tribute NUMERIC;
    v_evidence_hash BYTEA;
    v_expected_receipt_pda TEXT;
    v_total_tribute NUMERIC := 0;
    v_duplicate_vaults BIGINT;
    v_overlap_count BIGINT;
    v_is_replay BOOLEAN := false;
BEGIN
    IF pg_catalog.jsonb_typeof(p_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(p_steps) <> 'array' THEN
        RAISE EXCEPTION 'Threshold release snapshot and step array are required';
    END IF;
    v_item_id := (p_snapshot->>'batch_item_id')::UUID;

    SELECT hold.* INTO v_hold
    FROM public.reward_threshold_release_batch_items AS item
    JOIN public.reward_threshold_provisional_holds AS hold
      ON hold.id = item.hold_id
    WHERE item.id = v_item_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release item lacks frozen hold evidence';
    END IF;
    IF public.require_ride_economic_uint(
        v_hold.hold_evidence->'version', 'hold evidence version', 255
    ) <> 2 THEN
        RETURN public.freeze_reward_threshold_release_snapshot_without_segment_tss_v2(
            p_snapshot,
            p_steps,
            p_planner_lease_owner
        );
    END IF;
    IF p_planner_lease_owner IS NULL THEN
        RAISE EXCEPTION 'Threshold release planner lease owner is required';
    END IF;

    SELECT * INTO v_existing
    FROM public.reward_threshold_release_snapshots
    WHERE batch_item_id = v_item_id;
    v_is_replay := FOUND;

    IF NOT v_is_replay THEN
        SELECT * INTO v_claim
        FROM public.reward_threshold_release_item_claims
        WHERE batch_item_id = v_item_id
          AND lease_owner = p_planner_lease_owner
          AND lease_expires_at > pg_catalog.clock_timestamp()
          AND consumed_snapshot_id IS NULL
          AND terminal_disposition IS NULL
        FOR UPDATE;
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT * INTO v_item
    FROM public.reward_threshold_release_batch_items
    WHERE id = v_item_id AND disposition = 'eligible'
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release planner claim is not eligible';
    END IF;
    SELECT * INTO v_admission
    FROM public.reward_threshold_provisional_hold_admissions
    WHERE hold_id = v_hold.id AND ride_id = v_hold.ride_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release item lacks frozen chain admission';
    END IF;
    SELECT * INTO v_batch
    FROM public.reward_threshold_release_batches
    WHERE id = v_item.batch_id;
    SELECT * INTO v_plan
    FROM public.ride_economic_plans
    WHERE ride_id = v_hold.ride_id
      AND state = 'complete'
      AND terminal_projected_at IS NOT NULL
      AND reward_policy = 'threshold_provisional_hold_v1'
      AND total_tss = 0
      AND exact_cal_base_units = 0
      AND plan_evidence_hash = v_hold.admission_plan_evidence_hash
      AND NOT EXISTS (
          SELECT 1 FROM public.ride_economic_completion_steps AS normal_step
          WHERE normal_step.ride_id = v_hold.ride_id
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release parent plan is not complete and zero-economic';
    END IF;
    SELECT * INTO v_authority
    FROM public.reward_ftp_authorities
    WHERE id = v_batch.established_authority_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release batch lacks sealed Threshold authority';
    END IF;

    IF (p_snapshot->>'batch_item_id')::UUID IS DISTINCT FROM v_item.id
       OR (p_snapshot->>'ride_id')::UUID IS DISTINCT FROM v_hold.ride_id
       OR (p_snapshot->>'user_id')::UUID IS DISTINCT FROM v_hold.user_id
       OR (p_snapshot->>'reward_ftp_authority_id')::UUID IS DISTINCT FROM v_authority.id
       OR (p_snapshot->>'reward_ftp_w')::INTEGER IS DISTINCT FROM v_authority.ftp_w
       OR p_snapshot->>'reward_ftp_source' IS DISTINCT FROM 'derived_eftp'
       OR p_snapshot->>'reward_ftp_policy_version' IS DISTINCT FROM
            'reward_ftp_policy_2026_08_24_threshold_v1'
       OR p_snapshot->>'wallet' IS DISTINCT FROM v_plan.wallet
       OR (p_snapshot->>'admitted_at')::TIMESTAMPTZ IS DISTINCT FROM v_admission.admitted_at
       OR (p_snapshot->>'established_at')::TIMESTAMPTZ IS DISTINCT FROM v_batch.established_at
       OR pg_catalog.decode(
            p_snapshot->>'reward_ftp_authority_evidence_hash_hex', 'hex'
          ) IS DISTINCT FROM v_authority.evidence_hash
       OR pg_catalog.decode(p_snapshot->>'ride_hash_hex', 'hex') IS DISTINCT FROM
            v_plan.ride_hash THEN
        RAISE EXCEPTION 'Threshold release input conflicts with sealed authority';
    END IF;

    v_economic_tss := (p_snapshot->>'economic_tss')::NUMERIC;
    v_total_tss := public.require_ride_economic_uint(
        p_snapshot->'total_tss', 'total_tss', 4294967295
    );
    v_exact_cal := public.require_ride_economic_uint(
        p_snapshot->'exact_cal_base_units',
        'exact_cal_base_units',
        18446744073709551615
    );
    v_tribute_budget := public.require_ride_economic_uint(
        p_snapshot->'exact_tribute_budget_base_units',
        'exact_tribute_budget_base_units',
        18446744073709551615
    );
    IF v_economic_tss IS NULL
       OR v_economic_tss < 0
       OR v_economic_tss::TEXT = 'NaN'
       OR pg_catalog.trunc(v_economic_tss) > 4294967295::NUMERIC
       OR v_total_tss <> pg_catalog.trunc(v_economic_tss)
       OR v_exact_cal <= 0
       OR v_exact_cal <> pg_catalog.trunc(v_economic_tss * 1000000000)
       OR v_tribute_budget > v_exact_cal THEN
        RAISE EXCEPTION 'Threshold release CAL or tribute ceiling is not exact';
    END IF;

    v_submitted_snapshot_evidence := p_snapshot->'snapshot_evidence';
    IF pg_catalog.jsonb_typeof(v_submitted_snapshot_evidence) <> 'object' THEN
        RAISE EXCEPTION 'Threshold release snapshot evidence must be an object';
    END IF;
    IF pg_catalog.btrim(COALESCE(
            p_snapshot->>'expected_release_authority_pda', ''
       )) = ''
       OR pg_catalog.btrim(COALESCE(
            p_snapshot->>'expected_cal_receipt_pda', ''
       )) = '' THEN
        RAISE EXCEPTION 'Threshold release execution evidence is incomplete';
    END IF;
    IF pg_catalog.jsonb_typeof(
        COALESCE(v_hold.hold_evidence->'completion_steps', '[]'::JSONB)
    ) <> 'array'
       OR pg_catalog.jsonb_array_length(
            COALESCE(v_hold.hold_evidence->'completion_steps', '[]'::JSONB)
          ) <> pg_catalog.jsonb_array_length(p_steps) THEN
        RAISE EXCEPTION 'Threshold release steps conflict with frozen hold evidence';
    END IF;

    FOR v_step IN SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
    LOOP
        IF pg_catalog.jsonb_typeof(v_step) <> 'object' THEN
            RAISE EXCEPTION 'Threshold release completion step must be an object';
        END IF;
        v_step_index := public.require_ride_economic_uint(
            v_step->'step_index', 'step_index', 2147483647
        )::INTEGER;
        IF v_step_index <> v_expected_step_index THEN
            RAISE EXCEPTION 'Threshold release completion steps are not sequential';
        END IF;
        v_hold_step := v_hold.hold_evidence->'completion_steps'->v_step_index;
        v_pattern_id := (v_step->>'pattern_id')::UUID;
        v_vault_id := public.require_ride_economic_uint(
            v_step->'vault_id', 'vault_id', 18446744073709551615
        );
        v_vault_signature := v_step->>'vault_signature';
        v_time_s := public.require_ride_economic_uint(
            v_step->'completion_time_s', 'completion_time_s', 4294967295
        );
        v_completed_at := (v_step->>'completed_at')::TIMESTAMPTZ;
        v_tribute := public.require_ride_economic_uint(
            v_step->'exact_tribute_base_units',
            'exact_tribute_base_units',
            18446744073709551615
        );
        v_segment_np_w := CASE
            WHEN v_step->'segment_np_w' = 'null'::JSONB THEN NULL
            ELSE public.require_ride_economic_uint(
                v_step->'segment_np_w', 'segment_np_w', 65535
            )
        END;
        v_segment_np_mw := CASE
            WHEN v_step->'segment_np_milliwatts' = 'null'::JSONB THEN NULL
            ELSE public.require_ride_economic_uint(
                v_step->'segment_np_milliwatts',
                'segment_np_milliwatts',
                65535000
            )
        END;
        v_segment_np_duration_s := public.require_ride_economic_uint(
            v_step->'segment_np_duration_s',
            'segment_np_duration_s',
            4294967295
        );
        IF v_segment_np_duration_s > v_time_s
           OR v_segment_np_duration_s >
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
        v_tribute_weight := public.require_ride_economic_uint(
            v_step->'tribute_weight', 'tribute_weight', 18446744073709551615
        );
        v_intensity_bps := public.require_ride_economic_uint(
            v_step->'intensity_bps', 'intensity_bps', 4294967295
        );
        IF public.require_ride_economic_uint(
            v_step->'completion_evidence_version',
            'completion_evidence_version',
            255
        ) <> 3 THEN
            RAISE EXCEPTION 'Threshold release completion evidence must be V3';
        END IF;
        v_evidence_hash := pg_catalog.decode(
            v_step->>'completion_evidence_hash_hex', 'hex'
        );
        v_expected_receipt_pda := v_step->>'expected_receipt_pda';

        IF pg_catalog.jsonb_typeof(v_hold_step) <> 'object'
           OR v_pattern_id IS NULL
           OR pg_catalog.btrim(COALESCE(v_vault_signature, '')) = ''
           OR v_time_s < 1
           OR v_completed_at IS DISTINCT FROM v_plan.completed_at
           OR pg_catalog.octet_length(v_evidence_hash) <> 32
           OR pg_catalog.btrim(COALESCE(v_expected_receipt_pda, '')) = '' THEN
            RAISE EXCEPTION 'Threshold release completion step is incomplete';
        END IF;
        IF (v_hold_step->>'pattern_id')::UUID IS DISTINCT FROM v_pattern_id
           OR public.require_ride_economic_uint(
                v_hold_step->'vault_id', 'frozen vault_id',
                18446744073709551615
              ) IS DISTINCT FROM v_vault_id
           OR v_hold_step->>'vault_signature' IS DISTINCT FROM v_vault_signature
           OR public.require_ride_economic_uint(
                v_hold_step->'completion_time_s', 'frozen completion_time_s',
                4294967295
              ) IS DISTINCT FROM v_time_s
           OR (v_hold_step->>'completed_at')::TIMESTAMPTZ IS DISTINCT FROM v_completed_at
           OR v_step->'segment_start_offset_s' IS DISTINCT FROM v_hold_step->'segment_start_offset_s'
           OR v_step->'segment_end_offset_s' IS DISTINCT FROM v_hold_step->'segment_end_offset_s'
           OR v_step->'segment_np_w' IS DISTINCT FROM v_hold_step->'segment_np_w'
           OR v_step->'segment_np_milliwatts' IS DISTINCT FROM v_hold_step->'segment_np_milliwatts'
           OR v_step->'segment_np_duration_s' IS DISTINCT FROM v_hold_step->'segment_np_duration_s'
           OR v_step->'segment_power_sample_count' IS DISTINCT FROM v_hold_step->'segment_power_sample_count'
           OR v_step->'segment_power_coverage_bps' IS DISTINCT FROM v_hold_step->'segment_power_coverage_bps'
           OR v_step->'segment_power_metrics_version' IS DISTINCT FROM v_hold_step->'segment_power_metrics_version'
           OR v_step->'tribute_weight' IS DISTINCT FROM v_hold_step->'tribute_weight'
           OR v_step->'climb_distance_m' IS DISTINCT FROM v_hold_step->'climb_distance_m'
           OR v_step->'climb_vert_m' IS DISTINCT FROM v_hold_step->'climb_vert_m' THEN
            RAISE EXCEPTION 'Threshold release step conflicts with frozen hold evidence';
        END IF;
        IF (v_segment_np_w IS NULL) <> (v_segment_np_mw IS NULL)
           OR (v_segment_np_mw IS NOT NULL AND v_segment_np_duration_s = 0)
           OR (v_segment_np_mw IS NOT NULL AND v_segment_np_w <>
                pg_catalog.trunc((v_segment_np_mw + 500) / 1000))
           OR v_tribute_weight <> 0
           OR v_intensity_bps IS DISTINCT FROM (CASE
                WHEN v_segment_np_mw IS NULL THEN 0
                ELSE pg_catalog.trunc(
                    v_segment_np_mw * 10000 / (v_authority.ftp_w * 1000)
                )
              END) THEN
            RAISE EXCEPTION 'Threshold release step economics are not canonical';
        END IF;
        IF (
            public.require_ride_economic_uint(
                v_step->'segment_power_sample_count',
                'segment_power_sample_count',
                4294967295
            ) < 30
            OR public.require_ride_economic_uint(
                v_step->'segment_power_coverage_bps',
                'segment_power_coverage_bps',
                10000
            ) < 5000
        ) AND v_segment_np_mw IS NOT NULL THEN
            RAISE EXCEPTION 'insufficient segment power cannot authorize tribute';
        END IF;
        v_expected_tribute := CASE
            WHEN v_segment_np_mw IS NULL
              OR v_segment_np_mw = 0
              OR v_segment_np_duration_s = 0 THEN 0
            ELSE pg_catalog.trunc(
                v_segment_np_duration_s * v_segment_np_mw * v_segment_np_mw
                * 100 * 1000000000
                / (
                    v_authority.ftp_w::NUMERIC * v_authority.ftp_w::NUMERIC
                    * 1000000 * 3600
                )
            )
        END;
        IF v_tribute IS DISTINCT FROM v_expected_tribute THEN
            RAISE EXCEPTION 'Threshold release tribute is not measured Climb TSS';
        END IF;

        v_canonical_step := pg_catalog.jsonb_build_object(
            'step_index', v_step_index,
            'pattern_id', v_pattern_id::TEXT,
            'vault_id', v_vault_id,
            'vault_signature', v_vault_signature,
            'completion_time_s', v_time_s,
            'completed_at', pg_catalog.to_char(
                v_plan.completed_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'exact_tribute_base_units', v_tribute,
            'intensity_bps', v_intensity_bps,
            'segment_start_offset_s', v_hold_step->'segment_start_offset_s',
            'segment_end_offset_s', v_hold_step->'segment_end_offset_s',
            'segment_np_w', v_hold_step->'segment_np_w',
            'segment_np_milliwatts', v_hold_step->'segment_np_milliwatts',
            'segment_np_duration_s', v_hold_step->'segment_np_duration_s',
            'segment_power_sample_count', v_hold_step->'segment_power_sample_count',
            'segment_power_coverage_bps', v_hold_step->'segment_power_coverage_bps',
            'segment_power_metrics_version', v_hold_step->>'segment_power_metrics_version',
            'tribute_weight', v_tribute_weight,
            'climb_distance_m', v_hold_step->'climb_distance_m',
            'climb_vert_m', v_hold_step->'climb_vert_m',
            'completion_evidence_version', 3,
            'completion_evidence_hash_hex', pg_catalog.encode(v_evidence_hash, 'hex'),
            'expected_receipt_pda', v_expected_receipt_pda
        );
        v_canonical_steps := v_canonical_steps
            || pg_catalog.jsonb_build_array(v_canonical_step);
        v_total_tribute := v_total_tribute + v_tribute;
        v_expected_step_index := v_expected_step_index + 1;
    END LOOP;

    SELECT count(*) - count(DISTINCT public.require_ride_economic_uint(
        source.step->'vault_id', 'vault_id', 18446744073709551615
    ))
    INTO v_duplicate_vaults
    FROM pg_catalog.jsonb_array_elements(p_steps) AS source(step);
    IF v_duplicate_vaults <> 0 THEN
        RAISE EXCEPTION 'duplicate Vault in Threshold release plan';
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

    IF v_total_tribute <> v_tribute_budget THEN
        RAISE EXCEPTION 'Threshold release budget does not equal measured Climb sum';
    END IF;

    v_canonical_plan := pg_catalog.jsonb_build_object(
        'batch_item_id', v_item.id::TEXT,
        'ride_id', v_hold.ride_id::TEXT,
        'user_id', v_hold.user_id::TEXT,
        'wallet', v_plan.wallet,
        'ride_hash_hex', pg_catalog.encode(v_plan.ride_hash, 'hex'),
        'admitted_at', pg_catalog.to_char(
            v_admission.admitted_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US'
        ) || '+00:00',
        'established_at', pg_catalog.to_char(
            v_batch.established_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US'
        ) || '+00:00',
        'reward_ftp_authority_id', v_authority.id::TEXT,
        'reward_ftp_authority_evidence_hash_hex',
            pg_catalog.encode(v_authority.evidence_hash, 'hex'),
        'reward_ftp_w', v_authority.ftp_w,
        'reward_ftp_source', v_authority.source,
        'reward_ftp_policy_version',
            'reward_ftp_policy_2026_08_24_threshold_v1',
        'economic_tss', pg_catalog.trim_scale(v_economic_tss),
        'total_tss', v_total_tss,
        'exact_cal_base_units', v_exact_cal,
        'exact_tribute_budget_base_units', v_tribute_budget,
        'expected_release_authority_pda', p_snapshot->>'expected_release_authority_pda',
        'expected_cal_receipt_pda', p_snapshot->>'expected_cal_receipt_pda'
    );
    v_snapshot_evidence := pg_catalog.jsonb_build_object(
        'domain', 'BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2',
        'plan', v_canonical_plan,
        'steps', v_canonical_steps,
        'hold_evidence_hash_hex', pg_catalog.encode(v_hold.hold_evidence_hash, 'hex'),
        'admission_plan_evidence_hash_hex',
            pg_catalog.encode(v_hold.admission_plan_evidence_hash, 'hex')
    );
    IF pg_catalog.jsonb_typeof(v_submitted_snapshot_evidence->'plan') <> 'object'
       OR pg_catalog.jsonb_typeof(v_submitted_snapshot_evidence->'steps') <> 'array'
       OR pg_catalog.jsonb_array_length(
            v_submitted_snapshot_evidence->'steps'
          ) <> pg_catalog.jsonb_array_length(p_steps)
       OR (v_submitted_snapshot_evidence->'plan'->>'admitted_at')::TIMESTAMPTZ
            IS DISTINCT FROM v_admission.admitted_at
       OR (v_submitted_snapshot_evidence->'plan'->>'established_at')::TIMESTAMPTZ
            IS DISTINCT FROM v_batch.established_at
       OR (v_submitted_snapshot_evidence->'plan'->>'economic_tss')::NUMERIC
            IS DISTINCT FROM v_economic_tss THEN
        RAISE EXCEPTION 'Threshold release snapshot evidence is not canonical';
    END IF;
    v_normalized_submitted_evidence := pg_catalog.jsonb_set(
        v_submitted_snapshot_evidence,
        '{plan,admitted_at}',
        v_canonical_plan->'admitted_at',
        false
    );
    v_normalized_submitted_evidence := pg_catalog.jsonb_set(
        v_normalized_submitted_evidence,
        '{plan,established_at}',
        v_canonical_plan->'established_at',
        false
    );
    v_normalized_submitted_evidence := pg_catalog.jsonb_set(
        v_normalized_submitted_evidence,
        '{plan,economic_tss}',
        v_canonical_plan->'economic_tss',
        false
    );
    WHILE v_normalize_step_index < pg_catalog.jsonb_array_length(p_steps)
    LOOP
        IF (
            v_submitted_snapshot_evidence->'steps'
                ->v_normalize_step_index->>'completed_at'
           )::TIMESTAMPTZ IS DISTINCT FROM v_plan.completed_at THEN
            RAISE EXCEPTION 'Threshold release snapshot evidence is not canonical';
        END IF;
        v_normalized_submitted_evidence := pg_catalog.jsonb_set(
            v_normalized_submitted_evidence,
            ARRAY['steps', v_normalize_step_index::TEXT, 'completed_at'],
            v_canonical_steps->v_normalize_step_index->'completed_at',
            false
        );
        v_normalize_step_index := v_normalize_step_index + 1;
    END LOOP;
    IF v_normalized_submitted_evidence IS DISTINCT FROM v_snapshot_evidence THEN
        RAISE EXCEPTION 'Threshold release snapshot evidence is not canonical';
    END IF;
    v_snapshot_hash := pg_catalog.sha256(
        pg_catalog.convert_to(v_snapshot_evidence::TEXT, 'UTF8')
    );
    IF p_snapshot ? 'snapshot_evidence_hash_hex' THEN
        v_submitted_snapshot_hash := pg_catalog.decode(
            p_snapshot->>'snapshot_evidence_hash_hex', 'hex'
        );
        IF v_submitted_snapshot_hash IS DISTINCT FROM v_snapshot_hash THEN
            RAISE EXCEPTION 'Threshold release snapshot evidence hash is not canonical';
        END IF;
    END IF;

    IF v_is_replay THEN
        IF v_existing.snapshot_evidence IS DISTINCT FROM v_snapshot_evidence
           OR v_existing.snapshot_evidence_hash IS DISTINCT FROM v_snapshot_hash THEN
            RAISE EXCEPTION 'Threshold release snapshot replay conflicts with immutable authority';
        END IF;
        RETURN public.get_reward_threshold_release_execution(v_existing.id);
    END IF;

    v_snapshot_id := COALESCE(
        (p_snapshot->>'snapshot_id')::UUID,
        pg_catalog.gen_random_uuid()
    );
    INSERT INTO public.reward_threshold_release_snapshots (
        id, batch_item_id, ride_id, user_id, reward_ftp_authority_id,
        reward_ftp_w, reward_ftp_source, reward_ftp_policy_version,
        economic_tss, exact_cal_base_units,
        exact_tribute_budget_base_units, snapshot_evidence,
        snapshot_evidence_hash
    ) VALUES (
        v_snapshot_id, v_item.id, v_hold.ride_id, v_hold.user_id,
        v_authority.id, v_authority.ftp_w, v_authority.source,
        'reward_ftp_policy_2026_08_24_threshold_v1',
        v_economic_tss, v_exact_cal, v_tribute_budget,
        v_snapshot_evidence, v_snapshot_hash
    );
    INSERT INTO public.reward_threshold_release_executions (
        snapshot_id, wallet, ride_hash, release_plan_evidence_hash,
        expected_release_authority_pda, expected_cal_receipt_pda
    ) VALUES (
        v_snapshot_id, v_plan.wallet, v_plan.ride_hash, v_snapshot_hash,
        p_snapshot->>'expected_release_authority_pda',
        p_snapshot->>'expected_cal_receipt_pda'
    );
    FOR v_step IN SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
    LOOP
        INSERT INTO public.reward_threshold_release_steps (
            snapshot_id, step_index, pattern_id, vault_id, vault_signature,
            completion_time_s, completed_at, exact_tribute_base_units,
            completion_evidence_version, completion_evidence_hash,
            expected_receipt_pda
        ) VALUES (
            v_snapshot_id,
            (v_step->>'step_index')::INTEGER,
            (v_step->>'pattern_id')::UUID,
            (v_step->>'vault_id')::NUMERIC,
            v_step->>'vault_signature',
            (v_step->>'completion_time_s')::BIGINT,
            (v_step->>'completed_at')::TIMESTAMPTZ,
            (v_step->>'exact_tribute_base_units')::NUMERIC,
            3,
            pg_catalog.decode(v_step->>'completion_evidence_hash_hex', 'hex'),
            v_step->>'expected_receipt_pda'
        );
    END LOOP;
    UPDATE public.reward_threshold_release_item_claims
    SET consumed_snapshot_id = v_snapshot_id,
        consumed_at = pg_catalog.clock_timestamp(),
        updated_at = pg_catalog.clock_timestamp()
    WHERE batch_item_id = v_item.id
      AND lease_owner = p_planner_lease_owner
      AND consumed_snapshot_id IS NULL
      AND terminal_disposition IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release planner claim consumption lost its lease';
    END IF;
    RETURN public.get_reward_threshold_release_execution(v_snapshot_id);
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_reward_threshold_release_snapshot(
    JSONB, JSONB, UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_reward_threshold_release_snapshot(
    JSONB, JSONB, UUID
) TO service_role;

-- The production ride-detail resolver must expose the frozen policy domain so
-- clients can distinguish historical V1 releases from measured-TSS V2.
CREATE OR REPLACE FUNCTION public.resolve_reward_threshold_release_lifecycle(
    p_ride_id UUID
) RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_result JSONB;
BEGIN
    SELECT pg_catalog.jsonb_build_object(
        'status', CASE
            WHEN execution.state = 'complete'
             AND execution.terminal_projected_at IS NOT NULL THEN 'released'
            WHEN execution.state = 'review' THEN 'under_review'
            WHEN claim.terminal_disposition = 'review' THEN 'under_review'
            WHEN claim.terminal_disposition = 'not_counted' THEN 'not_counted'
            WHEN item.disposition = 'lapsed' THEN 'lapsed'
            WHEN snapshot.id IS NOT NULL THEN 'releasing'
            WHEN item.disposition = 'eligible' THEN 'planning'
            ELSE 'held'
        END,
        'ride_id', hold.ride_id,
        'hold_id', hold.id,
        'batch_item_id', item.id,
        'planner_reason', claim.terminal_reason,
        'review_reason', execution.review_reason,
        'snapshot', CASE WHEN snapshot.id IS NULL THEN NULL
            ELSE pg_catalog.jsonb_build_object(
                'id', snapshot.id,
                'ride_id', snapshot.ride_id,
                'exact_cal_base_units', snapshot.exact_cal_base_units,
                'exact_tribute_budget_base_units',
                    snapshot.exact_tribute_budget_base_units,
                'snapshot_evidence', snapshot.snapshot_evidence
            )
        END,
        'execution_state', execution.state,
        'terminal_projected_at', execution.terminal_projected_at,
        'steps', COALESCE((
            SELECT pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'snapshot_id', step.snapshot_id,
                    'step_index', step.step_index,
                    'pattern_id', step.pattern_id,
                    'vault_id', step.vault_id,
                    'vault_signature', step.vault_signature,
                    'completion_time_s', step.completion_time_s,
                    'exact_tribute_base_units', step.exact_tribute_base_units,
                    'completion_evidence_version',
                        step.completion_evidence_version,
                    'completion_evidence_hash',
                        pg_catalog.encode(step.completion_evidence_hash, 'hex'),
                    'expected_receipt_pda', step.expected_receipt_pda,
                    'state', step.state,
                    'chain_confirmed_at', step.chain_confirmed_at,
                    'projected_at', step.projected_at
                ) ORDER BY step.step_index
            )
            FROM public.reward_threshold_release_steps AS step
            WHERE step.snapshot_id = snapshot.id
        ), '[]'::JSONB)
    ) INTO v_result
    FROM public.reward_threshold_provisional_holds AS hold
    LEFT JOIN public.reward_threshold_release_batch_items AS item
      ON item.hold_id = hold.id
    LEFT JOIN public.reward_threshold_release_item_claims AS claim
      ON claim.batch_item_id = item.id
    LEFT JOIN public.reward_threshold_release_snapshots AS snapshot
      ON snapshot.batch_item_id = item.id
    LEFT JOIN public.reward_threshold_release_executions AS execution
      ON execution.snapshot_id = snapshot.id
    WHERE hold.ride_id = p_ride_id
    LIMIT 1;

    RETURN COALESCE(
        v_result,
        pg_catalog.jsonb_build_object(
            'status', 'absent',
            'ride_id', p_ride_id,
            'snapshot', NULL,
            'steps', '[]'::JSONB
        )
    );
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_reward_threshold_release_lifecycle(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_reward_threshold_release_lifecycle(UUID)
    TO service_role;
