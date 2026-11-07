-- Separate confirmed Vault creation metadata from the chain-owned projection.
--
-- The backend records immutable creation evidence and replay intent here. Only
-- the finalized TypeScript indexer may create rows in `indexed_vaults` or write
-- their chain-owned fields and ordering provenance.

CREATE TABLE IF NOT EXISTS public.vault_creation_handoffs (
    vault_id BIGINT PRIMARY KEY,
    vault_pda TEXT NOT NULL UNIQUE,
    signature_hex CHAR(128) NOT NULL UNIQUE,
    signature_hash_hex CHAR(64) NOT NULL UNIQUE,
    signature_v2_hex CHAR(128),
    start_lat DOUBLE PRECISION,
    start_lon DOUBLE PRECISION,
    end_lat DOUBLE PRECISION,
    end_lon DOUBLE PRECISION,
    creator_wallet TEXT NOT NULL,
    create_tx_signature TEXT,
    source_climb_id UUID,
    staged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    projection_attached_at TIMESTAMPTZ,
    projected_chain_slot BIGINT,
    CONSTRAINT vault_creation_handoffs_vault_id_check CHECK (vault_id >= 0),
    CONSTRAINT vault_creation_handoffs_signature_hex_check CHECK (
        signature_hex ~ '^[0-9a-fA-F]{128}$'
    ),
    CONSTRAINT vault_creation_handoffs_signature_hash_hex_check CHECK (
        signature_hash_hex ~ '^[0-9a-fA-F]{64}$'
    ),
    CONSTRAINT vault_creation_handoffs_signature_v2_hex_check CHECK (
        signature_v2_hex IS NULL
        OR signature_v2_hex ~ '^[0-9a-fA-F]{128}$'
    ),
    CONSTRAINT vault_creation_handoffs_coordinate_completeness_check CHECK (
        (start_lat IS NULL AND start_lon IS NULL AND end_lat IS NULL AND end_lon IS NULL)
        OR
        (start_lat IS NOT NULL AND start_lon IS NOT NULL AND end_lat IS NOT NULL AND end_lon IS NOT NULL)
    ),
    CONSTRAINT vault_creation_handoffs_projection_slot_check CHECK (
        projected_chain_slot IS NULL OR projected_chain_slot >= 0
    )
);

COMMENT ON TABLE public.vault_creation_handoffs IS
'Backend-owned confirmed Vault creation evidence and replay handoff. This table is not a chain projection.';

COMMENT ON COLUMN public.vault_creation_handoffs.projected_chain_slot IS
'Finalized indexer slot observed when the handoff was attached; never supplied by the backend create route.';

ALTER TABLE public.vault_creation_handoffs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.vault_creation_handoffs
    FROM PUBLIC, anon, authenticated, service_role;

-- Existing projected Vaults become legacy handoffs so current replay jobs can
-- move their foreign key without losing referential integrity.
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
    projection_attached_at,
    projected_chain_slot
)
SELECT
    iv.id,
    iv.pda,
    iv.signature_hex,
    iv.signature_hash_hex,
    iv.signature_v2_hex,
    CASE
        WHEN iv.start_lat IS NOT NULL
         AND iv.start_lon IS NOT NULL
         AND iv.end_lat IS NOT NULL
         AND iv.end_lon IS NOT NULL
            THEN iv.start_lat
        ELSE NULL
    END,
    CASE
        WHEN iv.start_lat IS NOT NULL
         AND iv.start_lon IS NOT NULL
         AND iv.end_lat IS NOT NULL
         AND iv.end_lon IS NOT NULL
            THEN iv.start_lon
        ELSE NULL
    END,
    CASE
        WHEN iv.start_lat IS NOT NULL
         AND iv.start_lon IS NOT NULL
         AND iv.end_lat IS NOT NULL
         AND iv.end_lon IS NOT NULL
            THEN iv.end_lat
        ELSE NULL
    END,
    CASE
        WHEN iv.start_lat IS NOT NULL
         AND iv.start_lon IS NOT NULL
         AND iv.end_lat IS NOT NULL
         AND iv.end_lon IS NOT NULL
            THEN iv.end_lon
        ELSE NULL
    END,
    iv.minter,
    CASE WHEN iv.chain_slot IS NOT NULL THEN now() ELSE NULL END,
    iv.chain_slot
FROM public.indexed_vaults AS iv
ON CONFLICT (vault_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.vault_backfill_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id BIGINT NOT NULL,
    vault_signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting_projection',
    priority INTEGER NOT NULL DEFAULT 0,
    total_candidates INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    matched_count INTEGER DEFAULT 0,
    leaderboard_updates INTEGER DEFAULT 0,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (vault_id)
);

