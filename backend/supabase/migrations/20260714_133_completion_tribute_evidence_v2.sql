-- Bind every newly frozen climb completion to its exact tribute amount.
-- Historical V1 rows remain readable, but cannot authorize new writes or a
-- non-reject manual review resolution.

ALTER TABLE public.ride_economic_completion_steps
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT NOT NULL
        DEFAULT 1;

ALTER TABLE public.vault_completions
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT;

UPDATE public.vault_completions
SET completion_evidence_version = 1
WHERE completion_evidence_version IS NULL
  AND completion_receipt_pda IS NOT NULL
  AND completion_evidence_hash IS NOT NULL;

ALTER TABLE public.indexed_climb_completion_receipts
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT NOT NULL
        DEFAULT 1,
    ADD COLUMN IF NOT EXISTS completion_evidence_hash BYTEA,
    ADD COLUMN IF NOT EXISTS cal_tributed NUMERIC(20, 0);

ALTER TABLE public.indexed_climb_completion_flows
    ADD COLUMN IF NOT EXISTS completion_evidence_version SMALLINT NOT NULL
        DEFAULT 1;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ride_economic_steps_evidence_version_check'
    ) THEN
        ALTER TABLE public.ride_economic_completion_steps
            ADD CONSTRAINT ride_economic_steps_evidence_version_check
            CHECK (
                completion_evidence_version IS NULL
                OR completion_evidence_version IN (1, 2)
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'vault_completions_evidence_version_check'
    ) THEN
        ALTER TABLE public.vault_completions
            ADD CONSTRAINT vault_completions_evidence_version_check
            CHECK (completion_evidence_version IN (1, 2));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'indexed_completion_receipts_evidence_version_check'
    ) THEN
        ALTER TABLE public.indexed_climb_completion_receipts
            ADD CONSTRAINT indexed_completion_receipts_evidence_version_check
            CHECK (completion_evidence_version IN (1, 2));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'indexed_completion_receipts_v2_amount_check'
    ) THEN
        ALTER TABLE public.indexed_climb_completion_receipts
            ADD CONSTRAINT indexed_completion_receipts_v2_amount_check CHECK (
                (completion_evidence_version = 1 AND cal_tributed IS NULL)
                OR (
                    completion_evidence_version = 2
                    AND cal_tributed BETWEEN 0 AND 18446744073709551615::NUMERIC
                    AND completion_evidence_hash IS NOT NULL
                    AND octet_length(completion_evidence_hash) = 32
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'indexed_completion_receipts_hash_check'
    ) THEN
        ALTER TABLE public.indexed_climb_completion_receipts
            ADD CONSTRAINT indexed_completion_receipts_hash_check CHECK (
                completion_evidence_hash IS NULL
                OR octet_length(completion_evidence_hash) = 32
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'indexed_completion_flows_evidence_version_check'
    ) THEN
        ALTER TABLE public.indexed_climb_completion_flows
            ADD CONSTRAINT indexed_completion_flows_evidence_version_check
            CHECK (completion_evidence_version IN (1, 2));
    END IF;
END;
$$;

DO $$
BEGIN
    IF to_regprocedure(
        'public.freeze_ride_economic_plan_unreviewed_v1(jsonb,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
            RENAME TO freeze_ride_economic_plan_unreviewed_v1;
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_unreviewed_v1(JSONB, JSONB)
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
    v_step JSONB;
    v_version NUMERIC;
BEGIN
    IF jsonb_typeof(p_steps) <> 'array' THEN
        RAISE EXCEPTION 'ride economic completion steps must be an array';
    END IF;

    FOR v_step IN SELECT value FROM jsonb_array_elements(p_steps)
    LOOP
        v_version := public.require_ride_economic_uint(
            v_step->'completion_evidence_version',
            'completion_evidence_version',
            255
        );
        IF v_version <> 2 THEN
            RAISE EXCEPTION
                'new ride economic plans require tribute-bound V2 completion evidence';
        END IF;
    END LOOP;

    PERFORM public.freeze_ride_economic_plan_unreviewed_v1(p_plan, p_steps);

    UPDATE public.ride_economic_completion_steps AS target
    SET completion_evidence_version = 2
    FROM jsonb_array_elements(p_steps) AS source(step)
    WHERE target.ride_id = v_ride_id
      AND target.step_index = public.require_ride_economic_uint(
            source.step->'step_index', 'step_index', 2147483647
          )::INTEGER;

    RETURN public.get_ride_economic_plan(v_ride_id);
END;
$$;

REVOKE ALL ON FUNCTION
    public.freeze_ride_economic_plan_unreviewed(JSONB, JSONB)
    FROM PUBLIC, anon, authenticated, service_role;

DO $$
DECLARE
    v_ride_id UUID;
BEGIN
    FOR v_ride_id IN
        SELECT DISTINCT plan.ride_id
        FROM public.ride_economic_plans AS plan
        JOIN public.ride_economic_completion_steps AS step
          ON step.ride_id = plan.ride_id
        WHERE step.completion_evidence_version = 1
          AND plan.state NOT IN ('complete', 'review', 'rejected')
    LOOP
        PERFORM public.enter_ride_economic_review(
            v_ride_id,
            NULL,
            false,
            'legacy_completion_evidence_v1_cutover',
            'migration:completion_tribute_evidence_v2',
            jsonb_build_object(
                'version', 1,
                'kind', 'legacy_completion_evidence',
                'operation', 'v2_cutover',
                'message',
                    'pending V1 plan cannot prove exact tribute after V2 cutover',
                'observed_at', clock_timestamp()
            )
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_require_v2_completion_step_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.completion_evidence_version <> 2
       AND NEW.state IN ('confirmed', 'projected') THEN
        RAISE EXCEPTION
            'V1 completion evidence cannot be confirmed or projected after V2 cutover';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_require_v2_completion_step_transition
    ON public.ride_economic_completion_steps;
CREATE TRIGGER br_require_v2_completion_step_transition
BEFORE UPDATE ON public.ride_economic_completion_steps
FOR EACH ROW
EXECUTE FUNCTION public.br_require_v2_completion_step_transition();

CREATE OR REPLACE FUNCTION public.br_bind_vault_completion_evidence_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_version SMALLINT;
BEGIN
    IF NEW.chain_confirmation_status = 'confirmed' THEN
        SELECT step.completion_evidence_version INTO v_version
        FROM public.ride_economic_completion_steps AS step
        WHERE step.expected_receipt_pda = NEW.completion_receipt_pda
          AND step.completion_evidence_hash = NEW.completion_evidence_hash;
        IF FOUND THEN
            NEW.completion_evidence_version := v_version;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_bind_vault_completion_evidence_version
    ON public.vault_completions;
CREATE TRIGGER br_bind_vault_completion_evidence_version
BEFORE INSERT OR UPDATE ON public.vault_completions
FOR EACH ROW
EXECUTE FUNCTION public.br_bind_vault_completion_evidence_version();

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

CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(
    p_activity_id TEXT
)
RETURNS VOID
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
            vc.completion_evidence_hash,
            vc.completion_evidence_version,
            vc.cal_tribute,
            iv.id AS vault_id
        FROM public.vault_completions AS vc
        LEFT JOIN public.indexed_vaults AS iv
          ON iv.signature_hex = vc.vault_signature
        WHERE vc.activity_id = p_activity_id
          AND vc.chain_confirmation_status = 'confirmed'
    )
    SELECT CASE
        WHEN COUNT(*) > 0
         AND COUNT(flow.credited_settlement_week) = COUNT(*)
         AND COUNT(*) FILTER (WHERE flow.cal_tributed > 0) > 0
         AND COUNT(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
             = COUNT(*) FILTER (WHERE flow.cal_tributed > 0)
            THEN MAX(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
        ELSE NULL
    END
    INTO v_finalized_at
    FROM confirmed_completions AS completion
    LEFT JOIN public.indexed_climb_completion_flows AS flow
      ON flow.completion_evidence_hash = completion.completion_evidence_hash
     AND flow.vault_id = completion.vault_id
     AND flow.completion_evidence_version = 2
     AND completion.completion_evidence_version = 2
     AND flow.cal_tributed = completion.cal_tribute
    LEFT JOIN LATERAL (
        SELECT MIN(indexed_distribution.finalized_at) AS finalized_at
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
    p_vault_id BIGINT,
    p_epoch BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    SELECT MIN(distribution.finalized_at)
    INTO v_finalized_at
    FROM public.indexed_epoch_distributions AS distribution
    WHERE distribution.vault_id = p_vault_id
      AND distribution.epoch = p_epoch
      AND distribution.finalized_at IS NOT NULL;

    UPDATE public.epoch_distributions AS legacy_distribution
    SET finalized_at = v_finalized_at
    WHERE legacy_distribution.epoch::BIGINT = p_epoch
      AND (
          legacy_distribution.vault_id::BIGINT = p_vault_id
          OR EXISTS (
              SELECT 1
              FROM public.indexed_vaults AS indexed_vault
              WHERE indexed_vault.id = p_vault_id
                AND legacy_distribution.vault_signature = indexed_vault.signature_hex
          )
      )
      AND legacy_distribution.finalized_at IS DISTINCT FROM v_finalized_at;

    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM public.indexed_climb_completion_flows AS flow
        JOIN public.indexed_vaults AS iv
          ON iv.id = flow.vault_id
        JOIN public.vault_completions AS vc
          ON vc.completion_evidence_hash = flow.completion_evidence_hash
         AND vc.vault_signature = iv.signature_hex
         AND vc.completion_evidence_version = 2
         AND flow.completion_evidence_version = 2
         AND vc.cal_tribute = flow.cal_tributed
        WHERE flow.vault_id = p_vault_id
          AND flow.credited_settlement_week = p_epoch
          AND vc.chain_confirmation_status = 'confirmed'
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
        SELECT DISTINCT vc.activity_id
        FROM public.indexed_vaults AS iv
        JOIN public.vault_completions AS vc
          ON vc.vault_signature = iv.signature_hex
        WHERE iv.id = NEW.vault_id
          AND vc.completion_evidence_hash = NEW.completion_evidence_hash
          AND vc.completion_evidence_version = 2
          AND NEW.completion_evidence_version = 2
          AND vc.cal_tribute = NEW.cal_tributed
          AND vc.chain_confirmation_status = 'confirmed'
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;

    RETURN NEW;
END;
$$;

DO $$
DECLARE
    v_activity_id TEXT;
BEGIN
    FOR v_activity_id IN
        SELECT DISTINCT activity_id
        FROM public.vault_completions
        WHERE activity_id IS NOT NULL AND activity_id <> ''
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_require_tribute_bound_review_resolution()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_step_count INTEGER;
    v_v2_step_count INTEGER;
    v_observation JSONB;
BEGIN
    IF NEW.outcome = 'reject' THEN
        RETURN NEW;
    END IF;

    SELECT count(*)::INTEGER,
           count(*) FILTER (
               WHERE completion_evidence_version = 2
           )::INTEGER
      INTO v_step_count, v_v2_step_count
    FROM public.ride_economic_completion_steps
    WHERE ride_id = NEW.ride_id;

    IF v_step_count <> v_v2_step_count THEN
        RAISE EXCEPTION
            'V1 completion evidence cannot authorize a non-reject review resolution';
    END IF;

    FOR v_observation IN
        SELECT value
        FROM jsonb_array_elements(COALESCE(
            NEW.chain_evidence->'completions', '[]'::JSONB
        ))
    LOOP
        IF public.require_ride_economic_uint(
                v_observation->'completion_evidence_version',
                'completion_evidence_version',
                255
           ) <> 2
           OR COALESCE((v_observation->>'tribute_bound')::BOOLEAN, false)
                IS NOT TRUE THEN
            RAISE EXCEPTION
                'review completion evidence must bind exact tribute with V2';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_require_tribute_bound_review_resolution
    ON public.ride_economic_review_resolutions;
CREATE TRIGGER br_require_tribute_bound_review_resolution
BEFORE INSERT ON public.ride_economic_review_resolutions
FOR EACH ROW
EXECUTE FUNCTION public.br_require_tribute_bound_review_resolution();

COMMENT ON COLUMN public.ride_economic_completion_steps.completion_evidence_version IS
    '1 is historical identity-only evidence; 2 binds ride, vault, time, and exact tribute.';
COMMENT ON COLUMN public.vault_completions.completion_evidence_version IS
    'Copied from the frozen completion step; only V2 is exact tribute evidence.';
