//! Account validation structs for every instruction.

use crate::*;

// --------------------- Instruction Contexts ---------------------

#[derive(Accounts)]
pub struct InitializeUser<'info> {
    #[account(
        init,
        payer = payer,
        space = UserState::SIZE,
        seeds = [USER_SEED, payer.key().as_ref()],
        bump
    )]
    pub user_state: Account<'info, UserState>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Initialize program configuration (one-time setup)
#[derive(Accounts)]
pub struct InitializeProgramConfig<'info> {
    #[account(
        init,
        payer = admin,
        space = ProgramConfig::SIZE,
        seeds = [PROGRAM_CONFIG_SEED],
        bump
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// CHECK: This program account is checked against crate::ID and upgradeable loader state.
    #[account(address = crate::ID @ ErrorCode::InvalidProgramAccount, executable)]
    pub program: UncheckedAccount<'info>,
    /// CHECK: Validated as this program's ProgramData account and upgrade authority source.
    #[account(owner = bpf_loader_upgradeable::ID @ ErrorCode::InvalidProgramData)]
    pub program_data: UncheckedAccount<'info>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Update program configuration (admin only)
#[derive(Accounts)]
pub struct UpdateProgramConfig<'info> {
    #[account(
        mut,
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        has_one = admin_authority @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// Current admin authority - must match program_config.admin_authority
    pub admin_authority: Signer<'info>,
}

/// Advance ProgramConfig's stable client-compatibility byte by one patch.
#[derive(Accounts)]
pub struct AdvanceProgramVersion<'info> {
    /// CHECK: PDA, owner, discriminator, initialization, and stored admin are
    /// validated against the stable ProgramConfig prefix in the instruction.
    #[account(
        mut,
        seeds = [PROGRAM_CONFIG_SEED],
        bump,
    )]
    pub program_config: UncheckedAccount<'info>,
    pub admin: Signer<'info>,
}

/// Backend-attested ride record anchored by a deterministic canonical ride hash.
#[derive(Accounts)]
#[instruction(
    ride_hash: [u8; 32],
    attestation_commitment: [u8; 32],
    parser_version: u32,
    source_kind: u8,
    completed_at: i64,
    started_at: i64,
    total_tss: u32,
    total_distance_m: u32,
    total_vert_m: u32,
    cal_earned: u64,
    climbs_crossed: u16
)]
pub struct RecordRide<'info> {
    #[account(
        init,
        payer = payer,
        space = RideAttestation::SIZE,
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_hash],
        bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        init_if_needed,
        payer = payer,
        space = RiderSoul::SIZE,
        seeds = [RIDER_SOUL_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_soul: Box<Account<'info, RiderSoul>>,
    /// Rider whose effort is being attested.
    /// CHECK: identity is validated by PDA seeds and persisted account state.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub authority: Signer<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Backend-attested CAL mint tied one-to-one to a recorded ride.
#[derive(Accounts)]
pub struct CreditCal<'info> {
    #[account(
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_attestation.ride_hash],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        init,
        payer = payer,
        space = CalMintReceipt::SIZE,
        seeds = [CAL_MINT_RECEIPT_SEED, ride_attestation.key().as_ref(), rider.key().as_ref()],
        bump
    )]
    pub cal_mint_receipt: Box<Account<'info, CalMintReceipt>>,
    /// Rider receiving CAL for the attested ride.
    /// CHECK: identity is validated against ride_attestation.rider and token-account constraints.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend,
        constraint = program_config.cal_mint != Pubkey::default() @ ErrorCode::MintsNotConfigured,
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub authority: Signer<'info>,
    #[account(
        mut,
        constraint = cal_mint.key() == program_config.cal_mint @ ErrorCode::InvalidMint,
    )]
    pub cal_mint: Account<'info, Mint>,
    /// CHECK: CAL mint authority PDA - verified by seeds
    #[account(
        seeds = [CAL_MINT_AUTH_SEED],
        bump = program_config.cal_mint_auth_bump,
    )]
    pub cal_mint_auth: UncheckedAccount<'info>,
    #[account(
        mut,
        constraint = destination.owner == rider.key() @ ErrorCode::InvalidTokenAccountOwner,
        constraint = destination.mint == cal_mint.key() @ ErrorCode::InvalidMint,
    )]
    pub destination: Account<'info, TokenAccount>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

/// Backend authorization for one provisional ride whose Threshold became
/// effective inside the immutable hold window.
#[derive(Accounts)]
pub struct AuthorizeHeldRideRelease<'info> {
    #[account(
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_attestation.ride_hash],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        init,
        payer = authority,
        space = HeldRideReleaseAuthority::SIZE,
        seeds = [HELD_RIDE_RELEASE_SEED, ride_attestation.key().as_ref()],
        bump
    )]
    pub release_authority: Box<Account<'info, HeldRideReleaseAuthority>>,
    /// Rider whose provisional economics are being authorized.
    /// CHECK: identity is validated against ride_attestation.rider.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Receipt-protected mint for CAL authorized by HeldRideReleaseAuthority.
