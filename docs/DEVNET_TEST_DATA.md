# Devnet Test Data

Reference for test accounts, vaults, and data used for development and demo purposes.

## Network Configuration

**Network:** Solana Devnet
**RPC:** `https://api.devnet.solana.com`

## Program IDs

| Program | ID |
|---------|-----|
| boulder_rollers | `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH` |
| CAL mint | `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh` |
| DUNG mint | `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk` |
| *(archived)* dung_mint program | `A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ` |
| *(archived)* proof_verifier | `Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC` |

## Backend Fee Payer Keypair

The backend fee payer pays SOL fees and rent only. It has no ProgramConfig or
program upgrade authority. See `docs/security/KEY_MAP.md` for the full role map.

**Local path:** `~/.config/solana/boulderroller-fee-payer.json`
**Env var:** `SOLANA_PAYER_SECRET` (JSON array of bytes)

To get devnet SOL for the payer:
```bash
solana airdrop 2 --url devnet $(solana-keygen pubkey ~/.config/solana/boulderroller-fee-payer.json)
```

## Test Vaults

> **TODO:** Create these vaults using Anchor tests or admin scripts.
> Update this section with actual vault data after creation.

### Planned Test Vaults

| Name | Signature (first 16 bytes) | Vert (m) | Dist (m) | Purpose |
|------|---------------------------|----------|----------|---------|
| Demo Climb Alpha | `TBD` | 150 | 2000 | Primary demo vault |
| Demo Climb Beta | `TBD` | 300 | 5000 | Secondary demo vault |
| Demo Climb Gamma | `TBD` | 500 | 8000 | High-stakes demo vault |

### Creating Test Vaults

Using Anchor tests:
```bash
cd protocol/anchor
anchor test --skip-local-validator
```

Or via backend admin (requires admin JWT):
```bash
curl -X POST https://api.boulderroller.xyz/vaults \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Climb Alpha",
    "signature_hex": "...",
    "vert_m": 150,
    "distance_m": 2000,
    "avg_gradient_pct": 7.5
  }'
```

## Test Wallets

| Purpose | Pubkey | Notes |
|---------|--------|-------|
| Test User 1 | `TBD` | Has CAL balance, stakes |
| Test User 2 | `TBD` | Leaderboard entries |
| Test User 3 | `TBD` | Local Legend candidate |
| POL Account | `TBD` | Protocol-owned liquidity |
| Treasury | `TBD` | Protocol treasury |

### Creating Test Wallets

```bash
# Generate a new test wallet
solana-keygen new --outfile ~/.config/solana/test-user-1.json

# Fund with devnet SOL
solana airdrop 2 --url devnet $(solana-keygen pubkey ~/.config/solana/test-user-1.json)
```

## Test Scenarios

### Scenario 1: Basic Ride → CAL Flow

1. Upload a FIT file for test user
2. Verify ride processed (check `/rides/{id}/status`)
3. Confirm CAL earned (check `/cal/onchain`)
4. Verify climb patterns detected

### Scenario 2: Vault Staking Flow

1. Test user stakes CAL in Demo Climb Alpha
2. Verify stake recorded in DB and on-chain
3. Check LP token balance

### Scenario 3: Epoch Distribution

1. Ensure vault has >= 1000 CAL tribute
2. Wait for epoch change OR trigger manually
3. Verify distribution queued
4. Verify receipts created
5. Verify DUNG distributed to leaderboard/stakers/legend

### Scenario 4: Harvest Flow

1. After epoch distribution, check pending rewards
2. Call harvest endpoint
3. Verify DUNG received
4. Verify 5% fee deducted

## Running Test Script

```bash
# Check current epoch status
python scripts/test_epoch_distribution.py status

# Check with admin details
python scripts/test_epoch_distribution.py status --token $ADMIN_TOKEN

# Dry run analysis (direct DB)
python scripts/test_epoch_distribution.py dry-run

# Trigger epoch processing
python scripts/test_epoch_distribution.py trigger --token $ADMIN_TOKEN

# Use staging API
python scripts/test_epoch_distribution.py status --staging
```

## Database Tables for Testing

### Quick Queries

```sql
-- Check epoch state
SELECT * FROM epoch_state;

-- Pending distributions
SELECT * FROM epoch_distributions WHERE status = 'pending';

-- Recent completions
SELECT * FROM vault_completions ORDER BY created_at DESC LIMIT 10;

-- Vault CAL balances
SELECT id, name, cal_tribute_accumulated
FROM indexed_vaults
WHERE cal_tribute_accumulated > 0
ORDER BY cal_tribute_accumulated DESC;

-- User CAL balances (on-chain — query via Solana RPC or indexed_user_states)
-- Note: wallet_points table removed April 2026 (migration 089)
```

### Reset Test Data

```sql
-- Clear pending distributions (careful!)
DELETE FROM epoch_distributions WHERE status = 'pending';

-- Reset vault CAL (for re-testing)
UPDATE indexed_vaults SET cal_tribute_accumulated = 0 WHERE name LIKE 'Demo%';
```

## Environment Variables

Required for test scripts:

```bash
export SUPABASE_URL="https://db.qzkqjevawthyboymqrle.supabase.co"
export SUPABASE_SERVICE_KEY="your-service-key"
export API_BASE="http://localhost:8000"  # or staging URL
```

## Troubleshooting

### "Vault not found" errors
- Check `indexed_vaults` table has the vault
- Verify vault indexer is running (`/health` shows vault count)
- Check vault signature format (128 hex chars)

### Epoch not transitioning
- Check `epoch_state` table for stored epoch
- Compare with current epoch from `get_current_epoch()`
- Verify epoch processor background task is running

### CAL not allocated
- Verify `economic_events` has entry for the operation
- Check `CAL_ALLOCATION_MODE` env var (should be `batch` or `live`)
- Check for errors in backend logs
- Note: `points_config`, `points_events`, `wallet_points` tables removed April 2026

### On-chain calls failing
- Verify `SOLANA_PAYER_SECRET` is set
- Check payer has SOL balance
- Confirm program IDs match deployed programs
- Check RPC endpoint is responsive
