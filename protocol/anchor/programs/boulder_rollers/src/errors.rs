//! Program error codes. Variants are append-only: on-chain codes are their positions.

use crate::*;

// --------------------- Errors ---------------------

#[error_code]
pub enum ErrorCode {
    #[msg("Already minted CAL today")]
    AlreadyMintedToday,

    #[msg("Insufficient CAL balance")]
    InsufficientCal,

    #[msg("Invalid segment name")]
    InvalidName,

    #[msg("Invalid distance")]
    InvalidDistance,

    #[msg("Invalid elevation")]
    InvalidElevation,

    #[msg("Minimum stake is 10 DUNG")]
    MinimumStakeRequired,

    #[msg("Epoch already distributed")]
    AlreadyDistributed,

    #[msg("Epoch not ended yet")]
    EpochNotEnded,

    #[msg("Settlement week is not yet finalizable")]
    SettlementWeekNotFinalizable,

    // Deprecated ABI slot. Lifetime tribute no longer admits rides by week.
    #[msg("Ride completed outside the currently open settlement window")]
    RideOutsideSettlementWindow,

    #[msg("Settlement week is out of sync with the vault state")]
    SettlementWeekOutOfSync,

    #[msg("Local Legend seat occupied - term has not expired")]
    SeatOccupied,

    #[msg("Election too soon - current term has not expired")]
    ElectionTooSoon,

    #[msg("Overflow")]
    Overflow,

    #[msg("Underflow")]
    Underflow,

    #[msg("Division by zero")]
    DivisionByZero,

    #[msg("Invalid scope for card type")]
    InvalidScope,

    #[msg("Invalid score delta")]
    InvalidScore,

    #[msg("Card already exists")]
    CardAlreadyExists,

    #[msg("Unauthorized scoring authority")]
    UnauthorizedAuthority,

    // Vault errors
    #[msg("Invalid completion time")]
    InvalidCompletionTime,

    #[msg("Invalid vault completion evidence hash")]
    InvalidEvidenceHash,

    #[msg("Ride timestamps are invalid")]
    InvalidRideTimestamps,

    #[msg("Ride attestation does not match the requested rider or action")]
    InvalidRideAttestation,

    #[msg("Requested amount does not match the recorded ride attestation")]
    AttestationAmountMismatch,

    #[msg("Insufficient tribute accumulated")]
    InsufficientTribute,

    #[msg("Invalid metadata length")]
    InvalidMetadata,

    // Supply cap errors
    #[msg("Supply cap exceeded")]
    SupplyCapExceeded,

    #[msg("Allocation cap exceeded")]
    AllocationCapExceeded,

    #[msg("Halving can only be applied once per halving period")]
    HalvingTooSoon,

    // Distribution errors
    #[msg("Invalid distribution config (must equal canonical 55/27/3/5/10 policy)")]
    InvalidDistributionConfig,

    #[msg("Invalid protocol parameters")]
    InvalidProtocolParameters,

    #[msg("Invalid ProgramConfig account layout")]
    InvalidProgramConfigLayout,

    #[msg("ProgramConfig does not contain the versioned settlement clock")]
    SettlementClockNotConfigured,

    #[msg("Settlement clock cutover must be a future Monday 12:00 UTC boundary")]
    InvalidSettlementClockCutover,

    #[msg("Settlement clock is immutable once configured")]
    SettlementClockAlreadyConfigured,

    #[msg("Protocol treasury account is required")]
    MissingProtocolTreasury,

    #[msg("Supply cap reached for allocation")]
    SupplyCapReached,

    #[msg("DungMintState account layout is not a supported 121, 129, or current layout")]
    InvalidDungMintStateLayout,

    #[msg("DungMintState total_minted does not equal the sum of allocation bucket counters")]
    DungMintAccountingMismatch,

    #[msg("Community reservation does not match the exact outstanding Community liabilities")]
    CommunityReservationMismatch,

