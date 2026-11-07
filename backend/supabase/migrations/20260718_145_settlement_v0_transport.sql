-- Durable v0 settlement transport. Lookup-table lifecycle is operational state;
-- payout amounts and the atomic on-chain distribution instruction are unchanged.

CREATE TABLE IF NOT EXISTS public.settlement_lookup_table_generations (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    vault_id NUMERIC(39, 0) NOT NULL,
    program_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    lookup_table_address TEXT NOT NULL UNIQUE,
    authority TEXT NOT NULL,
    recent_slot NUMERIC(39, 0) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('planned', 'active', 'retired')),
    create_tx_signature TEXT,
    last_tx_signature TEXT,
    last_extended_slot NUMERIC(39, 0),
    address_count INTEGER NOT NULL DEFAULT 0 CHECK (address_count BETWEEN 0 AND 256),
    manifest_sha256 TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    retired_at TIMESTAMPTZ,
    UNIQUE (program_id, vault_id, generation),
    CHECK (vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC),
    CHECK (recent_slot BETWEEN 0 AND 18446744073709551615::NUMERIC),
    CHECK (
        last_extended_slot IS NULL
        OR last_extended_slot BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_lookup_table_live_generation
    ON public.settlement_lookup_table_generations (program_id, vault_id)
    WHERE status IN ('planned', 'active');

ALTER TABLE public.settlement_attempts
    ADD COLUMN IF NOT EXISTS transaction_version SMALLINT,
    ADD COLUMN IF NOT EXISTS lookup_table_address TEXT,
    ADD COLUMN IF NOT EXISTS lookup_table_generation INTEGER,
    ADD COLUMN IF NOT EXISTS transport_manifest_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS lookup_table_last_extended_slot NUMERIC(39, 0),
    ADD COLUMN IF NOT EXISTS signed_transaction_bytes INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.settlement_attempts'::pg_catalog.regclass
          AND conname = 'settlement_attempts_v0_transport_check'
    ) THEN
        ALTER TABLE public.settlement_attempts
            ADD CONSTRAINT settlement_attempts_v0_transport_check CHECK (
                (transaction_version IS NULL AND lookup_table_address IS NULL
                    AND lookup_table_generation IS NULL
                    AND transport_manifest_sha256 IS NULL
                    AND lookup_table_last_extended_slot IS NULL
                    AND signed_transaction_bytes IS NULL)
                OR
                (transaction_version IS NOT NULL AND transaction_version = 0
                    AND lookup_table_address IS NOT NULL AND lookup_table_address <> ''
                    AND lookup_table_generation IS NOT NULL AND lookup_table_generation > 0
                    AND transport_manifest_sha256 IS NOT NULL
                    AND transport_manifest_sha256 ~ '^[0-9a-f]{64}$'
                    AND lookup_table_last_extended_slot IS NOT NULL
                    AND lookup_table_last_extended_slot BETWEEN 0 AND 18446744073709551615::NUMERIC
                    AND signed_transaction_bytes IS NOT NULL
                    AND signed_transaction_bytes BETWEEN 1 AND 900)
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_get_or_plan_settlement_lookup_table(
    p_vault_id TEXT,
    p_program_id TEXT,
    p_authority TEXT,
    p_recent_slot TEXT,
    p_lookup_table_address TEXT
) RETURNS SETOF public.settlement_lookup_table_generations
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_vault_id NUMERIC(39, 0) := public.br_parse_u64_text(p_vault_id, 'vault_id');
    v_recent_slot NUMERIC(39, 0) := public.br_parse_u64_text(p_recent_slot, 'recent_slot');
    v_generation INTEGER;
    v_row public.settlement_lookup_table_generations%ROWTYPE;
BEGIN
    IF coalesce(p_program_id, '') = '' OR coalesce(p_authority, '') = ''
       OR coalesce(p_lookup_table_address, '') = '' THEN
        RAISE EXCEPTION 'settlement lookup-table identity is required';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_program_id || ':' || p_vault_id, 0)
    );
    SELECT * INTO v_row
    FROM public.settlement_lookup_table_generations
    WHERE program_id = p_program_id AND vault_id = v_vault_id
      AND status IN ('active', 'planned')
    ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, generation DESC
    LIMIT 1
    FOR UPDATE;
    IF FOUND THEN
        IF v_row.authority <> p_authority THEN
            RAISE EXCEPTION 'settlement lookup-table authority changed for vault %', p_vault_id;
        END IF;
        RETURN NEXT v_row;
        RETURN;
    END IF;

    SELECT coalesce(pg_catalog.max(generation), 0) + 1 INTO v_generation
    FROM public.settlement_lookup_table_generations
    WHERE program_id = p_program_id AND vault_id = v_vault_id;
    INSERT INTO public.settlement_lookup_table_generations (
        vault_id, program_id, generation, lookup_table_address,
        authority, recent_slot, status
    ) VALUES (
        v_vault_id, p_program_id, v_generation, p_lookup_table_address,
        p_authority, v_recent_slot, 'planned'
    ) RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_rotate_settlement_lookup_table(
    p_current_id UUID,
    p_recent_slot TEXT,
    p_lookup_table_address TEXT
) RETURNS SETOF public.settlement_lookup_table_generations
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_recent_slot NUMERIC(39, 0) := public.br_parse_u64_text(p_recent_slot, 'recent_slot');
    v_current public.settlement_lookup_table_generations%ROWTYPE;
    v_row public.settlement_lookup_table_generations%ROWTYPE;
