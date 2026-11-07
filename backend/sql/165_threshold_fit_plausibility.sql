-- Provisional plausibility admission, Bead 8906g.2. No sealed authority is
-- rewritten. Constants require Tim ratification; calibration and limitations:
-- docs/research/THRESHOLD_FIT_PLAUSIBILITY.md.
-- Exact inverse-time collinearity is the CP model, not a rejection criterion.
BEGIN;

-- Drain existing writers before the authority census and retain the fence
-- through all function/trigger changes. An in-flight old registration body is
-- separately fenced at candidate insertion below, so it cannot resume later.
LOCK TABLE public.reward_threshold_candidates,
    public.reward_threshold_ratchets,
    public.reward_threshold_pending_promotions,
    public.reward_ftp_authorities IN SHARE ROW EXCLUSIVE MODE;

CREATE OR REPLACE FUNCTION public.reward_threshold_fit_is_plausible(
    p_best_180s_w NUMERIC, p_best_420s_w NUMERIC, p_best_900s_w NUMERIC
) RETURNS BOOLEAN
LANGUAGE sql IMMUTABLE SET search_path = ''
AS $$
    SELECT COALESCE((
        SELECT cp_w BETWEEN 50 AND 500
           -- PROVISIONAL inclusive floor: CP / E_180 >= 0.25.
           AND cp_w >= p_best_180s_w * 0.25
           -- PROVISIONAL inclusive ceiling: W-prime <= 60,000 joules.
           AND work_capacity_j <= 60000
        FROM public.derive_reward_threshold_cp(
            p_best_180s_w, p_best_420s_w, p_best_900s_w
        )
        WHERE p_best_180s_w::TEXT NOT IN ('NaN', 'Infinity', '-Infinity')
          AND p_best_420s_w::TEXT NOT IN ('NaN', 'Infinity', '-Infinity')
          AND p_best_900s_w::TEXT NOT IN ('NaN', 'Infinity', '-Infinity')
    ), FALSE)
$$;

-- Check both the submitting profile and the lifetime-max fit actually paying.
-- The latter can come from another source/earlier candidate. This also fences
-- pre-migration pending commitments whose cached economic maximum is invalid.
CREATE OR REPLACE FUNCTION public.reward_threshold_commitment_fit_is_plausible(
    p_user_id UUID, p_candidate_id UUID, p_economic_candidate_w NUMERIC
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.reward_threshold_candidates AS candidate
        WHERE candidate.id = p_candidate_id AND candidate.user_id = p_user_id
          AND candidate.power_source_id IS NOT NULL
          AND public.reward_threshold_fit_is_plausible(
              candidate.proposed_best_180s_w, candidate.proposed_best_420s_w,
              candidate.proposed_best_900s_w
          )
    ) AND EXISTS (
        SELECT 1 FROM public.reward_threshold_candidates AS economic
        WHERE economic.user_id = p_user_id AND economic.power_source_id IS NOT NULL
          AND economic.fitted_candidate_w = p_economic_candidate_w
          AND public.reward_threshold_fit_is_plausible(
              economic.proposed_best_180s_w, economic.proposed_best_420s_w,
              economic.proposed_best_900s_w
          )
    )
$$;

