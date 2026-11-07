-- 025_beetle_cards.sql
-- Beetle Cards: Soulbound effort NFTs tracking cumulative progress
--
-- Card Types:
-- - ClimbBeetle: Scoped per Arena (scope_id = arena UUID)
-- - SteadyBeetle: Global scope (scope_id = GLOBAL_SCOPE)
-- - ExplorerBeetle: Global scope (scope_id = GLOBAL_SCOPE)

-- Global scope constant (matches Solana program GLOBAL_SCOPE)
-- Steady and Explorer beetles use this as scope_id

-- Beetle Cards table (off-chain tracking, synced to Solana PDAs)
CREATE TABLE IF NOT EXISTS beetle_cards (
    id UUID PRIMARY KEY,
    wallet TEXT NOT NULL,
    card_type TEXT NOT NULL CHECK (card_type IN ('CLIMB', 'STEADY', 'EXPLORATION')),
    -- Scope ID:
    -- - For CLIMB: arena UUID
    -- - For STEADY/EXPLORATION: '00000000-0000-0000-0000-000000000000' (global)
    scope_id TEXT NOT NULL,
    score BIGINT NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 0 CHECK (level >= 0 AND level <= 10),
    patterns_scored INTEGER NOT NULL DEFAULT 0,
    -- On-chain PDA address (populated when synced to Solana)
    onchain_pda TEXT,
    -- Last sync timestamp (NULL if never synced)
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- One card per wallet/type/scope combination
    UNIQUE (wallet, card_type, scope_id)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_beetle_cards_wallet ON beetle_cards(wallet);
CREATE INDEX IF NOT EXISTS idx_beetle_cards_type ON beetle_cards(card_type);
CREATE INDEX IF NOT EXISTS idx_beetle_cards_scope ON beetle_cards(scope_id);
CREATE INDEX IF NOT EXISTS idx_beetle_cards_level ON beetle_cards(level DESC);
CREATE INDEX IF NOT EXISTS idx_beetle_cards_score ON beetle_cards(score DESC);

-- Beetle Card level-up history (for tracking progression)
CREATE TABLE IF NOT EXISTS beetle_card_level_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    beetle_card_id UUID NOT NULL REFERENCES beetle_cards(id) ON DELETE CASCADE,
    old_level INTEGER NOT NULL,
    new_level INTEGER NOT NULL,
    score_at_levelup BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_beetle_level_history_card ON beetle_card_level_history(beetle_card_id);

-- Beetle Card leaderboard view (global rankings by level and score)
CREATE OR REPLACE VIEW beetle_card_leaderboard AS
SELECT
    bc.id,
    bc.wallet,
    bc.card_type,
    bc.scope_id,
    bc.score,
    bc.level,
    bc.patterns_scored,
    bc.created_at,
    -- Rank within card type
    RANK() OVER (
        PARTITION BY bc.card_type, bc.scope_id
        ORDER BY bc.level DESC, bc.score DESC
    ) as rank,
    -- Arena name for climb beetles
    a.name as arena_name
FROM beetle_cards bc
LEFT JOIN arenas a ON bc.scope_id = a.id::text AND bc.card_type = 'CLIMB';

-- RLS Policies
ALTER TABLE beetle_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE beetle_card_level_history ENABLE ROW LEVEL SECURITY;

-- Anyone can read beetle cards (public leaderboard)
CREATE POLICY beetle_cards_select ON beetle_cards
    FOR SELECT USING (true);

-- Only system can insert/update beetle cards
CREATE POLICY beetle_cards_insert ON beetle_cards
    FOR INSERT WITH CHECK (false);

CREATE POLICY beetle_cards_update ON beetle_cards
    FOR UPDATE USING (false);

-- Level history is read-only for users
CREATE POLICY beetle_level_history_select ON beetle_card_level_history
    FOR SELECT USING (true);

-- Add comment for documentation
COMMENT ON TABLE beetle_cards IS 'Soulbound Beetle Cards tracking cumulative effort (off-chain mirror of Solana PDAs)';
COMMENT ON COLUMN beetle_cards.scope_id IS 'Arena UUID for CLIMB, GLOBAL_SCOPE (all zeros) for STEADY/EXPLORATION';
COMMENT ON COLUMN beetle_cards.level IS 'Level 0-10 based on score thresholds';
COMMENT ON COLUMN beetle_cards.onchain_pda IS 'Solana PDA address when synced on-chain';