BEGIN
    IF coalesce(p_lookup_table_address, '') = '' THEN
        RAISE EXCEPTION 'replacement lookup-table address is required';
    END IF;
    SELECT * INTO v_current
    FROM public.settlement_lookup_table_generations
    WHERE id = p_current_id
    FOR UPDATE;
    IF NOT FOUND OR v_current.status NOT IN ('planned', 'active') THEN
        RAISE EXCEPTION 'live settlement lookup-table generation is unavailable';
    END IF;

    UPDATE public.settlement_lookup_table_generations
    SET status = 'retired', retired_at = pg_catalog.now(), updated_at = pg_catalog.now()
    WHERE id = v_current.id;
    INSERT INTO public.settlement_lookup_table_generations (
        vault_id, program_id, generation, lookup_table_address,
        authority, recent_slot, status
    ) VALUES (
        v_current.vault_id, v_current.program_id, v_current.generation + 1,
        p_lookup_table_address, v_current.authority, v_recent_slot, 'planned'
    ) RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_record_settlement_lookup_table_ready(
    p_generation_id UUID,
    p_create_tx_signature TEXT,
    p_last_tx_signature TEXT,
    p_last_extended_slot TEXT,
    p_address_count INTEGER,
    p_manifest_sha256 TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_last_extended_slot NUMERIC(39, 0) := public.br_parse_u64_text(
        p_last_extended_slot, 'last_extended_slot'
    );
BEGIN
    IF p_address_count NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'settlement lookup-table address count must be between 1 and 256';
    END IF;
    IF p_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'settlement transport manifest SHA-256 is invalid';
    END IF;
    UPDATE public.settlement_lookup_table_generations
    SET status = 'active',
        create_tx_signature = coalesce(create_tx_signature, p_create_tx_signature),
        last_tx_signature = coalesce(p_last_tx_signature, last_tx_signature),
        last_extended_slot = v_last_extended_slot,
        address_count = p_address_count,
        manifest_sha256 = p_manifest_sha256,
        updated_at = pg_catalog.now()
    WHERE id = p_generation_id AND status IN ('planned', 'active');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lookup-table generation is unavailable';
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_mark_settlement_prepared_v0(
    p_job_id UUID,
    p_lease_token UUID,
    p_tx_signature TEXT,
    p_compute_unit_limit INTEGER,
    p_lookup_table_address TEXT,
    p_lookup_table_generation INTEGER,
    p_transport_manifest_sha256 TEXT,
    p_lookup_table_last_extended_slot TEXT,
    p_signed_transaction_bytes INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_job public.settlement_jobs%ROWTYPE;
    v_transport JSONB;
    v_last_extended_slot NUMERIC(39, 0) := public.br_parse_u64_text(
        p_lookup_table_last_extended_slot, 'lookup_table_last_extended_slot'
    );
BEGIN
    IF coalesce(p_tx_signature, '') = '' THEN
        RAISE EXCEPTION 'prepared transaction signature is required';
    END IF;
    IF p_compute_unit_limit IS NULL OR p_compute_unit_limit NOT BETWEEN 1 AND 1400000 THEN
        RAISE EXCEPTION 'prepared settlement compute unit limit is invalid';
    END IF;
    IF coalesce(p_lookup_table_address, '') = ''
       OR p_lookup_table_generation IS NULL OR p_lookup_table_generation <= 0
       OR p_signed_transaction_bytes IS NULL
       OR p_signed_transaction_bytes NOT BETWEEN 1 AND 900
       OR p_transport_manifest_sha256 IS NULL
       OR p_transport_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'prepared v0 settlement transport evidence is invalid';
    END IF;

    SELECT * INTO v_job FROM public.settlement_jobs
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for prepared job %', p_job_id;
    END IF;
    v_transport := v_job.precondition_result->'transport';
    IF v_transport IS NULL
       OR v_transport->>'transaction_version' <> '0'
       OR v_transport->>'lookup_table_address' <> p_lookup_table_address
       OR (v_transport->>'lookup_table_generation')::INTEGER <> p_lookup_table_generation
       OR v_transport->>'manifest_sha256' <> p_transport_manifest_sha256
       OR v_transport->>'last_extended_slot' <> p_lookup_table_last_extended_slot
       OR (v_transport->>'planned_serialized_bytes')::INTEGER <> p_signed_transaction_bytes THEN
        RAISE EXCEPTION 'prepared v0 transport diverges from frozen precondition';
    END IF;

    UPDATE public.settlement_jobs
    SET prepared_tx_signature = p_tx_signature, updated_at = pg_catalog.now()
    WHERE id = p_job_id
      AND (prepared_tx_signature IS NULL OR prepared_tx_signature = p_tx_signature);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'prepared settlement job signature fence was lost for job %', p_job_id;
    END IF;
    UPDATE public.settlement_attempts
    SET outcome = 'prepared', tx_signature = p_tx_signature,
        compute_unit_limit = p_compute_unit_limit,
        transaction_version = 0,
        lookup_table_address = p_lookup_table_address,
        lookup_table_generation = p_lookup_table_generation,
        transport_manifest_sha256 = p_transport_manifest_sha256,
        lookup_table_last_extended_slot = v_last_extended_slot,
        signed_transaction_bytes = p_signed_transaction_bytes,
        updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token
      AND (tx_signature IS NULL OR tx_signature = p_tx_signature);
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement attempt fence was lost for prepared job %', p_job_id;
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_return_settlement_to_preparation(
    p_job_id UUID,
    p_lease_token UUID,
    p_error TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_job public.settlement_jobs%ROWTYPE;
BEGIN
    SELECT * INTO v_job FROM public.settlement_jobs
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
      AND prepared_tx_signature IS NULL AND tx_signature IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unsigned settlement preparation fence was lost for job %', p_job_id;
    END IF;
    UPDATE public.settlement_jobs
    SET state = 'precondition_retry', precondition_result = NULL,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = pg_catalog.now(),
        last_error_class = 'transport_precondition_stale', last_error = p_error,
        updated_at = pg_catalog.now()
    WHERE id = p_job_id;
    UPDATE public.settlement_attempts
    SET outcome = 'blocked', error_class = 'transport_precondition_stale',
        error_message = p_error, updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token AND outcome = 'claimed';
    PERFORM public.br_refresh_settlement_run(v_job.run_id);
    RETURN TRUE;
END;
$$;

ALTER TABLE public.settlement_lookup_table_generations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.settlement_lookup_table_generations
    FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.br_get_or_plan_settlement_lookup_table(TEXT, TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_rotate_settlement_lookup_table(UUID, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_record_settlement_lookup_table_ready(UUID, TEXT, TEXT, TEXT, INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_mark_settlement_prepared_v0(UUID, UUID, TEXT, INTEGER, TEXT, INTEGER, TEXT, TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_return_settlement_to_preparation(UUID, UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.br_get_or_plan_settlement_lookup_table(TEXT, TEXT, TEXT, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.br_rotate_settlement_lookup_table(UUID, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.br_record_settlement_lookup_table_ready(UUID, TEXT, TEXT, TEXT, INTEGER, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.br_mark_settlement_prepared_v0(UUID, UUID, TEXT, INTEGER, TEXT, INTEGER, TEXT, TEXT, INTEGER)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.br_return_settlement_to_preparation(UUID, UUID, TEXT)
    TO service_role;
