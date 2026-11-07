-- Private rider Threshold projection and release-aware money state.
-- Rider surfaces never read authority tables directly and never receive the
-- display-only candidate. Only a genuinely scheduled future raise is exposed.

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS threshold_training_w INTEGER,
    ADD COLUMN IF NOT EXISTS threshold_training_kind TEXT,
    ADD COLUMN IF NOT EXISTS threshold_training_authority_id UUID
        REFERENCES public.reward_ftp_authorities(id),
    ADD COLUMN IF NOT EXISTS threshold_training_promotion_id UUID
        REFERENCES public.reward_threshold_pending_promotions(id);

ALTER TABLE public.reward_threshold_release_executions
    ADD COLUMN IF NOT EXISTS training_projected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS training_projection_error TEXT;

DROP INDEX IF EXISTS public.idx_reward_threshold_release_execution_due;
CREATE INDEX idx_reward_threshold_release_execution_due
    ON public.reward_threshold_release_executions(next_attempt_at, created_at)
    WHERE state <> 'review'
      AND (
          state <> 'complete'
          OR terminal_projected_at IS NULL
          OR training_projected_at IS NULL
      );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'rides_threshold_training_w_range'
    ) THEN
        ALTER TABLE public.rides ADD CONSTRAINT rides_threshold_training_w_range
            CHECK (
                threshold_training_w IS NULL
                OR threshold_training_w BETWEEN 50 AND 500
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'rides_threshold_training_kind_check'
    ) THEN
        ALTER TABLE public.rides ADD CONSTRAINT rides_threshold_training_kind_check
            CHECK (
                threshold_training_kind IS NULL
                OR threshold_training_kind IN ('sealed', 'pending')
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_reward_threshold_rider_projection(
    p_user_id UUID,
    p_as_of TIMESTAMPTZ DEFAULT pg_catalog.statement_timestamp()
) RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ratchet public.reward_threshold_ratchets%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_pending public.reward_threshold_pending_promotions%ROWTYPE;
    v_pending_count INTEGER;
    v_sealing_in_progress BOOLEAN := FALSE;
    v_pending_json JSONB := 'null'::JSONB;
    v_denominator JSONB;
BEGIN
    IF p_user_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.users WHERE id = p_user_id
    ) THEN
        RAISE EXCEPTION 'Threshold rider does not exist';
    END IF;
    IF p_as_of IS NULL THEN
        RAISE EXCEPTION 'Threshold projection clock is required';
    END IF;

    SELECT * INTO v_ratchet
    FROM public.reward_threshold_ratchets
    WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object(
            'state', 'establishing',
            'current_w', NULL,
            'established_at', NULL,
            'last_raised_at', NULL,
            'pending_monday', NULL,
            'training_denominator', pg_catalog.jsonb_build_object(
                'watts', 200,
                'kind', 'network_placeholder',
                'provisional', TRUE
            ),
            'sealing_in_progress', FALSE
        );
    END IF;

    IF (
        v_ratchet.sealed_authority_id IS NULL
        OR v_ratchet.sealed_ftp_w IS NULL
        OR v_ratchet.established_at IS NULL
    ) AND NOT (
        v_ratchet.sealed_authority_id IS NULL
        AND v_ratchet.sealed_ftp_w IS NULL
        AND v_ratchet.established_at IS NULL
        AND v_ratchet.last_raised_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Threshold ratchet is partially established';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = p_user_id
          AND pending.status = 'pending'
          AND pending.effective_at <= p_as_of
    ) INTO v_sealing_in_progress;

    IF v_ratchet.sealed_authority_id IS NULL THEN
        RETURN pg_catalog.jsonb_build_object(
            'state', 'establishing',
            'current_w', NULL,
            'established_at', NULL,
            'last_raised_at', NULL,
            'pending_monday', NULL,
            'training_denominator', pg_catalog.jsonb_build_object(
                'watts', 200,
                'kind', 'network_placeholder',
                'provisional', TRUE
            ),
            'sealing_in_progress', v_sealing_in_progress
        );
    END IF;

    SELECT * INTO v_authority
    FROM public.reward_ftp_authorities
    WHERE id = v_ratchet.sealed_authority_id;
    IF NOT FOUND
       OR v_authority.user_id IS DISTINCT FROM p_user_id
       OR v_authority.ftp_w IS DISTINCT FROM v_ratchet.sealed_ftp_w
       OR v_authority.effective_at > p_as_of
       OR v_ratchet.established_at > p_as_of
       OR (
           v_ratchet.last_raised_at IS NOT NULL
           AND v_ratchet.last_raised_at <= v_ratchet.established_at
       ) THEN
        RAISE EXCEPTION 'Threshold sealed authority is inconsistent';
    END IF;

    SELECT pg_catalog.count(*)::INTEGER INTO v_pending_count
    FROM public.reward_threshold_pending_promotions AS pending
    WHERE pending.user_id = p_user_id
      AND pending.status = 'pending'
      AND pending.promotion_kind = 'raise'
      AND pending.effective_at > p_as_of;
    IF v_pending_count > 1 THEN
        RAISE EXCEPTION 'Threshold has multiple future rider promotions';
    END IF;
    IF v_pending_count = 1 THEN
        SELECT * INTO v_pending
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = p_user_id
          AND pending.status = 'pending'
          AND pending.promotion_kind = 'raise'
          AND pending.effective_at > p_as_of;
        IF v_pending.target_ftp_w <= v_ratchet.sealed_ftp_w
           OR v_pending.baseline_authority_id IS DISTINCT FROM
                v_ratchet.sealed_authority_id THEN
            RAISE EXCEPTION 'Threshold future raise is inconsistent';
        END IF;
        v_pending_json := pg_catalog.jsonb_build_object(
            'promotion_id', v_pending.id,
            'watts', v_pending.target_ftp_w,
            'effective_at', v_pending.effective_at
        );
        v_denominator := pg_catalog.jsonb_build_object(
            'watts', v_pending.target_ftp_w,
            'kind', 'pending',
            'provisional', TRUE,
            'promotion_id', v_pending.id
        );
    ELSE
        v_denominator := pg_catalog.jsonb_build_object(
            'watts', v_ratchet.sealed_ftp_w,
            'kind', 'sealed',
            'provisional', FALSE,
            'authority_id', v_ratchet.sealed_authority_id
        );
    END IF;

    RETURN pg_catalog.jsonb_build_object(
        'state', 'established',
        'current_w', v_ratchet.sealed_ftp_w,
        'established_at', v_ratchet.established_at,
        'last_raised_at', v_ratchet.last_raised_at,
        'pending_monday', v_pending_json,
        'training_denominator', v_denominator,
        'sealing_in_progress', v_sealing_in_progress
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.get_reward_threshold_ride_projection(
    p_ride_id UUID
) RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride public.rides%ROWTYPE;
    v_hold public.reward_threshold_provisional_holds%ROWTYPE;
    v_admission public.reward_threshold_provisional_hold_admissions%ROWTYPE;
    v_item public.reward_threshold_release_batch_items%ROWTYPE;
    v_claim public.reward_threshold_release_item_claims%ROWTYPE;
    v_snapshot public.reward_threshold_release_snapshots%ROWTYPE;
    v_execution public.reward_threshold_release_executions%ROWTYPE;
    v_expected_cal INTEGER;
BEGIN
    SELECT * INTO v_ride FROM public.rides WHERE id = p_ride_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF v_ride.reward_policy IS DISTINCT FROM 'threshold_provisional_hold_v1' THEN
        RETURN NULL;
    END IF;

    SELECT * INTO v_hold
    FROM public.reward_threshold_provisional_holds
    WHERE ride_id = p_ride_id;
    IF NOT FOUND OR v_hold.user_id IS DISTINCT FROM v_ride.user_id THEN
        RAISE EXCEPTION 'Threshold hold authority is missing or inconsistent';
    END IF;
    SELECT * INTO v_admission
    FROM public.reward_threshold_provisional_hold_admissions
    WHERE hold_id = v_hold.id;
    IF NOT FOUND OR v_admission.ride_id IS DISTINCT FROM p_ride_id THEN
        RAISE EXCEPTION 'Threshold hold admission is missing or inconsistent';
    END IF;

    SELECT * INTO v_item
    FROM public.reward_threshold_release_batch_items
    WHERE hold_id = v_hold.id;
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('state', 'held');
    END IF;
    IF v_item.disposition = 'lapsed' THEN
        RETURN pg_catalog.jsonb_build_object('state', 'lapsed');
    END IF;

    SELECT * INTO v_claim
    FROM public.reward_threshold_release_item_claims
    WHERE batch_item_id = v_item.id;
    IF NOT FOUND THEN
        RETURN pg_catalog.jsonb_build_object('state', 'held');
    END IF;
    IF v_claim.terminal_disposition IS NOT NULL THEN
        RETURN pg_catalog.jsonb_build_object('state', v_claim.terminal_disposition);
    END IF;
    IF v_claim.consumed_snapshot_id IS NULL THEN
        RETURN pg_catalog.jsonb_build_object('state', 'held');
    END IF;

    SELECT * INTO v_snapshot
    FROM public.reward_threshold_release_snapshots
    WHERE id = v_claim.consumed_snapshot_id;
    IF NOT FOUND
       OR v_snapshot.batch_item_id IS DISTINCT FROM v_item.id
       OR v_snapshot.ride_id IS DISTINCT FROM p_ride_id
       OR v_snapshot.user_id IS DISTINCT FROM v_ride.user_id THEN
        RAISE EXCEPTION 'Threshold release snapshot is inconsistent';
    END IF;
    SELECT * INTO v_execution
    FROM public.reward_threshold_release_executions
    WHERE snapshot_id = v_snapshot.id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Threshold release execution is missing';
    END IF;
    IF v_execution.state = 'review' THEN
        RETURN pg_catalog.jsonb_build_object('state', 'review');
    END IF;
    IF v_execution.state <> 'complete' THEN
        RETURN pg_catalog.jsonb_build_object('state', 'held');
    END IF;
    IF v_execution.terminal_projected_at IS NULL
       OR v_execution.training_projected_at IS NULL THEN
        RETURN pg_catalog.jsonb_build_object('state', 'held');
    END IF;

    v_expected_cal := pg_catalog.trunc(
        v_snapshot.exact_cal_base_units / 1000000000
    )::INTEGER;
    IF v_ride.cal_earned IS DISTINCT FROM v_expected_cal THEN
        RAISE EXCEPTION 'Threshold release ride projection is inconsistent';
    END IF;
    RETURN pg_catalog.jsonb_build_object(
        'state', 'counted',
        'snapshot_id', v_snapshot.id,
        'threshold_w', v_snapshot.reward_ftp_w,
        'threshold_effective_at', v_execution.terminal_projected_at,
        'economic_tss', v_snapshot.economic_tss,
        'cal_earned', v_expected_cal
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.get_reward_threshold_ride_projections(
    p_ride_ids UUID[]
) RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride_id UUID;
    v_projection JSONB;
    v_result JSONB := '{}'::JSONB;
BEGIN
    IF p_ride_ids IS NULL THEN
        RAISE EXCEPTION 'Threshold ride ids are required';
    END IF;
    FOREACH v_ride_id IN ARRAY p_ride_ids LOOP
        v_projection := public.get_reward_threshold_ride_projection(v_ride_id);
        IF v_projection IS NOT NULL THEN
            v_result := v_result || pg_catalog.jsonb_build_object(
                v_ride_id::TEXT, v_projection
            );
        END IF;
    END LOOP;
    RETURN v_result;
END;
$$;

-- Once receipt-backed child economics are terminal, the original held ride
-- gains its one rider-visible Threshold TSS. Settlement attribution remains
-- entirely in the release week's child authority.
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
        SELECT 1 FROM public.reward_threshold_release_steps AS step
        WHERE step.snapshot_id = p_snapshot_id AND step.state <> 'projected'
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
        SET cal_earned = v_display_cal::INTEGER,
            tss = v_snapshot.economic_tss,
            threshold_training_w = v_snapshot.reward_ftp_w,
            threshold_training_kind = 'sealed',
            threshold_training_authority_id = v_snapshot.reward_ftp_authority_id,
            threshold_training_promotion_id = NULL
        WHERE id = v_product_ride_id
          AND user_id = v_snapshot.user_id
          AND COALESCE(cal_earned, 0) = 0
          AND tss IS NULL
          AND threshold_training_w IS NULL
          AND threshold_training_kind IS NULL
          AND threshold_training_authority_id IS NULL
          AND threshold_training_promotion_id IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Threshold release cannot overwrite existing ride projection'
                USING ERRCODE = 'BRR06';
        END IF;
    END IF;

    UPDATE public.reward_threshold_release_executions
    SET terminal_projected_at = pg_catalog.clock_timestamp(),
        last_error = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id;
    RETURN public.get_reward_threshold_release_execution(p_snapshot_id);
END;
$$;

-- A release stays claimable after chain and ride projection until its
-- original training day and forward Fitness/Fatigue/Form series are rebuilt.
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
          OR execution.training_projected_at IS NULL
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

CREATE OR REPLACE FUNCTION public.checkpoint_reward_threshold_training_retry(
    p_snapshot_id UUID,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    UPDATE public.reward_threshold_release_executions
    SET training_projection_error = pg_catalog.left(p_error, 2000),
        last_error = pg_catalog.left(p_error, 2000),
        next_attempt_at = pg_catalog.clock_timestamp()
            + pg_catalog.make_interval(
                secs => pg_catalog.greatest(
                    1, pg_catalog.least(p_retry_delay_seconds, 3600)
                )
            ),
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id
      AND state = 'complete'
      AND terminal_projected_at IS NOT NULL
      AND training_projected_at IS NULL;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_reward_threshold_training_projected(
    p_snapshot_id UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    UPDATE public.reward_threshold_release_executions
    SET training_projected_at = pg_catalog.clock_timestamp(),
        training_projection_error = NULL,
        last_error = NULL,
        lease_owner = NULL,
        lease_expires_at = NULL,
        lock_version = lock_version + 1,
        updated_at = pg_catalog.clock_timestamp()
    WHERE snapshot_id = p_snapshot_id
      AND state = 'complete'
      AND terminal_projected_at IS NOT NULL
      AND training_projected_at IS NULL;
    IF FOUND THEN
        RETURN TRUE;
    END IF;
    RETURN EXISTS (
        SELECT 1
        FROM public.reward_threshold_release_executions
        WHERE snapshot_id = p_snapshot_id
          AND training_projected_at IS NOT NULL
    );
END;
$$;

REVOKE ALL ON FUNCTION public.get_reward_threshold_rider_projection(UUID, TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_reward_threshold_rider_projection(UUID, TIMESTAMPTZ)
    TO service_role;
REVOKE ALL ON FUNCTION public.get_reward_threshold_ride_projection(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_reward_threshold_ride_projection(UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.get_reward_threshold_ride_projections(UUID[])
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_reward_threshold_ride_projections(UUID[])
    TO service_role;
REVOKE ALL ON FUNCTION public.claim_due_reward_threshold_release_execution(UUID, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.claim_due_reward_threshold_release_execution(UUID, INTEGER)
    TO service_role;
REVOKE ALL ON FUNCTION public.checkpoint_reward_threshold_training_retry(UUID, TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.checkpoint_reward_threshold_training_retry(UUID, TEXT, INTEGER)
    TO service_role;
REVOKE ALL ON FUNCTION public.mark_reward_threshold_training_projected(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.mark_reward_threshold_training_projected(UUID)
    TO service_role;
