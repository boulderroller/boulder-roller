# RFC: Privy Auth & UX Architecture

**Date:** 2024-12-26
**Status:** IMPLEMENTED (Jan 2026)
**Implementation:** `web/portal/src/contexts/AuthContext.tsx`, `backend/app/routes/auth.py`

> ⚠️ **Note:** Gas sponsorship details below reference the old "daily CAL claim" model.
> Current model: CAL earned from TSS, no daily claims needed. Gas sponsorship planned for
> vault completions and staking post-TGE.
>
> **June 2026 target update:** [Boulder Roller Balance and Gasless In-App
> Execution](./BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md) supersedes the
> narrow sponsorship table below. The target is Boulder Roller Balance plus
> gasless in-app execution, with wallet/security prompts reserved for platform
> boundary actions such as add funds, withdraw, transfer out, export, and
> account authority changes.

---

## Executive Summary

Replace wallet-only authentication with Privy embedded wallets. Users sign up with email/Google/Apple - wallet is created invisibly. Crypto natives can still connect Phantom. Full gas sponsorship for core loop actions.

**Goal:** Your cycling friends can sign up in 10 seconds without knowing what a wallet is.

---

## 1. Why Privy

### The Conversion Problem

```
Wallet-only funnel:
  100 athletes hear about app
  → 20 click "sign up"
  → 5 install Phantom (75% bounce at "what's a wallet?")
  → 4 complete signup
  → Conversion: 4%

Privy funnel:
  100 athletes hear about app
  → 20 click "sign up"
  → 18 click "Continue with Google" (familiar)
  → 15 complete signup
  → Conversion: 15%
```

**Result:** ~4x more users with same marketing spend.

### Why Privy Specifically

- Powers 75M+ accounts (Jupiter, Pump.fun, etc.)
- Acquired by Stripe (June 2025) - legitimacy signal
- Native Solana support with embedded wallets
- MPC key sharding (self-custodial, not custodial)
- Handles gas sponsorship infrastructure

---

## 2. Privy Costs

| Tier | MAU | Cost |
|------|-----|------|
| Free | 0-499 | $0 |
| Core | 500-2,499 | $299/mo |
| Scale | 2,500-9,999 | $499/mo |
| Enterprise | 10K+ | ~$0.001-0.005/tx |

**Points Period:** Free tier covers us.
**Post-TGE:** Scales with revenue.

---

## 3. Login Flow

### Modal Design

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              🪲 Boulder Roller                              │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  G  Continue with Google                        │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  🍎  Continue with Apple                        │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  ✉️  Continue with Email                        │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ───────────────────────────────────────────────────    │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  🦊  Connect Solana Wallet                      │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     Have a wallet? Phantom, Solflare, Backpack...          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key:** Social options first. Wallet for crypto natives at bottom.

### Technical Flow

```
User clicks "Continue with Google"
        │
        ▼
┌───────────────────────────────────────┐
│  Privy SDK                            │
│                                       │
│  1. Google OAuth                      │
│  2. Verify identity                   │
│  3. Create embedded Solana wallet     │
│  4. Return { user, wallet_address }   │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Our Backend                          │
│                                       │
│  1. Receive Privy JWT                 │
│  2. Verify with Privy                 │
│  3. Create/update user record         │
│  4. Link wallet_address to user       │
│  5. Return our session                │
└───────────────────────────────────────┘
        │
        ▼
User sees Dashboard (no wallet visible)
```

---

## 4. Wallet Visibility Philosophy

**Principle:** Crypto is the engine, not the paint job.

Users see CAL and DUNG as in-app currencies (like Strava kudos or airline miles), not as "crypto tokens."

### Where Wallet Appears

| Page | What User Sees | Wallet Visible? |
|------|----------------|-----------------|
| **Dashboard** | CAL: 2,847 / DUNG: 156 | ❌ Hidden |
| **RideView** | +89 points, 3 climbs | ❌ Hidden |
| **Leaderboard** | Rank #7 on Hawk Hill | ❌ Hidden |
| **Vault Detail** | 1,247 DUNG staked | ❌ Hidden (buttons work) |
| **Profile** | Bio, stats, badges | ⚠️ Collapsed "Wallet" section |
| **Portfolio** | All stakes, earnings | ✅ Full wallet management |
| **Settings > Advanced** | Export keys, link wallet | ✅ Power user zone |

### The Translation Layer

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  WHAT USERS SEE                 WHAT'S HAPPENING            │
│                                                             │
│  ┌─────────────────┐            ┌─────────────────┐        │
│  │  +89 points     │    ───►    │  UserState PDA  │        │
│  │  from ride      │            │  updated        │        │
│  └─────────────────┘            └─────────────────┘        │
│                                                             │
│  ┌─────────────────┐            ┌─────────────────┐        │
│  │  Stake 100 DUNG │    ───►    │  SPL transfer   │        │
│  │  in Mt. Tam     │            │  to vault PDA   │        │
│  └─────────────────┘            └─────────────────┘        │
│                                                             │
│  ┌─────────────────┐            ┌─────────────────┐        │
│  │  You're #3!     │    ───►    │  Leaderboard    │        │
│  │  🏆             │            │  PDA updated    │        │
│  └─────────────────┘            └─────────────────┘        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Gas Sponsorship Architecture

