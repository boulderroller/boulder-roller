-- Migration: 101_moderation_visibility_application.sql
-- Description: Apply moderation hide/remove actions to product visibility
-- Date: 2026-04-30

-- moderation_state is the shared product visibility flag used by reports.
-- It is deliberately soft-delete shaped: moderators can hide/remove content
-- from social/product surfaces without destroying protocol or audit facts.

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS moderation_state VARCHAR(30) NOT NULL DEFAULT 'visible',
    ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS moderated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_report_id UUID REFERENCES social_reports(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_reason TEXT;

ALTER TABLE comments
    ADD COLUMN IF NOT EXISTS moderation_state VARCHAR(30) NOT NULL DEFAULT 'visible',
    ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS moderated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_report_id UUID REFERENCES social_reports(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_reason TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS moderation_state VARCHAR(30) NOT NULL DEFAULT 'visible',
    ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS moderated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_report_id UUID REFERENCES social_reports(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_reason TEXT;

ALTER TABLE activities
    ADD COLUMN IF NOT EXISTS moderation_state VARCHAR(30) NOT NULL DEFAULT 'visible';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'rides_moderation_state_check'
    ) THEN
        ALTER TABLE rides
            ADD CONSTRAINT rides_moderation_state_check
            CHECK (moderation_state IN ('visible', 'hidden', 'removed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'comments_moderation_state_check'
    ) THEN
        ALTER TABLE comments
            ADD CONSTRAINT comments_moderation_state_check
            CHECK (moderation_state IN ('visible', 'hidden', 'removed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_moderation_state_check'
    ) THEN
        ALTER TABLE users
            ADD CONSTRAINT users_moderation_state_check
            CHECK (moderation_state IN ('visible', 'hidden', 'removed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'activities_moderation_state_check'
    ) THEN
        ALTER TABLE activities
            ADD CONSTRAINT activities_moderation_state_check
            CHECK (moderation_state IN ('visible', 'hidden', 'removed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_rides_moderation_state
    ON rides(moderation_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_comments_moderation_state
    ON comments(moderation_state, target_type, target_id, created_at);

CREATE INDEX IF NOT EXISTS idx_users_moderation_state
    ON users(moderation_state, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_activities_moderation_state
    ON activities(moderation_state, occurred_at DESC);
