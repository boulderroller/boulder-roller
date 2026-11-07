# RFC: Tokenomics Parameters

**Date:** 2026-01-01
**Status:** DRAFT
**Depends On:** Points period complete, Privy integration

> **Arrow-of-time note (2026-04-15):** This RFC predates `docs/PROTOCOL_TRUTHS.md`. Current canonical vocabulary and flows are defined in TRUTHS and `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md`. Distribution splits and percentages below remain correct; language has been updated to reflect the current Settlement Week / Record Board / direct-allocation model.
>
> **Ratified amendment (2026-07-13):** Settlement Weeks hand off Monday 12:00 UTC with a 24-hour grace; the weekly staker share not unlocked by the participation curve flows to that week's Record Royalty; and DUNG halves automatically every 26 Settlement Weeks with a 1-bps tail until cap exhaustion. These values, the configured DUNG mint, and the `55/27/3/10/5` split are ProgramConfig policy rather than backend-selected transaction parameters.

---

## Executive Summary

This historical RFC inventories Boulder Roller economic parameters. Its former
TGE and team-adjustability framing is superseded by the zero-start posture and
the ratified amendment above. Current binding semantics live in
`docs/PROTOCOL_TRUTHS.md`.

---

## 1. Distribution Splits

### Settlement Week Finalization (Weekly)

Each Settlement Week (Monday 12:00 UTC + 24-hour finalization grace window), each Vault with pending tribute finalizes per-bucket with direct discrete allocation:

| Recipient | Percentage | Notes |
|-----------|------------|-------|
| **Leaderboard** (Record Board all-time top 10) | 55% | Rank split: 30/20/15/10/8/6/5/3/2/1 |
| **Stakers** | 27% | Pro-rata direct allocation to eligible stakers |
| **Local Legend** | 3% | Single rolling stewardship seat |
| **Protocol** | 10% | Treasury operations |
| **POL** | 5% | Protocol-owned liquidity (never sold) |
| **Total** | 100% | |

Unavailable-recipient amounts and allocation dust carry within their own bucket.
The part of the weekly staker maximum not unlocked by the participation curve
instead joins that week's Record Royalty and is never unlocked retroactively.

### Leaderboard Breakdown (Top 10)

| Rank | Share of 55% | Effective % |
|------|--------------|-------------|
| 1st | 30% | 16.5% |
| 2nd | 20% | 11.0% |
| 3rd | 15% | 8.25% |
| 4th | 10% | 5.5% |
| 5th | 8% | 4.4% |
| 6th | 6% | 3.3% |
| 7th | 5% | 2.75% |
| 8th | 3% | 1.65% |
| 9th | 2% | 1.1% |
| 10th | 1% | 0.55% |

### Industry Comparison

| Protocol | Protocol Fee | Notes |
|----------|--------------|-------|
| Lido | 10% | 5% treasury + 5% operators |
| mETH | 10% | Split with operators |
| JitoSOL | 4% + 0.1% exit | Lower but sustainable |
| **Boulder Rollers** | **10% + 5% POL** | In line with industry |

---

## 2. The Local Legend System

### Design: Single Rolling Seat

```
OLD MODEL (deprecated):
  - 3 seats per vault
  - Each locks 1000 DUNG for 30 days
  - Split 10% three ways
  - Complex, capital-gated

CURRENT MODEL:
  - 1 Local Legend seat per vault
  - Rolling — 8 Settlement Weeks per term
  - Most completions wins
  - Gets 3% of vault distributions
  - No DUNG lock required
  - Dormant seats carry within the Local Legend bucket
```

### Election Mechanics

```
Every 8 Settlement Weeks:

1. Count completions per wallet on vault during the term
2. Wallet with most completions = new Local Legend
3. Seat holder serves for next 8 Settlement Weeks
4. Earns 3% of each Settlement Week's vault distribution
5. Performs light curation:
   - Approve/reject cover photos
   - Flag suspicious completions for review

Ties: Broken by earliest completion timestamp (ride-time) in the window
```

### Why This Design

