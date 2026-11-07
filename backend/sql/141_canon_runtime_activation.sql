-- V4-B canon runtime activation, immutable registry binding, and indexer projection.
-- Canonical mirror: backend/supabase/migrations/20260721_149_canon_runtime_activation.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE public.canon_climbs
    DROP CONSTRAINT IF EXISTS canon_climbs_version_u16_check;
ALTER TABLE public.canon_climbs
    ADD CONSTRAINT canon_climbs_version_u16_check
    CHECK (version BETWEEN 1 AND 65535) NOT VALID;
ALTER TABLE public.canon_climbs
    VALIDATE CONSTRAINT canon_climbs_version_u16_check;

-- Retired versions remain immutable history and may intentionally share the
-- compiler fingerprint with an explicit successor revision.
DROP INDEX IF EXISTS public.idx_canon_climbs_candidate_fingerprint;
CREATE UNIQUE INDEX idx_canon_climbs_candidate_fingerprint
    ON public.canon_climbs(candidate_fingerprint)
    WHERE status <> 'retired';

CREATE TABLE IF NOT EXISTS public.indexed_climbs (
    pda TEXT PRIMARY KEY,
    canon_climb_id UUID NOT NULL UNIQUE
        REFERENCES public.canon_climbs(id) ON DELETE RESTRICT,
    canon_commitment_hex TEXT NOT NULL UNIQUE
        CHECK (canon_commitment_hex ~ '^[0-9a-f]{128}$'),
    commitment_hash_hex TEXT NOT NULL UNIQUE
        CHECK (commitment_hash_hex ~ '^[0-9a-f]{64}$'),
    canon_id UUID NOT NULL,
    canon_version INTEGER NOT NULL CHECK (canon_version BETWEEN 1 AND 65535),
    canonical_profile_hash_hex TEXT NOT NULL
        CHECK (canonical_profile_hash_hex ~ '^[0-9a-f]{64}$'),
    predecessor_climb_pda TEXT,
    successor_climb_pda TEXT,
    record_continuity_policy TEXT NOT NULL
        CHECK (record_continuity_policy = 'new_record_board'),
    vault_pda TEXT,
    name TEXT NOT NULL,
    vert_m DOUBLE PRECISION NOT NULL CHECK (
        vert_m > 0 AND vert_m < 'Infinity'::double precision
    ),
    distance_m INTEGER NOT NULL CHECK (distance_m > 0),
    avg_gradient_pct DOUBLE PRECISION NOT NULL CHECK (
        avg_gradient_pct >= 0
        AND avg_gradient_pct <= 655.35
    ),
    registered_at TIMESTAMPTZ NOT NULL,
    registered_by TEXT NOT NULL,
    chain_slot BIGINT NOT NULL CHECK (chain_slot >= 0),
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    quarantined BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (canon_id, canon_version)
);

ALTER TABLE public.indexed_climbs
    ADD COLUMN IF NOT EXISTS successor_climb_pda TEXT,
    DROP CONSTRAINT IF EXISTS indexed_climbs_quarantined_check;

