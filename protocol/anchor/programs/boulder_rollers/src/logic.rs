//! Shared checks and arithmetic called by the instruction handlers.

use crate::*;

pub(crate) fn is_authoritative_vault_seed_generation(seed_generation: u32) -> bool {
    seed_generation >= MIN_AUTHORITATIVE_VAULT_SEED_GENERATION
}

pub(crate) fn scheduled_emission_rate_bps(settlement_week: u64, emission_start_week: u64) -> Result<u64> {
    if settlement_week < emission_start_week {
        return Ok(0);
    }
    let elapsed_weeks = settlement_week.saturating_sub(emission_start_week);
    let elapsed_halvings = elapsed_weeks / EPOCHS_PER_HALVING;
    let shift = u32::try_from(elapsed_halvings).unwrap_or(u32::MAX);
    let halved = BASIS_POINTS_DENOMINATOR.checked_shr(shift).unwrap_or(0);
    Ok(halved.max(MIN_EMISSION_RATE_BPS))
}

pub(crate) fn settlement_supply_headroom(state: &DungMintState) -> Result<SettlementSupplyHeadroom> {
    state.assert_solvent()?;
    Ok(SettlementSupplyHeadroom {
        total: state
            .max_supply
            .checked_sub(state.committed_total()?)
            .ok_or(ErrorCode::DungMintAccountingMismatch)?,
        community: COMMUNITY_CAP
            .checked_sub(state.committed_community()?)
            .ok_or(ErrorCode::DungMintAccountingMismatch)?,
        pol: POL_CAP
            .checked_sub(state.pol_minted)
            .ok_or(ErrorCode::DungMintAccountingMismatch)?,
        treasury: TREASURY_CAP
            .checked_sub(state.treasury_minted)
            .ok_or(ErrorCode::DungMintAccountingMismatch)?,
    })
}

pub(crate) fn settlement_base_fits(
    amount: u64,
    headroom: &SettlementSupplyHeadroom,
    config: &DistributionConfig,
) -> Result<bool> {
    let shares = settlement_bucket_shares(amount, config)?;
    Ok(amount <= headroom.total
        && shares.community_total()? <= headroom.community
        && shares.pol <= headroom.pol
        && shares.treasury <= headroom.treasury)
}

pub(crate) fn maximum_canonical_base_emission(
    requested: u64,
    headroom: &SettlementSupplyHeadroom,
    config: &DistributionConfig,
) -> Result<u64> {
    const SPLIT_ROUNDING_PERIOD: u64 = 100;

    let upper = requested.min(headroom.total);
    let period_shares = settlement_bucket_shares(SPLIT_ROUNDING_PERIOD, config)?;
    let period_community = period_shares.community_total()?;
    let mut maximum = 0u64;

    // All canonical BPS values are multiples of 100, so rounding repeats every
    // 100 base units. Search each residue exactly; within one residue class the
    // split grows linearly and every cap predicate is monotonic.
    for residue in 0..=upper.min(SPLIT_ROUNDING_PERIOD - 1) {
        let residue_shares = settlement_bucket_shares(residue, config)?;
        let residue_community = residue_shares.community_total()?;
        if residue_community > headroom.community
            || residue_shares.pol > headroom.pol
            || residue_shares.treasury > headroom.treasury
        {
            continue;
        }

        let mut periods = (upper - residue) / SPLIT_ROUNDING_PERIOD;
        periods = periods.min((headroom.community - residue_community) / period_community);
        periods = periods.min((headroom.pol - residue_shares.pol) / period_shares.pol);
        periods =
            periods.min((headroom.treasury - residue_shares.treasury) / period_shares.treasury);
        let candidate = residue
            .checked_add(
                periods
                    .checked_mul(SPLIT_ROUNDING_PERIOD)
                    .ok_or(ErrorCode::Overflow)?,
            )
            .ok_or(ErrorCode::Overflow)?;
        maximum = maximum.max(candidate);
    }

    Ok(maximum)
}

pub(crate) fn plan_settlement_emission(
    state: &DungMintState,
    scheduled_emission: u64,
    carry: SettlementBucketShares,
    config: &DistributionConfig,
) -> Result<SettlementEmissionPlan> {
    require!(config.validate(), ErrorCode::InvalidDistributionConfig);
    require!(carry.pol == 0, ErrorCode::UnreservedProtocolCarry);
    require!(carry.treasury == 0, ErrorCode::UnreservedProtocolCarry);
    let headroom = settlement_supply_headroom(state)?;
    let base_emission = maximum_canonical_base_emission(scheduled_emission, &headroom, config)?;
    let base = settlement_bucket_shares(base_emission, config)?;
    let bucket_totals = base.checked_add(&carry)?;
    let cap_limited = base_emission < scheduled_emission;

    Ok(SettlementEmissionPlan {
        base_emission,
        base_shares: base,
        bucket_totals,
        cap_limited,
        terminal: scheduled_emission > 0 && base_emission == 0,
    })
}

pub(crate) fn checked_u128_to_u64(value: u128) -> Result<u64> {
    u64::try_from(value).map_err(|_| error!(ErrorCode::Overflow))
}

pub(crate) fn checked_sum_u64(values: impl IntoIterator<Item = u64>) -> Result<u64> {
    let mut total = 0u128;
    for value in values {
        total = total
            .checked_add(value as u128)
            .ok_or(ErrorCode::Overflow)?;
    }
    checked_u128_to_u64(total)
}

pub(crate) fn checked_mul_div_u64(value: u64, multiplier: u64, divisor: u64) -> Result<u64> {
    let quotient = (value as u128)
        .checked_mul(multiplier as u128)
        .ok_or(ErrorCode::Overflow)?
        .checked_div(divisor as u128)
        .ok_or(ErrorCode::DivisionByZero)?;
    checked_u128_to_u64(quotient)
}

pub(crate) fn stake_lp_transition(
    prior_lp_tokens: u64,
    amount: u64,
    total_lp_supply: u64,
    total_cal_staked: u64,
) -> Result<StakeLpTransition> {
    require!(
        (total_lp_supply == 0) == (total_cal_staked == 0),
        ErrorCode::InvalidVault
    );
    require!(
        prior_lp_tokens <= total_lp_supply,
        ErrorCode::InvalidStakeAccount
    );

    let lp_to_mint = if total_lp_supply == 0 {
        amount
    } else {
        checked_mul_div_u64(amount, total_lp_supply, total_cal_staked)?
    };
    require!(lp_to_mint > 0, ErrorCode::InvalidAmount);

    let next_lp_tokens = prior_lp_tokens
        .checked_add(lp_to_mint)
        .ok_or(ErrorCode::Overflow)?;
    Ok(StakeLpTransition {
        lp_to_mint,
        next_lp_tokens,
    })
}

pub(crate) fn lp_custody_restoration(
    current_amount: u64,
    restore_amount: u64,
    recorded_lp_tokens: u64,
) -> Result<LpCustodyRestoration> {
    require!(restore_amount > 0, ErrorCode::InvalidAmount);
    require!(
        current_amount <= recorded_lp_tokens,
        ErrorCode::LpCustodyAmountMismatch
    );
    let next_amount = current_amount
        .checked_add(restore_amount)
        .ok_or(ErrorCode::Overflow)?;
    require!(
        next_amount <= recorded_lp_tokens,
        ErrorCode::LpCustodyAmountMismatch
    );
    Ok(LpCustodyRestoration {
        next_amount,
        sealed: next_amount == recorded_lp_tokens,
    })
}

pub(crate) fn require_position_lp_identity(
    account: &TokenAccount,
    expected_authority: Pubkey,
    expected_mint: Pubkey,
) -> Result<()> {
    require!(
        account.owner == expected_authority,
        ErrorCode::InvalidLpCustodyAuthority
    );
    require!(account.mint == expected_mint, ErrorCode::InvalidMint);
    require!(
        matches!(
            account.state,
            AccountState::Initialized | AccountState::Frozen
        ),
        ErrorCode::InvalidLpCustodyState
    );
    Ok(())
}

pub(crate) fn require_position_lp_ready(
    account: &TokenAccount,
    expected_authority: Pubkey,
    expected_mint: Pubkey,
    recorded_lp_tokens: u64,
    allow_fresh_empty: bool,
) -> Result<()> {
    require_position_lp_identity(account, expected_authority, expected_mint)?;
    require!(
        account.amount == recorded_lp_tokens,
        ErrorCode::LpCustodyAmountMismatch
    );
    let is_sealed = account.state == AccountState::Frozen;
    let is_fresh_empty = allow_fresh_empty
        && recorded_lp_tokens == 0
        && account.amount == 0
        && account.state == AccountState::Initialized;
    require!(
        is_sealed || is_fresh_empty,
        ErrorCode::InvalidLpCustodyState
    );
    Ok(())
}

pub(crate) fn thaw_position_lp_if_needed<'info>(
    token_program: AccountInfo<'info>,
    account: AccountInfo<'info>,
    mint: AccountInfo<'info>,
    vault_authority: AccountInfo<'info>,
    state: AccountState,
    signer_seeds: &[&[&[u8]]],
) -> Result<()> {
    if state == AccountState::Frozen {
        token::thaw_account(CpiContext::new_with_signer(
            token_program,
            ThawAccount {
                account,
                mint,
                authority: vault_authority,
            },
            signer_seeds,
        ))?;
    }
    Ok(())
}

