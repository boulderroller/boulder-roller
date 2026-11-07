-- User achievements: KOMs, PRs, milestones, badges
CREATE TABLE IF NOT EXISTS achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    ride_id UUID,
    segment_id UUID,
    achievement_type VARCHAR(50) NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    value FLOAT,
    rank INT,
    metadata JSONB,
    is_public BOOLEAN DEFAULT TRUE,
    notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_achievements_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_achievements_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_achievements_user ON achievements(user_id);
CREATE INDEX IF NOT EXISTS idx_achievements_type ON achievements(achievement_type);
CREATE INDEX IF NOT EXISTS idx_achievements_created ON achievements(created_at DESC);
