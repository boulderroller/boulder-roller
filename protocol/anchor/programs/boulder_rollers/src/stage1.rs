//! Stage 1 v1 custody. Authority: STAGE1_SPEC.md, ratified 2026-10-13.
//! Provider-backed intake is available in deployable builds. Synthetic rates
//! remain isolated behind `stage1-localnet`.
//! Intake caps use deposit-basis counters. Campaign valuation is resumable,
//! one lot per refresh; no instruction accepts an inventory of lots.
use super::stage1_providers as providers;
use super::*;

pub const S1_CITY: &[u8] = b"s1v1_city";
pub const S1_ASSET: &[u8] = b"s1v1_asset";
pub const S1_HILL: &[u8] = b"s1v1_hill";
pub const S1_LOT: &[u8] = b"s1v1_lot";
pub const S1_EXIT: &[u8] = b"s1v1_exit";
pub const S1_CUSTODY: &[u8] = b"s1v1_custody";
pub const S1_OWNER: &[u8] = b"s1v1_owner";
pub const S1_EARNINGS: &[u8] = b"s1v1_earnings";
pub const S1_REQUEST: &[u8] = b"s1v1_request";
pub const S1_WEEK: i64 = 604_800;
pub const S1_LINE: u64 = 10_000_000_000;
pub const S1_TOKEN_CAP: u64 = 2_000_000_000_000;
pub const S1_HILL_CAP: u64 = 500_000_000_000;
pub const S1_TOTAL_CAP: u64 = 5_000_000_000_000;
// Test fixture freshness, NOT admission policy for any production provider.
pub const S1_TEST_RATE_MAX_AGE: i64 = 60;
// Bounded local-adapter registry, stable slots; not a production allowlist.
pub const S1_ASSET_SLOTS: usize = 32;

#[account]
#[derive(InitSpace)]
pub struct Stage1CityConfig {
    pub version: u8,
    pub line_lamports: u64,
    pub live_lamports: u64,
    pub season_anchor: i64,
    pub season_weeks: u16,
    pub token_cap_lamports: u64,
    pub hill_cap_lamports: u64,
    pub total_cap_lamports: u64,
    pub held_lots: u64,
    pub held_basis_lamports: u64,
    pub asset_count: u8,
    pub rate_epochs: [u64; 32],
    pub fresh_until: [i64; 32],
    pub bump: u8,
    /// Real providers use epoch freshness; local fixtures retain seconds.
    pub provider_slots: u32,
    pub admitted_epochs: [u64; 32],
    pub publisher: Pubkey,
    pub dung_tss_ceiling_micros: u64,
    /// Zero means disabled; otherwise the configured start week plus one.
    pub dung_start_week_plus_one: u64,
    /// Separate emergency signer. It can pause and resume intake and settlement.
    pub guardian: Pubkey,
    pub intake_paused: bool,
    pub settlement_paused: bool,
    /// Admits ratified climbs and hills only; rotation remains admin-only.
    pub registrar: Pubkey,
}

#[account]
#[derive(InitSpace)]
pub struct Stage1AssetConfig {
    pub version: u8,
    pub city: Pubkey,
    pub mint: Pubkey,
    pub enabled: bool,
    pub adapter: u8,
    pub rate_numerator: u64,
    pub rate_denominator: u64,
    pub observed_at: i64,
    pub observation_admitted: bool,
    pub last_fresh_until: i64,
    pub admitted_numerator: u64,
    pub admitted_denominator: u64,
    pub slot: u8,
    pub held_basis_lamports: u64,
    /// Deployment-wide lifetime accumulator, never reset on exits/fee payment.
    pub harvested_units: u128,
    pub fees_assessed: u128,
    pub bump: u8,
    pub provider_account: Pubkey,
    pub admitted_epoch: u64,
    /// First successful authenticated observation of an expired provider.
    pub provider_stale_since: i64,
    pub outage_provider_epoch: u64,
    /// Authenticated unparseable/impossible state has no native update witness.
    pub outage_is_opaque: bool,
    pub ledger: Stage1Ledger,
}

#[account]
#[derive(InitSpace)]
pub struct Stage1HillBond {
    pub version: u8,
    pub city: Pubkey,
    pub climb: Pubkey,
    pub canon_id: [u8; 16],
    pub commitment_hash: [u8; 32],
    pub bonded: bool,
    pub bonded_at: i64,
    pub founder: Pubkey,
    pub founding_count: u64,
    /// Membership also requires the lot's bit in the immutable founding mask.
    pub founding_cutoff: u64,
    pub founding_fresh_slots: u32,
    pub last_sequence: u64,
    pub held_basis_lamports: u64,
    pub campaign_count: u64,
    pub asset_lots: [u64; 32],
    pub rate_epochs: [u64; 32],
    pub quoted_count: [u64; 32],
    pub quoted_backing: [u64; 32],
    /// Current per-slot quotes, frozen at bond; excluded slots have zero rates.
    pub quoted_numerators: [u64; 32],
    pub quoted_denominators: [u64; 32],
    pub bump: u8,
    /// Prior-epoch quotes retained for founding only; zero bonding-line value.
    pub founding_lagging_slots: u32,
    /// Settlement starts at admission, never at the city's week zero.
    pub admitted_week: u64,
    /// Conservative historical bounds for publisher-attested DUNG openings.
    /// Never compare a past opening to today's (possibly withdrawn) basis.
    pub dung_deposited_basis: u128,
    pub dung_founding_basis: u64,
    /// Latest ordinary deposit lock end. Complete only when no campaign lot
    /// was excluded at bonding (excluded conversions have a readonly hill).
    pub dung_lock_ends: [i64; 3],
    pub dung_next_week: u64,
    pub dung_publication_commitment: [u8; 32],
}

