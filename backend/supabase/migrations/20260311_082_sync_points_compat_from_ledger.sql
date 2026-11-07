-- =============================================================================
-- 082: Legacy points compatibility sync from authoritative ledger
--
-- The economic_events ledger is authoritative. This helper keeps the legacy
-- wallet_points / points_events tables in sync during the migration window so
-- older read paths and entitlement logic can continue to function.
--
-- Design goals:
-- - idempotent by ledger event UUID
-- - atomic update of wallet_points + points_events compatibility rows
-- - safe to retry after partial application-level failures
-- =============================================================================

CREATE OR REPLACE FUNCTION sync_points_compat_from_ledger(
    p_event_id UUID,
    p_wallet TEXT,
    p_amount NUMERIC,
    p_event_type TEXT,
    p_points_after NUMERIC,
    p_reference_type TEXT DEFAULT NULL,
    p_reference_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb,
    p_created_at TIMESTAMPTZ DEFAULT now()
) RETURNS BOOLEAN AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('points_compat:' || p_wallet));

    INSERT INTO wallet_points (wallet)
    VALUES (p_wallet)
    ON CONFLICT (wallet) DO NOTHING;

    IF EXISTS (
        SELECT 1
        FROM points_events
        WHERE id = p_event_id
    ) THEN
        RETURN FALSE;
    END IF;

    UPDATE wallet_points
    SET total_points = p_points_after,
        points_from_tss = points_from_tss + CASE
            WHEN p_event_type IN ('TSS_EARN', 'VAULT_COMPLETION') THEN p_amount
            ELSE 0
        END,
        points_from_referral = points_from_referral + CASE
            WHEN p_event_type = 'REFERRAL_BONUS' THEN p_amount
            ELSE 0
        END,
        points_from_leaderboard = points_from_leaderboard + CASE
            WHEN p_event_type IN ('LEADERBOARD_PAYOUT', 'LOCAL_LEGEND_EARNINGS') THEN p_amount
            ELSE 0
        END,
        points_from_staking = points_from_staking + CASE
            WHEN p_event_type = 'STAKE_EARNINGS' THEN p_amount
            ELSE 0
        END,
        lifetime_points_earned = lifetime_points_earned + CASE
            WHEN p_amount > 0 AND p_event_type IN (
                'TSS_EARN',
                'VAULT_COMPLETION',
                'LEADERBOARD_PAYOUT',
                'LOCAL_LEGEND_EARNINGS',
                'REFERRAL_BONUS',
                'STAKE_EARNINGS'
            ) THEN p_amount
            ELSE 0
        END,
        updated_at = now()
    WHERE wallet = p_wallet;

    INSERT INTO points_events (
        id,
        wallet,
        event_type,
        points_delta,
        points_after,
        reference_type,
        reference_id,
        metadata,
        created_at
    ) VALUES (
        p_event_id,
        p_wallet,
        p_event_type,
        p_amount,
        p_points_after,
        p_reference_type,
        p_reference_id,
        COALESCE(p_metadata, '{}'::jsonb),
        COALESCE(p_created_at, now())
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION sync_points_compat_from_ledger IS
    'Idempotently mirrors an authoritative POINTS ledger event into wallet_points '
    'and points_events for transitional compatibility.';


CREATE OR REPLACE FUNCTION points_wallet_balances_current(
    p_min_balance NUMERIC DEFAULT NULL,
    p_limit INTEGER DEFAULT NULL
) RETURNS TABLE (
    wallet TEXT,
    total_points NUMERIC,
    updated_at TIMESTAMPTZ
) AS $$
    WITH latest AS (
        SELECT DISTINCT ON (wallet)
            wallet,
            balance_after AS total_points,
            recorded_at AS updated_at
        FROM economic_events
        WHERE denomination = 'POINTS'
          AND is_reversed = FALSE
        ORDER BY wallet, id DESC
    )
    SELECT
        latest.wallet,
        latest.total_points,
        latest.updated_at
    FROM latest
    WHERE p_min_balance IS NULL OR latest.total_points > p_min_balance
    ORDER BY latest.total_points DESC, latest.wallet ASC
    LIMIT COALESCE(p_limit, 2147483647);
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION points_wallet_balances_current IS
    'Returns current POINTS balances per wallet from the authoritative ledger, '
    'ordered by total_points descending.';
