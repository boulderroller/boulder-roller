# Worker 1: Solana Programs Engineer

> **Note:** This doc references legacy program structure. Current protocol mechanics live in
> `history/BR_cal_allocation_refactor_spec.md`.

**Context:** Read `BOULDER_ROLLERS_V1_SPEC.md` first for full game design.

**Your Responsibility:** Build and deploy all Solana on-chain programs (smart contracts).

**Tech Stack:**
- Rust + Anchor Framework 0.29.0
- Solana 1.18.26
- Target: BPF (SBF)

**Working Directory:** `/protocol/anchor/`

---

## Current State (Already Done ✅)

- ✅ 3 programs compile: `proof_verifier`, `dung_mint`, `boulder_rollers`
- ✅ Basic ride recording exists (stub)
- ✅ Ed25519 attestation verification implemented
- ✅ Build system fixed (no BPF stack overflow)
- ✅ IDL generation working

---

## Your 7-Week Plan

### Week 1: Foundation & User State

#### Task 1.1: Define All Account Structures (Day 1-2)
**Goal:** Write complete account structs for all program features.

**Action:** Update `programs/boulder_rollers/src/lib.rs`

```rust
// Add these account structures:

#[account]
pub struct UserState {
    pub owner: Pubkey,
    pub cal_balance: u64,        // Non-transferable, stored on-chain
    pub cal_earned_today: u64,   // Counter for daily limit
    pub last_cal_mint: i64,      // Date of last mint (epoch days)
    pub total_rides: u64,
    pub total_tss: u64,          // Lifetime Training Stress Score
    pub bio_score: u16,          // 0-1000, for anti-cheat (V2)
    pub bump: u8,
}

#[account]
pub struct Segment {
    pub id: u64,
    pub creator: Pubkey,
    pub start_lat: i32,          // Encoded as lat * 1e7
    pub start_lon: i32,
    pub end_lat: i32,
    pub end_lon: i32,
    pub distance_meters: u32,
    pub elevation_gain: u16,
    pub name: [u8; 64],          // UTF-8, null-terminated
    pub description: [u8; 256],
    pub created_at: i64,
    pub total_rides: u64,
    pub total_staked: u64,       // For calculating Swanny slots
    pub cal_burned: u64,         // Tracks 1000 CAL → 1 DUNG conversion
    pub cover_photo_ipfs: [u8; 64],
    pub bump: u8,
}

#[account]
pub struct Claim {
    pub user: Pubkey,
    pub segment: u64,
    pub amount: u64,             // DUNG staked
    pub lp_tokens: u64,          // Minted to user
    pub staked_at: i64,
    pub last_harvest: i64,       // Last reward claim
    pub bump: u8,
}

#[account]
pub struct SwannySeat {
    pub segment: u64,
    pub seat_index: u8,          // 0, 1, or 2
    pub holder: Option<Pubkey>,
    pub locked_amount: u64,      // 1000 DUNG
    pub locked_at: i64,
    pub unlock_at: i64,          // locked_at + 30 days
    pub tasks_completed: u8,     // Bitmap: photo|tribunal|boost
    pub bump: u8,
}

#[account]
pub struct Epoch {
    pub segment: u64,
    pub epoch_number: u64,
    pub start_time: i64,         // Sunday 00:00 UTC
    pub end_time: i64,           // Next Sunday 00:00 UTC
    pub total_pot: u64,          // DUNG accumulated this week
    pub leaderboard: Vec<LeaderboardEntry>,  // Top 10
    pub distributed: bool,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct LeaderboardEntry {
    pub user: Pubkey,
    pub time_seconds: u32,       // Best time this epoch
    pub tss: u16,                // Effort score
}

#[account]
pub struct SegmentCounter {
    pub count: u64,              // Global segment ID counter
    pub bump: u8,
}
```

**Deliverable:** Compile without errors, document in `docs/schemas.md`

---

