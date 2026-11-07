//! Program constants, PDA seeds and protocol limits.

pub const USER_SEED: &[u8] = b"user";

pub const RIDER_SOUL_SEED: &[u8] = b"rider_soul";

pub const RIDE_ATTESTATION_SEED: &[u8] = b"ride_attestation";

pub const HELD_RIDE_RELEASE_SEED: &[u8] = b"held_ride_release";

pub const RIDE_TRIBUTE_BUDGET_SEED: &[u8] = b"ride_tribute_budget";

pub const CAL_MINT_RECEIPT_SEED: &[u8] = b"cal_mint_receipt";

pub const CLIMB_COMPLETION_RECEIPT_SEED: &[u8] = b"climb_completion_receipt";

pub const CLIMB_COMPLETION_EVIDENCE_V2_DOMAIN: &[u8] = b"BR_CLIMB_COMPLETION_V2";

pub const RELEASED_CLIMB_COMPLETION_EVIDENCE_V3_DOMAIN: &[u8] = b"BR_RELEASED_CLIMB_COMPLETION_V3";

pub const BEETLE_CARD_SEED: &[u8] = b"beetle_card";

// Vault seeds
pub const CLIMB_SEED: &[u8] = b"climb";

pub const CLIMB_VERSION_INDEX_SEED: &[u8] = b"climb_version";

pub const VAULT_SEED: &[u8] = b"vault";

pub const VAULT_COUNTER_SEED: &[u8] = b"vault_counter";

pub const VAULT_LP_MINT_SEED: &[u8] = b"vault_lp";

pub const VAULT_POSITION_LP_SEED: &[u8] = b"vault_position_lp";

pub const VAULT_COMPLETION_SEED: &[u8] = b"vault_completion";

pub const VAULT_STAKE_SEED: &[u8] = b"vault_stake";

pub const VAULT_CAL_ESCROW_SEED: &[u8] = b"vault_cal_escrow";

pub const RIDER_BALANCE_SEED: &[u8] = b"rider_balance";

pub const RIDER_BALANCE_AUTH_SEED: &[u8] = b"rider_balance_auth";

pub const RIDER_BALANCE_TOKEN_SEED: &[u8] = b"rider_balance_token";

pub const BALANCE_VAULT_AUTHORITY_SEED: &[u8] = b"balance_vault_auth";

pub const BALANCE_VAULT_OPERATION_DOMAIN: &[u8] = b"BR_BALANCE_VAULT_OPERATION_V1";

pub const VAULT_EMPTY_HISTORY_V2_DOMAIN: &[u8] = b"BR_VAULT_EMPTY_HISTORY_V2";

pub const CANON_COMMITMENT_LAYOUT_VERSION: u8 = 0x01;

pub const MAX_BALANCE_VAULT_AUTHORITY_SECONDS: i64 = 7 * 24 * 60 * 60;

// CAL Allocation Refactor seeds
pub const CAL_MINT_AUTH_SEED: &[u8] = b"cal_mint_auth";

pub const DUNG_MINT_AUTH_SEED: &[u8] = b"dung_mint_auth";

pub const DUNG_DECIMALS_MULTIPLIER: u64 = 1_000_000_000; // 1 DUNG with 9 decimals

// Vault economics constants (configurable per TOKENOMICS_PARAMETERS.md)
pub const VAULT_CREATION_DUNG: u64 = 100 * DUNG_DECIMALS_MULTIPLIER; // 100 DUNG to create vault
/// Whole CAL (not base units, unlike VAULT_CREATION_DUNG) burned by
/// create_vault_with_usdc, which scales it by CAL_DECIMALS_MULTIPLIER.
pub const VAULT_CREATION_CAL: u64 = 1000;

pub const VAULT_CREATION_USDC: u64 = 2_000_000; // $2 USDC (6 decimals)
pub const VAULT_CAL_TO_DUNG_THRESHOLD: u64 = 1_000; // CAL tribute needed to emit 1 DUNG

// CAL SPL token constants (CAL Allocation Refactor)
pub const CAL_DECIMALS: u8 = 9;

