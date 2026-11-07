-- Canonical feed.v1 event fields.
-- The legacy activities table remains the storage table, but these columns
-- make event semantics explicit instead of inferred from title/metadata.

ALTER TABLE activities
    ADD COLUMN IF NOT EXISTS schema_version VARCHAR(20) DEFAULT 'feed.v1',
    ADD COLUMN IF NOT EXISTS event_type VARCHAR(80),
    ADD COLUMN IF NOT EXISTS actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'public',
    ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

UPDATE activities
SET schema_version = COALESCE(schema_version, 'feed.v1'),
    actor_id = COALESCE(actor_id, user_id),
    occurred_at = COALESCE(occurred_at, created_at),
    visibility = CASE
        WHEN is_public IS FALSE THEN 'private'
        ELSE COALESCE(visibility, 'public')
    END,
    event_type = COALESCE(
        event_type,
        CASE
            WHEN activity_type IN ('follow', 'follow_created', 'new_follower') THEN 'follow_created'
            WHEN activity_type IN ('comment', 'comment_created') THEN 'comment_created'
            WHEN activity_type IN ('achievement', 'achievement_unlocked') THEN 'achievement_unlocked'
            WHEN activity_type IN ('record', 'record_rank_moved', 'rank_moved') THEN 'record_rank_moved'
            WHEN activity_type IN ('local_legend', 'local_legend_moved') THEN 'local_legend_moved'
            WHEN activity_type IN ('climb', 'climb_completed') OR target_type = 'climb' THEN 'climb_completed'
            WHEN activity_type IN ('report', 'report_resolved') THEN 'report_resolved'
            WHEN activity_type IN ('ride', 'ride_completed') OR target_type = 'ride' THEN 'ride_completed'
            ELSE 'social'
        END
    );

ALTER TABLE activities
    ALTER COLUMN schema_version SET NOT NULL,
    ALTER COLUMN event_type SET NOT NULL,
    ALTER COLUMN occurred_at SET NOT NULL,
    ALTER COLUMN visibility SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'activities_visibility_check'
    ) THEN
        ALTER TABLE activities
            ADD CONSTRAINT activities_visibility_check
            CHECK (visibility IN ('public', 'followers', 'private'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_activities_event_type_created
    ON activities(event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_activities_actor_created
    ON activities(actor_id, occurred_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_activities_dedupe_key
    ON activities(dedupe_key)
    WHERE dedupe_key IS NOT NULL;

COMMENT ON COLUMN activities.event_type IS
    'Canonical feed.v1 event type, e.g. ride_completed, climb_completed, local_legend_moved.';
COMMENT ON COLUMN activities.occurred_at IS
    'Domain event time used for feed ordering and pagination cursors.';
