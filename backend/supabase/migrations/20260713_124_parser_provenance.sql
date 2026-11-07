-- Parser V2 and economic provenance hardening.
--
-- New ride-economic plans resolve parser_version + policy_version against one
-- active immutable pipeline vector. Historical plans/events remain readable
-- without being rewritten.

ALTER TABLE public.pipeline_versions
    ADD COLUMN IF NOT EXISTS ride_parser_version BIGINT,
    ADD COLUMN IF NOT EXISTS policy_version TEXT;

-- The legacy registry stored a package string, not the parser semantic number.
-- Preserve those rows as V1 and retain their existing economic label as policy.
UPDATE public.pipeline_versions
SET ride_parser_version = COALESCE(ride_parser_version, 1),
    policy_version = COALESCE(policy_version, economics_version)
WHERE ride_parser_version IS NULL OR policy_version IS NULL;

ALTER TABLE public.pipeline_versions
    ALTER COLUMN ride_parser_version SET NOT NULL,
    ALTER COLUMN policy_version SET NOT NULL;

-- Snapshot the latest active vector, then register the two exact parser
-- semantic rows before switching the single active row to V2. Unknown
-- historical plan pairs fail closed during backfill rather than receiving
-- invented provenance.
DO $$
DECLARE
    v_template public.pipeline_versions%ROWTYPE;
    v_v1_id INTEGER;
    v_existing_id INTEGER;
BEGIN
    SELECT * INTO v_template
    FROM public.pipeline_versions
    WHERE deactivated_at IS NULL
    ORDER BY activated_at DESC, id DESC
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'cannot register parser provenance without an active pipeline vector template';
    END IF;

    -- The explicit V1 row is retained for raw-byte replay and backfill even
    -- though V2 becomes the sole active row below.
    SELECT id INTO v_v1_id
    FROM public.pipeline_versions
    WHERE parser_version = '1'
      AND ride_parser_version = 1
      AND policy_version = 'ride_effort_policy_2026_05_06'
      AND git_commit = 'e212e9e57ef93635b7ca5d21a68a5834af3ec1d0'
    ORDER BY id DESC
    LIMIT 1;

    IF NOT FOUND THEN
        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version,
            detector_params_hash, sig_format_version, sig_match_version,
            economics_version, integrity_version, git_commit, activated_at,
            deactivated_at, notes, ride_parser_version, policy_version
        ) VALUES (
            '1', v_template.detector_algorithm, v_template.detector_version,
            v_template.detector_params_hash, v_template.sig_format_version,
            v_template.sig_match_version, 'ride_effort_policy_2026_05_06',
            v_template.integrity_version,
            'e212e9e57ef93635b7ca5d21a68a5834af3ec1d0', now(), now(),
            'Parser semantic V1 replay row: legacy QName/state/missing-elevation semantics.',
            1, 'ride_effort_policy_2026_05_06'
        ) RETURNING id INTO v_v1_id;
    END IF;

    SELECT id INTO v_existing_id
    FROM public.pipeline_versions
    WHERE parser_version = '2'
      AND ride_parser_version = 2
      AND policy_version = 'ride_effort_policy_2026_05_06'
      AND git_commit = '9e6d49aa217c522222bb9922282df40ea799afeb'
    ORDER BY id DESC
    LIMIT 1;

    IF FOUND THEN
        IF (SELECT deactivated_at IS NOT NULL FROM public.pipeline_versions WHERE id = v_existing_id) THEN
            RAISE EXCEPTION 'parser V2 pipeline version is inactive and cannot be reactivated';
        END IF;
    ELSE
        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version,
            detector_params_hash, sig_format_version, sig_match_version,
            economics_version, integrity_version, git_commit, activated_at,
            deactivated_at, notes, ride_parser_version, policy_version
        ) VALUES (
            '2', v_template.detector_algorithm, v_template.detector_version,
            v_template.detector_params_hash, v_template.sig_format_version,
            v_template.sig_match_version, 'ride_effort_policy_2026_05_06',
            v_template.integrity_version,
            '9e6d49aa217c522222bb9922282df40ea799afeb', now(), NULL,
            'Parser semantic V2: missing GPX/TCX elevation remains missing; V1 replays remain raw-byte versioned.',
            2, 'ride_effort_policy_2026_05_06'
        ) RETURNING id INTO v_existing_id;
    END IF;

    UPDATE public.pipeline_versions
    SET deactivated_at = now()
    WHERE deactivated_at IS NULL AND id <> v_existing_id;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_versions_one_active
    ON public.pipeline_versions ((1))
    WHERE deactivated_at IS NULL;

