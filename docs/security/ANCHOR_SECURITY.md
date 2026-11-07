# Boulder Rollers Anchor Program Security Documentation

## Overview

This document describes the security architecture of the Boulder Rollers Solana programs, including PDA derivation, authority hierarchy, and access controls.

**Programs:**
- `boulder_rollers` (EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH)
- *(archived)* `dung_mint` (A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ)
- *(archived)* `proof_verifier` (Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC)

---

## PDA Derivation Reference

### Core Account PDAs

| Account | Seeds | Owner | Description |
|---------|-------|-------|-------------|
| UserState | `["user", user_pubkey]` | boulder_rollers | Legacy per-user points-period state and rider stats |
| RiderSoul | `["rider_soul", rider_pubkey]` | boulder_rollers | Lifetime rider identity and attested effort counters |
| RideAttestation | `["ride_attestation", rider_pubkey, ride_hash]` | boulder_rollers | Canonical ride hash and parser-version commitment |
| CalMintReceipt | `["cal_mint_receipt", ride_attestation, rider_pubkey]` | boulder_rollers | Structural replay guard for CAL minting |
| ClimbCompletionReceipt V1 | `["climb_completion_receipt", ride_attestation, vault_pubkey]` | boulder_rollers | Historical identity-only replay guard; new V1 writes fail closed |
| ClimbCompletionReceiptV2 | `["climb_completion_receipt", ride_attestation, vault_pubkey]` | boulder_rollers | Live replay guard storing evidence version, exact tribute, and V2 hash |
| RideTributeBudget | `["ride_tribute_budget", ride_attestation]` | boulder_rollers | Serializes a ride's completion writes and caps aggregate tribute at attested CAL |
| Vault | `["vault", vault_id (u64 le)]` | boulder_rollers | Climb vault with staking pool |
| VaultCounter | `["vault_counter"]` | boulder_rollers | Auto-increment vault ID counter |
| VaultStake | `["vault_stake", user_pubkey, vault_id (u64 le)]` | boulder_rollers | User's stake position in a vault |
| VaultCompletion | `["vault_completion", user_pubkey, vault_id (u64 le)]` | boulder_rollers | User's completion record per vault |
| VaultLeaderboard | `["vault_leaderboard", vault_id (u64 le)]` | boulder_rollers | Top 10 times per vault |
| VaultActivation | `["vault_activation", vault_id (u64 le)]` | boulder_rollers | Settlement activation state for a vault |
| LocalLegend | `["local_legend", vault_id (u64 le)]` | boulder_rollers | Elected curator for a vault |
| BeetleCard | `["beetle_card", user_pubkey, card_type (u8), scope_id]` | boulder_rollers | Soulbound NFT for rider identity |
| VaultLpMint | `["vault_lp", vault_id (u64 le)]` | boulder_rollers | LP token mint per vault |
| VaultCalEscrow | `["vault_cal_escrow", vault_id (u64 le)]` | boulder_rollers | CAL escrow ATA for staking |
| DungMintState | `["dung_mint_state"]` | boulder_rollers | Global DUNG supply cap tracking |

### Mint Authority PDAs (boulder_rollers)

| Account | Seeds | Owner | Description |
|---------|-------|-------|-------------|
| CalMintAuth | `["cal_mint_auth"]` | boulder_rollers | Authority to mint CAL |
| DungMintAuth | `["dung_mint_auth"]` | boulder_rollers | Authority to mint DUNG |

---

## Seed Constants