/// The ordinary CAL receipt seeds remain the single replay address.
#[derive(Accounts)]
pub struct CreditReleasedCal<'info> {
    #[account(
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_attestation.ride_hash],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        seeds = [HELD_RIDE_RELEASE_SEED, ride_attestation.key().as_ref()],
        bump = release_authority.bump,
        constraint = release_authority.ride_attestation == ride_attestation.key()
            @ ErrorCode::InvalidHeldRideReleaseAuthority,
        constraint = release_authority.rider == rider.key()
            @ ErrorCode::InvalidHeldRideReleaseAuthority
    )]
    pub release_authority: Box<Account<'info, HeldRideReleaseAuthority>>,
    #[account(
        init,
        payer = payer,
        space = ReleasedCalMintReceipt::SIZE,
        seeds = [CAL_MINT_RECEIPT_SEED, ride_attestation.key().as_ref(), rider.key().as_ref()],
        bump
    )]
    pub cal_mint_receipt: Box<Account<'info, ReleasedCalMintReceipt>>,
    #[account(
        mut,
        seeds = [RIDER_SOUL_SEED, rider.key().as_ref()],
        bump = rider_soul.bump,
        constraint = rider_soul.rider == rider.key() @ ErrorCode::InvalidRideAttestation
    )]
    pub rider_soul: Box<Account<'info, RiderSoul>>,
    /// Rider receiving the released CAL.
    /// CHECK: identity is validated against both immutable authorities and token constraints.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend,
        constraint = program_config.cal_mint != Pubkey::default() @ ErrorCode::MintsNotConfigured,
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub authority: Signer<'info>,
    #[account(
        mut,
        constraint = cal_mint.key() == program_config.cal_mint @ ErrorCode::InvalidMint,
    )]
    pub cal_mint: Account<'info, Mint>,
    /// CHECK: CAL mint authority PDA - verified by seeds.
    #[account(
        seeds = [CAL_MINT_AUTH_SEED],
        bump = program_config.cal_mint_auth_bump,
    )]
    pub cal_mint_auth: UncheckedAccount<'info>,
    #[account(
        mut,
        constraint = destination.owner == rider.key() @ ErrorCode::InvalidTokenAccountOwner,
        constraint = destination.mint == cal_mint.key() @ ErrorCode::InvalidMint,
    )]
    pub destination: Account<'info, TokenAccount>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

/// Tribute-bound completion context. V2 retains the V1 PDA seeds, so either
/// account discriminator occupies the one replay-guard address for the ride.
#[derive(Accounts)]
pub struct RecordClimbCompletionV2<'info> {
    #[account(
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_attestation.ride_hash],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        init,
        payer = authority,
        space = ClimbCompletionReceiptV2::SIZE,
        seeds = [CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation.key().as_ref(), vault.key().as_ref()],
        bump
    )]
    pub climb_completion_receipt: Box<Account<'info, ClimbCompletionReceiptV2>>,
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        init_if_needed,
        payer = authority,
        space = VaultCompletion::SIZE,
        seeds = [VAULT_COMPLETION_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_completion: Box<Account<'info, VaultCompletion>>,
    #[account(
        mut,
        seeds = [VAULT_LEADERBOARD_SEED, &vault.id.to_le_bytes()],
        bump = vault_leaderboard.bump
    )]
    pub vault_leaderboard: Box<Account<'info, VaultLeaderboard>>,
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive,
        constraint = vault_activation.permits_new_economic_history() @ ErrorCode::InvalidActivationSeed
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    /// CHECK: identity is validated against ride_attestation.rider and PDA seeds.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Release-bound tribute context. The receipt and budget retain the ordinary
/// replay PDA seeds while using distinct release-aware account discriminators.
#[derive(Accounts)]
pub struct RecordReleasedClimbCompletion<'info> {
    #[account(
        seeds = [RIDE_ATTESTATION_SEED, rider.key().as_ref(), &ride_attestation.ride_hash],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        seeds = [HELD_RIDE_RELEASE_SEED, ride_attestation.key().as_ref()],
        bump = release_authority.bump,
        constraint = release_authority.ride_attestation == ride_attestation.key()
            @ ErrorCode::InvalidHeldRideReleaseAuthority,
        constraint = release_authority.rider == rider.key()
            @ ErrorCode::InvalidHeldRideReleaseAuthority
    )]
    pub release_authority: Box<Account<'info, HeldRideReleaseAuthority>>,
    #[account(
        init,
        payer = authority,
        space = ReleasedClimbCompletionReceipt::SIZE,
        seeds = [CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation.key().as_ref(), vault.key().as_ref()],
        bump
    )]
    pub climb_completion_receipt: Box<Account<'info, ReleasedClimbCompletionReceipt>>,
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        init_if_needed,
        payer = authority,
        space = VaultCompletion::SIZE,
        seeds = [VAULT_COMPLETION_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_completion: Box<Account<'info, VaultCompletion>>,
    #[account(
        mut,
        seeds = [VAULT_LEADERBOARD_SEED, &vault.id.to_le_bytes()],
        bump = vault_leaderboard.bump
    )]
    pub vault_leaderboard: Box<Account<'info, VaultLeaderboard>>,
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive,
        constraint = vault_activation.permits_new_economic_history() @ ErrorCode::InvalidActivationSeed
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    /// Rider whose released effort is being applied to the climb.
    /// CHECK: identity is validated against the parent and release authorities.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct VerifyRideTributeBudget<'info> {
    #[account(
        seeds = [
            RIDE_ATTESTATION_SEED,
            ride_attestation.rider.as_ref(),
            &ride_attestation.ride_hash
        ],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        seeds = [RIDE_TRIBUTE_BUDGET_SEED, ride_attestation.key().as_ref()],
        bump = ride_tribute_budget.bump,
        constraint = ride_tribute_budget.ride_attestation == ride_attestation.key()
            @ ErrorCode::InvalidRideTributeBudget,
        constraint = ride_tribute_budget.total_cal_tributed <= ride_tribute_budget.cal_budget
            @ ErrorCode::RideTributeBudgetExceeded
    )]
    pub ride_tribute_budget: Box<Account<'info, RideTributeBudget>>,
}

