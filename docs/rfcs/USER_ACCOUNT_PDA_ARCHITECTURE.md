# RFC: User Account PDA Architecture

**Date:** 2024-12-26
**Status:** BRAINSTORM (partially superseded)
**Decision Required:** Before further Anchor development

> **April 2026 Update:** The "Points Period" off-chain layer described in this RFC has been
> removed from the codebase. The `wallet_points`, `points_events`, and `points_config` tables
> no longer exist. The protocol operates directly on CAL/DUNG (live on Solana devnet).
> References to "points period" and "off-chain points in PostgreSQL" below are historical.
>
> **June 2026 Update:** [Boulder Roller Balance and Gasless In-App
> Execution](./BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md) is the current
> product architecture target. This older RFC remains useful for PDA/session-key
> history, but the target direction is Boulder Roller Balance, gasless in-app
> execution, policy/delegate authority where appropriate, and wallet prompts
> mainly at platform boundaries.

---

## Context

Before implementing more Solana program logic, we need to decide on user account architecture. The choices here affect:
- UX (wallet popups, transaction signing friction)
- Security (key management, fund isolation)
- Complexity (PDA derivation, account relationships)
- Regulatory posture (custodial vs non-custodial)

---

## Current State

### What We Have (lib.rs)

```rust
// PDA: [USER_SEED, owner.key().as_ref()]
pub struct UserState {
    pub owner: Pubkey,           // User's main wallet
    pub cal_balance: u64,        // CAL tokens (non-transferable)
    pub cal_earned_today: u64,
    pub last_cal_mint: i64,
    pub total_rides: u64,
    pub total_tss: u64,
    pub bio_score: u16,
    pub bump: u8,
}
```

**Current model:** One PDA per user wallet. Stores CAL balance and stats. DUNG lives in user's actual token account (ATA).

**Problems with current model:**
1. Every interaction requires wallet signature (popup fatigue)
2. CAL is on-chain but could be off-chain (points period shows this works)
3. No session/delegation capability
4. No separation between "game balance" and "main wallet"

---

## Industry Patterns

### Pattern 1: STEPN Dual-Wallet

