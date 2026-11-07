//! Prospective bonded-hill issuance; no legacy DungMintState or cash ledger.
//! Opening inventory, rates, sporting truth and owner aggregation are publisher
//! attestations under STAGE1_SPEC §8.1. Bounds below do not verify those facts.
use super::*;
use anchor_lang::solana_program::hash::hashv;

pub const S1_DUNG: &[u8] = b"s1v1_dung";
pub const S1_DUNG_STATE: &[u8] = b"s1v1_dung_state";
pub const S1_DUNG_CLAIMS: &[u8] = b"s1v1_dung_claims";
pub const S1_DUNG_TSS_CEILING: u64 = 20_000_000_000;
pub const S1_DUNG_CLAIM_WAIT: i64 = 172_800;

#[derive(AnchorSerialize, AnchorDeserialize, Clone, InitSpace)]
pub struct Stage1DungOpening {
    /// Ordinary then founding, each ordered 0/13/26/52 weeks. Sum per-lot
    /// min(basis, floor(units*rate)); never floor aggregate units across lots.
    pub basis: [u64; 8],
    pub backing: [u64; 8],
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone, InitSpace)]
pub struct Stage1DungInput {
    /// Nonzero commitment to historical inventory, rates, owners and riding.
    pub source_snapshot: [u8; 32],
    pub field_count: u32,
    pub postbond_tss_micros: u64,
    pub top_count: u8,
    pub ascent_count: u32,
    pub earned_legend: bool,
    pub opening: Stage1DungOpening,
    /// Publisher-attested registered shares, bounded separately by each role.
    pub payable_role_totals: [u64; 2],
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone, InitSpace, Debug, PartialEq)]
pub struct Stage1DungAllocation {
    pub potential: u64,
    pub riders: u64,
    pub backers: u64,
    pub unminted: u64,
}
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct Stage1DungRoot {
    pub root: [u8; 32],
    pub total: u64,
    pub leaf_count: u32,
}
#[account]
#[derive(InitSpace)]
pub struct Stage1DungState {
    pub allocated_lifetime: u128,
    pub minted_lifetime: u128,
    pub bump: u8,
}
#[account]
#[derive(InitSpace)]
pub struct Stage1DungMint {
    pub city: Pubkey,
    pub hill: Pubkey,
    pub mint: Pubkey,
    pub week: u64,
    pub snapshot: [u8; 32],
    pub role_totals: [u64; 2],
    pub frozen_at: i64,
    pub minted: [u64; 2],
    pub bump: u8,
    /// Anti-republication bits while the mint record exists. The permanent
    /// hill cursor prevents this record's recreation after both roles close.
    pub published_roles: u8,
    pub rent_payer: Pubkey,
    pub unminted: u64,
}
#[account]
#[derive(InitSpace, Default)]
pub struct Stage1DungClaimSet {
    pub dung: Pubkey,
    /// 0 riders; 1 backers. Domain-separated in the §8 asset namespace.
    pub role: u8,
    pub root: [u8; 32],
    pub total: u64,
    pub leaf_count: u32,
    pub paid: u64,
    pub claimed_count: u32,
    pub bump: u8,
    pub published_at: i64,
    pub storage_version: u8,
    pub sealed: bool,
    pub rent_payer: Pubkey,
}

#[event]
pub struct Stage1DungPublished {
    pub dung: Pubkey,
    pub city: Pubkey,
    pub hill: Pubkey,
    pub mint: Pubkey,
    pub week: u64,
    pub input: Stage1DungInput,
    pub allocation: Stage1DungAllocation,
    pub backer_weight_quarters: u128,
    pub frozen_at: i64,
}
#[event]
pub struct Stage1DungRolePublished {
    pub claim_set: Pubkey,
    pub dung: Pubkey,
    pub role: u8,
    pub root: [u8; 32],
    pub total: u64,
    pub leaf_count: u32,
    pub published_at: i64,
    pub rent_payer: Pubkey,
}

/// The current ProgramConfig admin signs; an external multisig must supply
/// governance delay. This instruction itself is not a timelock.
pub fn configure(
    ctx: Context<Stage1SetPublisher>,
    tss_ceiling_micros: u64,
    start_week: Option<u64>,
) -> Result<()> {
    configure_policy(
        &mut ctx.accounts.city,
        tss_ceiling_micros,
        start_week,
        Clock::get()?.unix_timestamp,
    )
}

