-- Decision trace and abstention support for climb patterns.
-- Implements TRUTH_CONTRACT_V1 invariants INV-ECON-3, INV-ABST-1-3.
-- Every vault match decision is stored as machine-readable evidence.

ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS match_trace JSONB;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS economic_eligible BOOLEAN DEFAULT TRUE;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS abstention_reasons TEXT[];
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS detector_version TEXT;

-- Index for finding abstained climbs efficiently
CREATE INDEX IF NOT EXISTS idx_patterns_climb_eligible
    ON patterns_climb (economic_eligible)
    WHERE economic_eligible = FALSE;

COMMENT ON COLUMN patterns_climb.match_trace IS 'Machine-readable evidence for vault match decision (JSONB)';
COMMENT ON COLUMN patterns_climb.economic_eligible IS 'False if climb abstained from economic actions per ABSTENTION_POLICY.md';
COMMENT ON COLUMN patterns_climb.abstention_reasons IS 'List of abstention trigger codes (e.g., MATCH:probable_without_gps)';
COMMENT ON COLUMN patterns_climb.detector_version IS 'Algorithm version that produced this detection (persistence, momentum)';
