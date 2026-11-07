# Boulder Rollers - Technical Specification V2

> **Note:** Protocol mechanics have moved to `history/BR_cal_allocation_refactor_spec.md`.  
> This document is retained for historical context and may reference archived programs.

**Solana Program Architecture**

December 2025

---

## Overview

This document specifies the Solana program architecture for Boulder Rollers post-TGE. Legacy programs (`proof_verifier`, `dung_mint`) are now archived; active work is centered on `boulder_rollers` and the CAL allocation pipeline.

---

## 1. Program Summary

### Existing Programs

| Program | ID | Purpose |
|---------|-----|---------|
| `proof_verifier` | `Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC` | Records ride proofs |
| `dung_mint` | `A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ` | Mints DUNG from proofs |
| `boulder_rollers` | `HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst` | Vaults, staking, CAL allocation, DUNG rewards |

### New Program

| Program | Purpose |
|---------|---------|
| `tokenomics` | POL vault, achievements, cards, upgrades, governance |

---

## 2. Account Structures

### 2.1 POL Vault

```rust
// Seeds: ["pol_state"]
#[account]
pub struct PolState {
    pub admin: Pubkey,                  // 32 - Admin wallet
    pub dung_mint: Pubkey,              // 32 - DUNG token mint
    pub usdc_mint: Pubkey,              // 32 - USDC mint
    pub dung_vault: Pubkey,             // 32 - PDA token account
    pub usdc_vault: Pubkey,             // 32 - PDA token account
    pub lp_vault: Pubkey,               // 32 - LP token storage
    pub pumpswap_pool: Pubkey,          // 32 - PumpSwap pool address
    pub burn_bps: u16,                  // 2  - Basis points to burn (3000 = 30%)
    pub pol_bps: u16,                   // 2  - Basis points to POL (2000 = 20%)
    pub treasury_bps: u16,              // 2  - Basis points to treasury (5000 = 50%)
    pub swap_threshold: u64,            // 8  - Trigger TWAP at this balance
    pub total_burned: u64,              // 8  - Lifetime burned
    pub total_to_pol: u64,              // 8  - Lifetime to POL
    pub total_to_treasury: u64,         // 8  - Lifetime to treasury
    pub paused: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 32*7 + 2*3 + 8*4 + 1 + 1 = 272 bytes

// Seeds: ["pol_vault", "dung"]
// Standard SPL TokenAccount - holds accumulated DUNG

// Seeds: ["pol_vault", "usdc"]
// Standard SPL TokenAccount - holds swapped USDC

// Seeds: ["pol_vault", "lp"]
// Standard SPL TokenAccount - holds LP tokens
```

### 2.2 Achievements

```rust
// Seeds: ["achievement_config"]
#[account]
pub struct AchievementConfig {
    pub admin: Pubkey,                  // 32
    pub next_type_id: u16,              // 2
    pub paused: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 32 + 2 + 1 + 1 = 44 bytes

// Seeds: ["achievement_type", type_id.to_le_bytes()]
#[account]
pub struct AchievementType {
    pub type_id: u16,                   // 2
    pub name: [u8; 32],                 // 32
    pub category: AchievementCategory,  // 1
    pub threshold: u64,                 // 8  - e.g., 100 for 100km
    pub gates_level: u8,                // 1  - Which card level this gates (0 = none)
    pub metadata_uri: [u8; 128],        // 128
    pub active: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 2 + 32 + 1 + 8 + 1 + 128 + 1 + 1 = 182 bytes

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq)]
pub enum AchievementCategory {
    Distance = 0,           // Lifetime km
    SegmentChallenges = 1,  // Segment completions
    Streak = 2,             // Consecutive days
    Leaderboard = 3,        // Top 10, Top 3, KOM
    TSS = 4,                // Lifetime TSS
    WattsPerKg = 5,         // w/kg verification
}

// Seeds: ["user_achievement", wallet, type_id.to_le_bytes()]
#[account]
pub struct UserAchievement {
    pub wallet: Pubkey,                 // 32
    pub achievement_type: u16,          // 2
    pub earned_at: i64,                 // 8
    pub value: u64,                     // 8  - Actual value achieved
    pub proof_id: [u8; 16],             // 16 - Link to proof_verifier
    pub active: bool,                   // 1  - Can be revoked (e.g., lost KOMs)
    pub bump: u8,                       // 1
}
// Size: 8 + 32 + 2 + 8 + 8 + 16 + 1 + 1 = 76 bytes
```

### 2.3 Beetle Cards

```rust
// Seeds: ["card_config"]
#[account]
pub struct CardConfig {
    pub admin: Pubkey,                  // 32
    pub collection_mint: Pubkey,        // 32 - Metaplex collection
    pub base_uri: [u8; 128],            // 128
    pub max_level: u8,                  // 1  - 10
    pub base_upgrade_cost: u64,         // 8  - 25 DUNG (with decimals)
    pub cost_multiplier_bps: u16,       // 2  - 20000 = 2x per level
    pub cards_minted: u64,              // 8
    pub paused: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 32*2 + 128 + 1 + 8 + 2 + 8 + 1 + 1 = 221 bytes

// Seeds: ["beetle_card", wallet]
#[account]
pub struct BeetleCard {
    pub owner: Pubkey,                  // 32
    pub mint: Pubkey,                   // 32 - NFT mint address
    pub level: u8,                      // 1  - 1-10
    pub slots_unlocked: u8,             // 1  - 0-3
    pub total_dung_spent: u64,          // 8
    pub created_at: i64,                // 8
    pub last_upgrade: i64,              // 8
    pub attributes: CardAttributes,     // 32
    pub bump: u8,                       // 1
}
// Size: 8 + 32*2 + 1*2 + 8*3 + 32 + 1 = 130 bytes

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Default)]
pub struct CardAttributes {
    pub boulder_tier: u8,               // 1
    pub legs_tier: u8,                  // 1
    pub trail_tier: u8,                 // 1
    pub headgear_tier: u8,              // 1
    pub background_tier: u8,            // 1
    pub shell_tier: u8,                 // 1
    pub antennae_tier: u8,              // 1
    pub aura_tier: u8,                  // 1
    pub reserved: [u8; 24],             // 24 - Future expansion
}
// Size: 32 bytes
```

