# Boulder Roller - State Machines & Statecharts

**Generated:** January 14, 2026
**Purpose:** Comprehensive reference for all state machines in Boulder Roller

> **⚠ STALE RELATIVE TO PROTOCOL_TRUTHS (2026-04-15)**
>
> This document predates `docs/PROTOCOL_TRUTHS.md`. Several state machines described here are incorrect relative to the current TRUTHS-aligned model:
> - **Staking / Rewards section** — describes Synthetix-style `reward_rate` / `reward_per_token_stored` accrual math. This pattern has been **abandoned** per TRUTHS P8. The current model is discrete per-Settlement-Week direct allocation credited to `VaultStake.unclaimed_rewards`. See `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` WS-1.
> - **Epoch & Distribution section** — should be renamed to "Settlement Week Finalization" with per-bucket carry and a 24-hour grace window. Described state transitions need to be rewritten.
> - **Token Economics section** — any "instant conversion" or "1000 CAL = 1 DUNG" framing is stale. Tribute accumulates in the Vault and is allocated per-bucket at finalization.
> - **Local Legend section** — correct concept, but internal "Soigneur" naming should be Local Legend per TRUTHS §11.
>
> The structural state-machine diagrams are still useful as a reference for ride processing, pattern detection, auth, and error recovery — those sections remain accurate. Tokenomics state machines need a rewrite pass and are tracked for review under the `wdvr.8` cleanup workstream.

---

