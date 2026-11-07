-- Training analytics schema: daily aggregates + fitness metrics
CREATE TABLE IF NOT EXISTS daily_training_load (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_tss NUMERIC NOT NULL DEFAULT 0,
    ride_count INT NOT NULL DEFAULT 0,
    total_duration_sec INT NOT NULL DEFAULT 0,
    total_distance_m NUMERIC NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_dtl_user_date ON daily_training_load(user_id, date DESC);

CREATE TABLE IF NOT EXISTS fitness_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    ctl NUMERIC NOT NULL DEFAULT 0,
    atl NUMERIC NOT NULL DEFAULT 0,
    tsb NUMERIC NOT NULL DEFAULT 0,
    ramp_rate NUMERIC,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_fm_user_date ON fitness_metrics(user_id, date DESC);
