-- Durable, finalized-evidence settlement recovery state machine.

CREATE OR REPLACE FUNCTION public.br_parse_u64_text(p_value TEXT, p_field TEXT)
RETURNS NUMERIC(39, 0)
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $$
DECLARE
    v_value NUMERIC(39, 0);
BEGIN
    IF p_value !~ '^(0|[1-9][0-9]*)$' THEN
        RAISE EXCEPTION '% must be a canonical u64 decimal string', p_field;
    END IF;
    v_value := p_value::NUMERIC(39, 0);
    IF v_value > 18446744073709551615::NUMERIC THEN
        RAISE EXCEPTION '% is outside the u64 range', p_field;
    END IF;
    RETURN v_value;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_parse_uint39_text(p_value TEXT, p_field TEXT)
RETURNS NUMERIC(39, 0)
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_value !~ '^(0|[1-9][0-9]*)$' OR pg_catalog.length(p_value) > 39 THEN
        RAISE EXCEPTION '% must be a canonical nonnegative decimal string', p_field;
    END IF;
    RETURN p_value::NUMERIC(39, 0);
END;
$$;

-- Snapshot legacy evidence before changing compatible integer columns. The
-- fractional CAL column intentionally remains fractional: invalid historical
-- values are blocked evidence and are never rewritten into executable zeroes.
DO $$
DECLARE
    v_column TEXT;
BEGIN
    IF pg_catalog.to_regclass('public.epoch_state') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.epoch_state '
            'ALTER COLUMN current_epoch TYPE NUMERIC(39, 0) USING current_epoch::NUMERIC';
    END IF;

    IF pg_catalog.to_regclass('public.epoch_distributions') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.epoch_distributions '
            'ADD COLUMN IF NOT EXISTS settlement_import_snapshot JSONB';
        EXECUTE $legacy$
            UPDATE public.epoch_distributions
            SET settlement_import_snapshot = pg_catalog.jsonb_build_object(
                'epoch', epoch::TEXT,
                'vault_id', vault_id::TEXT,
                'vault_signature', pg_catalog.btrim(vault_signature::TEXT),
                'cal_to_convert', cal_to_convert::TEXT,
                'dung_to_mint', dung_to_mint::TEXT,
                'leaderboard_amount', leaderboard_amount::TEXT,
                'staker_amount', staker_amount::TEXT,
                'local_legend_amount', local_legend_amount::TEXT,
                'pol_amount', pol_amount::TEXT,
                'protocol_amount', protocol_amount::TEXT,
                'locked_staker_amount', CASE
                    WHEN pg_catalog.to_jsonb(epoch_distributions)->'locked_staker_amount' IS NULL
                        THEN NULL
                    ELSE pg_catalog.to_jsonb(epoch_distributions)->>'locked_staker_amount'
                END,
                'is_points_period', is_points_period,
                'status', status,
                'tx_signature', tx_signature,
                'captured_at', pg_catalog.clock_timestamp()
            )
            WHERE settlement_import_snapshot IS NULL
        $legacy$;
        EXECUTE 'ALTER TABLE public.epoch_distributions '
            'ALTER COLUMN is_points_period SET DEFAULT FALSE, '
            'ALTER COLUMN epoch TYPE NUMERIC(39, 0) USING epoch::NUMERIC, '
            'ALTER COLUMN vault_id TYPE NUMERIC(39, 0) USING vault_id::NUMERIC, '
            'ALTER COLUMN dung_to_mint TYPE NUMERIC(39, 0) USING dung_to_mint::NUMERIC, '
            'ALTER COLUMN leaderboard_amount TYPE NUMERIC(39, 0) USING leaderboard_amount::NUMERIC, '
            'ALTER COLUMN staker_amount TYPE NUMERIC(39, 0) USING staker_amount::NUMERIC, '
            'ALTER COLUMN local_legend_amount TYPE NUMERIC(39, 0) USING local_legend_amount::NUMERIC, '
            'ALTER COLUMN pol_amount TYPE NUMERIC(39, 0) USING pol_amount::NUMERIC, '
            'ALTER COLUMN protocol_amount TYPE NUMERIC(39, 0) USING protocol_amount::NUMERIC';
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'epoch_distributions'
              AND column_name = 'locked_staker_amount'
        ) THEN
            EXECUTE 'ALTER TABLE public.epoch_distributions '
                'ALTER COLUMN locked_staker_amount TYPE NUMERIC(39, 0) '
                'USING locked_staker_amount::NUMERIC';
        END IF;
    END IF;

    IF pg_catalog.to_regclass('public.epoch_history') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE public.epoch_history '
            'ALTER COLUMN epoch TYPE NUMERIC(39, 0) USING epoch::NUMERIC, '
            'ALTER COLUMN total_cal_converted TYPE NUMERIC(39, 6) USING total_cal_converted::NUMERIC, '
            'ALTER COLUMN total_dung_minted TYPE NUMERIC(39, 0) USING total_dung_minted::NUMERIC';
    END IF;

    IF pg_catalog.to_regclass('public.indexed_epoch_distributions') IS NOT NULL THEN
        FOREACH v_column IN ARRAY ARRAY[
            'vault_id', 'epoch', 'total_distributed', 'leaderboard_distributed',
            'staker_distributed', 'local_legend_distributed', 'pol_distributed',
            'protocol_distributed', 'locked_staker_amount', 'slot'
        ] LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'indexed_epoch_distributions'
                  AND column_name = v_column
            ) THEN
                EXECUTE pg_catalog.format(
                    'ALTER TABLE public.indexed_epoch_distributions ALTER COLUMN %I '
                    'TYPE NUMERIC(39, 0) USING %I::NUMERIC', v_column, v_column
                );
            END IF;
        END LOOP;
    END IF;

    IF pg_catalog.to_regclass('public.indexed_vaults') IS NOT NULL THEN
        FOREACH v_column IN ARRAY ARRAY[
            'cal_tribute_accumulated', 'cal_tribute_accumulated_next',
            'total_cal_burned', 'total_dung_emitted', 'total_staked',
            'pending_rewards', 'pending_rewards_next_week',
            'reward_per_token_stored', 'reward_rate', 'open_settlement_week',
            'carry_record_royalty', 'carry_stakers', 'carry_local_legend',
            'carry_pol', 'carry_treasury', 'last_distribution_epoch',
            'total_cal_staked'
        ] LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'indexed_vaults'
                  AND column_name = v_column
            ) THEN
                EXECUTE pg_catalog.format(
                    'ALTER TABLE public.indexed_vaults ALTER COLUMN %I '
                    'TYPE NUMERIC(39, 0) USING %I::NUMERIC', v_column, v_column
                );
            END IF;
        END LOOP;
    END IF;

    IF pg_catalog.to_regclass('public.indexed_staker_allocations') IS NOT NULL THEN
        FOREACH v_column IN ARRAY ARRAY[
            'vault_id', 'epoch', 'amount', 'lp_tokens', 'eligible_from_epoch', 'slot'
        ] LOOP
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'indexed_staker_allocations'
                  AND column_name = v_column
            ) THEN
                EXECUTE pg_catalog.format(
                    'ALTER TABLE public.indexed_staker_allocations ALTER COLUMN %I '
                    'TYPE NUMERIC(39, 0) USING %I::NUMERIC', v_column, v_column
                );
            END IF;
        END LOOP;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.settlement_planning_state (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    bootstrap_state TEXT NOT NULL DEFAULT 'uninitialized'
        CHECK (bootstrap_state IN ('uninitialized', 'initialized')),
    last_materialized_week NUMERIC(39, 0)
        CHECK (last_materialized_week BETWEEN -1 AND 18446744073709551615::NUMERIC),
    bootstrap_counter_count NUMERIC(39, 0),
    bootstrap_source_slot NUMERIC(39, 0),
    bootstrap_source_slot_min NUMERIC(39, 0),
    bootstrap_source_slot_max NUMERIC(39, 0),
    bootstrap_scope_hash TEXT,
    bootstrap_min_open_week NUMERIC(39, 0),
    bootstrap_latest_finalizable_week NUMERIC(39, 0),
    bootstrap_evidence JSONB,
    bootstrapped_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    CHECK (
        (bootstrap_state = 'uninitialized' AND last_materialized_week IS NULL)
        OR
        (bootstrap_state = 'initialized'
         AND last_materialized_week IS NOT NULL
         AND bootstrap_counter_count IS NOT NULL
         AND bootstrap_source_slot IS NOT NULL
         AND bootstrap_scope_hash IS NOT NULL
         AND bootstrap_evidence IS NOT NULL)
    )
);

