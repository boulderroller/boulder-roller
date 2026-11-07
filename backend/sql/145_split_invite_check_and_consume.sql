-- Split invite prechecks from signup-time consumption.
--
-- Pre-auth clients must be able to check an invite without burning a limited
-- use. Consumption is wallet-keyed and happens only after the final signup
-- wallet is known.

CREATE OR REPLACE FUNCTION check_invite_code(
    p_code TEXT
) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID) AS $$
DECLARE
    v_code_record RECORD;
BEGIN
    p_code := LOWER(TRIM(p_code));

    SELECT * INTO v_code_record
    FROM invite_codes ic
    WHERE LOWER(ic.code) = p_code;

    IF v_code_record IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF NOT v_code_record.is_active THEN
        RETURN QUERY SELECT FALSE, 'Invite code is no longer active'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF v_code_record.expires_at IS NOT NULL AND v_code_record.expires_at < NOW() THEN
        RETURN QUERY SELECT FALSE, 'Invite code has expired'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF v_code_record.max_uses IS NOT NULL AND v_code_record.current_uses >= v_code_record.max_uses THEN
        RETURN QUERY SELECT FALSE, 'Invite code has reached maximum uses'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    RETURN QUERY SELECT TRUE, 'Invite code valid'::TEXT, v_code_record.id;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION consume_invite_code(
    p_code TEXT,
    p_wallet TEXT,
    p_ip_address TEXT DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID) AS $$
DECLARE
    v_code_record RECORD;
    v_already_used BOOLEAN;
BEGIN
    p_code := LOWER(TRIM(p_code));
    p_wallet := TRIM(p_wallet);

    IF p_wallet IS NULL OR p_wallet = '' THEN
        RETURN QUERY SELECT FALSE, 'Wallet required to consume invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    -- Lock the invite row before checking max_uses so concurrent signups cannot
    -- oversubscribe a limited-use code.
    SELECT * INTO v_code_record
    FROM invite_codes ic
    WHERE LOWER(ic.code) = p_code
    FOR UPDATE;

    IF v_code_record IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF NOT v_code_record.is_active THEN
        RETURN QUERY SELECT FALSE, 'Invite code is no longer active'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF v_code_record.expires_at IS NOT NULL AND v_code_record.expires_at < NOW() THEN
        RETURN QUERY SELECT FALSE, 'Invite code has expired'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    SELECT EXISTS(
        SELECT 1 FROM invite_code_usage icu
        WHERE icu.code_id = v_code_record.id AND icu.wallet = p_wallet
    ) INTO v_already_used;

    IF v_already_used THEN
        RETURN QUERY SELECT TRUE, 'Invite code valid (already used by this wallet)'::TEXT, v_code_record.id;
        RETURN;
    END IF;

    IF v_code_record.max_uses IS NOT NULL AND v_code_record.current_uses >= v_code_record.max_uses THEN
        RETURN QUERY SELECT FALSE, 'Invite code has reached maximum uses'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    INSERT INTO invite_code_usage (code_id, wallet, ip_address, user_agent)
    VALUES (v_code_record.id, p_wallet, p_ip_address, p_user_agent);

    UPDATE invite_codes
    SET current_uses = current_uses + 1
    WHERE id = v_code_record.id;

    RETURN QUERY SELECT TRUE, 'Invite code consumed'::TEXT, v_code_record.id;
END;
$$ LANGUAGE plpgsql;

-- Preserve the old RPC name as a non-mutating compatibility alias. Signup code
-- must call consume_invite_code explicitly.
CREATE OR REPLACE FUNCTION validate_invite_code(
    p_code TEXT,
    p_wallet TEXT DEFAULT NULL,
    p_ip_address TEXT DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID) AS $$
BEGIN
    RETURN QUERY SELECT * FROM check_invite_code(p_code);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION check_invite_code(TEXT) IS
    'Non-mutating invite precheck for unauthenticated clients.';
COMMENT ON FUNCTION consume_invite_code(TEXT, TEXT, TEXT, TEXT) IS
    'Consumes an invite code for a known signup wallet, idempotent by code_id+wallet.';
COMMENT ON FUNCTION validate_invite_code(TEXT, TEXT, TEXT, TEXT) IS
    'Deprecated compatibility alias for non-mutating check_invite_code.';
