-- Fix ambiguous column reference in validate_invite_code function
CREATE OR REPLACE FUNCTION validate_invite_code(
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

    -- Fixed: qualify column references to avoid ambiguity with return table columns
    SELECT EXISTS(
        SELECT 1 FROM invite_code_usage icu
        WHERE icu.code_id = v_code_record.id AND icu.wallet = p_wallet
    ) INTO v_already_used;

    IF v_already_used THEN
        RETURN QUERY SELECT TRUE, 'Invite code valid (already used by this wallet)'::TEXT, v_code_record.id;
        RETURN;
    END IF;

    INSERT INTO invite_code_usage (code_id, wallet, ip_address, user_agent)
    VALUES (v_code_record.id, p_wallet, p_ip_address, p_user_agent);

    UPDATE invite_codes SET current_uses = current_uses + 1 WHERE id = v_code_record.id;

    RETURN QUERY SELECT TRUE, 'Invite code valid'::TEXT, v_code_record.id;
END;
$$ LANGUAGE plpgsql;
