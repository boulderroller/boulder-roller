-- 148: rider-visible ride title (boulderroller-v2-g0o24)
--
-- Historically the API served rides.file_name as the title and rider edits
-- were written back into file_name, conflating the original upload filename
-- with a rider-authored name. This adds a real title column:
--   * processing sets it (only when NULL) to the ratified default shape
--     ("{place} Ride" / "{time-of-day} Ride"),
--   * PATCH /rides/{id} edits land here and stop clobbering file_name,
--   * NULL means untitled legacy — the API falls back to file_name and
--     clients keep their legacy-null fallback. No backfill by design: rider
--     edits made before this column are indistinguishable from filenames.

ALTER TABLE rides ADD COLUMN IF NOT EXISTS title TEXT;

COMMENT ON COLUMN rides.title IS
    'Rider-visible ride title. NULL = untitled legacy ride (API falls back to file_name). Set at processing when absent using the ratified default shape; rider-editable afterwards.';