#### Task 1.2: Implement CAL System (Day 3-5)

**Goal:** Users can mint 2500 CAL daily and burn it on segments.

**Action 1:** Implement `initialize_user()` instruction

```rust
#[derive(Accounts)]
pub struct InitializeUser<'info> {
    #[account(
        init,
        payer = payer,
        space = 8 + 32 + 8 + 8 + 8 + 8 + 8 + 2 + 1,
        seeds = [b"user", payer.key().as_ref()],
        bump
    )]
    pub user_state: Account<'info, UserState>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn initialize_user(ctx: Context<InitializeUser>) -> Result<()> {
    let user_state = &mut ctx.accounts.user_state;
    user_state.owner = ctx.accounts.payer.key();
    user_state.cal_balance = 0;
    user_state.cal_earned_today = 0;
    user_state.last_cal_mint = 0;
    user_state.total_rides = 0;
    user_state.total_tss = 0;
    user_state.bio_score = 1000; // Start at max
    user_state.bump = ctx.bumps.user_state;
    Ok(())
}
```

**Action 2:** Implement `mint_daily_cal()` instruction

```rust
#[derive(Accounts)]
pub struct MintDailyCal<'info> {
    #[account(
        mut,
        seeds = [b"user", owner.key().as_ref()],
        bump = user_state.bump,
        has_one = owner
    )]
    pub user_state: Account<'info, UserState>,
    pub owner: Signer<'info>,
}

pub fn mint_daily_cal(ctx: Context<MintDailyCal>) -> Result<()> {
    let user_state = &mut ctx.accounts.user_state;
    let clock = Clock::get()?;
    let current_day = clock.unix_timestamp / 86400; // Epoch days
    let last_mint_day = user_state.last_cal_mint / 86400;

    require!(current_day > last_mint_day, ErrorCode::AlreadyMintedToday);

    user_state.cal_balance = user_state.cal_balance.checked_add(2500)
        .ok_or(ErrorCode::Overflow)?;
    user_state.cal_earned_today = 2500;
    user_state.last_cal_mint = clock.unix_timestamp;

    emit!(CalMinted {
        user: user_state.owner,
        amount: 2500,
        timestamp: clock.unix_timestamp,
    });

    Ok(())
}
```

**Action 3:** Implement `burn_cal_for_segment()` instruction

```rust
#[derive(Accounts)]
pub struct BurnCalForSegment<'info> {
    #[account(
        mut,
        seeds = [b"user", owner.key().as_ref()],
        bump = user_state.bump,
        has_one = owner
    )]
    pub user_state: Account<'info, UserState>,
    #[account(
        mut,
        seeds = [b"segment", &segment.id.to_le_bytes()],
        bump = segment.bump
    )]
    pub segment: Account<'info, Segment>,
    #[account(mut)]
    pub segment_pot: Account<'info, TokenAccount>, // DUNG pot
    pub owner: Signer<'info>,
    pub dung_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
}

pub fn burn_cal_for_segment(ctx: Context<BurnCalForSegment>) -> Result<()> {
    let user_state = &mut ctx.accounts.user_state;
    let segment = &mut ctx.accounts.segment;

    // Burn 100 CAL
    require!(user_state.cal_balance >= 100, ErrorCode::InsufficientCal);
    user_state.cal_balance = user_state.cal_balance.checked_sub(100)
        .ok_or(ErrorCode::Underflow)?;

    // Track burned CAL
    segment.cal_burned = segment.cal_burned.checked_add(100)
        .ok_or(ErrorCode::Overflow)?;

    // Check if we hit 1000 CAL → mint 1 DUNG
    if segment.cal_burned >= 1000 {
        segment.cal_burned -= 1000;

        // Mint 1 DUNG into segment pot
        let segment_id = segment.id;
        let seeds = &[
            b"segment",
            &segment_id.to_le_bytes(),
            &[segment.bump],
        ];
        let signer = &[&seeds[..]];

        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.dung_mint.to_account_info(),
                    to: ctx.accounts.segment_pot.to_account_info(),
                    authority: segment.to_account_info(),
                },
                signer,
            ),
            1_000_000_000, // 1 DUNG (9 decimals)
        )?;
    }

    Ok(())
}
```