### 2.4 Marketplace

```rust
// Seeds: ["marketplace_config"]
#[account]
pub struct MarketplaceConfig {
    pub admin: Pubkey,                  // 32
    pub fee_bps: u16,                   // 2  - 1000 = 10%
    pub fee_destination: Pubkey,        // 32 - POL vault or treasury
    pub paused: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 32 + 2 + 32 + 1 + 1 = 76 bytes

// Seeds: ["listing", seller, attribute_type]
#[account]
pub struct AttributeListing {
    pub seller: Pubkey,                 // 32
    pub attribute_type: u8,             // 1  - Which attribute slot
    pub tier: u8,                       // 1  - Tier being sold
    pub price: u64,                     // 8  - DUNG price
    pub original_earner: Pubkey,        // 32 - Who earned it originally
    pub created_at: i64,                // 8
    pub active: bool,                   // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 32 + 1 + 1 + 8 + 32 + 8 + 1 + 1 = 92 bytes
```

### 2.5 Governance

```rust
// Seeds: ["governance"]
#[account]
pub struct GovernanceConfig {
    pub multisig: Pubkey,               // 32 - Squads multisig
    pub timelock_seconds: u64,          // 8  - 172800 = 2 days
    pub proposal_count: u64,            // 8
    pub bump: u8,                       // 1
}
// Size: 8 + 32 + 8 + 8 + 1 = 57 bytes

// Seeds: ["proposal", proposal_id.to_le_bytes()]
#[account]
pub struct Proposal {
    pub id: u64,                        // 8
    pub proposer: Pubkey,               // 32
    pub target_program: Pubkey,         // 32
    pub instruction_data: Vec<u8>,      // 4 + max 512
    pub created_at: i64,                // 8
    pub execute_after: i64,             // 8
    pub executed: bool,                 // 1
    pub cancelled: bool,                // 1
    pub bump: u8,                       // 1
}
// Size: 8 + 8 + 32*2 + (4 + 512) + 8*2 + 1*3 = 615 bytes max
```

---

## 3. Instructions

### 3.1 POL Vault Instructions

```rust
/// Initialize POL vault and related accounts
pub fn initialize_pol(
    ctx: Context<InitializePol>,
    burn_bps: u16,          // 3000 = 30%
    pol_bps: u16,           // 2000 = 20%
    treasury_bps: u16,      // 5000 = 50%
    swap_threshold: u64,    // 5000 DUNG (with decimals)
) -> Result<()>

/// Process incoming fees with split
pub fn process_fee_split(
    ctx: Context<ProcessFeeSplit>,
    amount: u64,
    source: FeeSource,
) -> Result<()>

#[derive(AnchorSerialize, AnchorDeserialize)]
pub enum FeeSource {
    SegmentCreation,
    StakingExit,
    HarvestFee,
    CardUpgrade,
    Marketplace,
}

/// Trigger TWAP swap when threshold reached (permissionless crank)
pub fn trigger_swap(
    ctx: Context<TriggerSwap>,
    max_amount: u64,
) -> Result<()>

/// Add accumulated DUNG + USDC to PumpSwap LP
pub fn add_liquidity(
    ctx: Context<AddLiquidity>,
) -> Result<()>

/// Update POL parameters (governance-gated)
pub fn update_pol_params(
    ctx: Context<UpdatePolParams>,
    new_burn_bps: Option<u16>,
    new_pol_bps: Option<u16>,
    new_treasury_bps: Option<u16>,
    new_threshold: Option<u64>,
) -> Result<()>
```

### 3.2 Achievement Instructions

```rust
/// Initialize achievement system
pub fn initialize_achievements(
    ctx: Context<InitializeAchievements>,
) -> Result<()>

/// Create new achievement type (admin only)
pub fn create_achievement_type(
    ctx: Context<CreateAchievementType>,
    name: String,
    category: AchievementCategory,
    threshold: u64,
    gates_level: u8,
    metadata_uri: String,
) -> Result<()>

/// Award achievement to user (backend authority)
pub fn award_achievement(
    ctx: Context<AwardAchievement>,
    type_id: u16,
    value: u64,
    proof_id: [u8; 16],
) -> Result<()>

/// Revoke achievement (for revocable types like active KOMs)
pub fn revoke_achievement(
    ctx: Context<RevokeAchievement>,
    type_id: u16,
) -> Result<()>

/// Check if user has achievement (CPI target)
pub fn verify_achievement(
    ctx: Context<VerifyAchievement>,
    wallet: Pubkey,
    type_id: u16,
) -> Result<bool>
```

### 3.3 Card Instructions

```rust
/// Initialize card system with Metaplex collection
pub fn initialize_cards(
    ctx: Context<InitializeCards>,
    collection_mint: Pubkey,
    base_uri: String,
    base_upgrade_cost: u64,
) -> Result<()>

/// Mint beetle card for user (one per wallet)
pub fn mint_beetle_card(
    ctx: Context<MintBeetleCard>,
) -> Result<()>

/// Upgrade card level (burns DUNG, checks achievement gate)
pub fn upgrade_card(
    ctx: Context<UpgradeCard>,
) -> Result<()>

/// Unlock additional attribute slot
pub fn unlock_slot(
    ctx: Context<UnlockSlot>,
    slot_index: u8,    // 1, 2, or 3
) -> Result<()>

/// Update card visual attributes
pub fn update_attributes(
    ctx: Context<UpdateAttributes>,
    attributes: CardAttributes,
) -> Result<()>
```

### 3.4 Marketplace Instructions