    #[msg("Community reservation is smaller than the claim being collected")]
    InsufficientCommunityReservation,

    #[msg("VaultStake migration inventory count does not match the signed expectation")]
    VaultStakeCountMismatch,

    #[msg("Duplicate VaultStake account in migration inventory")]
    DuplicateVaultStake,

    #[msg("Invalid amount")]
    InvalidAmount,

    #[msg("Beetle card is already at maximum level")]
    MaxLevelReached,

    #[msg("Insufficient DUNG balance for upgrade")]
    InsufficientDungForUpgrade,

    #[msg("No rewards available to harvest")]
    NoRewardsToHarvest,

    #[msg("Insufficient score to unlock this level - keep earning effort points")]
    InsufficientScoreForUpgrade,

    #[msg("Elite gate requirements not met - requires 5 KOMs, 4.0 w/kg, 60-day streak, 50K TSS")]
    EliteGateNotMet,

    // Merkle proof errors
    #[msg("Invalid batch size")]
    InvalidBatchSize,

    #[msg("Invalid tree depth")]
    InvalidTreeDepth,

    #[msg("Invalid Merkle proof - verification failed")]
    InvalidMerkleProof,

    #[msg("Batch not found")]
    BatchNotFound,

    // Ownership errors
    #[msg("Account is not owned by signer")]
    NotOwner,

    // Admin authority errors
    #[msg("Unauthorized admin - signer does not match admin_authority")]
    UnauthorizedAdmin,

    #[msg("Unauthorized backend - signer does not match backend_authority")]
    UnauthorizedBackend,

    #[msg("Program config already initialized")]
    AlreadyInitialized,

    #[msg("Program config not initialized - call initialize_program_config first")]
    NotInitialized,

    // CAL Allocation Refactor errors
    #[msg("Mints already configured - configure_mints is one-time only")]
    MintsAlreadyConfigured,

    #[msg("Mints not yet configured - call configure_mints first")]
    MintsNotConfigured,

    #[msg("USDC payment rail not yet configured")]
    UsdcNotConfigured,

    #[msg("Unauthorized allocation submitter")]
    UnauthorizedSubmitter,

    #[msg("Invalid mint - does not match ProgramConfig")]
    InvalidMint,

    #[msg("Vault CAL escrow not initialized")]
    EscrowNotInitialized,

    #[msg("Token account owner does not match expected user")]
    InvalidTokenAccountOwner,

    #[msg("Epoch is not current or just-ended")]
    InvalidEpoch,

    #[msg("Vault is already activated")]
    VaultAlreadyActive,

    #[msg("Invalid vault activation seed audit state")]
    InvalidActivationSeed,

    #[msg("Vault is not yet activated - historical seeding in progress")]
    VaultNotActive,

    #[msg("Invalid vault account - wrong owner, empty, or PDA mismatch")]
    InvalidVault,

    #[msg("Vault already has live economic state; settlement-week override is unsafe")]
    VaultNotPristine,

    #[msg("Epoch already distributed for this vault")]
    EpochAlreadyDistributed,

    #[msg("Invalid token account - does not match configured address")]
    InvalidTokenAccount,

    #[msg("Invalid vault stake account passed to settlement")]
    InvalidStakeAccount,

    #[msg("Stake snapshot already has an unresolved change for another Settlement Week")]
    StakeSnapshotQueueFull,

    #[msg("Invalid RiderBalance account")]
    InvalidRiderBalance,

    #[msg("RiderBalance is not active")]
    InvalidBalanceStatus,

    #[msg("Invalid upgradeable program account")]
    InvalidProgramAccount,

    #[msg("Invalid upgradeable ProgramData account")]
    InvalidProgramData,

    // DUNG monetary-policy errors. Appended to preserve deployed error codes.
    #[msg("Emission halvings are automatic during Settlement and cannot be applied manually")]
    AutomaticEmissionSchedule,

