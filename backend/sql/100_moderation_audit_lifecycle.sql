-- Migration: 100_moderation_audit_lifecycle.sql
-- Description: Add moderation.v1 report outcome fields and action history
-- Date: 2026-04-30

CREATE TABLE IF NOT EXISTS social_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID NOT NULL,
    reason VARCHAR(80) NOT NULL,
    details TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    resolution_note TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE social_reports
    ADD COLUMN IF NOT EXISTS contract_version VARCHAR(40) DEFAULT 'moderation.v1',
    ADD COLUMN IF NOT EXISTS resolution_action VARCHAR(50),
    ADD COLUMN IF NOT EXISTS reporter_outcome VARCHAR(50),
    ADD COLUMN IF NOT EXISTS reporter_message TEXT,
    ADD COLUMN IF NOT EXISTS moderation_metadata JSONB DEFAULT '{}';

ALTER TABLE social_reports
    DROP CONSTRAINT IF EXISTS social_reports_status_check;

ALTER TABLE social_reports
    ADD CONSTRAINT social_reports_status_check
    CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed'));

ALTER TABLE social_reports
    DROP CONSTRAINT IF EXISTS social_reports_resolution_action_check;

ALTER TABLE social_reports
    ADD CONSTRAINT social_reports_resolution_action_check
    CHECK (
        resolution_action IS NULL
        OR resolution_action IN ('review_started', 'leave_visible', 'hide', 'remove', 'unsupported')
    );

CREATE INDEX IF NOT EXISTS idx_social_reports_status_created
    ON social_reports(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_reports_target
    ON social_reports(target_type, target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_reports_reporter
    ON social_reports(reporter_id, created_at DESC);

CREATE TABLE IF NOT EXISTS moderation_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES social_reports(id) ON DELETE SET NULL,
    actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR(50) NOT NULL,
    action_status VARCHAR(30) NOT NULL DEFAULT 'applied',
    target_type VARCHAR(50) NOT NULL,
    target_id TEXT NOT NULL,
    note TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE moderation_actions
    DROP CONSTRAINT IF EXISTS moderation_actions_type_check;

ALTER TABLE moderation_actions
    ADD CONSTRAINT moderation_actions_type_check
    CHECK (action_type IN ('review_started', 'leave_visible', 'hide', 'remove', 'unsupported'));

ALTER TABLE moderation_actions
    DROP CONSTRAINT IF EXISTS moderation_actions_status_check;

ALTER TABLE moderation_actions
    ADD CONSTRAINT moderation_actions_status_check
    CHECK (action_status IN ('applied', 'deferred', 'unsupported', 'failed'));

CREATE INDEX IF NOT EXISTS idx_moderation_actions_report
    ON moderation_actions(report_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_moderation_actions_target
    ON moderation_actions(target_type, target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_moderation_actions_actor
    ON moderation_actions(actor_id, created_at DESC);