### What We Sponsor (Full Core Loop)

| Action | Frequency | Sponsor? | Why |
|--------|-----------|----------|-----|
| Claim CAL | 1x/day | ✅ Yes | Core loop, must be frictionless |
| Record completion | Per ride | ✅ Yes | Invisible after upload |
| Update leaderboard | Per ride | ✅ Yes | Automatic |
| Stake DUNG | Rare | ❌ No | Intentional, user has tokens |
| Unstake DUNG | Rare | ❌ No | Withdrawal = user pays |
| Create vault | Rare | ❌ No | Pays $2 USDC anyway |
| Claim swanny rewards | Monthly | ✅ Yes | Earned it |

### Cost Per User

```
Solana tx fee: ~0.000005 SOL ≈ $0.001 at $200/SOL

Monthly per user:
  Claim CAL:         30 tx × $0.001 = $0.03
  Completions:       10 tx × $0.001 = $0.01
  Leaderboard:       10 tx × $0.001 = $0.01
  ─────────────────────────────────────────
  Total:             ~$0.05/user/month
```

### Sponsorship Infrastructure

```
┌─────────────────────────────────────────────────────────────┐
│  FEE PAYER WALLET                                           │
│                                                             │
│  - Backend-controlled keypair                               │
│  - Funded with SOL (alert if < 1 SOL)                       │
│  - Private key in env vars (never exposed)                  │
│  - Signs as fee payer for sponsored txs                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SPONSORSHIP FLOW                                           │
│                                                             │
│  1. Frontend builds tx (unsigned)                           │
│  2. Sends to backend: POST /api/sponsor                     │
│  3. Backend validates:                                      │
│     - Is instruction whitelisted?                           │
│     - Is user rate-limited?                                 │
│     - Is fee payer funded?                                  │
│  4. If valid: backend adds fee payer signature              │
│  5. Returns partially-signed tx to frontend                 │
│  6. Privy signs with user's embedded wallet                 │
│  7. Submit to network                                       │
└─────────────────────────────────────────────────────────────┘
```

### Anti-Abuse Rate Limits

| Action | Limit |
|--------|-------|
| claim_cal | 1x/day/user |
| record_completion | 20x/day/user |
| update_leaderboard | 20x/day/user |

---

## 6. Session Keys: Not Needed

Privy embedded wallets eliminate the need for session keys:

| Problem | Session Keys | Privy |
|---------|--------------|-------|
| Popup fatigue | Ephemeral keypair | Embedded wallet signs invisibly |
| Scoped permissions | Custom PDA | Privy SDK handles |
| Key management | localStorage | Privy MPC infra |
| Expiry/renewal | Build ourselves | Privy handles |

**Decision:** Skip session keys entirely. Privy handles it.

---

## 7. Migration Path

### Phase 1: Points Period (Current)

- Keep existing wallet-only auth
- No gas costs (everything off-chain)
- No changes needed

### Phase 2: Add Privy (Pre-TGE)

1. Install `@privy-io/react-auth` SDK
2. Configure Solana embedded wallets
3. Add social login options to modal
4. Keep wallet option for existing users
5. Migrate existing users: link wallet to Privy account

### Phase 3: Post-TGE

1. Enable on-chain transactions
2. Fund fee payer wallet with SOL
3. Activate gas sponsorship for core loop
4. Monitor costs vs revenue

---

## 8. Implementation Checklist

- [ ] Create Privy account and project
- [ ] Install SDK: `npm install @privy-io/react-auth`
- [ ] Configure Solana chain in Privy dashboard
- [ ] Update `AuthContext` to use Privy
- [ ] Update login modal with social options
- [ ] Create fee payer wallet (backend)
- [ ] Build `/api/sponsor` endpoint
- [ ] Add rate limiting to sponsorship
- [ ] Monitor fee payer balance (alerts)
- [ ] Test full flow on devnet

---

## 9. Open Questions

1. **Multiple devices:** How handle same user on phone + desktop? (Privy handles)
2. **Wallet export:** Actively encourage or just allow? (Just allow, in Settings)
3. **Existing users:** Auto-link or manual migration? (TBD)

---

## Sources

- [Privy Pricing](https://www.privy.io/pricing)
- [Privy Solana Gas Sponsorship](https://docs.privy.io/wallets/gas-and-asset-management/gas/solana)
- [Privy Solana Support](https://privy.io/blog/solana-support)
- [Helius Web3 UX Guide](https://www.helius.dev/blog/web3-ux)