pub fn configure_policy(
    city: &mut Stage1CityConfig,
    tss_ceiling_micros: u64,
    start_week: Option<u64>,
    now: i64,
) -> Result<()> {
    require!(tss_ceiling_micros > 0 || start_week.is_none(), ErrorCode::Stage1InvalidFunding);
    if start_week != city.dung_start_week_plus_one.checked_sub(1) {
        if let Some(week) = start_week {
            require!(
                opening_at(city, week)? >= now,
                ErrorCode::Stage1InvalidCalendar
            );
        }
    }
    city.dung_tss_ceiling_micros = tss_ceiling_micros;
    city.dung_start_week_plus_one = match start_week {
        Some(week) => week.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?,
        None => 0,
    };
    Ok(())
}

pub fn next_publication_week(city: &Stage1CityConfig, cursor: u64) -> Result<u64> {
    require!(city.dung_tss_ceiling_micros > 0, ErrorCode::Stage1NotLaunched);
    Ok(cursor.max(
        city.dung_start_week_plus_one
            .checked_sub(1)
            .ok_or(ErrorCode::Stage1NotLaunched)?,
    ))
}

pub fn check_publication(city: &Stage1CityConfig, cursor: u64, week: u64, tss: u64) -> Result<()> {
    require!(
        week == next_publication_week(city, cursor)?,
        ErrorCode::Stage1WeekNotFinalizable
    );
    require!(
        tss <= city.dung_tss_ceiling_micros,
        ErrorCode::Stage1InvalidFunding
    );
    Ok(())
}

pub fn check_claim_time(published_at: i64, now: i64) -> Result<()> {
    let opens = published_at
        .checked_add(S1_DUNG_CLAIM_WAIT)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(now >= opens, ErrorCode::Stage1Locked);
    Ok(())
}

pub fn opening_at(city: &Stage1CityConfig, week: u64) -> Result<i64> {
    let elapsed = i64::try_from((week as u128) * S1_WEEK as u128)
        .map_err(|_| error!(ErrorCode::Stage1Arithmetic))?;
    city.season_anchor
        .checked_add(elapsed)
        .ok_or_else(|| error!(ErrorCode::Stage1Arithmetic))
}

pub fn backer_weight(
    city: &Stage1CityConfig,
    hill: &Stage1HillBond,
    week: u64,
    opening: &Stage1DungOpening,
) -> Result<u128> {
    let boundary = opening_at(city, week)?;
    require!(
        hill.bonded && hill.bonded_at < boundary,
        ErrorCode::Stage1NotBonded
    );
    let bond_week = week_at(city.season_anchor, hill.bonded_at)?;
    require!(week > bond_week, ErrorCode::Stage1NotBonded);
    let bonus = week - bond_week <= 26;
    let founder_end = hill
        .bonded_at
        .checked_add(26 * S1_WEEK)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    let mut basis = 0u128;
    let mut founding = 0u128;
    let mut weight = 0u128;
    for i in 0..8 {
        require!(
            opening.backing[i] <= opening.basis[i],
            ErrorCode::Stage1InvalidFunding
        );
        basis = plus(basis, opening.basis[i] as u128)?;
        if i >= 4 {
            founding = plus(founding, opening.basis[i] as u128)?;
            let allowed = if boundary < founder_end { 6 } else { 4 };
            require!(
                opening.basis[i] == 0 || (hill.founding_count > 0 && i == allowed),
                ErrorCode::Stage1Locked
            );
        } else if i > 0 && hill.founding_count == hill.campaign_count {
            // No excluded campaign lots means all ordinary locks originate in
            // deposits, whose latest ends are retained. Otherwise conversions
            // make that ceiling incomplete: historical expiry remains attested.
            require!(
                opening.basis[i] == 0 || boundary < hill.dung_lock_ends[i - 1],
                ErrorCode::Stage1Locked
            );
        }
        let multiplier = (i % 4 + 1) as u128 * if i >= 4 && bonus { 2 } else { 1 };
        weight = plus(weight, (opening.backing[i] as u128) * multiplier)?;
    }
    require!(
        basis <= hill.dung_deposited_basis && founding <= hill.dung_founding_basis as u128,
        ErrorCode::Stage1InvalidFunding
    );
    if hill.founding_count == hill.campaign_count {
        let ordinary_ceiling = hill
            .dung_deposited_basis
            .checked_sub(hill.dung_founding_basis as u128)
            .ok_or(ErrorCode::Stage1Arithmetic)?;
        require!(
            basis - founding <= ordinary_ceiling,
            ErrorCode::Stage1InvalidFunding
        );
    }
    Ok(weight)
}