#[derive(Accounts)]
pub struct VerifyReleasedRideTributeBudget<'info> {
    #[account(
        seeds = [
            RIDE_ATTESTATION_SEED,
            ride_attestation.rider.as_ref(),
            &ride_attestation.ride_hash
        ],
        bump = ride_attestation.bump
    )]
    pub ride_attestation: Box<Account<'info, RideAttestation>>,
    #[account(
        seeds = [HELD_RIDE_RELEASE_SEED, ride_attestation.key().as_ref()],
        bump = release_authority.bump,
        constraint = release_authority.ride_attestation == ride_attestation.key()
            @ ErrorCode::InvalidHeldRideReleaseAuthority,
        constraint = release_authority.rider == ride_attestation.rider
            @ ErrorCode::InvalidHeldRideReleaseAuthority
    )]
    pub release_authority: Box<Account<'info, HeldRideReleaseAuthority>>,
    #[account(
        seeds = [RIDE_TRIBUTE_BUDGET_SEED, ride_attestation.key().as_ref()],
        bump = released_ride_tribute_budget.bump,
        constraint = released_ride_tribute_budget.ride_attestation == ride_attestation.key()
            @ ErrorCode::InvalidHeldRideTributeBudget,
        constraint = released_ride_tribute_budget.release_authority == release_authority.key()
            @ ErrorCode::InvalidHeldRideTributeBudget,
        constraint = released_ride_tribute_budget.total_cal_tributed
            <= released_ride_tribute_budget.cal_budget
            @ ErrorCode::RideTributeBudgetExceeded
    )]
    pub released_ride_tribute_budget: Box<Account<'info, ReleasedRideTributeBudget>>,
}

// --------------------- Beetle Card Contexts ---------------------

#[derive(Accounts)]
#[instruction(card_type: CardType, scope_id: [u8; 32])]
pub struct InitializeBeetleCard<'info> {
    #[account(
        init,
        payer = owner,
        space = BeetleCard::SIZE,
        seeds = [
            BEETLE_CARD_SEED,
            owner.key().as_ref(),
            &[card_type as u8],
            &scope_id,
        ],
        bump
    )]
    pub beetle_card: Account<'info, BeetleCard>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct IncrementBeetleScore<'info> {
    #[account(
        mut,
        seeds = [
            BEETLE_CARD_SEED,
            beetle_card.owner.as_ref(),
            &[beetle_card.card_type as u8],
            &beetle_card.scope_id,
        ],
        bump = beetle_card.bump
    )]
    pub beetle_card: Account<'info, BeetleCard>,
    /// Program config — gates scoring authority
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.backend_authority == scoring_authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// The authority that can increment scores — must match program_config.backend_authority
    pub scoring_authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct GetBeetleCardStats<'info> {
    #[account(
        seeds = [
            BEETLE_CARD_SEED,
            beetle_card.owner.as_ref(),
            &[beetle_card.card_type as u8],
            &beetle_card.scope_id,
        ],
        bump = beetle_card.bump
    )]
    pub beetle_card: Account<'info, BeetleCard>,
}

#[derive(Accounts)]
pub struct UpgradeBeetleCard<'info> {
    #[account(
        mut,
        seeds = [
            BEETLE_CARD_SEED,
            owner.key().as_ref(),
            &[beetle_card.card_type as u8],
            &beetle_card.scope_id,
        ],
        bump = beetle_card.bump,
        constraint = beetle_card.owner == owner.key() @ ErrorCode::UnauthorizedAuthority
    )]
    pub beetle_card: Account<'info, BeetleCard>,
    #[account(mut)]
    pub owner: Signer<'info>,
    /// Program config fixes the canonical DUNG mint and backend gate authority.
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// Backend authority signs after verifying special level gates off-chain.
    #[account(
        constraint = backend_authority.key() == program_config.backend_authority @ ErrorCode::UnauthorizedBackend
    )]
    pub backend_authority: Signer<'info>,
    /// DUNG token mint
    #[account(
        mut,
        constraint = dung_mint.key() == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub dung_mint: Account<'info, Mint>,
    /// Owner's DUNG token account (tokens will be burned from here)
    #[account(
        mut,
        constraint = owner_dung_account.owner == owner.key(),
        constraint = owner_dung_account.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub owner_dung_account: Account<'info, TokenAccount>,
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump = dung_mint_state.bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,
    pub token_program: Program<'info, Token>,
}

// --------------------- Vault Contexts ---------------------

