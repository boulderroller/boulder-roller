-- Migration: 009_user_profiles.sql
-- Description: Extend users table with profile fields, add username system, session management
-- Date: 2024-12-03

-- =============================================================================
-- PART 1: Extend users table with profile fields
-- =============================================================================

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS username text UNIQUE,
  ADD COLUMN IF NOT EXISTS display_name text,
  ADD COLUMN IF NOT EXISTS bio text,
  ADD COLUMN IF NOT EXISTS avatar_url text,
  ADD COLUMN IF NOT EXISTS weight_kg numeric DEFAULT 75,
  ADD COLUMN IF NOT EXISTS ftp_w integer DEFAULT 200,
  ADD COLUMN IF NOT EXISTS preferred_units text DEFAULT 'metric',
  ADD COLUMN IF NOT EXISTS is_public boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();

-- Constraint for preferred_units
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_preferred_units'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_preferred_units
      CHECK (preferred_units IN ('metric', 'imperial'));
  END IF;
END $$;

-- =============================================================================
-- PART 2: Username validation system
-- =============================================================================

-- Case-insensitive unique index on username
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower
  ON public.users(LOWER(username));

-- Username validation function
-- Rules: 3-20 chars, lowercase alphanumeric + underscores, must start with letter
CREATE OR REPLACE FUNCTION validate_username(uname text) RETURNS boolean AS $$
BEGIN
  IF uname IS NULL THEN
    RETURN true;  -- NULL usernames are allowed (not yet set)
  END IF;
  RETURN uname ~ '^[a-z][a-z0-9_]{2,19}$';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Add check constraint for username format
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_username_valid'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_username_valid
      CHECK (username IS NULL OR validate_username(username));
  END IF;
END $$;

-- =============================================================================
-- PART 3: Reserved usernames (prevent impersonation)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.reserved_usernames (
  username text PRIMARY KEY,
  reason text,
  created_at timestamptz DEFAULT now()
);

-- Insert reserved usernames
INSERT INTO public.reserved_usernames (username, reason) VALUES
  ('admin', 'system'),
  ('administrator', 'system'),
  ('boulder', 'brand'),
  ('rollers', 'brand'),
  ('boulderrollers', 'brand'),
  ('boulder_rollers', 'brand'),
  ('support', 'system'),
  ('help', 'system'),
  ('official', 'brand'),
  ('mod', 'system'),
  ('moderator', 'system'),
  ('system', 'system'),
  ('api', 'system'),
  ('app', 'system'),
  ('web', 'system'),
  ('ios', 'system'),
  ('android', 'system'),
  ('solana', 'brand'),
  ('dung', 'brand'),
  ('cal', 'brand'),
  ('kcal', 'brand'),
  ('strava', 'brand'),
  ('garmin', 'brand'),
  ('wahoo', 'brand'),
  ('zwift', 'brand'),
  ('peloton', 'brand'),
  ('null', 'reserved'),
  ('undefined', 'reserved'),
  ('root', 'system'),
  ('test', 'reserved'),
  ('demo', 'reserved')
ON CONFLICT (username) DO NOTHING;

-- =============================================================================
-- PART 4: Username availability check function
-- =============================================================================

CREATE OR REPLACE FUNCTION is_username_available(uname text)
RETURNS TABLE(available boolean, reason text) AS $$
BEGIN
  -- Check format
  IF NOT validate_username(LOWER(uname)) THEN
    RETURN QUERY SELECT false, 'Invalid format. Use 3-20 lowercase letters, numbers, underscores. Must start with a letter.';
    RETURN;
  END IF;

  -- Check reserved
  IF EXISTS (SELECT 1 FROM public.reserved_usernames WHERE reserved_usernames.username = LOWER(uname)) THEN
    RETURN QUERY SELECT false, 'This username is reserved.';
    RETURN;
  END IF;

  -- Check taken
  IF EXISTS (SELECT 1 FROM public.users WHERE LOWER(users.username) = LOWER(uname)) THEN
    RETURN QUERY SELECT false, 'This username is already taken.';
    RETURN;
  END IF;

  RETURN QUERY SELECT true, NULL::text;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- PART 5: Session management enhancements
-- =============================================================================

-- Add metadata columns to refresh tokens for session management UI
ALTER TABLE public.auth_refresh_tokens
  ADD COLUMN IF NOT EXISTS ip_address inet,
  ADD COLUMN IF NOT EXISTS location_hint text,
  ADD COLUMN IF NOT EXISTS last_used_at timestamptz;

-- Index for efficient session listing (active sessions only)
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_wallet_active
  ON public.auth_refresh_tokens(wallet)
  WHERE revoked_at IS NULL;

-- =============================================================================
-- PART 6: User stats view (aggregated ride data)
-- =============================================================================

CREATE OR REPLACE VIEW public.user_stats AS
SELECT
  u.id as user_id,
  COUNT(r.id) as total_rides,
  COALESCE(SUM(r.distance_m) / 1000.0, 0) as total_distance_km,
  COALESCE(SUM(r.elevation_gain_m), 0) as total_elevation_m,
  COALESCE(SUM(r.tss), 0) as total_tss,
  COALESCE(SUM(r.kcals), 0) as total_kcals,
  COALESCE(SUM(r.duration_sec), 0) as total_duration_sec,
  COALESCE(
    (SELECT SUM(me.amount)
     FROM public.mint_events me
     JOIN public.proofs p ON me.proof_id = p.id
     WHERE p.user_id = u.id),
    0
  ) as total_dung_earned
FROM public.users u
LEFT JOIN public.rides r ON r.user_id = u.id
GROUP BY u.id;

-- =============================================================================
-- PART 7: Row Level Security
-- =============================================================================

-- Enable RLS on users table
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

-- Anyone can read public profiles
DROP POLICY IF EXISTS users_select_public ON public.users;
CREATE POLICY users_select_public ON public.users
  FOR SELECT USING (is_public = true OR id = auth.uid());

-- Users can only update their own profile
DROP POLICY IF EXISTS users_update_own ON public.users;
CREATE POLICY users_update_own ON public.users
  FOR UPDATE USING (id = auth.uid());

-- Service role can do everything (bypasses RLS by default, but explicit)
DROP POLICY IF EXISTS users_service_all ON public.users;

-- =============================================================================
-- PART 8: Trigger for updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_updated_at ON public.users;
CREATE TRIGGER users_updated_at
  BEFORE UPDATE ON public.users
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- PART 9: Indexes for performance
-- =============================================================================

-- Index for looking up users by wallet (already exists, but ensure it)
CREATE INDEX IF NOT EXISTS idx_users_wallet ON public.users(wallet);

-- Index for public profile listings
CREATE INDEX IF NOT EXISTS idx_users_public ON public.users(is_public) WHERE is_public = true;

-- =============================================================================
-- DONE
-- =============================================================================

COMMENT ON TABLE public.reserved_usernames IS 'Usernames that cannot be claimed by users';
COMMENT ON COLUMN public.users.username IS 'Unique username (3-20 chars, lowercase alphanumeric + underscore)';
COMMENT ON COLUMN public.users.weight_kg IS 'User weight in kg for TSS/kcal calculations';
COMMENT ON COLUMN public.users.ftp_w IS 'Functional Threshold Power in watts for TSS calculations';
COMMENT ON COLUMN public.users.preferred_units IS 'Display preference: metric or imperial';
COMMENT ON COLUMN public.users.is_public IS 'Whether profile is publicly visible';
