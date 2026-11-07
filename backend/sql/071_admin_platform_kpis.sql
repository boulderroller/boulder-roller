-- Migration: 071_admin_platform_kpis.sql
-- Description: Aggregate KPI function for admin platform overview
-- Date: 2026-03-02

-- =============================================================================
-- ADMIN PLATFORM KPIs
-- Single function returning all dashboard metrics in one DB call.
-- Called by GET /admin/platform-overview.
-- =============================================================================

CREATE OR REPLACE FUNCTION admin_platform_kpis()
RETURNS jsonb AS $$
DECLARE
    result jsonb;
BEGIN
    SELECT jsonb_build_object(
        'users', (
            SELECT jsonb_build_object(
                'total', COUNT(*),
                'new_7d', COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days')
            )
            FROM users
        ),
        'rides', (
            SELECT jsonb_build_object(
                'total', COUNT(*),
                'this_week', COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days'),
                'total_tss', COALESCE(SUM(tss), 0),
                'total_distance_m', COALESCE(SUM(distance_m), 0),
                'total_elevation_m', COALESCE(SUM(elevation_gain_m), 0),
                'by_status', (
                    SELECT COALESCE(jsonb_object_agg(
                        COALESCE(processing_status, 'unknown'), cnt
                    ), '{}'::jsonb)
                    FROM (
                        SELECT processing_status, COUNT(*) AS cnt
                        FROM rides
                        GROUP BY processing_status
                    ) s
                )
            )
            FROM rides
        ),
        'vaults', (
            SELECT jsonb_build_object(
                'total', (SELECT COUNT(*) FROM indexed_vaults),
                'total_completions', (SELECT COALESCE(SUM(total_completions), 0) FROM indexed_vaults),
                'total_staked_cal', (
                    SELECT COALESCE(SUM(COALESCE(cal_staked, points_staked)), 0)
                    FROM vault_stakes
                    WHERE unstaked_at IS NULL
                ),
                'unique_stakers', (
                    SELECT COUNT(DISTINCT wallet)
                    FROM vault_stakes
                    WHERE unstaked_at IS NULL
                )
            )
        ),
        'climbs', (
            SELECT jsonb_build_object(
                'total', COUNT(*),
                'scored', COUNT(*) FILTER (WHERE significance_g IS NOT NULL),
                'pct_scored', CASE
                    WHEN COUNT(*) > 0
                    THEN ROUND(
                        COUNT(*) FILTER (WHERE significance_g IS NOT NULL)::numeric
                        / COUNT(*)::numeric * 100, 1
                    )
                    ELSE 0
                END
            )
            FROM patterns_climb
        ),
        'generated_at', to_jsonb(now())
    ) INTO result;

    RETURN result;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION admin_platform_kpis IS
    'Returns all admin dashboard KPIs in a single DB call. Called by /admin/platform-overview.';