pub const CAL_DECIMALS_MULTIPLIER: u64 = 1_000_000_000; // 1 CAL with 9 decimals
pub const CAL_MIN_STAKE: u64 = 100 * CAL_DECIMALS_MULTIPLIER; // Minimum 100 CAL stake (SPL)

pub const MINTER_RIGHTS_EPOCHS: u64 = 12; // ~3 months at weekly epochs
pub const EPOCH_DURATION_SECONDS: i64 = 604_800; // 7 days (weekly epochs)
pub const SETTLEMENT_FINALIZATION_GRACE_SECONDS: i64 = 86_400; // 24 hours
pub const HARVEST_FEE_BPS: u64 = 500; // 5% fee on DUNG harvest (per TOKENOMICS_V2)
pub const EXIT_FEE_BPS: u64 = 50; // 0.5% fee on CAL unstake (per TOKENOMICS_V2)
pub const MAX_RIDE_CLOCK_SKEW_SECONDS: i64 = 10 * 60;

pub const MAX_RIDE_AGE_SECONDS: i64 = 30 * 24 * 60 * 60;

pub const MAX_RIDE_DURATION_SECONDS: i64 = 36 * 60 * 60;

/// Loose physical ceiling on a ride's declared TSS. TSS accrues at
/// IF^2 * 100 per hour, so IF 40 (2,000 W normalized power at the 50 W reward
/// FTP floor) allows at most 1,600 / 36 TSS per elapsed second.
pub const MAX_RIDE_INTENSITY_FACTOR: u64 = 40;

pub const HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS: i64 = 16 * EPOCH_DURATION_SECONDS;

pub const HELD_RIDE_RELEASE_POLICY_VERSION: u8 = 1;

pub const MIN_HELD_RIDE_THRESHOLD_W: u16 = 50;

pub const MAX_HELD_RIDE_THRESHOLD_W: u16 = 500;

/// Deployed V1 settlement anchor: Sunday December 31, 2023 11:00:00 UTC.
/// It remains authoritative only for history before a configured V2 cutover.
pub const LEGACY_SETTLEMENT_WEEK_ANCHOR: i64 = 1_704_020_400;

/// Ratified cyclist-facing settlement anchor: Monday January 1, 2024 12:00:00 UTC.
pub const SETTLEMENT_WEEK_V2_ANCHOR: i64 = 1_704_110_400;

pub const SETTLEMENT_CLOCK_VERSION_V2: u8 = 2;

pub const SETTLEMENT_CLOCK_PHASE_SHIFT_SECONDS: i64 =
    SETTLEMENT_WEEK_V2_ANCHOR - LEGACY_SETTLEMENT_WEEK_ANCHOR;

/// Oldest timestamp accepted by the ride guard. Week assignment is handled by
/// the ProgramConfig-bound SettlementClock rather than this compatibility alias.
pub const EPOCH_ANCHOR: i64 = LEGACY_SETTLEMENT_WEEK_ANCHOR;

// ============================================================================
// NEW: Tokenomics V2 Constants
// ============================================================================

// New PDA seeds
pub const DUNG_MINT_STATE_SEED: &[u8] = b"dung_mint_state";

pub const VAULT_LEADERBOARD_SEED: &[u8] = b"vault_leaderboard";

pub const LOCAL_LEGEND_SEED: &[u8] = b"local_legend";

pub const VAULT_ACTIVATION_SEED: &[u8] = b"vault_activation";

pub const PROGRAM_CONFIG_SEED: &[u8] = b"program_config";

pub(crate) const MIN_AUTHORITATIVE_VAULT_SEED_GENERATION: u32 = 2;

// Supply caps (with 9 decimals)
pub const MAX_SUPPLY: u64 = 1_000_000_000 * DUNG_DECIMALS_MULTIPLIER; // 1B DUNG
pub const COMMUNITY_CAP: u64 = 400_000_000 * DUNG_DECIMALS_MULTIPLIER; // 400M
pub const TREASURY_CAP: u64 = 250_000_000 * DUNG_DECIMALS_MULTIPLIER; // 250M
pub const TEAM_CAP: u64 = 200_000_000 * DUNG_DECIMALS_MULTIPLIER; // 200M
pub const INVESTOR_CAP: u64 = 100_000_000 * DUNG_DECIMALS_MULTIPLIER; // 100M
pub const POL_CAP: u64 = 50_000_000 * DUNG_DECIMALS_MULTIPLIER; // 50M