CREATE TABLE IF NOT EXISTS public.canon_indexer_quarantine (
    account_pda TEXT PRIMARY KEY,
    account_type TEXT NOT NULL CHECK (account_type IN ('Climb', 'Vault')),
    reason TEXT NOT NULL,
    observed_program_version INTEGER,
    chain_slot BIGINT NOT NULL CHECK (chain_slot >= 0),
    payload_hash_hex TEXT CHECK (
        payload_hash_hex IS NULL OR payload_hash_hex ~ '^[0-9a-f]{64}$'
    ),
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.canon_indexer_pending (
    account_pda TEXT PRIMARY KEY,
    account_type TEXT NOT NULL CHECK (account_type = 'Vault'),
    reason TEXT NOT NULL,
    chain_slot BIGINT NOT NULL CHECK (chain_slot >= 0),
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts > 0),
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.indexed_vaults
    ADD COLUMN IF NOT EXISTS climb_pda TEXT,
    ADD COLUMN IF NOT EXISTS canon_climb_id UUID,
    ADD COLUMN IF NOT EXISTS canon_commitment_hex TEXT,
    ADD COLUMN IF NOT EXISTS canon_binding_status TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE public.indexed_vaults
    DROP CONSTRAINT IF EXISTS indexed_vaults_climb_pda_fkey,
    ADD CONSTRAINT indexed_vaults_climb_pda_fkey
        FOREIGN KEY (climb_pda) REFERENCES public.indexed_climbs(pda)
        DEFERRABLE INITIALLY DEFERRED,
    DROP CONSTRAINT IF EXISTS indexed_vaults_canon_climb_id_fkey,
    ADD CONSTRAINT indexed_vaults_canon_climb_id_fkey
        FOREIGN KEY (canon_climb_id) REFERENCES public.canon_climbs(id)
        DEFERRABLE INITIALLY DEFERRED,
    DROP CONSTRAINT IF EXISTS indexed_vaults_canon_commitment_hex_check,
    ADD CONSTRAINT indexed_vaults_canon_commitment_hex_check CHECK (
        canon_commitment_hex IS NULL
        OR canon_commitment_hex ~ '^[0-9a-f]{128}$'
    ),
    DROP CONSTRAINT IF EXISTS indexed_vaults_canon_binding_status_check,
    ADD CONSTRAINT indexed_vaults_canon_binding_status_check CHECK (
        canon_binding_status IN ('legacy', 'active', 'quarantined')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_vaults_active_canon_climb
    ON public.indexed_vaults(canon_climb_id)
    WHERE canon_binding_status = 'active';

CREATE TABLE IF NOT EXISTS public.canon_vault_activations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canon_climb_id UUID NOT NULL
        REFERENCES public.canon_climbs(id) ON DELETE RESTRICT,
    creator_wallet TEXT NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('dung', 'cal_usdc')),
    client_request_id TEXT NOT NULL CHECK (length(client_request_id) BETWEEN 1 AND 120),
    canon_commitment_hex TEXT NOT NULL
        CHECK (canon_commitment_hex ~ '^[0-9a-f]{128}$'),
    commitment_hash_hex TEXT NOT NULL
        CHECK (commitment_hash_hex ~ '^[0-9a-f]{64}$'),
    climb_pda TEXT NOT NULL,
    vault_id BIGINT NOT NULL CHECK (vault_id >= 0),
    vault_pda TEXT NOT NULL,
    vault_activation_pda TEXT NOT NULL,
    prepared_blockhash TEXT NOT NULL,
    last_valid_block_height BIGINT NOT NULL CHECK (last_valid_block_height > 0),
    prepared_message_hash TEXT CHECK (
        prepared_message_hash IS NULL
        OR prepared_message_hash ~ '^[0-9a-f]{64}$'
    ),
    tx_signature TEXT CHECK (
        tx_signature IS NULL
        OR tx_signature ~ '^[1-9A-HJ-NP-Za-km-z]{64,88}$'
    ),
    activation_status TEXT NOT NULL DEFAULT 'reserved' CHECK (
        activation_status IN (
            'reserved', 'confirmed', 'finalized', 'released', 'failed'
        )
    ),
    failure_reason TEXT,
    chain_slot BIGINT,
    constructor_evidence_hash TEXT CHECK (
        constructor_evidence_hash IS NULL
        OR constructor_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    constructor_evidence_verified BOOLEAN NOT NULL DEFAULT FALSE,
    constructor_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    finalized_at TIMESTAMPTZ,
    released_at TIMESTAMPTZ,
    absence_observed_slot BIGINT,
    absence_observed_block_height BIGINT,
    UNIQUE (creator_wallet, client_request_id)
);

ALTER TABLE public.canon_vault_activations
    ADD COLUMN IF NOT EXISTS constructor_evidence_hash TEXT,
    ADD COLUMN IF NOT EXISTS constructor_evidence_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS constructor_verified_at TIMESTAMPTZ,
    DROP CONSTRAINT IF EXISTS canon_vault_activations_constructor_evidence_check,
    ADD CONSTRAINT canon_vault_activations_constructor_evidence_check CHECK (
        (
            constructor_evidence_verified IS FALSE
            AND constructor_evidence_hash IS NULL
            AND constructor_verified_at IS NULL
        )
        OR (
            constructor_evidence_verified IS TRUE
            AND constructor_evidence_hash ~ '^[0-9a-f]{64}$'
            AND constructor_evidence_hash <> repeat('0', 64)
            AND constructor_verified_at IS NOT NULL
        )
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_vault_activations_live_climb
    ON public.canon_vault_activations(canon_climb_id)
    WHERE activation_status IN ('reserved', 'confirmed', 'finalized');
CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_vault_activations_live_vault
    ON public.canon_vault_activations(vault_id)
    WHERE activation_status IN ('reserved', 'confirmed', 'finalized');
CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_vault_activations_live_climb_pda
    ON public.canon_vault_activations(climb_pda)
    WHERE activation_status IN ('reserved', 'confirmed', 'finalized');
CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_vault_activations_live_vault_pda
    ON public.canon_vault_activations(vault_pda)
    WHERE activation_status IN ('reserved', 'confirmed', 'finalized');
CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_vault_activations_live_activation_pda
    ON public.canon_vault_activations(vault_activation_pda)
    WHERE activation_status IN ('reserved', 'confirmed', 'finalized');

ALTER TABLE public.indexed_climbs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canon_indexer_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canon_indexer_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canon_vault_activations ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.indexed_climbs FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.canon_indexer_quarantine FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.canon_indexer_pending FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.canon_vault_activations FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.indexed_climbs TO service_role;

-- The backend reads canon directly but cannot mutate it through its broad API role.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON TABLE public.canon_climbs, public.canon_corridor_cells
    FROM service_role;
GRANT SELECT ON TABLE public.canon_climbs, public.canon_corridor_cells TO service_role;

CREATE OR REPLACE FUNCTION public.freeze_committed_canon_climb()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_is_committed BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM public.canon_vault_activations AS activation
        WHERE activation.canon_climb_id = OLD.id
          AND activation.activation_status IN ('reserved', 'confirmed', 'finalized')
        UNION ALL
        SELECT 1
        FROM public.indexed_climbs AS indexed
        WHERE indexed.canon_climb_id = OLD.id
          AND indexed.quarantined IS FALSE
    ) INTO v_is_committed;
    IF NOT v_is_committed THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'committed canon climb is immutable'
            USING ERRCODE = '22000';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status = 'ratified' AND NEW.status = 'retired') THEN
        RAISE EXCEPTION 'committed canon climb is immutable'
            USING ERRCODE = '22000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status', 'retired_at', 'updated_at'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'retired_at', 'updated_at']) THEN
        RAISE EXCEPTION 'committed canon climb is immutable'
            USING ERRCODE = '22000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_freeze_committed_canon_climb ON public.canon_climbs;
