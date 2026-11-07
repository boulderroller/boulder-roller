//! Irrevocable, fee-free USDC sponsorship. Sporting allocation remains the
//! publisher's attestation; custody, schedules, windows and ages are enforced here.
use super::*;
use anchor_lang::solana_program::hash::hashv;

pub const S1_CASH: &[u8] = b"s1v1_cash";
pub const S1_BOOST: &[u8] = b"s1v1_boost";
pub const S1_BOOST_HILL: &[u8] = b"s1v1_boost_hill";
pub const S1_CASH_ADAPTER: u8 = 254;
pub const S1_MAX_BOOST_HILLS: usize = 16;
// Claude's default, revisable by Tim (STAGE1_SPEC §§6, 8.2).
pub const S1_BOOST_START_HORIZON: u64 = 13;
pub const S1_BOOST_MIN_TRANCHE: u64 = 1_000_000;
// EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v (Circle native mainnet USDC).
pub const S1_MAINNET_USDC: Pubkey = Pubkey::new_from_array([
    198, 250, 122, 243, 190, 219, 173, 58, 61, 101, 243, 106, 171, 201, 116, 49, 177, 187, 228,
    194, 210, 246, 224, 228, 124, 166, 2, 3, 69, 47, 93, 97,
]);

#[account]
#[derive(InitSpace)]
pub struct Stage1CashConfig {
    pub city: Pubkey,
    pub mint: Pubkey,
    pub is_test: bool,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Stage1Boost {
    pub city: Pubkey,
    pub mint: Pubkey,
    pub id: [u8; 32],
    pub funder: Pubkey,
    pub total: u64,
    pub start_week: u64,
    pub weeks: u8,
    /// Base58 hill identity UTF-8 order, NOT binary public-key order.
    #[max_len(16)]
    pub hills: Vec<Pubkey>,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Stage1BoostHill {
    pub boost: Pubkey,
    pub hill: Pubkey,
    pub sequence: u64,
    pub start_week: u64,
    pub weeks: u8,
    /// Immutable integer schedule; each index ages from start_week + index.
    pub scheduled: [u64; 13],
    pub holds: [[u64; 5]; 13],
    pub pool: u64,
    pub processed: bool,
    pub processed_week: u64,
    pub retired: bool,
    pub bump: u8,
}

fn add(a: u64, b: u64) -> Result<u64> {
    a.checked_add(b)
        .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
}

pub fn sorted_hills(mut hills: Vec<Pubkey>) -> Result<Vec<Pubkey>> {
    require!(
        !hills.is_empty() && hills.len() <= S1_MAX_BOOST_HILLS,
        ErrorCode::Stage1InvalidHill
    );
    hills.sort_by_cached_key(|hill| hill.to_string());
    require!(
        hills.windows(2).all(|pair| pair[0] != pair[1]),
        ErrorCode::Stage1InvalidHill
    );
    Ok(hills)
}

/// Equal-weight Hamilton: every fractional remainder is equal, so the first
/// remainder slots in hill-text/week order receive the indivisible units.
pub fn schedule(total: u64, hills: usize, weeks: u8, hill_index: usize) -> Result<[u64; 13]> {
    require!(
        total > 0
            && hills > 0
            && hills <= S1_MAX_BOOST_HILLS
            && hill_index < hills
            && (1..=13).contains(&weeks),
        ErrorCode::Stage1InvalidFunding
    );
    let slots = (hills * weeks as usize) as u64;
    require!(total / slots >= S1_BOOST_MIN_TRANCHE, ErrorCode::Stage1BoostTrancheMinimum);
    let mut result = [0; 13];
    for (j, value) in result.iter_mut().enumerate().take(weeks as usize) {
        *value =
            total / slots + u64::from((hill_index * weeks as usize + j) < (total % slots) as usize);
    }
    Ok(result)
}

pub fn register_cash(ctx: Context<Stage1RegisterCash>) -> Result<()> {
    let mint = ctx.accounts.mint.key();
    let is_test = cfg!(any(feature = "stage1-devnet", feature = "stage1-localnet"));
    if is_test {
        require!(
            mint != S1_MAINNET_USDC && stage1_providers::kind(mint).is_none(),
            ErrorCode::Stage1InvalidAsset
        );
    } else {
        require_keys_eq!(mint, S1_MAINNET_USDC, ErrorCode::Stage1InvalidAsset);
    }
    require!(
        ctx.accounts.mint.decimals == 6,
        ErrorCode::Stage1InvalidAsset
    );
    let asset = &mut ctx.accounts.asset;
    asset.version = 1;
    asset.city = ctx.accounts.city.key();
    asset.mint = mint;
    asset.adapter = S1_CASH_ADAPTER;
    // No staking slot, quote, enabled intake, principal or DUNG is created.
    asset.bump = ctx.bumps.asset;
    ctx.accounts.cash.set_inner(Stage1CashConfig {
        city: asset.city,
        mint,
        is_test,
        bump: ctx.bumps.cash,
    });
    stage1::make_custody(
        ctx.accounts.earnings.to_account_info(),
        asset.to_account_info(),
        ctx.accounts.mint.to_account_info(),
        ctx.accounts.admin.to_account_info(),
        ctx.accounts.system_program.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        S1_EARNINGS,
        mint,
    )?;
    asset.check_earnings(&ctx.accounts.earnings.to_account_info())
}

fn receive<'info>(
    asset: &mut Account<'info, Stage1AssetConfig>,
    earnings: &Account<'info, TokenAccount>,
    source: &Account<'info, TokenAccount>,
    funder: &Signer<'info>,
    token_program: &Program<'info, Token>,
    amount: u64,
) -> Result<()> {
    require!(
        amount > 0 && asset.adapter == S1_CASH_ADAPTER && earnings.key() != source.key(),
        ErrorCode::Stage1InvalidFunding
    );
    asset.check_earnings(&earnings.to_account_info())?;
    let before = earnings.amount;
    token::transfer(
        CpiContext::new(
            token_program.to_account_info(),
            Transfer {
                from: source.to_account_info(),
                to: earnings.to_account_info(),
                authority: funder.to_account_info(),
            },
        ),
        amount,
    )?;
    let received: TokenAccount = stage1::read_owned(&earnings.to_account_info())?;
    require!(
        received.amount.checked_sub(before) == Some(amount),
        ErrorCode::Stage1InvalidCustody
    );
    asset.ledger.admit_cash(amount)?;
    asset.check_earnings(&earnings.to_account_info())
}

pub fn sponsor(ctx: Context<Stage1Sponsor>, amount: u64) -> Result<()> {
    require!(!ctx.accounts.city.intake_paused, ErrorCode::Stage1IntakePaused);
    let week = week_at(
        ctx.accounts.city.season_anchor,
        Clock::get()?.unix_timestamp,
    )?;
    let book = &mut ctx.accounts.funding;
    require!(
        book.week == week
            && book.week >= ctx.accounts.cursor.next_week
            && book.snapshot == [0; 32]
            && !book.published,
        ErrorCode::Stage1InvalidFunding
    );
    receive(
        &mut ctx.accounts.asset,
        &ctx.accounts.earnings,
        &ctx.accounts.source,
        &ctx.accounts.funder,
        &ctx.accounts.token_program,
        amount,
    )?;
    book.available = add(book.available, amount)?;
    book.admitted_cash = add(book.admitted_cash, amount)?;
    book.lineage = hashv(&[
        b"BR-stage1-v1:cash\0",
        &book.lineage,
        ctx.accounts.funder.key().as_ref(),
        &amount.to_be_bytes(),
    ])
    .to_bytes();
    emit!(Stage1CashReceived {
        hill: book.hill,
        week,
        funder: ctx.accounts.funder.key(),
        amount,
        lineage: book.lineage
    });
    Ok(())
}

#[event]
pub struct Stage1CashReceived {
    pub hill: Pubkey,
    pub week: u64,
    pub funder: Pubkey,
    pub amount: u64,
    pub lineage: [u8; 32],
}

#[inline(never)]
fn create_stream<'info>(
    info: &AccountInfo<'info>,
    payer: &AccountInfo<'info>,
    system: &AccountInfo<'info>,
    stream: &Stage1BoostHill,
) -> Result<()> {
    use anchor_lang::system_program::{self, Allocate, Assign};
    require!(
        info.is_writable && info.data_is_empty() && info.owner == &System::id(),
        ErrorCode::Stage1InvalidFunding
    );
    let seeds: &[&[u8]] = &[
        S1_BOOST_HILL,
        stream.boost.as_ref(),
        stream.hill.as_ref(),
        &[stream.bump],
    ];
    let size = 8 + Stage1BoostHill::INIT_SPACE;
    let needed = Rent::get()?
        .minimum_balance(size)
        .saturating_sub(info.lamports());
    if needed > 0 {
        system_program::transfer(
            CpiContext::new(
                system.clone(),
                system_program::Transfer {
                    from: payer.clone(),
                    to: info.clone(),
                },
            ),
            needed,
        )?;
    }
    system_program::allocate(
        CpiContext::new_with_signer(
            system.clone(),
            Allocate {
                account_to_allocate: info.clone(),
            },
            &[seeds],
        ),
        size as u64,
    )?;
    system_program::assign(
        CpiContext::new_with_signer(
            system.clone(),
            Assign {
                account_to_assign: info.clone(),
            },
            &[seeds],
        ),
        &crate::ID,
    )?;
    stream.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])
}

