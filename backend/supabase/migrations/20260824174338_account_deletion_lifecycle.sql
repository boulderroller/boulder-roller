-- Trustworthy, durable account-deletion lifecycle.
--
-- Completion is an atomic database fact.  Legacy rows are never promoted to
-- completed because the previous worker swallowed failures and tombstoned the
-- wallet before authoritative completion.

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE SCHEMA IF NOT EXISTS br_private;
REVOKE ALL ON SCHEMA br_private FROM PUBLIC, anon, authenticated, service_role;

-- pgcrypto is relocatable and may already be installed in public (or another
-- extension schema). Bind private wrappers to the installed namespace instead
-- of assuming CREATE EXTENSION IF NOT EXISTS moved it.
DO $account_deletion_pgcrypto$
DECLARE
    v_pgcrypto_schema TEXT;
BEGIN
    SELECT namespace.nspname
    INTO v_pgcrypto_schema
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = extension.extnamespace
    WHERE extension.extname = 'pgcrypto';

    IF v_pgcrypto_schema IS NULL THEN
        CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
        SELECT namespace.nspname
        INTO STRICT v_pgcrypto_schema
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'pgcrypto';
    END IF;

    EXECUTE pg_catalog.format(
        'CREATE OR REPLACE FUNCTION br_private.account_deletion_random_bytes(integer) '
        'RETURNS bytea LANGUAGE sql VOLATILE SET search_path = '''' AS %L',
        pg_catalog.format('SELECT %I.gen_random_bytes($1)', v_pgcrypto_schema)
    );
    EXECUTE pg_catalog.format(
        'CREATE OR REPLACE FUNCTION br_private.account_deletion_hmac(bytea, bytea, text) '
        'RETURNS bytea LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = '''' AS %L',
        pg_catalog.format('SELECT %I.hmac($1, $2, $3)', v_pgcrypto_schema)
    );
END;
$account_deletion_pgcrypto$;

