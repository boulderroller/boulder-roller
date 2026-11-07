-- Segment efforts: matched ride segments with performance data
CREATE TABLE IF NOT EXISTS segment_efforts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    user_id UUID NOT NULL,
    started_at TIMESTAMPTZ,
    elapsed_time_sec INT NOT NULL,
    effort_score FLOAT NOT NULL,
    average_power_w FLOAT,
    average_hr_bpm FLOAT,
    average_speed_mps FLOAT,
    elevation_gain_m FLOAT,
    distance_m FLOAT,
    rank_at_time INT,
    is_pr BOOLEAN DEFAULT FALSE,
    is_kom BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_segment_efforts_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
    CONSTRAINT fk_segment_efforts_segment
        FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_segment_efforts_ride ON segment_efforts(ride_id);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_segment ON segment_efforts(segment_id);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_user ON segment_efforts(user_id);
CREATE INDEX IF NOT EXISTS idx_segment_efforts_score ON segment_efforts(segment_id, effort_score DESC);
