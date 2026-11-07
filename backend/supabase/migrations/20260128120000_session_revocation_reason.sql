-- Add revocation_reason column to auth_refresh_tokens for session management UX
-- This tracks why a session was revoked (logged_out, password_changed, admin, expired)

ALTER TABLE IF EXISTS public.auth_refresh_tokens
ADD COLUMN IF NOT EXISTS revocation_reason TEXT DEFAULT NULL;

DO $$
BEGIN
  IF to_regclass('public.auth_refresh_tokens') IS NOT NULL THEN
    CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_revocation_reason
      ON public.auth_refresh_tokens (revocation_reason)
      WHERE revocation_reason IS NOT NULL;

    COMMENT ON COLUMN public.auth_refresh_tokens.revocation_reason IS
      'Reason for session revocation: logged_out_other_device, password_changed, admin_action, session_expired';
  END IF;
END $$;