| Benefit | Explanation |
|---------|-------------|
| **Meritocratic** | Ride more → earn the seat |
| **Democratic** | No capital barrier (no DUNG lock) |
| **Simple** | 1 seat, easy to understand |
| **Aligned** | Local Legend cares about vault quality |
| **Anti-whale** | Capital can't buy the seat — TRUTHS P12 |

### Local Legend Responsibilities

| Task | Description | Frequency |
|------|-------------|-----------|
| Photo approval | Approve/reject vault cover photos | As needed |
| Completion review | Flag suspicious times for tribunal | As needed |
| Boost suggestions | Recommend vault for featuring | Optional |

**Dormancy behavior:** If there are no completions during a term window, the seat goes dormant and the 3% bucket carries forward within the Local Legend bucket to the next Settlement Week.

---

## 3. Fee Schedule

### Vault Creation

| Option | Cost | Notes |
|--------|------|-------|
| **Primary** | 1,000 CAL + $2 USDC | Post-TGE fee (pre-TGE uses entitlements and shadow USDC logging) |
| **Alternative** | 100 DUNG | Post-TGE token-only option |

**Parameterized:** Yes - adjustable pre-TGE
**Rationale:** Low barrier ($2) encourages vault creation. CAL burn adds deflationary pressure.

### Staking Fees

| Action | Fee | Destination |
|--------|-----|-------------|
| Stake entry | 0% | No friction to enter |
| **Unstake exit** | **0.5%** | 50% burn / 50% POL |

**Parameterized:** Yes
**Industry comparison:** 0.5% is standard (discourages churning without being punitive)

### Harvest Fees

| Action | Fee | Destination |
|--------|-----|-------------|
| Claim rewards | 5% | Protocol treasury |

**Parameterized:** Yes
**Rationale:** Small tax on withdrawals, not on accumulation.

### Marketplace Fees

| Action | Fee | Destination |
|--------|-----|-------------|
| Accessory sale | 5% | 50% burn / 50% treasury |

**Parameterized:** Yes
**Industry comparison:** Lower than typical 10% (OpenSea, Magic Eden). Encourages trading.

---

## 4. Settlement Clock

| Parameter | Value |
|-----------|-------|
| Settlement Week duration | 7 days (Monday 12:00 UTC -> Monday 12:00 UTC) |
| Finalization grace window | 24 hours after the week boundary |
| Normal DUNG receipt finalization | Tuesday 12:00 UTC |
| Local Legend rotation | 8 Settlement Weeks (~2 months) |
| Daily CAL mint | 2,500 CAL/user |

---

## 5. Supply & Emissions

### Total Supply

| Metric | Value |
|--------|-------|
| Max supply | 1,000,000,000 DUNG (1B) |
| Decimals | 9 |
| Chain | Solana (SPL Token) |

### Allocation

| Bucket | Amount | % | Vesting |
|--------|--------|---|---------|
| Community (Points) | 400M | 40% | 25% TGE, 75% over 12mo |
| Treasury | 250M | 25% | Unlocked as needed |
| Founder/Team | 200M | 20% | 1yr cliff, 4yr vest |
| Investors | 100M | 10% | 1yr cliff, 3yr vest |
| POL Liquidity | 50M | 5% | Never sold |

### Halving Schedule

| Epoch Range | Emission Rate | Notes |
|-------------|---------------|-------|
| 0-26 (6mo) | 100% | Full emissions |
| 27-52 | 50% | First halving |
| 53-78 | 25% | Second halving |
| 79-104 | 12.5% | Third halving |
| 105+ | Continues halving | Floors at 1 bps until cap exhaustion |

The halving count is derived from an immutable emission-start week. Delayed
execution catches up every elapsed interval. At cap exhaustion, settlement
continues successfully with zero new DUNG.

---

## 6. Revenue Projections

### Cost Structure (Monthly)

| Item | 1K Users | 10K Users | 50K Users |
|------|----------|-----------|-----------|
| Privy | $299 | $500 | ~$1,500 |
| Infrastructure | $75 | $150 | $300 |
| Gas sponsorship | $50 | $500 | $2,500 |
| **Total** | **$424** | **$1,150** | **$4,300** |

### Revenue Structure (Monthly)