```
┌─────────────────────────────────────────────────┐
│  STEPN Architecture                             │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌──────────────────┐    │
│  │   WALLET     │      │    SPENDING      │    │
│  │  (External)  │ ───► │   (In-App PDA)   │    │
│  │              │ ◄─── │                  │    │
│  │ - SOL        │      │ - GST            │    │
│  │ - GMT        │      │ - Game items     │    │
│  │ - NFT Shoes  │      │ - Repair costs   │    │
│  └──────────────┘      └──────────────────┘    │
│         │                      │               │
│         │    Gas fees for      │               │
│         └──── transfers ───────┘               │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Pros:**
- Users can't accidentally drain their main wallet in-game
- Game mechanics isolated from main funds
- Familiar UX (deposit/withdraw flow)

**Cons:**
- Extra friction (must deposit to play)
- Gas costs on transfers
- Still requires signature for spending→wallet transfers
- Feels "custodial" even if it isn't

**Boulder Rollers Fit:** MEDIUM - We don't have high-frequency micro-transactions like shoe repairs

---

### Pattern 2: Session Keys (MagicBlock/Gum)

```
┌─────────────────────────────────────────────────┐
│  Session Keys Architecture                      │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐                              │
│  │ MAIN WALLET  │                              │
│  │  (Phantom)   │                              │
│  └──────┬───────┘                              │
│         │                                       │
│         │ One-time approval                     │
│         │ (creates session)                     │
│         ▼                                       │
│  ┌──────────────────────────────────┐          │
│  │      SESSION KEY PDA             │          │
│  │                                  │          │
│  │  - Ephemeral keypair             │          │
│  │  - Scoped to boulder_rollers     │          │
│  │  - Expires after N hours/days    │          │
│  │  - Max spend limit               │          │
│  │  - Revocable by main wallet      │          │
│  └──────────────────────────────────┘          │
│         │                                       │
│         │ Auto-signs within scope               │
│         ▼                                       │
│  ┌──────────────────────────────────┐          │
│  │  Game Actions (no popups)        │          │
│  │  - Claim CAL                     │          │
│  │  - Record completions            │          │
│  │  - Update leaderboard            │          │
│  └──────────────────────────────────┘          │
│                                                 │
│  ⚠️ High-value actions still need main wallet: │
│     - Stake DUNG                               │
│     - Claim swanny seat                        │
│     - Withdraw                                 │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Pros:**
- Best UX for frequent actions (no popups)
- Security via scoping (can't drain wallet)
- Player keeps full custody
- Time-limited (sessions expire)

**Cons:**
- Complexity (session creation, validation, expiry)
- Need to handle session renewal
- Not all wallets support it natively
- Requires program changes to validate session signer

**Boulder Rollers Fit:** HIGH - We have frequent low-value actions (CAL claims, completions)

---

### Pattern 3: Burner Wallet (Client-Side)

```
┌─────────────────────────────────────────────────┐
│  Burner Wallet Architecture                     │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌──────────────────┐    │
│  │ MAIN WALLET  │      │  BURNER WALLET   │    │
│  │  (Hardware)  │ ───► │ (localStorage)   │    │
│  │              │      │                  │    │
│  │ - Main SOL   │      │ - 0.1 SOL        │    │
│  │ - Main DUNG  │      │ - Session use    │    │
│  └──────────────┘      └──────────────────┘    │
│                               │                │
│                               │ Auto-approve   │
│                               ▼                │
│                        All game txs            │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Pros:**
- Simple to implement
- Full auto-approve (best UX)
- Works with any wallet

**Cons:**
- Key stored in browser (can be lost)
- User must manually fund burner
- Clear cache = lose burner key
- Security risk if burner funded with too much

**Boulder Rollers Fit:** LOW - Too risky for a cycling app with real value

---

### Pattern 4: Hybrid Account System (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│  Boulder Rollers Hybrid Architecture                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                    USER'S MAIN WALLET                  │    │
│  │                      (Phantom/etc)                     │    │
│  │                                                        │    │
│  │  Owns: SOL, DUNG (ATA), NFTs, BeetleCards             │    │
│  │  Signs: Staking, Swanny, Withdrawals, High-value      │    │
│  └────────────────────────────────────────────────────────┘    │
│                              │                                  │
│         ┌────────────────────┼────────────────────┐            │
│         │                    │                    │            │
│         ▼                    ▼                    ▼            │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  UserState  │    │  VaultStake  │    │ SwannySeat   │      │
│  │    (PDA)    │    │    (PDA)     │    │    (PDA)     │      │
│  │             │    │              │    │              │      │
│  │ - CAL bal   │    │ - Per vault  │    │ - Lock state │      │
│  │ - Stats     │    │ - LP tokens  │    │ - Earnings   │      │
│  │ - Bio score │    │ - Harvest    │    │              │      │
│  └─────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
│  ═══════════════════════════════════════════════════════════   │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                 OPTIONAL: SESSION KEY                  │    │
│  │            (For frequent, low-value actions)           │    │
│  │                                                        │    │
│  │  Created: On login (1-click approval)                 │    │
│  │  Scope: boulder_rollers program only                  │    │
│  │  Expiry: 7 days (configurable)                        │    │
│  │  Limits: Max 100 CAL claim, 10 completions/day        │    │
│  │                                                        │    │
│  │  Can do:                                              │    │
│  │    ✓ Claim daily CAL                                  │    │
│  │    ✓ Record vault completions                         │    │
│  │    ✓ Update leaderboard times                         │    │
│  │                                                        │    │
│  │  Cannot do:                                           │    │
│  │    ✗ Transfer DUNG                                    │    │
│  │    ✗ Stake/unstake                                    │    │
│  │    ✗ Claim swanny seat                                │    │
│  │    ✗ Anything outside boulder_rollers                 │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ═══════════════════════════════════════════════════════════   │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              OFF-CHAIN (Points Period) — REMOVED       │    │
│  │                                                        │    │
│  │  ~~PostgreSQL: wallet_points, points_events~~          │    │
│  │                                                        │    │
│  │  This layer was removed April 2026.                   │    │
│  │  Protocol now runs on CAL/DUNG directly (on-chain).   │    │
│  │                                                        │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Decision Matrix

| Feature | Current | STEPN-style | Session Keys | Burner | Hybrid |
|---------|---------|-------------|--------------|--------|--------|
| **UX (frequent actions)** | ❌ Popup every time | ⚠️ Deposit friction | ✅ Seamless | ✅ Seamless | ✅ Seamless |
| **Security** | ✅ Full custody | ✅ Isolated funds | ✅ Scoped/limited | ⚠️ Key in browser | ✅ Scoped |
| **Complexity** | ✅ Simple | ⚠️ Transfer logic | ⚠️ Session mgmt | ✅ Simple | ⚠️ Medium |
| **Regulatory** | ✅ Non-custodial | ⚠️ Feels custodial | ✅ Non-custodial | ✅ Non-custodial | ✅ Non-custodial |
| **Implementation** | ✅ Done | ⚠️ Major changes | ⚠️ New PDAs | ⚠️ Client work | ⚠️ Incremental |

---

## Proposed Implementation: Hybrid Model

### Phase 1: ~~Keep Current (Points Period)~~ — COMPLETED (points removed)
- ~~No changes to on-chain user accounts~~
- ~~Points are off-chain (already working)~~
- **Points system removed April 2026.** Protocol runs on CAL/DUNG directly.

### Phase 2: Add Session Keys (Post-TGE)
Only if we need frequent on-chain actions.

```rust
// New PDA: Session Key
#[account]
pub struct SessionKey {
    pub owner: Pubkey,           // Main wallet that created this session
    pub session_pubkey: Pubkey,  // Ephemeral keypair (stored client-side)
    pub created_at: i64,
    pub expires_at: i64,
    pub max_cal_claims: u64,
    pub cal_claimed: u64,
    pub max_completions: u64,
    pub completions_recorded: u64,
    pub is_revoked: bool,
    pub bump: u8,
}

// Instruction: Create session (requires main wallet signature)
pub fn create_session(
    ctx: Context<CreateSession>,
    session_pubkey: Pubkey,
    duration_seconds: i64,
    max_cal_claims: u64,
    max_completions: u64,
) -> Result<()>

// Instruction: Use session (requires session keypair signature)
pub fn claim_cal_with_session(ctx: Context<ClaimCalWithSession>) -> Result<()>

// Instruction: Revoke session (main wallet can kill anytime)
pub fn revoke_session(ctx: Context<RevokeSession>) -> Result<()>
```

### Phase 3: Optional Spending Account (If Needed)
Only if users want fund isolation:

```rust
// New PDA: Spending Account (STEPN-style)
#[account]
pub struct SpendingAccount {
    pub owner: Pubkey,
    pub dung_balance: u64,
    pub cal_balance: u64,  // Move CAL here from UserState
    pub locked_for_swanny: u64,
    pub bump: u8,
}

// User deposits DUNG from ATA into spending account
// Game actions draw from spending account
// User withdraws back to ATA when done
```

---

## Questions to Decide

### Q1: Do we need on-chain CAL at all?

| Option | Pros | Cons |
|--------|------|------|
| **Keep CAL on-chain** | Verifiable, can't be faked | Gas costs, complexity |
| **Move CAL off-chain** | Free, fast, simpler | Trust backend, no composability |
| **Hybrid: Settle on-chain weekly** | Best of both? | Complexity |

**Recommendation:** Keep CAL on-chain for launch. It's the "energy" that converts to DUNG - should be verifiable.

### Q2: Session keys - build or use existing?

| Option | Pros | Cons |
|--------|------|------|
| **Build our own** | Full control, custom scoping | Time, audits |
| **Use MagicBlock/Gum SDK** | Battle-tested, maintained | Dependency, may not fit exactly |
| **Skip session keys** | Simpler | Bad UX if frequent txs |

**Recommendation:** Start without session keys. Add them only if UX becomes painful. Points period = no on-chain actions = no need.

### Q3: Spending account - STEPN style?

| Option | Pros | Cons |
|--------|------|------|
| **Yes, add spending account** | Fund isolation, familiar UX | Friction, feels custodial |
| **No, use ATAs directly** | Standard Solana flow | Mixed game/personal funds |

**Recommendation:** No spending account. We're not STEPN - we don't have shoe repairs, energy refills, etc. Our high-frequency actions are off-chain (ride uploads, points).

---

## Final Recommendation

```
┌───────────────────────────────────────────────────────┐
│              RECOMMENDED ARCHITECTURE                 │
├───────────────────────────────────────────────────────┤
│                                                       │
│  CURRENT STATE (Points removed April 2026):           │
│    - CAL/DUNG on-chain via Solana devnet              │
│    - Wallet needed for: connect, stake, harvest       │
│    - On-chain transactions for all token operations   │
│                                                       │
│  POST-TGE (Phase 1):                                 │
│    - UserState PDA for CAL + stats                   │
│    - DUNG in standard ATA                            │
│    - VaultStake PDAs for staking positions           │
│    - Wallet signs everything (accept popup friction) │
│                                                       │
│  POST-TGE (Phase 2, if needed):                      │
│    - Add session keys for frequent actions           │
│    - Scope: CAL claims, completion records           │
│    - High-value still needs main wallet              │
│                                                       │
│  NEVER:                                              │
│    - Custodial anything                              │
│    - Store keys server-side                          │
│    - Spending account (unnecessary complexity)       │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## PDA Summary (Post-TGE)

| PDA | Seeds | Purpose |
|-----|-------|---------|
| `UserState` | `[USER_SEED, owner]` | CAL balance, stats, bio score |
| `VaultCompletion` | `[COMPLETION_SEED, user, vault_id]` | User's completion record per vault |
| `VaultStake` | `[STAKE_SEED, user, vault_id]` | User's staking position per vault |
| `VaultLeaderboard` | `[LEADERBOARD_SEED, vault_id]` | Top 10 times per vault |
| `VaultSwannySeat` | `[SWANNY_SEED, vault_id, seat_idx]` | Swanny seat lock state |
| `BeetleCard` | `[BEETLE_SEED, owner, type, scope]` | Soulbound effort NFT |
| `SessionKey` (Phase 2) | `[SESSION_SEED, owner, session_pubkey]` | Ephemeral delegated signer |

---

## Action Items

1. **Decide:** Session keys now or later?
2. **Decide:** CAL on-chain vs off-chain?
3. **Decide:** Any spending account features?
4. **Document:** Finalize PDA schema
5. **Proceed:** Continue Anchor development with chosen architecture

---

---

## Appendix A: Why NOT Spending Accounts

**What is a "Spending Account"?**

STEPN-style pattern where users deposit funds into an in-app PDA before they can play:

```
User Wallet (real) ──deposit──► Spending PDA ──game actions──► ...
                   ◄──withdraw──
```

**Why STEPN needs it:**
- Shoe repairs (micro-transactions, many per day)
- Gem socketing (frequent)
- Energy refills (frequent)
- Minting new shoes (burns tokens)
- Mystery box opening

**Why we DON'T need it:**

| Boulder Rollers Action | Frequency | On-chain? |
|------------------------|-----------|-----------|
| Upload ride | 1-3x/day | ❌ Off-chain |
| Earn CAL | Per ride | ✅ On-chain (batch pipeline) |
| Claim CAL | 1x/day max | ✅ On-chain (simple) |
| Stake DUNG | Rare | ✅ On-chain (should sign) |
| Unstake DUNG | Rare | ✅ On-chain (should sign) |
| Claim swanny | Very rare | ✅ On-chain (should sign) |
| Claim rewards | Weekly | ✅ On-chain (could batch) |

**Our high-frequency loop is off-chain.** Adding a spending account creates friction (deposit/withdraw) without solving any real problem.

---

## Appendix B: Session Keys Deep Dive

### The Hyperliquid Model

[Hyperliquid's API wallet system](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets) is a good mental model:

```
┌─────────────────────────────────────────────────────┐
│  HYPERLIQUID AGENT WALLET ARCHITECTURE              │
├─────────────────────────────────────────────────────┤
│                                                     │
│  MASTER WALLET (your real keys)                     │
│       │                                             │
│       │ One-time authorization                      │
│       ▼                                             │
│  ┌─────────────────────────────────────────────┐   │
│  │  API WALLET (agent)                         │   │
│  │                                             │   │
│  │  - Has its own keypair                      │   │
│  │  - Signs on behalf of master                │   │
│  │  - CAN: place orders, cancel, modify        │   │
│  │  - CANNOT: withdraw funds                   │   │
│  │  - Expires / can be revoked                 │   │
│  │  - Nonces tracked separately                │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  KEY INSIGHT: "API wallets are only used to sign.  │
│  To query account data, you must pass the actual   │
│  address of the master account."                   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Why it's great:**
- Bots/APIs can trade without exposing main private key
- Scoped permissions (no withdrawals)
- Revocable at any time
- Clean separation of concerns

### The MagicBlock/Gum Model (Solana)

[Session keys on Solana](https://blog.magicblock.gg/session-keys/) follow similar principles:

```rust
// From solana-game-preset lumberjack example
#[session_auth_or(
    ctx.accounts.player.authority.key() == ctx.accounts.signer.key(),
    GameErrorCode::WrongAuthority
)]
pub fn chop_tree(ctx: Context<ChopTree>, counter: u64) -> Result<()> {
    // Player can use session token OR main wallet
    // ...
}
```

**How it works:**
1. User connects main wallet
2. Frontend generates ephemeral keypair (stored in browser)
3. Main wallet signs a `create_session` transaction
4. Session token PDA created, links ephemeral key → main wallet
5. Game instructions accept session key OR main wallet signature
6. `session_auth_or` macro validates either signer

### Session Keys: Complexity Breakdown

**On-Chain (Anchor program changes):**

```rust
// 1. Add dependency
// Cargo.toml
[dependencies]
session-keys = { version = "0.2", features = ["no-entrypoint"] }