```rust
/// Initialize marketplace
pub fn initialize_marketplace(
    ctx: Context<InitializeMarketplace>,
    fee_bps: u16,
) -> Result<()>

/// List attribute for sale
pub fn list_attribute(
    ctx: Context<ListAttribute>,
    attribute_type: u8,
    tier: u8,
    price: u64,
) -> Result<()>

/// Purchase listed attribute
pub fn purchase_attribute(
    ctx: Context<PurchaseAttribute>,
) -> Result<()>

/// Cancel listing
pub fn cancel_listing(
    ctx: Context<CancelListing>,
) -> Result<()>
```

### 3.5 Governance Instructions

```rust
/// Initialize governance with multisig
pub fn initialize_governance(
    ctx: Context<InitializeGovernance>,
    multisig: Pubkey,
    timelock_seconds: u64,
) -> Result<()>

/// Create proposal (multisig signer required)
pub fn create_proposal(
    ctx: Context<CreateProposal>,
    target_program: Pubkey,
    instruction_data: Vec<u8>,
) -> Result<()>

/// Execute proposal after timelock (permissionless)
pub fn execute_proposal(
    ctx: Context<ExecuteProposal>,
    proposal_id: u64,
) -> Result<()>

/// Cancel proposal (multisig only)
pub fn cancel_proposal(
    ctx: Context<CancelProposal>,
    proposal_id: u64,
) -> Result<()>
```

---

## 4. Upgrade Cost Calculation

```rust
/// Calculate DUNG cost for upgrading from current_level to next level
/// Formula: 25 * 2^(current_level - 1) DUNG
pub fn calculate_upgrade_cost(current_level: u8, config: &CardConfig) -> u64 {
    // config.base_upgrade_cost = 25_000_000_000 (25 DUNG with 9 decimals)
    // config.cost_multiplier_bps = 20000 (2x)

    let multiplier = 2u64.pow((current_level - 1) as u32);
    config.base_upgrade_cost.checked_mul(multiplier).unwrap()
}

// Example costs (with 9 decimals):
// L1→2: 25,000,000,000 (25 DUNG)
// L2→3: 50,000,000,000 (50 DUNG)
// L3→4: 100,000,000,000 (100 DUNG)
// L4→5: 200,000,000,000 (200 DUNG)
// L5→6: 400,000,000,000 (400 DUNG)
// L6→7: 800,000,000,000 (800 DUNG)
// L7→8: 1,600,000,000,000 (1,600 DUNG)
// L8→9: 3,200,000,000,000 (3,200 DUNG)
// L9→10: 6,400,000,000,000 (6,400 DUNG)

/// Slot unlock costs
pub const SLOT_COSTS: [u64; 3] = [
    100_000_000_000,    // Slot 1: 100 DUNG
    250_000_000_000,    // Slot 2: 250 DUNG
    500_000_000_000,    // Slot 3: 500 DUNG
];
```

---

## 5. Achievement Gates

```rust
/// Achievement type IDs that gate card levels
pub const LEVEL_GATES: [(u8, u16); 4] = [
    (5, 1),     // L5 requires achievement type 1 (50km/week)
    (7, 2),     // L7 requires achievement type 2 (10 segment challenges)
    (8, 3),     // L8 requires achievement type 3 (Top 10 any segment)
    (9, 4),     // L9 requires achievement type 4 (30-day streak)
];

/// L10 Elite Gate - requires ALL of these achievements
pub const L10_REQUIREMENTS: [u16; 4] = [
    10,     // 5+ Active KOMs
    11,     // 4.0+ w/kg verified
    12,     // 60-day streak
    13,     // 50,000+ lifetime TSS
];

/// Check if upgrade is allowed
pub fn check_upgrade_gate(
    current_level: u8,
    user_achievements: &[UserAchievement],
) -> Result<()> {
    let target_level = current_level + 1;

    // Check standard gates
    for (gate_level, required_type) in LEVEL_GATES {
        if target_level == gate_level {
            require!(
                user_achievements.iter().any(|a|
                    a.achievement_type == required_type && a.active
                ),
                TokenomicsError::AchievementGateNotMet
            );
        }
    }

    // Check L10 elite gate
    if target_level == 10 {
        for required in L10_REQUIREMENTS {
            require!(
                user_achievements.iter().any(|a|
                    a.achievement_type == required && a.active
                ),
                TokenomicsError::EliteGateNotMet
            );
        }
    }

    Ok(())
}
```

---

## 6. Fee Split Logic

```rust
/// Process fee with configurable split
pub fn process_fee_split(
    ctx: Context<ProcessFeeSplit>,
    amount: u64,
    source: FeeSource,
) -> Result<()> {
    let pol_state = &ctx.accounts.pol_state;

    // Calculate splits
    let burn_amount = amount
        .checked_mul(pol_state.burn_bps as u64)
        .unwrap()
        .checked_div(10000)
        .unwrap();

    let pol_amount = amount
        .checked_mul(pol_state.pol_bps as u64)
        .unwrap()
        .checked_div(10000)
        .unwrap();

    let treasury_amount = amount
        .checked_sub(burn_amount)
        .unwrap()
        .checked_sub(pol_amount)
        .unwrap();

    // Burn portion
    token::burn(
        ctx.accounts.burn_context(),
        burn_amount,
    )?;

    // Transfer to POL vault
    token::transfer(
        ctx.accounts.pol_transfer_context(),
        pol_amount,
    )?;

    // Transfer to treasury
    token::transfer(
        ctx.accounts.treasury_transfer_context(),
        treasury_amount,
    )?;

    // Emit event
    emit!(FeeSplitEvent {
        source,
        total: amount,
        burned: burn_amount,
        to_pol: pol_amount,
        to_treasury: treasury_amount,
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}
```

---

## 7. Integration Points

### 7.1 Modify `boulder_rollers::create_segment`