**Tests to Write:**
```bash
cd protocol/anchor
anchor test

# Test cases:
# 1. User can mint 2500 CAL once per day
# 2. Cannot mint CAL twice in same day
# 3. Can burn 100 CAL for segment
# 4. 1000 CAL burned → 1 DUNG minted into pot
# 5. CAL balance updates correctly
```

**Deliverable:** CAL system working, all tests pass, deploy to devnet

---

### Week 2: Segment Creation & Global Counter

#### Task 1.3: Implement Segment Counter (Day 1)

**Goal:** Atomic global ID generation for segments.

```rust
#[derive(Accounts)]
pub struct InitializeCounter<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + 8 + 1,
        seeds = [b"counter"],
        bump
    )]
    pub counter: Account<'info, SegmentCounter>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn initialize_counter(ctx: Context<InitializeCounter>) -> Result<()> {
    let counter = &mut ctx.accounts.counter;
    counter.count = 0;
    counter.bump = ctx.bumps.counter;
    Ok(())
}
```

**Deployment Script:**
```typescript
// tests/initialize_counter.ts
it("Initialize segment counter", async () => {
  const [counterPda] = await PublicKey.findProgramAddress(
    [Buffer.from("counter")],
    program.programId
  );

  await program.methods
    .initializeCounter()
    .accounts({
      counter: counterPda,
      authority: provider.wallet.publicKey,
      systemProgram: SystemProgram.programId,
    })
    .rpc();
});
```

---

#### Task 1.4: Implement Segment Creation (Day 2-4)

**Goal:** Users can create segments for 100 DUNG + 0.02 SOL.

```rust
#[derive(Accounts)]
pub struct CreateSegment<'info> {
    #[account(
        mut,
        seeds = [b"counter"],
        bump = counter.bump
    )]
    pub counter: Account<'info, SegmentCounter>,
    #[account(
        init,
        payer = creator,
        space = 8 + 8 + 32 + 4*4 + 4 + 2 + 64 + 256 + 8 + 8 + 8 + 8 + 64 + 1,
        seeds = [b"segment", &counter.count.to_le_bytes()],
        bump
    )]
    pub segment: Account<'info, Segment>,
    #[account(mut)]
    pub creator: Signer<'info>,
    #[account(mut)]
    pub creator_dung_account: Account<'info, TokenAccount>,
    #[account(mut)]
    pub treasury: SystemAccount<'info>,
    pub dung_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

pub fn create_segment(
    ctx: Context<CreateSegment>,
    start_lat: i32,
    start_lon: i32,
    end_lat: i32,
    end_lon: i32,
    distance_meters: u32,
    elevation_gain: u16,
    name: String,
    description: String,
) -> Result<()> {
    // Validation
    require!(name.len() >= 3 && name.len() <= 64, ErrorCode::InvalidName);
    require!(distance_meters >= 100 && distance_meters <= 50_000, ErrorCode::InvalidDistance);
    require!(elevation_gain <= 5000, ErrorCode::InvalidElevation);

    // Burn 100 DUNG from creator
    token::burn(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Burn {
                mint: ctx.accounts.dung_mint.to_account_info(),
                from: ctx.accounts.creator_dung_account.to_account_info(),
                authority: ctx.accounts.creator.to_account_info(),
            },
        ),
        100_000_000_000, // 100 DUNG
    )?;

    // Transfer 0.02 SOL to treasury
    let ix = anchor_lang::solana_program::system_instruction::transfer(
        &ctx.accounts.creator.key(),
        &ctx.accounts.treasury.key(),
        20_000_000, // 0.02 SOL
    );
    anchor_lang::solana_program::program::invoke(
        &ix,
        &[
            ctx.accounts.creator.to_account_info(),
            ctx.accounts.treasury.to_account_info(),
        ],
    )?;

    // Initialize segment
    let counter = &mut ctx.accounts.counter;
    let segment = &mut ctx.accounts.segment;

    segment.id = counter.count;
    segment.creator = ctx.accounts.creator.key();
    segment.start_lat = start_lat;
    segment.start_lon = start_lon;
    segment.end_lat = end_lat;
    segment.end_lon = end_lon;
    segment.distance_meters = distance_meters;
    segment.elevation_gain = elevation_gain;

    let mut name_bytes = [0u8; 64];
    name_bytes[..name.len()].copy_from_slice(name.as_bytes());
    segment.name = name_bytes;

    let mut desc_bytes = [0u8; 256];
    desc_bytes[..description.len()].copy_from_slice(description.as_bytes());
    segment.description = desc_bytes;

    segment.created_at = Clock::get()?.unix_timestamp;
    segment.total_rides = 0;
    segment.total_staked = 0;
    segment.cal_burned = 0;
    segment.bump = ctx.bumps.segment;

    // Increment counter
    counter.count = counter.count.checked_add(1).ok_or(ErrorCode::Overflow)?;

    emit!(SegmentCreated {
        id: segment.id,
        creator: segment.creator,
        start_lat,
        start_lon,
        end_lat,
        end_lon,
        timestamp: segment.created_at,
    });

    Ok(())
}
```