// 2. Import in lib.rs
use session_keys::{SessionError, SessionToken, session_auth_or, Session};

// 3. Add Session derive to instruction accounts
#[derive(Accounts, Session)]  // <-- Add Session
pub struct ClaimCal<'info> {
    #[account(mut)]
    pub user_state: Account<'info, UserState>,

    // Session token is optional - allows main wallet OR session
    #[session(
        signer = signer,           // The actual signer (session key or main)
        authority = user_state.owner  // The authority we're checking against
    )]
    pub session_token: Option<Account<'info, SessionToken>>,

    pub signer: Signer<'info>,
}

// 4. Add macro to instruction handler
#[session_auth_or(
    ctx.accounts.user_state.owner == ctx.accounts.signer.key(),
    ErrorCode::Unauthorized
)]
pub fn claim_cal(ctx: Context<ClaimCal>) -> Result<()> {
    // Works with session key OR main wallet
}
```

**Complexity: MEDIUM** - It's mostly macro-driven. The `session-keys` crate handles validation.

**Off-Chain (Frontend changes):**

```typescript
// 1. Generate ephemeral keypair on login
const sessionKeypair = Keypair.generate();
localStorage.setItem('sessionKey', bs58.encode(sessionKeypair.secretKey));

// 2. Create session token (one-time, main wallet signs)
const createSessionIx = await program.methods
  .createSession({
    targetProgram: BOULDER_ROLLERS_PROGRAM_ID,
    validUntil: new BN(Date.now() / 1000 + 7 * 24 * 60 * 60), // 7 days
  })
  .accounts({
    sessionToken: sessionTokenPDA,
    sessionSigner: sessionKeypair.publicKey,
    authority: mainWallet.publicKey,
  })
  .instruction();

