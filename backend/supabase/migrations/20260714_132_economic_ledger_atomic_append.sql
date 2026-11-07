-- Exact, serialized append authority for the economic ledger.
--
-- Historical hash-v1 rows remain byte-for-byte unchanged. New rows use a
-- scale-neutral v2 hash over exact NUMERIC values and can only be appended by
-- the service-owned RPC, which serializes each wallet/denomination stream.

ALTER TABLE public.economic_events
    ADD COLUMN IF NOT EXISTS hash_version SMALLINT;

-- The deployed immutability trigger predates hash_version and correctly blocks
-- every ordinary update. Replace it after the one-time legacy annotation.
DROP TRIGGER IF EXISTS trg_ledger_immutable ON public.economic_events;

UPDATE public.economic_events
SET hash_version = 1
WHERE hash_version IS NULL;

ALTER TABLE public.economic_events
    ALTER COLUMN hash_version SET DEFAULT 2,
    ALTER COLUMN hash_version SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.economic_events'::regclass
          AND conname = 'economic_events_hash_version_check'
    ) THEN
        ALTER TABLE public.economic_events
            ADD CONSTRAINT economic_events_hash_version_check
            CHECK (hash_version IN (1, 2));
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.canonical_ledger_numeric(p_value NUMERIC)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = ''
AS $$
DECLARE
    v_value TEXT;
BEGIN
    v_value := p_value::TEXT;
    IF v_value IN ('NaN', 'Infinity', '-Infinity') THEN
        RAISE EXCEPTION 'ledger amounts must be finite';
    END IF;
    IF p_value = 0 THEN
        RETURN '0';
    END IF;
    IF position('.' IN v_value) > 0 THEN
        v_value := regexp_replace(v_value, '0+$', '');
        v_value := regexp_replace(v_value, '[.]$', '');
    END IF;
    RETURN v_value;
END;
$$;

CREATE OR REPLACE FUNCTION public.economic_event_hash_v2(
    p_wallet TEXT,
    p_event_type TEXT,
    p_denomination TEXT,
    p_amount NUMERIC,
    p_balance_after NUMERIC,
    p_valid_at TIMESTAMPTZ,
    p_prev_hash TEXT
)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = ''
AS $$
DECLARE
    v_payload TEXT;