**Deliverable:** Segments can be created, counter increments, deploy to devnet

---

### Week 3: Staking System (Claims)

#### Task 1.5: Implement LP Token Mints (Day 1)

**Goal:** Each segment gets its own SPL token mint for LP tokens.

```rust
#[derive(Accounts)]
pub struct InitializeSegmentLpMint<'info> {
    #[account(
        seeds = [b"segment", &segment.id.to_le_bytes()],
        bump = segment.bump
    )]
    pub segment: Account<'info, Segment>,
    #[account(
        init,
        payer = payer,
        mint::decimals = 9,
        mint::authority = segment,
        seeds = [b"lp_mint", &segment.id.to_le_bytes()],
        bump
    )]
    pub lp_mint: Account<'info, Mint>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn initialize_segment_lp_mint(ctx: Context<InitializeSegmentLpMint>) -> Result<()> {
    // LP mint initialized via Anchor constraints
    Ok(())
}
```

---

#### Task 1.6: Implement Staking (Day 2-4)

**Goal:** Users stake DUNG, receive LP tokens.

```rust
#[derive(Accounts)]
pub struct StakeInSegment<'info> {
    #[account(
        mut,
        seeds = [b"segment", &segment.id.to_le_bytes()],
        bump = segment.bump
    )]
    pub segment: Account<'info, Segment>,
    #[account(
        init_if_needed,
        payer = staker,
        space = 8 + 32 + 8 + 8 + 8 + 8 + 8 + 1,
        seeds = [b"claim", staker.key().as_ref(), &segment.id.to_le_bytes()],
        bump
    )]
    pub claim: Account<'info, Claim>,
    #[account(mut)]
    pub staker: Signer<'info>,
    #[account(mut)]
    pub staker_dung_account: Account<'info, TokenAccount>,
    #[account(mut)]
    pub segment_pot: Account<'info, TokenAccount>, // Holds staked DUNG
    #[account(
        mut,
        seeds = [b"lp_mint", &segment.id.to_le_bytes()],
        bump
    )]
    pub lp_mint: Account<'info, Mint>,
    #[account(mut)]
    pub staker_lp_account: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

pub fn stake_in_segment(ctx: Context<StakeInSegment>, amount: u64) -> Result<()> {
    require!(amount >= 10_000_000_000, ErrorCode::MinimumStakeRequired); // 10 DUNG min

    let segment = &mut ctx.accounts.segment;
    let claim = &mut ctx.accounts.claim;

    // Calculate LP tokens to mint
    let total_staked = ctx.accounts.segment_pot.amount;
    let total_lp_supply = ctx.accounts.lp_mint.supply;

    let lp_to_mint = if total_lp_supply == 0 {
        // First staker: 1:1
        amount
    } else {
        // Pro-rata: lp = amount * total_lp / total_staked
        (amount as u128)
            .checked_mul(total_lp_supply as u128)
            .ok_or(ErrorCode::Overflow)?
            .checked_div(total_staked as u128)
            .ok_or(ErrorCode::DivisionByZero)? as u64
    };

    // Transfer DUNG from staker to pot
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.staker_dung_account.to_account_info(),
                to: ctx.accounts.segment_pot.to_account_info(),
                authority: ctx.accounts.staker.to_account_info(),
            },
        ),
        amount,
    )?;

    // Mint LP tokens to staker
    let segment_id = segment.id;
    let seeds = &[
        b"segment",
        &segment_id.to_le_bytes(),
        &[segment.bump],
    ];
    let signer = &[&seeds[..]];

    token::mint_to(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.lp_mint.to_account_info(),
                to: ctx.accounts.staker_lp_account.to_account_info(),
                authority: segment.to_account_info(),
            },
            signer,
        ),
        lp_to_mint,
    )?;

    // Update claim
    if claim.user == Pubkey::default() {
        claim.user = ctx.accounts.staker.key();
        claim.segment = segment.id;
        claim.staked_at = Clock::get()?.unix_timestamp;
        claim.bump = ctx.bumps.claim;
    }
    claim.amount = claim.amount.checked_add(amount).ok_or(ErrorCode::Overflow)?;
    claim.lp_tokens = claim.lp_tokens.checked_add(lp_to_mint).ok_or(ErrorCode::Overflow)?;

    // Update segment stats
    segment.total_staked = segment.total_staked.checked_add(amount).ok_or(ErrorCode::Overflow)?;

    Ok(())
}
```