    #[msg("POL and treasury carry must be zero because those recipients are always available")]
    UnreservedProtocolCarry,

    #[msg("Vault migration inventory count does not match VaultCounter")]
    VaultCountMismatch,

    #[msg("Duplicate Vault account in migration inventory")]
    DuplicateVault,

    #[msg("Duplicate account in DUNG migration inventory")]
    DuplicateMigrationAccount,

    #[msg("DUNG migration inventory contains an unexpected account")]
    InvalidMigrationInventory,

    #[msg("DUNG Community reservation policy migration has not completed")]
    DungReservationPolicyNotMigrated,

    #[msg("Stored DungMintState authority does not match ProgramConfig admin authority")]
    DungMintAuthorityMismatch,

    #[msg("Stored DungMintState bump is not the canonical PDA bump")]
    InvalidDungMintStateBump,

    #[msg("Legacy manual-halving history cannot prove the immutable emission start")]
    LegacyEmissionHistoryAmbiguous,

    // Ride tribute conservation errors. Appended to preserve deployed error codes.
    #[msg("Ride aggregate tribute exceeds ratified CAL tribute budget")]
    RideTributeBudgetExceeded,

    #[msg("Ride tribute budget account is missing or invalid")]
    InvalidRideTributeBudget,

    // Local Legend term-clock errors. Appended to preserve deployed error codes.
    #[msg("Local Legend term cannot begin after the current Settlement Week")]
    LocalLegendTermInFuture,

    #[msg("Local Legend term must continue from the prior term end")]
    LocalLegendTermOutOfSequence,

    // Completion evidence V2 errors. Appended to preserve deployed error codes.
    #[msg("V1 completion evidence is historical and cannot accept new writes")]
    LegacyCompletionEvidenceDisabled,

    #[msg("Completion evidence hash does not bind the exact V2 tribute fields")]
    CompletionEvidenceMismatch,

    // DUNG burn telemetry error. Appended to preserve deployed error codes.
    #[msg("Protocol DUNG burns cannot exceed lifetime DUNG minted by this program")]
    DungBurnAccountingMismatch,

    // ProgramConfig patch-version errors. Appended to preserve deployed codes.
    #[msg("ProgramConfig version changed before this transition was submitted")]
    StaleProgramVersion,

    #[msg("ProgramConfig version transitions must move forward")]
    RegressiveProgramVersion,

    #[msg("ProgramConfig version transitions cannot skip a patch")]
    SkippedProgramVersion,

    #[msg("Requested ProgramConfig version is not supported by this program")]
    UnsupportedProgramVersion,

    // Local Legend account-layout errors. Appended to preserve deployed codes.
    #[msg("Local Legend account layout is unsupported or corrupt")]
    InvalidLocalLegendLayout,

    #[msg("Stored Local Legend vault id does not match its PDA seed")]
    LocalLegendVaultMismatch,

    #[msg("Stored Local Legend bump is not the canonical PDA bump")]
    InvalidLocalLegendBump,

    // Vault LP custody errors. Appended to preserve deployed error codes.
    #[msg("Vault position LP authority does not match its VaultStake PDA")]
    InvalidLpCustodyAuthority,

    #[msg("Vault position LP custody is not in the required frozen state")]
    InvalidLpCustodyState,

    #[msg("Vault position LP amount does not match the recorded position")]
    LpCustodyAmountMismatch,

    #[msg("Legacy LP source does not hold the requested restoration amount")]
    InsufficientLpCustody,

    // Balance-funded Vault authorization errors. Appended to preserve deployed codes.
    #[msg("Balance-funded Vault action does not have the configured rider authority")]
    InvalidBalanceVaultAuthority,

    #[msg("Balance-funded Vault authority has expired")]
    BalanceVaultAuthorityExpired,

    #[msg("Balance-funded Vault authority has been revoked")]
    BalanceVaultAuthorityRevoked,