INSERT INTO public.settlement_planning_state (id, bootstrap_state, last_materialized_week)
VALUES (1, 'uninitialized', NULL)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.settlement_week_runs (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    settlement_week NUMERIC(39, 0) NOT NULL UNIQUE
        CHECK (settlement_week BETWEEN 0 AND 18446744073709551615::NUMERIC),
    state TEXT NOT NULL DEFAULT 'planning'
        CHECK (state IN ('planning', 'materialized', 'confirmed', 'review_required', 'blocked')),
    source_kind TEXT NOT NULL DEFAULT 'authoritative'
        CHECK (source_kind IN ('authoritative', 'legacy_import')),
    vault_counter_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    source_slot NUMERIC(39, 0),
    source_slot_min NUMERIC(39, 0),
    source_slot_max NUMERIC(39, 0),
    scope_evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    materialization_hash TEXT,
    expected_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    materialized_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    ready_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    skipped_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    blocked_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    review_job_count NUMERIC(39, 0) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    materialized_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    CHECK (
        vault_counter_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND expected_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND materialized_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND ready_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND skipped_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND blocked_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND review_job_count BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    CHECK (pg_catalog.jsonb_typeof(scope_evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS public.settlement_jobs (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.settlement_week_runs(id) ON DELETE CASCADE,
    settlement_week NUMERIC(39, 0) NOT NULL
        CHECK (settlement_week BETWEEN 0 AND 18446744073709551615::NUMERIC),
    vault_id NUMERIC(39, 0)
        CHECK (vault_id IS NULL OR vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC),
    vault_signature TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'authoritative'
        CHECK (source_kind IN ('authoritative', 'legacy_import')),
    legacy_evidence_only BOOLEAN NOT NULL DEFAULT FALSE,
    state TEXT NOT NULL CHECK (state IN (
        'precondition_pending', 'preparing', 'precondition_retry',
        'ready', 'skipped_empty', 'leased', 'submitted', 'reconciling',
        'retry_wait', 'confirmed', 'advanced_unproven', 'blocked'
    )),
    skip_reason TEXT,
    blocked_reason TEXT,
    expected_pre_open_week NUMERIC(39, 0) NOT NULL,
    auto_roll_from_empty BOOLEAN NOT NULL DEFAULT FALSE,
    cal_to_convert NUMERIC(39, 0) NOT NULL DEFAULT 0,
    dung_to_mint NUMERIC(39, 0) NOT NULL DEFAULT 0,
    current_week_value NUMERIC(39, 0) NOT NULL DEFAULT 0,
    next_week_value NUMERIC(39, 0) NOT NULL DEFAULT 0,
    pending_rewards NUMERIC(39, 0) NOT NULL DEFAULT 0,
    cal_tribute_accumulated NUMERIC(39, 0) NOT NULL DEFAULT 0,
    pending_rewards_next_week NUMERIC(39, 0) NOT NULL DEFAULT 0,
    cal_tribute_accumulated_next NUMERIC(39, 0) NOT NULL DEFAULT 0,
    carry_record_royalty NUMERIC(39, 0) NOT NULL DEFAULT 0,
    carry_stakers NUMERIC(39, 0) NOT NULL DEFAULT 0,
    carry_local_legend NUMERIC(39, 0) NOT NULL DEFAULT 0,
    carry_pol NUMERIC(39, 0) NOT NULL DEFAULT 0,
    carry_treasury NUMERIC(39, 0) NOT NULL DEFAULT 0,
    raw_snapshot JSONB NOT NULL,
    precondition_intent JSONB,
    precondition_result JSONB,
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    preparation_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (preparation_attempt_count >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    submit_started_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    next_reconcile_at TIMESTAMPTZ,
    prepared_tx_signature TEXT,
    tx_signature TEXT,
    terminal_evidence_quality TEXT,
    last_error_class TEXT,
    last_error TEXT,
    legacy_distribution_id UUID UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    confirmed_at TIMESTAMPTZ,
    CHECK (
        expected_pre_open_week BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND cal_to_convert BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND dung_to_mint BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND pending_rewards BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND cal_tribute_accumulated BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND pending_rewards_next_week BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND cal_tribute_accumulated_next BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND carry_record_royalty BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND carry_stakers BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND carry_local_legend BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND carry_pol BETWEEN 0 AND 18446744073709551615::NUMERIC
        AND carry_treasury BETWEEN 0 AND 18446744073709551615::NUMERIC
    ),
    CHECK (pg_catalog.jsonb_typeof(raw_snapshot) = 'object'),
    CHECK (precondition_intent IS NULL OR pg_catalog.jsonb_typeof(precondition_intent) = 'object'),
    CHECK (precondition_result IS NULL OR pg_catalog.jsonb_typeof(precondition_result) = 'object'),
    CHECK (state <> 'skipped_empty' OR skip_reason IS NOT NULL),
    CHECK (source_kind <> 'legacy_import' OR legacy_evidence_only),
    CHECK (
        state NOT IN ('preparing', 'leased')
        OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_settlement_authoritative_job
    ON public.settlement_jobs (run_id, vault_id)
    WHERE source_kind = 'authoritative';

CREATE TABLE IF NOT EXISTS public.settlement_attempts (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.settlement_jobs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    lease_token UUID NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('claimed', 'prepared', 'submitted', 'ambiguous', 'blocked')),
    tx_signature TEXT,
    error_class TEXT,
    error_message TEXT,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    UNIQUE (job_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS public.settlement_reconciliations (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES public.settlement_jobs(id) ON DELETE CASCADE,
    lease_token UUID NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN (
        'ready', 'confirmed', 'advanced_unproven', 'retry_wait', 'reconciling', 'blocked'
    )),
    signature_state TEXT NOT NULL CHECK (signature_state IN (
        'absent', 'pending', 'confirmed', 'finalized', 'failed', 'unknown'
    )),
    chain_commitment TEXT NOT NULL,
    observed_open_week NUMERIC(39, 0),
    indexed_tx_signature TEXT,
    indexed_signature_finalized BOOLEAN NOT NULL DEFAULT FALSE,
    recovered_tx_signature TEXT,
    evidence JSONB NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    CHECK (pg_catalog.jsonb_typeof(evidence) = 'object')
);

CREATE TABLE IF NOT EXISTS public.settlement_notification_outbox (
    id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    job_id UUID NOT NULL UNIQUE REFERENCES public.settlement_jobs(id) ON DELETE CASCADE,
    vault_id NUMERIC(39, 0) NOT NULL,
    vault_signature TEXT NOT NULL,
    settlement_week NUMERIC(39, 0) NOT NULL,
    raw_pending_dung NUMERIC(39, 0) NOT NULL,
    total_distributed NUMERIC(39, 0),
    tx_signature TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'delivering', 'delivered')),
    lease_owner TEXT,
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    delivered_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    CHECK (vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC),
    CHECK (settlement_week BETWEEN 0 AND 18446744073709551615::NUMERIC),
    CHECK (raw_pending_dung BETWEEN 0 AND 18446744073709551615::NUMERIC),
    CHECK (total_distributed IS NULL OR total_distributed BETWEEN 0 AND 18446744073709551615::NUMERIC)
);

CREATE INDEX IF NOT EXISTS idx_settlement_jobs_claim
    ON public.settlement_jobs (settlement_week, vault_id, created_at)
    WHERE state = 'ready';
CREATE INDEX IF NOT EXISTS idx_settlement_jobs_prepare
    ON public.settlement_jobs (next_attempt_at, settlement_week, vault_id)
    WHERE state IN ('precondition_pending', 'precondition_retry');
CREATE INDEX IF NOT EXISTS idx_settlement_jobs_reconcile
    ON public.settlement_jobs (next_reconcile_at, settlement_week, vault_id)
    WHERE state IN ('submitted', 'reconciling', 'retry_wait');
CREATE INDEX IF NOT EXISTS idx_settlement_jobs_lease_expiry
    ON public.settlement_jobs (lease_expires_at)
    WHERE lease_expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_settlement_outbox_claim
    ON public.settlement_notification_outbox (next_attempt_at, created_at)
    WHERE state IN ('pending', 'delivering');

CREATE OR REPLACE FUNCTION public.br_bootstrap_settlement_planning(
    p_counter_count TEXT,
    p_source_slot TEXT,
    p_latest_finalizable_week TEXT,
    p_vaults JSONB,
    p_scope_evidence JSONB
) RETURNS SETOF public.settlement_planning_state
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_counter NUMERIC(39, 0) := public.br_parse_u64_text(p_counter_count, 'counter_count');
    v_slot NUMERIC(39, 0) := public.br_parse_u64_text(p_source_slot, 'source_slot');
    v_latest NUMERIC(39, 0) := public.br_parse_u64_text(
        p_latest_finalizable_week, 'latest_finalizable_week'
    );
    v_slot_min NUMERIC(39, 0);
    v_slot_max NUMERIC(39, 0);
    v_min_open NUMERIC(39, 0);
    v_cursor NUMERIC(39, 0);
    v_scope_hash TEXT;
    v_state public.settlement_planning_state%ROWTYPE;
    v_count INTEGER;
    v_distinct_count INTEGER;
BEGIN
    IF pg_catalog.jsonb_typeof(p_vaults) <> 'array'
       OR pg_catalog.jsonb_typeof(p_scope_evidence) <> 'object' THEN
        RAISE EXCEPTION 'authoritative bootstrap evidence must be JSON objects/arrays';
    END IF;
    IF v_counter > 2147483647::NUMERIC
       OR pg_catalog.jsonb_array_length(p_vaults) <> v_counter::INTEGER THEN
        RAISE EXCEPTION 'incomplete bootstrap scope: expected %, received %',
            v_counter, pg_catalog.jsonb_array_length(p_vaults);
    END IF;
    IF p_scope_evidence->>'commitment' <> 'finalized'
       OR public.br_parse_u64_text(
            p_scope_evidence->>'counter_count', 'scope counter_count'
          ) <> v_counter THEN
        RAISE EXCEPTION 'bootstrap requires complete finalized VaultCounter evidence';
    END IF;

    v_slot_min := public.br_parse_u64_text(
        p_scope_evidence->>'source_slot_min', 'source_slot_min'
    );
    v_slot_max := public.br_parse_u64_text(
        p_scope_evidence->>'source_slot_max', 'source_slot_max'
    );
    IF v_slot_min > v_slot_max OR v_slot <> v_slot_max THEN
        RAISE EXCEPTION 'bootstrap source slot range is inconsistent';
    END IF;

    SELECT pg_catalog.count(*), pg_catalog.count(DISTINCT public.br_parse_u64_text(
               value->>'vault_id', 'vault_id'
           ))
    INTO v_count, v_distinct_count
    FROM pg_catalog.jsonb_array_elements(p_vaults);
    IF v_count <> v_distinct_count THEN
        RAISE EXCEPTION 'bootstrap contains duplicate vault IDs';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.jsonb_array_elements(p_vaults) item
        WHERE pg_catalog.jsonb_typeof(item) <> 'object'
           OR pg_catalog.jsonb_typeof(item->'vault_id') <> 'string'
           OR pg_catalog.jsonb_typeof(item->'open_settlement_week') <> 'string'
           OR public.br_parse_u64_text(item->>'vault_id', 'vault_id') >= v_counter
           OR coalesce(item->>'vault_pda', '') = ''
           OR coalesce(item->>'vault_signature', '') = ''
           OR coalesce(item->>'snapshot_hash', '') = ''
    ) THEN
        RAISE EXCEPTION 'bootstrap contains malformed counter-indexed vault evidence';
    END IF;

    IF v_counter = 0 THEN
        v_min_open := NULL;
        v_cursor := v_latest;
    ELSE
        SELECT pg_catalog.min(public.br_parse_u64_text(
                   value->>'open_settlement_week', 'open_settlement_week'
               ))
        INTO v_min_open
        FROM pg_catalog.jsonb_array_elements(p_vaults);
        v_cursor := least(v_latest, v_min_open - 1);
    END IF;

    v_scope_hash := pg_catalog.md5(
        p_vaults::TEXT || ':' || p_scope_evidence::TEXT || ':' || p_source_slot
    );

    SELECT * INTO v_state
    FROM public.settlement_planning_state
    WHERE id = 1
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement planning state row is missing';
    END IF;

    IF v_state.bootstrap_state = 'initialized' THEN
        IF v_state.bootstrap_counter_count <> v_counter
           OR v_state.bootstrap_source_slot <> v_slot
           OR v_state.bootstrap_scope_hash <> v_scope_hash
           OR v_state.bootstrap_latest_finalizable_week <> v_latest
           OR v_state.last_materialized_week <> v_cursor THEN
            RAISE EXCEPTION 'settlement bootstrap replay uses different authoritative evidence';
        END IF;
        RETURN NEXT v_state;
        RETURN;
    END IF;

    UPDATE public.settlement_planning_state
    SET bootstrap_state = 'initialized',
        last_materialized_week = v_cursor,
        bootstrap_counter_count = v_counter,
        bootstrap_source_slot = v_slot,
        bootstrap_source_slot_min = v_slot_min,
        bootstrap_source_slot_max = v_slot_max,
        bootstrap_scope_hash = v_scope_hash,
        bootstrap_min_open_week = v_min_open,
        bootstrap_latest_finalizable_week = v_latest,
        bootstrap_evidence = pg_catalog.jsonb_build_object(
            'vaults', p_vaults,
            'scope', p_scope_evidence,
            'safe_cursor', v_cursor::TEXT,
            'zero_vault_policy', CASE WHEN v_counter = 0
                THEN 'cursor_equals_latest_finalizable_week'
                ELSE NULL
            END
        ),
        bootstrapped_at = pg_catalog.now(),
        updated_at = pg_catalog.now()
    WHERE id = 1
    RETURNING * INTO v_state;

    RETURN NEXT v_state;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_refresh_settlement_run(p_run_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_run public.settlement_week_runs%ROWTYPE;
    v_total NUMERIC(39, 0);
    v_ready NUMERIC(39, 0);
    v_skipped NUMERIC(39, 0);
    v_blocked NUMERIC(39, 0);
    v_unfinished NUMERIC(39, 0);
    v_review NUMERIC(39, 0);
    v_legacy_review NUMERIC(39, 0);
    v_state TEXT;
BEGIN
    SELECT * INTO v_run
    FROM public.settlement_week_runs
    WHERE id = p_run_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement run % does not exist', p_run_id;
    END IF;

    SELECT
        pg_catalog.count(*) FILTER (WHERE source_kind = 'authoritative')::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE source_kind = 'authoritative' AND state = 'ready'
        )::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE source_kind = 'authoritative' AND state = 'skipped_empty'
        )::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE source_kind = 'authoritative' AND state = 'blocked'
        )::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE source_kind = 'authoritative'
              AND state NOT IN ('confirmed', 'skipped_empty', 'advanced_unproven')
        )::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE source_kind = 'authoritative' AND state = 'advanced_unproven'
        )::NUMERIC,
        pg_catalog.count(*) FILTER (
            WHERE legacy_evidence_only
              AND state IN ('blocked', 'reconciling', 'advanced_unproven')
        )::NUMERIC
    INTO v_total, v_ready, v_skipped, v_blocked, v_unfinished, v_review, v_legacy_review
    FROM public.settlement_jobs
    WHERE run_id = p_run_id;

    v_run.materialized_job_count := coalesce(v_total, 0);
    -- materialized_job_count <> expected_job_count can never be terminal.
    IF v_run.materialized_job_count <> v_run.expected_job_count THEN
        v_state := CASE WHEN v_run.state = 'planning' THEN 'planning' ELSE 'materialized' END;
    ELSIF coalesce(v_blocked, 0) > 0 THEN
        v_state := 'blocked';
    ELSIF coalesce(v_unfinished, 0) > 0 THEN
        v_state := 'materialized';
    ELSIF coalesce(v_review, 0) > 0
       OR coalesce(v_legacy_review, 0) > 0 THEN
        v_state := 'review_required';
    ELSE
        v_state := 'confirmed';
    END IF;

    UPDATE public.settlement_week_runs
    SET materialized_job_count = v_run.materialized_job_count,
        ready_job_count = coalesce(v_ready, 0),
        skipped_job_count = coalesce(v_skipped, 0),
        blocked_job_count = coalesce(v_blocked, 0),
        review_job_count = coalesce(v_review, 0) + coalesce(v_legacy_review, 0),
        state = v_state,
        completed_at = CASE
            WHEN v_state IN ('confirmed', 'review_required')
                THEN coalesce(completed_at, pg_catalog.now())
            ELSE NULL
        END,
        updated_at = pg_catalog.now()
    WHERE id = p_run_id;
