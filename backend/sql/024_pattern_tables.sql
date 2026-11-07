-- Pattern Tables Migration
-- Boulder Rollers v2: Tile-Based Attestation Architecture
--
-- This migration creates tables for detected patterns:
-- - patterns_climb: Sustained vertical gain efforts
-- - patterns_steady: Z2-Z3 aerobic blocks
-- - patterns_exploration: New tile discovery
-- - arenas: Named regions (tile sets)
-- - scored_patterns: CAL-gated scoring for DUNG rewards

-- =====================================================
-- ARENAS TABLE
-- Named regions defined as sets of tiles
-- =====================================================

CREATE TABLE IF NOT EXISTS arenas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    region_hash TEXT,  -- Hash of tile set for integrity verification
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index for active arenas lookup
CREATE INDEX IF NOT EXISTS idx_arenas_active ON arenas(is_active) WHERE is_active = TRUE;

-- Seed the "World Arena" (all tiles count, arena_id = NULL means World Arena)
-- This is the default arena for v1 - any climb anywhere counts
INSERT INTO arenas (id, name, description, is_active)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'World Arena',
    'Global arena - any climb anywhere qualifies. Default for v1.',
    TRUE
) ON CONFLICT (id) DO NOTHING;


-- =====================================================
-- ARENA_TILES TABLE
-- Tile membership for named arenas
-- =====================================================

CREATE TABLE IF NOT EXISTS arena_tiles (
    arena_id UUID NOT NULL REFERENCES arenas(id) ON DELETE CASCADE,
    tile_id TEXT NOT NULL,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (arena_id, tile_id)
);

CREATE INDEX IF NOT EXISTS idx_arena_tiles_tile ON arena_tiles(tile_id);


-- =====================================================
-- PATTERNS_CLIMB TABLE
-- Detected climb patterns
-- =====================================================

