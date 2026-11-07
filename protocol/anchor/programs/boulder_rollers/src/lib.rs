#[cfg(not(feature = "no-idl"))]
compile_error!("Deployable builds must disable Anchor IDL instructions with no-idl");

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    bpf_loader_upgradeable::{self, UpgradeableLoaderState},
    program::invoke_signed,
    program_utils::limited_deserialize,
};
use anchor_lang::Discriminator;
use anchor_spl::token::spl_token::instruction::mint_to as spl_mint_to;
use anchor_spl::token::spl_token::state::AccountState;
use anchor_spl::token::{
    self, Burn, FreezeAccount, Mint, MintTo, ThawAccount, Token, TokenAccount, Transfer,
};

mod generated_program_version;
pub mod stage1;
pub mod stage1_claims;
pub mod stage1_claim_storage;
pub mod stage1_governance;
pub mod stage1_sponsor;
pub mod stage1_dung;
mod stage1_providers;
#[cfg(feature = "stage1-devnet")]
mod stage1_devnet;
#[cfg(feature = "stage1-devnet")]
pub use stage1_devnet::*;
#[cfg(all(feature = "stage1-localnet", feature = "stage1-devnet"))]
compile_error!("stage1-localnet and stage1-devnet are mutually exclusive");
#[cfg(feature = "stage1-localnet")]
mod stage1_localnet;
#[cfg(all(feature = "smoke-helpers", not(feature = "stage1-localnet")))]
compile_error!("smoke-helpers compiles only into the isolated stage1-localnet test program");
#[cfg(feature = "smoke-helpers")]
mod smoke_helpers;
#[cfg(feature = "smoke-helpers")]
pub use smoke_helpers::*;
pub use generated_program_version::{
    CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION, PROGRAM_ABI_SHA256, PROGRAM_VERSION_FAMILY,
};
pub use stage1::*;
pub use stage1_claims::*;
pub use stage1_claim_storage::Stage1BatchLeaf;
pub use stage1_governance::*;
pub use stage1_sponsor::*;
pub use stage1_dung::*;
mod constants;
pub use constants::*;
mod events;
pub use events::*;
mod model;
pub use model::*;
mod contexts;
pub use contexts::*;
mod logic;
pub use logic::*;
mod errors;
pub use errors::ErrorCode;

#[cfg(not(feature = "stage1-localnet"))]
declare_id!("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH");
#[cfg(feature = "stage1-localnet")]
declare_id!("5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt");

#[program]
pub mod boulder_rollers {
    use super::*;

