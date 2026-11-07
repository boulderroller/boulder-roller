-- Versioned Settlement Week clock: preserve deployed history, then move the
-- rider-facing boundary to Monday 12:00 UTC with one explicit bridge week.

ALTER TABLE public.indexed_program_config
    ADD COLUMN IF NOT EXISTS settlement_clock_v2_starts_at BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS settlement_clock_source_commitment TEXT NOT NULL DEFAULT 'unverified';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conname = 'indexed_program_config_settlement_clock_commitment_check'
          AND conrelid = 'public.indexed_program_config'::REGCLASS
    ) THEN
        ALTER TABLE public.indexed_program_config
            ADD CONSTRAINT indexed_program_config_settlement_clock_commitment_check
            CHECK (settlement_clock_source_commitment IN ('unverified', 'finalized'));
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.settlement_clock_contract (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    contract_version SMALLINT NOT NULL CHECK (contract_version = 2),
    legacy_anchor_unix BIGINT NOT NULL CHECK (legacy_anchor_unix = 1704020400),
    v2_anchor_unix BIGINT NOT NULL CHECK (v2_anchor_unix = 1704110400),
    cutover_unix BIGINT NOT NULL,
    cutover_week BIGINT NOT NULL CHECK (cutover_week >= 0),
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds = 604800),
    grace_seconds INTEGER NOT NULL CHECK (grace_seconds = 86400),
    has_legacy_history BOOLEAN NOT NULL,
    program_config_pda TEXT NOT NULL,
    program_config_slot NUMERIC(39, 0) NOT NULL,
    program_config_commitment TEXT NOT NULL CHECK (program_config_commitment = 'finalized'),
    contract_hash TEXT NOT NULL CHECK (length(contract_hash) = 64),
    indexed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now()
);

CREATE OR REPLACE FUNCTION public.br_guard_settlement_clock_contract_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' AND pg_catalog.pg_trigger_depth() < 2 THEN
        RAISE EXCEPTION 'direct settlement_clock_contract insert is forbidden';
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'settlement_clock_contract is immutable';
END;
$$;

DROP TRIGGER IF EXISTS br_settlement_clock_contract_immutable
    ON public.settlement_clock_contract;
DROP TRIGGER IF EXISTS br_settlement_clock_contract_guard
    ON public.settlement_clock_contract;
CREATE TRIGGER br_settlement_clock_contract_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.settlement_clock_contract
FOR EACH ROW EXECUTE FUNCTION public.br_guard_settlement_clock_contract_mutation();

DROP FUNCTION IF EXISTS public.br_reject_settlement_clock_contract_mutation();

REVOKE INSERT, UPDATE, DELETE ON public.settlement_clock_contract FROM PUBLIC;
DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format(
                'REVOKE INSERT, UPDATE, DELETE ON public.settlement_clock_contract FROM %I',
                v_role
            );
        END IF;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_clock_evidence_hash(
    p_cutover_unix BIGINT,
    p_program_config_pda TEXT,
    p_program_config_slot NUMERIC,
    p_program_config_commitment TEXT
)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT pg_catalog.encode(
        pg_catalog.sha256(
            pg_catalog.convert_to(
                pg_catalog.concat_ws(
                    ':', 'settlement-clock-v2', '1704020400', '1704110400',
                    p_cutover_unix::TEXT, '604800', '86400',
                    p_program_config_pda, p_program_config_slot::TEXT,
                    p_program_config_commitment
                ),
                'UTF8'
            )
        ),
        'hex'
    );
$$;

CREATE OR REPLACE FUNCTION public.br_sync_settlement_clock_contract()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_cutover BIGINT;
    v_cutover_week BIGINT;
    v_has_legacy BOOLEAN;
    v_hash TEXT;
    v_existing_hash TEXT;
    v_existing public.settlement_clock_contract%ROWTYPE;
