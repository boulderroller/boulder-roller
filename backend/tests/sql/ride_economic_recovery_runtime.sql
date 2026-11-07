\set ON_ERROR_STOP on

CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.users (id UUID PRIMARY KEY);
CREATE TABLE public.rides (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE
);
CREATE TABLE public.vault_completions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    wallet TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    time_seconds BIGINT,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    validated BOOLEAN DEFAULT true,
    validation_override BOOLEAN DEFAULT false,
    validation_notes TEXT,
    cal_tribute NUMERIC NOT NULL DEFAULT 0,
    best_time_seconds BIGINT,
    best_time_achieved_at TIMESTAMPTZ,
    total_completions INTEGER DEFAULT 1,
    on_chain_tx TEXT,
    on_chain_tx_error TEXT,
    UNIQUE (vault_signature, activity_id)
);

CREATE OR REPLACE FUNCTION public.increment_vault_completions(TEXT)
RETURNS VOID LANGUAGE sql AS $$ SELECT $$;

\ir ../../supabase/migrations/20260713_121_ride_economic_recovery.sql
\ir ../../supabase/migrations/20260715_136_completion_projection_ownership.sql

DO $$
DECLARE
    v_ride UUID := '10000000-0000-0000-0000-000000000001';
    v_user UUID := '20000000-0000-0000-0000-000000000001';
    v_lease UUID := '30000000-0000-0000-0000-000000000001';
    v_plan JSONB;
BEGIN
    INSERT INTO public.users VALUES (v_user);
    INSERT INTO public.rides VALUES (v_ride, v_user);
    v_plan := jsonb_build_object(
        'ride_id', v_ride,
        'user_id', v_user,
        'wallet', 'wallet-complete',
        'ride_hash_hex', repeat('11', 32),
        'attestation_commitment_hex', repeat('22', 32),
        'parser_version', 7,
        'policy_version', 'policy-v1',
        'reward_policy', 'rewardable',
        'source_kind', 1,
        'started_at', '2026-07-13T12:00:00Z',
        'completed_at', '2026-07-13T13:00:00Z',
        'total_tss', 84,
        'total_distance_m', 12000,
        'total_vert_m', 300,
        'exact_cal_base_units', 0,
        'climbs_crossed', 0,
        'exact_tribute_base_units', 0,
        'plan_evidence_hash_hex', repeat('33', 32),
        'expected_attestation_pda', 'attestation-complete',
        'expected_cal_receipt_pda', 'cal-complete'
    );
    PERFORM public.freeze_ride_economic_plan(v_plan, '[]'::JSONB);
    PERFORM public.acquire_ride_economic_plan(v_ride, v_lease, 300);
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'planned', 'attestation_confirmed',
        jsonb_build_object('attestation_confirmed_at', now())
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'attestation_confirmed', 'completions_confirmed'
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'completions_confirmed', 'cal_confirmed',
        jsonb_build_object('cal_confirmed_at', now())
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'cal_confirmed', 'projections_reconciled'
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'projections_reconciled', 'complete'
    );

    PERFORM public.freeze_ride_economic_plan(
        v_plan || jsonb_build_object('plan_evidence_hash_hex', repeat('44', 32)),
        '[]'::JSONB
    );
    IF (SELECT state FROM public.ride_economic_plans WHERE ride_id = v_ride)
        <> 'complete' THEN
        RAISE EXCEPTION 'completed plan was demoted by mismatch replay';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.ride_economic_plan_audits
        WHERE ride_id = v_ride
          AND event_type = 'completed_plan_evidence_mismatch'
    ) THEN
        RAISE EXCEPTION 'completed mismatch audit was not retained';
    END IF;

    DELETE FROM public.users WHERE id = v_user;
    IF NOT EXISTS (
        SELECT 1 FROM public.ride_economic_plans WHERE ride_id = v_ride
    ) THEN
        RAISE EXCEPTION 'source deletion erased completed economic evidence';
    END IF;
END;
$$;

DO $$
DECLARE
    v_ride UUID := '10000000-0000-0000-0000-000000000002';
    v_user UUID := '20000000-0000-0000-0000-000000000002';
    v_lease UUID := '30000000-0000-0000-0000-000000000002';