-- The wallet/tombstone binding must be verifiable by the database itself.
-- A caller-supplied HMAC is only an assertion and can be swapped to evade a
-- tombstone. This singleton key is database-private, backup-stable, and never
-- exposed through PostgREST or to service_role.
CREATE TABLE IF NOT EXISTS br_private.account_deletion_keyring (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    hmac_key BYTEA NOT NULL CHECK (pg_catalog.octet_length(hmac_key) >= 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON br_private.account_deletion_keyring
    FROM PUBLIC, anon, authenticated, service_role;
INSERT INTO br_private.account_deletion_keyring (singleton, hmac_key)
VALUES (TRUE, br_private.account_deletion_random_bytes(32))
ON CONFLICT (singleton) DO NOTHING;

-- A retention decision must not be copied independently into blocker,
-- anonymization and completion-verification code.  This private registry is
-- the authority for relations where live rows block deletion while historical
-- rows are safe only after their identity has been scrubbed.
CREATE TABLE IF NOT EXISTS br_private.account_deletion_identity_policy (
    table_name TEXT NOT NULL,
    identity_column TEXT NOT NULL,
    blocker_predicate TEXT NOT NULL,
    scrub_predicate TEXT NOT NULL,
    residue_match_kind TEXT NOT NULL CHECK (residue_match_kind IN ('wallet_exact')),
    blocker_code TEXT NOT NULL,
    blocker_category TEXT NOT NULL,
    blocker_source TEXT NOT NULL,
    blocker_action TEXT NOT NULL,
    PRIMARY KEY (table_name, identity_column)
);
REVOKE ALL ON br_private.account_deletion_identity_policy
    FROM PUBLIC, anon, authenticated, service_role;
INSERT INTO br_private.account_deletion_identity_policy (
    table_name, identity_column, blocker_predicate, scrub_predicate,
    residue_match_kind, blocker_code, blocker_category, blocker_source,
    blocker_action
) VALUES (
    'swanny_seats', 'wallet', 'is_active IS TRUE', 'is_active IS NOT TRUE',
    'wallet_exact', 'stake_remains', 'stake', 'active_local_legend_seat',
    'contact_support'
)
ON CONFLICT (table_name, identity_column) DO UPDATE
SET blocker_predicate = EXCLUDED.blocker_predicate,
    scrub_predicate = EXCLUDED.scrub_predicate,
    residue_match_kind = EXCLUDED.residue_match_kind,
    blocker_code = EXCLUDED.blocker_code,
    blocker_category = EXCLUDED.blocker_category,
    blocker_source = EXCLUDED.blocker_source,
    blocker_action = EXCLUDED.blocker_action;

CREATE OR REPLACE FUNCTION public.br_account_deletion_wallet_fingerprint(
    p_wallet TEXT
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $$
DECLARE
    v_key BYTEA;
BEGIN
    IF p_wallet IS NULL OR p_wallet = '' THEN
        RAISE EXCEPTION 'invalid_account_deletion_wallet'
            USING ERRCODE = '22023';
    END IF;
    SELECT keyring.hmac_key INTO STRICT v_key
    FROM br_private.account_deletion_keyring AS keyring
    WHERE keyring.singleton;
    RETURN pg_catalog.encode(
        br_private.account_deletion_hmac(
            pg_catalog.convert_to(p_wallet, 'UTF8'),
            v_key,
            'sha256'
        ),
        'hex'
    );
END;
$$;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS account_state TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS account_deletion_locked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS anonymous_marker UUID,
    ADD COLUMN IF NOT EXISTS account_deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS account_deletion_request_id UUID;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_account_state_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_account_state_check CHECK (
        account_state IN ('active', 'deletion_pending', 'anonymized')
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_anonymous_marker
    ON public.users (anonymous_marker)
    WHERE anonymous_marker IS NOT NULL;

-- Retained sporting rows must be detached from the deleted ride identifier.
-- These columns are nullable in the current production schema; the ALTERs
-- also make older installations converge on the same contract.
ALTER TABLE IF EXISTS public.segment_efforts
    ALTER COLUMN ride_id DROP NOT NULL,
    ALTER COLUMN effort_score DROP NOT NULL;
ALTER TABLE IF EXISTS public.patterns_climb
    ALTER COLUMN activity_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS public.deletion_requests (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) ON DELETE SET NULL,
    wallet TEXT,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'legacy_unverified',
    error_message TEXT
);

-- A prior 152 replay may already have installed the generated projection;
-- remove it before converging the status type below.
ALTER TABLE public.deletion_requests
    DROP COLUMN IF EXISTS retryable;

ALTER TABLE public.deletion_requests
    ALTER COLUMN user_id DROP NOT NULL,
    ALTER COLUMN wallet DROP NOT NULL,
    ALTER COLUMN status TYPE VARCHAR(32),
    ALTER COLUMN status SET DEFAULT 'legacy_unverified',
    ADD COLUMN IF NOT EXISTS wallet_fingerprint TEXT,
    ADD COLUMN IF NOT EXISTS status_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS contract_version TEXT NOT NULL DEFAULT 'account-deletion.v1',
    ADD COLUMN IF NOT EXISTS blockers JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS failure_code TEXT,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS worker_id UUID,
    ADD COLUMN IF NOT EXISTS worker_lease_token UUID,
    ADD COLUMN IF NOT EXISTS worker_lease_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS storage_paths JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS storage_receipts JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS storage_authorized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS storage_completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS unuploaded_rides_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS local_review_receipt JSONB,
    ADD COLUMN IF NOT EXISTS preflight_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS preflight_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completion_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp();

-- Every historical state came from the unsafe fail-soft implementation.
UPDATE public.deletion_requests
SET status = 'legacy_unverified',
    contract_version = 'account-deletion.legacy',
    failure_code = COALESCE(failure_code, 'legacy_completion_unverified'),
    worker_id = NULL,
    worker_lease_token = NULL,
    worker_lease_until = NULL,
    completion_verified_at = NULL,
    updated_at = clock_timestamp()
WHERE completion_verified_at IS NULL
  AND (
    status IS NULL
    OR status NOT IN (
    'queued', 'processing', 'blocked', 'failed_retryable',
    'needs_support', 'completed', 'legacy_unverified'
    )
    OR status IN ('pending', 'failed', 'completed')
    OR wallet_fingerprint IS NULL
    OR status_token_hash IS NULL
    OR (
      status = 'processing'
      AND (worker_lease_token IS NULL OR worker_lease_until IS NULL)
    )
  );

ALTER TABLE public.deletion_requests
    ALTER COLUMN status SET NOT NULL;

ALTER TABLE public.deletion_requests
    DROP CONSTRAINT IF EXISTS deletion_requests_status_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_phase_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_blockers_array_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_storage_paths_array_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_storage_receipts_object_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_attempt_count_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_wallet_fingerprint_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_status_token_hash_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_lease_check,
    DROP CONSTRAINT IF EXISTS deletion_requests_completed_check;

-- Phase was a write-only shadow of these durable timestamps. Retryability is
-- a status projection, so make it impossible for writers to contradict status.
ALTER TABLE public.deletion_requests
    DROP COLUMN IF EXISTS request_phase;
ALTER TABLE public.deletion_requests
    ADD COLUMN retryable BOOLEAN GENERATED ALWAYS AS (
        status IN ('queued', 'processing', 'blocked', 'failed_retryable')
        AND storage_authorized_at IS NULL
    ) STORED;

ALTER TABLE public.deletion_requests
    ADD CONSTRAINT deletion_requests_status_check CHECK (
        status IN (
            'queued', 'processing', 'blocked', 'failed_retryable',
            'needs_support', 'completed', 'legacy_unverified'
        )
    ),
    ADD CONSTRAINT deletion_requests_blockers_array_check CHECK (
        jsonb_typeof(blockers) = 'array'
    ),
    ADD CONSTRAINT deletion_requests_storage_paths_array_check CHECK (
        jsonb_typeof(storage_paths) = 'array'
    ),
    ADD CONSTRAINT deletion_requests_storage_receipts_object_check CHECK (
        jsonb_typeof(storage_receipts) = 'object'
    ),
    ADD CONSTRAINT deletion_requests_attempt_count_check CHECK (attempt_count >= 0),
    ADD CONSTRAINT deletion_requests_wallet_fingerprint_check CHECK (
        wallet_fingerprint IS NULL OR wallet_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT deletion_requests_status_token_hash_check CHECK (
        status_token_hash IS NULL OR status_token_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT deletion_requests_lease_check CHECK (
        (worker_id IS NULL AND worker_lease_token IS NULL AND worker_lease_until IS NULL)
        OR
        (worker_id IS NOT NULL AND worker_lease_token IS NOT NULL AND worker_lease_until IS NOT NULL)
    ),
    ADD CONSTRAINT deletion_requests_completed_check CHECK (
        status <> 'completed'
        OR (
            completed_at IS NOT NULL
            AND completion_verified_at IS NOT NULL
            AND wallet IS NULL
            AND retryable = FALSE
            AND unuploaded_rides_acknowledged = TRUE
            AND storage_authorized_at IS NOT NULL
            AND storage_completed_at IS NOT NULL
        )
    );

DROP INDEX IF EXISTS public.idx_deletion_requests_one_active_per_user;
CREATE UNIQUE INDEX idx_deletion_requests_one_active_per_user
    ON public.deletion_requests (user_id)
    WHERE user_id IS NOT NULL
      AND status IN (
          'queued', 'processing', 'blocked', 'failed_retryable', 'needs_support'
      );
CREATE INDEX IF NOT EXISTS idx_deletion_requests_recovery
    ON public.deletion_requests (status, next_attempt_at, worker_lease_until, requested_at);
CREATE INDEX IF NOT EXISTS idx_deletion_requests_write_fence_user
    ON public.deletion_requests (user_id)
    WHERE user_id IS NOT NULL
      AND (
          status IN ('queued', 'processing')
          OR (
              storage_authorized_at IS NOT NULL
              AND status IN ('blocked', 'failed_retryable', 'needs_support')
          )
      );
CREATE INDEX IF NOT EXISTS idx_deletion_requests_write_fence_wallet
    ON public.deletion_requests (wallet)
    WHERE wallet IS NOT NULL
      AND (
          status IN ('queued', 'processing')
          OR (
              storage_authorized_at IS NOT NULL
              AND status IN ('blocked', 'failed_retryable', 'needs_support')
          )
      );

-- New tombstones contain only a database-private HMAC fingerprint. Never copy the raw
-- wallet from the legacy table into this relation.
CREATE TABLE IF NOT EXISTS public.deleted_account_tombstones (
    wallet_fingerprint TEXT PRIMARY KEY
        CHECK (wallet_fingerprint ~ '^[0-9a-f]{64}$'),
    anonymous_marker UUID NOT NULL,
    deletion_request_id UUID NOT NULL UNIQUE,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION public.br_jsonb_replace_exact_string(
    p_value JSONB,
    p_from TEXT,
    p_to TEXT
)
RETURNS JSONB
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = ''
AS $$
    SELECT CASE pg_catalog.jsonb_typeof(p_value)
        WHEN 'string' THEN CASE
            WHEN p_value = pg_catalog.to_jsonb(p_from)
                THEN pg_catalog.to_jsonb(p_to)
            ELSE p_value
        END
        WHEN 'array' THEN (
            SELECT COALESCE(
                pg_catalog.jsonb_agg(
                    public.br_jsonb_replace_exact_string(item.value, p_from, p_to)
                    ORDER BY item.ordinality
                ),
                '[]'::JSONB
            )
            FROM pg_catalog.jsonb_array_elements(p_value)
                WITH ORDINALITY AS item(value, ordinality)
        )
        WHEN 'object' THEN (
            SELECT COALESCE(
                pg_catalog.jsonb_object_agg(
                    entry.key,
                    public.br_jsonb_replace_exact_string(entry.value, p_from, p_to)
                ),
                '{}'::JSONB
            )
            FROM pg_catalog.jsonb_each(p_value) AS entry(key, value)
        )
        ELSE p_value
    END
$$;

ALTER TABLE public.deletion_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.deleted_account_tombstones ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.deleted_wallets ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.deletion_requests FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.deleted_account_tombstones FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.deleted_wallets FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.deletion_requests FROM service_role;
REVOKE ALL ON public.deleted_account_tombstones FROM service_role;
REVOKE ALL ON public.deleted_wallets FROM service_role;
GRANT SELECT ON public.deletion_requests TO service_role;

-- Every authority that can introduce the original wallet takes the same
-- transaction-scoped lock. Each authority derives the lock and tombstone key
-- from the database-private keyring and raw wallet; callers never supply it.
CREATE OR REPLACE FUNCTION public.br_lock_account_deletion_wallet(
    p_wallet_fingerprint TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF p_wallet_fingerprint IS NULL
       OR p_wallet_fingerprint !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid_account_deletion_wallet_fingerprint'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'account-deletion-wallet' || pg_catalog.chr(31) || p_wallet_fingerprint,
            0
        )
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.br_is_account_deleted(p_wallet TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $$
DECLARE
    v_fingerprint TEXT;
BEGIN
    v_fingerprint := public.br_account_deletion_wallet_fingerprint(p_wallet);
    RETURN EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy
        WHERE legacy.wallet = p_wallet
    );
END;
$$;

-- Authentication resolves tombstone precedence and the surviving user row in
-- one wallet-fenced database operation. A legacy tombstone must win even when
-- an interrupted old deletion job left an apparently active users row behind.
CREATE OR REPLACE FUNCTION public.br_get_auth_account_authority(p_wallet TEXT)
RETURNS TABLE(user_id UUID, account_state TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_fingerprint TEXT;
    v_user_id UUID;
    v_account_state TEXT;
BEGIN
    IF p_wallet IS NULL OR p_wallet = '' THEN
        RAISE EXCEPTION 'invalid_auth_account_wallet' USING ERRCODE = '22023';
    END IF;
    v_fingerprint := public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_fingerprint);

    IF EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy
        WHERE legacy.wallet = p_wallet
    ) THEN
        RETURN QUERY SELECT NULL::UUID, 'anonymized'::TEXT;
        RETURN;
    END IF;

    SELECT "user".id, "user".account_state
    INTO v_user_id, v_account_state
    FROM public.users AS "user"
    WHERE "user".wallet = p_wallet;
    RETURN QUERY SELECT v_user_id, v_account_state;
END;
$$;

-- User creation is a single fingerprint-fenced operation.  Direct INSERTs
-- are rejected by br_user_account_lifecycle_fence below.
CREATE OR REPLACE FUNCTION public.br_get_or_create_active_user(
    p_candidate_user_id UUID,
    p_wallet TEXT,
    p_email TEXT DEFAULT NULL
)
RETURNS TABLE(user_id UUID, was_created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_user_id UUID;
    v_was_created BOOLEAN := FALSE;
    v_account_state TEXT;
    v_existing_email TEXT;
    v_authoritative_fingerprint TEXT;
BEGIN
    IF p_candidate_user_id IS NULL OR p_wallet IS NULL OR p_wallet = '' THEN
        RAISE EXCEPTION 'invalid_account_user_candidate' USING ERRCODE = '22023';
    END IF;
    v_authoritative_fingerprint :=
        public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_authoritative_fingerprint);

    IF EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_authoritative_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy WHERE legacy.wallet = p_wallet
    ) THEN
        RAISE EXCEPTION 'account_deleted' USING ERRCODE = '55000';
    END IF;

    SELECT "user".id, "user".account_state, "user".email
    INTO v_user_id, v_account_state, v_existing_email
    FROM public.users AS "user"
    WHERE "user".wallet = p_wallet
    FOR UPDATE;
    IF FOUND THEN
        IF v_account_state <> 'active' THEN
            RAISE EXCEPTION 'account_deletion_pending' USING ERRCODE = '55000';
        END IF;
        IF p_email IS NOT NULL AND p_email <> ''
           AND v_existing_email IS DISTINCT FROM p_email THEN
            UPDATE public.users SET email = p_email, updated_at = clock_timestamp()
            WHERE id = v_user_id;
        END IF;
        RETURN QUERY SELECT v_user_id, FALSE;
        RETURN;
    END IF;

    PERFORM pg_catalog.set_config('app.account_deletion_user_create', 'on', TRUE);
    INSERT INTO public.users (id, wallet, email)
    VALUES (p_candidate_user_id, p_wallet, COALESCE(p_email, ''))
    ON CONFLICT (wallet) DO NOTHING
    RETURNING id INTO v_user_id;
    v_was_created := FOUND;
    PERFORM pg_catalog.set_config('app.account_deletion_user_create', '', TRUE);
    IF v_was_created THEN
        RETURN QUERY SELECT v_user_id, TRUE;
        RETURN;
    END IF;

    SELECT "user".id, "user".account_state
    INTO v_user_id, v_account_state
    FROM public.users AS "user"
    WHERE "user".wallet = p_wallet
    FOR UPDATE;
    IF NOT FOUND OR v_account_state <> 'active' THEN
        RAISE EXCEPTION 'account_deletion_pending' USING ERRCODE = '55000';
    END IF;
    RETURN QUERY SELECT v_user_id, FALSE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_user_account_lifecycle_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_lifecycle_request TEXT := pg_catalog.current_setting(
        'app.account_deletion_request_id', TRUE
    );
    v_user_create TEXT := pg_catalog.current_setting(
        'app.account_deletion_user_create', TRUE
    );
BEGIN
    IF v_lifecycle_request IS NOT NULL AND v_lifecycle_request <> '' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF v_user_create IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'account_user_create_requires_fingerprint_fence'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.account_state = 'deletion_pending'
       AND NEW.account_state = 'deletion_pending'
       AND (
           pg_catalog.to_jsonb(NEW)
               - ARRAY['follower_count', 'following_count', 'updated_at']
       ) = (
           pg_catalog.to_jsonb(OLD)
               - ARRAY['follower_count', 'following_count', 'updated_at']
       ) THEN
        -- Counterparty social actions may update only denormalized counters on
        -- the pending rider. The acting rider is fenced on the social row.
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE'
       OR OLD.account_state <> 'active'
       OR NEW.account_state <> 'active'
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.wallet IS DISTINCT FROM OLD.wallet
       OR NEW.anonymous_marker IS DISTINCT FROM OLD.anonymous_marker
       OR NEW.account_deleted_at IS DISTINCT FROM OLD.account_deleted_at
       OR NEW.account_deletion_locked_at IS DISTINCT FROM OLD.account_deletion_locked_at
       OR NEW.account_deletion_request_id IS DISTINCT FROM OLD.account_deletion_request_id THEN
        RAISE EXCEPTION 'account_user_write_fenced' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS account_deletion_user_lifecycle_fence ON public.users;
CREATE TRIGGER account_deletion_user_lifecycle_fence
BEFORE INSERT OR UPDATE OR DELETE ON public.users
FOR EACH ROW EXECUTE FUNCTION public.br_user_account_lifecycle_fence();

-- Nonces are the one identity write that must work before a user exists.
-- Both issue and consume share the database-derived finalizer wallet lock;
-- direct nonce writes are rejected by the fence.
CREATE OR REPLACE FUNCTION public.br_issue_auth_nonce(
    p_nonce_id UUID,
    p_wallet TEXT,
    p_nonce TEXT,
    p_issued_at TIMESTAMPTZ,
    p_expires_at TIMESTAMPTZ,
    p_device_id TEXT
)
RETURNS SETOF public.auth_nonces
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_row public.auth_nonces%ROWTYPE;
    v_account_state TEXT;
    v_authoritative_fingerprint TEXT;
BEGIN
    IF p_nonce_id IS NULL OR p_wallet IS NULL OR p_wallet = ''
       OR p_nonce IS NULL OR p_nonce = '' OR p_issued_at IS NULL
       OR p_expires_at IS NULL OR p_expires_at <= p_issued_at THEN
        RAISE EXCEPTION 'invalid_auth_nonce' USING ERRCODE = '22023';
    END IF;
    v_authoritative_fingerprint :=
        public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_authoritative_fingerprint);
    IF EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_authoritative_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy WHERE legacy.wallet = p_wallet
    ) THEN
        RAISE EXCEPTION 'account_deleted' USING ERRCODE = '55000';
    END IF;
    SELECT "user".account_state INTO v_account_state
    FROM public.users AS "user" WHERE "user".wallet = p_wallet
    FOR KEY SHARE;
    IF FOUND AND v_account_state <> 'active' THEN
        RAISE EXCEPTION 'account_deletion_pending' USING ERRCODE = '55000';
    END IF;
    PERFORM pg_catalog.set_config('app.account_deletion_nonce_write', 'on', TRUE);
    INSERT INTO public.auth_nonces (
        id, wallet, nonce, issued_at, expires_at, device_id
    ) VALUES (
        p_nonce_id, p_wallet, p_nonce, p_issued_at, p_expires_at, p_device_id
    ) RETURNING * INTO v_row;
    PERFORM pg_catalog.set_config('app.account_deletion_nonce_write', '', TRUE);
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_consume_auth_nonce(
    p_nonce_id UUID,
    p_wallet TEXT,
    p_used_at TIMESTAMPTZ
)
RETURNS TABLE(consumed BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_account_state TEXT;
    v_consumed BOOLEAN := FALSE;
    v_authoritative_fingerprint TEXT;
BEGIN
    IF p_nonce_id IS NULL OR p_wallet IS NULL OR p_wallet = '' OR p_used_at IS NULL THEN
        RAISE EXCEPTION 'invalid_auth_nonce_consumption' USING ERRCODE = '22023';
    END IF;
    v_authoritative_fingerprint :=
        public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_authoritative_fingerprint);
    IF EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_authoritative_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy WHERE legacy.wallet = p_wallet
    ) THEN
        RAISE EXCEPTION 'account_deleted' USING ERRCODE = '55000';
    END IF;
    SELECT "user".account_state INTO v_account_state
    FROM public.users AS "user" WHERE "user".wallet = p_wallet
    FOR KEY SHARE;
    IF FOUND AND v_account_state <> 'active' THEN
        RAISE EXCEPTION 'account_deletion_pending' USING ERRCODE = '55000';
    END IF;
    PERFORM pg_catalog.set_config('app.account_deletion_nonce_write', 'on', TRUE);
    UPDATE public.auth_nonces SET used_at = p_used_at
    WHERE id = p_nonce_id AND wallet = p_wallet AND used_at IS NULL;
    v_consumed := FOUND;
    PERFORM pg_catalog.set_config('app.account_deletion_nonce_write', '', TRUE);
    RETURN QUERY SELECT v_consumed;
END;
$$;

-- Migration 145 owns invite-code behavior (including optional arguments and
-- the empty-wallet FALSE result). Enforce deletion lifecycle at the one raw
-- wallet write instead of copying that RPC body here.
CREATE OR REPLACE FUNCTION public.br_account_deletion_assert_wallet_write_allowed(
    p_wallet TEXT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_account_state TEXT;
    v_authoritative_fingerprint TEXT;
BEGIN
    IF p_wallet IS NULL OR p_wallet = '' THEN
        RETURN;
    END IF;
    v_authoritative_fingerprint :=
        public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_authoritative_fingerprint);
    IF EXISTS (
        SELECT 1 FROM public.deleted_account_tombstones AS tombstone
        WHERE tombstone.wallet_fingerprint = v_authoritative_fingerprint
    ) OR EXISTS (
        SELECT 1 FROM public.deleted_wallets AS legacy WHERE legacy.wallet = p_wallet
    ) THEN
        RAISE EXCEPTION 'account_deleted' USING ERRCODE = '55000';
    END IF;
    SELECT "user".account_state INTO v_account_state
    FROM public.users AS "user" WHERE "user".wallet = p_wallet
    FOR KEY SHARE;
    IF FOUND AND v_account_state <> 'active' THEN
        RAISE EXCEPTION 'account_deletion_pending' USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_account_deletion_invite_usage_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    PERFORM public.br_account_deletion_assert_wallet_write_allowed(NEW.wallet);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS account_deletion_invite_usage_fence
    ON public.invite_code_usage;
CREATE TRIGGER account_deletion_invite_usage_fence
BEFORE INSERT OR UPDATE OF wallet ON public.invite_code_usage
FOR EACH ROW EXECUTE FUNCTION public.br_account_deletion_invite_usage_fence();

-- A service-role writer can bypass RLS, so a trigger fence is required.  The
-- finalizer sets a transaction-local request id to perform its own scrub.
CREATE OR REPLACE FUNCTION public.account_deletion_write_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_row JSONB;
    v_rows JSONB[];
    v_user_id UUID;
    v_candidate_user_id UUID;
    v_candidate_key TEXT;
    v_actor_keys TEXT[];
    v_candidate_wallet TEXT;
    v_ride_id UUID;
    v_wallet TEXT;
    v_request_id TEXT := pg_catalog.current_setting(
        'app.account_deletion_request_id',
        TRUE
    );
    v_nonce_write TEXT := pg_catalog.current_setting(
        'app.account_deletion_nonce_write',
        TRUE
    );
    v_has_wallet_fields BOOLEAN := CASE
        WHEN TG_NARGS > 0 THEN TG_ARGV[0]::BOOLEAN
        ELSE TRUE
    END;
    v_account_state TEXT;
BEGIN
    IF v_request_id IS NOT NULL AND v_request_id <> '' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'auth_nonces' AND v_nonce_write IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'auth_nonce_write_requires_fingerprint_fence'
            USING ERRCODE = '55000';
    END IF;
    IF NOT public.br_account_deletion_write_fence_active()
       AND (
           NOT v_has_wallet_fields
           OR (
               NOT EXISTS (SELECT 1 FROM public.deleted_account_tombstones)
               AND NOT EXISTS (SELECT 1 FROM public.deleted_wallets)
           )
       ) THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    v_rows := CASE TG_OP
        WHEN 'UPDATE' THEN ARRAY[
            pg_catalog.to_jsonb(OLD), pg_catalog.to_jsonb(NEW)
        ]::JSONB[]
        WHEN 'DELETE' THEN ARRAY[pg_catalog.to_jsonb(OLD)]::JSONB[]
        ELSE ARRAY[pg_catalog.to_jsonb(NEW)]::JSONB[]
    END;

    -- UPDATE checks both ownership snapshots. Otherwise a service-role writer
    -- could move a row away from a deletion-pending owner and evade both the
    -- deletion fence and the completion residue scan.
    FOREACH v_row IN ARRAY v_rows
    LOOP
        v_user_id := NULL;
        v_candidate_user_id := NULL;
        v_ride_id := NULL;
        v_wallet := NULL;
        v_account_state := NULL;

        -- A completed deletion's original wallet may never be reintroduced by
        -- a late projector, indexer or service-role write. Check every known
        -- wallet-shaped field in both OLD and NEW update snapshots against the
        -- database-private tombstone authority.
        IF TG_OP <> 'DELETE' THEN
            FOREACH v_candidate_key IN ARRAY ARRAY[
                'protocol_wallet', 'wallet', 'user_pubkey', 'owner_pubkey',
                'rider_pubkey', 'staker', 'staker_wallet', 'creator_wallet',
                'reviewer_wallet', 'admin_wallet', 'minter', 'kom_holder',
                'holder', 'previous_holder',
                'winner', 'winner_wallet', 'runner_up', 'runner_up_wallet',
                'bumped_by_wallet', 'flagged_by', 'disputed_wallet', 'resolved_by'
            ]
            LOOP
                v_candidate_wallet := NULLIF(v_row ->> v_candidate_key, '');
                IF v_candidate_wallet IS NULL THEN CONTINUE; END IF;
                IF v_wallet IS NULL THEN v_wallet := v_candidate_wallet; END IF;
                IF EXISTS (
                    SELECT 1 FROM public.deleted_account_tombstones AS tombstone
                    WHERE tombstone.wallet_fingerprint =
                        public.br_account_deletion_wallet_fingerprint(v_candidate_wallet)
                ) OR EXISTS (
                    SELECT 1 FROM public.deleted_wallets AS legacy
                    WHERE legacy.wallet = v_candidate_wallet
                ) THEN
                    RAISE EXCEPTION 'account_deleted' USING ERRCODE = '55000';
                END IF;
            END LOOP;
        END IF;

        -- Notification wallet fields identify the recipient, not the actor.
        -- Tombstones above still reject a completed identity, while the actor
        -- UUID below controls whether a pending rider may initiate the write.
        IF TG_TABLE_NAME = 'notifications' THEN
            v_wallet := NULL;
        END IF;

        v_actor_keys := CASE TG_TABLE_NAME
            WHEN 'follows' THEN ARRAY['follower_id']
            WHEN 'notifications' THEN ARRAY['actor_id']
            WHEN 'activities' THEN ARRAY['user_id', 'actor_id']
            WHEN 'social_reports' THEN ARRAY['reporter_id', 'reviewed_by']
            WHEN 'moderation_actions' THEN ARRAY['actor_id']
            WHEN 'system_controls' THEN ARRAY['updated_by']
            ELSE ARRAY[
                'user_id', 'reporter_id', 'reviewed_by', 'actor_id',
                'moderated_by', 'updated_by', 'created_by'
            ]
        END;
        FOREACH v_candidate_key IN ARRAY v_actor_keys
        LOOP
            BEGIN
                v_candidate_user_id := NULLIF(v_row ->> v_candidate_key, '')::UUID;
            EXCEPTION WHEN invalid_text_representation THEN
                v_candidate_user_id := NULL;
            END;
            IF v_candidate_user_id IS NULL THEN
                CONTINUE;
            END IF;
            IF v_user_id IS NULL THEN
                v_user_id := v_candidate_user_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                SELECT "user".account_state INTO v_account_state
                FROM public.users AS "user" WHERE "user".id = v_candidate_user_id
                FOR KEY SHARE;
                IF NOT FOUND
                   OR (
                       v_account_state <> 'active'
                       AND NOT (
                           v_account_state = 'anonymized'
                           AND TG_TABLE_NAME IN ('segment_efforts', 'leaderboard_entries')
                       )
                   ) THEN
                    RAISE EXCEPTION 'account_identity_write_fenced'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
        END LOOP;

        IF TG_OP <> 'DELETE'
           AND TG_TABLE_NAME IN (
               'activity_streams', 'activity_tile_samples', 'gps_points',
               'ride_climb_backfill_reviews', 'patterns_climb', 'patterns_steady',
               'patterns_exploration', 'scored_patterns', 'segment_efforts'
           ) THEN
            BEGIN
                v_ride_id := NULLIF(
                    COALESCE(v_row ->> 'ride_id', v_row ->> 'activity_id'),
                    ''
                )::UUID;
            EXCEPTION WHEN invalid_text_representation THEN
                v_ride_id := NULL;
            END;
            IF v_ride_id IS NOT NULL THEN
                SELECT ride.user_id INTO v_candidate_user_id
                FROM public.rides AS ride WHERE ride.id = v_ride_id
                FOR KEY SHARE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'account_identity_write_fenced'
                        USING ERRCODE = '55000';
                END IF;
                SELECT "user".account_state INTO v_account_state
                FROM public.users AS "user" WHERE "user".id = v_candidate_user_id
                FOR KEY SHARE;
                IF NOT FOUND OR v_account_state <> 'active' THEN
                    RAISE EXCEPTION 'account_identity_write_fenced'
                        USING ERRCODE = '55000';
                END IF;
                IF v_user_id IS NULL THEN
                    v_user_id := v_candidate_user_id;
                END IF;
            END IF;
        END IF;

        IF TG_OP <> 'DELETE' AND v_wallet IS NOT NULL
           AND TG_TABLE_NAME IN (
               'auth_refresh_tokens', 'strava_connections', 'mobile_push_devices',
               'mobile_push_deliveries', 'ios_diagnostics', 'wallet_tile_history',
               'user_profile_snapshots', 'invite_code_usage', 'bot_links',
               'patterns_climb', 'patterns_steady', 'patterns_exploration',
               'scored_patterns', 'vault_leaderboards', 'leaderboard_history',
               'vault_completions', 'distribution_receipts', 'vault_shadow_usdc',
               'wallet_points', 'points_events', 'cal_daily_balances'
           ) THEN
            SELECT "user".account_state INTO v_account_state
            FROM public.users AS "user" WHERE "user".wallet = v_wallet
            FOR KEY SHARE;
            IF NOT FOUND
               OR (
                   v_account_state <> 'active'
                   AND NOT (
                       v_account_state = 'anonymized'
                       AND TG_TABLE_NAME IN (
                           'patterns_climb', 'vault_leaderboards',
                           'leaderboard_history', 'vault_completions',
                           'distribution_receipts', 'vault_shadow_usdc',
                           'wallet_points', 'points_events', 'cal_daily_balances'
                       )
                   )
               ) THEN
                RAISE EXCEPTION 'account_identity_write_fenced'
                    USING ERRCODE = '55000';
            END IF;
        END IF;

        IF v_user_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.deletion_requests AS request
            WHERE request.user_id = v_user_id
              AND (
                  request.status IN ('queued', 'processing')
                  OR (
                      request.storage_authorized_at IS NOT NULL
                      AND request.status IN (
                          'blocked', 'failed_retryable', 'needs_support'
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION 'account_deletion_write_fenced'
                USING ERRCODE = '55000';
        END IF;
        IF v_wallet IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.deletion_requests AS request
            WHERE request.wallet = v_wallet
              AND (
                  request.status IN ('queued', 'processing')
                  OR (
                      request.storage_authorized_at IS NOT NULL
                      AND request.status IN (
                          'blocked', 'failed_retryable', 'needs_support'
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION 'account_deletion_write_fenced'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_account_deletion_write_fence_active()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.deletion_requests AS request
        WHERE request.status IN ('queued', 'processing')
           OR (
               request.storage_authorized_at IS NOT NULL
               AND request.status IN ('blocked', 'failed_retryable', 'needs_support')
           )
    )
$$;

-- High-volume ride-child ingestion pays one set-wise fence per statement. It
-- still takes key-share locks on the owning rider rows, preserving the same
-- serialization with request creation as the row fence.
CREATE OR REPLACE FUNCTION public.account_deletion_ride_write_fence_statement()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_transition TEXT;
    v_ride_column TEXT := TG_ARGV[0];
    v_actor_column TEXT := NULLIF(TG_ARGV[1], '');
    v_unsafe BOOLEAN;
BEGIN
    IF NULLIF(
        pg_catalog.current_setting('app.account_deletion_request_id', TRUE),
        ''
    ) IS NOT NULL THEN
        RETURN NULL;
    END IF;
    IF NOT public.br_account_deletion_write_fence_active() THEN
        RETURN NULL;
    END IF;

    FOREACH v_transition IN ARRAY CASE TG_OP
        WHEN 'INSERT' THEN ARRAY['account_deletion_new_rows']
        WHEN 'DELETE' THEN ARRAY['account_deletion_old_rows']
        ELSE ARRAY['account_deletion_old_rows', 'account_deletion_new_rows']
    END
    LOOP
        EXECUTE pg_catalog.format(
            'SELECT EXISTS ('
            ' SELECT 1 FROM %I AS source '
            ' LEFT JOIN public.rides AS ride ON ride.id = source.%I '
            ' WHERE source.%I IS NOT NULL AND ride.id IS NULL'
            ')',
            v_transition, v_ride_column, v_ride_column
        ) INTO v_unsafe;
        IF v_unsafe THEN
            RAISE EXCEPTION 'account_identity_write_fenced' USING ERRCODE = '55000';
        END IF;

        EXECUTE pg_catalog.format(
            'SELECT 1 FROM %I AS source '
            'JOIN public.rides AS ride ON ride.id = source.%I '
            'JOIN public.users AS owner ON owner.id = ride.user_id '
            'WHERE source.%I IS NOT NULL FOR KEY SHARE OF owner',
            v_transition, v_ride_column, v_ride_column
        );

        EXECUTE pg_catalog.format(
            'SELECT EXISTS ('
            ' SELECT 1 FROM %I AS source '
            ' JOIN public.rides AS ride ON ride.id = source.%I '
            ' LEFT JOIN public.users AS owner ON owner.id = ride.user_id '
            ' WHERE owner.id IS NULL OR owner.account_state <> ''active'' '
            ' OR EXISTS ('
            '   SELECT 1 FROM public.deletion_requests AS request '
            '   WHERE request.user_id = ride.user_id AND ('
            '     request.status IN (''queued'', ''processing'') OR ('
            '       request.storage_authorized_at IS NOT NULL '
            '       AND request.status IN (''blocked'', ''failed_retryable'', ''needs_support'')'
            '     )'
            '   )'
            ' )'
            ')',
            v_transition, v_ride_column
        ) INTO v_unsafe;
        IF v_unsafe THEN
            RAISE EXCEPTION 'account_deletion_write_fenced' USING ERRCODE = '55000';
        END IF;

        IF v_actor_column IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'SELECT EXISTS ('
                ' SELECT 1 FROM %I AS source '
                ' LEFT JOIN public.users AS actor ON actor.id = source.%I '
                ' WHERE source.%I IS NOT NULL '
                ' AND (actor.id IS NULL OR actor.account_state <> ''active'' OR EXISTS ('
                '   SELECT 1 FROM public.deletion_requests AS request '
                '   WHERE request.user_id = source.%I AND ('
                '     request.status IN (''queued'', ''processing'') OR ('
                '       request.storage_authorized_at IS NOT NULL '
                '       AND request.status IN (''blocked'', ''failed_retryable'', ''needs_support'')'
                '     )'
                '   )'
                ' ))'
                ')',
                v_transition, v_actor_column, v_actor_column, v_actor_column
            ) INTO v_unsafe;
            IF v_unsafe THEN
                RAISE EXCEPTION 'account_deletion_write_fenced' USING ERRCODE = '55000';
            END IF;
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$;

DO $$
DECLARE
    v_table TEXT;
    v_spec RECORD;
    v_has_wallet_fields BOOLEAN;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'rides', 'claims', 'vesting_schedules', 'user_state',
        'balance_operations', 'ride_economic_plans', 'economic_events',
        'vault_stakes', 'vault_shadow_usdc', 'scored_patterns',
        'canon_vault_activations', 'vault_creation_handoffs',
        'auth_refresh_tokens', 'auth_nonces', 'auth_identities',
        'strava_connections', 'privacy_zones',
        'ride_media', 'leaderboard_entries',
        'climb_attestations', 'vault_completions',
        'distribution_receipts', 'vault_leaderboards',
        'patterns_climb', 'patterns_steady', 'patterns_exploration',
        'wallet_tile_history', 'user_profile_snapshots',
        'mobile_push_devices', 'mobile_push_deliveries', 'ios_diagnostics',
        'bot_links', 'achievements', 'activities',
        'notifications', 'notification_preferences', 'comments', 'kudos',
        'export_requests',
        'follows', 'social_reports', 'moderation_actions', 'admin_users',
        'daily_training_load', 'fitness_metrics', 'beetle_cards',
        'system_controls'
    ]
    LOOP
        IF pg_catalog.to_regclass('public.' || v_table) IS NOT NULL THEN
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns AS columns
                WHERE columns.table_schema = 'public'
                  AND columns.table_name = v_table
                  AND columns.column_name IN (
                      'protocol_wallet', 'wallet', 'user_pubkey', 'owner_pubkey',
                      'rider_pubkey', 'staker', 'staker_wallet', 'creator_wallet',
                      'reviewer_wallet', 'admin_wallet', 'minter', 'kom_holder',
                      'holder', 'previous_holder', 'winner', 'winner_wallet',
                      'runner_up', 'runner_up_wallet', 'bumped_by_wallet',
                      'flagged_by', 'disputed_wallet', 'resolved_by'
                  )
            ) INTO v_has_wallet_fields;
            EXECUTE pg_catalog.format(
                'DROP TRIGGER IF EXISTS account_deletion_write_fence ON public.%I',
                v_table
            );
            EXECUTE pg_catalog.format(
                'CREATE TRIGGER account_deletion_write_fence '
                'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
                'FOR EACH ROW EXECUTE FUNCTION public.account_deletion_write_fence(%L)',
                v_table, v_has_wallet_fields::TEXT
            );
        END IF;
    END LOOP;

    -- Remove row-trigger versions from an earlier 152 replay, then install one
    -- transition-table fence for each statement on hot ride-child relations.
    FOR v_spec IN
        SELECT * FROM (VALUES
            ('activity_streams', 'ride_id', ''),
            ('gps_points', 'ride_id', ''),
            ('activity_tile_samples', 'activity_id', ''),
            ('ride_climb_backfill_reviews', 'activity_id', ''),
            ('segment_efforts', 'ride_id', 'user_id')
        ) AS source(table_name, ride_column, actor_column)
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS account_deletion_write_fence ON public.%I',
            v_spec.table_name
        );
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS account_deletion_write_fence_insert ON public.%I',
            v_spec.table_name
        );
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS account_deletion_write_fence_update ON public.%I',
            v_spec.table_name
        );
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS account_deletion_write_fence_delete ON public.%I',
            v_spec.table_name
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence_insert '
            'AFTER INSERT ON public.%I '
            'REFERENCING NEW TABLE AS account_deletion_new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION '
            'public.account_deletion_ride_write_fence_statement(%L, %L)',
            v_spec.table_name, v_spec.ride_column, v_spec.actor_column
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence_update '
            'AFTER UPDATE ON public.%I '
            'REFERENCING OLD TABLE AS account_deletion_old_rows '
            'NEW TABLE AS account_deletion_new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION '
            'public.account_deletion_ride_write_fence_statement(%L, %L)',
            v_spec.table_name, v_spec.ride_column, v_spec.actor_column
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence_delete '
            'AFTER DELETE ON public.%I '
            'REFERENCING OLD TABLE AS account_deletion_old_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION '
            'public.account_deletion_ride_write_fence_statement(%L, %L)',
            v_spec.table_name, v_spec.ride_column, v_spec.actor_column
        );
    END LOOP;

    DROP TRIGGER IF EXISTS account_deletion_write_fence
        ON public.invite_code_usage;

    -- Cover newly added raw-wallet authorities without relying on a manually
    -- maintained table list. Internal lifecycle authorities use their own
    -- narrowly granted RPCs and are deliberately excluded.
    FOR v_table IN
        SELECT DISTINCT columns.table_name
        FROM information_schema.columns AS columns
        JOIN pg_catalog.pg_class AS relation
          ON relation.relname = columns.table_name
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
         AND namespace.nspname = columns.table_schema
        WHERE columns.table_schema = 'public'
          AND relation.relkind IN ('r', 'p')
          AND columns.column_name IN (
              'protocol_wallet', 'wallet', 'user_pubkey', 'owner_pubkey',
              'rider_pubkey', 'staker', 'staker_wallet', 'creator_wallet',
              'reviewer_wallet', 'admin_wallet', 'minter', 'kom_holder',
              'holder', 'previous_holder',
              'winner', 'winner_wallet', 'runner_up', 'runner_up_wallet',
              'bumped_by_wallet', 'flagged_by', 'disputed_wallet', 'resolved_by'
          )
          AND columns.table_name NOT IN (
              'users', 'deletion_requests', 'deleted_account_tombstones',
              'deleted_wallets', 'invite_code_usage'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'DROP TRIGGER IF EXISTS account_deletion_write_fence ON public.%I',
            v_table
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence '
            'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.account_deletion_write_fence(''true'')',
            v_table
        );
    END LOOP;
