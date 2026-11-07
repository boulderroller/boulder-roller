-- Store client-facing rider progression snapshots on processed rides.
--
-- These fields are projected from attested ride TSS plus the rider's prior
-- backend TSS aggregate. They are not token/account truth, but they make the
-- post-ride status contract reproducible and stable across clients.

ALTER TABLE public.rides
  ADD COLUMN IF NOT EXISTS total_tss_after DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS level_delta INTEGER,
  ADD COLUMN IF NOT EXISTS level_after INTEGER;

COMMENT ON COLUMN public.rides.total_tss_after IS
  'Projected cumulative rider TSS immediately after this ride is processed.';
COMMENT ON COLUMN public.rides.level_delta IS
  'Projected rider level increase caused by this ride.';
COMMENT ON COLUMN public.rides.level_after IS
  'Projected rider level immediately after this ride is processed.';
