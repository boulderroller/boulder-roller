# Boulder Rollers Threat Model

> **State note (2026-04-15):** This threat model is under review as part of the V4-A coherence redeploy (beads `wdvr.5`). Staking mitigations were rewritten for the discrete per-Settlement-Week allocation model that abandons Synthetix-style reward accrual. Other sections remain under review — verify any specific mitigation against `docs/PROTOCOL_TRUTHS.md` and `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` before relying on it.

## System Overview

Boulder Rollers is a decentralized cycling platform where riders earn tokens (CAL/DUNG) by completing climbs. The system involves:

1. **Off-chain components:** Backend API, ride processing, GPS verification
2. **On-chain components:** Solana programs for tokenomics, staking, distributions
3. **User interactions:** Wallet signing, staking, claiming rewards

---

## Threat Categories

### 1. Token Economics Threats

#### 1.1 Supply Inflation Attack
**Threat:** Unauthorized DUNG minting exceeds 1B supply cap
**Impact:** CRITICAL - Token value destruction
**Mitigations:**
- On-chain `DungMintState` enforces `total_minted <= MAX_SUPPLY`
- Per-bucket caps (community/treasury/team/investor/POL)
- Halving schedule reduces emission rate every 180 days
- All mint operations check `can_mint()` before proceeding

**Invariant Test:**
```rust
// In lib.rs
require!(mint_state.can_mint(amount, bucket), ErrorCode::SupplyCapExceeded);
```

#### 1.2 CAL Duplication Attack
**Threat:** User credits CAL multiple times for same ride
**Impact:** HIGH - CAL inflation, unfair rewards
**Mitigations:**
- `credit_cal` requires `backend_authority` signature (chain-enforced via ProgramConfig)
- Structural replay protection via `CalMintReceipt` PDA keyed by `(ride_attestation, rider)` — Anchor `init` prevents duplicate receipts
- Backend tracks processed activity IDs (idempotency key)
- Canonicalized `ride_hash` binds each mint to a specific ride's canonical trace; recomputable from source by the rider (TRUTHS §10 verifiability)

#### 1.3 Reward Siphoning
**Threat:** Malicious actor claims rewards not earned
**Impact:** HIGH - Theft from staker bucket
**Mitigations:**
- Settlement Week finalization is atomic per-Vault, per-bucket, gated by `backend_authority` and protected by a `last_finalized_epoch` guard that prevents double-distribution
- Stakers receive discrete direct allocation credited to `VaultStake.unclaimed_rewards` at finalization. No accrual math, no per-token reward math — claim is a flat transfer of the field to the rider ATA
- Record Royalty payouts go directly to Record Board members by pubkey; eligibility is checked against the on-chain Record Board at finalization time
- No batch-claim proof path, no continuous reward accrual — surface area for siphoning is minimized by construction

---

### 2. Staking Security Threats

#### 2.1 Stake Manipulation
**Threat:** User stakes/unstakes mid-week to game reward distribution
**Impact:** MEDIUM - Unfair reward distribution
**Mitigations:**
- Full-epoch participation rule (TRUTHS P9): `VaultStake.effective_from_epoch` explicitly gates when a stake becomes eligible for a Settlement Week's allocation. Mid-week stake changes never affect the current week.
- No flash-stake attack possible — even if a rider stakes moments before finalization, `effective_from_epoch` is set to `current_epoch + 1`, meaning the stake earns nothing for the current Settlement Week
- The unlock curve (1% → 100% across 1–10 eligible stakers) counts only stakers who meet the full-epoch rule, preventing sockpuppet swarms from gaming rewards unlock

#### 2.2 Stake Accounting Integrity
**Threat:** Stake accounting diverges from actual CAL held
**Impact:** HIGH - Dilution or theft from stakers
**Mitigations:**
- `VaultStake.effective_cal` is the single source of truth per (vault, staker)
- CAL transferred into the Vault's CAL escrow PDA on stake; transferred back on unstake
- Account constraints verify ownership and PDA derivation before every operation

#### 2.3 Unauthorized Unstaking
**Threat:** User unstakes more than they own
**Impact:** HIGH - Theft from Vault
**Mitigations:**
- `require!(stake.effective_cal >= amount)` check before any principal return
- Stake position closed atomically on full unstake
- Account constraints verify rider ownership of VaultStake PDA

---

### 3. Vault Security Threats

#### 3.1 Vault Signature Collision
**Threat:** Two different climbs produce same 64-byte signature
**Impact:** MEDIUM - Vault matching errors
**Mitigations:**
- SHA256 gradient hash (32 bytes) + metrics + MD5 checksum
- Collision probability: 2^-128 for random inputs
- Backend validation of climb characteristics

#### 3.2 Vault Squatting
**Threat:** User creates vault for popular climb before legitimate founder
**Impact:** LOW - UX issue, not security
**Mitigations:**
- Vault creation cost (100 DUNG or 1K CAL + $2 USDC)
- Founder metadata rights expire after 12 Settlement Weeks
- Community can report fraudulent vaults