#[account]
#[derive(InitSpace)]
pub struct Stage1PledgeLot {
    pub version: u8,
    pub city: Pubkey,
    pub hill: Pubkey,
    pub owner: Pubkey,
    pub mint: Pubkey,
    pub asset_slot: u8,
    pub deposit_id: u64,
    pub deposited_at: i64,
    pub sequence: u64,
    pub cancelled: bool,
    pub quote_epoch: u64,
    pub quote_numerator: u64,
    pub quote_denominator: u64,
    pub quoted_backing: u64,
    pub units: u64,
    pub basis_lamports: u64,
    pub lock_weeks: u16,
    pub lock_end: i64,
    pub founding: bool,
    /// Owner converted an excluded pre-bond lot into ordinary, non-founding stake.
    pub converted: bool,
    pub exiting: bool,
    pub exit_request: Pubkey,
    pub pending_request: Pubkey,
    /// These units have separate token custody and never count as backing.
    pub owner_units: u64,
    pub prebond_units_frozen: u64,
    pub harvested_units: u64,
    /// Shortfall at the last validated observation, not a promise of recovery.
    pub observed_loss_lamports: u64,
    /// None when returned without a fresh rate; never invent a SOL loss.
    pub realized_loss_lamports: Option<u64>,
    pub returned_units: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Stage1WithdrawalRequest {
    pub version: u8,
    pub lot: Pubkey,
    pub owner: Pubkey,
    pub request_id: u64,
    pub basis_lamports: u64,
    pub notice_at: i64,
    pub eligible_at: i64,
    pub exit_lot: Pubkey,
    /// 0 notice, 1 exiting, 2 returned, 3 cancelled. Never reused/closed.
    pub status: u8,
    pub bump: u8,
}

#[derive(Clone, Copy)]
pub struct Stage1Rate {
    pub n: u64,
    pub d: u64,
}

fn floor_ratio(a: u64, b: u64, d: u64) -> Result<u128> {
    require!(d != 0, ErrorCode::Stage1InvalidRate);
    Ok((a as u128 * b as u128) / d as u128)
}
fn ceil_ratio(a: u64, b: u64, d: u64) -> Result<u128> {
    require!(d != 0, ErrorCode::Stage1InvalidRate);
    let product = a as u128 * b as u128;
    Ok(product / d as u128 + u128::from(product % d as u128 != 0))
}
fn narrow(value: u128) -> Result<u64> {
    u64::try_from(value).map_err(|_| error!(ErrorCode::Stage1Arithmetic))
}
fn add(a: u64, b: u64) -> Result<u64> {
    a.checked_add(b)
        .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
}
fn date(start: i64, weeks: u16) -> Result<i64> {
    start
        .checked_add(i64::from(weeks) * S1_WEEK)
        .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
}
impl Stage1Rate {
    fn basis(self, units: u64) -> Result<u64> {
        narrow(ceil_ratio(units, self.n, self.d)?)
    }
    fn backing(self, lot: &Stage1PledgeLot) -> Result<u64> {
        narrow(floor_ratio(lot.units, self.n, self.d)?.min(lot.basis_lamports as u128))
    }
    fn surplus(self, units: u64, basis: u64) -> Result<u64> {
        let protected = ceil_ratio(basis, self.d, self.n)?;
        narrow((units as u128).saturating_sub(protected))
    }
}

/// A rate is admitted only together with adapter provenance and freshness.
/// Delivery means actual SPL units; observations alone never create income.
trait Stage1LstAdapter {
    fn rate(
        asset: &Stage1AssetConfig,
        now: i64,
        provider_accounts: &[AccountInfo],
    ) -> Result<Stage1Rate>;
    fn deliver<'info>(
        token_program: AccountInfo<'info>,
        from: AccountInfo<'info>,
        to: AccountInfo<'info>,
        authority: AccountInfo<'info>,
        seeds: &[&[u8]],
        amount: u64,
        _provider_accounts: &[AccountInfo<'info>],
    ) -> Result<()> {
        if amount == 0 {
            return Ok(());
        }
        token::transfer(
            CpiContext::new_with_signer(
                token_program,
                Transfer {
                    from,
                    to,
                    authority,
                },
                &[seeds],
            ),
            amount,
        )
    }
}
#[cfg(feature = "stage1-localnet")]
struct LocalnetTestLst;
#[cfg(feature = "stage1-localnet")]
impl Stage1LstAdapter for LocalnetTestLst {
    fn rate(
        asset: &Stage1AssetConfig,
        now: i64,
        _provider_accounts: &[AccountInfo],
    ) -> Result<Stage1Rate> {
        require!(asset.adapter == 1, ErrorCode::Stage1AdapterDisabled);
        require!(
            asset.rate_numerator > 0 && asset.rate_denominator > 0,
            ErrorCode::Stage1InvalidRate
        );
        require!(now < asset.last_fresh_until, ErrorCode::Stage1StaleRate);
        // A rejected attempt is diagnostic only. Price custody with the last
        // admitted quote until its original window expires.
        Ok(Stage1Rate {
            n: asset.admitted_numerator,
            d: asset.admitted_denominator,
        })
    }
}
struct ActiveAdapter;
impl Stage1LstAdapter for ActiveAdapter {
    fn rate(asset: &Stage1AssetConfig, now: i64, accounts: &[AccountInfo]) -> Result<Stage1Rate> {
        #[cfg(feature = "stage1-localnet")]
        if asset.adapter == 1 {
            return LocalnetTestLst::rate(asset, now, accounts);
        }
        let epoch = Clock::get()?.epoch;
        let availability = providers::inspect(asset, accounts, epoch)?;
        if provider_fresh(asset, epoch) {
            return admitted_rate(asset);
        }
        // A healthy provider must be admitted before pricing; it can NEVER be
        // used as evidence for a stale escape just because the cache expired.
        require!(!availability.current(), ErrorCode::Stage1RateRefreshRequired);
        err!(ErrorCode::Stage1StaleRate)
    }
}
fn admitted_rate(asset: &Stage1AssetConfig) -> Result<Stage1Rate> {
    require!(
        asset.admitted_numerator > 0 && asset.admitted_denominator > 0,
        ErrorCode::Stage1InvalidRate
    );
    Ok(Stage1Rate {
        n: asset.admitted_numerator,
        d: asset.admitted_denominator,
    })
}
fn provider_fresh(asset: &Stage1AssetConfig, epoch: u64) -> bool {
    asset.admitted_denominator > 0 && asset.admitted_epoch == epoch
}
fn admit_provider(
    city: &mut Stage1CityConfig,
    asset: &mut Stage1AssetConfig,
    observation: providers::Observation,
    clock: &Clock,
) -> Result<()> {
    require!(observation.current, ErrorCode::Stage1StaleRate);
    require!(
        asset.admitted_denominator == 0 || asset.admitted_epoch <= clock.epoch,
        ErrorCode::Stage1InvalidRate
    );
    let slot = asset.slot as usize;
    require!(
        slot < S1_ASSET_SLOTS && city.provider_slots & (1u32 << slot) != 0,
        ErrorCode::Stage1InvalidAsset
    );
    // A successful usable observation ends an outage, even if this epoch's
    // admitted price is immutable and the new numerical value is ignored.
    asset.provider_stale_since = 0;
    asset.outage_provider_epoch = 0;
    asset.outage_is_opaque = false;
    if provider_fresh(asset, clock.epoch) {
        return Ok(());
    }
    let Stage1Rate { n, d } = observation.rate;
    if asset.admitted_denominator == 0
        || n as u128 * asset.admitted_denominator as u128
            != d as u128 * asset.admitted_numerator as u128
    {
        city.rate_epochs[slot] = add(city.rate_epochs[slot], 1)?;
    }
    asset.rate_numerator = n;
    asset.rate_denominator = d;
    asset.admitted_numerator = n;
    asset.admitted_denominator = d;
    asset.observed_at = clock.unix_timestamp;
    asset.observation_admitted = true;
    asset.admitted_epoch = clock.epoch;
    city.admitted_epochs[slot] = clock.epoch;
    asset.provider_stale_since = 0;
    Ok(())
}
/// No authority signer: provenance comes exclusively from the pinned accounts.
pub fn refresh_provider(ctx: Context<Stage1RefreshRate>) -> Result<()> {
    let clock = Clock::get()?;
    let availability = providers::inspect(
        &ctx.accounts.asset,
        &[
            ctx.accounts.provider.to_account_info(),
            ctx.accounts.mint.to_account_info(),
        ],
        clock.epoch,
    )?;
    let observation = availability.observation.ok_or(ErrorCode::Stage1InvalidProvider)?;
    admit_provider(
        &mut ctx.accounts.city,
        &mut ctx.accounts.asset,
        observation,
        &clock,
    )
}
/// Conservative seven-day grace begins at an authenticated unavailable reading,
/// never at a caller's timestamp or an inferred epoch duration. This separate
/// successful instruction cannot revoke a still-admitted epoch.
pub fn record_provider_outage(ctx: Context<Stage1RefreshRate>) -> Result<()> {
    let clock = Clock::get()?;
    let availability = providers::inspect(
        &ctx.accounts.asset,
        &[
            ctx.accounts.provider.to_account_info(),
            ctx.accounts.mint.to_account_info(),
        ],
        clock.epoch,
    )?;
    require!(
        !availability.current()
            && !provider_fresh(&ctx.accounts.asset, clock.epoch)
            && !availability.lagging(clock.epoch),
        ErrorCode::Stage1ProviderAvailable
    );
    require!(
        ctx.accounts.asset.admitted_denominator > 0
            && ctx.accounts.asset.admitted_epoch < clock.epoch,
        ErrorCode::Stage1InvalidRate
    );
    let (opaque, marker) = availability.outage_marker();
    if ctx.accounts.asset.provider_stale_since == 0
        || ctx.accounts.asset.outage_is_opaque != opaque
        || ctx.accounts.asset.outage_provider_epoch != marker
    {
        ctx.accounts.asset.provider_stale_since = clock.unix_timestamp;
        ctx.accounts.asset.outage_provider_epoch = marker;
        ctx.accounts.asset.outage_is_opaque = opaque;
    }
    Ok(())
}

fn check_lot(lot: &Stage1PledgeLot, key: Pubkey) -> Result<()> {
    let id = lot.deposit_id.to_le_bytes();
    let exit_seeds: &[&[u8]] = &[S1_EXIT, lot.exit_request.as_ref()];
    let pledge_seeds: &[&[u8]] = &[S1_LOT, lot.owner.as_ref(), &id];
    let seeds: &[&[u8]] = if lot.exiting {
        exit_seeds
    } else {
        pledge_seeds
    };
    let (expected, bump) = Pubkey::find_program_address(seeds, &crate::ID);
    require!(
        lot.version == 1 && lot.bump == bump && (lot.asset_slot as usize) < S1_ASSET_SLOTS,
        ErrorCode::Stage1InvalidLot
    );
    require_keys_eq!(key, expected, ErrorCode::Stage1InvalidLot);
    Ok(())
}
fn send_lot<'info>(
    lot: &Stage1PledgeLot,
    authority: AccountInfo<'info>,
    token_program: AccountInfo<'info>,
    from: AccountInfo<'info>,
    to: AccountInfo<'info>,
    units: u64,
) -> Result<()> {
    check_lot(lot, *authority.key)?;
    let id = lot.deposit_id.to_le_bytes();
    let bump = [lot.bump];
    let exit_seeds: &[&[u8]] = &[S1_EXIT, lot.exit_request.as_ref(), &bump];
    let pledge_seeds: &[&[u8]] = &[S1_LOT, lot.owner.as_ref(), &id, &bump];
    let seeds: &[&[u8]] = if lot.exiting {
        exit_seeds
    } else {
        pledge_seeds
    };
    ActiveAdapter::deliver(token_program, from, to, authority, seeds, units, &[])
}

pub(crate) fn read_owned<T: AccountDeserialize + Owner>(info: &AccountInfo) -> Result<T> {
    require_keys_eq!(*info.owner, T::owner(), ErrorCode::Stage1InvalidInventory);
    T::try_deserialize(&mut &info.try_borrow_data()?[..])
        .map_err(|_| error!(ErrorCode::Stage1InvalidInventory))
}
fn check_tokens(
    info: &AccountInfo,
    lot_key: Pubkey,
    mint: Pubkey,
    seed: &[u8],
    tracked: u64,
) -> Result<()> {
    let expected = Pubkey::find_program_address(&[seed, lot_key.as_ref()], &crate::ID).0;
    require_keys_eq!(*info.key, expected, ErrorCode::Stage1InvalidCustody);
    let account: TokenAccount = read_owned(info)?;
    require!(
        account.owner == lot_key && account.mint == mint && account.amount >= tracked,
        ErrorCode::Stage1InvalidCustody
    );
    // Unsolicited tokens are untracked: cannot repair a loss, pay riders, or
    // freeze a lot by breaking exact equality. No instruction spends them.
    Ok(())
}
fn check_custody(
    lot: &Stage1PledgeLot,
    key: Pubkey,
    custody: &AccountInfo,
    reserve: &AccountInfo,
) -> Result<()> {
    check_lot(lot, key)?;
    check_tokens(custody, key, lot.mint, S1_CUSTODY, lot.units)?;
    check_tokens(reserve, key, lot.mint, S1_OWNER, lot.owner_units)
}