ALTER TABLE public.vault_backfill_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.vault_backfill_jobs
    FROM PUBLIC, anon, authenticated, service_role;

DO $$
DECLARE
    v_constraint RECORD;
BEGIN
    FOR v_constraint IN
        SELECT c.conname
        FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = 'public.vault_backfill_jobs'::regclass
          AND c.confrelid = 'public.indexed_vaults'::regclass
          AND c.contype = 'f'
          AND c.conkey = ARRAY[
              (
                  SELECT a.attnum
                  FROM pg_catalog.pg_attribute AS a
                  WHERE a.attrelid = c.conrelid
                    AND a.attname = 'vault_id'
              )
          ]::SMALLINT[]
    LOOP
        EXECUTE format(
            'ALTER TABLE public.vault_backfill_jobs DROP CONSTRAINT %I',
            v_constraint.conname
        );
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = 'public.vault_backfill_jobs'::regclass
          AND c.conname = 'vault_backfill_jobs_handoff_fkey'
    ) THEN
        ALTER TABLE public.vault_backfill_jobs
            ADD CONSTRAINT vault_backfill_jobs_handoff_fkey
            FOREIGN KEY (vault_id)
            REFERENCES public.vault_creation_handoffs(vault_id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;
END;
$$;

ALTER TABLE public.vault_backfill_jobs
    VALIDATE CONSTRAINT vault_backfill_jobs_handoff_fkey;

UPDATE public.vault_backfill_jobs AS jobs
SET status = 'waiting_projection',
    started_at = NULL
WHERE jobs.status = 'queued'
  AND NOT EXISTS (
      SELECT 1
      FROM public.indexed_vaults AS vaults
      WHERE vaults.id = jobs.vault_id
        AND vaults.chain_slot IS NOT NULL
  );

DROP INDEX IF EXISTS public.idx_backfill_jobs_status;
CREATE INDEX idx_backfill_jobs_status
ON public.vault_backfill_jobs(status, priority DESC, created_at)
WHERE status IN ('waiting_projection', 'queued', 'processing');

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

    UPDATE public.balance_operations
    SET projection_status = 'recorded',
        rider_state = NULL,
        failure_reason = NULL,
        updated_at = now()
    WHERE action_type = 'create_vault'
      AND reference_type = 'vault'
      AND reference_id = p_vault_id::TEXT
      AND confirmation_status IN ('confirmed', 'finalized')
      AND projection_status IN ('not_started', 'pending', 'delayed');
END;
$$;

CREATE OR REPLACE FUNCTION public.br_apply_vault_handoff_to_projection(
    p_vault_id BIGINT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_chain_slot BIGINT;
BEGIN
    UPDATE public.indexed_vaults AS vaults
    SET signature_v2_hex = COALESCE(vaults.signature_v2_hex, handoffs.signature_v2_hex),
        signature_version = CASE
            WHEN COALESCE(vaults.signature_v2_hex, handoffs.signature_v2_hex) IS NOT NULL
             AND COALESCE(vaults.start_lat, handoffs.start_lat) IS NOT NULL
             AND COALESCE(vaults.start_lon, handoffs.start_lon) IS NOT NULL
             AND COALESCE(vaults.end_lat, handoffs.end_lat) IS NOT NULL
             AND COALESCE(vaults.end_lon, handoffs.end_lon) IS NOT NULL
                THEN 2
            ELSE vaults.signature_version
        END,
        start_lat = COALESCE(vaults.start_lat, handoffs.start_lat),
        start_lon = COALESCE(vaults.start_lon, handoffs.start_lon),
        end_lat = COALESCE(vaults.end_lat, handoffs.end_lat),
        end_lon = COALESCE(vaults.end_lon, handoffs.end_lon)
    FROM public.vault_creation_handoffs AS handoffs
    WHERE vaults.id = p_vault_id
      AND vaults.chain_slot IS NOT NULL
      AND handoffs.vault_id = vaults.id
    RETURNING vaults.chain_slot INTO v_chain_slot;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    PERFORM public.br_mark_vault_handoff_projected(p_vault_id, v_chain_slot);
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_fill_vault_handoff_metadata()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_handoff public.vault_creation_handoffs%ROWTYPE;
BEGIN
    IF NEW.chain_slot IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT *
    INTO v_handoff
    FROM public.vault_creation_handoffs
    WHERE vault_id = NEW.id;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    NEW.signature_v2_hex := COALESCE(NEW.signature_v2_hex, v_handoff.signature_v2_hex);
    NEW.start_lat := COALESCE(NEW.start_lat, v_handoff.start_lat);
    NEW.start_lon := COALESCE(NEW.start_lon, v_handoff.start_lon);
    NEW.end_lat := COALESCE(NEW.end_lat, v_handoff.end_lat);
    NEW.end_lon := COALESCE(NEW.end_lon, v_handoff.end_lon);

    IF NEW.signature_v2_hex IS NOT NULL
       AND NEW.start_lat IS NOT NULL
       AND NEW.start_lon IS NOT NULL
       AND NEW.end_lat IS NOT NULL
       AND NEW.end_lon IS NOT NULL THEN
        NEW.signature_version := 2;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_finalize_vault_handoff_projection()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    PERFORM public.br_mark_vault_handoff_projected(NEW.id, NEW.chain_slot);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_attach_staged_vault_metadata()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    PERFORM public.br_apply_vault_handoff_to_projection(NEW.vault_id);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_fill_vault_handoff_metadata
    ON public.indexed_vaults;
CREATE TRIGGER br_fill_vault_handoff_metadata
BEFORE INSERT OR UPDATE OF chain_slot ON public.indexed_vaults
FOR EACH ROW
EXECUTE FUNCTION public.br_fill_vault_handoff_metadata();

DROP TRIGGER IF EXISTS br_finalize_vault_handoff_projection
    ON public.indexed_vaults;
CREATE TRIGGER br_finalize_vault_handoff_projection
AFTER INSERT OR UPDATE OF chain_slot ON public.indexed_vaults
FOR EACH ROW
EXECUTE FUNCTION public.br_finalize_vault_handoff_projection();

DROP TRIGGER IF EXISTS br_attach_staged_vault_metadata
    ON public.vault_creation_handoffs;
CREATE TRIGGER br_attach_staged_vault_metadata
AFTER INSERT OR UPDATE OF
    signature_v2_hex,
    start_lat,
    start_lon,
    end_lat,
    end_lon
ON public.vault_creation_handoffs
FOR EACH ROW
EXECUTE FUNCTION public.br_attach_staged_vault_metadata();

CREATE OR REPLACE FUNCTION public.reconcile_waiting_vault_backfills(
    p_limit INTEGER DEFAULT 100
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_vault_id BIGINT;
    v_reconciled INTEGER := 0;
    v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 100), 0), 1000);
