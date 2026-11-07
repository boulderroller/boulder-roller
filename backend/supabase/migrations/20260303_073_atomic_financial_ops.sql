-- =============================================================================
-- 073: Atomic Financial Operations
--
-- Fixes CRITICAL race conditions in:
--   1. unstake_cal (read-then-write → atomic)
--   2. vault slot claiming (TOCTOU on vaults_used)
--   3. stake cap enforcement (TOCTOU on per-vault + global caps)
--
-- Uses pg_advisory_xact_lock (same pattern as stake_cal_atomic in 059)
-- =============================================================================

-- =============================================================================
-- 1. unstake_cal_atomic: Atomic unstaking with advisory lock
-- =============================================================================

CREATE OR REPLACE FUNCTION unstake_cal_atomic(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_lp_amount NUMERIC
) RETURNS TABLE (
    cal_returned NUMERIC,
    remaining_lp NUMERIC,
    remaining_cal NUMERIC
) AS $$
DECLARE
    v_current_lp NUMERIC;
    v_current_cal NUMERIC;
    v_cal_returned NUMERIC;
    v_stake_id UUID;
BEGIN
    -- Same lock key as stake_cal_atomic so stake/unstake serialize
    PERFORM pg_advisory_xact_lock(hashtext('stake:' || p_vault_signature));

    -- Read current stake within the lock
    SELECT id, lp_tokens, points_staked
    INTO v_stake_id, v_current_lp, v_current_cal
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature
      AND wallet = p_wallet
      AND unstaked_at IS NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No active stake found for this vault';
    END IF;

    IF p_lp_amount > v_current_lp THEN
        RAISE EXCEPTION 'Insufficient LP tokens: have %, requested %', v_current_lp, p_lp_amount;
    END IF;

    -- Calculate CAL to return (proportional)
    IF v_current_lp > 0 THEN
        v_cal_returned := (p_lp_amount / v_current_lp) * v_current_cal;
    ELSE
        v_cal_returned := 0;
    END IF;

    IF p_lp_amount >= v_current_lp THEN
        -- Full unstake: mark as unstaked
        UPDATE vault_stakes
        SET unstaked_at = now()
        WHERE id = v_stake_id;

        RETURN QUERY SELECT v_cal_returned, 0::NUMERIC, 0::NUMERIC;
    ELSE
        -- Partial unstake: decrement
        UPDATE vault_stakes
        SET lp_tokens = v_current_lp - p_lp_amount,
            points_staked = v_current_cal - v_cal_returned,
            updated_at = now()
        WHERE id = v_stake_id;

        RETURN QUERY SELECT
            v_cal_returned,
            v_current_lp - p_lp_amount,
            v_current_cal - v_cal_returned;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION unstake_cal_atomic IS
'Atomically unstake LP tokens from a vault with proper CAL return calculation.
Uses the same advisory lock as stake_cal_atomic to prevent race conditions
between concurrent stake/unstake operations.';


-- =============================================================================
-- 2. claim_vault_slot_atomic: Atomic vault slot claiming
-- =============================================================================

CREATE OR REPLACE FUNCTION claim_vault_slot_atomic(
    p_wallet TEXT
) RETURNS TABLE (
    new_vaults_used INT
) AS $$
DECLARE
    v_unlocked INT;
    v_used INT;
BEGIN
    -- Lock per-wallet to serialize vault creation attempts
    PERFORM pg_advisory_xact_lock(hashtext('vault_slot:' || p_wallet));

    SELECT vaults_unlocked, vaults_used
    INTO v_unlocked, v_used
    FROM wallet_points
    WHERE wallet = p_wallet;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Wallet not found in wallet_points';
    END IF;

    IF v_used >= v_unlocked THEN
        RAISE EXCEPTION 'Vault creation locked. Earn more lifetime points to unlock new vaults.';
    END IF;

    UPDATE wallet_points
    SET vaults_used = vaults_used + 1
    WHERE wallet = p_wallet;

    RETURN QUERY SELECT v_used + 1;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_vault_slot_atomic IS
