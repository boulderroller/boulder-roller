-- Persist one private-storage-backed avatar per rider profile.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS avatar_storage_path TEXT,
  ADD COLUMN IF NOT EXISTS avatar_mime_type TEXT,
  ADD COLUMN IF NOT EXISTS avatar_size_bytes INTEGER,
  ADD COLUMN IF NOT EXISTS avatar_updated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS avatar_pending_upload_id UUID,
  ADD COLUMN IF NOT EXISTS avatar_pending_storage_path TEXT,
  ADD COLUMN IF NOT EXISTS avatar_pending_file_name TEXT,
  ADD COLUMN IF NOT EXISTS avatar_pending_mime_type TEXT,
  ADD COLUMN IF NOT EXISTS avatar_pending_size_bytes INTEGER,
  ADD COLUMN IF NOT EXISTS avatar_pending_created_at TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_avatar_mime_type'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_avatar_mime_type
      CHECK (
        avatar_mime_type IS NULL
        OR avatar_mime_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif')
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_avatar_size_bytes'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_avatar_size_bytes
      CHECK (
        avatar_size_bytes IS NULL
        OR (avatar_size_bytes > 0 AND avatar_size_bytes <= 15728640)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_avatar_pending_mime_type'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_avatar_pending_mime_type
      CHECK (
        avatar_pending_mime_type IS NULL
        OR avatar_pending_mime_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif')
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_avatar_pending_size_bytes'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_avatar_pending_size_bytes
      CHECK (
        avatar_pending_size_bytes IS NULL
        OR (avatar_pending_size_bytes > 0 AND avatar_pending_size_bytes <= 15728640)
      );
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_avatar_storage_path
ON public.users (avatar_storage_path)
WHERE avatar_storage_path IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_avatar_pending_upload_id
ON public.users (avatar_pending_upload_id)
WHERE avatar_pending_upload_id IS NOT NULL;

COMMENT ON COLUMN public.users.avatar_storage_path IS
'Active rider avatar path in the private ride upload storage bucket. Public contracts receive short-lived signed avatarUrl values.';

COMMENT ON COLUMN public.users.avatar_pending_storage_path IS
'Pending rider avatar upload path. Promoted to avatar_storage_path only after storage existence and size checks pass.';