CREATE TRIGGER trg_freeze_committed_canon_climb
BEFORE UPDATE OR DELETE ON public.canon_climbs
FOR EACH ROW EXECUTE FUNCTION public.freeze_committed_canon_climb();

CREATE OR REPLACE FUNCTION public.require_committed_canon_successor()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_successor_count INTEGER;
BEGIN
    IF OLD.status = 'ratified'
       AND NEW.status = 'retired'
       AND EXISTS (
           SELECT 1
           FROM public.canon_vault_activations AS activation
           WHERE activation.canon_climb_id = OLD.id
             AND activation.activation_status IN ('reserved', 'confirmed', 'finalized')
           UNION ALL
           SELECT 1
           FROM public.indexed_climbs AS indexed
           WHERE indexed.canon_climb_id = OLD.id
             AND indexed.quarantined IS FALSE
       ) THEN
        SELECT count(*) INTO v_successor_count
        FROM public.canon_climbs AS successor
        WHERE successor.canon_id = OLD.canon_id
          AND successor.version = OLD.version + 1
          AND successor.supersedes_climb_id = OLD.id
          AND successor.status = 'ratified'
          AND successor.record_continuity_policy = 'new_record_board';
        IF v_successor_count <> 1 THEN
            RAISE EXCEPTION 'committed canon retirement requires one explicit canon successor'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_require_committed_canon_successor
    ON public.canon_climbs;
CREATE CONSTRAINT TRIGGER trg_require_committed_canon_successor
AFTER UPDATE ON public.canon_climbs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.require_committed_canon_successor();

CREATE OR REPLACE FUNCTION public.freeze_committed_canon_corridor_cell()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_old_id UUID;
    v_new_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN v_old_id := OLD.canon_climb_id; END IF;
    IF TG_OP <> 'DELETE' THEN v_new_id := NEW.canon_climb_id; END IF;
    IF EXISTS (
        SELECT 1
        FROM public.canon_vault_activations AS activation
        WHERE activation.canon_climb_id IN (v_old_id, v_new_id)
          AND activation.activation_status IN ('reserved', 'confirmed', 'finalized')
        UNION ALL
        SELECT 1
        FROM public.indexed_climbs AS indexed
        WHERE indexed.canon_climb_id IN (v_old_id, v_new_id)
          AND indexed.quarantined IS FALSE
    ) THEN
        RAISE EXCEPTION 'committed canon corridor is immutable'
            USING ERRCODE = '22000';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_freeze_committed_canon_corridor_cell
    ON public.canon_corridor_cells;
CREATE TRIGGER trg_freeze_committed_canon_corridor_cell
BEFORE INSERT OR UPDATE OR DELETE ON public.canon_corridor_cells
FOR EACH ROW EXECUTE FUNCTION public.freeze_committed_canon_corridor_cell();