#[derive(Accounts)]
#[instruction(args: RegisterRatifiedClimbArgs)]
pub struct RegisterRatifiedClimb<'info> {
    #[account(
        init,
        payer = admin,
        space = Climb::SIZE,
        seeds = [CLIMB_SEED, args.commitment_hash.as_ref()],
        bump
    )]
    pub climb: Box<Account<'info, Climb>>,
    #[account(
        init,
        payer = admin,
        space = ClimbVersionIndex::SIZE,
        seeds = [
            CLIMB_VERSION_INDEX_SEED,
            args.canon_id.as_ref(),
            &args.canon_version.to_be_bytes()
        ],
        bump
    )]
    pub climb_version_index: Box<Account<'info, ClimbVersionIndex>>,
    /// Optional only for canon version 1. Typed ownership plus handler PDA
    /// verification fail closed for fake successor lineage.
    #[account(mut)]
    pub predecessor_climb: Option<Box<Account<'info, Climb>>>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeVaultCounter<'info> {
    #[account(
        init,
        payer = authority,
        space = VaultCounter::SIZE,
        seeds = [VAULT_COUNTER_SEED],
        bump
    )]
    pub vault_counter: Account<'info, VaultCounter>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct CreateVault<'info> {
    #[account(
        mut,
        seeds = [VAULT_COUNTER_SEED],
        bump = vault_counter.bump
    )]
    pub vault_counter: Box<Account<'info, VaultCounter>>,
    #[account(
        init,
        payer = sponsor_authority,
        space = Vault::SIZE,
        seeds = [VAULT_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    /// CHECK: Writable Climb owner, discriminator, exact size, commitment PDA,
    /// bump, current-head status, and unused Vault link are checked in the
    /// shared binding helper before any identity is copied.
    #[account(mut)]
    pub climb: UncheckedAccount<'info>,
    /// Empty Record Board created atomically with the active V4-B Vault.
    /// CHECK: PDA and emptiness are checked before the account is created and
    /// serialized atomically by `create_empty_vault_leaderboard_account`.
    #[account(
        mut,
        seeds = [VAULT_LEADERBOARD_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault_leaderboard: UncheckedAccount<'info>,
    /// Local Legend account - creator becomes first Soigneur (8-epoch bootstrap term)
    #[account(
        init,
        payer = sponsor_authority,
        space = LocalLegend::SIZE,
        seeds = [LOCAL_LEGEND_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub local_legend: Box<Account<'info, LocalLegend>>,
    /// V4-B activation starts active at generation 2 with frozen empty-history evidence.
    #[account(
        init,
        payer = sponsor_authority,
        space = VaultActivation::SIZE,
        seeds = [VAULT_ACTIVATION_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    /// Configured backend authority sponsors and reserves the global Vault ID.
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    #[account(mut)]
    pub creator: Signer<'info>,
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump
    )]
    pub dung_mint_state: UncheckedAccount<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

/// Vault creation paid with a CAL burn plus a USDC transfer to the treasury.
#[derive(Accounts)]
pub struct CreateVaultWithUsdc<'info> {
    #[account(
        mut,
        seeds = [VAULT_COUNTER_SEED],
        bump = vault_counter.bump
    )]
    pub vault_counter: Box<Account<'info, VaultCounter>>,
    #[account(
        init,
        payer = sponsor_authority,
        space = Vault::SIZE,
        seeds = [VAULT_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    /// CHECK: Validated and persisted by `bind_climb_account_to_vault`.
    #[account(mut)]
    pub climb: UncheckedAccount<'info>,
    /// Empty Record Board created atomically with the active V4-B Vault.
    /// CHECK: Created and serialized atomically by the shared empty-board helper.
    #[account(
        mut,
        seeds = [VAULT_LEADERBOARD_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault_leaderboard: UncheckedAccount<'info>,
    /// Local Legend account - creator becomes first Soigneur (8-epoch bootstrap term)
    #[account(
        init,
        payer = sponsor_authority,
        space = LocalLegend::SIZE,
        seeds = [LOCAL_LEGEND_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub local_legend: Box<Account<'info, LocalLegend>>,
    /// V4-B activation starts active at generation 2 with frozen empty-history evidence.
    #[account(
        init,
        payer = sponsor_authority,
        space = VaultActivation::SIZE,
        seeds = [VAULT_ACTIVATION_SEED, &vault_counter.count.to_le_bytes()],
        bump
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    /// Configured backend authority sponsors and reserves the global Vault ID.
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    #[account(mut)]
    pub creator: Signer<'info>,
    /// Creator's CAL token account (burned: 1000 CAL)
    #[account(mut)]
    pub creator_cal_account: Box<Account<'info, TokenAccount>>,
    /// Protocol treasury USDC account
    #[account(mut)]
    pub protocol_usdc_account: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeVaultLpMint<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        init,
        payer = payer,
        mint::decimals = 9,
        mint::authority = vault,
        mint::freeze_authority = vault,
        mint::token_program = token_program,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Account<'info, Mint>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct InitializeVaultPositionLp<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    /// CHECK: Rider identity is bound into both derived position addresses.
    pub rider: UncheckedAccount<'info>,
    /// CHECK: This PDA may not exist before the rider's first deposit.
    #[account(
        seeds = [VAULT_STAKE_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_stake: UncheckedAccount<'info>,
    #[account(
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        seeds = [VAULT_POSITION_LP_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub position_lp_account: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeRiderBalance<'info> {
    #[account(
        init,
        payer = payer,
        space = RiderBalance::SIZE,
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    /// Rider identity for the Balance. This account is not required to sign.
    /// CHECK: Identity is bound by the RiderBalance PDA seeds.
    pub rider: UncheckedAccount<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct InitializeRiderBalanceToken<'info> {
    #[account(
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    /// Rider identity for the Balance. This account is not required to sign.
    /// CHECK: Identity is bound by the RiderBalance PDA seeds.
    pub rider: UncheckedAccount<'info>,
    /// CHECK: PDA used only as token-account authority.
    #[account(
        seeds = [RIDER_BALANCE_AUTH_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance_authority: UncheckedAccount<'info>,
    #[account(
        init_if_needed,
        payer = payer,
        token::mint = mint,
        token::authority = rider_balance_authority,
        seeds = [RIDER_BALANCE_TOKEN_SEED, rider.key().as_ref(), mint.key().as_ref()],
        bump
    )]
    pub rider_balance_token: Box<Account<'info, TokenAccount>>,
    pub mint: Box<Account<'info, Mint>>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct ConfigureBalanceVaultAuthority<'info> {
    #[account(
        mut,
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump,
        constraint = rider_balance.rider == rider.key() @ ErrorCode::InvalidRiderBalance
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    pub rider: Signer<'info>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        space = BalanceVaultAuthority::SIZE,
        seeds = [BALANCE_VAULT_AUTHORITY_SEED, rider.key().as_ref()],
        bump
    )]
    pub balance_vault_authority: Box<Account<'info, BalanceVaultAuthority>>,
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RevokeBalanceVaultAuthority<'info> {
    #[account(
        mut,
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump,
        constraint = rider_balance.rider == rider.key() @ ErrorCode::InvalidRiderBalance
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    pub rider: Signer<'info>,
    #[account(
        mut,
        seeds = [BALANCE_VAULT_AUTHORITY_SEED, rider.key().as_ref()],
        bump = balance_vault_authority.bump,
        constraint = balance_vault_authority.rider == rider.key() @ ErrorCode::InvalidBalanceVaultAuthority
    )]
    pub balance_vault_authority: Box<Account<'info, BalanceVaultAuthority>>,
}