pub(crate) fn freeze_position_lp<'info>(
    token_program: AccountInfo<'info>,
    account: AccountInfo<'info>,
    mint: AccountInfo<'info>,
    vault_authority: AccountInfo<'info>,
    signer_seeds: &[&[&[u8]]],
) -> Result<()> {
    token::freeze_account(CpiContext::new_with_signer(
        token_program,
        FreezeAccount {
            account,
            mint,
            authority: vault_authority,
        },
        signer_seeds,
    ))
}

pub(crate) fn unstake_accounting_transition(
    prior_cal_staked: u64,
    prior_lp_tokens: u64,
    lp_amount: u64,
    total_lp_supply: u64,
    total_cal_staked: u64,
) -> Result<UnstakeAccountingTransition> {
    require!(lp_amount > 0, ErrorCode::Underflow);
    require!(prior_lp_tokens >= lp_amount, ErrorCode::Underflow);
    require!(total_lp_supply > 0, ErrorCode::DivisionByZero);
    require!(
        prior_lp_tokens <= total_lp_supply,
        ErrorCode::InvalidStakeAccount
    );

    let next_lp_tokens = prior_lp_tokens
        .checked_sub(lp_amount)
        .ok_or(ErrorCode::Underflow)?;
    let cal_to_return = checked_mul_div_u64(lp_amount, total_cal_staked, total_lp_supply)?;
    let exit_fee = checked_mul_div_u64(cal_to_return, EXIT_FEE_BPS, BASIS_POINTS_DENOMINATOR)?;
    let cal_after_fee = cal_to_return
        .checked_sub(exit_fee)
        .ok_or(ErrorCode::Underflow)?;
    // cal_staked is remaining deposited-principal basis, not current pool
    // value. Allocate that basis to the retained LP and floor the retained
    // side so a full exit is exactly zero and the record never overstates it.
    let next_cal_staked = checked_mul_div_u64(prior_cal_staked, next_lp_tokens, prior_lp_tokens)?;

    Ok(UnstakeAccountingTransition {
        next_lp_tokens,
        cal_to_return,
        exit_fee,
        cal_after_fee,
        next_cal_staked,
    })
}

pub(crate) fn settlement_inventory_count_after_change(
    current: u32,
    was_required: bool,
    is_required: bool,
) -> Result<u32> {
    match (was_required, is_required) {
        (false, true) => current
            .checked_add(1)
            .ok_or_else(|| error!(ErrorCode::Overflow)),
        (true, false) => current
            .checked_sub(1)
            .ok_or_else(|| error!(ErrorCode::Underflow)),
        _ => Ok(current),
    }
}

pub(crate) fn leaderboard_entry_shares(leaderboard_total: u64, entries: &[LeaderEntry]) -> Result<Vec<u64>> {
    let num_entries = entries.len().min(LEADERBOARD_RANK_PCTS.len());
    if num_entries == 0 {
        return Ok(Vec::new());
    }

    let pct_sum = checked_sum_u64(
        LEADERBOARD_RANK_PCTS[..num_entries]
            .iter()
            .map(|&pct| pct as u64),
    )?;
    let mut shares = Vec::with_capacity(num_entries);
    let mut group_start = 0usize;

    while group_start < num_entries {
        let group_time = entries[group_start].time_s;
        let mut group_end = group_start + 1;
        while group_end < num_entries && entries[group_end].time_s == group_time {
            group_end += 1;
        }

        let pooled_pct = checked_sum_u64(
            LEADERBOARD_RANK_PCTS[group_start..group_end]
                .iter()
                .map(|&pct| pct as u64),
        )?;
        let group_size =
            u64::try_from(group_end - group_start).map_err(|_| error!(ErrorCode::Overflow))?;
        let denominator = pct_sum.checked_mul(group_size).ok_or(ErrorCode::Overflow)?;
        let equal_share = checked_mul_div_u64(leaderboard_total, pooled_pct, denominator)?;
        shares.extend(std::iter::repeat(equal_share).take(group_end - group_start));
        group_start = group_end;
    }

    Ok(shares)
}

pub(crate) fn staker_unlocked_share(staker_total: u64, unlock_pct: u8) -> Result<u64> {
    let unlock_bps = (unlock_pct as u64)
        .checked_mul(PERCENT_TO_BPS)
        .ok_or(ErrorCode::Overflow)?;
    checked_mul_div_u64(staker_total, unlock_bps, BASIS_POINTS_DENOMINATOR)
}

pub(crate) fn classify_prior_staker_carry(policy_marker: u64, carry_stakers: u64) -> PriorStakerCarry {
    if policy_marker == STAKER_REMAINDER_POLICY_MARKER {
        PriorStakerCarry {
            unlocked_dust: carry_stakers,
            legacy_locked: 0,
        }
    } else {
        PriorStakerCarry {
            unlocked_dust: 0,
            legacy_locked: carry_stakers,
        }
    }
}

pub(crate) fn staker_unlock_pct(eligible_staker_count: u32) -> u8 {
    if eligible_staker_count == 0 {
        0
    } else if eligible_staker_count >= 10 {
        100
    } else {
        STAKER_UNLOCK_PCTS[(eligible_staker_count - 1) as usize]
    }
}

pub(crate) fn staker_week_plan(
    base_stakers: u64,
    prior_carry_stakers: u64,
    eligible_staker_count: u32,
) -> Result<StakerWeekPlan> {
    let unlock_pct = staker_unlock_pct(eligible_staker_count);
    let weekly_unlocked = staker_unlocked_share(base_stakers, unlock_pct)?;
    let locked_staker_amount = base_stakers
        .checked_sub(weekly_unlocked)
        .ok_or(ErrorCode::Overflow)?;
    let staker_distributable = checked_sum_u64([weekly_unlocked, prior_carry_stakers])?;

    Ok(StakerWeekPlan {
        unlock_pct,
        weekly_unlocked,
        staker_distributable,
        locked_staker_amount,
    })
}

pub(crate) fn staker_carry_after(plan: StakerWeekPlan, staker_distributed: u64) -> Result<u64> {
    plan.staker_distributable
        .checked_sub(staker_distributed)
        .ok_or_else(|| error!(ErrorCode::Overflow))
}

pub(crate) fn load_complete_settlement_stake_inventory<'info>(
    program_id: &Pubkey,
    token_program_id: &Pubkey,
    remaining_accounts: &'info [AccountInfo<'info>],
    vault_id: u64,
    expected_stake_account_count: u32,
) -> Result<Vec<Account<'info, VaultStake>>> {
    let stake_account_start = remaining_accounts
        .iter()
        .position(|account| account.owner != token_program_id)
        .unwrap_or(remaining_accounts.len());
    let mut stake_accounts = Vec::new();
    let mut seen_keys = Vec::new();
    let mut valid_stake_account_count = 0u32;

    for stake_info in &remaining_accounts[stake_account_start..] {
        require_keys_eq!(
            *stake_info.owner,
            *program_id,
            ErrorCode::InvalidStakeAccount
        );
        require!(stake_info.is_writable, ErrorCode::InvalidStakeAccount);
        require!(
            stake_info.data_len() == VaultStake::SIZE,
            ErrorCode::InvalidStakeAccount
        );
        require!(
            !seen_keys.contains(stake_info.key),
            ErrorCode::DuplicateVaultStake
        );

        let stake = Account::<VaultStake>::try_from(stake_info)
            .map_err(|_| error!(ErrorCode::InvalidStakeAccount))?;
        require!(stake.vault_id == vault_id, ErrorCode::InvalidStakeAccount);

        let vault_id_bytes = vault_id.to_le_bytes();
        let (expected_pda, expected_bump) = Pubkey::find_program_address(
            &[VAULT_STAKE_SEED, stake.user.as_ref(), &vault_id_bytes],
            program_id,
        );
        require_keys_eq!(
            expected_pda,
            *stake_info.key,
            ErrorCode::InvalidStakeAccount
        );
        require!(stake.bump == expected_bump, ErrorCode::InvalidStakeAccount);
        require!(
            stake.requires_settlement_account(),
            ErrorCode::InvalidStakeAccount
        );
        seen_keys.push(*stake_info.key);
        valid_stake_account_count = valid_stake_account_count
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;

        stake_accounts.push(stake);
    }

    require!(
        valid_stake_account_count == expected_stake_account_count,
        ErrorCode::InvalidStakeAccount
    );

    Ok(stake_accounts)
}

