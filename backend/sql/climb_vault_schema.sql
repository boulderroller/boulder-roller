-- ============================================================================
-- CLIMB VAULT SCHEMA
-- ============================================================================
-- Canonical climbs derived from OSM/geographic data (NOT user-generated segments)
-- This is the "vault" of verified climbs that user rides can be matched against.
--
-- Philosophy:
-- - Route-agnostic: any path through the climb zone with matching elevation profile counts
-- - Source: OSM elevation data, not user-created segments (avoids Strava IP)
-- - Signatures: 64-byte fingerprints based on gradient shape, not GPS coordinates
-- ============================================================================

-- Canonical climbs in the vault
CREATE TABLE IF NOT EXISTS climb_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ========================================
    -- IDENTITY
    -- ========================================
    name TEXT NOT NULL,                          -- "Alpe d'Huez", "Flagstaff Mountain"
    slug TEXT UNIQUE,                            -- URL-friendly: "alpe-d-huez"
    description TEXT,                            -- Human-readable description
    region TEXT,                                 -- "French Alps", "Boulder County"
    country_code CHAR(2),                        -- ISO 3166-1 alpha-2

    -- ========================================
    -- GEOGRAPHIC BOUNDS
    -- Where the climb physically exists
    -- ========================================
    bounds_min_lat DOUBLE PRECISION NOT NULL,
    bounds_max_lat DOUBLE PRECISION NOT NULL,
    bounds_min_lon DOUBLE PRECISION NOT NULL,
    bounds_max_lon DOUBLE PRECISION NOT NULL,

    -- For complex climb shapes (switchbacks, etc.)
    bounds_polygon JSONB,                        -- GeoJSON Polygon/MultiPolygon

    -- H3 tiles that define this climb's area (resolution 10)
    h3_tile_ids TEXT[],                          -- Array of H3 indexes

    -- ========================================
    -- ELEVATION PROFILE
    -- The canonical characteristics of this climb
    -- ========================================
    base_elevation_m DOUBLE PRECISION,           -- Typical start elevation
    peak_elevation_m DOUBLE PRECISION,           -- Summit elevation
    total_vert_m DOUBLE PRECISION NOT NULL,      -- Expected vertical gain
    avg_gradient_pct DOUBLE PRECISION NOT NULL,  -- Average gradient
    max_gradient_pct DOUBLE PRECISION,           -- Steepest section
    distance_m DOUBLE PRECISION NOT NULL,        -- Typical distance

    -- ========================================
    -- SIGNATURE FOR MATCHING
    -- The 64-byte fingerprint that captures the climb's "shape"
    -- ========================================
    signature_hex CHAR(128) NOT NULL,            -- 64 bytes = 128 hex chars
    signature_tolerance DOUBLE PRECISION DEFAULT 0.65,  -- Min similarity to match (0.0-1.0)

    -- Gradient profile bins (32 values, each 0-255)
    -- Stored separately for debugging/visualization
    gradient_profile SMALLINT[],                 -- 32 gradient bins

    -- ========================================
    -- CLASSIFICATION
    -- ========================================
    uci_category TEXT CHECK (uci_category IN ('HC', '1', '2', '3', '4', 'UC')),
    difficulty_score DOUBLE PRECISION,           -- Computed: vert * (1 + gradient/10)

    -- Tags for filtering
    tags TEXT[],                                 -- ['iconic', 'tour-de-france', 'paved', etc.]

    -- ========================================
    -- SOURCE TRACKING
    -- Where this canonical climb data came from
    -- ========================================
    source TEXT DEFAULT 'osm' CHECK (source IN ('osm', 'manual', 'derived')),
    osm_way_ids BIGINT[],                        -- Related OSM way IDs
    osm_relation_id BIGINT,                      -- OSM relation if applicable
    source_metadata JSONB,                       -- Additional source info

    -- ========================================
    -- STATUS & METADATA
    -- ========================================
    verified BOOLEAN DEFAULT FALSE,              -- Human-verified canonical climb
    active BOOLEAN DEFAULT TRUE,                 -- Available for matching
    featured BOOLEAN DEFAULT FALSE,              -- Show in featured lists

    -- Stats (updated periodically)
    total_completions INTEGER DEFAULT 0,         -- How many times matched
    total_unique_riders INTEGER DEFAULT 0,       -- Unique users who've climbed it

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    verified_at TIMESTAMPTZ,
    verified_by UUID                             -- User who verified
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Geographic queries: find climbs in a bounding box
CREATE INDEX IF NOT EXISTS idx_climb_vault_bounds
ON climb_vault (bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon)
WHERE active = TRUE;

-- Signature prefix for quick filtering before full comparison
CREATE INDEX IF NOT EXISTS idx_climb_vault_sig_prefix
ON climb_vault (LEFT(signature_hex, 16))
WHERE active = TRUE;

-- Category filtering
CREATE INDEX IF NOT EXISTS idx_climb_vault_category
ON climb_vault (uci_category)
WHERE active = TRUE;

-- Region/country queries
CREATE INDEX IF NOT EXISTS idx_climb_vault_region
ON climb_vault (country_code, region)
WHERE active = TRUE;

-- Slug lookups
CREATE INDEX IF NOT EXISTS idx_climb_vault_slug
ON climb_vault (slug)
WHERE slug IS NOT NULL;