END;
$$;

-- Database-side blockers are rerun inside request creation and finalization.
-- Chain authorities are supplied separately by the worker at finalized
-- commitment and persisted in preflight_snapshot.
CREATE OR REPLACE FUNCTION public.br_account_deletion_db_blockers(
    p_user_id UUID,
    p_wallet TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_blockers JSONB := '[]'::JSONB;
    v_count BIGINT;
    v_amount NUMERIC;
    v_spec RECORD;
BEGIN
    SELECT state.cal_balance
    INTO v_amount
    FROM public.user_state AS state
    WHERE state.user_id = p_user_id;
    IF FOUND AND v_amount IS DISTINCT FROM 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'balance_remains', 'category', 'balance',
                'asset', 'CAL', 'count', 1,
                'source', 'app_cal_state', 'action', 'open_balance'
            )
        );
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.user_state AS state
        WHERE state.user_id = p_user_id AND state.next_cal_airdrop IS NOT NULL
    ) THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'claim_remains', 'category', 'claim',
                'count', 1, 'source', 'scheduled_cal_airdrop',
                'action', 'contact_support'
            ),
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', 1, 'source', 'scheduled_cal_airdrop',
                'action', 'contact_support'
            )
        );
    END IF;

    SELECT pg_catalog.count(*) INTO v_count
    FROM public.claims AS claim WHERE claim.user_id = p_user_id;
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'claim_remains', 'category', 'claim',
                'count', v_count, 'source', 'claims', 'action', 'open_balance'
            ),
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', v_count, 'source', 'claims', 'action', 'contact_support'
            )
        );
    END IF;

    SELECT pg_catalog.count(*) INTO v_count
    FROM public.vesting_schedules AS vesting WHERE vesting.user_id = p_user_id;
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'claim_remains', 'category', 'claim',
                'count', v_count, 'source', 'vesting_schedules',
                'action', 'open_balance'
            ),
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', v_count, 'source', 'vesting_schedules',
                'action', 'contact_support'
            )
        );
    END IF;

    SELECT pg_catalog.count(*) INTO v_count
    FROM public.rides AS ride
    WHERE ride.user_id = p_user_id
      AND COALESCE(ride.processing_status, 'pending') NOT IN ('completed', 'failed');
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'claim_remains', 'category', 'processing',
                'count', v_count, 'source', 'rides', 'action', 'retry'
            )
        );
    END IF;

    IF pg_catalog.to_regclass('public.vault_stakes') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*)
            FROM public.vault_stakes
            WHERE wallet = $1
              AND (
                  unstaked_at IS NULL
                  OR points_staked IS DISTINCT FROM 0
                  OR dung_staked IS DISTINCT FROM 0
                  OR lp_tokens IS DISTINCT FROM 0
              )
        $query$ INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'stake_remains', 'category', 'stake',
                    'count', v_count, 'source', 'vault_stakes',
                    'action', 'open_balance'
                )
            );
        ELSE
            EXECUTE 'SELECT count(*) FROM public.vault_stakes WHERE wallet = $1'
                INTO v_count USING p_wallet;
            IF v_count > 0 THEN
                v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'code', 'policy_review_required', 'category', 'policy',
                        'count', v_count, 'source', 'vault_stakes',
                        'action', 'contact_support'
                    )
                );
            END IF;
        END IF;
    END IF;

    SELECT pg_catalog.count(*) INTO v_count
    FROM public.indexed_stakes AS stake
    WHERE stake.user_pubkey = p_wallet
      AND (
          stake.cal_staked IS DISTINCT FROM 0
          OR stake.lp_tokens IS DISTINCT FROM 0
          OR stake.rewards_earned IS DISTINCT FROM 0
          OR stake.amount IS DISTINCT FROM 0
          OR stake.effective_lp_tokens IS DISTINCT FROM 0
          OR stake.pending_lp_tokens IS DISTINCT FROM 0
          OR stake.pending_effective_week_plus_one IS DISTINCT FROM 0
      );
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'stake_remains', 'category', 'stake',
                'count', v_count, 'source', 'indexed_stakes',
                'action', 'open_balance'
            )
        );
    ELSE
        SELECT pg_catalog.count(*) INTO v_count
        FROM public.indexed_stakes AS stake WHERE stake.user_pubkey = p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'indexed_stakes',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.balance_operations AS operation
            WHERE (operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2)
              AND NOT (
                  operation.confirmation_status IN ('confirmed', 'finalized')
                  AND operation.projection_status = 'recorded'
                  AND operation.rider_state IS DISTINCT FROM 'Needs review'
              )
        $query$ INTO v_count USING p_user_id, p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'claim',
                    'count', v_count, 'source', 'balance_operations',
                    'action', 'open_balance'
                )
            );
        END IF;
    END IF;

    SELECT pg_catalog.count(*) INTO v_count
    FROM public.ride_economic_plans AS plan
    WHERE plan.user_id = p_user_id
      AND NOT (plan.state = 'complete' AND plan.terminal_projected_at IS NOT NULL);
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'claim_remains', 'category', 'claim',
                'count', v_count, 'source', 'ride_economic_plans',
                'action', 'contact_support'
            )
        );
    ELSE
        SELECT pg_catalog.count(*) INTO v_count
        FROM public.ride_economic_plans AS plan
        WHERE plan.user_id = p_user_id;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'ride_economic_plans',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.vault_shadow_usdc') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.vault_shadow_usdc WHERE wallet = $1 AND settled_at IS NULL'
            INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'claim',
                    'asset', 'USDC', 'count', v_count,
                    'source', 'vault_shadow_usdc', 'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.scored_patterns') IS NOT NULL THEN
        EXECUTE $query$SELECT count(*) FROM public.scored_patterns
                  WHERE wallet = $1 AND COALESCE(status, 'PENDING') = 'PENDING'$query$
            INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'claim',
                    'count', v_count, 'source', 'scored_patterns',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.canon_vault_activations') IS NOT NULL THEN
        EXECUTE $query$SELECT count(*) FROM public.canon_vault_activations
                  WHERE creator_wallet = $1 AND activation_status IN ('reserved', 'confirmed')$query$
            INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'claim',
                    'count', v_count, 'source', 'canon_vault_activations',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.balance_operations AS operation
            WHERE operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2
        $query$ INTO v_count USING p_user_id, p_wallet;
        IF v_count > 0
           AND NOT v_blockers @> '[{"source":"balance_operations"}]'::JSONB THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'balance_operations',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    SELECT COALESCE(pg_catalog.sum(source_count), 0)::BIGINT
    INTO v_count
    FROM (
        SELECT pg_catalog.count(*) AS source_count
        FROM public.economic_events AS event
        WHERE event.wallet = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_ride_attestations AS attestation
        WHERE attestation.rider_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_staker_allocations AS allocation
        WHERE allocation.staker = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_accounts AS account
        WHERE account.owner_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_rider_souls AS soul
        WHERE soul.rider_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_cal_mint_receipts AS receipt
        WHERE receipt.rider_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_beetle_cards AS card
        WHERE card.owner_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_completions AS completion
        WHERE completion.user_pubkey = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_legends AS legend
        WHERE legend.holder = p_wallet OR legend.runner_up = p_wallet
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.indexed_leaderboards AS board
        WHERE board.entries::TEXT LIKE '%' || p_wallet || '%'
        UNION ALL
        SELECT pg_catalog.count(*) FROM public.settlement_jobs AS job
        WHERE job.precondition_intent::TEXT LIKE '%' || p_wallet || '%'
    ) AS provenance;
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', v_count, 'source', 'wallet_keyed_provenance',
                'action', 'contact_support'
            )
        );
    END IF;

    IF pg_catalog.to_regclass('public.indexed_events') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.indexed_events AS event
            WHERE event.user_pubkey = $1 OR event.fields::TEXT LIKE '%' || $1 || '%'
        $query$ INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'indexed_events',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.indexed_vaults') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.indexed_vaults '
                'WHERE minter = $1 OR kom_holder = $1'
            INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'indexed_vaults',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.tx_lifecycle') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.tx_lifecycle WHERE wallet = $1'
            INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'tx_lifecycle',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.replay_batches') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.replay_batches AS batch
            WHERE batch.wallet = $1
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.unnest(COALESCE(batch.ride_ids, ARRAY[]::TEXT[])) AS ride(ride_id)
                   WHERE ride.ride_id IN (
                       SELECT owned.id::TEXT FROM public.rides AS owned
                       WHERE owned.user_id = $2
                   )
               )
        $query$ INTO v_count USING p_wallet, p_user_id;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'replay_batches',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    -- These relations carry unresolved value or proof/provenance semantics.
    -- Ordinary ride and leaderboard history is handled by the anonymous
    -- projection in the finalizer below and is deliberately not blocked here.
    FOR v_spec IN
        SELECT key AS table_name, value AS column_name
        FROM pg_catalog.jsonb_each_text(
            '{
                "beetle_cards":"wallet",
                "scored_patterns":"wallet",
                "canon_vault_activations":"creator_wallet",
                "vault_creation_handoffs":"creator_wallet"
            }'::JSONB
        )
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'SELECT count(*) FROM public.%I WHERE %I = $1',
                v_spec.table_name,
                v_spec.column_name
            ) INTO v_count USING p_wallet;
            IF v_count > 0 THEN
                v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'code', 'policy_review_required', 'category', 'policy',
                        'count', v_count, 'source', v_spec.table_name,
                        'action', 'contact_support'
                    )
                );
            END IF;
        END IF;
    END LOOP;

    IF pg_catalog.to_regclass('public.climb_attestations') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.climb_attestations WHERE user_id = $1'
            INTO v_count USING p_user_id;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'climb_attestations',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    -- A ride can be removed only after every proof/economic authority linked
    -- to it has an explicit disposition. These sources remain Tim-gated. The
    -- repository and deployed schemas have legitimately differed here, so a
    -- table is queried only through columns that actually exist.
    FOR v_spec IN
        SELECT * FROM (VALUES
            ('canon_traversal_evidence', 'ride_id'),
            ('harvest_events', 'user_id'),
            ('reward_ftp_authorities', 'user_id'),
            ('admin_users', 'user_id')
        ) AS source(table_name, column_name)
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = v_spec.table_name
                 AND column_name = v_spec.column_name
           ) THEN
            IF v_spec.column_name = 'ride_id' THEN
                EXECUTE pg_catalog.format(
                    'SELECT count(*) FROM public.%I WHERE ride_id IN '
                    '(SELECT id FROM public.rides WHERE user_id = $1)',
                    v_spec.table_name
                ) INTO v_count USING p_user_id;
            ELSE
                EXECUTE pg_catalog.format(
                    'SELECT count(*) FROM public.%I WHERE %I = $1',
                    v_spec.table_name,
                    v_spec.column_name
                ) INTO v_count USING p_user_id;
            END IF;
            IF v_count > 0 THEN
                v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'code', 'policy_review_required', 'category', 'policy',
                        'count', v_count, 'source', v_spec.table_name,
                        'action', 'contact_support'
                    )
                );
            END IF;
        END IF;
    END LOOP;

    IF pg_catalog.to_regclass('public.proofs') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'proofs'
              AND column_name = 'user_id'
        ) AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'proofs'
              AND column_name = 'ride_id'
        ) THEN
            EXECUTE $query$
                SELECT count(*) FROM public.proofs
                WHERE user_id = $1 OR ride_id IN (
                    SELECT id FROM public.rides WHERE user_id = $1
                )
            $query$ INTO v_count USING p_user_id;
        ELSIF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'proofs'
              AND column_name = 'user_id'
        ) THEN
            EXECUTE 'SELECT count(*) FROM public.proofs WHERE user_id = $1'
                INTO v_count USING p_user_id;
        ELSIF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'proofs'
              AND column_name = 'ride_id'
        ) THEN
            EXECUTE 'SELECT count(*) FROM public.proofs WHERE ride_id IN '
                    '(SELECT id FROM public.rides WHERE user_id = $1)'
                INTO v_count USING p_user_id;
        ELSE
            v_count := 0;
        END IF;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'proofs',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.mint_events') IS NOT NULL THEN
        v_count := 0;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'mint_events'
              AND column_name = 'user_id'
        ) AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'mint_events'
              AND column_name = 'ride_id'
        ) THEN
            EXECUTE $query$
                SELECT count(*) FROM public.mint_events
                WHERE user_id = $1 OR ride_id IN (
                    SELECT id FROM public.rides WHERE user_id = $1
                )
            $query$
                INTO v_count USING p_user_id;
        ELSIF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'mint_events'
              AND column_name = 'user_id'
        ) THEN
            EXECUTE 'SELECT count(*) FROM public.mint_events WHERE user_id = $1'
                INTO v_count USING p_user_id;
        ELSIF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'mint_events'
              AND column_name = 'ride_id'
        ) THEN
            EXECUTE 'SELECT count(*) FROM public.mint_events WHERE ride_id IN '
                    '(SELECT id FROM public.rides WHERE user_id = $1)'
                INTO v_count USING p_user_id;
        END IF;
        IF v_count = 0 AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'mint_events'
              AND column_name = 'proof_id'
        ) AND pg_catalog.to_regclass('public.proofs') IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public' AND table_name = 'proofs'
                AND column_name = 'user_id'
          ) THEN
            EXECUTE $query$
                SELECT count(*)
                FROM public.mint_events AS mint
                JOIN public.proofs AS proof ON proof.id = mint.proof_id
                WHERE proof.user_id = $1
            $query$ INTO v_count USING p_user_id;
        END IF;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'mint_events',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.token_transactions') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.token_transactions
            WHERE user_id = $1 AND tx_signature IS NOT NULL
        $query$ INTO v_count USING p_user_id;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'token_transactions_on_chain',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.vault_completions') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.vault_completions
            WHERE wallet = $1
              AND (
                  on_chain_tx IS NOT NULL
                  OR completion_receipt_pda IS NOT NULL
                  OR chain_confirmed_at IS NOT NULL
                  OR chain_confirmation_status NOT IN ('legacy_unverified', 'not_submitted')
              )
        $query$ INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'vault_completions_on_chain',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.leaderboard_disputes') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.leaderboard_disputes
            WHERE status IN ('pending', 'under_review')
              AND (disputed_wallet = $1 OR flagged_by = $1 OR resolved_by = $1)
        $query$ INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'review',
                    'count', v_count, 'source', 'leaderboard_disputes',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    FOR v_spec IN
        SELECT policy.*
        FROM br_private.account_deletion_identity_policy AS policy
        ORDER BY policy.table_name, policy.identity_column
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'SELECT count(*) FROM public.%I WHERE %I = $1 AND (%s)',
                v_spec.table_name,
                v_spec.identity_column,
                v_spec.blocker_predicate
            ) INTO v_count USING p_wallet;
            IF v_count > 0 THEN
                v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'code', v_spec.blocker_code,
                        'category', v_spec.blocker_category,
                        'count', v_count,
                        'source', v_spec.blocker_source,
                        'action', v_spec.blocker_action
                    )
                );
            END IF;
        END IF;
    END LOOP;

    IF pg_catalog.to_regclass('public.local_legend_rollovers') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.local_legend_rollovers
            WHERE tx_signature IS NOT NULL
              AND (previous_holder = $1 OR winner = $1 OR runner_up = $1)
        $query$ INTO v_count USING p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'policy_review_required', 'category', 'policy',
                    'count', v_count, 'source', 'local_legend_on_chain_provenance',
                    'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    FOR v_spec IN
        SELECT * FROM (VALUES
            ('cal_allocation_staging', 'wallet'),
            ('cal_allocation_leaves', 'wallet'),
            ('tge_conversions', 'wallet')
        ) AS source(table_name, column_name)
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'SELECT count(*) FROM public.%I WHERE %I = $1',
                v_spec.table_name,
                v_spec.column_name
            ) INTO v_count USING p_wallet;
            IF v_count > 0 THEN
                v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                    pg_catalog.jsonb_build_object(
                        'code', 'policy_review_required', 'category', 'policy',
                        'count', v_count, 'source', v_spec.table_name,
                        'action', 'contact_support'
                    )
                );
            END IF;
        END IF;
    END LOOP;

    IF pg_catalog.to_regclass('public.wallet_points') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(sum(total_points), 0) '
                'FROM public.wallet_points WHERE wallet = $1'
            INTO v_amount USING p_wallet;
        IF v_amount IS DISTINCT FROM 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'balance_remains', 'category', 'balance',
                    'asset', 'POINTS', 'count', 1,
                    'source', 'wallet_points', 'action', 'contact_support'
                )
            );
        END IF;
    END IF;

    RETURN v_blockers;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_account_deletion_storage_paths(
    p_user_id UUID
)
RETURNS TEXT[]
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $$
DECLARE
    v_paths TEXT[] := ARRAY[]::TEXT[];
    v_optional_paths TEXT[];
