-- V2 signature columns on indexed_vaults for DCT-II climb matching.
-- Part of Climb Detection V2 (Phase 2: DCT Signatures).

ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS signature_version INT DEFAULT 1;
ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS signature_v2_hex CHAR(128);

-- Index for v2 lookups (most vaults won't have v2 yet)
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_sig_v2
    ON indexed_vaults (signature_v2_hex)
    WHERE signature_v2_hex IS NOT NULL;

COMMENT ON COLUMN indexed_vaults.signature_version IS 'Signature format version: 1=SHA256+MD5, 2=DCT+BLAKE3';
COMMENT ON COLUMN indexed_vaults.signature_v2_hex IS '128-char hex of 64-byte DCT-II v2 signature (NULL until backfilled)';