BEGIN
    FOR v_vault_id IN
        SELECT jobs.vault_id
        FROM public.vault_backfill_jobs AS jobs
        JOIN public.vault_creation_handoffs AS handoffs
          ON handoffs.vault_id = jobs.vault_id
        JOIN public.indexed_vaults AS vaults
          ON vaults.id = jobs.vault_id
         AND vaults.chain_slot IS NOT NULL
        WHERE jobs.status = 'waiting_projection'
        ORDER BY jobs.priority DESC, jobs.created_at
        FOR UPDATE OF jobs SKIP LOCKED
        LIMIT v_limit
    LOOP
        IF public.br_apply_vault_handoff_to_projection(v_vault_id) THEN
            v_reconciled := v_reconciled + 1;
        END IF;
    END LOOP;

    RETURN v_reconciled;
END;
$$;

CREATE OR REPLACE FUNCTION public.queue_vault_backfill(
    p_vault_id BIGINT,
    p_vault_signature TEXT,
    p_priority INTEGER DEFAULT 0
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_expected_signature TEXT;
    v_projection_ready BOOLEAN;
    v_job_id UUID;
BEGIN
    -- Migration-first compatibility: an old API process may still insert its
    -- null-slot shell before calling this RPC. Convert that shell into a durable
    -- handoff so replay intent is not lost while processes drain.
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
        projection_attached_at,
        projected_chain_slot
    )
    SELECT
        vaults.id,
        vaults.pda,
        vaults.signature_hex,
        vaults.signature_hash_hex,
        vaults.signature_v2_hex,
        CASE
            WHEN vaults.start_lat IS NOT NULL
             AND vaults.start_lon IS NOT NULL
             AND vaults.end_lat IS NOT NULL
             AND vaults.end_lon IS NOT NULL
                THEN vaults.start_lat
            ELSE NULL
        END,
        CASE
            WHEN vaults.start_lat IS NOT NULL
             AND vaults.start_lon IS NOT NULL
             AND vaults.end_lat IS NOT NULL
             AND vaults.end_lon IS NOT NULL
                THEN vaults.start_lon
            ELSE NULL
        END,
        CASE
            WHEN vaults.start_lat IS NOT NULL
             AND vaults.start_lon IS NOT NULL
             AND vaults.end_lat IS NOT NULL
             AND vaults.end_lon IS NOT NULL
                THEN vaults.end_lat
            ELSE NULL
        END,
        CASE
            WHEN vaults.start_lat IS NOT NULL
             AND vaults.start_lon IS NOT NULL
             AND vaults.end_lat IS NOT NULL
             AND vaults.end_lon IS NOT NULL
                THEN vaults.end_lon
            ELSE NULL
        END,
        vaults.minter,
        CASE WHEN vaults.chain_slot IS NOT NULL THEN now() ELSE NULL END,
        vaults.chain_slot
    FROM public.indexed_vaults AS vaults
    WHERE vaults.id = p_vault_id
    ON CONFLICT (vault_id) DO NOTHING;

    SELECT signature_hex::TEXT
    INTO v_expected_signature
    FROM public.vault_creation_handoffs
    WHERE vault_id = p_vault_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Vault creation handoff % does not exist', p_vault_id
            USING ERRCODE = '23503';
    END IF;

    IF v_expected_signature <> p_vault_signature THEN
        RAISE EXCEPTION 'Vault signature does not match handoff for vault %', p_vault_id
            USING ERRCODE = '23514';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.indexed_vaults
        WHERE id = p_vault_id
          AND chain_slot IS NOT NULL
    ) INTO v_projection_ready;

    INSERT INTO public.vault_backfill_jobs AS jobs (
        vault_id,
        vault_signature,
        status,
        priority
    ) VALUES (
        p_vault_id,
        p_vault_signature,
        CASE WHEN v_projection_ready THEN 'queued' ELSE 'waiting_projection' END,
        p_priority
    )
    ON CONFLICT (vault_id) DO UPDATE SET
        priority = GREATEST(jobs.priority, EXCLUDED.priority),
        status = CASE
            WHEN jobs.status = 'waiting_projection' AND v_projection_ready
                THEN 'queued'
            WHEN jobs.status = 'failed'
             AND jobs.retry_count < jobs.max_retries
                THEN CASE
                    WHEN v_projection_ready THEN 'queued'
                    ELSE 'waiting_projection'
                END
            ELSE jobs.status
        END
    RETURNING jobs.id INTO v_job_id;

    IF v_projection_ready THEN
        UPDATE public.indexed_vaults
        SET backfill_status = 'pending'
        WHERE id = p_vault_id
          AND backfill_status IS NULL;
    END IF;

    RETURN v_job_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_ready_vault_backfill_jobs(
    p_limit INTEGER DEFAULT 10
) RETURNS TABLE(
    id UUID,
    vault_id BIGINT,
    vault_signature TEXT,
    priority INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 10), 0), 1000);
