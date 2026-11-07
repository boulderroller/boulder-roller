-- Social report queue for rider/community safety.

CREATE TABLE IF NOT EXISTS social_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('ride', 'comment', 'user')),
    target_id UUID NOT NULL,
    reason TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    resolution_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_social_reports_target
    ON social_reports(target_type, target_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_reports_status
    ON social_reports(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_social_reports_reporter
    ON social_reports(reporter_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_social_reports_open_unique
    ON social_reports(reporter_id, target_type, target_id)
    WHERE status IN ('open', 'reviewing');