CREATE OR REPLACE FUNCTION public.reward_threshold_authority_fit_is_plausible(
    p_authority_id UUID
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT COALESCE((
        SELECT CASE
            -- Ratified migration-154 initialization inherits verified authority;
            -- there is no derived fit to classify. Do not invent one or change it.
            WHEN authority.evidence->>'promotion_kind' = 'initialization'
                 AND authority.evidence->>'candidate_id' IS NULL THEN TRUE
            ELSE public.reward_threshold_commitment_fit_is_plausible(
                authority.user_id, (authority.evidence->>'candidate_id')::UUID,
                (authority.evidence->>'economic_candidate_w')::NUMERIC
            ) END
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.id = p_authority_id AND authority.source = 'derived_eftp'
    ), FALSE)
$$;

-- This prospective policy cannot repair an already accepted bad economic max,
-- overwrite immutable sealed authority, or recall a frozen on-chain release.
-- Refuse atomically rather than strand old repair_required work or let an old
-- frozen snapshot bypass the new insertion checks. The live census had no
-- authorities and no eligible candidates; operators must recheck at rollout.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.reward_threshold_ratchets AS ratchet
        WHERE ratchet.economic_candidate_w IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.reward_threshold_candidates AS candidate
            WHERE candidate.user_id = ratchet.user_id
              AND candidate.power_source_id IS NOT NULL
              AND candidate.fitted_candidate_w = ratchet.economic_candidate_w
              AND public.reward_threshold_fit_is_plausible(
                  candidate.proposed_best_180s_w, candidate.proposed_best_420s_w,
                  candidate.proposed_best_900s_w
              )
        )
    ) OR EXISTS (
        SELECT 1 FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.status IN ('pending', 'repair_required')
          AND pending.promotion_kind <> 'initialization'
          AND NOT public.reward_threshold_commitment_fit_is_plausible(
              pending.user_id, pending.candidate_id, pending.target_candidate_w
          )
    ) OR EXISTS (
        SELECT 1 FROM public.reward_ftp_authorities AS authority
        WHERE authority.source = 'derived_eftp'
          AND NOT public.reward_threshold_authority_fit_is_plausible(authority.id)
    ) THEN
        RAISE EXCEPTION
            'Threshold plausibility migration requires review of existing economic authority; no changes applied'
            USING ERRCODE = 'BRR07';
    END IF;
END;
$$;

-- A pre-upgrade function body may resume after migration commits. Abort that
-- old transaction for retry instead of modifying NEW: its local variables
-- would otherwise still advance the economic maximum from the rejected fit.
CREATE OR REPLACE FUNCTION public.enforce_reward_threshold_fit_on_candidate()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
BEGIN
    IF NEW.power_source_id IS NOT NULL
       AND (NEW.disposition LIKE 'pending_%'
            OR NEW.disposition IN ('below_deadband', 'superseded'))
       AND NOT public.reward_threshold_fit_is_plausible(
           NEW.proposed_best_180s_w, NEW.proposed_best_420s_w,
           NEW.proposed_best_900s_w
       ) THEN
        RAISE EXCEPTION 'Threshold policy changed; retry registration for review'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_reward_threshold_fit_on_candidate
    BEFORE INSERT ON public.reward_threshold_candidates
    FOR EACH ROW EXECUTE FUNCTION public.enforce_reward_threshold_fit_on_candidate();

CREATE OR REPLACE FUNCTION public.enforce_reward_threshold_fit_on_seal()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
BEGIN
    IF NEW.evidence->>'promotion_kind' = 'initialization'
       AND NEW.evidence->>'candidate_id' IS NULL THEN
        RETURN NEW;
    END IF;
    IF NOT public.reward_threshold_commitment_fit_is_plausible(
        NEW.user_id, (NEW.evidence->>'candidate_id')::UUID,
        (NEW.evidence->>'economic_candidate_w')::NUMERIC
    ) THEN
        -- The existing batch sealer records repair_required; it never seals or
        -- releases CAL. Operator retry cannot bypass the unchanged predicate.
        RAISE EXCEPTION 'Threshold fit requires plausibility review' USING ERRCODE = 'BRR07';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_reward_threshold_fit_on_seal
    BEFORE INSERT ON public.reward_ftp_authorities
    FOR EACH ROW EXECUTE FUNCTION public.enforce_reward_threshold_fit_on_seal();

CREATE OR REPLACE FUNCTION public.enforce_reward_threshold_fit_on_release()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = ''
AS $$
DECLARE v_authority_id UUID;
BEGIN
    IF TG_TABLE_NAME = 'reward_threshold_release_batches' THEN
        v_authority_id := NEW.established_authority_id;
    ELSE
        v_authority_id := NEW.reward_ftp_authority_id;
    END IF;
    IF NOT public.reward_threshold_authority_fit_is_plausible(v_authority_id) THEN
        -- The planner maps this code to durable, repairable review, not lapse.
        RAISE EXCEPTION 'Threshold fit requires plausibility review' USING ERRCODE = 'BRR07';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_reward_threshold_fit_on_release_batch
    BEFORE INSERT ON public.reward_threshold_release_batches
    FOR EACH ROW EXECUTE FUNCTION public.enforce_reward_threshold_fit_on_release();
