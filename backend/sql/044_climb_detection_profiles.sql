-- Migration: 044_climb_detection_profiles
-- Purpose: Protocol-level climb detection tuning profiles
--
-- This enables geographic-aware climb detection without user-facing config.
-- Profiles are managed by the protocol team only.

-- ============================================================================
-- Climb Detection Profiles
-- ============================================================================

CREATE TABLE IF NOT EXISTS climb_detection_profiles (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT,

    -- Base terrain preset to start from (flat, rolling, hilly, mountainous, urban_hills)
    -- NULL means start from default config
    base_terrain TEXT DEFAULT 'auto',

    -- ========================================================================
    -- Core Detection Thresholds (NULL = inherit from base_terrain)
    -- ========================================================================

    -- Minimum vertical gain to qualify as a climb (meters)
    vert_min_m REAL,

    -- Maximum allowed descent within climb window before ending (meters)
    drop_tolerance_m REAL,

    -- Minimum duration for a climb (seconds)
    time_min_s INTEGER,

    -- Maximum duration for a climb (seconds)
    time_max_s INTEGER,

    -- Minimum VAM (Vertical Ascent Meters per hour) to qualify
    vam_min REAL,

    -- ========================================================================
    -- Gradient Thresholds
    -- ========================================================================

    -- Minimum gradient to be considered "climbing" for trimming (percent)
    gradient_min_pct REAL,

    -- Gradient threshold to START detecting a climb (percent)
    gradient_start_threshold REAL,

    -- Gradient threshold to END a climb (percent, usually 0 or negative)
    gradient_end_threshold REAL,

    -- ========================================================================
    -- Momentum Model Parameters
    -- ========================================================================

    -- Momentum level to trigger climb START
    momentum_start_threshold REAL,

    -- Momentum level to trigger climb END
    momentum_end_threshold REAL,

    -- How fast momentum builds when climbing (per sample)
    momentum_climb_rate REAL,

    -- How fast momentum drains when descending (per sample)
    momentum_drain_rate REAL,

    -- Passive decay multiplier on flat terrain
    momentum_decay_rate REAL,

    -- Maximum momentum cap
    momentum_max REAL,

    -- Gradient considered "neutral" (slow decay)
    momentum_gradient_neutral REAL,

    -- ========================================================================
    -- Processing Parameters
    -- ========================================================================

    -- Number of samples for elevation smoothing
    smoothing_window INTEGER,

    -- Samples for gradient calculation window
    gradient_window INTEGER,

    -- Maximum trim ratio (0.0 - 1.0)
    max_trim_ratio REAL,

    -- ========================================================================
    -- Metadata
    -- ========================================================================

    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for active profile lookups
CREATE INDEX idx_climb_detection_profiles_active ON climb_detection_profiles(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- Regional Profile Assignments (H3 resolution 4 ~1,700 km² hexagons)
-- ============================================================================

CREATE TABLE IF NOT EXISTS detection_profile_regions (
    -- H3 index at resolution 4 (regional scale)
    h3_index_r4 TEXT PRIMARY KEY,

    -- Profile to use for this region
    profile_name TEXT NOT NULL REFERENCES climb_detection_profiles(name) ON DELETE CASCADE,

    -- Optional notes about this region assignment
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for profile lookups
CREATE INDEX idx_detection_profile_regions_profile ON detection_profile_regions(profile_name);

-- ============================================================================
-- Seed Initial Profiles
-- ============================================================================

-- Urban Hills profile (Philly-tuned)
INSERT INTO climb_detection_profiles (
    name, description, base_terrain,
    vert_min_m, drop_tolerance_m, time_min_s, time_max_s, vam_min,
    gradient_min_pct, gradient_start_threshold, gradient_end_threshold,
    momentum_start_threshold, momentum_end_threshold,
    momentum_climb_rate, momentum_drain_rate, momentum_decay_rate,
    momentum_max, momentum_gradient_neutral,
    smoothing_window, gradient_window, max_trim_ratio
) VALUES (
    'urban_hills',
    'Short punchy urban climbs - Philadelphia, Pittsburgh, San Francisco, Bristol UK',
    'rolling',  -- Base preset
    20.0, 10.0, 60, 600, 200.0,  -- Core thresholds
    3.0, 2.5, 0.0,  -- Gradient thresholds
    1.5, 0.25, 0.20, 0.22, 0.990, 8.0, 1.0,  -- Momentum params
    3, 5, 0.5  -- Processing params
);

-- Coastal rolling profile (gentler, longer climbs near water)
INSERT INTO climb_detection_profiles (
    name, description, base_terrain,
    vert_min_m, drop_tolerance_m, time_min_s, vam_min,
    gradient_start_threshold
) VALUES (
    'coastal_rolling',
    'Gentle coastal climbs with ocean headwinds - Pacific Coast, Atlantic Coast',
    'rolling',
    30.0, 20.0, 90, 180.0,
    2.0
);

-- ============================================================================
-- Function to get profile config as JSONB for a given region
-- ============================================================================

CREATE OR REPLACE FUNCTION get_detection_config_for_h3(p_h3_index TEXT)
RETURNS JSONB AS $$
DECLARE
    v_profile_name TEXT;
    v_config JSONB;
BEGIN
    -- Try to find regional assignment (resolution 4)
    -- Truncate input H3 to resolution 4 for lookup
    SELECT profile_name INTO v_profile_name
    FROM detection_profile_regions
    WHERE h3_index_r4 = LEFT(p_h3_index, 11);  -- H3 res 4 is ~11 chars

    IF v_profile_name IS NULL THEN
        -- No regional assignment, return NULL (use auto-detection)
        RETURN NULL;
    END IF;

    -- Get profile config
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'name', p.name,
        'base_terrain', p.base_terrain,
        'vert_min_m', p.vert_min_m,
        'drop_tolerance_m', p.drop_tolerance_m,
        'time_min_s', p.time_min_s,
        'time_max_s', p.time_max_s,
        'vam_min', p.vam_min,
        'gradient_min_pct', p.gradient_min_pct,
        'gradient_start_threshold', p.gradient_start_threshold,
        'gradient_end_threshold', p.gradient_end_threshold,
        'momentum_start_threshold', p.momentum_start_threshold,
        'momentum_end_threshold', p.momentum_end_threshold,
        'momentum_climb_rate', p.momentum_climb_rate,
        'momentum_drain_rate', p.momentum_drain_rate,
        'momentum_decay_rate', p.momentum_decay_rate,
        'momentum_max', p.momentum_max,
        'momentum_gradient_neutral', p.momentum_gradient_neutral,
        'smoothing_window', p.smoothing_window,
        'gradient_window', p.gradient_window,
        'max_trim_ratio', p.max_trim_ratio
    )) INTO v_config
    FROM climb_detection_profiles p
    WHERE p.name = v_profile_name AND p.is_active = TRUE;

    RETURN v_config;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- Assign Philadelphia region to urban_hills profile
-- ============================================================================

-- Philadelphia metro area H3 cells at resolution 4
-- These cover roughly: Philadelphia, Camden, Wilmington, Trenton areas
INSERT INTO detection_profile_regions (h3_index_r4, profile_name, notes) VALUES
    ('8444b5bffff', 'urban_hills', 'Philadelphia - Center City & South Philly'),
    ('8444b5affff', 'urban_hills', 'Philadelphia - Manayunk, Roxborough, Wissahickon'),
    ('8444b59ffff', 'urban_hills', 'Philadelphia - Northwest'),
    ('8444b4bffff', 'urban_hills', 'Philadelphia - Northeast'),
    ('8444b4affff', 'urban_hills', 'Montgomery County - Lower Merion, Conshohocken')
ON CONFLICT (h3_index_r4) DO NOTHING;

-- Pittsburgh area
INSERT INTO detection_profile_regions (h3_index_r4, profile_name, notes) VALUES
    ('8444c1bffff', 'urban_hills', 'Pittsburgh - Downtown & Strip District'),
    ('8444c1affff', 'urban_hills', 'Pittsburgh - East End & Squirrel Hill')
ON CONFLICT (h3_index_r4) DO NOTHING;

-- San Francisco area
INSERT INTO detection_profile_regions (h3_index_r4, profile_name, notes) VALUES
    ('8428309ffff', 'urban_hills', 'San Francisco - City proper'),
    ('8428301ffff', 'urban_hills', 'San Francisco - Twin Peaks, Cole Valley')
ON CONFLICT (h3_index_r4) DO NOTHING;

COMMENT ON TABLE climb_detection_profiles IS 'Protocol-managed climb detection tuning profiles';
COMMENT ON TABLE detection_profile_regions IS 'Maps H3 regions to detection profiles';
