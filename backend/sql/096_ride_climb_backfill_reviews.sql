-- Persist ride-level climb backfill outcomes.
--
-- Some high-gain rides legitimately produce no canonical climb rows, or cannot
-- be replayed because the stored ride has no usable GPS track. Since those
-- cases have no patterns_climb row to annotate, keep a ride-level review record
-- so the high-gain zero-climb selector does not repeatedly reprocess reviewed
-- terminal outcomes.

CREATE TABLE IF NOT EXISTS ride_climb_backfill_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
    detector_algorithm TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN (
            'no_canonical_climb',
            'missing_gps_track',
            'gps_decode_failed',
            'tile_projection_failed'
        )
    ),
    status TEXT NOT NULL DEFAULT 'reviewed' CHECK (
        status IN ('reviewed', 'reopened')
    ),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (activity_id, detector_algorithm)
);

CREATE INDEX IF NOT EXISTS idx_ride_climb_backfill_reviews_terminal
    ON ride_climb_backfill_reviews(activity_id, detector_algorithm, outcome)
    WHERE status = 'reviewed';

COMMENT ON TABLE ride_climb_backfill_reviews IS
    'Ride-level audit outcomes for climb backfill attempts that have no patterns_climb row to annotate.';
COMMENT ON COLUMN ride_climb_backfill_reviews.outcome IS
    'Terminal climb backfill outcome, such as no_canonical_climb or missing_gps_track.';
COMMENT ON COLUMN ride_climb_backfill_reviews.details IS
    'Structured evidence from the backfill attempt, including GPS/tile counts and detector algorithm.';