pub fn allocation(
    tss_micros: u64,
    top_count: u8,
    ascent_count: u32,
    legend: bool,
    weight: u128,
) -> Result<Stage1DungAllocation> {
    require!(top_count <= 10, ErrorCode::Stage1InvalidFunding);
    let potential = u64::try_from((tss_micros as u128) * 1_000_000_000 / (1_000_000 * 1000))
        .map_err(|_| error!(ErrorCode::Stage1Arithmetic))?;
    // Hamilton: equal half remainder goes to UTF-8 key "backers".
    let riders_half = potential / 2;
    let backers_half = potential - riders_half;
    // UTF-8 bucket order: every_rider_by_ascents, local_legend, top_ten.
    let numerators = [35u128, 10, 55].map(|n| n * riders_half as u128);
    let mut parts = numerators.map(|n| (n / 100) as u64);
    let mut order = [0usize, 1, 2];
    order.sort_by_key(|i| (std::cmp::Reverse(numerators[*i] % 100), *i));
    let remainder = riders_half - parts.iter().sum::<u64>();
    for i in order.iter().take(remainder as usize) {
        parts[*i] += 1;
    }
    let riders = if ascent_count > 0 { parts[0] } else { 0 }
        + if legend { parts[1] } else { 0 }
        + if top_count > 0 { parts[2] } else { 0 };
    let backers = if weight > 0 { backers_half } else { 0 };
    let unminted = potential
        .checked_sub(riders)
        .and_then(|n| n.checked_sub(backers))
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    Ok(Stage1DungAllocation {
        potential,
        riders,
        backers,
        unminted,
    })
}

pub fn registered_allocation(ceiling: Stage1DungAllocation, payable: [u64; 2]) -> Result<Stage1DungAllocation> {
    require!(payable[0] <= ceiling.riders && payable[1] <= ceiling.backers, ErrorCode::Stage1InvalidFunding);
    Ok(Stage1DungAllocation { potential: ceiling.potential, riders: payable[0], backers: payable[1],
        unminted: ceiling.potential.checked_sub(payable[0]).and_then(|n| n.checked_sub(payable[1]))
            .ok_or(ErrorCode::Stage1Arithmetic)? })
}

pub fn dung_context(deployment: Pubkey, dung: &Stage1DungMint, role: u8) -> Result<String> {
    let name = match role {
        0 => "riders",
        1 => "backers",
        _ => return err!(ErrorCode::Stage1InvalidProof),
    };
    Ok(format!(
        "[\"{}\",\"{}\",\"{}\",{},\"{}:{}\"]",
        deployment, dung.city, dung.hill, dung.week, dung.mint, name
    ))
}

fn check_root(root: &Stage1DungRoot, total: u64, context: &str) -> Result<()> {
    require!(
        root.total == total && root.leaf_count <= S1_MAX_LEAVES,
        ErrorCode::Stage1InvalidFunding
    );
    if total == 0 {
        require!(
            root.leaf_count == 0 && root.root == empty_node(context).hash,
            ErrorCode::Stage1InvalidProof
        );
    } else {
        require!(
            root.leaf_count > 0 && root.leaf_count as u64 <= total && root.root != [0; 32],
            ErrorCode::Stage1InvalidProof
        );
    }
    Ok(())
}

pub fn publish(ctx: Context<Stage1PublishDung>, week: u64, input: Stage1DungInput) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let now = Clock::get()?.unix_timestamp;
    let close = opening_at(&ctx.accounts.city, week)?
        .checked_add(S1_WEEK + 86_400)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(now >= close, ErrorCode::Stage1WeekNotFinalizable);
    require!(
        input.source_snapshot != [0; 32],
        ErrorCode::Stage1SnapshotFrozen
    );
    require!(input.field_count >= 5, ErrorCode::Stage1InvalidFunding);
    let weight = backer_weight(
        &ctx.accounts.city,
        &ctx.accounts.hill_account.hill,
        week,
        &input.opening,
    )?;
    check_publication(
        &ctx.accounts.city,
        ctx.accounts.hill_account.hill.dung_next_week,
        week,
        input.postbond_tss_micros,
    )?;
    ctx.accounts.hill_account.hill.dung_next_week =
        week.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
    let allocated = registered_allocation(allocation(
        input.postbond_tss_micros,
        input.top_count,
        input.ascent_count,
        input.earned_legend,
        weight,
    )?, input.payable_role_totals)?;
    let totals = [allocated.riders, allocated.backers];
    let event = Stage1DungPublished { dung: ctx.accounts.dung.key(), city: ctx.accounts.city.key(),
        hill: ctx.accounts.hill_account.hill.key(), mint: ctx.accounts.mint.key(), week,
        input, allocation: allocated, backer_weight_quarters: weight, frozen_at: now };
    let snapshot = hashv(&[b"BR-stage1-v2:dung-publication\0", &event.try_to_vec()?]).to_bytes();
    let hill = &mut ctx.accounts.hill_account.hill;
    hill.dung_publication_commitment = hashv(&[b"BR-stage1-v2:dung-history\0",
        &hill.dung_publication_commitment, &snapshot]).to_bytes();
    **ctx.accounts.dung = Stage1DungMint { city: event.city, hill: event.hill, mint: event.mint,
        week, snapshot, role_totals: totals, frozen_at: now, minted: [0; 2], bump: ctx.bumps.dung,
        published_roles: 0, rent_payer: ctx.accounts.publisher.key(), unminted: event.allocation.unminted };
    emit!(event);
    let state = &mut ctx.accounts.state;
    state.bump = ctx.bumps.state;
    state.allocated_lifetime = plus(
        state.allocated_lifetime,
        totals[0] as u128 + totals[1] as u128,
    )?;
    Ok(())
}