## Table of Contents
1. [Ride Processing](#1-ride-processing)
2. [Pattern Detection](#2-pattern-detection)
3. [Vault Lifecycle](#3-vault-lifecycle)
4. [Token Economics (CAL/DUNG)](#4-token-economics)
5. [Staking & Rewards](#5-staking--rewards) *(includes Staker Unlock Curve)*
6. [Epoch & Distribution](#6-epoch--distribution)
7. [User Authentication](#7-user-authentication)
8. [Beetle Cards](#8-beetle-cards)
9. [Local Legend (Soigneur)](#9-local-legend-soigneur) *(includes Creator Bootstrap)*
10. [Attestation & Proofs](#10-attestation--proofs)
11. [Frontend UI States](#11-frontend-ui-states)
12. [Error Recovery & Retry Patterns](#12-error-recovery--retry-patterns)
13. [Strava Import Flow](#13-strava-import-flow)
14. [Mainnet Launch Conditions](#14-mainnet-launch-conditions)
15. [Edge Case Summary](#15-edge-case-summary)

---

## 1. Ride Processing

```
                                    ┌─────────────────────────────────────────┐
                                    │            RIDE PROCESSING              │
                                    └─────────────────────────────────────────┘

    ┌─────────────┐     Upload      ┌─────────────┐    Parse OK    ┌─────────────┐
    │             │ ───────────────►│             │───────────────►│             │
    │   CREATED   │                 │  PROCESSING │                │  COMPLETED  │
    │             │◄────────────────│             │                │             │
    └─────────────┘   Duplicate     └──────┬──────┘                └─────────────┘
                      (HTTP 409)           │
                                           │ Parse Error
                                           ▼
                                    ┌─────────────┐
                                    │             │
                                    │   FAILED    │
                                    │             │
                                    └─────────────┘

Processing Pipeline (PROCESSING state):
┌────────────────────────────────────────────────────────────────────────────────┐
│  1. Parse File (FIT/GPX/TCX) ──► 2. Calculate Metrics (TSS, VAM, NP)          │
│         │                                │                                      │
│         ▼                                ▼                                      │
│  3. Store Activity Streams ──► 4. Project GPS to H3 Tiles                      │
│         │                                │                                      │
│         ▼                                ▼                                      │
│  5. Detect Patterns ──► 6. Match Vaults ──► 7. Allocate CAL                   │
└────────────────────────────────────────────────────────────────────────────────┘
```

### States & Transitions

| State | Description | Exit Conditions |
|-------|-------------|-----------------|
| **CREATED** | Initial upload received | Enqueue to processing queue |
| **PROCESSING** | Parsing, metrics, patterns | Success → COMPLETED, Error → FAILED |
| **COMPLETED** | All metrics calculated | Terminal state |
| **FAILED** | Error during processing | Terminal state (error_message stored) |

### Key Metrics Calculated
- **TSS:** `(duration_s * IF^2) / 36`
- **VAM:** `(vert_m / time_s) * 3600`
- **W/kg:** `avg_power_w / user_weight_kg`

---

## 2. Pattern Detection

```
                                    ┌─────────────────────────────────────────┐
                                    │          PATTERN DETECTION              │
                                    └─────────────────────────────────────────┘

Three Pattern Types:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   CLIMB                      STEADY                     EXPLORATION            │
│   ┌─────────────┐            ┌─────────────┐            ┌─────────────┐        │
│   │ Sustained   │            │ Z2-Z3       │            │ New tile    │        │
│   │ vertical    │            │ aerobic     │            │ discovery   │        │
│   │ gain ≥50m   │            │ effort      │            │             │        │
│   └──────┬──────┘            └─────────────┘            └─────────────┘        │
│          │                                                                      │
│          ▼                                                                      │
│   ┌─────────────┐     Similarity                                               │
│   │  Generate   │ ──────≥0.90────►  VAULT MATCHED                              │
│   │  Signature  │                   (measured climb TSS)                        │
│   └─────────────┘                                                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Pattern State Flow:
┌──────────────┐     Attribution     ┌──────────────┐     Match      ┌──────────────┐
│              │ ──────────────────► │              │ ──────────────►│              │
│   DETECTED   │     (OSM lookup)    │  ATTRIBUTED  │   (sig≥0.90)   │ VAULT_MATCHED│
│              │                     │              │                │              │
└──────────────┘                     └──────────────┘                └──────────────┘
```

---

## 3. Vault Lifecycle

```
                                    ┌─────────────────────────────────────────┐
                                    │            VAULT LIFECYCLE              │
                                    └─────────────────────────────────────────┘

                   CREATION                    RIGHTS PERIOD                KOM PERIOD
              ┌──────────────┐            ┌──────────────────┐         ┌──────────────┐
              │              │            │                  │         │              │
              │   CREATED    │───────────►│  MINTER_CONTROL  │────────►│  KOM_CONTROL │
              │              │            │   (12 epochs)    │         │              │
              └──────────────┘            └──────────────────┘         └──────────────┘
                     │                            │                           │
                     │ Burns 100 DUNG             │ Can update metadata       │ KOM holder
                     │ OR 1000 CAL + $2 USDC      │ Receives distributions    │ has rights
                     │                            │                           │

Vault Economics Flow:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   User Completes Ride                                                           │
│          │                                                                      │
│          ▼                                                                      │
│   ┌─────────────┐     10% CAL      ┌─────────────┐    1000:1     ┌───────────┐ │
│   │   Pattern   │ ────tribute────► │   CAL Pot   │ ────ratio───► │  pending  │ │
│   │   Matched   │                  │ accumulated │               │  _rewards │ │
│   └─────────────┘                  └─────────────┘               └─────────────┘│
│                                                                        │        │
│                                            ┌───────────────────────────┘        │
│                                            ▼                                    │
│                                    ┌─────────────┐                              │
│                                    │   EPOCH     │  55% Leaderboard             │
│                                    │ DISTRIBUTION│  27% Stakers                 │
│                                    │             │   3% Local Legend            │
│                                    └─────────────┘   5% POL, 10% Protocol       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Vault On-Chain States:
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│   pending_rewards: u64        ◄── CAL→DUNG instant conversion (completions)     │
│   total_cal_staked: u64       ◄── Sum of all staker CAL                         │
│   reward_per_token_stored     ◄── Synthetix cumulative DUNG/LP (1e12 scale)     │
│   reward_rate: u64            ◄── DUNG per second (set at distribution)         │
│   kom_holder: Pubkey          ◄── Current fastest time holder                    │
│   kom_time_s: u32             ◄── Best time in seconds                          │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Vault States Summary

| State | Duration | Who Controls | Actions Allowed |
|-------|----------|--------------|-----------------|
| **MINTER_CONTROL** | 12 epochs (~3 months) | Creator | Update metadata, receive distributions |
| **KOM_CONTROL** | After rights expire | KOM holder | Same as minter (transferred) |

---

## 4. Token Economics

```
                                    ┌─────────────────────────────────────────┐
                                    │          TOKEN ECONOMICS                │
                                    └─────────────────────────────────────────┘

TOKEN TYPES:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   CAL (Caliber)                  DUNG (Reward)               LP TOKENS          │
│   ┌─────────────┐                ┌─────────────┐            ┌─────────────┐    │
│   │ Effort      │                │ Value       │            │ Vault       │    │
│   │ Earned from │                │ Minted via  │            │ Staking     │    │
│   │ TSS (rides) │                │ Epochs      │            │ Shares      │    │
│   └─────────────┘                └─────────────┘            └─────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

CAL Lifecycle:
┌──────────────┐     Tribute     ┌──────────────┐     Stake      ┌──────────────┐
│              │ ──────────────► │              │ ──────────────►│              │
│    EARNED    │      (10%)      │   TRIBUTED   │                │    STAKED    │
│  (from ride) │                 │  (to vault)  │                │ (in vault LP)│
└──────────────┘                 └──────────────┘                └──────┬───────┘
                                                                        │
                                                        ┌───────────────┘
                                                        │ Unstake
                                                        ▼
                                                 ┌──────────────┐
                                                 │  RETURNED    │
                                                 │ (CAL back)   │
                                                 └──────────────┘

DUNG Lifecycle:
┌──────────────┐     In vault    ┌──────────────┐    Harvest     ┌──────────────┐
│              │ ──────────────► │              │ ──────────────►│              │
│    MINTED    │    reward pool  │   PENDING    │                │  HARVESTED   │
│ (from epoch) │                 │  (in vault)  │                │  (claimed)   │
└──────────────┘                 └──────────────┘                └──────────────┘

Supply Caps (1B Total):
┌─────────────────────────────────────────────────────────────────────────────────┐
│   Community: 400M (40%)  │  Treasury: 250M (25%)  │  Team: 200M (20%)           │
│   Investors: 100M (10%)  │  POL: 50M (5%)                                       │
│                                                                                 │
│   Halving: Every 26 epochs (~6 months) - emission rate halves                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Staking & Rewards

```
                                    ┌─────────────────────────────────────────┐
                                    │        STAKING STATE MACHINE            │
                                    └─────────────────────────────────────────┘

SYNTHETIX MODEL (On-Chain):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   User Action          Synthetix Snapshot                  Result              │
│   ───────────          ─────────────────                   ──────              │
│                                                                                 │
│   STAKE CAL    ───►    Save earned rewards    ───►    LP tokens minted        │
│                        Update vault RPT                CAL deducted            │
│                        Update user checkpoint                                   │
│                                                                                 │
│   HARVEST      ───►    Calculate earned       ───►    DUNG minted (- 5% fee)  │
│                        Reset checkpoint               Fee to treasury          │
│                                                                                 │
│   UNSTAKE      ───►    Save earned rewards    ───►    LP burned               │
│                        Calculate CAL return           CAL returned             │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Staking State Flow:
┌──────────────┐     stake()     ┌──────────────┐    unstake()   ┌──────────────┐
│              │ ──────────────► │              │ ──────────────►│              │
│    IDLE      │                 │    STAKED    │                │   UNSTAKED   │
│  (has CAL)   │◄────────────────│  (has LP)    │                │  (CAL back)  │
└──────────────┘    unstake()    └──────┬───────┘                └──────────────┘
                                        │
                                        │ harvest()
                                        ▼
                                 ┌──────────────┐
                                 │  HARVESTED   │
                                 │ (DUNG minted)│
                                 └──────────────┘

LP Token Minting:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   First staker:    LP = CAL_amount (1:1)                                       │
│   Subsequent:      LP = CAL_amount * total_LP / total_CAL_staked               │
│                                                                                 │
│   Unstaking:       CAL = LP_amount * total_CAL_staked / total_LP               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Reward Calculation (Synthetix Formula):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   reward_per_token() = stored + (reward_rate * time_delta * 1e12 / total_lp)   │
│                                                                                 │
│   earned() = lp_tokens * (current_rpt - user_rpt_paid) / 1e12 + rewards_earned │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

STAKER UNLOCK CURVE (Reverse Leaderboard):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Problem: First staker shouldn't capture entire 27% pool (gameable)            │
│   Solution: Staker pool unlocks gradually based on number of unique stakers    │
│                                                                                 │
│   Uses leaderboard percentages [30,20,15,10,8,6,5,3,2,1] in REVERSE:           │
│                                                                                 │
│   # Stakers │ Unlocks │ Cumulative │ % of Total │ Remainder → Leaderboard      │
│   ──────────┼─────────┼────────────┼────────────┼──────────────────────────     │
│       1     │   +1%   │     1%     │   0.27%    │  26.73% to leaderboard        │
│       2     │   +2%   │     3%     │   0.81%    │  26.19% to leaderboard        │
│       3     │   +3%   │     6%     │   1.62%    │  25.38% to leaderboard        │
│       4     │   +5%   │    11%     │   2.97%    │  24.03% to leaderboard        │
│       5     │   +6%   │    17%     │   4.59%    │  22.41% to leaderboard        │
│       6     │   +8%   │    25%     │   6.75%    │  20.25% to leaderboard        │
│       7     │  +10%   │    35%     │   9.45%    │  17.55% to leaderboard        │
│       8     │  +15%   │    50%     │  13.50%    │  13.50% to leaderboard        │
│       9     │  +20%   │    70%     │  18.90%    │   8.10% to leaderboard        │
│      10+    │  +30%   │   100%     │  27.00%    │   0% to leaderboard           │
│                                                                                 │
│   Benefits:                                                                     │
│   - Anti-gaming: First staker only gets 1% of pool, not worth grab-and-run    │
│   - Network effects: "Get friends to stake to unlock more rewards!"            │
│   - Elegant symmetry: Same percentages as leaderboard, inverted                │
│   - Natural maturity: Vault starts rider-dominated, matures to staker-balanced │
│                                                                                 │
│   Implementation:                                                               │
│   - Track vault.staker_count (unique stakers)                                  │
│   - STAKER_UNLOCK_PCTS = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100]               │
│   - At distribution: effective_staker_share = staker_share * unlock_pct / 100 │
│   - Remainder added to leaderboard_total for proportional split               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Epoch & Distribution

```
                                    ┌─────────────────────────────────────────┐
                                    │         EPOCH STATE MACHINE             │
                                    └─────────────────────────────────────────┘

EPOCH CYCLE (7 days):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Anchor: Sun Dec 31 2023 12:00:00 UTC                                         │
│   Duration: 604,800 seconds (7 days)                                           │
│   Current Epoch = FLOOR((now - anchor) / duration)                             │
│                                                                                 │
│   ┌────────────────────────────────────────────────────────────────────┐       │
│   │                                                                    │       │
│   │   Day 0 ─────────────► Day 6 ─────────────► Day 7 (Epoch End)     │       │
│   │    │                                              │                │       │
│   │    │   ACCUMULATION PHASE                        │ DISTRIBUTION   │       │
│   │    │   - CAL earned per vault                    │ - Process      │       │
│   │    │   - Completions tracked                     │ - Mint DUNG    │       │
│   │    │   - Leaderboard updated                     │ - Pay stakers  │       │
│   │                                                                    │       │
│   └────────────────────────────────────────────────────────────────────┘       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Epoch States:
┌──────────────┐   epoch_end    ┌──────────────┐   confirmed   ┌──────────────┐
│              │ ──────────────►│              │──────────────►│              │
│ ACCUMULATING │                │ DISTRIBUTING │               │  COMPLETED   │
│              │                │              │               │              │
└──────────────┘                └──────────────┘               └──────────────┘

Distribution Breakdown (per vault):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   pending_rewards (DUNG pool)                                                   │
│          │                                                                      │
│          ├──► 55% LEADERBOARD ──► Top 10: [30,20,15,10,8,6,5,3,2,1]%           │
│          │                                                                      │
│          ├──► 27% STAKERS ──► reward_rate = share / EPOCH_SECONDS              │
│          │                                                                      │
│          ├──►  3% LOCAL LEGEND ──► If active, else → stakers                   │
│          │                                                                      │
│          ├──►  5% POL ──► Protocol-owned liquidity account                     │
│          │                                                                      │
│          └──► 10% PROTOCOL ──► Treasury                                        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. User Authentication

```
                                    ┌─────────────────────────────────────────┐
                                    │      AUTHENTICATION STATE MACHINE       │
                                    └─────────────────────────────────────────┘

WALLET AUTH (SIWS):
┌──────────────┐    getNonce    ┌──────────────┐     sign      ┌──────────────┐
│              │ ──────────────►│              │──────────────►│              │
│   CONNECT    │                │    SIGNING   │               │   VERIFYING  │
│   WALLET     │                │   MESSAGE    │               │              │
└──────────────┘                └──────────────┘               └──────┬───────┘
                                                                      │
                         ┌────────────────────────────────────────────┘
                         │ verifySignature() → JWT issued
                         ▼
                  ┌──────────────┐
                  │AUTHENTICATED │──────────────► getMe() → User profile
                  └──────────────┘

PRIVY AUTH (Social Login):
┌──────────────┐   Privy SDK   ┌──────────────┐    embed      ┌──────────────┐
│              │ ──────────────►│              │──────────────►│              │
│   SOCIAL     │                │   PRIVY      │   wallet      │   WALLET     │
│   LOGIN      │                │   AUTH       │   ready       │   PENDING    │
└──────────────┘                └──────────────┘               └──────┬───────┘
                                                                      │
                         ┌────────────────────────────────────────────┘
                         │ getAccessToken() → verifyPrivyToken()
                         ▼
                  ┌──────────────┐
                  │AUTHENTICATED │──────────────► Syncs to AuthContext
                  └──────────────┘

Session States:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌─────────────────┐         ┌─────────────────┐        ┌─────────────────┐   │
│   │ UNAUTHENTICATED │ ──────► │  AUTHENTICATED  │ ─────► │ UNAUTHENTICATED │   │
│   │  (InviteGate)   │  login  │ (DashboardLayout│ logout │  (Clear state)  │   │
│   └─────────────────┘         └─────────────────┘        └─────────────────┘   │
│                                        │                                        │
│                                        │ 401 Response                           │
│                                        ▼                                        │
│                               ┌─────────────────┐                               │
│                               │   REFRESHING    │                               │
│                               │  (auto-refresh) │                               │
│                               └─────────────────┘                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Token Storage (HttpOnly Cookies):
┌─────────────────────────────────────────────────────────────────────────────────┐
│   Access Token:  15 min TTL, HttpOnly cookie                                    │
│   Refresh Token: 14 day TTL, HttpOnly cookie                                    │
│   Client Flag:   localStorage 'br_authenticated' (for UI state only)           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Beetle Cards

```
                                    ┌─────────────────────────────────────────┐
                                    │       BEETLE CARD STATE MACHINE         │
                                    └─────────────────────────────────────────┘

CARD TYPES:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   CLIMB                      STEADY                     EXPLORER                │
│   ┌─────────────┐            ┌─────────────┐            ┌─────────────┐        │
│   │ Per-arena   │            │ Global      │            │ Global      │        │
│   │ scope_id =  │            │ scope_id =  │            │ scope_id =  │        │
│   │ vault_sig   │            │ GLOBAL      │            │ GLOBAL      │        │
│   └─────────────┘            └─────────────┘            └─────────────┘        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

TWO-PHASE UPGRADE MODEL:
┌──────────────┐  increment_score  ┌──────────────┐  upgrade_card  ┌──────────────┐
│              │ ─────────────────►│              │───────────────►│              │
│   CREATED    │    (backend)      │   ELIGIBLE   │  (user burns   │   UPGRADED   │
│   Level 0    │                   │   Level N    │   DUNG)        │   Level N+1  │
└──────────────┘                   └──────────────┘                └──────────────┘

Level Thresholds:
┌─────────────────────────────────────────────────────────────────────────────────┐
│   Level  │  Score Threshold  │  Upgrade Cost (DUNG)  │  Name                    │
│   ────── │  ──────────────── │  ──────────────────── │  ────                    │
│     1    │      100          │       25              │  Novice                  │
│     2    │      500          │       25              │  Apprentice              │
│     3    │    1,500          │       50              │  Journeyman              │
│     4    │    5,000          │      100              │  Expert                  │
│     5    │   15,000          │      200              │  Master                  │
│     6    │   50,000          │      400              │  Grandmaster             │
│     7    │  150,000          │      800              │  Champion                │
│     8    │  500,000          │    1,600              │  Legend                  │
│     9    │ 1,500,000         │    3,200              │  Mythic                  │
│    10    │ 5,000,000         │    6,400              │  Transcendent (Elite)    │
│                                                                                 │
│   Cost Formula: 25 * 2^(level-1) DUNG                                          │
│                                                                                 │
│   Elite Requirements (Level 10):                                               │
│   - 5 KOMs held                                                                │
│   - 4.0 W/kg FTP                                                              │
│   - 60-day riding streak                                                       │
│   - 50,000 lifetime TSS                                                        │
└─────────────────────────────────────────────────────────────────────────────────┘

Card State Flow:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   User Ride ──► Pattern Detected ──► Beetle Score Incremented                  │
│                                              │                                  │
│                                              ▼                                  │
│                                    ┌─────────────────┐                          │
│                                    │ Check Threshold │                          │
│                                    └────────┬────────┘                          │
│                                             │                                   │
│                           ┌─────────────────┴─────────────────┐                 │
│                           │                                   │                 │
│                    score >= threshold               score < threshold           │
│                           │                                   │                 │
│                           ▼                                   ▼                 │
│                    ┌─────────────┐                     ┌─────────────┐          │
│                    │  ELIGIBLE   │                     │  CONTINUE   │          │
│                    │ to upgrade  │                     │  scoring    │          │
│                    └──────┬──────┘                     └─────────────┘          │
│                           │                                                     │
│                           │ User pays DUNG                                      │
│                           ▼                                                     │
│                    ┌─────────────┐                                              │
│                    │  UPGRADED   │                                              │
│                    │  level++    │                                              │
│                    └─────────────┘                                              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Local Legend (Soigneur)

```
                                    ┌─────────────────────────────────────────┐
                                    │     LOCAL LEGEND STATE MACHINE          │
                                    └─────────────────────────────────────────┘

BOOTSTRAP: Creator = First Soigneur
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   CREATE VAULT (pay 100 DUNG or 1K CAL + $2)                                   │
│          │                                                                      │
│          ▼                                                                      │
│   ┌─────────────────────────────────────┐                                      │
│   │  CREATOR = FIRST LOCAL LEGEND       │                                      │
│   │  (automatic, no election needed)    │                                      │
│   │  Term: 8 epochs from creation       │                                      │
│   │  Gets: 3% of distributions          │                                      │
│   └─────────────────────────────────────┘                                      │
│          │                                                                      │
│          │ After 8 epochs                                                       │
│          ▼                                                                      │
│   ┌─────────────────────────────────────┐                                      │
│   │  ELECTION BY COMPLETIONS            │                                      │
│   │  (most completions wins seat)       │                                      │
│   │  Repeats every 8 epochs             │                                      │
│   └─────────────────────────────────────┘                                      │
│                                                                                 │
│   Incentive Alignment:                                                         │
│   - Creator pays to mint vault → rewarded via Legend seat during bootstrap     │
│   - Creator incentivized to promote vault (get riders, grow pot)               │
│   - After term, transitions to meritocracy (ride most, earn seat)              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

ELECTION CYCLE (8 epochs = 56 days):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌──────────────┐     vote      ┌──────────────┐    elect     ┌─────────────┐ │
│   │              │ ─────────────►│              │─────────────►│             │ │
│   │   VACANT     │               │   NOMINATED  │              │   ELECTED   │ │
│   │   (or term   │               │              │              │   ACTIVE    │ │
│   │   expired)   │               │              │              │             │ │
│   └──────────────┘               └──────────────┘              └──────┬──────┘ │
│          ▲                                                           │         │
│          │                                                           │         │
│          │ term_end_epoch reached                                    │         │
│          │ OR resignation                                            │         │
│          │                                                    resign │         │
│          │                                                           ▼         │
│          │                                                    ┌─────────────┐  │
│          └────────────────────────────────────────────────────│   INACTIVE  │  │
│                                                               │  (stepped   │  │
│                                                               │   down)     │  │
│                                                               └─────────────┘  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Legend States:
┌─────────────────────────────────────────────────────────────────────────────────┐
│   State        │  Receives 3%  │  Can Update Vault  │  Duration                 │
│   ─────        │  ───────────  │  ────────────────  │  ────────                 │
│   VACANT       │      No       │       No           │  Until election           │
│   ACTIVE       │      Yes      │       Yes*         │  8 epochs (56 days)       │
│   INACTIVE     │      No       │       No           │  Until term end           │
│                                                                                 │
│   * If minter rights expired, legend has vault control                          │
└─────────────────────────────────────────────────────────────────────────────────┘

Election Criteria:
- Most completions on vault during election period
- Ties: Earlier completion wins
- Runner-up tracked for audit trail
```

---

## 10. Attestation & Proofs

```
                                    ┌─────────────────────────────────────────┐
                                    │      ATTESTATION STATE MACHINE          │
                                    └─────────────────────────────────────────┘

RETIRED BATCH/CLAIM PATH:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   V4-A removed the off-chain batch/claim pipeline. The current economic path    │
│   is receipt-backed and direct:                                                 │
│                                                                                 │
│   RideAttestation ──► ClimbCompletionReceiptV2 ──► CalMintReceipt ──► Settlement│
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Receipt Structure:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ride_hash = canonical trace hash under parser_version                         │
│                                                                                 │
│   RideAttestation PDA: ["ride_attestation", rider, ride_hash]                  │
│   CalMintReceipt PDA: ["cal_mint_receipt", ride_attestation, rider]            │
│   ClimbCompletionReceipt V1/V2 PDA:                                           │
│     ["climb_completion_receipt", attestation, vault]                          │
│   V2 stores evidence_version, exact cal_tributed, and the tribute-bound hash.  │
│                                                                                 │
│   Anchor init semantics make each receipt structurally idempotent.              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

Receipt Verification (On-Chain):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   1. Verify backend_authority against ProgramConfig                             │
│   2. Verify PDA seeds for the attestation or receipt                            │
│   3. Recompute V2 hash over attestation, vault, time, and exact tribute          │
│   4. Initialize the V2 receipt once; duplicate attempts fail at account creation│
│   5. Emit V2 completion and flow events for the indexer projection              │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

The V1 `record_climb_completion` wire entry and 105-byte receipt layout remain
for historical decoding, but V1 accepts no new writes. A V1 receipt proves
identity only and cannot authorize exact tribute, automatic recovery, or
settlement finality.

---

## 11. Frontend UI States

```
                                    ┌─────────────────────────────────────────┐
                                    │        FRONTEND UI STATES               │
                                    └─────────────────────────────────────────┘

COMPONENT LOADING PATTERN:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌──────────────┐     fetch     ┌──────────────┐    render   ┌──────────────┐ │
│   │              │ ─────────────►│              │────────────►│              │ │
│   │   SKELETON   │               │   LOADING    │             │   LOADED     │ │
│   │  (shimmer)   │               │  (spinner)   │             │  (content)   │ │
│   └──────────────┘               └──────────────┘             └──────────────┘ │
│                                         │                                       │
│                                         │ error                                 │
│                                         ▼                                       │
│                                  ┌──────────────┐                               │
│                                  │    ERROR     │                               │
│                                  │  (+ retry)   │                               │
│                                  └──────────────┘                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

PORTFOLIO PAGE STATES:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Independent Loading Sections:                                                │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │  CAL/DUNG Balance │  Staked Pos.  │  Leaderboards  │  Distributions    │  │
│   │  [Loading...]     │  [Loading...] │  [Loading...]  │  [Loading...]     │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│   Each section can be:                                                         │
│   - Loading (skeleton)                                                         │
│   - Loaded (content)                                                           │
│   - Error (with retry button)                                                  │
│   - Hidden (if not applicable)                                                 │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

VAULT VIEW STATES:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌───────────────────────────────────────────────────────────────────────┐    │
│   │                                                                       │    │
│   │   IDLE ───► STAKING ───► CONFIRMING ───► SUCCESS                     │    │
│   │     │                                        │                        │    │
│   │     │                                        │                        │    │
│   │     │       ┌──────────────────────────────┘                         │    │
│   │     │       │ refetch vault data                                      │    │
│   │     ▼       ▼                                                         │    │
│   │   ┌─────────────┐                                                     │    │
│   │   │   UPDATED   │                                                     │    │
│   │   │  (new stake │                                                     │    │
│   │   │   shown)    │                                                     │    │
│   │   └─────────────┘                                                     │    │
│   │                                                                       │    │
│   │   Same pattern for: UNSTAKING, HARVESTING                            │    │
│   │                                                                       │    │
│   └───────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

TRANSACTION SIGNING FLOW (FRONTEND):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌──────────────┐   build    ┌──────────────┐   sign     ┌──────────────┐     │
│   │              │ ──────────►│              │──────────►│              │     │
│   │  BUILD_TX    │            │  AWAITING    │           │  SIGNED      │     │
│   │  (backend)   │            │  SIGNATURE   │           │              │     │
│   └──────────────┘            └──────────────┘           └──────┬───────┘     │
│                                      │                          │             │
│                               reject │                   submit │             │
│                                      ▼                          ▼             │
│                               ┌──────────────┐           ┌──────────────┐     │
│                               │  CANCELLED   │           │ BROADCASTING │     │
│                               │              │           │              │     │
│                               └──────────────┘           └──────┬───────┘     │
│                                                                 │             │
│                                                      confirmed │             │
│                                                                 ▼             │
│                                                          ┌──────────────┐     │
│                                                          │  CONFIRMED   │     │
│                                                          │              │     │
│                                                          └──────────────┘     │
│                                                                               │
│   Validity Window: ~2 minutes (150 blocks)                                    │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────────┘

THEME STATE:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Themes: hoo-breddin | water | sunny | safari | moss | foundries              │
│   Modes: light | dark                                                          │
│                                                                                 │
│   ┌─────────────────┐                                                          │
│   │  localStorage   │◄────────────────────────────────────┐                    │
│   │  (instant)      │                                     │                    │
│   └────────┬────────┘                                     │                    │
│            │                                              │                    │
│            ▼                                              │                    │
│   ┌─────────────────┐        sync         ┌─────────────────┐                  │
│   │  ThemeContext   │◄───────────────────►│  User Profile   │                  │
│   │  (CSS vars)     │                     │  (cross-device) │                  │
│   └─────────────────┘                     └─────────────────┘                  │
│                                                                                 │
│   Priority: Profile > localStorage (profile wins on conflict)                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. Error Recovery & Retry Patterns

```
                                    ┌─────────────────────────────────────────┐
                                    │     ERROR RECOVERY STATE MACHINE        │
                                    └─────────────────────────────────────────┘

RIDE PROCESSING ERRORS:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   PROCESSING ────► FAILED                                                       │
│        │              │                                                         │
│        │              ├── Parse Error (corrupt file, unsupported format)        │
│        │              ├── Metrics Error (invalid data, division by zero)        │
│        │              ├── H3 Error (invalid GPS coordinates)                    │
│        │              └── Pattern Error (detection failure)                     │
│        │                                                                        │
│        │   Recovery Options:                                                    │
│        │   ┌─────────────────────────────────────────────────────────────────┐ │
│        │   │  1. MANUAL RETRY: User re-uploads file                          │ │
│        │   │     - Reset status to PENDING                                   │ │
│        │   │     - Clear error_message                                       │ │
│        │   │     - Re-enter processing queue                                 │ │
│        │   │                                                                  │ │
│        │   │  2. PARTIAL RECOVERY: Some metrics saved                        │ │
│        │   │     - Store what succeeded (basic metrics)                      │ │
│        │   │     - Mark failed subsystems (e.g., pattern detection)          │ │
│        │   │     - Allow manual pattern attribution later                    │ │
│        │   │                                                                  │ │
│        │   │  3. TERMINAL FAILURE: Unrecoverable                             │ │
│        │   │     - Store error details for debugging                         │ │
│        │   │     - Notify user with actionable message                       │ │
│        │   │     - Log for aggregate error monitoring                        │ │
│        │   └─────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

TRANSACTION RETRY PATTERN (Solana):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   BUILD ──► SIGN ──► SUBMIT ──► CONFIRM                                        │
│                         │          │                                            │
│                         │          │ BlockhashExpired                           │
│                         │          ▼                                            │
│                         │    ┌───────────┐                                      │
│                         │    │  REBUILD  │──► New blockhash, re-sign, retry    │
│                         │    └───────────┘    (max 3 attempts)                  │
│                         │                                                       │
│                         │ NetworkError / Timeout                                │
│                         ▼                                                       │
│                   ┌───────────┐                                                 │
│                   │  BACKOFF  │──► Exponential backoff (1s, 2s, 4s)            │
│                   └───────────┘    (max 3 attempts)                             │
│                                                                                 │
│   Terminal Failures (no retry):                                                │
│   - InsufficientFunds                                                          │
│   - InvalidSignature                                                           │
│   - AccountNotFound                                                            │
│   - ProgramError (business logic failure)                                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Strava Import Flow

```
                                    ┌─────────────────────────────────────────┐
                                    │       STRAVA IMPORT STATE MACHINE       │
                                    └─────────────────────────────────────────┘

MANUAL IMPORT FLOW:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   ┌──────────────┐   OAuth    ┌──────────────┐   fetch    ┌──────────────┐     │
│   │              │ ──────────►│              │──────────►│              │     │
│   │   CONNECT    │            │  AUTHORIZED  │           │   FETCHING   │     │
│   │   (OAuth)    │            │              │           │  ACTIVITIES  │     │
│   └──────────────┘            └──────────────┘           └──────┬───────┘     │
│                                                                 │              │
│                                      ┌──────────────────────────┘              │
│                                      ▼                                         │
│                               ┌──────────────┐                                 │
│                               │   SELECTING  │   User picks activities        │
│                               │  ACTIVITIES  │   to import                    │
│                               └──────┬───────┘                                 │
│                                      │                                         │
│                                      ▼                                         │
│                               ┌──────────────┐                                 │
│                               │  DOWNLOADING │   Fetch FIT/GPX streams        │
│                               │   STREAMS    │   from Strava API              │
│                               └──────┬───────┘                                 │
│                                      │                                         │
│                                      ▼                                         │
│                               ┌──────────────┐                                 │
│                               │  PROCESSING  │   Same pipeline as uploads     │
│                               │              │   (parse, metrics, patterns)   │
│                               └──────┬───────┘                                 │
│                                      │                                         │
│                           ┌──────────┴──────────┐                              │
│                           ▼                     ▼                              │
│                    ┌──────────────┐      ┌──────────────┐                      │
│                    │  COMPLETED   │      │   FAILED     │                      │
│                    │  (imported)  │      │  (error msg) │                      │
│                    └──────────────┘      └──────────────┘                      │
│                                                                                 │
│   Notes:                                                                       │
│   - OAuth tokens stored encrypted, refreshed automatically                     │
│   - Rate limited: 100 requests/15 min, 1000/day                               │
│   - Duplicate detection via activity_id (Strava ID stored)                    │
│   - Webhook sync planned for future (auto-import new rides)                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 14. Mainnet Launch Conditions

> **Note (April 2026):** The points system has been removed. There is no longer a "points period"
> or points-to-DUNG conversion. The protocol runs directly on CAL/DUNG (live on Solana devnet).
> TGE now refers to mainnet deployment and public token trading, not a points conversion event.

```
                                    ┌─────────────────────────────────────────┐
                                    │       MAINNET LAUNCH CONDITIONS         │
                                    └─────────────────────────────────────────┘

TRIGGER CONDITIONS (ANY triggers launch):
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   DEVNET PROTOCOL ───────────────────────────────────────────► MAINNET LAUNCH  │
│                                                                                 │
│   Trigger if ANY condition met:                                                │
│   ┌─────────────────────────────────────────────────────────────────────────┐  │
│   │                                                                         │  │
│   │   USERS:    10,000 active users                                         │  │
│   │                                                                         │  │
│   │   VAULTS:   1,000 vaults created                                        │  │
│   │                                                                         │  │
│   │   TREASURY: $100,000 USDC accumulated                                   │  │
│   │                                                                         │  │
│   └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│   Launch State Transitions:                                                    │
│   ┌──────────────┐  trigger   ┌──────────────┐  go-live  ┌──────────────┐     │
│   │              │ ──────────►│              │──────────►│              │     │
│   │   DEVNET     │            │  MAINNET     │           │  PUBLIC      │     │
│   │              │            │  DEPLOYMENT  │           │ (CAL/DUNG)   │     │
│   └──────────────┘            └──────────────┘           └──────────────┘     │
│                                                                                 │
│   Mainnet Changes:                                                             │
│   - Program deployed to mainnet-beta                                           │
│   - Vault creation requires DUNG or CAL+USDC                                   │
│   - Token trading begins on DEXes                                              │
│   - Upgrade authority on hardware wallet                                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 15. Edge Case Summary

```
DISTRIBUTION EDGE CASES:
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│   Scenario                    │ Resolution                                     │
│   ────────────────────────────┼────────────────────────────────────────────    │
│   No stakers (0 unique)       │ 27% → Leaderboard (proportional)               │
│   Few stakers (1-9)           │ Partial unlock via reverse LB curve            │
│   10+ stakers                 │ Full 27% to stakers                            │
│   Local Legend vacant         │ 3% → Stakers (already implemented)             │
│   Legend term expired         │ 3% → Stakers until new election                │
│   Leaderboard < 10 entries    │ Only pay existing entries (temporary)          │
│   No completions in epoch     │ No CAL tribute → No DUNG to distribute         │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference Tables

### All Entity States

| Entity | States | Primary Transitions |
|--------|--------|---------------------|
| **Ride** | pending, processing, completed, failed | Upload → Process → Complete/Fail |
| **Pattern** | detected, attributed, vault_matched | Detect → Attribute → Match |
| **Vault** | minter_control, kom_control | Create → Rights expire → KOM takes over |
| **CAL Token** | earned, tributed, staked, unstaked | Ride → Tribute → Stake → Unstake |
| **DUNG Token** | minted, staked, harvested, vesting | Proof → Stake/Distribute → Harvest |
| **VaultStake** | idle, staked, unstaked, harvested | Stake → Earn → Harvest/Unstake |
| **Epoch** | accumulating, distributing, completed | Weekly cycle |
| **User Auth** | unauthenticated, authenticated | Login/Logout |
| **Beetle Card** | created, eligible, upgraded | Score → Threshold → Upgrade |
| **Local Legend** | vacant, nominated, active, inactive | Nominate → Elect → Serve → Term end |
| **Attestation** | pending, batched, submitted, confirmed | Create → Batch → Submit → Finalize |

### Key Thresholds & Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| Epoch Duration | 604,800s (7 days) | Distribution cycle |
| Minter Rights | 12 epochs (84 days) | Vault creator control period |
| Legend Term | 8 epochs (56 days) | Soigneur election cycle |
| CAL:DUNG Ratio | 1000:1 | Tribute conversion |
| Min Stake | 100 CAL | Vault staking minimum |
| Vault Cost (DUNG) | 100 DUNG | Create vault |
| Vault Cost (alt) | 1000 CAL + $2 USDC | Alternative payment |
| Harvest Fee | 5% | Protocol fee on DUNG claims |
| Halving Period | 26 epochs (~6 months) | Emission reduction |
| Max Supply | 1B DUNG | Hard cap |

---

*Last Updated: April 2, 2026*
*Includes: Staker Unlock Curve, Creator Bootstrap, Error Recovery, Mainnet Launch Conditions*
*Note: Points system references removed April 2026. Protocol runs on CAL/DUNG directly.*
