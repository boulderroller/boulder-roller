-- Freeze a Strava-pattern privacy snapshot on every ride while keeping ride
-- audience and map visibility independent. Existing rides remain at least as
-- private as the pre-migration projection, which hid their entire public map.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS default_map_visibility VARCHAR(20);
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS default_map_hide_start_m INTEGER;
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS default_map_hide_end_m INTEGER;

UPDATE public.users
SET default_map_visibility = 'hide_start_end'
WHERE default_map_visibility IS NULL
   OR default_map_visibility NOT IN ('show_all', 'hide_start_end', 'hide_entire');

UPDATE public.users
SET default_map_hide_start_m = 200
WHERE default_map_hide_start_m IS NULL
   OR default_map_hide_start_m NOT IN (0, 200, 400, 800, 1600);

UPDATE public.users
SET default_map_hide_end_m = 200
WHERE default_map_hide_end_m IS NULL
   OR default_map_hide_end_m NOT IN (0, 200, 400, 800, 1600);

ALTER TABLE public.users
    ALTER COLUMN default_map_visibility SET DEFAULT 'hide_start_end',
    ALTER COLUMN default_map_visibility SET NOT NULL,
    ALTER COLUMN default_map_hide_start_m SET DEFAULT 200,
    ALTER COLUMN default_map_hide_start_m SET NOT NULL,
    ALTER COLUMN default_map_hide_end_m SET DEFAULT 200,
    ALTER COLUMN default_map_hide_end_m SET NOT NULL;

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS map_visibility VARCHAR(20);
ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS map_hide_start_m INTEGER;
ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS map_hide_end_m INTEGER;

-- Preserve the current stricter world-state for every pre-existing ride.
UPDATE public.rides
SET map_visibility = 'hide_entire'
WHERE map_visibility IS NULL
   OR map_visibility NOT IN ('show_all', 'hide_start_end', 'hide_entire');

UPDATE public.rides
SET map_hide_start_m = 200
WHERE map_hide_start_m IS NULL
   OR map_hide_start_m NOT IN (0, 200, 400, 800, 1600);

UPDATE public.rides
SET map_hide_end_m = 200
WHERE map_hide_end_m IS NULL
   OR map_hide_end_m NOT IN (0, 200, 400, 800, 1600);

ALTER TABLE public.rides
    ALTER COLUMN map_visibility SET DEFAULT 'hide_start_end',
    ALTER COLUMN map_visibility SET NOT NULL,
    ALTER COLUMN map_hide_start_m SET DEFAULT 200,
    ALTER COLUMN map_hide_start_m SET NOT NULL,
    ALTER COLUMN map_hide_end_m SET DEFAULT 200,
    ALTER COLUMN map_hide_end_m SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_default_map_visibility_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_default_map_visibility_check
            CHECK (default_map_visibility IN ('show_all', 'hide_start_end', 'hide_entire'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_default_map_hide_start_m_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_default_map_hide_start_m_check
            CHECK (default_map_hide_start_m IN (0, 200, 400, 800, 1600));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_default_map_hide_end_m_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_default_map_hide_end_m_check
            CHECK (default_map_hide_end_m IN (0, 200, 400, 800, 1600));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'users_default_map_endpoint_distance_check'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_default_map_endpoint_distance_check
            CHECK (
                default_map_visibility <> 'hide_start_end'
                OR (default_map_hide_start_m > 0 AND default_map_hide_end_m > 0)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rides_map_visibility_check'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_map_visibility_check
            CHECK (map_visibility IN ('show_all', 'hide_start_end', 'hide_entire'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rides_map_hide_start_m_check'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_map_hide_start_m_check
            CHECK (map_hide_start_m IN (0, 200, 400, 800, 1600));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rides_map_hide_end_m_check'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_map_hide_end_m_check
            CHECK (map_hide_end_m IN (0, 200, 400, 800, 1600));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'rides_map_endpoint_distance_check'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_map_endpoint_distance_check
            CHECK (
                map_visibility <> 'hide_start_end'
                OR (map_hide_start_m > 0 AND map_hide_end_m > 0)
            );
    END IF;
END $$;

COMMENT ON COLUMN public.users.default_map_visibility IS
    'Default map projection for future rides: show_all, hide_start_end, or hide_entire.';
COMMENT ON COLUMN public.users.default_map_hide_start_m IS
    'Default cumulative meters hidden from the start of future rides.';
COMMENT ON COLUMN public.users.default_map_hide_end_m IS
    'Default cumulative meters hidden from the end of future rides.';
COMMENT ON COLUMN public.rides.map_visibility IS
    'Frozen per-ride map projection: show_all, hide_start_end, or hide_entire.';
COMMENT ON COLUMN public.rides.map_hide_start_m IS
    'Frozen cumulative meters hidden from this ride start.';
COMMENT ON COLUMN public.rides.map_hide_end_m IS
    'Frozen cumulative meters hidden from this ride end.';

-- The legacy policies used USING (true) and delegated ownership checks to the
-- backend. Keep the table behind the server boundary instead.
ALTER TABLE public.privacy_zones ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_zones_select ON public.privacy_zones;
DROP POLICY IF EXISTS privacy_zones_insert ON public.privacy_zones;
DROP POLICY IF EXISTS privacy_zones_update ON public.privacy_zones;
DROP POLICY IF EXISTS privacy_zones_delete ON public.privacy_zones;

REVOKE ALL ON TABLE public.privacy_zones FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.privacy_zones TO service_role;