#### 3.3 KOM Time Manipulation
**Threat:** User submits fake fast completion time
**Impact:** MEDIUM - Leaderboard manipulation
**Mitigations:**
- Backend validates completion against GPS data
- RideAttestation account binds the canonical ride hash, parser version, source kind, and backend signature to the completion
- Rate limiting on completions per user

---

### 4. Distribution Security Threats

#### 4.1 Double Distribution
**Threat:** Same epoch distributed twice
**Impact:** HIGH - Double rewards
**Mitigations:**
- `require!(vault.last_epoch_distributed < current_epoch)`
- Epoch boundary checks in `distribute_epoch_rewards`

#### 4.2 Distribution Skipping
**Threat:** Epoch skipped, rewards lost
**Impact:** MEDIUM - Lost rewards accumulate
**Mitigations:**
- Backend cron job triggers distribution
- Manual admin trigger available
- Monitoring/alerting on missed distributions

#### 4.3 Leaderboard Manipulation
**Threat:** User submits multiple fake completions to claim leaderboard %
**Impact:** HIGH - Steal from legitimate riders
**Mitigations:**
- Backend GPS verification before recording completion
- RideAttestation and ClimbCompletionReceipt accounts provide a chain-auditable receipt trail
- Rate limiting (1 completion per climb per 24h)

---

### 5. Authority Compromise Threats

#### 5.1 Admin Key Theft
**Threat:** Backend private key stolen
**Impact:** CRITICAL - Full control over token operations
**Mitigations:**
- Key stored in secure env, not in code
- Rate limiting on admin operations
- Monitoring for unusual activity
- Post-audit: Multisig for admin operations

#### 5.2 Upgrade Authority Abuse
**Threat:** Malicious program upgrade
**Impact:** CRITICAL - Full system compromise
**Mitigations:**
- Upgrade logs in version control
- Post-audit: Squads multisig + timelock
- Mainnet: Consider immutable core

---

### 6. External Integration Threats

#### 6.1 GPS Spoofing
**Threat:** User submits fake GPS data for rides
**Impact:** HIGH - Earn CAL without riding
**Mitigations:**
- Velocity sanity checks
- Heart rate correlation (when available)
- Power-based verification (when available)
- Community flagging system

#### 6.2 Strava API Abuse
**Threat:** Manipulated Strava activity imports
**Impact:** MEDIUM - Fake ride data
**Mitigations:**
- Strava webhook verification
- Cross-reference with known climb profiles
- Historical anomaly detection

---

## Risk Matrix

| Threat | Likelihood | Impact | Risk Level | Status |
|--------|------------|--------|------------|--------|
| Supply inflation | Low | Critical | HIGH | Mitigated |
| CAL duplication | Low | High | MEDIUM | Mitigated |
| Reward siphoning | Low | High | MEDIUM | Mitigated |
| Stake manipulation | Medium | Medium | MEDIUM | Mitigated |
| LP inflation | Low | High | MEDIUM | Mitigated |
| Unauthorized unstake | Low | High | MEDIUM | Mitigated |
| Signature collision | Very Low | Medium | LOW | Accepted |
| Vault squatting | Medium | Low | LOW | Accepted |
| KOM manipulation | Medium | Medium | MEDIUM | Mitigated |
| Double distribution | Low | High | MEDIUM | Mitigated |
| Distribution skip | Low | Medium | LOW | Monitored |
| Leaderboard manip | Medium | High | HIGH | Mitigated |
| Admin key theft | Low | Critical | HIGH | Planned |
| Upgrade abuse | Very Low | Critical | MEDIUM | Planned |
| GPS spoofing | Medium | High | HIGH | Mitigated |
| Strava abuse | Low | Medium | LOW | Monitored |

---

## Security Monitoring

### Metrics to Track
1. Total DUNG minted vs cap (should never exceed)
2. Daily CAL credits (anomaly detection)
3. Stake/unstake frequency per user
4. Distribution timing vs epoch boundaries
5. Completion rate per user (flag > 10/day)
6. Admin operation frequency

### Alerts
- DUNG minted > 90% of cap
- Single user > 1000 CAL in 24h
- Distribution missed by > 1 hour
- Admin operations from new IP
- Unusual vault creation spike

---

## Incident Response

### Severity Levels

| Level | Description | Response Time |
|-------|-------------|---------------|
| P0 | Active exploit, funds at risk | Immediate |
| P1 | Critical vulnerability discovered | < 4 hours |
| P2 | Significant issue, no immediate risk | < 24 hours |
| P3 | Minor issue | < 1 week |

### Emergency Actions
1. **Pause minting** - dung_mint has pause flag
2. **Pause distributions** - Backend can halt cron
3. **Pause frontend** - Vercel deployment control
4. **Communicate** - Discord, Twitter announcement

---

## Post-Audit Improvements

1. **Multisig Authority**
   - Squads multisig for admin operations
   - 2/3 threshold for routine ops
   - 3/5 for upgrades

2. **Timelock**
   - 48h delay on program upgrades
   - 24h delay on parameter changes

3. **Bug Bounty**
   - Up to $50K for critical vulnerabilities
   - Immunefi or custom program

4. **Formal Verification**
   - Key invariants (supply cap, staking math)
   - Consider Certora or similar tool
