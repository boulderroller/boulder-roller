-- 065: Add significance_cell_h3 to patterns_climb for cell-to-climb lookups
-- Stores the H3 cell index that was used for scoring this climb's significance.

ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_cell_h3 TEXT;

CREATE INDEX IF NOT EXISTS idx_patterns_climb_sig_cell
    ON patterns_climb(significance_cell_h3)
    WHERE significance_cell_h3 IS NOT NULL;