BEGIN
    SELECT pg_catalog.array_remove(
        ARRAY["user".avatar_storage_path, "user".avatar_pending_storage_path],
        NULL
    )
    INTO v_paths
    FROM public.users AS "user"
    WHERE "user".id = p_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account_deletion_user_unavailable' USING ERRCODE = '55000';
    END IF;

    SELECT COALESCE(
        pg_catalog.array_agg(DISTINCT ride.raw_file_path ORDER BY ride.raw_file_path)
            FILTER (WHERE ride.raw_file_path IS NOT NULL AND ride.raw_file_path <> ''),
        ARRAY[]::TEXT[]
    )
    INTO v_optional_paths
    FROM public.rides AS ride
    WHERE ride.user_id = p_user_id;
    v_paths := v_paths || v_optional_paths;

    IF pg_catalog.to_regclass('public.ride_media') IS NOT NULL THEN
        EXECUTE $query$
            SELECT COALESCE(
                array_agg(DISTINCT storage_path ORDER BY storage_path)
                    FILTER (WHERE storage_path IS NOT NULL AND storage_path <> ''),
                ARRAY[]::TEXT[]
            )
            FROM public.ride_media
            WHERE user_id = $1
        $query$ INTO v_optional_paths USING p_user_id;
        v_paths := v_paths || v_optional_paths;
    END IF;

    RETURN ARRAY(
        SELECT DISTINCT path
        FROM pg_catalog.unnest(v_paths) AS stored(path)
        WHERE path IS NOT NULL AND path <> ''
        ORDER BY path
    );
