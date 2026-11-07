//! One immutable, explicitly unbranded SPL test pool per devnet deployment.
use super::*;
use std::collections::BTreeSet;

pub const S1_TEST_POOL: &[u8] = b"s1v1_test_pool";

#[account]
#[derive(InitSpace)]
pub struct Stage1TestPool {
    pub version: u8,
    pub provider: Pubkey,
    pub mint: Pubkey,
    pub bump: u8,
}

#[derive(Accounts)]
pub struct Stage1RegisterTestPool<'info> {
    #[account(init, payer = admin, space = 8 + Stage1TestPool::INIT_SPACE, seeds = [S1_TEST_POOL], bump)]
    pub test_pool: Account<'info, Stage1TestPool>,
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(init, payer = admin, space = 8 + Stage1AssetConfig::INIT_SPACE, seeds = [S1_ASSET, mint.key().as_ref()], bump)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    pub mint: Box<Account<'info, Mint>>,
    /// CHECK: the SPL owner, complete layout and embedded mint are checked below.
    pub provider: UncheckedAccount<'info>,
    /// CHECK: make_custody initializes the SPL account at this exact PDA.
    #[account(mut, seeds = [S1_EARNINGS, mint.key().as_ref()], bump)]
    pub earnings: UncheckedAccount<'info>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn register(ctx: Context<Stage1RegisterTestPool>) -> Result<()> {
    {
        // Retained in the deployed ELF; artifact tooling rejects other clusters.
        msg!("BOULDERROLLER_STAGE1_DEVNET_TEST_POOL");
        let mint = ctx.accounts.mint.key();
        require!(stage1_providers::kind(mint).is_none(), ErrorCode::Stage1InvalidAsset);
        require!((ctx.accounts.city.asset_count as usize) < S1_ASSET_SLOTS, ErrorCode::Stage1InvalidAsset);
        let asset = &mut ctx.accounts.asset;
        asset.version = 1;
        asset.city = ctx.accounts.city.key();
        asset.mint = mint;
        asset.adapter = stage1_providers::DEVNET_TEST_SPL;
        asset.provider_account = ctx.accounts.provider.key();
        asset.slot = ctx.accounts.city.asset_count;
        asset.bump = ctx.bumps.asset;
        let observation = stage1_providers::observe(asset, &[
            ctx.accounts.provider.to_account_info(), ctx.accounts.mint.to_account_info(),
        ], Clock::get()?.epoch)?;
        require!(observation.current, ErrorCode::Stage1StaleRate);
        ctx.accounts.city.asset_count += 1;
        ctx.accounts.city.provider_slots |= 1u32 << asset.slot;
        stage1::make_custody(
            ctx.accounts.earnings.to_account_info(), asset.to_account_info(),
            ctx.accounts.mint.to_account_info(), ctx.accounts.admin.to_account_info(),
            ctx.accounts.system_program.to_account_info(), ctx.accounts.token_program.to_account_info(),
            S1_EARNINGS, mint,
        )?;
        ctx.accounts.test_pool.set_inner(Stage1TestPool {
            version: 1, provider: asset.provider_account, mint, bump: ctx.bumps.test_pool,
        });
        // Intentionally disabled and without a synthetic quote. Ordinary
        // permissionless refresh and explicit admin enablement must follow.
        Ok(())
    }
}

/// Feature-only fallback retains normal Anchor validation, init and exit hooks.
pub fn dispatch<'info>(program_id: &Pubkey, accounts: &'info [AccountInfo<'info>], data: &[u8]) -> Result<()> {
    if data.len() < 8 { return Err(anchor_lang::error::ErrorCode::InstructionMissing.into()); }
    // This actual dispatch name also binds the artifact guard to the ABI.
    let discriminator = anchor_lang::solana_program::hash::hash(b"global:register_stage1_test_pool").to_bytes();
    if data[..8] != discriminator[..8] {
        return Err(anchor_lang::error::ErrorCode::InstructionFallbackNotFound.into());
    }
    let mut remaining = accounts;
    let mut bumps = <Stage1RegisterTestPool as anchor_lang::Bumps>::Bumps::default();
    let mut reallocs = BTreeSet::new();
    let mut validated = Stage1RegisterTestPool::try_accounts(program_id, &mut remaining, &data[8..], &mut bumps, &mut reallocs)?;
    register(Context::new(program_id, &mut validated, remaining, bumps))?;
    validated.exit(program_id)
}