// Separate frame: several Anchor-generated SPL initializers exceed SBF's stack.
// Lamport-prefunded PDAs are allocated/assigned, so dust cannot deny an exit.
#[inline(never)]
#[allow(clippy::too_many_arguments)]
pub(crate) fn make_custody<'info>(
    account: AccountInfo<'info>,
    lot: AccountInfo<'info>,
    mint: AccountInfo<'info>,
    payer: AccountInfo<'info>,
    system: AccountInfo<'info>,
    token_program: AccountInfo<'info>,
    prefix: &[u8],
    seed_key: Pubkey,
) -> Result<()> {
    use anchor_lang::system_program::{self, Allocate, Assign};
    use anchor_spl::token::InitializeAccount3;
    let (expected, bump) = Pubkey::find_program_address(&[prefix, seed_key.as_ref()], &crate::ID);
    require_keys_eq!(expected, *account.key, ErrorCode::Stage1InvalidCustody);
    require!(
        account.data_is_empty() && *account.owner == anchor_lang::system_program::ID,
        ErrorCode::Stage1InvalidCustody
    );
    let needed = Rent::get()?
        .minimum_balance(TokenAccount::LEN)
        .saturating_sub(account.lamports());
    if needed > 0 {
        system_program::transfer(
            CpiContext::new(
                system.clone(),
                system_program::Transfer {
                    from: payer,
                    to: account.clone(),
                },
            ),
            needed,
        )?;
    }
    let seeds: &[&[u8]] = &[prefix, seed_key.as_ref(), &[bump]];
    system_program::allocate(
        CpiContext::new_with_signer(
            system.clone(),
            Allocate {
                account_to_allocate: account.clone(),
            },
            &[seeds],
        ),
        TokenAccount::LEN as u64,
    )?;
    system_program::assign(
        CpiContext::new_with_signer(
            system,
            Assign {
                account_to_assign: account.clone(),
            },
            &[seeds],
        ),
        &token::ID,
    )?;
    token::initialize_account3(CpiContext::new(
        token_program,
        InitializeAccount3 {
            account,
            mint,
            authority: lot,
        },
    ))
}

pub fn initialize_city(ctx: Context<Stage1InitCity>, season_anchor: i64) -> Result<()> {
    require!(
        season_anchor >= SETTLEMENT_WEEK_V2_ANCHOR
            && (season_anchor - SETTLEMENT_WEEK_V2_ANCHOR) % S1_WEEK == 0,
        ErrorCode::Stage1InvalidCalendar
    );
    *ctx.accounts.city = Stage1CityConfig {
        version: 1,
        line_lamports: S1_LINE,
        live_lamports: S1_LINE / 2,
        season_anchor,
        season_weeks: 26,
        token_cap_lamports: S1_TOKEN_CAP,
        hill_cap_lamports: S1_HILL_CAP,
        total_cap_lamports: S1_TOTAL_CAP,
        held_lots: 0,
        held_basis_lamports: 0,
        asset_count: 0,
        rate_epochs: [0; 32],
        fresh_until: [0; 32],
        bump: ctx.bumps.city,
        provider_slots: 0,
        admitted_epochs: [0; 32],
        publisher: Pubkey::default(),
        dung_tss_ceiling_micros: 0,
        dung_start_week_plus_one: 0,
        guardian: Pubkey::default(),
        intake_paused: false,
        settlement_paused: false,
        registrar: Pubkey::default(),
    };
    Ok(())
}

pub fn configure(ctx: Context<Stage1ConfigureAsset>, enabled: bool) -> Result<()> {
    require!(ctx.accounts.asset.adapter != S1_CASH_ADAPTER, ErrorCode::Stage1InvalidAsset);
    let kind = providers::kind(ctx.accounts.mint.key()).or_else(|| {
        // Only registration can initialize this adapter. No caller-chosen identity.
        if cfg!(feature = "stage1-devnet") && ctx.accounts.asset.version == 1
            && ctx.accounts.asset.adapter == providers::DEVNET_TEST_SPL {
            Some(providers::DEVNET_TEST_SPL)
        } else { None }
    });
    require!(
        kind.is_some() || cfg!(feature = "stage1-localnet"),
        ErrorCode::Stage1AdapterDisabled
    );
    let asset = &mut ctx.accounts.asset;
    if asset.version == 0 {
        asset.version = 1;
        asset.city = ctx.accounts.city.key();
        asset.mint = ctx.accounts.mint.key();
        require!(
            (ctx.accounts.city.asset_count as usize) < S1_ASSET_SLOTS,
            ErrorCode::Stage1InvalidAsset
        );
        asset.slot = ctx.accounts.city.asset_count;
        ctx.accounts.city.asset_count += 1;
        asset.adapter = kind.unwrap_or(1);
        if let Some(kind) = kind {
            asset.provider_account = providers::identity(kind)?.1;
            ctx.accounts.city.provider_slots |= 1u32 << asset.slot;
        }
        asset.bump = ctx.bumps.asset;
    }
    require!(
        asset.city == ctx.accounts.city.key() && asset.mint == ctx.accounts.mint.key(),
        ErrorCode::Stage1InvalidAsset
    );
    if ctx.accounts.earnings.data_is_empty() {
        make_custody(
            ctx.accounts.earnings.to_account_info(),
            asset.to_account_info(),
            ctx.accounts.mint.to_account_info(),
            ctx.accounts.admin.to_account_info(),
            ctx.accounts.system_program.to_account_info(),
            ctx.accounts.token_program.to_account_info(),
            S1_EARNINGS,
            ctx.accounts.mint.key(),
        )?;
    } else {
        let earnings: TokenAccount = read_owned(&ctx.accounts.earnings.to_account_info())?;
        require!(
            earnings.owner == asset.key() && earnings.mint == asset.mint,
            ErrorCode::Stage1InvalidCustody
        );
    }
    if enabled && kind.is_some() {
        let clock = Clock::get()?;
        require!(
            provider_fresh(asset, clock.epoch),
            ErrorCode::Stage1RateRefreshRequired
        );
        let observation = providers::observe(asset, ctx.remaining_accounts, clock.epoch)?;
        require!(observation.current, ErrorCode::Stage1StaleRate);
        require!(
            asset.adapter != providers::JUP || observation.exits_verified,
            ErrorCode::Stage1ProviderPolicyUnverified
        );
    }
    asset.enabled = enabled;
    // Register disabled, validate permissionlessly, then explicitly enable.
    Ok(())
}

#[cfg(feature = "stage1-localnet")]
pub fn test_rate(ctx: Context<Stage1TestRate>, n: u64, d: u64, observed_at: i64) -> Result<()> {
    require!(
        ctx.accounts.asset.adapter == 1,
        ErrorCode::Stage1AdapterDisabled
    );
    require!(n > 0 && d > 0, ErrorCode::Stage1InvalidRate);
    let now = Clock::get()?.unix_timestamp;
    let until = observed_at
        .checked_add(S1_TEST_RATE_MAX_AGE + 1)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    let admitted = observed_at <= now && now < until;
    let asset = &mut ctx.accounts.asset;
    let slot = asset.slot as usize;
    require!(slot < S1_ASSET_SLOTS, ErrorCode::Stage1InvalidAsset);
    asset.rate_numerator = n;
    asset.rate_denominator = d;
    asset.observed_at = observed_at;
    asset.observation_admitted = admitted;
    if admitted {
        let until = until.max(asset.last_fresh_until);
        if asset.admitted_denominator == 0
            || n as u128 * asset.admitted_denominator as u128
                != d as u128 * asset.admitted_numerator as u128
        {
            ctx.accounts.city.rate_epochs[slot] = add(ctx.accounts.city.rate_epochs[slot], 1)?;
        }
        asset.admitted_numerator = n;
        asset.admitted_denominator = d;
        asset.last_fresh_until = until;
        ctx.accounts.city.fresh_until[slot] = until;
    }
    // Rejected observations never change either admitted expiry or quote.
    Ok(())
}

