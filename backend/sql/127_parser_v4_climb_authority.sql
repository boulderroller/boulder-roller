-- Parser V4 provenance for authoritative canonical climb matching.
--
-- V4 preserves V3 source parsing and canonical field semantics. The version
-- bump binds newly attested rides to the canonical-v2 reward matching output
-- introduced by aa77d5b7; V1-V3 rows remain immutable replay authorities.

INSERT INTO public.detector_configs (
    algorithm, version, params, params_hash, notes
) VALUES (
    'canonical_v2',
    '2.0.0',
    '{"candidate_ambiguity_policy":"abstain","canonical_signature_smoothing_window_samples":5,"dct_match_coeffs":6,"endpoint_max_distance_m":150,"geometry_tolerance":0.25,"h3_match_max_grid_distance":3,"h3_match_resolution":7,"h3_undefined_policy":"reject","native_match_threshold":0.08,"native_probable_match_threshold":0.15,"null_island_policy":"reject","oriented_endpoints_required":true,"osm_reward_dependency":false,"reward_min_similarity":0.9,"sample_space":"timestamped_finite_elevation_stable_time_order","signature_format_version":2,"v1_reward_fallback":false}'::JSONB,
    'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2',
    'Authoritative canonical-v2 reward matching: oriented endpoints, native geometry/H3/DCT, ambiguity abstention, and no V1 fallback.'
)
ON CONFLICT (params_hash) DO NOTHING;

DO $$
DECLARE
    v_template public.pipeline_versions%ROWTYPE;
    v_existing public.pipeline_versions%ROWTYPE;
    v_conflict_count INTEGER;
    v_v4_id INTEGER;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.detector_configs AS config
        WHERE config.params_hash =
              'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2'
          AND config.algorithm = 'canonical_v2'
          AND config.version = '2.0.0'
          AND config.params =
              '{"candidate_ambiguity_policy":"abstain","canonical_signature_smoothing_window_samples":5,"dct_match_coeffs":6,"endpoint_max_distance_m":150,"geometry_tolerance":0.25,"h3_match_max_grid_distance":3,"h3_match_resolution":7,"h3_undefined_policy":"reject","native_match_threshold":0.08,"native_probable_match_threshold":0.15,"null_island_policy":"reject","oriented_endpoints_required":true,"osm_reward_dependency":false,"reward_min_similarity":0.9,"sample_space":"timestamped_finite_elevation_stable_time_order","signature_format_version":2,"v1_reward_fallback":false}'::JSONB
    ) THEN
        RAISE EXCEPTION 'parser V4 detector configuration provenance conflict';
    END IF;

    SELECT count(*) INTO v_conflict_count
    FROM public.pipeline_versions
    WHERE parser_version = '4-ftp-v1'
       OR ride_parser_version = 4;

    IF v_conflict_count > 1 THEN
        RAISE EXCEPTION 'multiple parser V4 pipeline provenance rows exist';
    END IF;

    SELECT * INTO v_existing
    FROM public.pipeline_versions
    WHERE parser_version = '4-ftp-v1'
       OR ride_parser_version = 4
    ORDER BY id DESC
    LIMIT 1;

    IF FOUND THEN
        IF v_existing.parser_version IS DISTINCT FROM '4-ftp-v1'
           OR v_existing.ride_parser_version IS DISTINCT FROM 4
           OR v_existing.detector_algorithm IS DISTINCT FROM 'canonical_v2'
           OR v_existing.detector_version IS DISTINCT FROM '2.0.0'
           OR v_existing.detector_params_hash IS DISTINCT FROM
              'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2'
           OR v_existing.sig_format_version IS DISTINCT FROM 'v2'
           OR v_existing.sig_match_version IS DISTINCT FROM
              'dct6-h3r7-geometry25-oriented150-sim090'
           OR v_existing.economics_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR v_existing.policy_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR btrim(v_existing.git_commit) IS DISTINCT FROM
              'bb7604ddc0af3f983d0a21191bf27bddfa463e80' THEN
            RAISE EXCEPTION 'parser V4 pipeline provenance conflict';
        END IF;
        IF v_existing.deactivated_at IS NOT NULL THEN
            RAISE EXCEPTION
                'parser V4 pipeline version is inactive and cannot be reactivated';
        END IF;
        v_v4_id := v_existing.id;
    ELSE
        SELECT * INTO v_template
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY activated_at DESC, id DESC
        LIMIT 1;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'cannot register parser V4 without an active pipeline template';
        END IF;
        IF v_template.parser_version IS DISTINCT FROM '3-ftp-v1'
           OR v_template.ride_parser_version IS DISTINCT FROM 3
           OR v_template.economics_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR v_template.policy_version IS DISTINCT FROM
              'ride_effort_policy_2026_07_14_ftp_v1'
           OR btrim(v_template.git_commit) IS DISTINCT FROM
              '9f97a5a92c3987d7d36b617cb01dde50f46f94e4' THEN
            RAISE EXCEPTION 'parser V4 requires the exact active V3 FTP authority';
        END IF;

        UPDATE public.pipeline_versions
        SET deactivated_at = now()
        WHERE deactivated_at IS NULL;

        INSERT INTO public.pipeline_versions (
            parser_version, detector_algorithm, detector_version,
            detector_params_hash, sig_format_version, sig_match_version,
            economics_version, integrity_version, git_commit, activated_at,
            deactivated_at, notes, ride_parser_version, policy_version
        ) VALUES (
            '4-ftp-v1', 'canonical_v2', '2.0.0',
            'a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2',
            'v2', 'dct6-h3r7-geometry25-oriented150-sim090',
            'ride_effort_policy_2026_07_14_ftp_v1',
            v_template.integrity_version,
            'bb7604ddc0af3f983d0a21191bf27bddfa463e80',
            now(), NULL,
            'Parser V4: V3 ride metrics plus authoritative canonical-v2 climb reward matching.',
            4, 'ride_effort_policy_2026_07_14_ftp_v1'
        ) RETURNING id INTO v_v4_id;
    END IF;

    UPDATE public.pipeline_versions
    SET deactivated_at = now()
    WHERE deactivated_at IS NULL AND id <> v_v4_id;
END;
$$;
