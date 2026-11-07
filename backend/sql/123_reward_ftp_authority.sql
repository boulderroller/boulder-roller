-- Immutable reward FTP authority and ride-time economic TSS provenance.
--
-- Rider profile FTP remains mutable training/display data. Rewardable TSS uses
-- either the neutral 200 W network default or an append-only service-verified
-- authority effective when the activity started. Historical rows stay NULL.

CREATE TABLE IF NOT EXISTS public.reward_ftp_authorities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id),
    ftp_w INTEGER NOT NULL CHECK (ftp_w BETWEEN 50 AND 500),
    source TEXT NOT NULL CHECK (
        source IN ('operator_verified', 'trusted_provider', 'verified_power_test')
    ),
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB
        CHECK (jsonb_typeof(evidence) = 'object'),
    evidence_hash BYTEA NOT NULL CHECK (octet_length(evidence_hash) = 32),
    verified_by TEXT NOT NULL CHECK (btrim(verified_by) <> ''),
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    effective_at TIMESTAMPTZ NOT NULL,
    supersedes_id UUID REFERENCES public.reward_ftp_authorities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, effective_at)
);

CREATE INDEX IF NOT EXISTS idx_reward_ftp_authorities_effective
    ON public.reward_ftp_authorities(user_id, effective_at DESC, verified_at DESC);

ALTER TABLE public.reward_ftp_authorities ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.reward_ftp_authorities FROM anon, authenticated;
REVOKE ALL ON public.reward_ftp_authorities FROM service_role;
GRANT SELECT ON public.reward_ftp_authorities TO service_role;

CREATE OR REPLACE FUNCTION public.prevent_reward_ftp_authority_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    RAISE EXCEPTION 'reward FTP authorities are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_reward_ftp_authorities_immutable
    ON public.reward_ftp_authorities;
CREATE TRIGGER trg_reward_ftp_authorities_immutable
    BEFORE UPDATE OR DELETE ON public.reward_ftp_authorities
    FOR EACH ROW EXECUTE FUNCTION public.prevent_reward_ftp_authority_mutation();

CREATE OR REPLACE FUNCTION public.register_reward_ftp_authority(
    p_user_id UUID,
    p_ftp_w INTEGER,
    p_source TEXT,
    p_evidence JSONB,
    p_verified_by TEXT,
    p_effective_at TIMESTAMPTZ DEFAULT NULL
) RETURNS public.reward_ftp_authorities
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
    v_this_monday TIMESTAMPTZ := (
        date_trunc('week', v_now AT TIME ZONE 'UTC')
        + INTERVAL '12 hours'
    ) AT TIME ZONE 'UTC';
    v_next_monday TIMESTAMPTZ := CASE
        WHEN v_now < v_this_monday THEN v_this_monday
        ELSE v_this_monday + INTERVAL '1 week'
    END;
    v_effective_at TIMESTAMPTZ;
    v_supersedes_id UUID;
    v_row public.reward_ftp_authorities%ROWTYPE;
BEGIN
    IF p_ftp_w NOT BETWEEN 50 AND 500 THEN
        RAISE EXCEPTION 'reward FTP must be between 50 and 500 watts';
    END IF;
    IF p_source NOT IN (
        'operator_verified', 'trusted_provider', 'verified_power_test'
    ) THEN
        RAISE EXCEPTION 'unsupported verified reward FTP source: %', p_source;
    END IF;
    IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN
        RAISE EXCEPTION 'reward FTP evidence must be a JSON object';
    END IF;
    IF btrim(COALESCE(p_verified_by, '')) = '' THEN
        RAISE EXCEPTION 'reward FTP verifier is required';
    END IF;

    v_effective_at := COALESCE(p_effective_at, v_next_monday);
    IF v_effective_at < v_next_monday THEN
        RAISE EXCEPTION
            'reward FTP changes cannot activate before next Monday 12:00 UTC: %',
            v_next_monday;
    END IF;
    IF v_effective_at IS DISTINCT FROM (
        date_trunc('week', v_effective_at AT TIME ZONE 'UTC')
        + INTERVAL '12 hours'
    ) AT TIME ZONE 'UTC' THEN
        RAISE EXCEPTION 'reward FTP changes must activate Monday 12:00 UTC';
    END IF;

    SELECT authority.id INTO v_supersedes_id
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = p_user_id
    ORDER BY authority.effective_at DESC, authority.verified_at DESC, authority.id DESC
    LIMIT 1;

    INSERT INTO public.reward_ftp_authorities (
        user_id, ftp_w, source, evidence, evidence_hash, verified_by,
        effective_at, supersedes_id
    ) VALUES (
        p_user_id,
        p_ftp_w,
        p_source,
        p_evidence,
        pg_catalog.sha256(pg_catalog.convert_to(p_evidence::TEXT, 'UTF8')),
        p_verified_by,
        v_effective_at,
        v_supersedes_id
    ) RETURNING * INTO v_row;

    RETURN v_row;
