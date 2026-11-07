-- Atomic ride media lifecycle transitions for the one-cover invariant.

CREATE OR REPLACE FUNCTION public.complete_ride_media_upload(
    p_media_id UUID,
    p_ride_id UUID,
    p_size_bytes INTEGER DEFAULT NULL
)
RETURNS SETOF public.ride_media
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    target_role TEXT;
BEGIN
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
        size_bytes = COALESCE(p_size_bytes, size_bytes),
        sort_order = CASE WHEN target_role = 'cover' THEN 0 ELSE sort_order END,
        updated_at = NOW()
    WHERE id = p_media_id
      AND ride_id = p_ride_id
      AND upload_status = 'uploading'
    RETURNING *;
END;
$$;

CREATE OR REPLACE FUNCTION public.set_ride_media_cover(
    p_ride_id UUID,
    p_media_id UUID
)
RETURNS SETOF public.ride_media
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    -- Serialize manual cover changes with upload completion for the same ride.
    PERFORM 1
    FROM public.ride_media
    WHERE ride_id = p_ride_id
    FOR UPDATE;

    UPDATE public.ride_media
    SET role = 'photo',
        updated_at = NOW()
    WHERE ride_id = p_ride_id
      AND id <> p_media_id
      AND role = 'cover'
      AND upload_status = 'ready'
      AND moderation_state = 'visible';

    RETURN QUERY
    UPDATE public.ride_media
    SET role = 'cover',
        sort_order = 0,
        updated_at = NOW()
    WHERE id = p_media_id
      AND ride_id = p_ride_id
      AND upload_status = 'ready'
      AND moderation_state = 'visible'
    RETURNING *;
END;
$$;
