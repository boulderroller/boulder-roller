-- Persist source provenance for reconstructed/imported ride files.
--
-- Strava imports are reconstructed from API streams into GPX because Strava's
-- public API does not expose the original FIT/GPX/TCX export. These columns
-- keep that distinction visible to the attestation/read layers instead of
-- laundering reconstructed stream data into an indistinguishable native GPX.

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS import_source TEXT,
    ADD COLUMN IF NOT EXISTS import_source_id TEXT,
    ADD COLUMN IF NOT EXISTS import_diagnostics JSONB;

CREATE INDEX IF NOT EXISTS idx_rides_import_source
    ON rides(import_source)
    WHERE import_source IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rides_import_source_id
    ON rides(import_source, import_source_id)
    WHERE import_source_id IS NOT NULL;

COMMENT ON COLUMN rides.import_source IS
    'Original import/source adapter that produced the stored ride file, e.g. strava_stream_reconstructed_gpx.';
COMMENT ON COLUMN rides.import_source_id IS
    'Source-system identifier for the imported ride, e.g. Strava activity ID.';
COMMENT ON COLUMN rides.import_diagnostics IS
    'Structured source-fidelity diagnostics such as stream counts, sampling gaps, coverage, quality tier, and flags.';