pub(crate) fn pre_scan_settlement_stakes<'info>(
    program_id: &Pubkey,
    token_program_id: &Pubkey,
    remaining_accounts: &'info [AccountInfo<'info>],
    vault_id: u64,
    settlement_clock: &SettlementClock,
    settlement_week: u64,
    expected_stake_account_count: u32,
) -> Result<(Vec<(Account<'info, VaultStake>, u64)>, u128, u32)> {
    let inventory = load_complete_settlement_stake_inventory(
        program_id,
        token_program_id,
        remaining_accounts,
        vault_id,
        expected_stake_account_count,
    )?;
    let mut weighted_inventory = Vec::with_capacity(inventory.len());
    let mut total_lp = 0u128;
    let mut next_inventory_count = 0u32;

    for mut stake in inventory {
        let settlement_lp = stake.lp_tokens_for_settlement(settlement_clock, settlement_week)?;
        total_lp = total_lp
            .checked_add(settlement_lp as u128)
            .ok_or(ErrorCode::Overflow)?;
        if stake.requires_settlement_account() {
            next_inventory_count = next_inventory_count
                .checked_add(1)
                .ok_or(ErrorCode::Overflow)?;
        }
        weighted_inventory.push((stake, settlement_lp));
    }

    Ok((weighted_inventory, total_lp, next_inventory_count))
}

pub(crate) fn staker_lp_share(unlocked_total: u64, stake_lp: u64, total_lp: u128) -> Result<u64> {
    let allocation = (unlocked_total as u128)
        .checked_mul(stake_lp as u128)
        .ok_or(ErrorCode::Overflow)?
        .checked_div(total_lp)
        .ok_or(ErrorCode::DivisionByZero)?;
    checked_u128_to_u64(allocation)
}

pub(crate) fn harvest_reward_split(total_earned: u64, harvest_fee_bps: u64) -> Result<(u64, u64)> {
    let harvest_fee = checked_mul_div_u64(total_earned, harvest_fee_bps, BASIS_POINTS_DENOMINATOR)?;
    let dung_to_staker = total_earned
        .checked_sub(harvest_fee)
        .ok_or(ErrorCode::Underflow)?;
    Ok((harvest_fee, dung_to_staker))
}

pub(crate) fn settlement_bucket_shares(
    total_dung: u64,
    config: &DistributionConfig,
) -> Result<SettlementBucketShares> {
    require!(config.validate(), ErrorCode::InvalidDistributionConfig);

    let mut shares = SettlementBucketShares {
        record_royalty: checked_mul_div_u64(
            total_dung,
            config.leaderboard_share_bps,
            BASIS_POINTS_DENOMINATOR,
        )?,
        stakers: checked_mul_div_u64(
            total_dung,
            config.staker_share_bps,
            BASIS_POINTS_DENOMINATOR,
        )?,
        local_legend: checked_mul_div_u64(
            total_dung,
            config.local_legend_share_bps,
            BASIS_POINTS_DENOMINATOR,
        )?,
        pol: checked_mul_div_u64(total_dung, config.pol_share_bps, BASIS_POINTS_DENOMINATOR)?,
        treasury: checked_mul_div_u64(
            total_dung,
            config.protocol_fee_bps,
            BASIS_POINTS_DENOMINATOR,
        )?,
    };
    let allocated = shares.total()?;
    let dust = total_dung
        .checked_sub(allocated)
        .ok_or(ErrorCode::Overflow)?;
    shares.record_royalty = checked_sum_u64([shares.record_royalty, dust])?;

    Ok(shares)
}

pub(crate) fn require_program_upgrade_authority(
    program_info: &AccountInfo,
    program_data_info: &AccountInfo,
    admin_key: Pubkey,
) -> Result<()> {
    require!(
        *program_info.key == crate::ID,
        ErrorCode::InvalidProgramAccount
    );
    require!(
        *program_info.owner == bpf_loader_upgradeable::ID,
        ErrorCode::InvalidProgramAccount
    );
    require!(
        *program_data_info.owner == bpf_loader_upgradeable::ID,
        ErrorCode::InvalidProgramData
    );

    let program_data = program_info.data.borrow();
    let program_state = limited_deserialize::<UpgradeableLoaderState>(
        &program_data,
        UpgradeableLoaderState::size_of_program() as u64,
    )
    .map_err(|_| error!(ErrorCode::InvalidProgramAccount))?;
    match program_state {
        UpgradeableLoaderState::Program {
            programdata_address,
        } => {
            require_keys_eq!(
                programdata_address,
                *program_data_info.key,
                ErrorCode::InvalidProgramData
            );
        }
        _ => return err!(ErrorCode::InvalidProgramAccount),
    }

    let loader_data = program_data_info.data.borrow();
    let loader_state = limited_deserialize::<UpgradeableLoaderState>(
        &loader_data,
        UpgradeableLoaderState::size_of_programdata_metadata() as u64,
    )
    .map_err(|_| error!(ErrorCode::InvalidProgramData))?;
    match loader_state {
        UpgradeableLoaderState::ProgramData {
            upgrade_authority_address: Some(upgrade_authority),
            ..
        } => {
            require_keys_eq!(upgrade_authority, admin_key, ErrorCode::UnauthorizedAdmin);
        }
        _ => return err!(ErrorCode::UnauthorizedAdmin),
    }

    Ok(())
}

pub(crate) fn require_completed_at_economic_window(completed_at: i64, current_time: i64) -> Result<()> {
    require!(
        completed_at >= EPOCH_ANCHOR,
        ErrorCode::InvalidRideTimestamps
    );
    require!(
        completed_at <= current_time.saturating_add(MAX_RIDE_CLOCK_SKEW_SECONDS),
        ErrorCode::InvalidRideTimestamps
    );
    require!(
        completed_at >= current_time.saturating_sub(MAX_RIDE_AGE_SECONDS),
        ErrorCode::InvalidRideTimestamps
    );
    Ok(())
}

pub(crate) fn require_valid_ride_timestamps(
    started_at: i64,
    completed_at: i64,
    current_time: i64,
) -> Result<()> {
    require!(completed_at >= started_at, ErrorCode::InvalidRideTimestamps);
    require_completed_at_economic_window(completed_at, current_time)?;
    let duration_s = completed_at
        .checked_sub(started_at)
        .ok_or(ErrorCode::InvalidRideTimestamps)?;
    require!(
        duration_s > 0 && duration_s <= MAX_RIDE_DURATION_SECONDS,
        ErrorCode::InvalidRideTimestamps
    );
    Ok(())
}

/// Bound one attestation's economics. CAL is earned at one whole CAL per TSS
/// (the backend floors both from the same TSS), so base units may not exceed
/// the declared TSS's conversion; the declared TSS may not exceed what IF 40
/// sustains over the elapsed ride. This bounds a single malformed call. A
/// compromised attester key can still declare any ride inside these limits.
pub fn require_ride_economics_within_bounds(
    started_at: i64,
    completed_at: i64,
    total_tss: u32,
    cal_earned: u64,
) -> Result<()> {
    require!(
        cal_earned / CAL_DECIMALS_MULTIPLIER <= u64::from(total_tss),
        ErrorCode::RideCalExceedsTss
    );
    let duration_s = completed_at
        .checked_sub(started_at)
        .filter(|duration_s| *duration_s > 0)
        .ok_or(ErrorCode::InvalidRideTimestamps)?;
    // TSS = elapsed_hours * IF^2 * 100, so the ceiling is elapsed_s * IF^2 / 36.
    let intensity_ceiling = duration_s as u128
        * u128::from(MAX_RIDE_INTENSITY_FACTOR * MAX_RIDE_INTENSITY_FACTOR);
    require!(
        u128::from(total_tss) * 36 <= intensity_ceiling,
        ErrorCode::RideTssExceedsDuration
    );
    Ok(())
}

pub(crate) fn require_accepted_ride_timestamps(
    started_at: i64,
    completed_at: i64,
    settled_at: i64,
) -> Result<()> {
    // Child effects inherit the immutable admission clock recorded by record_ride.
    require_valid_ride_timestamps(started_at, completed_at, settled_at)
}

pub(crate) fn ride_cal_tribute_budget(cal_earned: u64) -> Result<u64> {
    // The backend and database freeze exact measured climb-TSS amounts. The
    // program cannot reproduce NP from a raw ride file, so its independent
    // invariant is the full attested-CAL conservation ceiling.
    Ok(cal_earned)
}

/// Validate the ratified hold window against the immutable chain-admission
/// clock. A Threshold already effective when a late upload is admitted has no
/// held duration. Otherwise eligibility is decided when the rider's first
/// Threshold authority becomes effective. Release retries may occur later.
pub fn require_valid_held_ride_release_window(
    admitted_at: i64,
    threshold_effective_at: i64,
    release_time: i64,
) -> Result<()> {
    require!(
        admitted_at > 0 && threshold_effective_at > 0,
        ErrorCode::InvalidHeldRideReleaseWindow
    );
    let held_for = if threshold_effective_at > admitted_at {
        threshold_effective_at
            .checked_sub(admitted_at)
            .ok_or(ErrorCode::InvalidHeldRideReleaseWindow)?
    } else {
        0
    };
    require!(
        held_for <= HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS,
        ErrorCode::HeldRideReleaseWindowExpired
    );
    require!(
        release_time >= admitted_at,
        ErrorCode::InvalidHeldRideReleaseWindow
    );
    require!(
        release_time >= threshold_effective_at,
        ErrorCode::HeldRideThresholdNotEffective
    );
    Ok(())
}

/// Derive the maximum release-specific tribute while proving that the parent
/// attestation authorized no ordinary CAL economics.
pub fn held_ride_release_tribute_budget(
    parent_attestation_cal: u64,
    released_cal: u64,
) -> Result<u64> {
    require!(
        parent_attestation_cal == 0,
        ErrorCode::HeldRideParentHasEconomics
    );
    require!(released_cal > 0, ErrorCode::InvalidAmount);
    ride_cal_tribute_budget(released_cal)
}

/// A release is permanently attributed to the Settlement Week captured when
/// its child authority is created. A Vault still draining an older flow must
/// wait; a Vault that has already advanced past the release can never be
/// retargeted automatically.
pub fn require_held_release_settlement_week(
    vault_open_settlement_week: u64,
    release_settlement_week: u64,
) -> Result<()> {
    require!(
        vault_open_settlement_week >= release_settlement_week,
        ErrorCode::HeldRideReleaseFlowNotOpen
    );
    require!(
        vault_open_settlement_week <= release_settlement_week,
        ErrorCode::HeldRideReleaseFlowClosed
    );
    Ok(())
}

pub(crate) fn credit_ride_tribute_budget<'info>(
    budget_info: &AccountInfo<'info>,
    authority_info: &AccountInfo<'info>,
    system_program_info: &AccountInfo<'info>,
    program_id: &Pubkey,
    ride_attestation: Pubkey,
    cal_budget: u64,
    cal_tribute: u64,
) -> Result<()> {
    let (expected_budget, bump) = Pubkey::find_program_address(
        &[RIDE_TRIBUTE_BUDGET_SEED, ride_attestation.as_ref()],
        program_id,
    );
    require_keys_eq!(
        *budget_info.key,
        expected_budget,
        ErrorCode::InvalidRideTributeBudget
    );
    require!(budget_info.is_writable, ErrorCode::InvalidRideTributeBudget);

    let bump_seed = [bump];
    let seeds: &[&[u8]] = &[
        RIDE_TRIBUTE_BUDGET_SEED,
        ride_attestation.as_ref(),
        &bump_seed,
    ];
    let signer_seeds = &[seeds];
    if budget_info.owner == &anchor_lang::system_program::ID {
        require!(
            budget_info.data_is_empty(),
            ErrorCode::InvalidRideTributeBudget
        );
        let required_lamports = Rent::get()?.minimum_balance(RideTributeBudget::SIZE).max(1);
        let current_lamports = budget_info.lamports();
        if current_lamports == 0 {
            let accounts = anchor_lang::system_program::CreateAccount {
                from: authority_info.clone(),
                to: budget_info.clone(),
            };
            anchor_lang::system_program::create_account(
                CpiContext::new(system_program_info.clone(), accounts).with_signer(signer_seeds),
                required_lamports,
                RideTributeBudget::SIZE as u64,
                program_id,
            )?;
        } else {
            let top_up = required_lamports.saturating_sub(current_lamports);
            if top_up > 0 {
                let accounts = anchor_lang::system_program::Transfer {
                    from: authority_info.clone(),
                    to: budget_info.clone(),
                };
                anchor_lang::system_program::transfer(
                    CpiContext::new(system_program_info.clone(), accounts),
                    top_up,
                )?;
            }
            anchor_lang::system_program::allocate(
                CpiContext::new(
                    system_program_info.clone(),
                    anchor_lang::system_program::Allocate {
                        account_to_allocate: budget_info.clone(),
                    },
                )
                .with_signer(signer_seeds),
                RideTributeBudget::SIZE as u64,
            )?;
            anchor_lang::system_program::assign(
                CpiContext::new(
                    system_program_info.clone(),
                    anchor_lang::system_program::Assign {
                        account_to_assign: budget_info.clone(),
                    },
                )
                .with_signer(signer_seeds),
                program_id,
            )?;
        }
    }
    require!(
        budget_info.owner == program_id && budget_info.data_len() == RideTributeBudget::SIZE,
        ErrorCode::InvalidRideTributeBudget
    );

    let mut budget = {
        let data = budget_info.try_borrow_data()?;
        if data[..8] == [0; 8] {
            RideTributeBudget {
                ride_attestation,
                cal_budget,
                total_cal_tributed: 0,
                bump,
            }
        } else {
            RideTributeBudget::try_deserialize(&mut &data[..])?
        }
    };
    require!(
        budget.ride_attestation == ride_attestation
            && budget.cal_budget == cal_budget
            && budget.bump == bump,
        ErrorCode::InvalidRideTributeBudget
    );
    budget.credit(cal_tribute)?;
    budget.try_serialize(&mut &mut budget_info.try_borrow_mut_data()?[..])?;
    Ok(())
}

