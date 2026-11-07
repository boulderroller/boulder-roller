//! Events emitted by the program.

use crate::*;

// --------------------- Events ---------------------

#[event]
pub struct ProgramConfigInitialized {
    pub admin: Pubkey,
    pub backend: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct ProgramConfigUpdated {
    pub admin: Pubkey,
    pub backend: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct ProgramVersionAdvanced {
    pub admin: Pubkey,
    pub previous_version: u8,
    pub current_version: u8,
    pub timestamp: i64,
}

#[event]
pub struct ProtocolParametersUpdated {
    pub vault_creation_dung: u64,
    pub vault_creation_cal: u64,
    pub harvest_fee_bps: u64,
    pub minter_rights_epochs: u64,
    pub local_legend_term_epochs: u64,
    pub epochs_per_halving: u64,
    pub timestamp: i64,
}

#[event]
pub struct RideAttestationRecorded {
    pub rider: Pubkey,
    pub ride_hash: [u8; 32],
    pub parser_version: u32,
    pub economic_epoch: u64,
    pub cal_earned: u64,
    pub completed_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct CalCredited {
    pub rider: Pubkey,
    pub ride_attestation: Pubkey,
    pub amount: u64,
    pub timestamp: i64,
}

#[event]
pub struct HeldRideReleaseAuthorized {
    pub release_authority: Pubkey,
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
    pub release_settlement_week: u64,
    pub released_slot: u64,
    pub timestamp: i64,
}

#[event]
pub struct ReleasedCalCredited {
    pub cal_mint_receipt: Pubkey,
    pub release_authority: Pubkey,
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub economic_tss: u32,
    pub amount: u64,
    pub release_settlement_week: u64,
    pub timestamp: i64,
}

#[event]
pub struct ClimbCompleted {
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub completed_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct ClimbCompletionFlowAssigned {
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub completion_evidence_hash: [u8; 32],
    pub credited_settlement_week: u64,
    pub cal_tributed: u64,
    pub timestamp: i64,
}

#[event]
pub struct ClimbCompletedV2 {
    pub evidence_version: u8,
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub completed_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct ClimbCompletionFlowAssignedV2 {
    pub evidence_version: u8,
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub completion_evidence_hash: [u8; 32],
    pub credited_settlement_week: u64,
    pub cal_tributed: u64,
    pub timestamp: i64,
}

#[event]
pub struct ReleasedClimbCompleted {
    pub evidence_version: u8,
    pub climb_completion_receipt: Pubkey,
    pub release_authority: Pubkey,
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub rider: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub completed_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct ReleasedClimbCompletionFlowAssigned {
    pub evidence_version: u8,
    pub release_authority: Pubkey,
    pub vault_id: u64,
    pub ride_attestation: Pubkey,
    pub completion_evidence_hash: [u8; 32],
    pub credited_settlement_week: u64,
    pub cal_tributed: u64,
    pub timestamp: i64,
}

#[event]
pub struct BeetleCardCreated {
    pub owner: Pubkey,
    pub card_type: u8,
    pub scope_id: [u8; 32],
    pub timestamp: i64,
}

#[event]
pub struct BeetleScoreIncremented {
    pub owner: Pubkey,
    pub card_type: u8,
    pub scope_id: [u8; 32],
    pub delta_score: u64,
    pub new_score: u64,
    pub new_level: u8,
    pub leveled_up: bool,
    pub timestamp: i64,
}

#[event]
pub struct BeetleCardStats {
    pub owner: Pubkey,
    pub card_type: u8,
    pub scope_id: [u8; 32],
    pub score: u64,
    pub level: u8,
    pub patterns_scored: u32,
    pub created_at: i64,
    pub last_updated: i64,
}

#[event]
pub struct BeetleCardUpgraded {
    pub owner: Pubkey,
    pub card_type: u8,
    pub scope_id: [u8; 32],
    pub old_level: u8,
    pub new_level: u8,
    pub dung_burned: u64,
    pub timestamp: i64,
}

#[event]
pub struct BeetleUpgradeCost {
    pub owner: Pubkey,
    pub card_type: u8,
    pub current_level: u8,
    pub upgrade_cost: u64,
    pub can_upgrade: bool,
}

// --------------------- Vault Events ---------------------

#[event]
pub struct ClimbRegistered {
    pub climb: Pubkey,
    pub commitment_hash: [u8; 32],
    pub canon_id: [u8; 16],
    pub canon_version: u16,
    pub predecessor_climb: Pubkey,
    pub record_continuity_policy: RecordContinuityPolicy,
    pub registered_by: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct VaultCreated {
    pub id: u64,
    pub minter: Pubkey,
    pub signature_hash: [u8; 32],
    pub vert_m: u32,
    pub payment_method: u8,
    pub timestamp: i64,
}

#[event]
pub struct VaultCompleted {
    pub vault_id: u64,
    pub user: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub timestamp: i64,
}

#[event]
pub struct VaultCompletedV2 {
    pub evidence_version: u8,
    pub vault_id: u64,
    pub user: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub timestamp: i64,
}

#[event]
pub struct ReleasedVaultCompleted {
    pub evidence_version: u8,
    pub release_authority: Pubkey,
    pub vault_id: u64,
    pub user: Pubkey,
    pub time_s: u32,
    pub cal_tributed: u64,
    pub completion_evidence_hash: [u8; 32],
    pub is_new_kom: bool,
    pub timestamp: i64,
}

#[event]
pub struct VaultMetadataUpdated {
    pub vault_id: u64,
    pub updated_by: Pubkey,
    pub timestamp: i64,
}

// --------------------- Local Legend Events ---------------------

#[event]
pub struct LocalLegendElected {
    pub vault_id: u64,
    pub winner: Pubkey,
    pub winner_completions: u32,
    pub runner_up: Pubkey,
    pub runner_up_completions: u32,
    pub election_period: u64,
    pub term_start_epoch: u64,
    pub term_end_epoch: u64,
    pub is_bootstrap: bool,
    pub timestamp: i64,
}

#[event]
pub struct LocalLegendResigned {
    pub vault_id: u64,
    pub holder: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct LocalLegendDormant {
    pub vault_id: u64,
    pub previous_holder: Pubkey,
    pub election_period: u64,
    pub term_start_epoch: u64,
    pub term_end_epoch: u64,
    pub timestamp: i64,
}

#[event]
pub struct LocalLegendMigrated {
    pub authority: Pubkey,
    pub vault_id: u64,
    pub old_size: u32,
    pub new_size: u32,
    pub is_bootstrap: bool,
    pub migrated: bool,
    pub timestamp: i64,
}

// --------------------- Supply Cap Events ---------------------

#[event]
pub struct HalvingApplied {
    pub new_rate_bps: u64,
    pub epoch: u64,
    pub timestamp: i64,
}

#[event]
pub struct DungMintStateMigrated {
    pub authority: Pubkey,
    pub old_size: u32,
    pub new_size: u32,
    pub community_reserved: u64,
    pub reservation_policy_version: u8,
    pub vault_stake_count: u32,
    pub vault_count: u32,
    pub timestamp: i64,
}

#[event]
pub struct EmissionCapApplied {
    pub vault_id: u64,
    pub settlement_week: u64,
    pub emission_rate_bps: u64,
    pub scheduled_emission: u64,
    pub admitted_base_emission: u64,
    pub terminal: bool,
    pub timestamp: i64,
}

#[event]
pub struct DungMinted {
    pub amount: u64,
    pub allocation: u8,
    pub recipient: Pubkey,
    pub total_minted: u64,
    pub timestamp: i64,
}

#[event]
pub struct DungBurned {
    pub actor: Pubkey,
    pub amount: u64,
    pub burn_kind: u8,
    pub total_protocol_burned: u64,
    pub timestamp: i64,
}

// --------------------- Distribution Events ---------------------

/// Marks settlements that use the ratified same-week staker remainder policy.
/// Its presence lets historical indexers distinguish the prior carry policy
/// without relying on a deployment-slot configuration.
#[event]
pub struct StakerRemainderPolicyApplied {
    pub vault_id: u64,
    pub settlement_week: u64,
    pub policy_version: u8,
    pub current_locked_reallocated: u64,
    pub legacy_carry_reallocated: u64,
    pub timestamp: i64,
}

#[event]
pub struct EpochRewardsDistributed {
    pub vault_id: u64,
    pub epoch: u64,
    pub total_distributed: u64,
    pub leaderboard_distributed: u64,
    pub staker_distributed: u64,
    pub local_legend_distributed: u64,
    pub pol_distributed: u64,
    pub protocol_distributed: u64,
    /// Eligible stakers at distribution time.
    pub staker_count: u32,
    /// Current Settlement Week staker unlock percentage (0-100).
    pub unlock_pct: u8,
    /// Current-week DUNG reallocated to same-week Record Royalty.
    pub locked_staker_amount: u64,
    pub timestamp: i64,
}

// --------------------- CAL Staking Events ---------------------

#[event]
pub struct BalanceVaultAuthorityConfigured {
    pub rider: Pubkey,
    pub authority: Pubkey,
    pub policy_hash: [u8; 32],
    pub generation: u64,
    pub expires_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct BalanceVaultAuthorityRevoked {
    pub rider: Pubkey,
    pub authority: Pubkey,
    pub generation: u64,
    pub timestamp: i64,
}

#[event]
pub struct BalanceVaultOperationAuthorized {
    pub rider: Pubkey,
    pub authority: Pubkey,
    pub operation_id: [u8; 32],
    pub kind: BalanceVaultOperationKind,
    pub vault_id: u64,
    pub primary_amount: u64,
    pub secondary_amount: u64,
    pub generation: u64,
    pub nonce: u64,
    pub expires_at: i64,
    pub timestamp: i64,
}

#[event]
pub struct CalStaked {
    pub vault_id: u64,
    pub staker: Pubkey,
    pub amount: u64,
    pub lp_minted: u64,
    pub timestamp: i64,
}

#[event]
pub struct VaultLpCustodyRestored {
    pub rider: Pubkey,
    pub vault_id: u64,
    pub source: Pubkey,
    pub amount: u64,
    pub custody_amount: u64,
    pub sealed: bool,
    pub timestamp: i64,
}

#[event]
pub struct CalUnstaked {
    pub vault_id: u64,
    pub staker: Pubkey,
    pub cal_returned: u64,
    pub lp_burned: u64,
    pub timestamp: i64,
}

#[event]
pub struct UnstakeWithFee {
    pub user: Pubkey,
    pub vault_id: u64,
    pub cal_returned: u64,
    pub fee_amount: u64,
    pub timestamp: i64,
}

#[event]
pub struct RewardsHarvested {
    pub vault_id: u64,
    pub staker: Pubkey,
    pub dung_earned: u64,
    pub harvest_fee: u64,
    pub dung_received: u64,
    pub timestamp: i64,
}

#[event]
pub struct StakerAllocation {
    pub vault_id: u64,
    pub epoch: u64,
    pub staker: Pubkey,
    pub amount: u64,
    pub lp_tokens: u64,
    /// Retained for historical event-schema compatibility. New emissions store
    /// the settlement snapshot week here; `epoch` remains the canonical week.
    pub eligible_from_epoch: u64,
    pub timestamp: i64,
}

// --------------------- CAL Allocation Refactor Events ---------------------

#[event]
pub struct ProgramConfigMigrated {
    pub admin: Pubkey,
    pub new_size: u32,
    pub timestamp: i64,
}

#[event]
pub struct MintsConfigured {
    pub cal_mint: Pubkey,
    pub dung_mint: Pubkey,
    pub cal_mint_auth_bump: u8,
    pub dung_mint_auth_bump: u8,
    pub timestamp: i64,
}

#[event]
pub struct TreasuryAccountsConfigured {
    pub pol_token_account: Pubkey,
    pub treasury_token_account: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct UsdcPaymentConfigured {
    pub usdc_mint: Pubkey,
    pub usdc_treasury_token_account: Pubkey,
    pub vault_creation_usdc: u64,
    pub timestamp: i64,
}

#[event]
pub struct VaultActivated {
    pub vault_id: u64,
    pub seed_generation: u32,
    pub seed_cutoff_at: i64,
    pub activated_at: i64,
    pub economics_start_epoch: u64,
    pub matched_users: u32,
    pub matched_completions: u32,
    pub evidence_hash: [u8; 32],
    pub seed_completions_written: u32,
    pub leaderboard_seeded: bool,
    pub timestamp: i64,
}