-- ============================================================================
-- CLIMB ATTESTATIONS
-- Records of user climbs matched against vault + on-chain proof status
-- ============================================================================

CREATE TABLE IF NOT EXISTS climb_attestations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- ========================================
    -- THE MATCH
    -- ========================================
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ride_id UUID NOT NULL,                       -- Reference to rides table
    vault_climb_id UUID NOT NULL REFERENCES climb_vault(id) ON DELETE CASCADE,

    -- Match quality (how well did user's climb match the canonical?)
    signature_similarity DOUBLE PRECISION NOT NULL CHECK (signature_similarity >= 0 AND signature_similarity <= 1),

    -- ========================================
    -- USER'S PERFORMANCE
    -- ========================================
    vert_m DOUBLE PRECISION NOT NULL,
    time_s INTEGER NOT NULL,
    vam DOUBLE PRECISION,                        -- Vertical Ascent Meters/hour
    avg_power_w DOUBLE PRECISION,
    avg_hr INTEGER,

    -- User's climb signature (their specific effort)
    user_signature_hex CHAR(128) NOT NULL,

    -- ========================================
    -- TILE PROOF
    -- Which H3 tiles the user traversed (verifiable on-chain)
    -- ========================================
    tile_ids TEXT[] NOT NULL,                    -- Array of H3 tile IDs
    tile_count INTEGER GENERATED ALWAYS AS (array_length(tile_ids, 1)) STORED,

    -- Start/end tiles for quick verification
    start_tile_id TEXT,
    end_tile_id TEXT,

    -- ========================================
    -- ON-CHAIN ATTESTATION
    -- ========================================
    attestation_status TEXT DEFAULT 'pending'
        CHECK (attestation_status IN ('pending', 'batched', 'submitted', 'confirmed', 'failed')),

    -- Merkle tree info (when batched)
    merkle_batch_id UUID,                        -- Which batch this is part of
    merkle_leaf_index INTEGER,                   -- Position in the tree
    merkle_leaf_hash CHAR(64),                   -- SHA-256 of leaf data (32 bytes = 64 hex)

    -- Solana transaction (when submitted)
    solana_tx_signature TEXT,                    -- Transaction signature
    solana_slot BIGINT,                          -- Slot number

    -- ========================================
    -- TIMESTAMPS
    -- ========================================
    climb_started_at TIMESTAMPTZ NOT NULL,
    climb_completed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    batched_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ
);

-- ============================================================================
-- ATTESTATION INDEXES
-- ============================================================================

-- User's attestation history
CREATE INDEX IF NOT EXISTS idx_attestations_user
ON climb_attestations (user_id, climb_completed_at DESC);

-- Pending attestations for batching
CREATE INDEX IF NOT EXISTS idx_attestations_pending
ON climb_attestations (attestation_status, created_at)
WHERE attestation_status = 'pending';

-- Vault climb leaderboard queries
CREATE INDEX IF NOT EXISTS idx_attestations_vault_climb
ON climb_attestations (vault_climb_id, time_s ASC);

-- Merkle batch lookups
CREATE INDEX IF NOT EXISTS idx_attestations_batch
ON climb_attestations (merkle_batch_id)
WHERE merkle_batch_id IS NOT NULL;

-- ============================================================================
-- MERKLE BATCHES
-- Groups of attestations combined into a single on-chain transaction
-- ============================================================================

CREATE TABLE IF NOT EXISTS merkle_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Tree structure
    merkle_root CHAR(64) NOT NULL,               -- Root hash (32 bytes = 64 hex)
    tree_depth INTEGER NOT NULL,                 -- Depth of the Merkle tree
    leaf_count INTEGER NOT NULL,                 -- Number of attestations in batch

    -- Full tree stored for proof generation
    tree_json JSONB NOT NULL,                    -- Complete Merkle tree structure

    -- On-chain status
    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'submitted', 'confirmed', 'failed')),
    solana_tx_signature TEXT,
    solana_slot BIGINT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for climb_vault
DROP TRIGGER IF EXISTS climb_vault_updated_at ON climb_vault;
CREATE TRIGGER climb_vault_updated_at
    BEFORE UPDATE ON climb_vault
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active vault climbs with computed fields
CREATE OR REPLACE VIEW climb_vault_active AS
SELECT
    cv.*,
    -- Compute difficulty if not set
    COALESCE(cv.difficulty_score, cv.total_vert_m * (1 + cv.avg_gradient_pct / 10)) as computed_difficulty,
    -- Bounding box center
    (cv.bounds_min_lat + cv.bounds_max_lat) / 2 as center_lat,
    (cv.bounds_min_lon + cv.bounds_max_lon) / 2 as center_lon
FROM climb_vault cv
WHERE cv.active = TRUE;

-- Leaderboard view for a climb
CREATE OR REPLACE VIEW climb_leaderboards AS
SELECT
    ca.vault_climb_id,
    ca.user_id,
    u.wallet as user_wallet,
    ca.time_s,
    ca.vam,
    ca.vert_m,
    ca.climb_completed_at,
    ca.attestation_status,
    ROW_NUMBER() OVER (PARTITION BY ca.vault_climb_id ORDER BY ca.time_s ASC) as rank
FROM climb_attestations ca
JOIN users u ON u.id = ca.user_id
WHERE ca.attestation_status IN ('confirmed', 'submitted');
