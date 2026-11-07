-- Persist user-supplied photos attached to ride activity records.

CREATE TABLE IF NOT EXISTS public.ride_media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL REFERENCES public.rides(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL UNIQUE,
    file_name TEXT,
    mime_type TEXT NOT NULL CHECK (mime_type LIKE 'image/%'),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 15728640),
    width INTEGER,
    height INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'photo' CHECK (role IN ('photo', 'cover')),
    upload_status TEXT NOT NULL DEFAULT 'uploading'
        CHECK (upload_status IN ('uploading', 'ready', 'failed')),
    moderation_state TEXT NOT NULL DEFAULT 'visible'
        CHECK (moderation_state IN ('visible', 'pending', 'hidden', 'removed')),
    moderated_at TIMESTAMPTZ,
    moderated_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    moderation_report_id UUID REFERENCES public.social_reports(id) ON DELETE SET NULL,
    moderation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ride_media_ride_display
ON public.ride_media (ride_id, upload_status, moderation_state, sort_order, created_at);

CREATE INDEX IF NOT EXISTS idx_ride_media_user
ON public.ride_media (user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ride_media_one_cover_per_ride
ON public.ride_media (ride_id)
WHERE role = 'cover' AND upload_status = 'ready' AND moderation_state = 'visible';

COMMENT ON TABLE public.ride_media IS
'User-supplied image media attached to ride activity records.';

COMMENT ON COLUMN public.ride_media.storage_path IS
'Path in the private ride upload storage bucket. Clients receive short-lived signed URLs, not durable public URLs.';

COMMENT ON COLUMN public.ride_media.upload_status IS
'Direct upload lifecycle. Only ready media is returned in public ride/feed contracts.';
