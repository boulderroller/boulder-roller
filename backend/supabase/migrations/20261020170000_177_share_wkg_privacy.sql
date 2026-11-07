-- Per-rider, explicit opt-in. Existing accounts never opt in implicitly.
SET LOCAL lock_timeout = '5s';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS share_wkg BOOLEAN NOT NULL DEFAULT false;
COMMENT ON COLUMN public.users.share_wkg IS
    'privacy.v2: permission to show measured W/kg to authorized non-owner viewers. Does not grant ride visibility.';
