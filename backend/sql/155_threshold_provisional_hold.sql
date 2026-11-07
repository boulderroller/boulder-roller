-- Threshold provisional holds and one-time release authority.
--
-- A ride admitted while its rider still has the neutral 200 W display
-- placeholder keeps that immutable ride-time snapshot and its ordinary frozen
-- economic plan.  Establishment creates an append-only release batch.  Each
-- eligible child release binds a distinct Threshold snapshot and V3 receipt
-- evidence; it never rewrites the sporting RideAttestation or a settled week.

-- Release receipts use V3 exact-amount evidence.  Ordinary ride completion
-- steps remain V2-only; only the shared chain projections admit V3.
ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS normalized_power_raw_w DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS normalized_power_duration_s INTEGER;
ALTER TABLE public.rides
    ADD CONSTRAINT rides_threshold_release_power_inputs_check CHECK (
        (
            normalized_power_raw_w IS NULL
            AND normalized_power_duration_s IS NULL
        )
        OR (
            normalized_power_raw_w > 0
            AND normalized_power_raw_w <> 'NaN'::DOUBLE PRECISION
            AND pg_catalog.abs(normalized_power_raw_w) <
                'Infinity'::DOUBLE PRECISION
            AND normalized_power_duration_s > 0
        )
    );

COMMENT ON COLUMN public.rides.normalized_power_raw_w IS
    'Service-only immutable raw normalized power retained for a possible Threshold release snapshot.';
COMMENT ON COLUMN public.rides.normalized_power_duration_s IS
    'Service-only immutable duration paired with normalized_power_raw_w.';

-- Threshold release power inputs are immutable once established. Service
-- retries preserve the stored pair and continue unrelated ride updates.
CREATE OR REPLACE FUNCTION public.enforce_ride_threshold_release_power_inputs()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    v_changed BOOLEAN := (
        (TG_OP = 'INSERT' AND (
            NEW.normalized_power_raw_w IS NOT NULL
            OR NEW.normalized_power_duration_s IS NOT NULL
        ))
        OR (TG_OP = 'UPDATE' AND (
            NEW.normalized_power_raw_w IS DISTINCT FROM
                OLD.normalized_power_raw_w
            OR NEW.normalized_power_duration_s IS DISTINCT FROM
                OLD.normalized_power_duration_s
        ))
    );
    v_service_actor BOOLEAN := (
        current_user IN ('postgres', 'supabase_admin', 'service_role')
        OR pg_catalog.pg_has_role(
            current_user, 'service_role', 'MEMBER'
        )
    );
BEGIN
    IF v_changed AND NOT v_service_actor THEN
        RAISE EXCEPTION 'Threshold release power inputs are service-only';
    END IF;
    IF TG_OP = 'UPDATE'
       AND (
           OLD.normalized_power_raw_w IS NOT NULL
           OR OLD.normalized_power_duration_s IS NOT NULL
       )
       AND v_changed THEN
        -- Parser upgrades and retry paths may recompute the raw pair. Preserve
        -- the first successful parse while allowing unrelated ride progress
        -- to commit instead of turning reprocessing into a hard failure.
        NEW.normalized_power_raw_w := OLD.normalized_power_raw_w;
        NEW.normalized_power_duration_s := OLD.normalized_power_duration_s;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_rides_threshold_release_power_inputs
    ON public.rides;
CREATE TRIGGER trg_rides_threshold_release_power_inputs
    BEFORE INSERT OR UPDATE OF
        normalized_power_raw_w, normalized_power_duration_s
    ON public.rides
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_ride_threshold_release_power_inputs();

ALTER TABLE public.vault_completions
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT;

CREATE TABLE IF NOT EXISTS public.indexed_cal_mint_receipts (
    pda TEXT PRIMARY KEY,
    ride_attestation_pda TEXT NOT NULL,
    rider_pubkey TEXT NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    chain_slot BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    bump SMALLINT,
    UNIQUE (ride_attestation_pda, rider_pubkey)
);

CREATE TABLE IF NOT EXISTS public.indexed_climb_completion_receipts (
    pda TEXT PRIMARY KEY,
    ride_attestation_pda TEXT NOT NULL,
    vault_pda TEXT NOT NULL,
    chain_slot BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    bump SMALLINT,
    UNIQUE (ride_attestation_pda, vault_pda)
);
ALTER TABLE public.indexed_climb_completion_receipts
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT NOT NULL
        DEFAULT 1,
    ADD COLUMN IF NOT EXISTS completion_evidence_hash BYTEA,
    ADD COLUMN IF NOT EXISTS cal_tributed NUMERIC(20, 0);