pub fn initialize_hill(ctx: Context<Stage1InitHill>) -> Result<()> {
    let city: Stage1CityConfig = read_owned(&ctx.accounts.city.to_account_info())?;
    require!(city.bump == ctx.bumps.city, ErrorCode::Stage1InvalidCityLayout);
    let config: ProgramConfig = read_owned(&ctx.accounts.program_config.to_account_info())?;
    require!(config.initialized && (config.admin_authority == ctx.accounts.admin.key()
        || (city.registrar != Pubkey::default() && city.registrar == ctx.accounts.admin.key())), ErrorCode::Stage1Unauthorized);
    let climb = &ctx.accounts.climb;
    require!(
        climb.successor_climb == Pubkey::default(),
        ErrorCode::Stage1InvalidHill
    );
    let commitment = build_canon_commitment_v1(
        climb.canon_id,
        climb.canon_version,
        climb.canonical_profile_hash,
    )?;
    require!(
        climb.canon_commitment == commitment
            && climb.commitment_hash == canon_commitment_hash(&commitment),
        ErrorCode::Stage1InvalidHill
    );
    let hill = &mut ctx.accounts.hill;
    hill.version = 1;
    hill.city = ctx.accounts.city.key();
    hill.climb = climb.key();
    hill.canon_id = climb.canon_id;
    hill.commitment_hash = climb.commitment_hash;
    hill.bump = ctx.bumps.hill;
    hill.admitted_week = stage1_claims::week_at(
        city.season_anchor,
        Clock::get()?.unix_timestamp.max(city.season_anchor),
    )?;
    Ok(())
}