END;
$$;

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS economic_tss NUMERIC,
    ADD COLUMN IF NOT EXISTS reward_ftp_w INTEGER,
    ADD COLUMN IF NOT EXISTS reward_ftp_source TEXT,
    ADD COLUMN IF NOT EXISTS reward_ftp_authority_id UUID
        REFERENCES public.reward_ftp_authorities(id),
    ADD COLUMN IF NOT EXISTS reward_ftp_policy_version TEXT,
    ADD COLUMN IF NOT EXISTS reward_ftp_activity_started_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_economic_tss_nonnegative'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_economic_tss_nonnegative
            CHECK (economic_tss IS NULL OR economic_tss >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_reward_ftp_w_range'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_reward_ftp_w_range
            CHECK (reward_ftp_w IS NULL OR reward_ftp_w BETWEEN 50 AND 500);
    END IF;
END;
$$;

COMMENT ON COLUMN public.rides.economic_tss IS
    'Rewardable TSS computed from the immutable reward FTP snapshot; display tss remains profile-derived.';
COMMENT ON COLUMN public.rides.reward_ftp_w IS
    'Immutable FTP denominator used for economic_tss and CAL.';
COMMENT ON COLUMN public.rides.reward_ftp_source IS
    'network_default or the service-verified authority source used for this ride.';
COMMENT ON COLUMN public.rides.reward_ftp_authority_id IS
    'Append-only verified authority row; NULL only for the neutral network default.';
COMMENT ON COLUMN public.rides.reward_ftp_policy_version IS
    'Versioned reward FTP selection policy committed by the frozen economic plan.';
COMMENT ON COLUMN public.rides.reward_ftp_activity_started_at IS
    'Parsed activity start used to resolve the effective reward FTP version.';

CREATE OR REPLACE FUNCTION public.enforce_ride_reward_ftp_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.reward_ftp_w IS NOT NULL AND (
            NEW.reward_ftp_w IS DISTINCT FROM OLD.reward_ftp_w
            OR NEW.reward_ftp_source IS DISTINCT FROM OLD.reward_ftp_source
            OR NEW.reward_ftp_authority_id IS DISTINCT FROM OLD.reward_ftp_authority_id
            OR NEW.reward_ftp_policy_version IS DISTINCT FROM OLD.reward_ftp_policy_version
            OR NEW.reward_ftp_activity_started_at IS DISTINCT FROM OLD.reward_ftp_activity_started_at
        ) THEN
            RAISE EXCEPTION 'ride reward FTP snapshot is immutable';
        END IF;
        IF OLD.economic_tss IS NOT NULL
           AND NEW.economic_tss IS DISTINCT FROM OLD.economic_tss THEN
            RAISE EXCEPTION 'ride economic TSS snapshot is immutable';
        END IF;
    END IF;

    IF NEW.reward_ftp_w IS NULL THEN
        IF NEW.reward_ftp_source IS NOT NULL
           OR NEW.reward_ftp_authority_id IS NOT NULL
           OR NEW.reward_ftp_policy_version IS NOT NULL
           OR NEW.reward_ftp_activity_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'partial ride reward FTP snapshot is forbidden';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reward_ftp_w NOT BETWEEN 50 AND 500
       OR NEW.reward_ftp_policy_version IS DISTINCT FROM
          'reward_ftp_policy_2026_07_14'
       OR NEW.reward_ftp_activity_started_at IS NULL THEN
        RAISE EXCEPTION 'invalid ride reward FTP snapshot';
    END IF;

    IF NEW.reward_ftp_source = 'network_default' THEN
        IF NEW.reward_ftp_w <> 200 OR NEW.reward_ftp_authority_id IS NOT NULL THEN
            RAISE EXCEPTION 'inconsistent network-default reward FTP snapshot';
        END IF;
    ELSIF NOT EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.id = NEW.reward_ftp_authority_id
          AND authority.user_id = NEW.user_id
          AND authority.ftp_w = NEW.reward_ftp_w
          AND authority.source = NEW.reward_ftp_source
          AND authority.effective_at <= NEW.reward_ftp_activity_started_at
    ) THEN
        RAISE EXCEPTION 'ride reward FTP snapshot lacks matching verified authority';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_rides_reward_ftp_immutable ON public.rides;
CREATE TRIGGER trg_rides_reward_ftp_immutable
    BEFORE INSERT OR UPDATE ON public.rides
    FOR EACH ROW EXECUTE FUNCTION public.enforce_ride_reward_ftp_snapshot();

