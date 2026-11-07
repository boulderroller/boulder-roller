-- Tim 2026-09-25: first admitted buckets win permanently. Price only new seconds.
BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions;
SET LOCAL search_path = public, extensions, pg_catalog;

CREATE TABLE IF NOT EXISTS public.ride_effort_admission_locks (
    user_id UUID PRIMARY KEY,
    revision BIGINT NOT NULL DEFAULT 0
);
ALTER TABLE public.ride_effort_admission_locks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ride_effort_admission_locks
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.ride_effort_spans_from_ms(p_spans JSONB)
RETURNS TSTZMULTIRANGE
LANGUAGE plpgsql
IMMUTABLE
SET search_path = ''
AS $$
DECLARE
    v_part JSONB;
    v_result TSTZMULTIRANGE := '{}';
    v_start BIGINT;
    v_end BIGINT;
BEGIN
    IF jsonb_typeof(p_spans) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'effort spans must be an array';
    END IF;
    FOR v_part IN SELECT value FROM jsonb_array_elements(p_spans) LOOP
        IF jsonb_typeof(v_part) <> 'array'
           OR jsonb_array_length(v_part) <> 2
           OR jsonb_typeof(v_part->0) <> 'number'
           OR jsonb_typeof(v_part->1) <> 'number'
           OR (v_part->>0) !~ '^-?[0-9]+$'
           OR (v_part->>1) !~ '^-?[0-9]+$' THEN
            RAISE EXCEPTION 'effort endpoints must be integer milliseconds';
        END IF;
        v_start := (v_part->>0)::BIGINT;
        v_end := (v_part->>1)::BIGINT;
        IF v_start >= v_end THEN
            RAISE EXCEPTION 'effort span must have positive length';
        END IF;
        v_result := v_result + tstzmultirange(tstzrange(
            'epoch'::TIMESTAMPTZ + v_start * INTERVAL '1 millisecond',
            'epoch'::TIMESTAMPTZ + v_end * INTERVAL '1 millisecond',
            '[)'
        ));
    END LOOP;
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.ride_effort_spans_to_ms(p_spans TSTZMULTIRANGE)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT coalesce(jsonb_agg(jsonb_build_array(
        (extract(epoch FROM lower(r)) * 1000)::BIGINT,
        (extract(epoch FROM upper(r)) * 1000)::BIGINT
    ) ORDER BY lower(r)), '[]'::JSONB)
    FROM unnest(p_spans) AS r;
$$;

ALTER TABLE public.ride_economic_plans
    ADD COLUMN IF NOT EXISTS effort_spans TSTZMULTIRANGE,
    ADD COLUMN IF NOT EXISTS paid_spans TSTZMULTIRANGE,
    ADD COLUMN IF NOT EXISTS covered_spans TSTZMULTIRANGE;

-- This transaction changes only spans on legacy rows. Pre-155 economics must
-- not be revalidated against the newer network-default admission rule.
ALTER TABLE public.ride_economic_plans
    DISABLE TRIGGER trg_ride_economic_plan_reward_ftp;
DO $$
DECLARE
    v_row RECORD;
    v_effort TSTZMULTIRANGE;
    v_covered TSTZMULTIRANGE;
BEGIN
    FOR v_row IN
        SELECT *
        FROM public.ride_economic_plans
        WHERE paid_spans IS NULL
        ORDER BY user_id, created_at, ride_id
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM public.rides
            WHERE id = v_row.ride_id AND user_id = v_row.user_id
        ) THEN
            RAISE EXCEPTION 'legacy effort backfill missing ride %', v_row.ride_id;
        END IF;
        v_effort := tstzmultirange(tstzrange(
            v_row.started_at, v_row.completed_at, '[)'
        ));
        SELECT coalesce(range_agg(paid_spans), '{}')
        INTO v_covered
        FROM public.ride_economic_plans
        WHERE user_id = v_row.user_id AND paid_spans IS NOT NULL;

        -- Legacy pricing was whole-file, even where an earlier envelope wins.
        -- As at a live freeze, only a hold or a plan that paid CAL claims its
        -- seconds; a zero-value plan leaves them open to a later file.
        UPDATE public.ride_economic_plans
        SET effort_spans = v_effort,
            paid_spans = CASE
                WHEN v_row.reward_policy = 'threshold_provisional_hold_v1'
                     OR v_row.exact_cal_base_units > 0
                THEN v_effort - v_covered
                ELSE '{}'
            END,
            covered_spans = '{}'
        WHERE ride_id = v_row.ride_id;
    END LOOP;
