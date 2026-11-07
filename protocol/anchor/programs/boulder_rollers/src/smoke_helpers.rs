//! Localnet-only test setup instructions, compiled only with the
//! `smoke-helpers` feature, which only the isolated `stage1-localnet` test
//! program enables. Deployable builds contain neither these handlers nor their
//! discriminators: Anchor 0.29 cannot feature-gate a `#[program]` handler, so
//! they are reached through the program's fallback (see `localnet_dispatch`).
//! scripts/build-stage1-localnet.py splices `smoke_helpers_idl.rs` into an
//! IDL-only source copy so the localnet test IDL still describes them.
use super::*;
use std::collections::BTreeSet;

#[derive(AnchorDeserialize)]
struct SettlementWeekArgs {
    settlement_week: u64,
}

#[derive(AnchorDeserialize)]
struct SeedPendingRewardsArgs {
    settlement_week: u64,
    pending_rewards: u64,
}

#[derive(AnchorDeserialize)]
struct StakeEligibilityArgs {
    eligible_from_epoch: u64,
}

/// Route one fallback instruction to a test-setup handler, or report the
/// discriminator as unknown exactly as the deployable fallback does.
pub fn dispatch<'info>(
    program_id: &Pubkey,
    accounts: &'info [AccountInfo<'info>],
    data: &[u8],
) -> Result<()> {
    if data.len() < 8 {
        return Err(anchor_lang::error::ErrorCode::InstructionMissing.into());
    }
    macro_rules! invoke {
        ($accounts:ty, $handler:expr) => {{
            let mut remaining = accounts;
            let mut bumps = <$accounts as anchor_lang::Bumps>::Bumps::default();
            let mut reallocs = BTreeSet::new();
            let mut validated = <$accounts>::try_accounts(
                program_id,
                &mut remaining,
                &data[8..],
                &mut bumps,
                &mut reallocs,
            )?;
            let ctx = Context::new(program_id, &mut validated, remaining, bumps);
            $handler(ctx)?;
            validated.exit(program_id)
        }};
    }
    let discriminator =
        |name: &str| anchor_lang::solana_program::hash::hash(name.as_bytes()).to_bytes();
    if data[..8] == discriminator("global:admin_override_open_settlement_week")[..8] {
        let args = SettlementWeekArgs::deserialize(&mut &data[8..])?;
        invoke!(AdminOverrideOpenSettlementWeek<'info>, |ctx| {
            admin_override_open_settlement_week(ctx, args.settlement_week)
        })
    } else if data[..8] == discriminator("global:admin_seed_pending_rewards")[..8] {
        let args = SeedPendingRewardsArgs::deserialize(&mut &data[8..])?;
        invoke!(AdminSeedPendingRewards<'info>, |ctx| {
            admin_seed_pending_rewards(ctx, args.settlement_week, args.pending_rewards)
        })
    } else if data[..8] == discriminator("global:admin_override_stake_eligibility")[..8] {
        let args = StakeEligibilityArgs::deserialize(&mut &data[8..])?;
        invoke!(AdminOverrideStakeEligibility<'info>, |ctx| {
            admin_override_stake_eligibility(ctx, args.eligible_from_epoch)
        })
    } else {
        Err(anchor_lang::error::ErrorCode::InstructionFallbackNotFound.into())
    }
}

/// Test setup only: override a vault's open settlement week before any
/// live economic activity has started. This keeps Gate 1 deterministic on a
/// fresh lane without weakening the actual runtime settlement semantics.
pub fn admin_override_open_settlement_week(
    ctx: Context<AdminOverrideOpenSettlementWeek>,
    settlement_week: u64,
) -> Result<()> {
    let clock = Clock::get()?;
    let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
    let current_week = settlement_clock.week_at(clock.unix_timestamp)?;
    require!(settlement_week <= current_week, ErrorCode::InvalidEpoch);

    let vault = &mut ctx.accounts.vault;
    require!(vault.total_cal_staked == 0, ErrorCode::VaultNotPristine);
    require!(vault.pending_rewards == 0, ErrorCode::VaultNotPristine);
    require!(
        vault.pending_rewards_next_week == 0,
        ErrorCode::VaultNotPristine
    );
    require!(vault.carry_record_royalty == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_stakers == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_local_legend == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_pol == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_treasury == 0, ErrorCode::VaultNotPristine);

    vault.open_settlement_week = settlement_week;
    vault.last_distribution_epoch = settlement_week.saturating_sub(1);
    Ok(())
}

/// Test setup only: seed a reward-authoritative vault's current settlement
/// week with a deterministic pending balance so Gate 1 can finalize a fresh
/// lane without waiting for wall-clock time to pass.
pub fn admin_seed_pending_rewards(
    ctx: Context<AdminSeedPendingRewards>,
    settlement_week: u64,
    pending_rewards: u64,
) -> Result<()> {
    require!(pending_rewards > 0, ErrorCode::InvalidAmount);

    let vault = &mut ctx.accounts.vault;
    require!(
        settlement_week == vault.open_settlement_week,
        ErrorCode::InvalidEpoch
    );
    require!(vault.pending_rewards == 0, ErrorCode::VaultNotPristine);
    require!(
        vault.pending_rewards_next_week == 0,
        ErrorCode::VaultNotPristine
    );
    require!(vault.carry_record_royalty == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_stakers == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_local_legend == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_pol == 0, ErrorCode::VaultNotPristine);
    require!(vault.carry_treasury == 0, ErrorCode::VaultNotPristine);

    vault.pending_rewards = pending_rewards;
    Ok(())
}

/// Test setup only: make a freshly-created stake eligible for a
/// rewound Settlement Week so Gate 1 can prove harvestability on a pristine
/// lane without weakening the live staking maturity rules.
pub fn admin_override_stake_eligibility(
    ctx: Context<AdminOverrideStakeEligibility>,
    eligible_from_epoch: u64,
) -> Result<()> {
    let vault = &ctx.accounts.vault;
    let stake = &mut ctx.accounts.vault_stake;

    require!(stake.rewards_earned == 0, ErrorCode::VaultNotPristine);
    require!(stake.cal_staked > 0, ErrorCode::InvalidAmount);
    require!(
        eligible_from_epoch <= vault.open_settlement_week,
        ErrorCode::InvalidEpoch
    );

    let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
    stake.initialize_snapshot_if_legacy(&settlement_clock, vault.open_settlement_week)?;
    stake.effective_lp_tokens = stake.lp_tokens;
    stake.pending_lp_tokens = 0;
    stake.pending_effective_week_plus_one = 0;
    Ok(())
}

#[derive(Accounts)]
pub struct AdminOverrideOpenSettlementWeek<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
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
pub struct AdminSeedPendingRewards<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active @ ErrorCode::VaultNotActive,
        constraint = vault_activation.permits_new_economic_history() @ ErrorCode::InvalidActivationSeed
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
pub struct AdminOverrideStakeEligibility<'info> {
    #[account(
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,
    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, vault_stake.user.as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump
    )]
    pub vault_stake: Account<'info, VaultStake>,
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
