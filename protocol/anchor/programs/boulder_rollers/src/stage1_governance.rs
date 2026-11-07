//! Pause/resume guardian and admission-only registrar. Economic administration uses the
//! single ProgramConfig admin, which can be a Squads vault PDA signer.
use super::*;

/// Historical unreleased layouts, including the discriminator. Fields after
/// the shared 881-byte 1c prefix were appended independently on two branches.
pub const S1_CITY_INITIAL_SIZE: usize = 881;
pub fn migrate_city_bytes(data: &[u8]) -> Result<Vec<u8>> {
    let size = 8 + Stage1CityConfig::INIT_SPACE;
    require!(size == 963 && [881, 897, 914, 915, 931, 963].contains(&data.len()), ErrorCode::Stage1InvalidCityLayout);
    require!(data[..8] == <Stage1CityConfig as anchor_lang::Discriminator>::discriminator(), ErrorCode::Stage1InvalidCityLayout);
    let mut out = vec![0u8; size];
    out[..881].copy_from_slice(&data[..881]);
    match data.len() {
        881 => (),
        897 => out[881..897].copy_from_slice(&data[881..897]),
        914 | 915 => out[897..897 + data.len() - 881].copy_from_slice(&data[881..]),
        931 | 963 => out[..data.len()].copy_from_slice(data),
        _ => return err!(ErrorCode::Stage1InvalidCityLayout),
    }
    Stage1CityConfig::try_deserialize(&mut out.as_slice())?;
    Ok(out)
}
/// Anyone can pay the exact top-up. Preserve historical semantic fields;
/// fresh registrar is disabled and a missing DUNG start remains unset.
pub fn migrate_city(ctx: Context<Stage1MigrateCity>) -> Result<()> {
    let city = ctx.accounts.city.to_account_info();
    let size = 8 + Stage1CityConfig::INIT_SPACE;
    let bytes = migrate_city_bytes(&city.try_borrow_data()?)?;
    if city.data_len() == size {
        Stage1CityConfig::try_deserialize(&mut &city.try_borrow_data()?[..])?;
        return Ok(());
    }
    let top_up = Rent::get()?.minimum_balance(size).saturating_sub(city.lamports());
    if top_up > 0 {
        anchor_lang::solana_program::program::invoke(
            &anchor_lang::solana_program::system_instruction::transfer(
                &ctx.accounts.payer.key(), &city.key(), top_up),
            &[ctx.accounts.payer.to_account_info(), city.clone(), ctx.accounts.system_program.to_account_info()],
        )?;
    }
    city.realloc(size, true)?;
    city.try_borrow_mut_data()?.copy_from_slice(&bytes);
    Ok(())
}

pub fn set_guardian(ctx: Context<Stage1AdminGovernance>, guardian: Pubkey) -> Result<()> {
    require!(guardian != Pubkey::default()
        && guardian != ctx.accounts.admin.key()
        && guardian != ctx.accounts.program_config.backend_authority
        && guardian != ctx.accounts.city.publisher
        && guardian != ctx.accounts.city.registrar, ErrorCode::Stage1InvalidGuardian);
    ctx.accounts.city.guardian = guardian;
    // Rotation never resumes intake, even if the previous guardian was lost.
    Ok(())
}

pub fn set_registrar(ctx: Context<Stage1AdminGovernance>, registrar: Pubkey) -> Result<()> {
    require!(registrar == Pubkey::default() || (registrar != ctx.accounts.admin.key()
        && registrar != ctx.accounts.program_config.backend_authority
        && registrar != ctx.accounts.city.publisher
        && registrar != ctx.accounts.city.guardian), ErrorCode::Stage1Unauthorized);
    ctx.accounts.city.registrar = registrar;
    Ok(())
}

/// Preserve registerRatifiedClimb's deployed account metas. A registrar must
/// additionally supply the canonical city as the sole remaining account.
pub fn authorize_registrar(config: &ProgramConfig, signer: Pubkey, remaining: &[AccountInfo]) -> Result<()> {
    if signer == config.admin_authority { return Ok(()); }
    require!(remaining.len() == 1, ErrorCode::UnauthorizedAdmin);
    let city = &remaining[0];
    require!(city.key() == Pubkey::find_program_address(&[S1_CITY], &crate::ID).0
        && city.owner == &crate::ID && !city.executable, ErrorCode::UnauthorizedAdmin);
    let state = Stage1CityConfig::try_deserialize(&mut &city.try_borrow_data()?[..])?;
    require!(state.registrar != Pubkey::default() && state.registrar == signer, ErrorCode::UnauthorizedAdmin);
    Ok(())
}

pub fn pause(ctx: Context<Stage1PauseIntake>) -> Result<()> {
    ctx.accounts.city.intake_paused = true;
    Ok(())
}

pub fn resume(ctx: Context<Stage1ResumeGovernance>) -> Result<()> {
    ctx.accounts.city.intake_paused = false;
    Ok(())
}

pub fn pause_settlement(ctx: Context<Stage1PauseIntake>) -> Result<()> {
    ctx.accounts.city.settlement_paused = true;
    Ok(())
}

pub fn resume_settlement(ctx: Context<Stage1ResumeGovernance>) -> Result<()> {
    ctx.accounts.city.settlement_paused = false;
    Ok(())
}

pub fn settlement_open(city: &Stage1CityConfig) -> Result<()> {
    require!(!city.settlement_paused, ErrorCode::Stage1SettlementPaused);
    Ok(())
}

#[derive(Accounts)]
pub struct Stage1AdminGovernance<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub admin: Signer<'info>,
}

#[derive(Accounts)]
pub struct Stage1ResumeGovernance<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && (program_config.admin_authority == admin.key()
            || (city.guardian != Pubkey::default() && city.guardian == admin.key())) @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub admin: Signer<'info>,
}

#[derive(Accounts)]
pub struct Stage1PauseIntake<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump,
        constraint = city.guardian != Pubkey::default() && city.guardian == guardian.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    pub guardian: Signer<'info>,
}

#[derive(Accounts)]
pub struct Stage1MigrateCity<'info> {
    /// CHECK: Exact old/new length and discriminator checked before expansion.
    #[account(mut, seeds = [S1_CITY], bump, owner = crate::ID)]
    pub city: UncheckedAccount<'info>,
    #[account(mut)]
    pub payer: Signer<'info>,
    pub system_program: Program<'info, System>,
}