END;
$$;
ALTER TABLE public.ride_economic_plans
    ENABLE TRIGGER trg_ride_economic_plan_reward_ftp;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_plans'::REGCLASS
          AND conname = 'ride_economic_plans_paid_within_effort'
    ) THEN
        ALTER TABLE public.ride_economic_plans
            ADD CONSTRAINT ride_economic_plans_paid_within_effort
            CHECK (paid_spans IS NULL OR effort_spans IS NULL OR paid_spans <@ effort_spans);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.ride_economic_plans'::REGCLASS
          AND conname = 'ride_economic_plans_paid_spans_exclusive'
    ) THEN
        ALTER TABLE public.ride_economic_plans
            ADD CONSTRAINT ride_economic_plans_paid_spans_exclusive
            EXCLUDE USING gist (user_id WITH =, paid_spans WITH &&);
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_enforce_effort_trim_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF (OLD.effort_spans IS NOT NULL AND OLD.effort_spans IS DISTINCT FROM NEW.effort_spans)
       OR (OLD.paid_spans IS NOT NULL AND OLD.paid_spans IS DISTINCT FROM NEW.paid_spans)
       OR (OLD.covered_spans IS NOT NULL AND OLD.covered_spans IS DISTINCT FROM NEW.covered_spans) THEN
        RAISE EXCEPTION 'frozen effort spans cannot change';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS br_enforce_effort_trim_immutability ON public.ride_economic_plans;
CREATE TRIGGER br_enforce_effort_trim_immutability
    BEFORE UPDATE ON public.ride_economic_plans
    FOR EACH ROW EXECUTE FUNCTION public.br_enforce_effort_trim_immutability();

CREATE OR REPLACE FUNCTION public.br_require_effort_trim_presence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.ride_economic_plans
        WHERE ride_id = NEW.ride_id
          AND (effort_spans IS NULL OR paid_spans IS NULL OR covered_spans IS NULL)
    ) THEN
        RAISE EXCEPTION 'frozen effort spans required';
    END IF;
    RETURN NULL;
END;
$$;
DROP TRIGGER IF EXISTS br_require_effort_trim_presence ON public.ride_economic_plans;
CREATE CONSTRAINT TRIGGER br_require_effort_trim_presence
    AFTER INSERT ON public.ride_economic_plans
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION public.br_require_effort_trim_presence();

