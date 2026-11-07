-- Canonical auth identities for deterministic wallet/Privy linking.
-- Supports one user model across wallet-first and Privy-first logins.

CREATE TABLE IF NOT EXISTS auth_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('wallet', 'privy')),
    provider_subject TEXT NOT NULL,
    wallet TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider, provider_subject)
);

CREATE INDEX IF NOT EXISTS idx_auth_identities_user_id ON auth_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_identities_provider_user_id ON auth_identities(provider, user_id);

-- Backfill wallet identities for existing users to make lookup deterministic.
INSERT INTO auth_identities (user_id, provider, provider_subject, wallet)
SELECT u.id, 'wallet', u.wallet, u.wallet
FROM users u
WHERE u.wallet IS NOT NULL AND u.wallet <> ''
ON CONFLICT (provider, provider_subject) DO NOTHING;

COMMENT ON TABLE auth_identities IS 'Canonical identity mapping across wallet and Privy providers.';
COMMENT ON COLUMN auth_identities.provider_subject IS 'Provider-specific stable subject (wallet address for wallet provider, Privy sub claim for Privy provider).';
