-- Extend moderation/reporting and cleanup support to ride media.

ALTER TABLE public.social_reports
    DROP CONSTRAINT IF EXISTS social_reports_target_type_check;

ALTER TABLE public.social_reports
    ADD CONSTRAINT social_reports_target_type_check
    CHECK (target_type IN ('ride', 'comment', 'user', 'ride_media'));

ALTER TABLE public.ride_media
    ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS moderated_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_report_id UUID REFERENCES public.social_reports(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderation_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_ride_media_cleanup
ON public.ride_media (upload_status, updated_at)
WHERE upload_status IN ('uploading', 'failed');