#[derive(AnchorDeserialize)]
struct HillAdmissionIdentity {
    version: u8,
    city: Pubkey,
    _climb: Pubkey,
    canon_id: [u8; 16],
}

#[inline(never)]
fn validate_hill(info: &AccountInfo, city: Pubkey) -> Result<()> {
    // Boost eligibility needs only admission identity, not the large staking
    // inventory. Only this program can create/write this exact account type.
    // Decoding 16 boxed inventories would exhaust Solana's default bump heap.
    require!(
        *info.owner == crate::ID && !info.executable,
        ErrorCode::Stage1InvalidHill
    );
    let data = info.try_borrow_data()?;
    require!(
        data.len() == 8 + Stage1HillBond::INIT_SPACE && data[..8] == Stage1HillBond::DISCRIMINATOR,
        ErrorCode::Stage1InvalidHill
    );
    let hill = HillAdmissionIdentity::deserialize(&mut &data[8..])?;
    let expected = Pubkey::find_program_address(&[S1_HILL, hill.canon_id.as_ref()], &crate::ID).0;
    require!(
        *info.key == expected && hill.version == 1 && hill.city == city,
        ErrorCode::Stage1InvalidHill
    );
    Ok(())
}

#[cfg(test)]
mod admission_tests {
    use super::*;