pub fn verify_dung_proof(
    dung: &Stage1DungMint,
    set: &Stage1DungClaimSet,
    deployment: Pubkey,
    index: u32,
    person: Pubkey,
    recipient: Pubkey,
    amount: u64,
    proof: &[Stage1SumNode],
) -> Result<()> {
    require!(
        set.leaf_count > 0
            && set.leaf_count <= S1_MAX_LEAVES
            && index < set.leaf_count
            && amount > 0,
        ErrorCode::Stage1InvalidProof
    );
    let depth = (32 - (set.leaf_count - 1).leading_zeros()) as usize;
    require!(proof.len() == depth, ErrorCode::Stage1InvalidProof);
    let context = dung_context(deployment, dung, set.role)?;
    let empty = empty_node(&context);
    let mut node = leaf_node(&context, index, person, recipient, amount);
    let (mut position, mut width) = (index, set.leaf_count);
    for sibling in proof {
        if (position ^ 1) >= width {
            require!(*sibling == empty, ErrorCode::Stage1InvalidProof);
        }
        node = if position & 1 == 0 {
            parent_node(&node, sibling)?
        } else {
            parent_node(sibling, &node)?
        };
        position /= 2;
        width = (width + 1) / 2;
    }
    require!(
        node.hash == set.root && node.sum == set.total as u128,
        ErrorCode::Stage1InvalidProof
    );
    Ok(())
}

pub fn claim_progress(
    paid: u64,
    count: u32,
    total: u64,
    leaves: u32,
    amount: u64,
) -> Result<(u64, u32)> {
    let next_paid = paid
        .checked_add(amount)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    let next_count = count.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(
        amount > 0 && next_paid <= total && next_count <= leaves,
        ErrorCode::Stage1Solvency
    );
    Ok((next_paid, next_count))
}

fn consume_claim(dung: &mut Stage1DungMint, set: &mut Stage1DungClaimSet, info: &AccountInfo,
    registration: &Stage1Recipient, destination: Pubkey, index: u32, person: Pubkey,
    amount: u64, proof: &[Stage1SumNode]) -> Result<()> {
    require!(set.sealed && set.role < 2, ErrorCode::Stage1ClaimStorage);
    stage1_claim_storage::ready(info, 8 + Stage1DungClaimSet::INIT_SPACE, set.leaf_count, set.storage_version)?;
    check_claim_time(set.published_at, Clock::get()?.unix_timestamp)?;
    require!(registration.person == person && registration.registered_at <= dung.frozen_at
        && destination == registration.recipient, ErrorCode::Stage1InvalidRecipient);
    verify_dung_proof(dung, set, crate::ID, index, person, registration.recipient, amount, proof)?;
    stage1_claim_storage::mark(&mut info.try_borrow_mut_data()?[8 + Stage1DungClaimSet::INIT_SPACE..],
        set.leaf_count, set.claimed_count, index)?;
    let (paid, count) = claim_progress(set.paid, set.claimed_count, set.total, set.leaf_count, amount)?;
    set.paid = paid;
    set.claimed_count = count;
    dung.minted[set.role as usize] = paid;
    Ok(())
}

pub fn claim(
    ctx: Context<Stage1ClaimDung>,
    index: u32,
    person: Pubkey,
    amount: u64,
    proof: Vec<Stage1SumNode>,
) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let info = ctx.accounts.claim_set.to_account_info();
    consume_claim(&mut ctx.accounts.dung, &mut ctx.accounts.claim_set, &info,
        &ctx.accounts.registration, ctx.accounts.destination.owner, index, person, amount, &proof)?;
    let state = &mut ctx.accounts.state;
    state.minted_lifetime = plus(state.minted_lifetime, amount as u128)?;
    require!(
        state.minted_lifetime <= state.allocated_lifetime,
        ErrorCode::Stage1Solvency
    );
    let bump = [ctx.accounts.program_config.dung_mint_auth_bump];
    token::mint_to(
        CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            MintTo {
                mint: ctx.accounts.mint.to_account_info(),
                to: ctx.accounts.destination.to_account_info(),
                authority: ctx.accounts.dung_mint_auth.to_account_info(),
            },
            &[&[DUNG_MINT_AUTH_SEED, &bump]],
        ),
        amount,
    )?;
    Ok(())
}

