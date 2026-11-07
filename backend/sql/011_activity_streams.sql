-- Activity streams: time-series data for power, HR, cadence, speed
CREATE TABLE IF NOT EXISTS activity_streams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,
    stream_type VARCHAR(20) NOT NULL,
    timestamps TIMESTAMPTZ[] NOT NULL,
    values FLOAT[] NOT NULL,
    sample_count INT NOT NULL,
    min_value FLOAT,
    max_value FLOAT,
    avg_value FLOAT,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_activity_streams_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
    CONSTRAINT unique_ride_stream_type
        UNIQUE (ride_id, stream_type)
);

CREATE INDEX IF NOT EXISTS idx_activity_streams_ride ON activity_streams(ride_id);
CREATE INDEX IF NOT EXISTS idx_activity_streams_type ON activity_streams(stream_type);