    #[test]
    fn boost_hill_admission_requires_exact_owned_identity() {
        let city = Pubkey::new_unique();
        let canon_id = [7; 16];
        let key = Pubkey::find_program_address(&[S1_HILL, &canon_id], &crate::ID).0;
        let zeroes = vec![0; 8 + Stage1HillBond::INIT_SPACE];
        let mut hill = Stage1HillBond::try_deserialize_unchecked(&mut zeroes.as_slice()).unwrap();
        hill.version = 1;
        hill.city = city;
        hill.canon_id = canon_id;
        let mut valid = Vec::new();
        hill.try_serialize(&mut valid).unwrap();
        assert_eq!(valid.len(), 8 + Stage1HillBond::INIT_SPACE);
        let accepts = |key: Pubkey, owner: Pubkey, executable: bool, mut data: Vec<u8>| {
            let mut lamports = 1;
            let info = AccountInfo::new(
                &key,
                false,
                false,
                &mut lamports,
                &mut data,
                &owner,
                executable,
                0,
            );
            validate_hill(&info, city).is_ok()
        };
        assert!(accepts(key, crate::ID, false, valid.clone()));
        assert!(!accepts(key, Pubkey::new_unique(), false, valid.clone()));
        assert!(!accepts(key, crate::ID, true, valid.clone()));
        assert!(!accepts(
            Pubkey::new_unique(),
            crate::ID,
            false,
            valid.clone()
        ));
        for length in [0, 7, valid.len() - 1, valid.len() + 1] {
            let mut data = valid.clone();
            data.resize(length, 0);
            assert!(!accepts(key, crate::ID, false, data));
        }
        // Discriminator, version, city, and canon ID each authenticate admission.
        for (offset, value) in [
            (0, valid[0] ^ 1),
            (8, 0),
            (8, 2),
            (9, valid[9] ^ 1),
            (73, 8),
        ] {
            let mut data = valid.clone();
            data[offset] = value;
            assert!(!accepts(key, crate::ID, false, data));
        }
    }
}

