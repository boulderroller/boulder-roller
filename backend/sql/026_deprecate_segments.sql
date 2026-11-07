-- 026_deprecate_segments.sql
-- Deprecation of segment infrastructure in favor of pattern-based system
--
-- This migration marks segment-related tables as deprecated.
-- The tables are NOT dropped to preserve existing staking relationships,
-- but new segment creation should be prevented.
--
-- New Architecture:
-- - Pattern detection replaces segment matching
-- - Arenas replace geographic segment boundaries
-- - Beetle Cards track effort history instead of segment leaderboards
-- - CAL gates scoring, not segment participation

-- Add deprecation marker to segments table
COMMENT ON TABLE segments IS 'DEPRECATED: Use patterns_* tables instead. Kept for backwards compatibility with existing staking.';

-- Add deprecation marker to segment_efforts table
COMMENT ON TABLE segment_efforts IS 'DEPRECATED: Use scored_patterns table instead. Kept for backwards compatibility.';

-- Prevent new segment creation by adding a check constraint
-- (This allows existing segments to remain but prevents new ones)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'no_new_segments'
    ) THEN
        -- Add a trigger to prevent new segment insertion
        CREATE OR REPLACE FUNCTION prevent_new_segments()
        RETURNS TRIGGER AS $trigger$
        BEGIN
            RAISE EXCEPTION 'Segment creation is deprecated. Use pattern-based system instead.';
        END;
        $trigger$ LANGUAGE plpgsql;

        -- Only create trigger if it doesn't exist
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger WHERE tgname = 'no_new_segments_trigger'
        ) THEN
            CREATE TRIGGER no_new_segments_trigger
                BEFORE INSERT ON segments
                FOR EACH ROW
                EXECUTE FUNCTION prevent_new_segments();
        END IF;
    END IF;
END $$;

-- Create view mapping old segment concepts to new pattern concepts
CREATE OR REPLACE VIEW deprecated_segment_to_pattern_mapping AS
SELECT
    'segments' as old_table,
    'arenas + patterns_*' as new_tables,
    'Geographic boundaries are now Arenas; segment efforts are now Patterns' as migration_note
UNION ALL
SELECT
    'segment_efforts',
    'scored_patterns',
    'Segment times are replaced by pattern scoring with CAL/DUNG'
UNION ALL
SELECT
    'segment leaderboards',
    'beetle_card_leaderboard + leaderboard endpoints',
    'Per-segment leaderboards replaced by effort-based pattern leaderboards';

-- Add index comment for documentation
COMMENT ON VIEW deprecated_segment_to_pattern_mapping IS 'Reference mapping from deprecated segment tables to new pattern-based architecture';