pub(crate) fn credit_held_ride_tribute_budget<'info>(
    budget_info: &AccountInfo<'info>,
    authority_info: &AccountInfo<'info>,
    system_program_info: &AccountInfo<'info>,
    program_id: &Pubkey,
    ride_attestation: Pubkey,
    held_ride_release: Pubkey,
    cal_budget: u64,
    cal_tribute: u64,
) -> Result<()> {
    let (expected_budget, bump) = Pubkey::find_program_address(
        &[RIDE_TRIBUTE_BUDGET_SEED, ride_attestation.as_ref()],
        program_id,
    );
    require_keys_eq!(
        *budget_info.key,
        expected_budget,
        ErrorCode::InvalidHeldRideTributeBudget
    );
    require!(
        budget_info.is_writable,
        ErrorCode::InvalidHeldRideTributeBudget
    );

    let bump_seed = [bump];
    let seeds: &[&[u8]] = &[
        RIDE_TRIBUTE_BUDGET_SEED,
        ride_attestation.as_ref(),
        &bump_seed,
    ];
    let signer_seeds = &[seeds];
    if budget_info.owner == &anchor_lang::system_program::ID {
        require!(
            budget_info.data_is_empty(),
            ErrorCode::InvalidHeldRideTributeBudget
        );
        let required_lamports = Rent::get()?
            .minimum_balance(ReleasedRideTributeBudget::SIZE)
            .max(1);
        let current_lamports = budget_info.lamports();
        if current_lamports == 0 {
            let accounts = anchor_lang::system_program::CreateAccount {
                from: authority_info.clone(),
                to: budget_info.clone(),
            };
            anchor_lang::system_program::create_account(
                CpiContext::new(system_program_info.clone(), accounts).with_signer(signer_seeds),
                required_lamports,
                ReleasedRideTributeBudget::SIZE as u64,
                program_id,
            )?;
        } else {
            let top_up = required_lamports.saturating_sub(current_lamports);
            if top_up > 0 {
                let accounts = anchor_lang::system_program::Transfer {
                    from: authority_info.clone(),
                    to: budget_info.clone(),
                };
                anchor_lang::system_program::transfer(
                    CpiContext::new(system_program_info.clone(), accounts),
                    top_up,
                )?;
            }
            anchor_lang::system_program::allocate(
                CpiContext::new(
                    system_program_info.clone(),
                    anchor_lang::system_program::Allocate {
                        account_to_allocate: budget_info.clone(),
                    },
                )
                .with_signer(signer_seeds),
                ReleasedRideTributeBudget::SIZE as u64,
            )?;
            anchor_lang::system_program::assign(
                CpiContext::new(
                    system_program_info.clone(),
                    anchor_lang::system_program::Assign {
                        account_to_assign: budget_info.clone(),
                    },
                )
                .with_signer(signer_seeds),
                program_id,
            )?;
        }
    }
    require!(
        budget_info.owner == program_id
            && budget_info.data_len() == ReleasedRideTributeBudget::SIZE,
        ErrorCode::InvalidHeldRideTributeBudget
    );

    let mut budget = {
        let data = budget_info.try_borrow_data()?;
        if data[..8] == [0; 8] {
            ReleasedRideTributeBudget {
                ride_attestation,
                release_authority: held_ride_release,
                cal_budget,
                total_cal_tributed: 0,
                bump,
            }
        } else {
            ReleasedRideTributeBudget::try_deserialize(&mut &data[..])?
        }
    };
    require!(
        budget.ride_attestation == ride_attestation
            && budget.release_authority == held_ride_release
            && budget.cal_budget == cal_budget
            && budget.bump == bump,
        ErrorCode::InvalidHeldRideTributeBudget
    );
    budget.credit(cal_tribute)?;
    budget.try_serialize(&mut &mut budget_info.try_borrow_mut_data()?[..])?;
    Ok(())
}

pub fn build_climb_completion_evidence_v2(
    ride_attestation: &Pubkey,
    vault: &Pubkey,
    completion_time_s: u32,
    cal_tribute: u64,
) -> [u8; 32] {
    let completion_time_bytes = completion_time_s.to_le_bytes();
    let cal_tribute_bytes = cal_tribute.to_le_bytes();
    anchor_lang::solana_program::hash::hashv(&[
        CLIMB_COMPLETION_EVIDENCE_V2_DOMAIN,
        ride_attestation.as_ref(),
        vault.as_ref(),
        &completion_time_bytes,
        &cal_tribute_bytes,
    ])
    .to_bytes()
}