CREATE OR REPLACE FUNCTION public.bind_ride_reward_ftp(
    p_ride_id UUID,
    p_activity_started_at TIMESTAMPTZ DEFAULT NULL
) RETURNS TABLE (
    reward_ftp_w INTEGER,
    reward_ftp_source TEXT,
    reward_ftp_authority_id UUID,
    reward_ftp_policy_version TEXT,
    reward_ftp_activity_started_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride public.rides%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_activity_started_at TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_ride
    FROM public.rides AS ride
    WHERE ride.id = p_ride_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'ride not found for reward FTP binding: %', p_ride_id;
    END IF;

    IF v_ride.reward_ftp_w IS NOT NULL THEN
        RETURN QUERY
        SELECT ride.reward_ftp_w, ride.reward_ftp_source,
               ride.reward_ftp_authority_id, ride.reward_ftp_policy_version,
               ride.reward_ftp_activity_started_at
        FROM public.rides AS ride
        WHERE ride.id = p_ride_id;
        RETURN;
    END IF;

    v_activity_started_at := COALESCE(p_activity_started_at, clock_timestamp());
    SELECT authority.* INTO v_authority
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id
      AND authority.effective_at <= v_activity_started_at
    ORDER BY authority.effective_at DESC, authority.verified_at DESC, authority.id DESC
    LIMIT 1;

    UPDATE public.rides AS ride
    SET reward_ftp_w = CASE WHEN FOUND THEN v_authority.ftp_w ELSE 200 END,
        reward_ftp_source = CASE
            WHEN FOUND THEN v_authority.source ELSE 'network_default'
        END,
        reward_ftp_authority_id = CASE WHEN FOUND THEN v_authority.id ELSE NULL END,
        reward_ftp_policy_version = 'reward_ftp_policy_2026_07_14',
        reward_ftp_activity_started_at = v_activity_started_at
    WHERE ride.id = p_ride_id;

    RETURN QUERY
    SELECT ride.reward_ftp_w, ride.reward_ftp_source,
           ride.reward_ftp_authority_id, ride.reward_ftp_policy_version,
           ride.reward_ftp_activity_started_at
    FROM public.rides AS ride
    WHERE ride.id = p_ride_id;
END;
$$;

ALTER TABLE IF EXISTS public.user_profile_snapshots
    ADD COLUMN IF NOT EXISTS reward_ftp_w INTEGER,
    ADD COLUMN IF NOT EXISTS reward_ftp_source TEXT,
    ADD COLUMN IF NOT EXISTS reward_ftp_authority_id UUID
        REFERENCES public.reward_ftp_authorities(id),
    ADD COLUMN IF NOT EXISTS reward_ftp_policy_version TEXT;

ALTER TABLE public.ride_economic_plans
    ADD COLUMN IF NOT EXISTS reward_ftp_w INTEGER,
    ADD COLUMN IF NOT EXISTS reward_ftp_source TEXT,
    ADD COLUMN IF NOT EXISTS reward_ftp_authority_id UUID
        REFERENCES public.reward_ftp_authorities(id),
    ADD COLUMN IF NOT EXISTS reward_ftp_policy_version TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_plans'::regclass
          AND conname = 'ride_economic_plans_reward_ftp_w_range'
    ) THEN
        ALTER TABLE public.ride_economic_plans
            ADD CONSTRAINT ride_economic_plans_reward_ftp_w_range
            CHECK (reward_ftp_w IS NULL OR reward_ftp_w BETWEEN 50 AND 500);
    END IF;
END;
$$;

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

    -- The renamed V1 freezer inserts NULLs; the wrapper below fills them in the
    -- same transaction. Historical plans remain NULL and are never backfilled.
    IF NEW.reward_ftp_w IS NULL THEN
        IF NEW.reward_ftp_source IS NOT NULL
           OR NEW.reward_ftp_authority_id IS NOT NULL
           OR NEW.reward_ftp_policy_version IS NOT NULL THEN
            RAISE EXCEPTION 'partial plan reward FTP snapshot is forbidden';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reward_ftp_w NOT BETWEEN 50 AND 500
       OR NEW.reward_ftp_policy_version IS DISTINCT FROM
          'reward_ftp_policy_2026_07_14' THEN
        RAISE EXCEPTION 'invalid frozen plan reward FTP snapshot';
    END IF;
    IF NEW.reward_ftp_source = 'network_default' THEN
        IF NEW.reward_ftp_w <> 200 OR NEW.reward_ftp_authority_id IS NOT NULL THEN
            RAISE EXCEPTION 'inconsistent plan network-default reward FTP';
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
          AND trunc(ride.economic_tss)::BIGINT = NEW.total_tss
    ) THEN
        RAISE EXCEPTION
            'frozen plan reward FTP or economic TSS differs from ride snapshot';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ride_economic_plan_reward_ftp
    ON public.ride_economic_plans;
