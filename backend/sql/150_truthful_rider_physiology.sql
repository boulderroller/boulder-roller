-- 150: truthful FTP/weight profile contract (boulderroller-v2-coq7q)
--
-- Choice A (ratified 2026-08-11 via the derived-FTP direction): the profile
-- API must represent absence and provenance instead of fabricating 200 W /
-- 75 kg. Column defaults were the fabricator: every rider who never opened
-- profile settings carried invented physiology into display surfaces.
--
--   * defaults dropped — new riders start with honest NULL;
--   * per-field source columns record provenance: 'manual' (rider-entered)
--     or 'derived' (future derived-FTP lane, boulderroller-v2-2982);
--   * legacy rows equal to the fabricated defaults reset to NULL. Ratified
--     tradeoff: a rider who genuinely typed exactly 200 W or 75.0 kg before
--     this migration is indistinguishable from the fabricated rows and
--     re-enters the value once;
--   * remaining non-null values were rider-entered (profile settings was the
--     only writer) and are stamped 'manual'.
--
-- Reward FTP (reward_ftp_* on rides) is a separate authority and untouched.

ALTER TABLE users ALTER COLUMN weight_kg DROP DEFAULT;
ALTER TABLE users ALTER COLUMN ftp_w DROP DEFAULT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS weight_kg_source TEXT,
    ADD COLUMN IF NOT EXISTS ftp_w_source TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_weight_kg_source_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_weight_kg_source_check
            CHECK (weight_kg_source IN ('manual', 'derived'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_ftp_w_source_check'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_ftp_w_source_check
            CHECK (ftp_w_source IN ('manual', 'derived'));
    END IF;
END $$;

-- One-time legacy reset: fabricated defaults become honest absence. Guarded
-- on source IS NULL so re-running never clears post-migration manual entries.
UPDATE users SET weight_kg = NULL
    WHERE weight_kg = 75 AND weight_kg_source IS NULL;
UPDATE users SET ftp_w = NULL
    WHERE ftp_w = 200 AND ftp_w_source IS NULL;

-- Surviving values were rider-entered; record that provenance.
UPDATE users SET weight_kg_source = 'manual'
    WHERE weight_kg IS NOT NULL AND weight_kg_source IS NULL;
UPDATE users SET ftp_w_source = 'manual'
    WHERE ftp_w IS NOT NULL AND ftp_w_source IS NULL;

COMMENT ON COLUMN public.users.weight_kg IS
    'Rider weight in kg. NULL = never provided (the API renders absence, never a fabricated default).';
COMMENT ON COLUMN public.users.ftp_w IS
    'Functional Threshold Power in watts. NULL = never provided (the API renders absence, never a fabricated default).';
COMMENT ON COLUMN public.users.weight_kg_source IS
    'Provenance of weight_kg: manual (rider-entered) or derived. NULL when weight_kg is NULL.';
COMMENT ON COLUMN public.users.ftp_w_source IS
    'Provenance of ftp_w: manual (rider-entered) or derived. NULL when ftp_w is NULL.';