```rust
// Core seeds
pub const USER_SEED: &[u8] = b"user";
pub const RIDER_SOUL_SEED: &[u8] = b"rider_soul";
pub const RIDE_ATTESTATION_SEED: &[u8] = b"ride_attestation";
pub const CAL_MINT_RECEIPT_SEED: &[u8] = b"cal_mint_receipt";
pub const CLIMB_COMPLETION_RECEIPT_SEED: &[u8] = b"climb_completion_receipt";
pub const RIDE_TRIBUTE_BUDGET_SEED: &[u8] = b"ride_tribute_budget";
pub const VAULT_SEED: &[u8] = b"vault";
pub const VAULT_COUNTER_SEED: &[u8] = b"vault_counter";
pub const VAULT_LP_MINT_SEED: &[u8] = b"vault_lp";
pub const VAULT_COMPLETION_SEED: &[u8] = b"vault_completion";
pub const VAULT_STAKE_SEED: &[u8] = b"vault_stake";
pub const VAULT_LEADERBOARD_SEED: &[u8] = b"vault_leaderboard";
pub const VAULT_ACTIVATION_SEED: &[u8] = b"vault_activation";
pub const LOCAL_LEGEND_SEED: &[u8] = b"local_legend";
pub const BEETLE_CARD_SEED: &[u8] = b"beetle_card";
pub const DUNG_MINT_STATE_SEED: &[u8] = b"dung_mint_state";
pub const VAULT_CAL_ESCROW_SEED: &[u8] = b"vault_cal_escrow";
pub const CAL_MINT_AUTH_SEED: &[u8] = b"cal_mint_auth";
pub const DUNG_MINT_AUTH_SEED: &[u8] = b"dung_mint_auth";

// Legacy seeds (maintained for backwards compatibility)
pub const SEGMENT_SEED: &[u8] = b"segment";
pub const CLAIM_SEED: &[u8] = b"claim";
pub const SWANNY_SEAT_SEED: &[u8] = b"swanny_seat";
pub const COUNTER_SEED: &[u8] = b"counter";
pub const LP_MINT_SEED: &[u8] = b"lp_mint";
pub const ARENA_SEED: &[u8] = b"arena";
pub const EPOCH_SEED: &[u8] = b"epoch";
```

### Completion Evidence Versions

V1 account bytes and hash semantics are frozen for historical decoding. V1
does not contain `cal_tributed`, so it cannot prove an exact amount and cannot
authorize new writes or a non-reject recovery decision.

V2 uses the same PDA seeds with a distinct discriminator and stores
`evidence_version = 2`, `cal_tributed`, and SHA-256 over the domain
`BR_CLIMB_COMPLETION_V2`, RideAttestation pubkey, Vault pubkey, little-endian
`u32` completion time, and little-endian `u64` tribute. The program recomputes
the hash before any economic state mutation.

---

## Authority Hierarchy

### Admin Authority
- **Role:** ProgramConfig administration and maintenance
- **Current devnet pubkey:** `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH`
- **Current devnet file:** `~/.config/solana/boulderroller-admin-upgrade-authority.json`
- **Permissions:** configure ProgramConfig, run admin maintenance, migration,
  seed, and override instructions.
- **Constraint:** This key is also the current devnet program upgrade authority.
  It must never be used as a fee payer.

### Upgrade Authority
- **Role:** Program upgrades (should be multisig post-audit)
- **Current devnet pubkey:** `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH`
- **Recommended:** Squads multisig at the mainnet gate; see
  `docs/security/KEY_MAP.md`.

### Backend Authority
- **Role:** Backend-attested operational writes
- **Current devnet pubkey:** `CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha`
- **Current devnet file:** `~/.config/solana/boulderroller-backend-authority.json`
- **Permissions:** `record_ride`, `credit_cal`, climb-completion writes,
  settlement, and other `ProgramConfig.backend_authority` gated actions.
- **Constraint:** No program upgrade authority and no ProgramConfig admin power.

### Fee Payer
- **Role:** Pays SOL fees and rent only
- **Current devnet pubkey:** `9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP`
- **Current devnet file:** `~/.config/solana/boulderroller-fee-payer.json`
- **Constraint:** No protocol authority. It must be cheap to rotate.

### Mint Authority
- **Role:** DUNG token minting
- **Holder:** `MintAuth` PDA owned by dung_mint program
- **Constraints:**
  - Enforces supply cap (1B DUNG)
  - Enforces allocation buckets
  - Enforces halving schedule

