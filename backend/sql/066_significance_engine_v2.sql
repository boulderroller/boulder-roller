-- 066: Significance Engine V2 — review feedback, rider diversity, cell history.
--
-- Three systems in one migration:
--   1. Human feedback loop (review_status on patterns_climb + climb_reviews audit table)
--   2. Rider diversity tracking (effective sample size on terrain_cells)
--   3. Cell parameter history (append-only snapshots for drift detection)

-- =====================================================================
-- 1. HUMAN FEEDBACK LOOP
-- =====================================================================

-- Review status on individual climb detections
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS review_status TEXT;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

-- Stale flag: set when the cell's GPD params drift, cleared on re-score
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_stale BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN patterns_climb.review_status IS
    'NULL=unreviewed, confirmed=human verified, false_positive=not a real climb, '
    'disputed=conflicting reviews, auto_confirmed=algorithmically confirmed';

CREATE INDEX IF NOT EXISTS idx_patterns_climb_review_status
    ON patterns_climb(review_status)
    WHERE review_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_patterns_climb_stale
    ON patterns_climb(significance_stale)
    WHERE significance_stale = TRUE;

-- Partial index for the bootstrap exclusion query (hot path):
-- includes unreviewed (NULL) and everything except false_positive.
CREATE INDEX IF NOT EXISTS idx_patterns_climb_not_fp
    ON patterns_climb(persistence_m)
    WHERE persistence_m IS NOT NULL
      AND persistence_m > 3.0
      AND (review_status IS NULL OR review_status != 'false_positive');

-- Audit trail for all review actions (append-only)
CREATE TABLE IF NOT EXISTS climb_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    climb_id UUID NOT NULL REFERENCES patterns_climb(id) ON DELETE CASCADE,
    reviewer_id TEXT NOT NULL,
    reviewer_wallet TEXT,

    verdict TEXT NOT NULL,
    previous_status TEXT,

    reason TEXT,
    category TEXT,
    confidence_note TEXT,

    batch_id UUID,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_review_verdict CHECK (
        verdict IN ('confirmed', 'false_positive', 'disputed', 'reverted')
    ),
    CONSTRAINT chk_review_category CHECK (
        category IS NULL OR category IN (
            'noise', 'too_short', 'duplicate', 'sensor_error',
            'misattributed', 'borderline', 'other'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_climb_reviews_climb ON climb_reviews(climb_id);
CREATE INDEX IF NOT EXISTS idx_climb_reviews_batch ON climb_reviews(batch_id) WHERE batch_id IS NOT NULL;

COMMENT ON TABLE climb_reviews IS
    'Append-only audit trail for human review of detected climbs';

-- Per-cell feedback aggregation view
CREATE OR REPLACE VIEW v_cell_feedback_summary AS
SELECT
    pc.significance_cell_h3 AS h3_index,
    COUNT(*) AS total_climbs,
    COUNT(*) FILTER (WHERE pc.review_status = 'false_positive') AS false_positive_count,
    COUNT(*) FILTER (WHERE pc.review_status = 'confirmed') AS confirmed_count,
    COUNT(*) FILTER (WHERE pc.review_status = 'auto_confirmed') AS auto_confirmed_count,
    COUNT(*) FILTER (WHERE pc.review_status = 'disputed') AS disputed_count,
    COUNT(*) FILTER (WHERE pc.review_status IS NULL) AS unreviewed_count,
    CASE
        WHEN COUNT(*) FILTER (WHERE pc.review_status = 'false_positive') >= 3
        THEN TRUE ELSE FALSE
    END AS needs_refit
FROM patterns_climb pc
WHERE pc.significance_cell_h3 IS NOT NULL
GROUP BY pc.significance_cell_h3;


-- =====================================================================
-- 2. RIDER DIVERSITY TRACKING
-- =====================================================================

ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS n_unique_riders INT DEFAULT 0;
ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS effective_n REAL;
ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS top_rider_pct REAL;
ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS diversity_tier INT NOT NULL DEFAULT 0;
ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS n_unique_routes INT;

COMMENT ON COLUMN terrain_cells.n_unique_riders IS
    'Count of distinct wallets contributing observations to this cell';
COMMENT ON COLUMN terrain_cells.effective_n IS
    'Kish effective sample size: (sum w_i)^2 / sum(w_i^2). '
    'Equals n if all riders contribute equally, 1 if one rider dominates';
COMMENT ON COLUMN terrain_cells.top_rider_pct IS
    'Fraction of observations from the most prolific rider (0-1)';
COMMENT ON COLUMN terrain_cells.diversity_tier IS
    '0=suspect (1 rider or eff<3), 1=thin (2-4 riders), 2=adequate (5+), 3=rich (10+)';


-- =====================================================================
-- 3. CELL PARAMETER HISTORY (drift detection)
-- =====================================================================

ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS run_id UUID;
ALTER TABLE terrain_cells ADD COLUMN IF NOT EXISTS history_count INT DEFAULT 0;

CREATE TABLE IF NOT EXISTS terrain_cell_history (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    h3_index TEXT NOT NULL,
    h3_resolution INT NOT NULL,

    -- Full parameter snapshot
    n_features INT,
    k_exceedances INT,
    threshold_m REAL,
    threshold_quantile REAL,
    gpd_xi REAL,
    gpd_sigma REAL,
    xi_ci_hi REAL,
    g_cap REAL,
    confidence_tier INT NOT NULL DEFAULT 0,
    tail_diag_pass BOOLEAN DEFAULT FALSE,

    -- Diversity snapshot
    n_unique_riders INT,
    effective_n REAL,
    diversity_tier INT,

    -- Deltas from previous snapshot
    prev_gpd_xi REAL,
    prev_gpd_sigma REAL,
    delta_xi REAL,
    delta_sigma REAL,
    delta_n_features INT,
    delta_k_exceedances INT,
    tier_changed BOOLEAN DEFAULT FALSE,
    diag_changed BOOLEAN DEFAULT FALSE,

    -- Drift assessment
    max_score_impact REAL,
    drift_flagged BOOLEAN DEFAULT FALSE,

    -- Metadata
    trigger_reason TEXT NOT NULL DEFAULT 'manual_bootstrap',
    excluded_climb_ids TEXT[],
    admin_wallet TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cell_history_h3_time
    ON terrain_cell_history (h3_index, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_cell_history_run
    ON terrain_cell_history (run_id);

CREATE INDEX IF NOT EXISTS idx_cell_history_drift
    ON terrain_cell_history (drift_flagged)
    WHERE drift_flagged = TRUE;

COMMENT ON TABLE terrain_cell_history IS
    'Append-only snapshots of terrain cell GPD parameters per bootstrap run';
COMMENT ON COLUMN terrain_cell_history.max_score_impact IS
    'Maximum absolute score change for any climb in this cell vs previous params';
COMMENT ON COLUMN terrain_cell_history.trigger_reason IS
    'manual_bootstrap, ride_data_growth, feedback_exclusion, parameter_change';