// Halving schedule
pub const EPOCHS_PER_HALVING: u64 = 26; // ~6 months at weekly epochs
pub const MIN_EMISSION_RATE_BPS: u64 = 1;

pub const DUNG_RESERVATION_POLICY_VERSION: u8 = 1;

// Local Legend constants (replaces old 3-seat swanny system)
// Local Legend: 1 seat per vault, elected by most completions, 8-epoch term
pub const LOCAL_LEGEND_TERM_EPOCHS: u64 = 8; // 56 days (8 weekly epochs)
pub const LOCAL_LEGEND_SHARE_BPS: u64 = 300; // 3% of vault distributions (per TOKENOMICS_V2)

// Leaderboard percentages (sum = 100)
pub const LEADERBOARD_RANK_PCTS: [u8; 10] = [30, 20, 15, 10, 8, 6, 5, 3, 2, 1];

// Staker unlock curve: reverse leaderboard percentages
// Unlocks staker pool gradually based on unique staker count
// 0 stakers = 0%, 1 = 1%, 2 = 3%, ..., 10+ = 100%
// Each week's locked remainder joins that week's Record Royalty. carry_stakers
// contains only already-unlocked pro-rata integer dust.
pub const STAKER_UNLOCK_PCTS: [u8; 10] = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100];

// Stored in the retired reward_rate slot so deployed Vault accounts can cut
// over without an account resize. The marker is greater than MAX_SUPPLY and
// therefore cannot be a valid legacy DUNG reward rate.
pub const STAKER_REMAINDER_POLICY_MARKER: u64 = 0x5354_414B_4552_0001;

pub const STAKER_REMAINDER_POLICY_VERSION: u8 = 1;

pub(crate) const BASIS_POINTS_DENOMINATOR: u64 = 10_000;

pub(crate) const PERCENT_TO_BPS: u64 = 100;

// ============================================================================

// Beetle Card constants - soulbound effort NFTs
pub const GLOBAL_SCOPE: [u8; 32] = [0u8; 32]; // Zero bytes = global scope (Steady, Explorer)

// Level thresholds for Beetle Cards (cumulative scores) - ELIGIBILITY GATES
// HYBRID model: Score thresholds UNLOCK eligibility, then DUNG burn to CLAIM level.
// Users must reach the score threshold before they can upgrade by burning DUNG.
pub const LEVEL_THRESHOLDS: [u64; 10] = [
    100,       // Level 1: 100 score required
    500,       // Level 2: 500 score required
    1_500,     // Level 3: 1,500 score required
    5_000,     // Level 4: 5,000 score required
    15_000,    // Level 5: 15,000 score required + gate check
    50_000,    // Level 6: 50,000 score required
    150_000,   // Level 7: 150,000 score required + gate check
    500_000,   // Level 8: 500,000 score required + gate check
    1_500_000, // Level 9: 1,500,000 score required + gate check
    5_000_000, // Level 10 (max): 5,000,000 score + ELITE GATE (5 KOMs, 4.0 w/kg, 60-day streak, 50K TSS)
];

// Beetle Card upgrade costs (TOKENOMICS_V2 spec)
// Formula: 25 * 2^(level-1) DUNG
// L1->2: 25, L2->3: 50, L3->4: 100, L4->5: 200, etc.
pub const BEETLE_BASE_UPGRADE_COST: u64 = 25 * DUNG_DECIMALS_MULTIPLIER; // 25 DUNG
pub const BEETLE_MAX_LEVEL: u8 = 10;

pub const DUNG_BURN_KIND_BEETLE_UPGRADE: u8 = 0;

pub const DUNG_BURN_KIND_VAULT_CREATION: u8 = 1;
