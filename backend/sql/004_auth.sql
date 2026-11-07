-- Auth-related tables for SIWS flow
CREATE TABLE IF NOT EXISTS public.auth_nonces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet text NOT NULL,
  nonce text UNIQUE NOT NULL,
  issued_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  device_id text,
  used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_auth_nonces_wallet ON public.auth_nonces(wallet);
CREATE INDEX IF NOT EXISTS idx_auth_nonces_expires_at ON public.auth_nonces(expires_at);

CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet text NOT NULL,
  token_hash text UNIQUE NOT NULL,
  device_id text NOT NULL,
  user_agent text,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_refresh_unique_device ON public.auth_refresh_tokens(wallet, device_id);