BEGIN
    IF NEW.settlement_clock_version = 0
       AND NEW.settlement_clock_v2_starts_at = 0 THEN
        RETURN NEW;
    END IF;
    IF NEW.settlement_clock_version <> 2 THEN
        RAISE EXCEPTION 'unsupported settlement clock version %', NEW.settlement_clock_version;
    END IF;
    IF NEW.settlement_clock_source_commitment <> 'finalized' OR NEW.chain_slot IS NULL THEN
        RAISE EXCEPTION 'settlement clock requires a finalized ProgramConfig projection';
    END IF;

    v_cutover := NEW.settlement_clock_v2_starts_at;
    v_has_legacy := v_cutover <> 1704110400;
    IF v_cutover < 1704110400
       OR MOD(v_cutover - 1704110400, 604800) <> 0 THEN
        RAISE EXCEPTION 'invalid Monday settlement clock cutover %', v_cutover;
    END IF;
    v_cutover_week := (v_cutover - 1704110400) / 604800;
    IF v_has_legacy
       AND FLOOR(((v_cutover - 1) - 1704020400)::NUMERIC / 604800)::BIGINT
           <> v_cutover_week THEN
        RAISE EXCEPTION 'settlement clock cutover would renumber week %', v_cutover_week;
    END IF;

    v_hash := public.br_settlement_clock_evidence_hash(
        v_cutover,
        NEW.pda,
        NEW.chain_slot,
        NEW.settlement_clock_source_commitment
    );

    SELECT * INTO v_existing
    FROM public.settlement_clock_contract
    WHERE id = 1;

    IF FOUND THEN
        v_existing_hash := public.br_settlement_clock_evidence_hash(
            v_existing.cutover_unix,
            v_existing.program_config_pda,
            v_existing.program_config_slot,
            v_existing.program_config_commitment
        );
        IF v_existing.cutover_unix <> v_cutover
           OR v_existing.cutover_week <> v_cutover_week
           OR v_existing.contract_version <> 2
           OR v_existing.legacy_anchor_unix <> 1704020400
           OR v_existing.v2_anchor_unix <> 1704110400
           OR v_existing.duration_seconds <> 604800
           OR v_existing.grace_seconds <> 86400
           OR v_existing.has_legacy_history <> v_has_legacy
           OR v_existing.program_config_pda <> NEW.pda
           OR v_existing.program_config_commitment <> 'finalized'
           OR v_existing.contract_hash <> v_existing_hash THEN
            RAISE EXCEPTION 'indexed ProgramConfig attempted to replace immutable settlement clock';
        END IF;
    ELSE
        IF v_has_legacy AND EXISTS (
            SELECT 1
            FROM public.settlement_week_runs
            WHERE settlement_week >= v_cutover_week
              AND source_kind = 'authoritative'
        ) THEN
            RAISE EXCEPTION 'settlement run already exists at or after cutover week %', v_cutover_week;
        END IF;

        INSERT INTO public.settlement_clock_contract (
            id, contract_version, legacy_anchor_unix, v2_anchor_unix,
            cutover_unix, cutover_week, duration_seconds, grace_seconds,
            has_legacy_history, program_config_pda, program_config_slot,
            program_config_commitment, contract_hash, indexed_at
        ) VALUES (
            1, 2, 1704020400, 1704110400,
            v_cutover, v_cutover_week, 604800, 86400,
            v_has_legacy, NEW.pda, NEW.chain_slot,
            NEW.settlement_clock_source_commitment, v_hash, NEW.indexed_at
        );

        UPDATE public.settlement_planning_state
        SET settlement_clock_version = 2,
            settlement_clock_v2_starts_at = v_cutover,
            settlement_clock_contract_hash = v_hash,
            updated_at = pg_catalog.now()
        WHERE id = 1;
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_guard_indexed_program_config_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.chain_slot < OLD.chain_slot THEN
        RAISE EXCEPTION 'indexed ProgramConfig slot regression from % to %',
            OLD.chain_slot, NEW.chain_slot;
    END IF;
    IF OLD.settlement_clock_version = 2
       AND (
           NEW.settlement_clock_version <> OLD.settlement_clock_version
           OR NEW.settlement_clock_v2_starts_at <> OLD.settlement_clock_v2_starts_at
           OR NEW.settlement_clock_source_commitment <> OLD.settlement_clock_source_commitment
       ) THEN
        RAISE EXCEPTION 'indexed ProgramConfig attempted to replace immutable settlement clock';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_indexed_program_config_clock_guard
    ON public.indexed_program_config;
CREATE TRIGGER br_indexed_program_config_clock_guard
BEFORE UPDATE ON public.indexed_program_config
FOR EACH ROW EXECUTE FUNCTION public.br_guard_indexed_program_config_clock();

DROP TRIGGER IF EXISTS br_indexed_program_config_settlement_clock
    ON public.indexed_program_config;
CREATE TRIGGER br_indexed_program_config_settlement_clock
AFTER INSERT OR UPDATE OF settlement_clock_v2_starts_at,
    settlement_clock_version, settlement_clock_source_commitment, pda, chain_slot
ON public.indexed_program_config
FOR EACH ROW EXECUTE FUNCTION public.br_sync_settlement_clock_contract();

