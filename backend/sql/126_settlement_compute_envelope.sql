-- Persist the exact compute envelope attached to each newly prepared
-- settlement transaction. Historical attempts remain valid without evidence.

ALTER TABLE public.settlement_attempts
    ADD COLUMN IF NOT EXISTS compute_unit_limit INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.settlement_attempts'::pg_catalog.regclass
          AND conname = 'settlement_attempts_compute_unit_limit_check'
    ) THEN
        ALTER TABLE public.settlement_attempts
            ADD CONSTRAINT settlement_attempts_compute_unit_limit_check
            CHECK (
                compute_unit_limit IS NULL
                OR compute_unit_limit BETWEEN 1 AND 1400000
            );
    END IF;
END;
$$;

-- Keep the three-argument overload during rollout so callers deployed before
-- this migration continue to resolve. New workers use this evidence-bearing
-- overload, which requires a limit and atomically fences both durable writes.
CREATE OR REPLACE FUNCTION public.br_mark_settlement_prepared(
    p_job_id UUID,
    p_lease_token UUID,
    p_tx_signature TEXT,
    p_compute_unit_limit INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF coalesce(p_tx_signature, '') = '' THEN
        RAISE EXCEPTION 'prepared transaction signature is required';
    END IF;
    IF p_compute_unit_limit IS NULL THEN
        RAISE EXCEPTION 'prepared settlement compute unit limit is required';
    END IF;
    IF p_compute_unit_limit NOT BETWEEN 1 AND 1400000 THEN
        RAISE EXCEPTION 'prepared settlement compute unit limit must be between 1 and 1400000';
    END IF;

    UPDATE public.settlement_jobs
    SET prepared_tx_signature = p_tx_signature, updated_at = pg_catalog.now()
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
      AND (prepared_tx_signature IS NULL OR prepared_tx_signature = p_tx_signature)
    RETURNING * INTO v_job;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for prepared job %', p_job_id;
    END IF;

    UPDATE public.settlement_attempts
    SET outcome = 'prepared', tx_signature = p_tx_signature,
        compute_unit_limit = p_compute_unit_limit,
        updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token
      AND (tx_signature IS NULL OR tx_signature = p_tx_signature)
      AND (
          compute_unit_limit IS NULL
          OR compute_unit_limit = p_compute_unit_limit
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement attempt fence was lost for prepared job %', p_job_id;
    END IF;
    RETURN TRUE;
END;
$$;

DO $$
DECLARE v_owner NAME;
BEGIN
    SELECT pg_catalog.pg_get_userbyid(p.proowner)
    INTO v_owner
    FROM pg_catalog.pg_proc AS p
    JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'br_mark_settlement_prepared'
      AND p.pronargs = 3;

    IF v_owner IS NULL THEN
        RAISE EXCEPTION 'existing br_mark_settlement_prepared owner is unavailable';
    END IF;
    EXECUTE pg_catalog.format(
        'ALTER FUNCTION public.br_mark_settlement_prepared(UUID, UUID, TEXT, INTEGER) OWNER TO %I',
        v_owner
    );
END;
$$;

REVOKE ALL ON FUNCTION
    public.br_mark_settlement_prepared(UUID, UUID, TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION
    public.br_mark_settlement_prepared(UUID, UUID, TEXT, INTEGER)
    TO service_role;