```rust
// Current: Direct burn + SOL transfer
// New: CPI to tokenomics for fee split

pub fn create_segment(ctx: Context<CreateSegment>, ...) -> Result<()> {
    // ... existing validation ...

    // Route DUNG fee through POL split
    let cpi_program = ctx.accounts.tokenomics_program.to_account_info();
    let cpi_accounts = ProcessFeeSplit {
        pol_state: ctx.accounts.pol_state.to_account_info(),
        payer_token_account: ctx.accounts.creator_dung_account.to_account_info(),
        pol_vault: ctx.accounts.pol_dung_vault.to_account_info(),
        treasury: ctx.accounts.treasury_token_account.to_account_info(),
        dung_mint: ctx.accounts.dung_mint.to_account_info(),
        token_program: ctx.accounts.token_program.to_account_info(),
    };
    let cpi_ctx = CpiContext::new(cpi_program, cpi_accounts);

    tokenomics::cpi::process_fee_split(
        cpi_ctx,
        SEGMENT_CREATION_FEE,  // 100 DUNG
        FeeSource::SegmentCreation,
    )?;

    // SOL still goes to treasury directly (unchanged)
    // ...
}
```

### 7.2 Backend Achievement Integration

```python
# backend/app/services/achievement_service.py

class AchievementService:
    async def check_and_award(self, user_id: str, ride_data: dict):
        """Check if ride triggers any achievements and award on-chain."""

        user = await self.repo.get_user(user_id)

        # Check distance achievements
        if user.lifetime_km >= 100 and not await self.has_achievement(user_id, 1):
            await self.award_on_chain(user.wallet, type_id=1, value=user.lifetime_km)

        # Check streak achievements
        if user.current_streak >= 30 and not await self.has_achievement(user_id, 4):
            await self.award_on_chain(user.wallet, type_id=4, value=user.current_streak)

        # Check w/kg (requires recent ride with power)
        if ride_data.get('avg_power') and user.weight_kg:
            wkg = ride_data['avg_power'] / user.weight_kg
            if wkg >= 4.0:
                await self.award_on_chain(user.wallet, type_id=11, value=int(wkg * 100))

    async def award_on_chain(self, wallet: str, type_id: int, value: int):
        """Submit achievement award transaction to Solana."""
        ix = award_achievement_instruction(
            wallet=wallet,
            type_id=type_id,
            value=value,
            proof_id=generate_proof_id(),
        )
        await self.solana_client.send_transaction(ix)
```

---

## 8. Events

```rust
#[event]
pub struct FeeSplitEvent {
    pub source: FeeSource,
    pub total: u64,
    pub burned: u64,
    pub to_pol: u64,
    pub to_treasury: u64,
    pub timestamp: i64,
}

#[event]
pub struct AchievementAwarded {
    pub wallet: Pubkey,
    pub achievement_type: u16,
    pub value: u64,
    pub timestamp: i64,
}

#[event]
pub struct CardUpgraded {
    pub wallet: Pubkey,
    pub from_level: u8,
    pub to_level: u8,
    pub cost: u64,
    pub timestamp: i64,
}

#[event]
pub struct AttributePurchased {
    pub buyer: Pubkey,
    pub seller: Pubkey,
    pub attribute_type: u8,
    pub tier: u8,
    pub price: u64,
    pub fee: u64,
    pub timestamp: i64,
}

#[event]
pub struct LiquidityAdded {
    pub dung_amount: u64,
    pub usdc_amount: u64,
    pub lp_received: u64,
    pub timestamp: i64,
}
```

---

## 9. Error Codes

```rust
#[error_code]
pub enum TokenomicsError {
    #[msg("Invalid fee split configuration")]
    InvalidFeeSplit,

    #[msg("POL vault is paused")]
    PolPaused,

    #[msg("Swap threshold not reached")]
    SwapThresholdNotReached,

    #[msg("Achievement already awarded")]
    AchievementAlreadyAwarded,

    #[msg("Achievement type not found")]
    AchievementTypeNotFound,

    #[msg("Card already minted for this wallet")]
    CardAlreadyMinted,

    #[msg("Card is at max level")]
    CardMaxLevel,

    #[msg("Achievement gate not met for this level")]
    AchievementGateNotMet,

    #[msg("Elite gate requirements not met")]
    EliteGateNotMet,

    #[msg("All slots already unlocked")]
    AllSlotsUnlocked,

    #[msg("Attribute not tradeable")]
    AttributeNotTradeable,

    #[msg("Listing not found")]
    ListingNotFound,

    #[msg("Insufficient DUNG balance")]
    InsufficientBalance,

    #[msg("Proposal still in timelock")]
    ProposalInTimelock,

    #[msg("Proposal already executed")]
    ProposalAlreadyExecuted,

    #[msg("Unauthorized")]
    Unauthorized,
}
```

---

## 10. File Structure

```
protocol/anchor/programs/tokenomics/
├── Cargo.toml
└── src/
    ├── lib.rs                      # Program entry
    ├── errors.rs                   # TokenomicsError
    ├── constants.rs                # Seeds, costs, gates
    ├── state/
    │   ├── mod.rs
    │   ├── pol.rs                  # PolState
    │   ├── achievements.rs         # AchievementConfig, AchievementType, UserAchievement
    │   ├── cards.rs                # CardConfig, BeetleCard, CardAttributes
    │   ├── marketplace.rs          # MarketplaceConfig, AttributeListing
    │   └── governance.rs           # GovernanceConfig, Proposal
    ├── instructions/
    │   ├── mod.rs
    │   ├── pol/
    │   │   ├── mod.rs
    │   │   ├── initialize.rs
    │   │   ├── process_fee_split.rs
    │   │   ├── trigger_swap.rs
    │   │   ├── add_liquidity.rs
    │   │   └── update_params.rs
    │   ├── achievements/
    │   │   ├── mod.rs
    │   │   ├── initialize.rs
    │   │   ├── create_type.rs
    │   │   ├── award.rs
    │   │   ├── revoke.rs
    │   │   └── verify.rs
    │   ├── cards/
    │   │   ├── mod.rs
    │   │   ├── initialize.rs
    │   │   ├── mint.rs
    │   │   ├── upgrade.rs
    │   │   ├── unlock_slot.rs
    │   │   └── update_attributes.rs
    │   ├── marketplace/
    │   │   ├── mod.rs
    │   │   ├── initialize.rs
    │   │   ├── list.rs
    │   │   ├── purchase.rs
    │   │   └── cancel.rs
    │   └── governance/
    │       ├── mod.rs
    │       ├── initialize.rs
    │       ├── create_proposal.rs
    │       ├── execute_proposal.rs
    │       └── cancel_proposal.rs
    └── events.rs                   # Event definitions
```