#[derive(Accounts)]
pub struct SetRiderBalanceStatus<'info> {
    #[account(
        mut,
        seeds = [RIDER_BALANCE_SEED, rider_balance.rider.as_ref()],
        bump = rider_balance.bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == admin.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub admin: Signer<'info>,
}

// --------------------- CAL Staking Contexts ---------------------

#[derive(Accounts)]
pub struct StakeCalInVault<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        space = VaultStake::SIZE,
        seeds = [VAULT_STAKE_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_stake: Box<Account<'info, VaultStake>>,
    /// Vault must be activated before staking is allowed
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive,
        constraint = vault_activation.permits_new_economic_history() @ ErrorCode::InvalidActivationSeed
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    /// Any signer can sponsor rent for the user-owned stake account.
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    #[account(mut)]
    pub staker: Signer<'info>,
    /// Staker's CAL SPL token account (source of staked CAL)
    #[account(mut)]
    pub staker_cal_ata: Box<Account<'info, TokenAccount>>,
    /// Vault CAL escrow (destination for staked CAL, owned by vault PDA)
    #[account(
        mut,
        seeds = [VAULT_CAL_ESCROW_SEED, &vault.id.to_le_bytes()],
        bump,
    )]
    pub vault_cal_escrow: Box<Account<'info, TokenAccount>>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    /// Canonical internal LP custody for this rider-and-Vault position.
    #[account(
        mut,
        seeds = [VAULT_POSITION_LP_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub staker_lp_account: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct DepositCalFromBalance<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        space = VaultStake::SIZE,
        seeds = [VAULT_STAKE_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_stake: Box<Account<'info, VaultStake>>,
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive,
        constraint = vault_activation.permits_new_economic_history() @ ErrorCode::InvalidActivationSeed
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    /// Rider identity for the Balance and VaultStake. This account is not a signer.
    /// CHECK: Identity is bound by RiderBalance and VaultStake PDA seeds.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    /// CHECK: PDA used only as token authority.
    #[account(
        seeds = [RIDER_BALANCE_AUTH_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance_authority: UncheckedAccount<'info>,
    #[account(
        mut,
        seeds = [BALANCE_VAULT_AUTHORITY_SEED, rider.key().as_ref()],
        bump = balance_vault_authority.bump,
        constraint = balance_vault_authority.rider == rider.key() @ ErrorCode::InvalidBalanceVaultAuthority
    )]
    pub balance_vault_authority: Box<Account<'info, BalanceVaultAuthority>>,
    pub operation_authority: Signer<'info>,
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(
        mut,
        seeds = [RIDER_BALANCE_TOKEN_SEED, rider.key().as_ref(), program_config.cal_mint.as_ref()],
        bump
    )]
    pub rider_balance_cal_account: Box<Account<'info, TokenAccount>>,
    #[account(
        mut,
        seeds = [VAULT_CAL_ESCROW_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_cal_escrow: Box<Account<'info, TokenAccount>>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    /// The same canonical position custody used by direct wallet deposits.
    #[account(
        mut,
        seeds = [VAULT_POSITION_LP_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub rider_balance_lp_account: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RestoreVaultLpCustody<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        seeds = [VAULT_STAKE_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump,
        constraint = vault_stake.user == rider.key() @ ErrorCode::InvalidStakeAccount,
        constraint = vault_stake.vault_id == vault.id @ ErrorCode::InvalidStakeAccount
    )]
    pub vault_stake: Box<Account<'info, VaultStake>>,
    /// CHECK: Identity is bound by the VaultStake and custody PDA seeds.
    pub rider: UncheckedAccount<'info>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    pub source_authority: Signer<'info>,
    #[account(
        mut,
        token::mint = vault_lp_mint,
        token::authority = source_authority
    )]
    pub source_lp_account: Box<Account<'info, TokenAccount>>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        seeds = [VAULT_POSITION_LP_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub position_lp_account: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct RestoreBalanceVaultLpCustody<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        seeds = [VAULT_STAKE_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump,
        constraint = vault_stake.user == rider.key() @ ErrorCode::InvalidStakeAccount,
        constraint = vault_stake.vault_id == vault.id @ ErrorCode::InvalidStakeAccount
    )]
    pub vault_stake: Box<Account<'info, VaultStake>>,
    /// CHECK: Identity is bound by the VaultStake and Balance PDA seeds.
    pub rider: UncheckedAccount<'info>,
    /// CHECK: PDA used only as the legacy Balance token authority.
    #[account(
        seeds = [RIDER_BALANCE_AUTH_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance_authority: UncheckedAccount<'info>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    #[account(
        mut,
        seeds = [RIDER_BALANCE_TOKEN_SEED, rider.key().as_ref(), vault_lp_mint.key().as_ref()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = rider_balance_authority
    )]
    pub rider_balance_lp_account: Box<Account<'info, TokenAccount>>,
    #[account(
        init_if_needed,
        payer = sponsor_authority,
        seeds = [VAULT_POSITION_LP_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub position_lp_account: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub sponsor_authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UnstakeCalFromVault<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,
    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump
    )]
    pub vault_stake: Box<Account<'info, VaultStake>>,
    /// Vault must be activated before unstaking is allowed
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump
    )]
    pub vault_activation: Box<Account<'info, VaultActivation>>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub staker: Signer<'info>,
    /// Staker's CAL SPL token account (receives returned CAL)
    #[account(mut)]
    pub staker_cal_ata: Account<'info, TokenAccount>,
    /// Vault CAL escrow (source of returned CAL, owned by vault PDA)
    #[account(
        mut,
        seeds = [VAULT_CAL_ESCROW_SEED, &vault.id.to_le_bytes()],
        bump,
    )]
    pub vault_cal_escrow: Account<'info, TokenAccount>,
    /// CAL SPL mint (for burning exit fee)
    #[account(mut)]
    pub cal_mint: Account<'info, Mint>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Account<'info, Mint>,
    /// Canonical internal LP custody for this rider-and-Vault position.
    #[account(
        mut,
        seeds = [VAULT_POSITION_LP_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub staker_lp_account: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct WithdrawCalToBalance<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump,
        constraint = vault_stake.user == rider.key() @ ErrorCode::InvalidStakeAccount,
        constraint = vault_stake.vault_id == vault.id @ ErrorCode::InvalidStakeAccount
    )]
    pub vault_stake: Account<'info, VaultStake>,
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    /// Rider identity for the Balance and VaultStake. This account is not a signer.
    /// CHECK: Identity is bound by RiderBalance and VaultStake PDA seeds.
    pub rider: UncheckedAccount<'info>,
    #[account(
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    /// CHECK: PDA used only as token authority.
    #[account(
        seeds = [RIDER_BALANCE_AUTH_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance_authority: UncheckedAccount<'info>,
    #[account(
        mut,
        seeds = [BALANCE_VAULT_AUTHORITY_SEED, rider.key().as_ref()],
        bump = balance_vault_authority.bump,
        constraint = balance_vault_authority.rider == rider.key() @ ErrorCode::InvalidBalanceVaultAuthority
    )]
    pub balance_vault_authority: Box<Account<'info, BalanceVaultAuthority>>,
    pub operation_authority: Signer<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(
        mut,
        seeds = [RIDER_BALANCE_TOKEN_SEED, rider.key().as_ref(), program_config.cal_mint.as_ref()],
        bump
    )]
    pub rider_balance_cal_account: Box<Account<'info, TokenAccount>>,
    #[account(
        mut,
        seeds = [VAULT_CAL_ESCROW_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_cal_escrow: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub cal_mint: Box<Account<'info, Mint>>,
    #[account(
        mut,
        seeds = [VAULT_LP_MINT_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_lp_mint: Box<Account<'info, Mint>>,
    /// The same canonical position custody used by direct wallet withdrawals.
    #[account(
        mut,
        seeds = [VAULT_POSITION_LP_SEED, rider.key().as_ref(), &vault.id.to_le_bytes()],
        bump,
        token::mint = vault_lp_mint,
        token::authority = vault_stake
    )]
    pub rider_balance_lp_account: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct WithdrawToWallet<'info> {
    #[account(
        seeds = [RIDER_BALANCE_SEED, rider.key().as_ref()],
        bump = rider_balance.bump
    )]
    pub rider_balance: Box<Account<'info, RiderBalance>>,
    pub rider: Signer<'info>,
    /// CHECK: PDA used only as token authority.
    #[account(
        seeds = [RIDER_BALANCE_AUTH_SEED, rider.key().as_ref()],
        bump
    )]
    pub rider_balance_authority: UncheckedAccount<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump
    )]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(
        mut,
        seeds = [RIDER_BALANCE_TOKEN_SEED, rider.key().as_ref(), mint.key().as_ref()],
        bump
    )]
    pub rider_balance_source: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub rider_wallet_destination: Box<Account<'info, TokenAccount>>,
    pub mint: Box<Account<'info, Mint>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct HarvestRewards<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump
    )]
    pub vault_stake: Account<'info, VaultStake>,
    /// Vault must be activated before rewards can be harvested
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    #[account(mut)]
    pub staker: Signer<'info>,
    /// DUNG mint (DUNG_MINT_AUTH_PDA is mint authority)
    #[account(
        mut,
        constraint = dung_mint.key() == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub dung_mint: Account<'info, Mint>,
    /// Staker's DUNG token account (receives rewards minus fee)
    #[account(
        mut,
        constraint = staker_dung_account.owner == staker.key() @ ErrorCode::InvalidTokenAccount,
        constraint = staker_dung_account.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub staker_dung_account: Account<'info, TokenAccount>,
    /// Protocol treasury DUNG token account (receives 5% fee)
    #[account(
        mut,
        constraint = protocol_treasury.key() == program_config.treasury_token_account @ ErrorCode::InvalidTokenAccount,
        constraint = protocol_treasury.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub protocol_treasury: Account<'info, TokenAccount>,
    /// DUNG mint state (for supply cap enforcement)
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump = dung_mint_state.bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,
    /// Program config (for DUNG mint auth bump)
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// DUNG mint authority PDA
    /// CHECK: Derived from DUNG_MINT_AUTH_SEED, verified by signing
    #[account(
        seeds = [DUNG_MINT_AUTH_SEED],
        bump = program_config.dung_mint_auth_bump,
    )]
    pub dung_mint_auth: UncheckedAccount<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct CollectStakeRewardsFor<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump,
        constraint = vault_stake.user == staker.key() @ ErrorCode::InvalidStakeAccount,
        constraint = vault_stake.vault_id == vault.id @ ErrorCode::InvalidStakeAccount
    )]
    pub vault_stake: Account<'info, VaultStake>,
    /// Vault must be activated before rewards can be collected
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    /// Rider identity for the VaultStake PDA. This account is not a signer.
    /// CHECK: Identity is validated by VaultStake seeds and token destination constraints.
    pub staker: UncheckedAccount<'info>,
    /// Any signer can pay fees or relay the permissionless-for-rider collect.
    #[account(mut)]
    pub payer: Signer<'info>,
    /// DUNG mint (DUNG_MINT_AUTH_PDA is mint authority)
    #[account(
        mut,
        constraint = dung_mint.key() == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub dung_mint: Account<'info, Mint>,
    /// Rider's DUNG token account (receives rewards minus fee)
    #[account(
        mut,
        constraint = staker_dung_account.owner == staker.key() @ ErrorCode::InvalidTokenAccount,
        constraint = staker_dung_account.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub staker_dung_account: Account<'info, TokenAccount>,
    /// Protocol treasury DUNG token account (receives harvest fee)
    #[account(
        mut,
        constraint = protocol_treasury.key() == program_config.treasury_token_account @ ErrorCode::InvalidTokenAccount,
        constraint = protocol_treasury.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub protocol_treasury: Account<'info, TokenAccount>,
    /// DUNG mint state (for supply cap enforcement)
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump = dung_mint_state.bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,
    /// Program config (for DUNG mint auth bump, mint, fee, and treasury)
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// DUNG mint authority PDA
    /// CHECK: Derived from DUNG_MINT_AUTH_SEED, verified by signing
    #[account(
        seeds = [DUNG_MINT_AUTH_SEED],
        bump = program_config.dung_mint_auth_bump,
    )]
    pub dung_mint_auth: UncheckedAccount<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct UpdateVaultMetadata<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// Must be the current rights holder (minter or KOM)
    pub authority: Signer<'info>,
}

