-- =============================================================================
-- 084: patterns_climb v2 signature column
--
-- Ride processing now persists the DCT v2 climb signature for exact replay,
-- backfill, and vault matching. Production pattern writes currently fail
-- because the table is missing this column, even though application code
-- already inserts it.
-- =============================================================================

ALTER TABLE patterns_climb
    ADD COLUMN IF NOT EXISTS signature_v2_hex TEXT;

COMMENT ON COLUMN patterns_climb.signature_v2_hex IS
    'Hex-encoded DCT v2 climb signature used for replay diffs and vault matching.';

CREATE INDEX IF NOT EXISTS idx_patterns_climb_signature_v2
    ON patterns_climb(signature_v2_hex)
    WHERE signature_v2_hex IS NOT NULL;

-- Refresh PostgREST schema cache so the new column becomes writable
-- immediately through the Supabase REST API.
NOTIFY pgrst, 'reload schema';