pub fn build_released_climb_completion_evidence_v3(
    held_ride_release: &Pubkey,
    ride_attestation: &Pubkey,
    vault: &Pubkey,
    completion_time_s: u32,
    cal_tribute: u64,
) -> [u8; 32] {
    let completion_time_bytes = completion_time_s.to_le_bytes();
    let cal_tribute_bytes = cal_tribute.to_le_bytes();
    anchor_lang::solana_program::hash::hashv(&[
        RELEASED_CLIMB_COMPLETION_EVIDENCE_V3_DOMAIN,
        held_ride_release.as_ref(),
        ride_attestation.as_ref(),
        vault.as_ref(),
        &completion_time_bytes,
        &cal_tribute_bytes,
    ])
    .to_bytes()
}

pub(crate) fn inspect_dung_mint_state_layout(data: &[u8]) -> Result<DungMintStateLayout> {
    require!(
        data.len() == DungMintState::LEGACY_SIZE
            || data.len() == DungMintState::CLAIM_RESERVATION_SIZE
            || data.len() == DungMintState::SIZE,
        ErrorCode::InvalidDungMintStateLayout
    );
    require!(
        data[..8] == DungMintState::discriminator(),
        ErrorCode::InvalidDungMintStateLayout
    );

    let mut legacy_data = &data[8..DungMintState::LEGACY_SIZE];
    let legacy = LegacyDungMintState::deserialize(&mut legacy_data)
        .map_err(|_| error!(ErrorCode::InvalidDungMintStateLayout))?;
    require!(
        legacy_data.is_empty(),
        ErrorCode::InvalidDungMintStateLayout
    );

    let community_reserved = if data.len() >= DungMintState::CLAIM_RESERVATION_SIZE {
        let reservation_bytes: [u8; 8] = data
            [DungMintState::COMMUNITY_RESERVED_OFFSET..DungMintState::CLAIM_RESERVATION_SIZE]
            .try_into()
            .map_err(|_| error!(ErrorCode::InvalidDungMintStateLayout))?;
        Some(u64::from_le_bytes(reservation_bytes))
    } else {
        None
    };
    let reservation_policy_version = if data.len() == DungMintState::SIZE {
        Some(data[DungMintState::RESERVATION_POLICY_VERSION_OFFSET])
    } else {
        None
    };

    Ok(DungMintStateLayout {
        legacy,
        community_reserved,
        reservation_policy_version,
    })
}

pub(crate) fn validate_dung_mint_state_migration(
    data: &[u8],
    expected_authority: Pubkey,
    expected_bump: u8,
    expected_community_reserved: u64,
) -> Result<bool> {
    let layout = inspect_dung_mint_state_layout(data)?;
    require_keys_eq!(
        layout.legacy.authority,
        expected_authority,
        ErrorCode::DungMintAuthorityMismatch
    );
    require!(
        layout.legacy.bump == expected_bump,
        ErrorCode::InvalidDungMintStateBump
    );

    if let Some(policy_version) = layout.reservation_policy_version {
        require!(
            policy_version == DUNG_RESERVATION_POLICY_VERSION,
            ErrorCode::DungReservationPolicyNotMigrated
        );
        let current_reservation = layout
            .community_reserved
            .ok_or(ErrorCode::InvalidDungMintStateLayout)?;
        require!(
            current_reservation == expected_community_reserved,
            ErrorCode::CommunityReservationMismatch
        );
        layout
            .legacy
            .with_reservation_policy(current_reservation, policy_version)
            .assert_solvent()?;
        return Ok(false);
    }

    require!(
        layout.legacy.current_emission_rate_bps == BASIS_POINTS_DENOMINATOR,
        ErrorCode::LegacyEmissionHistoryAmbiguous
    );
    let prior_reservation = layout.community_reserved.unwrap_or(0);
    require!(
        prior_reservation <= expected_community_reserved,
        ErrorCode::CommunityReservationMismatch
    );
    layout
        .legacy
        .with_reservation_policy(expected_community_reserved, DUNG_RESERVATION_POLICY_VERSION)
        .assert_solvent()?;
    Ok(true)
}

pub(crate) fn write_dung_mint_state_policy(
    data: &mut [u8],
    reservation: u64,
    policy_version: u8,
) -> Result<()> {
    require!(
        data.len() == DungMintState::SIZE,
        ErrorCode::InvalidDungMintStateLayout
    );
    data[DungMintState::COMMUNITY_RESERVED_OFFSET..DungMintState::CLAIM_RESERVATION_SIZE]
        .copy_from_slice(&reservation.to_le_bytes());
    data[DungMintState::RESERVATION_POLICY_VERSION_OFFSET] = policy_version;
    Ok(())
}

pub(crate) fn sum_migration_community_obligations<'info>(
    program_id: &Pubkey,
    account_infos: &[AccountInfo<'info>],
    expected_vault_stake_count: u32,
    expected_vault_count: u32,
) -> Result<u64> {
    let mut seen_keys = Vec::with_capacity(account_infos.len());
    let mut seen_positions = Vec::with_capacity(account_infos.len());
    let mut seen_vault_ids = Vec::with_capacity(expected_vault_count as usize);
    let mut actual_vault_stake_count = 0u32;
    let mut actual_vault_count = 0u32;
    let mut total = 0u128;

    for account_info in account_infos {
        require_keys_eq!(
            *account_info.owner,
            *program_id,
            ErrorCode::InvalidMigrationInventory
        );
        require!(
            !seen_keys.contains(account_info.key),
            ErrorCode::DuplicateMigrationAccount
        );

        if account_info.data_len() == VaultStake::SIZE {
            let stake = {
                let data = account_info.try_borrow_data()?;
                let mut data_ref: &[u8] = &data;
                VaultStake::try_deserialize(&mut data_ref)
                    .map_err(|_| error!(ErrorCode::InvalidStakeAccount))?
            };
            let position = (stake.user, stake.vault_id);
            require!(
                !seen_positions.contains(&position),
                ErrorCode::DuplicateVaultStake
            );

            let vault_id_bytes = stake.vault_id.to_le_bytes();
            let (expected_pda, expected_bump) = Pubkey::find_program_address(
                &[VAULT_STAKE_SEED, stake.user.as_ref(), &vault_id_bytes],
                program_id,
            );
            require_keys_eq!(
                expected_pda,
                *account_info.key,
                ErrorCode::InvalidStakeAccount
            );
            require!(stake.bump == expected_bump, ErrorCode::InvalidStakeAccount);

            total = total
                .checked_add(stake.rewards_earned as u128)
                .ok_or(ErrorCode::Overflow)?;
            actual_vault_stake_count = actual_vault_stake_count
                .checked_add(1)
                .ok_or(ErrorCode::Overflow)?;
            seen_positions.push(position);
        } else if account_info.data_len() == Vault::SIZE {
            let vault = {
                let data = account_info.try_borrow_data()?;
                let mut data_ref: &[u8] = &data;
                Vault::try_deserialize(&mut data_ref)
                    .map_err(|_| error!(ErrorCode::InvalidVault))?
            };
            require!(
                vault.id < u64::from(expected_vault_count),
                ErrorCode::InvalidVault
            );
            require!(
                !seen_vault_ids.contains(&vault.id),
                ErrorCode::DuplicateVault
            );
            let vault_id_bytes = vault.id.to_le_bytes();
            let (expected_pda, expected_bump) =
                Pubkey::find_program_address(&[VAULT_SEED, &vault_id_bytes], program_id);
            require_keys_eq!(expected_pda, *account_info.key, ErrorCode::InvalidVault);
            require!(vault.bump == expected_bump, ErrorCode::InvalidVault);
            require!(vault.carry_pol == 0, ErrorCode::UnreservedProtocolCarry);
            require!(
                vault.carry_treasury == 0,
                ErrorCode::UnreservedProtocolCarry
            );

            total = total
                .checked_add(vault.carry_record_royalty as u128)
                .and_then(|sum| sum.checked_add(vault.carry_stakers as u128))
                .and_then(|sum| sum.checked_add(vault.carry_local_legend as u128))
                .ok_or(ErrorCode::Overflow)?;
            actual_vault_count = actual_vault_count
                .checked_add(1)
                .ok_or(ErrorCode::Overflow)?;
            seen_vault_ids.push(vault.id);
        } else {
            return err!(ErrorCode::InvalidMigrationInventory);
        }

        seen_keys.push(*account_info.key);
    }

    require!(
        actual_vault_stake_count == expected_vault_stake_count,
        ErrorCode::VaultStakeCountMismatch
    );
    require!(
        actual_vault_count == expected_vault_count,
        ErrorCode::VaultCountMismatch
    );

    checked_u128_to_u64(total)
}