---

## 11. Implementation Phases

### Phase 1: POL Vault (Week 1-2)
- [ ] Create `tokenomics` program skeleton
- [ ] Implement `PolState` and vault accounts
- [ ] Implement `process_fee_split`
- [ ] Modify `boulder_rollers` to CPI for segment fees
- [ ] Basic tests

### Phase 2: Achievements (Week 2-3)
- [ ] Implement achievement accounts
- [ ] Implement `award_achievement` instruction
- [ ] Backend integration for auto-awarding
- [ ] Create predefined achievement types
- [ ] Tests

### Phase 3: Cards (Week 3-4)
- [ ] Set up Metaplex collection
- [ ] Implement `BeetleCard` accounts
- [ ] Implement `mint_beetle_card`
- [ ] Implement `upgrade_card` with gates
- [ ] Implement `unlock_slot`
- [ ] Tests

### Phase 4: Marketplace (Week 4-5)
- [ ] Implement marketplace accounts
- [ ] Implement listing/purchase flow
- [ ] Fee integration with POL
- [ ] Tests

### Phase 5: Governance (Week 5-6)
- [ ] Set up Squads multisig
- [ ] Implement proposal lifecycle
- [ ] Add governance guards to all params
- [ ] Tests

### Phase 6: Integration (Week 6-7)
- [ ] Full integration tests
- [ ] Devnet deployment
- [ ] Backend integration tests
- [ ] Security review
- [ ] Documentation

---

## 12. Security Considerations

1. **PDA Authority** - All vaults use program-derived authorities
2. **Reentrancy** - Use `#[access_control]` and careful ordering
3. **Overflow** - Use `checked_*` math everywhere
4. **Governance Timelock** - 2-day minimum for parameter changes
5. **Achievement Authority** - Only backend can award (trusted signer)
6. **Fee Validation** - Ensure burn + pol + treasury = 10000 bps
7. **Upgrade Authorization** - Ownership + achievement verification

---

## 13. Testing Strategy

### Unit Tests
- Fee split calculations
- Upgrade cost calculations
- Achievement gate checks
- LP ratio calculations

### Integration Tests
- Full upgrade flow (mint → upgrade → gate check)
- Fee split → POL accumulation → swap → LP
- Achievement award → gate unlock → upgrade
- Marketplace listing → purchase → attribute transfer

### Devnet Testing
- End-to-end with real wallets
- Stress testing with multiple users
- Edge case scenarios

---

## 14. Advanced Analytics (Backend)

The power data requirement unlocks analytics that Strava refuses to build. This is a core differentiator.

### 14.1 Data Models

```python
# backend/app/models/analytics.py

class PowerCurvePoint(Base):
    """Power curve data point for a user."""
    __tablename__ = "power_curve_points"

    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), index=True)
    duration_seconds = Column(Integer)      # 1, 5, 10, 30, 60, 300, 600, 1200, 3600...
    power_watts = Column(Integer)           # Best power for this duration
    ride_id = Column(UUID, ForeignKey("rides.id"))
    achieved_at = Column(DateTime)
    season = Column(String(10))             # "2025-Q1", "2025-Q2", etc.

    __table_args__ = (
        UniqueConstraint('user_id', 'duration_seconds', 'season'),
    )

class UserFitnessProfile(Base):
    """User's current fitness metrics."""
    __tablename__ = "user_fitness_profiles"

    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), unique=True)
    ftp = Column(Integer)                   # Functional Threshold Power (watts)
    weight_kg = Column(Float)               # Current weight
    w_per_kg = Column(Float)                # Computed: ftp / weight_kg
    critical_power = Column(Integer)        # CP from bio-passport model
    w_prime = Column(Integer)               # W' anaerobic capacity (joules)
    last_ftp_test = Column(DateTime)
    updated_at = Column(DateTime)

class SegmentLeaderboardEntry(Base):
    """Segment leaderboard with power metrics."""
    __tablename__ = "segment_leaderboard_entries"

    id = Column(UUID, primary_key=True)
    segment_id = Column(UUID, ForeignKey("segments.id"), index=True)
    user_id = Column(UUID, ForeignKey("users.id"), index=True)
    ride_id = Column(UUID, ForeignKey("rides.id"))

    # Time-based (standard)
    elapsed_time_seconds = Column(Integer)

    # Power-based (our advantage)
    avg_power = Column(Integer)
    normalized_power = Column(Integer)
    avg_w_per_kg = Column(Float)            # Key differentiator
    max_power = Column(Integer)
    intensity_factor = Column(Float)        # NP / FTP
    tss = Column(Float)                     # Segment TSS

    # Conditions
    elevation_gain = Column(Float)
    avg_gradient = Column(Float)
    temperature_c = Column(Float)           # From weather API if available
    wind_speed_kmh = Column(Float)          # From weather API

    achieved_at = Column(DateTime)

    __table_args__ = (
        Index('ix_segment_wkg', 'segment_id', 'avg_w_per_kg'),
        Index('ix_segment_time', 'segment_id', 'elapsed_time_seconds'),
    )

class SeasonProgression(Base):
    """Track user progression across seasons."""
    __tablename__ = "season_progressions"

    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), index=True)
    season = Column(String(10))             # "2025-Q1"

    # Volume
    total_rides = Column(Integer)
    total_km = Column(Float)
    total_elevation_m = Column(Float)
    total_tss = Column(Float)

    # Fitness
    start_ftp = Column(Integer)
    end_ftp = Column(Integer)
    peak_ftp = Column(Integer)
    avg_w_per_kg = Column(Float)

    # Achievements
    koms_gained = Column(Integer)
    koms_lost = Column(Integer)
    top_10s = Column(Integer)

    __table_args__ = (
        UniqueConstraint('user_id', 'season'),
    )
```