END;
$$;

DROP FUNCTION IF EXISTS public.create_account_deletion_request(
    UUID, UUID, TEXT, BOOLEAN, TEXT[], TEXT, JSONB, JSONB
);
CREATE OR REPLACE FUNCTION public.create_account_deletion_request(
    p_request_id UUID,
    p_user_id UUID,
    p_wallet TEXT,
    p_unuploaded_rides_acknowledged BOOLEAN,
    p_status_token_hash TEXT,
    p_preflight_snapshot JSONB DEFAULT '{}'::JSONB,
    p_local_review_receipt JSONB DEFAULT NULL
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_existing public.deletion_requests%ROWTYPE;
    v_wallet TEXT;
    v_blockers JSONB;
    v_status TEXT;
    v_snapshot JSONB;
    v_authoritative_fingerprint TEXT;
    v_storage_paths TEXT[] := ARRAY[]::TEXT[];
BEGIN
    IF p_request_id IS NULL
       OR p_user_id IS NULL
       OR p_wallet IS NULL
       OR p_wallet = ''
       OR p_status_token_hash IS NULL
       OR p_status_token_hash !~ '^[0-9a-f]{64}$'
       OR p_unuploaded_rides_acknowledged IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'invalid_account_deletion_request'
            USING ERRCODE = '22023';
    END IF;

    v_authoritative_fingerprint :=
        public.br_account_deletion_wallet_fingerprint(p_wallet);
    PERFORM public.br_lock_account_deletion_wallet(v_authoritative_fingerprint);

    SELECT * INTO v_existing
    FROM public.deletion_requests AS request
    WHERE request.id = p_request_id
    FOR UPDATE;
    IF FOUND THEN
        IF v_existing.user_id IS DISTINCT FROM p_user_id
           OR v_existing.wallet_fingerprint IS DISTINCT FROM v_authoritative_fingerprint
           OR v_existing.status_token_hash IS DISTINCT FROM p_status_token_hash THEN
            RAISE EXCEPTION 'account_deletion_request_id_conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;

    SELECT "user".wallet INTO v_wallet
    FROM public.users AS "user"
    WHERE "user".id = p_user_id
    FOR UPDATE;
    IF NOT FOUND
       OR v_wallet IS DISTINCT FROM p_wallet
       OR EXISTS (
           SELECT 1 FROM public.users AS "user"
           WHERE "user".id = p_user_id AND "user".account_state <> 'active'
       ) THEN
        RAISE EXCEPTION 'account_deletion_user_unavailable'
            USING ERRCODE = '55000';
    END IF;

    IF p_preflight_snapshot IS NULL
       OR pg_catalog.jsonb_typeof(p_preflight_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)) <> 'array'
       OR p_preflight_snapshot ->> 'available' NOT IN ('true', 'false') THEN
        RAISE EXCEPTION 'invalid_account_deletion_preflight_snapshot'
            USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(pg_catalog.jsonb_agg(DISTINCT blocker.value), '[]'::JSONB)
    INTO v_blockers
    FROM pg_catalog.jsonb_array_elements(
        COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)
        || public.br_account_deletion_db_blockers(p_user_id, p_wallet)
    ) AS blocker(value);
    IF COALESCE(
        (p_preflight_snapshot ->> 'destructive_boundary_available')::BOOLEAN,
        FALSE
    ) IS NOT TRUE
       AND NOT v_blockers @> '[{"source":"on_chain_deletion_boundary"}]'::JSONB THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', 1, 'source', 'on_chain_deletion_boundary',
                'action', 'contact_support'
            )
        );
    END IF;
    v_status := CASE
        WHEN COALESCE((p_preflight_snapshot ->> 'available')::BOOLEAN, FALSE) IS NOT TRUE
            THEN 'failed_retryable'
        WHEN v_blockers @> '[{"code":"policy_review_required"}]'::JSONB
            THEN 'needs_support'
        WHEN pg_catalog.jsonb_array_length(v_blockers) > 0
            THEN 'blocked'
        ELSE 'queued'
    END;
    v_snapshot := p_preflight_snapshot || pg_catalog.jsonb_build_object(
        'allowed', v_status = 'queued',
        'blockers', v_blockers
    );

    IF EXISTS (
        SELECT 1 FROM public.deletion_requests AS request
        WHERE request.user_id = p_user_id
          AND request.status IN (
              'queued', 'processing', 'blocked', 'failed_retryable', 'needs_support'
          )
    ) THEN
        RAISE EXCEPTION 'account_deletion_request_already_active'
            USING ERRCODE = '23505';
    END IF;

    IF v_status = 'queued' THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'deletion_pending',
            account_deletion_locked_at = clock_timestamp(),
            account_deletion_request_id = p_request_id,
            updated_at = clock_timestamp()
        WHERE id = p_user_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
        v_storage_paths := public.br_account_deletion_storage_paths(p_user_id);
    END IF;

    INSERT INTO public.deletion_requests (
        id, user_id, wallet, wallet_fingerprint, status_token_hash,
        status, blockers, failure_code, storage_paths,
        unuploaded_rides_acknowledged, local_review_receipt,
        preflight_snapshot, preflight_checked_at, requested_at, updated_at
    ) VALUES (
        p_request_id, p_user_id, p_wallet, v_authoritative_fingerprint, p_status_token_hash,
        v_status, v_blockers,
        CASE WHEN v_status = 'failed_retryable' THEN 'preflight_unavailable' ELSE NULL END,
        pg_catalog.to_jsonb(v_storage_paths),
        TRUE, p_local_review_receipt,
        v_snapshot, clock_timestamp(), clock_timestamp(), clock_timestamp()
    )
    RETURNING * INTO v_existing;
    RETURN NEXT v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.claim_account_deletion_request(
    p_request_id UUID,
    p_worker_id UUID,
    p_lease_seconds INTEGER DEFAULT 300
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_row public.deletion_requests%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 900 THEN
        RAISE EXCEPTION 'invalid_account_deletion_lease' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_row
    FROM public.deletion_requests AS request
    WHERE request.id = p_request_id
      AND (
          request.status = 'queued'
          OR (
              request.status = 'failed_retryable'
              AND request.storage_authorized_at IS NOT NULL
          )
          OR (
              request.status = 'processing'
              AND request.worker_lease_until < clock_timestamp()
          )
      )
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    UPDATE public.deletion_requests
    SET status = 'processing',
        worker_id = p_worker_id,
        worker_lease_token = pg_catalog.gen_random_uuid(),
        worker_lease_until = clock_timestamp() + pg_catalog.make_interval(secs => p_lease_seconds),
        attempt_count = attempt_count + 1,
        failure_code = NULL,
        updated_at = clock_timestamp()
    WHERE id = p_request_id
    RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_account_deletion_blocked(
    p_request_id UUID,
    p_blockers JSONB,
    p_lease_token UUID DEFAULT NULL
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.deletion_requests WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR p_lease_token IS NULL
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp()
       OR pg_catalog.jsonb_typeof(COALESCE(p_blockers, '[]'::JSONB)) <> 'array' THEN
        RAISE EXCEPTION 'stale_account_deletion_lease' USING ERRCODE = '55000';
    END IF;
    UPDATE public.deletion_requests
    SET status = CASE WHEN storage_authorized_at IS NULL
                      THEN 'blocked' ELSE 'needs_support' END,
        blockers = COALESCE(p_blockers, '[]'::JSONB),
        failure_code = CASE WHEN storage_authorized_at IS NULL
                            THEN NULL ELSE 'blocker_after_storage_authorization' END,
        worker_id = NULL, worker_lease_token = NULL, worker_lease_until = NULL,
        updated_at = clock_timestamp()
    WHERE id = p_request_id RETURNING * INTO v_row;
    IF v_row.storage_authorized_at IS NULL THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'active', account_deletion_locked_at = NULL,
            account_deletion_request_id = NULL, updated_at = clock_timestamp()
        WHERE id = v_row.user_id AND account_deletion_request_id = p_request_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
    END IF;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.support_account_deletion_request(
    p_request_id UUID,
    p_blockers JSONB,
    p_lease_token UUID DEFAULT NULL
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.deletion_requests WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR p_lease_token IS NULL
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp()
       OR pg_catalog.jsonb_typeof(COALESCE(p_blockers, '[]'::JSONB)) <> 'array' THEN
        RAISE EXCEPTION 'stale_account_deletion_lease' USING ERRCODE = '55000';
    END IF;
    UPDATE public.deletion_requests
    SET status = 'needs_support', blockers = COALESCE(p_blockers, '[]'::JSONB),
        failure_code = NULL,
        worker_id = NULL, worker_lease_token = NULL, worker_lease_until = NULL,
        updated_at = clock_timestamp()
    WHERE id = p_request_id RETURNING * INTO v_row;
    IF v_row.storage_authorized_at IS NULL THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'active', account_deletion_locked_at = NULL,
            account_deletion_request_id = NULL, updated_at = clock_timestamp()
        WHERE id = v_row.user_id AND account_deletion_request_id = p_request_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
    END IF;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_account_deletion_request(
    p_request_id UUID,
    p_lease_token UUID,
    p_failure_code TEXT
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.deletion_requests WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'stale_account_deletion_lease' USING ERRCODE = '55000';
    END IF;
    UPDATE public.deletion_requests
    SET status = 'failed_retryable', failure_code = p_failure_code,
        worker_id = NULL, worker_lease_token = NULL,
        worker_lease_until = NULL, next_attempt_at = NULL,
        updated_at = clock_timestamp()
    WHERE id = p_request_id RETURNING * INTO v_row;
    IF v_row.storage_authorized_at IS NULL THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'active', account_deletion_locked_at = NULL,
            account_deletion_request_id = NULL, updated_at = clock_timestamp()
        WHERE id = v_row.user_id AND account_deletion_request_id = p_request_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
    END IF;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.fail_account_deletion_dispatch(
    p_request_id UUID
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row
    FROM public.deletion_requests
    WHERE id = p_request_id AND status = 'queued'
    FOR UPDATE;
    IF NOT FOUND THEN RETURN; END IF;
    UPDATE public.deletion_requests
    SET status = 'failed_retryable', failure_code = 'queue_unavailable',
        updated_at = clock_timestamp()
    WHERE id = p_request_id AND status = 'queued'
    RETURNING * INTO v_row;
    IF FOUND THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'active', account_deletion_locked_at = NULL,
            account_deletion_request_id = NULL, updated_at = clock_timestamp()
        WHERE id = v_row.user_id AND account_deletion_request_id = p_request_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
        RETURN NEXT v_row;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.renew_account_deletion_lease(
    p_request_id UUID,
    p_lease_token UUID,
    p_lease_seconds INTEGER DEFAULT 300
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    IF p_lease_seconds < 30 OR p_lease_seconds > 900 THEN
        RAISE EXCEPTION 'invalid_account_deletion_lease' USING ERRCODE = '22023';
    END IF;
    UPDATE public.deletion_requests
    SET worker_lease_until = clock_timestamp()
            + pg_catalog.make_interval(secs => p_lease_seconds),
        updated_at = clock_timestamp()
    WHERE id = p_request_id
      AND status = 'processing'
      AND worker_lease_token = p_lease_token
      AND worker_lease_until > clock_timestamp()
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'stale_account_deletion_lease' USING ERRCODE = '55000';
    END IF;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.authorize_account_deletion_storage(
    p_request_id UUID,
    p_lease_token UUID,
    p_preflight_snapshot JSONB
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_row public.deletion_requests%ROWTYPE;
    v_blockers JSONB;
    v_status TEXT;
    v_snapshot JSONB;
BEGIN
    SELECT * INTO v_row
    FROM public.deletion_requests AS request
    WHERE request.id = p_request_id
    FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp()
       OR NOT v_row.unuploaded_rides_acknowledged
       OR p_preflight_snapshot IS NULL
       OR pg_catalog.jsonb_typeof(p_preflight_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(
           COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)
       ) <> 'array' THEN
        RAISE EXCEPTION 'stale_or_unsafe_account_deletion_storage_authorization'
            USING ERRCODE = '55000';
    END IF;

    PERFORM 1
    FROM public.users AS "user"
    WHERE "user".id = v_row.user_id
      AND "user".wallet = v_row.wallet
      AND "user".account_state = 'deletion_pending'
      AND "user".account_deletion_request_id = p_request_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account_deletion_user_fence_missing'
            USING ERRCODE = '55000';
    END IF;

    SELECT COALESCE(pg_catalog.jsonb_agg(DISTINCT blocker.value), '[]'::JSONB)
    INTO v_blockers
    FROM pg_catalog.jsonb_array_elements(
        COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)
        || public.br_account_deletion_db_blockers(v_row.user_id, v_row.wallet)
    ) AS blocker(value);
    IF COALESCE(
        (p_preflight_snapshot ->> 'destructive_boundary_available')::BOOLEAN,
        FALSE
    ) IS NOT TRUE
       AND NOT v_blockers @> '[{"source":"on_chain_deletion_boundary"}]'::JSONB THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', 1, 'source', 'on_chain_deletion_boundary',
                'action', 'contact_support'
            )
        );
    END IF;

    v_status := CASE
        WHEN COALESCE((p_preflight_snapshot ->> 'available')::BOOLEAN, FALSE) IS NOT TRUE
            THEN 'failed_retryable'
        WHEN v_blockers @> '[{"code":"policy_review_required"}]'::JSONB
            THEN 'needs_support'
        WHEN pg_catalog.jsonb_array_length(v_blockers) > 0
            THEN 'blocked'
        ELSE 'processing'
    END;
    IF v_row.storage_authorized_at IS NOT NULL AND v_status <> 'processing' THEN
        v_status := 'needs_support';
    END IF;
    v_snapshot := p_preflight_snapshot || pg_catalog.jsonb_build_object(
        'allowed', v_status = 'processing', 'blockers', v_blockers
    );

    IF v_status <> 'processing' THEN
        UPDATE public.deletion_requests
        SET status = v_status, blockers = v_blockers,
            failure_code = CASE
                WHEN storage_authorized_at IS NOT NULL
                    THEN 'blocker_after_storage_authorization'
                WHEN v_status = 'failed_retryable'
                    THEN 'preflight_unavailable'
                ELSE NULL
            END,
            preflight_snapshot = v_snapshot,
            preflight_checked_at = clock_timestamp(),
            worker_id = NULL, worker_lease_token = NULL,
            worker_lease_until = NULL, updated_at = clock_timestamp()
        WHERE id = p_request_id
        RETURNING * INTO v_row;
        IF v_row.storage_authorized_at IS NULL THEN
            PERFORM pg_catalog.set_config(
                'app.account_deletion_request_id', p_request_id::TEXT, TRUE
            );
            UPDATE public.users
            SET account_state = 'active', account_deletion_locked_at = NULL,
                account_deletion_request_id = NULL,
                updated_at = clock_timestamp()
            WHERE id = v_row.user_id
              AND account_deletion_request_id = p_request_id;
            PERFORM pg_catalog.set_config(
                'app.account_deletion_request_id', '', TRUE
            );
        END IF;
        RETURN NEXT v_row;
        RETURN;
    END IF;

    UPDATE public.deletion_requests
    SET storage_authorized_at = COALESCE(storage_authorized_at, clock_timestamp()),
        blockers = '[]'::JSONB, failure_code = NULL,
        preflight_snapshot = v_snapshot,
        preflight_checked_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE id = p_request_id
    RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_account_deletion_storage_receipt(
    p_request_id UUID,
    p_lease_token UUID,
    p_path TEXT,
    p_outcome TEXT
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row
    FROM public.deletion_requests
    WHERE id = p_request_id
    FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp()
       OR v_row.storage_authorized_at IS NULL
       OR p_path IS NULL OR p_path = ''
       OR p_outcome IS DISTINCT FROM 'confirmed_absent'
       OR NOT (v_row.storage_paths ? p_path) THEN
        RAISE EXCEPTION 'stale_or_invalid_account_deletion_storage_receipt'
            USING ERRCODE = '55000';
    END IF;
    UPDATE public.deletion_requests
    SET storage_receipts = storage_receipts
            || pg_catalog.jsonb_build_object(p_path, p_outcome),
        updated_at = clock_timestamp()
    WHERE id = p_request_id
    RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_account_deletion_storage_removed(
    p_request_id UUID,
    p_lease_token UUID,
    p_preflight_snapshot JSONB
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE v_row public.deletion_requests%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM public.deletion_requests WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND OR v_row.status <> 'processing'
       OR v_row.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_row.worker_lease_until <= clock_timestamp()
       OR v_row.storage_authorized_at IS NULL
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.jsonb_array_elements_text(v_row.storage_paths) AS path(value)
           WHERE v_row.storage_receipts ->> path.value IS DISTINCT FROM 'confirmed_absent'
       )
       OR EXISTS (
           SELECT 1
           FROM pg_catalog.jsonb_each_text(v_row.storage_receipts) AS receipt(path, outcome)
           WHERE receipt.outcome IS DISTINCT FROM 'confirmed_absent'
              OR NOT (v_row.storage_paths ? receipt.path)
       )
       OR (
           SELECT pg_catalog.count(*)
           FROM pg_catalog.jsonb_object_keys(v_row.storage_receipts)
       ) IS DISTINCT FROM pg_catalog.jsonb_array_length(v_row.storage_paths)::BIGINT
       THEN
        RAISE EXCEPTION 'stale_or_unsafe_account_deletion_storage_phase'
            USING ERRCODE = '55000';
    END IF;
    UPDATE public.deletion_requests
    SET storage_completed_at = COALESCE(storage_completed_at, clock_timestamp()),
        updated_at = clock_timestamp()
    WHERE id = p_request_id RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

DROP FUNCTION IF EXISTS public.retry_account_deletion_request(UUID, BOOLEAN, JSONB);
DROP FUNCTION IF EXISTS public.retry_account_deletion_request(UUID, BOOLEAN, TEXT[], JSONB);
DROP FUNCTION IF EXISTS public.retry_account_deletion_request(UUID, JSONB);
CREATE OR REPLACE FUNCTION public.retry_account_deletion_request(
    p_request_id UUID,
    p_preflight_snapshot JSONB
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_row public.deletion_requests%ROWTYPE;
    v_wallet_fingerprint TEXT;
    v_blockers JSONB;
    v_status TEXT;
    v_snapshot JSONB;
    v_storage_paths TEXT[] := ARRAY[]::TEXT[];
BEGIN
    SELECT request.wallet_fingerprint INTO v_wallet_fingerprint
    FROM public.deletion_requests AS request WHERE request.id = p_request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account_deletion_retry_unavailable' USING ERRCODE = '55000';
    END IF;
    PERFORM public.br_lock_account_deletion_wallet(v_wallet_fingerprint);

    SELECT * INTO v_row
    FROM public.deletion_requests
    WHERE id = p_request_id
    FOR UPDATE;
    IF NOT FOUND OR v_row.status NOT IN ('blocked', 'failed_retryable') THEN
        RAISE EXCEPTION 'account_deletion_retry_unavailable' USING ERRCODE = '55000';
    END IF;
    IF NOT v_row.unuploaded_rides_acknowledged THEN
        RAISE EXCEPTION 'account_deletion_acknowledgement_required'
            USING ERRCODE = '55000';
    END IF;
    IF v_row.storage_authorized_at IS NOT NULL THEN
        -- Recovery after crossing the destructive boundary is worker-owned and
        -- listed durably below; a rider retry cannot rewrite its evidence.
        RAISE EXCEPTION 'account_deletion_retry_unavailable' USING ERRCODE = '55000';
    END IF;
    IF p_preflight_snapshot IS NULL
       OR pg_catalog.jsonb_typeof(p_preflight_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)) <> 'array' THEN
        RAISE EXCEPTION 'invalid_account_deletion_preflight_snapshot'
            USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(pg_catalog.jsonb_agg(DISTINCT blocker.value), '[]'::JSONB)
    INTO v_blockers
    FROM pg_catalog.jsonb_array_elements(
        COALESCE(p_preflight_snapshot -> 'blockers', '[]'::JSONB)
        || public.br_account_deletion_db_blockers(v_row.user_id, v_row.wallet)
    ) AS blocker(value);
    IF COALESCE((p_preflight_snapshot ->> 'destructive_boundary_available')::BOOLEAN, FALSE) IS NOT TRUE
       AND NOT v_blockers @> '[{"source":"on_chain_deletion_boundary"}]'::JSONB THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required', 'category', 'policy',
                'count', 1, 'source', 'on_chain_deletion_boundary',
                'action', 'contact_support'
            )
        );
    END IF;
    IF COALESCE((p_preflight_snapshot ->> 'available')::BOOLEAN, FALSE) IS NOT TRUE THEN
        RAISE EXCEPTION 'account_deletion_retry_unavailable' USING ERRCODE = '55000';
    END IF;
    IF v_blockers @> '[{"source":"on_chain_deletion_boundary"}]'::JSONB
       OR v_blockers @> '[{"code":"policy_review_required"}]'::JSONB THEN
        -- Retry cannot silently cross a new human/support boundary or burn a
        -- recoverable row into terminal support.
        RAISE EXCEPTION 'account_deletion_retry_requires_support'
            USING ERRCODE = '55000';
    END IF;
    v_status := CASE
        WHEN COALESCE((p_preflight_snapshot ->> 'available')::BOOLEAN, FALSE) IS NOT TRUE
            THEN 'failed_retryable'
        WHEN v_blockers @> '[{"code":"policy_review_required"}]'::JSONB
            THEN 'needs_support'
        WHEN pg_catalog.jsonb_array_length(v_blockers) > 0
            THEN 'blocked'
        ELSE 'queued'
    END;
    v_snapshot := p_preflight_snapshot || pg_catalog.jsonb_build_object(
        'allowed', v_status = 'queued', 'blockers', v_blockers
    );
    IF v_status = 'queued' THEN
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'deletion_pending',
            account_deletion_locked_at = clock_timestamp(),
            account_deletion_request_id = p_request_id,
            updated_at = clock_timestamp()
        WHERE id = v_row.user_id
          AND wallet = v_row.wallet
          AND (
              account_state = 'active'
              OR (
                  account_state = 'deletion_pending'
                  AND account_deletion_request_id = p_request_id
              )
          );
        IF NOT FOUND THEN
            RAISE EXCEPTION 'account_deletion_user_unavailable' USING ERRCODE = '55000';
        END IF;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
        v_storage_paths := public.br_account_deletion_storage_paths(v_row.user_id);
    ELSE
        PERFORM pg_catalog.set_config(
            'app.account_deletion_request_id', p_request_id::TEXT, TRUE
        );
        UPDATE public.users
        SET account_state = 'active', account_deletion_locked_at = NULL,
            account_deletion_request_id = NULL, updated_at = clock_timestamp()
        WHERE id = v_row.user_id AND account_deletion_request_id = p_request_id;
        PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);
    END IF;
    UPDATE public.deletion_requests
    SET status = v_status, blockers = v_blockers,
        preflight_snapshot = v_snapshot, preflight_checked_at = clock_timestamp(),
        failure_code = CASE WHEN v_status = 'failed_retryable'
                            THEN 'preflight_unavailable' ELSE NULL END,
        storage_paths = pg_catalog.to_jsonb(v_storage_paths),
        storage_receipts = '{}'::JSONB, storage_completed_at = NULL,
        worker_id = NULL, worker_lease_token = NULL, worker_lease_until = NULL,
        next_attempt_at = NULL, updated_at = clock_timestamp()
    WHERE id = p_request_id
    RETURNING * INTO v_row;
    RETURN NEXT v_row;
END;
$$;

CREATE OR REPLACE FUNCTION public.list_recoverable_account_deletions(
    p_limit INTEGER DEFAULT 100
)
RETURNS TABLE(id UUID)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT request.id
    FROM public.deletion_requests AS request
    WHERE request.status = 'queued'
       OR (
           request.status = 'failed_retryable'
           AND request.storage_authorized_at IS NOT NULL
       )
       OR (
           request.status = 'processing'
           AND request.worker_lease_until < clock_timestamp()
       )
    ORDER BY request.requested_at, request.id
    LIMIT GREATEST(1, LEAST(p_limit, 500))
$$;

-- Completion verification is a database observation, not a timestamp the
-- worker is trusted to assert. The scan is intentionally broad because an
-- account deletion is rare and false completion is the higher-cost failure.
CREATE OR REPLACE FUNCTION public.br_account_deletion_personal_residue(
    p_user_id UUID,
    p_wallet TEXT,
    p_email TEXT,
    p_ride_ids UUID[],
    p_anonymous_marker UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_residue JSONB := '[]'::JSONB;
    v_spec RECORD;
    v_count BIGINT;
    v_found BOOLEAN;
    v_needles TEXT[];
BEGIN
    v_needles := pg_catalog.array_remove(
        ARRAY[p_user_id::TEXT, NULLIF(p_wallet, ''), NULLIF(p_email, '')],
        NULL
    ) || ARRAY(
        SELECT ride_id::TEXT
        FROM pg_catalog.unnest(COALESCE(p_ride_ids, ARRAY[]::UUID[])) AS ride(ride_id)
    );
    -- Build one OR predicate per relation, then use EXISTS so clean relations
    -- stop without the former full scan for every candidate column. Ordinary
    -- heap relations with no allocated main fork are physically empty and may
    -- be skipped; partitioned parents are never skipped by parent size because
    -- their rows live in child relations. Planner estimates are not trusted.
    FOR v_spec IN
        SELECT columns.table_name,
               relation.oid AS relation_oid,
               relation.relkind,
               pg_catalog.string_agg(
                   CASE
                       WHEN policy.residue_match_kind = 'wallet_exact' THEN
                           pg_catalog.format('source.%I = $4', columns.column_name)
                       WHEN columns.udt_name = 'uuid' THEN pg_catalog.format(
                           '(source.%I = $1 OR (cardinality($2) > 0 AND source.%I = ANY($2)))',
                           columns.column_name, columns.column_name
                       )
                       ELSE pg_catalog.format(
                           'EXISTS ('
                           ' SELECT 1 FROM pg_catalog.unnest($3::TEXT[]) AS needle(value) '
                           ' WHERE needle.value IS NOT NULL '
                           ' AND pg_catalog.strpos(COALESCE(source.%I::TEXT, ''''), needle.value) > 0'
                           ')',
                           columns.column_name
                       )
                   END,
                   ' OR ' ORDER BY columns.ordinal_position
               ) AS predicate
        FROM information_schema.columns AS columns
        JOIN pg_catalog.pg_class AS relation
          ON relation.relname = columns.table_name
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
         AND namespace.nspname = columns.table_schema
        LEFT JOIN br_private.account_deletion_identity_policy AS policy
          ON policy.table_name = columns.table_name
         AND policy.identity_column = columns.column_name
        WHERE columns.table_schema = 'public'
          AND relation.relkind IN ('r', 'p')
          AND columns.udt_name IN (
              'uuid', 'text', 'varchar', 'bpchar', 'json', 'jsonb', '_text', '_uuid'
          )
        GROUP BY columns.table_name, relation.oid, relation.relkind
    LOOP
        IF v_spec.relkind = 'r'
           AND pg_catalog.pg_relation_size(v_spec.relation_oid) = 0 THEN
            CONTINUE;
        END IF;
        EXECUTE pg_catalog.format(
            'SELECT EXISTS (SELECT 1 FROM public.%I AS source WHERE %s)',
            v_spec.table_name, v_spec.predicate
        ) INTO v_found USING
            p_user_id,
            COALESCE(p_ride_ids, ARRAY[]::UUID[]),
            v_needles,
            p_wallet;
        IF v_found THEN
            v_residue := v_residue || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'table', v_spec.table_name,
                    'column', '*',
                    'kind', 'original_identity',
                    'count', 1
                )
            );
        END IF;
    END LOOP;

    SELECT count(*) INTO v_count
    FROM public.users AS "user"
    WHERE "user".id = p_anonymous_marker
      AND "user".anonymous_marker = p_anonymous_marker
      AND "user".wallet = 'anonymous:' || p_anonymous_marker::TEXT
      AND "user".account_state = 'anonymized'
      AND "user".email IS NULL
      AND "user".username IS NULL
      AND "user".display_name IS NULL
      AND "user".bio IS NULL
      AND "user".avatar_url IS NULL
      AND "user".weight_kg IS NULL
      AND "user".ftp_w IS NULL
      AND "user".location IS NULL
      AND "user".is_public IS FALSE;
    IF v_count <> 1 THEN
        v_residue := v_residue || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'table', 'users', 'column', 'anonymous_marker',
                'kind', 'anonymous_principal_invariant', 'count', v_count
            )
        );
    END IF;
    RETURN v_residue;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_account_anonymization(
    p_request_id UUID,
    p_user_id UUID,
    p_lease_token UUID
)
RETURNS SETOF public.deletion_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_request public.deletion_requests%ROWTYPE;
    v_wallet_fingerprint TEXT;
    v_wallet TEXT;
    v_email TEXT;
    v_marker UUID := pg_catalog.gen_random_uuid();
    v_anonymous_wallet TEXT;
    v_blockers JSONB;
    v_residue JSONB;
    v_ride_ids UUID[] := ARRAY[]::UUID[];
    v_ride_id_texts TEXT[] := ARRAY[]::TEXT[];
    v_spec RECORD;
    v_count BIGINT;
    v_set_clause TEXT;
BEGIN
    SELECT request.wallet_fingerprint INTO v_wallet_fingerprint
    FROM public.deletion_requests AS request WHERE request.id = p_request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account_deletion_finalization_precondition_failed'
            USING ERRCODE = '55000';
    END IF;
    PERFORM public.br_lock_account_deletion_wallet(v_wallet_fingerprint);

    SELECT * INTO v_request
    FROM public.deletion_requests AS request
    WHERE request.id = p_request_id
    FOR UPDATE;
    IF NOT FOUND OR v_request.user_id IS DISTINCT FROM p_user_id
       OR v_request.status <> 'processing'
       OR v_request.worker_lease_token IS DISTINCT FROM p_lease_token
       OR v_request.worker_lease_until <= clock_timestamp()
       OR NOT v_request.unuploaded_rides_acknowledged
       OR v_request.storage_authorized_at IS NULL
       OR v_request.storage_completed_at IS NULL
       OR v_request.preflight_checked_at IS NULL
       OR pg_catalog.jsonb_typeof(v_request.preflight_snapshot) <> 'object'
       OR pg_catalog.jsonb_typeof(v_request.preflight_snapshot -> 'blockers') <> 'array'
       OR pg_catalog.jsonb_array_length(v_request.preflight_snapshot -> 'blockers') <> 0
       OR COALESCE((v_request.preflight_snapshot ->> 'allowed')::BOOLEAN, FALSE) IS NOT TRUE
       OR COALESCE((v_request.preflight_snapshot ->> 'available')::BOOLEAN, FALSE) IS NOT TRUE
       OR COALESCE(
           (v_request.preflight_snapshot ->> 'destructive_boundary_available')::BOOLEAN,
           FALSE
       ) IS NOT TRUE THEN
        RAISE EXCEPTION 'account_deletion_finalization_precondition_failed'
            USING ERRCODE = '55000';
    END IF;

    SELECT "user".wallet, "user".email INTO v_wallet, v_email
    FROM public.users AS "user"
    WHERE "user".id = p_user_id
      AND "user".account_state = 'deletion_pending'
      AND "user".account_deletion_request_id = p_request_id
    FOR UPDATE;
    IF NOT FOUND OR v_wallet IS DISTINCT FROM v_request.wallet THEN
        RAISE EXCEPTION 'account_deletion_user_fence_missing'
            USING ERRCODE = '55000';
    END IF;
    SELECT COALESCE(pg_catalog.array_agg(ride.id), ARRAY[]::UUID[])
    INTO v_ride_ids
    FROM public.rides AS ride WHERE ride.user_id = p_user_id;
    SELECT COALESCE(pg_catalog.array_agg(ride_id::TEXT), ARRAY[]::TEXT[])
    INTO v_ride_id_texts
    FROM pg_catalog.unnest(v_ride_ids) AS ride(ride_id);

    v_blockers := public.br_account_deletion_db_blockers(p_user_id, v_wallet);
    IF pg_catalog.jsonb_array_length(v_blockers) > 0 THEN
        UPDATE public.deletion_requests
        SET status = 'needs_support', blockers = v_blockers,
            failure_code = 'blocker_after_storage_authorization',
            worker_id = NULL, worker_lease_token = NULL, worker_lease_until = NULL,
            updated_at = clock_timestamp()
        WHERE id = p_request_id RETURNING * INTO v_request;
        RETURN NEXT v_request;
        RETURN;
    END IF;

    PERFORM pg_catalog.set_config('app.account_deletion_request_id', p_request_id::TEXT, TRUE);
    v_anonymous_wallet := 'anonymous:' || v_marker::TEXT;

    -- The anonymous principal is a genuinely new public identifier.  Retained
    -- sporting/economic facts are moved to it before the original principal
    -- is deleted, so the old UUID cannot remain a rider-facing fallback.
    INSERT INTO public.users (
        id, wallet, email, is_public, follower_count, following_count,
        default_ride_visibility, default_map_visibility,
        default_map_hide_start_m, default_map_hide_end_m,
        account_state, anonymous_marker, account_deleted_at,
        account_deletion_locked_at, account_deletion_request_id, updated_at
    ) VALUES (
        v_marker, v_anonymous_wallet, NULL, FALSE, 0, 0,
        'private', 'hide_entire', 0, 0,
        'anonymized', v_marker, clock_timestamp(), NULL, NULL, clock_timestamp()
    );

    -- Credentials, provider links, device/contact data, social content,
    -- training aggregates, location traces, and user-authored profile data are
    -- removed. Optional tables are executed dynamically so older installations
    -- remain migration-safe without weakening the completion invariant.
    DELETE FROM public.auth_refresh_tokens WHERE wallet = v_wallet;
    DELETE FROM public.auth_nonces WHERE wallet = v_wallet;
    DELETE FROM public.auth_identities WHERE user_id = p_user_id;
    IF pg_catalog.to_regclass('public.strava_imported_activities') IS NOT NULL THEN
        EXECUTE $query$
            DELETE FROM public.strava_imported_activities
            WHERE strava_connection_id IN (
                SELECT id FROM public.strava_connections WHERE wallet = $1
            )
        $query$ USING v_wallet;
    END IF;
    DELETE FROM public.strava_connections WHERE wallet = v_wallet;
    DELETE FROM public.privacy_zones WHERE user_id = p_user_id;
    IF pg_catalog.to_regclass('public.gps_points') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.gps_points WHERE ride_id IN '
                '(SELECT id FROM public.rides WHERE user_id = $1)'
            USING p_user_id;
    END IF;
    DELETE FROM public.activity_streams
    WHERE ride_id IN (SELECT id FROM public.rides WHERE user_id = p_user_id);
    IF pg_catalog.to_regclass('public.activity_tile_samples') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.activity_tile_samples WHERE activity_id IN '
                '(SELECT id FROM public.rides WHERE user_id = $1)'
            USING p_user_id;
    END IF;
    IF pg_catalog.to_regclass('public.ride_climb_backfill_reviews') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.ride_climb_backfill_reviews WHERE activity_id IN '
                '(SELECT id FROM public.rides WHERE user_id = $1)'
            USING p_user_id;
    END IF;
    DELETE FROM public.ride_media WHERE user_id = p_user_id;
    DELETE FROM public.mobile_push_devices WHERE wallet = v_wallet;
    IF pg_catalog.to_regclass('public.mobile_push_deliveries') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.mobile_push_deliveries WHERE wallet = $1'
            USING v_wallet;
    END IF;
    DELETE FROM public.ios_diagnostics WHERE wallet = v_wallet;
    IF pg_catalog.to_regclass('public.invite_code_usage') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.invite_code_usage WHERE wallet = $1'
            USING v_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.bot_links') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.bot_links WHERE wallet = $1' USING v_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.user_profile_snapshots') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.user_profile_snapshots WHERE wallet = $1'
            USING v_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.wallet_tile_history') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.wallet_tile_history WHERE wallet = $1'
            USING v_wallet;
    END IF;

    FOR v_spec IN
        SELECT * FROM (VALUES
            ('achievements', 'user_id'),
            ('daily_training_load', 'user_id'),
            ('fitness_metrics', 'user_id'),
            ('activities', 'user_id'),
            ('notifications', 'user_id'),
            ('notification_preferences', 'user_id'),
            ('export_requests', 'user_id'),
            ('comments', 'user_id'),
            ('kudos', 'user_id'),
            ('social_reports', 'reporter_id'),
            ('admin_users', 'user_id')
        ) AS personal(table_name, column_name)
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'DELETE FROM public.%I WHERE %I = $1',
                v_spec.table_name,
                v_spec.column_name
            ) USING p_user_id;
        END IF;
    END LOOP;
    IF pg_catalog.to_regclass('public.follows') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.follows WHERE follower_id = $1 OR following_id = $1'
            USING p_user_id;
    END IF;
    IF pg_catalog.to_regclass('public.social_reports') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.social_reports WHERE target_id = $1'
            USING p_user_id;
    END IF;
    IF pg_catalog.to_regclass('public.waitlist') IS NOT NULL
       AND v_email IS NOT NULL AND v_email <> '' THEN
        EXECUTE 'DELETE FROM public.waitlist WHERE lower(email) = lower($1)'
            USING v_email;
    END IF;

    -- Shared moderation/audit history can remain only after its actor, free
    -- text, metadata, network and device identifiers are removed.
    IF pg_catalog.to_regclass('public.moderation_actions') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.moderation_actions
            SET actor_id = NULL, note = NULL, metadata = '{}'::JSONB,
                target_id = CASE WHEN target_id = $1::TEXT THEN 'deleted-account' ELSE target_id END
            WHERE actor_id = $1 OR target_id = $1::TEXT
        $query$ USING p_user_id;
        EXECUTE $query$
            UPDATE public.moderation_actions
            SET note = NULL, metadata = '{}'::JSONB, target_id = 'deleted-ride'
            WHERE target_id = ANY($1)
        $query$ USING v_ride_id_texts;
    END IF;

    UPDATE public.audit_log
    SET user_id = NULL, target_id = CASE WHEN target_id = p_user_id THEN NULL ELSE target_id END,
        metadata = '{}'::JSONB, ip_address = NULL, user_agent = NULL
    WHERE user_id = p_user_id OR target_id = p_user_id;
    UPDATE public.audit_log
    SET target_id = NULL, metadata = '{}'::JSONB,
        ip_address = NULL, user_agent = NULL
    WHERE target_id = ANY(v_ride_ids);

    -- Preserve only the ratified athletic facts: climb/segment identity, time,
    -- placement and history dates. Physiological, route-sample, signature and
    -- old ride identifiers are removed.
    UPDATE public.segment_efforts
    SET user_id = v_marker, ride_id = NULL, started_at = NULL,
        effort_score = NULL, average_power_w = NULL, average_hr_bpm = NULL,
        average_speed_mps = NULL, elevation_gain_m = NULL, distance_m = NULL
    WHERE user_id = p_user_id;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'segment_efforts'
          AND column_name = 'tss'
    ) THEN
        EXECUTE 'UPDATE public.segment_efforts SET tss = NULL WHERE user_id = $1'
            USING v_marker;
    END IF;
    UPDATE public.leaderboard_entries
    SET user_id = v_marker, tss = NULL
    WHERE user_id = p_user_id;
    IF pg_catalog.to_regclass('public.patterns_climb') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.patterns_climb
            SET activity_id = NULL, wallet = $2,
                avg_power_w = NULL, w_per_kg = NULL, avg_hr = NULL,
                start_offset_s = 0, end_offset_s = 0
            WHERE wallet = $1
        $query$ USING v_wallet, v_anonymous_wallet;
        SELECT pg_catalog.string_agg(
            pg_catalog.format('%I = NULL', columns.column_name), ', '
            ORDER BY columns.ordinal_position
        ) INTO v_set_clause
        FROM information_schema.columns AS columns
        WHERE columns.table_schema = 'public'
          AND columns.table_name = 'patterns_climb'
          AND columns.column_name IN (
              'start_lat', 'start_lon', 'end_lat', 'end_lon', 'tile_ids',
              'signature_hex', 'signature_v2_hex', 'match_trace',
              'reviewed_by', 'attribution_summary', 'abstention_reasons',
              'significance_cell_h3'
          );
        IF v_set_clause IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'UPDATE public.patterns_climb SET %s WHERE wallet = $1',
                v_set_clause
            ) USING v_anonymous_wallet;
        END IF;
    END IF;
    IF pg_catalog.to_regclass('public.patterns_steady') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.patterns_steady WHERE wallet = $1' USING v_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.patterns_exploration') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.patterns_exploration WHERE wallet = $1' USING v_wallet;
    END IF;

    -- Preserve ratified leaderboard and settled off-chain economic history
    -- under the anonymous marker. Any row carrying an unresolved proof or
    -- chain edge was rejected by br_account_deletion_db_blockers above.
    UPDATE public.leaderboard_history
    SET wallet = CASE WHEN wallet = v_wallet THEN v_anonymous_wallet ELSE wallet END,
        bumped_by_wallet = CASE
            WHEN bumped_by_wallet = v_wallet THEN v_anonymous_wallet
            ELSE bumped_by_wallet
        END
    WHERE wallet = v_wallet OR bumped_by_wallet = v_wallet;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'leaderboard_history'
          AND column_name = 'avg_power_w'
    ) THEN
        EXECUTE 'UPDATE public.leaderboard_history SET avg_power_w = NULL '
                'WHERE wallet = $1'
            USING v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.vault_leaderboards') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.vault_leaderboards
            SET wallet = $2, avg_power_w = NULL, completion_id = NULL,
                device_name = NULL, activity_id = NULL,
                flagged_by = CASE WHEN flagged_by = $1 THEN $2 ELSE flagged_by END,
                flag_reason = NULL
            WHERE wallet = $1
        $query$ USING v_wallet, v_anonymous_wallet;
        EXECUTE 'UPDATE public.vault_leaderboards '
                'SET flagged_by = $2, flag_reason = NULL WHERE flagged_by = $1'
            USING v_wallet, v_anonymous_wallet;
    END IF;
    UPDATE public.vault_completions
    SET wallet = v_anonymous_wallet,
        activity_id = 'anonymous:' || pg_catalog.gen_random_uuid()::TEXT,
        avg_power_w = NULL, device_name = NULL, validation_notes = NULL,
        on_chain_tx_error = NULL
    WHERE wallet = v_wallet;
    IF pg_catalog.to_regclass('public.leaderboard_disputes') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.leaderboard_disputes
            SET disputed_wallet = CASE WHEN disputed_wallet = $1 THEN $2 ELSE disputed_wallet END,
                flagged_by = CASE WHEN flagged_by = $1 THEN $2 ELSE flagged_by END,
                resolved_by = CASE WHEN resolved_by = $1 THEN $2 ELSE resolved_by END,
                flag_reason = NULL, evidence_notes = NULL, resolution_notes = NULL
            WHERE disputed_wallet = $1 OR flagged_by = $1 OR resolved_by = $1
        $query$ USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.swanny_elections') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.swanny_elections
            SET winner_wallet = CASE WHEN winner_wallet = $1 THEN $2 ELSE winner_wallet END,
                runner_up_wallet = CASE WHEN runner_up_wallet = $1 THEN $2 ELSE runner_up_wallet END
            WHERE winner_wallet = $1 OR runner_up_wallet = $1
        $query$ USING v_wallet, v_anonymous_wallet;
    END IF;
    FOR v_spec IN
        SELECT policy.*
        FROM br_private.account_deletion_identity_policy AS policy
        ORDER BY policy.table_name, policy.identity_column
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NOT NULL THEN
            EXECUTE pg_catalog.format(
                'UPDATE public.%I SET %I = $2 WHERE %I = $1 AND (%s)',
                v_spec.table_name,
                v_spec.identity_column,
                v_spec.identity_column,
                v_spec.scrub_predicate
            ) USING v_wallet, v_anonymous_wallet;
        END IF;
    END LOOP;
    IF pg_catalog.to_regclass('public.local_legend_rollovers') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.local_legend_rollovers
            SET previous_holder = CASE WHEN previous_holder = $1 THEN $2 ELSE previous_holder END,
                winner = CASE WHEN winner = $1 THEN $2 ELSE winner END,
                runner_up = CASE WHEN runner_up = $1 THEN $2 ELSE runner_up END,
                error_message = NULL
            WHERE previous_holder = $1 OR winner = $1 OR runner_up = $1
        $query$ USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.distribution_receipts') IS NOT NULL THEN
        EXECUTE 'UPDATE public.distribution_receipts SET wallet = $2 WHERE wallet = $1'
            USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.vault_distributions') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.vault_distributions
            SET leaderboard_details = public.br_jsonb_replace_exact_string(
                leaderboard_details, $1, $2
            )
            WHERE leaderboard_details IS NOT NULL
              AND leaderboard_details::TEXT LIKE '%' || pg_catalog.to_jsonb($1::TEXT)::TEXT || '%'
        $query$ USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.vault_shadow_usdc') IS NOT NULL THEN
        EXECUTE 'UPDATE public.vault_shadow_usdc SET wallet = $2 '
                'WHERE wallet = $1 AND settled_at IS NOT NULL'
            USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.wallet_points') IS NOT NULL THEN
        -- wallet_points.wallet is the parent key for points_events and for its
        -- own referral edge without ON UPDATE CASCADE. Create the anonymous
        -- parent first, rekey settled children, then remove the old parent.
        EXECUTE $query$
            INSERT INTO public.wallet_points (
                wallet, total_points, points_from_tss, points_from_creation,
                points_from_referral, points_from_leaderboard,
                points_from_staking, lifetime_points_earned, referred_by,
                created_at, updated_at
            )
            SELECT $2, total_points, points_from_tss, points_from_creation,
                   points_from_referral, points_from_leaderboard,
                   points_from_staking, lifetime_points_earned, NULL,
                   created_at, updated_at
            FROM public.wallet_points WHERE wallet = $1
        $query$ USING v_wallet, v_anonymous_wallet;
        IF pg_catalog.to_regclass('public.points_events') IS NOT NULL THEN
            EXECUTE 'UPDATE public.points_events SET wallet = $2, '
                    'reference_id = NULL, metadata = ''{}''::JSONB '
                    'WHERE wallet = $1'
                USING v_wallet, v_anonymous_wallet;
        END IF;
        EXECUTE 'UPDATE public.wallet_points SET referred_by = $2 WHERE referred_by = $1'
            USING v_wallet, v_anonymous_wallet;
        EXECUTE 'DELETE FROM public.wallet_points WHERE wallet = $1'
            USING v_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.cal_daily_balances') IS NOT NULL THEN
        EXECUTE 'UPDATE public.cal_daily_balances SET wallet = $2 WHERE wallet = $1'
            USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.vault_cal_contributions') IS NOT NULL THEN
        EXECUTE 'UPDATE public.vault_cal_contributions SET wallet = $2, '
                'activity_id = pg_catalog.gen_random_uuid() WHERE wallet = $1'
            USING v_wallet, v_anonymous_wallet;
    END IF;
    IF pg_catalog.to_regclass('public.token_transactions') IS NOT NULL THEN
        EXECUTE 'UPDATE public.token_transactions SET user_id = $2, '
                'reference_id = NULL, tx_signature = NULL, metadata = ''{}''::JSONB '
                'WHERE user_id = $1'
            USING p_user_id, v_marker;
    END IF;
    IF pg_catalog.to_regclass('public.user_stats') IS NOT NULL THEN
        EXECUTE 'DELETE FROM public.user_stats WHERE user_id = $1' USING p_user_id;
    END IF;
    DELETE FROM public.user_state WHERE user_id = p_user_id;

    -- Operational actor references are scrubbed schema-wide. Nullable actor
    -- fields lose attribution; non-nullable audit fields move to the anonymous
    -- principal instead of retaining the original UUID.
    FOR v_spec IN
        SELECT columns.table_name, columns.column_name,
               columns.is_nullable = 'YES' AS is_nullable
        FROM information_schema.columns AS columns
        WHERE columns.table_schema = 'public'
          AND columns.udt_name = 'uuid'
          AND columns.column_name IN (
              'actor_id', 'reviewed_by', 'moderated_by', 'resolved_by',
              'updated_by', 'created_by'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'UPDATE public.%I SET %I = %s WHERE %I = $1',
            v_spec.table_name,
            v_spec.column_name,
            CASE WHEN v_spec.is_nullable THEN 'NULL' ELSE '$2' END,
            v_spec.column_name
        ) USING p_user_id, v_marker;
    END LOOP;
    FOR v_spec IN
        SELECT columns.table_name, columns.column_name
        FROM information_schema.columns AS columns
        WHERE columns.table_schema = 'public'
          AND columns.udt_name IN ('text', 'varchar', 'bpchar')
          AND columns.column_name IN (
              'reviewer_wallet', 'admin_wallet', 'created_by', 'reviewed_by'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'UPDATE public.%I SET %I = $2 WHERE %I = $1',
            v_spec.table_name, v_spec.column_name, v_spec.column_name
        ) USING v_wallet, v_anonymous_wallet;
    END LOOP;

    -- Detach every retained result first, then remove the general ride record.
    -- Any unhandled ride foreign key aborts the transaction instead of being
    -- silently cascaded away or leaving a public link.
    FOR v_spec IN
        SELECT child_ns.nspname AS schema_name,
               child.relname AS table_name,
               child_column.attname AS column_name
        FROM pg_catalog.pg_constraint AS constraint_row
        JOIN pg_catalog.pg_class AS child ON child.oid = constraint_row.conrelid
        JOIN pg_catalog.pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
        JOIN pg_catalog.pg_attribute AS child_column
          ON child_column.attrelid = child.oid
         AND child_column.attnum = constraint_row.conkey[1]
        WHERE constraint_row.contype = 'f'
          AND constraint_row.confrelid = 'public.rides'::regclass
          AND child_ns.nspname = 'public'
    LOOP
        EXECUTE pg_catalog.format(
            'SELECT count(*) FROM %I.%I WHERE %I IN '
            '(SELECT id FROM public.rides WHERE user_id = $1)',
            v_spec.schema_name, v_spec.table_name, v_spec.column_name
        ) INTO v_count USING p_user_id;
        IF v_count > 0 THEN
            RAISE EXCEPTION 'account_deletion_unhandled_ride_reference:%',
                v_spec.table_name USING ERRCODE = '55000';
        END IF;
    END LOOP;
    DELETE FROM public.rides WHERE user_id = p_user_id;

    -- No request row may retain the old principal. Legacy/unverified rows keep
    -- their truthful state, but their identity, error text and local receipts
    -- are scrubbed alongside the current v1 request.
    UPDATE public.deletion_requests
    SET user_id = NULL, wallet = NULL,
        storage_paths = '[]'::JSONB, storage_receipts = '{}'::JSONB,
        local_review_receipt = NULL, preflight_snapshot = '{}'::JSONB,
        error_message = NULL
    WHERE id = p_request_id OR user_id = p_user_id OR wallet = v_wallet;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users'
          AND column_name = 'moderated_by'
    ) THEN
        EXECUTE 'UPDATE public.users SET moderated_by = NULL WHERE moderated_by = $1'
            USING p_user_id;
    END IF;

    FOR v_spec IN
        SELECT child_ns.nspname AS schema_name,
               child.relname AS table_name,
               child_column.attname AS column_name
        FROM pg_catalog.pg_constraint AS constraint_row
        JOIN pg_catalog.pg_class AS child ON child.oid = constraint_row.conrelid
        JOIN pg_catalog.pg_namespace AS child_ns ON child_ns.oid = child.relnamespace
        JOIN pg_catalog.pg_attribute AS child_column
          ON child_column.attrelid = child.oid
         AND child_column.attnum = constraint_row.conkey[1]
        WHERE constraint_row.contype = 'f'
          AND constraint_row.confrelid = 'public.users'::regclass
          AND child_ns.nspname = 'public'
    LOOP
        EXECUTE pg_catalog.format(
            'SELECT count(*) FROM %I.%I WHERE %I = $1',
            v_spec.schema_name, v_spec.table_name, v_spec.column_name
        ) INTO v_count USING p_user_id;
        IF v_count > 0 THEN
            RAISE EXCEPTION 'account_deletion_unhandled_user_reference:%',
                v_spec.table_name USING ERRCODE = '55000';
        END IF;
    END LOOP;
    DELETE FROM public.users WHERE id = p_user_id;
    PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);

    v_residue := public.br_account_deletion_personal_residue(
        p_user_id, v_wallet, v_email, v_ride_ids, v_marker
    );
    IF pg_catalog.jsonb_array_length(v_residue) > 0 THEN
        RAISE EXCEPTION 'account_deletion_personal_residue:%', v_residue::TEXT
            USING ERRCODE = '55000';
    END IF;

    INSERT INTO public.deleted_account_tombstones (
        wallet_fingerprint, anonymous_marker, deletion_request_id, deleted_at
    ) VALUES (
        v_request.wallet_fingerprint, v_marker, p_request_id, clock_timestamp()
    );

    UPDATE public.deletion_requests
    SET wallet = NULL, status = 'completed',
        blockers = '[]'::JSONB, failure_code = NULL,
        worker_id = NULL, worker_lease_token = NULL, worker_lease_until = NULL,
        completed_at = clock_timestamp(), completion_verified_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE id = p_request_id
    RETURNING * INTO v_request;

    RETURN NEXT v_request;
END;
$$;

-- Internal lifecycle functions are not rider-callable PostgREST endpoints.
REVOKE EXECUTE ON FUNCTION br_private.account_deletion_random_bytes(INTEGER) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION br_private.account_deletion_hmac(BYTEA, BYTEA, TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_wallet_fingerprint(TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.br_lock_account_deletion_wallet(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_is_account_deleted(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_get_auth_account_authority(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_jsonb_replace_exact_string(JSONB, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_get_or_create_active_user(UUID, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_user_account_lifecycle_fence() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_issue_auth_nonce(UUID, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_consume_auth_nonce(UUID, TEXT, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_assert_wallet_write_allowed(TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_invite_usage_fence() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.consume_invite_code(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.account_deletion_write_fence() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_write_fence_active() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.account_deletion_ride_write_fence_statement() FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_storage_paths(UUID) FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.create_account_deletion_request(UUID, UUID, TEXT, BOOLEAN, TEXT, JSONB, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.claim_account_deletion_request(UUID, UUID, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mark_account_deletion_blocked(UUID, JSONB, UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.support_account_deletion_request(UUID, JSONB, UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.fail_account_deletion_request(UUID, UUID, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.fail_account_deletion_dispatch(UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.renew_account_deletion_lease(UUID, UUID, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.authorize_account_deletion_storage(UUID, UUID, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.record_account_deletion_storage_receipt(UUID, UUID, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.mark_account_deletion_storage_removed(UUID, UUID, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.retry_account_deletion_request(UUID, JSONB) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.list_recoverable_account_deletions(INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.br_account_deletion_personal_residue(UUID, TEXT, TEXT, UUID[], UUID) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.finalize_account_anonymization(UUID, UUID, UUID) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.br_get_or_create_active_user(UUID, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_is_account_deleted(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_get_auth_account_authority(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_issue_auth_nonce(UUID, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_consume_auth_nonce(UUID, TEXT, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_invite_code(TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.create_account_deletion_request(UUID, UUID, TEXT, BOOLEAN, TEXT, JSONB, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_account_deletion_request(UUID, UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.mark_account_deletion_blocked(UUID, JSONB, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.support_account_deletion_request(UUID, JSONB, UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_account_deletion_request(UUID, UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.fail_account_deletion_dispatch(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_account_deletion_lease(UUID, UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.authorize_account_deletion_storage(UUID, UUID, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_account_deletion_storage_receipt(UUID, UUID, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.mark_account_deletion_storage_removed(UUID, UUID, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.retry_account_deletion_request(UUID, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.list_recoverable_account_deletions(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.finalize_account_anonymization(UUID, UUID, UUID) TO service_role;

COMMENT ON TABLE public.deletion_requests IS
    'Durable account-deletion state. completed means atomic anonymization and tombstone verification succeeded.';
COMMENT ON TABLE public.deleted_account_tombstones IS
    'Private HMAC wallet fingerprints that prevent deleted identities from recreating accounts.';
