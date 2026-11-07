-- =============================================================================
-- 074: Pipeline Versions & Detector Configs
--
-- Implements A5's versioning model (Deliverable 1) for reproducible ride
-- processing. Every derived output (metrics, climbs, vault matches, points)
-- is tagged with the pipeline version that produced it.
--
-- Creates:
--   1. pipeline_versions: Immutable registry of version vectors
--   2. detector_configs: Frozen snapshots of detector parameters
--   3. FK columns on rides and patterns_climb
--   4. Initial version row for current pipeline state
--
-- See: output/A5_VERIFICATION_DATA_PLATFORM_DESIGN.md, Section 2
-- =============================================================================

-- =============================================================================
-- 1. detector_configs: Frozen detector parameter snapshots
-- =============================================================================

CREATE TABLE IF NOT EXISTS detector_configs (
    id              SERIAL PRIMARY KEY,

    -- Algorithm identity
    algorithm       TEXT NOT NULL,       -- "persistence" or "momentum"
    version         TEXT NOT NULL,       -- Semver, e.g. "1.0.0"

    -- Frozen parameter snapshot (deterministic JSON serialization)
    params          JSONB NOT NULL,      -- Full parameter set for reproducibility
    params_hash     CHAR(64) NOT NULL,   -- SHA256 of canonical JSON serialization

    -- Metadata
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT,

    -- Same params_hash = same config
    UNIQUE (params_hash)
);

COMMENT ON TABLE detector_configs IS
    'Frozen snapshots of climb detector parameters. Each row represents '
    'a unique parameter configuration. The params_hash ensures deduplication.';


-- =============================================================================
-- 2. pipeline_versions: Immutable version vector registry
-- =============================================================================

CREATE TABLE IF NOT EXISTS pipeline_versions (
    id              SERIAL PRIMARY KEY,

    -- Component versions
    parser_version      TEXT NOT NULL,       -- e.g. "wp-0.1.0" (from Cargo.toml)
    detector_algorithm  TEXT NOT NULL,       -- e.g. "persistence", "momentum"
    detector_version    TEXT NOT NULL,       -- e.g. "1.0.0" (semver for detector params)
    detector_params_hash TEXT NOT NULL,      -- SHA256 of frozen detector config
    sig_format_version  TEXT NOT NULL,       -- e.g. "v2" (signature layout version)
    sig_match_version   TEXT NOT NULL,       -- e.g. "dct6-gps150" (match algo + params)
    economics_version   TEXT NOT NULL,       -- e.g. "points-1.0" or "cal-1.0"
    integrity_version   TEXT NOT NULL,       -- e.g. "si-1.0" (sensor integrity version)

    -- Metadata
    git_commit      CHAR(40) NOT NULL,      -- Full SHA of the commit
    activated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_at  TIMESTAMPTZ,            -- NULL = currently active
    notes           TEXT,

    -- Same component combo = same version
    UNIQUE (parser_version, detector_algorithm, detector_version,
            sig_format_version, sig_match_version, economics_version,
            integrity_version)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_versions_active
    ON pipeline_versions (activated_at DESC)
    WHERE deactivated_at IS NULL;

COMMENT ON TABLE pipeline_versions IS
    'Immutable registry of pipeline version vectors. One active version at a time. '
    'Old versions retained for replay and audit. Never UPDATE or DELETE rows.';


-- =============================================================================
-- 3. Add pipeline_version_id FK to rides and patterns_climb
-- =============================================================================

-- rides: tracks which pipeline version produced the metrics (TSS, NP, IF, etc.)
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS pipeline_version_id INTEGER
    REFERENCES pipeline_versions(id);

COMMENT ON COLUMN rides.pipeline_version_id IS
    'FK to pipeline_versions. Identifies the exact code version that parsed '
    'this ride and computed its metrics. NULL for rides processed before versioning.';

-- patterns_climb: tracks which pipeline version detected this climb
ALTER TABLE patterns_climb
    ADD COLUMN IF NOT EXISTS pipeline_version_id INTEGER
    REFERENCES pipeline_versions(id);

COMMENT ON COLUMN patterns_climb.pipeline_version_id IS
    'FK to pipeline_versions. Identifies the exact code version that detected '
    'this climb. NULL for climbs detected before versioning.';


-- =============================================================================
-- 4. Insert initial pipeline version (current state as of 2026-03-06)
-- =============================================================================

-- First, insert the current detector config
INSERT INTO detector_configs (algorithm, version, params, params_hash, notes)
VALUES (
    'persistence',
    '1.0.0',
    '{
        "noise_gate_tau": 3.0,
        "smoothing_window": 5,
        "ride_elevation_smoothing": 21,
        "match_threshold": 0.08,
        "probable_threshold": 0.15,
        "geometric_tolerance": 0.25,
        "gradient_cap_pct": 45,
        "vam_cap_mhr": 2500,
        "vert_floor_m": 5,
        "distance_cap_m": 500,
        "dct_match_coeffs": 6,
        "gps_gate_m": 150
    }'::jsonb,
    -- SHA256 of the canonical JSON above (pre-computed for determinism)
    -- In production, this would be computed by the application layer
    'a0000000000000000000000000000000a0000000000000000000000000000000',
    'Initial persistence v1.0.0 detector config — pre-versioning baseline'
)
ON CONFLICT (params_hash) DO NOTHING;

-- Now insert the initial pipeline version
INSERT INTO pipeline_versions (
    parser_version,
    detector_algorithm,
    detector_version,
    detector_params_hash,
    sig_format_version,
    sig_match_version,
    economics_version,
    integrity_version,
    git_commit,
    activated_at,
    notes
) VALUES (
    'wp-0.1.0',           -- workout-parse Cargo.toml version
    'persistence',         -- current default detector (CLIMB_ALGORITHM env)
    '1.0.0',              -- initial semver for persistence params
    'a0000000000000000000000000000000a0000000000000000000000000000000',
    'v2',                 -- DCT-II 64-byte signatures (byte 0 = 0x02)
    'dct6-gps150',        -- DCT_MATCH_COEFFS=6, GPS gate=150m
    'points-1.0',         -- pre-TGE points period (1 TSS = 1 point)
    'si-1.0',             -- sensor integrity scorer v1
    '471caf249e0bb589af1120e301211e1a99af9788',  -- HEAD at migration creation
    now(),
    'Initial pipeline version — pre-versioning baseline. All rides and climbs '
    'processed before this migration have NULL pipeline_version_id.'
)
ON CONFLICT (parser_version, detector_algorithm, detector_version,
             sig_format_version, sig_match_version, economics_version,
             integrity_version)
DO NOTHING;