pub fn claim_batch(ctx: Context<Stage1ClaimDungBatch>, person: Pubkey, leaves: Vec<Stage1BatchLeaf>) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    require!(!leaves.is_empty() && leaves.len() <= stage1_claim_storage::CLAIM_BATCH_LIMIT
        && leaves.len() * 2 == ctx.remaining_accounts.len(), ErrorCode::Stage1InvalidBatch);
    let city = Pubkey::find_program_address(&[S1_CITY], &crate::ID).0;
    let mut amount = 0u64;
    for (i, leaf) in leaves.iter().enumerate() {
        let dung_info = &ctx.remaining_accounts[2*i];
        let info = &ctx.remaining_accounts[2*i+1];
        require!(dung_info.is_writable && info.is_writable
            && !(0..i).any(|j| ctx.remaining_accounts[2*j+1].key == info.key), ErrorCode::Stage1InvalidBatch);
        // Reload after each write: rider/backer entries may share this Dung.
        let mut dung: Stage1DungMint = stage1::read_owned(dung_info)?;
        let mut set: Stage1DungClaimSet = stage1::read_owned(info)?;
        require!(dung.city == city && dung.mint == ctx.accounts.mint.key()
            && set.dung == *dung_info.key && set.role < 2, ErrorCode::Stage1InvalidProof);
        let expected = Pubkey::create_program_address(&[S1_DUNG, dung.hill.as_ref(), &dung.week.to_le_bytes(), &[dung.bump]],
            &crate::ID).map_err(|_| error!(ErrorCode::Stage1ClaimStorage))?;
        require_keys_eq!(expected, *dung_info.key, ErrorCode::Stage1ClaimStorage);
        let expected = Pubkey::create_program_address(&[S1_DUNG_CLAIMS, dung_info.key.as_ref(), &[set.role], &[set.bump]],
            &crate::ID).map_err(|_| error!(ErrorCode::Stage1ClaimStorage))?;
        require_keys_eq!(expected, *info.key, ErrorCode::Stage1ClaimStorage);
        consume_claim(&mut dung, &mut set, info, &ctx.accounts.registration, ctx.accounts.destination.owner,
            leaf.index, person, leaf.amount, &leaf.proof)?;
        set.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])?;
        dung.try_serialize(&mut &mut dung_info.try_borrow_mut_data()?[..])?;
        amount = amount.checked_add(leaf.amount).ok_or(ErrorCode::Stage1Arithmetic)?;
    }
    let state = &mut ctx.accounts.state;
    state.minted_lifetime = plus(state.minted_lifetime, amount as u128)?;
    require!(state.minted_lifetime <= state.allocated_lifetime, ErrorCode::Stage1Solvency);
    let bump = [ctx.accounts.program_config.dung_mint_auth_bump];
    token::mint_to(CpiContext::new_with_signer(ctx.accounts.token_program.to_account_info(), MintTo {
        mint: ctx.accounts.mint.to_account_info(), to: ctx.accounts.destination.to_account_info(),
        authority: ctx.accounts.dung_mint_auth.to_account_info() }, &[&[DUNG_MINT_AUTH_SEED, &bump]]), amount)?;
    Ok(())
}

pub fn prepare_claim_set(ctx: Context<Stage1PrepareDungClaims>, role: u8, leaf_count: u32) -> Result<()> {
    require!(role < 2, ErrorCode::Stage1InvalidProof);
    require!(ctx.accounts.dung.published_roles & (1 << role) == 0, ErrorCode::Stage1ClaimStorage);
    let info = ctx.accounts.claim_set.to_account_info();
    let mut set = if info.owner == &System::id() && info.data_is_empty() {
        Stage1DungClaimSet { dung: ctx.accounts.dung.key(), role, bump: ctx.bumps.claim_set, rent_payer: ctx.accounts.publisher.key(),
            storage_version: stage1_claim_storage::CLAIM_STORAGE_VERSION, ..Stage1DungClaimSet::default() }
    } else { stage1::read_owned::<Stage1DungClaimSet>(&info)? };
    require!(!set.sealed && set.storage_version == stage1_claim_storage::CLAIM_STORAGE_VERSION
        && set.dung == ctx.accounts.dung.key() && set.role == role && set.bump == ctx.bumps.claim_set
        && set.paid == 0 && set.claimed_count == 0 && set.published_at == 0,
        ErrorCode::Stage1ClaimStorage);
    let size = 8 + Stage1DungClaimSet::INIT_SPACE + stage1_claim_storage::tail_size(leaf_count)?;
    stage1_claim_storage::grow(&info, &ctx.accounts.publisher.to_account_info(),
        &ctx.accounts.system_program.to_account_info(), size,
        &[S1_DUNG_CLAIMS, ctx.accounts.dung.key().as_ref(), &[role], &[set.bump]])?;
    set.leaf_count = leaf_count;
    set.try_serialize(&mut &mut info.try_borrow_mut_data()?[..])?;
    Ok(())
}

