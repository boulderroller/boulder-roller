ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS preliminary_ride_hash_hex CHAR(64),
    ADD COLUMN IF NOT EXISTS preliminary_parser_version INTEGER,
    ADD COLUMN IF NOT EXISTS canonical_match BOOLEAN,
    ADD COLUMN IF NOT EXISTS review_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_rides_preliminary_ride_hash_hex
    ON rides(preliminary_ride_hash_hex);