    #[msg("Balance-funded Vault authority generation is stale")]
    StaleBalanceVaultAuthority,

    #[msg("Balance-funded Vault operation does not match its signed intent")]
    InvalidBalanceVaultOperation,

    #[msg("Balance-funded Vault operation intent has expired")]
    BalanceVaultOperationExpired,

    #[msg("Balance-funded Vault operation nonce is stale or already consumed")]
    BalanceVaultOperationReplay,

    // V4-B canon Climb errors. Appended to preserve V4-A deployed codes.
    #[msg("Canon commitment fields or hash do not match the deterministic D12 layout")]
    InvalidCanonCommitment,

    #[msg("Canon version does not have the exact required predecessor and continuity")]
    InvalidCanonLineage,

    #[msg("Climb account is not the canonical program-owned commitment PDA")]
    InvalidClimb,

    #[msg("Climb already has its sole economic Vault activation")]
    ClimbAlreadyActivated,

    #[msg("Canon Climb already has a registered successor")]
    CanonSuccessorAlreadyRegistered,

    #[msg("Canon Climb is stale because a successor version is registered")]
    StaleClimbVersion,

    #[msg("Carry-records-forward is unavailable until exact on-chain record continuity exists")]
    RecordContinuityUnavailable,

    // Held-ride Threshold release errors. Appended to preserve deployed codes.
    #[msg("Held-ride release timestamps are invalid relative to chain admission")]
    InvalidHeldRideReleaseWindow,

    #[msg("Threshold authority became effective after the held-ride eligibility window")]
    HeldRideReleaseWindowExpired,

    #[msg("Held-ride release cannot precede the Threshold authority effective time")]
    HeldRideThresholdNotEffective,

    #[msg("Held-ride parent attestation already contains ordinary economics")]
    HeldRideParentHasEconomics,

    #[msg("Held-ride release tribute budget is missing or invalid")]
    InvalidHeldRideTributeBudget,

    #[msg("Held-ride release authority does not match its immutable parent or rider")]
    InvalidHeldRideReleaseAuthority,

    #[msg("Held-ride release Threshold is outside the admitted structural bounds")]
    InvalidHeldRideThreshold,

    #[msg("Held-ride release Threshold policy version is unsupported")]
    InvalidHeldRideReleasePolicy,

    #[msg("Released completion evidence does not bind the exact release fields")]
    ReleasedCompletionEvidenceMismatch,

    #[msg("Held-ride release Settlement Flow is not open yet")]
    HeldRideReleaseFlowNotOpen,

    #[msg("Held-ride release Settlement Flow has already closed")]
    HeldRideReleaseFlowClosed,

    // Stage 1 errors appended; legacy numeric codes are unchanged.
    #[msg("Stage 1 owner or admin authorization required")]
    Stage1Unauthorized,

    #[msg("Stage 1 arithmetic exceeds account integer limits")]
    Stage1Arithmetic,

    #[msg("Asset adapter is disabled in this build or for new intake")]
    Stage1AdapterDisabled,

    #[msg("Positive exact redemption rate required")]
    Stage1InvalidRate,

    #[msg("Redemption observation is stale or in the future")]
    Stage1StaleRate,

    #[msg("Invalid Stage 1 lot binding")]
    Stage1InvalidLot,

    #[msg("Complete distinct held-lot inventory required")]
    Stage1InvalidInventory,

    #[msg("Invalid lot token custody")]
    Stage1InvalidCustody,

    #[msg("Invalid asset binding")]
    Stage1InvalidAsset,

    #[msg("Canonical current Climb required")]
    Stage1InvalidHill,

    #[msg("City launch must be a Monday 12 UTC boundary")]
    Stage1InvalidCalendar,

    #[msg("City has not launched")]
    Stage1NotLaunched,

    #[msg("Positive amount and admitted lock required")]
    Stage1InvalidAmount,