CREATE TABLE IF NOT EXISTS patterns_climb (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL,
    wallet TEXT NOT NULL,
    arena_id UUID REFERENCES arenas(id),  -- NULL = World Arena

    -- Core metrics
    vert_m FLOAT NOT NULL,          -- Total vertical gain in meters
    time_s INTEGER NOT NULL,        -- Duration in seconds

    -- Power/HR metrics (optional)
    avg_power_w FLOAT,              -- Average power during climb
    w_per_kg FLOAT,                 -- Watts per kg (if weight available)
    avg_hr INTEGER,                 -- Average heart rate

    -- Time offsets within activity
    start_offset_s INTEGER NOT NULL DEFAULT 0,
    end_offset_s INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Foreign key to rides table
    CONSTRAINT fk_climb_pattern_ride FOREIGN KEY (activity_id) REFERENCES rides(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_climb_patterns_activity ON patterns_climb(activity_id);
CREATE INDEX IF NOT EXISTS idx_climb_patterns_wallet ON patterns_climb(wallet);
CREATE INDEX IF NOT EXISTS idx_climb_patterns_arena ON patterns_climb(arena_id);
CREATE INDEX IF NOT EXISTS idx_climb_patterns_vert ON patterns_climb(vert_m DESC);
CREATE INDEX IF NOT EXISTS idx_climb_patterns_wpkg ON patterns_climb(w_per_kg DESC) WHERE w_per_kg IS NOT NULL;


-- =====================================================
-- PATTERNS_STEADY TABLE
-- Detected steady aerobic patterns
-- =====================================================

CREATE TABLE IF NOT EXISTS patterns_steady (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL,
    wallet TEXT NOT NULL,

    -- Core metrics
    duration_s INTEGER NOT NULL,    -- Duration in seconds

    -- Power metrics (optional)
    avg_power_w FLOAT,              -- Average power
    np_power_w FLOAT,               -- Normalized power

    -- HR metrics (optional)
    avg_hr INTEGER,                 -- Average heart rate

    -- Intensity metrics
    intensity_index FLOAT,          -- IF = NP/FTP (0.0-1.0+)
    variability_index FLOAT,        -- VI = NP/AP

    -- Time offsets within activity
    start_offset_s INTEGER NOT NULL DEFAULT 0,
    end_offset_s INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Foreign key to rides table
    CONSTRAINT fk_steady_pattern_ride FOREIGN KEY (activity_id) REFERENCES rides(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_steady_patterns_activity ON patterns_steady(activity_id);
CREATE INDEX IF NOT EXISTS idx_steady_patterns_wallet ON patterns_steady(wallet);
CREATE INDEX IF NOT EXISTS idx_steady_patterns_duration ON patterns_steady(duration_s DESC);


-- =====================================================
-- PATTERNS_EXPLORATION TABLE
-- Detected exploration patterns
-- =====================================================

CREATE TABLE IF NOT EXISTS patterns_exploration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL,
    wallet TEXT NOT NULL,

    -- Core metrics
    new_tiles_wallet INTEGER NOT NULL,   -- Tiles new to this wallet
    new_tiles_global INTEGER,            -- Tiles new to entire system

    -- Optional metrics
    total_tiles INTEGER DEFAULT 0,       -- Total unique tiles in activity
    night_minutes INTEGER,               -- Minutes riding at night (22:00-04:00)

    -- Time offsets within activity
    start_offset_s INTEGER NOT NULL DEFAULT 0,
    end_offset_s INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Foreign key to rides table
    CONSTRAINT fk_exploration_pattern_ride FOREIGN KEY (activity_id) REFERENCES rides(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_exploration_patterns_activity ON patterns_exploration(activity_id);
CREATE INDEX IF NOT EXISTS idx_exploration_patterns_wallet ON patterns_exploration(wallet);
CREATE INDEX IF NOT EXISTS idx_exploration_patterns_new_tiles ON patterns_exploration(new_tiles_wallet DESC);


-- =====================================================
-- SCORED_PATTERNS TABLE
-- Patterns that have been "scored" for DUNG rewards
-- =====================================================

CREATE TABLE IF NOT EXISTS scored_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL,
    wallet TEXT NOT NULL,
    pattern_type TEXT NOT NULL,          -- 'CLIMB', 'STEADY', 'EXPLORATION'
    pattern_id UUID NOT NULL,            -- FK to patterns_* table

    -- Arena/Flow references
    arena_id UUID REFERENCES arenas(id),
    flow_id UUID,                        -- Reserved for v2

    -- Economic metrics
    cal_cost INTEGER NOT NULL DEFAULT 0,
    dung_total NUMERIC NOT NULL DEFAULT 0,

    -- On-chain tracking
    tx_hash TEXT,
    status TEXT DEFAULT 'PENDING',       -- PENDING, SUCCESS, FAILED

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Foreign key to rides table
    CONSTRAINT fk_scored_pattern_ride FOREIGN KEY (activity_id) REFERENCES rides(id) ON DELETE CASCADE,

    -- Ensure valid pattern type
    CONSTRAINT valid_pattern_type CHECK (pattern_type IN ('CLIMB', 'STEADY', 'EXPLORATION')),

    -- Ensure valid status
    CONSTRAINT valid_status CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_scored_patterns_activity ON scored_patterns(activity_id);
CREATE INDEX IF NOT EXISTS idx_scored_patterns_wallet ON scored_patterns(wallet);
CREATE INDEX IF NOT EXISTS idx_scored_patterns_status ON scored_patterns(status);
CREATE INDEX IF NOT EXISTS idx_scored_patterns_type ON scored_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_scored_patterns_created ON scored_patterns(created_at DESC);

-- Unique constraint: can only score each pattern once
CREATE UNIQUE INDEX IF NOT EXISTS idx_scored_patterns_unique
    ON scored_patterns(pattern_type, pattern_id);


-- =====================================================
-- CAL_DAILY_BALANCES TABLE
-- Track daily CAL allowance and usage
-- =====================================================

CREATE TABLE IF NOT EXISTS cal_daily_balances (
    wallet TEXT NOT NULL,
    date DATE NOT NULL,
    cal_allocated INTEGER DEFAULT 2200,  -- Daily CAL budget (BMR baseline)
    cal_used INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (wallet, date)
);

-- Index for daily balance lookups
CREATE INDEX IF NOT EXISTS idx_cal_balances_date ON cal_daily_balances(date DESC);


-- =====================================================
-- COMMENTS
-- =====================================================

COMMENT ON TABLE arenas IS 'Named regions defined as sets of H3 tiles';
COMMENT ON TABLE arena_tiles IS 'Tile membership for arenas';
COMMENT ON TABLE patterns_climb IS 'Detected climb patterns (sustained vertical gain)';
COMMENT ON TABLE patterns_steady IS 'Detected steady patterns (Z2-Z3 aerobic blocks)';
COMMENT ON TABLE patterns_exploration IS 'Detected exploration patterns (new tile discovery)';
COMMENT ON TABLE scored_patterns IS 'Patterns scored for DUNG rewards (CAL-gated)';
COMMENT ON TABLE cal_daily_balances IS 'Daily CAL budget tracking per wallet';