BEGIN
    UPDATE public.vault_backfill_jobs AS jobs
    SET status = 'waiting_projection',
        started_at = NULL
    WHERE jobs.status = 'queued'
      AND NOT EXISTS (
          SELECT 1
          FROM public.indexed_vaults AS vaults
          WHERE vaults.id = jobs.vault_id
            AND vaults.chain_slot IS NOT NULL
      );

    PERFORM public.reconcile_waiting_vault_backfills(v_limit);

    RETURN QUERY
    SELECT jobs.id,
           jobs.vault_id,
           jobs.vault_signature,
           jobs.priority,
           jobs.created_at
    FROM public.vault_backfill_jobs AS jobs
    JOIN public.indexed_vaults AS vaults
      ON vaults.id = jobs.vault_id
     AND vaults.chain_slot IS NOT NULL
    WHERE jobs.status = 'queued'
    ORDER BY jobs.priority DESC, jobs.created_at
    LIMIT v_limit;
END;
$$;

CREATE OR REPLACE FUNCTION public.start_backfill_job(
    p_job_id UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_vault_id BIGINT;
BEGIN
    UPDATE public.vault_backfill_jobs AS jobs
    SET status = 'processing',
        started_at = now(),
        retry_count = jobs.retry_count + 1
    WHERE jobs.id = p_job_id
      AND jobs.status IN ('queued', 'failed')
      AND EXISTS (
          SELECT 1
          FROM public.indexed_vaults AS vaults
          WHERE vaults.id = jobs.vault_id
            AND vaults.chain_slot IS NOT NULL
      )
    RETURNING jobs.vault_id INTO v_vault_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    UPDATE public.indexed_vaults
    SET backfill_status = 'in_progress',
        backfill_started_at = now(),
        backfill_error = NULL
    WHERE id = v_vault_id;

    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_backfill_job(
    p_job_id UUID,
    p_matched_count INTEGER,
    p_leaderboard_updates INTEGER
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_vault_id BIGINT;
BEGIN
    UPDATE public.vault_backfill_jobs AS jobs
    SET status = 'completed',
        completed_at = now(),
        matched_count = p_matched_count,
        leaderboard_updates = p_leaderboard_updates
    WHERE jobs.id = p_job_id
    RETURNING jobs.vault_id INTO v_vault_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    UPDATE public.indexed_vaults
    SET backfill_status = 'completed',
        backfill_completed_at = now(),
        backfill_completions_found = p_matched_count
    WHERE id = v_vault_id;

    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_backfill_job(
    p_job_id UUID,
    p_error TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_vault_id BIGINT;
    v_retry_count INTEGER;
    v_max_retries INTEGER;
    v_projection_ready BOOLEAN;
BEGIN
    SELECT jobs.vault_id,
           jobs.retry_count,
           jobs.max_retries,
           EXISTS (
               SELECT 1
               FROM public.indexed_vaults AS vaults
               WHERE vaults.id = jobs.vault_id
                 AND vaults.chain_slot IS NOT NULL
           )
    INTO v_vault_id, v_retry_count, v_max_retries, v_projection_ready
    FROM public.vault_backfill_jobs AS jobs
    WHERE jobs.id = p_job_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    UPDATE public.vault_backfill_jobs
    SET status = CASE
            WHEN v_retry_count >= v_max_retries THEN 'failed'
            WHEN v_projection_ready THEN 'queued'
            ELSE 'waiting_projection'
        END,
        error_message = p_error
    WHERE id = p_job_id;

    UPDATE public.indexed_vaults
    SET backfill_status = CASE
            WHEN v_retry_count >= v_max_retries THEN 'failed'
            ELSE 'pending'
        END,
        backfill_error = p_error
    WHERE id = v_vault_id;

    RETURN TRUE;
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

    UPDATE public.balance_operations
    SET projection_status = 'pending',
        rider_state = 'Pending',
        failure_reason = NULL,
        updated_at = now()
    WHERE operation_id = p_operation_id
      AND action_type = 'create_vault'
      AND reference_type = 'vault'
      AND reference_id = p_vault_id::TEXT
      AND confirmation_status IN ('confirmed', 'finalized')
      AND projection_status IN ('not_started', 'pending', 'delayed');

    SELECT iv.chain_slot
    INTO v_chain_slot
    FROM public.indexed_vaults AS iv
    WHERE iv.id = p_vault_id
      AND iv.chain_slot IS NOT NULL;

    RETURN QUERY SELECT v_job_id, v_chain_slot IS NOT NULL, v_chain_slot;
END;
$$;

COMMENT ON FUNCTION public.queue_vault_backfill(BIGINT, TEXT, INTEGER) IS
'Queues replay against a confirmed creation handoff and waits for a numbered indexer projection when needed.';

COMMENT ON FUNCTION public.reconcile_waiting_vault_backfills(INTEGER) IS
'Repairs route/indexer commit-order races after both durable rows become visible.';

COMMENT ON FUNCTION public.get_ready_vault_backfill_jobs(INTEGER) IS
'Reconciles visible projections, then returns the bounded ready-job dispatch set.';

COMMENT ON FUNCTION public.stage_confirmed_vault_creation(
    BIGINT, TEXT, TEXT, TEXT, TEXT,
    DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION,
    TEXT, TEXT, UUID, TEXT, INTEGER
) IS
'Atomically records backend-owned confirmed Vault metadata and replay intent without inserting indexed_vaults.';

REVOKE ALL ON FUNCTION public.br_mark_vault_handoff_projected(BIGINT, BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_apply_vault_handoff_to_projection(BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_fill_vault_handoff_metadata()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_finalize_vault_handoff_projection()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_attach_staged_vault_metadata()
    FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.reconcile_waiting_vault_backfills(INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.reconcile_waiting_vault_backfills(INTEGER)
    TO service_role;

REVOKE ALL ON FUNCTION public.get_ready_vault_backfill_jobs(INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.get_ready_vault_backfill_jobs(INTEGER)
    TO service_role;

REVOKE ALL ON FUNCTION public.queue_vault_backfill(BIGINT, TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.queue_vault_backfill(BIGINT, TEXT, INTEGER)
    TO service_role;

REVOKE ALL ON FUNCTION public.start_backfill_job(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.start_backfill_job(UUID)
    TO service_role;

REVOKE ALL ON FUNCTION public.complete_backfill_job(UUID, INTEGER, INTEGER)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.complete_backfill_job(UUID, INTEGER, INTEGER)
    TO service_role;

REVOKE ALL ON FUNCTION public.fail_backfill_job(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.fail_backfill_job(UUID, TEXT)
    TO service_role;

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