BEGIN
    INSERT INTO public.users VALUES (v_user);
    INSERT INTO public.rides VALUES (v_ride, v_user);
    PERFORM public.freeze_ride_economic_plan(
        jsonb_build_object(
            'ride_id', v_ride,
            'user_id', v_user,
            'wallet', 'wallet-partial',
            'ride_hash_hex', repeat('55', 32),
            'attestation_commitment_hex', repeat('66', 32),
            'parser_version', 7,
            'policy_version', 'policy-v1',
            'reward_policy', 'rewardable',
            'source_kind', 1,
            'started_at', '2026-07-13T12:00:00Z',
            'completed_at', '2026-07-13T13:00:00Z',
            'total_tss', 84,
            'total_distance_m', 12000,
            'total_vert_m', 300,
            'exact_cal_base_units', 0,
            'climbs_crossed', 0,
            'exact_tribute_base_units', 0,
            'plan_evidence_hash_hex', repeat('77', 32),
            'expected_attestation_pda', 'attestation-partial',
            'expected_cal_receipt_pda', 'cal-partial'
        ),
        '[]'::JSONB
    );
    PERFORM public.acquire_ride_economic_plan(v_ride, v_lease, 300);
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'planned', 'attestation_confirmed',
        jsonb_build_object('attestation_confirmed_at', now())
    );
    DELETE FROM public.users WHERE id = v_user;
    IF (SELECT state FROM public.ride_economic_plans WHERE ride_id = v_ride)
        <> 'attestation_confirmed' THEN
        RAISE EXCEPTION 'source deletion erased or stranded partial recovery';
    END IF;
END;
$$;

DO $$
DECLARE
    v_ride UUID := '10000000-0000-0000-0000-000000000003';
    v_user UUID := '20000000-0000-0000-0000-000000000003';
    v_lease UUID := '30000000-0000-0000-0000-000000000003';
BEGIN
    INSERT INTO public.users VALUES (v_user);
    INSERT INTO public.rides VALUES (v_ride, v_user);
    PERFORM public.freeze_ride_economic_plan(
        jsonb_build_object(
            'ride_id', v_ride,
            'user_id', v_user,
            'wallet', 'wallet-conflict',
            'ride_hash_hex', repeat('88', 32),
            'attestation_commitment_hex', repeat('99', 32),
            'parser_version', 7,
            'policy_version', 'policy-v1',
            'reward_policy', 'rewardable',
            'source_kind', 1,
            'started_at', '2026-07-13T12:00:00Z',
            'completed_at', '2026-07-13T13:00:00Z',
            'total_tss', 84,
            'total_distance_m', 12000,
            'total_vert_m', 300,
            'exact_cal_base_units', 0,
            'climbs_crossed', 1,
            'exact_tribute_base_units', 11,
            'plan_evidence_hash_hex', repeat('aa', 32),
            'expected_attestation_pda', 'attestation-conflict',
            'expected_cal_receipt_pda', 'cal-conflict'
        ),
        jsonb_build_array(jsonb_build_object(
            'step_index', 0,
            'pattern_id', '40000000-0000-0000-0000-000000000003',
            'vault_id', 9,
            'vault_signature', 'vault-9',
            'completion_time_s', 321,
            'completed_at', '2026-07-13T13:00:00Z',
            'exact_tribute_base_units', 11,
            'intensity_bps', 10000,
            'climb_distance_m', NULL,
            'climb_vert_m', NULL,
            'completion_evidence_hash_hex', repeat('bb', 32),
            'expected_receipt_pda', 'receipt-9'
        ))
    );
    PERFORM public.acquire_ride_economic_plan(v_ride, v_lease, 300);
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'planned', 'attestation_confirmed',
        jsonb_build_object('attestation_confirmed_at', now())
    );
    PERFORM public.confirm_ride_economic_completion(
        v_ride, v_lease, 0, 'receipt-9', NULL, now()
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'attestation_confirmed', 'completions_confirmed'
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'completions_confirmed', 'cal_confirmed',
        jsonb_build_object('cal_confirmed_at', now())
    );

    INSERT INTO public.vault_completions (
        vault_signature, wallet, activity_id, time_seconds, completed_at,
        validated, validation_override, on_chain_tx
    ) VALUES (
        'vault-9', 'legacy-wallet', v_ride::TEXT, 999, now(),
        true, true, 'arbitrary-legacy-transaction'
    );
    IF (SELECT validated FROM public.vault_completions
        WHERE activity_id = v_ride::TEXT) THEN
        RAISE EXCEPTION 'legacy completion remained validated';
    END IF;

    PERFORM public.reconcile_confirmed_vault_completion(v_ride, v_lease, 0);
    IF (SELECT on_chain_tx FROM public.vault_completions
        WHERE activity_id = v_ride::TEXT) IS NOT NULL THEN
        RAISE EXCEPTION 'account-only reconciliation retained legacy tx text';
    END IF;
    PERFORM public.mark_ride_economic_completion_projected(v_ride, v_lease, 0);
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'cal_confirmed', 'projections_reconciled'
    );
    PERFORM public.advance_ride_economic_plan(
        v_ride, v_lease, 'projections_reconciled', 'complete'
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.confirmed_vault_completion_candidates
        WHERE activity_id = v_ride::TEXT AND on_chain_tx IS NULL
    ) THEN
        RAISE EXCEPTION 'account-only confirmed candidate was not projected';
    END IF;
