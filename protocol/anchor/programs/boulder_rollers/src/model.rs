//! Account layouts and the plain types they carry.

use crate::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SettlementClock {
    pub(crate) v2_starts_at: i64,
}

impl SettlementClock {
    pub fn v2_only() -> Self {
        Self {
            v2_starts_at: SETTLEMENT_WEEK_V2_ANCHOR,
        }
    }

    pub fn with_legacy_cutover(v2_starts_at: i64) -> Result<Self> {
        require!(
            v2_starts_at > SETTLEMENT_WEEK_V2_ANCHOR,
            ErrorCode::InvalidSettlementClockCutover
        );
        require!(
            (v2_starts_at - SETTLEMENT_WEEK_V2_ANCHOR) % EPOCH_DURATION_SECONDS == 0,
            ErrorCode::InvalidSettlementClockCutover
        );

        let clock = Self { v2_starts_at };
        let transition_week = clock
            .transition_week()?
            .ok_or(ErrorCode::InvalidSettlementClockCutover)?;
        require!(
            Self::week_from_anchor(v2_starts_at - 1, LEGACY_SETTLEMENT_WEEK_ANCHOR)
                == transition_week,
            ErrorCode::InvalidSettlementClockCutover
        );
        Ok(clock)
    }

    pub fn v2_starts_at(&self) -> i64 {
        self.v2_starts_at
    }

    pub fn transition_week(&self) -> Result<Option<u64>> {
        if self.v2_starts_at == SETTLEMENT_WEEK_V2_ANCHOR {
            return Ok(None);
        }
        require!(
            self.v2_starts_at > SETTLEMENT_WEEK_V2_ANCHOR
                && (self.v2_starts_at - SETTLEMENT_WEEK_V2_ANCHOR) % EPOCH_DURATION_SECONDS == 0,
            ErrorCode::InvalidSettlementClockCutover
        );
        Ok(Some(Self::week_from_anchor(
            self.v2_starts_at,
            SETTLEMENT_WEEK_V2_ANCHOR,
        )))
    }

    pub fn week_at(&self, timestamp: i64) -> Result<u64> {
        if self.transition_week()?.is_some() && timestamp < self.v2_starts_at {
            return Ok(Self::week_from_anchor(
                timestamp,
                LEGACY_SETTLEMENT_WEEK_ANCHOR,
            ));
        }
        Ok(Self::week_from_anchor(timestamp, SETTLEMENT_WEEK_V2_ANCHOR))
    }

    pub fn week_start(&self, week: u64) -> Result<i64> {
        let anchor = match self.transition_week()? {
            Some(transition_week) if week <= transition_week => LEGACY_SETTLEMENT_WEEK_ANCHOR,
            _ => SETTLEMENT_WEEK_V2_ANCHOR,
        };
        Self::timestamp_from_anchor(anchor, week)
    }

    pub fn week_end(&self, week: u64) -> Result<i64> {
        if self.transition_week()? == Some(week) {
            return Self::timestamp_from_anchor(
                SETTLEMENT_WEEK_V2_ANCHOR,
                week.checked_add(1).ok_or(ErrorCode::Overflow)?,
            );
        }
        self.week_start(week)?
            .checked_add(EPOCH_DURATION_SECONDS)
            .ok_or(ErrorCode::Overflow.into())
    }

    pub fn week_finalization_time(&self, week: u64) -> Result<i64> {
        self.week_end(week)?
            .checked_add(SETTLEMENT_FINALIZATION_GRACE_SECONDS)
            .ok_or(ErrorCode::Overflow.into())
    }

    /// Latest week whose handoff and finalization grace have both elapsed.
    pub fn latest_finalizable_week(&self, timestamp: i64) -> Result<u64> {
        let previous_week = self.week_at(timestamp)?.saturating_sub(1);
        if timestamp >= self.week_finalization_time(previous_week)? {
            Ok(previous_week)
        } else {
            Ok(previous_week.saturating_sub(1))
        }
    }

    pub fn is_week_start(&self, timestamp: i64) -> Result<bool> {
        let week = self.week_at(timestamp)?;
        Ok(self.week_start(week)? == timestamp)
    }

    pub fn anchor_version_at(&self, timestamp: i64) -> Result<u8> {
        Ok(
            if self.transition_week()?.is_some() && timestamp < self.v2_starts_at {
                1
            } else {
                SETTLEMENT_CLOCK_VERSION_V2
            },
        )
    }

    pub(crate) fn week_from_anchor(timestamp: i64, anchor: i64) -> u64 {
        if timestamp < anchor {
            return 0;
        }
        ((timestamp - anchor) / EPOCH_DURATION_SECONDS) as u64
    }

    pub(crate) fn timestamp_from_anchor(anchor: i64, week: u64) -> Result<i64> {
        let week = i64::try_from(week).map_err(|_| ErrorCode::Overflow)?;
        anchor
            .checked_add(
                week.checked_mul(EPOCH_DURATION_SECONDS)
                    .ok_or(ErrorCode::Overflow)?,
            )
            .ok_or(ErrorCode::Overflow.into())
    }
}

// ============================================================================
// DISTRIBUTION CONFIG (Tokenomics V2)
// ============================================================================

/// Canonical distribution configuration (TOKENOMICS_V2).
///
/// The value remains in the instruction ABI for compatibility, but the program
/// accepts only this exact policy.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct DistributionConfig {
    pub leaderboard_share_bps: u64,  // 5500 = 55%
    pub staker_share_bps: u64,       // 2700 = 27%
    pub local_legend_share_bps: u64, // 300 = 3% (single elected legend)
    pub pol_share_bps: u64,          // 500 = 5% (protocol-owned liquidity)
    pub protocol_fee_bps: u64,       // 1000 = 10%
}

impl DistributionConfig {
    pub const fn canonical() -> Self {
        Self {
            leaderboard_share_bps: 5_500,
            staker_share_bps: 2_700,
            local_legend_share_bps: 300,
            pol_share_bps: 500,
            protocol_fee_bps: 1_000,
        }
    }

