-- Add revocation_reason column to auth_refresh_tokens for session management UX
-- This tracks why a session was revoked (logged_out, password_changed, admin, expired)

ALTER TABLE auth_refresh_tokens
ADD COLUMN IF NOT EXISTS revocation_reason TEXT DEFAULT NULL;

-- Add index for querying revoked sessions
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_revocation_reason
ON auth_refresh_tokens (revocation_reason)
WHERE revocation_reason IS NOT NULL;

COMMENT ON COLUMN auth_refresh_tokens.revocation_reason IS 'Reason for session revocation: logged_out_other_device, password_changed, admin_action, session_expired';
