-- Invite Codes: Server-side validation for alpha access
-- Replaces hardcoded frontend codes with backend-validated codes

CREATE TABLE IF NOT EXISTS invite_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    max_uses INTEGER DEFAULT NULL,  -- NULL = unlimited
    current_uses INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_by TEXT,  -- wallet of creator (if applicable)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NULL  -- NULL = never expires
);

-- Index for quick code lookups
CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code);
CREATE INDEX IF NOT EXISTS idx_invite_codes_active ON invite_codes(is_active);

-- Track code usage
CREATE TABLE IF NOT EXISTS invite_code_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID NOT NULL REFERENCES invite_codes(id),
    wallet TEXT NOT NULL,
    used_at TIMESTAMPTZ DEFAULT NOW(),
    ip_address TEXT,
    user_agent TEXT,
    UNIQUE(code_id, wallet)  -- Each wallet can only use a code once
);

CREATE INDEX IF NOT EXISTS idx_invite_code_usage_code ON invite_code_usage(code_id);
CREATE INDEX IF NOT EXISTS idx_invite_code_usage_wallet ON invite_code_usage(wallet);

-- Function to validate and record invite code usage
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
    -- Normalize code to lowercase
    p_code := LOWER(TRIM(p_code));

    -- Look up the code
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

    -- Check if wallet already used this code
    SELECT EXISTS(
        SELECT 1 FROM invite_code_usage icu
        WHERE icu.code_id = v_code_record.id AND icu.wallet = p_wallet
    ) INTO v_already_used;

    IF v_already_used THEN
        -- Already used is still valid (idempotent)
        RETURN QUERY SELECT TRUE, 'Invite code valid (already used by this wallet)'::TEXT, v_code_record.id;
        RETURN;
    END IF;

    -- Record usage
    INSERT INTO invite_code_usage (code_id, wallet, ip_address, user_agent)
    VALUES (v_code_record.id, p_wallet, p_ip_address, p_user_agent);

    -- Increment usage count
    UPDATE invite_codes SET current_uses = current_uses + 1 WHERE id = v_code_record.id;

    RETURN QUERY SELECT TRUE, 'Invite code valid'::TEXT, v_code_record.id;
END;
$$ LANGUAGE plpgsql;

-- Alpha invite codes are seeded via admin tooling, not in migration files.
-- See .env for INVITE_CODES configuration.

COMMENT ON TABLE invite_codes IS 'Server-validated invite codes for alpha access';
COMMENT ON TABLE invite_code_usage IS 'Tracks which wallets have used which invite codes';
COMMENT ON FUNCTION validate_invite_code IS 'Validates and records invite code usage, returns validity status';