// --------------------- Supply Cap Enforcement Contexts ---------------------

#[derive(Accounts)]
pub struct InitializeDungMintState<'info> {
    #[account(
        init,
        payer = authority,
        space = DungMintState::SIZE,
        seeds = [DUNG_MINT_STATE_SEED],
        bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == authority.key() @ ErrorCode::UnauthorizedAdmin,
        constraint = program_config.dung_mint != Pubkey::default() @ ErrorCode::MintsNotConfigured,
        constraint = program_config.epochs_per_halving == EPOCHS_PER_HALVING @ ErrorCode::InvalidProtocolParameters
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct MigrateDungMintState<'info> {
    /// Legacy accounts cannot deserialize into the appended layout, so the
    /// migration validates the discriminator and authority from raw bytes.
    /// CHECK: PDA, owner, discriminator, and stored authority are validated.
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump,
        owner = crate::ID
    )]
    pub dung_mint_state: UncheckedAccount<'info>,
    /// Privileged authorization only; rent and fees are paid separately.
    pub authority: Signer<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == authority.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(
        seeds = [VAULT_COUNTER_SEED],
        bump = vault_counter.bump
    )]
    pub vault_counter: Account<'info, VaultCounter>,
    pub system_program: Program<'info, System>,
}

// --------------------- Distribution Context ---------------------

