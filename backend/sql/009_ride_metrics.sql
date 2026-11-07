-- Migration: Add detailed ride metrics columns
-- Supports file-based upload with server-side parsing (Strava-style)

-- Add new columns to rides table for computed metrics
ALTER TABLE rides ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS distance_m NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS elevation_gain_m NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS avg_power_w NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS avg_hr_bpm NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS avg_speed_mps NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS avg_cadence_rpm NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS max_power_w INTEGER;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS max_hr_bpm INTEGER;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS normalized_power_w NUMERIC;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS gps_track JSONB;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS file_name TEXT;
ALTER TABLE rides ADD COLUMN IF NOT EXISTS device_name TEXT;

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_rides_started_at ON rides (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_rides_user_started ON rides (user_id, started_at DESC);

-- Comment on new columns
COMMENT ON COLUMN rides.distance_m IS 'Total distance in meters';
COMMENT ON COLUMN rides.elevation_gain_m IS 'Total elevation gain in meters';
COMMENT ON COLUMN rides.avg_power_w IS 'Average power in watts';
COMMENT ON COLUMN rides.avg_hr_bpm IS 'Average heart rate in bpm';
COMMENT ON COLUMN rides.avg_speed_mps IS 'Average speed in meters per second';
COMMENT ON COLUMN rides.avg_cadence_rpm IS 'Average cadence in RPM';
COMMENT ON COLUMN rides.max_power_w IS 'Maximum power in watts';
COMMENT ON COLUMN rides.max_hr_bpm IS 'Maximum heart rate in bpm';
COMMENT ON COLUMN rides.normalized_power_w IS 'Normalized Power (NP) for TSS calculation';
COMMENT ON COLUMN rides.gps_track IS 'GPS track as array of {lat, lon, elevation_m, timestamp}';
COMMENT ON COLUMN rides.file_name IS 'Original uploaded filename';
COMMENT ON COLUMN rides.device_name IS 'Device that recorded the ride (e.g., Garmin Edge 530)';
