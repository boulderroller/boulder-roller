-- Authoritative ride metrics evidence and parser V3 provenance.
--
-- Historical rides remain nullable. New live processing persists the exact
-- metrics engine, moving time, and sensor coverage used by effort policy.
-- Parser V3 becomes the sole active immutable pipeline vector; V1/V2 rows
-- remain available for replay and historical ride-economic plans.

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS moving_time_sec INTEGER,
    ADD COLUMN IF NOT EXISTS metrics_version TEXT,
    ADD COLUMN IF NOT EXISTS power_sample_count INTEGER,
    ADD COLUMN IF NOT EXISTS power_sample_coverage_bps INTEGER,
    ADD COLUMN IF NOT EXISTS heart_rate_sample_count INTEGER,
    ADD COLUMN IF NOT EXISTS heart_rate_sample_coverage_bps INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_moving_time_sec_nonnegative'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_moving_time_sec_nonnegative
            CHECK (moving_time_sec IS NULL OR moving_time_sec >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_power_sample_count_nonnegative'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_power_sample_count_nonnegative
            CHECK (power_sample_count IS NULL OR power_sample_count >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_power_sample_coverage_bps_range'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_power_sample_coverage_bps_range
            CHECK (
                power_sample_coverage_bps IS NULL
                OR power_sample_coverage_bps BETWEEN 0 AND 10000
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_heart_rate_sample_count_nonnegative'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_heart_rate_sample_count_nonnegative
            CHECK (heart_rate_sample_count IS NULL OR heart_rate_sample_count >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.rides'::regclass
          AND conname = 'rides_heart_rate_sample_coverage_bps_range'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_heart_rate_sample_coverage_bps_range
            CHECK (
                heart_rate_sample_coverage_bps IS NULL
                OR heart_rate_sample_coverage_bps BETWEEN 0 AND 10000
            );
    END IF;
END;
$$;
COMMENT ON COLUMN public.rides.moving_time_sec IS
    'Timestamp-derived continuous riding seconds used by authoritative ride metrics.';
COMMENT ON COLUMN public.rides.metrics_version IS
    'Versioned metrics engine identifier. NULL for rides processed before authoritative metrics versioning.';
COMMENT ON COLUMN public.rides.power_sample_count IS
    'Recorded power samples retained by the authoritative metrics engine, including explicit zero watts.';
COMMENT ON COLUMN public.rides.power_sample_coverage_bps IS
    'Power sample coverage over authoritative moving time in basis points, constrained to 0..10000.';
COMMENT ON COLUMN public.rides.heart_rate_sample_count IS
    'Recorded heart-rate samples retained by the authoritative metrics engine.';
COMMENT ON COLUMN public.rides.heart_rate_sample_coverage_bps IS
    'Heart-rate sample coverage over authoritative moving time in basis points, constrained to 0..10000.';

DO $$
DECLARE
    v_template public.pipeline_versions%ROWTYPE;
    v_existing public.pipeline_versions%ROWTYPE;
    v_conflict_count INTEGER;
    v_v3_id INTEGER;
BEGIN
    SELECT count(*) INTO v_conflict_count
    FROM public.pipeline_versions
    WHERE parser_version = '3'
       OR ride_parser_version = 3;

    IF v_conflict_count > 1 THEN
        RAISE EXCEPTION
            'authoritative metrics V3 provenance conflict: multiple parser V3 rows exist';
    END IF;

    SELECT * INTO v_existing
    FROM public.pipeline_versions
    WHERE parser_version = '3'
       OR ride_parser_version = 3
    ORDER BY id DESC
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.parser_version IS DISTINCT FROM '3'
           OR v_existing.ride_parser_version IS DISTINCT FROM 3
           OR v_existing.policy_version IS DISTINCT FROM 'ride_effort_policy_2026_07_14'
           OR v_existing.economics_version IS DISTINCT FROM 'ride_effort_policy_2026_07_14'
           OR btrim(v_existing.git_commit) IS DISTINCT FROM '5d4c2c2eb150115a9b2deb771e7bcde2e199f3c7' THEN
            RAISE EXCEPTION
                'authoritative metrics V3 provenance conflict: existing parser V3 vector differs';
        END IF;

        IF v_existing.deactivated_at IS NOT NULL THEN
            RAISE EXCEPTION
                'authoritative metrics V3 pipeline version is inactive and cannot be reactivated';
        END IF;

        v_v3_id := v_existing.id;
    ELSE
        SELECT * INTO v_template
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY activated_at DESC, id DESC
        LIMIT 1;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'cannot register authoritative metrics V3 without an active pipeline vector template';
        END IF;

        UPDATE public.pipeline_versions
        SET deactivated_at = now()
        WHERE deactivated_at IS NULL;

        INSERT INTO public.pipeline_versions (
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
            deactivated_at,
            notes,
            ride_parser_version,
            policy_version
        ) VALUES (
            '3',
            v_template.detector_algorithm,
            v_template.detector_version,
            v_template.detector_params_hash,
            v_template.sig_format_version,
            v_template.sig_match_version,
            'ride_effort_policy_2026_07_14',
            v_template.integrity_version,
            '5d4c2c2eb150115a9b2deb771e7bcde2e199f3c7',
            now(),
            NULL,
            'Parser semantic V3 with workout_parse_metrics_v1 as the sole rewardable TSS/CAL metrics engine.',
            3,
            'ride_effort_policy_2026_07_14'
        )
        RETURNING id INTO v_v3_id;
    END IF;

    UPDATE public.pipeline_versions
    SET deactivated_at = now()
    WHERE deactivated_at IS NULL AND id <> v_v3_id;
END;
$$;
