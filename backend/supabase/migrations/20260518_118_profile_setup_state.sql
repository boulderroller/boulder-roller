-- Track profile setup completion explicitly instead of deriving it from username.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS profile_setup_completed_at timestamptz;

UPDATE public.users
SET profile_setup_completed_at = COALESCE(updated_at, created_at, now())
WHERE profile_setup_completed_at IS NULL
  AND username IS NOT NULL
  AND btrim(username) <> '';

CREATE INDEX IF NOT EXISTS idx_users_profile_setup_completed_at
  ON public.users(profile_setup_completed_at)
  WHERE profile_setup_completed_at IS NOT NULL;

COMMENT ON COLUMN public.users.profile_setup_completed_at IS
  'Set when the rider completes the required first-run profile setup. Do not infer onboarding completion from username alone.';