// A numerical rate change invalidates only that token slot. A stale slot has
// no readiness requirement and counts as zero; unrelated intake stays usable.
fn sync_campaign(hill: &mut Stage1HillBond, city: &Stage1CityConfig) -> Result<()> {
    for i in 0..S1_ASSET_SLOTS {
        if hill.rate_epochs[i] != city.rate_epochs[i] {
            hill.quoted_count[i] = 0;
            hill.quoted_backing[i] = 0;
            hill.quoted_numerators[i] = 0;
            hill.quoted_denominators[i] = 0;
            hill.rate_epochs[i] = city.rate_epochs[i];
        }
    }
    Ok(())
}
fn quote(lot: &mut Stage1PledgeLot, hill: &mut Stage1HillBond, rate: Stage1Rate) -> Result<()> {
    let slot = lot.asset_slot as usize;
    if lot.quote_epoch == hill.rate_epochs[slot] {
        hill.quoted_backing[slot] = hill.quoted_backing[slot]
            .checked_sub(lot.quoted_backing)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
    } else {
        hill.quoted_count[slot] = add(hill.quoted_count[slot], 1)?;
    }
    lot.quote_epoch = hill.rate_epochs[slot];
    lot.quote_numerator = rate.n;
    lot.quote_denominator = rate.d;
    lot.quoted_backing = rate.backing(lot)?;
    hill.quoted_backing[slot] = add(hill.quoted_backing[slot], lot.quoted_backing)?;
    hill.quoted_numerators[slot] = rate.n;
    hill.quoted_denominators[slot] = rate.d;
    Ok(())
}
fn fresh_campaign(
    hill: &Stage1HillBond,
    city: &Stage1CityConfig,
    now: i64,
    epoch: u64,
    lagging_slots: u32,
    unreadable_slots: u32,
) -> Result<(u64, u64, u32)> {
    let (mut backing, mut count, mut mask) = (0, 0, 0);
    for i in 0..S1_ASSET_SLOTS {
        let fresh = if city.provider_slots & (1u32 << i) != 0 {
            (unreadable_slots | lagging_slots) & (1u32 << i) == 0
                && city.rate_epochs[i] > 0 && city.admitted_epochs[i] == epoch
        } else {
            now < city.fresh_until[i]
        };
        if hill.asset_lots[i] > 0 && (fresh || lagging_slots & (1u32 << i) != 0) {
            if fresh {
                require!(
                    hill.rate_epochs[i] == city.rate_epochs[i]
                        && hill.quoted_count[i] == hill.asset_lots[i],
                    ErrorCode::Stage1CampaignRefreshRequired
                );
                backing = add(backing, hill.quoted_backing[i])?;
            }
            count = add(count, hill.asset_lots[i])?;
            mask |= 1u32 << i;
        }
    }
    Ok((backing, count, mask))
}
pub fn refresh(ctx: Context<Stage1Refresh>) -> Result<()> {
    require!(
        !ctx.accounts.hill.bonded
            && ctx.accounts.lot.basis_lamports > 0
            && !ctx.accounts.lot.exiting,
        ErrorCode::Stage1CannotCancel
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let rate = ActiveAdapter::rate(
        &ctx.accounts.asset,
        Clock::get()?.unix_timestamp,
        ctx.remaining_accounts,
    )?;
    sync_campaign(&mut ctx.accounts.hill, &ctx.accounts.city)?;
    quote(&mut ctx.accounts.lot, &mut ctx.accounts.hill, rate)
}

/// Remaining accounts: [asset (writable), provider state, mint] for each
/// backed real-provider slot plus the incoming real asset, in slot order.
/// Disabled intake does not let a bonder omit already-custodied principal.
fn refresh_backed(
    city_key: Pubkey,
    city: &mut Stage1CityConfig,
    hill: &mut Stage1HillBond,
    incoming: &mut Stage1AssetConfig,
    accounts: &[AccountInfo],
    clock: &Clock,
) -> Result<(u32, u32)> {
    let mut cursor = 0;
    let mut lagging_slots = 0;
    let mut unreadable_slots = 0;
    for slot in 0..city.asset_count as usize {
        if city.provider_slots & (1u32 << slot) == 0
            || (hill.asset_lots[slot] == 0 && incoming.slot as usize != slot)
        {
            continue;
        }
        let group = accounts
            .get(cursor..cursor + 3)
            .ok_or(ErrorCode::Stage1InvalidProvider)?;
        cursor += 3;
        let mut asset: Stage1AssetConfig = read_owned(&group[0])?;
        let (address, bump) =
            Pubkey::find_program_address(&[S1_ASSET, asset.mint.as_ref()], &crate::ID);
        require!(
            group[0].is_writable
                && *group[0].key == address
                && asset.bump == bump
                && asset.version == 1
                && asset.city == city_key
                && asset.slot as usize == slot,
            ErrorCode::Stage1InvalidProvider
        );
        let is_incoming = incoming.slot as usize == slot;
        let asset = if is_incoming {
            &mut *incoming
        } else {
            &mut asset
        };
        let availability = providers::inspect(asset, &group[1..], clock.epoch)?;
        if let Some(observation) = availability.observation {
            if observation.current {
                admit_provider(city, asset, observation, clock)?;
            }
            if availability.lagging(clock.epoch) {
                require!(!is_incoming, ErrorCode::Stage1StaleRate);
                lagging_slots |= 1u32 << slot;
                sync_campaign(hill, city)?;
                // Grace follows the pool, not refresh activity in this program.
                // Freeze its own last-epoch quote without admitting line value.
                hill.quoted_numerators[slot] = observation.rate.n;
                hill.quoted_denominators[slot] = observation.rate.d;
            } else if provider_fresh(asset, clock.epoch) {
                sync_campaign(hill, city)?;
                // An earlier below-line pledge may have stored a lagged quote.
                // Recovery to the same cached ratio does not bump the revision,
                // so explicitly restore the admitted quote before bonding.
                hill.quoted_numerators[slot] = asset.admitted_numerator;
                hill.quoted_denominators[slot] = asset.admitted_denominator;
            }
        } else {
            require!(!is_incoming, ErrorCode::Stage1InvalidProvider);
            // The cached quote remains available for exits, but unreadable
            // accounting cannot back a bond, even in its admitted epoch.
            unreadable_slots |= 1u32 << slot;
        }
        if !is_incoming {
            asset.try_serialize(&mut &mut group[0].try_borrow_mut_data()?[..])?;
        }
    }
    require!(cursor == accounts.len(), ErrorCode::Stage1InvalidProvider);
    Ok((lagging_slots, unreadable_slots))
}
pub fn deposit(
    ctx: Context<Stage1Pledge>,
    deposit_id: u64,
    units: u64,
    lock_weeks: u16,
    must_bond: bool,
) -> Result<()> {
    require!(!ctx.accounts.city.intake_paused, ErrorCode::Stage1IntakePaused);
    let clock = Clock::get()?;
    let now = clock.unix_timestamp;
    require!(
        units > 0 && [0, 13, 26, 52].contains(&lock_weeks),
        ErrorCode::Stage1InvalidAmount
    );
    require!(
        now >= ctx.accounts.city.season_anchor,
        ErrorCode::Stage1NotLaunched
    );
    require!(
        ctx.accounts.climb.canon_id == ctx.accounts.hill_account.hill.canon_id
            && ctx.accounts.climb.successor_climb == Pubkey::default(),
        ErrorCode::Stage1InvalidHill
    );
    require!(ctx.accounts.asset.enabled, ErrorCode::Stage1AdapterDisabled);
    let mut lagging_slots = 0;
    let mut unreadable_slots = 0;
    if !ctx.accounts.hill_account.hill.bonded {
        (lagging_slots, unreadable_slots) = refresh_backed(
            ctx.accounts.city.key(),
            &mut ctx.accounts.city,
            &mut ctx.accounts.hill_account.hill,
            &mut ctx.accounts.asset,
            ctx.remaining_accounts,
            &clock,
        )?;
    } else if ctx.accounts.asset.adapter != 1 {
        let availability =
            providers::inspect(&ctx.accounts.asset, ctx.remaining_accounts, clock.epoch)?;
        require!(
            availability.observation.is_some(),
            ErrorCode::Stage1InvalidProvider
        );
        require!(!availability.lagging(clock.epoch), ErrorCode::Stage1StaleRate);
        if let Some(observation) = availability.observation.filter(|o| o.current) {
            admit_provider(
                &mut ctx.accounts.city,
                &mut ctx.accounts.asset,
                observation,
                &clock,
            )?;
        } else {
            require!(
                provider_fresh(&ctx.accounts.asset, clock.epoch),
                ErrorCode::Stage1StaleRate
            );
        }
    }
    let rate = if ctx.accounts.asset.adapter == 1 {
        ActiveAdapter::rate(&ctx.accounts.asset, now, &[])?
    } else {
        require!(
            provider_fresh(&ctx.accounts.asset, clock.epoch),
            ErrorCode::Stage1StaleRate
        );
        admitted_rate(&ctx.accounts.asset)?
    };
    let basis = rate.basis(units)?;
    let city_key = ctx.accounts.city.key();
    let hill_key = ctx.accounts.hill_account.hill.key();
    let mint = ctx.accounts.mint.key();
    let total = add(ctx.accounts.city.held_basis_lamports, basis)?;
    let token_total = add(ctx.accounts.asset.held_basis_lamports, basis)?;
    let hill_total = add(ctx.accounts.hill_account.hill.held_basis_lamports, basis)?;
    require!(
        total <= ctx.accounts.city.total_cap_lamports
            && token_total <= ctx.accounts.city.token_cap_lamports
            && hill_total <= ctx.accounts.city.hill_cap_lamports,
        ErrorCode::Stage1ExposureCap
    );
    if !ctx.accounts.hill_account.hill.bonded {
        sync_campaign(&mut ctx.accounts.hill_account.hill, &ctx.accounts.city)?;
        fresh_campaign(
            &ctx.accounts.hill_account.hill,
            &ctx.accounts.city,
            now,
            clock.epoch,
            lagging_slots,
            unreadable_slots,
        )?;
    }
    ctx.accounts.asset.check_accounting()?;
    ctx.accounts.asset.ledger.deposit(units)?;
    let lot = &mut ctx.accounts.lot;
    lot.version = 1;
    lot.city = city_key;
    lot.hill = hill_key;
    lot.owner = ctx.accounts.owner.key();
    lot.mint = mint;
    lot.asset_slot = ctx.accounts.asset.slot;
    lot.deposit_id = deposit_id;
    lot.deposited_at = now;
    lot.units = units;
    lot.basis_lamports = basis;
    lot.observed_loss_lamports = basis - rate.backing(lot)?;
    lot.lock_weeks = lock_weeks;
    lot.bump = ctx.bumps.lot;
    let hill = &mut ctx.accounts.hill_account.hill;
    hill.last_sequence = add(hill.last_sequence, 1)?;
    lot.sequence = hill.last_sequence;
    if !hill.bonded {
        quote(lot, hill, rate)?;
        hill.campaign_count = add(hill.campaign_count, 1)?;
        let slot = ctx.accounts.asset.slot as usize;
        hill.asset_lots[slot] = add(hill.asset_lots[slot], 1)?;
    }
    let (backing, founding_count, founding_slots) = if hill.bonded {
        (0, 0, 0)
    } else {
        fresh_campaign(hill, &ctx.accounts.city, now, clock.epoch, lagging_slots, unreadable_slots)?
    };
    let crossing = !hill.bonded && backing >= ctx.accounts.city.line_lamports;
    require!(!must_bond || crossing, ErrorCode::Stage1BelowLine);
    for (account, prefix) in [
        (ctx.accounts.custody.to_account_info(), S1_CUSTODY),
        (ctx.accounts.owner_reserve.to_account_info(), S1_OWNER),
    ] {
        make_custody(
            account,
            lot.to_account_info(),
            ctx.accounts.mint.to_account_info(),
            ctx.accounts.owner.to_account_info(),
            ctx.accounts.system_program.to_account_info(),
            ctx.accounts.token_program.to_account_info(),
            prefix,
            lot.key(),
        )?;
    }
    token::transfer(
        CpiContext::new(
            ctx.accounts.token_program.to_account_info(),
            Transfer {
                from: ctx.accounts.source.to_account_info(),
                to: ctx.accounts.custody.to_account_info(),
                authority: ctx.accounts.owner.to_account_info(),
            },
        ),
        units,
    )?;
    ctx.accounts.city.held_lots = add(ctx.accounts.city.held_lots, 1)?;
    ctx.accounts.city.held_basis_lamports = total;
    ctx.accounts.asset.held_basis_lamports = token_total;
    ctx.accounts.hill_account.hill.held_basis_lamports = hill_total;
    let hill = &mut ctx.accounts.hill_account.hill;
    hill.dung_deposited_basis = hill.dung_deposited_basis.checked_add(basis as u128)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    if hill.bonded {
        lot.lock_end = date(now, lock_weeks)?;
        record_dung_lock(hill, lock_weeks, lot.lock_end);
    } else if crossing {
        hill.dung_founding_basis = hill_total;
        hill.dung_next_week = stage1_claims::week_at(ctx.accounts.city.season_anchor, now)?
            .checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
        hill.bonded = true;
        hill.bonded_at = now;
        hill.founder = ctx.accounts.owner.key();
        hill.founding_count = founding_count;
        hill.founding_cutoff = hill.last_sequence;
        hill.founding_fresh_slots = founding_slots;
        hill.founding_lagging_slots = lagging_slots & founding_slots;
        for i in 0..S1_ASSET_SLOTS {
            if founding_slots & (1u32 << i) == 0 {
                hill.quoted_numerators[i] = 0;
                hill.quoted_denominators[i] = 0;
            }
        }
        found(lot, rate, now)?; // ceil-basis new lot has no surplus.
    }
    ctx.accounts.asset.check_accounting()
}
fn found(lot: &mut Stage1PledgeLot, rate: Stage1Rate, now: i64) -> Result<()> {
    let surplus = rate.surplus(lot.units, lot.basis_lamports)?;
    lot.units -= surplus;
    lot.owner_units = surplus;
    lot.prebond_units_frozen = surplus;
    lot.founding = true;
    lot.lock_weeks = 26;
    lot.lock_end = date(now, 26)?;
    lot.observed_loss_lamports = lot.basis_lamports - rate.backing(lot)?;
    Ok(())
}

fn record_dung_lock(hill: &mut Stage1HillBond, weeks: u16, end: i64) {
    if let Some(index) = [13, 26, 52].iter().position(|w| *w == weeks) {
        hill.dung_lock_ends[index] = hill.dung_lock_ends[index].max(end);
    }
}

fn is_founding(lot: &Stage1PledgeLot, hill: &Stage1HillBond) -> bool {
    hill.bonded
        && !lot.cancelled
        && !lot.exiting
        && !lot.converted
        && lot.sequence > 0
        && lot.sequence <= hill.founding_cutoff
        && (lot.asset_slot as usize) < S1_ASSET_SLOTS
        && hill.founding_fresh_slots & (1u32 << lot.asset_slot) != 0
}
fn is_active(lot: &Stage1PledgeLot, hill: &Stage1HillBond) -> bool {
    hill.bonded
        && !lot.cancelled
        && (lot.exiting
            || lot.converted
            || lot.sequence > hill.founding_cutoff
            || is_founding(lot, hill))
}
fn materialize<'info>(
    lot: &mut Stage1PledgeLot,
    hill: &Stage1HillBond,
    key: AccountInfo<'info>,
    custody: AccountInfo<'info>,
    reserve: AccountInfo<'info>,
    token_program: AccountInfo<'info>,
) -> Result<()> {
    if !lot.founding && is_founding(lot, hill) {
        let slot = lot.asset_slot as usize;
        require!(
            lot.quote_epoch == hill.rate_epochs[slot]
                || hill.founding_lagging_slots & (1u32 << slot) != 0,
            ErrorCode::Stage1InvalidLot
        );
        let rate = Stage1Rate {
            n: hill.quoted_numerators[slot],
            d: hill.quoted_denominators[slot],
        };
        let surplus = rate.surplus(lot.units, lot.basis_lamports)?;
        send_lot(lot, key, token_program, custody, reserve, surplus)?;
        found(lot, rate, hill.bonded_at)?;
    }
    Ok(())
}
pub fn materialize_lot(ctx: Context<Stage1Refresh>) -> Result<()> {
    require!(ctx.accounts.hill.bonded, ErrorCode::Stage1NotBonded);
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let key = ctx.accounts.lot.to_account_info();
    materialize(
        &mut ctx.accounts.lot,
        &ctx.accounts.hill,
        key,
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    )?;
    ctx.accounts.asset.check_accounting()
}
fn returned_basis(
    city: &mut Stage1CityConfig,
    asset: &mut Stage1AssetConfig,
    hill: &mut Stage1HillBond,
    basis: u64,
) -> Result<()> {
    city.held_basis_lamports = city
        .held_basis_lamports
        .checked_sub(basis)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    asset.held_basis_lamports = asset
        .held_basis_lamports
        .checked_sub(basis)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    hill.held_basis_lamports = hill
        .held_basis_lamports
        .checked_sub(basis)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    city.held_lots = city
        .held_lots
        .checked_sub(1)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    Ok(())
}
// Real-provider grace starts at an authenticated unavailable observation after
// admission/grace expiry. Both exit steps recheck it; opaque state cannot prove
// unobserved provider history. Usable readmission clears the outage record.
fn exit_rate(
    asset: &Stage1AssetConfig,
    now: i64,
    providers: &[AccountInfo],
) -> Result<Option<Stage1Rate>> {
    match ActiveAdapter::rate(asset, now, providers) {
        Ok(rate) => Ok(Some(rate)),
        Err(error) => {
            if !matches!(&error, anchor_lang::error::Error::AnchorError(e)
                if e.error_code_number == ErrorCode::Stage1StaleRate as u32 + 6000)
            {
                return Err(error);
            }
            if asset.adapter != 1 {
                let epoch = Clock::get()?.epoch;
                let availability = providers::inspect(asset, providers, epoch)?;
                let (opaque, marker) = availability.outage_marker();
                require!(
                    !availability.lagging(epoch)
                        && opaque == asset.outage_is_opaque
                        && marker == asset.outage_provider_epoch,
                    ErrorCode::Stage1StaleRate
                );
            }
            let stale_since = if asset.adapter == 1 {
                asset.last_fresh_until
            } else {
                asset.provider_stale_since
            };
            require!(
                stale_since > 0
                    && now
                        >= stale_since
                            .checked_add(S1_WEEK)
                            .ok_or(ErrorCode::Stage1Arithmetic)?,
                ErrorCode::Stage1StaleRate
            );
            // The fallback authorizes only an in-kind transfer, never valuation.
            Ok(None)
        }
    }
}