#### Task 1.7: Implement Unstaking (Day 5)

```rust
pub fn unstake_from_segment(ctx: Context<UnstakeFromSegment>, lp_amount: u64) -> Result<()> {
    // Burn LP tokens
    // Calculate DUNG to return: dung = lp * total_staked / total_lp
    // Transfer DUNG from pot to user
    // Update claim, close if amount == 0
    // (Full implementation similar to stake)
}
```

**Deliverable:** Full staking system working, tests pass

---

### Week 4: Epochs & Distribution

#### Task 1.8: Implement Epoch Creation (Day 1-2)

```rust
pub fn create_epoch(ctx: Context<CreateEpoch>, epoch_number: u64) -> Result<()> {
    let epoch = &mut ctx.accounts.epoch;
    let clock = Clock::get()?;

    // Calculate Sunday 00:00 UTC boundaries
    let start_time = /* calculate based on epoch_number */;
    let end_time = start_time + 604800; // +7 days

    epoch.segment = ctx.accounts.segment.id;
    epoch.epoch_number = epoch_number;
    epoch.start_time = start_time;
    epoch.end_time = end_time;
    epoch.total_pot = 0;
    epoch.leaderboard = Vec::new();
    epoch.distributed = false;
    epoch.bump = ctx.bumps.epoch;

    Ok(())
}
```

#### Task 1.9: Update record_ride() (Day 3)

**Goal:** Add ride to leaderboard, keep top 10 sorted.

