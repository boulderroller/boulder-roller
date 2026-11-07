-- Application deployment must use the SAME secret as this transaction-local setting:
-- set_config('app.invite_code_secret', <bound INVITE_CODE_SECRET>, true).
-- No secret literal belongs in this file, SQL logs, or persisted database settings.
BEGIN;
SET LOCAL search_path = public, extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
ALTER TABLE public.invite_codes
    ADD COLUMN IF NOT EXISTS code_hash TEXT,
    ADD COLUMN IF NOT EXISTS intended_for TEXT,
    ADD COLUMN IF NOT EXISTS issued_to_label TEXT,
    ALTER COLUMN code DROP NOT NULL,
    ALTER COLUMN max_uses SET DEFAULT 1,
    ALTER COLUMN expires_at SET DEFAULT (now() + interval '7 days');
DO $$
DECLARE secret TEXT := current_setting('app.invite_code_secret', true);
BEGIN
    IF EXISTS (SELECT 1 FROM public.invite_codes WHERE code IS NOT NULL) THEN
        IF secret IS NULL OR secret = '' THEN
            RAISE EXCEPTION 'Invite backfill requires transaction-local app.invite_code_secret';
        END IF;
        UPDATE public.invite_codes
        SET code_hash = encode(hmac(convert_to(lower(trim(code)), 'UTF8'),
                                   convert_to(secret, 'UTF8'), 'sha256'), 'hex'),
            code = NULL
        WHERE code IS NOT NULL;
    END IF;
END $$;
ALTER TABLE public.invite_codes ALTER COLUMN code_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS invite_codes_code_hash_key ON public.invite_codes(code_hash);
ALTER TABLE public.invite_codes DROP CONSTRAINT IF EXISTS invite_codes_plaintext_absent;
ALTER TABLE public.invite_codes ADD CONSTRAINT invite_codes_plaintext_absent CHECK (code IS NULL);
-- Replace old signatures, including the legacy alias, so no plaintext RPC survives.
DROP FUNCTION IF EXISTS public.validate_invite_code(TEXT, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.check_invite_code(TEXT);
DROP FUNCTION IF EXISTS public.consume_invite_code(TEXT, TEXT, TEXT, TEXT);
-- Split invite prechecks from signup-time consumption.
--
-- Pre-auth clients must be able to check an invite without burning a limited
-- use. Consumption is wallet-keyed and happens only after the final signup
-- wallet is known.

CREATE OR REPLACE FUNCTION check_invite_code(
    p_code TEXT,
    p_wallet TEXT DEFAULT NULL,
    p_email TEXT DEFAULT NULL
) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID) AS $$
DECLARE
    v_code_record RECORD;
BEGIN
    -- p_code is an application-computed HMAC, never plaintext.

    SELECT * INTO v_code_record
    FROM invite_codes ic
    WHERE ic.code_hash = p_code;

    IF v_code_record IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF (p_wallet IS NOT NULL OR p_email IS NOT NULL)
       AND v_code_record.intended_for IS NOT NULL AND NOT (
        CASE WHEN position('@' in v_code_record.intended_for) > 0
        THEN lower(trim(v_code_record.intended_for)) = lower(trim(coalesce(p_email, '')))
        ELSE trim(v_code_record.intended_for) = trim(coalesce(p_wallet, '')) END
    ) THEN
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
    p_user_agent TEXT DEFAULT NULL,
    p_email TEXT DEFAULT NULL
) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID) AS $$
DECLARE
    v_code_record RECORD;
    v_already_used BOOLEAN;
BEGIN
    -- p_code is an application-computed HMAC, never plaintext.
    p_wallet := TRIM(p_wallet);

    IF p_wallet IS NULL OR p_wallet = '' THEN
        RETURN QUERY SELECT FALSE, 'Wallet required to consume invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    -- Lock the invite row before checking max_uses so concurrent signups cannot
    -- oversubscribe a limited-use code.
    SELECT * INTO v_code_record
    FROM invite_codes ic
    WHERE ic.code_hash = p_code
    FOR UPDATE;

    IF v_code_record IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF v_code_record.intended_for IS NOT NULL AND NOT (
        CASE WHEN position('@' in v_code_record.intended_for) > 0
        THEN lower(trim(v_code_record.intended_for)) = lower(trim(coalesce(p_email, '')))
        ELSE trim(v_code_record.intended_for) = trim(coalesce(p_wallet, '')) END
    ) THEN
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

    IF v_already_used AND v_code_record.max_uses IS NULL THEN
        RETURN QUERY SELECT TRUE, 'Invite code valid (already used by this wallet)'::TEXT, v_code_record.id;
        RETURN;
    END IF;

    IF v_code_record.max_uses IS NOT NULL AND v_code_record.current_uses >= v_code_record.max_uses THEN
        RETURN QUERY SELECT FALSE, 'Invite code has reached maximum uses'::TEXT, NULL::UUID;
        RETURN;
    END IF;

    IF v_already_used THEN
        RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
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
    RETURN QUERY SELECT * FROM check_invite_code(p_code, p_wallet, NULL);
END;
$$ LANGUAGE plpgsql STABLE;


ALTER TABLE public.invite_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invite_code_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.invite_codes, public.invite_code_usage FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.invite_codes, public.invite_code_usage TO service_role;
REVOKE ALL ON FUNCTION public.check_invite_code(TEXT,TEXT,TEXT), public.consume_invite_code(TEXT,TEXT,TEXT,TEXT,TEXT), public.validate_invite_code(TEXT,TEXT,TEXT,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.check_invite_code(TEXT,TEXT,TEXT), public.consume_invite_code(TEXT,TEXT,TEXT,TEXT,TEXT), public.validate_invite_code(TEXT,TEXT,TEXT,TEXT) TO service_role;
COMMIT;