CREATE TABLE IF NOT EXISTS public.ride_effort_completion_windows (
    ride_id UUID NOT NULL REFERENCES public.ride_economic_plans(ride_id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    vault_id NUMERIC(20,0) NOT NULL CHECK (vault_id >= 0 AND vault_id <= 18446744073709551615),
    completion_window TSTZRANGE NOT NULL CHECK (
        NOT isempty(completion_window)
        AND NOT lower_inf(completion_window)
        AND NOT upper_inf(completion_window)
    ),
    PRIMARY KEY (ride_id, vault_id),
    EXCLUDE USING gist (user_id WITH =, vault_id WITH =, completion_window WITH &&)
);
ALTER TABLE public.ride_effort_completion_windows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ride_effort_completion_windows
    FROM PUBLIC, anon, authenticated, service_role;

INSERT INTO public.ride_effort_completion_windows
SELECT p.ride_id, p.user_id, s.vault_id, tstzrange(
    p.started_at + s.segment_start_offset_s * INTERVAL '1 second',
    p.started_at + (s.segment_end_offset_s + 1) * INTERVAL '1 second',
    '[)'
)
FROM public.ride_economic_plans AS p
JOIN public.ride_economic_completion_steps AS s USING (ride_id)
WHERE s.segment_start_offset_s IS NOT NULL AND s.segment_end_offset_s IS NOT NULL
ORDER BY p.created_at, p.ride_id
ON CONFLICT DO NOTHING;

INSERT INTO public.ride_effort_completion_windows
SELECT p.ride_id, p.user_id, (s->>'vault_id')::NUMERIC, tstzrange(
    p.started_at + (s->>'segment_start_offset_s')::INTEGER * INTERVAL '1 second',
    p.started_at + ((s->>'segment_end_offset_s')::INTEGER + 1) * INTERVAL '1 second',
    '[)'
)
FROM public.ride_economic_plans AS p
JOIN public.reward_threshold_provisional_holds AS h USING (ride_id)
CROSS JOIN jsonb_array_elements(h.hold_evidence->'completion_steps') AS s
WHERE s->>'segment_start_offset_s' IS NOT NULL AND s->>'segment_end_offset_s' IS NOT NULL
ORDER BY p.created_at, p.ride_id
ON CONFLICT DO NOTHING;

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS effort_spans_ms JSONB,
    ADD COLUMN IF NOT EXISTS effort_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS covered_effort_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS paid_effort_seconds INTEGER;

-- A ride frozen before this migration keeps the effort its plan was backfilled
-- with above. The parser's buckets can never equal that whole-file span, so a
-- replay that derived them again would send a settled ride to review. This
-- span-only update must not revalidate legacy snapshots against newer rules.
ALTER TABLE public.rides DISABLE TRIGGER trg_rides_reward_ftp_immutable;
ALTER TABLE public.rides DISABLE TRIGGER trg_rides_threshold_evidence;
UPDATE public.rides AS ride
SET effort_spans_ms = public.ride_effort_spans_to_ms(plan.effort_spans)
FROM public.ride_economic_plans AS plan
WHERE plan.ride_id = ride.id
  AND plan.user_id = ride.user_id
  AND ride.effort_spans_ms IS NULL;
ALTER TABLE public.rides ENABLE TRIGGER trg_rides_threshold_evidence;
ALTER TABLE public.rides ENABLE TRIGGER trg_rides_reward_ftp_immutable;

CREATE OR REPLACE FUNCTION public.br_enforce_ride_effort_immutability()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF OLD.effort_spans_ms IS NOT NULL
       AND NEW.effort_spans_ms IS DISTINCT FROM OLD.effort_spans_ms THEN
        RAISE EXCEPTION 'ride effort spans cannot change';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS br_enforce_ride_effort_immutability ON public.rides;
CREATE TRIGGER br_enforce_ride_effort_immutability
    BEFORE UPDATE ON public.rides
    FOR EACH ROW EXECUTE FUNCTION public.br_enforce_ride_effort_immutability();

DO $$
BEGIN
    IF to_regprocedure('public.freeze_ride_economic_plan_unreviewed_without_effort_trim(jsonb,jsonb)') IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_unreviewed_without_effort_trim;
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan_unreviewed_without_effort_trim(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.freeze_ride_economic_plan_unreviewed(p_plan JSONB, p_steps JSONB)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride UUID := (p_plan->>'ride_id')::UUID;
    v_user UUID := (p_plan->>'user_id')::UUID;
    v_trim JSONB := p_plan->'effort_trim';
    v_effort TSTZMULTIRANGE;
    v_paid TSTZMULTIRANGE;
    v_declared_covered TSTZMULTIRANGE;
    v_covered TSTZMULTIRANGE;
BEGIN
    IF v_trim->>'version' IS DISTINCT FROM 'ride_effort_trim_v1' THEN
        RAISE EXCEPTION 'effort trim version required';
    END IF;
    v_effort := public.ride_effort_spans_from_ms(v_trim->'effort_spans_ms');
    v_paid := public.ride_effort_spans_from_ms(v_trim->'paid_spans_ms');
    v_declared_covered := public.ride_effort_spans_from_ms(v_trim->'covered_spans_ms');
    IF public.ride_effort_spans_to_ms(v_effort) IS DISTINCT FROM v_trim->'effort_spans_ms'
       OR public.ride_effort_spans_to_ms(v_paid) IS DISTINCT FROM v_trim->'paid_spans_ms'
       OR public.ride_effort_spans_to_ms(v_declared_covered) IS DISTINCT FROM v_trim->'covered_spans_ms' THEN
        RAISE EXCEPTION 'noncanonical effort spans';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.rides AS r
        WHERE r.id = v_ride AND r.user_id = v_user
          AND r.effort_spans_ms IS NOT NULL
          AND public.ride_effort_spans_from_ms(r.effort_spans_ms) = v_effort
    ) OR NOT v_paid <@ v_effort THEN
        RAISE EXCEPTION 'effort differs from parsed ride';
    END IF;
    INSERT INTO public.ride_effort_admission_locks AS fence (user_id)
    VALUES (v_user)
    ON CONFLICT (user_id) DO UPDATE SET revision = fence.revision + 1;

    -- New READ COMMITTED snapshot after the preceding fence write.
    SELECT coalesce(range_agg(paid_spans), '{}')
    INTO v_covered
    FROM public.ride_economic_plans
    WHERE user_id = v_user AND ride_id <> v_ride AND paid_spans && v_effort;
    IF public.ride_effort_spans_to_ms(v_covered * v_effort)
       IS DISTINCT FROM v_trim->'covered_spans_ms' OR v_paid && v_covered THEN
        RAISE EXCEPTION 'stale_effort_coverage' USING ERRCODE = 'BRR08';
    END IF;
    IF p_plan->>'reward_policy' = 'threshold_provisional_hold_v1'
       OR (p_plan->>'exact_cal_base_units')::NUMERIC > 0 THEN
        IF v_paid = '{}'::TSTZMULTIRANGE OR EXISTS (
            SELECT 1 FROM unnest((v_effort - v_covered) - v_paid) AS r
            WHERE upper(r) - lower(r) >= INTERVAL '2 seconds'
        ) THEN
            RAISE EXCEPTION 'paid effort is not maximal';
        END IF;
    ELSIF v_paid <> '{}'::TSTZMULTIRANGE THEN
        RAISE EXCEPTION 'zero value plan cannot claim effort';
    END IF;

    PERFORM public.freeze_ride_economic_plan_unreviewed_without_effort_trim(p_plan, p_steps);
    BEGIN
        UPDATE public.ride_economic_plans
        SET effort_spans = v_effort,
            paid_spans = v_paid,
            covered_spans = v_covered * v_effort
        WHERE ride_id = v_ride;

        INSERT INTO public.ride_effort_completion_windows
        SELECT p.ride_id, p.user_id, s.vault_id, tstzrange(
            p.started_at + s.segment_start_offset_s * INTERVAL '1 second',
            p.started_at + (s.segment_end_offset_s + 1) * INTERVAL '1 second',
            '[)'
        )
        FROM public.ride_economic_plans AS p
        JOIN public.ride_economic_completion_steps AS s USING (ride_id)
        WHERE p.ride_id = v_ride
        ON CONFLICT (ride_id, vault_id) DO NOTHING;
    EXCEPTION WHEN exclusion_violation THEN
        RAISE EXCEPTION 'stale_effort_coverage' USING ERRCODE = 'BRR08';
    END;
    IF EXISTS (
        SELECT 1 FROM public.ride_effort_completion_windows
        WHERE ride_id = v_ride AND NOT tstzmultirange(completion_window) && v_paid
    ) THEN
        RAISE EXCEPTION 'completion outside paid effort';
    END IF;
    RETURN public.get_ride_economic_plan(v_ride);
END;
$$;
REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.get_ride_effort_trim_basis(
    p_user_id UUID,
    p_ride_id UUID,
    p_completion_spans_ms JSONB DEFAULT '[]'::JSONB
)
RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT jsonb_build_object(
        'frozen', (
            SELECT jsonb_build_object(
                'effort_spans_ms', public.ride_effort_spans_to_ms(effort_spans),
                'paid_spans_ms', public.ride_effort_spans_to_ms(paid_spans),
                'covered_spans_ms', public.ride_effort_spans_to_ms(covered_spans)
            )
            FROM public.ride_economic_plans
            WHERE ride_id = p_ride_id AND user_id = p_user_id
        ),
        'covered_spans_ms', (
            SELECT public.ride_effort_spans_to_ms(coalesce(range_agg(p.paid_spans), '{}'))
            FROM public.ride_economic_plans AS p
            JOIN public.rides AS r ON r.id = p_ride_id AND r.user_id = p_user_id
            WHERE p.user_id = p_user_id AND p.ride_id <> p_ride_id
              AND p.paid_spans && public.ride_effort_spans_from_ms(r.effort_spans_ms)
        ),
        'covered_completion_windows', (
            SELECT coalesce(jsonb_agg(jsonb_build_object(
                'vault_id', w.vault_id,
                'start_ms', (extract(epoch FROM lower(w.completion_window)) * 1000)::BIGINT,
                'end_ms', (extract(epoch FROM upper(w.completion_window)) * 1000)::BIGINT
            ) ORDER BY lower(w.completion_window), w.vault_id), '[]')
            FROM public.ride_effort_completion_windows AS w
            JOIN public.rides AS r ON r.id = p_ride_id AND r.user_id = p_user_id
            WHERE w.user_id = p_user_id AND w.ride_id <> p_ride_id
              AND (
                  w.completion_window && range_merge(
                      public.ride_effort_spans_from_ms(r.effort_spans_ms)
                  )
                  -- A climb can extend to an isolated file-edge sample that
                  -- has no effort bucket. Include its canonical window too.
                  OR tstzmultirange(w.completion_window)
                      && public.ride_effort_spans_from_ms(p_completion_spans_ms)
              )
        )
    );
$$;
REVOKE ALL ON FUNCTION public.get_ride_effort_trim_basis(UUID, UUID, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ride_effort_trim_basis(UUID, UUID, JSONB) TO service_role;

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
              ((NEW.covered_spans IS NULL OR NEW.covered_spans = '{}'::TSTZMULTIRANGE)
                AND pg_catalog.trunc(ride.economic_tss)::BIGINT = NEW.total_tss)
              OR (NEW.covered_spans <> '{}'::TSTZMULTIRANGE
                AND NEW.total_tss = pg_catalog.trunc(NEW.exact_cal_base_units / 1000000000))
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

    -- A replay that differs from the stored plan, such as one frozen under the
    -- previous evidence domain, gets the stored plan back: the two-argument
    -- freeze has audited it or sent a live plan to review. Its hold was
    -- registered when the plan was first frozen.
    IF pg_catalog.decode(v_plan->>'plan_evidence_hash_hex', 'hex')
        IS DISTINCT FROM pg_catalog.decode(p_plan->>'plan_evidence_hash_hex', 'hex')
       AND v_plan->>'state' IN ('complete', 'review', 'rejected') THEN
        RETURN v_plan;
    END IF;

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
    BEGIN
        INSERT INTO public.ride_effort_completion_windows
        SELECT p.ride_id, p.user_id, (s->>'vault_id')::NUMERIC, tstzrange(
            p.started_at + public.require_ride_economic_uint(
                s->'segment_start_offset_s', 'segment_start_offset_s', 4294967295
            )::BIGINT * INTERVAL '1 second',
            p.started_at + (public.require_ride_economic_uint(
                s->'segment_end_offset_s', 'segment_end_offset_s', 4294967295
            )::BIGINT + 1) * INTERVAL '1 second',
            '[)'
        )
        FROM public.ride_economic_plans AS p
        CROSS JOIN jsonb_array_elements(
            p_threshold_hold->'hold_evidence'->'completion_steps'
        ) AS s
        WHERE p.ride_id = (p_plan->>'ride_id')::UUID
        ON CONFLICT (ride_id, vault_id) DO NOTHING;
    EXCEPTION WHEN exclusion_violation THEN
        RAISE EXCEPTION 'stale_effort_coverage' USING ERRCODE = 'BRR08';
    END;
    IF EXISTS (
        SELECT 1 FROM public.ride_effort_completion_windows AS w
        JOIN public.ride_economic_plans AS p USING (ride_id)
        WHERE p.ride_id = (p_plan->>'ride_id')::UUID
          AND NOT tstzmultirange(w.completion_window) && p.paid_spans
    ) THEN
        RAISE EXCEPTION 'held completion outside paid effort';
    END IF;
    RETURN public.get_ride_economic_plan((p_plan->>'ride_id')::UUID);
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_ride_economic_plan(JSONB, JSONB, JSONB) TO service_role;
REVOKE ALL ON FUNCTION
    public.ride_effort_spans_from_ms(JSONB),
    public.ride_effort_spans_to_ms(TSTZMULTIRANGE),
    public.br_enforce_effort_trim_immutability(),
    public.br_require_effort_trim_presence(),
    public.br_enforce_ride_effort_immutability()
    FROM PUBLIC, anon, authenticated, service_role;
COMMIT;