    #[msg("Ratified exposure cap exceeded")]
    Stage1ExposureCap,

    #[msg("Triggering pledge does not bond this hill")]
    Stage1BelowLine,

    #[msg("Only a pre-bond pledge can be cancelled")]
    Stage1CannotCancel,

    #[msg("Pre-bond income belongs to the owner")]
    Stage1NotBonded,

    #[msg("Harvest would consume protected principal")]
    Stage1PrincipalProtected,

    #[msg("Invalid or replayed withdrawal request")]
    Stage1InvalidRequest,

    #[msg("Lot lock has not elapsed")]
    Stage1Locked,

    #[msg("Four weeks of notice have not elapsed")]
    Stage1NoticeIncomplete,

    #[msg("Partial exit is smaller than one returnable token base unit")]
    Stage1ExitTooSmall,
    #[msg("Refresh each active campaign lot at the current numeric rates before bonding")]
    Stage1CampaignRefreshRequired,
    #[msg("A stale full-lot exit requires notice for all remaining basis")]
    Stage1StalePartialExit,
    #[msg("Provider identity, owner, mint or layout is invalid")]
    Stage1InvalidProvider,
    #[msg("A current provider rate must be admitted first")]
    Stage1RateRefreshRequired,
    #[msg("The provider or its admitted epoch is still available")]
    Stage1ProviderAvailable,
    #[msg("Provider exit configuration has not been verified for admission")]
    Stage1ProviderPolicyUnverified,
    #[msg("Provider cannot prove a continuous outage from this account layout")]
    Stage1ProviderOutageUnverifiable,
    #[msg("Stage 1 per-asset equalities failed")]
    Stage1Solvency,
    #[msg("Invalid or insufficient hill/week/asset funding")]
    Stage1InvalidFunding,
    #[msg("Invalid Merkle-sum proof, padding, count or leaf")]
    Stage1InvalidProof,
    #[msg("Allocation exceeds the frozen rider cap")]
    Stage1AllocationCap,
    #[msg("Fixed recipient registration does not match this claim")]
    Stage1InvalidRecipient,
    #[msg("Weekly measurement commitment is already frozen or empty")]
    Stage1SnapshotFrozen,
    #[msg("Week is not next or has not passed close plus grace")]
    Stage1WeekNotFinalizable,
    #[msg("Invalid, expired or stale hold release proposal")]
    Stage1InvalidHold,
    #[msg("Held tranche has not reached its original 26-week age")]
    Stage1HoldNotExpired,
    #[msg("Boost must start 1..13 weeks after the current city week")]
    Stage1BoostStartHorizon,
    #[msg("Every boost hill-week tranche must be at least 1 USDC")]
    Stage1BoostTrancheMinimum,
    #[msg("Quiet-week skip reaches a boost tranche due week")]
    Stage1SkipBoostDue,
    #[msg("Quiet-week skip reaches an original hold maturity")]
    Stage1SkipHoldMaturity,
    #[msg("Stage 1 deposits, pledges and bonds are paused")]
    Stage1IntakePaused,
    #[msg("Guardian must be a separate, nonzero emergency signer")]
    Stage1InvalidGuardian,
    #[msg("Stage 1 city layout is not the exact pre-governance or current layout")]
    Stage1InvalidCityLayout,
    #[msg("Weekly publication and settlement processing are paused")]
    Stage1SettlementPaused,
    #[msg("Claim storage layout, allocation or publication state is invalid")]
    Stage1ClaimStorage,
    #[msg("This claim index or person has already been paid")]
    Stage1ClaimReplay,
    #[msg("One to four distinct claim sets are required")]
    Stage1InvalidBatch,
    #[msg("Ride CAL exceeds one whole CAL per declared TSS")]
    RideCalExceedsTss,
    #[msg("Declared TSS exceeds the intensity ceiling for the ride's duration")]
    RideTssExceedsDuration,
}