#[derive(Accounts)]
pub struct DistributeEpochRewards<'info> {
    /// Vault account
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Box<Account<'info, Vault>>,

    /// Vault leaderboard (from Workstream 2)
    #[account(
        seeds = [VAULT_LEADERBOARD_SEED, &vault.id.to_le_bytes()],
        bump = vault_leaderboard.bump
    )]
    pub vault_leaderboard: Account<'info, VaultLeaderboard>,

    /// Local Legend (optional, single elected curator per vault)
    /// Elected by most completions, serves 8-epoch terms
    #[account(
        seeds = [LOCAL_LEGEND_SEED, &vault.id.to_le_bytes()],
        bump = local_legend.bump
    )]
    pub local_legend: Option<Account<'info, LocalLegend>>,
    /// Vault must be activated before epoch rewards can be distributed
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive
    )]
    pub vault_activation: Account<'info, VaultActivation>,

    /// POL (protocol-owned liquidity) token account — must match program_config
    #[account(
        mut,
        constraint = pol_account.key() == program_config.pol_token_account @ ErrorCode::InvalidTokenAccount,
        constraint = pol_account.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub pol_account: Account<'info, TokenAccount>,

    /// Protocol treasury token account — must match program_config
    #[account(
        mut,
        constraint = protocol_treasury.key() == program_config.treasury_token_account @ ErrorCode::InvalidTokenAccount,
        constraint = protocol_treasury.mint == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub protocol_treasury: Account<'info, TokenAccount>,

    /// DUNG mint
    #[account(
        mut,
        constraint = dung_mint.key() == program_config.dung_mint @ ErrorCode::InvalidMint
    )]
    pub dung_mint: Account<'info, Mint>,

    /// DUNG mint state (from Workstream 1, for supply cap)
    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump = dung_mint_state.bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,

    /// Program config — gates backend_authority and stores known POL/treasury accounts
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == backend_authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,

    /// Backend authority that runs the distribution crank
    pub backend_authority: Signer<'info>,

    /// DUNG mint authority PDA (sole DUNG minting authority)
    /// CHECK: Derived from DUNG_MINT_AUTH_SEED, verified by signing
    #[account(
        seeds = [DUNG_MINT_AUTH_SEED],
        bump = program_config.dung_mint_auth_bump,
    )]
    pub dung_mint_auth: UncheckedAccount<'info>,

    pub token_program: Program<'info, Token>,
}

