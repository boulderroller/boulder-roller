-- Enable PostGIS if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis;

-- GPS track points for segment matching
CREATE TABLE IF NOT EXISTS gps_points (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,
    sequence_num INT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    elevation_m FLOAT,
    distance_m FLOAT,
    location GEOGRAPHY(POINT, 4326),
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_gps_points_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_gps_points_ride ON gps_points(ride_id, sequence_num);
CREATE INDEX IF NOT EXISTS idx_gps_points_timestamp ON gps_points(ride_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_gps_points_location ON gps_points USING GIST(location);

CREATE OR REPLACE FUNCTION update_gps_location()
RETURNS TRIGGER AS $$
BEGIN
    NEW.location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_gps_points_location
    BEFORE INSERT OR UPDATE ON gps_points
    FOR EACH ROW
    EXECUTE FUNCTION update_gps_location();