```rust
pub fn record_ride(ctx: Context<RecordRide>, time_seconds: u32, tss: u16) -> Result<()> {
    // (Existing attestation verification logic...)

    let epoch = &mut ctx.accounts.epoch;

    // Insert into leaderboard (sorted by time_seconds)
    let entry = LeaderboardEntry {
        user: ctx.accounts.rider.key(),
        time_seconds,
        tss,
    };

    // Find insertion point
    let mut insert_at = epoch.leaderboard.len();
    for (i, existing) in epoch.leaderboard.iter().enumerate() {
        if time_seconds < existing.time_seconds {
            insert_at = i;
            break;
        }
    }

    // Insert and keep only top 10
    if insert_at < 10 {
        epoch.leaderboard.insert(insert_at, entry);
        if epoch.leaderboard.len() > 10 {
            epoch.leaderboard.truncate(10);
        }
    }

    Ok(())
}
```

#### Task 1.10: Implement close_epoch() Distribution (Day 4-5)

**Goal:** Calculate and emit distribution events (pull model).

```rust
pub fn close_epoch(ctx: Context<CloseEpoch>) -> Result<()> {
    let epoch = &mut ctx.accounts.epoch;
    let clock = Clock::get()?;

    require!(!epoch.distributed, ErrorCode::AlreadyDistributed);
    require!(clock.unix_timestamp >= epoch.end_time, ErrorCode::EpochNotEnded);

    let total_pot = ctx.accounts.segment_pot.amount;

    // 70% leaderboard
    let leaderboard_pot = total_pot * 70 / 100;
    let splits = [30, 20, 15, 10, 8, 6, 5, 3, 2, 1];

    for (i, entry) in epoch.leaderboard.iter().enumerate() {
        let amount = leaderboard_pot * splits[i] / 100;

        emit!(LeaderboardReward {
            epoch: epoch.epoch_number,
            segment: epoch.segment,
            user: entry.user,
            rank: i as u8 + 1,
            amount,
        });
    }

    // 20% claimers (emit event, backend tracks)
    let claimant_pot = total_pot * 20 / 100;
    emit!(ClaimantPotReady {
        epoch: epoch.epoch_number,
        segment: epoch.segment,
        amount: claimant_pot,
    });

    // 10% Swannys
    let swanny_pot = total_pot * 10 / 100;
    let per_swanny = swanny_pot / 3;

    // (Load Swanny accounts and emit rewards)

    epoch.distributed = true;
    Ok(())
}
```

**Deliverable:** Epochs work, distribution math correct, events emitted

---

### Week 5: Swanny Seats

#### Task 1.11: Implement Swanny Claiming (Day 1-3)

```rust
pub fn claim_swanny_seat(ctx: Context<ClaimSwannySeat>) -> Result<()> {
    let seat = &mut ctx.accounts.swanny_seat;
    let clock = Clock::get()?;

    // Check seat vacant or expired
    if let Some(holder) = seat.holder {
        require!(clock.unix_timestamp > seat.unlock_at, ErrorCode::SeatOccupied);
    }

    // Lock 1000 DUNG
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.user_dung_account.to_account_info(),
                to: ctx.accounts.segment_pot.to_account_info(),
                authority: ctx.accounts.user.to_account_info(),
            },
        ),
        1000_000_000_000, // 1000 DUNG
    )?;

    // Assign seat
    seat.holder = Some(ctx.accounts.user.key());
    seat.locked_amount = 1000_000_000_000;
    seat.locked_at = clock.unix_timestamp;
    seat.unlock_at = clock.unix_timestamp + 2_592_000; // +30 days
    seat.tasks_completed = 0;

    Ok(())
}
```

#### Task 1.12: Implement Release & Renew (Day 4-5)

```rust
pub fn release_swanny_seat(ctx: Context<ReleaseSwannySeat>) -> Result<()> {
    // Check unlock_at passed
    // Return 1000 DUNG to holder
    // Set holder = None
}

pub fn renew_swanny_seat(ctx: Context<RenewSwannySeat>) -> Result<()> {
    // Extend unlock_at by 30 days
    // No additional payment
}
```

**Deliverable:** Swanny seats working, 3 per segment

---

### Week 6: Integration & Testing