pub(crate) fn migrate_dung_mint_state_layout<'info>(
    mint_state_info: &AccountInfo<'info>,
    expected_authority: Pubkey,
    expected_bump: u8,
    payer_info: &AccountInfo<'info>,
    system_program_info: &AccountInfo<'info>,
    expected_community_reserved: u64,
) -> Result<usize> {
    let migration_required = {
        let data = mint_state_info.try_borrow_data()?;
        validate_dung_mint_state_migration(
            &data,
            expected_authority,
            expected_bump,
            expected_community_reserved,
        )?
    };

    if !migration_required {
        return Ok(DungMintState::SIZE);
    }

    let rent = Rent::get()?;
    let required_lamports = rent.minimum_balance(DungMintState::SIZE);
    let rent_top_up = required_lamports.saturating_sub(mint_state_info.lamports());
    if rent_top_up > 0 {
        anchor_lang::system_program::transfer(
            CpiContext::new(
                system_program_info.clone(),
                anchor_lang::system_program::Transfer {
                    from: payer_info.clone(),
                    to: mint_state_info.clone(),
                },
            ),
            rent_top_up,
        )?;
    }

    mint_state_info.realloc(DungMintState::SIZE, true)?;
    {
        let mut data = mint_state_info.try_borrow_mut_data()?;
        write_dung_mint_state_policy(
            &mut data,
            expected_community_reserved,
            DUNG_RESERVATION_POLICY_VERSION,
        )?;
    }
    {
        let data = mint_state_info.try_borrow_data()?;
        require!(
            !validate_dung_mint_state_migration(
                &data,
                expected_authority,
                expected_bump,
                expected_community_reserved,
            )?,
            ErrorCode::InvalidDungMintStateLayout
        );
    }

    Ok(DungMintState::SIZE)
}

pub(crate) fn validate_program_version_transition(
    stored_version: u8,
    expected_current_version: u8,
    new_version: u8,
) -> Result<()> {
    require!(
        stored_version == expected_current_version,
        ErrorCode::StaleProgramVersion
    );
    require!(
        new_version > stored_version,
        ErrorCode::RegressiveProgramVersion
    );
    let exact_next = stored_version.checked_add(1).ok_or(ErrorCode::Overflow)?;
    require!(new_version == exact_next, ErrorCode::SkippedProgramVersion);
    require!(
        new_version == CURRENT_PROGRAM_VERSION,
        ErrorCode::UnsupportedProgramVersion
    );
    Ok(())
}

pub(crate) fn advance_program_version_bytes(
    data: &mut [u8],
    admin: Pubkey,
    expected_current_version: u8,
    new_version: u8,
) -> Result<(u8, u8)> {
    require!(
        data.len() >= ProgramConfig::STABLE_PREFIX_SIZE,
        ErrorCode::InvalidProgramConfigLayout
    );
    require!(
        data[..8] == ProgramConfig::discriminator(),
        ErrorCode::InvalidProgramConfigLayout
    );
    let stored_admin = Pubkey::try_from(
        &data[ProgramConfig::ADMIN_AUTHORITY_OFFSET..ProgramConfig::BACKEND_AUTHORITY_OFFSET],
    )
    .map_err(|_| ErrorCode::InvalidProgramConfigLayout)?;
    require_keys_eq!(stored_admin, admin, ErrorCode::UnauthorizedAdmin);
    require!(
        data[ProgramConfig::INITIALIZED_OFFSET] == 1,
        ErrorCode::NotInitialized
    );

    let stored_version = data[ProgramConfig::PROGRAM_VERSION_OFFSET];
    validate_program_version_transition(stored_version, expected_current_version, new_version)?;
    data[ProgramConfig::PROGRAM_VERSION_OFFSET] = new_version;
    Ok((stored_version, new_version))
}

pub(crate) fn advance_program_version_data(
    program_config: &AccountInfo,
    admin: Pubkey,
    expected_current_version: u8,
    new_version: u8,
) -> Result<(u8, u8)> {
    require_keys_eq!(
        *program_config.owner,
        ID,
        ErrorCode::InvalidProgramConfigLayout
    );
    let mut data = program_config.try_borrow_mut_data()?;
    advance_program_version_bytes(&mut data, admin, expected_current_version, new_version)
}

pub(crate) fn read_program_config_info(
    program_config: &AccountInfo,
    program_id: &Pubkey,
) -> Result<ProgramConfig> {
    require_keys_eq!(
        *program_config.owner,
        *program_id,
        ErrorCode::InvalidProgramConfigLayout
    );
    require!(
        program_config.data_len() == ProgramConfig::SIZE,
        ErrorCode::InvalidProgramConfigLayout
    );
    let data = program_config.try_borrow_data()?;
    let mut data_ref: &[u8] = &data;
    let config = ProgramConfig::try_deserialize(&mut data_ref)
        .map_err(|_| error!(ErrorCode::InvalidProgramConfigLayout))?;
    let (expected_program_config, expected_bump) =
        Pubkey::find_program_address(&[PROGRAM_CONFIG_SEED], program_id);
    require_keys_eq!(
        *program_config.key,
        expected_program_config,
        ErrorCode::InvalidProgramConfigLayout
    );
    require!(
        config.bump == expected_bump,
        ErrorCode::InvalidProgramConfigLayout
    );
    Ok(config)
}

