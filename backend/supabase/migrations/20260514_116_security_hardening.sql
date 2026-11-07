-- Harden auth/account deletion, Strava provenance, and public waitlist capture.

-- Tombstone deleted wallets so stateless access tokens cannot recreate an
-- account after the user requested deletion.
CREATE TABLE IF NOT EXISTS public.deleted_wallets (
  wallet text PRIMARY KEY,
  deleted_user_id uuid,
  deletion_request_id uuid,
  deleted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deleted_wallets_deleted_at
  ON public.deleted_wallets(deleted_at DESC);

-- Keep deletion request history after the users row is removed.
ALTER TABLE IF EXISTS public.deletion_requests
  ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE IF EXISTS public.deletion_requests
  DROP CONSTRAINT IF EXISTS deletion_requests_user_id_fkey;

ALTER TABLE IF EXISTS public.deletion_requests
  ADD CONSTRAINT deletion_requests_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;

-- Public landing-page waitlist storage.
CREATE TABLE IF NOT EXISTS public.waitlist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  source text NOT NULL DEFAULT 'landing',
  ip_hash bigint,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_waitlist_created_at
  ON public.waitlist(created_at DESC);

-- Strava imports now create rides directly; the provenance marker must point
-- at rides.id instead of the legacy activities table.
UPDATE public.strava_imported_activities imported
SET activity_id = NULL
WHERE activity_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.rides rides WHERE rides.id = imported.activity_id
  );

ALTER TABLE IF EXISTS public.strava_imported_activities
  DROP CONSTRAINT IF EXISTS strava_imported_activities_activity_id_fkey;

ALTER TABLE IF EXISTS public.strava_imported_activities
  ADD CONSTRAINT strava_imported_activities_activity_id_fkey
  FOREIGN KEY (activity_id) REFERENCES public.rides(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.strava_imported_activities.activity_id IS
  'Boulder Roller rides.id for the imported Strava activity; legacy name retained for compatibility.';
