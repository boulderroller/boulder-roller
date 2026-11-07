-- Read-only. Run after photo writes are quiesced and signed uploads expire.
-- psql -XAt -f scripts/photo_metadata_manifest.sql > reviewed-photos.json
WITH refs AS (
    SELECT storage_path AS path, mime_type,
        jsonb_build_object('table', 'ride_media', 'id', id, 'path_column', 'storage_path',
            'metadata', jsonb_build_object('width', width, 'height', height,
                'size_bytes', size_bytes, 'mime_type', mime_type)) AS ref
    FROM public.ride_media WHERE storage_path IS NOT NULL
    UNION ALL
    SELECT avatar_storage_path, avatar_mime_type,
        jsonb_build_object('table', 'users', 'id', id, 'path_column', 'avatar_storage_path',
            'metadata', jsonb_build_object('avatar_size_bytes', avatar_size_bytes,
                'avatar_mime_type', avatar_mime_type))
    FROM public.users WHERE avatar_storage_path IS NOT NULL
    UNION ALL
    SELECT avatar_pending_storage_path, avatar_pending_mime_type,
        jsonb_build_object('table', 'users', 'id', id, 'path_column', 'avatar_pending_storage_path',
            'metadata', jsonb_build_object('avatar_pending_size_bytes', avatar_pending_size_bytes,
                'avatar_pending_mime_type', avatar_pending_mime_type))
    FROM public.users WHERE avatar_pending_storage_path IS NOT NULL
), objects AS (
    SELECT path, min(mime_type) AS mime_type, jsonb_agg(ref) AS refs FROM refs GROUP BY path
)
SELECT coalesce(jsonb_agg(jsonb_build_object('path', path, 'mime_type', mime_type,
    'references', refs) ORDER BY path), '[]'::jsonb) FROM objects;
-- This selects referenced active/pending photos. Inventory orphan objects and
-- cleanup-only paths separately, review their storage Content-Type and append
-- exact photo paths with references: []; never infer a MIME type from a suffix.
