-- Fix ambiguous column reference in get_wallet_entitlements function
-- The return table column 'lifetime_points_earned' conflicts with the CTE column of same name

CREATE OR REPLACE FUNCTION get_wallet_entitlements(
    p_wallet TEXT
) RETURNS TABLE (
    lifetime_points_earned NUMERIC,
    vaults_unlocked INTEGER,
    vaults_used INTEGER,
    stake_cap_points NUMERIC,
    stake_used_points NUMERIC,
    stake_multiplier NUMERIC,
    per_vault_stake_cap NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    WITH wp AS (
        SELECT w.lifetime_points_earned AS lpe
        FROM wallet_points w
        WHERE w.wallet = p_wallet
    ),
    tier AS (
        SELECT t.*
        FROM points_entitlement_tiers t
        WHERE t.min_points <= COALESCE((SELECT lpe FROM wp), 0)
        ORDER BY t.min_points DESC
        LIMIT 1
    ),
    vaults_cnt AS (
        SELECT COUNT(*)::INT AS cnt
        FROM indexed_vaults iv
        WHERE iv.minter = p_wallet
    ),
    stake_used AS (
        SELECT COALESCE(SUM(vs.points_staked), 0) AS total
        FROM vault_stakes vs
        WHERE vs.wallet = p_wallet
          AND vs.unstaked_at IS NULL
    ),
    cfg AS (
        SELECT c.per_vault_stake_cap AS pvc
        FROM points_entitlement_config c
        WHERE c.id = 1
    )
    SELECT
        COALESCE((SELECT lpe FROM wp), 0)::NUMERIC,
        COALESCE((SELECT t.vaults_unlocked FROM tier t), 0)::INTEGER,
        COALESCE((SELECT cnt FROM vaults_cnt), 0)::INTEGER,
        COALESCE((SELECT t.stake_cap_points FROM tier t), 0)::NUMERIC,
        COALESCE((SELECT total FROM stake_used), 0)::NUMERIC,
        COALESCE((SELECT t.stake_multiplier FROM tier t), 1.00)::NUMERIC,
        COALESCE((SELECT pvc FROM cfg), 1000)::NUMERIC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_wallet_entitlements IS 'Get lifetime points entitlements, vault usage, and staking caps (fixed ambiguous column)';