CREATE TRIGGER trg_reward_threshold_fit_on_release_snapshot
    BEFORE INSERT ON public.reward_threshold_release_snapshots
    FOR EACH ROW EXECUTE FUNCTION public.enforce_reward_threshold_fit_on_release();

CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort_at(
    p_ride_id UUID,
    p_best_180s_w NUMERIC,
    p_best_420s_w NUMERIC,
    p_best_900s_w NUMERIC,
    p_accepted_at TIMESTAMPTZ
) RETURNS public.reward_threshold_candidates
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_ride public.rides%ROWTYPE;
    v_effort public.reward_threshold_efforts%ROWTYPE;
    v_candidate public.reward_threshold_candidates%ROWTYPE;
    v_ratchet public.reward_threshold_ratchets%ROWTYPE;
    v_source_envelope public.reward_threshold_source_envelopes%ROWTYPE;
    v_standing_pending public.reward_threshold_pending_promotions%ROWTYPE;
    v_received_at TIMESTAMPTZ;
    v_schedule_anchor_at TIMESTAMPTZ;
    v_upload_target_at TIMESTAMPTZ;
    v_source_eligible BOOLEAN;
    v_source_decision TEXT;
    v_evidence JSONB;
    v_display_180 NUMERIC;
    v_display_420 NUMERIC;
    v_display_900 NUMERIC;
    v_display_cp NUMERIC;
    v_display_work NUMERIC;
    v_proposed_180 NUMERIC;
    v_proposed_420 NUMERIC;
    v_proposed_900 NUMERIC;
    v_fitted_cp NUMERIC;
    v_fitted_work NUMERIC;
    v_fit_plausible BOOLEAN := FALSE;
    v_economic_cp NUMERIC;
    v_economic_work NUMERIC;
    v_standing_fitted_cp NUMERIC;
    v_previous_candidate_id UUID;
    v_candidate_id UUID := gen_random_uuid();
    v_baseline_id UUID;
    v_baseline_w INTEGER;
    v_baseline_effective_at TIMESTAMPTZ;
    v_first_existing_effective_at TIMESTAMPTZ;
    v_latest_existing_effective_at TIMESTAMPTZ;
    v_disposition TEXT;
    v_promotion_kind TEXT;
    v_target_w INTEGER;
    v_target_at TIMESTAMPTZ;