CREATE OR REPLACE FUNCTION public.prevent_pipeline_version_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE on pipeline_versions is forbidden';
    END IF;

    -- A version vector is immutable. The only permitted update is one-way
    -- deactivation; this lets a later vector become active without mutation.
    IF OLD.deactivated_at IS NULL
       AND NEW.deactivated_at IS NOT NULL
       AND NEW.id IS NOT DISTINCT FROM OLD.id
       AND NEW.parser_version IS NOT DISTINCT FROM OLD.parser_version
       AND NEW.ride_parser_version IS NOT DISTINCT FROM OLD.ride_parser_version
       AND NEW.policy_version IS NOT DISTINCT FROM OLD.policy_version
       AND NEW.detector_algorithm IS NOT DISTINCT FROM OLD.detector_algorithm
       AND NEW.detector_version IS NOT DISTINCT FROM OLD.detector_version
       AND NEW.detector_params_hash IS NOT DISTINCT FROM OLD.detector_params_hash
       AND NEW.sig_format_version IS NOT DISTINCT FROM OLD.sig_format_version
       AND NEW.sig_match_version IS NOT DISTINCT FROM OLD.sig_match_version
       AND NEW.economics_version IS NOT DISTINCT FROM OLD.economics_version
       AND NEW.integrity_version IS NOT DISTINCT FROM OLD.integrity_version
       AND NEW.git_commit IS NOT DISTINCT FROM OLD.git_commit
       AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
       AND NEW.notes IS NOT DISTINCT FROM OLD.notes THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'pipeline_versions are immutable except one-way deactivation';
END;
$$;

DROP TRIGGER IF EXISTS trg_pipeline_versions_immutable ON public.pipeline_versions;
CREATE TRIGGER trg_pipeline_versions_immutable
    BEFORE UPDATE OR DELETE ON public.pipeline_versions
    FOR EACH ROW EXECUTE FUNCTION public.prevent_pipeline_version_mutation();

ALTER TABLE public.ride_economic_plans
    ADD COLUMN IF NOT EXISTS pipeline_version_id INTEGER
    REFERENCES public.pipeline_versions(id);

UPDATE public.ride_economic_plans AS plan
SET pipeline_version_id = (
    SELECT version.id
    FROM public.pipeline_versions AS version
    WHERE version.ride_parser_version = plan.parser_version
      AND version.policy_version = plan.policy_version
      AND (
          (
              version.parser_version = '1'
              AND version.git_commit = 'e212e9e57ef93635b7ca5d21a68a5834af3ec1d0'
          )
          OR (
              version.parser_version = '2'
              AND version.git_commit = '9e6d49aa217c522222bb9922282df40ea799afeb'
          )
      )
    ORDER BY version.deactivated_at IS NULL DESC, version.id DESC
    LIMIT 1
)
WHERE plan.pipeline_version_id IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.ride_economic_plans
        WHERE pipeline_version_id IS NULL
    ) THEN
        RAISE EXCEPTION 'ride_economic_plans provenance backfill did not resolve every frozen plan';
    END IF;
END;
$$;

ALTER TABLE public.ride_economic_plans
    ALTER COLUMN pipeline_version_id SET NOT NULL;

COMMENT ON COLUMN public.ride_economic_plans.pipeline_version_id IS
    'Immutable active pipeline vector selected from the frozen parser_version and policy_version.';

