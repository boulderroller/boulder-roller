-- Terrain cell GPD parameters for geographic significance scoring.
-- Part of Climb Detection V2 (Phase 3: GPD Bootstrap).
--
-- Each row stores fitted Generalized Pareto Distribution parameters for an
-- H3 cell, derived from DEM elevation profiles along OSM road networks.
-- Used to score climb persistence relative to local terrain.

CREATE TABLE IF NOT EXISTS terrain_cells (
    h3_index TEXT PRIMARY KEY,            -- H3 cell index (TEXT, consistent with tile pipeline)
    h3_resolution INT NOT NULL,           -- 4 (coarse fallback) or 5 (primary)
    n_features INT,                       -- Total persistence features found in cell
    k_exceedances INT,                    -- Number of features above threshold
    threshold_m REAL,                     -- Selected GPD threshold (meters)
    threshold_quantile REAL,              -- Which quantile was selected (0.80-0.95)
    gpd_xi REAL,                          -- Shape parameter (>0 heavy tail, <0 bounded)
    gpd_sigma REAL,                       -- Scale parameter
    xi_ci_hi REAL,                        -- 90% upper confidence bound on xi
    g_cap REAL,                           -- Sample-size score cap from Beta(1,k) posterior
    confidence_tier INT NOT NULL DEFAULT 0, -- 0=empirical, 1=low, 2=moderate, 3=full
    tail_diag_pass BOOLEAN DEFAULT FALSE, -- True if >= 2 of 3 diagnostics passed
    bootstrapped_at TIMESTAMPTZ,          -- When this cell was last fitted
    osm_road_km REAL,                     -- Total road km sampled in this cell
    parent_h3_index TEXT                  -- Parent res-4 cell (for fallback lookups)
);

CREATE INDEX IF NOT EXISTS idx_terrain_cells_parent
    ON terrain_cells (parent_h3_index)
    WHERE parent_h3_index IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_terrain_cells_resolution
    ON terrain_cells (h3_resolution);

COMMENT ON TABLE terrain_cells IS 'GPD terrain parameters per H3 cell for climb significance scoring';
COMMENT ON COLUMN terrain_cells.gpd_xi IS 'Shape: >0.1 mountainous, -0.05..0.1 rolling, <-0.05 flat';
COMMENT ON COLUMN terrain_cells.confidence_tier IS '0=empirical (k<12), 1=low (12-19), 2=moderate (20-29), 3=full (30+)';