END;
$$;

DO $$
DECLARE
    v_candidates JSONB;
BEGIN
    v_candidates := public.get_confirmed_local_legend_candidates(
        9,
        TIMESTAMPTZ '2000-01-01T00:00:00Z',
        TIMESTAMPTZ '2100-01-01T00:00:00Z'
    );
    IF v_candidates->>'authoritative' <> 'true'
       OR (v_candidates->>'confirmed_receipt_count')::BIGINT <> 1
       OR (v_candidates->>'wallet_count')::BIGINT <> 1
       OR (v_candidates->'candidates'->0->>'completion_count')::BIGINT <> 1 THEN
        RAISE EXCEPTION 'confirmed Local Legend aggregate was incomplete';
    END IF;
END;
$$;

DO $$
DECLARE
    v_base JSONB := jsonb_build_object(
        'ride_id', '10000000-0000-0000-0000-000000000004',
        'user_id', '20000000-0000-0000-0000-000000000004',
        'wallet', 'wallet-boundary',
        'ride_hash_hex', repeat('cc', 32),
        'attestation_commitment_hex', repeat('dd', 32),
        'parser_version', 4294967295,
        'policy_version', 'policy-v1',
        'reward_policy', 'rewardable',
        'source_kind', 255,
        'started_at', '2026-07-13T12:00:00Z',
        'completed_at', '2026-07-13T13:00:00Z',
        'total_tss', 4294967295,
        'total_distance_m', 4294967295,
        'total_vert_m', 4294967295,
        'exact_cal_base_units', 18446744073709551615,
        'climbs_crossed', 65535,
        'exact_tribute_base_units', 0,
        'plan_evidence_hash_hex', repeat('ee', 32),
        'expected_attestation_pda', 'attestation-boundary',
        'expected_cal_receipt_pda', 'cal-boundary'
    );
BEGIN
    PERFORM public.freeze_ride_economic_plan(v_base, '[]'::JSONB);

    BEGIN
        PERFORM public.freeze_ride_economic_plan(
            v_base
                || jsonb_build_object(
                    'ride_id', '10000000-0000-0000-0000-000000000005',
                    'plan_evidence_hash_hex', repeat('ef', 32),
                    'exact_cal_base_units', 18446744073709551616
                ),
            '[]'::JSONB
        );
        RAISE EXCEPTION 'expected u64 overflow rejection';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'expected u64 overflow rejection'
           OR SQLERRM NOT LIKE '%exceeds protocol maximum%' THEN
            RAISE;
        END IF;
    END;

    BEGIN
        PERFORM public.freeze_ride_economic_plan(
            v_base
                || jsonb_build_object(
                    'ride_id', '10000000-0000-0000-0000-000000000006',
                    'plan_evidence_hash_hex', repeat('f0', 32),
                    'total_tss', 84.5
                ),
            '[]'::JSONB
        );
        RAISE EXCEPTION 'expected fractional rejection';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'expected fractional rejection'
           OR SQLERRM NOT LIKE '%unsigned decimal digits%' THEN
            RAISE;
        END IF;
    END;
END;
$$;

SELECT 'ride_economic_recovery_runtime_ok' AS result;