#[allow(clippy::too_many_arguments)]
pub fn build_balance_vault_operation_id(
    program_id: &Pubkey,
    rider: &Pubkey,
    operation_authority: &Pubkey,
    kind: BalanceVaultOperationKind,
    vault_id: u64,
    primary_amount: u64,
    secondary_amount: u64,
    generation: u64,
    nonce: u64,
    expires_at: i64,
) -> [u8; 32] {
    let kind_bytes = [kind as u8];
    let vault_id_bytes = vault_id.to_le_bytes();
    let primary_amount_bytes = primary_amount.to_le_bytes();
    let secondary_amount_bytes = secondary_amount.to_le_bytes();
    let generation_bytes = generation.to_le_bytes();
    let nonce_bytes = nonce.to_le_bytes();
    let expires_at_bytes = expires_at.to_le_bytes();
    anchor_lang::solana_program::hash::hashv(&[
        BALANCE_VAULT_OPERATION_DOMAIN,
        program_id.as_ref(),
        rider.as_ref(),
        operation_authority.as_ref(),
        &kind_bytes,
        &vault_id_bytes,
        &primary_amount_bytes,
        &secondary_amount_bytes,
        &generation_bytes,
        &nonce_bytes,
        &expires_at_bytes,
    ])
    .to_bytes()
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn authorize_balance_vault_operation(
    rider_balance: &RiderBalance,
    balance_vault_authority: &mut BalanceVaultAuthority,
    operation_authority: Pubkey,
    program_id: &Pubkey,
    kind: BalanceVaultOperationKind,
    vault_id: u64,
    primary_amount: u64,
    secondary_amount: u64,
    authorization: BalanceVaultOperationAuthorization,
    now: i64,
) -> Result<()> {
    require!(
        rider_balance.status == RiderBalanceStatus::Active && rider_balance.revoked_at == 0,
        ErrorCode::InvalidBalanceStatus
    );
    require!(
        rider_balance.active_authority_model == BalanceAuthorityModel::RiderSession,
        ErrorCode::InvalidBalanceVaultAuthority
    );
    require_keys_eq!(
        balance_vault_authority.rider,
        rider_balance.rider,
        ErrorCode::InvalidBalanceVaultAuthority
    );
    require_keys_eq!(
        balance_vault_authority.authority,
        operation_authority,
        ErrorCode::InvalidBalanceVaultAuthority
    );
    require_keys_eq!(
        rider_balance.delegate_authority,
        operation_authority,
        ErrorCode::InvalidBalanceVaultAuthority
    );
    require!(
        balance_vault_authority.policy_hash != [0; 32]
            && balance_vault_authority.policy_hash == rider_balance.policy_hash,
        ErrorCode::InvalidBalanceVaultAuthority
    );
    require!(
        balance_vault_authority.revoked_at == 0,
        ErrorCode::BalanceVaultAuthorityRevoked
    );
    require!(
        now < balance_vault_authority.expires_at,
        ErrorCode::BalanceVaultAuthorityExpired
    );
    require!(
        authorization.generation == balance_vault_authority.generation,
        ErrorCode::StaleBalanceVaultAuthority
    );
    require!(
        authorization.nonce == balance_vault_authority.next_nonce,
        ErrorCode::BalanceVaultOperationReplay
    );
    require!(
        authorization.expires_at > now
            && authorization.expires_at <= balance_vault_authority.expires_at,
        ErrorCode::BalanceVaultOperationExpired
    );

    let expected_operation_id = build_balance_vault_operation_id(
        program_id,
        &rider_balance.rider,
        &operation_authority,
        kind,
        vault_id,
        primary_amount,
        secondary_amount,
        authorization.generation,
        authorization.nonce,
        authorization.expires_at,
    );
    require!(
        authorization.operation_id != [0; 32]
            && authorization.operation_id == expected_operation_id,
        ErrorCode::InvalidBalanceVaultOperation
    );

    balance_vault_authority.next_nonce = balance_vault_authority
        .next_nonce
        .checked_add(1)
        .ok_or(ErrorCode::Overflow)?;
    balance_vault_authority.last_operation_id = authorization.operation_id;
    Ok(())
}

pub(crate) fn read_token_account_info(token_account: &AccountInfo) -> Result<TokenAccount> {
    require_keys_eq!(
        *token_account.owner,
        anchor_spl::token::ID,
        ErrorCode::InvalidTokenAccount
    );

    let data = token_account.try_borrow_data()?;
    let mut data_ref: &[u8] = &data;
    TokenAccount::try_deserialize_unchecked(&mut data_ref)
        .map_err(|_| ErrorCode::InvalidTokenAccount.into())
}

pub(crate) fn read_dung_mint_state_unchecked(
    state_info: &AccountInfo,
    expected_bump: u8,
) -> Result<DungMintState> {
    require_keys_eq!(*state_info.owner, ID, ErrorCode::InvalidDungMintStateLayout);
    require!(
        state_info.data_len() == DungMintState::SIZE,
        ErrorCode::InvalidDungMintStateLayout
    );
    let state = {
        let data = state_info.try_borrow_data()?;
        DungMintState::try_deserialize(&mut &data[..])?
    };
    require!(
        state.bump == expected_bump,
        ErrorCode::InvalidDungMintStateBump
    );
    Ok(state)
}

pub(crate) fn write_dung_mint_state_unchecked(state_info: &AccountInfo, state: &DungMintState) -> Result<()> {
    let mut data = state_info.try_borrow_mut_data()?;
    state.try_serialize(&mut &mut data[..])?;
    Ok(())
}

pub(crate) fn build_canon_commitment_v1(
    canon_id: [u8; 16],
    canon_version: u16,
    canonical_profile_hash: [u8; 32],
) -> Result<[u8; 64]> {
    require!(
        canon_id.iter().any(|byte| *byte != 0)
            && canon_version > 0
            && canonical_profile_hash.iter().any(|byte| *byte != 0),
        ErrorCode::InvalidCanonCommitment
    );

    let mut commitment = [0; 64];
    commitment[0] = CANON_COMMITMENT_LAYOUT_VERSION;
    commitment[1..17].copy_from_slice(&canon_id);
    commitment[17..19].copy_from_slice(&canon_version.to_be_bytes());
    commitment[32..64].copy_from_slice(&canonical_profile_hash);
    Ok(commitment)
}

pub(crate) fn canon_commitment_hash(commitment: &[u8; 64]) -> [u8; 32] {
    anchor_lang::solana_program::hash::hash(commitment).to_bytes()
}

pub(crate) fn validate_climb_lineage(
    canon_id: [u8; 16],
    canon_version: u16,
    record_continuity_policy: RecordContinuityPolicy,
    predecessor: Option<([u8; 16], u16)>,
) -> Result<()> {
    // V4-B can open a fresh record board for a ratified successor, but it does
    // not yet migrate or share the predecessor Vault's records. Reject the
    // carry label until exact on-chain record continuity is implemented.
    require!(
        record_continuity_policy == RecordContinuityPolicy::NewRecordBoard,
        ErrorCode::RecordContinuityUnavailable
    );

    if canon_version == 1 {
        require!(predecessor.is_none(), ErrorCode::InvalidCanonLineage);
        return Ok(());
    }

    let (predecessor_canon_id, predecessor_version) =
        predecessor.ok_or(ErrorCode::InvalidCanonLineage)?;
    require!(
        predecessor_canon_id == canon_id,
        ErrorCode::InvalidCanonLineage
    );
    require!(
        predecessor_version
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?
            == canon_version,
        ErrorCode::InvalidCanonLineage
    );
    Ok(())
}

pub(crate) fn link_climb_successor(predecessor: &mut Climb, successor: Pubkey) -> Result<()> {
    require!(
        successor != Pubkey::default(),
        ErrorCode::InvalidCanonLineage
    );
    require!(
        predecessor.successor_climb == Pubkey::default(),
        ErrorCode::CanonSuccessorAlreadyRegistered
    );
    predecessor.successor_climb = successor;
    Ok(())
}

pub(crate) fn require_backend_vault_creation_sponsor(
    backend_authority: Pubkey,
    sponsor_authority: Pubkey,
) -> Result<()> {
    require_keys_eq!(
        backend_authority,
        sponsor_authority,
        ErrorCode::UnauthorizedBackend
    );
    Ok(())
}

pub(crate) fn bind_climb_to_vault(
    climb: &mut Climb,
    climb_key: Pubkey,
    vault_key: Pubkey,
) -> Result<VaultClimbBinding> {
    require!(
        climb.successor_climb == Pubkey::default(),
        ErrorCode::StaleClimbVersion
    );
    require!(
        climb.vault == Pubkey::default(),
        ErrorCode::ClimbAlreadyActivated
    );
    let expected_commitment = build_canon_commitment_v1(
        climb.canon_id,
        climb.canon_version,
        climb.canonical_profile_hash,
    )?;
    require!(
        climb.canon_commitment == expected_commitment
            && climb.commitment_hash == canon_commitment_hash(&climb.canon_commitment),
        ErrorCode::InvalidCanonCommitment
    );

    climb.vault = vault_key;
    Ok(VaultClimbBinding {
        climb: climb_key,
        canon_commitment: climb.canon_commitment,
        commitment_hash: climb.commitment_hash,
        name: climb.name,
        vert_m: climb.vert_m,
        distance_m: climb.distance_m,
        avg_gradient_pct: climb.avg_gradient_pct,
    })
}

/// Decode and persist the one-shot Climb binding outside the generated
/// `Accounts::try_accounts` frame. The four creation contexts are already near
/// Solana's stack limit, so they carry a writable unchecked account and this
/// helper restores the full owner, discriminator, exact-size, PDA, bump,
/// commitment, current-head, and single-activation checks before any copy.
pub(crate) fn bind_climb_account_to_vault(
    climb_info: &AccountInfo,
    program_id: &Pubkey,
    vault_key: Pubkey,
) -> Result<VaultClimbBinding> {
    require_keys_eq!(*climb_info.owner, *program_id, ErrorCode::InvalidClimb);
    require!(climb_info.is_writable, ErrorCode::InvalidClimb);
    require!(
        climb_info.data_len() == Climb::SIZE,
        ErrorCode::InvalidClimb
    );

    let mut climb = {
        let data = climb_info.try_borrow_data()?;
        let mut serialized: &[u8] = &data;
        Climb::try_deserialize(&mut serialized).map_err(|_| error!(ErrorCode::InvalidClimb))?
    };
    let (expected_climb, expected_bump) =
        Pubkey::find_program_address(&[CLIMB_SEED, climb.commitment_hash.as_ref()], program_id);
    require_keys_eq!(*climb_info.key, expected_climb, ErrorCode::InvalidClimb);
    require!(climb.bump == expected_bump, ErrorCode::InvalidClimb);

    let binding = bind_climb_to_vault(&mut climb, *climb_info.key, vault_key)?;
    let mut data = climb_info.try_borrow_mut_data()?;
    climb.try_serialize(&mut &mut data[..])?;
    Ok(binding)
}

pub(crate) fn initialize_chain_authoritative_activation(
    activation: &mut VaultActivation,
    vault_id: u64,
    timestamp: i64,
    economics_start_epoch: u64,
    climb: &Pubkey,
    vault: &Pubkey,
    bump: u8,
) {
    let evidence_hash = anchor_lang::solana_program::hash::hashv(&[
        VAULT_EMPTY_HISTORY_V2_DOMAIN,
        climb.as_ref(),
        vault.as_ref(),
    ])
    .to_bytes();

    activation.vault_id = vault_id;
    activation.is_active = true;
    activation.seed_completions_written = 0;
    activation.leaderboard_seeded = true;
    activation.created_at = timestamp;
    activation.activated_at = timestamp;
    activation.last_seed_at = timestamp;
    activation.seed_generation = 2;
    activation.seed_cutoff_at = timestamp;
    activation.economics_start_epoch = economics_start_epoch;
    activation.matched_users = 0;
    activation.matched_completions = 0;
    activation.evidence_hash = evidence_hash;
    activation.bump = bump;
}

pub(crate) fn empty_vault_leaderboard(vault_id: u64, bump: u8) -> VaultLeaderboard {
    VaultLeaderboard {
        vault_id,
        entries: Vec::new(),
        last_updated: 0,
        bump,
    }
}

pub(crate) fn create_empty_vault_leaderboard_account<'info>(
    leaderboard_info: &AccountInfo<'info>,
    sponsor_info: &AccountInfo<'info>,
    system_program_info: &AccountInfo<'info>,
    program_id: &Pubkey,
    vault_id: u64,
    bump: u8,
) -> Result<()> {
    let vault_id_bytes = vault_id.to_le_bytes();
    let (expected_key, expected_bump) =
        Pubkey::find_program_address(&[VAULT_LEADERBOARD_SEED, &vault_id_bytes], program_id);
    require_keys_eq!(
        *leaderboard_info.key,
        expected_key,
        ErrorCode::InvalidActivationSeed
    );
    require!(bump == expected_bump, ErrorCode::InvalidActivationSeed);
    require!(
        leaderboard_info.owner == &anchor_lang::system_program::ID
            && leaderboard_info.data_is_empty(),
        ErrorCode::InvalidActivationSeed
    );

    let signer_seeds: &[&[u8]] = &[VAULT_LEADERBOARD_SEED, &vault_id_bytes, &[bump]];
    let required_lamports = Rent::get()?.minimum_balance(VaultLeaderboard::SIZE).max(1);
    let current_lamports = leaderboard_info.lamports();
    if current_lamports == 0 {
        let create = anchor_lang::solana_program::system_instruction::create_account(
            sponsor_info.key,
            leaderboard_info.key,
            required_lamports,
            VaultLeaderboard::SIZE as u64,
            program_id,
        );
        invoke_signed(
            &create,
            &[
                sponsor_info.clone(),
                leaderboard_info.clone(),
                system_program_info.clone(),
            ],
            &[signer_seeds],
        )?;
    } else {
        // A system transfer can fund this predictable PDA before vault creation.
        // Preserve the donation and charge the sponsor only the missing rent.
        let top_up = required_lamports.saturating_sub(current_lamports);
        if top_up > 0 {
            anchor_lang::system_program::transfer(
                CpiContext::new(
                    system_program_info.clone(),
                    anchor_lang::system_program::Transfer {
                        from: sponsor_info.clone(),
                        to: leaderboard_info.clone(),
                    },
                ),
                top_up,
            )?;
        }
        invoke_signed(
            &anchor_lang::solana_program::system_instruction::allocate(
                leaderboard_info.key,
                VaultLeaderboard::SIZE as u64,
            ),
            &[leaderboard_info.clone(), system_program_info.clone()],
            &[signer_seeds],
        )?;
        invoke_signed(
            &anchor_lang::solana_program::system_instruction::assign(
                leaderboard_info.key,
                program_id,
            ),
            &[leaderboard_info.clone(), system_program_info.clone()],
            &[signer_seeds],
        )?;
    }

    let leaderboard = empty_vault_leaderboard(vault_id, bump);
    {
        let mut data = leaderboard_info.try_borrow_mut_data()?;
        leaderboard.try_serialize(&mut &mut data[..])?;
    }
    require_keys_eq!(
        *leaderboard_info.owner,
        *program_id,
        ErrorCode::InvalidActivationSeed
    );
    require!(
        leaderboard_info.data_len() == VaultLeaderboard::SIZE,
        ErrorCode::InvalidActivationSeed
    );
    let decoded = {
        let data = leaderboard_info.try_borrow_data()?;
        VaultLeaderboard::try_deserialize(&mut &data[..])?
    };
    require!(
        decoded.vault_id == vault_id
            && decoded.entries.is_empty()
            && decoded.last_updated == 0
            && decoded.bump == bump,
        ErrorCode::InvalidActivationSeed
    );
    Ok(())
}