### User Authority
- **Role:** Self-service operations requiring user signature
- **Permissions:**
  - `create_vault` / `create_vault_with_usdc` - Create new vaults
  - `stake_cal_in_vault` / `unstake_cal_from_vault` - Staking operations
  - `harvest` - Claim staking rewards
  - `upgrade_beetle_card` - Upgrade BeetleCard level
  - `elect_local_legend` - Trigger election

---

## Access Control Patterns

### Owner Checks
```rust
// UserState owner validation
constraint = user_state.owner == signer.key() @ ErrorCode::NotOwner
```

### Admin Checks
```rust
// Admin authority validation (should be hardcoded or PDA)
#[account(constraint = admin.key() == ADMIN_PUBKEY)]
pub admin: Signer<'info>,
```

### PDA Authority Signing
```rust
// Vault signs for LP token mints
let seeds = &[VAULT_SEED, &vault_id.to_le_bytes(), &[vault.bump]];
let signer_seeds = &[&seeds[..]];
// Use in CpiContext::new_with_signer
```

---

## Critical Invariants

### Supply Cap Invariants
1. `total_minted <= MAX_SUPPLY (1B DUNG)`
2. `community_minted <= COMMUNITY_CAP (400M)`
3. `treasury_minted <= TREASURY_CAP (250M)`
4. `team_minted <= TEAM_CAP (200M)`
5. `investor_minted <= INVESTOR_CAP (100M)`
6. `pol_minted <= POL_CAP (50M)`

### Staking Invariants
1. `vault.total_cal_staked == sum(all VaultStake.effective_cal)`
2. User cannot unstake more CAL than they own
3. Stake eligibility is gated by `VaultStake.effective_from_epoch` — stakes become effective the next Settlement Week, preventing mid-week games
4. User cannot collect more than `VaultStake.unclaimed_rewards` (discrete allocation credit)

### Distribution Invariants
1. Distribution shares sum to 10000 bps (100%)
2. Leaderboard (Record Board) rank percentages sum to 100%
3. Cannot finalize before wall-clock Settlement Week end + 24-hour grace window
4. Cannot finalize the same Settlement Week twice (`last_finalized_epoch` guard)
5. Per-bucket carry preserved: unused amounts never cross buckets

### Vault Creation Invariants
1. Signature must be 64 bytes
2. Name length: 3-64 characters
3. Vertical gain: minimum 50m (500 in storage)
4. Payment must match method (DUNG, CAL+USDC, or CAL only)

---

## Attack Surface Analysis

### Potential Vectors

| Vector | Mitigation | Status |
|--------|------------|--------|
| Admin key compromise | Mainnet-gate Squads migration, hardware-backed signers, separation from fee payer | Planned |
| Replay attacks | Nonce in proofs, completion tracking | Implemented |
| Integer overflow | Checked math throughout | Implemented |
| Supply cap bypass | On-chain enforcement in DungMintState | Implemented |
| Unauthorized minting | PDA authority with constraints | Implemented |
| Stake manipulation | LP token accounting, burns on unstake | Implemented |
| Distribution front-running | Backend-controlled timing | Implemented |

### Out of Scope (Accepted Risks)
- MEV on public transactions (mitigated by backend batching)
- Validator censorship (accepted for devnet)
- RPC provider reliability (multi-provider strategy planned)

---

## Upgrade Path

### Current State (Pre-Audit)
- Programs upgradeable by single key
- All changes logged in version control
- Devnet deployment only

### Post-Audit Requirements
1. Squads multisig for upgrade authority
2. Timelock on upgrades (48h minimum)
3. Mainnet deployment with immutable core logic
4. Emergency pause mechanism retained

---

## Audit Preparation Checklist

- [x] All PDAs documented with derivation
- [x] All authority roles documented
- [x] Supply cap enforcement on-chain
- [x] Critical invariants documented
- [x] Attack vectors analyzed
- [ ] Formal verification of key invariants
- [ ] Third-party audit scheduled
- [ ] Bug bounty program defined