CREATE OR REPLACE FUNCTION public.br_settlement_clock_contract_hash()
RETURNS TEXT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_hash TEXT;
BEGIN
    SELECT contract_hash INTO v_hash
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF v_hash IS NULL THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    RETURN v_hash;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_week(p_completed_at TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
    v_timestamp BIGINT;
    v_anchor BIGINT;
BEGIN
    SELECT * INTO v_contract
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    v_timestamp := FLOOR(EXTRACT(EPOCH FROM p_completed_at))::BIGINT;
    v_anchor := CASE
        WHEN v_contract.has_legacy_history AND v_timestamp < v_contract.cutover_unix
            THEN v_contract.legacy_anchor_unix
        ELSE v_contract.v2_anchor_unix
    END;
    RETURN GREATEST(
        0,
        FLOOR((v_timestamp - v_anchor)::NUMERIC / v_contract.duration_seconds)::BIGINT
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_week_start(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
    v_anchor BIGINT;
BEGIN
    IF p_week < 0 THEN
        RAISE EXCEPTION 'settlement week must be non-negative';
    END IF;
    SELECT * INTO v_contract
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    v_anchor := CASE
        WHEN v_contract.has_legacy_history AND p_week <= v_contract.cutover_week
            THEN v_contract.legacy_anchor_unix
        ELSE v_contract.v2_anchor_unix
    END;
    RETURN pg_catalog.to_timestamp(v_anchor + p_week * v_contract.duration_seconds);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_week_end(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
BEGIN
    SELECT * INTO v_contract
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    IF v_contract.has_legacy_history AND p_week = v_contract.cutover_week THEN
        RETURN pg_catalog.to_timestamp(
            v_contract.v2_anchor_unix + (p_week + 1) * v_contract.duration_seconds
        );
    END IF;
    RETURN public.br_settlement_week_start(p_week)
        + pg_catalog.make_interval(secs => v_contract.duration_seconds);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_week_finalization_time(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_grace INTEGER;
BEGIN
    SELECT grace_seconds INTO v_grace
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF v_grace IS NULL THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    RETURN public.br_settlement_week_end(p_week)
        + pg_catalog.make_interval(secs => v_grace);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_clock_version_at(p_at TIMESTAMPTZ)
RETURNS SMALLINT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
BEGIN
    SELECT * INTO v_contract
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    IF v_contract.has_legacy_history
       AND FLOOR(EXTRACT(EPOCH FROM p_at))::BIGINT < v_contract.cutover_unix THEN
        RETURN 1;
    END IF;
    RETURN 2;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_settlement_clock_version_for_week(p_week BIGINT)
RETURNS SMALLINT
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
BEGIN
    SELECT * INTO v_contract
    FROM public.settlement_clock_contract
    WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    IF v_contract.has_legacy_history AND p_week < v_contract.cutover_week THEN
        RETURN 1;
    END IF;
    RETURN 2;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_current_epoch()
RETURNS INTEGER
LANGUAGE SQL
STABLE
AS $$
    SELECT public.br_settlement_week(pg_catalog.now())::INTEGER;
$$;

CREATE OR REPLACE FUNCTION public.br_current_settlement_week_start()
RETURNS TIMESTAMPTZ
LANGUAGE SQL
STABLE
AS $$
    SELECT public.br_settlement_week_start(
        public.br_settlement_week(pg_catalog.now())
    );
$$;

CREATE OR REPLACE FUNCTION public.get_global_kom_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time',
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
) RETURNS TABLE (
    rank BIGINT,
    wallet TEXT,
    kom_count BIGINT,
    podium_count BIGINT,
    top10_count BIGINT,
    total_vaults BIGINT,
    most_recent_kom_at TIMESTAMPTZ
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY
    WITH filtered_entries AS (
        SELECT vl.wallet, vl.rank AS lb_rank, vl.achieved_at
        FROM public.vault_leaderboards vl
        WHERE p_time_filter = 'all_time'
           OR (p_time_filter = 'this_epoch'
               AND vl.achieved_at >= public.br_current_settlement_week_start())
           OR (p_time_filter = 'last_30_days'
               AND vl.achieved_at >= pg_catalog.now() - INTERVAL '30 days')
    ), user_stats AS (
        SELECT
            fe.wallet,
            COUNT(*) FILTER (WHERE fe.lb_rank = 1) AS kom_count,
            COUNT(*) FILTER (WHERE fe.lb_rank <= 3) AS podium_count,
            COUNT(*) AS top10_count,
            COUNT(DISTINCT fe.wallet) AS total_vaults,
            MAX(fe.achieved_at) FILTER (WHERE fe.lb_rank = 1) AS most_recent_kom_at
        FROM filtered_entries fe
        GROUP BY fe.wallet
    )
    SELECT
        ROW_NUMBER() OVER (
            ORDER BY us.kom_count DESC, us.podium_count DESC,
                us.top10_count DESC, us.most_recent_kom_at DESC NULLS LAST
        )::BIGINT,
        us.wallet, us.kom_count, us.podium_count, us.top10_count,
        us.total_vaults, us.most_recent_kom_at
    FROM user_stats us
    WHERE us.kom_count > 0
    ORDER BY us.kom_count DESC, us.podium_count DESC,
        us.top10_count DESC, us.most_recent_kom_at DESC NULLS LAST
    LIMIT p_limit OFFSET p_offset;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_global_earnings_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time',
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
) RETURNS TABLE (
    rank BIGINT,
    wallet TEXT,
    total_earnings NUMERIC,
    leaderboard_earnings NUMERIC,
    staking_earnings NUMERIC,
    legend_earnings NUMERIC,
    vaults_with_earnings BIGINT,
    last_earning_at TIMESTAMPTZ
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY
    WITH filtered_events AS (
        SELECT pe.wallet, pe.points_delta, pe.event_type, pe.created_at, pe.reference_id
        FROM public.points_events pe
        WHERE pe.event_type IN (
            'LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS'
        )
          AND pe.points_delta > 0
          AND (
              p_time_filter = 'all_time'
              OR (p_time_filter = 'this_epoch'
                  AND pe.created_at >= public.br_current_settlement_week_start())
              OR (p_time_filter = 'last_30_days'
                  AND pe.created_at >= pg_catalog.now() - INTERVAL '30 days')
          )
    ), user_earnings AS (
        SELECT
            fe.wallet,
            SUM(fe.points_delta) AS total_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'LEADERBOARD_PAYOUT'
            ) AS leaderboard_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'STAKE_EARNINGS'
            ) AS staking_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'LOCAL_LEGEND_EARNINGS'
            ) AS legend_earnings,
            COUNT(DISTINCT fe.reference_id) AS vaults_with_earnings,
            MAX(fe.created_at) AS last_earning_at
        FROM filtered_events fe
        GROUP BY fe.wallet
    )
    SELECT
        ROW_NUMBER() OVER (
            ORDER BY ue.total_earnings DESC,
                ue.leaderboard_earnings DESC NULLS LAST,
                ue.last_earning_at DESC NULLS LAST
        )::BIGINT,
        ue.wallet,
        COALESCE(ue.total_earnings, 0),
        COALESCE(ue.leaderboard_earnings, 0),
        COALESCE(ue.staking_earnings, 0),
        COALESCE(ue.legend_earnings, 0),
        ue.vaults_with_earnings,
        ue.last_earning_at
    FROM user_earnings ue
    WHERE ue.total_earnings > 0
    ORDER BY ue.total_earnings DESC,
        ue.leaderboard_earnings DESC NULLS LAST,
        ue.last_earning_at DESC NULLS LAST
    LIMIT p_limit OFFSET p_offset;
END;
$$;

CREATE OR REPLACE FUNCTION public.count_global_kom_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS BIGINT
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_result BIGINT;
BEGIN
    SELECT COUNT(DISTINCT vl.wallet) INTO v_result
    FROM public.vault_leaderboards vl
    WHERE vl.rank = 1
      AND (
          p_time_filter = 'all_time'
          OR (p_time_filter = 'this_epoch'
              AND vl.achieved_at >= public.br_current_settlement_week_start())
          OR (p_time_filter = 'last_30_days'
              AND vl.achieved_at >= pg_catalog.now() - INTERVAL '30 days')
      );
    RETURN COALESCE(v_result, 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.count_global_earnings_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS BIGINT
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_result BIGINT;
BEGIN
    SELECT COUNT(DISTINCT pe.wallet) INTO v_result
    FROM public.points_events pe
    WHERE pe.event_type IN (
        'LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS'
    )
      AND pe.points_delta > 0
      AND (
          p_time_filter = 'all_time'
          OR (p_time_filter = 'this_epoch'
              AND pe.created_at >= public.br_current_settlement_week_start())
          OR (p_time_filter = 'last_30_days'
              AND pe.created_at >= pg_catalog.now() - INTERVAL '30 days')
      );
    RETURN COALESCE(v_result, 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.get_user_global_kom_rank(
    p_wallet TEXT,
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS TABLE (
    user_rank BIGINT,
    total_users BIGINT,
    kom_count BIGINT,
    podium_count BIGINT,
    top10_count BIGINT,
    percentile NUMERIC
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY
    WITH filtered_entries AS (
        SELECT vl.wallet, vl.rank AS lb_rank
        FROM public.vault_leaderboards vl
        WHERE p_time_filter = 'all_time'
           OR (p_time_filter = 'this_epoch'
               AND vl.achieved_at >= public.br_current_settlement_week_start())
           OR (p_time_filter = 'last_30_days'
               AND vl.achieved_at >= pg_catalog.now() - INTERVAL '30 days')
    ), user_stats AS (
        SELECT
            fe.wallet,
            COUNT(*) FILTER (WHERE fe.lb_rank = 1) AS kom_count,
            COUNT(*) FILTER (WHERE fe.lb_rank <= 3) AS podium_count,
            COUNT(*) AS top10_count
        FROM filtered_entries fe
        GROUP BY fe.wallet
    ), ranked AS (
        SELECT
            us.wallet, us.kom_count, us.podium_count, us.top10_count,
            ROW_NUMBER() OVER (
                ORDER BY us.kom_count DESC, us.podium_count DESC, us.top10_count DESC
            ) AS rnk
        FROM user_stats us
        WHERE us.kom_count > 0
    ), totals AS (
        SELECT COUNT(*) AS cnt FROM ranked
    )
    SELECT
        ranked.rnk::BIGINT,
        totals.cnt::BIGINT,
        ranked.kom_count,
        ranked.podium_count,
        ranked.top10_count,
        ROUND((1 - ranked.rnk::NUMERIC / NULLIF(totals.cnt, 0)) * 100, 1)
    FROM ranked, totals
    WHERE ranked.wallet = p_wallet;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_user_global_earnings_rank(
    p_wallet TEXT,
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS TABLE (
    user_rank BIGINT,
    total_users BIGINT,
    total_earnings NUMERIC,
    leaderboard_earnings NUMERIC,
    staking_earnings NUMERIC,
    legend_earnings NUMERIC,
    percentile NUMERIC
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY
    WITH filtered_events AS (
        SELECT pe.wallet, pe.points_delta, pe.event_type
        FROM public.points_events pe
        WHERE pe.event_type IN (
            'LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS'
        )
          AND pe.points_delta > 0
          AND (
              p_time_filter = 'all_time'
              OR (p_time_filter = 'this_epoch'
                  AND pe.created_at >= public.br_current_settlement_week_start())
              OR (p_time_filter = 'last_30_days'
                  AND pe.created_at >= pg_catalog.now() - INTERVAL '30 days')
          )
    ), user_earnings AS (
        SELECT
            fe.wallet,
            SUM(fe.points_delta) AS total_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'LEADERBOARD_PAYOUT'
            ) AS leaderboard_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'STAKE_EARNINGS'
            ) AS staking_earnings,
            SUM(fe.points_delta) FILTER (
                WHERE fe.event_type = 'LOCAL_LEGEND_EARNINGS'
            ) AS legend_earnings
        FROM filtered_events fe
        GROUP BY fe.wallet
    ), ranked AS (
        SELECT
            ue.wallet,
            COALESCE(ue.total_earnings, 0) AS total_earnings,
            COALESCE(ue.leaderboard_earnings, 0) AS leaderboard_earnings,
            COALESCE(ue.staking_earnings, 0) AS staking_earnings,
            COALESCE(ue.legend_earnings, 0) AS legend_earnings,
            ROW_NUMBER() OVER (ORDER BY ue.total_earnings DESC) AS rnk
        FROM user_earnings ue
        WHERE ue.total_earnings > 0
    ), totals AS (
        SELECT COUNT(*) AS cnt FROM ranked
    )
    SELECT
        ranked.rnk::BIGINT,
        totals.cnt::BIGINT,
        ranked.total_earnings,
        ranked.leaderboard_earnings,
        ranked.staking_earnings,
        ranked.legend_earnings,
        ROUND((1 - ranked.rnk::NUMERIC / NULLIF(totals.cnt, 0)) * 100, 1)
    FROM ranked, totals
    WHERE ranked.wallet = p_wallet;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_settlement_week_at(p_at TIMESTAMPTZ)
RETURNS BIGINT
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_week(p_at);
    END IF;
    RETURN GREATEST(
        0,
        FLOOR((EXTRACT(EPOCH FROM p_at) - 1704020400) / 604800)::BIGINT
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_clock_version_at(p_at TIMESTAMPTZ)
RETURNS SMALLINT
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_clock_version_at(p_at);
    END IF;
    RETURN 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_clock_version_for_week(p_week BIGINT)
RETURNS SMALLINT
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_clock_version_for_week(p_week);
    END IF;
    RETURN 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_clock_hash_for_week(p_week BIGINT)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF public.br_backfill_clock_version_for_week(p_week) = 1 THEN
        RETURN 'legacy-v1:1704020400:604800:86400';
    END IF;
    RETURN public.br_settlement_clock_contract_hash();
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_week_start(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_week_start(p_week);
    END IF;
    RETURN pg_catalog.to_timestamp(1704020400 + p_week * 604800);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_week_end(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_week_end(p_week);
    END IF;
    RETURN pg_catalog.to_timestamp(1704020400 + (p_week + 1) * 604800);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_week_finalization_time(p_week BIGINT)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.settlement_clock_contract WHERE id = 1) THEN
        RETURN public.br_settlement_week_finalization_time(p_week);
    END IF;
    RETURN pg_catalog.to_timestamp(1704020400 + (p_week + 1) * 604800 + 86400);
END;
$$;

CREATE OR REPLACE FUNCTION public.br_backfill_is_cutover_week(p_week BIGINT)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
BEGIN
    SELECT * INTO v_contract FROM public.settlement_clock_contract WHERE id = 1;
    RETURN FOUND
        AND v_contract.has_legacy_history
        AND p_week = v_contract.cutover_week;
END;
$$;

ALTER TABLE public.vault_completions
    ADD COLUMN IF NOT EXISTS settlement_week BIGINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.vault_completions
        WHERE (
            settlement_week IS NOT NULL
            AND settlement_week IS DISTINCT FROM public.br_backfill_settlement_week_at(completed_at)
        ) OR (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM public.br_backfill_clock_version_at(completed_at)
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent vault_completions clock provenance';
    END IF;
END;
$$;

UPDATE public.vault_completions
SET settlement_week = public.br_backfill_settlement_week_at(completed_at),
    settlement_clock_version = public.br_backfill_clock_version_at(completed_at)
WHERE settlement_week IS NULL OR settlement_clock_version IS NULL;

ALTER TABLE public.vault_completions
    ALTER COLUMN settlement_week SET NOT NULL,
    ALTER COLUMN settlement_clock_version SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_vault_completion_settlement_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.settlement_week := public.br_settlement_week(NEW.completed_at);
    NEW.settlement_clock_version := public.br_settlement_clock_version_at(NEW.completed_at);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_vault_completion_settlement_clock
    ON public.vault_completions;
CREATE TRIGGER br_vault_completion_settlement_clock
BEFORE INSERT OR UPDATE ON public.vault_completions
FOR EACH ROW EXECUTE FUNCTION public.br_assign_vault_completion_settlement_clock();

-- Migration 089's distribution trigger fires during the backfill below. Replace
-- both trigger functions first so legacy rows use their stored settlement week.
CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(p_activity_id TEXT)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
BEGIN
    IF p_activity_id IS NULL OR p_activity_id = '' THEN
        RETURN;
    END IF;
    WITH chain_completions AS (
        SELECT iv.id AS vault_id, vc.settlement_week
        FROM public.vault_completions vc
        JOIN public.indexed_vaults iv ON iv.signature_hex = vc.vault_signature
        WHERE vc.activity_id = p_activity_id
          AND vc.on_chain_tx IS NOT NULL
    ), completion_settlements AS (
        SELECT cc.vault_id, cc.settlement_week, MIN(ied.finalized_at) AS finalized_at
        FROM chain_completions cc
        LEFT JOIN public.indexed_epoch_distributions ied
          ON ied.vault_id = cc.vault_id
         AND ied.epoch = cc.settlement_week
         AND ied.finalized_at IS NOT NULL
        GROUP BY cc.vault_id, cc.settlement_week
    )
    SELECT CASE
        WHEN COUNT(*) > 0 AND COUNT(finalized_at) = COUNT(*) THEN MAX(finalized_at)
        ELSE NULL
    END
    INTO v_finalized_at
    FROM completion_settlements;

    UPDATE public.rides
    SET finalized_at = v_finalized_at
    WHERE id::TEXT = p_activity_id
      AND finalized_at IS DISTINCT FROM v_finalized_at;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_sync_epoch_distribution_finalized_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_activity_id TEXT;
BEGIN
    v_finalized_at := COALESCE(
        NEW.finalized_at,
        CASE WHEN NEW.block_time IS NOT NULL THEN pg_catalog.to_timestamp(NEW.block_time) END
    );
    IF v_finalized_at IS NULL THEN
        RETURN NEW;
    END IF;

    UPDATE public.epoch_distributions ed
    SET finalized_at = v_finalized_at
    FROM public.indexed_vaults iv
    WHERE iv.id = NEW.vault_id
      AND ed.epoch::BIGINT = NEW.epoch
      AND (ed.vault_id::BIGINT = NEW.vault_id OR ed.vault_signature = iv.signature_hex)
      AND ed.finalized_at IS DISTINCT FROM v_finalized_at;

    FOR v_activity_id IN
        SELECT DISTINCT vc.activity_id
        FROM public.vault_completions vc
        JOIN public.indexed_vaults iv ON iv.signature_hex = vc.vault_signature
        WHERE iv.id = NEW.vault_id
          AND vc.settlement_week = NEW.epoch
          AND vc.on_chain_tx IS NOT NULL
    LOOP
        PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
    END LOOP;
    RETURN NEW;
END;
$$;

ALTER TABLE public.indexed_epoch_distributions
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.indexed_epoch_distributions
        WHERE (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM
                public.br_backfill_clock_version_for_week(epoch::BIGINT)
        ) OR (
            settlement_clock_contract_hash IS NOT NULL
            AND settlement_clock_contract_hash IS DISTINCT FROM
                public.br_backfill_clock_hash_for_week(epoch::BIGINT)
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent indexed_epoch_distributions clock provenance';
    END IF;
END;
$$;

UPDATE public.indexed_epoch_distributions
SET settlement_clock_version = public.br_backfill_clock_version_for_week(epoch::BIGINT),
    settlement_clock_contract_hash = public.br_backfill_clock_hash_for_week(epoch::BIGINT)
WHERE settlement_clock_version IS NULL
   OR settlement_clock_contract_hash IS NULL;

ALTER TABLE public.indexed_epoch_distributions
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_distribution_settlement_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.settlement_clock_version :=
        public.br_settlement_clock_version_for_week(NEW.epoch::BIGINT);
    NEW.settlement_clock_contract_hash := CASE
        WHEN NEW.settlement_clock_version = 1
            THEN 'legacy-v1:1704020400:604800:86400'
        ELSE public.br_settlement_clock_contract_hash()
    END;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_indexed_distribution_settlement_clock
    ON public.indexed_epoch_distributions;
CREATE TRIGGER br_indexed_distribution_settlement_clock
BEFORE INSERT OR UPDATE ON public.indexed_epoch_distributions
FOR EACH ROW EXECUTE FUNCTION public.br_assign_distribution_settlement_clock();

ALTER TABLE public.indexed_legends
    ADD COLUMN IF NOT EXISTS term_start_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS term_end_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.indexed_legends
        WHERE (
            term_start_at IS NOT NULL
            AND term_start_at IS DISTINCT FROM
                public.br_backfill_week_start(term_start_epoch::BIGINT)
        ) OR (
            term_end_at IS NOT NULL
            AND term_end_at IS DISTINCT FROM
                public.br_backfill_week_start(term_end_epoch::BIGINT)
        ) OR (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM
                public.br_backfill_clock_version_for_week(term_end_epoch::BIGINT)
        ) OR (
            settlement_clock_contract_hash IS NOT NULL
            AND settlement_clock_contract_hash IS DISTINCT FROM
                public.br_backfill_clock_hash_for_week(term_end_epoch::BIGINT)
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent indexed_legends clock provenance';
    END IF;
END;
$$;

UPDATE public.indexed_legends
SET term_start_at = public.br_backfill_week_start(term_start_epoch::BIGINT),
    term_end_at = public.br_backfill_week_start(term_end_epoch::BIGINT),
    settlement_clock_version =
        public.br_backfill_clock_version_for_week(term_end_epoch::BIGINT),
    settlement_clock_contract_hash =
        public.br_backfill_clock_hash_for_week(term_end_epoch::BIGINT)
WHERE term_start_at IS NULL
   OR term_end_at IS NULL
   OR settlement_clock_version IS NULL
   OR settlement_clock_contract_hash IS NULL;

ALTER TABLE public.indexed_legends
    ALTER COLUMN term_start_at SET NOT NULL,
    ALTER COLUMN term_end_at SET NOT NULL,
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_legend_settlement_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.term_start_at := public.br_settlement_week_start(NEW.term_start_epoch::BIGINT);
    NEW.term_end_at := public.br_settlement_week_start(NEW.term_end_epoch::BIGINT);
    NEW.settlement_clock_version :=
        public.br_settlement_clock_version_for_week(NEW.term_end_epoch::BIGINT);
    NEW.settlement_clock_contract_hash := CASE
        WHEN NEW.settlement_clock_version = 1
            THEN 'legacy-v1:1704020400:604800:86400'
        ELSE public.br_settlement_clock_contract_hash()
    END;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_indexed_legend_settlement_clock ON public.indexed_legends;
CREATE TRIGGER br_indexed_legend_settlement_clock
BEFORE INSERT OR UPDATE ON public.indexed_legends
FOR EACH ROW EXECUTE FUNCTION public.br_assign_legend_settlement_clock();

CREATE TABLE IF NOT EXISTS public.local_legend_rollovers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id BIGINT NOT NULL,
    vault_signature TEXT NOT NULL,
    term_start_epoch BIGINT NOT NULL,
    term_end_epoch BIGINT NOT NULL,
    previous_holder TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('elected', 'dormant')),
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'failed')),
    winner TEXT,
    winner_completions INTEGER NOT NULL DEFAULT 0,
    runner_up TEXT,
    runner_up_completions INTEGER NOT NULL DEFAULT 0,
    tx_signature TEXT,
    error_message TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vault_id, term_end_epoch)
);

CREATE INDEX IF NOT EXISTS idx_local_legend_rollovers_status
    ON public.local_legend_rollovers(status, term_end_epoch);

COMMENT ON TABLE public.local_legend_rollovers IS
    'Audit/idempotency table for backend-submitted Local Legend rollover transactions.';

ALTER TABLE public.local_legend_rollovers
    ADD COLUMN IF NOT EXISTS term_start_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS term_end_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.local_legend_rollovers
        WHERE (
            term_start_at IS NOT NULL
            AND term_start_at IS DISTINCT FROM
                public.br_backfill_week_start(term_start_epoch::BIGINT)
        ) OR (
            term_end_at IS NOT NULL
            AND term_end_at IS DISTINCT FROM
                public.br_backfill_week_start(term_end_epoch::BIGINT)
        ) OR (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM
                public.br_backfill_clock_version_for_week(term_end_epoch::BIGINT)
        ) OR (
            settlement_clock_contract_hash IS NOT NULL
            AND settlement_clock_contract_hash IS DISTINCT FROM
                public.br_backfill_clock_hash_for_week(term_end_epoch::BIGINT)
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent local_legend_rollovers clock provenance';
    END IF;
END;
$$;

UPDATE public.local_legend_rollovers
SET term_start_at = public.br_backfill_week_start(term_start_epoch::BIGINT),
    term_end_at = public.br_backfill_week_start(term_end_epoch::BIGINT),
    settlement_clock_version =
        public.br_backfill_clock_version_for_week(term_end_epoch::BIGINT),
    settlement_clock_contract_hash =
        public.br_backfill_clock_hash_for_week(term_end_epoch::BIGINT)
WHERE term_start_at IS NULL
   OR term_end_at IS NULL
   OR settlement_clock_version IS NULL
   OR settlement_clock_contract_hash IS NULL;

ALTER TABLE public.local_legend_rollovers
    ALTER COLUMN term_start_at SET NOT NULL,
    ALTER COLUMN term_end_at SET NOT NULL,
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

DROP TRIGGER IF EXISTS br_local_legend_rollover_settlement_clock
    ON public.local_legend_rollovers;
CREATE TRIGGER br_local_legend_rollover_settlement_clock
BEFORE INSERT OR UPDATE
ON public.local_legend_rollovers
FOR EACH ROW EXECUTE FUNCTION public.br_assign_legend_settlement_clock();

ALTER TABLE public.settlement_planning_state
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_v2_starts_at BIGINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
    v_version SMALLINT := 1;
    v_cutover BIGINT := NULL;
    v_hash TEXT := 'legacy-v1:1704020400:604800:86400';
BEGIN
    SELECT * INTO v_contract FROM public.settlement_clock_contract WHERE id = 1;
    IF FOUND THEN
        v_version := v_contract.contract_version;
        v_cutover := v_contract.cutover_unix;
        v_hash := v_contract.contract_hash;
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.settlement_planning_state
        WHERE (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM v_version
        ) OR (
            settlement_clock_v2_starts_at IS NOT NULL
            AND settlement_clock_v2_starts_at IS DISTINCT FROM v_cutover
        ) OR (
            settlement_clock_contract_hash IS NOT NULL
            AND settlement_clock_contract_hash IS DISTINCT FROM v_hash
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent settlement_planning_state clock provenance';
    END IF;

    UPDATE public.settlement_planning_state
    SET settlement_clock_version = v_version,
        settlement_clock_v2_starts_at = v_cutover,
        settlement_clock_contract_hash = v_hash
    WHERE settlement_clock_version IS NULL
       OR settlement_clock_v2_starts_at IS NULL
       OR settlement_clock_contract_hash IS NULL;
END;
$$;

ALTER TABLE public.settlement_week_runs
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT,
    ADD COLUMN IF NOT EXISTS week_starts_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS week_ends_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS finalizable_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_cutover_week BOOLEAN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.settlement_week_runs
        WHERE (
            settlement_clock_version IS NOT NULL
            AND settlement_clock_version IS DISTINCT FROM
                public.br_backfill_clock_version_for_week(settlement_week::BIGINT)
        ) OR (
            settlement_clock_contract_hash IS NOT NULL
            AND settlement_clock_contract_hash IS DISTINCT FROM
                public.br_backfill_clock_hash_for_week(settlement_week::BIGINT)
        ) OR (
            week_starts_at IS NOT NULL
            AND week_starts_at IS DISTINCT FROM
                public.br_backfill_week_start(settlement_week::BIGINT)
        ) OR (
            week_ends_at IS NOT NULL
            AND week_ends_at IS DISTINCT FROM
                public.br_backfill_week_end(settlement_week::BIGINT)
        ) OR (
            finalizable_at IS NOT NULL
            AND finalizable_at IS DISTINCT FROM
                public.br_backfill_week_finalization_time(settlement_week::BIGINT)
        ) OR (
            is_cutover_week IS NOT NULL
            AND is_cutover_week IS DISTINCT FROM
                public.br_backfill_is_cutover_week(settlement_week::BIGINT)
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent settlement_week_runs clock provenance';
    END IF;
END;
$$;

UPDATE public.settlement_week_runs
SET settlement_clock_version =
        public.br_backfill_clock_version_for_week(settlement_week::BIGINT),
    settlement_clock_contract_hash =
        public.br_backfill_clock_hash_for_week(settlement_week::BIGINT),
    week_starts_at = public.br_backfill_week_start(settlement_week::BIGINT),
    week_ends_at = public.br_backfill_week_end(settlement_week::BIGINT),
    finalizable_at =
        public.br_backfill_week_finalization_time(settlement_week::BIGINT),
    is_cutover_week = public.br_backfill_is_cutover_week(settlement_week::BIGINT)
WHERE settlement_clock_version IS NULL
   OR settlement_clock_contract_hash IS NULL
   OR week_starts_at IS NULL
   OR week_ends_at IS NULL
   OR finalizable_at IS NULL
   OR is_cutover_week IS NULL;

ALTER TABLE public.settlement_week_runs
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL,
    ALTER COLUMN week_starts_at SET NOT NULL,
    ALTER COLUMN week_ends_at SET NOT NULL,
    ALTER COLUMN finalizable_at SET NOT NULL,
    ALTER COLUMN is_cutover_week SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_settlement_run_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_contract public.settlement_clock_contract%ROWTYPE;
BEGIN
    SELECT * INTO v_contract FROM public.settlement_clock_contract WHERE id = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement clock contract is not indexed';
    END IF;
    NEW.settlement_clock_version :=
        public.br_settlement_clock_version_for_week(NEW.settlement_week::BIGINT);
    NEW.settlement_clock_contract_hash := CASE
        WHEN NEW.settlement_clock_version = 1
            THEN 'legacy-v1:1704020400:604800:86400'
        ELSE v_contract.contract_hash
    END;
    NEW.week_starts_at := public.br_settlement_week_start(NEW.settlement_week::BIGINT);
    NEW.week_ends_at := public.br_settlement_week_end(NEW.settlement_week::BIGINT);
    NEW.finalizable_at :=
        public.br_settlement_week_finalization_time(NEW.settlement_week::BIGINT);
    NEW.is_cutover_week := v_contract.has_legacy_history
        AND NEW.settlement_week::BIGINT = v_contract.cutover_week;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_settlement_run_clock ON public.settlement_week_runs;
CREATE TRIGGER br_settlement_run_clock
BEFORE INSERT OR UPDATE ON public.settlement_week_runs
FOR EACH ROW EXECUTE FUNCTION public.br_assign_settlement_run_clock();

ALTER TABLE public.settlement_jobs
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.settlement_jobs AS jobs
        JOIN public.settlement_week_runs AS runs ON runs.id = jobs.run_id
        WHERE (
            jobs.settlement_clock_version IS NOT NULL
            AND jobs.settlement_clock_version IS DISTINCT FROM runs.settlement_clock_version
        ) OR (
            jobs.settlement_clock_contract_hash IS NOT NULL
            AND jobs.settlement_clock_contract_hash IS DISTINCT FROM
                runs.settlement_clock_contract_hash
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent settlement_jobs clock provenance';
    END IF;
END;
$$;

UPDATE public.settlement_jobs AS jobs
SET settlement_clock_version = runs.settlement_clock_version,
    settlement_clock_contract_hash = runs.settlement_clock_contract_hash
FROM public.settlement_week_runs AS runs
WHERE runs.id = jobs.run_id
  AND (
      jobs.settlement_clock_version IS NULL
      OR jobs.settlement_clock_contract_hash IS NULL
  );

ALTER TABLE public.settlement_jobs
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_settlement_job_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    SELECT settlement_clock_version, settlement_clock_contract_hash
    INTO NEW.settlement_clock_version, NEW.settlement_clock_contract_hash
    FROM public.settlement_week_runs
    WHERE id = NEW.run_id;
    IF NEW.settlement_clock_version IS NULL THEN
        RAISE EXCEPTION 'settlement run clock provenance is missing';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_settlement_job_clock ON public.settlement_jobs;
CREATE TRIGGER br_settlement_job_clock
BEFORE INSERT OR UPDATE ON public.settlement_jobs
FOR EACH ROW EXECUTE FUNCTION public.br_assign_settlement_job_clock();

ALTER TABLE public.settlement_reconciliations
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.settlement_reconciliations AS reconciliations
        JOIN public.settlement_jobs AS jobs ON jobs.id = reconciliations.job_id
        WHERE (
            reconciliations.settlement_clock_version IS NOT NULL
            AND reconciliations.settlement_clock_version IS DISTINCT FROM
                jobs.settlement_clock_version
        ) OR (
            reconciliations.settlement_clock_contract_hash IS NOT NULL
            AND reconciliations.settlement_clock_contract_hash IS DISTINCT FROM
                jobs.settlement_clock_contract_hash
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent settlement_reconciliations clock provenance';
    END IF;
END;
$$;

UPDATE public.settlement_reconciliations AS reconciliations
SET settlement_clock_version = jobs.settlement_clock_version,
    settlement_clock_contract_hash = jobs.settlement_clock_contract_hash
FROM public.settlement_jobs AS jobs
WHERE jobs.id = reconciliations.job_id
  AND (
      reconciliations.settlement_clock_version IS NULL
      OR reconciliations.settlement_clock_contract_hash IS NULL
  );

ALTER TABLE public.settlement_reconciliations
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

CREATE OR REPLACE FUNCTION public.br_assign_settlement_child_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    SELECT settlement_clock_version, settlement_clock_contract_hash
    INTO NEW.settlement_clock_version, NEW.settlement_clock_contract_hash
    FROM public.settlement_jobs
    WHERE id = NEW.job_id;
    IF NEW.settlement_clock_version IS NULL THEN
        RAISE EXCEPTION 'settlement job clock provenance is missing';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS br_settlement_reconciliation_clock
    ON public.settlement_reconciliations;
CREATE TRIGGER br_settlement_reconciliation_clock
BEFORE INSERT OR UPDATE ON public.settlement_reconciliations
FOR EACH ROW EXECUTE FUNCTION public.br_assign_settlement_child_clock();

ALTER TABLE public.settlement_notification_outbox
    ADD COLUMN IF NOT EXISTS settlement_clock_version SMALLINT,
    ADD COLUMN IF NOT EXISTS settlement_clock_contract_hash TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.settlement_notification_outbox AS outbox
        JOIN public.settlement_jobs AS jobs ON jobs.id = outbox.job_id
        WHERE (
            outbox.settlement_clock_version IS NOT NULL
            AND outbox.settlement_clock_version IS DISTINCT FROM
                jobs.settlement_clock_version
        ) OR (
            outbox.settlement_clock_contract_hash IS NOT NULL
            AND outbox.settlement_clock_contract_hash IS DISTINCT FROM
                jobs.settlement_clock_contract_hash
        )
    ) THEN
        RAISE EXCEPTION 'inconsistent settlement_notification_outbox clock provenance';
    END IF;
END;
$$;

UPDATE public.settlement_notification_outbox AS outbox
SET settlement_clock_version = jobs.settlement_clock_version,
    settlement_clock_contract_hash = jobs.settlement_clock_contract_hash
FROM public.settlement_jobs AS jobs
WHERE jobs.id = outbox.job_id
  AND (
      outbox.settlement_clock_version IS NULL
      OR outbox.settlement_clock_contract_hash IS NULL
  );

ALTER TABLE public.settlement_notification_outbox
    ALTER COLUMN settlement_clock_version SET NOT NULL,
    ALTER COLUMN settlement_clock_contract_hash SET NOT NULL;

DROP TRIGGER IF EXISTS br_settlement_notification_clock
    ON public.settlement_notification_outbox;
CREATE TRIGGER br_settlement_notification_clock
BEFORE INSERT OR UPDATE ON public.settlement_notification_outbox
FOR EACH ROW EXECUTE FUNCTION public.br_assign_settlement_child_clock();

DROP FUNCTION IF EXISTS public.br_backfill_settlement_week_at(TIMESTAMPTZ);
DROP FUNCTION IF EXISTS public.br_backfill_clock_version_at(TIMESTAMPTZ);
DROP FUNCTION IF EXISTS public.br_backfill_clock_version_for_week(BIGINT);
DROP FUNCTION IF EXISTS public.br_backfill_clock_hash_for_week(BIGINT);
DROP FUNCTION IF EXISTS public.br_backfill_week_start(BIGINT);
DROP FUNCTION IF EXISTS public.br_backfill_week_end(BIGINT);
DROP FUNCTION IF EXISTS public.br_backfill_week_finalization_time(BIGINT);
DROP FUNCTION IF EXISTS public.br_backfill_is_cutover_week(BIGINT);

REVOKE EXECUTE ON FUNCTION public.elect_swanny(TEXT, INTEGER) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.claim_inactive_seat(TEXT, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_current_epoch_for_history() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.record_leaderboard_entry(TEXT, TEXT, INTEGER, INTEGER, INTEGER)
    FROM PUBLIC;
DO $$
BEGIN
    -- Migration 087 retires this writer, but older installations can still
    -- carry the signature. Harden it when present without requiring it.
    IF to_regprocedure(
        'public.update_vault_leaderboard(text,text,integer,integer,uuid,timestamptz)'
    ) IS NOT NULL THEN
        EXECUTE
            'REVOKE EXECUTE ON FUNCTION public.update_vault_leaderboard('
            'text,text,integer,integer,uuid,timestamptz) FROM PUBLIC';
    END IF;
END;
$$;

COMMENT ON TABLE public.settlement_clock_contract IS
    'Immutable projection of the ProgramConfig settlement clock. Existing rows retain v1 provenance; the configured cutover preserves numeric week continuity with one explicit 25-hour bridge.';
COMMENT ON FUNCTION public.br_settlement_week(TIMESTAMPTZ) IS
    'Versioned ProgramConfig-derived Settlement Week assignment. Never reinterpret stored historical week values.';