#[derive(Accounts)]
#[instruction(week: u64)]
pub struct Stage1PublishDung<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(constraint = hill_account.hill.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill_account: Stage1HillAccount<'info>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump, constraint = program_config.initialized @ ErrorCode::NotInitialized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(address = program_config.dung_mint @ ErrorCode::InvalidMint, constraint = mint.decimals == 9 @ ErrorCode::InvalidMint)]
    pub mint: Box<Account<'info, Mint>>,
    #[account(init, payer = publisher, space = 8 + Stage1DungMint::INIT_SPACE, seeds = [S1_DUNG, hill_account.hill.key().as_ref(), &week.to_le_bytes()], bump)]
    pub dung: Box<Account<'info, Stage1DungMint>>,
    #[account(init_if_needed, payer = publisher, space = 8 + Stage1DungState::INIT_SPACE, seeds = [S1_DUNG_STATE], bump)]
    pub state: Box<Account<'info, Stage1DungState>>,
    #[account(mut)]
    pub publisher: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn publish_claim_set(
    ctx: Context<Stage1PublishDungClaims>,
    role: u8,
    root: Stage1DungRoot,
) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let set = &ctx.accounts.claim_set;
    stage1_claim_storage::ready(&set.to_account_info(), 8 + Stage1DungClaimSet::INIT_SPACE, root.leaf_count, set.storage_version)?;
    require!(!set.sealed && set.leaf_count == root.leaf_count && set.paid == 0 && set.claimed_count == 0,
        ErrorCode::Stage1ClaimStorage);
    let dung = &mut ctx.accounts.dung;
    require!(role < 2, ErrorCode::Stage1InvalidProof);
    require!(dung.published_roles & (1 << role) == 0, ErrorCode::Stage1ClaimStorage);
    let total = dung.role_totals[role as usize];
    check_root(&root, total, &dung_context(crate::ID, dung, role)?)?;
    **ctx.accounts.claim_set = Stage1DungClaimSet {
        dung: dung.key(),
        role,
        root: root.root,
        total,
        leaf_count: root.leaf_count,
        paid: 0,
        claimed_count: 0,
        bump: ctx.accounts.claim_set.bump,
        published_at: Clock::get()?.unix_timestamp,
        storage_version: stage1_claim_storage::CLAIM_STORAGE_VERSION,
        sealed: true,
        rent_payer: ctx.accounts.claim_set.rent_payer,
    };
    dung.published_roles |= 1 << role;
    let set = &ctx.accounts.claim_set;
    let event = Stage1DungRolePublished { claim_set: set.key(), dung: dung.key(), role,
        root: set.root, total, leaf_count: set.leaf_count, published_at: set.published_at, rent_payer: set.rent_payer };
    let hill = &mut ctx.accounts.hill;
    hill.dung_publication_commitment = hashv(&[b"BR-stage1-v2:dung-role-history\0",
        &hill.dung_publication_commitment, &event.try_to_vec()?]).to_bytes();
    emit!(event);
    Ok(())
}

#[derive(Accounts)]
#[instruction(role: u8)]
pub struct Stage1PrepareDungClaims<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(seeds = [S1_DUNG, dung.hill.as_ref(), &dung.week.to_le_bytes()], bump = dung.bump, has_one = city)]
    pub dung: Box<Account<'info, Stage1DungMint>>,
    /// CHECK: canonical PDA; owner, unsealed header and allocation checked in handler.
    #[account(mut, seeds = [S1_DUNG_CLAIMS, dung.key().as_ref(), &[role]], bump)]
    pub claim_set: UncheckedAccount<'info>,
    #[account(mut)]
    pub publisher: Signer<'info>,
    pub system_program: Program<'info, System>,
}
#[derive(Accounts)]
#[instruction(role: u8)]
pub struct Stage1PublishDungClaims<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_DUNG, dung.hill.as_ref(), &dung.week.to_le_bytes()], bump = dung.bump, has_one = city)]
    pub dung: Box<Account<'info, Stage1DungMint>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city, constraint = dung.hill == hill.key() @ ErrorCode::Stage1InvalidHill)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    #[account(mut, seeds = [S1_DUNG_CLAIMS, dung.key().as_ref(), &[role]], bump = claim_set.bump, has_one = dung,
        constraint = claim_set.role == role @ ErrorCode::Stage1InvalidProof)]
    pub claim_set: Box<Account<'info, Stage1DungClaimSet>>,
    #[account(mut)]
    pub publisher: Signer<'info>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