CREATE TABLE IF NOT EXISTS public.indexed_climb_completion_flows (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL CHECK (event_index >= 0),
    vault_id NUMERIC(20, 0) NOT NULL CHECK (
        vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    ride_attestation TEXT NOT NULL CHECK (ride_attestation <> ''),
    completion_evidence_hash BYTEA NOT NULL UNIQUE CHECK (
        pg_catalog.octet_length(completion_evidence_hash) = 32
    ),
    credited_settlement_week NUMERIC(20, 0) NOT NULL CHECK (
        credited_settlement_week BETWEEN
            0 AND 18446744073709551615::NUMERIC
    ),
    cal_tributed NUMERIC(39, 0) NOT NULL CHECK (
        cal_tributed BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    slot NUMERIC(39, 0) NOT NULL CHECK (
        slot BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    block_time BIGINT CHECK (block_time IS NULL OR block_time >= 0),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    completion_evidence_version SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tx_signature, event_index)
);

ALTER TABLE public.vault_completions
    DROP CONSTRAINT IF EXISTS vault_completions_evidence_version_check;
ALTER TABLE public.vault_completions
    ADD CONSTRAINT vault_completions_evidence_version_check
    CHECK (completion_evidence_version IN (1, 2, 3));

ALTER TABLE public.indexed_climb_completion_receipts
    DROP CONSTRAINT IF EXISTS indexed_completion_receipts_evidence_version_check;
ALTER TABLE public.indexed_climb_completion_receipts
    ADD CONSTRAINT indexed_completion_receipts_evidence_version_check
    CHECK (completion_evidence_version IN (1, 2, 3));

ALTER TABLE public.indexed_climb_completion_receipts
    DROP CONSTRAINT IF EXISTS indexed_completion_receipts_v2_amount_check;
ALTER TABLE public.indexed_climb_completion_receipts
    ADD CONSTRAINT indexed_completion_receipts_v2_amount_check CHECK (
        (completion_evidence_version = 1 AND cal_tributed IS NULL)
        OR (
            completion_evidence_version IN (2, 3)
            AND cal_tributed BETWEEN
                0 AND 18446744073709551615::NUMERIC
            AND completion_evidence_hash IS NOT NULL
            AND pg_catalog.octet_length(completion_evidence_hash) = 32
        )
    );

ALTER TABLE public.indexed_climb_completion_flows
    DROP CONSTRAINT IF EXISTS indexed_completion_flows_evidence_version_check;
ALTER TABLE public.indexed_climb_completion_flows
    ADD CONSTRAINT indexed_completion_flows_evidence_version_check
    CHECK (completion_evidence_version IN (1, 2, 3));

ALTER TABLE public.indexed_cal_mint_receipts
    ADD COLUMN IF NOT EXISTS release_authority_pda TEXT,
    ADD COLUMN IF NOT EXISTS release_settlement_week NUMERIC(20, 0);
ALTER TABLE public.indexed_cal_mint_receipts
    ADD CONSTRAINT indexed_cal_mint_receipts_release_check CHECK (
        (
            release_authority_pda IS NULL
            AND release_settlement_week IS NULL
        )
        OR (
            pg_catalog.btrim(release_authority_pda) <> ''
            AND release_settlement_week BETWEEN
                0 AND 18446744073709551615::NUMERIC
        )
    );

ALTER TABLE public.indexed_climb_completion_receipts
    ADD COLUMN IF NOT EXISTS release_authority_pda TEXT,
    ADD COLUMN IF NOT EXISTS credited_settlement_week NUMERIC(20, 0);
ALTER TABLE public.indexed_climb_completion_receipts
    ADD CONSTRAINT indexed_completion_receipts_release_v3_check CHECK (
        (
            completion_evidence_version IN (1, 2)
            AND release_authority_pda IS NULL
            AND credited_settlement_week IS NULL
        )
        OR (
            completion_evidence_version = 3
            AND pg_catalog.btrim(release_authority_pda) <> ''
            AND credited_settlement_week BETWEEN
                0 AND 18446744073709551615::NUMERIC
        )
    );

ALTER TABLE public.indexed_climb_completion_flows
    ADD COLUMN IF NOT EXISTS release_authority_pda TEXT;
ALTER TABLE public.indexed_climb_completion_flows
    ADD CONSTRAINT indexed_completion_flows_release_v3_check CHECK (
        (
            completion_evidence_version IN (1, 2)
            AND release_authority_pda IS NULL
        )
        OR (
            completion_evidence_version = 3
            AND pg_catalog.btrim(release_authority_pda) <> ''
        )
    );

CREATE TABLE public.indexed_held_ride_release_authorities (
    pda TEXT PRIMARY KEY CHECK (pg_catalog.btrim(pda) <> ''),
    ride_attestation_pda TEXT NOT NULL UNIQUE
        CHECK (pg_catalog.btrim(ride_attestation_pda) <> ''),
    rider_pubkey TEXT NOT NULL CHECK (pg_catalog.btrim(rider_pubkey) <> ''),
    threshold_authority_id_hex CHAR(32) NOT NULL CHECK (
        threshold_authority_id_hex ~ '^[0-9a-f]{32}$'
    ),
    threshold_authority_commitment_hex CHAR(64) NOT NULL CHECK (
        threshold_authority_commitment_hex ~ '^[0-9a-f]{64}$'
    ),
    threshold_effective_at BIGINT NOT NULL,
    threshold_w INTEGER NOT NULL CHECK (threshold_w BETWEEN 50 AND 500),
    threshold_policy_version SMALLINT NOT NULL CHECK (
        threshold_policy_version = 1
    ),
    economic_tss NUMERIC(10, 0) NOT NULL CHECK (
        economic_tss BETWEEN 0 AND 4294967295::NUMERIC
    ),
    cal_earned NUMERIC(20, 0) NOT NULL CHECK (
        cal_earned BETWEEN 1 AND 18446744073709551615::NUMERIC
    ),
    cal_tribute_budget NUMERIC(20, 0) NOT NULL CHECK (
        cal_tribute_budget BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND cal_tribute_budget = pg_catalog.trunc(cal_earned * 1000 / 10000)
    ),
    release_plan_hash_hex CHAR(64) NOT NULL CHECK (
        release_plan_hash_hex ~ '^[0-9a-f]{64}$'
    ),
    released_at BIGINT NOT NULL,
    released_slot NUMERIC(20, 0) NOT NULL CHECK (
        released_slot BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    release_settlement_week NUMERIC(20, 0) NOT NULL CHECK (
        release_settlement_week BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    attester TEXT NOT NULL CHECK (pg_catalog.btrim(attester) <> ''),
    chain_slot BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    bump SMALLINT NOT NULL CHECK (bump BETWEEN 0 AND 255)
);

CREATE UNIQUE INDEX idx_indexed_held_release_authority_threshold
    ON public.indexed_held_ride_release_authorities(
        threshold_authority_id_hex,
        ride_attestation_pda
    );
CREATE INDEX idx_indexed_held_release_authority_rider
    ON public.indexed_held_ride_release_authorities(
        rider_pubkey,
        release_settlement_week
    );
CREATE INDEX idx_indexed_cal_receipts_release_authority
    ON public.indexed_cal_mint_receipts(release_authority_pda)
    WHERE release_authority_pda IS NOT NULL;
CREATE INDEX idx_indexed_completion_receipts_release_authority
    ON public.indexed_climb_completion_receipts(release_authority_pda)
    WHERE release_authority_pda IS NOT NULL;
CREATE INDEX idx_indexed_completion_flows_release_authority
    ON public.indexed_climb_completion_flows(release_authority_pda)
    WHERE release_authority_pda IS NOT NULL;

CREATE OR REPLACE FUNCTION public.enforce_indexed_held_release_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'indexed held-ride release authority is immutable';
    END IF;
    IF NEW.pda IS DISTINCT FROM OLD.pda
       OR NEW.ride_attestation_pda IS DISTINCT FROM OLD.ride_attestation_pda
       OR NEW.rider_pubkey IS DISTINCT FROM OLD.rider_pubkey
       OR NEW.threshold_authority_id_hex IS DISTINCT FROM OLD.threshold_authority_id_hex
       OR NEW.threshold_authority_commitment_hex IS DISTINCT FROM OLD.threshold_authority_commitment_hex
       OR NEW.threshold_effective_at IS DISTINCT FROM OLD.threshold_effective_at
       OR NEW.threshold_w IS DISTINCT FROM OLD.threshold_w
       OR NEW.threshold_policy_version IS DISTINCT FROM OLD.threshold_policy_version
       OR NEW.economic_tss IS DISTINCT FROM OLD.economic_tss
       OR NEW.cal_earned IS DISTINCT FROM OLD.cal_earned
       OR NEW.cal_tribute_budget IS DISTINCT FROM OLD.cal_tribute_budget
       OR NEW.release_plan_hash_hex IS DISTINCT FROM OLD.release_plan_hash_hex
       OR NEW.released_at IS DISTINCT FROM OLD.released_at
       OR NEW.released_slot IS DISTINCT FROM OLD.released_slot
       OR NEW.release_settlement_week IS DISTINCT FROM OLD.release_settlement_week
       OR NEW.attester IS DISTINCT FROM OLD.attester
       OR NEW.bump IS DISTINCT FROM OLD.bump THEN
        RAISE EXCEPTION 'indexed held-ride release authority is immutable';
    END IF;
    RETURN NEW;
END;
$$;

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
    v_tribute_weight NUMERIC;
    v_intensity_bps NUMERIC;
    v_evidence_hash BYTEA;
    v_expected_receipt_pda TEXT;
    v_total_tribute NUMERIC := 0;
    v_total_tribute_weight NUMERIC := 0;
    v_base_tribute_sum NUMERIC;
    v_base_tribute NUMERIC;
    v_tribute_remainder NUMERIC;
    v_undistributed_tribute NUMERIC;
    v_remainder_rank NUMERIC;
    v_expected_tribute NUMERIC;
    v_is_replay BOOLEAN := false;
BEGIN
    IF pg_catalog.jsonb_typeof(p_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(p_steps) <> 'array' THEN
        RAISE EXCEPTION 'Threshold release snapshot and step array are required';
    END IF;
    v_item_id := (p_snapshot->>'batch_item_id')::UUID;
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
    SELECT * INTO v_hold
    FROM public.reward_threshold_provisional_holds
    WHERE id = v_item.hold_id;
    SELECT * INTO v_admission
    FROM public.reward_threshold_provisional_hold_admissions
    WHERE hold_id = v_hold.id
      AND ride_id = v_hold.ride_id;
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
          SELECT 1
          FROM public.ride_economic_completion_steps AS normal_step
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
       OR (p_snapshot->>'reward_ftp_authority_id')::UUID IS DISTINCT FROM
            v_authority.id
       OR (p_snapshot->>'reward_ftp_w')::INTEGER IS DISTINCT FROM
            v_authority.ftp_w
       OR p_snapshot->>'reward_ftp_source' IS DISTINCT FROM 'derived_eftp'
       OR p_snapshot->>'reward_ftp_policy_version' IS DISTINCT FROM
            'reward_ftp_policy_2026_08_24_threshold_v1'
       OR p_snapshot->>'wallet' IS DISTINCT FROM v_plan.wallet
       OR (p_snapshot->>'admitted_at')::TIMESTAMPTZ IS DISTINCT FROM
            v_admission.admitted_at
       OR (p_snapshot->>'established_at')::TIMESTAMPTZ IS DISTINCT FROM
            v_batch.established_at
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
       OR v_tribute_budget <> pg_catalog.trunc(v_exact_cal * 1000 / 10000) THEN
        RAISE EXCEPTION 'Threshold release CAL and tribute budget are not exact';
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

    FOR v_step IN
        SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
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
        v_tribute_weight := public.require_ride_economic_uint(
            v_step->'tribute_weight', 'tribute_weight', 18446744073709551615
        );
        v_intensity_bps := public.require_ride_economic_uint(
            v_step->'intensity_bps', 'intensity_bps', 4294967295
        );
        IF public.require_ride_economic_uint(
            v_step->'completion_evidence_version',
            'completion_evidence_version', 255
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
           OR (v_hold_step->>'completed_at')::TIMESTAMPTZ IS DISTINCT FROM
                v_completed_at
           OR v_step->'segment_start_offset_s' IS DISTINCT FROM
                v_hold_step->'segment_start_offset_s'
           OR v_step->'segment_end_offset_s' IS DISTINCT FROM
                v_hold_step->'segment_end_offset_s'
           OR v_step->'segment_np_w' IS DISTINCT FROM
                v_hold_step->'segment_np_w'
           OR v_step->'segment_power_sample_count' IS DISTINCT FROM
                v_hold_step->'segment_power_sample_count'
           OR v_step->'segment_power_coverage_bps' IS DISTINCT FROM
                v_hold_step->'segment_power_coverage_bps'
           OR v_step->'segment_power_metrics_version' IS DISTINCT FROM
                v_hold_step->'segment_power_metrics_version'
           OR v_step->'tribute_weight' IS DISTINCT FROM
                v_hold_step->'tribute_weight'
           OR v_step->'climb_distance_m' IS DISTINCT FROM
                v_hold_step->'climb_distance_m'
           OR v_step->'climb_vert_m' IS DISTINCT FROM
                v_hold_step->'climb_vert_m' THEN
            RAISE EXCEPTION 'Threshold release step conflicts with frozen hold evidence';
        END IF;
        IF v_tribute_weight IS DISTINCT FROM (
                CASE WHEN v_segment_np_w IS NULL THEN 0
                     ELSE v_time_s * v_segment_np_w END
           ) OR v_intensity_bps IS DISTINCT FROM (
                CASE WHEN v_segment_np_w IS NULL THEN 0
                     ELSE pg_catalog.trunc(
                         v_segment_np_w * 10000 / v_authority.ftp_w
                     ) END
           ) THEN
            RAISE EXCEPTION 'Threshold release step economics are not canonical';
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
            'segment_power_sample_count',
                v_hold_step->'segment_power_sample_count',
            'segment_power_coverage_bps',
                v_hold_step->'segment_power_coverage_bps',
            'segment_power_metrics_version',
                v_hold_step->>'segment_power_metrics_version',
            'tribute_weight', v_tribute_weight,
            'climb_distance_m', v_hold_step->'climb_distance_m',
            'climb_vert_m', v_hold_step->'climb_vert_m',
            'completion_evidence_version', 3,
            'completion_evidence_hash_hex',
                pg_catalog.encode(v_evidence_hash, 'hex'),
            'expected_receipt_pda', v_expected_receipt_pda
        );
        v_canonical_steps := v_canonical_steps
            || pg_catalog.jsonb_build_array(v_canonical_step);
        v_total_tribute := v_total_tribute + v_tribute;
        v_total_tribute_weight := v_total_tribute_weight + v_tribute_weight;
        v_expected_step_index := v_expected_step_index + 1;
    END LOOP;
    IF v_total_tribute > v_tribute_budget THEN
        RAISE EXCEPTION 'Threshold release steps exceed exact tribute budget';
    END IF;
    IF v_total_tribute_weight = 0 AND v_total_tribute <> 0 THEN
        RAISE EXCEPTION 'Zero-weight Threshold release steps cannot receive tribute';
    END IF;
    IF v_total_tribute_weight > 0 THEN
        SELECT COALESCE(pg_catalog.sum(pg_catalog.trunc(
            public.require_ride_economic_uint(
                element.value->'tribute_weight', 'tribute_weight',
                18446744073709551615
            ) * v_tribute_budget / v_total_tribute_weight
        )), 0)
        INTO v_base_tribute_sum
        FROM pg_catalog.jsonb_array_elements(p_steps) AS element(value);
        v_undistributed_tribute := v_tribute_budget - v_base_tribute_sum;

        FOR v_step IN
            SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
        LOOP
            v_vault_id := public.require_ride_economic_uint(
                v_step->'vault_id', 'vault_id', 18446744073709551615
            );
            v_tribute_weight := public.require_ride_economic_uint(
                v_step->'tribute_weight', 'tribute_weight',
                18446744073709551615
            );
            v_tribute := public.require_ride_economic_uint(
                v_step->'exact_tribute_base_units',
                'exact_tribute_base_units', 18446744073709551615
            );
            v_base_tribute := pg_catalog.trunc(
                v_tribute_weight * v_tribute_budget / v_total_tribute_weight
            );
            v_tribute_remainder := pg_catalog.mod(
                v_tribute_weight * v_tribute_budget,
                v_total_tribute_weight
            );
            SELECT pg_catalog.count(*)
            INTO v_remainder_rank
            FROM pg_catalog.jsonb_array_elements(p_steps) AS ranked(value)
            WHERE pg_catalog.mod(
                    public.require_ride_economic_uint(
                        ranked.value->'tribute_weight', 'tribute_weight',
                        18446744073709551615
                    ) * v_tribute_budget,
                    v_total_tribute_weight
                  ) > v_tribute_remainder
               OR (
                    pg_catalog.mod(
                        public.require_ride_economic_uint(
                            ranked.value->'tribute_weight', 'tribute_weight',
                            18446744073709551615
                        ) * v_tribute_budget,
                        v_total_tribute_weight
                    ) = v_tribute_remainder
                    AND public.require_ride_economic_uint(
                        ranked.value->'vault_id', 'vault_id',
                        18446744073709551615
                    ) < v_vault_id
               );
            v_expected_tribute := v_base_tribute + CASE
                WHEN v_remainder_rank < v_undistributed_tribute THEN 1
                ELSE 0
            END;
            IF v_tribute IS DISTINCT FROM v_expected_tribute THEN
                RAISE EXCEPTION 'Threshold release tribute allocation is not canonical';
            END IF;
        END LOOP;
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
        'expected_release_authority_pda',
            p_snapshot->>'expected_release_authority_pda',
        'expected_cal_receipt_pda', p_snapshot->>'expected_cal_receipt_pda'
    );
    v_snapshot_evidence := pg_catalog.jsonb_build_object(
        'domain', 'BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1',
        'plan', v_canonical_plan,
        'steps', v_canonical_steps,
        'hold_evidence_hash_hex',
            pg_catalog.encode(v_hold.hold_evidence_hash, 'hex'),
        'admission_plan_evidence_hash_hex',
            pg_catalog.encode(v_hold.admission_plan_evidence_hash, 'hex')
    );
    IF pg_catalog.jsonb_typeof(v_submitted_snapshot_evidence->'plan') <> 'object'
       OR pg_catalog.jsonb_typeof(v_submitted_snapshot_evidence->'steps') <> 'array'
       OR pg_catalog.jsonb_array_length(
            v_submitted_snapshot_evidence->'steps'
          ) <> pg_catalog.jsonb_array_length(p_steps)
       OR (
            v_submitted_snapshot_evidence->'plan'->>'admitted_at'
          )::TIMESTAMPTZ IS DISTINCT FROM v_admission.admitted_at
       OR (
            v_submitted_snapshot_evidence->'plan'->>'established_at'
          )::TIMESTAMPTZ IS DISTINCT FROM v_batch.established_at
       OR (
            v_submitted_snapshot_evidence->'plan'->>'economic_tss'
          )::NUMERIC IS DISTINCT FROM v_economic_tss THEN
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
            ARRAY[
                'steps', v_normalize_step_index::TEXT, 'completed_at'
            ],
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

    FOR v_step IN
        SELECT value FROM pg_catalog.jsonb_array_elements(p_steps)
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

CREATE TRIGGER trg_indexed_held_release_authority_immutable
    BEFORE UPDATE OR DELETE
    ON public.indexed_held_ride_release_authorities
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_indexed_held_release_immutability();

ALTER TABLE public.indexed_held_ride_release_authorities
    ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.indexed_held_ride_release_authorities
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON public.indexed_held_ride_release_authorities TO service_role;

CREATE TABLE public.reward_threshold_provisional_holds (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    -- Frozen identity remains after mutable ride deletion, matching the
    -- retained ride_economic_plans authority pattern.
    ride_id UUID NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES public.users(id),
    held_at TIMESTAMPTZ NOT NULL,
    ride_started_at TIMESTAMPTZ NOT NULL,
    admission_plan_evidence_hash BYTEA NOT NULL
        CHECK (pg_catalog.octet_length(admission_plan_evidence_hash) = 32),
    hold_evidence JSONB NOT NULL
        CHECK (pg_catalog.jsonb_typeof(hold_evidence) = 'object'),
    hold_evidence_hash BYTEA NOT NULL UNIQUE
        CHECK (pg_catalog.octet_length(hold_evidence_hash) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CHECK (held_at >= ride_started_at)
);

-- Hold evidence is frozen before the parent transaction is admitted. The
-- separate one-time admission row binds the finalized RideAttestation clock
-- that the protocol also uses for the inclusive 16-week eligibility check.
CREATE TABLE public.reward_threshold_provisional_hold_admissions (
    hold_id UUID PRIMARY KEY
        REFERENCES public.reward_threshold_provisional_holds(id),
    ride_id UUID NOT NULL UNIQUE,
    admitted_at TIMESTAMPTZ NOT NULL,
    ride_attestation_pda TEXT NOT NULL UNIQUE
        CHECK (pg_catalog.btrim(ride_attestation_pda) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp()
);

CREATE TABLE public.reward_threshold_release_batches (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id),
    established_authority_id UUID NOT NULL UNIQUE
        REFERENCES public.reward_ftp_authorities(id),
    established_at TIMESTAMPTZ NOT NULL,
    reward_ftp_w INTEGER NOT NULL CHECK (reward_ftp_w BETWEEN 50 AND 500),
    reward_ftp_source TEXT NOT NULL CHECK (reward_ftp_source = 'derived_eftp'),
    reward_ftp_policy_version TEXT NOT NULL CHECK (
        reward_ftp_policy_version =
            'reward_ftp_policy_2026_08_24_threshold_v1'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp()
);

CREATE TABLE public.reward_threshold_release_batch_items (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES public.reward_threshold_release_batches(id),
    hold_id UUID NOT NULL UNIQUE
        REFERENCES public.reward_threshold_provisional_holds(id),
    disposition TEXT NOT NULL CHECK (disposition IN ('eligible', 'lapsed')),
    eligibility_cutoff_at TIMESTAMPTZ NOT NULL,
    established_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    UNIQUE (batch_id, hold_id),
    CHECK (eligibility_cutoff_at = established_at - INTERVAL '16 weeks')
);

CREATE TABLE public.reward_threshold_release_snapshots (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    batch_item_id UUID NOT NULL UNIQUE
        REFERENCES public.reward_threshold_release_batch_items(id),
    ride_id UUID NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES public.users(id),
    reward_ftp_authority_id UUID NOT NULL
        REFERENCES public.reward_ftp_authorities(id),
    reward_ftp_w INTEGER NOT NULL CHECK (reward_ftp_w BETWEEN 50 AND 500),
    reward_ftp_source TEXT NOT NULL CHECK (reward_ftp_source = 'derived_eftp'),
    reward_ftp_policy_version TEXT NOT NULL CHECK (
        reward_ftp_policy_version =
            'reward_ftp_policy_2026_08_24_threshold_v1'
    ),
    economic_tss NUMERIC NOT NULL CHECK (economic_tss >= 0),
    exact_cal_base_units NUMERIC(20, 0) NOT NULL CHECK (
        exact_cal_base_units BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    exact_tribute_budget_base_units NUMERIC(20, 0) NOT NULL CHECK (
        exact_tribute_budget_base_units BETWEEN
            0 AND 18446744073709551615::NUMERIC
        AND exact_tribute_budget_base_units =
            pg_catalog.trunc(exact_cal_base_units * 1000 / 10000)
    ),
    snapshot_evidence JSONB NOT NULL
        CHECK (pg_catalog.jsonb_typeof(snapshot_evidence) = 'object'),
    snapshot_evidence_hash BYTEA NOT NULL UNIQUE
        CHECK (pg_catalog.octet_length(snapshot_evidence_hash) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp()
);

-- Planner leases are operational and deliberately separate from the four
-- immutable authority tables.
CREATE TABLE public.reward_threshold_release_item_claims (
    batch_item_id UUID PRIMARY KEY
        REFERENCES public.reward_threshold_release_batch_items(id),
    lease_owner UUID NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    consumed_snapshot_id UUID UNIQUE
        REFERENCES public.reward_threshold_release_snapshots(id),
    consumed_at TIMESTAMPTZ,
    terminal_disposition TEXT CHECK (
        terminal_disposition IN ('review', 'not_counted')
    ),
    terminal_reason TEXT,
    terminal_evidence JSONB CHECK (
        terminal_evidence IS NULL
        OR pg_catalog.jsonb_typeof(terminal_evidence) = 'object'
    ),
    terminal_at TIMESTAMPTZ,
    repair_reason TEXT,
    repaired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CHECK (
        (
            consumed_snapshot_id IS NULL
            AND consumed_at IS NULL
            AND terminal_disposition IS NULL
            AND terminal_reason IS NULL
            AND terminal_evidence IS NULL
            AND terminal_at IS NULL
        )
        OR (
            consumed_snapshot_id IS NOT NULL
            AND consumed_at IS NOT NULL
            AND terminal_disposition IS NULL
            AND terminal_reason IS NULL
            AND terminal_evidence IS NULL
            AND terminal_at IS NULL
        )
        OR (
            consumed_snapshot_id IS NULL
            AND consumed_at IS NULL
            AND terminal_disposition IS NOT NULL
            AND pg_catalog.btrim(terminal_reason) <> ''
            AND terminal_evidence IS NOT NULL
            AND terminal_at IS NOT NULL
        )
    )
);

CREATE TABLE public.reward_threshold_release_executions (
    snapshot_id UUID PRIMARY KEY
        REFERENCES public.reward_threshold_release_snapshots(id),
    wallet TEXT NOT NULL CHECK (pg_catalog.btrim(wallet) <> ''),
    ride_hash BYTEA NOT NULL CHECK (pg_catalog.octet_length(ride_hash) = 32),
    release_plan_evidence_hash BYTEA NOT NULL UNIQUE
        CHECK (pg_catalog.octet_length(release_plan_evidence_hash) = 32),
    expected_release_authority_pda TEXT NOT NULL UNIQUE
        CHECK (pg_catalog.btrim(expected_release_authority_pda) <> ''),
    expected_cal_receipt_pda TEXT NOT NULL UNIQUE
        CHECK (pg_catalog.btrim(expected_cal_receipt_pda) <> ''),
    state TEXT NOT NULL DEFAULT 'planned' CHECK (state IN (
        'planned', 'release_authority_confirmed', 'completions_confirmed',
        'cal_confirmed', 'projections_reconciled', 'complete', 'review'
    )),
    release_authority_actual_tx_signature TEXT,
    release_authority_confirmed_at TIMESTAMPTZ,
    cal_actual_tx_signature TEXT,
    cal_confirmed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    last_error TEXT,
    review_reason TEXT,
    review_from_state TEXT CHECK (
        review_from_state IS NULL
        OR review_from_state IN (
            'planned', 'release_authority_confirmed', 'cal_confirmed',
            'completions_confirmed', 'projections_reconciled', 'complete'
        )
    ),
    review_evidence JSONB CHECK (
        review_evidence IS NULL
        OR pg_catalog.jsonb_typeof(review_evidence) = 'object'
    ),
    terminal_projected_at TIMESTAMPTZ,
    lock_version BIGINT NOT NULL DEFAULT 0 CHECK (lock_version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CHECK (
        release_authority_actual_tx_signature IS NULL
        OR release_authority_actual_tx_signature NOT LIKE 'exists:%'
    ),
    CHECK (
        cal_actual_tx_signature IS NULL
        OR cal_actual_tx_signature NOT LIKE 'exists:%'
    ),
    CHECK (
        state IN ('planned', 'review')
        OR release_authority_confirmed_at IS NOT NULL
    ),
    CHECK (
        state NOT IN (
            'cal_confirmed', 'completions_confirmed',
            'projections_reconciled', 'complete'
        )
        OR cal_confirmed_at IS NOT NULL
    ),
    CHECK (
        (lease_owner IS NULL AND lease_expires_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

CREATE TABLE public.reward_threshold_release_steps (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    snapshot_id UUID NOT NULL
        REFERENCES public.reward_threshold_release_snapshots(id),
    step_index INTEGER NOT NULL CHECK (step_index >= 0),
    pattern_id UUID NOT NULL,
    vault_id NUMERIC(20, 0) NOT NULL CHECK (
        vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    vault_signature TEXT NOT NULL CHECK (pg_catalog.btrim(vault_signature) <> ''),
    completion_time_s BIGINT NOT NULL CHECK (
        completion_time_s BETWEEN 1 AND 4294967295
    ),
    completed_at TIMESTAMPTZ NOT NULL,
    exact_tribute_base_units NUMERIC(20, 0) NOT NULL CHECK (
        exact_tribute_base_units BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    completion_evidence_version SMALLINT NOT NULL DEFAULT 3
        CHECK (completion_evidence_version = 3),
    completion_evidence_hash BYTEA NOT NULL UNIQUE
        CHECK (pg_catalog.octet_length(completion_evidence_hash) = 32),
    expected_receipt_pda TEXT NOT NULL UNIQUE
        CHECK (pg_catalog.btrim(expected_receipt_pda) <> ''),
    state TEXT NOT NULL DEFAULT 'planned'
        CHECK (state IN ('planned', 'confirmed', 'projected', 'review')),
    actual_tx_signature TEXT,
    chain_confirmed_at TIMESTAMPTZ,
    projected_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    UNIQUE (snapshot_id, step_index),
    UNIQUE (snapshot_id, vault_id),
    CHECK (actual_tx_signature IS NULL OR actual_tx_signature NOT LIKE 'exists:%'),
    CHECK (state IN ('planned', 'review') OR chain_confirmed_at IS NOT NULL),
    CHECK (state <> 'projected' OR projected_at IS NOT NULL)
);

CREATE INDEX idx_reward_threshold_holds_user_held
    ON public.reward_threshold_provisional_holds(user_id, held_at, id);
CREATE INDEX idx_reward_threshold_hold_admissions_clock
    ON public.reward_threshold_provisional_hold_admissions(admitted_at, hold_id);
CREATE INDEX idx_reward_threshold_release_items_batch
    ON public.reward_threshold_release_batch_items(batch_id, disposition, id);
CREATE INDEX idx_reward_threshold_release_item_claim_expiry
    ON public.reward_threshold_release_item_claims(lease_expires_at)
    WHERE consumed_snapshot_id IS NULL AND terminal_disposition IS NULL;
CREATE INDEX idx_reward_threshold_release_execution_due
    ON public.reward_threshold_release_executions(next_attempt_at, created_at)
    WHERE state <> 'review'
      AND (state <> 'complete' OR terminal_projected_at IS NULL);
CREATE INDEX idx_reward_threshold_release_execution_lease
    ON public.reward_threshold_release_executions(lease_expires_at)
    WHERE lease_owner IS NOT NULL;
CREATE INDEX idx_reward_threshold_release_steps_snapshot_state
    ON public.reward_threshold_release_steps(snapshot_id, state, step_index);

CREATE OR REPLACE FUNCTION public.prevent_reward_threshold_hold_release_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    RAISE EXCEPTION 'Threshold hold and release authority is immutable';
END;
$$;

CREATE TRIGGER trg_reward_threshold_provisional_holds_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_provisional_holds
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_reward_threshold_hold_release_mutation();
CREATE TRIGGER trg_reward_threshold_provisional_hold_admissions_immutable
    BEFORE UPDATE OR DELETE
    ON public.reward_threshold_provisional_hold_admissions
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_reward_threshold_hold_release_mutation();
CREATE TRIGGER trg_reward_threshold_release_batches_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_release_batches
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_reward_threshold_hold_release_mutation();
CREATE TRIGGER trg_reward_threshold_release_batch_items_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_release_batch_items
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_reward_threshold_hold_release_mutation();
CREATE TRIGGER trg_reward_threshold_release_snapshots_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_release_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_reward_threshold_hold_release_mutation();

-- Migration 154 extended the account-deletion policy gate through derived
-- Threshold evidence. Extend the same human-gated, anonymize-not-erase
-- authority over the hold/release tables introduced here.
ALTER FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    RENAME TO br_account_deletion_db_blockers_pre_threshold_hold_release;
REVOKE ALL ON FUNCTION
    public.br_account_deletion_db_blockers_pre_threshold_hold_release(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.br_account_deletion_db_blockers(
    p_user_id UUID,
    p_wallet TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_blockers JSONB;
    v_count BIGINT;
BEGIN
    v_blockers := COALESCE(
        public.br_account_deletion_db_blockers_pre_threshold_hold_release(
            p_user_id, p_wallet
        ),
        '[]'::JSONB
    );
    SELECT
        (SELECT pg_catalog.count(*)
         FROM public.reward_threshold_provisional_holds
         WHERE user_id = p_user_id)
        + (SELECT pg_catalog.count(*)
           FROM public.reward_threshold_release_batches
           WHERE user_id = p_user_id)
        + (SELECT pg_catalog.count(*)
           FROM public.reward_threshold_release_snapshots
           WHERE user_id = p_user_id)
        + (SELECT pg_catalog.count(*)
           FROM public.indexed_held_ride_release_authorities
           WHERE rider_pubkey = p_wallet)
    INTO v_count;
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required',
                'category', 'policy',
                'count', v_count,
                'source', 'reward_threshold_hold_release_evidence',
                'action', 'contact_support'
            )
        );
    END IF;
    RETURN v_blockers;
END;
$$;
REVOKE ALL ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    TO service_role;

-- The indexed authority is keyed only by the rider wallet. Serialize its
-- writes with account-deletion request creation before the generic fence can
-- take its no-active-request fast path. This also rejects tombstoned wallets
-- while permitting chain authorities for wallets that never had an account.
CREATE OR REPLACE FUNCTION
public.reward_threshold_indexed_release_wallet_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    PERFORM public.br_account_deletion_assert_wallet_write_allowed(
        NEW.rider_pubkey
    );
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION
    public.reward_threshold_indexed_release_wallet_fence()
    FROM PUBLIC, anon, authenticated, service_role;

CREATE TRIGGER account_deletion_00_threshold_release_wallet_lock
    BEFORE INSERT OR UPDATE OF rider_pubkey
    ON public.indexed_held_ride_release_authorities
    FOR EACH ROW
    EXECUTE FUNCTION public.reward_threshold_indexed_release_wallet_fence();
CREATE TRIGGER account_deletion_write_fence
    BEFORE INSERT OR UPDATE OR DELETE
    ON public.indexed_held_ride_release_authorities
    FOR EACH ROW
    EXECUTE FUNCTION public.account_deletion_write_fence('true');

DO $$
DECLARE
    v_table TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'reward_threshold_provisional_holds',
        'reward_threshold_release_batches',
        'reward_threshold_release_snapshots'
    ] LOOP
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_00_threshold_owner_lock '
            'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.reward_threshold_account_owner_fence()',
            v_table
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence '
            'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.account_deletion_write_fence(''false'')',
            v_table
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.validate_reward_threshold_release_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_item public.reward_threshold_release_batch_items%ROWTYPE;
    v_hold public.reward_threshold_provisional_holds%ROWTYPE;
    v_batch public.reward_threshold_release_batches%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
BEGIN
    SELECT * INTO v_item
    FROM public.reward_threshold_release_batch_items
    WHERE id = NEW.batch_item_id;
    IF NOT FOUND OR v_item.disposition IS DISTINCT FROM 'eligible' THEN
        RAISE EXCEPTION 'Threshold release snapshot requires an eligible batch item';
    END IF;

    SELECT * INTO v_hold
    FROM public.reward_threshold_provisional_holds
    WHERE id = v_item.hold_id;
    SELECT * INTO v_batch
    FROM public.reward_threshold_release_batches
    WHERE id = v_item.batch_id;
    SELECT * INTO v_authority
    FROM public.reward_ftp_authorities
    WHERE id = v_batch.established_authority_id;

    IF NEW.ride_id IS DISTINCT FROM v_hold.ride_id
       OR NEW.user_id IS DISTINCT FROM v_hold.user_id
       OR NEW.user_id IS DISTINCT FROM v_batch.user_id
       OR NEW.reward_ftp_authority_id IS DISTINCT FROM v_authority.id
       OR NEW.reward_ftp_w IS DISTINCT FROM v_authority.ftp_w
       OR NEW.reward_ftp_source IS DISTINCT FROM v_authority.source
       OR NEW.reward_ftp_policy_version IS DISTINCT FROM
            'reward_ftp_policy_2026_08_24_threshold_v1' THEN
        RAISE EXCEPTION 'Threshold release snapshot conflicts with its sealed authority';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reward_threshold_release_snapshot_validate
    BEFORE INSERT ON public.reward_threshold_release_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION public.validate_reward_threshold_release_snapshot();

CREATE OR REPLACE FUNCTION public.enforce_reward_threshold_release_execution_frozen()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
       OR NEW.wallet IS DISTINCT FROM OLD.wallet
       OR NEW.ride_hash IS DISTINCT FROM OLD.ride_hash
       OR NEW.release_plan_evidence_hash IS DISTINCT FROM OLD.release_plan_evidence_hash
       OR NEW.expected_release_authority_pda IS DISTINCT FROM OLD.expected_release_authority_pda
       OR NEW.expected_cal_receipt_pda IS DISTINCT FROM OLD.expected_cal_receipt_pda
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Threshold release execution authority is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reward_threshold_release_execution_frozen
    BEFORE UPDATE ON public.reward_threshold_release_executions
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_reward_threshold_release_execution_frozen();

CREATE OR REPLACE FUNCTION public.enforce_reward_threshold_release_step_frozen()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.snapshot_id IS DISTINCT FROM OLD.snapshot_id
       OR NEW.step_index IS DISTINCT FROM OLD.step_index
       OR NEW.pattern_id IS DISTINCT FROM OLD.pattern_id
       OR NEW.vault_id IS DISTINCT FROM OLD.vault_id
       OR NEW.vault_signature IS DISTINCT FROM OLD.vault_signature
       OR NEW.completion_time_s IS DISTINCT FROM OLD.completion_time_s
       OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
       OR NEW.exact_tribute_base_units IS DISTINCT FROM OLD.exact_tribute_base_units
       OR NEW.completion_evidence_version IS DISTINCT FROM OLD.completion_evidence_version
       OR NEW.completion_evidence_hash IS DISTINCT FROM OLD.completion_evidence_hash
       OR NEW.expected_receipt_pda IS DISTINCT FROM OLD.expected_receipt_pda
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'Threshold release step authority is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reward_threshold_release_step_frozen
    BEFORE UPDATE ON public.reward_threshold_release_steps
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_reward_threshold_release_step_frozen();

ALTER TABLE public.reward_threshold_provisional_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_provisional_hold_admissions
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_batch_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_item_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_release_steps ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.reward_threshold_provisional_holds
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_provisional_hold_admissions
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_batches
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_batch_items
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_snapshots
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_item_claims
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_executions
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_release_steps
    FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT ON public.reward_threshold_provisional_holds TO service_role;
GRANT SELECT ON public.reward_threshold_provisional_hold_admissions
    TO service_role;
GRANT SELECT ON public.reward_threshold_release_batches TO service_role;
GRANT SELECT ON public.reward_threshold_release_batch_items TO service_role;
GRANT SELECT ON public.reward_threshold_release_snapshots TO service_role;
GRANT SELECT ON public.reward_threshold_release_item_claims TO service_role;
GRANT SELECT ON public.reward_threshold_release_executions TO service_role;
GRANT SELECT ON public.reward_threshold_release_steps TO service_role;

-- A provisional parent deliberately freezes zero chain economics while the
-- immutable ride row retains its 200 W display-derived economic_tss.  This is
-- the only plan policy allowed to differ from the ride TSS snapshot.
DO $threshold_default_cutover$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.ride_economic_plans AS plan
        WHERE plan.reward_ftp_w = 200
          AND plan.reward_ftp_source = 'network_default'
          AND plan.reward_ftp_authority_id IS NULL
          AND (
              plan.exact_cal_base_units <> 0
              OR plan.exact_tribute_base_units <> 0
              OR (
                  plan.state NOT IN ('complete', 'review')
                  AND plan.total_tss <> 0
              )
              OR (
                  plan.state NOT IN ('complete', 'review')
                  AND EXISTS (
                      SELECT 1
                      FROM public.ride_economic_completion_steps AS step
                      WHERE step.ride_id = plan.ride_id
                        AND step.exact_tribute_base_units <> 0
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION
            'Threshold cutover blocked by executable 200 W network-default economics'
            USING HINT =
                'Review the affected immutable plan/chain authority before retrying migration 155';
    END IF;
END;
$threshold_default_cutover$;

CREATE OR REPLACE FUNCTION public.enforce_plan_reward_ftp_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.reward_ftp_w IS NOT NULL AND (
        NEW.reward_ftp_w IS DISTINCT FROM OLD.reward_ftp_w
        OR NEW.reward_ftp_source IS DISTINCT FROM OLD.reward_ftp_source
        OR NEW.reward_ftp_authority_id IS DISTINCT FROM OLD.reward_ftp_authority_id
        OR NEW.reward_ftp_policy_version IS DISTINCT FROM OLD.reward_ftp_policy_version
    ) THEN
        RAISE EXCEPTION 'frozen plan reward FTP provenance cannot be changed';
    END IF;

    IF NEW.reward_ftp_w IS NULL THEN
        IF NEW.reward_ftp_source IS NOT NULL
           OR NEW.reward_ftp_authority_id IS NOT NULL
           OR NEW.reward_ftp_policy_version IS NOT NULL THEN
            RAISE EXCEPTION 'partial plan reward FTP snapshot is forbidden';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reward_ftp_w NOT BETWEEN 50 AND 500
       OR NEW.reward_ftp_policy_version NOT IN (
            'reward_ftp_policy_2026_07_14',
            'reward_ftp_policy_2026_08_24_threshold_v1'
       ) THEN
        RAISE EXCEPTION 'invalid frozen plan reward FTP snapshot';
    END IF;
    IF NEW.reward_ftp_source = 'network_default' THEN
        IF NEW.reward_ftp_w <> 200 OR NEW.reward_ftp_authority_id IS NOT NULL THEN
            RAISE EXCEPTION 'inconsistent plan network-default reward FTP';
        END IF;
        IF NEW.total_tss <> 0
           OR NEW.exact_cal_base_units <> 0
           OR NEW.exact_tribute_base_units <> 0 THEN
            RAISE EXCEPTION '200 W network default cannot authorize counted economics';
        END IF;
    ELSIF NOT EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.id = NEW.reward_ftp_authority_id
          AND authority.user_id = NEW.user_id
          AND authority.ftp_w = NEW.reward_ftp_w
          AND authority.source = NEW.reward_ftp_source
          AND authority.effective_at <= NEW.started_at
    ) THEN
        RAISE EXCEPTION 'frozen plan lacks matching verified reward FTP authority';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.rides AS ride
        WHERE ride.id = NEW.ride_id
          AND ride.user_id = NEW.user_id
          AND ride.reward_ftp_w = NEW.reward_ftp_w
          AND ride.reward_ftp_source = NEW.reward_ftp_source
          AND ride.reward_ftp_authority_id IS NOT DISTINCT FROM
                NEW.reward_ftp_authority_id
          AND ride.reward_ftp_policy_version = NEW.reward_ftp_policy_version
          AND ride.reward_ftp_activity_started_at = NEW.started_at
          AND ride.economic_tss IS NOT NULL
          AND (
              pg_catalog.trunc(ride.economic_tss)::BIGINT = NEW.total_tss
              OR (
                  NEW.reward_policy = 'threshold_provisional_hold_v1'
                  AND NEW.reward_ftp_w = 200
                  AND NEW.reward_ftp_source = 'network_default'
                  AND NEW.reward_ftp_authority_id IS NULL
                  AND NEW.total_tss = 0
                  AND NEW.exact_cal_base_units = 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.ride_economic_completion_steps AS step
                      WHERE step.ride_id = NEW.ride_id
                  )
              )
          )
    ) THEN
        RAISE EXCEPTION 'frozen plan reward FTP or economic TSS differs from ride snapshot';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.prevent_network_default_completion_step()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.exact_tribute_base_units <> 0 AND EXISTS (
        SELECT 1
        FROM public.ride_economic_plans AS plan
        WHERE plan.ride_id = NEW.ride_id
          AND plan.reward_ftp_w = 200
          AND plan.reward_ftp_source = 'network_default'
          AND plan.reward_ftp_authority_id IS NULL
    ) THEN
        RAISE EXCEPTION '200 W network default cannot authorize completion economics';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_prevent_network_default_completion_step
    BEFORE INSERT ON public.ride_economic_completion_steps
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_network_default_completion_step();

CREATE OR REPLACE FUNCTION public.create_reward_threshold_release_batch(
    p_established_authority_id UUID,
    p_created_at TIMESTAMPTZ
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_batch public.reward_threshold_release_batches%ROWTYPE;
BEGIN
    IF p_established_authority_id IS NULL OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'Threshold release authority and creation clock are required';
    END IF;

    SELECT * INTO v_authority
    FROM public.reward_ftp_authorities
    WHERE id = p_established_authority_id;
    IF NOT FOUND
       OR v_authority.source IS DISTINCT FROM 'derived_eftp'
       OR v_authority.verified_by IS DISTINCT FROM 'derived-threshold-v1'
       OR v_authority.evidence->>'policy_version' IS DISTINCT FROM
            'reward_ftp_policy_2026_08_24_threshold_v1' THEN
        RAISE EXCEPTION 'Threshold release requires a sealed derived authority';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.reward_threshold_pending_promotions AS promotion
        WHERE promotion.user_id = v_authority.user_id
          AND promotion.status = 'sealed'
          AND promotion.sealed_authority_id = v_authority.id
          AND promotion.promotion_kind IN ('initialization', 'establishment')
          AND NOT EXISTS (
              SELECT 1
              FROM public.reward_threshold_pending_promotions AS earlier
              WHERE earlier.user_id = promotion.user_id
                AND earlier.status = 'sealed'
                AND earlier.promotion_kind IN (
                    'initialization', 'establishment'
                )
                AND (
                    earlier.effective_at < promotion.effective_at
                    OR (
                        earlier.effective_at = promotion.effective_at
                        AND earlier.id < promotion.id
                    )
                )
          )
    ) THEN
        RAISE EXCEPTION
            'Threshold release requires the first sealed establishment authority';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_authority.user_id::TEXT, 2982)
    );

    INSERT INTO public.reward_threshold_release_batches (
        user_id, established_authority_id, established_at,
        reward_ftp_w, reward_ftp_source, reward_ftp_policy_version, created_at
    ) VALUES (
        v_authority.user_id, v_authority.id, v_authority.effective_at,
        v_authority.ftp_w, v_authority.source,
        'reward_ftp_policy_2026_08_24_threshold_v1', p_created_at
    )
    ON CONFLICT (established_authority_id) DO NOTHING;

    SELECT * INTO v_batch
    FROM public.reward_threshold_release_batches
    WHERE established_authority_id = v_authority.id;
    IF NOT FOUND
       OR v_batch.user_id IS DISTINCT FROM v_authority.user_id
       OR v_batch.established_at IS DISTINCT FROM v_authority.effective_at
       OR v_batch.reward_ftp_w IS DISTINCT FROM v_authority.ftp_w
       OR v_batch.reward_ftp_source IS DISTINCT FROM v_authority.source THEN
        RAISE EXCEPTION 'Threshold release batch conflicts with sealed authority';
    END IF;

    INSERT INTO public.reward_threshold_release_batch_items (
        batch_id, hold_id, disposition, eligibility_cutoff_at,
        established_at, created_at
    )
    SELECT
        v_batch.id,
        hold.id,
        CASE
            WHEN v_batch.established_at - admission.admitted_at > INTERVAL '16 weeks'
                THEN 'lapsed'
            ELSE 'eligible'
        END,
        v_batch.established_at - INTERVAL '16 weeks',
        v_batch.established_at,
        p_created_at
    FROM public.reward_threshold_provisional_holds AS hold
    JOIN public.reward_threshold_provisional_hold_admissions AS admission
      ON admission.hold_id = hold.id
     AND admission.ride_id = hold.ride_id
    WHERE hold.user_id = v_batch.user_id
      AND NOT EXISTS (
          SELECT 1
          FROM public.reward_threshold_release_batch_items AS existing
          WHERE existing.hold_id = hold.id
      )
    ORDER BY admission.admitted_at, hold.id
    ON CONFLICT (hold_id) DO NOTHING;

    RETURN v_batch.id;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_reward_threshold_provisional_hold_admission(
    p_ride_id UUID,
    p_admitted_at TIMESTAMPTZ,
    p_ride_attestation_pda TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_hold public.reward_threshold_provisional_holds%ROWTYPE;
    v_plan public.ride_economic_plans%ROWTYPE;
    v_admission public.reward_threshold_provisional_hold_admissions%ROWTYPE;
    v_authority_id UUID;
    v_batch_id UUID;
BEGIN
    IF p_ride_id IS NULL
       OR p_admitted_at IS NULL
       OR pg_catalog.btrim(COALESCE(p_ride_attestation_pda, '')) = '' THEN
        RAISE EXCEPTION 'Threshold hold chain admission is incomplete';
    END IF;

    SELECT * INTO v_hold
    FROM public.reward_threshold_provisional_holds
    WHERE ride_id = p_ride_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold hold chain admission lacks frozen hold evidence';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_hold.user_id::TEXT, 2982)
    );
    SELECT * INTO v_plan
    FROM public.ride_economic_plans
    WHERE ride_id = p_ride_id
      AND state IN (
          'attestation_confirmed', 'completions_confirmed', 'cal_confirmed',
          'projections_reconciled', 'complete'
      )
      AND reward_policy = 'threshold_provisional_hold_v1'
      AND total_tss = 0
      AND exact_cal_base_units = 0
      AND expected_attestation_pda = p_ride_attestation_pda
      AND attestation_confirmed_at = p_admitted_at
      AND plan_evidence_hash = v_hold.admission_plan_evidence_hash
      AND NOT EXISTS (
          SELECT 1
          FROM public.ride_economic_completion_steps AS step
          WHERE step.ride_id = p_ride_id
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold hold admission conflicts with finalized parent attestation';
    END IF;
    IF p_admitted_at < v_hold.ride_started_at THEN
        RAISE EXCEPTION 'Threshold hold admission precedes the original ride';
    END IF;

    INSERT INTO public.reward_threshold_provisional_hold_admissions (
        hold_id, ride_id, admitted_at, ride_attestation_pda
    ) VALUES (
        v_hold.id, v_hold.ride_id, p_admitted_at, p_ride_attestation_pda
    )
    ON CONFLICT (hold_id) DO NOTHING;

    SELECT * INTO v_admission
    FROM public.reward_threshold_provisional_hold_admissions
    WHERE hold_id = v_hold.id;
    IF NOT FOUND
       OR v_admission.ride_id IS DISTINCT FROM v_hold.ride_id
       OR v_admission.admitted_at IS DISTINCT FROM p_admitted_at
       OR v_admission.ride_attestation_pda IS DISTINCT FROM
            p_ride_attestation_pda THEN
        RAISE EXCEPTION 'Threshold hold admission replay conflicts with chain authority';
    END IF;

    -- A checkpoint may be retried after later raises have advanced the
    -- ratchet's current authority. Prefer the immutable first release batch;
    -- if it has not yet been materialized, recover the earliest sealed
    -- initialization/establishment promotion. This also handles ratchets that
    -- began on a legacy verified authority, whose established_at predates the
    -- release-capable derived initialization copy.
    SELECT batch.established_authority_id INTO v_authority_id
    FROM public.reward_threshold_release_batches AS batch
    WHERE batch.user_id = v_hold.user_id
    ORDER BY batch.established_at, batch.id
    LIMIT 1;
    IF NOT FOUND THEN
        SELECT pending.sealed_authority_id INTO v_authority_id
        FROM public.reward_threshold_pending_promotions AS pending
        JOIN public.reward_ftp_authorities AS authority
          ON authority.id = pending.sealed_authority_id
         AND authority.user_id = pending.user_id
        WHERE pending.user_id = v_hold.user_id
          AND pending.status = 'sealed'
          AND pending.promotion_kind IN ('initialization', 'establishment')
          AND authority.source = 'derived_eftp'
          AND authority.verified_by = 'derived-threshold-v1'
          AND authority.evidence->>'policy_version' =
                'reward_ftp_policy_2026_08_24_threshold_v1'
        ORDER BY pending.effective_at, pending.id
        LIMIT 1;
    END IF;
    IF FOUND THEN
        v_batch_id := public.create_reward_threshold_release_batch(
            v_authority_id, p_admitted_at
        );
    END IF;

    RETURN pg_catalog.jsonb_build_object(
        'hold_id', v_hold.id,
        'ride_id', v_hold.ride_id,
        'admitted_at', v_admission.admitted_at,
        'ride_attestation_pda', v_admission.ride_attestation_pda,
        'batch_id', v_batch_id,
        'batch_item_id', (
            SELECT item.id
            FROM public.reward_threshold_release_batch_items AS item
            WHERE item.hold_id = v_hold.id
        ),
        'disposition', (
            SELECT item.disposition
            FROM public.reward_threshold_release_batch_items AS item
            WHERE item.hold_id = v_hold.id
        )
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.register_reward_threshold_provisional_hold(
    p_hold JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride_id UUID;
    v_user_id UUID;
    v_held_at TIMESTAMPTZ;
    v_started_at TIMESTAMPTZ;
    v_admission_hash BYTEA;
    v_hold_evidence JSONB;
    v_hold_hash BYTEA;
    v_hold public.reward_threshold_provisional_holds%ROWTYPE;
BEGIN
    IF p_hold IS NULL OR pg_catalog.jsonb_typeof(p_hold) <> 'object' THEN
        RAISE EXCEPTION 'Threshold hold must be a JSON object';
    END IF;
    v_ride_id := (p_hold->>'ride_id')::UUID;
    v_user_id := (p_hold->>'user_id')::UUID;
    v_held_at := (p_hold->>'held_at')::TIMESTAMPTZ;
    v_started_at := (p_hold->>'ride_started_at')::TIMESTAMPTZ;
    v_admission_hash := pg_catalog.decode(
        p_hold->>'admission_plan_evidence_hash_hex', 'hex'
    );
    v_hold_evidence := p_hold->'hold_evidence';
    IF pg_catalog.octet_length(v_admission_hash) <> 32
       OR pg_catalog.jsonb_typeof(v_hold_evidence) <> 'object' THEN
        RAISE EXCEPTION 'invalid Threshold hold evidence';
    END IF;
    v_hold_hash := pg_catalog.sha256(
        pg_catalog.convert_to(v_hold_evidence::TEXT, 'UTF8')
    );

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_user_id::TEXT, 2982)
    );
    IF NOT EXISTS (
        SELECT 1
        FROM public.rides AS ride
        JOIN public.ride_economic_plans AS plan ON plan.ride_id = ride.id
        WHERE ride.id = v_ride_id
          AND ride.user_id = v_user_id
          AND ride.reward_ftp_w = 200
          AND ride.reward_ftp_source = 'network_default'
          AND ride.reward_ftp_authority_id IS NULL
          AND ride.reward_ftp_activity_started_at = v_started_at
          AND plan.user_id = v_user_id
          AND plan.reward_policy = 'threshold_provisional_hold_v1'
          AND plan.total_tss = 0
          AND plan.exact_cal_base_units = 0
          AND plan.plan_evidence_hash = v_admission_hash
          AND NOT EXISTS (
              SELECT 1
              FROM public.ride_economic_completion_steps AS step
              WHERE step.ride_id = plan.ride_id
          )
    ) THEN
        RAISE EXCEPTION 'Threshold hold lacks its immutable zero-CAL admission plan';
    END IF;

    INSERT INTO public.reward_threshold_provisional_holds (
        ride_id, user_id, held_at, ride_started_at,
        admission_plan_evidence_hash, hold_evidence, hold_evidence_hash
    ) VALUES (
        v_ride_id, v_user_id, v_held_at, v_started_at,
        v_admission_hash, v_hold_evidence, v_hold_hash
    )
    ON CONFLICT (ride_id) DO NOTHING;

    SELECT * INTO v_hold
    FROM public.reward_threshold_provisional_holds
    WHERE ride_id = v_ride_id;
    IF NOT FOUND
       OR v_hold.user_id IS DISTINCT FROM v_user_id
       OR v_hold.held_at IS DISTINCT FROM v_held_at
       OR v_hold.ride_started_at IS DISTINCT FROM v_started_at
       OR v_hold.admission_plan_evidence_hash IS DISTINCT FROM v_admission_hash
       OR v_hold.hold_evidence IS DISTINCT FROM v_hold_evidence
       OR v_hold.hold_evidence_hash IS DISTINCT FROM v_hold_hash THEN
        RAISE EXCEPTION 'Threshold hold replay conflicts with immutable authority';
    END IF;

    RETURN pg_catalog.jsonb_build_object(
        'hold_id', v_hold.id,
        'ride_id', v_hold.ride_id,
        'user_id', v_hold.user_id,
        'held_at', v_hold.held_at,
        'admitted_at', NULL
    );
END;
$$;

-- The zero parent and its provisional evidence are one admission boundary.
-- Any validation or insert failure in the hold path rolls back the underlying
-- two-argument plan freeze in the same RPC transaction.
DO $$
BEGIN
    IF pg_catalog.to_regprocedure(
        'public.freeze_ride_economic_plan_without_threshold_hold_atomicity(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_without_threshold_hold_atomicity;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_without_threshold_hold_atomicity(
        JSONB, JSONB
    ) FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.freeze_ride_economic_plan(
    p_plan JSONB,
    p_steps JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF p_plan->>'reward_policy' = 'threshold_provisional_hold_v1' THEN
        RAISE EXCEPTION
            'Threshold hold policy requires atomic hold evidence';
    END IF;
    RETURN public.freeze_ride_economic_plan_without_threshold_hold_atomicity(
        p_plan, p_steps
    );
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
    TO service_role;

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

    v_plan :=
        public.freeze_ride_economic_plan_without_threshold_hold_atomicity(
            p_plan, p_steps
        );

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

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB)
    TO service_role;

CREATE OR REPLACE FUNCTION public.bind_reward_threshold_release_batch_on_seal()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF OLD.status = 'pending'
       AND NEW.status = 'sealed'
       AND NEW.promotion_kind IN ('initialization', 'establishment')
       AND NOT EXISTS (
           SELECT 1
           FROM public.reward_threshold_pending_promotions AS earlier
           WHERE earlier.user_id = NEW.user_id
             AND earlier.status = 'sealed'
             AND earlier.promotion_kind IN ('initialization', 'establishment')
             AND earlier.id <> NEW.id
             AND (
                 earlier.effective_at < NEW.effective_at
                 OR (
                     earlier.effective_at = NEW.effective_at
                     AND earlier.id < NEW.id
                 )
             )
       ) THEN
        PERFORM public.create_reward_threshold_release_batch(
            NEW.sealed_authority_id, NEW.sealed_at
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reward_threshold_release_batch_on_seal
    AFTER UPDATE OF status, sealed_authority_id, sealed_at
    ON public.reward_threshold_pending_promotions
    FOR EACH ROW
    EXECUTE FUNCTION public.bind_reward_threshold_release_batch_on_seal();

CREATE OR REPLACE FUNCTION public.claim_due_reward_threshold_release_item(
    p_lease_owner UUID,
    p_lease_seconds INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := pg_catalog.clock_timestamp();
    v_item_id UUID;
    v_claimed_item_id UUID;
    v_result JSONB;
BEGIN
    IF p_lease_owner IS NULL OR p_lease_seconds NOT BETWEEN 1 AND 300 THEN
        RAISE EXCEPTION 'Threshold release planner lease must be 1 to 300 seconds';
    END IF;

    SELECT item.id INTO v_item_id
    FROM public.reward_threshold_release_batch_items AS item
    JOIN public.reward_threshold_provisional_holds AS hold
      ON hold.id = item.hold_id
    JOIN public.reward_threshold_provisional_hold_admissions AS admission
      ON admission.hold_id = hold.id
     AND admission.ride_id = hold.ride_id
    JOIN public.ride_economic_plans AS plan
      ON plan.ride_id = hold.ride_id
    LEFT JOIN public.reward_threshold_release_snapshots AS snapshot
      ON snapshot.batch_item_id = item.id
    LEFT JOIN public.reward_threshold_release_item_claims AS claim
      ON claim.batch_item_id = item.id
    WHERE item.disposition = 'eligible'
      AND snapshot.id IS NULL
      AND plan.state = 'complete'
      AND plan.terminal_projected_at IS NOT NULL
      AND plan.terminal_projected_at IS NOT NULL
      AND plan.reward_policy = 'threshold_provisional_hold_v1'
      AND plan.total_tss = 0
      AND plan.exact_cal_base_units = 0
      AND plan.plan_evidence_hash = hold.admission_plan_evidence_hash
      AND NOT EXISTS (
          SELECT 1
          FROM public.ride_economic_completion_steps AS step
          WHERE step.ride_id = plan.ride_id
      )
      AND (
          claim.batch_item_id IS NULL
          OR (
              claim.consumed_snapshot_id IS NULL
              AND claim.terminal_disposition IS NULL
              AND claim.lease_expires_at <= v_now
          )
      )
    ORDER BY item.established_at, admission.admitted_at, item.id
    FOR UPDATE OF item SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    INSERT INTO public.reward_threshold_release_item_claims AS claim (
        batch_item_id, lease_owner, lease_expires_at
    ) VALUES (
        v_item_id, p_lease_owner,
        v_now + pg_catalog.make_interval(secs => p_lease_seconds)
    )
    ON CONFLICT (batch_item_id) DO UPDATE SET
        lease_owner = EXCLUDED.lease_owner,
        lease_expires_at = EXCLUDED.lease_expires_at,
        attempts = claim.attempts + 1,
        updated_at = v_now
    WHERE claim.consumed_snapshot_id IS NULL
      AND claim.terminal_disposition IS NULL
      AND claim.lease_expires_at <= v_now
    RETURNING batch_item_id INTO v_claimed_item_id;
    IF v_claimed_item_id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT pg_catalog.jsonb_build_object(
        'batch_item_id', item.id,
        'batch_id', batch.id,
        'hold_id', hold.id,
        'ride_id', hold.ride_id,
        'user_id', hold.user_id,
        'admitted_at', admission.admitted_at,
        'ride_started_at', hold.ride_started_at,
        'admission_plan_evidence_hash_hex',
            pg_catalog.encode(hold.admission_plan_evidence_hash, 'hex'),
        'hold_evidence', hold.hold_evidence,
        'hold_evidence_hash_hex',
            pg_catalog.encode(hold.hold_evidence_hash, 'hex'),
        'wallet', plan.wallet,
        'ride_hash_hex', pg_catalog.encode(plan.ride_hash, 'hex'),
        'expected_attestation_pda', plan.expected_attestation_pda,
        'established_at', batch.established_at,
        'reward_ftp_authority_id', batch.established_authority_id,
        'reward_ftp_authority_evidence_hash_hex',
            pg_catalog.encode(authority.evidence_hash, 'hex'),
        'reward_ftp_w', batch.reward_ftp_w,
        'reward_ftp_source', batch.reward_ftp_source,
        'reward_ftp_policy_version', batch.reward_ftp_policy_version,
        'planner_lease_owner', p_lease_owner,
        'planner_lease_expires_at', claim.lease_expires_at
    ) INTO v_result
    FROM public.reward_threshold_release_batch_items AS item
    JOIN public.reward_threshold_release_batches AS batch
      ON batch.id = item.batch_id
    JOIN public.reward_threshold_provisional_holds AS hold
      ON hold.id = item.hold_id
    JOIN public.reward_threshold_provisional_hold_admissions AS admission
      ON admission.hold_id = hold.id
     AND admission.ride_id = hold.ride_id
    JOIN public.reward_ftp_authorities AS authority
      ON authority.id = batch.established_authority_id
    JOIN public.ride_economic_plans AS plan
      ON plan.ride_id = hold.ride_id
    JOIN public.reward_threshold_release_item_claims AS claim
      ON claim.batch_item_id = item.id
    WHERE item.id = v_item_id;
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_reward_threshold_release_item_terminal(
    p_batch_item_id UUID,
    p_lease_owner UUID,
    p_disposition TEXT,
    p_reason TEXT,
    p_evidence JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_claim public.reward_threshold_release_item_claims%ROWTYPE;
BEGIN
    IF p_disposition NOT IN ('review', 'not_counted')
       OR pg_catalog.btrim(COALESCE(p_reason, '')) = ''
       OR pg_catalog.jsonb_typeof(p_evidence) <> 'object' THEN
        RAISE EXCEPTION 'Threshold release terminal planner evidence is incomplete';
    END IF;
    UPDATE public.reward_threshold_release_item_claims
    SET terminal_disposition = p_disposition,
        terminal_reason = pg_catalog.left(p_reason, 2000),
        terminal_evidence = p_evidence,
        terminal_at = pg_catalog.clock_timestamp(),
        lease_expires_at = pg_catalog.clock_timestamp(),
        updated_at = pg_catalog.clock_timestamp()
    WHERE batch_item_id = p_batch_item_id
      AND lease_owner = p_lease_owner
      AND lease_expires_at > pg_catalog.clock_timestamp()
      AND consumed_snapshot_id IS NULL
      AND terminal_disposition IS NULL
      AND NOT EXISTS (
          SELECT 1
          FROM public.reward_threshold_release_snapshots AS snapshot
          WHERE snapshot.batch_item_id = p_batch_item_id
      )
    RETURNING * INTO v_claim;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN pg_catalog.jsonb_build_object(
        'batch_item_id', v_claim.batch_item_id,
        'disposition', v_claim.terminal_disposition,
        'reason', v_claim.terminal_reason,
        'evidence', v_claim.terminal_evidence,
        'terminal_at', v_claim.terminal_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.repair_reward_threshold_release_item_review(
    p_batch_item_id UUID,
    p_reason TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_claim public.reward_threshold_release_item_claims%ROWTYPE;
BEGIN
    IF pg_catalog.btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'Threshold release item repair reason is required';
    END IF;
    UPDATE public.reward_threshold_release_item_claims
    SET terminal_disposition = NULL,
        terminal_reason = NULL,
        terminal_evidence = NULL,
        terminal_at = NULL,
        repair_reason = pg_catalog.left(p_reason, 2000),
        repaired_at = pg_catalog.clock_timestamp(),
        lease_expires_at = pg_catalog.clock_timestamp(),
        updated_at = pg_catalog.clock_timestamp()
    WHERE batch_item_id = p_batch_item_id
      AND consumed_snapshot_id IS NULL
      AND terminal_disposition = 'review'
      AND NOT EXISTS (
          SELECT 1
          FROM public.reward_threshold_release_snapshots AS snapshot
          WHERE snapshot.batch_item_id = p_batch_item_id
      )
    RETURNING * INTO v_claim;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN pg_catalog.jsonb_build_object(
        'batch_item_id', v_claim.batch_item_id,
        'status', 'planning',
        'repair_reason', v_claim.repair_reason,
        'repaired_at', v_claim.repaired_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.get_reward_threshold_release_execution(
    p_snapshot_id UUID
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
        'snapshot_id', snapshot.id,
        'batch_item_id', snapshot.batch_item_id,
        'ride_id', snapshot.ride_id,
        'user_id', snapshot.user_id,
        'state', execution.state,
        'wallet', execution.wallet,
        'ride_hash_hex', pg_catalog.encode(execution.ride_hash, 'hex'),
        'admitted_at', admission.admitted_at,
        'established_at', batch.established_at,
        'reward_ftp_authority_id', snapshot.reward_ftp_authority_id,
        'reward_ftp_authority_evidence_hash_hex',
            pg_catalog.encode(authority.evidence_hash, 'hex'),
        'reward_ftp_w', snapshot.reward_ftp_w,
        'reward_ftp_source', snapshot.reward_ftp_source,
        'reward_ftp_policy_version', snapshot.reward_ftp_policy_version,
        'economic_tss', snapshot.economic_tss,
        'total_tss', pg_catalog.trunc(snapshot.economic_tss),
        'exact_cal_base_units', snapshot.exact_cal_base_units,
        'exact_tribute_budget_base_units',
            snapshot.exact_tribute_budget_base_units,
        'snapshot_evidence', snapshot.snapshot_evidence,
        'snapshot_evidence_hash_hex',
            pg_catalog.encode(snapshot.snapshot_evidence_hash, 'hex'),
        'release_plan_evidence_hash_hex',
            pg_catalog.encode(execution.release_plan_evidence_hash, 'hex'),
        'expected_attestation_pda', plan.expected_attestation_pda,
        'expected_release_authority_pda',
            execution.expected_release_authority_pda,
        'expected_cal_receipt_pda', execution.expected_cal_receipt_pda,
        'release_authority_actual_tx_signature',
            execution.release_authority_actual_tx_signature,
        'release_authority_confirmed_at',
            execution.release_authority_confirmed_at,
        'cal_actual_tx_signature', execution.cal_actual_tx_signature,
        'cal_confirmed_at', execution.cal_confirmed_at,
        'release_settlement_week', indexed_release.release_settlement_week,
        'attempts', execution.attempts,
        'lease_owner', execution.lease_owner,
        'lease_expires_at', execution.lease_expires_at,
        'next_attempt_at', execution.next_attempt_at,
        'last_error', execution.last_error,
        'review_reason', execution.review_reason,
        'review_evidence', execution.review_evidence,
        'terminal_projected_at', execution.terminal_projected_at,
        'lock_version', execution.lock_version,
        'steps', COALESCE((
            SELECT pg_catalog.jsonb_agg(
                pg_catalog.jsonb_build_object(
                    'step_index', step.step_index,
                    'pattern_id', step.pattern_id,
                    'vault_id', step.vault_id,
                    'vault_signature', step.vault_signature,
                    'completion_time_s', step.completion_time_s,
                    'completed_at', step.completed_at,
                    'exact_tribute_base_units',
                        step.exact_tribute_base_units,
                    'completion_evidence_version',
                        step.completion_evidence_version,
                    'completion_evidence_hash_hex',
                        pg_catalog.encode(step.completion_evidence_hash, 'hex'),
                    'expected_receipt_pda', step.expected_receipt_pda,
                    'state', step.state,
                    'actual_tx_signature', step.actual_tx_signature,
                    'chain_confirmed_at', step.chain_confirmed_at,
                    'projected_at', step.projected_at,
                    'attempts', step.attempts,
                    'last_error', step.last_error
                ) ORDER BY step.step_index
            )
            FROM public.reward_threshold_release_steps AS step
            WHERE step.snapshot_id = snapshot.id
        ), '[]'::JSONB)
    ) INTO v_result
    FROM public.reward_threshold_release_snapshots AS snapshot
    JOIN public.reward_threshold_release_batch_items AS item
      ON item.id = snapshot.batch_item_id
    JOIN public.reward_threshold_release_batches AS batch
      ON batch.id = item.batch_id
    JOIN public.reward_threshold_provisional_holds AS hold
      ON hold.id = item.hold_id
    JOIN public.reward_threshold_provisional_hold_admissions AS admission
      ON admission.hold_id = hold.id
     AND admission.ride_id = hold.ride_id
    JOIN public.reward_ftp_authorities AS authority
      ON authority.id = snapshot.reward_ftp_authority_id
    JOIN public.reward_threshold_release_executions AS execution
      ON execution.snapshot_id = snapshot.id
    JOIN public.ride_economic_plans AS plan
      ON plan.ride_id = snapshot.ride_id
    LEFT JOIN public.indexed_held_ride_release_authorities AS indexed_release
      ON indexed_release.pda = execution.expected_release_authority_pda
    WHERE snapshot.id = p_snapshot_id;
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION
public.validate_exact_indexed_reward_threshold_release_authority(
    p_snapshot_id UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_snapshot public.reward_threshold_release_snapshots%ROWTYPE;
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_plan public.ride_economic_plans%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_indexed_release public.indexed_held_ride_release_authorities%ROWTYPE;
    v_cal_receipt public.indexed_cal_mint_receipts%ROWTYPE;
BEGIN
    SELECT * INTO v_snapshot
    FROM public.reward_threshold_release_snapshots
    WHERE id = p_snapshot_id;
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = p_snapshot_id;
    SELECT * INTO v_plan
    FROM public.ride_economic_plans
    WHERE ride_id = v_snapshot.ride_id;
    SELECT * INTO v_authority
    FROM public.reward_ftp_authorities
    WHERE id = v_snapshot.reward_ftp_authority_id;
    IF v_snapshot.id IS NULL
       OR v_execution.snapshot_id IS NULL
       OR v_plan.ride_id IS NULL
       OR v_authority.id IS NULL THEN
        RAISE EXCEPTION 'Threshold release frozen authority is incomplete';
    END IF;

    SELECT * INTO v_indexed_release
    FROM public.indexed_held_ride_release_authorities
    WHERE pda = v_execution.expected_release_authority_pda;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_execution.wallet IS DISTINCT FROM v_plan.wallet
       OR v_snapshot.user_id IS DISTINCT FROM v_plan.user_id
       OR v_indexed_release.ride_attestation_pda IS DISTINCT FROM
            v_plan.expected_attestation_pda
       OR v_indexed_release.rider_pubkey IS DISTINCT FROM v_execution.wallet
       OR v_indexed_release.threshold_authority_id_hex IS DISTINCT FROM
            pg_catalog.encode(pg_catalog.uuid_send(v_authority.id), 'hex')
       OR v_indexed_release.threshold_authority_commitment_hex IS DISTINCT FROM
            pg_catalog.encode(v_authority.evidence_hash, 'hex')
       OR v_indexed_release.threshold_effective_at IS DISTINCT FROM
            EXTRACT(epoch FROM v_authority.effective_at)::BIGINT
       OR v_indexed_release.threshold_w IS DISTINCT FROM v_snapshot.reward_ftp_w
       OR v_indexed_release.threshold_policy_version IS DISTINCT FROM 1
       OR v_indexed_release.economic_tss IS DISTINCT FROM
            pg_catalog.trunc(v_snapshot.economic_tss)
       OR v_indexed_release.cal_earned IS DISTINCT FROM
            v_snapshot.exact_cal_base_units
       OR v_indexed_release.cal_tribute_budget IS DISTINCT FROM
            v_snapshot.exact_tribute_budget_base_units
       OR v_indexed_release.release_plan_hash_hex IS DISTINCT FROM
            pg_catalog.encode(v_execution.release_plan_evidence_hash, 'hex') THEN
        RAISE EXCEPTION 'indexed Threshold release authority conflicts with frozen snapshot'
            USING ERRCODE = 'BRR01';
    END IF;

    SELECT * INTO v_cal_receipt
    FROM public.indexed_cal_mint_receipts
    WHERE pda = v_execution.expected_cal_receipt_pda;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_cal_receipt.ride_attestation_pda IS DISTINCT FROM
            v_plan.expected_attestation_pda
       OR v_cal_receipt.rider_pubkey IS DISTINCT FROM v_execution.wallet
       OR v_cal_receipt.release_authority_pda IS DISTINCT FROM
            v_indexed_release.pda
       OR v_cal_receipt.amount IS DISTINCT FROM
            v_snapshot.exact_cal_base_units
       OR v_cal_receipt.release_settlement_week IS DISTINCT FROM
            v_indexed_release.release_settlement_week THEN
        RAISE EXCEPTION 'indexed Threshold release CAL receipt conflicts with frozen snapshot'
            USING ERRCODE = 'BRR02';
    END IF;
    RETURN TRUE;
END;
$$;
REVOKE ALL ON FUNCTION
    public.validate_exact_indexed_reward_threshold_release_authority(UUID)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.claim_due_reward_threshold_release_execution(
    p_lease_owner UUID,
    p_lease_seconds INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_snapshot_id UUID;
    v_now TIMESTAMPTZ := pg_catalog.clock_timestamp();
BEGIN
    IF p_lease_owner IS NULL OR p_lease_seconds NOT BETWEEN 1 AND 300 THEN
        RAISE EXCEPTION 'Threshold release execution lease must be 1 to 300 seconds';
    END IF;
    SELECT execution.snapshot_id INTO v_snapshot_id
    FROM public.reward_threshold_release_executions AS execution
    JOIN public.reward_threshold_release_snapshots AS snapshot
      ON snapshot.id = execution.snapshot_id
    JOIN public.ride_economic_plans AS plan
      ON plan.ride_id = snapshot.ride_id
    WHERE execution.state <> 'review'
      AND (
          execution.state <> 'complete'
          OR execution.terminal_projected_at IS NULL
      )
      AND execution.next_attempt_at <= v_now
      AND (
          execution.lease_owner IS NULL
          OR execution.lease_expires_at <= v_now
      )
      AND plan.state = 'complete'
      AND plan.reward_policy = 'threshold_provisional_hold_v1'
      AND plan.total_tss = 0
      AND plan.exact_cal_base_units = 0
      AND NOT EXISTS (
          SELECT 1
          FROM public.ride_economic_completion_steps AS normal_step
          WHERE normal_step.ride_id = plan.ride_id
      )
    ORDER BY execution.next_attempt_at, execution.created_at,
             execution.snapshot_id
    FOR UPDATE OF execution SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    UPDATE public.reward_threshold_release_executions
    SET lease_owner = p_lease_owner,
        lease_expires_at = v_now
            + pg_catalog.make_interval(secs => p_lease_seconds),
        attempts = attempts + 1,
        lock_version = lock_version + 1,
        updated_at = v_now
    WHERE snapshot_id = v_snapshot_id;
    RETURN public.get_reward_threshold_release_execution(v_snapshot_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.advance_reward_threshold_release_execution(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_expected_state TEXT,
    p_next_state TEXT,
    p_fields JSONB DEFAULT '{}'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_now TIMESTAMPTZ := pg_catalog.clock_timestamp();
BEGIN
    IF pg_catalog.jsonb_typeof(p_fields) <> 'object' THEN
        RAISE EXCEPTION 'Threshold release transition fields must be an object';
    END IF;
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = p_snapshot_id
      AND state = p_expected_state
      AND lease_owner = p_lease_owner
      AND lease_expires_at > v_now
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF NOT (
        (p_expected_state = 'planned'
            AND p_next_state = 'release_authority_confirmed')
        OR (p_expected_state = 'release_authority_confirmed'
            AND p_next_state = 'cal_confirmed')
        OR (p_expected_state = 'cal_confirmed'
            AND p_next_state = 'completions_confirmed')
        OR (p_expected_state = 'completions_confirmed'
            AND p_next_state = 'projections_reconciled')
        OR (p_expected_state = 'projections_reconciled'
            AND p_next_state = 'complete')
    ) THEN
        RAISE EXCEPTION 'invalid Threshold release state transition: % -> %',
            p_expected_state, p_next_state;
    END IF;

    IF p_next_state = 'release_authority_confirmed'
       AND (
           COALESCE(
               p_fields->>'release_authority_actual_tx_signature',
               p_fields->>'release_authority_tx_signature',
               ''
           ) LIKE 'exists:%'
           OR (
               COALESCE(
                   p_fields->>'release_authority_actual_tx_signature',
                   p_fields->>'release_authority_tx_signature'
               ) IS NOT NULL
               AND pg_catalog.btrim(COALESCE(
                   p_fields->>'release_authority_actual_tx_signature',
                   p_fields->>'release_authority_tx_signature'
               )) = ''
           )
           OR (p_fields->>'release_authority_confirmed_at')::TIMESTAMPTZ
                IS NULL
       ) THEN
        RAISE EXCEPTION 'Threshold release authority confirmation is incomplete';
    END IF;
    IF p_next_state = 'completions_confirmed' AND EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_steps AS step
        WHERE step.snapshot_id = p_snapshot_id
          AND step.state NOT IN ('confirmed', 'projected')
    ) THEN
        RAISE EXCEPTION 'Threshold release completion receipts are not all confirmed';
    END IF;
    IF p_next_state = 'cal_confirmed'
       AND (
           COALESCE(
               p_fields->>'cal_actual_tx_signature',
               p_fields->>'cal_tx_signature',
               ''
           ) LIKE 'exists:%'
           OR (
               COALESCE(
                   p_fields->>'cal_actual_tx_signature',
                   p_fields->>'cal_tx_signature'
               ) IS NOT NULL
               AND pg_catalog.btrim(COALESCE(
                   p_fields->>'cal_actual_tx_signature',
                   p_fields->>'cal_tx_signature'
               )) = ''
           )
           OR (p_fields->>'cal_confirmed_at')::TIMESTAMPTZ IS NULL
       ) THEN
        RAISE EXCEPTION 'Threshold release CAL confirmation is incomplete';
    END IF;
    IF p_next_state = 'projections_reconciled' AND EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_steps AS step
        WHERE step.snapshot_id = p_snapshot_id
          AND step.state <> 'projected'
    ) THEN
        RAISE EXCEPTION 'Threshold release completion projections are incomplete';
    END IF;
    IF p_next_state = 'complete' AND NOT EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_snapshots AS snapshot
        JOIN public.ride_economic_plans AS plan
          ON plan.ride_id = snapshot.ride_id
        WHERE snapshot.id = p_snapshot_id
          AND plan.state = 'complete'
          AND plan.reward_policy = 'threshold_provisional_hold_v1'
          AND plan.total_tss = 0
          AND plan.exact_cal_base_units = 0
    ) THEN
        RAISE EXCEPTION 'Threshold release zero parent plan is not complete';
    END IF;
    IF p_next_state = 'complete'
       AND NOT public.validate_exact_indexed_reward_threshold_release_authority(
            p_snapshot_id
       ) THEN
        RAISE EXCEPTION 'Threshold release exact indexed authority is incomplete';
    END IF;

    UPDATE public.reward_threshold_release_executions
    SET state = p_next_state,
        release_authority_actual_tx_signature = CASE
            WHEN p_next_state = 'release_authority_confirmed'
                THEN COALESCE(
                    p_fields->>'release_authority_actual_tx_signature',
                    p_fields->>'release_authority_tx_signature'
                )
            ELSE release_authority_actual_tx_signature
        END,
        release_authority_confirmed_at = CASE
            WHEN p_next_state = 'release_authority_confirmed'
                THEN (p_fields->>'release_authority_confirmed_at')::TIMESTAMPTZ
            ELSE release_authority_confirmed_at
        END,
        cal_actual_tx_signature = CASE
            WHEN p_next_state = 'cal_confirmed'
                THEN COALESCE(
                    p_fields->>'cal_actual_tx_signature',
                    p_fields->>'cal_tx_signature'
                )
            ELSE cal_actual_tx_signature
        END,
        cal_confirmed_at = CASE
            WHEN p_next_state = 'cal_confirmed'
                THEN (p_fields->>'cal_confirmed_at')::TIMESTAMPTZ
            ELSE cal_confirmed_at
        END,
        last_error = NULL,
        lock_version = lock_version + 1,
        updated_at = v_now
    WHERE snapshot_id = p_snapshot_id;
    RETURN public.get_reward_threshold_release_execution(p_snapshot_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.confirm_reward_threshold_release_step(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_step_index INTEGER,
    p_expected_receipt_pda TEXT,
    p_tx_signature TEXT,
    p_confirmed_at TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_step public.reward_threshold_release_steps%ROWTYPE;
BEGIN
    IF (p_tx_signature IS NOT NULL AND pg_catalog.btrim(p_tx_signature) = '')
       OR COALESCE(p_tx_signature, '') LIKE 'exists:%'
       OR p_confirmed_at IS NULL THEN
        RAISE EXCEPTION 'Threshold release completion confirmation is incomplete';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_executions AS execution
        WHERE execution.snapshot_id = p_snapshot_id
          AND execution.state = 'cal_confirmed'
          AND execution.lease_owner = p_lease_owner
          AND execution.lease_expires_at > pg_catalog.clock_timestamp()
    ) THEN
        RETURN NULL;
    END IF;

    SELECT * INTO v_step
    FROM public.reward_threshold_release_steps
    WHERE snapshot_id = p_snapshot_id
      AND step_index = p_step_index
      AND expected_receipt_pda = p_expected_receipt_pda
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_step.state IN ('confirmed', 'projected') THEN
        IF v_step.actual_tx_signature IS DISTINCT FROM p_tx_signature
           OR v_step.chain_confirmed_at IS DISTINCT FROM p_confirmed_at THEN
            RAISE EXCEPTION 'Threshold release completion replay conflicts with receipt';
        END IF;
    ELSE
        UPDATE public.reward_threshold_release_steps
        SET state = 'confirmed',
            actual_tx_signature = p_tx_signature,
            chain_confirmed_at = p_confirmed_at,
            last_error = NULL,
            updated_at = pg_catalog.clock_timestamp()
        WHERE id = v_step.id
        RETURNING * INTO v_step;
    END IF;
    RETURN pg_catalog.jsonb_build_object(
        'snapshot_id', v_step.snapshot_id,
        'step_index', v_step.step_index,
        'state', v_step.state,
        'expected_receipt_pda', v_step.expected_receipt_pda,
        'actual_tx_signature', v_step.actual_tx_signature,
        'chain_confirmed_at', v_step.chain_confirmed_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_reward_threshold_release_review(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_reason TEXT,
    p_conflict_evidence JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF pg_catalog.btrim(COALESCE(p_reason, '')) = ''
       OR pg_catalog.jsonb_typeof(p_conflict_evidence) <> 'object' THEN
        RAISE EXCEPTION 'Threshold release review evidence is incomplete';
    END IF;
    UPDATE public.reward_threshold_release_executions
    SET state = 'review',
        review_from_state = state,
        review_reason = pg_catalog.left(p_reason, 2000),
        review_evidence = p_conflict_evidence,
        last_error = pg_catalog.left(p_reason, 2000),
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id
      AND lease_owner = p_lease_owner
      AND lease_expires_at > pg_catalog.clock_timestamp()
      AND state <> 'review'
      AND (state <> 'complete' OR terminal_projected_at IS NULL);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    UPDATE public.reward_threshold_release_steps
    SET state = CASE WHEN state = 'planned' THEN 'review' ELSE state END,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id;
    RETURN public.get_reward_threshold_release_execution(p_snapshot_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.repair_reward_threshold_release_execution(
    p_snapshot_id UUID,
    p_reason TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_resume_state TEXT;
BEGIN
    IF pg_catalog.btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'Threshold release repair reason is required';
    END IF;
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = p_snapshot_id
      AND state = 'review'
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    v_resume_state := CASE
        WHEN v_execution.review_from_state = 'complete' THEN 'complete'
        WHEN v_execution.release_authority_confirmed_at IS NULL THEN 'planned'
        WHEN v_execution.cal_confirmed_at IS NULL THEN
            'release_authority_confirmed'
        ELSE 'cal_confirmed'
    END;

    -- Confirmed/projected receipts are immutable and remain spent. Only work
    -- that never received a durable receipt is eligible to resume.
    UPDATE public.reward_threshold_release_steps
    SET state = 'planned',
        last_error = NULL,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id
      AND state = 'review'
      AND chain_confirmed_at IS NULL;

    UPDATE public.reward_threshold_release_executions
    SET state = v_resume_state,
        review_reason = NULL,
        review_evidence = NULL,
        review_from_state = NULL,
        last_error = NULL,
        next_attempt_at = pg_catalog.clock_timestamp(),
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id;

    RETURN public.get_reward_threshold_release_execution(p_snapshot_id)
        || pg_catalog.jsonb_build_object('repair_reason', p_reason);
END;
$$;

CREATE OR REPLACE FUNCTION public.checkpoint_reward_threshold_release_retry(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_error TEXT,
    p_step_index INTEGER DEFAULT NULL,
    p_retry_delay_seconds INTEGER DEFAULT 30
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    UPDATE public.reward_threshold_release_executions
    SET last_error = pg_catalog.left(p_error, 2000),
        next_attempt_at = pg_catalog.clock_timestamp()
            + pg_catalog.make_interval(
                secs => GREATEST(
                    1, LEAST(p_retry_delay_seconds, 3600)
                )
            ),
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id
      AND lease_owner = p_lease_owner
      AND state <> 'review'
      AND (state <> 'complete' OR terminal_projected_at IS NULL);
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    IF p_step_index IS NOT NULL THEN
        UPDATE public.reward_threshold_release_steps
        SET attempts = attempts + 1,
            last_error = pg_catalog.left(p_error, 2000),
            updated_at = pg_catalog.clock_timestamp()
        WHERE snapshot_id = p_snapshot_id
          AND step_index = p_step_index;
    END IF;
    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_bind_vault_completion_evidence_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_version SMALLINT;
    v_matches INTEGER;
BEGIN
    IF NEW.chain_confirmation_status = 'confirmed' THEN
        SELECT pg_catalog.count(*)::INTEGER,
               pg_catalog.min(source.completion_evidence_version)
        INTO v_matches, v_version
        FROM (
            SELECT step.completion_evidence_version
            FROM public.ride_economic_completion_steps AS step
            WHERE step.expected_receipt_pda = NEW.completion_receipt_pda
              AND step.completion_evidence_hash = NEW.completion_evidence_hash
            UNION ALL
            SELECT release_step.completion_evidence_version
            FROM public.reward_threshold_release_steps AS release_step
            WHERE release_step.expected_receipt_pda = NEW.completion_receipt_pda
              AND release_step.completion_evidence_hash =
                    NEW.completion_evidence_hash
        ) AS source;
        IF v_matches <> 1 THEN
            RAISE EXCEPTION 'confirmed completion lacks one frozen evidence authority';
        END IF;
        IF NEW.completion_evidence_version IS NOT NULL
           AND NEW.completion_evidence_version IS DISTINCT FROM v_version THEN
            RAISE EXCEPTION 'confirmed completion evidence version conflicts with frozen authority';
        END IF;
        NEW.completion_evidence_version := v_version;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_enforce_completion_flow_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'immutable completion-flow evidence cannot be deleted';
    END IF;
    IF NEW.tx_signature IS DISTINCT FROM OLD.tx_signature
       OR NEW.event_index IS DISTINCT FROM OLD.event_index
       OR NEW.release_authority_pda IS DISTINCT FROM OLD.release_authority_pda
       OR NEW.vault_id IS DISTINCT FROM OLD.vault_id
       OR NEW.ride_attestation IS DISTINCT FROM OLD.ride_attestation
       OR NEW.completion_evidence_hash IS DISTINCT FROM OLD.completion_evidence_hash
       OR NEW.completion_evidence_version IS DISTINCT FROM OLD.completion_evidence_version
       OR NEW.credited_settlement_week IS DISTINCT FROM OLD.credited_settlement_week
       OR NEW.cal_tributed IS DISTINCT FROM OLD.cal_tributed THEN
        RAISE EXCEPTION 'immutable completion-flow evidence cannot be changed';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.reconcile_confirmed_reward_threshold_release_completion(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_step_index INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_snapshot public.reward_threshold_release_snapshots%ROWTYPE;
    v_step public.reward_threshold_release_steps%ROWTYPE;
    v_plan public.ride_economic_plans%ROWTYPE;
    v_indexed_release public.indexed_held_ride_release_authorities%ROWTYPE;
    v_receipt public.indexed_climb_completion_receipts%ROWTYPE;
    v_flow public.indexed_climb_completion_flows%ROWTYPE;
    v_completion public.vault_completions%ROWTYPE;
BEGIN
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = p_snapshot_id
      AND state = 'completions_confirmed'
      AND lease_owner = p_lease_owner
      AND lease_expires_at > pg_catalog.clock_timestamp();
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_snapshot
    FROM public.reward_threshold_release_snapshots
    WHERE id = p_snapshot_id;
    SELECT * INTO v_step
    FROM public.reward_threshold_release_steps
    WHERE snapshot_id = p_snapshot_id
      AND step_index = p_step_index
      AND state IN ('confirmed', 'projected')
      AND chain_confirmed_at IS NOT NULL;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_plan
    FROM public.ride_economic_plans
    WHERE ride_id = v_snapshot.ride_id;

    IF NOT public.validate_exact_indexed_reward_threshold_release_authority(
        p_snapshot_id
    ) THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_indexed_release
    FROM public.indexed_held_ride_release_authorities
    WHERE pda = v_execution.expected_release_authority_pda;

    SELECT * INTO v_receipt
    FROM public.indexed_climb_completion_receipts
    WHERE pda = v_step.expected_receipt_pda;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_receipt.ride_attestation_pda IS DISTINCT FROM
            v_plan.expected_attestation_pda
       OR v_receipt.release_authority_pda IS DISTINCT FROM
            v_indexed_release.pda
       OR v_receipt.completion_evidence_version IS DISTINCT FROM 3
       OR v_receipt.completion_evidence_hash IS DISTINCT FROM
            v_step.completion_evidence_hash
       OR v_receipt.cal_tributed IS DISTINCT FROM
            v_step.exact_tribute_base_units
       OR v_receipt.credited_settlement_week IS DISTINCT FROM
            v_indexed_release.release_settlement_week THEN
        RAISE EXCEPTION 'indexed Threshold release completion receipt conflicts with frozen step'
            USING ERRCODE = 'BRR03';
    END IF;

    SELECT * INTO v_flow
    FROM public.indexed_climb_completion_flows
    WHERE completion_evidence_hash = v_step.completion_evidence_hash;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_flow.release_authority_pda IS DISTINCT FROM v_indexed_release.pda
       OR v_flow.vault_id IS DISTINCT FROM v_step.vault_id
       OR v_flow.ride_attestation IS DISTINCT FROM v_plan.expected_attestation_pda
       OR v_flow.completion_evidence_version IS DISTINCT FROM 3
       OR v_flow.credited_settlement_week IS DISTINCT FROM
            v_receipt.credited_settlement_week
       OR v_flow.credited_settlement_week IS DISTINCT FROM
            v_indexed_release.release_settlement_week
       OR v_flow.cal_tributed IS DISTINCT FROM v_step.exact_tribute_base_units THEN
        RAISE EXCEPTION 'indexed Threshold release Settlement Flow conflicts with frozen step'
            USING ERRCODE = 'BRR04';
    END IF;

    INSERT INTO public.vault_completions (
        vault_signature, wallet, activity_id, time_seconds, completed_at,
        validated, validation_notes, cal_tribute, best_time_seconds,
        best_time_achieved_at, total_completions, on_chain_tx,
        on_chain_tx_error, chain_confirmation_status, completion_receipt_pda,
        completion_evidence_hash, completion_evidence_version,
        chain_confirmed_at
    ) VALUES (
        v_step.vault_signature, v_execution.wallet, v_snapshot.ride_id::TEXT,
        v_step.completion_time_s, v_step.completed_at, true, NULL,
        v_step.exact_tribute_base_units, v_step.completion_time_s,
        v_step.completed_at, 1, v_step.actual_tx_signature, NULL, 'confirmed',
        v_step.expected_receipt_pda, v_step.completion_evidence_hash, 3,
        v_step.chain_confirmed_at
    )
    ON CONFLICT (vault_signature, activity_id) DO NOTHING;

    SELECT * INTO v_completion
    FROM public.vault_completions
    WHERE vault_signature = v_step.vault_signature
      AND activity_id = v_snapshot.ride_id::TEXT;
    IF NOT FOUND
       OR v_completion.wallet IS DISTINCT FROM v_execution.wallet
       OR v_completion.completed_at IS DISTINCT FROM v_step.completed_at
       OR v_completion.cal_tribute IS DISTINCT FROM
            v_step.exact_tribute_base_units
       OR v_completion.chain_confirmation_status IS DISTINCT FROM 'confirmed'
       OR v_completion.completion_receipt_pda IS DISTINCT FROM
            v_step.expected_receipt_pda
       OR v_completion.completion_evidence_hash IS DISTINCT FROM
            v_step.completion_evidence_hash
       OR v_completion.completion_evidence_version IS DISTINCT FROM 3 THEN
        RAISE EXCEPTION 'Threshold release cannot overwrite an existing completion projection'
            USING ERRCODE = 'BRR05';
    END IF;
    RETURN pg_catalog.to_jsonb(v_completion) - 'completion_evidence_hash';
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_reward_threshold_release_step_projected(
    p_snapshot_id UUID,
    p_lease_owner UUID,
    p_step_index INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_step public.reward_threshold_release_steps%ROWTYPE;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_executions AS execution
        WHERE execution.snapshot_id = p_snapshot_id
          AND execution.state = 'completions_confirmed'
          AND execution.lease_owner = p_lease_owner
          AND execution.lease_expires_at > pg_catalog.clock_timestamp()
    ) THEN
        RETURN NULL;
    END IF;
    SELECT * INTO v_step
    FROM public.reward_threshold_release_steps
    WHERE snapshot_id = p_snapshot_id
      AND step_index = p_step_index
      AND state IN ('confirmed', 'projected')
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.vault_completions AS completion
        JOIN public.indexed_climb_completion_receipts AS receipt
          ON receipt.pda = completion.completion_receipt_pda
        JOIN public.indexed_climb_completion_flows AS flow
          ON flow.completion_evidence_hash = completion.completion_evidence_hash
        WHERE completion.completion_receipt_pda = v_step.expected_receipt_pda
          AND completion.completion_evidence_hash = v_step.completion_evidence_hash
          AND completion.completion_evidence_version = 3
          AND completion.cal_tribute = v_step.exact_tribute_base_units
          AND receipt.completion_evidence_version = 3
          AND receipt.completion_evidence_hash = v_step.completion_evidence_hash
          AND receipt.cal_tributed = v_step.exact_tribute_base_units
          AND flow.completion_evidence_version = 3
          AND flow.vault_id = v_step.vault_id
          AND flow.cal_tributed = v_step.exact_tribute_base_units
          AND flow.release_authority_pda = receipt.release_authority_pda
          AND flow.credited_settlement_week = receipt.credited_settlement_week
    ) THEN
        RETURN NULL;
    END IF;
    UPDATE public.reward_threshold_release_steps
    SET state = 'projected',
        projected_at = COALESCE(projected_at, pg_catalog.clock_timestamp()),
        last_error = NULL,
        updated_at = pg_catalog.clock_timestamp()
    WHERE id = v_step.id
    RETURNING * INTO v_step;
    RETURN pg_catalog.jsonb_build_object(
        'snapshot_id', v_step.snapshot_id,
        'step_index', v_step.step_index,
        'state', v_step.state,
        'projected_at', v_step.projected_at
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.project_reward_threshold_release_terminal(
    p_snapshot_id UUID
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_snapshot public.reward_threshold_release_snapshots%ROWTYPE;
    v_product_ride_id UUID;
    v_display_cal NUMERIC;
BEGIN
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = p_snapshot_id
      AND state = 'complete'
      AND lease_owner IS NOT NULL
      AND lease_expires_at > pg_catalog.clock_timestamp()
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_execution.terminal_projected_at IS NOT NULL THEN
        RETURN public.get_reward_threshold_release_execution(p_snapshot_id);
    END IF;
    SELECT * INTO v_snapshot
    FROM public.reward_threshold_release_snapshots
    WHERE id = p_snapshot_id;
    IF EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_steps AS step
        WHERE step.snapshot_id = p_snapshot_id
          AND step.state <> 'projected'
    ) THEN
        RAISE EXCEPTION 'Threshold release terminal projection has incomplete steps';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.ride_economic_plans AS plan
        WHERE plan.ride_id = v_snapshot.ride_id
          AND plan.state = 'complete'
          AND plan.terminal_projected_at IS NOT NULL
          AND plan.reward_policy = 'threshold_provisional_hold_v1'
          AND plan.total_tss = 0
          AND plan.exact_cal_base_units = 0
    ) THEN
        RAISE EXCEPTION 'Threshold release terminal projection lacks its zero parent plan';
    END IF;
    IF NOT public.validate_exact_indexed_reward_threshold_release_authority(
        p_snapshot_id
    ) THEN
        RAISE EXCEPTION 'Threshold release terminal projection lacks exact indexed authority';
    END IF;

    v_display_cal := pg_catalog.trunc(
        v_snapshot.exact_cal_base_units / 1000000000
    );
    IF v_display_cal NOT BETWEEN 0 AND 2147483647::NUMERIC THEN
        RAISE EXCEPTION 'Threshold release display CAL exceeds ride projection range';
    END IF;
    SELECT ride.id INTO v_product_ride_id
    FROM public.rides AS ride
    WHERE ride.id = v_snapshot.ride_id
    FOR UPDATE;
    IF FOUND THEN
        UPDATE public.rides
        SET cal_earned = v_display_cal::INTEGER
        WHERE id = v_product_ride_id
          AND user_id = v_snapshot.user_id
          AND COALESCE(cal_earned, 0) = 0;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Threshold release cannot overwrite existing ride CAL'
                USING ERRCODE = 'BRR06';
        END IF;
    END IF;

    UPDATE public.reward_threshold_release_executions
    SET terminal_projected_at = pg_catalog.clock_timestamp(),
        last_error = NULL,
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id;
    RETURN public.get_reward_threshold_release_execution(p_snapshot_id);
END;
$$;

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
                    snapshot.exact_tribute_budget_base_units
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

CREATE OR REPLACE VIEW public.reward_threshold_release_ops
WITH (security_invoker = true)
AS
SELECT
    hold.ride_id,
    hold.user_id,
    hold.id AS hold_id,
    admission.admitted_at,
    item.id AS batch_item_id,
    item.disposition AS item_disposition,
    claim.attempts AS planner_attempts,
    claim.terminal_disposition,
    claim.terminal_reason,
    claim.terminal_at,
    claim.repair_reason AS planner_repair_reason,
    snapshot.id AS snapshot_id,
    execution.state AS execution_state,
    execution.attempts AS execution_attempts,
    execution.next_attempt_at,
    execution.last_error,
    execution.review_reason,
    execution.review_from_state,
    execution.terminal_projected_at,
    CASE
        WHEN execution.state = 'complete'
         AND execution.terminal_projected_at IS NOT NULL THEN 'released'
        WHEN execution.state = 'review' THEN 'under_review'
        WHEN claim.terminal_disposition = 'review' THEN 'under_review'
        WHEN claim.terminal_disposition = 'not_counted' THEN 'not_counted'
        WHEN item.disposition = 'lapsed' THEN 'lapsed'
        WHEN snapshot.id IS NOT NULL THEN 'releasing'
        WHEN item.disposition = 'eligible' THEN 'planning'
        ELSE 'held'
    END AS lifecycle_status
FROM public.reward_threshold_provisional_holds AS hold
LEFT JOIN public.reward_threshold_provisional_hold_admissions AS admission
  ON admission.hold_id = hold.id
LEFT JOIN public.reward_threshold_release_batch_items AS item
  ON item.hold_id = hold.id
LEFT JOIN public.reward_threshold_release_item_claims AS claim
  ON claim.batch_item_id = item.id
LEFT JOIN public.reward_threshold_release_snapshots AS snapshot
  ON snapshot.batch_item_id = item.id
LEFT JOIN public.reward_threshold_release_executions AS execution
  ON execution.snapshot_id = snapshot.id;

CREATE OR REPLACE FUNCTION public.enforce_indexed_release_cal_receipt_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.release_authority_pda IS NOT NULL AND (
        TG_OP = 'DELETE'
        OR NEW.pda IS DISTINCT FROM OLD.pda
        OR NEW.ride_attestation_pda IS DISTINCT FROM OLD.ride_attestation_pda
        OR NEW.release_authority_pda IS DISTINCT FROM OLD.release_authority_pda
        OR NEW.rider_pubkey IS DISTINCT FROM OLD.rider_pubkey
        OR NEW.amount IS DISTINCT FROM OLD.amount
        OR NEW.release_settlement_week IS DISTINCT FROM OLD.release_settlement_week
    ) THEN
        RAISE EXCEPTION 'indexed Threshold release CAL receipt is immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER trg_indexed_release_cal_receipt_immutable
    BEFORE UPDATE OR DELETE ON public.indexed_cal_mint_receipts
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_indexed_release_cal_receipt_immutability();

CREATE OR REPLACE FUNCTION public.enforce_indexed_release_completion_receipt_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.completion_evidence_version = 3 AND (
        TG_OP = 'DELETE'
        OR NEW.pda IS DISTINCT FROM OLD.pda
        OR NEW.ride_attestation_pda IS DISTINCT FROM OLD.ride_attestation_pda
        OR NEW.release_authority_pda IS DISTINCT FROM OLD.release_authority_pda
        OR NEW.vault_pda IS DISTINCT FROM OLD.vault_pda
        OR NEW.completion_evidence_version IS DISTINCT FROM
            OLD.completion_evidence_version
        OR NEW.completion_evidence_hash IS DISTINCT FROM
            OLD.completion_evidence_hash
        OR NEW.cal_tributed IS DISTINCT FROM OLD.cal_tributed
        OR NEW.credited_settlement_week IS DISTINCT FROM
            OLD.credited_settlement_week
    ) THEN
        RAISE EXCEPTION 'indexed Threshold release completion receipt is immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER trg_indexed_release_completion_receipt_immutable
    BEFORE UPDATE OR DELETE ON public.indexed_climb_completion_receipts
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_indexed_release_completion_receipt_immutability();

CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(
    p_activity_id TEXT
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
BEGIN
    IF p_activity_id IS NULL OR p_activity_id = '' THEN
        RETURN;
    END IF;
    WITH confirmed_completions AS (
        SELECT
            completion.completion_evidence_hash,
            completion.completion_evidence_version,
            completion.cal_tribute,
            indexed_vault.id AS vault_id
        FROM public.vault_completions AS completion
        LEFT JOIN public.indexed_vaults AS indexed_vault
          ON indexed_vault.signature_hex = completion.vault_signature
        WHERE completion.activity_id = p_activity_id
          AND completion.chain_confirmation_status = 'confirmed'
    )
    SELECT CASE
        WHEN pg_catalog.count(*) > 0
         AND pg_catalog.count(flow.credited_settlement_week) =
                pg_catalog.count(*)
         AND pg_catalog.count(*) FILTER (WHERE flow.cal_tributed > 0) > 0
         AND pg_catalog.count(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
             = pg_catalog.count(*) FILTER (WHERE flow.cal_tributed > 0)
            THEN pg_catalog.max(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
        ELSE NULL
    END
    INTO v_finalized_at
    FROM confirmed_completions AS completion
    LEFT JOIN public.indexed_climb_completion_flows AS flow
      ON flow.completion_evidence_hash = completion.completion_evidence_hash
     AND flow.vault_id = completion.vault_id
     AND flow.completion_evidence_version =
            completion.completion_evidence_version
     AND flow.completion_evidence_version IN (2, 3)
     AND flow.cal_tributed = completion.cal_tribute
    LEFT JOIN LATERAL (
        SELECT pg_catalog.min(indexed_distribution.finalized_at) AS finalized_at
        FROM public.indexed_epoch_distributions AS indexed_distribution
        WHERE indexed_distribution.vault_id = flow.vault_id
          AND indexed_distribution.epoch = flow.credited_settlement_week
          AND indexed_distribution.finalized_at IS NOT NULL
    ) AS distribution ON true;

    UPDATE public.rides
    SET finalized_at = v_finalized_at
    WHERE id::TEXT = p_activity_id
      AND finalized_at IS DISTINCT FROM v_finalized_at;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_refresh_distribution_dependents(
    p_vault_id NUMERIC,
    p_epoch NUMERIC
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    IF p_vault_id IS NULL
       OR p_vault_id <> pg_catalog.trunc(p_vault_id)
       OR p_vault_id NOT BETWEEN
            0 AND 18446744073709551615::NUMERIC THEN
        RAISE EXCEPTION 'vault_id must be an unsigned u64 integer'
            USING ERRCODE = '22003';
    END IF;
    IF p_epoch IS NULL
       OR p_epoch <> pg_catalog.trunc(p_epoch)
       OR p_epoch NOT BETWEEN
            0 AND 18446744073709551615::NUMERIC THEN
        RAISE EXCEPTION 'epoch must be an unsigned u64 integer'
            USING ERRCODE = '22003';
    END IF;

    SELECT pg_catalog.min(distribution.finalized_at)
    INTO v_finalized_at
    FROM public.indexed_epoch_distributions AS distribution
    WHERE distribution.vault_id = p_vault_id
      AND distribution.epoch = p_epoch
      AND distribution.finalized_at IS NOT NULL;

    UPDATE public.epoch_distributions AS legacy_distribution
    SET finalized_at = v_finalized_at
    WHERE legacy_distribution.epoch::NUMERIC = p_epoch
      AND (
          legacy_distribution.vault_id::NUMERIC = p_vault_id
          OR EXISTS (
              SELECT 1
              FROM public.indexed_vaults AS indexed_vault
              WHERE indexed_vault.id = p_vault_id
                AND legacy_distribution.vault_signature =
                    indexed_vault.signature_hex
          )
      )
      AND legacy_distribution.finalized_at IS DISTINCT FROM v_finalized_at;

    FOR v_activity_id IN
        SELECT DISTINCT completion.activity_id
        FROM public.indexed_climb_completion_flows AS flow
        JOIN public.indexed_vaults AS indexed_vault
          ON indexed_vault.id = flow.vault_id
        JOIN public.vault_completions AS completion
          ON completion.completion_evidence_hash =
                flow.completion_evidence_hash
         AND completion.vault_signature = indexed_vault.signature_hex
         AND completion.completion_evidence_version =
                flow.completion_evidence_version
         AND completion.completion_evidence_version IN (2, 3)
         AND completion.cal_tribute = flow.cal_tributed
        WHERE flow.vault_id = p_vault_id
          AND flow.credited_settlement_week = p_epoch
          AND completion.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_sync_completion_flow_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_activity_id TEXT;
BEGIN
    FOR v_activity_id IN
        SELECT DISTINCT completion.activity_id
        FROM public.indexed_vaults AS indexed_vault
        JOIN public.vault_completions AS completion
          ON completion.vault_signature = indexed_vault.signature_hex
        WHERE indexed_vault.id = NEW.vault_id
          AND completion.completion_evidence_hash =
                NEW.completion_evidence_hash
          AND completion.completion_evidence_version =
                NEW.completion_evidence_version
          AND completion.completion_evidence_version IN (2, 3)
          AND completion.cal_tribute = NEW.cal_tributed
          AND completion.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
    RETURN NEW;
END;
$$;

-- Local Legend consumes confirmed completion receipts, regardless of whether
-- their economics were admitted with the immutable parent V2 plan or the
-- one-time V3 Threshold release child authority. The branches are disjoint by
-- frozen evidence lineage and each remains exactly-once.
CREATE OR REPLACE VIEW public.confirmed_vault_completion_candidates
WITH (security_invoker = true)
AS
SELECT
    step.vault_id,
    completion.vault_signature,
    completion.wallet,
    completion.activity_id,
    completion.completed_at,
    completion.time_seconds,
    completion.cal_tribute,
    completion.on_chain_tx,
    completion.chain_confirmation_status,
    completion.completion_receipt_pda,
    completion.completion_evidence_hash,
    completion.chain_confirmed_at
FROM public.vault_completions AS completion
JOIN public.ride_economic_plans AS plan
  ON plan.ride_id::TEXT = completion.activity_id
JOIN public.ride_economic_completion_steps AS step
  ON step.ride_id = plan.ride_id
 AND step.vault_signature = completion.vault_signature
 AND step.expected_receipt_pda = completion.completion_receipt_pda
WHERE plan.state = 'complete'
  AND step.state = 'projected'
  AND completion.chain_confirmation_status = 'confirmed'
  AND completion.completion_receipt_pda IS NOT NULL
  AND completion.chain_confirmed_at IS NOT NULL
  AND (
      completion.on_chain_tx IS NULL
      OR completion.on_chain_tx NOT LIKE 'exists:%'
  )
UNION ALL
SELECT
    release_step.vault_id,
    completion.vault_signature,
    completion.wallet,
    completion.activity_id,
    completion.completed_at,
    completion.time_seconds,
    completion.cal_tribute,
    completion.on_chain_tx,
    completion.chain_confirmation_status,
    completion.completion_receipt_pda,
    completion.completion_evidence_hash,
    completion.chain_confirmed_at
FROM public.vault_completions AS completion
JOIN public.reward_threshold_release_snapshots AS snapshot
  ON snapshot.ride_id::TEXT = completion.activity_id
JOIN public.reward_threshold_release_executions AS execution
  ON execution.snapshot_id = snapshot.id
JOIN public.reward_threshold_release_steps AS release_step
  ON release_step.snapshot_id = snapshot.id
 AND release_step.vault_signature = completion.vault_signature
 AND release_step.expected_receipt_pda = completion.completion_receipt_pda
 AND release_step.completion_evidence_hash =
        completion.completion_evidence_hash
 AND release_step.exact_tribute_base_units = completion.cal_tribute
 AND release_step.completed_at = completion.completed_at
 AND release_step.completion_time_s = completion.time_seconds
JOIN public.ride_economic_plans AS parent_plan
  ON parent_plan.ride_id = snapshot.ride_id
JOIN public.indexed_climb_completion_receipts AS indexed_receipt
  ON indexed_receipt.pda = completion.completion_receipt_pda
 AND indexed_receipt.ride_attestation_pda =
        parent_plan.expected_attestation_pda
 AND indexed_receipt.release_authority_pda =
        execution.expected_release_authority_pda
 AND indexed_receipt.completion_evidence_hash =
        release_step.completion_evidence_hash
 AND indexed_receipt.cal_tributed = release_step.exact_tribute_base_units
JOIN public.indexed_climb_completion_flows AS flow
  ON flow.completion_evidence_hash = release_step.completion_evidence_hash
 AND flow.release_authority_pda = execution.expected_release_authority_pda
 AND flow.vault_id = release_step.vault_id
 AND flow.ride_attestation = parent_plan.expected_attestation_pda
 AND flow.cal_tributed = release_step.exact_tribute_base_units
 AND flow.credited_settlement_week =
        indexed_receipt.credited_settlement_week
WHERE completion.completion_evidence_version = 3
  AND completion.wallet = execution.wallet
  AND execution.state = 'complete'
  AND execution.terminal_projected_at IS NOT NULL
  AND release_step.state = 'projected'
  AND release_step.completion_evidence_version = 3
  AND parent_plan.state = 'complete'
  AND parent_plan.terminal_projected_at IS NOT NULL
  AND parent_plan.reward_policy = 'threshold_provisional_hold_v1'
  AND parent_plan.total_tss = 0
  AND parent_plan.exact_cal_base_units = 0
  AND indexed_receipt.completion_evidence_version = 3
  AND flow.completion_evidence_version = 3
  AND completion.chain_confirmation_status = 'confirmed'
  AND completion.completion_receipt_pda IS NOT NULL
  AND completion.chain_confirmed_at IS NOT NULL
  AND (
      completion.on_chain_tx IS NULL
      OR completion.on_chain_tx NOT LIKE 'exists:%'
  );

REVOKE ALL ON public.confirmed_vault_completion_candidates FROM PUBLIC;
REVOKE ALL ON public.confirmed_vault_completion_candidates
    FROM anon, authenticated;
GRANT SELECT ON public.confirmed_vault_completion_candidates TO service_role;

REVOKE ALL ON FUNCTION public.create_reward_threshold_release_batch(
    UUID, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.register_reward_threshold_provisional_hold(JSONB)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
    public.register_reward_threshold_provisional_hold(JSONB)
    TO service_role;

REVOKE ALL ON FUNCTION
    public.record_reward_threshold_provisional_hold_admission(
        UUID, TIMESTAMPTZ, TEXT
    ) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
    public.record_reward_threshold_provisional_hold_admission(
        UUID, TIMESTAMPTZ, TEXT
    ) TO service_role;

REVOKE ALL ON FUNCTION public.claim_due_reward_threshold_release_item(
    UUID, INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_reward_threshold_release_item(
    UUID, INTEGER
) TO service_role;

REVOKE ALL ON FUNCTION public.mark_reward_threshold_release_item_terminal(
    UUID, UUID, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_reward_threshold_release_item_terminal(
    UUID, UUID, TEXT, TEXT, JSONB
) TO service_role;

REVOKE ALL ON FUNCTION public.repair_reward_threshold_release_item_review(
    UUID, TEXT
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.repair_reward_threshold_release_item_review(
    UUID, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.freeze_reward_threshold_release_snapshot(
    JSONB, JSONB, UUID
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.freeze_reward_threshold_release_snapshot(
    JSONB, JSONB, UUID
) TO service_role;

REVOKE ALL ON FUNCTION public.get_reward_threshold_release_execution(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_reward_threshold_release_execution(UUID)
    TO service_role;

REVOKE ALL ON FUNCTION public.claim_due_reward_threshold_release_execution(
    UUID, INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_reward_threshold_release_execution(
    UUID, INTEGER
) TO service_role;

REVOKE ALL ON FUNCTION public.advance_reward_threshold_release_execution(
    UUID, UUID, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.advance_reward_threshold_release_execution(
    UUID, UUID, TEXT, TEXT, JSONB
) TO service_role;

REVOKE ALL ON FUNCTION public.confirm_reward_threshold_release_step(
    UUID, UUID, INTEGER, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.confirm_reward_threshold_release_step(
    UUID, UUID, INTEGER, TEXT, TEXT, TIMESTAMPTZ
) TO service_role;

REVOKE ALL ON FUNCTION
    public.reconcile_confirmed_reward_threshold_release_completion(
        UUID, UUID, INTEGER
    ) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION
    public.reconcile_confirmed_reward_threshold_release_completion(
        UUID, UUID, INTEGER
    ) TO service_role;

REVOKE ALL ON FUNCTION public.mark_reward_threshold_release_step_projected(
    UUID, UUID, INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_reward_threshold_release_step_projected(
    UUID, UUID, INTEGER
) TO service_role;

REVOKE ALL ON FUNCTION public.mark_reward_threshold_release_review(
    UUID, UUID, TEXT, JSONB
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_reward_threshold_release_review(
    UUID, UUID, TEXT, JSONB
) TO service_role;

REVOKE ALL ON FUNCTION public.repair_reward_threshold_release_execution(
    UUID, TEXT
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.repair_reward_threshold_release_execution(
    UUID, TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.checkpoint_reward_threshold_release_retry(
    UUID, UUID, TEXT, INTEGER, INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.checkpoint_reward_threshold_release_retry(
    UUID, UUID, TEXT, INTEGER, INTEGER
) TO service_role;

REVOKE ALL ON FUNCTION public.project_reward_threshold_release_terminal(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.project_reward_threshold_release_terminal(UUID)
    TO service_role;

REVOKE ALL ON FUNCTION public.resolve_reward_threshold_release_lifecycle(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.resolve_reward_threshold_release_lifecycle(UUID)
    TO service_role;

REVOKE ALL ON public.reward_threshold_release_ops
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.reward_threshold_release_ops TO service_role;

REVOKE ALL ON FUNCTION public.prevent_reward_threshold_hold_release_mutation()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.prevent_network_default_completion_step()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.validate_reward_threshold_release_snapshot()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.bind_reward_threshold_release_batch_on_seal()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_reward_threshold_release_execution_frozen()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_reward_threshold_release_step_frozen()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_indexed_held_release_immutability()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_indexed_release_cal_receipt_immutability()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
    public.enforce_indexed_release_completion_receipt_immutability()
    FROM PUBLIC, anon, authenticated, service_role;

COMMENT ON TABLE public.reward_threshold_provisional_holds IS
    'Immutable pre-chain evidence for a zero-CAL ride held pending Threshold establishment; retained after mutable ride deletion.';
COMMENT ON TABLE public.reward_threshold_provisional_hold_admissions IS
    'One-time finalized RideAttestation clock used for held-ride eligibility; retained after mutable ride deletion.';
COMMENT ON TABLE public.reward_threshold_release_batches IS
    'One immutable release batch per sealed Threshold authority; eligibility is frozen at creation.';
COMMENT ON TABLE public.reward_threshold_release_snapshots IS
    'Release-specific Threshold economics retained after mutable ride deletion; never a rewrite of ride-time 200 W provenance.';
COMMENT ON TABLE public.reward_threshold_release_steps IS
    'V3 child completion receipts attributed to the release-time Settlement Flow.';
COMMENT ON COLUMN public.vault_completions.completion_evidence_version IS
    '1 is historical identity-only; 2 is ordinary exact tribute; 3 is held-ride Threshold release exact tribute.';