pub fn cancel(ctx: Context<Stage1OwnerLot>) -> Result<()> {
    require!(
        !is_active(&ctx.accounts.lot, &ctx.accounts.hill)
            && !ctx.accounts.lot.exiting
            && ctx.accounts.lot.basis_lamports > 0,
        ErrorCode::Stage1CannotCancel
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let units = ctx.accounts.lot.units;
    send_lot(
        &ctx.accounts.lot,
        ctx.accounts.lot.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.destination.to_account_info(),
        units,
    )?;
    if !ctx.accounts.hill.bonded {
        sync_campaign(&mut ctx.accounts.hill, &ctx.accounts.city)?;
    }
    let lot = &mut ctx.accounts.lot;
    let hill = &mut ctx.accounts.hill;
    if !hill.bonded {
        let slot = lot.asset_slot as usize;
        hill.asset_lots[slot] = hill.asset_lots[slot]
            .checked_sub(1)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
        if lot.quote_epoch == hill.rate_epochs[slot] {
            hill.quoted_count[slot] = hill.quoted_count[slot]
                .checked_sub(1)
                .ok_or(ErrorCode::Stage1Arithmetic)?;
            hill.quoted_backing[slot] = hill.quoted_backing[slot]
                .checked_sub(lot.quoted_backing)
                .ok_or(ErrorCode::Stage1Arithmetic)?;
        }
        hill.campaign_count = hill
            .campaign_count
            .checked_sub(1)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
    }
    returned_basis(
        &mut ctx.accounts.city,
        &mut ctx.accounts.asset,
        hill,
        lot.basis_lamports,
    )?;
    ctx.accounts.asset.ledger.owner_return(units, 0)?;
    lot.returned_units = add(lot.returned_units, units)?;
    lot.units = 0;
    lot.basis_lamports = 0;
    lot.cancelled = true;
    ctx.accounts.asset.check_accounting()
}
pub fn convert(ctx: Context<Stage1Convert>, lock_weeks: u16) -> Result<()> {
    require!(!ctx.accounts.city.intake_paused, ErrorCode::Stage1IntakePaused);
    require!(
        [0, 13, 26, 52].contains(&lock_weeks),
        ErrorCode::Stage1InvalidAmount
    );
    require!(
        ctx.accounts.hill.bonded
            && !is_active(&ctx.accounts.lot, &ctx.accounts.hill)
            && !ctx.accounts.lot.cancelled
            && !ctx.accounts.lot.exiting
            && ctx.accounts.lot.basis_lamports > 0
            && ctx.accounts.lot.pending_request == Pubkey::default(),
        ErrorCode::Stage1CannotCancel
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let now = Clock::get()?.unix_timestamp;
    let rate = ActiveAdapter::rate(&ctx.accounts.asset, now, ctx.remaining_accounts)?;
    let lot = &mut ctx.accounts.lot;
    let surplus = rate.surplus(lot.units, lot.basis_lamports)?;
    send_lot(
        lot,
        lot.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        surplus,
    )?;
    lot.units -= surplus;
    lot.owner_units = surplus;
    lot.prebond_units_frozen = surplus;
    lot.converted = true;
    lot.lock_weeks = lock_weeks;
    lot.lock_end = date(now, lock_weeks)?;
    lot.observed_loss_lamports = lot.basis_lamports - rate.backing(lot)?;
    ctx.accounts.asset.check_accounting()
}
pub fn prebond(ctx: Context<Stage1OwnerLot>) -> Result<()> {
    require!(
        ctx.accounts.hill.bonded && !ctx.accounts.lot.exiting,
        ErrorCode::Stage1CannotCancel
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let key = ctx.accounts.lot.to_account_info();
    materialize(
        &mut ctx.accounts.lot,
        &ctx.accounts.hill,
        key,
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    )?;
    let units = ctx.accounts.lot.owner_units;
    send_lot(
        &ctx.accounts.lot,
        ctx.accounts.lot.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.destination.to_account_info(),
        units,
    )?;
    ctx.accounts.lot.returned_units = add(ctx.accounts.lot.returned_units, units)?;
    ctx.accounts.lot.owner_units = 0;
    ctx.accounts.asset.ledger.owner_return(0, units)?;
    ctx.accounts.asset.check_accounting()
}

#[event]
pub struct Stage1IncomeDelivered {
    pub lot: Pubkey,
    pub hill: Pubkey,
    pub mint: Pubkey,
    pub units: u64,
    pub fee_units: u64,
    pub timestamp: i64,
}
#[allow(clippy::too_many_arguments)]
fn sweep<'info>(
    lot: &mut Stage1PledgeLot,
    key: AccountInfo<'info>,
    asset: &mut Stage1AssetConfig,
    rate: Stage1Rate,
    custody: AccountInfo<'info>,
    earnings: AccountInfo<'info>,
    token_program: AccountInfo<'info>,
    requested: Option<u64>,
    now: i64,
    anchor: i64,
    funding: Option<&AccountInfo>,
) -> Result<()> {
    asset.check_earnings(&earnings)?;
    let surplus = rate.surplus(lot.units, lot.basis_lamports)?;
    let amount = requested.unwrap_or(surplus);
    require!(amount <= surplus, ErrorCode::Stage1PrincipalProtected);
    lot.observed_loss_lamports = lot.basis_lamports - rate.backing(lot)?;
    if amount == 0 {
        return Ok(());
    }
    send_lot(lot, key.clone(), token_program, custody, earnings.clone(), amount)?;
    let lifetime = asset
        .harvested_units
        .checked_add(amount as u128)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    let fees = lifetime / 10;
    let fee = narrow(
        fees.checked_sub(asset.fees_assessed)
            .ok_or(ErrorCode::Stage1Arithmetic)?,
    )?;
    let asset_key = Pubkey::find_program_address(&[S1_ASSET, lot.mint.as_ref()], &crate::ID).0;
    stage1_claims::credit_harvest(funding, lot.city, lot.hill, asset_key, lot.mint,
        stage1_claims::week_at(anchor, now)?, *key.key, amount, fee)?;
    asset.ledger.harvest(amount, fee)?;
    asset.harvested_units = lifetime;
    asset.fees_assessed = fees;
    lot.units -= amount;
    lot.harvested_units = add(lot.harvested_units, amount)?;
    emit!(Stage1IncomeDelivered {
        lot: *key.key,
        hill: lot.hill,
        mint: lot.mint,
        units: amount,
        fee_units: fee,
        timestamp: now
    });
    asset.check_earnings(&earnings)
}

fn sweep_accounts<'a, 'info>(asset: &Stage1AssetConfig, accounts: &'a [AccountInfo<'info>])
    -> Result<(&'a [AccountInfo<'info>], Option<&'a AccountInfo<'info>>)> {
    let providers = if asset.adapter == 1 { 0 } else { 2 };
    require!(accounts.len() >= providers && accounts.len() <= providers + 1, ErrorCode::Stage1InvalidProvider);
    Ok((&accounts[..providers], accounts.get(providers)))
}
pub fn harvest(ctx: Context<Stage1Harvest>, units: u64) -> Result<()> {
    let (provider_accounts, funding) = sweep_accounts(&ctx.accounts.asset, ctx.remaining_accounts)?;
    require!(units > 0, ErrorCode::Stage1InvalidAmount);
    require!(
        is_active(&ctx.accounts.lot, &ctx.accounts.hill),
        ErrorCode::Stage1NotBonded
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let clock = Clock::get()?;
    if ctx.accounts.asset.adapter != 1 {
        // Keep the immutable cached quote for exits; new income additionally
        // requires clean provider accounting in this instruction.
        providers::observe(&ctx.accounts.asset, provider_accounts, clock.epoch)?;
    }
    let key = ctx.accounts.lot.to_account_info();
    materialize(
        &mut ctx.accounts.lot,
        &ctx.accounts.hill,
        key,
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    )?;
    let now = clock.unix_timestamp;
    let rate = ActiveAdapter::rate(&ctx.accounts.asset, now, provider_accounts)?;
    let key = ctx.accounts.lot.to_account_info();
    sweep(
        &mut ctx.accounts.lot,
        key,
        &mut ctx.accounts.asset,
        rate,
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.earnings.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        Some(units),
        now,
        ctx.accounts.city.season_anchor,
        funding,
    )
}

pub fn request(ctx: Context<Stage1Request>, request_id: u64, basis: u64) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let lot = &mut ctx.accounts.lot;
    check_lot(lot, lot.key())?;
    require!(
        is_active(lot, &ctx.accounts.hill)
            && !lot.exiting
            && lot.pending_request == Pubkey::default(),
        ErrorCode::Stage1InvalidRequest
    );
    let lock_end = if is_founding(lot, &ctx.accounts.hill) {
        date(ctx.accounts.hill.bonded_at, 26)?
    } else {
        lot.lock_end
    };
    require!(now >= lock_end, ErrorCode::Stage1Locked);
    require!(
        basis > 0 && basis <= lot.basis_lamports,
        ErrorCode::Stage1InvalidAmount
    );
    let req = &mut ctx.accounts.request;
    req.version = 1;
    req.lot = lot.key();
    req.owner = lot.owner;
    req.request_id = request_id;
    req.basis_lamports = basis;
    req.notice_at = now;
    req.eligible_at = date(now, 4)?;
    req.bump = ctx.bumps.request;
    lot.pending_request = req.key();
    Ok(())
}
pub fn cancel_request(ctx: Context<Stage1CancelRequest>) -> Result<()> {
    check_lot(&ctx.accounts.lot, ctx.accounts.lot.key())?;
    require!(
        ctx.accounts.request.status == 0
            && ctx.accounts.lot.pending_request == ctx.accounts.request.key(),
        ErrorCode::Stage1InvalidRequest
    );
    ctx.accounts.lot.pending_request = Pubkey::default();
    ctx.accounts.request.status = 3;
    Ok(())
}

