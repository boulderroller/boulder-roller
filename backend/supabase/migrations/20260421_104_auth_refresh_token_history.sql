-- Preserve refresh-token history and avoid false-positive replay detection.
--
-- The original auth schema enforced a unique (wallet, device_id) index, and
-- application code deleted the old row before inserting a rotated token. That
-- erased the revocation trail needed to distinguish benign rotation races from
-- true token reuse. Keep historical rows and replace strict device uniqueness
-- with a lookup index so simultaneous same-device refreshes cannot turn into
-- hard DB conflicts.

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