pub fn post_boost<'info>(
    ctx: Context<'_, '_, 'info, 'info, Stage1PostBoost<'info>>,
    id: [u8; 32],
    total: u64,
    start_week: u64,
    weeks: u8,
) -> Result<()> {
    require!(!ctx.accounts.city.intake_paused, ErrorCode::Stage1IntakePaused);
    let now = week_at(
        ctx.accounts.city.season_anchor,
        Clock::get()?.unix_timestamp,
    )?;
    require!(
        (1..=13).contains(&weeks),
        ErrorCode::Stage1InvalidFunding
    );
    require!(start_week > now && start_week - now <= S1_BOOST_START_HORIZON,
        ErrorCode::Stage1BoostStartHorizon);
    // Validate the final riding close and its grace fit the chain timestamp.
    let end = add(start_week, weeks as u64)?;
    let seconds = (end as u128) * S1_WEEK as u128 + 86_400;
    let seconds = i64::try_from(seconds).map_err(|_| error!(ErrorCode::Stage1Arithmetic))?;
    ctx.accounts
        .city
        .season_anchor
        .checked_add(seconds)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(
        ctx.remaining_accounts.len() % 3 == 0,
        ErrorCode::Stage1InvalidHill
    );
    let supplied: Vec<Pubkey> = ctx
        .remaining_accounts
        .chunks_exact(3)
        .map(|a| *a[0].key)
        .collect();
    let hills = sorted_hills(supplied.clone())?;
    require!(hills == supplied, ErrorCode::Stage1InvalidHill);
    let boost_key = ctx.accounts.boost.key();
    for (i, infos) in ctx.remaining_accounts.chunks_exact(3).enumerate() {
        validate_hill(&infos[0], ctx.accounts.city.key())?;
        let mut cursor: Stage1SettlementCursor = stage1::read_owned(&infos[1])?;
        let expected = Pubkey::find_program_address(
            &[
                S1_CURSOR,
                hills[i].as_ref(),
                ctx.accounts.asset.mint.as_ref(),
            ],
            &crate::ID,
        )
        .0;
        require!(
            infos[1].is_writable
                && *infos[1].key == expected
                && cursor.city == ctx.accounts.city.key()
                && cursor.hill == hills[i]
                && cursor.asset == ctx.accounts.asset.key()
                && cursor.mint == ctx.accounts.asset.mint
                && start_week >= cursor.next_week,
            ErrorCode::Stage1InvalidFunding
        );
        let (expected, bump) = Pubkey::find_program_address(
            &[S1_BOOST_HILL, boost_key.as_ref(), hills[i].as_ref()],
            &crate::ID,
        );
        require_keys_eq!(expected, *infos[2].key, ErrorCode::Stage1InvalidFunding);
        let scheduled = schedule(total, hills.len(), weeks, i)?;
        let amount = scheduled.iter().try_fold(0u64, |sum, v| add(sum, *v))?;
        let mut holds = [[0; 5]; 13];
        for j in 0..13 {
            holds[j][0] = scheduled[j];
        }
        let stream = Stage1BoostHill {
            boost: boost_key,
            hill: hills[i],
            sequence: cursor.cash_sequence,
            start_week,
            weeks,
            scheduled,
            holds,
            pool: 0,
            processed: false,
            processed_week: 0,
            retired: amount == 0,
            bump,
        };
        cursor.cash_sequence = add(cursor.cash_sequence, 1)?;
        if amount > 0 {
            cursor.active_cash_streams = add(cursor.active_cash_streams, 1)?;
        }
        cursor.future_cash = add(cursor.future_cash, amount)?;
        cursor.admit_boost_due(start_week)?;
        create_stream(
            &infos[2],
            &ctx.accounts.funder.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            &stream,
        )?;
        cursor.try_serialize(&mut &mut infos[1].try_borrow_mut_data()?[..])?;
    }
    receive(
        &mut ctx.accounts.asset,
        &ctx.accounts.earnings,
        &ctx.accounts.source,
        &ctx.accounts.funder,
        &ctx.accounts.token_program,
        total,
    )?;
    ctx.accounts.boost.set_inner(Stage1Boost {
        city: ctx.accounts.city.key(),
        mint: ctx.accounts.asset.mint,
        id,
        funder: ctx.accounts.funder.key(),
        total,
        start_week,
        weeks,
        hills,
        bump: ctx.bumps.boost,
    });
    Ok(())
}