pub fn begin(ctx: Context<Stage1BeginWithdrawal>) -> Result<()> {
    let mut city: Stage1CityConfig = read_owned(&ctx.accounts.city.to_account_info())?;
    require!(city.bump == ctx.bumps.city, ErrorCode::Stage1InvalidCityLayout);
    let now = Clock::get()?.unix_timestamp;
    let (provider_accounts, funding) = sweep_accounts(&ctx.accounts.asset, ctx.remaining_accounts)?;
    require!(
        is_active(&ctx.accounts.lot, &ctx.accounts.hill_account.hill)
            && ctx.accounts.request.status == 0
            && ctx.accounts.lot.pending_request == ctx.accounts.request.key(),
        ErrorCode::Stage1InvalidRequest
    );
    require!(
        now >= ctx.accounts.request.eligible_at,
        ErrorCode::Stage1NoticeIncomplete
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let key = ctx.accounts.lot.to_account_info();
    materialize(
        &mut ctx.accounts.lot,
        &ctx.accounts.hill_account.hill,
        key,
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
    )?;
    let rate = exit_rate(&ctx.accounts.asset, now, provider_accounts)?;
    require!(
        rate.is_some() || ctx.accounts.request.basis_lamports == ctx.accounts.lot.basis_lamports,
        ErrorCode::Stage1StalePartialExit
    );
    let key = ctx.accounts.lot.to_account_info();
    if let Some(rate) = rate {
        sweep(
            &mut ctx.accounts.lot,
            key.clone(),
            &mut ctx.accounts.asset,
            rate,
            ctx.accounts.custody.to_account_info(),
            ctx.accounts.earnings.to_account_info(),
            ctx.accounts.token_program.to_account_info(),
            None,
            now,
            city.season_anchor,
            funding,
        )?;
    }
    let lot = &mut ctx.accounts.lot;
    let basis = ctx.accounts.request.basis_lamports;
    let units = narrow(floor_ratio(lot.units, basis, lot.basis_lamports)?)?;
    let remaining_basis = lot.basis_lamports - basis;
    let remaining_units = lot.units - units;
    let exit_dust = rate
        .map(|r| r.surplus(units, basis))
        .transpose()?
        .unwrap_or(0);
    let remaining_dust = rate
        .map(|r| r.surplus(remaining_units, remaining_basis))
        .transpose()?
        .unwrap_or(0);
    let dust = add(exit_dust, remaining_dust)?;
    let exit_units = units - exit_dust;
    require!(
        remaining_basis == 0 || add(exit_units, dust)? > 0,
        ErrorCode::Stage1ExitTooSmall
    );
    for (account, prefix) in [
        (ctx.accounts.exit_custody.to_account_info(), S1_CUSTODY),
        (ctx.accounts.exit_reserve.to_account_info(), S1_OWNER),
    ] {
        make_custody(
            account,
            ctx.accounts.exit_lot.to_account_info(),
            ctx.accounts.mint.to_account_info(),
            ctx.accounts.owner.to_account_info(),
            ctx.accounts.system_program.to_account_info(),
            ctx.accounts.token_program.to_account_info(),
            prefix,
            ctx.accounts.exit_lot.key(),
        )?;
    }
    // All writes/transfers, including the sweep above, roll back on rejection.
    send_lot(
        lot,
        key.clone(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.exit_custody.to_account_info(),
        exit_units,
    )?;
    send_lot(
        lot,
        key,
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.exit_reserve.to_account_info(),
        dust,
    )?;
    let child = &mut ctx.accounts.exit_lot;
    child.version = 1;
    child.city = lot.city;
    child.hill = lot.hill;
    child.owner = lot.owner;
    child.mint = lot.mint;
    child.asset_slot = lot.asset_slot;
    child.deposited_at = lot.deposited_at;
    child.units = exit_units;
    child.basis_lamports = basis;
    child.lock_weeks = lot.lock_weeks;
    child.lock_end = lot.lock_end;
    child.founding = lot.founding;
    child.exiting = true;
    child.exit_request = ctx.accounts.request.key();
    child.owner_units = dust;
    child.bump = ctx.bumps.exit_lot;
    child.observed_loss_lamports = rate
        .map(|r| r.backing(child).map(|v| basis - v))
        .transpose()?
        .unwrap_or(lot.observed_loss_lamports);
    lot.units = remaining_units - remaining_dust;
    lot.basis_lamports = remaining_basis;
    lot.observed_loss_lamports = rate
        .map(|r| r.backing(lot).map(|v| remaining_basis - v))
        .transpose()?
        .unwrap_or(0);
    lot.pending_request = Pubkey::default();
    ctx.accounts.request.status = 1;
    ctx.accounts.request.exit_lot = child.key();
    if remaining_basis != 0 {
        city.held_lots = add(city.held_lots, 1)?;
    }
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())?;
    city.try_serialize(&mut &mut ctx.accounts.city.try_borrow_mut_data()?[..])
}

pub fn complete(ctx: Context<Stage1CompleteWithdrawal>) -> Result<()> {
    require!(
        ctx.accounts.request.status == 1
            && ctx.accounts.lot.exiting
            && ctx.accounts.lot.exit_request == ctx.accounts.request.key()
            && ctx.accounts.request.exit_lot == ctx.accounts.lot.key(),
        ErrorCode::Stage1InvalidRequest
    );
    check_custody(
        &ctx.accounts.lot,
        ctx.accounts.lot.key(),
        &ctx.accounts.custody.to_account_info(),
        &ctx.accounts.owner_reserve.to_account_info(),
    )?;
    let now = Clock::get()?.unix_timestamp;
    let (provider_accounts, funding) = sweep_accounts(&ctx.accounts.asset, ctx.remaining_accounts)?;
    let rate = exit_rate(&ctx.accounts.asset, now, provider_accounts)?;
    let key = ctx.accounts.lot.to_account_info();
    if let Some(rate) = rate {
        sweep(
            &mut ctx.accounts.lot,
            key.clone(),
            &mut ctx.accounts.asset,
            rate,
            ctx.accounts.custody.to_account_info(),
            ctx.accounts.earnings.to_account_info(),
            ctx.accounts.token_program.to_account_info(),
            None,
            now,
            ctx.accounts.city.season_anchor,
            funding,
        )?;
    }
    let lot = &mut ctx.accounts.lot;
    send_lot(
        lot,
        key.clone(),
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.custody.to_account_info(),
        ctx.accounts.destination.to_account_info(),
        lot.units,
    )?;
    send_lot(
        lot,
        key,
        ctx.accounts.token_program.to_account_info(),
        ctx.accounts.owner_reserve.to_account_info(),
        ctx.accounts.destination.to_account_info(),
        lot.owner_units,
    )?;
    ctx.accounts.asset.ledger.owner_return(lot.units, lot.owner_units)?;
    lot.returned_units = add(lot.returned_units, add(lot.units, lot.owner_units)?)?;
    lot.realized_loss_lamports = rate
        .map(|r| {
            floor_ratio(add(lot.units, lot.owner_units)?, r.n, r.d)
                .map(|value| (lot.basis_lamports as u128).saturating_sub(value) as u64)
        })
        .transpose()?;
    returned_basis(
        &mut ctx.accounts.city,
        &mut ctx.accounts.asset,
        &mut ctx.accounts.hill,
        lot.basis_lamports,
    )?;
    lot.units = 0;
    lot.owner_units = 0;
    lot.basis_lamports = 0;
    ctx.accounts.request.status = 2;
    ctx.accounts.asset.check_earnings(&ctx.accounts.earnings.to_account_info())
}

#[derive(Accounts)]
pub struct Stage1InitCity<'info> {
    #[account(init, payer = admin, space = 8 + Stage1CityConfig::INIT_SPACE, seeds = [S1_CITY], bump)]
    pub city: Account<'info, Stage1CityConfig>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stage1ConfigureAsset<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(init_if_needed, payer = admin, space = 8 + Stage1AssetConfig::INIT_SPACE, seeds = [S1_ASSET, mint.key().as_ref()], bump)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    pub mint: Box<Account<'info, Mint>>,
    /// CHECK: PDA checked here; make_custody initializes SPL ownership, mint and authority.
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

#[derive(Accounts)]
pub struct Stage1TestRate<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Account<'info, Stage1AssetConfig>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    pub admin: Signer<'info>,
}