    pub fn pledge<'info>(
        ctx: Context<'_, '_, '_, 'info, Stage1Pledge<'info>>,
        deposit_id: u64,
        units: u64,
        lock_weeks: u16,
    ) -> Result<()> {
        stage1::deposit(ctx, deposit_id, units, lock_weeks, false)
    }
    /// An explicit threshold-reaching pledge. Failure rolls back the deposit;
    /// the triggering owner, never a deposit-free crank, receives the title.
    pub fn bond<'info>(
        ctx: Context<'_, '_, '_, 'info, Stage1Pledge<'info>>,
        deposit_id: u64,
        units: u64,
        lock_weeks: u16,
    ) -> Result<()> {
        stage1::deposit(ctx, deposit_id, units, lock_weeks, true)
    }

    pub fn init_city_config(ctx: Context<Stage1InitCity>, season_anchor: i64) -> Result<()> {
        stage1::initialize_city(ctx, season_anchor)
    }
    pub fn configure_asset(ctx: Context<Stage1ConfigureAsset>, enabled: bool) -> Result<()> {
        stage1::configure(ctx, enabled)
    }
    pub fn init_hill_bond(ctx: Context<Stage1InitHill>) -> Result<()> {
        stage1::initialize_hill(ctx)
    }
    pub fn refresh_campaign_lot(ctx: Context<Stage1Refresh>) -> Result<()> {
        stage1::refresh(ctx)
    }
    pub fn materialize_stage1_lot(ctx: Context<Stage1Refresh>) -> Result<()> {
        stage1::materialize_lot(ctx)
    }
    pub fn convert_excluded_pledge(ctx: Context<Stage1Convert>, lock_weeks: u16) -> Result<()> {
        stage1::convert(ctx, lock_weeks)
    }
    // Anchor 0.29 does not feature-filter individual instruction handlers.
    // Network-only dispatch is compiled in separate modules and is absent
    // from the default IDL. Isolated builds generate their own IDLs.
    pub fn localnet_dispatch<'info>(
        program_id: &Pubkey,
        accounts: &'info [AccountInfo<'info>],
        data: &[u8],
    ) -> Result<()> {
        if data.len() < 8 {
            return Err(anchor_lang::error::ErrorCode::InstructionMissing.into());
        }
        #[cfg(feature = "stage1-localnet")]
        {
            stage1_localnet::dispatch(program_id, accounts, data)
        }
        #[cfg(feature = "stage1-devnet")]
        {
            stage1_devnet::dispatch(program_id, accounts, data)
        }
        #[cfg(not(any(feature = "stage1-localnet", feature = "stage1-devnet")))]
        {
            let _ = (program_id, accounts, data);
            Err(anchor_lang::error::ErrorCode::InstructionFallbackNotFound.into())
        }
    }
    pub fn cancel_pledge(ctx: Context<Stage1OwnerLot>) -> Result<()> {
        stage1::cancel(ctx)
    }
    pub fn withdraw_prebond(ctx: Context<Stage1OwnerLot>) -> Result<()> {
        stage1::prebond(ctx)
    }
    pub fn harvest_stage1(ctx: Context<Stage1Harvest>, units: u64) -> Result<()> {
        stage1::harvest(ctx, units)
    }
    pub fn request_withdrawal(
        ctx: Context<Stage1Request>,
        request_id: u64,
        basis: u64,
    ) -> Result<()> {
        stage1::request(ctx, request_id, basis)
    }
    pub fn cancel_withdrawal(ctx: Context<Stage1CancelRequest>) -> Result<()> {
        stage1::cancel_request(ctx)
    }
    pub fn begin_withdrawal(ctx: Context<Stage1BeginWithdrawal>) -> Result<()> {
        stage1::begin(ctx)
    }
    pub fn complete_withdrawal(ctx: Context<Stage1CompleteWithdrawal>) -> Result<()> {
        stage1::complete(ctx)
    }

    pub fn initialize_user(ctx: Context<InitializeUser>) -> Result<()> {
        let user_state = &mut ctx.accounts.user_state;
        user_state.owner = ctx.accounts.payer.key();
        user_state.legacy_cal_snapshot = 0;
        user_state.legacy_cal_earned_today = 0;
        user_state.legacy_last_cal_mint = 0;
        user_state.total_rides = 0;
        user_state.total_tss = 0;
        user_state.bio_score = 1000;
        user_state.bump = ctx.bumps.user_state;
        Ok(())
    }

    /// Initialize program configuration with admin and backend authorities.
    /// This is a one-time setup instruction that can only be called once.
    /// The program upgrade authority becomes the initial admin and can set the backend authority.
    pub fn initialize_program_config(
        ctx: Context<InitializeProgramConfig>,
        backend_authority: Pubkey,
    ) -> Result<()> {
        require_program_upgrade_authority(
            &ctx.accounts.program.to_account_info(),
            &ctx.accounts.program_data.to_account_info(),
            ctx.accounts.admin.key(),
        )?;

        let config = &mut ctx.accounts.program_config;

        require!(!config.initialized, ErrorCode::AlreadyInitialized);

        config.admin_authority = ctx.accounts.admin.key();
        config.backend_authority = backend_authority;
        config.program_version = CURRENT_PROGRAM_VERSION;
        config.initialized = true;
        config.bump = ctx.bumps.program_config;
        config.apply_protocol_parameters(ProtocolParameters::defaults());
        config.vault_creation_usdc = VAULT_CREATION_USDC;
        config.settlement_clock_v2_starts_at = SETTLEMENT_WEEK_V2_ANCHOR;
        config.settlement_clock_version = SETTLEMENT_CLOCK_VERSION_V2;

        emit!(ProgramConfigInitialized {
            admin: config.admin_authority,
            backend: config.backend_authority,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Update program configuration authorities (admin only).
    pub fn update_program_config(
        ctx: Context<UpdateProgramConfig>,
        new_admin: Option<Pubkey>,
        new_backend: Option<Pubkey>,
    ) -> Result<()> {
        let config = &mut ctx.accounts.program_config;

        if let Some(admin) = new_admin {
            config.admin_authority = admin;
        }

        if let Some(backend) = new_backend {
            config.backend_authority = backend;
        }

        emit!(ProgramConfigUpdated {
            admin: config.admin_authority,
            backend: config.backend_authority,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Advance the external client compatibility gate by one exact patch.
    ///
    /// This uses ProgramConfig's stable prefix so a deployed legacy layout can
    /// be versioned before any independent account-layout migration.
    pub fn advance_program_version(
        ctx: Context<AdvanceProgramVersion>,
        expected_current_version: u8,
        new_version: u8,
    ) -> Result<()> {
        let (previous_version, current_version) = advance_program_version_data(
            &ctx.accounts.program_config.to_account_info(),
            ctx.accounts.admin.key(),
            expected_current_version,
            new_version,
        )?;

        emit!(ProgramVersionAdvanced {
            admin: ctx.accounts.admin.key(),
            previous_version,
            current_version,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Update governance-controlled protocol parameters (admin only).
    pub fn update_protocol_parameters(
        ctx: Context<UpdateProgramConfig>,
        parameters: ProtocolParameters,
    ) -> Result<()> {
        require!(parameters.validate(), ErrorCode::InvalidProtocolParameters);

        let config = &mut ctx.accounts.program_config;
        config.apply_protocol_parameters(parameters);

        emit!(ProtocolParametersUpdated {
            vault_creation_dung: config.vault_creation_dung,
            vault_creation_cal: config.vault_creation_cal,
            harvest_fee_bps: config.harvest_fee_bps,
            minter_rights_epochs: config.minter_rights_epochs,
            local_legend_term_epochs: config.local_legend_term_epochs,
            epochs_per_halving: config.epochs_per_halving,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// One-time setup: store CAL and DUNG mint pubkeys and derive auth bumps.
    /// Fails if mints already configured (immutable after set).
    pub fn configure_mints(
        ctx: Context<ConfigureMints>,
        cal_mint: Pubkey,
        dung_mint: Pubkey,
    ) -> Result<()> {
        let config = &mut ctx.accounts.program_config;

        // One-time only: cal_mint must be default (not yet configured)
        require!(
            config.cal_mint == Pubkey::default(),
            ErrorCode::MintsAlreadyConfigured
        );

        config.cal_mint = cal_mint;
        config.dung_mint = dung_mint;

        // Derive and store auth bumps
        let (_, cal_bump) = Pubkey::find_program_address(&[CAL_MINT_AUTH_SEED], ctx.program_id);
        let (_, dung_bump) = Pubkey::find_program_address(&[DUNG_MINT_AUTH_SEED], ctx.program_id);
        config.cal_mint_auth_bump = cal_bump;
        config.dung_mint_auth_bump = dung_bump;

        emit!(MintsConfigured {
            cal_mint,
            dung_mint,
            cal_mint_auth_bump: cal_bump,
            dung_mint_auth_bump: dung_bump,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Configure POL and treasury DUNG token accounts (admin-only).
    /// These are validated during distribute_epoch_rewards to prevent redirection.
    pub fn configure_treasury_accounts(
        ctx: Context<ConfigureTreasuryAccounts>,
        pol_token_account: Pubkey,
        treasury_token_account: Pubkey,
    ) -> Result<()> {
        let config = &mut ctx.accounts.program_config;
        config.pol_token_account = pol_token_account;
        config.treasury_token_account = treasury_token_account;

        emit!(TreasuryAccountsConfigured {
            pol_token_account,
            treasury_token_account,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Configure canonical USDC payment rail for vault creation (admin-only).
    pub fn configure_usdc_payment(
        ctx: Context<ConfigureUsdcPayment>,
        vault_creation_usdc: u64,
    ) -> Result<()> {
        require!(vault_creation_usdc > 0, ErrorCode::InvalidAmount);

        let config = &mut ctx.accounts.program_config;
        config.usdc_mint = ctx.accounts.usdc_mint.key();
        config.usdc_treasury_token_account = ctx.accounts.usdc_treasury_token_account.key();
        config.vault_creation_usdc = vault_creation_usdc;

        emit!(UsdcPaymentConfigured {
            usdc_mint: config.usdc_mint,
            usdc_treasury_token_account: config.usdc_treasury_token_account,
            vault_creation_usdc,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Initialize a vault CAL escrow ATA (owned by vault PDA).
    /// Required before SPL CAL staking in a vault.
    pub fn initialize_vault_cal_escrow(_ctx: Context<InitializeVaultCalEscrow>) -> Result<()> {
        // ATA is initialized by Anchor constraints, nothing else to do
        Ok(())
    }

    /// Record a canonical ride attestation and update the rider's soulbound effort state.
    pub fn record_ride(
        ctx: Context<RecordRide>,
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
        climbs_crossed: u16,
    ) -> Result<()> {
        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        require_valid_ride_timestamps(started_at, completed_at, clock.unix_timestamp)?;
        require_ride_economics_within_bounds(started_at, completed_at, total_tss, cal_earned)?;
        let economic_epoch = settlement_clock.week_at(completed_at)?;
        let ride_attestation = &mut ctx.accounts.ride_attestation;
        ride_attestation.rider = ctx.accounts.rider.key();
        ride_attestation.ride_hash = ride_hash;
        ride_attestation.attestation_commitment = attestation_commitment;
        ride_attestation.parser_version = parser_version;
        ride_attestation.source_kind = source_kind;
        ride_attestation.completed_at = completed_at;
        ride_attestation.started_at = started_at;
        ride_attestation.total_tss = total_tss;
        ride_attestation.total_distance_m = total_distance_m;
        ride_attestation.total_vert_m = total_vert_m;
        ride_attestation.cal_earned = cal_earned;
        ride_attestation.climbs_crossed = climbs_crossed;
        ride_attestation.attester = ctx.accounts.authority.key();
        ride_attestation.settled_at = clock.unix_timestamp;
        ride_attestation.settled_slot = clock.slot;
        ride_attestation.economic_epoch = economic_epoch;
        ride_attestation.finalized =
            clock.unix_timestamp >= settlement_clock.week_finalization_time(economic_epoch)?;
        ride_attestation.bump = ctx.bumps.ride_attestation;

        let rider_soul = &mut ctx.accounts.rider_soul;
        if rider_soul.rider == Pubkey::default() {
            rider_soul.rider = ctx.accounts.rider.key();
            rider_soul.created_at = completed_at;
            rider_soul.total_rides = 0;
            rider_soul.total_tss = 0;
            rider_soul.total_distance_m = 0;
            rider_soul.total_vert_m = 0;
            rider_soul.total_cal_earned = 0;
            rider_soul.archetype = 0;
            rider_soul.bio_score = 0;
            rider_soul.climb_card = None;
            rider_soul.steady_card = None;
            rider_soul.explorer_card = None;
            rider_soul.bump = ctx.bumps.rider_soul;
        }

        rider_soul.total_rides = rider_soul
            .total_rides
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.total_tss = rider_soul
            .total_tss
            .checked_add(total_tss as u64)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.total_distance_m = rider_soul
            .total_distance_m
            .checked_add(total_distance_m as u64)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.total_vert_m = rider_soul
            .total_vert_m
            .checked_add(total_vert_m as u64)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.total_cal_earned = rider_soul
            .total_cal_earned
            .checked_add(cal_earned)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.bio_score = rider_soul
            .bio_score
            .checked_add(total_tss as u64)
            .ok_or(ErrorCode::Overflow)?;

        emit!(RideAttestationRecorded {
            rider: ride_attestation.rider,
            ride_hash,
            parser_version,
            economic_epoch,
            cal_earned,
            completed_at,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Receipt-protected CAL mint tied to a canonical ride attestation.
    pub fn credit_cal(ctx: Context<CreditCal>, amount: u64) -> Result<()> {
        require!(amount > 0, ErrorCode::InvalidAmount);
        require!(
            ctx.accounts.ride_attestation.rider == ctx.accounts.rider.key(),
            ErrorCode::InvalidRideAttestation
        );
        require!(
            ctx.accounts.ride_attestation.cal_earned == amount,
            ErrorCode::AttestationAmountMismatch
        );
        require_accepted_ride_timestamps(
            ctx.accounts.ride_attestation.started_at,
            ctx.accounts.ride_attestation.completed_at,
            ctx.accounts.ride_attestation.settled_at,
        )?;
        let clock = Clock::get()?;

        let receipt = &mut ctx.accounts.cal_mint_receipt;
        receipt.ride_attestation = ctx.accounts.ride_attestation.key();
        receipt.rider = ctx.accounts.rider.key();
        receipt.amount = amount;
        receipt.bump = ctx.bumps.cal_mint_receipt;

        let config = &ctx.accounts.program_config;
        let seeds = &[CAL_MINT_AUTH_SEED, &[config.cal_mint_auth_bump]];
        let signer = &[&seeds[..]];

        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.cal_mint.to_account_info(),
                    to: ctx.accounts.destination.to_account_info(),
                    authority: ctx.accounts.cal_mint_auth.to_account_info(),
                },
                signer,
            ),
            amount,
        )?;

        emit!(CalCredited {
            rider: ctx.accounts.rider.key(),
            ride_attestation: ctx.accounts.ride_attestation.key(),
            amount,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Create the immutable child authority for one eligible provisional ride.
    /// This authorizes later receipts but does not itself mint or credit tribute.
    #[allow(clippy::too_many_arguments)]
    pub fn authorize_held_ride_release(
        ctx: Context<AuthorizeHeldRideRelease>,
        threshold_authority_id: [u8; 16],
        threshold_authority_commitment: [u8; 32],
        threshold_effective_at: i64,
        threshold_w: u16,
        threshold_policy_version: u8,
        economic_tss: u32,
        cal_earned: u64,
        cal_tribute_budget: u64,
        release_plan_hash: [u8; 32],
    ) -> Result<()> {
        let ride_attestation = &ctx.accounts.ride_attestation;
        require!(
            ride_attestation.rider == ctx.accounts.rider.key(),
            ErrorCode::InvalidRideAttestation
        );
        require!(
            ride_attestation.cal_earned == 0 && ride_attestation.total_tss == 0,
            ErrorCode::HeldRideParentHasEconomics
        );
        require_accepted_ride_timestamps(
            ride_attestation.started_at,
            ride_attestation.completed_at,
            ride_attestation.settled_at,
        )?;
        require_ride_economics_within_bounds(
            ride_attestation.started_at,
            ride_attestation.completed_at,
            economic_tss,
            cal_earned,
        )?;
        require!(
            threshold_authority_id != [0; 16]
                && threshold_authority_commitment != [0; 32]
                && release_plan_hash != [0; 32],
            ErrorCode::InvalidHeldRideReleaseAuthority
        );
        require!(
            (MIN_HELD_RIDE_THRESHOLD_W..=MAX_HELD_RIDE_THRESHOLD_W).contains(&threshold_w),
            ErrorCode::InvalidHeldRideThreshold
        );
        require!(
            threshold_policy_version == HELD_RIDE_RELEASE_POLICY_VERSION,
            ErrorCode::InvalidHeldRideReleasePolicy
        );
        let tribute_ceiling =
            held_ride_release_tribute_budget(ride_attestation.cal_earned, cal_earned)?;
        require!(
            cal_tribute_budget <= tribute_ceiling,
            ErrorCode::InvalidHeldRideTributeBudget
        );

        let clock = Clock::get()?;
        require_valid_held_ride_release_window(
            ride_attestation.settled_at,
            threshold_effective_at,
            clock.unix_timestamp,
        )?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let release_settlement_week = settlement_clock.week_at(clock.unix_timestamp)?;

        let release = &mut ctx.accounts.release_authority;
        release.ride_attestation = ride_attestation.key();
        release.rider = ctx.accounts.rider.key();
        release.threshold_authority_id = threshold_authority_id;
        release.threshold_authority_commitment = threshold_authority_commitment;
        release.threshold_effective_at = threshold_effective_at;
        release.threshold_w = threshold_w;
        release.threshold_policy_version = threshold_policy_version;
        release.economic_tss = economic_tss;
        release.cal_earned = cal_earned;
        release.cal_tribute_budget = cal_tribute_budget;
        release.release_plan_hash = release_plan_hash;
        release.released_at = clock.unix_timestamp;
        release.released_slot = clock.slot;
        release.release_settlement_week = release_settlement_week;
        release.attester = ctx.accounts.authority.key();
        release.bump = ctx.bumps.release_authority;

        emit!(HeldRideReleaseAuthorized {
            release_authority: release.key(),
            ride_attestation: ride_attestation.key(),
            rider: release.rider,
            threshold_authority_id,
            threshold_authority_commitment,
            threshold_effective_at,
            threshold_w,
            threshold_policy_version,
            economic_tss,
            cal_earned,
            cal_tribute_budget,
            release_plan_hash,
            release_settlement_week,
            released_slot: clock.slot,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Mint the exact CAL authorized by a held-ride release and apply its
    /// previously deferred effort totals to RiderSoul exactly once.
    pub fn credit_released_cal(ctx: Context<CreditReleasedCal>) -> Result<()> {
        let ride_attestation = &ctx.accounts.ride_attestation;
        let release = &ctx.accounts.release_authority;
        require!(
            ride_attestation.rider == ctx.accounts.rider.key()
                && release.rider == ctx.accounts.rider.key()
                && release.ride_attestation == ride_attestation.key(),
            ErrorCode::InvalidHeldRideReleaseAuthority
        );
        require!(
            ride_attestation.cal_earned == 0 && ride_attestation.total_tss == 0,
            ErrorCode::HeldRideParentHasEconomics
        );
        require!(release.cal_earned > 0, ErrorCode::InvalidAmount);
        require_accepted_ride_timestamps(
            ride_attestation.started_at,
            ride_attestation.completed_at,
            ride_attestation.settled_at,
        )?;
        let tribute_ceiling =
            held_ride_release_tribute_budget(ride_attestation.cal_earned, release.cal_earned)?;
        require!(
            release.cal_tribute_budget <= tribute_ceiling,
            ErrorCode::InvalidHeldRideTributeBudget
        );

        let receipt = &mut ctx.accounts.cal_mint_receipt;
        receipt.ride_attestation = ride_attestation.key();
        receipt.release_authority = release.key();
        receipt.rider = ctx.accounts.rider.key();
        receipt.amount = release.cal_earned;
        receipt.release_settlement_week = release.release_settlement_week;
        receipt.bump = ctx.bumps.cal_mint_receipt;

        let rider_soul = &mut ctx.accounts.rider_soul;
        require!(
            rider_soul.rider == ctx.accounts.rider.key(),
            ErrorCode::InvalidRideAttestation
        );
        rider_soul.total_tss = rider_soul
            .total_tss
            .checked_add(u64::from(release.economic_tss))
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.total_cal_earned = rider_soul
            .total_cal_earned
            .checked_add(release.cal_earned)
            .ok_or(ErrorCode::Overflow)?;
        rider_soul.bio_score = rider_soul
            .bio_score
            .checked_add(u64::from(release.economic_tss))
            .ok_or(ErrorCode::Overflow)?;

        let config = &ctx.accounts.program_config;
        let seeds = &[CAL_MINT_AUTH_SEED, &[config.cal_mint_auth_bump]];
        let signer = &[&seeds[..]];
        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.cal_mint.to_account_info(),
                    to: ctx.accounts.destination.to_account_info(),
                    authority: ctx.accounts.cal_mint_auth.to_account_info(),
                },
                signer,
            ),
            release.cal_earned,
        )?;

        let clock = Clock::get()?;
        emit!(ReleasedCalCredited {
            cal_mint_receipt: receipt.key(),
            release_authority: release.key(),
            ride_attestation: ride_attestation.key(),
            rider: ctx.accounts.rider.key(),
            economic_tss: release.economic_tss,
            amount: release.cal_earned,
            release_settlement_week: release.release_settlement_week,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Tribute-bound climb completion anchored to a ride attestation.
    /// The first remaining account must be the writable RideTributeBudget PDA.
    pub fn record_climb_completion_v2<'info>(
        ctx: Context<'_, '_, 'info, 'info, RecordClimbCompletionV2<'info>>,
        completion_time_s: u32,
        cal_tribute: u64,
        completion_evidence_hash: [u8; 32],
    ) -> Result<()> {
        require!(completion_time_s > 0, ErrorCode::InvalidCompletionTime);
        require!(
            completion_evidence_hash != [0; 32],
            ErrorCode::InvalidEvidenceHash
        );
        require!(
            ctx.accounts.ride_attestation.rider == ctx.accounts.rider.key(),
            ErrorCode::InvalidRideAttestation
        );
        let expected_evidence_hash = build_climb_completion_evidence_v2(
            &ctx.accounts.ride_attestation.key(),
            &ctx.accounts.vault.key(),
            completion_time_s,
            cal_tribute,
        );
        require!(
            completion_evidence_hash == expected_evidence_hash,
            ErrorCode::CompletionEvidenceMismatch
        );

        require_accepted_ride_timestamps(
            ctx.accounts.ride_attestation.started_at,
            ctx.accounts.ride_attestation.completed_at,
            ctx.accounts.ride_attestation.settled_at,
        )?;
        credit_ride_tribute_budget(
            ctx.remaining_accounts
                .first()
                .ok_or(ErrorCode::InvalidRideTributeBudget)?,
            &ctx.accounts.authority.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            ctx.program_id,
            ctx.accounts.ride_attestation.key(),
            ride_cal_tribute_budget(ctx.accounts.ride_attestation.cal_earned)?,
            cal_tribute,
        )?;

        let clock = Clock::get()?;
        let vault = &mut ctx.accounts.vault;
        let completion = &mut ctx.accounts.vault_completion;
        let leaderboard = &mut ctx.accounts.vault_leaderboard;
        let completed_at = ctx.accounts.ride_attestation.completed_at;
        let ride_epoch = ctx.accounts.ride_attestation.economic_epoch;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;

        let receipt = &mut ctx.accounts.climb_completion_receipt;
        receipt.ride_attestation = ctx.accounts.ride_attestation.key();
        receipt.vault = vault.key();
        receipt.evidence_version = 2;
        receipt.cal_tributed = cal_tribute;
        receipt.completion_evidence_hash = completion_evidence_hash;
        receipt.bump = ctx.bumps.climb_completion_receipt;

        vault.maybe_advance_empty_settlement_week(&settlement_clock, clock.unix_timestamp)?;
        let credited_settlement_week = vault.open_settlement_week;

        if completion.user == Pubkey::default() {
            completion.user = ctx.accounts.rider.key();
            completion.vault_id = vault.id;
            completion.completions = 0;
            completion.best_time_s = u32::MAX;
            completion.total_cal_tributed = 0;
            completion.bump = ctx.bumps.vault_completion;
        }

        completion.completions = completion
            .completions
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        completion.note_completed_at(completed_at);

        let is_personal_best = completion_time_s < completion.best_time_s;
        if is_personal_best {
            completion.best_time_s = completion_time_s;
        }

        let is_new_kom = vault.kom_time_s == 0 || completion_time_s < vault.kom_time_s;
        if is_new_kom {
            vault.kom_holder = ctx.accounts.rider.key();
            vault.kom_time_s = completion_time_s;
            vault.kom_set_epoch = ride_epoch;
        }

        if leaderboard.vault_id == 0 {
            leaderboard.vault_id = vault.id;
        }
        leaderboard.update_entry(ctx.accounts.rider.key(), completion_time_s, completed_at);

        if cal_tribute > 0 {
            completion.total_cal_tributed = completion
                .total_cal_tributed
                .checked_add(cal_tribute)
                .ok_or(ErrorCode::Overflow)?;

            vault.total_cal_burned = vault
                .total_cal_burned
                .checked_add(cal_tribute)
                .ok_or(ErrorCode::Overflow)?;

            vault.credit_lifetime_tribute(cal_tribute)?;
        }

        vault.total_completions = vault
            .total_completions
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;

        emit!(ClimbCompletedV2 {
            evidence_version: 2,
            vault_id: vault.id,
            ride_attestation: ctx.accounts.ride_attestation.key(),
            rider: ctx.accounts.rider.key(),
            time_s: completion_time_s,
            cal_tributed: cal_tribute,
            completion_evidence_hash,
            is_new_kom,
            completed_at,
            timestamp: clock.unix_timestamp,
        });

        emit!(ClimbCompletionFlowAssignedV2 {
            evidence_version: 2,
            vault_id: vault.id,
            ride_attestation: ctx.accounts.ride_attestation.key(),
            completion_evidence_hash,
            credited_settlement_week,
            cal_tributed: cal_tribute,
            timestamp: clock.unix_timestamp,
        });

        emit!(VaultCompletedV2 {
            evidence_version: 2,
            vault_id: vault.id,
            user: ctx.accounts.rider.key(),
            time_s: completion_time_s,
            cal_tributed: cal_tribute,
            completion_evidence_hash,
            is_new_kom,
            timestamp: completed_at,
        });

        Ok(())
    }

    /// Apply one release-bound climb completion. Sporting truth retains the
    /// parent's original completion time; tribute enters the Vault's current
    /// oldest open Settlement Flow.
    /// The first remaining account must be the writable released budget PDA.
    pub fn record_released_climb_completion<'info>(
        ctx: Context<'_, '_, 'info, 'info, RecordReleasedClimbCompletion<'info>>,
        completion_time_s: u32,
        cal_tribute: u64,
        completion_evidence_hash: [u8; 32],
    ) -> Result<()> {
        require!(completion_time_s > 0, ErrorCode::InvalidCompletionTime);
        require!(
            completion_evidence_hash != [0; 32],
            ErrorCode::InvalidEvidenceHash
        );
        let ride_attestation = &ctx.accounts.ride_attestation;
        let release = &ctx.accounts.release_authority;
        require!(
            ride_attestation.rider == ctx.accounts.rider.key()
                && release.rider == ctx.accounts.rider.key()
                && release.ride_attestation == ride_attestation.key(),
            ErrorCode::InvalidHeldRideReleaseAuthority
        );
        require!(
            ride_attestation.cal_earned == 0 && ride_attestation.total_tss == 0,
            ErrorCode::HeldRideParentHasEconomics
        );
        let tribute_ceiling =
            held_ride_release_tribute_budget(ride_attestation.cal_earned, release.cal_earned)?;
        require!(
            release.cal_tribute_budget <= tribute_ceiling,
            ErrorCode::InvalidHeldRideTributeBudget
        );
        let expected_evidence_hash = build_released_climb_completion_evidence_v3(
            &release.key(),
            &ride_attestation.key(),
            &ctx.accounts.vault.key(),
            completion_time_s,
            cal_tribute,
        );
        require!(
            completion_evidence_hash == expected_evidence_hash,
            ErrorCode::ReleasedCompletionEvidenceMismatch
        );
        require_accepted_ride_timestamps(
            ride_attestation.started_at,
            ride_attestation.completed_at,
            ride_attestation.settled_at,
        )?;
        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        ctx.accounts
            .vault
            .maybe_advance_empty_settlement_week(&settlement_clock, clock.unix_timestamp)?;
        require_held_release_settlement_week(
            ctx.accounts.vault.open_settlement_week,
            release.release_settlement_week,
        )?;
        let credited_settlement_week = release.release_settlement_week;

        credit_held_ride_tribute_budget(
            ctx.remaining_accounts
                .first()
                .ok_or(ErrorCode::InvalidHeldRideTributeBudget)?,
            &ctx.accounts.authority.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            ctx.program_id,
            ride_attestation.key(),
            release.key(),
            release.cal_tribute_budget,
            cal_tribute,
        )?;

        let vault = &mut ctx.accounts.vault;
        let completion = &mut ctx.accounts.vault_completion;
        let leaderboard = &mut ctx.accounts.vault_leaderboard;
        let completed_at = ride_attestation.completed_at;
        let ride_epoch = ride_attestation.economic_epoch;
        let receipt = &mut ctx.accounts.climb_completion_receipt;
        receipt.ride_attestation = ride_attestation.key();
        receipt.release_authority = release.key();
        receipt.vault = vault.key();
        receipt.evidence_version = 3;
        receipt.cal_tributed = cal_tribute;
        receipt.completion_evidence_hash = completion_evidence_hash;
        receipt.credited_settlement_week = credited_settlement_week;
        receipt.bump = ctx.bumps.climb_completion_receipt;

        if completion.user == Pubkey::default() {
            completion.user = ctx.accounts.rider.key();
            completion.vault_id = vault.id;
            completion.completions = 0;
            completion.best_time_s = u32::MAX;
            completion.total_cal_tributed = 0;
            completion.bump = ctx.bumps.vault_completion;
        }

        completion.completions = completion
            .completions
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        completion.note_completed_at(completed_at);

        let is_personal_best = completion_time_s < completion.best_time_s;
        if is_personal_best {
            completion.best_time_s = completion_time_s;
        }

        let is_new_kom = vault.kom_time_s == 0 || completion_time_s < vault.kom_time_s;
        if is_new_kom {
            vault.kom_holder = ctx.accounts.rider.key();
            vault.kom_time_s = completion_time_s;
            vault.kom_set_epoch = ride_epoch;
        }

        if leaderboard.vault_id == 0 {
            leaderboard.vault_id = vault.id;
        }
        leaderboard.update_entry(ctx.accounts.rider.key(), completion_time_s, completed_at);

        if cal_tribute > 0 {
            completion.total_cal_tributed = completion
                .total_cal_tributed
                .checked_add(cal_tribute)
                .ok_or(ErrorCode::Overflow)?;
            vault.total_cal_burned = vault
                .total_cal_burned
                .checked_add(cal_tribute)
                .ok_or(ErrorCode::Overflow)?;
            vault.credit_lifetime_tribute(cal_tribute)?;
        }

        vault.total_completions = vault
            .total_completions
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;

        emit!(ReleasedClimbCompleted {
            evidence_version: 3,
            climb_completion_receipt: receipt.key(),
            release_authority: release.key(),
            vault_id: vault.id,
            ride_attestation: ride_attestation.key(),
            rider: ctx.accounts.rider.key(),
            time_s: completion_time_s,
            cal_tributed: cal_tribute,
            completion_evidence_hash,
            is_new_kom,
            completed_at,
            timestamp: clock.unix_timestamp,
        });
        emit!(ReleasedClimbCompletionFlowAssigned {
            evidence_version: 3,
            release_authority: release.key(),
            vault_id: vault.id,
            ride_attestation: ride_attestation.key(),
            completion_evidence_hash,
            credited_settlement_week,
            cal_tributed: cal_tribute,
            timestamp: clock.unix_timestamp,
        });
        emit!(ReleasedVaultCompleted {
            evidence_version: 3,
            release_authority: release.key(),
            vault_id: vault.id,
            user: ctx.accounts.rider.key(),
            time_s: completion_time_s,
            cal_tributed: cal_tribute,
            completion_evidence_hash,
            is_new_kom,
            timestamp: completed_at,
        });

        Ok(())
    }

    /// Read-only integrity check for the ride-scoped tribute conservation ledger.
    pub fn verify_ride_tribute_budget(ctx: Context<VerifyRideTributeBudget>) -> Result<()> {
        require!(
            ctx.accounts.ride_tribute_budget.cal_budget
                == ride_cal_tribute_budget(ctx.accounts.ride_attestation.cal_earned)?,
            ErrorCode::InvalidRideTributeBudget
        );
        Ok(())
    }

    /// Read-only integrity check for a release-scoped tribute conservation ledger.
    pub fn verify_released_ride_tribute_budget(
        ctx: Context<VerifyReleasedRideTributeBudget>,
    ) -> Result<()> {
        require!(
            ctx.accounts.ride_attestation.cal_earned == 0
                && ctx.accounts.ride_attestation.total_tss == 0,
            ErrorCode::HeldRideParentHasEconomics
        );
        let tribute_ceiling = held_ride_release_tribute_budget(
            ctx.accounts.ride_attestation.cal_earned,
            ctx.accounts.release_authority.cal_earned,
        )?;
        require!(
            ctx.accounts.release_authority.cal_tribute_budget <= tribute_ceiling
                && ctx.accounts.released_ride_tribute_budget.cal_budget
                    == ctx.accounts.release_authority.cal_tribute_budget,
            ErrorCode::InvalidHeldRideTributeBudget
        );
        Ok(())
    }

    // =====================================================
    // BEETLE CARD INSTRUCTIONS
    // =====================================================

    /// Initialize a new Beetle Card (soulbound, one per type/scope combo)
    /// Anyone can create their own card, but cards are non-transferable
    pub fn initialize_beetle_card(
        ctx: Context<InitializeBeetleCard>,
        card_type: CardType,
        scope_id: [u8; 32],
    ) -> Result<()> {
        // Validate scope based on card type
        match card_type {
            CardType::Climb => {
                // Climb cards must have non-zero scope (arena ID)
                require!(scope_id != GLOBAL_SCOPE, ErrorCode::InvalidScope);
            }
            CardType::Steady | CardType::Explorer => {
                // Steady and Explorer cards must use global scope
                require!(scope_id == GLOBAL_SCOPE, ErrorCode::InvalidScope);
            }
        }

        let clock = Clock::get()?;
        let card = &mut ctx.accounts.beetle_card;

        card.owner = ctx.accounts.owner.key();
        card.card_type = card_type;
        card.scope_id = scope_id;
        card.score = 0;
        card.level = 0;
        card.patterns_scored = 0;
        card.last_updated = clock.unix_timestamp;
        card.created_at = clock.unix_timestamp;
        card.bump = ctx.bumps.beetle_card;

        emit!(BeetleCardCreated {
            owner: card.owner,
            card_type: card_type as u8,
            scope_id,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Increment a Beetle Card's score after scoring a pattern
    /// This is called by the backend after successful pattern scoring
    /// The authority must be a trusted scoring authority
    ///
    /// HYBRID MODEL: Score tracks effort (eligibility), but does NOT auto-update level.
    /// Level only changes via upgrade_beetle_card instruction (burning DUNG).
    /// The event shows eligible_level to indicate what level the user CAN claim.
    pub fn increment_beetle_score(
        ctx: Context<IncrementBeetleScore>,
        delta_score: u64,
    ) -> Result<()> {
        require!(delta_score > 0, ErrorCode::InvalidScore);

        let clock = Clock::get()?;
        let card = &mut ctx.accounts.beetle_card;

        card.score = card
            .score
            .checked_add(delta_score)
            .ok_or(ErrorCode::Overflow)?;
        card.patterns_scored = card
            .patterns_scored
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        // NOTE: Level is NOT auto-updated in HYBRID model
        // User must call upgrade_beetle_card with DUNG to claim level
        card.last_updated = clock.unix_timestamp;

        // Calculate eligible level for event (what user CAN claim, not what they have)
        let eligible_level = BeetleCard::calculate_level(card.score);
        let can_upgrade = eligible_level > card.level;

        emit!(BeetleScoreIncremented {
            owner: card.owner,
            card_type: card.card_type as u8,
            scope_id: card.scope_id,
            delta_score,
            new_score: card.score,
            new_level: card.level,   // Current claimed level (unchanged)
            leveled_up: can_upgrade, // True if eligible for higher level than current
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Read-only instruction to get card stats (useful for indexing)
    pub fn get_beetle_card_stats(ctx: Context<GetBeetleCardStats>) -> Result<()> {
        let card = &ctx.accounts.beetle_card;

        emit!(BeetleCardStats {
            owner: card.owner,
            card_type: card.card_type as u8,
            scope_id: card.scope_id,
            score: card.score,
            level: card.level,
            patterns_scored: card.patterns_scored,
            created_at: card.created_at,
            last_updated: card.last_updated,
        });

        Ok(())
    }

    /// Upgrade a Beetle Card to the next level (HYBRID model)
    ///
    /// HYBRID model requirements:
    /// 1. User must have sufficient SCORE (effort threshold) to unlock the level
    /// 2. User must burn DUNG to claim the level
    ///
    /// Formula: 25 * 2^(current_level - 1) DUNG per level
    /// Level 0->1: 25 DUNG, Level 1->2: 25 DUNG, Level 2->3: 50 DUNG, etc.
    ///
    /// Special gates (verified by backend_authority before this instruction is signed):
    /// - Level 5: 50km/week badge
    /// - Level 7: 10 segment challenges
    /// - Level 8: Top 10 any segment
    /// - Level 9: 30-day streak
    /// - Level 10: ELITE GATE (5 KOMs, 4.0 w/kg, 60-day streak, 50K TSS)
    pub fn upgrade_beetle_card(ctx: Context<UpgradeBeetleCard>) -> Result<()> {
        let card = &mut ctx.accounts.beetle_card;
        let clock = Clock::get()?;

        // Check not at max level
        require!(card.level < BEETLE_MAX_LEVEL, ErrorCode::MaxLevelReached);

        let next_level = card.level + 1;

        // HYBRID MODEL: Check score threshold (effort eligibility)
        // User must have earned enough score through effort before they can upgrade
        let required_score = LEVEL_THRESHOLDS[(next_level - 1) as usize];
        require!(
            card.score >= required_score,
            ErrorCode::InsufficientScoreForUpgrade
        );

        let config = &ctx.accounts.program_config;
        require!(
            ctx.accounts.dung_mint.key() == config.dung_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.backend_authority.key() == config.backend_authority,
            ErrorCode::UnauthorizedBackend
        );

        // Calculate upgrade cost: 25 * 2^(level) for level 0, 25 * 2^(level-1) for level 1+
        // This gives: L0->1: 25, L1->2: 25, L2->3: 50, L3->4: 100, etc.
        let upgrade_cost = if card.level == 0 {
            BEETLE_BASE_UPGRADE_COST
        } else {
            BEETLE_BASE_UPGRADE_COST
                .checked_mul(2u64.pow((card.level - 1) as u32))
                .ok_or(ErrorCode::Overflow)?
        };

        // Burn DUNG tokens from user
        token::burn(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: ctx.accounts.dung_mint.to_account_info(),
                    from: ctx.accounts.owner_dung_account.to_account_info(),
                    authority: ctx.accounts.owner.to_account_info(),
                },
            ),
            upgrade_cost,
        )?;
        ctx.accounts
            .dung_mint_state
            .record_protocol_burn(upgrade_cost)?;
        let total_protocol_burned = ctx.accounts.dung_mint_state.total_burned;

        let old_level = card.level;
        card.level = card.level.checked_add(1).ok_or(ErrorCode::Overflow)?;
        card.last_updated = clock.unix_timestamp;

        emit!(BeetleCardUpgraded {
            owner: card.owner,
            card_type: card.card_type as u8,
            scope_id: card.scope_id,
            old_level,
            new_level: card.level,
            dung_burned: upgrade_cost,
            timestamp: clock.unix_timestamp,
        });
        emit!(DungBurned {
            actor: card.owner,
            amount: upgrade_cost,
            burn_kind: DUNG_BURN_KIND_BEETLE_UPGRADE,
            total_protocol_burned,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Calculate the DUNG cost to upgrade from current level to next level
    /// Formula: 25 * 2^(level-1) DUNG (with level 0->1 being 25 DUNG)
    /// Returns the cost with 9 decimals (e.g., 25_000_000_000 for 25 DUNG)
    pub fn get_upgrade_cost(ctx: Context<GetBeetleCardStats>) -> Result<()> {
        let card = &ctx.accounts.beetle_card;

        let upgrade_cost = if card.level >= BEETLE_MAX_LEVEL {
            0 // Max level, no upgrade possible
        } else if card.level == 0 {
            BEETLE_BASE_UPGRADE_COST
        } else {
            BEETLE_BASE_UPGRADE_COST
                .checked_mul(2u64.pow((card.level - 1) as u32))
                .unwrap_or(0)
        };

        emit!(BeetleUpgradeCost {
            owner: card.owner,
            card_type: card.card_type as u8,
            current_level: card.level,
            upgrade_cost,
            can_upgrade: card.level < BEETLE_MAX_LEVEL,
        });

        Ok(())
    }

    // =====================================================
    // VAULT INSTRUCTIONS
    // =====================================================

    /// Register one ratified canon Climb. The admin signature is the on-chain
    /// attestation that the supplied identity came from the curated registry.
    /// All committed identity fields are immutable after this instruction.
    pub fn register_ratified_climb(
        ctx: Context<RegisterRatifiedClimb>,
        args: RegisterRatifiedClimbArgs,
    ) -> Result<()> {
        stage1_governance::authorize_registrar(&ctx.accounts.program_config, ctx.accounts.admin.key(), ctx.remaining_accounts)?;
        require!(
            args.name.len() >= 3 && args.name.len() <= 64,
            ErrorCode::InvalidName
        );
        require!(args.vert_m > 0, ErrorCode::InvalidElevation);
        require!(args.distance_m > 0, ErrorCode::InvalidDistance);

        let canon_commitment = build_canon_commitment_v1(
            args.canon_id,
            args.canon_version,
            args.canonical_profile_hash,
        )?;
        let commitment_hash = canon_commitment_hash(&canon_commitment);
        require!(
            commitment_hash == args.commitment_hash,
            ErrorCode::InvalidCanonCommitment
        );

        let predecessor_lineage = ctx
            .accounts
            .predecessor_climb
            .as_ref()
            .map(|predecessor| (predecessor.canon_id, predecessor.canon_version));
        if let Some(predecessor) = ctx.accounts.predecessor_climb.as_ref() {
            require!(
                predecessor.successor_climb == Pubkey::default(),
                ErrorCode::CanonSuccessorAlreadyRegistered
            );
        }
        validate_climb_lineage(
            args.canon_id,
            args.canon_version,
            args.record_continuity_policy,
            predecessor_lineage,
        )?;

        let climb_key = ctx.accounts.climb.key();
        let predecessor_key = if let Some(predecessor) = ctx.accounts.predecessor_climb.as_mut() {
            let expected_commitment = build_canon_commitment_v1(
                predecessor.canon_id,
                predecessor.canon_version,
                predecessor.canonical_profile_hash,
            )?;
            require!(
                predecessor.canon_commitment == expected_commitment
                    && predecessor.commitment_hash
                        == canon_commitment_hash(&predecessor.canon_commitment),
                ErrorCode::InvalidCanonCommitment
            );
            let (expected_predecessor, _) = Pubkey::find_program_address(
                &[CLIMB_SEED, predecessor.commitment_hash.as_ref()],
                ctx.program_id,
            );
            require_keys_eq!(
                predecessor.key(),
                expected_predecessor,
                ErrorCode::InvalidClimb
            );
            link_climb_successor(predecessor, climb_key)?;
            predecessor.key()
        } else {
            Pubkey::default()
        };

        let mut name = [0; 64];
        name[..args.name.len()].copy_from_slice(args.name.as_bytes());
        let clock = Clock::get()?;
        let climb = &mut ctx.accounts.climb;
        climb.canon_commitment = canon_commitment;
        climb.commitment_hash = commitment_hash;
        climb.canon_id = args.canon_id;
        climb.canon_version = args.canon_version;
        climb.canonical_profile_hash = args.canonical_profile_hash;
        climb.predecessor_climb = predecessor_key;
        climb.successor_climb = Pubkey::default();
        climb.record_continuity_policy = args.record_continuity_policy;
        climb.vault = Pubkey::default();
        climb.name = name;
        climb.vert_m = args.vert_m;
        climb.distance_m = args.distance_m;
        climb.avg_gradient_pct = args.avg_gradient_pct;
        climb.registered_at = clock.unix_timestamp;
        climb.registered_by = ctx.accounts.admin.key();
        climb.bump = ctx.bumps.climb;

        let version_index = &mut ctx.accounts.climb_version_index;
        version_index.canon_id = args.canon_id;
        version_index.canon_version = args.canon_version;
        version_index.climb = climb_key;
        version_index.bump = ctx.bumps.climb_version_index;

        emit!(ClimbRegistered {
            climb: climb_key,
            commitment_hash,
            canon_id: args.canon_id,
            canon_version: args.canon_version,
            predecessor_climb: predecessor_key,
            record_continuity_policy: args.record_continuity_policy,
            registered_by: ctx.accounts.admin.key(),
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Initialize the vault counter (one-time setup)
    pub fn initialize_vault_counter(ctx: Context<InitializeVaultCounter>) -> Result<()> {
        let counter = &mut ctx.accounts.vault_counter;
        counter.count = 0;
        counter.bump = ctx.bumps.vault_counter;
        Ok(())
    }

    /// Create a new vault from a ratified canon Climb.
    /// Payment: burns DUNG tokens
    pub fn create_vault<'info>(ctx: Context<'_, '_, '_, 'info, CreateVault<'info>>) -> Result<()> {
        let vault_key = ctx.accounts.vault.key();
        let binding =
            bind_climb_account_to_vault(ctx.accounts.climb.as_ref(), ctx.program_id, vault_key)?;

        let program_config_info = ctx
            .remaining_accounts
            .first()
            .ok_or(ErrorCode::InvalidProgramConfigLayout)?;
        let config = read_program_config_info(program_config_info, ctx.program_id)?;
        let dung_mint_info = ctx
            .remaining_accounts
            .get(1)
            .ok_or(ErrorCode::InvalidMint)?;
        let creator_dung_account_info = ctx
            .remaining_accounts
            .get(2)
            .ok_or(ErrorCode::InvalidTokenAccount)?;
        require!(config.initialized, ErrorCode::NotInitialized);
        let settlement_clock = config.settlement_clock()?;
        require!(
            *dung_mint_info.key == config.dung_mint,
            ErrorCode::InvalidMint
        );
        let creator_dung_account = read_token_account_info(creator_dung_account_info)?;
        require!(
            creator_dung_account.owner == ctx.accounts.creator.key(),
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            creator_dung_account.mint == config.dung_mint,
            ErrorCode::InvalidMint
        );
        require_backend_vault_creation_sponsor(
            config.backend_authority,
            ctx.accounts.sponsor_authority.key(),
        )?;
        let mut dung_mint_state = read_dung_mint_state_unchecked(
            ctx.accounts.dung_mint_state.as_ref(),
            ctx.bumps.dung_mint_state,
        )?;

        // Burn DUNG for vault creation
        token::burn(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: dung_mint_info.clone(),
                    from: creator_dung_account_info.clone(),
                    authority: ctx.accounts.creator.to_account_info(),
                },
            ),
            config.vault_creation_dung,
        )?;
        dung_mint_state.record_protocol_burn(config.vault_creation_dung)?;
        let total_protocol_burned = dung_mint_state.total_burned;
        write_dung_mint_state_unchecked(ctx.accounts.dung_mint_state.as_ref(), &dung_mint_state)?;

        let clock = Clock::get()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        let counter = &mut ctx.accounts.vault_counter;
        let vault = &mut ctx.accounts.vault;

        let signature_hash = binding.commitment_hash;

        vault.id = counter.count;
        vault.signature = binding.canon_commitment;
        vault.signature_hash = signature_hash;
        vault.climb = binding.climb;
        vault.minter = ctx.accounts.creator.key();
        vault.mint_epoch = current_epoch;
        vault.rights_expires_epoch = current_epoch + config.minter_rights_epochs;
        vault.kom_holder = Pubkey::default();
        vault.kom_time_s = 0;
        vault.kom_set_epoch = 0;

        vault.name = binding.name;
        vault.avatar_ipfs = [0u8; 46];
        vault.slogan = [0u8; 128];

        // Economics - start at zero
        vault.cal_tribute_accumulated = 0;
        vault.cal_tribute_accumulated_next = 0;
        vault.total_cal_burned = 0;
        vault.total_dung_emitted = 0;
        vault.total_completions = 0;
        vault.total_cal_staked = 0;
        vault.staker_count = 0;
        vault.reward_per_token_stored = 0;
        vault.last_update_time = 0;
        vault.reward_rate = STAKER_REMAINDER_POLICY_MARKER;
        vault.pending_rewards = 0;
        vault.pending_rewards_next_week = 0;
        vault.open_settlement_week = current_epoch;
        vault.carry_record_royalty = 0;
        vault.carry_stakers = 0;
        vault.carry_local_legend = 0;
        vault.carry_pol = 0;
        vault.carry_treasury = 0;
        vault.total_staked = 0;
        vault.last_distribution_epoch = 0;

        // Metrics
        vault.vert_m = binding.vert_m;
        vault.distance_m = binding.distance_m;
        vault.avg_gradient_pct = binding.avg_gradient_pct;

        vault.created_at = clock.unix_timestamp;
        vault.bump = ctx.bumps.vault;

        // Initialize Local Legend - creator becomes first Soigneur (8-epoch bootstrap term)
        let legend = &mut ctx.accounts.local_legend;
        legend.vault_id = counter.count; // Same as vault.id
        legend.holder = ctx.accounts.creator.key();
        legend.election_period = 0; // Bootstrap (not elected)
        legend.term_start_epoch = current_epoch;
        legend.term_end_epoch = current_epoch + config.local_legend_term_epochs;
        legend.completions_at_election = 0; // Creator bootstrap, not elected
        legend.runner_up = Pubkey::default();
        legend.runner_up_completions = 0;
        legend.total_earned = 0;
        legend.is_active = true;
        legend.is_bootstrap = true;
        legend.bump = ctx.bumps.local_legend;

        create_empty_vault_leaderboard_account(
            ctx.accounts.vault_leaderboard.as_ref(),
            &ctx.accounts.sponsor_authority.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            ctx.program_id,
            counter.count,
            ctx.bumps.vault_leaderboard,
        )?;
        initialize_chain_authoritative_activation(
            &mut ctx.accounts.vault_activation,
            counter.count,
            clock.unix_timestamp,
            current_epoch,
            &binding.climb,
            &vault_key,
            ctx.bumps.vault_activation,
        );

        counter.count = counter.count.checked_add(1).ok_or(ErrorCode::Overflow)?;

        emit!(VaultCreated {
            id: vault.id,
            minter: vault.minter,
            signature_hash,
            vert_m: binding.vert_m,
            payment_method: VaultPaymentMethod::Dung as u8,
            timestamp: clock.unix_timestamp,
        });
        emit!(DungBurned {
            actor: ctx.accounts.creator.key(),
            amount: config.vault_creation_dung,
            burn_kind: DUNG_BURN_KIND_VAULT_CREATION,
            total_protocol_burned,
            timestamp: clock.unix_timestamp,
        });

        // Emit legend bootstrap event (election_period=0 indicates bootstrap)
        emit!(LocalLegendElected {
            vault_id: vault.id,
            winner: ctx.accounts.creator.key(),
            winner_completions: 0,
            runner_up: Pubkey::default(),
            runner_up_completions: 0,
            election_period: 0, // Bootstrap
            term_start_epoch: legend.term_start_epoch,
            term_end_epoch: legend.term_end_epoch,
            is_bootstrap: true,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Create a vault for a ratified Climb by burning `vault_creation_cal`
    /// whole CAL and transferring `vault_creation_usdc` USDC base units to the
    /// configured treasury. The creator signs both token movements.
    pub fn create_vault_with_usdc<'info>(
        ctx: Context<'_, '_, '_, 'info, CreateVaultWithUsdc<'info>>,
    ) -> Result<()> {
        let vault_key = ctx.accounts.vault.key();
        let binding =
            bind_climb_account_to_vault(ctx.accounts.climb.as_ref(), ctx.program_id, vault_key)?;
        let cal_mint_info = ctx
            .remaining_accounts
            .first()
            .ok_or(ErrorCode::InvalidMint)?;
        let program_config_info = ctx
            .remaining_accounts
            .get(1)
            .ok_or(ErrorCode::InvalidProgramConfigLayout)?;
        let creator_usdc_info = ctx
            .remaining_accounts
            .get(2)
            .ok_or(ErrorCode::InvalidTokenAccount)?;
        let config = read_program_config_info(program_config_info, ctx.program_id)?;
        require!(config.initialized, ErrorCode::NotInitialized);
        require_backend_vault_creation_sponsor(
            config.backend_authority,
            ctx.accounts.sponsor_authority.key(),
        )?;
        let settlement_clock = config.settlement_clock()?;
        require!(
            config.cal_mint != Pubkey::default(),
            ErrorCode::MintsNotConfigured
        );
        require!(config.is_usdc_configured(), ErrorCode::UsdcNotConfigured);
        require!(
            *cal_mint_info.key == config.cal_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.creator_cal_account.owner == ctx.accounts.creator.key(),
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.creator_cal_account.mint == config.cal_mint,
            ErrorCode::InvalidMint
        );
        let creator_usdc_account = read_token_account_info(creator_usdc_info)?;
        require!(
            creator_usdc_account.owner == ctx.accounts.creator.key(),
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            creator_usdc_account.mint == config.usdc_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.protocol_usdc_account.key() == config.usdc_treasury_token_account,
            ErrorCode::InvalidTokenAccount
        );
        require!(
            ctx.accounts.protocol_usdc_account.mint == config.usdc_mint,
            ErrorCode::InvalidMint
        );
        let vault_creation_cal_amount = config
            .vault_creation_cal
            .checked_mul(CAL_DECIMALS_MULTIPLIER)
            .ok_or(ErrorCode::Overflow)?;

        // Burn the configured creation CAL, scaled from whole CAL to base units.
        token::burn(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: cal_mint_info.clone(),
                    from: ctx.accounts.creator_cal_account.to_account_info(),
                    authority: ctx.accounts.creator.to_account_info(),
                },
            ),
            vault_creation_cal_amount,
        )?;

        // Transfer USDC from creator to protocol treasury
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: creator_usdc_info.clone(),
                    to: ctx.accounts.protocol_usdc_account.to_account_info(),
                    authority: ctx.accounts.creator.to_account_info(),
                },
            ),
            config.vault_creation_usdc,
        )?;

        let clock = Clock::get()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        let counter = &mut ctx.accounts.vault_counter;
        let vault = &mut ctx.accounts.vault;

        let signature_hash = binding.commitment_hash;

        vault.id = counter.count;
        vault.signature = binding.canon_commitment;
        vault.signature_hash = signature_hash;
        vault.climb = binding.climb;
        vault.minter = ctx.accounts.creator.key();
        vault.mint_epoch = current_epoch;
        vault.rights_expires_epoch = current_epoch + config.minter_rights_epochs;
        vault.kom_holder = Pubkey::default();
        vault.kom_time_s = 0;
        vault.kom_set_epoch = 0;

        vault.name = binding.name;
        vault.avatar_ipfs = [0u8; 46];
        vault.slogan = [0u8; 128];

        // Economics start empty; the creation burn is not climb tribute.
        vault.cal_tribute_accumulated = 0;
        vault.cal_tribute_accumulated_next = 0;
        vault.total_cal_burned = 0;
        vault.total_dung_emitted = 0;
        vault.total_completions = 0;
        vault.total_cal_staked = 0;
        vault.staker_count = 0;
        vault.reward_per_token_stored = 0;
        vault.last_update_time = 0;
        vault.reward_rate = STAKER_REMAINDER_POLICY_MARKER;
        vault.pending_rewards = 0;
        vault.pending_rewards_next_week = 0;
        vault.open_settlement_week = current_epoch;
        vault.carry_record_royalty = 0;
        vault.carry_stakers = 0;
        vault.carry_local_legend = 0;
        vault.carry_pol = 0;
        vault.carry_treasury = 0;
        vault.total_staked = 0;
        vault.last_distribution_epoch = 0;

        // Metrics
        vault.vert_m = binding.vert_m;
        vault.distance_m = binding.distance_m;
        vault.avg_gradient_pct = binding.avg_gradient_pct;

        vault.created_at = clock.unix_timestamp;
        vault.bump = ctx.bumps.vault;

        // Initialize Local Legend - creator becomes first Soigneur (8-epoch bootstrap term)
        let legend = &mut ctx.accounts.local_legend;
        legend.vault_id = counter.count; // Same as vault.id
        legend.holder = ctx.accounts.creator.key();
        legend.election_period = 0; // Bootstrap (not elected)
        legend.term_start_epoch = current_epoch;
        legend.term_end_epoch = current_epoch + config.local_legend_term_epochs;
        legend.completions_at_election = 0; // Creator bootstrap, not elected
        legend.runner_up = Pubkey::default();
        legend.runner_up_completions = 0;
        legend.total_earned = 0;
        legend.is_active = true;
        legend.is_bootstrap = true;
        legend.bump = ctx.bumps.local_legend;

        create_empty_vault_leaderboard_account(
            ctx.accounts.vault_leaderboard.as_ref(),
            &ctx.accounts.sponsor_authority.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            ctx.program_id,
            counter.count,
            ctx.bumps.vault_leaderboard,
        )?;
        initialize_chain_authoritative_activation(
            &mut ctx.accounts.vault_activation,
            counter.count,
            clock.unix_timestamp,
            current_epoch,
            &binding.climb,
            &vault_key,
            ctx.bumps.vault_activation,
        );

        counter.count = counter.count.checked_add(1).ok_or(ErrorCode::Overflow)?;

        emit!(VaultCreated {
            id: vault.id,
            minter: vault.minter,
            signature_hash,
            vert_m: binding.vert_m,
            payment_method: VaultPaymentMethod::CalPlusUsdc as u8,
            timestamp: clock.unix_timestamp,
        });

        // Emit legend bootstrap event (election_period=0 indicates bootstrap)
        emit!(LocalLegendElected {
            vault_id: vault.id,
            winner: ctx.accounts.creator.key(),
            winner_completions: 0,
            runner_up: Pubkey::default(),
            runner_up_completions: 0,
            election_period: 0, // Bootstrap
            term_start_epoch: legend.term_start_epoch,
            term_end_epoch: legend.term_end_epoch,
            is_bootstrap: true,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Initialize LP mint for vault staking
    pub fn initialize_vault_lp_mint(_ctx: Context<InitializeVaultLpMint>) -> Result<()> {
        Ok(())
    }

    /// Initialize and seal the deterministic LP custody account for a rider.
    pub fn initialize_vault_position_lp(ctx: Context<InitializeVaultPositionLp>) -> Result<()> {
        let position = &ctx.accounts.position_lp_account;
        require_position_lp_identity(
            position,
            ctx.accounts.vault_stake.key(),
            ctx.accounts.vault_lp_mint.key(),
        )?;
        require!(
            position.state == AccountState::Initialized || position.state == AccountState::Frozen,
            ErrorCode::InvalidLpCustodyState
        );
        if position.state == AccountState::Initialized {
            let vault = &ctx.accounts.vault;
            let vault_id_bytes = vault.id.to_le_bytes();
            let vault_bump = [vault.bump];
            let vault_seeds = &[VAULT_SEED, &vault_id_bytes, &vault_bump];
            let vault_signer = &[&vault_seeds[..]];
            freeze_position_lp(
                ctx.accounts.token_program.to_account_info(),
                position.to_account_info(),
                ctx.accounts.vault_lp_mint.to_account_info(),
                vault.to_account_info(),
                vault_signer,
            )?;
        }
        Ok(())
    }

    /// Initialize a rider-scoped Boulder Roller Balance header.
    pub fn initialize_rider_balance(ctx: Context<InitializeRiderBalance>) -> Result<()> {
        let balance = &mut ctx.accounts.rider_balance;
        let clock = Clock::get()?;
        balance.rider = ctx.accounts.rider.key();
        balance.status = RiderBalanceStatus::Active;
        balance.active_authority_model = BalanceAuthorityModel::AppBalance;
        balance.policy_hash = [0; 32];
        balance.delegate_authority = Pubkey::default();
        balance.last_authority_rotation_at = clock.unix_timestamp;
        balance.revoked_at = 0;
        balance.bump = ctx.bumps.rider_balance;
        Ok(())
    }

    /// Initialize a RiderBalance-owned token account for a specific mint.
    pub fn initialize_rider_balance_token(
        _ctx: Context<InitializeRiderBalanceToken>,
    ) -> Result<()> {
        Ok(())
    }

    /// Configure or rotate the rider signer used for no-prompt Balance-funded
    /// Vault actions. The rider signs this authority-change boundary once.
    pub fn configure_balance_vault_authority(
        ctx: Context<ConfigureBalanceVaultAuthority>,
        authority: Pubkey,
        policy_hash: [u8; 32],
        expires_at: i64,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(
            authority != Pubkey::default(),
            ErrorCode::InvalidBalanceVaultAuthority
        );
        require!(
            policy_hash != [0; 32],
            ErrorCode::InvalidBalanceVaultAuthority
        );
        require!(
            expires_at > now
                && expires_at
                    <= now
                        .checked_add(MAX_BALANCE_VAULT_AUTHORITY_SECONDS)
                        .ok_or(ErrorCode::Overflow)?,
            ErrorCode::BalanceVaultAuthorityExpired
        );

        let balance = &mut ctx.accounts.rider_balance;
        require!(
            balance.status == RiderBalanceStatus::Active && balance.revoked_at == 0,
            ErrorCode::InvalidBalanceStatus
        );

        let session = &mut ctx.accounts.balance_vault_authority;
        let generation = if session.rider == Pubkey::default() {
            1
        } else {
            require_keys_eq!(
                session.rider,
                ctx.accounts.rider.key(),
                ErrorCode::InvalidBalanceVaultAuthority
            );
            session
                .generation
                .checked_add(1)
                .ok_or(ErrorCode::Overflow)?
        };
        session.rider = ctx.accounts.rider.key();
        session.authority = authority;
        session.policy_hash = policy_hash;
        session.generation = generation;
        session.next_nonce = 0;
        session.expires_at = expires_at;
        session.revoked_at = 0;
        session.last_operation_id = [0; 32];
        session.bump = ctx.bumps.balance_vault_authority;

        balance.active_authority_model = BalanceAuthorityModel::RiderSession;
        balance.policy_hash = policy_hash;
        balance.delegate_authority = authority;
        balance.last_authority_rotation_at = now;

        emit!(BalanceVaultAuthorityConfigured {
            rider: balance.rider,
            authority,
            policy_hash,
            generation,
            expires_at,
            timestamp: now,
        });
        Ok(())
    }

    /// Revoke the active Vault-action session without revoking the Balance
    /// itself. A later no-prompt action requires a new rider-signed rotation.
    pub fn revoke_balance_vault_authority(ctx: Context<RevokeBalanceVaultAuthority>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let balance = &mut ctx.accounts.rider_balance;
        let session = &mut ctx.accounts.balance_vault_authority;
        require_keys_eq!(
            session.rider,
            ctx.accounts.rider.key(),
            ErrorCode::InvalidBalanceVaultAuthority
        );
        require!(
            session.revoked_at == 0,
            ErrorCode::BalanceVaultAuthorityRevoked
        );

        session.revoked_at = now;
        session.expires_at = now;
        session.generation = session
            .generation
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        session.next_nonce = 0;
        balance.active_authority_model = BalanceAuthorityModel::AppBalance;
        balance.policy_hash = [0; 32];
        balance.delegate_authority = Pubkey::default();
        balance.last_authority_rotation_at = now;

        emit!(BalanceVaultAuthorityRevoked {
            rider: balance.rider,
            authority: session.authority,
            generation: session.generation,
            timestamp: now,
        });
        Ok(())
    }

    /// Admin control for locking, recovery, and revocation tests/policy gates.
    pub fn set_rider_balance_status(
        ctx: Context<SetRiderBalanceStatus>,
        status: RiderBalanceStatus,
    ) -> Result<()> {
        let balance = &mut ctx.accounts.rider_balance;
        balance.status = status;
        balance.last_authority_rotation_at = Clock::get()?.unix_timestamp;
        balance.revoked_at = if status == RiderBalanceStatus::Revoked {
            balance.last_authority_rotation_at
        } else if status == RiderBalanceStatus::Active {
            0
        } else {
            balance.revoked_at
        };
        if status != RiderBalanceStatus::Active {
            balance.active_authority_model = BalanceAuthorityModel::AppBalance;
            balance.policy_hash = [0; 32];
            balance.delegate_authority = Pubkey::default();
        }
        Ok(())
    }

    // =========================================================================
    // CAL STAKING
    // =========================================================================

    /// Stake CAL in a vault from the user's SPL CAL token account.
    /// CAL is the energy token earned from riding — staking it earns DUNG rewards
    /// via discrete settlement-week allocation at each Settlement Week finalization.
    pub fn stake_cal_in_vault(ctx: Context<StakeCalInVault>, amount: u64) -> Result<()> {
        // Minimum 100 CAL stake (SPL amount with decimals)
        require!(amount >= CAL_MIN_STAKE, ErrorCode::MinimumStakeRequired);

        let vault = &mut ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;

        // ============================================
        // SPL CAL Transfer: user_cal_ata → vault_cal_escrow
        // ============================================
        let is_new_position = stake.user == Pubkey::default();
        let was_inactive = stake.lp_tokens == 0;
        let was_required_for_settlement = stake.requires_settlement_account();
        let total_cal_staked = vault.total_cal_staked;
        let total_lp_supply = ctx.accounts.vault_lp_mint.supply;
        let lp_custody_state = ctx.accounts.staker_lp_account.state;
        require_position_lp_ready(
            &ctx.accounts.staker_lp_account,
            stake.key(),
            ctx.accounts.vault_lp_mint.key(),
            stake.lp_tokens,
            stake.lp_tokens == 0,
        )?;
        let lp_transition =
            stake_lp_transition(stake.lp_tokens, amount, total_lp_supply, total_cal_staked)?;

        if is_new_position {
            stake.user = ctx.accounts.staker.key();
            stake.vault_id = vault.id;
            stake.staked_at = current_time;
            stake.pending_effective_week_plus_one = 0;
            stake.effective_lp_tokens = 0;
            stake.rewards_earned = 0;
            stake.pending_lp_tokens = 0;
            stake.bump = ctx.bumps.vault_stake;
        } else if was_inactive {
            stake.staked_at = current_time;
        }
        stake.prepare_lp_change(
            &settlement_clock,
            lp_transition.next_lp_tokens,
            current_time,
            vault.open_settlement_week,
        )?;
        let next_staker_count = settlement_inventory_count_after_change(
            vault.staker_count,
            was_required_for_settlement,
            stake.requires_settlement_account_with_live_lp(lp_transition.next_lp_tokens),
        )?;

        // SPL transfer CAL from user to vault escrow
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.staker_cal_ata.to_account_info(),
                    to: ctx.accounts.vault_cal_escrow.to_account_info(),
                    authority: ctx.accounts.staker.to_account_info(),
                },
            ),
            amount,
        )?;

        // Add CAL to vault's staked total
        vault.total_cal_staked = vault
            .total_cal_staked
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;

        // Mint LP tokens to staker
        let vault_id = vault.id;
        let seeds = &[VAULT_SEED, &vault_id.to_le_bytes(), &[vault.bump]];
        let signer = &[&seeds[..]];

        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.staker_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            lp_custody_state,
            signer,
        )?;

        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.vault_lp_mint.to_account_info(),
                    to: ctx.accounts.staker_lp_account.to_account_info(),
                    authority: vault.to_account_info(),
                },
                signer,
            ),
            lp_transition.lp_to_mint,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.staker_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            signer,
        )?;

        // Update current principal and redeemable LP. Settlement uses the
        // separate effective/pending LP snapshots prepared before token CPIs.
        stake.cal_staked = stake
            .cal_staked
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;
        stake.lp_tokens = lp_transition.next_lp_tokens;

        vault.staker_count = next_staker_count;

        emit!(CalStaked {
            vault_id: vault.id,
            staker: ctx.accounts.staker.key(),
            amount,
            lp_minted: lp_transition.lp_to_mint,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Deposit CAL from Boulder Roller Balance into a vault without requiring
    /// the rider wallet to sign. CAL comes from Balance while LP is held in the
    /// same program-controlled position custody used by direct deposits.
    pub fn deposit_cal_from_balance(
        ctx: Context<DepositCalFromBalance>,
        amount: u64,
        authorization: BalanceVaultOperationAuthorization,
    ) -> Result<()> {
        require!(amount >= CAL_MIN_STAKE, ErrorCode::MinimumStakeRequired);

        let vault = &mut ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let rider_key = ctx.accounts.rider.key();
        let balance_authority_key = ctx.accounts.rider_balance_authority.key();
        let was_required_for_settlement = stake.requires_settlement_account();

        require!(
            ctx.accounts.vault_activation.is_active,
            ErrorCode::VaultNotActive
        );
        require!(
            ctx.accounts.program_config.initialized,
            ErrorCode::NotInitialized
        );
        require!(
            ctx.accounts.program_config.cal_mint != Pubkey::default(),
            ErrorCode::MintsNotConfigured
        );
        require!(
            ctx.accounts.rider_balance.rider == rider_key,
            ErrorCode::InvalidRiderBalance
        );
        require!(
            ctx.accounts.rider_balance.status == RiderBalanceStatus::Active
                && ctx.accounts.rider_balance.revoked_at == 0,
            ErrorCode::InvalidBalanceStatus
        );
        authorize_balance_vault_operation(
            &ctx.accounts.rider_balance,
            ctx.accounts.balance_vault_authority.as_mut(),
            ctx.accounts.operation_authority.key(),
            ctx.program_id,
            BalanceVaultOperationKind::DepositCal,
            vault.id,
            amount,
            0,
            authorization,
            current_time,
        )?;
        if stake.user != Pubkey::default() {
            require!(
                stake.user == rider_key && stake.vault_id == vault.id,
                ErrorCode::InvalidStakeAccount
            );
        }
        require!(
            ctx.accounts.rider_balance_cal_account.owner == balance_authority_key,
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.rider_balance_cal_account.mint == ctx.accounts.program_config.cal_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.vault_cal_escrow.owner == vault.key(),
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.vault_cal_escrow.mint == ctx.accounts.program_config.cal_mint,
            ErrorCode::InvalidMint
        );
        let is_new_position = stake.user == Pubkey::default();
        let was_inactive = stake.lp_tokens == 0;
        let total_cal_staked = vault.total_cal_staked;
        let total_lp_supply = ctx.accounts.vault_lp_mint.supply;
        let lp_custody_state = ctx.accounts.rider_balance_lp_account.state;
        require_position_lp_ready(
            &ctx.accounts.rider_balance_lp_account,
            stake.key(),
            ctx.accounts.vault_lp_mint.key(),
            stake.lp_tokens,
            stake.lp_tokens == 0,
        )?;
        let lp_transition =
            stake_lp_transition(stake.lp_tokens, amount, total_lp_supply, total_cal_staked)?;

        if is_new_position {
            stake.user = rider_key;
            stake.vault_id = vault.id;
            stake.staked_at = current_time;
            stake.pending_effective_week_plus_one = 0;
            stake.effective_lp_tokens = 0;
            stake.rewards_earned = 0;
            stake.pending_lp_tokens = 0;
            stake.bump = ctx.bumps.vault_stake;
        } else if was_inactive {
            stake.staked_at = current_time;
        }
        stake.prepare_lp_change(
            &settlement_clock,
            lp_transition.next_lp_tokens,
            current_time,
            vault.open_settlement_week,
        )?;
        let next_staker_count = settlement_inventory_count_after_change(
            vault.staker_count,
            was_required_for_settlement,
            stake.requires_settlement_account_with_live_lp(lp_transition.next_lp_tokens),
        )?;

        let balance_auth_bump = ctx.bumps.rider_balance_authority;
        let balance_auth_seeds = &[
            RIDER_BALANCE_AUTH_SEED,
            rider_key.as_ref(),
            &[balance_auth_bump],
        ];
        let balance_auth_signer = &[&balance_auth_seeds[..]];

        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.rider_balance_cal_account.to_account_info(),
                    to: ctx.accounts.vault_cal_escrow.to_account_info(),
                    authority: ctx.accounts.rider_balance_authority.to_account_info(),
                },
                balance_auth_signer,
            ),
            amount,
        )?;

        vault.total_cal_staked = vault
            .total_cal_staked
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;

        let vault_id = vault.id;
        let vault_seeds = &[VAULT_SEED, &vault_id.to_le_bytes(), &[vault.bump]];
        let vault_signer = &[&vault_seeds[..]];

        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.rider_balance_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            lp_custody_state,
            vault_signer,
        )?;

        token::mint_to(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                MintTo {
                    mint: ctx.accounts.vault_lp_mint.to_account_info(),
                    to: ctx.accounts.rider_balance_lp_account.to_account_info(),
                    authority: vault.to_account_info(),
                },
                vault_signer,
            ),
            lp_transition.lp_to_mint,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.rider_balance_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            vault_signer,
        )?;

        stake.cal_staked = stake
            .cal_staked
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;
        stake.lp_tokens = lp_transition.next_lp_tokens;

        vault.staker_count = next_staker_count;

        emit!(CalStaked {
            vault_id: vault.id,
            staker: rider_key,
            amount,
            lp_minted: lp_transition.lp_to_mint,
            timestamp: current_time,
        });

        emit!(BalanceVaultOperationAuthorized {
            rider: rider_key,
            authority: ctx.accounts.operation_authority.key(),
            operation_id: authorization.operation_id,
            kind: BalanceVaultOperationKind::DepositCal,
            vault_id: vault.id,
            primary_amount: amount,
            secondary_amount: 0,
            generation: authorization.generation,
            nonce: authorization.nonce,
            expires_at: authorization.expires_at,
            timestamp: current_time,
        });

        Ok(())
    }

    /// Restore legacy wallet, custom-destination, or transferred LP into the
    /// deterministic position custody account. The current holder signs for
    /// the source; restoration never changes VaultStake accounting.
    pub fn restore_vault_lp_custody(
        ctx: Context<RestoreVaultLpCustody>,
        amount: u64,
    ) -> Result<()> {
        let vault = &ctx.accounts.vault;
        let stake = &ctx.accounts.vault_stake;
        let position = &ctx.accounts.position_lp_account;
        require!(
            ctx.accounts.source_lp_account.state == AccountState::Initialized,
            ErrorCode::InvalidLpCustodyState
        );
        require!(
            ctx.accounts.source_lp_account.amount >= amount,
            ErrorCode::InsufficientLpCustody
        );
        require_position_lp_identity(position, stake.key(), ctx.accounts.vault_lp_mint.key())?;
        require!(
            position.state == AccountState::Frozen
                || (position.state == AccountState::Initialized && position.amount == 0),
            ErrorCode::InvalidLpCustodyState
        );
        let restoration = lp_custody_restoration(position.amount, amount, stake.lp_tokens)?;

        let vault_id_bytes = vault.id.to_le_bytes();
        let vault_bump = [vault.bump];
        let vault_seeds = &[VAULT_SEED, &vault_id_bytes, &vault_bump];
        let vault_signer = &[&vault_seeds[..]];
        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            position.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            position.state,
            vault_signer,
        )?;
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.source_lp_account.to_account_info(),
                    to: position.to_account_info(),
                    authority: ctx.accounts.source_authority.to_account_info(),
                },
            ),
            amount,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            position.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            vault_signer,
        )?;

        emit!(VaultLpCustodyRestored {
            rider: ctx.accounts.rider.key(),
            vault_id: vault.id,
            source: ctx.accounts.source_lp_account.key(),
            amount,
            custody_amount: restoration.next_amount,
            sealed: restoration.sealed,
            timestamp: Clock::get()?.unix_timestamp,
        });
        Ok(())
    }

    /// Restore LP held by the legacy Boulder Roller Balance token PDA. The
    /// Balance authority signs inside the program; no rider wallet signature is
    /// required because the destination is that rider's fixed Vault position.
    pub fn restore_balance_vault_lp_custody(
        ctx: Context<RestoreBalanceVaultLpCustody>,
        amount: u64,
    ) -> Result<()> {
        let vault = &ctx.accounts.vault;
        let stake = &ctx.accounts.vault_stake;
        let position = &ctx.accounts.position_lp_account;
        require!(
            ctx.accounts.rider_balance_lp_account.state == AccountState::Initialized,
            ErrorCode::InvalidLpCustodyState
        );
        require!(
            ctx.accounts.rider_balance_lp_account.amount >= amount,
            ErrorCode::InsufficientLpCustody
        );
        require_position_lp_identity(position, stake.key(), ctx.accounts.vault_lp_mint.key())?;
        require!(
            position.state == AccountState::Frozen
                || (position.state == AccountState::Initialized && position.amount == 0),
            ErrorCode::InvalidLpCustodyState
        );
        let restoration = lp_custody_restoration(position.amount, amount, stake.lp_tokens)?;

        let vault_id_bytes = vault.id.to_le_bytes();
        let vault_bump = [vault.bump];
        let vault_seeds = &[VAULT_SEED, &vault_id_bytes, &vault_bump];
        let vault_signer = &[&vault_seeds[..]];
        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            position.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            position.state,
            vault_signer,
        )?;

        let balance_bump = [ctx.bumps.rider_balance_authority];
        let rider_key = ctx.accounts.rider.key();
        let balance_seeds = &[RIDER_BALANCE_AUTH_SEED, rider_key.as_ref(), &balance_bump];
        let balance_signer = &[&balance_seeds[..]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.rider_balance_lp_account.to_account_info(),
                    to: position.to_account_info(),
                    authority: ctx.accounts.rider_balance_authority.to_account_info(),
                },
                balance_signer,
            ),
            amount,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            position.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            vault_signer,
        )?;

        emit!(VaultLpCustodyRestored {
            rider: rider_key,
            vault_id: vault.id,
            source: ctx.accounts.rider_balance_lp_account.key(),
            amount,
            custody_amount: restoration.next_amount,
            sealed: restoration.sealed,
            timestamp: Clock::get()?.unix_timestamp,
        });
        Ok(())
    }

    /// Unstake CAL from a vault (SPL transfer from escrow back to user)
    /// Exit fee CAL is burned (not kept). Unclaimed DUNG rewards remain on the
    /// VaultStake account until harvested.
    pub fn unstake_cal_from_vault(ctx: Context<UnstakeCalFromVault>, lp_amount: u64) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let was_required_for_settlement = stake.requires_settlement_account();
        let lp_custody_state = ctx.accounts.staker_lp_account.state;
        require_position_lp_ready(
            &ctx.accounts.staker_lp_account,
            stake.key(),
            ctx.accounts.vault_lp_mint.key(),
            stake.lp_tokens,
            false,
        )?;

        let accounting = unstake_accounting_transition(
            stake.cal_staked,
            stake.lp_tokens,
            lp_amount,
            ctx.accounts.vault_lp_mint.supply,
            vault.total_cal_staked,
        )?;
        let next_lp_tokens = accounting.next_lp_tokens;
        stake.prepare_lp_change(
            &settlement_clock,
            next_lp_tokens,
            current_time,
            vault.open_settlement_week,
        )?;
        let next_staker_count = settlement_inventory_count_after_change(
            vault.staker_count,
            was_required_for_settlement,
            stake.requires_settlement_account_with_live_lp(next_lp_tokens),
        )?;

        // ============================================
        // Normal Unstaking Logic
        // ============================================
        let cal_to_return = accounting.cal_to_return;
        let vault_id = vault.id;
        let vault_id_bytes = vault_id.to_le_bytes();
        let vault_bump = [vault.bump];
        let vault_seeds = &[VAULT_SEED, &vault_id_bytes, &vault_bump];
        let vault_signer = &[&vault_seeds[..]];
        let stake_user = stake.user;
        let stake_bump = [stake.bump];
        let stake_seeds = &[
            VAULT_STAKE_SEED,
            stake_user.as_ref(),
            &vault_id_bytes,
            &stake_bump,
        ];
        let stake_signer = &[&stake_seeds[..]];

        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.staker_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            lp_custody_state,
            vault_signer,
        )?;

        // Burn LP tokens
        token::burn(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: ctx.accounts.vault_lp_mint.to_account_info(),
                    from: ctx.accounts.staker_lp_account.to_account_info(),
                    authority: stake.to_account_info(),
                },
                stake_signer,
            ),
            lp_amount,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.staker_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            vault_signer,
        )?;

        // Calculate exit fee (0.5% = 50 basis points)
        let exit_fee = accounting.exit_fee;
        let cal_after_fee = accounting.cal_after_fee;

        // SPL transfer: escrow → user (minus fee)
        if cal_after_fee > 0 {
            token::transfer(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    Transfer {
                        from: ctx.accounts.vault_cal_escrow.to_account_info(),
                        to: ctx.accounts.staker_cal_ata.to_account_info(),
                        authority: vault.to_account_info(),
                    },
                    vault_signer,
                ),
                cal_after_fee,
            )?;
        }

        // Burn exit fee CAL for clean accounting
        if exit_fee > 0 {
            token::burn(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    Burn {
                        mint: ctx.accounts.cal_mint.to_account_info(),
                        from: ctx.accounts.vault_cal_escrow.to_account_info(),
                        authority: vault.to_account_info(),
                    },
                    vault_signer,
                ),
                exit_fee,
            )?;
        }

        // Update vault and stake records
        vault.total_cal_staked = vault
            .total_cal_staked
            .checked_sub(cal_to_return)
            .ok_or(ErrorCode::Underflow)?;
        stake.cal_staked = accounting.next_cal_staked;
        stake.lp_tokens = next_lp_tokens;
        vault.staker_count = next_staker_count;

        emit!(UnstakeWithFee {
            user: ctx.accounts.staker.key(),
            vault_id: vault.id,
            cal_returned: cal_after_fee,
            fee_amount: exit_fee,
            timestamp: current_time,
        });

        Ok(())
    }

    /// Withdraw CAL from a vault back into Boulder Roller Balance without
    /// requiring the rider wallet to sign.
    pub fn withdraw_cal_to_balance(
        ctx: Context<WithdrawCalToBalance>,
        lp_amount: u64,
        authorization: BalanceVaultOperationAuthorization,
    ) -> Result<()> {
        let vault = &mut ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let rider_key = ctx.accounts.rider.key();
        let balance_authority_key = ctx.accounts.rider_balance_authority.key();
        let was_required_for_settlement = stake.requires_settlement_account();
        let lp_custody_state = ctx.accounts.rider_balance_lp_account.state;
        require_position_lp_ready(
            &ctx.accounts.rider_balance_lp_account,
            stake.key(),
            ctx.accounts.vault_lp_mint.key(),
            stake.lp_tokens,
            false,
        )?;

        let accounting = unstake_accounting_transition(
            stake.cal_staked,
            stake.lp_tokens,
            lp_amount,
            ctx.accounts.vault_lp_mint.supply,
            vault.total_cal_staked,
        )?;
        let next_lp_tokens = accounting.next_lp_tokens;
        stake.prepare_lp_change(
            &settlement_clock,
            next_lp_tokens,
            current_time,
            vault.open_settlement_week,
        )?;
        let next_staker_count = settlement_inventory_count_after_change(
            vault.staker_count,
            was_required_for_settlement,
            stake.requires_settlement_account_with_live_lp(next_lp_tokens),
        )?;
        require!(
            ctx.accounts.vault_activation.is_active,
            ErrorCode::VaultNotActive
        );
        require!(
            ctx.accounts.program_config.initialized,
            ErrorCode::NotInitialized
        );
        require!(
            ctx.accounts.program_config.cal_mint != Pubkey::default(),
            ErrorCode::MintsNotConfigured
        );
        require!(
            ctx.accounts.rider_balance.rider == rider_key,
            ErrorCode::InvalidRiderBalance
        );
        require!(
            ctx.accounts.rider_balance.status == RiderBalanceStatus::Active
                && ctx.accounts.rider_balance.revoked_at == 0,
            ErrorCode::InvalidBalanceStatus
        );
        authorize_balance_vault_operation(
            &ctx.accounts.rider_balance,
            ctx.accounts.balance_vault_authority.as_mut(),
            ctx.accounts.operation_authority.key(),
            ctx.program_id,
            BalanceVaultOperationKind::WithdrawCal,
            vault.id,
            lp_amount,
            0,
            authorization,
            current_time,
        )?;
        require!(
            ctx.accounts.rider_balance_cal_account.owner == balance_authority_key,
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.rider_balance_cal_account.mint == ctx.accounts.program_config.cal_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.vault_cal_escrow.owner == vault.key(),
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.vault_cal_escrow.mint == ctx.accounts.program_config.cal_mint,
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.cal_mint.key() == ctx.accounts.program_config.cal_mint,
            ErrorCode::InvalidMint
        );
        let cal_to_return = accounting.cal_to_return;
        let vault_id = vault.id;
        let vault_id_bytes = vault_id.to_le_bytes();
        let vault_bump = [vault.bump];
        let vault_seeds = &[VAULT_SEED, &vault_id_bytes, &vault_bump];
        let vault_signer = &[&vault_seeds[..]];
        let stake_user = stake.user;
        let stake_bump = [stake.bump];
        let stake_seeds = &[
            VAULT_STAKE_SEED,
            stake_user.as_ref(),
            &vault_id_bytes,
            &stake_bump,
        ];
        let stake_signer = &[&stake_seeds[..]];

        thaw_position_lp_if_needed(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.rider_balance_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            lp_custody_state,
            vault_signer,
        )?;

        token::burn(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Burn {
                    mint: ctx.accounts.vault_lp_mint.to_account_info(),
                    from: ctx.accounts.rider_balance_lp_account.to_account_info(),
                    authority: stake.to_account_info(),
                },
                stake_signer,
            ),
            lp_amount,
        )?;
        freeze_position_lp(
            ctx.accounts.token_program.to_account_info(),
            ctx.accounts.rider_balance_lp_account.to_account_info(),
            ctx.accounts.vault_lp_mint.to_account_info(),
            vault.to_account_info(),
            vault_signer,
        )?;

        let exit_fee = accounting.exit_fee;
        let cal_after_fee = accounting.cal_after_fee;

        if cal_after_fee > 0 {
            token::transfer(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    Transfer {
                        from: ctx.accounts.vault_cal_escrow.to_account_info(),
                        to: ctx.accounts.rider_balance_cal_account.to_account_info(),
                        authority: vault.to_account_info(),
                    },
                    vault_signer,
                ),
                cal_after_fee,
            )?;
        }

        if exit_fee > 0 {
            token::burn(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    Burn {
                        mint: ctx.accounts.cal_mint.to_account_info(),
                        from: ctx.accounts.vault_cal_escrow.to_account_info(),
                        authority: vault.to_account_info(),
                    },
                    vault_signer,
                ),
                exit_fee,
            )?;
        }

        vault.total_cal_staked = vault
            .total_cal_staked
            .checked_sub(cal_to_return)
            .ok_or(ErrorCode::Underflow)?;
        stake.cal_staked = accounting.next_cal_staked;
        stake.lp_tokens = next_lp_tokens;
        vault.staker_count = next_staker_count;

        emit!(UnstakeWithFee {
            user: rider_key,
            vault_id: vault.id,
            cal_returned: cal_after_fee,
            fee_amount: exit_fee,
            timestamp: current_time,
        });

        emit!(BalanceVaultOperationAuthorized {
            rider: rider_key,
            authority: ctx.accounts.operation_authority.key(),
            operation_id: authorization.operation_id,
            kind: BalanceVaultOperationKind::WithdrawCal,
            vault_id: vault.id,
            primary_amount: lp_amount,
            secondary_amount: 0,
            generation: authorization.generation,
            nonce: authorization.nonce,
            expires_at: authorization.expires_at,
            timestamp: current_time,
        });

        Ok(())
    }

    /// Move assets out of Boulder Roller Balance to the rider's wallet. This is
    /// a wallet-boundary action: the rider signs, while the program signs only
    /// for the constrained RiderBalance token PDA.
    pub fn withdraw_to_wallet(ctx: Context<WithdrawToWallet>, amount: u64) -> Result<()> {
        let rider_key = ctx.accounts.rider.key();
        let balance_authority_key = ctx.accounts.rider_balance_authority.key();

        require!(amount > 0, ErrorCode::InvalidAmount);
        require!(
            ctx.accounts.program_config.initialized,
            ErrorCode::NotInitialized
        );
        require!(
            ctx.accounts.rider_balance.rider == rider_key,
            ErrorCode::InvalidRiderBalance
        );
        require!(
            ctx.accounts.rider_balance.status == RiderBalanceStatus::Active
                && ctx.accounts.rider_balance.revoked_at == 0,
            ErrorCode::InvalidBalanceStatus
        );
        require!(
            ctx.accounts.rider_balance_source.owner == balance_authority_key,
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.rider_balance_source.mint == ctx.accounts.mint.key(),
            ErrorCode::InvalidMint
        );
        require!(
            ctx.accounts.rider_wallet_destination.owner == rider_key,
            ErrorCode::InvalidTokenAccountOwner
        );
        require!(
            ctx.accounts.rider_wallet_destination.mint == ctx.accounts.mint.key(),
            ErrorCode::InvalidMint
        );

        let balance_auth_bump = ctx.bumps.rider_balance_authority;
        let balance_auth_seeds = &[
            RIDER_BALANCE_AUTH_SEED,
            rider_key.as_ref(),
            &[balance_auth_bump],
        ];
        let balance_auth_signer = &[&balance_auth_seeds[..]];

        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.to_account_info(),
                Transfer {
                    from: ctx.accounts.rider_balance_source.to_account_info(),
                    to: ctx.accounts.rider_wallet_destination.to_account_info(),
                    authority: ctx.accounts.rider_balance_authority.to_account_info(),
                },
                balance_auth_signer,
            ),
            amount,
        )?;

        Ok(())
    }

    /// Harvest DUNG rewards that were directly allocated during settlement-week finalization.
    /// A 5% fee is taken and sent to protocol treasury (per TOKENOMICS_V2)
    pub fn harvest_rewards(ctx: Context<HarvestRewards>) -> Result<()> {
        let vault = &ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        let total_earned = stake.rewards_earned;
        require!(total_earned > 0, ErrorCode::NoRewardsToHarvest);

        // Reset earned after the claim has been accepted.
        stake.rewards_earned = 0;

        // ============================================
        // Calculate fee and mint DUNG
        // ============================================
        let (harvest_fee, dung_to_staker) =
            harvest_reward_split(total_earned, ctx.accounts.program_config.harvest_fee_bps)?;

        // Convert the exact settlement reservation into minted supply. The
        // reservation and claim reset roll back if either mint CPI fails.
        let dung_mint_state = &mut ctx.accounts.dung_mint_state;
        dung_mint_state.consume_community_reservation(total_earned)?;

        // Use DUNG_MINT_AUTH_PDA as sole DUNG minting authority
        let config = &ctx.accounts.program_config;
        let dung_auth_seeds = &[DUNG_MINT_AUTH_SEED, &[config.dung_mint_auth_bump]];
        let dung_auth_signer = &[&dung_auth_seeds[..]];

        // Mint DUNG to staker (minus fee)
        if dung_to_staker > 0 {
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.staker_dung_account.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    dung_auth_signer,
                ),
                dung_to_staker,
            )?;
        }

        // Mint fee to protocol treasury
        if harvest_fee > 0 {
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.protocol_treasury.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    dung_auth_signer,
                ),
                harvest_fee,
            )?;
        }

        emit!(RewardsHarvested {
            vault_id: vault.id,
            staker: ctx.accounts.staker.key(),
            dung_earned: total_earned,
            harvest_fee,
            dung_received: dung_to_staker,
            timestamp: current_time,
        });

        Ok(())
    }

    /// Collect DUNG rewards for a rider without requiring the rider wallet to
    /// sign. Safety comes from VaultStake derivation, rider-owned destination,
    /// ProgramConfig treasury/mint constraints, and DungMintState caps.
    pub fn collect_stake_rewards_for(ctx: Context<CollectStakeRewardsFor>) -> Result<()> {
        let vault = &ctx.accounts.vault;
        let stake = &mut ctx.accounts.vault_stake;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        let total_earned = stake.rewards_earned;
        require!(total_earned > 0, ErrorCode::NoRewardsToHarvest);

        // Reset earned after the claim has been accepted. Anchor rolls the
        // state change back if a later mint CPI fails.
        stake.rewards_earned = 0;

        let (harvest_fee, dung_to_staker) =
            harvest_reward_split(total_earned, ctx.accounts.program_config.harvest_fee_bps)?;

        let dung_mint_state = &mut ctx.accounts.dung_mint_state;
        dung_mint_state.consume_community_reservation(total_earned)?;

        let config = &ctx.accounts.program_config;
        let dung_auth_seeds = &[DUNG_MINT_AUTH_SEED, &[config.dung_mint_auth_bump]];
        let dung_auth_signer = &[&dung_auth_seeds[..]];

        if dung_to_staker > 0 {
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.staker_dung_account.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    dung_auth_signer,
                ),
                dung_to_staker,
            )?;
        }

        if harvest_fee > 0 {
            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.protocol_treasury.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    dung_auth_signer,
                ),
                harvest_fee,
            )?;
        }

        emit!(RewardsHarvested {
            vault_id: vault.id,
            staker: ctx.accounts.staker.key(),
            dung_earned: total_earned,
            harvest_fee,
            dung_received: dung_to_staker,
            timestamp: current_time,
        });

        Ok(())
    }

    /// Update vault metadata (name, avatar, slogan)
    /// Only callable by rights holder (minter during rights period, then KOM)
    pub fn update_vault_metadata(
        ctx: Context<UpdateVaultMetadata>,
        name: Option<String>,
        avatar_ipfs: Option<String>,
        slogan: Option<String>,
    ) -> Result<()> {
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let vault = &mut ctx.accounts.vault;
        let clock = Clock::get()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;

        // Verify caller is rights holder
        let rights_holder = vault.rights_holder(current_epoch);
        require!(
            ctx.accounts.authority.key() == rights_holder,
            ErrorCode::UnauthorizedAuthority
        );

        if let Some(new_name) = name {
            require!(
                new_name.len() >= 3 && new_name.len() <= 64,
                ErrorCode::InvalidName
            );
            let mut name_bytes = [0u8; 64];
            name_bytes[..new_name.len()].copy_from_slice(new_name.as_bytes());
            vault.name = name_bytes;
        }

        if let Some(new_avatar) = avatar_ipfs {
            require!(new_avatar.len() <= 46, ErrorCode::InvalidMetadata);
            let mut avatar_bytes = [0u8; 46];
            avatar_bytes[..new_avatar.len()].copy_from_slice(new_avatar.as_bytes());
            vault.avatar_ipfs = avatar_bytes;
        }

        if let Some(new_slogan) = slogan {
            require!(new_slogan.len() <= 128, ErrorCode::InvalidMetadata);
            let mut slogan_bytes = [0u8; 128];
            slogan_bytes[..new_slogan.len()].copy_from_slice(new_slogan.as_bytes());
            vault.slogan = slogan_bytes;
        }

        emit!(VaultMetadataUpdated {
            vault_id: vault.id,
            updated_by: ctx.accounts.authority.key(),
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    // =====================================================
    // SUPPLY CAP ENFORCEMENT INSTRUCTIONS
    // =====================================================

    /// Initialize the global DUNG mint state (one-time setup)
    /// Only callable by program authority
    pub fn initialize_dung_mint_state(ctx: Context<InitializeDungMintState>) -> Result<()> {
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let mint_state = &mut ctx.accounts.dung_mint_state;
        let clock = Clock::get()?;
        let emission_start_week = settlement_clock.latest_finalizable_week(clock.unix_timestamp)?;

        mint_state.authority = ctx.accounts.program_config.admin_authority;
        mint_state.max_supply = MAX_SUPPLY;
        mint_state.total_minted = 0;
        mint_state.total_burned = 0;
        mint_state.community_minted = 0;
        mint_state.treasury_minted = 0;
        mint_state.team_minted = 0;
        mint_state.investor_minted = 0;
        mint_state.pol_minted = 0;
        mint_state.current_emission_rate_bps = BASIS_POINTS_DENOMINATOR;
        // Historical ABI name retained for deployed decoders. This value is
        // now the immutable emission-start Settlement Week and is never moved.
        mint_state.last_halving_epoch = emission_start_week;
        mint_state.bump = ctx.bumps.dung_mint_state;
        mint_state.community_reserved = 0;
        mint_state.reservation_policy_version = DUNG_RESERVATION_POLICY_VERSION;

        Ok(())
    }

    /// Grow the legacy DungMintState and reserve every pre-upgrade Community
    /// obligation. The authority supplies the complete VaultStake and Vault
    /// inventories as remaining accounts; every account is PDA-validated and
    /// summed on-chain. Repeating the instruction is a no-op only when the
    /// live claims and Community carries still equal the stored reservation.
    pub fn migrate_dung_mint_state<'info>(
        ctx: Context<'_, '_, 'info, 'info, MigrateDungMintState<'info>>,
        expected_vault_stake_count: u32,
        expected_vault_count: u32,
        expected_community_reserved: u64,
    ) -> Result<()> {
        require!(
            ctx.accounts.vault_counter.count == u64::from(expected_vault_count),
            ErrorCode::VaultCountMismatch
        );
        let community_reserved = sum_migration_community_obligations(
            ctx.program_id,
            ctx.remaining_accounts,
            expected_vault_stake_count,
            expected_vault_count,
        )?;
        require!(
            community_reserved == expected_community_reserved,
            ErrorCode::CommunityReservationMismatch
        );
        let old_size = ctx.accounts.dung_mint_state.data_len();
        let new_size = migrate_dung_mint_state_layout(
            &ctx.accounts.dung_mint_state.to_account_info(),
            ctx.accounts.program_config.admin_authority,
            ctx.bumps.dung_mint_state,
            &ctx.accounts.payer.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
            community_reserved,
        )?;

        emit!(DungMintStateMigrated {
            authority: ctx.accounts.authority.key(),
            old_size: u32::try_from(old_size).map_err(|_| ErrorCode::Overflow)?,
            new_size: u32::try_from(new_size).map_err(|_| ErrorCode::Overflow)?,
            community_reserved,
            reservation_policy_version: DUNG_RESERVATION_POLICY_VERSION,
            vault_stake_count: expected_vault_stake_count,
            vault_count: expected_vault_count,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    // =====================================================
    // DISTRIBUTION INSTRUCTION (Tokenomics V2)
    // =====================================================

    /// Distribute Settlement Week rewards using the canonical policy.
    /// The config argument remains for ABI compatibility, but only the
    /// canonical 55/27/3/5/10 split is accepted.
    ///
    /// Distributes DUNG from accumulated CAL tribute to (TOKENOMICS_V2):
    /// - Record Royalty: 55% base, prior record carry, and same-week locked staker share
    /// - Stakers: current-week unlocked share plus prior unlocked pro-rata dust
    /// - 3% Local Legend (single elected curator per vault)
    /// - 5% POL (protocol-owned liquidity)
    /// - 10% Protocol Treasury
    pub fn distribute_epoch_rewards<'info>(
        ctx: Context<'_, '_, 'info, 'info, DistributeEpochRewards<'info>>,
        settlement_week: u64,
        config: DistributionConfig,
    ) -> Result<()> {
        // The config remains an instruction argument for ABI compatibility,
        // but monetary policy is not caller-selectable.
        require!(config.validate(), ErrorCode::InvalidDistributionConfig);
        require!(
            ctx.accounts.dung_mint_state.reservation_policy_version
                == DUNG_RESERVATION_POLICY_VERSION,
            ErrorCode::DungReservationPolicyNotMigrated
        );

        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let vault = &mut ctx.accounts.vault;
        let clock = Clock::get()?;
        let current_time = clock.unix_timestamp;

        vault.maybe_advance_empty_settlement_week(&settlement_clock, current_time)?;
        require!(
            settlement_week == vault.open_settlement_week,
            ErrorCode::SettlementWeekOutOfSync
        );
        require!(
            current_time >= settlement_clock.week_finalization_time(settlement_week)?,
            ErrorCode::SettlementWeekNotFinalizable
        );

        require!(
            ctx.accounts.program_config.epochs_per_halving == EPOCHS_PER_HALVING,
            ErrorCode::InvalidProtocolParameters
        );
        let raw_dung = vault.pending_rewards;
        let emission_rate_bps = scheduled_emission_rate_bps(
            settlement_week,
            ctx.accounts.dung_mint_state.last_halving_epoch,
        )?;
        let scheduled_emission =
            checked_mul_div_u64(raw_dung, emission_rate_bps, BASIS_POINTS_DENOMINATOR)?;
        let prior_carry = SettlementBucketShares {
            record_royalty: vault.carry_record_royalty,
            stakers: vault.carry_stakers,
            local_legend: vault.carry_local_legend,
            pol: vault.carry_pol,
            treasury: vault.carry_treasury,
        };
        let prior_staker_carry =
            classify_prior_staker_carry(vault.reward_rate, prior_carry.stakers);
        let emission_plan = plan_settlement_emission(
            &ctx.accounts.dung_mint_state,
            scheduled_emission,
            prior_carry,
            &config,
        )?;
        // Commit the complete new Community share before any payout. Existing
        // carry was reserved when first admitted; direct mints consume the
        // reservation while deferred claims and unavailable-recipient carry
        // retain it.
        ctx.accounts
            .dung_mint_state
            .reserve_community(emission_plan.base_shares.community_total()?)?;
        let base_stakers = emission_plan.base_shares.stakers;
        let record_royalty_total = checked_sum_u64([
            emission_plan.bucket_totals.record_royalty,
            prior_staker_carry.legacy_locked,
        ])?;
        let legend_total = emission_plan.bucket_totals.local_legend;
        let pol_total = emission_plan.bucket_totals.pol;
        let treasury_total = emission_plan.bucket_totals.treasury;

        // Use DUNG_MINT_AUTH_PDA as sole DUNG minting authority
        let program_config = &ctx.accounts.program_config;
        let dung_auth_bump = program_config.dung_mint_auth_bump;
        let dung_auth_seeds = &[DUNG_MINT_AUTH_SEED, &[dung_auth_bump]];
        let signer = &[&dung_auth_seeds[..]];

        // Get keys upfront for validation and instruction building
        let dung_mint_key = ctx.accounts.dung_mint.key();
        let dung_mint_auth_key = ctx.accounts.dung_mint_auth.key();
        let token_program_key = ctx.accounts.token_program.key();

        // Recipient token accounts remain first in remaining_accounts. The
        // program-owned tail must contain every settlement-relevant VaultStake
        // exactly once, including live-zero tombstones, before any mint can occur.
        let (stake_accounts, total_lp, next_staker_count) = pre_scan_settlement_stakes(
            ctx.program_id,
            &token_program_key,
            ctx.remaining_accounts,
            vault.id,
            &settlement_clock,
            settlement_week,
            vault.staker_count,
        )?;
        let eligible_staker_count = u32::try_from(
            stake_accounts
                .iter()
                .filter(|(_, settlement_lp)| *settlement_lp > 0)
                .count(),
        )
        .map_err(|_| ErrorCode::Overflow)?;
        let staker_plan = staker_week_plan(
            base_stakers,
            prior_staker_carry.unlocked_dust,
            eligible_staker_count,
        )?;
        let unlock_pct = staker_plan.unlock_pct;
        let locked_staker_amount = staker_plan.locked_staker_amount;
        let leaderboard_total = checked_sum_u64([record_royalty_total, locked_staker_amount])?;

        let mut leaderboard_distributed = 0u64;
        let mut staker_distributed = 0u64;
        let mut local_legend_distributed = 0u64;
        let mut pol_distributed = 0u64;
        let mut protocol_distributed = 0u64;

        // 1. Distribute base Record Royalty plus this week's policy-locked
        // staker amount to the all-time top 10.
        // remaining_accounts contains: [leaderboard_recipient_atas..., legend_recipient_ata?, vault_stake_pdas...]
        // Uses proportional distribution: if <10 entries, full pot is split proportionally
        let mut remaining_idx = 0usize;
        if leaderboard_total > 0 {
            let leaderboard = &ctx.accounts.vault_leaderboard;
            let num_entries = leaderboard.entries.len().min(10);
            let entry_shares =
                leaderboard_entry_shares(leaderboard_total, &leaderboard.entries[..num_entries])?;

            for (entry, entry_amount) in leaderboard
                .entries
                .iter()
                .take(num_entries)
                .zip(entry_shares)
            {
                let recipient_info = ctx
                    .remaining_accounts
                    .get(remaining_idx)
                    .ok_or(ErrorCode::InvalidMetadata)?;
                remaining_idx += 1;

                // Validate token account manually
                let recipient_data =
                    TokenAccount::try_deserialize(&mut &recipient_info.data.borrow()[..])?;
                require!(
                    recipient_data.owner == entry.user,
                    ErrorCode::InvalidMetadata
                );
                require!(
                    recipient_data.mint == dung_mint_key,
                    ErrorCode::InvalidMetadata
                );

                // Mint to leaderboard recipient using DUNG_MINT_AUTH_PDA
                let mint_ix = spl_mint_to(
                    &token_program_key,
                    &dung_mint_key,
                    recipient_info.key,
                    &dung_mint_auth_key,
                    &[],
                    entry_amount,
                )?;
                invoke_signed(
                    &mint_ix,
                    &[
                        ctx.accounts.dung_mint.to_account_info(),
                        recipient_info.clone(),
                        ctx.accounts.dung_mint_auth.to_account_info(),
                    ],
                    signer,
                )?;

                leaderboard_distributed = checked_sum_u64([leaderboard_distributed, entry_amount])?;

                ctx.accounts
                    .dung_mint_state
                    .consume_community_reservation(entry_amount)?;
            }
        }
        let carry_record_royalty = leaderboard_total
            .checked_sub(leaderboard_distributed)
            .ok_or(ErrorCode::Overflow)?;

        // 2. Distribute to Local Legend (carry within legend bucket if inactive)
        if legend_total > 0 {
            if let Some(legend) = ctx.accounts.local_legend.as_mut() {
                let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;

                // Only distribute if legend is active and term hasn't expired
                if legend.is_active
                    && !legend.is_term_expired(current_epoch)
                    && legend.holder != Pubkey::default()
                {
                    let legend_recipient_info = ctx
                        .remaining_accounts
                        .get(remaining_idx)
                        .ok_or(ErrorCode::InvalidMetadata)?;
                    // Validate token account manually
                    let legend_recipient_data = TokenAccount::try_deserialize(
                        &mut &legend_recipient_info.data.borrow()[..],
                    )?;
                    require!(
                        legend_recipient_data.owner == legend.holder,
                        ErrorCode::InvalidMetadata
                    );
                    require!(
                        legend_recipient_data.mint == dung_mint_key,
                        ErrorCode::InvalidMetadata
                    );

                    // Mint to legend using DUNG_MINT_AUTH_PDA
                    let mint_ix = spl_mint_to(
                        &token_program_key,
                        &dung_mint_key,
                        legend_recipient_info.key,
                        &dung_mint_auth_key,
                        &[],
                        legend_total,
                    )?;
                    invoke_signed(
                        &mint_ix,
                        &[
                            ctx.accounts.dung_mint.to_account_info(),
                            legend_recipient_info.clone(),
                            ctx.accounts.dung_mint_auth.to_account_info(),
                        ],
                        signer,
                    )?;

                    local_legend_distributed = legend_total;
                    legend.total_earned = legend
                        .total_earned
                        .checked_add(legend_total)
                        .ok_or(ErrorCode::Overflow)?;
                    ctx.accounts
                        .dung_mint_state
                        .consume_community_reservation(legend_total)?;
                }
            }
        }
        let carry_local_legend = legend_total
            .checked_sub(local_legend_distributed)
            .ok_or(ErrorCode::Overflow)?;

        // 3. Allocate to the LP snapshot for this Settlement Week. Current LP
        // can be zero after a mid-week full exit, so supplied tombstones still
        // participate until their pending zero target becomes effective.
        for (mut stake, settlement_lp) in stake_accounts {
            let allocation = if staker_plan.staker_distributable > 0 && total_lp > 0 {
                staker_lp_share(staker_plan.staker_distributable, settlement_lp, total_lp)?
            } else {
                0
            };
            if allocation > 0 {
                stake.rewards_earned = stake
                    .rewards_earned
                    .checked_add(allocation)
                    .ok_or(ErrorCode::Overflow)?;
                staker_distributed = checked_sum_u64([staker_distributed, allocation])?;
                emit!(StakerAllocation {
                    vault_id: vault.id,
                    epoch: settlement_week,
                    staker: stake.user,
                    amount: allocation,
                    lp_tokens: settlement_lp,
                    eligible_from_epoch: settlement_week,
                    timestamp: current_time,
                });
            }
            stake.exit(ctx.program_id)?;
        }
        let carry_stakers = staker_carry_after(staker_plan, staker_distributed)?;

        // 4. Distribute to POL (5%, protocol-owned liquidity)
        if pol_total > 0 {
            let dung_mint_state = &mut ctx.accounts.dung_mint_state;
            require!(
                dung_mint_state.can_mint(pol_total, AllocationBucket::Pol),
                ErrorCode::SupplyCapReached
            );

            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.pol_account.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    signer,
                ),
                pol_total,
            )?;

            pol_distributed = pol_total;
            dung_mint_state.record_mint(pol_total, AllocationBucket::Pol)?;
        }
        let carry_pol = pol_total
            .checked_sub(pol_distributed)
            .ok_or(ErrorCode::Overflow)?;

        // 5. Distribute to Protocol Treasury (10%)
        if treasury_total > 0 {
            let dung_mint_state = &mut ctx.accounts.dung_mint_state;
            require!(
                dung_mint_state.can_mint(treasury_total, AllocationBucket::Treasury),
                ErrorCode::SupplyCapReached
            );

            token::mint_to(
                CpiContext::new_with_signer(
                    ctx.accounts.token_program.to_account_info(),
                    MintTo {
                        mint: ctx.accounts.dung_mint.to_account_info(),
                        to: ctx.accounts.protocol_treasury.to_account_info(),
                        authority: ctx.accounts.dung_mint_auth.to_account_info(),
                    },
                    signer,
                ),
                treasury_total,
            )?;

            protocol_distributed = treasury_total;
            dung_mint_state.record_mint(treasury_total, AllocationBucket::Treasury)?;
        }
        let carry_treasury = treasury_total
            .checked_sub(protocol_distributed)
            .ok_or(ErrorCode::Overflow)?;

        let total_distributed = leaderboard_distributed
            .checked_add(staker_distributed)
            .ok_or(ErrorCode::Overflow)?
            .checked_add(local_legend_distributed)
            .ok_or(ErrorCode::Overflow)?
            .checked_add(pol_distributed)
            .ok_or(ErrorCode::Overflow)?
            .checked_add(protocol_distributed)
            .ok_or(ErrorCode::Overflow)?;

        let has_future_capacity = settlement_base_fits(
            1,
            &settlement_supply_headroom(&ctx.accounts.dung_mint_state)?,
            &config,
        )?;
        if emission_rate_bps > 0 {
            let observed = ctx.accounts.dung_mint_state.current_emission_rate_bps;
            ctx.accounts.dung_mint_state.current_emission_rate_bps = if observed == 0 {
                emission_rate_bps
            } else {
                observed.min(emission_rate_bps)
            };
        }

        if emission_plan.cap_limited {
            emit!(EmissionCapApplied {
                vault_id: vault.id,
                settlement_week,
                emission_rate_bps,
                scheduled_emission,
                admitted_base_emission: emission_plan.base_emission,
                terminal: emission_plan.terminal || !has_future_capacity,
                timestamp: current_time,
            });
        }

        vault.total_dung_emitted = vault
            .total_dung_emitted
            .checked_add(total_distributed)
            .ok_or(ErrorCode::Overflow)?;
        vault.carry_record_royalty = carry_record_royalty;
        vault.carry_stakers = carry_stakers;
        vault.carry_local_legend = carry_local_legend;
        vault.carry_pol = carry_pol;
        vault.carry_treasury = carry_treasury;
        vault.staker_count = next_staker_count;
        vault.reward_rate = STAKER_REMAINDER_POLICY_MARKER;
        vault.roll_to_next_settlement_week()?;

        emit!(StakerRemainderPolicyApplied {
            vault_id: vault.id,
            settlement_week,
            policy_version: STAKER_REMAINDER_POLICY_VERSION,
            current_locked_reallocated: locked_staker_amount,
            legacy_carry_reallocated: prior_staker_carry.legacy_locked,
            timestamp: current_time,
        });

        emit!(EpochRewardsDistributed {
            vault_id: vault.id,
            epoch: settlement_week,
            total_distributed,
            leaderboard_distributed,
            staker_distributed,
            local_legend_distributed,
            pol_distributed,
            protocol_distributed,
            staker_count: eligible_staker_count,
            unlock_pct,
            locked_staker_amount,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    // =====================================================
    // LOCAL LEGEND INSTRUCTIONS
    // =====================================================

    /// Grow a legacy Local Legend account to the explicit bootstrap layout.
    /// Admin-only and idempotent; callers cannot choose the inferred state.
    pub fn migrate_local_legend(ctx: Context<MigrateLocalLegend>, vault_id: u64) -> Result<()> {
        let outcome = migrate_local_legend_layout(
            &ctx.accounts.local_legend.to_account_info(),
            vault_id,
            ctx.bumps.local_legend,
            &ctx.accounts.payer.to_account_info(),
            &ctx.accounts.system_program.to_account_info(),
        )?;

        emit!(LocalLegendMigrated {
            authority: ctx.accounts.authority.key(),
            vault_id,
            old_size: u32::try_from(outcome.old_size).map_err(|_| ErrorCode::Overflow)?,
            new_size: u32::try_from(outcome.new_size).map_err(|_| ErrorCode::Overflow)?,
            is_bootstrap: outcome.is_bootstrap,
            migrated: outcome.migrated,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Elect a new Local Legend for a vault
    /// Called by backend after computing election results off-chain
    /// Elections happen every 8 epochs based on most completions
    pub fn elect_local_legend(
        ctx: Context<ElectLocalLegend>,
        winner_completions: u32,
        runner_up: Pubkey,
        runner_up_completions: u32,
        term_start_epoch: u64,
    ) -> Result<()> {
        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        let term_epochs = ctx.accounts.program_config.local_legend_term_epochs;
        let term_end_epoch = next_local_legend_term_end(
            &ctx.accounts.local_legend,
            term_start_epoch,
            current_epoch,
            term_epochs,
        )?;
        let election_period = LocalLegend::election_period_for_epoch(term_start_epoch, term_epochs);

        let legend = &mut ctx.accounts.local_legend;
        let vault = &ctx.accounts.vault;

        // Initialize if first election
        if legend.vault_id == 0 {
            legend.vault_id = vault.id;
            legend.bump = ctx.bumps.local_legend;
        }

        // Record election results
        legend.holder = ctx.accounts.winner.key();
        legend.election_period = election_period;
        legend.term_start_epoch = term_start_epoch;
        legend.term_end_epoch = term_end_epoch;
        legend.completions_at_election = winner_completions;
        legend.runner_up = runner_up;
        legend.runner_up_completions = runner_up_completions;
        legend.is_active = true;
        legend.is_bootstrap = false;

        emit!(LocalLegendElected {
            vault_id: vault.id,
            winner: ctx.accounts.winner.key(),
            winner_completions,
            runner_up,
            runner_up_completions,
            election_period,
            term_start_epoch: legend.term_start_epoch,
            term_end_epoch: legend.term_end_epoch,
            is_bootstrap: false,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Resign from Local Legend position
    /// Allows current legend to step down before term ends
    pub fn resign_local_legend(ctx: Context<ResignLocalLegend>) -> Result<()> {
        let clock = Clock::get()?;
        let legend = &mut ctx.accounts.local_legend;

        require!(
            ctx.accounts.legend_holder.key() == legend.holder,
            ErrorCode::UnauthorizedAuthority
        );

        legend.is_active = false;

        emit!(LocalLegendResigned {
            vault_id: legend.vault_id,
            holder: legend.holder,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Mark the Local Legend seat dormant for the next term when no rider is eligible.
    /// Callable by the backend election scheduler after the current term expires.
    pub fn deactivate_local_legend(
        ctx: Context<DeactivateLocalLegend>,
        term_start_epoch: u64,
    ) -> Result<()> {
        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        let term_epochs = ctx.accounts.program_config.local_legend_term_epochs;
        let term_end_epoch = next_local_legend_term_end(
            &ctx.accounts.local_legend,
            term_start_epoch,
            current_epoch,
            term_epochs,
        )?;
        let election_period = LocalLegend::election_period_for_epoch(term_start_epoch, term_epochs);
        let legend = &mut ctx.accounts.local_legend;

        let previous_holder = legend.holder;
        legend.election_period = election_period;
        legend.term_start_epoch = term_start_epoch;
        legend.term_end_epoch = term_end_epoch;
        legend.completions_at_election = 0;
        legend.runner_up = Pubkey::default();
        legend.runner_up_completions = 0;
        legend.is_active = false;
        legend.is_bootstrap = false;

        emit!(LocalLegendDormant {
            vault_id: ctx.accounts.vault.id,
            previous_holder,
            election_period,
            term_start_epoch: legend.term_start_epoch,
            term_end_epoch: legend.term_end_epoch,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    // =========================================================================
    // VAULT ACTIVATION LIFECYCLE (admin-only historical seeding)
    // =========================================================================

    /// Seed a vault's completion summary with absolute historical values.
    /// Unlike canonical record_climb_completion_v2 writes, this sets exact values.
    /// Only callable by backend authority while vault is not yet activated.
    pub fn admin_seed_vault_completion_summary(
        ctx: Context<AdminSeedVaultCompletionSummary>,
        total_completions: u64,
        best_time_s: u32,
        best_time_holder: Pubkey,
    ) -> Result<()> {
        let activation = &ctx.accounts.vault_activation;
        require!(!activation.is_active, ErrorCode::VaultAlreadyActive);

        let vault = &mut ctx.accounts.vault;
        vault.total_completions = total_completions;

        // Set KOM if a valid best time is provided
        if best_time_s > 0 && best_time_holder != Pubkey::default() {
            vault.kom_holder = best_time_holder;
            vault.kom_time_s = best_time_s;
        }

        let clock = Clock::get()?;
        let activation = &mut ctx.accounts.vault_activation;
        activation.seed_completions_written = activation
            .seed_completions_written
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        activation.last_seed_at = clock.unix_timestamp;

        Ok(())
    }

    /// Replace a vault's leaderboard with exact historical entries.
    /// Overwrites the entire leaderboard (absolute, not delta).
    /// Only callable by backend authority while vault is not yet activated.
    pub fn admin_replace_vault_leaderboard(
        ctx: Context<AdminReplaceVaultLeaderboard>,
        entries: Vec<LeaderEntry>,
    ) -> Result<()> {
        let activation = &ctx.accounts.vault_activation;
        require!(!activation.is_active, ErrorCode::VaultAlreadyActive);
        require!(
            entries.len() <= VaultLeaderboard::MAX_ENTRIES,
            ErrorCode::InvalidBatchSize
        );

        let leaderboard = &mut ctx.accounts.vault_leaderboard;
        let vault = &ctx.accounts.vault;

        if leaderboard.vault_id == 0 {
            leaderboard.vault_id = vault.id;
            leaderboard.bump = ctx.bumps.vault_leaderboard;
        }

        // Absolute replacement with the same canonical order as live writes.
        // Original ride time only bounds membership at the ten-seat edge;
        // equal seated times still share rank and pooled payouts.
        leaderboard.entries = entries;
        leaderboard.canonicalize_entries();

        let clock = Clock::get()?;
        leaderboard.last_updated = leaderboard
            .entries
            .iter()
            .map(|entry| entry.recorded_at)
            .max()
            .unwrap_or(clock.unix_timestamp);

        let activation = &mut ctx.accounts.vault_activation;
        activation.leaderboard_seeded = true;
        activation.last_seed_at = clock.unix_timestamp;

        Ok(())
    }

    /// Activate a vault after authoritative historical seeding is complete.
    /// Generation 2+ enables receipt-backed completion, staking, and smoke rewards.
    /// This is a one-way operation — vaults cannot be deactivated.
    #[allow(clippy::too_many_arguments)]
    pub fn admin_activate_vault(
        ctx: Context<AdminActivateVault>,
        vault_id: u64,
        total_completions: u64,
        kom_holder: Pubkey,
        kom_time_s: u32,
        kom_recorded_at: i64,
        seed_generation: u32,
        seed_cutoff_at: i64,
        matched_users: u32,
        matched_completions: u32,
        evidence_hash: [u8; 32],
    ) -> Result<()> {
        let activation = &mut ctx.accounts.vault_activation;
        require!(!activation.is_active, ErrorCode::VaultAlreadyActive);
        require!(evidence_hash != [0; 32], ErrorCode::InvalidRideAttestation);
        require!(
            is_authoritative_vault_seed_generation(seed_generation),
            ErrorCode::InvalidActivationSeed
        );
        require!(seed_cutoff_at > 0, ErrorCode::InvalidActivationSeed);
        require!(
            matched_completions as u64 == total_completions,
            ErrorCode::InvalidActivationSeed
        );
        require!(
            matched_users <= matched_completions,
            ErrorCode::InvalidActivationSeed
        );

        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;
        let current_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        let vault = &mut ctx.accounts.vault;
        require!(vault.id == vault_id, ErrorCode::InvalidVault);

        vault.total_completions = total_completions;
        if kom_time_s > 0 && kom_holder != Pubkey::default() {
            vault.kom_holder = kom_holder;
            vault.kom_time_s = kom_time_s;
            vault.kom_set_epoch = if kom_recorded_at >= LEGACY_SETTLEMENT_WEEK_ANCHOR {
                settlement_clock.week_at(kom_recorded_at)?
            } else {
                0
            };
        } else {
            require!(kom_time_s == 0, ErrorCode::InvalidAmount);
            require!(kom_holder == Pubkey::default(), ErrorCode::InvalidVault);
            vault.kom_holder = Pubkey::default();
            vault.kom_time_s = 0;
            vault.kom_set_epoch = 0;
        }

        activation.is_active = true;
        activation.seed_generation = seed_generation;
        activation.seed_cutoff_at = seed_cutoff_at;
        activation.activated_at = clock.unix_timestamp;
        activation.economics_start_epoch = current_epoch;
        activation.matched_users = matched_users;
        activation.matched_completions = matched_completions;
        activation.evidence_hash = evidence_hash;

        emit!(VaultActivated {
            vault_id: vault.id,
            seed_generation,
            seed_cutoff_at,
            activated_at: activation.activated_at,
            economics_start_epoch: current_epoch,
            matched_users,
            matched_completions,
            evidence_hash,
            seed_completions_written: activation.seed_completions_written,
            leaderboard_seeded: activation.leaderboard_seeded,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }

    /// Backfill activation PDA for vaults created before Phase B.
    /// Creates the activation account and immediately sets is_active = true.
    /// One-shot per vault: init constraint prevents replay. Admin-only.
    /// Takes vault_id as arg to avoid deserializing legacy vault accounts.
    pub fn admin_backfill_vault_activation(
        ctx: Context<AdminBackfillVaultActivation>,
        vault_id: u64,
    ) -> Result<()> {
        // Verify the vault account exists and is owned by this program
        let vault_info = &ctx.accounts.vault;
        require!(vault_info.owner == ctx.program_id, ErrorCode::InvalidVault);
        require!(!vault_info.data_is_empty(), ErrorCode::InvalidVault);

        // Verify vault PDA seeds match the provided vault_id
        let (expected_vault_pda, _) =
            Pubkey::find_program_address(&[VAULT_SEED, &vault_id.to_le_bytes()], ctx.program_id);
        require!(
            vault_info.key() == expected_vault_pda,
            ErrorCode::InvalidVault
        );

        let clock = Clock::get()?;
        let settlement_clock = ctx.accounts.program_config.settlement_clock()?;

        let activation = &mut ctx.accounts.vault_activation;
        activation.vault_id = vault_id;
        activation.is_active = true;
        activation.seed_completions_written = 0;
        activation.leaderboard_seeded = false;
        activation.created_at = clock.unix_timestamp;
        activation.activated_at = clock.unix_timestamp;
        activation.last_seed_at = 0;
        activation.seed_generation = 0;
        activation.seed_cutoff_at = clock.unix_timestamp;
        activation.economics_start_epoch = settlement_clock.week_at(clock.unix_timestamp)?;
        activation.matched_users = 0;
        activation.matched_completions = 0;
        activation.evidence_hash = [0; 32];
        activation.bump = ctx.bumps.vault_activation;

        emit!(VaultActivated {
            vault_id,
            seed_generation: 0,
            seed_cutoff_at: activation.seed_cutoff_at,
            activated_at: activation.activated_at,
            economics_start_epoch: activation.economics_start_epoch,
            matched_users: 0,
            matched_completions: 0,
            evidence_hash: [0; 32],
            seed_completions_written: 0,
            leaderboard_seeded: false,
            timestamp: clock.unix_timestamp,
        });

        Ok(())
    }
    pub fn refresh_stage1_rate(ctx: Context<Stage1RefreshRate>) -> Result<()> {
        stage1::refresh_provider(ctx)
    }
    pub fn record_stage1_provider_outage(ctx: Context<Stage1RefreshRate>) -> Result<()> {
        stage1::record_provider_outage(ctx)
    }

    pub fn set_stage1_publisher(ctx: Context<Stage1SetPublisher>, publisher: Pubkey) -> Result<()> {
        require!(publisher == Pubkey::default() || (publisher != ctx.accounts.city.guardian && publisher != ctx.accounts.city.registrar), ErrorCode::Stage1InvalidGuardian);
        stage1_claims::set_publisher(ctx, publisher)
    }
    pub fn init_stage1_settlement(ctx: Context<Stage1InitSettlement>) -> Result<()> { stage1_claims::init_settlement(ctx) }
    pub fn skip_stage1_empty_weeks(ctx: Context<Stage1SkipEmpty>, through: u64) -> Result<()> { stage1_claims::skip_empty(ctx, through) }
    pub fn open_stage1_week(ctx: Context<Stage1OpenWeek>, week: u64) -> Result<()> { stage1_claims::open_week(ctx, week) }
    pub fn register_stage1_recipient(ctx: Context<Stage1RegisterRecipient>, recipient: Pubkey) -> Result<()> { stage1_claims::register_recipient(ctx, recipient) }
    pub fn freeze_stage1_snapshot(ctx: Context<Stage1FreezeSnapshot>, snapshot: [u8; 32], cap: u64) -> Result<()> { stage1_claims::freeze_snapshot(ctx, snapshot, cap) }
    pub fn prepare_stage1_hold(ctx: Context<Stage1PrepareHold>, remaining: [u64; 5]) -> Result<()> { stage1_claims::prepare_hold(ctx, remaining) }
    pub fn expire_stage1_hold(ctx: Context<Stage1ExpireHold>, week: u64) -> Result<()> { stage1_claims::expire_hold(ctx, week) }
    pub fn publish_stage1_claim_set(ctx: Context<Stage1Publish>, root: [u8; 32], total: u128, leaf_count: u32, new_holds: [u64; 5]) -> Result<()> { stage1_claims::publish(ctx, root, total, leaf_count, new_holds) }
    pub fn prepare_stage1_claim_set(ctx: Context<Stage1PrepareClaims>, leaf_count: u32) -> Result<()> { stage1_claims::prepare_claim_set(ctx, leaf_count) }
    pub fn claim_stage1_batch(ctx: Context<Stage1ClaimBatch>, person: Pubkey, leaves: Vec<Stage1CashBatchLeaf>) -> Result<()> { stage1_claims::claim_batch(ctx, person, leaves) }
    pub fn claim_stage1(ctx: Context<Stage1Claim>, index: u32, person: Pubkey, amount: u64, proof: Vec<Stage1SumNode>, terms: Stage1ClaimTerms) -> Result<()> { stage1_claims::claim(ctx, index, person, amount, proof, terms) }
    pub fn close_stage1_claim_set(ctx: Context<Stage1CloseClaims>) -> Result<()> { stage1_claims::close_claim_set(ctx) }
    pub fn close_stage1_dung_claim_set(ctx: Context<Stage1CloseDungClaims>) -> Result<()> { stage1_dung::close_claim_set(ctx) }
    pub fn close_stage1_week_funding(ctx: Context<Stage1CloseWeekFunding>) -> Result<()> { stage1_claims::close_week_funding(ctx) }
    pub fn close_stage1_dung_mint(ctx: Context<Stage1CloseDungMint>) -> Result<()> { stage1_dung::close_mint(ctx) }
    pub fn set_stage1_guardian(ctx: Context<Stage1AdminGovernance>, guardian: Pubkey) -> Result<()> { stage1_governance::set_guardian(ctx, guardian) }
    pub fn set_stage1_registrar(ctx: Context<Stage1AdminGovernance>, registrar: Pubkey) -> Result<()> { stage1_governance::set_registrar(ctx, registrar) }
    pub fn pause_stage1_intake(ctx: Context<Stage1PauseIntake>) -> Result<()> { stage1_governance::pause(ctx) }
    pub fn resume_stage1_intake(ctx: Context<Stage1ResumeGovernance>) -> Result<()> { stage1_governance::resume(ctx) }
    pub fn pause_stage1_settlement(ctx: Context<Stage1PauseIntake>) -> Result<()> { stage1_governance::pause_settlement(ctx) }
    pub fn resume_stage1_settlement(ctx: Context<Stage1ResumeGovernance>) -> Result<()> { stage1_governance::resume_settlement(ctx) }
    pub fn migrate_stage1_city(ctx: Context<Stage1MigrateCity>) -> Result<()> { stage1_governance::migrate_city(ctx) }
    pub fn register_stage1_cash(ctx: Context<Stage1RegisterCash>) -> Result<()> { stage1_sponsor::register_cash(ctx) }
    pub fn sponsor_stage1(ctx: Context<Stage1Sponsor>, amount: u64) -> Result<()> { stage1_sponsor::sponsor(ctx, amount) }
    pub fn post_stage1_boost<'info>(ctx: Context<'_, '_, 'info, 'info, Stage1PostBoost<'info>>, id: [u8; 32], total: u64, start_week: u64, weeks: u8) -> Result<()> { stage1_sponsor::post_boost(ctx, id, total, start_week, weeks) }
    pub fn process_stage1_boost(ctx: Context<Stage1ProcessBoost>, remaining: [[u64; 5]; 13]) -> Result<()> { stage1_sponsor::process_boost(ctx, remaining) }
    pub fn publish_stage1_dung(ctx: Context<Stage1PublishDung>, week: u64, input: Stage1DungInput) -> Result<()> { stage1_dung::publish(ctx, week, input) }
    pub fn configure_stage1_dung(ctx: Context<Stage1SetPublisher>, tss_ceiling_micros: u64, start_week: Option<u64>) -> Result<()> { stage1_dung::configure(ctx, tss_ceiling_micros, start_week) }
    pub fn publish_stage1_dung_claim_set(ctx: Context<Stage1PublishDungClaims>, role: u8, root: Stage1DungRoot) -> Result<()> { stage1_dung::publish_claim_set(ctx, role, root) }
    pub fn skip_stage1_dung_weeks(ctx: Context<Stage1SkipDung>, through: u64, snapshot: [u8; 32], max_field_count: u32, total_postbond_tss_micros: u128) -> Result<()> { stage1_dung::skip_weeks(ctx, through, snapshot, max_field_count, total_postbond_tss_micros) }
    pub fn claim_stage1_dung(ctx: Context<Stage1ClaimDung>, index: u32, person: Pubkey, amount: u64, proof: Vec<Stage1SumNode>) -> Result<()> { stage1_dung::claim(ctx, index, person, amount, proof) }
    pub fn prepare_stage1_dung_claim_set(ctx: Context<Stage1PrepareDungClaims>, role: u8, leaf_count: u32) -> Result<()> { stage1_dung::prepare_claim_set(ctx, role, leaf_count) }
    pub fn claim_stage1_dung_batch(ctx: Context<Stage1ClaimDungBatch>, person: Pubkey, leaves: Vec<Stage1BatchLeaf>) -> Result<()> { stage1_dung::claim_batch(ctx, person, leaves) }

}

#[cfg(test)]
mod leaderboard_prefund_tests;

#[cfg(test)]
mod tests;