### 14.2 Power Curve Calculations

```python
# backend/app/services/power_curve_service.py

POWER_CURVE_DURATIONS = [
    1, 5, 10, 15, 20, 30,           # Sprint (seconds)
    60, 120, 180, 300,              # Anaerobic (1-5 min)
    600, 900, 1200, 1800,           # VO2max (10-30 min)
    2400, 3600, 5400, 7200          # Threshold/Endurance (40min-2hr)
]

class PowerCurveService:
    def calculate_best_powers(self, power_data: list[int], sample_rate: int = 1) -> dict:
        """
        Calculate best average power for each standard duration.
        Uses rolling window algorithm.
        """
        results = {}
        n = len(power_data)

        for duration in POWER_CURVE_DURATIONS:
            window_size = duration * sample_rate
            if window_size > n:
                continue

            # Rolling sum for efficiency
            window_sum = sum(power_data[:window_size])
            best_avg = window_sum / window_size

            for i in range(1, n - window_size + 1):
                window_sum = window_sum - power_data[i-1] + power_data[i + window_size - 1]
                avg = window_sum / window_size
                if avg > best_avg:
                    best_avg = avg

            results[duration] = int(best_avg)

        return results

    def update_user_curve(self, user_id: str, ride_id: str, power_data: list[int]):
        """Update user's power curve with new ride data."""
        ride_bests = self.calculate_best_powers(power_data)
        season = self._get_current_season()

        for duration, power in ride_bests.items():
            existing = self.repo.get_power_curve_point(user_id, duration, season)

            if existing is None or power > existing.power_watts:
                self.repo.upsert_power_curve_point(
                    user_id=user_id,
                    duration_seconds=duration,
                    power_watts=power,
                    ride_id=ride_id,
                    season=season
                )

    def compare_to_kom(self, user_id: str, segment_id: str) -> dict:
        """
        Compare user's power curve to the KOM holder's curve.
        Returns gaps at each duration.
        """
        user_curve = self.repo.get_user_curve(user_id)

        # Get KOM holder
        kom = self.repo.get_segment_leader(segment_id, order_by='elapsed_time')
        if not kom:
            return None

        kom_curve = self.repo.get_user_curve(kom.user_id)

        comparison = []
        for duration in POWER_CURVE_DURATIONS:
            user_power = user_curve.get(duration, 0)
            kom_power = kom_curve.get(duration, 0)

            if user_power and kom_power:
                gap_watts = kom_power - user_power
                gap_percent = (gap_watts / kom_power) * 100 if kom_power else 0

                comparison.append({
                    "duration": duration,
                    "user_watts": user_power,
                    "kom_watts": kom_power,
                    "gap_watts": gap_watts,
                    "gap_percent": round(gap_percent, 1)
                })

        return {
            "kom_holder": kom.user_id,
            "kom_time": kom.elapsed_time_seconds,
            "comparison": comparison,
            "weakest_point": max(comparison, key=lambda x: x['gap_percent'])
        }
```

### 14.3 Predictive Segment Time

```python
# backend/app/services/prediction_service.py

class SegmentPredictionService:
    def predict_segment_time(
        self,
        user_id: str,
        segment_id: str
    ) -> dict:
        """
        Predict user's segment time based on their power profile.
        Uses physics-based model with gradient and their FTP/w'.
        """
        user = self.repo.get_user_fitness(user_id)
        segment = self.repo.get_segment(segment_id)

        if not user.ftp or not user.weight_kg:
            return {"error": "FTP and weight required for prediction"}

        # Calculate power required to match segment profile
        # Using simplified physics model
        avg_gradient = segment.elevation_gain / segment.distance_m

        # Rolling resistance + gravity + aero (simplified)
        # P = (m * g * Crr * v) + (m * g * grade * v) + (0.5 * Cd * A * rho * v^3)

        # For climbing-dominant segments, simplified:
        # P ≈ m * g * (Crr + grade) * v
        # v ≈ P / (m * g * (Crr + grade))

        g = 9.81
        Crr = 0.005  # Typical road rolling resistance
        m = user.weight_kg + 8  # Bike + kit

        # Sustainable power (FTP for steady effort, higher for shorter)
        segment_duration_estimate = segment.distance_m / 8  # ~30 km/h rough estimate
        sustainable_power = self._power_for_duration(user, segment_duration_estimate)

        # Calculate speed
        resistance = Crr + avg_gradient
        if resistance <= 0:
            resistance = 0.01  # Prevent division issues on descents

        velocity = sustainable_power / (m * g * resistance)
        predicted_time = segment.distance_m / velocity

        # Get current leaderboard for context
        user_best = self.repo.get_user_segment_best(user_id, segment_id)
        kom = self.repo.get_segment_leader(segment_id)

        return {
            "predicted_time_seconds": int(predicted_time),
            "predicted_time_formatted": self._format_time(predicted_time),
            "sustainable_power_watts": sustainable_power,
            "assumed_w_per_kg": round(sustainable_power / user.weight_kg, 2),
            "your_best": user_best.elapsed_time_seconds if user_best else None,
            "kom_time": kom.elapsed_time_seconds if kom else None,
            "potential_gain_seconds": (user_best.elapsed_time_seconds - predicted_time) if user_best else None,
            "note": "Prediction assumes optimal conditions (no wind, fresh legs)"
        }

    def _power_for_duration(self, user: UserFitnessProfile, duration_seconds: float) -> int:
        """
        Estimate sustainable power for a given duration.
        Uses Critical Power model: P = CP + W'/(t)
        """
        if user.critical_power and user.w_prime:
            cp = user.critical_power
            w_prime = user.w_prime
        else:
            # Fallback: estimate from FTP
            cp = int(user.ftp * 0.95)
            w_prime = 15000  # Default ~15kJ

        if duration_seconds <= 0:
            return cp

        power = cp + (w_prime / duration_seconds)

        # Cap at reasonable sprint power
        max_power = user.ftp * 2.5
        return min(int(power), int(max_power))

    def _format_time(self, seconds: float) -> str:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
```