END;
$$;

DROP FUNCTION IF EXISTS public.br_materialize_settlement_week(TEXT, TEXT, TEXT, JSONB);

CREATE OR REPLACE FUNCTION public.br_materialize_settlement_week(
    p_settlement_week TEXT,
    p_counter_count TEXT,
    p_source_slot TEXT,
    p_source_slot_min TEXT,
    p_source_slot_max TEXT,
    p_scope_evidence JSONB,
    p_jobs JSONB
) RETURNS TABLE (
    run_id UUID,
    settlement_week NUMERIC(39, 0),
    state TEXT,
    job_count INTEGER,
    ready_count INTEGER,
    skipped_count INTEGER
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    v_week NUMERIC(39, 0) := public.br_parse_u64_text(p_settlement_week, 'settlement_week');
    v_counter NUMERIC(39, 0) := public.br_parse_u64_text(p_counter_count, 'counter_count');
    v_slot NUMERIC(39, 0) := public.br_parse_u64_text(p_source_slot, 'source_slot');
    v_slot_min NUMERIC(39, 0) := public.br_parse_u64_text(p_source_slot_min, 'source_slot_min');
    v_slot_max NUMERIC(39, 0) := public.br_parse_u64_text(p_source_slot_max, 'source_slot_max');
    v_cursor NUMERIC(39, 0);
    v_bootstrap_state TEXT;
    v_prior_run_state TEXT;
    v_run public.settlement_week_runs%ROWTYPE;
    v_run_found BOOLEAN;
    v_job JSONB;
    v_job_state TEXT;
    v_vault_id NUMERIC(39, 0);
    v_expected_open NUMERIC(39, 0);
    v_snapshot_field TEXT;
    v_hash TEXT := pg_catalog.md5(
        p_jobs::TEXT || ':' || p_scope_evidence::TEXT || ':' || p_source_slot_min || ':' || p_source_slot_max
    );
    v_count INTEGER;
    v_distinct_count INTEGER;
BEGIN
    IF pg_catalog.jsonb_typeof(p_jobs) <> 'array'
       OR pg_catalog.jsonb_typeof(p_scope_evidence) <> 'object' THEN
        RAISE EXCEPTION 'materialization requires canonical JSON evidence';
    END IF;
    IF p_scope_evidence->>'commitment' <> 'finalized'
       OR public.br_parse_u64_text(
            p_scope_evidence->>'counter_count', 'scope counter_count'
          ) <> v_counter
       OR v_slot_min > v_slot_max
       OR v_slot <> v_slot_max THEN
        RAISE EXCEPTION 'materialization scope is not complete finalized evidence';
    END IF;
    IF v_counter > 2147483647::NUMERIC
       OR pg_catalog.jsonb_array_length(p_jobs) <> v_counter::INTEGER THEN
        RAISE EXCEPTION 'incomplete VaultCounter scope: expected %, received %',
            v_counter, pg_catalog.jsonb_array_length(p_jobs);
    END IF;

    SELECT bootstrap_state, last_materialized_week
    INTO v_bootstrap_state, v_cursor
    FROM public.settlement_planning_state
    WHERE id = 1
    FOR UPDATE;
    IF NOT FOUND OR v_bootstrap_state <> 'initialized' OR v_cursor IS NULL THEN
        RAISE EXCEPTION 'settlement planning has not been bootstrapped from finalized VaultCounter evidence';
    END IF;

    SELECT r.* INTO v_run
    FROM public.settlement_week_runs r
    WHERE r.settlement_week = v_week
    FOR UPDATE;
    v_run_found := FOUND;

    IF v_run_found AND v_run.source_kind = 'authoritative'
       AND EXISTS (
            SELECT 1 FROM public.settlement_jobs j
            WHERE j.run_id = v_run.id AND j.source_kind = 'authoritative'
       ) THEN
        IF v_run.materialization_hash <> v_hash
           OR v_run.vault_counter_count <> v_counter
           OR v_run.source_slot_min <> v_slot_min
           OR v_run.source_slot_max <> v_slot_max THEN
            RAISE EXCEPTION 'settlement week % was materialized from different chain evidence', v_week;
        END IF;
        RETURN QUERY
        SELECT r.id, r.settlement_week, r.state,
               r.materialized_job_count::INTEGER,
               r.ready_job_count::INTEGER,
               r.skipped_job_count::INTEGER
        FROM public.settlement_week_runs r WHERE r.id = v_run.id;
        RETURN;
    END IF;

    IF v_week <> v_cursor + 1 THEN
        RAISE EXCEPTION 'settlement week % is not the next materializable week after %', v_week, v_cursor;
    END IF;
    IF v_cursor >= 0 THEN
        SELECT r.state INTO v_prior_run_state
        FROM public.settlement_week_runs r
        WHERE r.settlement_week = v_cursor
        FOR UPDATE;
        IF FOUND AND v_prior_run_state NOT IN ('confirmed', 'review_required') THEN
            RAISE EXCEPTION 'settlement week % is not terminal; refusing to materialize week %',
                v_cursor, v_week;
        END IF;
    END IF;

    IF NOT v_run_found THEN
        INSERT INTO public.settlement_week_runs (
            settlement_week, state, source_kind, vault_counter_count,
            source_slot, source_slot_min, source_slot_max, scope_evidence,
            materialization_hash, expected_job_count
        ) VALUES (
            v_week, 'planning', 'authoritative', v_counter,
            v_slot, v_slot_min, v_slot_max, p_scope_evidence,
            v_hash, v_counter
        ) RETURNING * INTO v_run;
    ELSE
        UPDATE public.settlement_week_runs
        SET state = 'planning', source_kind = 'authoritative',
            vault_counter_count = v_counter, source_slot = v_slot,
            source_slot_min = v_slot_min, source_slot_max = v_slot_max,
            scope_evidence = p_scope_evidence, materialization_hash = v_hash,
            expected_job_count = v_counter, updated_at = pg_catalog.now()
        WHERE id = v_run.id RETURNING * INTO v_run;
    END IF;

    SELECT pg_catalog.count(*), pg_catalog.count(DISTINCT public.br_parse_u64_text(
               value->>'vault_id', 'vault_id'
           ))
    INTO v_count, v_distinct_count
    FROM pg_catalog.jsonb_array_elements(p_jobs);
    IF v_count <> v_distinct_count OR EXISTS (
        SELECT 1 FROM pg_catalog.jsonb_array_elements(p_jobs) item
        WHERE public.br_parse_u64_text(item->>'vault_id', 'vault_id') >= v_counter
    ) THEN
        RAISE EXCEPTION 'materialization vault IDs do not exactly match VaultCounter scope';
    END IF;

    FOR v_job IN SELECT value FROM pg_catalog.jsonb_array_elements(p_jobs)
    LOOP
        IF pg_catalog.jsonb_typeof(v_job) <> 'object'
           OR pg_catalog.jsonb_typeof(v_job->'vault_id') <> 'string'
           OR pg_catalog.jsonb_typeof(v_job->'expected_pre_open_week') <> 'string'
           OR pg_catalog.jsonb_typeof(v_job->'raw_snapshot') <> 'object' THEN
            RAISE EXCEPTION 'settlement job uses a non-canonical JSON boundary';
        END IF;
        v_vault_id := public.br_parse_u64_text(v_job->>'vault_id', 'vault_id');
        v_expected_open := public.br_parse_u64_text(
            v_job->>'expected_pre_open_week', 'expected_pre_open_week'
        );
        v_job_state := v_job->>'state';
        IF v_job_state NOT IN (
            'precondition_pending', 'ready', 'skipped_empty', 'reconciling', 'blocked'
        ) THEN
            RAISE EXCEPTION 'invalid materialized settlement state %', v_job_state;
        END IF;
        IF coalesce(v_job->>'vault_signature', '') = '' THEN
            RAISE EXCEPTION 'vault % is missing its signature', v_vault_id;
        END IF;
        FOREACH v_snapshot_field IN ARRAY ARRAY[
            'id', 'open_settlement_week', 'pending_rewards',
            'cal_tribute_accumulated', 'pending_rewards_next_week',
            'cal_tribute_accumulated_next', 'carry_record_royalty',
            'carry_stakers', 'carry_local_legend', 'carry_pol', 'carry_treasury'
        ] LOOP
            IF pg_catalog.jsonb_typeof(v_job->'raw_snapshot'->v_snapshot_field) <> 'string' THEN
                RAISE EXCEPTION 'raw snapshot field % must be a decimal string', v_snapshot_field;
            END IF;
            PERFORM public.br_parse_u64_text(
                v_job->'raw_snapshot'->>v_snapshot_field,
                'raw_snapshot.' || v_snapshot_field
            );
        END LOOP;
        IF v_job_state = 'skipped_empty'
           AND coalesce(v_job->>'skip_reason', '') = '' THEN
            RAISE EXCEPTION 'skipped vault % is missing a reason', v_vault_id;
        END IF;
        IF coalesce((v_job->>'auto_roll_from_empty')::BOOLEAN, FALSE)
           AND v_expected_open + 1 <> v_week THEN
            RAISE EXCEPTION 'vault % has an invalid auto-roll precondition', v_vault_id;
        END IF;

        INSERT INTO public.settlement_jobs (
            run_id, settlement_week, vault_id, vault_signature, source_kind,
            legacy_evidence_only, state, skip_reason, blocked_reason,
            expected_pre_open_week, auto_roll_from_empty, cal_to_convert,
            dung_to_mint, current_week_value, next_week_value, pending_rewards,
            cal_tribute_accumulated, pending_rewards_next_week,
            cal_tribute_accumulated_next, carry_record_royalty, carry_stakers,
            carry_local_legend, carry_pol, carry_treasury, raw_snapshot,
            next_reconcile_at
        ) VALUES (
            v_run.id, v_week, v_vault_id, v_job->>'vault_signature',
            'authoritative', FALSE, v_job_state, v_job->>'skip_reason',
            v_job->>'blocked_reason', v_expected_open,
            coalesce((v_job->>'auto_roll_from_empty')::BOOLEAN, FALSE),
            public.br_parse_u64_text(v_job->>'cal_to_convert', 'cal_to_convert'),
            public.br_parse_u64_text(v_job->>'dung_to_mint', 'dung_to_mint'),
            public.br_parse_uint39_text(v_job->>'current_week_value', 'current_week_value'),
            public.br_parse_uint39_text(v_job->>'next_week_value', 'next_week_value'),
            public.br_parse_u64_text(v_job->>'pending_rewards', 'pending_rewards'),
            public.br_parse_u64_text(v_job->>'cal_tribute_accumulated', 'cal_tribute_accumulated'),
            public.br_parse_u64_text(v_job->>'pending_rewards_next_week', 'pending_rewards_next_week'),
            public.br_parse_u64_text(v_job->>'cal_tribute_accumulated_next', 'cal_tribute_accumulated_next'),
            public.br_parse_u64_text(v_job->>'carry_record_royalty', 'carry_record_royalty'),
            public.br_parse_u64_text(v_job->>'carry_stakers', 'carry_stakers'),
            public.br_parse_u64_text(v_job->>'carry_local_legend', 'carry_local_legend'),
            public.br_parse_u64_text(v_job->>'carry_pol', 'carry_pol'),
            public.br_parse_u64_text(v_job->>'carry_treasury', 'carry_treasury'),
            v_job->'raw_snapshot',
            CASE WHEN v_job_state = 'reconciling' THEN pg_catalog.now() ELSE NULL END
        )
        ON CONFLICT (run_id, vault_id) WHERE source_kind = 'authoritative'
        DO UPDATE SET
            vault_signature = EXCLUDED.vault_signature,
            state = EXCLUDED.state,
            skip_reason = EXCLUDED.skip_reason,
            blocked_reason = EXCLUDED.blocked_reason,
            expected_pre_open_week = EXCLUDED.expected_pre_open_week,
            auto_roll_from_empty = EXCLUDED.auto_roll_from_empty,
            cal_to_convert = EXCLUDED.cal_to_convert,
            dung_to_mint = EXCLUDED.dung_to_mint,
            current_week_value = EXCLUDED.current_week_value,
            next_week_value = EXCLUDED.next_week_value,
            pending_rewards = EXCLUDED.pending_rewards,
            cal_tribute_accumulated = EXCLUDED.cal_tribute_accumulated,
            pending_rewards_next_week = EXCLUDED.pending_rewards_next_week,
            cal_tribute_accumulated_next = EXCLUDED.cal_tribute_accumulated_next,
            carry_record_royalty = EXCLUDED.carry_record_royalty,
            carry_stakers = EXCLUDED.carry_stakers,
            carry_local_legend = EXCLUDED.carry_local_legend,
            carry_pol = EXCLUDED.carry_pol,
            carry_treasury = EXCLUDED.carry_treasury,
            raw_snapshot = EXCLUDED.raw_snapshot,
            next_reconcile_at = EXCLUDED.next_reconcile_at,
            updated_at = pg_catalog.now();
    END LOOP;

    PERFORM public.br_refresh_settlement_run(v_run.id);
    SELECT * INTO v_run FROM public.settlement_week_runs WHERE id = v_run.id;
    IF v_run.materialized_job_count <> v_run.expected_job_count THEN
        RAISE EXCEPTION 'materialization did not create the complete expected job scope';
    END IF;

    UPDATE public.settlement_week_runs
    SET materialized_at = coalesce(materialized_at, pg_catalog.now()),
        updated_at = pg_catalog.now()
    WHERE id = v_run.id;
    UPDATE public.settlement_planning_state
    SET last_materialized_week = v_week, updated_at = pg_catalog.now()
    WHERE id = 1 AND bootstrap_state = 'initialized';

    RETURN QUERY
    SELECT r.id, r.settlement_week, r.state,
           r.materialized_job_count::INTEGER,
           r.ready_job_count::INTEGER,
           r.skipped_job_count::INTEGER
    FROM public.settlement_week_runs r WHERE r.id = v_run.id;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_claim_settlement_preparation(
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 300,
    p_vault_id TEXT DEFAULT NULL
) RETURNS SETOF public.settlement_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_vault_id NUMERIC(39, 0) := CASE WHEN p_vault_id IS NULL THEN NULL
        ELSE public.br_parse_u64_text(p_vault_id, 'vault_id') END;
    v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF coalesce(p_worker_id, '') = '' THEN
        RAISE EXCEPTION 'worker ID is required';
    END IF;
    SELECT j.* INTO v_job
    FROM public.settlement_jobs j
    WHERE j.state IN ('precondition_pending', 'precondition_retry')
      AND (j.next_attempt_at IS NULL OR j.next_attempt_at <= pg_catalog.now())
      AND (v_vault_id IS NULL OR j.vault_id = v_vault_id)
    ORDER BY j.settlement_week, j.vault_id, j.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN RETURN; END IF;

    UPDATE public.settlement_jobs
    SET state = 'preparing', lease_owner = p_worker_id,
        lease_token = pg_catalog.gen_random_uuid(),
        lease_expires_at = pg_catalog.now() + pg_catalog.make_interval(
            secs => greatest(p_lease_seconds, 30)
        ),
        preparation_attempt_count = preparation_attempt_count + 1,
        next_attempt_at = NULL, updated_at = pg_catalog.now()
    WHERE id = v_job.id
    RETURNING * INTO v_job;
    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_set_settlement_precondition_intent(
    p_job_id UUID,
    p_lease_token UUID,
    p_intent JSONB
) RETURNS SETOF public.settlement_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF pg_catalog.jsonb_typeof(p_intent) <> 'object' THEN
        RAISE EXCEPTION 'settlement precondition intent must be a JSON object';
    END IF;
    SELECT * INTO v_job FROM public.settlement_jobs
    WHERE id = p_job_id AND state = 'preparing' AND lease_token = p_lease_token
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement preparation fence was lost for job %', p_job_id;
    END IF;
    IF v_job.precondition_intent IS NOT NULL
       AND v_job.precondition_intent <> p_intent THEN
        RAISE EXCEPTION 'settlement precondition intent is already frozen for job %', p_job_id;
    END IF;
    UPDATE public.settlement_jobs
    SET precondition_intent = coalesce(precondition_intent, p_intent),
        updated_at = pg_catalog.now()
    WHERE id = p_job_id
    RETURNING * INTO v_job;
    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_finish_settlement_preparation(
    p_job_id UUID,
    p_lease_token UUID,
    p_completed BOOLEAN,
    p_error TEXT,
    p_retry_seconds INTEGER,
    p_result JSONB DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF p_completed AND (
        pg_catalog.jsonb_typeof(p_result) <> 'object'
        OR (p_result->>'completed')::BOOLEAN IS DISTINCT FROM TRUE
    ) THEN
        RAISE EXCEPTION 'completed settlement precondition requires durable result evidence';
    END IF;
    UPDATE public.settlement_jobs
    SET state = CASE WHEN p_completed THEN 'ready' ELSE 'precondition_retry' END,
        precondition_result = CASE WHEN p_completed THEN p_result ELSE precondition_result END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = CASE WHEN p_completed THEN NULL ELSE
            pg_catalog.now() + pg_catalog.make_interval(
                secs => greatest(p_retry_seconds, 1)
            ) END,
        last_error_class = CASE WHEN p_completed THEN NULL ELSE 'legend_precondition_retry' END,
        last_error = CASE WHEN p_completed THEN NULL ELSE p_error END,
        updated_at = pg_catalog.now()
    WHERE id = p_job_id AND state = 'preparing' AND lease_token = p_lease_token
    RETURNING * INTO v_job;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement preparation fence was lost for job %', p_job_id;
    END IF;
    PERFORM public.br_refresh_settlement_run(v_job.run_id);
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_claim_settlement_job(
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 300,
    p_vault_id TEXT DEFAULT NULL
) RETURNS SETOF public.settlement_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_vault_id NUMERIC(39, 0) := CASE WHEN p_vault_id IS NULL THEN NULL
        ELSE public.br_parse_u64_text(p_vault_id, 'vault_id') END;
    v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF coalesce(p_worker_id, '') = '' THEN
        RAISE EXCEPTION 'worker ID is required';
    END IF;
    SELECT j.* INTO v_job
    FROM public.settlement_jobs j
    WHERE j.state = 'ready'
      AND j.source_kind = 'authoritative'
      AND NOT j.legacy_evidence_only
      AND (v_vault_id IS NULL OR j.vault_id = v_vault_id)
    ORDER BY j.settlement_week, j.vault_id, j.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN RETURN; END IF;

    UPDATE public.settlement_jobs j
    SET state = 'leased', lease_owner = p_worker_id,
        lease_token = pg_catalog.gen_random_uuid(),
        lease_expires_at = pg_catalog.now() + pg_catalog.make_interval(
            secs => greatest(p_lease_seconds, 30)
        ),
        attempt_count = j.attempt_count + 1,
        submit_started_at = pg_catalog.clock_timestamp(),
        next_attempt_at = NULL, updated_at = pg_catalog.now()
    WHERE j.id = v_job.id
    RETURNING j.* INTO v_job;

    INSERT INTO public.settlement_attempts (
        job_id, attempt_no, lease_token, outcome
    ) VALUES (
        v_job.id, v_job.attempt_count, v_job.lease_token, 'claimed'
    );
    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_renew_settlement_lease(
    p_job_id UUID,
    p_lease_token UUID,
    p_lease_seconds INTEGER DEFAULT 300
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.settlement_jobs
    SET lease_expires_at = pg_catalog.now() + pg_catalog.make_interval(
            secs => greatest(p_lease_seconds, 30)
        ),
        updated_at = pg_catalog.now()
    WHERE id = p_job_id
      AND state IN ('leased', 'preparing', 'reconciling')
      AND lease_token = p_lease_token
      AND lease_expires_at > pg_catalog.now();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for job %', p_job_id;
    END IF;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_claim_settlement_reconciliation(
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 300,
    p_vault_id TEXT DEFAULT NULL
) RETURNS SETOF public.settlement_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_vault_id NUMERIC(39, 0) := CASE WHEN p_vault_id IS NULL THEN NULL
        ELSE public.br_parse_u64_text(p_vault_id, 'vault_id') END;
    v_job public.settlement_jobs%ROWTYPE;
BEGIN
    SELECT j.* INTO v_job
    FROM public.settlement_jobs j
    WHERE j.state IN ('submitted', 'reconciling', 'retry_wait')
      AND (j.next_reconcile_at IS NULL OR j.next_reconcile_at <= pg_catalog.now())
      AND (j.lease_expires_at IS NULL OR j.lease_expires_at <= pg_catalog.now())
      AND (v_vault_id IS NULL OR j.vault_id = v_vault_id)
    ORDER BY j.settlement_week, j.vault_id, j.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN RETURN; END IF;

    UPDATE public.settlement_jobs
    SET state = 'reconciling', lease_owner = p_worker_id,
        lease_token = pg_catalog.gen_random_uuid(),
        lease_expires_at = pg_catalog.now() + pg_catalog.make_interval(
            secs => greatest(p_lease_seconds, 30)
        ),
        updated_at = pg_catalog.now()
    WHERE id = v_job.id
    RETURNING * INTO v_job;
    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_reap_stale_settlement_leases()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_reaped INTEGER;
BEGIN
    WITH reaped AS (
        UPDATE public.settlement_jobs
        SET state = CASE
                WHEN state = 'preparing' THEN 'precondition_retry'
                ELSE 'reconciling'
            END,
            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
            next_attempt_at = CASE WHEN state = 'preparing' THEN pg_catalog.now() ELSE next_attempt_at END,
            next_reconcile_at = CASE WHEN state <> 'preparing' THEN pg_catalog.now() ELSE next_reconcile_at END,
            last_error_class = 'stale_lease',
            last_error = 'worker lease expired; reconciliation required before resend',
            updated_at = pg_catalog.now()
        WHERE state IN ('preparing', 'leased', 'reconciling')
          AND lease_expires_at <= pg_catalog.now()
        RETURNING 1
    ) SELECT pg_catalog.count(*) INTO v_reaped FROM reaped;
    RETURN v_reaped;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_retry_repairable_settlement_jobs(p_limit INTEGER DEFAULT 10)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_count INTEGER;
BEGIN
    WITH repair AS (
        SELECT j.id FROM public.settlement_jobs j
        WHERE j.state = 'blocked'
          AND j.last_error_class IN ('repairable_preflight', 'preflight_blocked')
          AND (j.next_attempt_at IS NULL OR j.next_attempt_at <= pg_catalog.now())
        ORDER BY j.updated_at
        FOR UPDATE SKIP LOCKED
        LIMIT greatest(p_limit, 0)
    ), changed AS (
        UPDATE public.settlement_jobs j
        SET state = 'reconciling', next_reconcile_at = pg_catalog.now(),
            blocked_reason = NULL, last_error_class = 'repairable_preflight',
            updated_at = pg_catalog.now()
        FROM repair WHERE j.id = repair.id RETURNING 1
    ) SELECT pg_catalog.count(*) INTO v_count FROM changed;
    RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_mark_settlement_prepared(
    p_job_id UUID,
    p_lease_token UUID,
    p_tx_signature TEXT
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
        updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_mark_settlement_submitted(
    p_job_id UUID,
    p_lease_token UUID,
    p_tx_signature TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF coalesce(p_tx_signature, '') = '' THEN
        RAISE EXCEPTION 'transaction signature is required';
    END IF;
    UPDATE public.settlement_jobs
    SET state = 'submitted', tx_signature = p_tx_signature,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_reconcile_at = pg_catalog.now(), last_error_class = NULL,
        last_error = NULL, updated_at = pg_catalog.now()
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
      AND (prepared_tx_signature IS NULL OR prepared_tx_signature = p_tx_signature)
    RETURNING * INTO v_job;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for job %', p_job_id;
    END IF;
    UPDATE public.settlement_attempts
    SET outcome = 'submitted', tx_signature = p_tx_signature,
        accepted_at = pg_catalog.now(), updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token;
    RETURN TRUE;
END;
$$;

DROP FUNCTION IF EXISTS public.br_mark_settlement_ambiguous(UUID, UUID, TEXT);
DROP FUNCTION IF EXISTS public.br_mark_settlement_ambiguous(UUID, UUID, TEXT, TEXT);

CREATE OR REPLACE FUNCTION public.br_mark_settlement_ambiguous(
    p_job_id UUID,
    p_lease_token UUID,
    p_error TEXT,
    p_error_class TEXT,
    p_tx_signature TEXT DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_job public.settlement_jobs%ROWTYPE;
BEGIN
    IF p_error_class NOT IN (
        'ambiguous_submit', 'retryable_submit', 'deterministic_submit',
        'repairable_preflight'
    ) THEN
        RAISE EXCEPTION 'invalid settlement submit error class %', p_error_class;
    END IF;
    UPDATE public.settlement_jobs
    SET state = 'reconciling', tx_signature = coalesce(
            tx_signature, p_tx_signature, prepared_tx_signature
        ),
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_reconcile_at = pg_catalog.now(), last_error_class = p_error_class,
        last_error = p_error, updated_at = pg_catalog.now()
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
    RETURNING * INTO v_job;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for job %', p_job_id;
    END IF;
    UPDATE public.settlement_attempts
    SET outcome = 'ambiguous', tx_signature = coalesce(tx_signature, p_tx_signature),
        accepted_at = CASE WHEN p_tx_signature IS NOT NULL THEN pg_catalog.now() ELSE accepted_at END,
        error_class = p_error_class, error_message = p_error,
        updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token;
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_mark_settlement_blocked(
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
    UPDATE public.settlement_jobs
    SET state = 'blocked', blocked_reason = p_error,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        last_error_class = 'invariant_invalid_plan', last_error = p_error,
        updated_at = pg_catalog.now()
    WHERE id = p_job_id AND state = 'leased' AND lease_token = p_lease_token
    RETURNING * INTO v_job;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement lease fence was lost for job %', p_job_id;
    END IF;
    UPDATE public.settlement_attempts
    SET outcome = 'blocked', error_class = 'invariant_invalid_plan',
        error_message = p_error, updated_at = pg_catalog.now()
    WHERE job_id = p_job_id AND attempt_no = v_job.attempt_count
      AND lease_token = p_lease_token;
    PERFORM public.br_refresh_settlement_run(v_job.run_id);
    RETURN TRUE;
END;
$$;

DROP FUNCTION IF EXISTS public.br_finish_settlement_reconciliation(
    UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, INTEGER
);

CREATE OR REPLACE FUNCTION public.br_finish_settlement_reconciliation(
    p_job_id UUID,
    p_lease_token UUID,
    p_decision TEXT,
    p_evidence JSONB,
    p_signature_state TEXT,
    p_chain_commitment TEXT,
    p_observed_open_week TEXT DEFAULT NULL,
    p_indexed_tx_signature TEXT DEFAULT NULL,
    p_indexed_signature_finalized BOOLEAN DEFAULT FALSE,
    p_recovered_tx_signature TEXT DEFAULT NULL,
    p_error TEXT DEFAULT NULL,
    p_retry_seconds INTEGER DEFAULT 60
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_job public.settlement_jobs%ROWTYPE;
    v_open_week NUMERIC(39, 0) := CASE WHEN p_observed_open_week IS NULL THEN NULL
        ELSE public.br_parse_u64_text(p_observed_open_week, 'observed_open_week') END;
    v_signature TEXT;
    v_total_distributed NUMERIC(39, 0);
BEGIN
    IF p_decision NOT IN (
        'ready', 'confirmed', 'advanced_unproven', 'retry_wait', 'reconciling', 'blocked'
    ) THEN
        RAISE EXCEPTION 'invalid settlement reconciliation decision %', p_decision;
    END IF;
    IF p_signature_state NOT IN (
        'absent', 'pending', 'confirmed', 'finalized', 'failed', 'unknown'
    ) THEN
        RAISE EXCEPTION 'invalid settlement signature state %', p_signature_state;
    END IF;
    IF pg_catalog.jsonb_typeof(coalesce(p_evidence, '{}'::JSONB)) <> 'object' THEN
        RAISE EXCEPTION 'settlement reconciliation evidence must be a JSON object';
    END IF;

    SELECT * INTO v_job FROM public.settlement_jobs
    WHERE id = p_job_id AND state = 'reconciling' AND lease_token = p_lease_token
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement reconciliation fence was lost for job %', p_job_id;
    END IF;

    IF p_decision = 'confirmed' AND (
        p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week <= v_job.settlement_week
        OR NOT (
            p_signature_state = 'finalized'
            OR (
                p_indexed_signature_finalized
                AND coalesce(p_indexed_tx_signature, '') <> ''
            )
        )
    ) THEN
        RAISE EXCEPTION 'confirmed settlement decision lacks finalized matching chain evidence';
    END IF;
    IF p_decision = 'advanced_unproven' AND (
        p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week <= v_job.settlement_week
    ) THEN
        RAISE EXCEPTION 'advanced settlement closure lacks finalized vault evidence';
    END IF;
    IF p_decision IN ('ready', 'retry_wait') AND (
        v_job.legacy_evidence_only
        OR p_chain_commitment <> 'finalized'
        OR v_open_week IS NULL
        OR v_open_week NOT IN (v_job.expected_pre_open_week, v_job.settlement_week)
        OR p_signature_state NOT IN ('absent', 'failed')
        OR p_indexed_tx_signature IS NOT NULL
        OR v_job.last_error_class = 'deterministic_submit'
    ) THEN
        RAISE EXCEPTION 'settlement resend decision is not supported by finalized no-effect evidence';
    END IF;
    IF p_decision = 'ready'
       AND v_job.last_error_class IS DISTINCT FROM 'retry_recheck_required' THEN
        RAISE EXCEPTION 'settlement resend requires a fresh delayed reconciliation';
    END IF;

    v_signature := CASE
        WHEN p_decision = 'confirmed'
         AND p_indexed_signature_finalized
         AND coalesce(p_indexed_tx_signature, '') <> ''
            THEN p_indexed_tx_signature
        WHEN p_decision = 'confirmed' AND p_signature_state = 'finalized'
            THEN coalesce(
                p_recovered_tx_signature,
                v_job.tx_signature,
                v_job.prepared_tx_signature,
                p_indexed_tx_signature
            )
        ELSE coalesce(
            v_job.tx_signature,
            v_job.prepared_tx_signature,
            p_indexed_tx_signature,
            p_recovered_tx_signature
        )
    END;
    INSERT INTO public.settlement_reconciliations (
        job_id, lease_token, decision, signature_state, chain_commitment,
        observed_open_week, indexed_tx_signature, indexed_signature_finalized,
        recovered_tx_signature, evidence, error_message
    ) VALUES (
        p_job_id, p_lease_token, p_decision, p_signature_state,
        p_chain_commitment, v_open_week, p_indexed_tx_signature,
        p_indexed_signature_finalized, p_recovered_tx_signature,
        coalesce(p_evidence, '{}'::JSONB), p_error
    );

    UPDATE public.settlement_jobs
    SET state = p_decision, tx_signature = v_signature,
        terminal_evidence_quality = CASE
            WHEN p_decision = 'confirmed' AND p_indexed_signature_finalized
                THEN 'finalized_indexed_distribution'
            WHEN p_decision = 'confirmed' THEN 'finalized_signature_and_vault'
            WHEN p_decision = 'advanced_unproven' THEN 'finalized_vault_advanced_unproven'
            ELSE terminal_evidence_quality
        END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = NULL,
        next_reconcile_at = CASE WHEN p_decision IN ('retry_wait', 'reconciling')
            THEN pg_catalog.now() + pg_catalog.make_interval(
                secs => greatest(p_retry_seconds, 1)
            ) ELSE NULL END,
        confirmed_at = CASE WHEN p_decision IN ('confirmed', 'advanced_unproven')
            THEN pg_catalog.now() ELSE confirmed_at END,
        blocked_reason = CASE WHEN p_decision = 'blocked' THEN p_error
            WHEN p_decision = 'ready' THEN NULL ELSE blocked_reason END,
        last_error_class = CASE
            WHEN p_decision IN ('confirmed', 'advanced_unproven', 'ready') THEN NULL
            WHEN p_decision = 'retry_wait' THEN 'retry_recheck_required'
            WHEN p_decision = 'reconciling' THEN last_error_class
            ELSE coalesce(last_error_class, 'reconciliation_blocked')
        END,
        last_error = CASE WHEN p_decision IN ('confirmed', 'advanced_unproven', 'ready')
            THEN NULL ELSE coalesce(p_error, last_error) END,
        updated_at = pg_catalog.now()
    WHERE id = p_job_id AND lease_token = p_lease_token;

    IF p_decision = 'confirmed' THEN
        IF coalesce(v_signature, '') = '' THEN
            RAISE EXCEPTION 'confirmed settlement has no finalized transaction signature';
        END IF;
        IF p_indexed_signature_finalized
           AND p_evidence->'indexed_distribution'->>'total_distributed' IS NOT NULL THEN
            v_total_distributed := public.br_parse_u64_text(
                p_evidence->'indexed_distribution'->>'total_distributed',
                'indexed total_distributed'
            );
        END IF;
        INSERT INTO public.settlement_notification_outbox (
            job_id, vault_id, vault_signature, settlement_week,
            raw_pending_dung, total_distributed, tx_signature
        ) VALUES (
            v_job.id, v_job.vault_id, v_job.vault_signature,
            v_job.settlement_week, v_job.dung_to_mint,
            v_total_distributed, v_signature
        ) ON CONFLICT (job_id) DO NOTHING;
    END IF;

    IF p_decision = 'confirmed' AND v_job.legacy_distribution_id IS NOT NULL
       AND pg_catalog.to_regclass('public.epoch_distributions') IS NOT NULL THEN
        EXECUTE 'UPDATE public.epoch_distributions '
            'SET status = ''completed'', tx_signature = COALESCE(tx_signature, $1), '
            'processed_at = COALESCE(processed_at, now()), error_message = NULL '
            'WHERE id = $2'
        USING v_signature, v_job.legacy_distribution_id;
    END IF;

    PERFORM public.br_refresh_settlement_run(v_job.run_id);
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_claim_settlement_notification(
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 300
) RETURNS SETOF public.settlement_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE v_event public.settlement_notification_outbox%ROWTYPE;
BEGIN
    SELECT o.* INTO v_event
    FROM public.settlement_notification_outbox o
    WHERE o.state IN ('pending', 'delivering')
      AND (o.next_attempt_at IS NULL OR o.next_attempt_at <= pg_catalog.now())
      AND (o.lease_expires_at IS NULL OR o.lease_expires_at <= pg_catalog.now())
    ORDER BY o.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1;
    IF NOT FOUND THEN RETURN; END IF;
    UPDATE public.settlement_notification_outbox
    SET state = 'delivering', lease_owner = p_worker_id,
        lease_token = pg_catalog.gen_random_uuid(),
        lease_expires_at = pg_catalog.now() + pg_catalog.make_interval(
            secs => greatest(p_lease_seconds, 30)
        ),
        attempt_count = attempt_count + 1, updated_at = pg_catalog.now()
    WHERE id = v_event.id
    RETURNING * INTO v_event;
    RETURN NEXT v_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_finish_settlement_notification(
    p_outbox_id UUID,
    p_lease_token UUID,
    p_delivered BOOLEAN,
    p_error TEXT DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    UPDATE public.settlement_notification_outbox
    SET state = CASE WHEN p_delivered THEN 'delivered' ELSE 'pending' END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = CASE WHEN p_delivered THEN NULL ELSE
            pg_catalog.now() + pg_catalog.make_interval(
                secs => least(3600, 30 * (2 ^ least(attempt_count, 7))::INTEGER)
            ) END,
        last_error = CASE WHEN p_delivered THEN NULL ELSE p_error END,
        delivered_at = CASE WHEN p_delivered THEN pg_catalog.now() ELSE delivered_at END,
        updated_at = pg_catalog.now()
    WHERE id = p_outbox_id AND state = 'delivering' AND lease_token = p_lease_token;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement notification fence was lost for outbox %', p_outbox_id;
    END IF;
    RETURN TRUE;
END;
$$;

-- Import every historical production candidate. The stale points boolean is
-- preserved as evidence but is never exclusion authority. Legacy jobs are
-- reconciliation-only and cannot enter the submit claim.
DO $$
DECLARE v_run RECORD;
BEGIN
    IF pg_catalog.to_regclass('public.epoch_distributions') IS NULL THEN RETURN; END IF;

    INSERT INTO public.settlement_week_runs (
        settlement_week, state, source_kind, vault_counter_count,
        expected_job_count, materialized_at
    )
    SELECT greatest(ed.epoch, 0)::NUMERIC,
           'materialized', 'legacy_import', 0, 0, pg_catalog.now()
    FROM public.epoch_distributions ed
    GROUP BY greatest(ed.epoch, 0)
    ON CONFLICT (settlement_week) DO NOTHING;

    INSERT INTO public.settlement_jobs (
        run_id, settlement_week, vault_id, vault_signature, source_kind,
        legacy_evidence_only, state, blocked_reason, expected_pre_open_week,
        cal_to_convert, dung_to_mint, current_week_value, pending_rewards,
        cal_tribute_accumulated, raw_snapshot, tx_signature,
        next_reconcile_at, legacy_distribution_id
    )
    SELECT
        runs.id,
        greatest(ed.epoch, 0)::NUMERIC,
        CASE WHEN ed.vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC
            THEN ed.vault_id::NUMERIC ELSE NULL END,
        CASE WHEN pg_catalog.btrim(ed.vault_signature::TEXT) <> ''
            THEN pg_catalog.btrim(ed.vault_signature::TEXT)
            ELSE 'legacy:' || ed.id::TEXT END,
        'legacy_import', TRUE,
        CASE
            WHEN ed.epoch < 0 OR ed.vault_id IS NULL OR ed.vault_id < 0
              OR pg_catalog.btrim(ed.vault_signature::TEXT) = ''
              OR NOT (
                    (ed.settlement_import_snapshot->>'cal_to_convert')
                        ~ '^(0|[1-9][0-9]*)([.]0+)?$'
                    AND (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC
                        BETWEEN 0 AND 18446744073709551615::NUMERIC
                    AND (ed.settlement_import_snapshot->>'dung_to_mint')
                        ~ '^(0|[1-9][0-9]*)$'
                    AND (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC
                        BETWEEN 0 AND 18446744073709551615::NUMERIC
              )
              OR (
                    coalesce(ed.is_points_period, TRUE)
                    AND coalesce(ed.status, 'pending') IN ('pending', 'failed')
                    AND coalesce(ed.tx_signature, '') = ''
              )
                THEN 'blocked'
            ELSE 'reconciling'
        END,
        CASE
            WHEN ed.epoch < 0 THEN 'legacy row has an invalid settlement week'
            WHEN ed.vault_id IS NULL THEN 'legacy row has no vault identity'
            WHEN ed.vault_id < 0 THEN 'legacy row has an invalid vault identity'
            WHEN pg_catalog.btrim(ed.vault_signature::TEXT) = ''
                THEN 'legacy row has no vault signature'
            WHEN NOT (
                (ed.settlement_import_snapshot->>'cal_to_convert')
                    ~ '^(0|[1-9][0-9]*)([.]0+)?$'
            ) THEN 'legacy row crossed a non-integral protocol amount boundary'
            WHEN (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC
                    NOT BETWEEN 0 AND 18446744073709551615::NUMERIC
                THEN 'legacy row has an invalid CAL amount'
            WHEN NOT (
                (ed.settlement_import_snapshot->>'dung_to_mint')
                    ~ '^(0|[1-9][0-9]*)$'
            ) OR (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC
                    NOT BETWEEN 0 AND 18446744073709551615::NUMERIC
                THEN 'legacy row has an invalid DUNG amount'
            WHEN coalesce(ed.is_points_period, TRUE)
              AND coalesce(ed.status, 'pending') IN ('pending', 'failed')
              AND coalesce(ed.tx_signature, '') = ''
                THEN 'legacy points classification is ambiguous'
            ELSE NULL
        END,
        greatest(ed.epoch, 0)::NUMERIC,
        CASE WHEN (ed.settlement_import_snapshot->>'cal_to_convert')
                    ~ '^(0|[1-9][0-9]*)([.]0+)?$'
                  AND (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC
                    BETWEEN 0 AND 18446744073709551615::NUMERIC
            THEN (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC ELSE 0 END,
        CASE WHEN (ed.settlement_import_snapshot->>'dung_to_mint')
                    ~ '^(0|[1-9][0-9]*)$'
                  AND (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC
                    BETWEEN 0 AND 18446744073709551615::NUMERIC
            THEN (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC ELSE 0 END,
        CASE WHEN (ed.settlement_import_snapshot->>'dung_to_mint')
                    ~ '^(0|[1-9][0-9]*)$'
            THEN least(
                (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC,
                18446744073709551615::NUMERIC
            ) ELSE 0 END,
        CASE WHEN (ed.settlement_import_snapshot->>'dung_to_mint')
                    ~ '^(0|[1-9][0-9]*)$'
            THEN least(
                (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC,
                18446744073709551615::NUMERIC
            ) ELSE 0 END,
        CASE WHEN (ed.settlement_import_snapshot->>'cal_to_convert')
                    ~ '^(0|[1-9][0-9]*)([.]0+)?$'
                  AND (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC
                    BETWEEN 0 AND 18446744073709551615::NUMERIC
            THEN (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC ELSE 0 END,
        coalesce(ed.settlement_import_snapshot, '{}'::JSONB)
            || pg_catalog.jsonb_build_object(
                'legacy_distribution_id', ed.id::TEXT,
                'legacy_status', coalesce(ed.status, 'pending'),
                'legacy_original_cal_to_convert', ed.settlement_import_snapshot->>'cal_to_convert',
                'legacy_original_dung_to_mint', ed.settlement_import_snapshot->>'dung_to_mint',
                'legacy_original_is_points_period', ed.is_points_period,
                'legacy_amount_valid', (
                    (ed.settlement_import_snapshot->>'cal_to_convert')
                        ~ '^(0|[1-9][0-9]*)([.]0+)?$'
                    AND (ed.settlement_import_snapshot->>'cal_to_convert')::NUMERIC
                        BETWEEN 0 AND 18446744073709551615::NUMERIC
                    AND (ed.settlement_import_snapshot->>'dung_to_mint')
                        ~ '^(0|[1-9][0-9]*)$'
                    AND (ed.settlement_import_snapshot->>'dung_to_mint')::NUMERIC
                        BETWEEN 0 AND 18446744073709551615::NUMERIC
                ),
                'legacy_classification', CASE
                    WHEN NOT coalesce(ed.is_points_period, TRUE)
                        THEN 'declared_live'
                    WHEN coalesce(ed.status, 'pending') IN ('processing', 'completed')
                      OR coalesce(ed.tx_signature, '') <> ''
                        THEN 'possible_live_despite_stale_default'
                    ELSE 'ambiguous_stale_points_default'
                END
            ),
        ed.tx_signature,
        CASE WHEN ed.vault_id IS NOT NULL THEN pg_catalog.now() ELSE NULL END,
        ed.id
    FROM public.epoch_distributions ed
    JOIN public.settlement_week_runs runs
      ON runs.settlement_week = greatest(ed.epoch, 0)::NUMERIC
    WHERE coalesce(ed.status, 'pending') IN (
        'pending', 'processing', 'failed', 'completed'
    )
    ON CONFLICT (legacy_distribution_id) DO NOTHING;

    FOR v_run IN
        SELECT DISTINCT run_id AS id
        FROM public.settlement_jobs
        WHERE source_kind = 'legacy_import'
    LOOP
        PERFORM public.br_refresh_settlement_run(v_run.id);
    END LOOP;
END;
$$;

-- Disable every overload of the retired queue write path.
DO $$
DECLARE v_legacy_function REGPROCEDURE;
BEGIN
    FOR v_legacy_function IN
        SELECT p.oid::REGPROCEDURE
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = 'queue_vault_distribution'
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated, service_role',
            v_legacy_function
        );
    END LOOP;
END;
$$;

ALTER TABLE public.settlement_planning_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.settlement_week_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.settlement_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.settlement_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.settlement_reconciliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.settlement_notification_outbox ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.settlement_planning_state FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.settlement_week_runs FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.settlement_jobs FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.settlement_attempts FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.settlement_reconciliations FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.settlement_notification_outbox FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT ON TABLE public.settlement_planning_state, public.settlement_jobs TO service_role;

REVOKE ALL ON FUNCTION public.br_parse_u64_text(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_parse_uint39_text(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_refresh_settlement_run(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_bootstrap_settlement_planning(TEXT, TEXT, TEXT, JSONB, JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_materialize_settlement_week(TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_claim_settlement_preparation(TEXT, INTEGER, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_set_settlement_precondition_intent(UUID, UUID, JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_finish_settlement_preparation(UUID, UUID, BOOLEAN, TEXT, INTEGER, JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_claim_settlement_job(TEXT, INTEGER, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_renew_settlement_lease(UUID, UUID, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_claim_settlement_reconciliation(TEXT, INTEGER, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_reap_stale_settlement_leases() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_retry_repairable_settlement_jobs(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_mark_settlement_prepared(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_mark_settlement_submitted(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_mark_settlement_ambiguous(UUID, UUID, TEXT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_mark_settlement_blocked(UUID, UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_finish_settlement_reconciliation(
    UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, TEXT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_claim_settlement_notification(TEXT, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.br_finish_settlement_notification(UUID, UUID, BOOLEAN, TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.br_bootstrap_settlement_planning(TEXT, TEXT, TEXT, JSONB, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_materialize_settlement_week(TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_claim_settlement_preparation(TEXT, INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_set_settlement_precondition_intent(UUID, UUID, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_finish_settlement_preparation(UUID, UUID, BOOLEAN, TEXT, INTEGER, JSONB) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_claim_settlement_job(TEXT, INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_renew_settlement_lease(UUID, UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_claim_settlement_reconciliation(TEXT, INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_reap_stale_settlement_leases() TO service_role;
GRANT EXECUTE ON FUNCTION public.br_retry_repairable_settlement_jobs(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_mark_settlement_prepared(UUID, UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_mark_settlement_submitted(UUID, UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_mark_settlement_ambiguous(UUID, UUID, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_mark_settlement_blocked(UUID, UUID, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_finish_settlement_reconciliation(
    UUID, UUID, TEXT, JSONB, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, TEXT, INTEGER
) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_claim_settlement_notification(TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.br_finish_settlement_notification(UUID, UUID, BOOLEAN, TEXT) TO service_role;

COMMENT ON TABLE public.settlement_planning_state IS
    'Explicitly uninitialized until one finalized complete VaultCounter bootstrap succeeds.';
COMMENT ON TABLE public.settlement_week_runs IS
    'Transactional complete-scope Settlement Week plans.';
COMMENT ON TABLE public.settlement_jobs IS
    'Fenced per-vault settlement jobs, durable preconditions, and legacy reconciliation evidence.';
COMMENT ON TABLE public.settlement_notification_outbox IS
    'Idempotent settlement notification delivery created atomically with finalized confirmation.';

NOTIFY pgrst, 'reload schema';
