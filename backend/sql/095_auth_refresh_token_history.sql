-- Preserve refresh-token history and avoid same-device login failures.
--
-- The original auth schema enforced a unique (wallet, device_id) index. That
-- turns repeat login or refresh rotation on the same device into a hard DB
-- conflict once application code starts preserving revoked-token history.
--
-- Replace strict device uniqueness with lookup indexes so:
--   1. repeated sign-in on the same device succeeds
--   2. refresh-token replay detection retains a revocation trail

ALTER TABLE public.auth_refresh_tokens
  ADD COLUMN IF NOT EXISTS revocation_reason text;

DROP INDEX IF EXISTS idx_auth_refresh_unique_device;
DROP INDEX IF EXISTS idx_auth_refresh_active_device;

CREATE INDEX IF NOT EXISTS idx_auth_refresh_device_status
  ON public.auth_refresh_tokens(wallet, device_id, revoked_at);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_revocation_reason
  ON public.auth_refresh_tokens(revocation_reason)
  WHERE revocation_reason IS NOT NULL;

COMMENT ON COLUMN public.auth_refresh_tokens.revocation_reason IS
  'Reason for session revocation: rotated, replaced, logged_out, revoked, refresh_reuse_detected';
