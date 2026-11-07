-- Make founder bootstrap Local Legend state explicit in the indexer projection.
-- Existing V3/V4 rows used election_period=0 and completions_at_election=0 as
-- a bootstrap sentinel; keep that backfill so current devnet rows remain legible.

ALTER TABLE indexed_legends
    ADD COLUMN IF NOT EXISTS is_bootstrap BOOLEAN NOT NULL DEFAULT false;

UPDATE indexed_legends
SET is_bootstrap = true
WHERE election_period = 0
  AND completions_at_election = 0
  AND is_active = true;

COMMENT ON COLUMN indexed_legends.is_bootstrap IS
    'True when the Local Legend seat is the founder bootstrap stint rather than an elected recent-participation win.';