#### Task 1.13: Integration with Backend (Day 1-2)
- Help Worker 2 call your instructions
- Debug transaction failures
- Optimize compute units (<200k per instruction)

#### Task 1.14: Security Audit Prep (Day 3-4)
- Add invariant checks (total distributions == pot)
- Use checked_* arithmetic everywhere
- Document all assumptions
- Add reentrancy guards

#### Task 1.15: Fuzzing & Edge Cases (Day 5)
```bash
cargo install cargo-fuzz
cargo fuzz run fuzz_target_1
```

---

### Week 7: Mainnet Deployment

#### Task 1.16: Deploy to Mainnet (Day 1-2)
```bash
# Generate mainnet keypairs
solana-keygen new -o mainnet-deployer.json

# Deploy programs
anchor deploy --provider.cluster mainnet

# Initialize global state
anchor run initialize_mainnet
```

#### Task 1.17: Publish IDL (Day 3)
```bash
# Publish to NPM
cd target/idl
npm publish @boulder-rollers/idl
```

#### Task 1.18: Monitoring (Day 4-5)
- Set up program account monitoring
- Alert on unexpected state changes
- Document emergency procedures

---

## Error Codes to Add

```rust
#[error_code]
pub enum ErrorCode {
    // Existing errors...

    #[msg("Already minted CAL today")]
    AlreadyMintedToday,

    #[msg("Insufficient CAL balance")]
    InsufficientCal,

    #[msg("Invalid segment name")]
    InvalidName,

    #[msg("Invalid distance")]
    InvalidDistance,

    #[msg("Invalid elevation")]
    InvalidElevation,

    #[msg("Minimum stake is 10 DUNG")]
    MinimumStakeRequired,

    #[msg("Epoch already distributed")]
    AlreadyDistributed,

    #[msg("Epoch not ended yet")]
    EpochNotEnded,

    #[msg("Swanny seat occupied")]
    SeatOccupied,

    #[msg("Overflow")]
    Overflow,

    #[msg("Underflow")]
    Underflow,

    #[msg("Division by zero")]
    DivisionByZero,
}
```

---

## Testing Checklist

- [ ] User can initialize account
- [ ] User mints 2500 CAL once per day
- [ ] Cannot mint CAL twice same day
- [ ] Can burn 100 CAL for segment
- [ ] 1000 CAL → 1 DUNG minted
- [ ] Segment creation costs 100 DUNG + 0.02 SOL
- [ ] Segment ID increments
- [ ] Staking mints LP tokens (1:1 first, pro-rata after)
- [ ] Unstaking burns LP tokens, returns DUNG
- [ ] Leaderboard keeps top 10 sorted
- [ ] Epoch distribution math correct (70/20/10)
- [ ] Cannot distribute twice
- [ ] Swanny seat locks 1000 DUNG for 30 days
- [ ] All arithmetic uses checked_*

---

## Communication with Other Workers

**Worker 2 (Backend) needs from you:**
- Devnet program IDs (after each deployment)
- IDL files (publish to NPM after changes)
- RPC methods to call your instructions
- Event schemas (for listening to on-chain events)

**Worker 3 (iOS) needs from you:**
- Program IDs (devnet + mainnet)
- IDL (they use Solana.swift to call your programs)

**Worker 4 (DevOps) needs from you:**
- Deployment scripts
- Monitoring requirements (what to alert on)

**Deliverables each week:**
1. Updated IDL published to NPM
2. Deployment to devnet
3. Test results (screenshot or CI link)
4. Update `docs/schemas.md` with any changes

---

## Resources

- Anchor Docs: https://www.anchor-lang.com/
- Solana Cookbook: https://solanacookbook.com/
- SPL Token: https://spl.solana.com/token
- Your working directory: `/protocol/anchor/`
- Test command: `anchor test`
- Build command: `anchor build`
- Deploy: `anchor deploy --provider.cluster devnet`