impl Stage1BoostHill {
    /// A frozen week's staging moves only held obligations. A root publication
    /// later converts their exact released sum to claimable, once all streams
    /// present at freeze have been processed. New posts cannot substitute.
    pub fn process(
        &mut self,
        book: &mut Stage1WeekFunding,
        cursor: &mut Stage1SettlementCursor,
        ledger: &mut Stage1Ledger,
        remaining: [[u64; 5]; 13],
    ) -> Result<()> {
        require!(
            !self.retired
                && self.sequence < book.cash_sequence
                && book.snapshot != [0; 32]
                && !book.published
                && book.week == cursor.next_week
                && (!self.processed || self.processed_week < book.week),
            ErrorCode::Stage1InvalidHold
        );
        let last = add(self.start_week, self.weeks as u64 - 1)?;
        let mut released = 0;
        for j in 0..13 {
            let born = add(self.start_week, j as u64)?;
            let before = bucket_sum(&self.holds[j])?;
            let after = bucket_sum(&remaining[j])?;
            if j >= self.weeks as usize || born > book.week {
                require!(remaining[j] == self.holds[j], ErrorCode::Stage1InvalidHold);
                if j < self.weeks as usize && before > 0 {
                    cursor.note_following_boost_due(born)?;
                }
                continue;
            }
            if book.week - born >= S1_HELD_AGE {
                require!(after == 0, ErrorCode::Stage1InvalidHold);
                self.pool = add(self.pool, before)?;
                ledger.pool = plus(ledger.pool, before as u128)?;
            } else if book.week > last {
                require!(remaining[j] == self.holds[j], ErrorCode::Stage1InvalidHold);
            } else {
                validate_remaining(&self.holds[j], &remaining[j])?;
                released = add(released, before - after)?;
            }
            if born == book.week {
                require!(before == self.scheduled[j], ErrorCode::Stage1InvalidHold);
                cursor.future_cash = cursor
                    .future_cash
                    .checked_sub(before)
                    .ok_or(ErrorCode::Stage1Solvency)?;
                cursor.pending_current_holds = add(cursor.pending_current_holds, after)?;
            } else {
                cursor.transition_cash_hold(born, before, after)?;
            }
            self.holds[j] = remaining[j];
        }
        book.boost_released = add(book.boost_released, released)?;
        book.cash_processed = add(book.cash_processed, 1)?;
        require!(
            book.cash_processed <= book.cash_expected,
            ErrorCode::Stage1InvalidHold
        );
        let bytes: Vec<u8> = remaining
            .iter()
            .flatten()
            .flat_map(|v| v.to_be_bytes())
            .collect();
        book.boost_commitment = hashv(&[
            b"BR-stage1-v1:boost-release\0",
            &book.boost_commitment,
            self.boost.as_ref(),
            &self.sequence.to_be_bytes(),
            &book.week.to_be_bytes(),
            &released.to_be_bytes(),
            &bytes,
            &self.pool.to_be_bytes(),
        ])
        .to_bytes();
        self.processed = true;
        self.processed_week = book.week;
        if self.holds.iter().flatten().all(|v| *v == 0) {
            self.retired = true;
            cursor.active_cash_streams = cursor
                .active_cash_streams
                .checked_sub(1)
                .ok_or(ErrorCode::Stage1Solvency)?;
        }
        Ok(())
    }
}