| Source | 1K Users | 10K Users | 50K Users |
|--------|----------|-----------|-----------|
| Vault creation ($2) | $200 | $2,000 | $10,000 |
| Protocol fee (10%) | $40* | $400* | $2,000* |
| Exit fees (0.5%) | $10 | $100 | $500 |
| Harvest fees (5%) | $20 | $200 | $1,000 |
| **Total** | **$270** | **$2,700** | **$13,500** |

*Assumes 100 DUNG avg pot/vault/week, $0.01/DUNG

### Break-Even Analysis

| Scale | Costs | Revenue | Profit |
|-------|-------|---------|--------|
| 1K users | $424 | $270 | -$154 (subsidize early) |
| 5K users | $750 | $1,350 | +$600 |
| 10K users | $1,150 | $2,700 | +$1,550 |
| 50K users | $4,300 | $13,500 | +$9,200 |

**Break-even:** ~3,000 users

---

## 7. Parameter Authority

### Current Zero-Start Posture

The configured DUNG mint, `55/27/3/10/5` split, Monday settlement clock,
26-week halving interval, immutable emission start, and 1-bps tail are
ProgramConfig policy. A settlement transaction may not substitute its own
values merely because they sum to 10,000 basis points.

Fee percentages and Local Legend term length remain separate configured
parameters. Changing any binding economic parameter requires an explicitly
ratified, versioned protocol change; there is no active token-governance path.

### Historical Governance Sketch

The former TGE voting and timelock model is frozen design inventory under
zero-start. It is not an active authority surface or scheduled roadmap.

---

## 8. Parameter Summary Table

| Parameter | Value | Adjustable? | Location |
|-----------|-------|-------------|----------|
| Leaderboard (Record Board) % | 55% | ✅ Pre-TGE | vault_distribution_config |
| Staker % | 27% | ✅ Pre-TGE | vault_distribution_config |
| Local Legend % | 3% | ✅ Pre-TGE | vault_distribution_config |
| Protocol % | 10% | ✅ Pre-TGE | vault_distribution_config |
| POL % | 5% | ✅ Pre-TGE | vault_distribution_config |
| Vault creation (USDC) | $2 (shadow log pre-TGE, fee post-TGE) | ✅ Pre-TGE | vault_config |
| Vault creation (DUNG) | 100 (post-TGE) | ✅ Pre-TGE | vault_config |
| Vault creation (CAL) | 1,000 (post-TGE) | ✅ Pre-TGE | vault_config |
| Unstake fee | 0.5% | ✅ Pre-TGE | staking_config |
| Collect fee | 5% | ✅ Pre-TGE | staking_config |
| Marketplace fee | 5% | ✅ Pre-TGE | marketplace_config |
| Settlement Week duration | 7 days | ⚠️ Careful | settlement_config |
| Finalization grace window | 24 hours | ⚠️ Careful | settlement_config |
| Local Legend rotation | 8 Settlement Weeks | ✅ Pre-TGE | legend_config |
| Daily CAL mint | 2,500 | ⚠️ Careful | cal_config |

---

## 9. Changes from TOKENOMICS_V2.md

| Item | Old | New | Rationale |
|------|-----|-----|-----------|
| Soigneur seats | 3 | 1 | Simpler, more democratic |
| Soigneur lock | 1000 DUNG | None | Merit-based, not capital-gated |
| Soigneur election | Lock-based | Most rides | "Local Legend" reward |
| Soigneur rotation | 30 days | 2 months | Less churn, more stability |
| Soigneur % | 10% | 3% | Reduced, shifted to stakers |
| Staker % | 20% | 27% | Attracts more capital |
| Marketplace fee | 10% | 5% | Encourage trading |

---

## 10. Next Steps

1. Update `vault_distribution_config` table with new splits
2. Simplify `swanny_seats` table (1 seat, no lock; soigneur alias)
3. Add `swanny_elections` table for rotation tracking (soigneur alias)
4. Update Anchor program constants
5. Test full epoch distribution with new splits

---

## Sources

- [Lido Fee Structure](https://docs.lido.fi/)
- [LiquiFi Token Allocation Benchmarks](https://www.liquifi.finance/post/token-vesting-and-allocation-benchmarks)
- [DeFi Protocol Fee Trends 2025](https://www.cryptopolitan.com/defi-protocols-distributed-fees-in-2025/)
