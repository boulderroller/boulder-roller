-- Shadow USDC Tracking
-- During points period, vault creation requires CAL + $2 USDC (spec).
-- USDC plumbing isn't ready yet, so we track "shadow USDC" owed.
-- These can be settled when USDC integration is complete.

CREATE TABLE IF NOT EXISTS vault_shadow_usdc (
    vault_signature CHAR(128) PRIMARY KEY,
    wallet TEXT NOT NULL,
    usdc_owed NUMERIC(10, 2) NOT NULL DEFAULT 2.00,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    settled_at TIMESTAMPTZ  -- NULL until real USDC is paid
);

CREATE INDEX IF NOT EXISTS idx_shadow_usdc_wallet ON vault_shadow_usdc(wallet);
CREATE INDEX IF NOT EXISTS idx_shadow_usdc_unsettled ON vault_shadow_usdc(settled_at) WHERE settled_at IS NULL;

COMMENT ON TABLE vault_shadow_usdc IS 'Track $2 USDC owed for vault creation during points period';
COMMENT ON COLUMN vault_shadow_usdc.settled_at IS 'NULL = unsettled, timestamp = when real USDC was paid';
