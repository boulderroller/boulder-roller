-- 149: projection-only DEM elevation correction (boulderroller-v2-odmi6.2.1)
--
-- Server-side corrected climbing totals + relief profile sampled from the
-- repository-controlled USGS 3DEP Delaware Valley grid (the canon pipeline's
-- DEM source). These columns are a read-model projection:
--   * rides.elevation_gain_m is NEVER overwritten — it remains raw device
--     truth and feeds the frozen economic plan and achievements;
--   * NULL status = correction never attempted (legacy rides);
--   * status 'unavailable' = attempted and truthfully abstained (reason set,
--     gain and profile NULL — absence is never rendered as zero).

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS elevation_correction_status TEXT,
    ADD COLUMN IF NOT EXISTS elevation_correction_source TEXT,
    ADD COLUMN IF NOT EXISTS elevation_correction_version TEXT,
    ADD COLUMN IF NOT EXISTS elevation_correction_coverage_bps INTEGER,
    ADD COLUMN IF NOT EXISTS elevation_correction_reason TEXT,
    ADD COLUMN IF NOT EXISTS elevation_corrected_gain_m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS elevation_correction_profile JSONB;

COMMENT ON COLUMN rides.elevation_correction_status IS
    'DEM correction outcome: corrected | unavailable. NULL = never attempted. Projection-only; never replaces elevation_gain_m.';
COMMENT ON COLUMN rides.elevation_correction_source IS
    'DEM source version the correction sampled (e.g. usgs_3dep_13as_dv_1as_grid_v1).';
COMMENT ON COLUMN rides.elevation_correction_version IS
    'Correction algorithm version (map-match/smoothing/hysteresis parameters).';
COMMENT ON COLUMN rides.elevation_correction_coverage_bps IS
    'Route points matched against the DEM, in basis points of all route points.';
COMMENT ON COLUMN rides.elevation_correction_reason IS
    'Why the correction abstained (insufficient_dem_coverage, missing_route, dem_grid_missing).';
COMMENT ON COLUMN rides.elevation_corrected_gain_m IS
    'Trustworthy DEM-corrected climbing total in meters. NULL = no trustworthy value (clients render a dash, never zero).';
COMMENT ON COLUMN rides.elevation_correction_profile IS
    'Delta-encoded corrected elevation per gps_track point (decimeters, br profile v1). Internal storage for the /gps relief projection.';
