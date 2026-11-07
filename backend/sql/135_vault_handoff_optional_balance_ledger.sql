-- Keep Vault handoff projection independent from the optional Balance ledger.
--
-- Migration 129 predates the canonical Balance schema but references
-- balance_operations from two runtime functions. Resolve that relation only
-- when it is installed so the chain projection remains authoritative and the
-- Balance receipt is enriched when available.

CREATE OR REPLACE FUNCTION public.br_mark_vault_handoff_projected(
    p_vault_id BIGINT,
    p_chain_slot BIGINT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF p_chain_slot IS NULL OR p_chain_slot < 0 THEN
        RETURN;
    END IF;

    UPDATE public.vault_creation_handoffs
    SET projection_attached_at = COALESCE(projection_attached_at, now()),
        projected_chain_slot = CASE
            WHEN projected_chain_slot IS NULL THEN p_chain_slot
            ELSE GREATEST(projected_chain_slot, p_chain_slot)
        END,
        updated_at = now()
    WHERE vault_id = p_vault_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE public.vault_backfill_jobs
    SET status = 'queued',
        error_message = NULL
    WHERE vault_id = p_vault_id
      AND status = 'waiting_projection';

    UPDATE public.indexed_vaults
    SET backfill_status = 'pending'
    WHERE id = p_vault_id
      AND chain_slot IS NOT NULL
      AND backfill_status IS NULL;

    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $balance_update$
            UPDATE public.balance_operations
            SET projection_status = 'recorded',
                rider_state = NULL,
                failure_reason = NULL,
                updated_at = now()
            WHERE action_type = 'create_vault'
              AND reference_type = 'vault'
              AND reference_id = $1::TEXT
              AND confirmation_status IN ('confirmed', 'finalized')
              AND projection_status IN ('not_started', 'pending', 'delayed')
        $balance_update$
        USING p_vault_id;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.stage_confirmed_vault_creation(
    p_vault_id BIGINT,
    p_vault_pda TEXT,
    p_signature_hex TEXT,
    p_signature_hash_hex TEXT,
    p_signature_v2_hex TEXT,
    p_start_lat DOUBLE PRECISION,
    p_start_lon DOUBLE PRECISION,
    p_end_lat DOUBLE PRECISION,
    p_end_lon DOUBLE PRECISION,
    p_creator_wallet TEXT,
    p_create_tx_signature TEXT,
    p_source_climb_id UUID,
    p_operation_id TEXT,
    p_priority INTEGER DEFAULT 100
) RETURNS TABLE(job_id UUID, projection_ready BOOLEAN, chain_slot BIGINT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_existing public.vault_creation_handoffs%ROWTYPE;
    v_job_id UUID;
    v_chain_slot BIGINT;
BEGIN
    INSERT INTO public.vault_creation_handoffs (
        vault_id,
        vault_pda,
        signature_hex,
        signature_hash_hex,
        signature_v2_hex,
        start_lat,
        start_lon,
        end_lat,
        end_lon,
        creator_wallet,
        create_tx_signature,
        source_climb_id
    ) VALUES (
        p_vault_id,
        p_vault_pda,
        p_signature_hex,
        p_signature_hash_hex,
        p_signature_v2_hex,
        p_start_lat,
        p_start_lon,
        p_end_lat,
        p_end_lon,
        p_creator_wallet,
        p_create_tx_signature,
        p_source_climb_id
    )
    ON CONFLICT (vault_id) DO NOTHING;

    SELECT *
    INTO v_existing
    FROM public.vault_creation_handoffs
    WHERE vault_id = p_vault_id
    FOR UPDATE;

    IF v_existing.vault_pda <> p_vault_pda
       OR v_existing.signature_hex::TEXT <> p_signature_hex
       OR v_existing.signature_hash_hex::TEXT <> p_signature_hash_hex
       OR v_existing.creator_wallet <> p_creator_wallet
       OR (
            v_existing.signature_v2_hex IS NOT NULL
            AND v_existing.signature_v2_hex::TEXT <> p_signature_v2_hex
       )
       OR (
            v_existing.start_lat IS NOT NULL
            AND v_existing.start_lat IS DISTINCT FROM p_start_lat
       )
       OR (
            v_existing.start_lon IS NOT NULL
            AND v_existing.start_lon IS DISTINCT FROM p_start_lon
       )
       OR (
            v_existing.end_lat IS NOT NULL
            AND v_existing.end_lat IS DISTINCT FROM p_end_lat
       )
       OR (
            v_existing.end_lon IS NOT NULL
            AND v_existing.end_lon IS DISTINCT FROM p_end_lon
       )
       OR (
            v_existing.create_tx_signature IS NOT NULL
            AND v_existing.create_tx_signature <> p_create_tx_signature
       )
       OR (
            v_existing.source_climb_id IS NOT NULL
            AND v_existing.source_climb_id IS DISTINCT FROM p_source_climb_id
       ) THEN
        RAISE EXCEPTION 'Confirmed Vault creation retry does not match handoff for vault %', p_vault_id
            USING ERRCODE = '23514';
    END IF;

    UPDATE public.vault_creation_handoffs
    SET signature_v2_hex = COALESCE(signature_v2_hex, p_signature_v2_hex),
        start_lat = COALESCE(start_lat, p_start_lat),
        start_lon = COALESCE(start_lon, p_start_lon),
        end_lat = COALESCE(end_lat, p_end_lat),
        end_lon = COALESCE(end_lon, p_end_lon),
        create_tx_signature = COALESCE(create_tx_signature, p_create_tx_signature),
        source_climb_id = COALESCE(source_climb_id, p_source_climb_id),
        updated_at = now()
    WHERE vault_id = p_vault_id;

    v_job_id := public.queue_vault_backfill(
        p_vault_id,
        p_signature_hex,
        p_priority
    );

    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $balance_update$
            UPDATE public.balance_operations
            SET projection_status = 'pending',
                rider_state = 'Pending',
                failure_reason = NULL,
                updated_at = now()
            WHERE operation_id = $1
              AND action_type = 'create_vault'
              AND reference_type = 'vault'
              AND reference_id = $2::TEXT
              AND confirmation_status IN ('confirmed', 'finalized')
              AND projection_status IN ('not_started', 'pending', 'delayed')
        $balance_update$
        USING p_operation_id, p_vault_id;
    END IF;

    SELECT iv.chain_slot
    INTO v_chain_slot
    FROM public.indexed_vaults AS iv
    WHERE iv.id = p_vault_id
      AND iv.chain_slot IS NOT NULL;

    RETURN QUERY SELECT v_job_id, v_chain_slot IS NOT NULL, v_chain_slot;
END;
$$;

COMMENT ON FUNCTION public.br_mark_vault_handoff_projected(BIGINT, BIGINT) IS
'Advances the canonical Vault handoff and updates an installed Balance receipt without requiring the optional Balance schema.';

COMMENT ON FUNCTION public.stage_confirmed_vault_creation(
    BIGINT, TEXT, TEXT, TEXT, TEXT,
    DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION,
    TEXT, TEXT, UUID, TEXT, INTEGER
) IS
'Atomically records confirmed Vault metadata and replay intent; Balance receipt enrichment is optional.';

REVOKE ALL ON FUNCTION public.br_mark_vault_handoff_projected(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.stage_confirmed_vault_creation(
    BIGINT, TEXT, TEXT, TEXT, TEXT,
    DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION,
    TEXT, TEXT, UUID, TEXT, INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.stage_confirmed_vault_creation(
    BIGINT, TEXT, TEXT, TEXT, TEXT,
    DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION,
    TEXT, TEXT, UUID, TEXT, INTEGER
) TO service_role;

NOTIFY pgrst, 'reload schema';