pub(crate) fn read_local_legend_u64(data: &[u8], offset: usize) -> Result<u64> {
    let bytes: [u8; 8] = data
        .get(offset..offset + 8)
        .ok_or(ErrorCode::InvalidLocalLegendLayout)?
        .try_into()
        .map_err(|_| ErrorCode::InvalidLocalLegendLayout)?;
    Ok(u64::from_le_bytes(bytes))
}

pub(crate) fn read_local_legend_u32(data: &[u8], offset: usize) -> Result<u32> {
    let bytes: [u8; 4] = data
        .get(offset..offset + 4)
        .ok_or(ErrorCode::InvalidLocalLegendLayout)?
        .try_into()
        .map_err(|_| ErrorCode::InvalidLocalLegendLayout)?;
    Ok(u32::from_le_bytes(bytes))
}

pub(crate) fn inspect_local_legend_layout(
    data: &[u8],
    expected_vault_id: u64,
    expected_bump: u8,
) -> Result<LocalLegendAccountLayout> {
    require!(
        matches!(data.len(), LocalLegend::LEGACY_SIZE | LocalLegend::SIZE),
        ErrorCode::InvalidLocalLegendLayout
    );
    require!(
        data.get(..8) == Some(LocalLegend::DISCRIMINATOR.as_slice()),
        ErrorCode::InvalidLocalLegendLayout
    );

    let vault_id = read_local_legend_u64(data, LocalLegend::VAULT_ID_OFFSET)?;
    require!(
        vault_id == expected_vault_id,
        ErrorCode::LocalLegendVaultMismatch
    );
    require!(
        matches!(data[LocalLegend::IS_ACTIVE_OFFSET], 0 | 1),
        ErrorCode::InvalidLocalLegendLayout
    );

    if data.len() == LocalLegend::SIZE {
        require!(
            matches!(data[LocalLegend::IS_BOOTSTRAP_OFFSET], 0 | 1),
            ErrorCode::InvalidLocalLegendLayout
        );
        require!(
            data[LocalLegend::BUMP_OFFSET] == expected_bump,
            ErrorCode::InvalidLocalLegendBump
        );
        let mut data_ref = data;
        LocalLegend::try_deserialize(&mut data_ref)
            .map_err(|_| error!(ErrorCode::InvalidLocalLegendLayout))?;
        return Ok(LocalLegendAccountLayout::Current);
    }

    let bump = data[LocalLegend::LEGACY_BUMP_OFFSET];
    require!(bump == expected_bump, ErrorCode::InvalidLocalLegendBump);
    let election_period = read_local_legend_u64(data, LocalLegend::ELECTION_PERIOD_OFFSET)?;
    let completions_at_election =
        read_local_legend_u32(data, LocalLegend::COMPLETIONS_AT_ELECTION_OFFSET)?;
    let is_bootstrap = data[LocalLegend::IS_ACTIVE_OFFSET] == 1
        && election_period == 0
        && completions_at_election == 0;

    Ok(LocalLegendAccountLayout::Legacy { is_bootstrap, bump })
}

pub(crate) fn write_local_legend_current_layout(
    data: &mut [u8],
    layout: LocalLegendAccountLayout,
) -> Result<()> {
    require!(
        data.len() == LocalLegend::SIZE,
        ErrorCode::InvalidLocalLegendLayout
    );
    if let LocalLegendAccountLayout::Legacy { is_bootstrap, bump } = layout {
        data[LocalLegend::BUMP_OFFSET] = bump;
        data[LocalLegend::IS_BOOTSTRAP_OFFSET] = u8::from(is_bootstrap);
    }
    Ok(())
}

pub(crate) fn migrate_local_legend_layout<'info>(
    local_legend_info: &AccountInfo<'info>,
    expected_vault_id: u64,
    expected_bump: u8,
    payer_info: &AccountInfo<'info>,
    system_program_info: &AccountInfo<'info>,
) -> Result<LocalLegendMigrationOutcome> {
    let (old_size, layout, is_bootstrap) = {
        let data = local_legend_info.try_borrow_data()?;
        let layout = inspect_local_legend_layout(&data, expected_vault_id, expected_bump)?;
        let is_bootstrap = match layout {
            LocalLegendAccountLayout::Legacy { is_bootstrap, .. } => is_bootstrap,
            LocalLegendAccountLayout::Current => data[LocalLegend::IS_BOOTSTRAP_OFFSET] == 1,
        };
        (data.len(), layout, is_bootstrap)
    };

    if layout == LocalLegendAccountLayout::Current {
        return Ok(LocalLegendMigrationOutcome {
            old_size,
            new_size: old_size,
            is_bootstrap,
            migrated: false,
        });
    }

    let required_lamports = Rent::get()?.minimum_balance(LocalLegend::SIZE);
    let rent_top_up = required_lamports.saturating_sub(local_legend_info.lamports());
    if rent_top_up > 0 {
        anchor_lang::system_program::transfer(
            CpiContext::new(
                system_program_info.clone(),
                anchor_lang::system_program::Transfer {
                    from: payer_info.clone(),
                    to: local_legend_info.clone(),
                },
            ),
            rent_top_up,
        )?;
    }

    local_legend_info.realloc(LocalLegend::SIZE, true)?;
    {
        let mut data = local_legend_info.try_borrow_mut_data()?;
        write_local_legend_current_layout(&mut data, layout)?;
    }
    {
        let data = local_legend_info.try_borrow_data()?;
        require!(
            inspect_local_legend_layout(&data, expected_vault_id, expected_bump)?
                == LocalLegendAccountLayout::Current,
            ErrorCode::InvalidLocalLegendLayout
        );
    }

    Ok(LocalLegendMigrationOutcome {
        old_size,
        new_size: LocalLegend::SIZE,
        is_bootstrap,
        migrated: true,
    })
}

pub(crate) fn next_local_legend_term_end(
    legend: &LocalLegend,
    term_start_epoch: u64,
    current_epoch: u64,
    term_epochs: u64,
) -> Result<u64> {
    require!(term_epochs > 0, ErrorCode::InvalidProtocolParameters);
    require!(
        term_start_epoch <= current_epoch,
        ErrorCode::LocalLegendTermInFuture
    );
    if legend.term_end_epoch > 0 {
        require!(
            term_start_epoch == legend.term_end_epoch,
            ErrorCode::LocalLegendTermOutOfSequence
        );
    } else {
        require!(
            legend.holder == Pubkey::default(),
            ErrorCode::LocalLegendTermOutOfSequence
        );
    }
    term_start_epoch
        .checked_add(term_epochs)
        .ok_or(error!(ErrorCode::Overflow))
}