'Atomically claim a vault creation slot. Prevents TOCTOU race where two
concurrent vault creations could both pass the entitlement check.';


-- =============================================================================
-- 3. stake_cal_with_cap: Extended staking with cap enforcement inside lock
-- =============================================================================

CREATE OR REPLACE FUNCTION stake_cal_with_cap(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_cal_amount NUMERIC,
    p_per_vault_cap NUMERIC DEFAULT NULL,
    p_global_cap NUMERIC DEFAULT NULL
) RETURNS TABLE (
    stake_id UUID,
    lp_tokens_issued NUMERIC,
    total_staked_after NUMERIC,
    total_lp_after NUMERIC
) AS $$
DECLARE
    v_stake_id UUID;
    v_total_staked NUMERIC;
    v_total_lp NUMERIC;
    v_lp_tokens NUMERIC;
    v_existing_stake RECORD;
    v_existing_staked NUMERIC;
    v_global_staked NUMERIC;
BEGIN
    -- Same lock key as stake_cal_atomic / unstake_cal_atomic
    PERFORM pg_advisory_xact_lock(hashtext('stake:' || p_vault_signature));

    -- Per-vault cap check (inside the lock)
    IF p_per_vault_cap IS NOT NULL THEN
        SELECT COALESCE(points_staked, 0)
        INTO v_existing_staked
        FROM vault_stakes
        WHERE vault_signature = p_vault_signature
          AND wallet = p_wallet
          AND unstaked_at IS NULL;

        IF NOT FOUND THEN
            v_existing_staked := 0;
        END IF;

        IF v_existing_staked + p_cal_amount > p_per_vault_cap THEN
            RAISE EXCEPTION 'Per-vault stake cap exceeded: have %, adding %, cap %',
                v_existing_staked, p_cal_amount, p_per_vault_cap;
        END IF;
    END IF;

    -- Global cap check (across all vaults for this wallet)
    IF p_global_cap IS NOT NULL THEN
        SELECT COALESCE(SUM(points_staked), 0)
        INTO v_global_staked
        FROM vault_stakes
        WHERE wallet = p_wallet
          AND unstaked_at IS NULL;

        IF v_global_staked + p_cal_amount > p_global_cap THEN
            RAISE EXCEPTION 'Global stake cap exceeded for your current tier';
        END IF;
    END IF;

    -- Get current vault totals (within the lock)
    SELECT
        COALESCE(SUM(points_staked), 0),
        COALESCE(SUM(lp_tokens), 0)
    INTO v_total_staked, v_total_lp
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature
      AND unstaked_at IS NULL;

    -- Calculate LP tokens (same logic as stake_cal_atomic)
    IF v_total_staked = 0 THEN
        v_lp_tokens := p_cal_amount;
    ELSE
        v_lp_tokens := (p_cal_amount / v_total_staked) * v_total_lp;
    END IF;

    -- Check for existing stake from this wallet
    SELECT id, points_staked, lp_tokens
    INTO v_existing_stake
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature
      AND wallet = p_wallet
      AND unstaked_at IS NULL;

    IF FOUND THEN
        UPDATE vault_stakes
        SET points_staked = points_staked + p_cal_amount,
            lp_tokens = lp_tokens + v_lp_tokens,
            updated_at = now()
        WHERE id = v_existing_stake.id
        RETURNING id INTO v_stake_id;
    ELSE
        INSERT INTO vault_stakes (
            vault_signature, wallet, points_staked, lp_tokens, staked_at
        ) VALUES (
            p_vault_signature, p_wallet, p_cal_amount, v_lp_tokens, now()
        )
        RETURNING id INTO v_stake_id;
    END IF;

    RETURN QUERY SELECT
        v_stake_id,
        v_lp_tokens,
        v_total_staked + p_cal_amount,
        v_total_lp + v_lp_tokens;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION stake_cal_with_cap IS
'Extended version of stake_cal_atomic that enforces per-vault and global
stake caps inside the advisory lock, preventing TOCTOU race conditions.
Pass NULL for caps to skip enforcement (e.g., post-TGE).';