// --------------------- Local Legend Contexts ---------------------

#[derive(Accounts)]
#[instruction(vault_id: u64)]
pub struct MigrateLocalLegend<'info> {
    /// Legacy data cannot deserialize into the appended layout, so migration
    /// validates the raw discriminator, vault id, booleans, and stored bump.
    /// CHECK: PDA, owner, discriminator, vault id, and bump are all validated.
    #[account(
        mut,
        seeds = [LOCAL_LEGEND_SEED, &vault_id.to_le_bytes()],
        bump,
        owner = crate::ID
    )]
    pub local_legend: UncheckedAccount<'info>,
    pub authority: Signer<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == authority.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ElectLocalLegend<'info> {
    /// Vault this legend is for
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,

    /// Local Legend account (init_if_needed for first election)
    #[account(
        init_if_needed,
        payer = authority,
        space = LocalLegend::SIZE,
        seeds = [LOCAL_LEGEND_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub local_legend: Account<'info, LocalLegend>,

    /// Winner of the election (their completion record should be verified off-chain)
    /// CHECK: Verified by backend election process
    pub winner: UncheckedAccount<'info>,

    /// Program config — gates backend_authority for election calls
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,

    /// Backend authority that runs elections — must match program_config.backend_authority
    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ResignLocalLegend<'info> {
    #[account(
        mut,
        seeds = [LOCAL_LEGEND_SEED, &local_legend.vault_id.to_le_bytes()],
        bump = local_legend.bump
    )]
    pub local_legend: Account<'info, LocalLegend>,

    /// Current legend holder signing to resign
    pub legend_holder: Signer<'info>,
}

#[derive(Accounts)]
pub struct DeactivateLocalLegend<'info> {
    /// Vault this legend is for
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,

    #[account(
        mut,
        seeds = [LOCAL_LEGEND_SEED, &vault.id.to_le_bytes()],
        bump = local_legend.bump
    )]
    pub local_legend: Account<'info, LocalLegend>,

    /// Program config — gates backend_authority for dormant rollover calls
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,

    /// Backend authority that runs elections — must match program_config.backend_authority
    #[account(mut)]
    pub authority: Signer<'info>,
}

// --------------------- Vault Activation Contexts ---------------------

#[derive(Accounts)]
pub struct AdminSeedVaultCompletionSummary<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
pub struct AdminReplaceVaultLeaderboard<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        init_if_needed,
        payer = authority,
        space = VaultLeaderboard::SIZE,
        seeds = [VAULT_LEADERBOARD_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_leaderboard: Account<'info, VaultLeaderboard>,
    #[account(
        mut,
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct AdminActivateVault<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
}

#[derive(Accounts)]
#[instruction(vault_id: u64)]
pub struct AdminBackfillVaultActivation<'info> {
    /// CHECK: Vault account verified in handler (owner + PDA seeds).
    /// Using UncheckedAccount to avoid deserializing legacy vault structs.
    pub vault: UncheckedAccount<'info>,
    #[account(
        init,
        payer = authority,
        space = VaultActivation::SIZE,
        seeds = [VAULT_ACTIVATION_SEED, &vault_id.to_le_bytes()],
        bump
    )]
    pub vault_activation: Account<'info, VaultActivation>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.backend_authority == authority.key() @ ErrorCode::UnauthorizedBackend
    )]
    pub program_config: Account<'info, ProgramConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

// --------------------- ProgramConfig Migration Contexts ---------------------

/// Configure CAL and DUNG mint pubkeys (one-time, admin-only)
#[derive(Accounts)]
pub struct ConfigureMints<'info> {
    #[account(
        mut,
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == admin.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    pub admin: Signer<'info>,
}

/// Configure POL and treasury DUNG token accounts (admin-only)
#[derive(Accounts)]
pub struct ConfigureTreasuryAccounts<'info> {
    #[account(
        mut,
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == admin.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    pub admin: Signer<'info>,
}

/// Configure canonical USDC mint, treasury account, and vault payment amount.
#[derive(Accounts)]
pub struct ConfigureUsdcPayment<'info> {
    #[account(
        mut,
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized @ ErrorCode::NotInitialized,
        constraint = program_config.admin_authority == admin.key() @ ErrorCode::UnauthorizedAdmin
    )]
    pub program_config: Account<'info, ProgramConfig>,
    pub admin: Signer<'info>,
    pub usdc_mint: Account<'info, Mint>,
    #[account(
        constraint = usdc_treasury_token_account.mint == usdc_mint.key() @ ErrorCode::InvalidMint
    )]
    pub usdc_treasury_token_account: Account<'info, TokenAccount>,
}

/// Initialize vault CAL escrow ATA (owned by vault PDA)
#[derive(Accounts)]
pub struct InitializeVaultCalEscrow<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump,
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.cal_mint != Pubkey::default() @ ErrorCode::MintsNotConfigured,
    )]
    pub program_config: Account<'info, ProgramConfig>,
    /// Vault CAL escrow token account
    #[account(
        init,
        payer = payer,
        token::mint = cal_mint,
        token::authority = vault,
        seeds = [VAULT_CAL_ESCROW_SEED, &vault.id.to_le_bytes()],
        bump
    )]
    pub vault_cal_escrow: Account<'info, TokenAccount>,
    /// CAL SPL mint
    #[account(
        constraint = cal_mint.key() == program_config.cal_mint @ ErrorCode::InvalidMint,
    )]
    pub cal_mint: Account<'info, Mint>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}
