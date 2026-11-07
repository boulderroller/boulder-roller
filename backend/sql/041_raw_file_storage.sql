-- Migration: Add raw file storage columns to rides table
-- Enables storing original FIT/GPX/TCX files for reprocessing and user download
-- Following Strava's pattern: store original file permanently

-- Add storage-related columns
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS raw_file_path TEXT,
    ADD COLUMN IF NOT EXISTS raw_file_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS file_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS reprocess_count INT DEFAULT 0;

-- Index for duplicate detection (same user, same file hash)
CREATE INDEX IF NOT EXISTS idx_rides_user_file_hash
    ON rides(user_id, file_hash)
    WHERE file_hash IS NOT NULL;

-- Index for finding rides with stored files (admin/cleanup queries)
CREATE INDEX IF NOT EXISTS idx_rides_has_raw_file
    ON rides(raw_file_path)
    WHERE raw_file_path IS NOT NULL;

-- Helper function for atomic reprocess count increment
CREATE OR REPLACE FUNCTION increment_ride_reprocess(p_ride_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE rides
    SET reprocess_count = COALESCE(reprocess_count, 0) + 1
    WHERE id = p_ride_id;
END;
$$ LANGUAGE plpgsql;

-- Comments for documentation
COMMENT ON COLUMN rides.raw_file_path IS 'Supabase Storage path to original upload file (e.g., rides/{user_id}/{ride_id}.fit)';
COMMENT ON COLUMN rides.raw_file_size_bytes IS 'Size of original file in bytes';
COMMENT ON COLUMN rides.file_hash IS 'SHA256 hash of file content for deduplication';
COMMENT ON COLUMN rides.uploaded_at IS 'When file was uploaded (distinct from ride started_at)';
COMMENT ON COLUMN rides.reprocess_count IS 'Number of times this ride has been reprocessed';