pub fn process_boost(ctx: Context<Stage1ProcessBoost>, remaining: [[u64; 5]; 13]) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())?;
    ctx.accounts.stream.process(
        &mut ctx.accounts.funding,
        &mut ctx.accounts.cursor,
        &mut ctx.accounts.asset.ledger,
        remaining,
    )?;
    ctx.accounts
        .asset
        .check_earnings(&ctx.accounts.earnings.to_account_info())
}

#[derive(Accounts)]
pub struct Stage1RegisterCash<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(init, payer = admin, space = 8 + Stage1CashConfig::INIT_SPACE, seeds = [S1_CASH], bump)]
    pub cash: Box<Account<'info, Stage1CashConfig>>,
    #[account(init, payer = admin, space = 8 + Stage1AssetConfig::INIT_SPACE, seeds = [S1_ASSET, mint.key().as_ref()], bump)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    pub mint: Box<Account<'info, Mint>>,
    /// CHECK: exact PDA; make_custody validates and initializes SPL custody.
    #[account(mut, seeds = [S1_EARNINGS, mint.key().as_ref()], bump)]
    pub earnings: UncheckedAccount<'info>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump,
        constraint = program_config.initialized && program_config.admin_authority == admin.key() @ ErrorCode::Stage1Unauthorized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut)]
    pub admin: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stage1Sponsor<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_CASH], bump = cash.bump, has_one = city, constraint = cash.mint == asset.mint @ ErrorCode::Stage1InvalidAsset)]
    pub cash: Box<Account<'info, Stage1CashConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_FUNDING, funding.hill.as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = funding.bump,
        has_one = city, has_one = asset, constraint = funding.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    #[account(seeds = [S1_CURSOR, funding.hill.as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == funding.hill && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
    #[account(mut, seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = asset.mint, token::authority = funder)]
    pub source: Box<Account<'info, TokenAccount>>,
    pub funder: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(id: [u8; 32])]
pub struct Stage1PostBoost<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_CASH], bump = cash.bump, has_one = city, constraint = cash.mint == asset.mint @ ErrorCode::Stage1InvalidAsset)]
    pub cash: Box<Account<'info, Stage1CashConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(init, payer = funder, space = 8 + Stage1Boost::INIT_SPACE, seeds = [S1_BOOST, funder.key().as_ref(), &id], bump)]
    pub boost: Box<Account<'info, Stage1Boost>>,
    #[account(mut, seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = asset.mint, token::authority = funder)]
    pub source: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub funder: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Stage1ProcessBoost<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_ASSET, asset.mint.as_ref()], bump = asset.bump, has_one = city, constraint = asset.adapter == S1_CASH_ADAPTER @ ErrorCode::Stage1InvalidAsset)]
    pub asset: Box<Account<'info, Stage1AssetConfig>>,
    #[account(mut, seeds = [S1_FUNDING, funding.hill.as_ref(), asset.mint.as_ref(), &funding.week.to_le_bytes()], bump = funding.bump,
        has_one = city, has_one = asset, constraint = funding.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub funding: Box<Account<'info, Stage1WeekFunding>>,
    #[account(mut, seeds = [S1_CURSOR, funding.hill.as_ref(), asset.mint.as_ref()], bump = cursor.bump,
        has_one = city, has_one = asset, constraint = cursor.hill == funding.hill && cursor.mint == asset.mint @ ErrorCode::Stage1InvalidFunding)]
    pub cursor: Box<Account<'info, Stage1SettlementCursor>>,
    #[account(mut, seeds = [S1_BOOST_HILL, stream.boost.as_ref(), funding.hill.as_ref()], bump = stream.bump,
        constraint = stream.hill == funding.hill @ ErrorCode::Stage1InvalidHill)]
    pub stream: Box<Account<'info, Stage1BoostHill>>,
    #[account(seeds = [S1_EARNINGS, asset.mint.as_ref()], bump, token::mint = asset.mint, token::authority = asset)]
    pub earnings: Box<Account<'info, TokenAccount>>,
    pub publisher: Signer<'info>,
}
