-- Token transaction history and harvest events
ALTER TABLE epochs
    ADD COLUMN IF NOT EXISTS rewards_per_lp NUMERIC;

ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS last_harvest_epoch BIGINT DEFAULT 0;

CREATE TABLE IF NOT EXISTS harvest_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    segment_id UUID NOT NULL REFERENCES segments(id),
    epoch_number BIGINT NOT NULL,
    lp_tokens_held NUMERIC NOT NULL,
    dung_harvested NUMERIC NOT NULL,
    tx_signature VARCHAR(128),
    harvested_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS token_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    tx_type VARCHAR(50) NOT NULL,
    token_type VARCHAR(10) NOT NULL,
    amount NUMERIC NOT NULL,
    balance_after NUMERIC,
    reference_type VARCHAR(50),
    reference_id UUID,
    tx_signature VARCHAR(128),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tx_user ON token_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_tx_created ON token_transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_type ON token_transactions(tx_type);