#[derive(Accounts)]
pub struct Stage1RefreshRate<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_ASSET, mint.key().as_ref()], bump = asset.bump, has_one = city, has_one = mint)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    /// CHECK: pinned address, owner, layout and mint validated before reading.
    pub provider: UncheckedAccount<'info>,
    pub mint: Box<Account<'info, Mint>>,
}

#[derive(Accounts)]
pub struct Stage1InitHill<'info> {
    /// CHECK: Canonical owner/PDA here; discriminator and saved bump checked in handler.
    #[account(seeds = [S1_CITY], bump, owner = crate::ID)]
    pub city: UncheckedAccount<'info>,
    #[account(seeds = [CLIMB_SEED, climb.commitment_hash.as_ref()], bump = climb.bump)]
    pub climb: Box<Account<'info, Climb>>,
    #[account(init, payer = admin, space = 8 + Stage1HillBond::INIT_SPACE, seeds = [S1_HILL, climb.canon_id.as_ref()], bump)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut)]
    pub admin: Signer<'info>,
    /// CHECK: Canonical owner/PDA here; full discriminator, initialization and role checked in handler.
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump, owner = crate::ID)]
    pub program_config: UncheckedAccount<'info>,
    pub system_program: Program<'info, System>,
}

// Anchor emits a non-inlined try_accounts frame for each composite. Keep the
// bounded per-slot hill data out of the already large pledge/exit init frame.
#[derive(Accounts)]
pub struct Stage1HillAccount<'info> {
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
}

#[derive(Accounts)]
#[instruction(deposit_id: u64)]
pub struct Stage1Pledge<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(seeds = [CLIMB_SEED, climb.commitment_hash.as_ref()], bump = climb.bump)]
    pub climb: Box<Account<'info, Climb>>,
    #[account(mut, seeds = [S1_ASSET, mint.key().as_ref()], bump = asset.bump, has_one = city, has_one = mint)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    pub mint: Box<Account<'info, Mint>>,
    #[account(init, payer = owner, space = 8 + Stage1PledgeLot::INIT_SPACE,
        seeds = [S1_LOT, owner.key().as_ref(), &deposit_id.to_le_bytes()], bump)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    /// CHECK: PDA and SPL initialization/ownership are checked by make_custody.
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump)]
    pub custody: UncheckedAccount<'info>,
    /// CHECK: PDA and SPL initialization/ownership are checked by make_custody.
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump)]
    pub owner_reserve: UncheckedAccount<'info>,
    #[account(mut, token::mint = mint, token::authority = owner)]
    pub source: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Stage1OwnerLot<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill, has_one = owner)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(mut, seeds = [S1_ASSET, lot.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = lot.mint, token::authority = owner)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub owner: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Stage1Convert<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill, has_one = owner)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(seeds = [S1_ASSET, lot.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    pub owner: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Stage1Harvest<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(mut, seeds = [S1_ASSET, lot.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_EARNINGS, lot.mint.as_ref()], bump, token::mint = lot.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Stage1Refresh<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(seeds = [S1_ASSET, lot.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(request_id: u64)]
pub struct Stage1Request<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill, has_one = owner)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(init, payer = owner, space = 8 + Stage1WithdrawalRequest::INIT_SPACE,
        seeds = [S1_REQUEST, lot.key().as_ref(), &request_id.to_le_bytes()], bump)]
    pub request: Box<Account<'info, Stage1WithdrawalRequest>>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stage1CancelRequest<'info> {
    #[account(mut, has_one = owner)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(mut, seeds = [S1_REQUEST, lot.key().as_ref(), &request.request_id.to_le_bytes()], bump = request.bump, has_one = lot, has_one = owner)]
    pub request: Box<Account<'info, Stage1WithdrawalRequest>>,
    pub owner: Signer<'info>,
}

#[derive(Accounts)]
pub struct Stage1BeginWithdrawal<'info> {
    /// CHECK: Canonical owner/PDA here; discriminator and saved bump checked in handler.
    #[account(mut, seeds = [S1_CITY], bump, owner = crate::ID)]
    pub city: UncheckedAccount<'info>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(mut, has_one = city, has_one = owner, has_one = mint,
        constraint = lot.hill == hill_account.hill.key() @ ErrorCode::Stage1InvalidLot)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(mut, seeds = [S1_REQUEST, lot.key().as_ref(), &request.request_id.to_le_bytes()], bump = request.bump, has_one = lot, has_one = owner)]
    pub request: Box<Account<'info, Stage1WithdrawalRequest>>,
    pub mint: Box<Account<'info, Mint>>,
    #[account(mut, seeds = [S1_ASSET, mint.key().as_ref()], bump = asset.bump, has_one = city, has_one = mint)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_EARNINGS, mint.key().as_ref()], bump, token::mint = mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(init, payer = owner, space = 8 + Stage1PledgeLot::INIT_SPACE, seeds = [S1_EXIT, request.key().as_ref()], bump)]
    pub exit_lot: Box<Account<'info, Stage1PledgeLot>>,
    /// CHECK: PDA and SPL initialization/ownership are checked by make_custody.
    #[account(mut, seeds = [S1_CUSTODY, exit_lot.key().as_ref()], bump)]
    pub exit_custody: UncheckedAccount<'info>,
    /// CHECK: PDA and SPL initialization/ownership are checked by make_custody.
    #[account(mut, seeds = [S1_OWNER, exit_lot.key().as_ref()], bump)]
    pub exit_reserve: UncheckedAccount<'info>,
    #[account(mut)]
    pub owner: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Stage1CompleteWithdrawal<'info> {
    #[account(mut, seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, has_one = city, has_one = hill, has_one = owner)]
    pub lot: Box<Account<'info, Stage1PledgeLot>>,
    #[account(mut, seeds = [S1_REQUEST, request.lot.as_ref(), &request.request_id.to_le_bytes()], bump = request.bump, has_one = owner)]
    pub request: Box<Account<'info, Stage1WithdrawalRequest>>,
    #[account(mut, seeds = [S1_ASSET, lot.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_CUSTODY, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub custody: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_OWNER, lot.key().as_ref()], bump, token::mint = lot.mint, token::authority = lot)]
    pub owner_reserve: Box<Account<'info, TokenAccount>>,
    #[account(mut, seeds = [S1_EARNINGS, lot.mint.as_ref()], bump, token::mint = lot.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = lot.mint, token::authority = owner)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub owner: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stage1_invalid_provider_is_never_a_stale_exit() {
        let mut asset = Stage1AssetConfig::try_deserialize_unchecked(
            &mut &vec![0; 8 + Stage1AssetConfig::INIT_SPACE][..],
        )
        .unwrap();
        asset.adapter = 255;
        asset.last_fresh_until = 1;
        assert!(
            exit_rate(&asset, S1_WEEK + 2, &[]).is_err(),
            "an unauthorized adapter must not authorize in-kind stale escape"
        );
    }

    #[test]
    fn stage1_integer_extremes_do_not_overflow_or_floor_deposit_basis() {
        let rate = Stage1Rate {
            n: u64::MAX,
            d: u64::MAX,
        };
        assert_eq!(rate.basis(u64::MAX).unwrap(), u64::MAX);
        assert_eq!(rate.surplus(u64::MAX, u64::MAX).unwrap(), 0);
        assert_eq!(Stage1Rate { n: 1, d: 1000 }.basis(1999).unwrap(), 2);
        assert_eq!(Stage1Rate { n: 1, d: 1000 }.surplus(1999, 2).unwrap(), 0);
        assert!(Stage1Rate { n: u64::MAX, d: 1 }.basis(u64::MAX).is_err());
        assert!(date(i64::MAX, 52).is_err());
    }

    #[test]
    fn stage1_extreme_positive_loss_retains_units_without_overflowing_coverage() {
        assert_eq!(
            Stage1Rate { n: 1, d: u64::MAX }
                .surplus(u64::MAX, u64::MAX)
                .unwrap(),
            0
        );
        assert!(ceil_ratio(1, 1, 0).is_err());
        assert!(floor_ratio(1, 1, 0).is_err());
    }
}