CREATE OR REPLACE FUNCTION public.bind_ride_economic_plan_pipeline_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_pipeline_version_id INTEGER;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.pipeline_version_id IS DISTINCT FROM OLD.pipeline_version_id
           OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
           OR NEW.policy_version IS DISTINCT FROM OLD.policy_version THEN
            RAISE EXCEPTION 'frozen ride economic provenance cannot be changed';
        END IF;
        RETURN NEW;
    END IF;

    SELECT id INTO v_pipeline_version_id
    FROM public.pipeline_versions
    WHERE deactivated_at IS NULL
      AND ride_parser_version = NEW.parser_version
      AND policy_version = NEW.policy_version;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'no active immutable pipeline version for parser_version % and policy_version %',
            NEW.parser_version, NEW.policy_version;
    END IF;

    NEW.pipeline_version_id := v_pipeline_version_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ride_economic_plan_pipeline_version
    ON public.ride_economic_plans;
CREATE TRIGGER trg_ride_economic_plan_pipeline_version
    BEFORE INSERT OR UPDATE ON public.ride_economic_plans
    FOR EACH ROW EXECUTE FUNCTION public.bind_ride_economic_plan_pipeline_version();

-- Do not use a CHECK ... NOT VALID here: PostgreSQL evaluates it on updates,
-- which would block the permitted is_reversed transition on historical rows.
CREATE OR REPLACE FUNCTION public.require_economic_event_pipeline_version()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.pipeline_version_id IS NULL THEN
        RAISE EXCEPTION 'new economic_events require pipeline_version_id';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_economic_events_require_pipeline_version
    ON public.economic_events;
CREATE TRIGGER trg_economic_events_require_pipeline_version
    BEFORE INSERT ON public.economic_events
    FOR EACH ROW EXECUTE FUNCTION public.require_economic_event_pipeline_version();

-- Keep the historical reversal workflow, but require every other ledger
-- field to be identical. This preserves old hash chains and prevents a
-- reversal update from smuggling a provenance or amount mutation.
CREATE OR REPLACE FUNCTION public.prevent_ledger_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE on economic_events is forbidden. Ledger is append-only.';
    END IF;

    IF OLD.is_reversed = FALSE
       AND NEW.is_reversed = TRUE
       AND NEW.id IS NOT DISTINCT FROM OLD.id
       AND NEW.event_uuid IS NOT DISTINCT FROM OLD.event_uuid
       AND NEW.event_type IS NOT DISTINCT FROM OLD.event_type
       AND NEW.wallet IS NOT DISTINCT FROM OLD.wallet
       AND NEW.counterparty IS NOT DISTINCT FROM OLD.counterparty
       AND NEW.amount IS NOT DISTINCT FROM OLD.amount
       AND NEW.denomination IS NOT DISTINCT FROM OLD.denomination
       AND NEW.balance_after IS NOT DISTINCT FROM OLD.balance_after
       AND NEW.caused_by_id IS NOT DISTINCT FROM OLD.caused_by_id
       AND NEW.batch_id IS NOT DISTINCT FROM OLD.batch_id
       AND NEW.pipeline_version_id IS NOT DISTINCT FROM OLD.pipeline_version_id
       AND NEW.reference_type IS NOT DISTINCT FROM OLD.reference_type
       AND NEW.reference_id IS NOT DISTINCT FROM OLD.reference_id
       AND NEW.valid_at IS NOT DISTINCT FROM OLD.valid_at
       AND NEW.recorded_at IS NOT DISTINCT FROM OLD.recorded_at
       AND NEW.reversal_of_id IS NOT DISTINCT FROM OLD.reversal_of_id
       AND NEW.evidence IS NOT DISTINCT FROM OLD.evidence
       AND NEW.prev_hash IS NOT DISTINCT FROM OLD.prev_hash
       AND NEW.event_hash IS NOT DISTINCT FROM OLD.event_hash THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'UPDATE on economic_events is forbidden except is_reversed FALSE->TRUE';
END;
$$;

DROP TRIGGER IF EXISTS trg_ledger_immutable ON public.economic_events;
CREATE TRIGGER trg_ledger_immutable
    BEFORE UPDATE OR DELETE ON public.economic_events
    FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_mutation();

COMMENT ON FUNCTION public.require_economic_event_pipeline_version() IS
    'Insert-only provenance enforcement. Historical NULL rows retain their allowed reversal update and legacy event hashes.';