// Main wallet signs this one time
await wallet.signTransaction(createSessionTx);

// 3. Future transactions use session keypair
const claimCalIx = await program.methods
  .claimCal()
  .accounts({
    userState: userStatePDA,
    sessionToken: sessionTokenPDA,  // Pass the session
    signer: sessionKeypair.publicKey,  // Session key signs
  })
  .instruction();

// Session keypair signs - no popup!
const tx = new Transaction().add(claimCalIx);
tx.sign(sessionKeypair);  // Local signing, no wallet popup
await connection.sendTransaction(tx);
```

**Complexity: MEDIUM** - Need to manage keypair lifecycle in localStorage/sessionStorage.

### Session Keys: What Could Go Wrong

| Risk | Mitigation |
|------|------------|
| Session key stolen | Short expiry (7 days), scoped to our program only |
| User clears browser | Session lost, must re-create (one popup) |
| Key rotation | Revoke old session, create new one |
| Multiple devices | Each device has own session key |
| Nonce collisions | Increment counter per action (like lumberjack) |

### Our Implementation Plan

**Phase 1: ~~Skip session keys (Points Period)~~ — Points removed**
- ~~All actions are off-chain~~ (CAL/DUNG now on-chain)
- Session keys may be reconsidered for frequent on-chain actions

**Phase 2: Add session keys (Post-TGE, if needed)**

Only scope to low-risk, frequent actions:

| Action | Session Key? | Why |
|--------|--------------|-----|
| `claim_cal` | ✅ Yes | Daily, low value |
| `record_completion` | ✅ Yes | Per ride, just records time |
| `update_leaderboard` | ✅ Yes | Just updates position |
| `stake_dung` | ❌ No | High value, require main wallet |
| `unstake_dung` | ❌ No | Withdrawal, require main wallet |
| `claim_swanny` | ❌ No | Locks 1000 DUNG, require main wallet |
| `distribute_rewards` | ❌ No | Admin action |

**Estimated effort:** 2-3 days for Anchor changes, 1-2 days for frontend.

---

## Appendix C: Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12-26 | CAL stays on-chain | Crypto natives want to speculate/trade |
| 2024-12-26 | No spending account | Our high-frequency loop is off-chain |
| 2024-12-26 | Session keys = Phase 2 | Don't need until post-TGE on-chain actions |

---

## Sources

- [Solana PDA Documentation](https://solana.com/docs/core/pda)
- [MagicBlock Session Keys](https://blog.magicblock.gg/session-keys/)
- [Helius PDA Guide](https://www.helius.dev/blog/solana-pda)
- [Solana Auto-Approve Guide](https://solana.com/developers/guides/advanced/auto-approve)
- [STEPN Support Docs](https://support.stepn.com/hc/en-us/articles/7328627333657-How-to-Fund-your-STEPN-Account)
- [Hyperliquid API Wallets](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets)
- [Hyperliquid Signing Docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/signing)
- [MagicBlock Session Keys GitHub](https://github.com/magicblock-labs/session-keys)
- [Solana Game Preset (Lumberjack)](https://github.com/solana-developers/solana-game-preset)