    pub fn validate(&self) -> bool {
        *self == Self::canonical()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SettlementBucketShares {
    pub(crate) record_royalty: u64,
    pub(crate) stakers: u64,
    pub(crate) local_legend: u64,
    pub(crate) pol: u64,
    pub(crate) treasury: u64,
}

impl SettlementBucketShares {
    pub(crate) fn total(&self) -> Result<u64> {
        checked_sum_u64([
            self.record_royalty,
            self.stakers,
            self.local_legend,
            self.pol,
            self.treasury,
        ])
    }

    pub(crate) fn community_total(&self) -> Result<u64> {
        checked_sum_u64([self.record_royalty, self.stakers, self.local_legend])
    }

    pub(crate) fn checked_add(&self, other: &Self) -> Result<Self> {
        Ok(Self {
            record_royalty: checked_sum_u64([self.record_royalty, other.record_royalty])?,
            stakers: checked_sum_u64([self.stakers, other.stakers])?,
            local_legend: checked_sum_u64([self.local_legend, other.local_legend])?,
            pol: checked_sum_u64([self.pol, other.pol])?,
            treasury: checked_sum_u64([self.treasury, other.treasury])?,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SettlementSupplyHeadroom {
    pub(crate) total: u64,
    pub(crate) community: u64,
    pub(crate) pol: u64,
    pub(crate) treasury: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct SettlementEmissionPlan {
    pub(crate) base_emission: u64,
    pub(crate) base_shares: SettlementBucketShares,
    pub(crate) bucket_totals: SettlementBucketShares,
    pub(crate) cap_limited: bool,
    pub(crate) terminal: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct StakeLpTransition {
    pub(crate) lp_to_mint: u64,
    pub(crate) next_lp_tokens: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct LpCustodyRestoration {
    pub(crate) next_amount: u64,
    pub(crate) sealed: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct UnstakeAccountingTransition {
    pub(crate) next_lp_tokens: u64,
    pub(crate) cal_to_return: u64,
    pub(crate) exit_fee: u64,
    pub(crate) cal_after_fee: u64,
    pub(crate) next_cal_staked: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct StakerWeekPlan {
    pub(crate) unlock_pct: u8,
    pub(crate) weekly_unlocked: u64,
    pub(crate) staker_distributable: u64,
    pub(crate) locked_staker_amount: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct PriorStakerCarry {
    pub(crate) unlocked_dust: u64,
    pub(crate) legacy_locked: u64,
}

/// Protocol parameters stored in ProgramConfig.
///
/// The top-level constants remain the default launch values. ProgramConfig
/// stores the live values so future governance updates do not require a
/// program upgrade for routine economic tuning. The emission interval is an
/// immutable monetary-policy constant even though it remains in this legacy
/// aggregate ABI.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy)]
pub struct ProtocolParameters {
    pub vault_creation_dung: u64,
    pub vault_creation_cal: u64,
    pub harvest_fee_bps: u64,
    pub minter_rights_epochs: u64,
    pub local_legend_term_epochs: u64,
    pub epochs_per_halving: u64,
}

impl ProtocolParameters {
    pub fn defaults() -> Self {
        Self {
            vault_creation_dung: VAULT_CREATION_DUNG,
            vault_creation_cal: VAULT_CREATION_CAL,
            harvest_fee_bps: HARVEST_FEE_BPS,
            minter_rights_epochs: MINTER_RIGHTS_EPOCHS,
            local_legend_term_epochs: LOCAL_LEGEND_TERM_EPOCHS,
            epochs_per_halving: EPOCHS_PER_HALVING,
        }
    }

    pub fn validate(&self) -> bool {
        self.vault_creation_dung > 0
            && self.vault_creation_cal > 0
            && self.harvest_fee_bps <= 10_000
            && self.minter_rights_epochs > 0
            && self.local_legend_term_epochs > 0
            && self.epochs_per_halving == EPOCHS_PER_HALVING
    }
}

/// Record continuity carried by a canon successor.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecordContinuityPolicy {
    /// Genesis climbs and material boundary revisions open a fresh Record Board.
    NewRecordBoard,
    /// Minor canon corrections preserve the predecessor's records.
    CarryRecordsForward,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub struct RegisterRatifiedClimbArgs {
    /// SHA-256 of the exact D12 commitment. This is repeated as an argument so
    /// Anchor can derive the PDA, then verified against program-built bytes.
    pub commitment_hash: [u8; 32],
    pub canon_id: [u8; 16],
    pub canon_version: u16,
    pub canonical_profile_hash: [u8; 32],
    pub name: String,
    pub vert_m: u32,
    pub distance_m: u32,
    pub avg_gradient_pct: u16,
    pub record_continuity_policy: RecordContinuityPolicy,
}

// --------------------- Accounts ---------------------

#[account]
pub struct UserState {
    pub owner: Pubkey,
    /// Legacy pre-TGE CAL counter retained only for backward compatibility.
    /// Live CAL balances come from SPL token accounts.
    pub legacy_cal_snapshot: u64,
    /// Legacy daily CAL counter retained for historical replay/UI context only.
    pub legacy_cal_earned_today: u64,
    /// Legacy timestamp for the last points-period CAL mint.
    pub legacy_last_cal_mint: i64,
    pub total_rides: u64,
    pub total_tss: u64,
    pub bio_score: u16,
    pub bump: u8,
}

impl UserState {
    pub const SIZE: usize = 8 + 32 + 8 + 8 + 8 + 8 + 8 + 2 + 1;
}

/// Soulbound rider identity and lifetime effort metrics.
/// PDA: [RIDER_SOUL_SEED, rider]
#[account]
pub struct RiderSoul {
    pub rider: Pubkey,
    pub created_at: i64,
    pub total_rides: u64,
    pub total_tss: u64,
    pub total_distance_m: u64,
    pub total_vert_m: u64,
    pub total_cal_earned: u64,
    pub archetype: u8,
    pub bio_score: u64,
    pub climb_card: Option<Pubkey>,
    pub steady_card: Option<Pubkey>,
    pub explorer_card: Option<Pubkey>,
    pub bump: u8,
}

impl RiderSoul {
    pub const SIZE: usize =
        8 + 32 + 8 + 8 + 8 + 8 + 8 + 8 + 1 + 8 + (1 + 32) + (1 + 32) + (1 + 32) + 1;
}

/// Canonical ride attestation used to anchor all ride-driven economics.
/// PDA: [RIDE_ATTESTATION_SEED, rider, ride_hash]
#[account]
pub struct RideAttestation {
    pub rider: Pubkey,
    pub ride_hash: [u8; 32],
    pub attestation_commitment: [u8; 32],
    pub parser_version: u32,
    pub source_kind: u8,
    pub completed_at: i64,
    pub started_at: i64,
    pub total_tss: u32,
    pub total_distance_m: u32,
    pub total_vert_m: u32,
    pub cal_earned: u64,
    pub climbs_crossed: u16,
    pub attester: Pubkey,
    pub settled_at: i64,
    pub settled_slot: u64,
    pub economic_epoch: u64,
    pub finalized: bool,
    pub bump: u8,
}

impl RideAttestation {
    pub const SIZE: usize =
        8 + 32 + 32 + 32 + 4 + 1 + 8 + 8 + 4 + 4 + 4 + 8 + 2 + 32 + 8 + 8 + 8 + 1 + 1;
}

/// One-time immutable authority for economics released after Threshold
/// establishment. The parent RideAttestation remains the sporting authority.
/// PDA: [HELD_RIDE_RELEASE_SEED, ride_attestation]
#[account]
pub struct HeldRideReleaseAuthority {
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub threshold_authority_id: [u8; 16],
    pub threshold_authority_commitment: [u8; 32],
    pub threshold_effective_at: i64,
    pub threshold_w: u16,
    pub threshold_policy_version: u8,
    pub economic_tss: u32,
    pub cal_earned: u64,
    pub cal_tribute_budget: u64,
    pub release_plan_hash: [u8; 32],
    pub released_at: i64,
    pub released_slot: u64,
    pub release_settlement_week: u64,
    pub attester: Pubkey,
    pub bump: u8,
}

impl HeldRideReleaseAuthority {
    pub const SIZE: usize = 8 + 32 + 32 + 16 + 32 + 8 + 2 + 1 + 4 + 8 + 8 + 32 + 8 + 8 + 8 + 32 + 1;
}

/// Ride-scoped conservation ledger for all climb tribute instructions.
/// PDA: [RIDE_TRIBUTE_BUDGET_SEED, ride_attestation]
#[account]
pub struct RideTributeBudget {
    pub ride_attestation: Pubkey,
    pub cal_budget: u64,
    pub total_cal_tributed: u64,
    pub bump: u8,
}

impl RideTributeBudget {
    pub const SIZE: usize = 8 + 32 + 8 + 8 + 1;

    pub(crate) fn credit(&mut self, cal_tribute: u64) -> Result<()> {
        let next_total = self
            .total_cal_tributed
            .checked_add(cal_tribute)
            .ok_or(ErrorCode::Overflow)?;
        require!(
            next_total <= self.cal_budget,
            ErrorCode::RideTributeBudgetExceeded
        );
        self.total_cal_tributed = next_total;
        Ok(())
    }
}

/// Release-scoped conservation ledger. Its distinct discriminator occupies
/// the ordinary ride budget PDA so the two economic paths cannot coexist.
/// PDA: [RIDE_TRIBUTE_BUDGET_SEED, ride_attestation]
#[account]
pub struct ReleasedRideTributeBudget {
    pub ride_attestation: Pubkey,
    pub release_authority: Pubkey,
    pub cal_budget: u64,
    pub total_cal_tributed: u64,
    pub bump: u8,
}

impl ReleasedRideTributeBudget {
    pub const SIZE: usize = 8 + 32 + 32 + 8 + 8 + 1;

    pub(crate) fn credit(&mut self, cal_tribute: u64) -> Result<()> {
        let next_total = self
            .total_cal_tributed
            .checked_add(cal_tribute)
            .ok_or(ErrorCode::Overflow)?;
        require!(
            next_total <= self.cal_budget,
            ErrorCode::RideTributeBudgetExceeded
        );
        self.total_cal_tributed = next_total;
        Ok(())
    }
}

/// Idempotent receipt proving a ride's CAL mint was settled exactly once.
/// PDA: [CAL_MINT_RECEIPT_SEED, ride_attestation, rider]
#[account]
pub struct CalMintReceipt {
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub amount: u64,
    pub bump: u8,
}

impl CalMintReceipt {
    pub const SIZE: usize = 8 + 32 + 32 + 8 + 1;
}

/// Release-aware CAL receipt. Its distinct discriminator occupies the
/// ordinary CAL receipt PDA and therefore preserves the one-mint replay guard.
#[account]
pub struct ReleasedCalMintReceipt {
    pub ride_attestation: Pubkey,
    pub release_authority: Pubkey,
    pub rider: Pubkey,
    pub amount: u64,
    pub release_settlement_week: u64,
    pub bump: u8,
}

impl ReleasedCalMintReceipt {
    pub const SIZE: usize = 8 + 32 + 32 + 32 + 8 + 8 + 1;
}

/// Tribute-bound completion receipt proving a ride was applied to a climb/vault
/// exactly once. PDA: [CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation, vault].
/// Its discriminator differs from the retired V1 receipt; the shared PDA seeds
/// remain the replay guard.
#[account]
pub struct ClimbCompletionReceiptV2 {
    pub ride_attestation: Pubkey,
    pub vault: Pubkey,
    pub evidence_version: u8,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub bump: u8,
}

impl ClimbCompletionReceiptV2 {
    pub const SIZE: usize = 8 + 32 + 32 + 1 + 8 + 32 + 1;
}

/// Release-aware completion receipt. It retains the ordinary per-Vault PDA
/// replay guard but binds the completion to the immutable release authority.
#[account]
pub struct ReleasedClimbCompletionReceipt {
    pub ride_attestation: Pubkey,
    pub release_authority: Pubkey,
    pub vault: Pubkey,
    pub evidence_version: u8,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub credited_settlement_week: u64,
    pub bump: u8,
}

impl ReleasedClimbCompletionReceipt {
    pub const SIZE: usize = 8 + 32 + 32 + 32 + 1 + 8 + 32 + 8 + 1;
}

// --------------------- Vault Types ---------------------

/// Payment method for vault creation
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum VaultPaymentMethod {
    /// Burn DUNG tokens
    Dung = 0,
    /// Burn CAL + transfer USDC
    CalPlusUsdc = 1,
    /// CAL deposit only (points period)
    Cal = 2,
}

/// Allocation bucket for supply cap tracking
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum AllocationBucket {
    Community = 0,
    Treasury = 1,
    Team = 2,
    Investor = 3,
    Pol = 4,
}

/// Counter for auto-incrementing vault IDs
#[account]
pub struct VaultCounter {
    pub count: u64,
    pub bump: u8,
}

impl VaultCounter {
    pub const SIZE: usize = 8 + 8 + 1; // discriminator + count + bump
}

/// Global DUNG mint state for supply cap enforcement
/// PDA: [DUNG_MINT_STATE_SEED]
#[account]
pub struct DungMintState {
    pub authority: Pubkey,
    pub max_supply: u64,
    /// Lifetime DUNG minted through this program; burns never reduce this counter.
    pub total_minted: u64,
    /// DUNG burned by this program since protocol burn accounting activated.
    /// The SPL mint account, not this telemetry field, is circulation authority.
    pub total_burned: u64,
    /// Actual Community allocation minted through this program.
    pub community_minted: u64,
    pub treasury_minted: u64,
    pub team_minted: u64,
    pub investor_minted: u64,
    pub pol_minted: u64,
    /// Lowest deterministic schedule rate observed by a successful settlement.
    /// Capacity exhaustion affects admission, not the policy rate.
    pub current_emission_rate_bps: u64,
    /// Historical ABI name retained for compatibility. This is the immutable
    /// emission-start Settlement Week; automatic settlement never changes it.
    pub last_halving_epoch: u64,
    pub bump: u8,
    /// Exact Community supply committed to claims and Community bucket carry.
    /// Appended after the legacy bump so migration preserves bytes 0..121.
    pub community_reserved: u64,
    /// Version 1 proves the reservation covers every Community obligation.
    pub reservation_policy_version: u8,
}

impl DungMintState {
    pub const LEGACY_SIZE: usize = 8   // discriminator
        + 32  // authority
        + 8   // max_supply
        + 8   // total_minted
        + 8   // total_burned
        + 8   // community_minted
        + 8   // treasury_minted
        + 8   // team_minted
        + 8   // investor_minted
        + 8   // pol_minted
        + 8   // current_emission_rate_bps
        + 8   // last_halving_epoch
        + 1; // bump
    pub const COMMUNITY_RESERVED_OFFSET: usize = Self::LEGACY_SIZE;
    pub const CLAIM_RESERVATION_SIZE: usize = Self::LEGACY_SIZE + 8;
    pub const RESERVATION_POLICY_VERSION_OFFSET: usize = Self::CLAIM_RESERVATION_SIZE;
    pub const SIZE: usize = Self::CLAIM_RESERVATION_SIZE + 1;

    pub fn committed_total(&self) -> Result<u64> {
        checked_sum_u64([self.total_minted, self.community_reserved])
    }

    pub fn committed_community(&self) -> Result<u64> {
        checked_sum_u64([self.community_minted, self.community_reserved])
    }

    pub fn minted_bucket_total(&self) -> Result<u64> {
        checked_sum_u64([
            self.community_minted,
            self.treasury_minted,
            self.team_minted,
            self.investor_minted,
            self.pol_minted,
        ])
    }

    pub fn assert_solvent(&self) -> Result<()> {
        require!(
            self.reservation_policy_version == DUNG_RESERVATION_POLICY_VERSION,
            ErrorCode::DungReservationPolicyNotMigrated
        );
        require!(
            self.total_minted == self.minted_bucket_total()?,
            ErrorCode::DungMintAccountingMismatch
        );
        require!(
            self.committed_total()? <= self.max_supply,
            ErrorCode::SupplyCapReached
        );
        require!(
            self.committed_community()? <= COMMUNITY_CAP,
            ErrorCode::SupplyCapReached
        );
        Ok(())
    }

    /// Check if an immediate mint can be committed without exceeding caps.
    /// Existing deferred Community claims reduce every bucket's total headroom.
    pub fn can_mint(&self, amount: u64, allocation: AllocationBucket) -> bool {
        let new_total = match checked_sum_u64([self.total_minted, self.community_reserved, amount])
        {
            Ok(total) => total,
            Err(_) => return false,
        };

        if new_total > self.max_supply {
            return false;
        }

        let (current, cap) = match allocation {
            AllocationBucket::Community => {
                let committed = match self.committed_community() {
                    Ok(committed) => committed,
                    Err(_) => return false,
                };
                (committed, COMMUNITY_CAP)
            }
            AllocationBucket::Treasury => (self.treasury_minted, TREASURY_CAP),
            AllocationBucket::Team => (self.team_minted, TEAM_CAP),
            AllocationBucket::Investor => (self.investor_minted, INVESTOR_CAP),
            AllocationBucket::Pol => (self.pol_minted, POL_CAP),
        };

        let new_allocation = match checked_sum_u64([current, amount]) {
            Ok(total) => total,
            Err(_) => return false,
        };

        new_allocation <= cap
    }

    /// Record an immediate mint operation.
    pub fn record_mint(&mut self, amount: u64, allocation: AllocationBucket) -> Result<()> {
        self.assert_solvent()?;
        require!(
            self.can_mint(amount, allocation),
            ErrorCode::SupplyCapReached
        );

        let new_total_minted = self
            .total_minted
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;

        let new_allocation_minted = match allocation {
            AllocationBucket::Community => self.community_minted.checked_add(amount),
            AllocationBucket::Treasury => self.treasury_minted.checked_add(amount),
            AllocationBucket::Team => self.team_minted.checked_add(amount),
            AllocationBucket::Investor => self.investor_minted.checked_add(amount),
            AllocationBucket::Pol => self.pol_minted.checked_add(amount),
        }
        .ok_or(ErrorCode::Overflow)?;

        self.total_minted = new_total_minted;
        match allocation {
            AllocationBucket::Community => self.community_minted = new_allocation_minted,
            AllocationBucket::Treasury => self.treasury_minted = new_allocation_minted,
            AllocationBucket::Team => self.team_minted = new_allocation_minted,
            AllocationBucket::Investor => self.investor_minted = new_allocation_minted,
            AllocationBucket::Pol => self.pol_minted = new_allocation_minted,
        }

        self.assert_solvent()
    }

    /// Record burns executed by this program without changing lifetime mint
    /// counters or allocation headroom.
    pub fn record_protocol_burn(&mut self, amount: u64) -> Result<()> {
        self.assert_solvent()?;
        let total_burned = self
            .total_burned
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;
        require!(
            total_burned <= self.total_minted,
            ErrorCode::DungBurnAccountingMismatch
        );
        self.total_burned = total_burned;
        Ok(())
    }

    /// Commit exact Community headroom for an admitted settlement obligation.
    pub fn reserve_community(&mut self, amount: u64) -> Result<()> {
        self.assert_solvent()?;
        require!(
            self.can_mint(amount, AllocationBucket::Community),
            ErrorCode::SupplyCapReached
        );
        let new_reserved = self
            .community_reserved
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;
        self.community_reserved = new_reserved;
        self.assert_solvent()
    }

    /// Convert a Community commitment into actual minted supply.
    /// There is intentionally no release path: only the matching direct or
    /// deferred settlement mint can reduce the reservation.
    pub fn consume_community_reservation(&mut self, amount: u64) -> Result<()> {
        self.assert_solvent()?;
        let new_reserved = self
            .community_reserved
            .checked_sub(amount)
            .ok_or(ErrorCode::InsufficientCommunityReservation)?;
        let new_total_minted = self
            .total_minted
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;
        let new_community_minted = self
            .community_minted
            .checked_add(amount)
            .ok_or(ErrorCode::Overflow)?;

        let committed_total = checked_sum_u64([new_total_minted, new_reserved])?;
        let committed_community = checked_sum_u64([new_community_minted, new_reserved])?;
        require!(
            committed_total <= self.max_supply,
            ErrorCode::SupplyCapReached
        );
        require!(
            committed_community <= COMMUNITY_CAP,
            ErrorCode::SupplyCapReached
        );

        self.community_reserved = new_reserved;
        self.total_minted = new_total_minted;
        self.community_minted = new_community_minted;

        Ok(())
    }

    /// Apply emission rate to an amount
    pub fn apply_emission_rate(&self, amount: u64) -> Result<u64> {
        checked_mul_div_u64(
            amount,
            self.current_emission_rate_bps,
            BASIS_POINTS_DENOMINATOR,
        )
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq, Eq)]
pub(crate) struct LegacyDungMintState {
    pub(crate) authority: Pubkey,
    pub(crate) max_supply: u64,
    pub(crate) total_minted: u64,
    pub(crate) total_burned: u64,
    pub(crate) community_minted: u64,
    pub(crate) treasury_minted: u64,
    pub(crate) team_minted: u64,
    pub(crate) investor_minted: u64,
    pub(crate) pol_minted: u64,
    pub(crate) current_emission_rate_bps: u64,
    pub(crate) last_halving_epoch: u64,
    pub(crate) bump: u8,
}

impl LegacyDungMintState {
    pub(crate) fn with_reservation_policy(
        &self,
        community_reserved: u64,
        reservation_policy_version: u8,
    ) -> DungMintState {
        DungMintState {
            authority: self.authority,
            max_supply: self.max_supply,
            total_minted: self.total_minted,
            total_burned: self.total_burned,
            community_minted: self.community_minted,
            treasury_minted: self.treasury_minted,
            team_minted: self.team_minted,
            investor_minted: self.investor_minted,
            pol_minted: self.pol_minted,
            current_emission_rate_bps: self.current_emission_rate_bps,
            last_halving_epoch: self.last_halving_epoch,
            bump: self.bump,
            community_reserved,
            reservation_policy_version,
        }
    }
}

pub(crate) struct DungMintStateLayout {
    pub(crate) legacy: LegacyDungMintState,
    pub(crate) community_reserved: Option<u64>,
    pub(crate) reservation_policy_version: Option<u8>,
}

// ============================================================================
// Program Config (Admin Authority)
// ============================================================================

/// Program configuration for admin and backend authority management
/// PDA: [PROGRAM_CONFIG_SEED]
///
/// Security: This account gates access to privileged operations:
/// - admin_authority: Can update config, perform admin operations
/// - backend_authority: Can credit/debit CAL, record vault completions
#[account]
pub struct ProgramConfig {
    /// Admin authority (can update config, perform admin operations)
    pub admin_authority: Pubkey,
    /// Backend authority (can credit/debit CAL, record completions)
    pub backend_authority: Pubkey,
    /// Program/account-layout version gate for external clients
    pub program_version: u8,
    /// Whether the config has been initialized
    pub initialized: bool,
    /// PDA bump
    pub bump: u8,

    // === Mint configuration ===
    /// CAL SPL mint pubkey (immutable after configure_mints)
    pub cal_mint: Pubkey,
    /// DUNG SPL mint pubkey (immutable after configure_mints)
    pub dung_mint: Pubkey,
    /// Bump for CAL_MINT_AUTH_PDA
    pub cal_mint_auth_bump: u8,
    /// Bump for DUNG_MINT_AUTH_PDA
    pub dung_mint_auth_bump: u8,
    /// POL token account (DUNG ATA for protocol-owned liquidity)
    pub pol_token_account: Pubkey,
    /// Treasury token account (DUNG ATA for protocol treasury)
    pub treasury_token_account: Pubkey,

    // === Governance-configurable protocol parameters ===
    /// DUNG burn required for DUNG-only vault creation
    pub vault_creation_dung: u64,
    /// Whole CAL burned by create_vault_with_usdc (scaled to base units at use)
    pub vault_creation_cal: u64,
    /// Harvest fee in basis points
    pub harvest_fee_bps: u64,
    /// Founder metadata/culture rights duration in settlement weeks
    pub minter_rights_epochs: u64,
    /// Local Legend term duration in settlement weeks
    pub local_legend_term_epochs: u64,
    /// Settlement weeks between emission halvings
    pub epochs_per_halving: u64,

    // === Canonical USDC payment rail ===
    /// USDC SPL mint pubkey for supported app payments
    pub usdc_mint: Pubkey,
    /// Treasury USDC token account receiving supported app payments
    pub usdc_treasury_token_account: Pubkey,
    /// USDC amount required for CAL+USDC vault creation
    pub vault_creation_usdc: u64,

    // === Settlement clock ===
    /// Immutable Monday-clock cutover. The canonical anchor means a fresh V2-only clock.
    pub settlement_clock_v2_starts_at: i64,
    /// Stored explicitly so clients and indexers can reject unknown clock layouts.
    pub settlement_clock_version: u8,
}

impl ProgramConfig {
    pub const ADMIN_AUTHORITY_OFFSET: usize = 8;
    pub const BACKEND_AUTHORITY_OFFSET: usize = Self::ADMIN_AUTHORITY_OFFSET + 32;
    pub const PROGRAM_VERSION_OFFSET: usize = Self::BACKEND_AUTHORITY_OFFSET + 32;
    pub const INITIALIZED_OFFSET: usize = Self::PROGRAM_VERSION_OFFSET + 1;
    pub const BUMP_OFFSET: usize = Self::INITIALIZED_OFFSET + 1;
    pub const STABLE_PREFIX_SIZE: usize = Self::BUMP_OFFSET + 1;

    /// Size through mint configuration, before payout destination accounts.
    pub const SIZE_WITH_MINTS: usize = 8    // discriminator
        + 32   // admin_authority
        + 32   // backend_authority
        + 1    // program_version
        + 1    // initialized
        + 1    // bump
        + 32   // cal_mint
        + 32   // dung_mint
        + 1    // cal_mint_auth_bump
        + 1; // dung_mint_auth_bump

    /// Compact size with POL/treasury token account addresses, before
    /// governance-configurable parameters were appended.
    pub const SIZE_WITH_TREASURY_ACCOUNTS: usize = Self::SIZE_WITH_MINTS
        + 32   // pol_token_account
        + 32; // treasury_token_account

    pub const PROTOCOL_PARAMETERS_SIZE: usize = 8      // vault_creation_dung
        + 8    // vault_creation_cal
        + 8    // harvest_fee_bps
        + 8    // minter_rights_epochs
        + 8    // local_legend_term_epochs
        + 8; // epochs_per_halving

    pub const PROTOCOL_PARAMETERS_OFFSET: usize = Self::SIZE_WITH_TREASURY_ACCOUNTS;

    /// Size before canonical USDC payment rail fields were appended.
    pub const SIZE_BEFORE_USDC_CONFIG: usize =
        Self::SIZE_WITH_TREASURY_ACCOUNTS + Self::PROTOCOL_PARAMETERS_SIZE;

    pub const USDC_CONFIG_SIZE: usize = 32      // usdc_mint
        + 32    // usdc_treasury_token_account
        + 8; // vault_creation_usdc

    pub const USDC_CONFIG_OFFSET: usize = Self::SIZE_BEFORE_USDC_CONFIG;

    /// Size before the versioned settlement clock was appended.
    pub const SIZE_BEFORE_SETTLEMENT_CLOCK: usize =
        Self::SIZE_BEFORE_USDC_CONFIG + Self::USDC_CONFIG_SIZE;

    pub const SETTLEMENT_CLOCK_SIZE: usize = 8 // settlement_clock_v2_starts_at
        + 1; // settlement_clock_version

    pub const SETTLEMENT_CLOCK_OFFSET: usize = Self::SIZE_BEFORE_SETTLEMENT_CLOCK;

    /// Current ProgramConfig size.
    pub const SIZE: usize = Self::SIZE_BEFORE_SETTLEMENT_CLOCK + Self::SETTLEMENT_CLOCK_SIZE;

    pub fn apply_protocol_parameters(&mut self, parameters: ProtocolParameters) {
        self.vault_creation_dung = parameters.vault_creation_dung;
        self.vault_creation_cal = parameters.vault_creation_cal;
        self.harvest_fee_bps = parameters.harvest_fee_bps;
        self.minter_rights_epochs = parameters.minter_rights_epochs;
        self.local_legend_term_epochs = parameters.local_legend_term_epochs;
        self.epochs_per_halving = parameters.epochs_per_halving;
    }

    pub fn is_usdc_configured(&self) -> bool {
        self.usdc_mint != Pubkey::default()
            && self.usdc_treasury_token_account != Pubkey::default()
            && self.vault_creation_usdc > 0
    }

    pub fn settlement_clock(&self) -> Result<SettlementClock> {
        require!(
            self.settlement_clock_version == SETTLEMENT_CLOCK_VERSION_V2,
            ErrorCode::SettlementClockNotConfigured
        );
        if self.settlement_clock_v2_starts_at == SETTLEMENT_WEEK_V2_ANCHOR {
            return Ok(SettlementClock::v2_only());
        }
        SettlementClock::with_legacy_cutover(self.settlement_clock_v2_starts_at)
    }
}

/// Curated, immutable identity for one ratified canon Climb version.
/// PDA: [CLIMB_SEED, sha256(D12 commitment)]
#[account]
pub struct Climb {
    pub canon_commitment: [u8; 64],
    pub commitment_hash: [u8; 32],
    pub canon_id: [u8; 16],
    pub canon_version: u16,
    pub canonical_profile_hash: [u8; 32],
    pub predecessor_climb: Pubkey,
    /// Set exactly once when the admin registers the next exact canon version.
    /// A nonzero successor makes this Climb stale for new Vault activation.
    pub successor_climb: Pubkey,
    pub record_continuity_policy: RecordContinuityPolicy,
    /// The sole economic activation of this exact canon version.
    pub vault: Pubkey,
    pub name: [u8; 64],
    pub vert_m: u32,
    pub distance_m: u32,
    pub avg_gradient_pct: u16,
    pub registered_at: i64,
    pub registered_by: Pubkey,
    pub bump: u8,
}

impl Climb {
    pub const SIZE: usize = 8 // discriminator
        + 64 // canon_commitment
        + 32 // commitment_hash
        + 16 // canon_id
        + 2 // canon_version
        + 32 // canonical_profile_hash
        + 32 // predecessor_climb
        + 32 // successor_climb
        + 1 // record_continuity_policy
        + 32 // vault
        + 64 // name
        + 4 // vert_m
        + 4 // distance_m
        + 2 // avg_gradient_pct
        + 8 // registered_at
        + 32 // registered_by
        + 1; // bump
}

/// Enforces one on-chain Climb for each `(canon_id, canon_version)` pair even
/// though the Climb itself is addressed by its commitment hash.
#[account]
pub struct ClimbVersionIndex {
    pub canon_id: [u8; 16],
    pub canon_version: u16,
    pub climb: Pubkey,
    pub bump: u8,
}

impl ClimbVersionIndex {
    pub const SIZE: usize = 8 + 16 + 2 + 32 + 1;
}

#[derive(Debug)]
pub(crate) struct VaultClimbBinding {
    pub(crate) climb: Pubkey,
    pub(crate) canon_commitment: [u8; 64],
    pub(crate) commitment_hash: [u8; 32],
    pub(crate) name: [u8; 64],
    pub(crate) vert_m: u32,
    pub(crate) distance_m: u32,
    pub(crate) avg_gradient_pct: u16,
}

/// A climb vault - on-chain economic activation of one canon Climb
/// PDA: [VAULT_SEED, &id.to_le_bytes()]
#[account]
pub struct Vault {
    // Identity
    pub id: u64,
    pub signature: [u8; 64],      // D12 canon commitment copied from Climb
    pub signature_hash: [u8; 32], // SHA256 of the D12 commitment for indexing

    // Creator/Ownership
    pub minter: Pubkey,            // First claimer (mint rights for N epochs)
    pub mint_epoch: u64,           // Epoch when minted
    pub rights_expires_epoch: u64, // Epoch when minter rights expire

    // Current KOM
    pub kom_holder: Pubkey, // Current KOM (best time holder), Pubkey::default() if none
    pub kom_time_s: u32,    // Best completion time (0 if no completions)
    pub kom_set_epoch: u64, // Epoch when KOM was set

    // Metadata (minter-controlled during rights period, then KOM)
    pub name: [u8; 64],        // Display name (UTF-8)
    pub avatar_ipfs: [u8; 46], // IPFS CID for avatar image
    pub slogan: [u8; 128],     // Short slogan/tagline

    // Economics
    pub cal_tribute_accumulated: u64, // CAL remainder in the oldest open settlement flow
    pub cal_tribute_accumulated_next: u64, // DEPRECATED: legacy next-week remainder, drained on rollover
    pub total_cal_burned: u64,             // Lifetime CAL burned
    pub total_dung_emitted: u64,           // Lifetime DUNG distributed or allocated
    pub total_completions: u64,            // Number of rides completed

    // Staking (CAL-only, discrete Settlement Week allocation per TRUTHS P8)
    pub total_cal_staked: u64, // CAL staked in vault (principal)
    pub staker_count: u32,     // Settlement-relevant VaultStake inventory count

    // Legacy Synthetix fields (deprecated, kept only to minimize Phase 1 blast radius)
    pub reward_per_token_stored: u64,
    pub last_update_time: i64,
    /// Retired Synthetix slot. Stores STAKER_REMAINDER_POLICY_MARKER after the
    /// one-time legacy carry cutover; the account layout remains unchanged.
    pub reward_rate: u64,

    // Settlement-week inflow
    pub pending_rewards: u64, // DUNG staged in the oldest open settlement flow
    pub pending_rewards_next_week: u64, // DEPRECATED: legacy next-week DUNG, drained on rollover
    pub open_settlement_week: u64, // Oldest unsettled settlement week

    // Per-bucket carry (preserved within bucket identity)
    pub carry_record_royalty: u64,
    /// Already-unlocked staker pro-rata integer dust only.
    pub carry_stakers: u64,
    pub carry_local_legend: u64,
    pub carry_pol: u64,
    pub carry_treasury: u64,

    // Legacy (deprecated, kept for account compatibility)
    pub total_staked: u64, // DEPRECATED: was DUNG staked, now unused

    // Epoch guard — prevents double-distribution in same epoch
    pub last_distribution_epoch: u64,

    // Metrics copied from the immutable Climb account
    pub vert_m: u32,           // Vertical gain (meters * 10 for precision)
    pub distance_m: u32,       // Distance (meters)
    pub avg_gradient_pct: u16, // Gradient (pct * 100)

    pub created_at: i64,
    pub bump: u8,
    /// V4-B append-only link to the immutable canon Climb account.
    pub climb: Pubkey,
}

impl Vault {
    pub const SIZE: usize = 8   // discriminator
        + 8                      // id
        + 64                     // signature
        + 32                     // signature_hash
        + 32                     // minter
        + 8                      // mint_epoch
        + 8                      // rights_expires_epoch
        + 32                     // kom_holder
        + 4                      // kom_time_s
        + 8                      // kom_set_epoch
        + 64                     // name
        + 46                     // avatar_ipfs
        + 128                    // slogan
        + 8                      // cal_tribute_accumulated
        + 8                      // cal_tribute_accumulated_next
        + 8                      // total_cal_burned
        + 8                      // total_dung_emitted
        + 8                      // total_completions
        + 8                      // total_cal_staked
        + 4                      // staker_count
        + 8                      // reward_per_token_stored
        + 8                      // last_update_time
        + 8                      // reward_rate (staker remainder policy marker)
        + 8                      // pending_rewards
        + 8                      // pending_rewards_next_week
        + 8                      // open_settlement_week
        + 8                      // carry_record_royalty
        + 8                      // carry_stakers
        + 8                      // carry_local_legend
        + 8                      // carry_pol
        + 8                      // carry_treasury
        + 8                      // total_staked (deprecated)
        + 8                      // last_distribution_epoch
        + 4                      // vert_m
        + 4                      // distance_m
        + 2                      // avg_gradient_pct
        + 8                      // created_at
        + 1                      // bump
        + 32; // climb

    /// Check if minter rights are still active
    pub fn minter_has_rights(&self, current_epoch: u64) -> bool {
        current_epoch < self.rights_expires_epoch
    }

    /// Get the current rights holder (minter if rights active, else KOM)
    pub fn rights_holder(&self, current_epoch: u64) -> Pubkey {
        if self.minter_has_rights(current_epoch) {
            self.minter
        } else if self.kom_holder != Pubkey::default() {
            self.kom_holder
        } else {
            self.minter // Fallback to minter if no KOM
        }
    }

    pub fn current_week_empty(&self) -> bool {
        self.cal_tribute_accumulated == 0
            && self.pending_rewards == 0
            && self.carry_record_royalty == 0
            && self.carry_stakers == 0
            && self.carry_local_legend == 0
            && self.carry_pol == 0
            && self.carry_treasury == 0
    }

    pub(crate) fn credit_tribute_bucket(
        cal_remainder: &mut u64,
        pending_rewards: &mut u64,
        cal_tribute: u64,
    ) -> Result<()> {
        *cal_remainder = cal_remainder
            .checked_add(cal_tribute)
            .ok_or(ErrorCode::Overflow)?;

        let dung_converted = *cal_remainder / VAULT_CAL_TO_DUNG_THRESHOLD;
        *cal_remainder %= VAULT_CAL_TO_DUNG_THRESHOLD;

        if dung_converted > 0 {
            *pending_rewards = pending_rewards
                .checked_add(dung_converted)
                .ok_or(ErrorCode::Overflow)?;
        }

        Ok(())
    }

    pub fn credit_lifetime_tribute(&mut self, cal_tribute: u64) -> Result<()> {
        Self::credit_tribute_bucket(
            &mut self.cal_tribute_accumulated,
            &mut self.pending_rewards,
            cal_tribute,
        )
    }

    pub fn roll_to_next_settlement_week(&mut self) -> Result<()> {
        self.open_settlement_week = self
            .open_settlement_week
            .checked_add(1)
            .ok_or(ErrorCode::Overflow)?;
        self.last_distribution_epoch = self.open_settlement_week.saturating_sub(1);

        self.pending_rewards = self.pending_rewards_next_week;
        self.pending_rewards_next_week = 0;

        let carried_cal = self
            .cal_tribute_accumulated
            .checked_add(self.cal_tribute_accumulated_next)
            .ok_or(ErrorCode::Overflow)?;
        self.cal_tribute_accumulated = 0;
        self.cal_tribute_accumulated_next = 0;
        Self::credit_tribute_bucket(
            &mut self.cal_tribute_accumulated,
            &mut self.pending_rewards,
            carried_cal,
        )?;

        Ok(())
    }

    pub fn maybe_advance_empty_settlement_week(
        &mut self,
        settlement_clock: &SettlementClock,
        current_time: i64,
    ) -> Result<()> {
        while current_time >= settlement_clock.week_finalization_time(self.open_settlement_week)?
            && self.current_week_empty()
        {
            self.roll_to_next_settlement_week()?;
        }

        Ok(())
    }

    /// Rewards are credited discretely at Settlement Week finalization.
    pub fn earned(&self, stake: &VaultStake, _current_time: i64) -> u64 {
        stake.rewards_earned
    }
}

/// User's completion record for a specific vault
/// PDA: [VAULT_COMPLETION_SEED, user, &vault_id.to_le_bytes()]
#[account]
pub struct VaultCompletion {
    pub user: Pubkey,
    pub vault_id: u64,
    pub completions: u32, // Number of times completed
    pub best_time_s: u32, // Personal best time
    pub last_completed_at: i64,
    pub total_cal_tributed: u64, // Lifetime CAL tributed to this vault
    pub bump: u8,
}

impl VaultCompletion {
    pub const SIZE: usize = 8 + 32 + 8 + 4 + 4 + 8 + 8 + 1;

    pub fn note_completed_at(&mut self, completed_at: i64) {
        self.last_completed_at = self.last_completed_at.max(completed_at);
    }
}

/// User's staking position in a vault. Rewards are credited via discrete
/// per-Settlement-Week direct allocation (TRUTHS P8). The settlement snapshot
/// fields reuse the former Synthetix/amount slots, preserving the 105-byte
/// account layout deployed on devnet.
/// PDA: [VAULT_STAKE_SEED, user, &vault_id.to_le_bytes()]
#[account]
pub struct VaultStake {
    pub user: Pubkey,
    pub vault_id: u64,
    pub cal_staked: u64, // CAL staked (principal)
    pub lp_tokens: u64,  // LP tokens received
    pub staked_at: i64,
    /// Zero means no pending transition; otherwise stores effective week + 1.
    pub pending_effective_week_plus_one: u64,
    pub effective_lp_tokens: u64, // LP weight frozen for the open Settlement Week
    pub rewards_earned: u64,      // Pending unclaimed DUNG rewards
    pub pending_lp_tokens: u64,   // Full LP target when the pending week begins

    pub bump: u8,
}

impl VaultStake {
    pub const SIZE: usize = 8   // discriminator
        + 32                     // user
        + 8                      // vault_id
        + 8                      // cal_staked
        + 8                      // lp_tokens
        + 8                      // staked_at
        + 8                      // pending_effective_week_plus_one
        + 8                      // effective_lp_tokens
        + 8                      // rewards_earned
        + 8                      // pending_lp_tokens
        + 1; // bump

    pub fn effective_week_for_change(
        settlement_clock: &SettlementClock,
        changed_at: i64,
    ) -> Result<u64> {
        let current_week = settlement_clock.week_at(changed_at)?;
        if settlement_clock.is_week_start(changed_at)? {
            Ok(current_week)
        } else {
            current_week
                .checked_add(1)
                .ok_or(ErrorCode::Overflow.into())
        }
    }

    pub fn pending_effective_week(&self) -> Result<Option<u64>> {
        if self.pending_effective_week_plus_one == 0 {
            return Ok(None);
        }
        Ok(Some(
            self.pending_effective_week_plus_one
                .checked_sub(1)
                .ok_or(ErrorCode::Underflow)?,
        ))
    }

    pub(crate) fn initialize_snapshot_if_legacy(
        &mut self,
        settlement_clock: &SettlementClock,
        reference_week: u64,
    ) -> Result<()> {
        // Before snapshot accounting, these two amount slots were always zero
        // and the week slot held raw eligible_from_epoch. The live devnet
        // census verifies that invariant for every deployed VaultStake.
        if self.effective_lp_tokens != 0 || self.pending_lp_tokens != 0 {
            return Ok(());
        }

        if self.lp_tokens == 0 {
            self.pending_effective_week_plus_one = 0;
            return Ok(());
        }

        let recorded_eligible_week = self.pending_effective_week_plus_one;
        let ratified_effective_week =
            Self::effective_week_for_change(settlement_clock, self.staked_at)?;
        // The legacy formula added one extra wait week. Keep any earlier admin
        // override, but never migrate a position later than the ratified rule.
        let migrated_effective_week = recorded_eligible_week.min(ratified_effective_week);
        if migrated_effective_week <= reference_week {
            self.effective_lp_tokens = self.lp_tokens;
            self.pending_effective_week_plus_one = 0;
        } else {
            self.pending_lp_tokens = self.lp_tokens;
            self.pending_effective_week_plus_one = migrated_effective_week
                .checked_add(1)
                .ok_or(ErrorCode::Overflow)?;
        }
        Ok(())
    }

    pub(crate) fn promote_pending_through(&mut self, first_unsettled_week: u64) -> Result<()> {
        if let Some(pending_week) = self.pending_effective_week()? {
            if pending_week <= first_unsettled_week {
                self.effective_lp_tokens = self.pending_lp_tokens;
                self.pending_lp_tokens = 0;
                self.pending_effective_week_plus_one = 0;
            }
        }
        Ok(())
    }

    pub fn requires_settlement_account(&self) -> bool {
        self.requires_settlement_account_with_live_lp(self.lp_tokens)
    }

    pub fn requires_settlement_account_with_live_lp(&self, live_lp_tokens: u64) -> bool {
        live_lp_tokens > 0 || self.effective_lp_tokens > 0 || self.pending_lp_tokens > 0
    }

    pub fn prepare_lp_change(
        &mut self,
        settlement_clock: &SettlementClock,
        target_lp_tokens: u64,
        changed_at: i64,
        first_unsettled_week: u64,
    ) -> Result<()> {
        self.initialize_snapshot_if_legacy(settlement_clock, first_unsettled_week)?;
        self.promote_pending_through(first_unsettled_week)?;

        let effective_week = Self::effective_week_for_change(settlement_clock, changed_at)?;
        if let Some(pending_week) = self.pending_effective_week()? {
            require!(
                pending_week == effective_week,
                ErrorCode::StakeSnapshotQueueFull
            );
            self.pending_lp_tokens = target_lp_tokens;
            return Ok(());
        }

        if target_lp_tokens == self.effective_lp_tokens {
            return Ok(());
        }
        self.pending_lp_tokens = target_lp_tokens;
        self.pending_effective_week_plus_one =
            effective_week.checked_add(1).ok_or(ErrorCode::Overflow)?;
        Ok(())
    }

    pub fn lp_tokens_for_settlement(
        &mut self,
        settlement_clock: &SettlementClock,
        settlement_week: u64,
    ) -> Result<u64> {
        self.initialize_snapshot_if_legacy(settlement_clock, settlement_week)?;
        if let Some(pending_week) = self.pending_effective_week()? {
            if pending_week <= settlement_week {
                self.effective_lp_tokens = self.pending_lp_tokens;
                self.pending_lp_tokens = 0;
                self.pending_effective_week_plus_one = 0;
            }
        }
        Ok(self.effective_lp_tokens)
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum RiderBalanceStatus {
    Active = 0,
    Locked = 1,
    Recovering = 2,
    Revoked = 3,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum BalanceAuthorityModel {
    AppBalance = 0,
    Policy = 1,
    Delegate = 2,
    RiderSession = 3,
}

/// Rider-scoped Boulder Roller Balance header.
/// PDA: [RIDER_BALANCE_SEED, rider]
#[account]
pub struct RiderBalance {
    pub rider: Pubkey,
    pub status: RiderBalanceStatus,
    pub active_authority_model: BalanceAuthorityModel,
    pub policy_hash: [u8; 32],
    pub delegate_authority: Pubkey,
    pub last_authority_rotation_at: i64,
    pub revoked_at: i64,
    pub bump: u8,
}

impl RiderBalance {
    pub const SIZE: usize = 8   // discriminator
        + 32                    // rider
        + 1                     // status
        + 1                     // active_authority_model
        + 32                    // policy_hash
        + 32                    // delegate_authority
        + 8                     // last_authority_rotation_at
        + 8                     // revoked_at
        + 1; // bump
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum BalanceVaultOperationKind {
    CreateVault = 0,
    DepositCal = 1,
    WithdrawCal = 2,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub struct BalanceVaultOperationAuthorization {
    pub operation_id: [u8; 32],
    pub generation: u64,
    pub nonce: u64,
    pub expires_at: i64,
}

/// Revocable rider-scoped signer for no-prompt Balance-funded Vault actions.
/// PDA: [BALANCE_VAULT_AUTHORITY_SEED, rider]
#[account]
pub struct BalanceVaultAuthority {
    pub rider: Pubkey,
    pub authority: Pubkey,
    pub policy_hash: [u8; 32],
    pub generation: u64,
    pub next_nonce: u64,
    pub expires_at: i64,
    pub revoked_at: i64,
    pub last_operation_id: [u8; 32],
    pub bump: u8,
}

impl BalanceVaultAuthority {
    pub const SIZE: usize = 8   // discriminator
        + 32                    // rider
        + 32                    // authority
        + 32                    // policy_hash
        + 8                     // generation
        + 8                     // next_nonce
        + 8                     // expires_at
        + 8                     // revoked_at
        + 32                    // last_operation_id
        + 1; // bump
}

// --------------------- Tokenomics V2 Vault Types ---------------------

/// Leaderboard entry for a vault
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy)]
pub struct LeaderEntry {
    pub user: Pubkey,
    pub time_s: u32,
    pub recorded_at: i64,
}

/// Vault leaderboard - tracks top 10 times
/// PDA: [VAULT_LEADERBOARD_SEED, &vault_id.to_le_bytes()]
#[account]
pub struct VaultLeaderboard {
    pub vault_id: u64,
    pub entries: Vec<LeaderEntry>, // Max 10 entries
    pub last_updated: i64,
    pub bump: u8,
}

impl VaultLeaderboard {
    pub const MAX_ENTRIES: usize = 10;
    pub const SIZE: usize = 8 + 8 + 4 + (Self::MAX_ENTRIES * (32 + 4 + 8)) + 8 + 1;

    pub(crate) fn canonicalize_entries(&mut self) {
        self.entries.sort_by(|a, b| {
            a.time_s
                .cmp(&b.time_s)
                .then(a.recorded_at.cmp(&b.recorded_at))
                .then(a.user.to_bytes().cmp(&b.user.to_bytes()))
        });

        let mut unique = Vec::with_capacity(self.entries.len().min(Self::MAX_ENTRIES));
        for entry in self.entries.drain(..) {
            if unique
                .iter()
                .any(|existing: &LeaderEntry| existing.user == entry.user)
            {
                continue;
            }
            unique.push(entry);
            if unique.len() == Self::MAX_ENTRIES {
                break;
            }
        }
        self.entries = unique;
    }

    /// Add or update an entry on the leaderboard
    pub fn update_entry(&mut self, user: Pubkey, time_s: u32, timestamp: i64) {
        // Find existing entry for user
        if let Some(entry) = self.entries.iter_mut().find(|e| e.user == user) {
            if (time_s, timestamp) < (entry.time_s, entry.recorded_at) {
                entry.time_s = time_s;
                entry.recorded_at = timestamp;
            }
        } else {
            self.entries.push(LeaderEntry {
                user,
                time_s,
                recorded_at: timestamp,
            });
        }

        self.canonicalize_entries();
        self.last_updated = self.last_updated.max(timestamp);
    }
}

/// Local Legend - single elected curator per vault
/// Elected by most completions in the election period, serves 8-epoch term
/// PDA: [LOCAL_LEGEND_SEED, &vault_id.to_le_bytes()]
#[account]
pub struct LocalLegend {
    pub vault_id: u64,
    pub holder: Pubkey,        // Current legend (Pubkey::default() if vacant)
    pub election_period: u64,  // Election period when elected (epoch / 8)
    pub term_start_epoch: u64, // First epoch of current term
    pub term_end_epoch: u64,   // Last epoch of current term (exclusive)
    pub completions_at_election: u32, // Completions count when elected
    pub runner_up: Pubkey,     // Second place in election
    pub runner_up_completions: u32, // Runner-up's completion count
    pub total_earned: u64,     // Lifetime DUNG earned as legend
    pub is_active: bool,       // If currently earning rewards
    pub is_bootstrap: bool,    // Founder bootstrap seat, not an elected win
    pub bump: u8,
}

impl LocalLegend {
    pub const SIZE: usize = 8   // discriminator
        + 8                      // vault_id
        + 32                     // holder
        + 8                      // election_period
        + 8                      // term_start_epoch
        + 8                      // term_end_epoch
        + 4                      // completions_at_election
        + 32                     // runner_up
        + 4                      // runner_up_completions
        + 8                      // total_earned
        + 1                      // is_active
        + 1                      // is_bootstrap
        + 1; // bump

    pub const LEGACY_SIZE: usize = Self::SIZE - 1;
    pub const VAULT_ID_OFFSET: usize = 8;
    pub const ELECTION_PERIOD_OFFSET: usize = 48;
    pub const COMPLETIONS_AT_ELECTION_OFFSET: usize = 72;
    pub const IS_ACTIVE_OFFSET: usize = 120;
    pub const IS_BOOTSTRAP_OFFSET: usize = 121;
    pub const LEGACY_BUMP_OFFSET: usize = 121;
    pub const BUMP_OFFSET: usize = 122;

    /// Calculate election period from epoch (8-epoch rotation)
    pub fn election_period_for_epoch(epoch: u64, term_epochs: u64) -> u64 {
        epoch / term_epochs
    }

    /// Check if term has expired
    pub fn is_term_expired(&self, current_epoch: u64) -> bool {
        current_epoch >= self.term_end_epoch
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum LocalLegendAccountLayout {
    Legacy { is_bootstrap: bool, bump: u8 },
    Current,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct LocalLegendMigrationOutcome {
    pub(crate) old_size: usize,
    pub(crate) new_size: usize,
    pub(crate) is_bootstrap: bool,
    pub(crate) migrated: bool,
}

/// Vault activation lifecycle — gates economic operations until historical seeding is done.
/// Created at vault creation (is_active = false), flipped to active after admin seeding.
/// PDA: [VAULT_ACTIVATION_SEED, &vault_id.to_le_bytes()]
#[account]
pub struct VaultActivation {
    pub vault_id: u64,
    pub is_active: bool,
    /// Operational counter retained for seeding job observability.
    pub seed_completions_written: u32,
    /// Operational flag retained for seeding job observability.
    pub leaderboard_seeded: bool,
    pub created_at: i64,
    pub activated_at: i64,
    pub last_seed_at: i64,
    /// Canonical seed generation. Authoritative historical imports start at 2.
    pub seed_generation: u32,
    /// Ride-time cutoff for historical seed material.
    pub seed_cutoff_at: i64,
    /// First settlement epoch allowed to receive live economic state.
    pub economics_start_epoch: u64,
    pub matched_users: u32,
    pub matched_completions: u32,
    /// SHA-256 bundle hash over the historical seed evidence set.
    pub evidence_hash: [u8; 32],
    pub bump: u8,
}

impl VaultActivation {
    pub const SIZE: usize = 8   // discriminator
        + 8                      // vault_id
        + 1                      // is_active
        + 4                      // seed_completions_written
        + 1                      // leaderboard_seeded
        + 8                      // created_at
        + 8                      // activated_at
        + 8                      // last_seed_at
        + 4                      // seed_generation
        + 8                      // seed_cutoff_at
        + 8                      // economics_start_epoch
        + 4                      // matched_users
        + 4                      // matched_completions
        + 32                     // evidence_hash
        + 1; // bump

    pub(crate) fn permits_new_economic_history(&self) -> bool {
        self.is_active && is_authoritative_vault_seed_generation(self.seed_generation)
    }
}

// --------------------- Beetle Card Types ---------------------

/// Type of Beetle Card - determines scope behavior
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq)]
pub enum CardType {
    /// ClimbBeetle: Scoped per Arena (scope_id = arena pubkey)
    Climb = 0,
    /// SteadyBeetle: Global scope (scope_id = GLOBAL_SCOPE)
    Steady = 1,
    /// ExplorerBeetle: Global scope (scope_id = GLOBAL_SCOPE)
    Explorer = 2,
}

/// Soulbound Beetle Card - tracks effort history
/// PDA: [BEETLE_CARD_SEED, owner, card_type, scope_id]
#[account]
pub struct BeetleCard {
    /// Owner wallet (immutable, soulbound)
    pub owner: Pubkey,
    /// Type of beetle card (Climb, Steady, Explorer)
    pub card_type: CardType,
    /// Scope identifier:
    /// - For Climb: Arena pubkey bytes
    /// - For Steady/Explorer: GLOBAL_SCOPE (all zeros)
    pub scope_id: [u8; 32],
    /// Cumulative effort score (pattern-specific metric)
    pub score: u64,
    /// Current level (1-10 based on score thresholds)
    pub level: u8,
    /// Total patterns scored contributing to this card
    pub patterns_scored: u32,
    /// Unix timestamp of last score increment
    pub last_updated: i64,
    /// Unix timestamp of card creation
    pub created_at: i64,
    /// PDA bump
    pub bump: u8,
}

impl BeetleCard {
    pub const SIZE: usize = 8  // discriminator
        + 32  // owner
        + 1   // card_type
        + 32  // scope_id
        + 8   // score
        + 1   // level
        + 4   // patterns_scored
        + 8   // last_updated
        + 8   // created_at
        + 1; // bump

    /// Calculate level from score using thresholds
    pub fn calculate_level(score: u64) -> u8 {
        for (i, &threshold) in LEVEL_THRESHOLDS.iter().enumerate() {
            if score < threshold {
                return i as u8;
            }
        }
        10 // Max level
    }
}
