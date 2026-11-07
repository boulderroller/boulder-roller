SET LOCAL lock_timeout = '5s';

-- A successful replacement retains the previous object until verified cleanup.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS avatar_cleanup_storage_paths TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- Freeze both photo lifecycle paths in the existing deletion/receipt authority.
CREATE OR REPLACE FUNCTION public.br_account_deletion_storage_paths(p_user_id UUID)
RETURNS TEXT[]
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = ''
AS $$
DECLARE
    v_paths TEXT[];
    v_optional_paths TEXT[];
BEGIN
    SELECT pg_catalog.array_remove(
        ARRAY[u.avatar_storage_path, u.avatar_pending_storage_path] || u.avatar_cleanup_storage_paths, NULL
    ) INTO v_paths FROM public.users u WHERE u.id = p_user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account_deletion_user_unavailable' USING ERRCODE = '55000';
    END IF;

    SELECT COALESCE(pg_catalog.array_agg(raw_file_path) FILTER (WHERE raw_file_path IS NOT NULL), ARRAY[]::TEXT[])
    INTO v_optional_paths FROM public.rides WHERE user_id = p_user_id;
    v_paths := v_paths || v_optional_paths;
    IF pg_catalog.to_regclass('public.ride_media') IS NOT NULL THEN
        EXECUTE 'SELECT COALESCE(array_agg(storage_path), ARRAY[]::TEXT[]) FROM public.ride_media WHERE user_id = $1'
        INTO v_optional_paths USING p_user_id;
        v_paths := v_paths || v_optional_paths;
    END IF;

    RETURN ARRAY(
        SELECT DISTINCT path FROM (
            SELECT path FROM pg_catalog.unnest(v_paths) stored(path)
            UNION ALL
            SELECT CASE WHEN path LIKE 'sanitized/avatars/%' OR path LIKE 'sanitized/ride-media/%'
                THEN pg_catalog.substr(path, 11) ELSE 'sanitized/' || path END
            FROM pg_catalog.unnest(v_paths) stored(path)
            WHERE path LIKE 'avatars/%' OR path LIKE 'ride-media/%'
               OR path LIKE 'sanitized/avatars/%' OR path LIKE 'sanitized/ride-media/%'
        ) paired WHERE path IS NOT NULL AND path <> '' ORDER BY path
    );
END;
$$;
REVOKE ALL ON FUNCTION public.br_account_deletion_storage_paths(UUID) FROM PUBLIC, anon, authenticated, service_role;

-- Owner-scoped exports need read access to full Threshold history, not just
-- the current projection. No new writes or client-role grants are admitted.
GRANT SELECT ON public.reward_threshold_efforts,
    public.reward_threshold_candidates,
    public.reward_threshold_source_envelopes,
    public.reward_threshold_ratchets,
    public.reward_threshold_pending_promotions,
    public.vault_creation_handoffs,
    public.ride_effort_completion_windows TO service_role;

-- Publish the server-only object atomically with the existing one-cover rule.
-- The unused legacy repository caller was removed; all routes sanitize first.
DROP FUNCTION IF EXISTS public.complete_ride_media_upload(UUID, UUID, INTEGER);
-- Remove the superseded six-argument sanitizer overload if a prior draft ran.
DROP FUNCTION IF EXISTS public.complete_sanitized_ride_media_upload(UUID, UUID, INTEGER, TEXT, INTEGER, INTEGER);
CREATE OR REPLACE FUNCTION public.complete_sanitized_ride_media_upload(
    p_media_id UUID,
    p_ride_id UUID,
    p_size_bytes INTEGER,
    p_storage_path TEXT,
    p_width INTEGER,
    p_height INTEGER,
    p_mime_type TEXT DEFAULT NULL
)
RETURNS SETOF public.ride_media
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    target_role TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.ride_media
        WHERE id = p_media_id AND ride_id = p_ride_id
          AND upload_status = 'uploading'
          AND p_storage_path = 'sanitized/' || storage_path
          AND (p_mime_type IS NULL OR p_mime_type IN ('image/jpeg', 'image/png', 'image/webp'))
    ) THEN
        RETURN;
    END IF;

    -- Serialize cover changes for this ride before the partial unique index sees them.
    PERFORM 1
    FROM public.ride_media
    WHERE ride_id = p_ride_id
    FOR UPDATE;

    SELECT role
    INTO target_role
    FROM public.ride_media
    WHERE id = p_media_id
      AND ride_id = p_ride_id
      AND upload_status = 'uploading'
      AND p_storage_path = 'sanitized/' || storage_path
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    IF target_role = 'cover' THEN
        UPDATE public.ride_media
        SET role = 'photo',
            updated_at = NOW()
        WHERE ride_id = p_ride_id
          AND id <> p_media_id
          AND role = 'cover'
          AND upload_status = 'ready'
          AND moderation_state = 'visible';
    END IF;

    RETURN QUERY
    UPDATE public.ride_media
    SET upload_status = 'ready',
        storage_path = p_storage_path,
        width = p_width,
        height = p_height,
        mime_type = COALESCE(p_mime_type, mime_type),
        size_bytes = COALESCE(p_size_bytes, size_bytes),
        sort_order = CASE WHEN target_role = 'cover' THEN 0 ELSE sort_order END,
        updated_at = NOW()
    WHERE id = p_media_id
      AND ride_id = p_ride_id
      AND upload_status = 'uploading'
      AND p_storage_path = 'sanitized/' || storage_path
    RETURNING *;
END;
$$;

REVOKE ALL ON FUNCTION public.complete_sanitized_ride_media_upload(UUID, UUID, INTEGER, TEXT, INTEGER, INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.complete_sanitized_ride_media_upload(UUID, UUID, INTEGER, TEXT, INTEGER, INTEGER, TEXT)
    TO service_role;