#[instruction(index: u32, person: Pubkey)]
pub struct Stage1ClaimDung<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = dung.city == city.key() @ ErrorCode::Stage1InvalidHill)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_DUNG, dung.hill.as_ref(), &dung.week.to_le_bytes()], bump = dung.bump)]
    pub dung: Box<Account<'info, Stage1DungMint>>,
    #[account(mut, seeds = [S1_DUNG_CLAIMS, dung.key().as_ref(), &[claim_set.role]], bump = claim_set.bump, has_one = dung,
        constraint = claim_set.role < 2 @ ErrorCode::Stage1InvalidProof)]
    pub claim_set: Box<Account<'info, Stage1DungClaimSet>>,
    #[account(mut, seeds = [S1_DUNG_STATE], bump = state.bump)]
    pub state: Box<Account<'info, Stage1DungState>>,
    #[account(seeds = [S1_RECIPIENT, person.as_ref()], bump = registration.bump)]
    pub registration: Account<'info, Stage1Recipient>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump, constraint = program_config.initialized @ ErrorCode::NotInitialized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut, address = program_config.dung_mint @ ErrorCode::InvalidMint, constraint = mint.key() == dung.mint @ ErrorCode::InvalidMint,
        constraint = mint.decimals == 9 @ ErrorCode::InvalidMint)]
    pub mint: Box<Account<'info, Mint>>,
    /// CHECK: existing DUNG mint authority; SPL mint_to verifies its authority.
    #[account(seeds = [DUNG_MINT_AUTH_SEED], bump = program_config.dung_mint_auth_bump)]
    pub dung_mint_auth: UncheckedAccount<'info>,
    #[account(mut, token::mint = mint)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(person: Pubkey)]
pub struct Stage1ClaimDungBatch<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_DUNG_STATE], bump = state.bump)]
    pub state: Box<Account<'info, Stage1DungState>>,
    #[account(seeds = [S1_RECIPIENT, person.as_ref()], bump = registration.bump)]
    pub registration: Account<'info, Stage1Recipient>,
    #[account(seeds = [PROGRAM_CONFIG_SEED], bump = program_config.bump, constraint = program_config.initialized @ ErrorCode::NotInitialized)]
    pub program_config: Box<Account<'info, ProgramConfig>>,
    #[account(mut, address = program_config.dung_mint @ ErrorCode::InvalidMint, constraint = mint.decimals == 9 @ ErrorCode::InvalidMint)]
    pub mint: Box<Account<'info, Mint>>,
    /// CHECK: existing DUNG mint authority; SPL mint_to verifies its authority.
    #[account(seeds = [DUNG_MINT_AUTH_SEED], bump = program_config.dung_mint_auth_bump)]
    pub dung_mint_auth: UncheckedAccount<'info>,
    #[account(mut, token::mint = mint)]
    pub destination: Box<Account<'info, TokenAccount>>,
    pub token_program: Program<'info, Token>,
}