### 14.4 w/kg Leaderboards

```python
# backend/app/services/leaderboard_service.py

class LeaderboardService:
    def get_segment_leaderboard(
        self,
        segment_id: str,
        order_by: str = "time",  # "time", "w_per_kg", "power"
        limit: int = 50
    ) -> list[dict]:
        """
        Get segment leaderboard with multiple ranking options.
        """
        query = self.db.query(SegmentLeaderboardEntry).filter(
            SegmentLeaderboardEntry.segment_id == segment_id
        )

        if order_by == "time":
            query = query.order_by(SegmentLeaderboardEntry.elapsed_time_seconds.asc())
        elif order_by == "w_per_kg":
            query = query.order_by(SegmentLeaderboardEntry.avg_w_per_kg.desc())
        elif order_by == "power":
            query = query.order_by(SegmentLeaderboardEntry.normalized_power.desc())

        entries = query.limit(limit).all()

        return [
            {
                "rank": i + 1,
                "user_id": e.user_id,
                "username": self.repo.get_username(e.user_id),
                "time_seconds": e.elapsed_time_seconds,
                "time_formatted": self._format_time(e.elapsed_time_seconds),
                "avg_power": e.avg_power,
                "normalized_power": e.normalized_power,
                "w_per_kg": round(e.avg_w_per_kg, 2) if e.avg_w_per_kg else None,
                "tss": round(e.tss, 1) if e.tss else None,
                "achieved_at": e.achieved_at.isoformat()
            }
            for i, e in enumerate(entries)
        ]

    def get_user_segment_analysis(
        self,
        user_id: str,
        segment_id: str
    ) -> dict:
        """
        Deep analysis of user's segment performance.
        """
        entries = self.repo.get_user_segment_attempts(user_id, segment_id)

        if not entries:
            return {"attempts": 0}

        best_time = min(entries, key=lambda e: e.elapsed_time_seconds)
        best_wkg = max(entries, key=lambda e: e.avg_w_per_kg or 0)

        # Calculate progression
        sorted_by_date = sorted(entries, key=lambda e: e.achieved_at)
        times = [e.elapsed_time_seconds for e in sorted_by_date]

        # Simple trend: compare first half avg to second half avg
        mid = len(times) // 2
        if mid > 0:
            first_half_avg = sum(times[:mid]) / mid
            second_half_avg = sum(times[mid:]) / (len(times) - mid)
            trend = "improving" if second_half_avg < first_half_avg else "plateau"
        else:
            trend = "insufficient_data"

        return {
            "attempts": len(entries),
            "best_time": {
                "seconds": best_time.elapsed_time_seconds,
                "formatted": self._format_time(best_time.elapsed_time_seconds),
                "date": best_time.achieved_at.isoformat(),
                "power": best_time.avg_power,
                "w_per_kg": best_time.avg_w_per_kg
            },
            "best_w_per_kg": {
                "value": round(best_wkg.avg_w_per_kg, 2),
                "time": best_wkg.elapsed_time_seconds,
                "date": best_wkg.achieved_at.isoformat()
            },
            "average_time": sum(times) / len(times),
            "trend": trend,
            "total_tss_on_segment": sum(e.tss or 0 for e in entries)
        }
```

### 14.5 Segment TSS

```python
# backend/app/services/tss_service.py

class TSSService:
    def calculate_segment_tss(
        self,
        normalized_power: int,
        user_ftp: int,
        duration_seconds: int
    ) -> float:
        """
        Calculate Training Stress Score for a segment effort.
        TSS = (t × NP × IF) / (FTP × 3600) × 100
        where IF = NP / FTP
        """
        if not user_ftp or user_ftp == 0:
            return 0.0

        intensity_factor = normalized_power / user_ftp
        tss = (duration_seconds * normalized_power * intensity_factor) / (user_ftp * 3600) * 100

        return round(tss, 1)

    def calculate_ride_segment_breakdown(
        self,
        ride_id: str,
        user_id: str
    ) -> list[dict]:
        """
        Break down ride TSS by segment crossed.
        Shows where the training stress came from.
        """
        ride = self.repo.get_ride(ride_id)
        user = self.repo.get_user_fitness(user_id)
        segments_crossed = self.repo.get_ride_segments(ride_id)

        breakdown = []
        for seg in segments_crossed:
            entry = self.repo.get_segment_entry(ride_id, seg.segment_id)

            tss = self.calculate_segment_tss(
                entry.normalized_power,
                user.ftp,
                entry.elapsed_time_seconds
            )

            breakdown.append({
                "segment_id": seg.segment_id,
                "segment_name": seg.name,
                "time_seconds": entry.elapsed_time_seconds,
                "normalized_power": entry.normalized_power,
                "tss": tss,
                "tss_percent_of_ride": round((tss / ride.total_tss) * 100, 1) if ride.total_tss else 0
            })

        return sorted(breakdown, key=lambda x: x['tss'], reverse=True)
```

### 14.6 Season Progression Tracking