BEGIN
    IF p_accepted_at IS NULL THEN
        RAISE EXCEPTION 'Threshold acceptance time is required';
    END IF;
    IF p_best_180s_w IS NULL
       AND p_best_420s_w IS NULL
       AND p_best_900s_w IS NULL THEN
        RAISE EXCEPTION 'Threshold evidence requires at least one power anchor';
    END IF;
    IF p_best_180s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_420s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_900s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_180s_w < 0 OR p_best_420s_w < 0 OR p_best_900s_w < 0 THEN
        RAISE EXCEPTION 'Threshold anchors must be finite nonnegative watts';
    END IF;

    SELECT * INTO v_ride
    FROM public.rides AS ride
    WHERE ride.id = p_ride_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ride not found for Threshold evidence: %', p_ride_id;
    END IF;

    SELECT candidate.* INTO v_candidate
    FROM public.reward_threshold_candidates AS candidate
    WHERE candidate.ride_id = p_ride_id;
    IF FOUND THEN
        RETURN v_candidate;
    END IF;

    IF v_ride.upload_verified_at > p_accepted_at + INTERVAL '10 minutes' THEN
        RAISE EXCEPTION 'Threshold upload verification clock skew exceeds 10 minutes';
    END IF;
    v_received_at := least(
        COALESCE(v_ride.upload_verified_at, p_accepted_at), p_accepted_at
    );
    v_schedule_anchor_at := greatest(
        COALESCE(v_ride.upload_verified_at, p_accepted_at), p_accepted_at
    );

    v_source_eligible := COALESCE((
        v_ride.upload_verified_at IS NOT NULL
        AND COALESCE(
            lower(btrim(v_ride.file_hash::TEXT)) ~ '^[0-9a-f]{64}$',
            FALSE
        )
        AND v_ride.threshold_recording_source = 'br_ios'
        AND v_ride.threshold_power_source_id IS NOT NULL
        AND v_ride.threshold_source_identity_complete IS TRUE
        AND v_ride.import_diagnostics->>'provenance_tier' = 'first_party_recorded'
        AND v_ride.canonical_match IS TRUE
    ), FALSE);
    v_source_decision := CASE
        WHEN v_ride.upload_verified_at IS NULL THEN 'missing_upload_verification'
        WHEN v_ride.file_hash IS NULL
             OR lower(btrim(v_ride.file_hash::TEXT)) !~ '^[0-9a-f]{64}$'
            THEN 'missing_raw_file_hash'
        WHEN v_ride.threshold_recording_source IS DISTINCT FROM 'br_ios'
            THEN 'not_br_ios_recording'
        WHEN v_ride.threshold_power_source_id IS NULL
             OR v_ride.threshold_source_identity_complete IS NOT TRUE
            THEN 'missing_or_mixed_power_source_identity'
        WHEN v_ride.import_diagnostics->>'provenance_tier'
             IS DISTINCT FROM 'first_party_recorded'
            THEN 'not_first_party_recorded'
        WHEN v_ride.canonical_match IS NOT TRUE THEN 'canonical_mismatch_or_absent'
        ELSE 'eligible'
    END;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_ride.user_id::TEXT, 2982)
    );

    PERFORM public.seal_due_reward_threshold_promotions_for_user_at(
        v_ride.user_id, p_accepted_at
    );
    v_upload_target_at := public.next_reward_threshold_monday(
        v_schedule_anchor_at
    );

    SELECT authority.id, authority.ftp_w, authority.effective_at
    INTO v_baseline_id, v_baseline_w, v_baseline_effective_at
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id
    ORDER BY authority.ftp_w DESC, authority.verified_at DESC,
             authority.effective_at DESC, authority.id DESC
    LIMIT 1;
    SELECT min(authority.effective_at), max(authority.effective_at)
    INTO v_first_existing_effective_at, v_latest_existing_effective_at
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id;

    INSERT INTO public.reward_threshold_ratchets (
        user_id, sealed_authority_id, sealed_ftp_w, established_at
    ) VALUES (
        v_ride.user_id, v_baseline_id, v_baseline_w, v_first_existing_effective_at
    )
    ON CONFLICT (user_id) DO NOTHING;
    UPDATE public.reward_threshold_ratchets AS ratchet
    SET sealed_authority_id = v_baseline_id,
        sealed_ftp_w = v_baseline_w,
        established_at = COALESCE(
            ratchet.established_at, v_first_existing_effective_at
        ),
        updated_at = p_accepted_at
    WHERE ratchet.user_id = v_ride.user_id
      AND v_baseline_w IS NOT NULL
      AND (
          ratchet.sealed_ftp_w IS NULL
          OR ratchet.sealed_ftp_w < v_baseline_w
      );
    SELECT * INTO v_ratchet
    FROM public.reward_threshold_ratchets AS ratchet
    WHERE ratchet.user_id = v_ride.user_id
    FOR UPDATE;

    v_display_180 := greatest(v_ratchet.display_best_180s_w, p_best_180s_w);
    v_display_420 := greatest(v_ratchet.display_best_420s_w, p_best_420s_w);
    v_display_900 := greatest(v_ratchet.display_best_900s_w, p_best_900s_w);
    SELECT cp_w, work_capacity_j INTO v_display_cp, v_display_work
    FROM public.derive_reward_threshold_cp(
        v_display_180, v_display_420, v_display_900
    );

    IF v_source_eligible THEN
        INSERT INTO public.reward_threshold_source_envelopes (
            user_id, power_source_id
        ) VALUES (
            v_ride.user_id, v_ride.threshold_power_source_id
        )
        ON CONFLICT (user_id, power_source_id) DO NOTHING;
        SELECT * INTO v_source_envelope
        FROM public.reward_threshold_source_envelopes AS envelope
        WHERE envelope.user_id = v_ride.user_id
          AND envelope.power_source_id = v_ride.threshold_power_source_id
        FOR UPDATE;

        v_proposed_180 := greatest(
            v_source_envelope.accepted_best_180s_w, p_best_180s_w
        );
        v_proposed_420 := greatest(
            v_source_envelope.accepted_best_420s_w, p_best_420s_w
        );
        v_proposed_900 := greatest(
            v_source_envelope.accepted_best_900s_w, p_best_900s_w
        );
        SELECT cp_w, work_capacity_j INTO v_fitted_cp, v_fitted_work
        FROM public.derive_reward_threshold_cp(
            v_proposed_180, v_proposed_420, v_proposed_900
        );
        v_fit_plausible := public.reward_threshold_fit_is_plausible(
            v_proposed_180, v_proposed_420, v_proposed_900
        );
        IF v_fit_plausible THEN
            IF v_ratchet.economic_candidate_w IS NULL
               OR v_fitted_cp > v_ratchet.economic_candidate_w THEN
                v_economic_cp := v_fitted_cp;
                v_economic_work := v_fitted_work;
            ELSE
                v_economic_cp := v_ratchet.economic_candidate_w;
                v_economic_work := v_ratchet.economic_work_capacity_j;
            END IF;
        ELSE
            v_economic_cp := v_ratchet.economic_candidate_w;
            v_economic_work := v_ratchet.economic_work_capacity_j;
        END IF;
    ELSE
        v_proposed_180 := NULL;
        v_proposed_420 := NULL;
        v_proposed_900 := NULL;
    END IF;

    IF NOT v_source_eligible THEN
        v_disposition := 'display_only';
    ELSIF v_fitted_cp IS NULL THEN
        IF v_proposed_180 IS NULL OR v_proposed_420 IS NULL OR v_proposed_900 IS NULL THEN
            v_disposition := 'insufficient_history';
        ELSE
            v_disposition := 'invalid_fit_review';
        END IF;
    ELSIF v_fitted_cp < 50 THEN
        v_disposition := 'below_bounds_review';
    ELSIF v_fitted_cp > 500 THEN
        v_disposition := 'above_bounds_review';
    ELSIF NOT v_fit_plausible THEN
        v_disposition := 'below_bounds_review';
    ELSE
        v_target_w := pg_catalog.ceil(v_economic_cp)::INTEGER;
        v_target_at := v_upload_target_at;
        IF v_baseline_w IS NULL THEN
            v_disposition := 'pending_establishment';
            v_promotion_kind := 'establishment';
        ELSIF v_economic_cp < v_baseline_w::NUMERIC * 1.025 THEN
            v_disposition := 'below_deadband';
            v_target_w := NULL;
            v_target_at := NULL;
        ELSE
            v_disposition := 'pending_raise';
            v_promotion_kind := 'raise';
            v_target_at := greatest(
                v_target_at,
                public.reward_threshold_monday_on_or_after(
                    v_latest_existing_effective_at
                )
            );
        END IF;
    END IF;

    IF v_disposition LIKE 'pending_%' THEN
        WHILE EXISTS (
            SELECT 1
            FROM public.reward_ftp_authorities AS authority
            WHERE authority.user_id = v_ride.user_id
              AND authority.effective_at = v_target_at
        ) OR EXISTS (
            SELECT 1
            FROM public.reward_threshold_pending_promotions AS occupied
            WHERE occupied.user_id = v_ride.user_id
              AND occupied.effective_at = v_target_at
              AND occupied.status <> 'pending'
        ) LOOP
            v_target_at := public.next_reward_threshold_monday(v_target_at);
        END LOOP;

        SELECT pending.* INTO v_standing_pending
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = v_ride.user_id
          AND pending.effective_at = v_target_at
          AND pending.status = 'pending'
        FOR UPDATE;
        IF FOUND THEN
            SELECT candidate.fitted_candidate_w INTO v_standing_fitted_cp
            FROM public.reward_threshold_candidates AS candidate
            WHERE candidate.id = v_standing_pending.candidate_id;
            IF NOT (
                v_target_w > v_standing_pending.target_ftp_w
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp > v_standing_pending.target_candidate_w
                )
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp = v_standing_pending.target_candidate_w
                    AND v_fitted_cp > COALESCE(v_standing_fitted_cp, 0)
                )
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp = v_standing_pending.target_candidate_w
                    AND v_fitted_cp = v_standing_fitted_cp
                    AND v_candidate_id::TEXT
                        < COALESCE(
                            v_standing_pending.candidate_id::TEXT,
                            'ffffffff-ffff-ffff-ffff-ffffffffffff'
                        )
                )
            ) THEN
                v_disposition := 'superseded';
                v_target_w := NULL;
                v_target_at := NULL;
            ELSE
                v_previous_candidate_id := v_standing_pending.candidate_id;
            END IF;
        END IF;
    END IF;

    v_evidence := pg_catalog.jsonb_build_object(
        'ride_id', p_ride_id,
        'file_hash', lower(btrim(v_ride.file_hash::TEXT)),
        'upload_verified_at', v_ride.upload_verified_at,
        'accepted_at', p_accepted_at,
        'recording_source', v_ride.threshold_recording_source,
        'power_source_id', v_ride.threshold_power_source_id,
        'provenance_tier', v_ride.import_diagnostics->>'provenance_tier',
        'canonical_match', v_ride.canonical_match,
        'source_decision', v_source_decision,
        'best_180s_w', p_best_180s_w,
        'best_420s_w', p_best_420s_w,
        'best_900s_w', p_best_900s_w,
        'model_version', 'threshold_cp_3_7_15_v1',
        'fit_plausibility_policy', 'threshold_fit_plausibility_v1',
        'fit_plausible', v_fit_plausible,
        'rounding', 'ceil_after_raw_deadband'
    );
    INSERT INTO public.reward_threshold_efforts (
        ride_id, user_id, upload_verified_at, evidence_received_at,
        accepted_at, file_hash,
        recording_source, power_source_id, provenance_tier, canonical_match,
        structural_source_eligible, source_decision,
        best_180s_w, best_420s_w, best_900s_w, model_version,
        evidence, evidence_hash
    ) VALUES (
        p_ride_id, v_ride.user_id, v_ride.upload_verified_at, v_received_at,
        p_accepted_at,
        NULLIF(lower(btrim(v_ride.file_hash::TEXT)), ''),
        v_ride.threshold_recording_source, v_ride.threshold_power_source_id,
        v_ride.import_diagnostics->>'provenance_tier', v_ride.canonical_match,
        v_source_eligible, v_source_decision,
        p_best_180s_w, p_best_420s_w, p_best_900s_w,
        'threshold_cp_3_7_15_v1', v_evidence,
        pg_catalog.sha256(pg_catalog.convert_to(v_evidence::TEXT, 'UTF8'))
    ) RETURNING * INTO v_effort;

    INSERT INTO public.reward_threshold_candidates (
        id, effort_id, ride_id, user_id, power_source_id,
        display_best_180s_w, display_best_420s_w, display_best_900s_w,
        display_candidate_w, display_work_capacity_j,
        proposed_best_180s_w, proposed_best_420s_w, proposed_best_900s_w,
        fitted_candidate_w, fitted_work_capacity_j,
        economic_candidate_w, economic_work_capacity_j,
        baseline_authority_id, baseline_ftp_w, target_ftp_w,
        disposition, target_effective_at, superseded_at
    ) VALUES (
        v_candidate_id, v_effort.id, p_ride_id, v_ride.user_id,
        CASE WHEN v_source_eligible
            THEN v_ride.threshold_power_source_id ELSE NULL END,
        v_display_180, v_display_420, v_display_900,
        v_display_cp, v_display_work,
        v_proposed_180, v_proposed_420, v_proposed_900,
        v_fitted_cp, v_fitted_work,
        v_economic_cp, v_economic_work,
        v_baseline_id, v_baseline_w, v_target_w, v_disposition, v_target_at,
        CASE WHEN v_disposition = 'superseded' THEN p_accepted_at ELSE NULL END
    ) RETURNING * INTO v_candidate;

    UPDATE public.reward_threshold_ratchets AS ratchet
    SET display_best_180s_w = v_display_180,
        display_best_420s_w = v_display_420,
        display_best_900s_w = v_display_900,
        display_candidate_w = CASE
            WHEN v_display_cp BETWEEN 50 AND 500
                THEN greatest(ratchet.display_candidate_w, v_display_cp)
            ELSE ratchet.display_candidate_w
        END,
        economic_candidate_w = CASE
            WHEN v_source_eligible AND v_fit_plausible
                THEN greatest(ratchet.economic_candidate_w, v_fitted_cp)
            ELSE ratchet.economic_candidate_w
        END,
        economic_work_capacity_j = CASE
            WHEN v_source_eligible AND v_fit_plausible
                 AND (
                    ratchet.economic_candidate_w IS NULL
                    OR v_fitted_cp > ratchet.economic_candidate_w
                 ) THEN v_fitted_work
            ELSE ratchet.economic_work_capacity_j
        END,
        economic_power_source_id = CASE
            WHEN v_source_eligible AND v_fit_plausible
                 AND (
                    ratchet.economic_candidate_w IS NULL
                    OR v_fitted_cp > ratchet.economic_candidate_w
                 ) THEN v_ride.threshold_power_source_id
            ELSE ratchet.economic_power_source_id
        END,
        updated_at = p_accepted_at
    WHERE ratchet.user_id = v_ride.user_id;

    IF v_source_eligible THEN
        UPDATE public.reward_threshold_source_envelopes AS envelope
        SET accepted_best_180s_w = v_proposed_180,
            accepted_best_420s_w = v_proposed_420,
            accepted_best_900s_w = v_proposed_900,
            accepted_candidate_w = CASE
                WHEN v_fit_plausible
                    THEN greatest(envelope.accepted_candidate_w, v_fitted_cp)
                ELSE envelope.accepted_candidate_w
            END,
            accepted_work_capacity_j = CASE
                WHEN v_fit_plausible
                     AND (
                        envelope.accepted_candidate_w IS NULL
                        OR v_fitted_cp > envelope.accepted_candidate_w
                     ) THEN v_fitted_work
                ELSE envelope.accepted_work_capacity_j
            END,
            last_accepted_candidate_id = CASE
                WHEN v_fit_plausible
                     AND (
                        envelope.accepted_candidate_w IS NULL
                        OR v_fitted_cp > envelope.accepted_candidate_w
                     ) THEN v_candidate.id
                ELSE envelope.last_accepted_candidate_id
            END,
            updated_at = p_accepted_at
        WHERE envelope.user_id = v_ride.user_id
          AND envelope.power_source_id = v_ride.threshold_power_source_id;
    END IF;

    IF v_disposition LIKE 'pending_%' THEN
        INSERT INTO public.reward_threshold_pending_promotions (
            user_id, effective_at, candidate_id, baseline_authority_id,
            promotion_kind, target_candidate_w, target_ftp_w, status, updated_at
        ) VALUES (
            v_ride.user_id, v_target_at, v_candidate.id, v_baseline_id,
            v_promotion_kind, v_economic_cp, v_target_w, 'pending', p_accepted_at
        )
        ON CONFLICT (user_id, effective_at) DO UPDATE
        SET candidate_id = EXCLUDED.candidate_id,
            baseline_authority_id = EXCLUDED.baseline_authority_id,
            promotion_kind = EXCLUDED.promotion_kind,
            target_candidate_w = EXCLUDED.target_candidate_w,
            target_ftp_w = EXCLUDED.target_ftp_w,
            updated_at = EXCLUDED.updated_at
        WHERE public.reward_threshold_pending_promotions.status = 'pending';

        IF v_previous_candidate_id IS NOT NULL
           AND v_previous_candidate_id IS DISTINCT FROM v_candidate.id THEN
            UPDATE public.reward_threshold_candidates AS previous
            SET disposition = 'superseded',
                target_ftp_w = NULL,
                target_effective_at = NULL,
                superseded_at = p_accepted_at
            WHERE previous.id = v_previous_candidate_id;
        END IF;
    END IF;

    SELECT * INTO v_candidate
    FROM public.reward_threshold_candidates AS candidate
    WHERE candidate.id = v_candidate_id;
    RETURN v_candidate;
END;
$$;


REVOKE ALL ON FUNCTION public.reward_threshold_fit_is_plausible(NUMERIC, NUMERIC, NUMERIC)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reward_threshold_commitment_fit_is_plausible(UUID, UUID, NUMERIC)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reward_threshold_authority_fit_is_plausible(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_reward_threshold_fit_on_candidate()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_reward_threshold_fit_on_seal()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_reward_threshold_fit_on_release()
    FROM PUBLIC, anon, authenticated, service_role;
COMMIT;