CREATE OR REPLACE FUNCTION public.reserve_canon_vault_activation(
    p_canon_climb_id UUID,
    p_creator_wallet TEXT,
    p_payment_method TEXT,
    p_client_request_id TEXT,
    p_canon_commitment_hex TEXT,
    p_commitment_hash_hex TEXT,
    p_climb_pda TEXT,
    p_vault_id BIGINT,
    p_vault_pda TEXT,
    p_vault_activation_pda TEXT,
    p_prepared_blockhash TEXT,
    p_last_valid_block_height BIGINT
)
RETURNS TABLE(preparation_id UUID, activation_status TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_climb public.canon_climbs%ROWTYPE;
    v_profile_hash TEXT;
    v_expected_commitment TEXT;
    v_existing public.canon_vault_activations%ROWTYPE;
    v_inserted public.canon_vault_activations%ROWTYPE;
BEGIN
    IF p_payment_method NOT IN ('dung', 'cal_usdc')
       OR p_creator_wallet IS NULL OR btrim(p_creator_wallet) = ''
       OR p_client_request_id IS NULL OR length(p_client_request_id) NOT BETWEEN 1 AND 120
       OR p_climb_pda IS NULL OR btrim(p_climb_pda) = ''
       OR p_vault_pda IS NULL OR btrim(p_vault_pda) = ''
       OR p_vault_activation_pda IS NULL OR btrim(p_vault_activation_pda) = ''
       OR p_vault_id < 0 OR p_last_valid_block_height <= 0 THEN
        RAISE EXCEPTION 'invalid canon activation reservation'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_climb
    FROM public.canon_climbs
    WHERE id = p_canon_climb_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_climb.status <> 'ratified'
       OR v_climb.canon_id IS NULL
       OR v_climb.canon_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR v_climb.record_continuity_policy <> 'new_record_board' THEN
        RAISE EXCEPTION 'canon climb is not the current ratified row'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.canon_climbs AS other
        WHERE other.canon_id = v_climb.canon_id
          AND other.status = 'ratified'
          AND other.id <> v_climb.id
    ) THEN
        RAISE EXCEPTION 'canon climb is not uniquely ratified'
            USING ERRCODE = '23514';
    END IF;

    v_profile_hash := lower(
        v_climb.provenance #>> '{canonical_profile_hash,value}'
    );
    IF v_climb.provenance #>> '{canonical_profile_hash,algorithm}'
           <> 'blake3_canonical_profile_v1'
       OR v_profile_hash !~ '^[0-9a-f]{64}$'
       OR v_profile_hash = repeat('0', 64)
       OR v_climb.version NOT BETWEEN 1 AND 65535 THEN
        RAISE EXCEPTION 'canon climb profile commitment is invalid'
            USING ERRCODE = '23514';
    END IF;
    v_expected_commitment :=
        '01'
        || replace(v_climb.canon_id::text, '-', '')
        || lpad(to_hex(v_climb.version), 4, '0')
        || repeat('00', 13)
        || v_profile_hash;
    IF lower(p_canon_commitment_hex) <> v_expected_commitment
       OR lower(p_commitment_hash_hex) <>
            pg_catalog.encode(
                public.digest(
                    pg_catalog.decode(v_expected_commitment, 'hex'),
                    'sha256'
                ),
                'hex'
            ) THEN
        RAISE EXCEPTION 'canon commitment does not match exact registry row'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.indexed_climbs AS indexed
        WHERE indexed.canon_climb_id = v_climb.id
          AND indexed.pda = p_climb_pda
          AND indexed.canon_commitment_hex = v_expected_commitment
          AND indexed.canonical_profile_hash_hex = v_profile_hash
          AND indexed.canon_id = v_climb.canon_id
          AND indexed.canon_version = v_climb.version
          AND indexed.record_continuity_policy = 'new_record_board'
          AND indexed.successor_climb_pda IS NULL
          AND indexed.vault_pda IS NULL
          AND indexed.quarantined IS FALSE
    ) THEN
        RAISE EXCEPTION 'exact indexed V4-B Climb is unavailable'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_existing
    FROM public.canon_vault_activations AS existing
    WHERE existing.creator_wallet = p_creator_wallet
      AND existing.client_request_id = p_client_request_id
    FOR UPDATE;
    IF FOUND THEN
        IF v_existing.canon_climb_id <> p_canon_climb_id
           OR v_existing.payment_method <> p_payment_method
           OR v_existing.canon_commitment_hex <> lower(p_canon_commitment_hex)
           OR v_existing.commitment_hash_hex <> lower(p_commitment_hash_hex)
           OR v_existing.climb_pda <> p_climb_pda
           OR v_existing.vault_id <> p_vault_id
           OR v_existing.vault_pda <> p_vault_pda
           OR v_existing.vault_activation_pda <> p_vault_activation_pda THEN
            RAISE EXCEPTION 'client request id conflicts with prior reservation'
                USING ERRCODE = '23505';
        END IF;
        IF v_existing.activation_status = 'released' THEN
            UPDATE public.canon_vault_activations AS activation
            SET vault_id = p_vault_id,
                vault_pda = p_vault_pda,
                vault_activation_pda = p_vault_activation_pda,
                prepared_blockhash = p_prepared_blockhash,
                last_valid_block_height = p_last_valid_block_height,
                prepared_message_hash = NULL,
                tx_signature = NULL,
                activation_status = 'reserved',
                failure_reason = NULL,
                chain_slot = NULL,
                confirmed_at = NULL,
                finalized_at = NULL,
                released_at = NULL,
                absence_observed_slot = NULL,
                absence_observed_block_height = NULL,
                updated_at = now()
            WHERE activation.id = v_existing.id
            RETURNING * INTO v_existing;
        ELSIF v_existing.activation_status IN ('reserved', 'confirmed', 'finalized')
          AND (
              v_existing.prepared_blockhash <> p_prepared_blockhash
              OR v_existing.last_valid_block_height <> p_last_valid_block_height
          ) THEN
            RAISE EXCEPTION 'client request id conflicts with prior reservation'
                USING ERRCODE = '23505';
        ELSIF v_existing.activation_status NOT IN ('reserved', 'confirmed', 'finalized') THEN
            RAISE EXCEPTION 'client request id is not reusable'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT v_existing.id, v_existing.activation_status;
        RETURN;
    END IF;

    INSERT INTO public.canon_vault_activations (
        canon_climb_id, creator_wallet, payment_method, client_request_id,
        canon_commitment_hex, commitment_hash_hex, climb_pda,
        vault_id, vault_pda, vault_activation_pda,
        prepared_blockhash, last_valid_block_height
    ) VALUES (
        p_canon_climb_id, p_creator_wallet, p_payment_method, p_client_request_id,
        lower(p_canon_commitment_hex), lower(p_commitment_hash_hex), p_climb_pda,
        p_vault_id, p_vault_pda, p_vault_activation_pda,
        p_prepared_blockhash, p_last_valid_block_height
    ) RETURNING * INTO v_inserted;
    RETURN QUERY SELECT v_inserted.id, v_inserted.activation_status;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_canon_vault_release_candidate(
    p_vault_id BIGINT
)
RETURNS TABLE(
    preparation_id UUID,
    canon_climb_id UUID,
    creator_wallet TEXT,
    client_request_id TEXT,
    payment_method TEXT,
    canon_commitment_hex TEXT,
    commitment_hash_hex TEXT,
    climb_pda TEXT,
    vault_id BIGINT,
    vault_pda TEXT,
    vault_activation_pda TEXT,
    prepared_blockhash TEXT,
    last_valid_block_height BIGINT,
    activation_status TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT activation.id, activation.canon_climb_id,
           activation.creator_wallet, activation.client_request_id,
           activation.payment_method, activation.canon_commitment_hex,
           activation.commitment_hash_hex, activation.climb_pda,
           activation.vault_id, activation.vault_pda,
           activation.vault_activation_pda, activation.prepared_blockhash,
           activation.last_valid_block_height, activation.activation_status
    FROM public.canon_vault_activations AS activation
    WHERE activation.vault_id = p_vault_id
      AND activation.activation_status IN ('reserved', 'confirmed');
$$;

CREATE OR REPLACE FUNCTION public.get_canon_vault_preparation(
    p_preparation_id UUID,
    p_creator_wallet TEXT
)
RETURNS TABLE(
    preparation_id UUID,
    canon_climb_id UUID,
    creator_wallet TEXT,
    payment_method TEXT,
    canon_commitment_hex TEXT,
    commitment_hash_hex TEXT,
    climb_pda TEXT,
    vault_id BIGINT,
    vault_pda TEXT,
    vault_activation_pda TEXT,
    prepared_blockhash TEXT,
    last_valid_block_height BIGINT,
    activation_status TEXT,
    tx_signature TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT activation.id, activation.canon_climb_id, activation.creator_wallet,
           activation.payment_method, activation.canon_commitment_hex,
           activation.commitment_hash_hex, activation.climb_pda,
           activation.vault_id, activation.vault_pda,
           activation.vault_activation_pda,
           activation.prepared_blockhash, activation.last_valid_block_height,
           activation.activation_status, activation.tx_signature
    FROM public.canon_vault_activations AS activation
    WHERE activation.id = p_preparation_id
      AND activation.creator_wallet = p_creator_wallet;
$$;

CREATE OR REPLACE FUNCTION public.get_canon_climb_runtime_states(
    p_canon_climb_ids UUID[]
)
RETURNS TABLE(canon_climb_id UUID, runtime_state TEXT)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF COALESCE(cardinality(p_canon_climb_ids), 0) > 100 THEN
        RAISE EXCEPTION 'canon runtime state query is limited to 100 rows'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM unnest(COALESCE(p_canon_climb_ids, ARRAY[]::UUID[]))
             AS requested(canon_climb_id)
        LEFT JOIN public.indexed_climbs AS climb
          ON climb.canon_climb_id = requested.canon_climb_id
         AND climb.quarantined IS FALSE
        LEFT JOIN public.indexed_vaults AS vault
          ON vault.canon_climb_id = requested.canon_climb_id
         AND vault.canon_binding_status = 'active'
         AND vault.climb_pda = climb.pda
         AND vault.pda = climb.vault_pda
         AND vault.signature_hex = climb.canon_commitment_hex
         AND vault.signature_hash_hex = climb.commitment_hash_hex
         AND vault.canon_commitment_hex = climb.canon_commitment_hex
        LEFT JOIN public.canon_vault_activations AS activation
          ON activation.canon_climb_id = requested.canon_climb_id
         AND activation.activation_status = 'finalized'
         AND activation.climb_pda = climb.pda
         AND activation.canon_commitment_hex = climb.canon_commitment_hex
         AND activation.commitment_hash_hex = climb.commitment_hash_hex
        LEFT JOIN public.indexed_vault_activations AS chain_activation
          ON chain_activation.vault_id = vault.id
         AND chain_activation.pda = activation.vault_activation_pda
         AND activation.vault_id = vault.id
         AND activation.vault_pda = vault.pda
         AND activation.constructor_evidence_verified IS TRUE
         AND chain_activation.is_active IS TRUE
         AND chain_activation.seed_generation = 2
         AND chain_activation.seed_completions_written = 0
         AND chain_activation.leaderboard_seeded IS TRUE
         AND chain_activation.matched_users = 0
         AND chain_activation.matched_completions = 0
         AND chain_activation.created_at > 0
         AND chain_activation.created_at = chain_activation.activated_at
         AND chain_activation.created_at = chain_activation.last_seed_at
         AND chain_activation.created_at = chain_activation.seed_cutoff_at
         AND lower(btrim(chain_activation.evidence_hash::text))
             ~ '^[0-9a-f]{64}$'
         AND lower(btrim(chain_activation.evidence_hash::text)) <> repeat('0', 64)
         AND lower(btrim(chain_activation.evidence_hash::text))
             = activation.constructor_evidence_hash
        WHERE (
            (vault.id IS NOT NULL)::integer
            + (activation.id IS NOT NULL)::integer
            + (chain_activation.vault_id IS NOT NULL)::integer
        ) NOT IN (0, 3)
    ) THEN
        RAISE EXCEPTION 'canonical Vault projection and activation state disagree'
            USING ERRCODE = '23514';
    END IF;
    RETURN QUERY
    SELECT requested.canon_climb_id,
           CASE
               WHEN vault.id IS NOT NULL
                    AND activation.activation_status = 'finalized'
                    AND chain_activation.vault_id IS NOT NULL THEN 'active'
               WHEN activation.activation_status IN ('reserved', 'confirmed') THEN 'reserved'
               WHEN climb.pda IS NOT NULL
                    AND climb.successor_climb_pda IS NULL
                    AND climb.vault_pda IS NULL THEN 'available'
               ELSE 'unavailable'
           END AS runtime_state
    FROM unnest(COALESCE(p_canon_climb_ids, ARRAY[]::UUID[]))
         AS requested(canon_climb_id)
    LEFT JOIN public.indexed_climbs AS climb
      ON climb.canon_climb_id = requested.canon_climb_id
     AND climb.quarantined IS FALSE
    LEFT JOIN public.indexed_vaults AS vault
      ON vault.canon_climb_id = requested.canon_climb_id
     AND vault.canon_binding_status = 'active'
     AND vault.climb_pda = climb.pda
     AND vault.pda = climb.vault_pda
     AND vault.signature_hex = climb.canon_commitment_hex
     AND vault.signature_hash_hex = climb.commitment_hash_hex
     AND vault.canon_commitment_hex = climb.canon_commitment_hex
    LEFT JOIN LATERAL (
        SELECT candidate.activation_status, candidate.vault_id,
               candidate.vault_pda, candidate.vault_activation_pda,
               candidate.chain_slot, candidate.constructor_evidence_hash,
               candidate.constructor_evidence_verified
        FROM public.canon_vault_activations AS candidate
        WHERE candidate.canon_climb_id = requested.canon_climb_id
          AND candidate.activation_status IN ('reserved', 'confirmed', 'finalized')
          AND candidate.climb_pda = climb.pda
          AND candidate.canon_commitment_hex = climb.canon_commitment_hex
          AND candidate.commitment_hash_hex = climb.commitment_hash_hex
        ORDER BY CASE candidate.activation_status
            WHEN 'finalized' THEN 1
            WHEN 'confirmed' THEN 2
            ELSE 3
        END
        LIMIT 1
    ) AS activation ON TRUE
    LEFT JOIN public.indexed_vault_activations AS chain_activation
      ON chain_activation.vault_id = activation.vault_id
     AND chain_activation.pda = activation.vault_activation_pda
     AND activation.vault_id = vault.id
     AND activation.vault_pda = vault.pda
     AND chain_activation.is_active IS TRUE
     AND chain_activation.seed_generation = 2
     AND chain_activation.seed_completions_written = 0
     AND chain_activation.leaderboard_seeded IS TRUE
     AND chain_activation.matched_users = 0
     AND chain_activation.matched_completions = 0
     AND chain_activation.created_at > 0
     AND chain_activation.created_at = chain_activation.activated_at
     AND chain_activation.created_at = chain_activation.last_seed_at
     AND chain_activation.created_at = chain_activation.seed_cutoff_at
     AND lower(btrim(chain_activation.evidence_hash::text)) ~ '^[0-9a-f]{64}$'
     AND lower(btrim(chain_activation.evidence_hash::text)) <> repeat('0', 64)
     AND activation.constructor_evidence_verified IS TRUE
     AND lower(btrim(chain_activation.evidence_hash::text))
         = activation.constructor_evidence_hash;
END;
$$;

CREATE OR REPLACE FUNCTION public.confirm_canon_vault_activation(
    p_preparation_id UUID,
    p_creator_wallet TEXT,
    p_tx_signature TEXT,
    p_prepared_message_hash TEXT
)
RETURNS TABLE(preparation_id UUID, activation_status TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.canon_vault_activations%ROWTYPE;
BEGIN
    IF p_tx_signature IS NULL
       OR p_tx_signature !~ '^[1-9A-HJ-NP-Za-km-z]{64,88}$'
       OR p_prepared_message_hash IS NULL
       OR p_prepared_message_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'canonical activation confirmation evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_row
    FROM public.canon_vault_activations AS activation
    WHERE activation.id = p_preparation_id
      AND activation.creator_wallet = p_creator_wallet
    FOR UPDATE;
    IF NOT FOUND OR v_row.activation_status NOT IN ('reserved', 'confirmed', 'finalized') THEN
        RAISE EXCEPTION 'canon activation preparation is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF (v_row.tx_signature IS NOT NULL AND v_row.tx_signature <> p_tx_signature)
       OR (
           v_row.prepared_message_hash IS NOT NULL
           AND v_row.prepared_message_hash <> p_prepared_message_hash
       ) THEN
        RAISE EXCEPTION 'canon activation transaction conflicts with prior confirmation'
            USING ERRCODE = '23505';
    END IF;
    UPDATE public.canon_vault_activations AS activation
    SET activation_status = CASE
            WHEN activation.activation_status = 'reserved' THEN 'confirmed'
            ELSE activation.activation_status
        END,
        tx_signature = COALESCE(activation.tx_signature, p_tx_signature),
        prepared_message_hash = COALESCE(
            activation.prepared_message_hash, p_prepared_message_hash
        ),
        confirmed_at = COALESCE(activation.confirmed_at, now()),
        updated_at = now()
    WHERE activation.id = p_preparation_id
    RETURNING activation.id, activation.activation_status
    INTO preparation_id, activation_status;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_canon_vault_activation(
    p_climb_pda TEXT,
    p_vault_pda TEXT,
    p_chain_slot BIGINT,
    p_constructor_evidence_hash TEXT
)
RETURNS TABLE(preparation_id UUID, activation_status TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.canon_vault_activations%ROWTYPE;
BEGIN
    IF p_chain_slot IS NULL OR p_chain_slot < 0
       OR p_constructor_evidence_hash IS NULL
       OR p_constructor_evidence_hash !~ '^[0-9a-f]{64}$'
       OR p_constructor_evidence_hash = repeat('0', 64) THEN
        RAISE EXCEPTION 'canonical Vault projection slot is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_row
    FROM public.canon_vault_activations AS activation
    WHERE activation.climb_pda = p_climb_pda
      AND activation.vault_pda = p_vault_pda
      AND activation.activation_status IN ('confirmed', 'finalized')
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'confirmed canon activation is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF v_row.constructor_evidence_hash IS NOT NULL
       AND v_row.constructor_evidence_hash <> p_constructor_evidence_hash THEN
        RAISE EXCEPTION 'canonical constructor evidence conflicts with finalization'
            USING ERRCODE = '23505';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.indexed_climbs AS climb
        JOIN public.indexed_vaults AS vault
          ON vault.climb_pda = climb.pda
         AND vault.canon_climb_id = climb.canon_climb_id
         AND vault.signature_hex = climb.canon_commitment_hex
         AND vault.signature_hash_hex = climb.commitment_hash_hex
         AND vault.canon_commitment_hex = climb.canon_commitment_hex
         AND vault.canon_binding_status = 'active'
        JOIN public.indexed_vault_activations AS chain_activation
          ON chain_activation.vault_id = vault.id
         AND chain_activation.pda = v_row.vault_activation_pda
         AND chain_activation.is_active IS TRUE
         AND chain_activation.seed_generation = 2
         AND chain_activation.seed_completions_written = 0
         AND chain_activation.leaderboard_seeded IS TRUE
         AND chain_activation.matched_users = 0
         AND chain_activation.matched_completions = 0
         AND chain_activation.created_at > 0
         AND chain_activation.created_at = chain_activation.activated_at
         AND chain_activation.created_at = chain_activation.last_seed_at
         AND chain_activation.created_at = chain_activation.seed_cutoff_at
         AND lower(btrim(chain_activation.evidence_hash::text))
             = p_constructor_evidence_hash
        WHERE climb.pda = v_row.climb_pda
          AND climb.canon_climb_id = v_row.canon_climb_id
          AND climb.canon_commitment_hex = v_row.canon_commitment_hex
          AND climb.commitment_hash_hex = v_row.commitment_hash_hex
          AND climb.vault_pda = v_row.vault_pda
          AND vault.pda = v_row.vault_pda
          AND vault.id = v_row.vault_id
          AND vault.chain_slot = p_chain_slot
    ) THEN
        RAISE EXCEPTION 'indexed Climb to Vault binding is incomplete'
            USING ERRCODE = '23514';
    END IF;
    UPDATE public.canon_vault_activations AS activation
    SET activation_status = 'finalized',
        chain_slot = COALESCE(activation.chain_slot, p_chain_slot),
        constructor_evidence_hash = p_constructor_evidence_hash,
        constructor_evidence_verified = TRUE,
        constructor_verified_at = COALESCE(activation.constructor_verified_at, now()),
        finalized_at = COALESCE(activation.finalized_at, now()),
        updated_at = now()
    WHERE activation.id = v_row.id
    RETURNING activation.id, activation.activation_status
    INTO preparation_id, activation_status;
    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public.release_canon_vault_activation(
    p_preparation_id UUID,
    p_creator_wallet TEXT,
    p_chain_absence_confirmed BOOLEAN,
    p_observed_finalized_slot BIGINT,
    p_observed_finalized_block_height BIGINT,
    p_reason TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.canon_vault_activations%ROWTYPE;
BEGIN
    IF p_chain_absence_confirmed IS NOT TRUE
       OR p_observed_finalized_slot IS NULL
       OR p_observed_finalized_slot < 0
       OR p_observed_finalized_block_height IS NULL
       OR p_observed_finalized_block_height < 0 THEN
        RAISE EXCEPTION 'explicit finalized on-chain absence is required to release reservation'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_row
    FROM public.canon_vault_activations AS activation
    WHERE activation.id = p_preparation_id
      AND activation.creator_wallet = p_creator_wallet
      AND activation.activation_status IN ('reserved', 'confirmed')
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF NOT (p_observed_finalized_block_height > v_row.last_valid_block_height) THEN
        RAISE EXCEPTION 'prepared transaction expiry must be finalized before release'
            USING ERRCODE = '23514';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'reservation release reason is required'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.indexed_climbs AS climb
        WHERE climb.canon_climb_id = v_row.canon_climb_id
          AND climb.pda = v_row.climb_pda
          AND climb.canon_commitment_hex = v_row.canon_commitment_hex
          AND climb.commitment_hash_hex = v_row.commitment_hash_hex
          AND climb.vault_pda IS NULL
          AND climb.quarantined IS FALSE
    ) THEN
        RAISE EXCEPTION 'exact source Climb must remain unbound before release'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.indexed_vaults AS vault
        WHERE vault.id = v_row.vault_id
           OR vault.pda = v_row.vault_pda
           OR (
               vault.canon_climb_id = v_row.canon_climb_id
               AND vault.canon_binding_status = 'active'
           )
    ) THEN
        RAISE EXCEPTION 'indexed Climb to Vault binding must be absent before release'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.indexed_vault_activations AS chain_activation
        WHERE chain_activation.vault_id = v_row.vault_id
           OR chain_activation.pda = v_row.vault_activation_pda
    ) THEN
        RAISE EXCEPTION 'indexed VaultActivation must be absent before release'
            USING ERRCODE = '23514';
    END IF;
    UPDATE public.canon_vault_activations AS activation
    SET activation_status = 'released',
        failure_reason = p_reason,
        absence_observed_slot = p_observed_finalized_slot,
        absence_observed_block_height = p_observed_finalized_block_height,
        released_at = now(),
        updated_at = now()
    WHERE activation.id = v_row.id;
    RETURN FOUND;
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_committed_canon_climb() FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_committed_canon_successor() FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.freeze_committed_canon_corridor_cell() FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.reserve_canon_vault_activation(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, BIGINT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.get_canon_vault_preparation(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.get_canon_vault_release_candidate(BIGINT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.get_canon_climb_runtime_states(UUID[])
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.confirm_canon_vault_activation(UUID, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.finalize_canon_vault_activation(TEXT, TEXT, BIGINT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.release_canon_vault_activation(
    UUID, TEXT, BOOLEAN, BIGINT, BIGINT, TEXT
)
    FROM PUBLIC, anon, authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.reserve_canon_vault_activation(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BIGINT, TEXT, TEXT, TEXT, BIGINT
) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_canon_vault_preparation(UUID, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.get_canon_vault_release_candidate(BIGINT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.get_canon_climb_runtime_states(UUID[])
    TO service_role;
GRANT EXECUTE ON FUNCTION public.confirm_canon_vault_activation(UUID, TEXT, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.release_canon_vault_activation(
    UUID, TEXT, BOOLEAN, BIGINT, BIGINT, TEXT
)
    TO service_role;

COMMENT ON TABLE public.canon_vault_activations IS
    'Private exact-row reservation and finalized V4-B Climb to Vault binding authority.';
COMMENT ON TABLE public.indexed_climbs IS
    'Finalized V4-B Climb accounts resolved to one immutable ratified registry row.';
COMMENT ON TABLE public.canon_indexer_quarantine IS
    'Malformed or non-V4-B Climb and Vault accounts withheld from canonical projections.';
COMMENT ON TABLE public.canon_indexer_pending IS
    'Exact V4-B Vault accounts awaiting a finalized Climb projection or backend confirmation.';
