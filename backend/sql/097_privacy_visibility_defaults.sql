-- Set-and-forget privacy defaults for rider activity visibility.
-- Existing rides keep their current visibility; future rides inherit the
-- rider's default unless an upload/import explicitly sets a ride override.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_ride_visibility VARCHAR(20) DEFAULT 'public';

UPDATE users
SET default_ride_visibility = 'public'
WHERE default_ride_visibility IS NULL
   OR default_ride_visibility NOT IN ('public', 'followers', 'private');

ALTER TABLE users
    ALTER COLUMN default_ride_visibility SET DEFAULT 'public';

ALTER TABLE users
    ALTER COLUMN default_ride_visibility SET NOT NULL;

ALTER TABLE rides
    ALTER COLUMN visibility SET DEFAULT 'public';

UPDATE rides
SET visibility = 'public'
WHERE visibility IS NULL
   OR visibility NOT IN ('public', 'followers', 'private');

ALTER TABLE rides
    ALTER COLUMN visibility SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_default_ride_visibility_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_default_ride_visibility_check
            CHECK (default_ride_visibility IN ('public', 'followers', 'private'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'rides_visibility_check'
    ) THEN
        ALTER TABLE rides
            ADD CONSTRAINT rides_visibility_check
            CHECK (visibility IN ('public', 'followers', 'private'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_default_ride_visibility
    ON users(default_ride_visibility);

COMMENT ON COLUMN users.default_ride_visibility IS
    'Default visibility applied to newly uploaded/imported rides: public, followers, private.';