CREATE TRIGGER trg_ride_economic_plan_reward_ftp
    BEFORE INSERT OR UPDATE ON public.ride_economic_plans
    FOR EACH ROW EXECUTE FUNCTION public.enforce_plan_reward_ftp_snapshot();

DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_ride_economic_plan_without_reward_ftp(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_without_reward_ftp;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_without_reward_ftp(JSONB, JSONB)
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
    v_plan public.ride_economic_plans%ROWTYPE;
BEGIN
    PERFORM public.freeze_ride_economic_plan_without_reward_ftp(p_plan, p_steps);
    SELECT * INTO v_plan
    FROM public.ride_economic_plans AS plan
    WHERE plan.ride_id = v_ride_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ride economic plan was not persisted';
    END IF;
    IF v_plan.reward_ftp_w IS NOT NULL
       OR v_plan.policy_version IS DISTINCT FROM
          'ride_effort_policy_2026_07_14_ftp_v1'
       OR encode(v_plan.plan_evidence_hash, 'hex') IS DISTINCT FROM
          lower(p_plan->>'plan_evidence_hash_hex') THEN
        RETURN public.get_ride_economic_plan(v_ride_id);
    END IF;

    UPDATE public.ride_economic_plans AS plan
    SET reward_ftp_w = public.require_ride_economic_uint(
            p_plan->'reward_ftp_w', 'reward_ftp_w', 65535
        )::INTEGER,
        reward_ftp_source = p_plan->>'reward_ftp_source',
        reward_ftp_authority_id = NULLIF(
            p_plan->>'reward_ftp_authority_id', ''
        )::UUID,
        reward_ftp_policy_version = p_plan->>'reward_ftp_policy_version'
    WHERE plan.ride_id = v_ride_id;

    RETURN public.get_ride_economic_plan(v_ride_id);
END;
$$;

DO $$
DECLARE
    v_template public.pipeline_versions%ROWTYPE;
    v_existing public.pipeline_versions%ROWTYPE;
    v_ftp_id INTEGER;
BEGIN
    SELECT * INTO v_existing
    FROM public.pipeline_versions
    WHERE parser_version = '3-ftp-v1'
       OR policy_version = 'ride_effort_policy_2026_07_14_ftp_v1'
    ORDER BY id DESC
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.parser_version IS DISTINCT FROM '3-ftp-v1'
           OR v_existing.ride_parser_version IS DISTINCT FROM 3
           OR v_existing.policy_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR v_existing.economics_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR btrim(v_existing.git_commit) IS DISTINCT FROM
              '9f97a5a92c3987d7d36b617cb01dde50f46f94e4' THEN
            RAISE EXCEPTION 'reward FTP pipeline provenance conflict';
        END IF;
        IF v_existing.deactivated_at IS NOT NULL THEN
            RAISE EXCEPTION 'reward FTP pipeline version is inactive';
        END IF;
        v_ftp_id := v_existing.id;
    ELSE
        SELECT * INTO v_template
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY activated_at DESC, id DESC
        LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'cannot register reward FTP policy without active template';
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
            '3-ftp-v1', v_template.detector_algorithm, v_template.detector_version,
            v_template.detector_params_hash, v_template.sig_format_version,
            v_template.sig_match_version,
            'ride_effort_policy_2026_07_14_ftp_v1',
            v_template.integrity_version,
            '9f97a5a92c3987d7d36b617cb01dde50f46f94e4',
            now(), NULL,
            'Parser V3 metrics with immutable ride-time reward FTP authority and economic TSS.',
            3, 'ride_effort_policy_2026_07_14_ftp_v1'
        ) RETURNING id INTO v_ftp_id;
    END IF;

    UPDATE public.pipeline_versions
    SET deactivated_at = now()
    WHERE deactivated_at IS NULL AND id <> v_ftp_id;
END;
$$;

REVOKE ALL ON FUNCTION public.register_reward_ftp_authority(
    UUID, INTEGER, TEXT, JSONB, TEXT, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.bind_ride_reward_ftp(
    UUID, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(
    JSONB, JSONB
) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.register_reward_ftp_authority(
    UUID, INTEGER, TEXT, JSONB, TEXT, TIMESTAMPTZ
) TO service_role;
GRANT EXECUTE ON FUNCTION public.bind_ride_reward_ftp(
    UUID, TIMESTAMPTZ
) TO service_role;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(
    JSONB, JSONB
) TO service_role;