/// Sporting absence is publisher-attested, exactly like nonzero TSS and field
/// at publication. Cash custody/holds are never skipped by this instruction.
pub fn skip_weeks(
    ctx: Context<Stage1SkipDung>,
    through: u64,
    snapshot: [u8; 32],
    max_field_count: u32,
    total_postbond_tss_micros: u128,
) -> Result<()> {
    stage1_governance::settlement_open(&ctx.accounts.city)?;
    let hill = &mut ctx.accounts.hill;
    require!(hill.bonded, ErrorCode::Stage1NotBonded);
    let start = next_publication_week(&ctx.accounts.city, hill.dung_next_week)?;
    require!(
        through >= start && through - start < S1_SKIP_LIMIT,
        ErrorCode::Stage1WeekNotFinalizable
    );
    let cutoff = opening_at(&ctx.accounts.city, through)?
        .checked_add(S1_WEEK + 86_400)
        .ok_or(ErrorCode::Stage1Arithmetic)?;
    require!(
        Clock::get()?.unix_timestamp >= cutoff,
        ErrorCode::Stage1WeekNotFinalizable
    );
    require!(
        snapshot != [0; 32] && (max_field_count < 5 || total_postbond_tss_micros == 0),
        ErrorCode::Stage1InvalidFunding
    );
    let commitment = hashv(&[
        b"BR-stage1-v1:dung-skip\0",
        crate::ID.as_ref(),
        ctx.accounts.city.key().as_ref(),
        hill.key().as_ref(),
        &start.to_le_bytes(),
        &through.to_le_bytes(),
        &snapshot,
        &max_field_count.to_le_bytes(),
        &total_postbond_tss_micros.to_le_bytes(),
    ])
    .to_bytes();
    hill.dung_next_week = through.checked_add(1).ok_or(ErrorCode::Stage1Arithmetic)?;
    emit!(Stage1DungWeeksSkipped {
        hill: hill.key(),
        from_week: start,
        through_week: through,
        snapshot,
        max_field_count,
        total_postbond_tss_micros,
        commitment
    });
    Ok(())
}
#[derive(Accounts)]
pub struct Stage1SkipDung<'info> {
    #[account(seeds = [S1_CITY], bump = city.bump, constraint = city.publisher == publisher.key() @ ErrorCode::Stage1Unauthorized)]
    pub city: Box<Account<'info, Stage1CityConfig>>,
    #[account(mut, seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump, has_one = city)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    pub publisher: Signer<'info>,
}
#[event]
pub struct Stage1DungWeeksSkipped {
    pub hill: Pubkey,
    pub from_week: u64,
    pub through_week: u64,
    pub snapshot: [u8; 32],
    pub max_field_count: u32,
    pub total_postbond_tss_micros: u128,
    pub commitment: [u8; 32],
}

pub fn close_claim_set(ctx: Context<Stage1CloseDungClaims>) -> Result<()> {
    let set = &ctx.accounts.claim_set;
    stage1_claim_storage::ready(&set.to_account_info(), 8 + Stage1DungClaimSet::INIT_SPACE, set.leaf_count, set.storage_version)?;
    stage1_claim_storage::fully_claimed(set.sealed, set.paid, set.total as u128, set.claimed_count, set.leaf_count)
}
#[derive(Accounts)]
pub struct Stage1CloseDungClaims<'info> {
    #[account(mut, close = rent_payer, seeds = [S1_DUNG_CLAIMS, claim_set.dung.as_ref(), &[claim_set.role]],
        bump = claim_set.bump, has_one = rent_payer, constraint = claim_set.role < 2 @ ErrorCode::Stage1InvalidProof)]
    pub claim_set: Box<Account<'info, Stage1DungClaimSet>>,
    /// CHECK: immutable original refund destination.
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,
}

pub fn close_mint(ctx: Context<Stage1CloseDungMint>) -> Result<()> {
    let dung = &ctx.accounts.dung;
    require!(ctx.accounts.hill.dung_next_week > dung.week && dung.published_roles == 3
        && dung.minted == dung.role_totals, ErrorCode::Stage1ClaimStorage);
    stage1_claims::require_absent(&ctx.accounts.rider_set.to_account_info())?;
    stage1_claims::require_absent(&ctx.accounts.backer_set.to_account_info())?;
    // allocated_lifetime/minted_lifetime live in Stage1DungState; no supply or
    // accounting field changes here, and no policy/guardian gate can trap rent.
    Ok(())
}

#[derive(Accounts)]
pub struct Stage1CloseDungMint<'info> {
    #[account(mut, close = rent_payer, seeds = [S1_DUNG, dung.hill.as_ref(), &dung.week.to_le_bytes()],
        bump = dung.bump, has_one = hill, has_one = rent_payer)]
    pub dung: Box<Account<'info, Stage1DungMint>>,
    #[account(seeds = [S1_HILL, hill.canon_id.as_ref()], bump = hill.bump,
        constraint = hill.city == dung.city @ ErrorCode::Stage1InvalidHill)]
    pub hill: Box<Account<'info, Stage1HillBond>>,
    /// CHECK: canonical rider set must be closed after full payment.
    #[account(seeds = [S1_DUNG_CLAIMS, dung.key().as_ref(), &[0]], bump)]
    pub rider_set: UncheckedAccount<'info>,
    /// CHECK: canonical backer set must be closed after full payment.
    #[account(seeds = [S1_DUNG_CLAIMS, dung.key().as_ref(), &[1]], bump)]
    pub backer_set: UncheckedAccount<'info>,
    /// CHECK: immutable original mint-record payer.
    #[account(mut)]
    pub rent_payer: UncheckedAccount<'info>,
}