```python
# backend/app/services/progression_service.py

class ProgressionService:
    def get_season_summary(self, user_id: str, season: str = None) -> dict:
        """
        Get comprehensive season progression summary.
        """
        if not season:
            season = self._get_current_season()

        progression = self.repo.get_season_progression(user_id, season)

        if not progression:
            return {"season": season, "no_data": True}

        # Get power curve evolution
        curve_start = self.repo.get_user_curve(user_id, season=f"{season}-start")
        curve_current = self.repo.get_user_curve(user_id, season=season)

        curve_gains = {}
        for duration in POWER_CURVE_DURATIONS:
            start = curve_start.get(duration, 0)
            current = curve_current.get(duration, 0)
            if start > 0:
                curve_gains[duration] = {
                    "start_watts": start,
                    "current_watts": current,
                    "gain_watts": current - start,
                    "gain_percent": round(((current - start) / start) * 100, 1)
                }

        return {
            "season": season,
            "volume": {
                "total_rides": progression.total_rides,
                "total_km": round(progression.total_km, 1),
                "total_elevation_m": round(progression.total_elevation_m),
                "total_tss": round(progression.total_tss)
            },
            "fitness": {
                "ftp_start": progression.start_ftp,
                "ftp_current": progression.end_ftp,
                "ftp_peak": progression.peak_ftp,
                "ftp_gain_watts": progression.end_ftp - progression.start_ftp if progression.start_ftp else None,
                "ftp_gain_percent": round(((progression.end_ftp - progression.start_ftp) / progression.start_ftp) * 100, 1) if progression.start_ftp else None,
                "w_per_kg": round(progression.avg_w_per_kg, 2) if progression.avg_w_per_kg else None
            },
            "power_curve_gains": curve_gains,
            "achievements": {
                "koms_gained": progression.koms_gained,
                "koms_lost": progression.koms_lost,
                "net_koms": progression.koms_gained - progression.koms_lost,
                "top_10s": progression.top_10s
            }
        }

    def compare_seasons(self, user_id: str, season1: str, season2: str) -> dict:
        """
        Compare two seasons for year-over-year analysis.
        """
        s1 = self.get_season_summary(user_id, season1)
        s2 = self.get_season_summary(user_id, season2)

        if s1.get("no_data") or s2.get("no_data"):
            return {"error": "Insufficient data for comparison"}

        return {
            "seasons": [season1, season2],
            "volume_diff": {
                "rides": s2["volume"]["total_rides"] - s1["volume"]["total_rides"],
                "km": round(s2["volume"]["total_km"] - s1["volume"]["total_km"], 1),
                "tss": round(s2["volume"]["total_tss"] - s1["volume"]["total_tss"])
            },
            "fitness_diff": {
                "ftp": (s2["fitness"]["ftp_current"] or 0) - (s1["fitness"]["ftp_current"] or 0),
                "w_per_kg": round((s2["fitness"]["w_per_kg"] or 0) - (s1["fitness"]["w_per_kg"] or 0), 2)
            },
            "achievement_diff": {
                "net_koms": s2["achievements"]["net_koms"] - s1["achievements"]["net_koms"],
                "top_10s": s2["achievements"]["top_10s"] - s1["achievements"]["top_10s"]
            }
        }
```

### 14.7 API Endpoints

```python
# backend/app/routes/analytics.py

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/power-curve/{user_id}")
async def get_power_curve(
    user_id: str,
    season: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get user's power curve."""
    return await power_curve_service.get_user_curve(user_id, season)

@router.get("/power-curve/{user_id}/vs-kom/{segment_id}")
async def compare_to_kom(
    user_id: str,
    segment_id: str,
    current_user: User = Depends(get_current_user)
):
    """Compare user's power curve to segment KOM holder."""
    return await power_curve_service.compare_to_kom(user_id, segment_id)

@router.get("/segments/{segment_id}/leaderboard")
async def get_leaderboard(
    segment_id: str,
    order_by: str = Query("time", enum=["time", "w_per_kg", "power"]),
    limit: int = Query(50, le=100)
):
    """Get segment leaderboard with multiple sort options."""
    return await leaderboard_service.get_segment_leaderboard(segment_id, order_by, limit)

@router.get("/segments/{segment_id}/predict/{user_id}")
async def predict_segment_time(
    segment_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """Predict segment time based on user's power profile."""
    return await prediction_service.predict_segment_time(user_id, segment_id)

@router.get("/segments/{segment_id}/analysis/{user_id}")
async def get_segment_analysis(
    segment_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """Deep analysis of user's segment performance."""
    return await leaderboard_service.get_user_segment_analysis(user_id, segment_id)

@router.get("/rides/{ride_id}/tss-breakdown")
async def get_ride_tss_breakdown(
    ride_id: str,
    current_user: User = Depends(get_current_user)
):
    """Break down ride TSS by segments crossed."""
    return await tss_service.calculate_ride_segment_breakdown(ride_id, current_user.id)

@router.get("/progression/{user_id}")
async def get_season_progression(
    user_id: str,
    season: str = None,
    current_user: User = Depends(get_current_user)
):
    """Get season progression summary."""
    return await progression_service.get_season_summary(user_id, season)

@router.get("/progression/{user_id}/compare")
async def compare_seasons(
    user_id: str,
    season1: str,
    season2: str,
    current_user: User = Depends(get_current_user)
):
    """Compare two seasons year-over-year."""
    return await progression_service.compare_seasons(user_id, season1, season2)

@router.get("/fitness/{user_id}")
async def get_fitness_profile(
    user_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get user's current fitness profile (FTP, w/kg, CP, W')."""
    return await fitness_service.get_user_fitness(user_id)

@router.put("/fitness/ftp")
async def update_ftp(
    ftp: int,
    weight_kg: float = None,
    current_user: User = Depends(get_current_user)
):
    """Update user's FTP (manual entry or auto-detected)."""
    return await fitness_service.update_ftp(current_user.id, ftp, weight_kg)
```

### 14.8 Analytics vs Strava

| Feature | Strava | Boulder Rollers |
|---------|--------|-----------------|
| Time leaderboard | ✓ | ✓ |
| w/kg leaderboard | ✗ | ✓ |
| Power leaderboard | ✗ | ✓ |
| Power curve | ✗ | ✓ Full curve analysis |
| Compare to KOM's curve | ✗ | ✓ "See exactly what you need" |
| Predicted segment time | ✗ | ✓ "At your FTP, you'd do X:XX" |
| Segment TSS | ✗ | ✓ Per-segment stress tracking |
| TSS breakdown by segment | ✗ | ✓ "Where did your training stress come from?" |
| Season progression | Basic | Full power curve evolution |
| Year-over-year comparison | ✗ | ✓ Volume, fitness, achievements |
| Critical Power model | ✗ | ✓ Bio-passport for anti-cheat + predictions |

**Key insight:** We require power data. So we can do things they never will.

---

**This spec is the technical reference for Boulder Rollers V2 Solana programs.**