BEGIN
    v_payload := concat_ws(
        E'\n',
        'economic-event-v2',
        char_length(p_wallet)::TEXT || ':' || p_wallet,
        char_length(p_event_type)::TEXT || ':' || p_event_type,
        char_length(p_denomination)::TEXT || ':' || p_denomination,
        public.canonical_ledger_numeric(p_amount),
        public.canonical_ledger_numeric(p_balance_after),
        to_char(
            p_valid_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        p_prev_hash
    );
    RETURN pg_catalog.encode(
        pg_catalog.sha256(pg_catalog.convert_to(v_payload, 'UTF8')),
        'hex'
    );
END;
$$;

-- PostgreSQL STRICT functions do not run for NULL arguments. The public hash
-- helper therefore receives the explicit genesis marker from the append RPC.
CREATE OR REPLACE FUNCTION public.append_economic_event(
    p_wallet TEXT,
    p_event_type TEXT,
    p_amount TEXT,
    p_denomination TEXT,
    p_valid_at TIMESTAMPTZ,
    p_pipeline_version_id INTEGER,
    p_caused_by_id BIGINT DEFAULT NULL,
    p_batch_id UUID DEFAULT NULL,
    p_reference_type TEXT DEFAULT NULL,
    p_reference_id TEXT DEFAULT NULL,
    p_counterparty TEXT DEFAULT NULL,
    p_reversal_of_id BIGINT DEFAULT NULL,
    p_evidence JSONB DEFAULT NULL
)
RETURNS public.economic_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_amount NUMERIC;
    v_balance_after NUMERIC;
    v_previous_balance NUMERIC;
    v_previous_hash TEXT;
    v_event_hash TEXT;
    v_event public.economic_events%ROWTYPE;
BEGIN
    IF p_wallet IS NULL OR btrim(p_wallet) = '' THEN
        RAISE EXCEPTION 'wallet is required';
    END IF;
    IF p_event_type IS NULL OR btrim(p_event_type) = '' THEN
        RAISE EXCEPTION 'event_type is required';
    END IF;
    IF p_denomination IS NULL OR btrim(p_denomination) = '' THEN
        RAISE EXCEPTION 'denomination is required';
    END IF;
    IF p_valid_at IS NULL THEN
        RAISE EXCEPTION 'valid_at is required';
    END IF;
    IF p_pipeline_version_id IS NULL THEN
        RAISE EXCEPTION 'pipeline_version_id is required for new economic events';
    END IF;
    IF p_amount IS NULL
       OR length(p_amount) > 128
       OR p_amount !~ '^-?(0|[1-9][0-9]*)([.][0-9]+)?$' THEN
        RAISE EXCEPTION 'amount must be a canonical decimal string';
    END IF;

    v_amount := p_amount::NUMERIC;
    IF public.canonical_ledger_numeric(v_amount) <> p_amount THEN
        RAISE EXCEPTION 'amount must be scale-neutral canonical decimal text';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_wallet || pg_catalog.chr(31) || p_denomination,
            0
        )
    );

    SELECT btrim(event.event_hash)
    INTO v_previous_hash
    FROM public.economic_events AS event
    WHERE event.wallet = p_wallet
      AND event.denomination = p_denomination
    ORDER BY event.id DESC
    LIMIT 1;

    SELECT event.balance_after
    INTO v_previous_balance
    FROM public.economic_events AS event
    WHERE event.wallet = p_wallet
      AND event.denomination = p_denomination
      AND event.is_reversed = FALSE
    ORDER BY event.id DESC
    LIMIT 1;

    v_balance_after := COALESCE(v_previous_balance, 0) + v_amount;
    IF length(public.canonical_ledger_numeric(v_balance_after)) > 128 THEN
        RAISE EXCEPTION 'balance_after exceeds the 128-character exact-decimal limit';
    END IF;
    v_event_hash := public.economic_event_hash_v2(
        p_wallet,
        p_event_type,
        p_denomination,
        v_amount,
        v_balance_after,
        p_valid_at,
        COALESCE(v_previous_hash, 'genesis')
    );

    INSERT INTO public.economic_events (
        event_type,
        wallet,
        counterparty,
        amount,
        denomination,
        balance_after,
        caused_by_id,
        batch_id,
        pipeline_version_id,
        reference_type,
        reference_id,
        valid_at,
        reversal_of_id,
        is_reversed,
        evidence,
        prev_hash,
        event_hash,
        hash_version
    ) VALUES (
        p_event_type,
        p_wallet,
        p_counterparty,
        v_amount,
        p_denomination,
        v_balance_after,
        p_caused_by_id,
        p_batch_id,
        p_pipeline_version_id,
        p_reference_type,
        p_reference_id,
        p_valid_at,
        p_reversal_of_id,
        FALSE,
        p_evidence,
        v_previous_hash,
        v_event_hash,
        2
    )
    RETURNING * INTO v_event;

    RETURN v_event;
END;
$$;

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
       AND NEW.event_hash IS NOT DISTINCT FROM OLD.event_hash
       AND NEW.hash_version IS NOT DISTINCT FROM OLD.hash_version THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'UPDATE on economic_events is forbidden except is_reversed FALSE->TRUE';
END;
$$;

DROP TRIGGER IF EXISTS trg_ledger_immutable ON public.economic_events;
CREATE TRIGGER trg_ledger_immutable
    BEFORE UPDATE OR DELETE ON public.economic_events
    FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_mutation();

ALTER TABLE public.economic_events ENABLE ROW LEVEL SECURITY;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON TABLE public.economic_events
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE SELECT
    ON TABLE public.economic_events
    FROM PUBLIC, anon, authenticated;
REVOKE ALL
    ON SEQUENCE public.economic_events_id_seq
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.economic_events TO service_role;

REVOKE ALL ON FUNCTION public.append_economic_event(
    TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, INTEGER, BIGINT, UUID,
    TEXT, TEXT, TEXT, BIGINT, JSONB
) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.append_economic_event(
    TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, INTEGER, BIGINT, UUID,
    TEXT, TEXT, TEXT, BIGINT, JSONB
) TO service_role;

REVOKE ALL ON FUNCTION public.canonical_ledger_numeric(NUMERIC)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.economic_event_hash_v2(
    TEXT, TEXT, TEXT, NUMERIC, NUMERIC, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;

COMMENT ON COLUMN public.economic_events.hash_version IS
    '1 preserves legacy Python JSON hashes; 2 is the exact database-authoritative hash contract.';
COMMENT ON FUNCTION public.append_economic_event(
    TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, INTEGER, BIGINT, UUID,
    TEXT, TEXT, TEXT, BIGINT, JSONB
) IS
    'The only runtime ledger append authority. Serializes one wallet/denomination stream and hashes exact stored NUMERIC values.';
