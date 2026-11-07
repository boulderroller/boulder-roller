use super::*;
use std::str::FromStr;

fn distribution_config() -> DistributionConfig {
    DistributionConfig {
        leaderboard_share_bps: 5_500,
        staker_share_bps: 2_700,
        local_legend_share_bps: 300,
        pol_share_bps: 500,
        protocol_fee_bps: 1_000,
    }
}

fn test_settlement_clock() -> SettlementClock {
    SettlementClock::v2_only()
}

fn ride_bound_error(result: Result<()>) -> String {
    match result {
        Err(anchor_lang::error::Error::AnchorError(error)) => error.error_name,
        other => panic!("expected a ride bound rejection, got {other:?}"),
    }
}

#[test]
fn ride_cal_is_bounded_by_the_backend_tss_conversion() {
    let bound = require_ride_economics_within_bounds;
    let (start, end) = (1_700_000_000, 1_700_003_600);
    // The backend floors display TSS and base units from one decimal TSS:
    // 250.999999999 TSS records total_tss 250 and 250_999_999_999 base units.
    assert!(bound(start, end, 250, 250_999_999_999).is_ok());
    assert!(bound(start, end, 250, 250 * CAL_DECIMALS_MULTIPLIER).is_ok());
    // Held and uncounted rides carry no CAL; counted TSS without CAL is fine.
    assert!(bound(start, end, 0, 0).is_ok());
    assert!(bound(start, end, 250, 0).is_ok());
    assert_eq!(
        ride_bound_error(bound(start, end, 250, 251 * CAL_DECIMALS_MULTIPLIER)),
        "RideCalExceedsTss"
    );
    assert_eq!(
        ride_bound_error(bound(start, end, 0, CAL_DECIMALS_MULTIPLIER)),
        "RideCalExceedsTss"
    );
    assert_eq!(
        ride_bound_error(bound(start, end, 0, u64::MAX)),
        "RideCalExceedsTss"
    );
}

#[test]
fn ride_tss_is_bounded_by_intensity_factor_forty_over_elapsed_time() {
    let bound = require_ride_economics_within_bounds;
    let start = 1_700_000_000;
    // One hour at IF 40 is 40^2 * 100 = 160,000 TSS.
    assert!(bound(start, start + 3_600, 160_000, 0).is_ok());
    assert_eq!(
        ride_bound_error(bound(start, start + 3_600, 160_001, 0)),
        "RideTssExceedsDuration"
    );
    // The ceiling scales with elapsed seconds, including the shortest ride.
    assert!(bound(start, start + 9, 400, 0).is_ok());
    assert_eq!(
        ride_bound_error(bound(start, start + 9, 401, 0)),
        "RideTssExceedsDuration"
    );
    // The longest admissible ride still cannot carry u32::MAX TSS.
    let longest = start + MAX_RIDE_DURATION_SECONDS;
    assert!(bound(start, longest, 5_760_000, 0).is_ok());
    assert_eq!(
        ride_bound_error(bound(start, longest, u32::MAX, 0)),
        "RideTssExceedsDuration"
    );
    // A ride with no elapsed time carries no TSS at all.
    assert_eq!(
        ride_bound_error(bound(start, start, 1, 0)),
        "InvalidRideTimestamps"
    );
}

#[test]
fn ride_economics_bound_admits_the_worst_real_power_ride_with_margin() {
    let bound = require_ride_economics_within_bounds;
    // Worst of 480 real power rides re-priced at the 50 W reward FTP floor:
    // 1.775 TSS per elapsed second, against a 44.4 TSS/s ceiling.
    let start = 1_700_000_000;
    let elapsed = 3_600;
    let tss = 1_775 * elapsed as u32 / 1_000;
    let cal = u64::from(tss) * CAL_DECIMALS_MULTIPLIER + 999_999_999;
    assert!(bound(start, start + elapsed, tss, cal).is_ok());
    assert!(bound(start, start + elapsed, tss * 25, 0).is_ok());
}

#[test]
fn canon_commitment_v1_matches_cross_language_vector() {
    let canon_id = [
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd,
        0xee, 0xff,
    ];
    let profile_hash = std::array::from_fn(|index| index as u8);

    let commitment = build_canon_commitment_v1(canon_id, 0x0102, profile_hash).unwrap();

    assert_eq!(
        commitment,
        [
            0x01, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb, 0xcc,
            0xdd, 0xee, 0xff, 0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
            0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
            0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f,
        ]
    );
    assert_eq!(
        canon_commitment_hash(&commitment),
        [
            0x52, 0xba, 0xdf, 0x13, 0x70, 0xae, 0x44, 0xb8, 0x76, 0xa6, 0xd1, 0x0c, 0xcd, 0xae,
            0x13, 0x97, 0xe5, 0xf4, 0xa3, 0x15, 0x90, 0x0c, 0x91, 0xdd, 0xcb, 0x4f, 0x1b, 0x89,
            0xe7, 0x76, 0xe3, 0xc0,
        ]
    );
}

#[test]
fn canon_registration_rejects_zero_identity_and_invalid_lineage() {
    let canon_id = [7; 16];
    let profile_hash = [9; 32];

    assert_error_code(
        build_canon_commitment_v1([0; 16], 1, profile_hash),
        ErrorCode::InvalidCanonCommitment,
    );
    assert_error_code(
        build_canon_commitment_v1(canon_id, 0, profile_hash),
        ErrorCode::InvalidCanonCommitment,
    );
    assert_error_code(
        build_canon_commitment_v1(canon_id, 1, [0; 32]),
        ErrorCode::InvalidCanonCommitment,
    );
    assert!(
        validate_climb_lineage(canon_id, 1, RecordContinuityPolicy::NewRecordBoard, None,)
            .is_ok()
    );
    assert_error_code(
        validate_climb_lineage(
            canon_id,
            1,
            RecordContinuityPolicy::CarryRecordsForward,
            None,
        ),
        ErrorCode::RecordContinuityUnavailable,
    );
    assert_error_code(
        validate_climb_lineage(canon_id, 2, RecordContinuityPolicy::NewRecordBoard, None),
        ErrorCode::InvalidCanonLineage,
    );
    assert!(validate_climb_lineage(
        canon_id,
        2,
        RecordContinuityPolicy::NewRecordBoard,
        Some((canon_id, 1)),
    )
    .is_ok());
    assert_error_code(
        validate_climb_lineage(
            canon_id,
            3,
            RecordContinuityPolicy::CarryRecordsForward,
            Some((canon_id, 1)),
        ),
        ErrorCode::RecordContinuityUnavailable,
    );
    assert_error_code(
        validate_climb_lineage(
            canon_id,
            2,
            RecordContinuityPolicy::CarryRecordsForward,
            Some(([8; 16], 1)),
        ),
        ErrorCode::RecordContinuityUnavailable,
    );
}

#[test]
fn wallet_funded_vault_creation_rejects_permissionless_counter_consumption() {
    let backend_authority = Pubkey::new_unique();

    assert!(
        require_backend_vault_creation_sponsor(backend_authority, backend_authority,).is_ok()
    );
    assert_error_code(
        require_backend_vault_creation_sponsor(backend_authority, Pubkey::new_unique()),
        ErrorCode::UnauthorizedBackend,
    );
}

#[test]
fn carry_records_forward_is_unavailable_until_exact_continuity_exists() {
    let canon_id = [7; 16];

    assert_error_code(
        validate_climb_lineage(
            canon_id,
            2,
            RecordContinuityPolicy::CarryRecordsForward,
            Some((canon_id, 1)),
        ),
        ErrorCode::RecordContinuityUnavailable,
    );
}

fn ratified_test_climb() -> Climb {
    let canon_id = [7; 16];
    let canonical_profile_hash = [9; 32];
    let canon_commitment =
        build_canon_commitment_v1(canon_id, 1, canonical_profile_hash).unwrap();
    let mut name = [0; 64];
    name[..12].copy_from_slice(b"Test Climb 1");
    Climb {
        canon_commitment,
        commitment_hash: canon_commitment_hash(&canon_commitment),
        canon_id,
        canon_version: 1,
        canonical_profile_hash,
        predecessor_climb: Pubkey::default(),
        successor_climb: Pubkey::default(),
        record_continuity_policy: RecordContinuityPolicy::NewRecordBoard,
        vault: Pubkey::default(),
        name,
        vert_m: 1_234,
        distance_m: 5_678,
        avg_gradient_pct: 712,
        registered_at: 1_700_000_000,
        registered_by: Pubkey::new_unique(),
        bump: 253,
    }
}

#[test]
fn vault_binding_copies_only_ratified_climb_identity_and_is_single_use() {
    let mut climb = ratified_test_climb();
    let climb_key = Pubkey::new_unique();
    let vault_key = Pubkey::new_unique();

    let binding = bind_climb_to_vault(&mut climb, climb_key, vault_key).unwrap();

    assert_eq!(binding.climb, climb_key);
    assert_eq!(binding.canon_commitment, climb.canon_commitment);
    assert_eq!(binding.commitment_hash, climb.commitment_hash);
    assert_eq!(binding.name, climb.name);
    assert_eq!(binding.vert_m, climb.vert_m);
    assert_eq!(binding.distance_m, climb.distance_m);
    assert_eq!(binding.avg_gradient_pct, climb.avg_gradient_pct);
    assert_eq!(climb.vault, vault_key);
    assert_error_code(
        bind_climb_to_vault(&mut climb, climb_key, Pubkey::new_unique()),
        ErrorCode::ClimbAlreadyActivated,
    );
}

#[test]
fn successor_registration_makes_predecessor_stale_and_rejects_branch() {
    let mut predecessor = ratified_test_climb();
    let successor = Pubkey::new_unique();

    link_climb_successor(&mut predecessor, successor).unwrap();
    assert_eq!(predecessor.successor_climb, successor);
    assert_error_code(
        bind_climb_to_vault(&mut predecessor, Pubkey::new_unique(), Pubkey::new_unique()),
        ErrorCode::StaleClimbVersion,
    );
    assert_error_code(
        link_climb_successor(&mut predecessor, Pubkey::new_unique()),
        ErrorCode::CanonSuccessorAlreadyRegistered,
    );
}

#[test]
fn vault_binding_rejects_corrupt_commitment_and_account_sizes_are_exact() {
    let mut climb = ratified_test_climb();
    climb.canon_commitment[19] = 1;
    assert_error_code(
        bind_climb_to_vault(&mut climb, Pubkey::new_unique(), Pubkey::new_unique()),
        ErrorCode::InvalidCanonCommitment,
    );

    let climb = ratified_test_climb();
    let mut climb_data = Vec::with_capacity(Climb::SIZE);
    climb.try_serialize(&mut climb_data).unwrap();
    assert_eq!(climb_data.len(), Climb::SIZE);

    let version_index = ClimbVersionIndex {
        canon_id: climb.canon_id,
        canon_version: climb.canon_version,
        climb: Pubkey::new_unique(),
        bump: 252,
    };
    let mut index_data = Vec::with_capacity(ClimbVersionIndex::SIZE);
    version_index.try_serialize(&mut index_data).unwrap();
    assert_eq!(index_data.len(), ClimbVersionIndex::SIZE);
    assert_eq!(Vault::SIZE, 649);
}

#[test]
fn clean_vault_activation_is_generation_two_with_frozen_empty_history_evidence() {
    let mut activation = vault_activation(false, 0);
    let leaderboard = empty_vault_leaderboard(7, 253);
    let climb = Pubkey::new_from_array([0x11; 32]);
    let vault = Pubkey::new_from_array([0x22; 32]);

    initialize_chain_authoritative_activation(
        &mut activation,
        7,
        1_700_000_000,
        52,
        &climb,
        &vault,
        254,
    );

    assert!(activation.is_active);
    assert_eq!(leaderboard.vault_id, 7);
    assert!(leaderboard.entries.is_empty());
    assert_eq!(leaderboard.last_updated, 0);
    assert_eq!(leaderboard.bump, 253);
    assert_eq!(activation.seed_generation, 2);
    assert_eq!(activation.seed_completions_written, 0);
    assert!(activation.leaderboard_seeded);
    assert_eq!(activation.activated_at, 1_700_000_000);
    assert_eq!(activation.economics_start_epoch, 52);
    assert_eq!(
        activation.evidence_hash,
        [
            0x44, 0xc8, 0x21, 0x58, 0xa1, 0xcc, 0x16, 0xd5, 0x46, 0x61, 0x4c, 0x03, 0x30, 0x60,
            0xaf, 0x41, 0x91, 0xf2, 0xa8, 0x4d, 0xfe, 0x97, 0x2c, 0x4e, 0x35, 0x00, 0x22, 0x91,
            0x1c, 0xb7, 0x23, 0x94,
        ]
    );
    assert_ne!(activation.evidence_hash, [0; 32]);
    assert!(activation.permits_new_economic_history());
}

fn vault_activation(is_active: bool, seed_generation: u32) -> VaultActivation {
    VaultActivation {
        vault_id: 7,
        is_active,
        seed_completions_written: 0,
        leaderboard_seeded: false,
        created_at: 0,
        activated_at: 0,
        last_seed_at: 0,
        seed_generation,
        seed_cutoff_at: 0,
        economics_start_epoch: 0,
        matched_users: 0,
        matched_completions: 0,
        evidence_hash: [0; 32],
        bump: 255,
    }
}

#[test]
fn vault_activation_quarantines_legacy_generations_from_new_economic_history() {
    let actual =
        [(true, 0), (true, 1), (true, 2), (false, 2)].map(|(is_active, generation)| {
            vault_activation(is_active, generation).permits_new_economic_history()
        });

    assert_eq!(actual, [false, false, true, false]);
}

#[test]
fn appended_tribute_errors_preserve_deployed_error_indices() {
    assert_eq!(ErrorCode::InsufficientTribute as u32, 25);
    assert_eq!(ErrorCode::LegacyEmissionHistoryAmbiguous as u32, 89);
    assert_eq!(ErrorCode::RideTributeBudgetExceeded as u32, 90);
    assert_eq!(ErrorCode::InvalidRideTributeBudget as u32, 91);
    assert_eq!(ErrorCode::LocalLegendTermInFuture as u32, 92);
    assert_eq!(ErrorCode::LocalLegendTermOutOfSequence as u32, 93);
    assert_eq!(ErrorCode::LegacyCompletionEvidenceDisabled as u32, 94);
    assert_eq!(ErrorCode::CompletionEvidenceMismatch as u32, 95);
    assert_eq!(ErrorCode::DungBurnAccountingMismatch as u32, 96);
    assert_eq!(ErrorCode::StaleProgramVersion as u32, 97);
    assert_eq!(ErrorCode::RegressiveProgramVersion as u32, 98);
    assert_eq!(ErrorCode::SkippedProgramVersion as u32, 99);
    assert_eq!(ErrorCode::UnsupportedProgramVersion as u32, 100);
    assert_eq!(ErrorCode::InvalidLocalLegendLayout as u32, 101);
    assert_eq!(ErrorCode::LocalLegendVaultMismatch as u32, 102);
    assert_eq!(ErrorCode::InvalidLocalLegendBump as u32, 103);
    assert_eq!(ErrorCode::InvalidLpCustodyAuthority as u32, 104);
    assert_eq!(ErrorCode::InvalidLpCustodyState as u32, 105);
    assert_eq!(ErrorCode::LpCustodyAmountMismatch as u32, 106);
    assert_eq!(ErrorCode::InsufficientLpCustody as u32, 107);
    assert_eq!(ErrorCode::InvalidCanonCommitment as u32, 115);
    assert_eq!(ErrorCode::InvalidCanonLineage as u32, 116);
    assert_eq!(ErrorCode::InvalidClimb as u32, 117);
    assert_eq!(ErrorCode::ClimbAlreadyActivated as u32, 118);
    assert_eq!(ErrorCode::CanonSuccessorAlreadyRegistered as u32, 119);
    assert_eq!(ErrorCode::StaleClimbVersion as u32, 120);
    assert_eq!(ErrorCode::RecordContinuityUnavailable as u32, 121);
    assert_eq!(ErrorCode::InvalidHeldRideReleaseWindow as u32, 122);
    assert_eq!(ErrorCode::HeldRideReleaseWindowExpired as u32, 123);
    assert_eq!(ErrorCode::HeldRideThresholdNotEffective as u32, 124);
    assert_eq!(ErrorCode::HeldRideParentHasEconomics as u32, 125);
    assert_eq!(ErrorCode::InvalidHeldRideTributeBudget as u32, 126);
    assert_eq!(ErrorCode::InvalidHeldRideReleaseAuthority as u32, 127);
    assert_eq!(ErrorCode::InvalidHeldRideThreshold as u32, 128);
    assert_eq!(ErrorCode::InvalidHeldRideReleasePolicy as u32, 129);
    assert_eq!(ErrorCode::ReleasedCompletionEvidenceMismatch as u32, 130);
}

#[test]
fn program_version_transition_changes_only_the_stable_version_byte() {
    assert_eq!(PREVIOUS_PROGRAM_VERSION, 0x4D);
    assert_eq!(CURRENT_PROGRAM_VERSION, 0x4E);
    assert_eq!(PROGRAM_VERSION_FAMILY, "V4-B");
    let supported_previous = CURRENT_PROGRAM_VERSION - 1;
    let admin = Pubkey::new_unique();
    let mut data = vec![0xA5; ProgramConfig::SIZE_WITH_MINTS];
    data[..8].copy_from_slice(&ProgramConfig::discriminator());
    data[ProgramConfig::ADMIN_AUTHORITY_OFFSET..ProgramConfig::BACKEND_AUTHORITY_OFFSET]
        .copy_from_slice(admin.as_ref());
    data[ProgramConfig::PROGRAM_VERSION_OFFSET] = supported_previous;
    data[ProgramConfig::INITIALIZED_OFFSET] = 1;
    let before = data.clone();

    assert_eq!(
        advance_program_version_bytes(
            &mut data,
            admin,
            supported_previous,
            CURRENT_PROGRAM_VERSION,
        )
        .unwrap(),
        (supported_previous, CURRENT_PROGRAM_VERSION)
    );
    assert_eq!(
        data[ProgramConfig::PROGRAM_VERSION_OFFSET],
        CURRENT_PROGRAM_VERSION
    );
    for (offset, value) in data.iter().enumerate() {
        if offset != ProgramConfig::PROGRAM_VERSION_OFFSET {
            assert_eq!(*value, before[offset], "unexpected write at byte {offset}");
        }
    }
}

#[test]
fn program_version_transition_rejects_stale_regressive_skipped_and_future_values() {
    let supported_previous = CURRENT_PROGRAM_VERSION - 1;
    assert_error_code(
        validate_program_version_transition(
            supported_previous,
            supported_previous - 1,
            CURRENT_PROGRAM_VERSION,
        ),
        ErrorCode::StaleProgramVersion,
    );
    assert_error_code(
        validate_program_version_transition(
            supported_previous,
            supported_previous,
            supported_previous,
        ),
        ErrorCode::RegressiveProgramVersion,
    );
    assert_error_code(
        validate_program_version_transition(
            supported_previous - 1,
            supported_previous - 1,
            CURRENT_PROGRAM_VERSION,
        ),
        ErrorCode::SkippedProgramVersion,
    );
    assert_error_code(
        validate_program_version_transition(
            CURRENT_PROGRAM_VERSION,
            CURRENT_PROGRAM_VERSION,
            CURRENT_PROGRAM_VERSION + 1,
        ),
        ErrorCode::UnsupportedProgramVersion,
    );
}

#[test]
fn program_version_transition_rejects_a_noncanonical_initialized_byte() {
    let supported_previous = CURRENT_PROGRAM_VERSION - 1;
    let admin = Pubkey::new_unique();
    let mut data = vec![0; ProgramConfig::STABLE_PREFIX_SIZE];
    data[..8].copy_from_slice(&ProgramConfig::discriminator());
    data[ProgramConfig::ADMIN_AUTHORITY_OFFSET..ProgramConfig::BACKEND_AUTHORITY_OFFSET]
        .copy_from_slice(admin.as_ref());
    data[ProgramConfig::PROGRAM_VERSION_OFFSET] = supported_previous;
    data[ProgramConfig::INITIALIZED_OFFSET] = 2;

    assert_error_code(
        advance_program_version_bytes(
            &mut data,
            admin,
            supported_previous,
            CURRENT_PROGRAM_VERSION,
        ),
        ErrorCode::NotInitialized,
    );
}

#[test]
fn completion_evidence_v2_matches_frozen_vector_and_binds_tribute() {
    let ride_attestation = Pubkey::new_from_array([1; 32]);
    let vault = Pubkey::new_from_array([2; 32]);
    let evidence =
        build_climb_completion_evidence_v2(&ride_attestation, &vault, 615, 123_000_000_000);

    assert_eq!(
        evidence,
        [
            0xb6, 0x78, 0xac, 0x1c, 0x76, 0xf6, 0xed, 0x24, 0xb7, 0x55, 0x46, 0x46, 0x14, 0x83,
            0xcb, 0x11, 0x4a, 0x68, 0x0f, 0x59, 0x65, 0xfd, 0xcc, 0x84, 0x8e, 0x82, 0xf4, 0x80,
            0xcb, 0x20, 0xbd, 0x6c,
        ]
    );
    assert_ne!(
        evidence,
        build_climb_completion_evidence_v2(&ride_attestation, &vault, 615, 123_000_000_001,)
    );
}

#[test]
fn released_completion_evidence_v3_matches_frozen_vector_and_binds_child_authority() {
    let release_authority = Pubkey::new_from_array([3; 32]);
    let ride_attestation = Pubkey::new_from_array([1; 32]);
    let vault = Pubkey::new_from_array([2; 32]);
    let evidence = build_released_climb_completion_evidence_v3(
        &release_authority,
        &ride_attestation,
        &vault,
        615,
        123_000_000_000,
    );

    assert_eq!(
        evidence,
        [
            0x29, 0x2f, 0xd8, 0x8d, 0x4d, 0x66, 0xe1, 0xa6, 0xf1, 0xf4, 0x3d, 0xc7, 0x2e, 0xce,
            0x5e, 0x0a, 0x01, 0x02, 0x4b, 0x57, 0xde, 0x84, 0x45, 0x9d, 0xdf, 0x5f, 0x62, 0x25,
            0xa9, 0xff, 0x32, 0x7b,
        ]
    );
    assert_ne!(
        evidence,
        build_released_climb_completion_evidence_v3(
            &Pubkey::new_from_array([4; 32]),
            &ride_attestation,
            &vault,
            615,
            123_000_000_000,
        )
    );
    assert_ne!(
        evidence,
        build_released_climb_completion_evidence_v3(
            &release_authority,
            &ride_attestation,
            &vault,
            615,
            123_000_000_001,
        )
    );
}

#[test]
fn released_tribute_budget_is_cumulative_and_cannot_exceed_child_cap() {
    let mut budget = ReleasedRideTributeBudget {
        ride_attestation: Pubkey::new_unique(),
        release_authority: Pubkey::new_unique(),
        cal_budget: 10,
        total_cal_tributed: 0,
        bump: 255,
    };

    budget.credit(4).unwrap();
    budget.credit(6).unwrap();
    assert_eq!(budget.total_cal_tributed, 10);
    assert_error_code(budget.credit(1), ErrorCode::RideTributeBudgetExceeded);
    assert_eq!(budget.total_cal_tributed, 10);
}

#[test]
fn balance_vault_operation_id_matches_backend_vector_and_binds_amount() {
    let program_id = Pubkey::from_str("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH").unwrap();
    let rider = Pubkey::from_str("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF").unwrap();
    let authority = Pubkey::from_str("9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP").unwrap();
    let operation_id = build_balance_vault_operation_id(
        &program_id,
        &rider,
        &authority,
        BalanceVaultOperationKind::DepositCal,
        7,
        5_000_000_000,
        0,
        3,
        7,
        1_800_000_000,
    );

    assert_eq!(
        operation_id,
        [
            0xbf, 0x6a, 0x06, 0x6a, 0x62, 0x33, 0x73, 0x2a, 0x6d, 0x67, 0x51, 0xe2, 0x7a, 0xbe,
            0xc2, 0x13, 0xb2, 0xe9, 0xfd, 0xd5, 0xf6, 0x35, 0x2f, 0xfb, 0x08, 0x91, 0x0d, 0x1e,
            0x04, 0x68, 0x87, 0x49,
        ]
    );
    assert_ne!(
        operation_id,
        build_balance_vault_operation_id(
            &program_id,
            &rider,
            &authority,
            BalanceVaultOperationKind::DepositCal,
            7,
            5_000_000_001,
            0,
            3,
            7,
            1_800_000_000,
        )
    );
}

fn local_legend_with_term(term_start_epoch: u64, term_end_epoch: u64) -> LocalLegend {
    LocalLegend {
        vault_id: 7,
        holder: Pubkey::new_unique(),
        election_period: 1,
        term_start_epoch,
        term_end_epoch,
        completions_at_election: 3,
        runner_up: Pubkey::new_unique(),
        runner_up_completions: 2,
        total_earned: 0,
        is_active: true,
        is_bootstrap: false,
        bump: 255,
    }
}

fn legacy_local_legend_bytes(legend: &LocalLegend) -> Vec<u8> {
    let mut data = Vec::with_capacity(LocalLegend::LEGACY_SIZE);
    data.extend_from_slice(&LocalLegend::DISCRIMINATOR);
    data.extend_from_slice(&legend.vault_id.to_le_bytes());
    data.extend_from_slice(legend.holder.as_ref());
    data.extend_from_slice(&legend.election_period.to_le_bytes());
    data.extend_from_slice(&legend.term_start_epoch.to_le_bytes());
    data.extend_from_slice(&legend.term_end_epoch.to_le_bytes());
    data.extend_from_slice(&legend.completions_at_election.to_le_bytes());
    data.extend_from_slice(legend.runner_up.as_ref());
    data.extend_from_slice(&legend.runner_up_completions.to_le_bytes());
    data.extend_from_slice(&legend.total_earned.to_le_bytes());
    data.push(u8::from(legend.is_active));
    data.push(legend.bump);
    assert_eq!(data.len(), LocalLegend::LEGACY_SIZE);
    data
}

#[test]
fn legacy_local_legend_migration_inserts_bootstrap_before_bump() {
    let mut legend = local_legend_with_term(13, 21);
    legend.election_period = 0;
    legend.completions_at_election = 0;
    legend.total_earned = 987_654_321;
    legend.is_bootstrap = true;
    let legacy = legacy_local_legend_bytes(&legend);
    let original = legacy.clone();

    let mut legacy_ref: &[u8] = &legacy;
    assert!(LocalLegend::try_deserialize(&mut legacy_ref).is_err());

    let layout = inspect_local_legend_layout(&legacy, legend.vault_id, legend.bump).unwrap();
    assert_eq!(
        layout,
        LocalLegendAccountLayout::Legacy {
            is_bootstrap: true,
            bump: legend.bump,
        }
    );

    let mut migrated = legacy;
    migrated.resize(LocalLegend::SIZE, 0);
    write_local_legend_current_layout(&mut migrated, layout).unwrap();

    assert_eq!(
        &migrated[..LocalLegend::IS_BOOTSTRAP_OFFSET],
        &original[..121]
    );
    assert_eq!(migrated[LocalLegend::IS_BOOTSTRAP_OFFSET], 1);
    assert_eq!(migrated[LocalLegend::BUMP_OFFSET], legend.bump);
    let mut migrated_ref: &[u8] = &migrated;
    let decoded = LocalLegend::try_deserialize(&mut migrated_ref).unwrap();
    assert_eq!(decoded.vault_id, legend.vault_id);
    assert_eq!(decoded.holder, legend.holder);
    assert_eq!(decoded.term_start_epoch, legend.term_start_epoch);
    assert_eq!(decoded.term_end_epoch, legend.term_end_epoch);
    assert_eq!(decoded.total_earned, legend.total_earned);
    assert!(decoded.is_active);
    assert!(decoded.is_bootstrap);
    assert_eq!(decoded.bump, legend.bump);
    assert_eq!(
        inspect_local_legend_layout(&migrated, legend.vault_id, legend.bump).unwrap(),
        LocalLegendAccountLayout::Current
    );
}

#[test]
fn legacy_local_legend_migration_infers_only_the_documented_bootstrap_sentinel() {
    let mut elected = local_legend_with_term(16, 24);
    elected.election_period = 2;
    elected.completions_at_election = 7;
    elected.is_bootstrap = false;
    let data = legacy_local_legend_bytes(&elected);

    assert_eq!(
        inspect_local_legend_layout(&data, elected.vault_id, elected.bump).unwrap(),
        LocalLegendAccountLayout::Legacy {
            is_bootstrap: false,
            bump: elected.bump,
        }
    );

    let mut inactive_sentinel = local_legend_with_term(0, 0);
    inactive_sentinel.election_period = 0;
    inactive_sentinel.completions_at_election = 0;
    inactive_sentinel.is_active = false;
    let data = legacy_local_legend_bytes(&inactive_sentinel);
    assert_eq!(
        inspect_local_legend_layout(&data, inactive_sentinel.vault_id, inactive_sentinel.bump,)
            .unwrap(),
        LocalLegendAccountLayout::Legacy {
            is_bootstrap: false,
            bump: inactive_sentinel.bump,
        }
    );
}

#[test]
fn legacy_local_legend_migration_rejects_ambiguous_or_corrupt_layouts() {
    let legend = local_legend_with_term(8, 16);
    let data = legacy_local_legend_bytes(&legend);

    let mut wrong_discriminator = data.clone();
    wrong_discriminator[0] ^= 1;
    assert_error_code(
        inspect_local_legend_layout(&wrong_discriminator, legend.vault_id, legend.bump),
        ErrorCode::InvalidLocalLegendLayout,
    );
    assert_error_code(
        inspect_local_legend_layout(&data, legend.vault_id + 1, legend.bump),
        ErrorCode::LocalLegendVaultMismatch,
    );
    assert_error_code(
        inspect_local_legend_layout(&data, legend.vault_id, legend.bump.wrapping_sub(1)),
        ErrorCode::InvalidLocalLegendBump,
    );

    let mut noncanonical_active = data.clone();
    noncanonical_active[LocalLegend::IS_ACTIVE_OFFSET] = 2;
    assert_error_code(
        inspect_local_legend_layout(&noncanonical_active, legend.vault_id, legend.bump),
        ErrorCode::InvalidLocalLegendLayout,
    );

    assert_error_code(
        inspect_local_legend_layout(&data[..data.len() - 1], legend.vault_id, legend.bump),
        ErrorCode::InvalidLocalLegendLayout,
    );
    let mut oversized = data;
    oversized.extend_from_slice(&[0, 0]);
    assert_error_code(
        inspect_local_legend_layout(&oversized, legend.vault_id, legend.bump),
        ErrorCode::InvalidLocalLegendLayout,
    );
}

#[test]
fn local_legend_catch_up_uses_prior_term_end_instead_of_wall_clock_week() {
    let legend = local_legend_with_term(10, 18);

    let next_end = next_local_legend_term_end(&legend, 18, 40, 8).unwrap();

    assert_eq!(next_end, 26);
}

#[test]
fn local_legend_bootstrap_accepts_an_unaligned_historical_start() {
    let mut legend = local_legend_with_term(0, 0);
    legend.holder = Pubkey::default();
    legend.is_active = false;

    let next_end = next_local_legend_term_end(&legend, 13, 40, 8).unwrap();

    assert_eq!(next_end, 21);
}

#[test]
fn local_legend_term_transition_rejects_skips_and_future_terms() {
    let legend = local_legend_with_term(10, 18);

    assert_error_code(
        next_local_legend_term_end(&legend, 24, 40, 8),
        ErrorCode::LocalLegendTermOutOfSequence,
    );
    assert_error_code(
        next_local_legend_term_end(&legend, 18, 17, 8),
        ErrorCode::LocalLegendTermInFuture,
    );
}

#[test]
fn ride_cal_tribute_budget_is_the_full_attested_cal_ceiling() {
    assert_eq!(ride_cal_tribute_budget(0).unwrap(), 0);
    assert_eq!(ride_cal_tribute_budget(9).unwrap(), 9);
    assert_eq!(ride_cal_tribute_budget(10).unwrap(), 10);
    assert_eq!(ride_cal_tribute_budget(20).unwrap(), 20);
    assert_eq!(ride_cal_tribute_budget(u64::MAX).unwrap(), u64::MAX);
}

#[test]
fn ride_tribute_budget_accepts_exact_budget_and_rejects_overrun() {
    let mut budget = RideTributeBudget {
        ride_attestation: Pubkey::new_unique(),
        cal_budget: 100,
        total_cal_tributed: 0,
        bump: 255,
    };

    budget.credit(60).unwrap();
    budget.credit(40).unwrap();
    assert_eq!(budget.total_cal_tributed, 100);
    assert!(budget.credit(1).is_err());
    assert_eq!(budget.total_cal_tributed, 100);
}

fn tribute_test_vault(open_settlement_week: u64) -> Vault {
    Vault {
        id: 7,
        signature: [0; 64],
        signature_hash: [0; 32],
        minter: Pubkey::default(),
        mint_epoch: 0,
        rights_expires_epoch: 0,
        kom_holder: Pubkey::default(),
        kom_time_s: 0,
        kom_set_epoch: 0,
        name: [0; 64],
        avatar_ipfs: [0; 46],
        slogan: [0; 128],
        cal_tribute_accumulated: 0,
        cal_tribute_accumulated_next: 0,
        total_cal_burned: 0,
        total_dung_emitted: 0,
        total_completions: 0,
        total_cal_staked: 0,
        staker_count: 0,
        reward_per_token_stored: 0,
        last_update_time: 0,
        reward_rate: STAKER_REMAINDER_POLICY_MARKER,
        pending_rewards: 0,
        pending_rewards_next_week: 0,
        open_settlement_week,
        carry_record_royalty: 0,
        carry_stakers: 0,
        carry_local_legend: 0,
        carry_pol: 0,
        carry_treasury: 0,
        total_staked: 0,
        last_distribution_epoch: open_settlement_week.saturating_sub(1),
        vert_m: 0,
        distance_m: 0,
        avg_gradient_pct: 0,
        created_at: 0,
        bump: 0,
        climb: Pubkey::default(),
    }
}

#[test]
fn lifetime_tribute_credits_the_current_open_flow_meter() {
    let mut vault = tribute_test_vault(42);
    vault.cal_tribute_accumulated = 900;
    vault.pending_rewards = 3;

    vault.credit_lifetime_tribute(250).unwrap();

    assert_eq!(vault.open_settlement_week, 42);
    assert_eq!(vault.cal_tribute_accumulated, 150);
    assert_eq!(vault.pending_rewards, 4);
    assert_eq!(vault.cal_tribute_accumulated_next, 0);
    assert_eq!(vault.pending_rewards_next_week, 0);
}

#[test]
fn lifetime_tribute_drains_legacy_next_week_state_before_new_credit() {
    let clock = test_settlement_clock();
    let mut vault = tribute_test_vault(9);
    vault.cal_tribute_accumulated_next = 750;
    vault.pending_rewards_next_week = 2;
    let now = clock.week_finalization_time(9).unwrap();

    vault
        .maybe_advance_empty_settlement_week(&clock, now)
        .unwrap();
    vault.credit_lifetime_tribute(500).unwrap();

    assert_eq!(vault.open_settlement_week, 10);
    assert_eq!(vault.cal_tribute_accumulated, 250);
    assert_eq!(vault.pending_rewards, 3);
    assert_eq!(vault.cal_tribute_accumulated_next, 0);
    assert_eq!(vault.pending_rewards_next_week, 0);
}

#[test]
fn held_release_completion_advances_an_empty_lagging_vault_to_frozen_week() {
    let clock = test_settlement_clock();
    let release_week = 13;
    let mut vault = tribute_test_vault(11);
    let now = clock.week_finalization_time(release_week - 1).unwrap();

    vault
        .maybe_advance_empty_settlement_week(&clock, now)
        .unwrap();
    require_held_release_settlement_week(
        vault.open_settlement_week,
        release_week,
    )
    .unwrap();
    vault.credit_lifetime_tribute(500).unwrap();

    assert_eq!(vault.open_settlement_week, release_week);
    assert_eq!(vault.cal_tribute_accumulated, 500);
}

#[test]
fn accepted_attestation_freezes_the_exact_thirty_day_boundary() {
    let accepted_at = EPOCH_ANCHOR + MAX_RIDE_AGE_SECONDS + 10_000;
    let completed_at = accepted_at - MAX_RIDE_AGE_SECONDS;
    let started_at = completed_at - 3_600;

    assert!(require_valid_ride_timestamps(started_at, completed_at, accepted_at).is_ok());
    assert!(require_valid_ride_timestamps(started_at, completed_at, accepted_at + 1).is_err());
    assert!(require_accepted_ride_timestamps(started_at, completed_at, accepted_at).is_ok());
}

#[test]
fn delayed_completion_cannot_regress_the_latest_completion_time() {
    let mut completion = VaultCompletion {
        user: Pubkey::default(),
        vault_id: 7,
        completions: 1,
        best_time_s: 900,
        last_completed_at: 2_000,
        total_cal_tributed: 0,
        bump: 0,
    };

    completion.note_completed_at(1_000);
    assert_eq!(completion.last_completed_at, 2_000);

    completion.note_completed_at(3_000);
    assert_eq!(completion.last_completed_at, 3_000);
}

#[test]
fn distribution_config_rejects_sum_valid_noncanonical_policy() {
    let alternate = DistributionConfig {
        leaderboard_share_bps: 5_400,
        staker_share_bps: 2_800,
        ..distribution_config()
    };

    assert!(!alternate.validate());
    assert!(distribution_config().validate());
}

#[test]
fn protocol_parameters_keep_the_halving_interval_canonical() {
    let mut alternate = ProtocolParameters::defaults();
    alternate.epochs_per_halving = EPOCHS_PER_HALVING + 1;

    assert!(!alternate.validate());
    assert!(ProtocolParameters::defaults().validate());
}

#[test]
fn emission_schedule_catches_up_and_holds_the_one_bps_tail() {
    let start = 120;

    assert_eq!(scheduled_emission_rate_bps(start, start).unwrap(), 10_000);
    assert_eq!(
        scheduled_emission_rate_bps(start + (2 * EPOCHS_PER_HALVING), start).unwrap(),
        2_500
    );
    assert_eq!(
        scheduled_emission_rate_bps(start + (64 * EPOCHS_PER_HALVING), start).unwrap(),
        1
    );
    assert_eq!(scheduled_emission_rate_bps(start - 1, start).unwrap(), 0);
}

#[test]
fn settlement_cap_plan_is_deterministic_and_terminal_without_impossible_carry() {
    let mut state = dung_mint_state(COMMUNITY_CAP - 70, COMMUNITY_CAP - 70, 60);
    state.max_supply = MAX_SUPPLY;
    let carries = SettlementBucketShares {
        record_royalty: 20,
        stakers: 20,
        local_legend: 20,
        pol: 0,
        treasury: 0,
    };

    let first =
        plan_settlement_emission(&state, 1_000, carries, &distribution_config()).unwrap();
    let retry =
        plan_settlement_emission(&state, 1_000, carries, &distribution_config()).unwrap();

    assert_eq!(first, retry);
    assert!(first.cap_limited);
    assert!(first.base_emission <= 11);
    assert_eq!(
        first.bucket_totals.total().unwrap(),
        60 + first.base_emission
    );

    state.community_minted = COMMUNITY_CAP - 60;
    state.total_minted = COMMUNITY_CAP - 60;
    let terminal =
        plan_settlement_emission(&state, 1_000, carries, &distribution_config()).unwrap();
    assert_eq!(terminal.base_emission, 0);
    assert_eq!(terminal.bucket_totals, carries);
    assert!(terminal.cap_limited);
    assert!(terminal.terminal);
}

#[test]
fn cap_planner_checks_every_split_rounding_residue() {
    let headroom = SettlementSupplyHeadroom {
        total: 20,
        community: 17,
        pol: 1,
        treasury: 2,
    };

    assert!(!settlement_base_fits(19, &headroom, &distribution_config()).unwrap());
    assert!(settlement_base_fits(20, &headroom, &distribution_config()).unwrap());
    assert_eq!(
        maximum_canonical_base_emission(20, &headroom, &distribution_config()).unwrap(),
        20
    );
}

fn dung_mint_state(
    total_minted: u64,
    community_minted: u64,
    community_reserved: u64,
) -> DungMintState {
    DungMintState {
        authority: Pubkey::default(),
        max_supply: MAX_SUPPLY,
        total_minted,
        total_burned: 0,
        community_minted,
        treasury_minted: 0,
        team_minted: 0,
        investor_minted: 0,
        pol_minted: 0,
        current_emission_rate_bps: BASIS_POINTS_DENOMINATOR,
        last_halving_epoch: 0,
        bump: 0,
        community_reserved,
        reservation_policy_version: DUNG_RESERVATION_POLICY_VERSION,
    }
}

fn live_legacy_dung_mint_state() -> LegacyDungMintState {
    LegacyDungMintState {
        authority: Pubkey::from_str("G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH").unwrap(),
        max_supply: 1_000_000_000_000_000_000,
        total_minted: 2_931_043_565_625,
        total_burned: 0,
        community_minted: 2_330_993_610_285,
        treasury_minted: 400_033_303_560,
        team_minted: 0,
        investor_minted: 0,
        pol_minted: 200_016_651_780,
        current_emission_rate_bps: 10_000,
        last_halving_epoch: 120,
        bump: 254,
    }
}

fn legacy_dung_mint_state_bytes(state: &LegacyDungMintState) -> Vec<u8> {
    let mut data = Vec::with_capacity(DungMintState::LEGACY_SIZE);
    data.extend_from_slice(&DungMintState::discriminator());
    state.serialize(&mut data).unwrap();
    assert_eq!(data.len(), DungMintState::LEGACY_SIZE);
    data
}

fn leaked_account_info(key: Pubkey, owner: Pubkey, data: Vec<u8>) -> AccountInfo<'static> {
    let key = Box::leak(Box::new(key));
    let owner = Box::leak(Box::new(owner));
    let lamports = Box::leak(Box::new(0u64));
    let data = Box::leak(data.into_boxed_slice());
    AccountInfo::new(key, false, true, lamports, data, owner, false, 0)
}

fn vault_stake_account_info(
    user: Pubkey,
    vault_id: u64,
    rewards_earned: u64,
    active: bool,
) -> AccountInfo<'static> {
    let vault_id_bytes = vault_id.to_le_bytes();
    let (key, bump) =
        Pubkey::find_program_address(&[VAULT_STAKE_SEED, user.as_ref(), &vault_id_bytes], &ID);
    let stake = VaultStake {
        user,
        vault_id,
        cal_staked: if active { 1 } else { 0 },
        lp_tokens: if active { 1 } else { 0 },
        staked_at: 0,
        pending_effective_week_plus_one: 0,
        effective_lp_tokens: if active { 1 } else { 0 },
        rewards_earned,
        pending_lp_tokens: 0,
        bump,
    };
    let mut data = Vec::with_capacity(VaultStake::SIZE);
    stake.try_serialize(&mut data).unwrap();
    assert_eq!(data.len(), VaultStake::SIZE);
    leaked_account_info(key, ID, data)
}

fn vault_account_info(
    id: u64,
    carry_record_royalty: u64,
    carry_stakers: u64,
    carry_local_legend: u64,
    carry_pol: u64,
    carry_treasury: u64,
) -> AccountInfo<'static> {
    let id_bytes = id.to_le_bytes();
    let (key, bump) = Pubkey::find_program_address(&[VAULT_SEED, &id_bytes], &ID);
    let vault = Vault {
        id,
        signature: [0; 64],
        signature_hash: [0; 32],
        minter: Pubkey::default(),
        mint_epoch: 0,
        rights_expires_epoch: 0,
        kom_holder: Pubkey::default(),
        kom_time_s: 0,
        kom_set_epoch: 0,
        name: [0; 64],
        avatar_ipfs: [0; 46],
        slogan: [0; 128],
        cal_tribute_accumulated: 0,
        cal_tribute_accumulated_next: 0,
        total_cal_burned: 0,
        total_dung_emitted: 0,
        total_completions: 0,
        total_cal_staked: 0,
        staker_count: 0,
        reward_per_token_stored: 0,
        last_update_time: 0,
        reward_rate: STAKER_REMAINDER_POLICY_MARKER,
        pending_rewards: 0,
        pending_rewards_next_week: 0,
        open_settlement_week: 0,
        carry_record_royalty,
        carry_stakers,
        carry_local_legend,
        carry_pol,
        carry_treasury,
        total_staked: 0,
        last_distribution_epoch: 0,
        vert_m: 0,
        distance_m: 0,
        avg_gradient_pct: 0,
        created_at: 0,
        bump,
        climb: Pubkey::default(),
    };
    let mut data = Vec::with_capacity(Vault::SIZE);
    vault.try_serialize(&mut data).unwrap();
    assert_eq!(data.len(), Vault::SIZE);
    leaked_account_info(key, ID, data)
}

fn vault_stake_position_account_info(
    user: Pubkey,
    vault_id: u64,
    cal_staked: u64,
    live_lp_tokens: u64,
    effective_lp_tokens: u64,
    pending_lp_tokens: u64,
    pending_effective_week: Option<u64>,
) -> AccountInfo<'static> {
    let vault_id_bytes = vault_id.to_le_bytes();
    let (key, bump) =
        Pubkey::find_program_address(&[VAULT_STAKE_SEED, user.as_ref(), &vault_id_bytes], &ID);
    let stake = VaultStake {
        user,
        vault_id,
        cal_staked,
        lp_tokens: live_lp_tokens,
        staked_at: 0,
        pending_effective_week_plus_one: pending_effective_week
            .map(|week| week.checked_add(1).unwrap())
            .unwrap_or(0),
        effective_lp_tokens,
        rewards_earned: 0,
        pending_lp_tokens,
        bump,
    };
    let mut data = Vec::with_capacity(VaultStake::SIZE);
    stake.try_serialize(&mut data).unwrap();
    assert_eq!(data.len(), VaultStake::SIZE);
    leaked_account_info(key, ID, data)
}

fn expected_share(value: u64, multiplier: u64, divisor: u64) -> u64 {
    u64::try_from((value as u128) * (multiplier as u128) / (divisor as u128)).unwrap()
}

fn snapshot_stake(
    live_lp_tokens: u64,
    effective_lp_tokens: u64,
    pending_lp_tokens: u64,
    pending_effective_week: Option<u64>,
) -> VaultStake {
    VaultStake {
        user: Pubkey::new_unique(),
        vault_id: 7,
        cal_staked: live_lp_tokens,
        lp_tokens: live_lp_tokens,
        staked_at: 0,
        pending_effective_week_plus_one: pending_effective_week
            .map(|week| week.checked_add(1).unwrap())
            .unwrap_or(0),
        effective_lp_tokens,
        rewards_earned: 0,
        pending_lp_tokens,
        bump: 0,
    }
}

fn assert_error_code<T: std::fmt::Debug>(result: Result<T>, expected: ErrorCode) {
    let error = result.expect_err("expected checked arithmetic to return an error");
    match error {
        anchor_lang::error::Error::AnchorError(error) => {
            assert_eq!(error.error_code_number, u32::from(expected));
        }
        other => panic!("expected Anchor error, got {other:?}"),
    }
}

#[test]
fn stake_lp_transition_rejects_zero_output_before_ingress() {
    assert_error_code(
        stake_lp_transition(0, CAL_MIN_STAKE, 1, CAL_MIN_STAKE + 1).map(|_| ()),
        ErrorCode::InvalidAmount,
    );
}

#[test]
fn stake_lp_transition_rejects_inconsistent_pool_inventory() {
    assert_error_code(
        stake_lp_transition(0, CAL_MIN_STAKE, 0, CAL_MIN_STAKE).map(|_| ()),
        ErrorCode::InvalidVault,
    );
    assert_error_code(
        stake_lp_transition(0, CAL_MIN_STAKE, CAL_MIN_STAKE, 0).map(|_| ()),
        ErrorCode::InvalidVault,
    );
    assert_error_code(
        stake_lp_transition(1, CAL_MIN_STAKE, 0, 0).map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn stake_lp_transition_is_checked_without_inferring_inventory_identity() {
    let initial = stake_lp_transition(0, 100, 0, 0).unwrap();
    assert_eq!(initial.lp_to_mint, 100);
    assert_eq!(initial.next_lp_tokens, 100);

    let top_up = stake_lp_transition(initial.next_lp_tokens, 50, 100, 100).unwrap();
    assert_eq!(top_up.lp_to_mint, 50);
    assert_eq!(top_up.next_lp_tokens, 150);

    let non_unit_ratio = stake_lp_transition(0, 2, 2, 3).unwrap();
    assert_eq!(non_unit_ratio.lp_to_mint, 1);
    assert_eq!(non_unit_ratio.next_lp_tokens, 1);

    let reactivation = stake_lp_transition(0, 100, 100, 100).unwrap();
    assert_eq!(reactivation.next_lp_tokens, 100);
}

#[test]
fn lp_custody_restoration_is_incremental_bounded_and_exact() {
    let partial = lp_custody_restoration(0, 40, 100).unwrap();
    assert_eq!(partial.next_amount, 40);
    assert!(!partial.sealed);

    let complete = lp_custody_restoration(partial.next_amount, 60, 100).unwrap();
    assert_eq!(complete.next_amount, 100);
    assert!(complete.sealed);

    let boundary = lp_custody_restoration(u64::MAX - 1, 1, u64::MAX).unwrap();
    assert_eq!(boundary.next_amount, u64::MAX);
    assert!(boundary.sealed);
}

#[test]
fn lp_custody_restoration_rejects_zero_overfill_and_overflow() {
    assert_error_code(
        lp_custody_restoration(0, 0, 100).map(|_| ()),
        ErrorCode::InvalidAmount,
    );
    assert_error_code(
        lp_custody_restoration(101, 1, 100).map(|_| ()),
        ErrorCode::LpCustodyAmountMismatch,
    );
    assert_error_code(
        lp_custody_restoration(40, 61, 100).map(|_| ()),
        ErrorCode::LpCustodyAmountMismatch,
    );
    assert_error_code(
        lp_custody_restoration(u64::MAX - 1, 2, u64::MAX).map(|_| ()),
        ErrorCode::Overflow,
    );
}

#[test]
fn unstake_accounting_keeps_principal_separate_from_appreciated_pool_value() {
    let transition =
        unstake_accounting_transition(100_000, 100_000, 50_000, 100_000, 150_000).unwrap();

    assert_eq!(transition.next_lp_tokens, 50_000);
    assert_eq!(transition.cal_to_return, 75_000);
    assert_eq!(transition.exit_fee, 375);
    assert_eq!(transition.cal_after_fee, 74_625);
    assert_eq!(transition.next_cal_staked, 50_000);
}

#[test]
fn unstake_accounting_full_exit_clears_principal_at_any_pool_ratio() {
    let appreciated =
        unstake_accounting_transition(100_000, 100_000, 100_000, 100_000, 150_000).unwrap();
    assert_eq!(appreciated.cal_to_return, 150_000);
    assert_eq!(appreciated.next_lp_tokens, 0);
    assert_eq!(appreciated.next_cal_staked, 0);

    let depreciated =
        unstake_accounting_transition(100_000, 100_000, 100_000, 100_000, 50_000).unwrap();
    assert_eq!(depreciated.cal_to_return, 50_000);
    assert_eq!(depreciated.next_lp_tokens, 0);
    assert_eq!(depreciated.next_cal_staked, 0);
}

#[test]
fn unstake_accounting_floors_retained_principal_and_preserves_pool_dust() {
    let transition = unstake_accounting_transition(10, 3, 1, 3, 10).unwrap();

    assert_eq!(transition.next_lp_tokens, 2);
    assert_eq!(transition.cal_to_return, 3);
    assert_eq!(transition.next_cal_staked, 6);
    assert_eq!(10 - transition.cal_to_return, 7);

    let final_exit = unstake_accounting_transition(
        transition.next_cal_staked,
        transition.next_lp_tokens,
        transition.next_lp_tokens,
        transition.next_lp_tokens,
        7,
    )
    .unwrap();
    assert_eq!(final_exit.cal_to_return, 7);
    assert_eq!(final_exit.next_cal_staked, 0);
}

#[test]
fn unstake_accounting_reduces_principal_even_when_pool_value_is_zero() {
    let transition = unstake_accounting_transition(100, 100, 40, 100, 0).unwrap();

    assert_eq!(transition.cal_to_return, 0);
    assert_eq!(transition.exit_fee, 0);
    assert_eq!(transition.cal_after_fee, 0);
    assert_eq!(transition.next_lp_tokens, 60);
    assert_eq!(transition.next_cal_staked, 60);
}

#[test]
fn unstake_accounting_conserves_exact_units_at_u64_boundaries() {
    let transition =
        unstake_accounting_transition(u64::MAX, u64::MAX, u64::MAX - 1, u64::MAX, u64::MAX)
            .unwrap();

    assert_eq!(transition.next_lp_tokens + (u64::MAX - 1), u64::MAX);
    assert_eq!(transition.next_cal_staked + (u64::MAX - 1), u64::MAX);
    assert_eq!(
        transition.cal_after_fee + transition.exit_fee,
        transition.cal_to_return
    );
    assert_eq!(transition.cal_to_return, u64::MAX - 1);
}

#[test]
fn unstake_accounting_rejects_impossible_lp_inventory() {
    assert_error_code(
        unstake_accounting_transition(100, 101, 1, 100, 100).map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn lp_accounting_small_domain_preserves_exact_invariants() {
    for total_lp_supply in 0..=12u64 {
        for total_cal_staked in 0..=12u64 {
            for prior_lp_tokens in 0..=total_lp_supply {
                for amount in 1..=12u64 {
                    let result = stake_lp_transition(
                        prior_lp_tokens,
                        amount,
                        total_lp_supply,
                        total_cal_staked,
                    );
                    let inventory_is_consistent =
                        (total_lp_supply == 0) == (total_cal_staked == 0);

                    if !inventory_is_consistent {
                        assert!(result.is_err());
                        continue;
                    }

                    let expected_mint = if total_lp_supply == 0 {
                        amount
                    } else {
                        expected_share(amount, total_lp_supply, total_cal_staked)
                    };
                    if expected_mint == 0 {
                        assert!(result.is_err());
                        continue;
                    }

                    let transition = result.unwrap();
                    assert_eq!(transition.lp_to_mint, expected_mint);
                    assert_eq!(
                        transition.next_lp_tokens,
                        prior_lp_tokens + transition.lp_to_mint
                    );
                }
            }
        }
    }

    for total_lp_supply in 1..=12u64 {
        for prior_lp_tokens in 1..=total_lp_supply {
            for lp_amount in 1..=prior_lp_tokens {
                for prior_cal_staked in 0..=12u64 {
                    for total_cal_staked in 0..=12u64 {
                        let transition = unstake_accounting_transition(
                            prior_cal_staked,
                            prior_lp_tokens,
                            lp_amount,
                            total_lp_supply,
                            total_cal_staked,
                        )
                        .unwrap();

                        assert_eq!(transition.next_lp_tokens + lp_amount, prior_lp_tokens);
                        assert_eq!(
                            transition.cal_to_return,
                            expected_share(lp_amount, total_cal_staked, total_lp_supply)
                        );
                        assert_eq!(
                            transition.cal_after_fee + transition.exit_fee,
                            transition.cal_to_return
                        );
                        assert_eq!(
                            transition.exit_fee,
                            expected_share(
                                transition.cal_to_return,
                                EXIT_FEE_BPS,
                                BASIS_POINTS_DENOMINATOR
                            )
                        );
                        assert!(transition.cal_to_return <= total_cal_staked);
                        assert_eq!(
                            total_cal_staked - transition.cal_to_return
                                + transition.cal_to_return,
                            total_cal_staked
                        );
                        assert_eq!(
                            transition.next_cal_staked,
                            expected_share(
                                prior_cal_staked,
                                transition.next_lp_tokens,
                                prior_lp_tokens
                            )
                        );
                        assert!(transition.next_cal_staked <= prior_cal_staked);
                        if lp_amount == prior_lp_tokens {
                            assert_eq!(transition.next_cal_staked, 0);
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn settlement_inventory_count_tracks_only_relevance_transitions() {
    assert_eq!(
        settlement_inventory_count_after_change(7, false, true).unwrap(),
        8
    );
    assert_eq!(
        settlement_inventory_count_after_change(8, true, true).unwrap(),
        8
    );
    assert_eq!(
        settlement_inventory_count_after_change(8, true, false).unwrap(),
        7
    );
    assert_eq!(
        settlement_inventory_count_after_change(7, false, false).unwrap(),
        7
    );
    assert_error_code(
        settlement_inventory_count_after_change(u32::MAX, false, true),
        ErrorCode::Overflow,
    );
    assert_error_code(
        settlement_inventory_count_after_change(0, true, false),
        ErrorCode::Underflow,
    );
}

#[test]
fn settlement_bucket_shares_near_cap_conserve_without_overflow() {
    let shares = settlement_bucket_shares(MAX_SUPPLY, &distribution_config()).unwrap();

    assert_eq!(shares.total().unwrap(), MAX_SUPPLY);
}

#[test]
fn deferred_staker_liability_is_reserved_at_settlement_cap_edge() {
    let mut mint_state = dung_mint_state(COMMUNITY_CAP - 60, COMMUNITY_CAP - 60, 0);

    assert!(mint_state.can_mint(58, AllocationBucket::Community));
    mint_state
        .record_mint(58, AllocationBucket::Community)
        .unwrap();

    assert_error_code(
        mint_state.reserve_community(27),
        ErrorCode::SupplyCapReached,
    );
    assert_eq!(mint_state.community_reserved, 0);
    assert_eq!(mint_state.committed_community().unwrap(), COMMUNITY_CAP - 2);
}

#[test]
fn collection_consumes_reservation_once_without_changing_committed_supply() {
    let mut mint_state = dung_mint_state(100, 100, 0);
    mint_state.reserve_community(27).unwrap();

    let committed_total = mint_state.committed_total().unwrap();
    let committed_community = mint_state.committed_community().unwrap();
    mint_state.consume_community_reservation(27).unwrap();

    assert_eq!(mint_state.total_minted, 127);
    assert_eq!(mint_state.community_minted, 127);
    assert_eq!(mint_state.community_reserved, 0);
    assert_eq!(mint_state.committed_total().unwrap(), committed_total);
    assert_eq!(
        mint_state.committed_community().unwrap(),
        committed_community
    );

    let state_after_collection = (
        mint_state.total_minted,
        mint_state.community_minted,
        mint_state.community_reserved,
    );
    assert_error_code(
        mint_state.consume_community_reservation(27),
        ErrorCode::InsufficientCommunityReservation,
    );
    assert_eq!(
        (
            mint_state.total_minted,
            mint_state.community_minted,
            mint_state.community_reserved,
        ),
        state_after_collection
    );
}

#[test]
fn protocol_burn_accounting_is_checked_without_reopening_emission_headroom() {
    let mut mint_state = dung_mint_state(100, 100, 0);
    let committed_before = mint_state.committed_total().unwrap();

    mint_state.record_protocol_burn(30).unwrap();

    assert_eq!(mint_state.total_burned, 30);
    assert_eq!(mint_state.total_minted, 100);
    assert_eq!(mint_state.committed_total().unwrap(), committed_before);
    assert!(mint_state.can_mint(COMMUNITY_CAP - 100, AllocationBucket::Community));
    assert!(!mint_state.can_mint(COMMUNITY_CAP - 99, AllocationBucket::Community));

    let state_after_burn = mint_state.total_burned;
    assert_error_code(
        mint_state.record_protocol_burn(71),
        ErrorCode::DungBurnAccountingMismatch,
    );
    assert_eq!(mint_state.total_burned, state_after_burn);
}

#[test]
fn outstanding_claims_block_all_immediate_mints_at_total_cap() {
    let mut mint_state = dung_mint_state(MAX_SUPPLY - 10, COMMUNITY_CAP - 10, 0);
    mint_state.treasury_minted = TREASURY_CAP;
    mint_state.team_minted = TEAM_CAP;
    mint_state.investor_minted = INVESTOR_CAP;
    mint_state.pol_minted = POL_CAP;
    mint_state.assert_solvent().unwrap();

    mint_state.reserve_community(10).unwrap();
    mint_state.total_burned = u64::MAX;
    assert_eq!(mint_state.committed_total().unwrap(), MAX_SUPPLY);
    assert_eq!(mint_state.committed_community().unwrap(), COMMUNITY_CAP);
    for allocation in [
        AllocationBucket::Community,
        AllocationBucket::Treasury,
        AllocationBucket::Team,
        AllocationBucket::Investor,
        AllocationBucket::Pol,
    ] {
        assert!(!mint_state.can_mint(1, allocation));
        assert_error_code(
            mint_state.record_mint(1, allocation),
            ErrorCode::SupplyCapReached,
        );
    }

    mint_state.consume_community_reservation(10).unwrap();
    assert_eq!(mint_state.total_minted, MAX_SUPPLY);
    assert_eq!(mint_state.community_minted, COMMUNITY_CAP);
    assert_eq!(mint_state.community_reserved, 0);
    mint_state.assert_solvent().unwrap();
}

#[test]
fn fee_carry_and_zero_allocation_paths_conserve_exact_units() {
    for total_earned in [0, 1, 27, u64::MAX] {
        for fee_bps in [0, HARVEST_FEE_BPS, BASIS_POINTS_DENOMINATOR] {
            let (fee, rider_amount) = harvest_reward_split(total_earned, fee_bps).unwrap();
            assert_eq!(checked_sum_u64([fee, rider_amount]).unwrap(), total_earned);
            assert_eq!(
                fee,
                checked_mul_div_u64(total_earned, fee_bps, BASIS_POINTS_DENOMINATOR).unwrap()
            );
        }
    }

    let staker_total = 27;
    let zero_unlocked = staker_unlocked_share(staker_total, 0).unwrap();
    let zero_carry = staker_total.checked_sub(zero_unlocked).unwrap();
    let mut zero_state = dung_mint_state(0, 0, 0);
    zero_state.reserve_community(zero_unlocked).unwrap();
    assert_eq!(zero_state.community_reserved, 0);
    assert_eq!(zero_carry, staker_total);

    let unlocked = 5;
    let total_lp = 3u128;
    let allocations = [
        staker_lp_share(unlocked, 1, total_lp).unwrap(),
        staker_lp_share(unlocked, 1, total_lp).unwrap(),
        staker_lp_share(unlocked, 1, total_lp).unwrap(),
    ];
    let distributed = checked_sum_u64(allocations).unwrap();
    let carry = unlocked.checked_sub(distributed).unwrap();
    let mut rounding_state = dung_mint_state(0, 0, 0);
    rounding_state.reserve_community(distributed).unwrap();

    assert_eq!(distributed, 3);
    assert_eq!(carry, 2);
    assert_eq!(checked_sum_u64([distributed, carry]).unwrap(), unlocked);
    assert_eq!(rounding_state.community_reserved, distributed);
}

#[test]
fn stake_change_week_uses_the_ratified_boundary_seconds() {
    let clock = test_settlement_clock();
    let week = 10;
    let start = clock.week_start(week).unwrap();

    assert_eq!(
        VaultStake::effective_week_for_change(&clock, start - 1).unwrap(),
        week
    );
    assert_eq!(
        VaultStake::effective_week_for_change(&clock, start).unwrap(),
        week
    );
    assert_eq!(
        VaultStake::effective_week_for_change(&clock, start + 1).unwrap(),
        week + 1
    );
}

#[test]
fn mature_top_up_keeps_current_week_weight_and_promotes_next_week() {
    let clock = test_settlement_clock();
    let week = 10;
    let changed_at = clock.week_start(week).unwrap() + 1;
    let mut stake = snapshot_stake(100, 100, 0, None);

    stake
        .prepare_lp_change(&clock, 1_100, changed_at, week)
        .unwrap();

    assert_eq!(stake.effective_lp_tokens, 100);
    assert_eq!(stake.pending_lp_tokens, 1_100);
    assert_eq!(stake.pending_effective_week().unwrap(), Some(week + 1));
    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 100);
    assert_eq!(
        stake.lp_tokens_for_settlement(&clock, week + 1).unwrap(),
        1_100
    );
    assert_eq!(stake.effective_lp_tokens, 1_100);
    assert_eq!(stake.pending_effective_week().unwrap(), None);
}

#[test]
fn partial_exit_does_not_rewrite_the_open_week() {
    let clock = test_settlement_clock();
    let week = 10;
    let changed_at = clock.week_start(week).unwrap() + 30;
    let mut stake = snapshot_stake(100, 100, 0, None);

    stake
        .prepare_lp_change(&clock, 40, changed_at, week)
        .unwrap();

    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 100);
    assert_eq!(
        stake.lp_tokens_for_settlement(&clock, week + 1).unwrap(),
        40
    );
}

#[test]
fn full_exit_and_reentry_in_one_effective_week_replace_the_pending_target() {
    let clock = test_settlement_clock();
    let week = 10;
    let changed_at = clock.week_start(week).unwrap() + 60;
    let mut stake = snapshot_stake(100, 100, 0, None);

    stake
        .prepare_lp_change(&clock, 0, changed_at, week)
        .unwrap();
    stake
        .prepare_lp_change(&clock, 60, changed_at + 1, week)
        .unwrap();

    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 100);
    assert_eq!(
        stake.lp_tokens_for_settlement(&clock, week + 1).unwrap(),
        60
    );
}

#[test]
fn unresolved_changes_for_two_future_weeks_fail_closed() {
    let clock = test_settlement_clock();
    let week = 10;
    let mut stake = snapshot_stake(100, 100, 0, None);

    stake
        .prepare_lp_change(&clock, 150, clock.week_start(week).unwrap() + 1, week)
        .unwrap();
    assert_error_code(
        stake.prepare_lp_change(&clock, 200, clock.week_start(week + 1).unwrap() + 1, week),
        ErrorCode::StakeSnapshotQueueFull,
    );
}

#[test]
fn open_week_transition_promotes_before_queueing_the_next_week() {
    let clock = test_settlement_clock();
    let week = 10;
    let mut stake = snapshot_stake(150, 100, 150, Some(week));

    stake
        .prepare_lp_change(&clock, 200, clock.week_start(week).unwrap() + 1, week)
        .unwrap();

    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 150);
    assert_eq!(
        stake.lp_tokens_for_settlement(&clock, week + 1).unwrap(),
        200
    );
}

#[test]
fn legacy_active_stake_lazily_becomes_an_effective_snapshot() {
    let clock = test_settlement_clock();
    let week = 10;
    let mut stake = snapshot_stake(100, 0, 0, Some(week - 1));
    // Before this change the same bytes held raw eligible_from_epoch rather
    // than the plus-one pending-week encoding.
    stake.pending_effective_week_plus_one = week - 1;

    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 100);
    assert_eq!(stake.effective_lp_tokens, 100);
    assert_eq!(stake.pending_effective_week().unwrap(), None);
}

#[test]
fn legacy_future_stake_drops_the_old_extra_wait_week() {
    let clock = test_settlement_clock();
    let week = 10;
    let mut stake = snapshot_stake(100, 0, 0, Some(week + 2));
    stake.staked_at = clock.week_start(week).unwrap() + 1;
    // Raw legacy encoding: the old formula stored week + 2 directly.
    stake.pending_effective_week_plus_one = week + 2;

    assert_eq!(stake.lp_tokens_for_settlement(&clock, week).unwrap(), 0);
    assert_eq!(stake.pending_effective_week().unwrap(), Some(week + 1));
    assert_eq!(
        stake.lp_tokens_for_settlement(&clock, week + 1).unwrap(),
        100
    );
}

#[test]
fn legacy_dung_migration_appends_reservation_and_preserves_121_bytes() {
    let legacy = live_legacy_dung_mint_state();
    let legacy_bytes = legacy_dung_mint_state_bytes(&legacy);
    let original_legacy_bytes = legacy_bytes.clone();
    let expected_reservation = 449_565;

    assert!(validate_dung_mint_state_migration(
        &legacy_bytes,
        legacy.authority,
        legacy.bump,
        expected_reservation,
    )
    .unwrap());

    let mut migrated_bytes = legacy_bytes;
    migrated_bytes.resize(DungMintState::SIZE, 0);
    write_dung_mint_state_policy(
        &mut migrated_bytes,
        expected_reservation,
        DUNG_RESERVATION_POLICY_VERSION,
    )
    .unwrap();

    assert_eq!(DungMintState::LEGACY_SIZE, 121);
    assert_eq!(DungMintState::CLAIM_RESERVATION_SIZE, 129);
    assert_eq!(DungMintState::SIZE, 130);
    assert_eq!(
        &migrated_bytes[..DungMintState::LEGACY_SIZE],
        original_legacy_bytes.as_slice()
    );
    assert!(!validate_dung_mint_state_migration(
        &migrated_bytes,
        legacy.authority,
        legacy.bump,
        expected_reservation,
    )
    .unwrap());

    let layout = inspect_dung_mint_state_layout(&migrated_bytes).unwrap();
    assert_eq!(layout.legacy, legacy);
    assert_eq!(layout.community_reserved, Some(expected_reservation));
    assert_eq!(
        layout.reservation_policy_version,
        Some(DUNG_RESERVATION_POLICY_VERSION)
    );
    layout
        .legacy
        .with_reservation_policy(expected_reservation, DUNG_RESERVATION_POLICY_VERSION)
        .assert_solvent()
        .unwrap();

    assert_error_code(
        validate_dung_mint_state_migration(
            &migrated_bytes,
            legacy.authority,
            legacy.bump,
            expected_reservation + 1,
        ),
        ErrorCode::CommunityReservationMismatch,
    );
}

#[test]
fn claim_only_reservation_migration_tops_up_monotonically_and_sets_policy_version() {
    let legacy = live_legacy_dung_mint_state();
    let claim_only_reservation: u64 = 449_565;
    let full_reservation: u64 = 1_069_289_469_981;
    let mut claim_only_bytes = legacy_dung_mint_state_bytes(&legacy);
    claim_only_bytes.resize(DungMintState::CLAIM_RESERVATION_SIZE, 0);
    claim_only_bytes
        [DungMintState::COMMUNITY_RESERVED_OFFSET..DungMintState::CLAIM_RESERVATION_SIZE]
        .copy_from_slice(&claim_only_reservation.to_le_bytes());

    assert!(validate_dung_mint_state_migration(
        &claim_only_bytes,
        legacy.authority,
        legacy.bump,
        full_reservation,
    )
    .unwrap());
    assert_error_code(
        validate_dung_mint_state_migration(
            &claim_only_bytes,
            legacy.authority,
            legacy.bump,
            claim_only_reservation - 1,
        ),
        ErrorCode::CommunityReservationMismatch,
    );

    claim_only_bytes.resize(DungMintState::SIZE, 0);
    write_dung_mint_state_policy(
        &mut claim_only_bytes,
        full_reservation,
        DUNG_RESERVATION_POLICY_VERSION,
    )
    .unwrap();
    assert!(!validate_dung_mint_state_migration(
        &claim_only_bytes,
        legacy.authority,
        legacy.bump,
        full_reservation,
    )
    .unwrap());
}

#[test]
fn settlement_accounting_rejects_an_unmigrated_reservation_policy() {
    let mut state = dung_mint_state(0, 0, 0);
    state.reservation_policy_version = 0;

    assert_error_code(
        plan_settlement_emission(
            &state,
            1_000,
            SettlementBucketShares {
                record_royalty: 0,
                stakers: 0,
                local_legend: 0,
                pol: 0,
                treasury: 0,
            },
            &distribution_config(),
        ),
        ErrorCode::DungReservationPolicyNotMigrated,
    );
}

#[test]
fn legacy_dung_migration_rejects_unproven_identity_and_emission_history() {
    let legacy = live_legacy_dung_mint_state();
    let data = legacy_dung_mint_state_bytes(&legacy);

    assert_error_code(
        validate_dung_mint_state_migration(&data, Pubkey::new_unique(), legacy.bump, 449_565),
        ErrorCode::DungMintAuthorityMismatch,
    );
    assert_error_code(
        validate_dung_mint_state_migration(
            &data,
            legacy.authority,
            legacy.bump.wrapping_add(1),
            449_565,
        ),
        ErrorCode::InvalidDungMintStateBump,
    );

    let mut halved = legacy;
    halved.current_emission_rate_bps = BASIS_POINTS_DENOMINATOR / 2;
    let halved_data = legacy_dung_mint_state_bytes(&halved);
    assert_error_code(
        validate_dung_mint_state_migration(
            &halved_data,
            halved.authority,
            halved.bump,
            449_565,
        ),
        ErrorCode::LegacyEmissionHistoryAmbiguous,
    );
}

#[test]
fn legacy_dung_migration_rejects_corrupted_bucket_identity() {
    let mut corrupted = live_legacy_dung_mint_state();
    corrupted.total_minted = corrupted.total_minted.checked_add(1).unwrap();
    let data = legacy_dung_mint_state_bytes(&corrupted);

    assert_error_code(
        validate_dung_mint_state_migration(&data, corrupted.authority, corrupted.bump, 449_565),
        ErrorCode::DungMintAccountingMismatch,
    );
}

#[test]
fn migration_inventory_includes_inactive_claims_and_rejects_bad_inputs() {
    let inactive = vault_stake_account_info(Pubkey::new_unique(), 7, 149_877, false);
    assert_eq!(
        sum_migration_community_obligations(&ID, &[inactive.clone()], 1, 0).unwrap(),
        149_877
    );

    assert_error_code(
        sum_migration_community_obligations(&ID, &[inactive.clone()], 2, 0),
        ErrorCode::VaultStakeCountMismatch,
    );
    assert_error_code(
        sum_migration_community_obligations(&ID, &[inactive.clone(), inactive.clone()], 2, 0),
        ErrorCode::DuplicateMigrationAccount,
    );

    let valid_data = inactive.try_borrow_data().unwrap().to_vec();
    let wrong_owner = leaked_account_info(
        *inactive.key,
        anchor_lang::system_program::ID,
        valid_data.clone(),
    );
    assert_error_code(
        sum_migration_community_obligations(&ID, &[wrong_owner], 1, 0),
        ErrorCode::InvalidMigrationInventory,
    );

    let mut wrong_size_data = valid_data.clone();
    wrong_size_data.pop();
    let wrong_size = leaked_account_info(*inactive.key, ID, wrong_size_data);
    assert_error_code(
        sum_migration_community_obligations(&ID, &[wrong_size], 1, 0),
        ErrorCode::InvalidMigrationInventory,
    );

    let mut wrong_discriminator_data = valid_data.clone();
    wrong_discriminator_data[0] ^= 1;
    let wrong_discriminator = leaked_account_info(*inactive.key, ID, wrong_discriminator_data);
    assert_error_code(
        sum_migration_community_obligations(&ID, &[wrong_discriminator], 1, 0),
        ErrorCode::InvalidStakeAccount,
    );

    let wrong_pda = leaked_account_info(Pubkey::new_unique(), ID, valid_data);
    assert_error_code(
        sum_migration_community_obligations(&ID, &[wrong_pda], 1, 0),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn migration_inventory_reserves_community_carry_and_rejects_protocol_carry() {
    let stake = vault_stake_account_info(Pubkey::new_unique(), 0, 149_877, false);
    let vault = vault_account_info(0, 100, 200, 300, 0, 0);

    assert_eq!(
        sum_migration_community_obligations(&ID, &[stake, vault], 1, 1).unwrap(),
        150_477
    );

    let unreserved_pol = vault_account_info(0, 0, 0, 0, 1, 0);
    assert_error_code(
        sum_migration_community_obligations(&ID, &[unreserved_pol], 0, 1),
        ErrorCode::UnreservedProtocolCarry,
    );
}

#[test]
fn migration_inventory_sum_uses_checked_u128_and_fallible_u64_narrowing() {
    let first = vault_stake_account_info(Pubkey::new_unique(), 1, u64::MAX, false);
    let second = vault_stake_account_info(Pubkey::new_unique(), 2, 1, false);

    assert_error_code(
        sum_migration_community_obligations(&ID, &[first, second], 2, 0),
        ErrorCode::Overflow,
    );
}

#[test]
fn settlement_stake_prescan_requires_complete_relevant_inventory_and_uses_week_snapshot() {
    let vault_id = 7;
    let settlement_week = 10;
    let eligible_user = Pubkey::new_unique();
    let tombstone_user = Pubkey::new_unique();
    let recipient =
        leaked_account_info(Pubkey::new_unique(), anchor_spl::token::ID, Vec::new());
    let eligible = vault_stake_position_account_info(eligible_user, vault_id, 3, 3, 3, 0, None);
    let pending = vault_stake_position_account_info(
        Pubkey::new_unique(),
        vault_id,
        5,
        5,
        0,
        5,
        Some(settlement_week + 1),
    );
    let tombstone = vault_stake_position_account_info(
        tombstone_user,
        vault_id,
        0,
        0,
        2,
        0,
        Some(settlement_week + 1),
    );
    let supplied = Box::leak(vec![recipient, eligible, pending, tombstone].into_boxed_slice());

    let (inventory, total_lp, next_inventory_count) = pre_scan_settlement_stakes(
        &ID,
        &anchor_spl::token::ID,
        supplied,
        vault_id,
        &test_settlement_clock(),
        settlement_week,
        3,
    )
    .unwrap();

    assert_eq!(inventory.len(), 3);
    let eligible = inventory
        .iter()
        .filter(|(_, settlement_lp)| *settlement_lp > 0)
        .map(|(stake, settlement_lp)| (stake.user, *settlement_lp))
        .collect::<Vec<_>>();
    assert_eq!(eligible, vec![(eligible_user, 3), (tombstone_user, 2)]);
    assert_eq!(total_lp, 5);
    assert_eq!(next_inventory_count, 3);
}

#[test]
fn settlement_stake_prescan_rejects_any_omitted_inventory_account() {
    let supplied = Box::leak(
        vec![vault_stake_account_info(Pubkey::new_unique(), 7, 0, true)].into_boxed_slice(),
    );

    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            supplied,
            7,
            &test_settlement_clock(),
            10,
            2,
        )
        .map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn settlement_stake_prescan_rejects_fully_inert_accounts() {
    let supplied = Box::leak(
        vec![vault_stake_account_info(Pubkey::new_unique(), 7, 0, false)].into_boxed_slice(),
    );

    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            supplied,
            7,
            &test_settlement_clock(),
            10,
            1,
        )
        .map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn settlement_stake_prescan_drops_a_tombstone_when_zero_becomes_effective() {
    let settlement_week = 10;
    let tombstone = vault_stake_position_account_info(
        Pubkey::new_unique(),
        7,
        0,
        0,
        2,
        0,
        Some(settlement_week),
    );
    let supplied = Box::leak(vec![tombstone].into_boxed_slice());

    let (inventory, total_lp, next_inventory_count) = pre_scan_settlement_stakes(
        &ID,
        &anchor_spl::token::ID,
        supplied,
        7,
        &test_settlement_clock(),
        settlement_week,
        1,
    )
    .unwrap();

    assert_eq!(inventory.len(), 1);
    assert_eq!(inventory[0].1, 0);
    assert_eq!(total_lp, 0);
    assert_eq!(next_inventory_count, 0);
}

#[test]
fn settlement_stake_prescan_rejects_duplicates_and_malformed_tail() {
    let vault_id = 7;
    let stake = vault_stake_account_info(Pubkey::new_unique(), vault_id, 0, true);
    let duplicates = Box::leak(vec![stake.clone(), stake.clone()].into_boxed_slice());
    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            duplicates,
            vault_id,
            &test_settlement_clock(),
            0,
            2,
        )
        .map(|_| ()),
        ErrorCode::DuplicateVaultStake,
    );

    let valid_data = stake.try_borrow_data().unwrap().to_vec();
    let wrong_pda = leaked_account_info(Pubkey::new_unique(), ID, valid_data.clone());
    let wrong_pda_supplied = Box::leak(vec![wrong_pda].into_boxed_slice());
    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            wrong_pda_supplied,
            vault_id,
            &test_settlement_clock(),
            0,
            1,
        )
        .map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );

    let wrong_owner =
        leaked_account_info(*stake.key, anchor_lang::system_program::ID, valid_data);
    let wrong_owner_supplied = Box::leak(vec![wrong_owner].into_boxed_slice());
    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            wrong_owner_supplied,
            vault_id,
            &test_settlement_clock(),
            0,
            1,
        )
        .map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );

    let token_owned_tail =
        leaked_account_info(Pubkey::new_unique(), anchor_spl::token::ID, Vec::new());
    let token_tail_supplied =
        Box::leak(vec![stake.clone(), token_owned_tail].into_boxed_slice());
    assert_error_code(
        pre_scan_settlement_stakes(
            &ID,
            &anchor_spl::token::ID,
            token_tail_supplied,
            vault_id,
            &test_settlement_clock(),
            0,
            1,
        )
        .map(|_| ()),
        ErrorCode::InvalidStakeAccount,
    );
}

#[test]
fn settlement_stake_prescan_preserves_snapshot_payout_weights() {
    let vault_id = 7;
    let settlement_week = 10;
    let first =
        vault_stake_position_account_info(Pubkey::new_unique(), vault_id, 2, 2, 2, 0, None);
    let second =
        vault_stake_position_account_info(Pubkey::new_unique(), vault_id, 3, 3, 3, 0, None);
    let pending = vault_stake_position_account_info(
        Pubkey::new_unique(),
        vault_id,
        5,
        5,
        0,
        5,
        Some(settlement_week + 1),
    );
    let supplied = Box::leak(vec![first, second, pending].into_boxed_slice());

    let (inventory, total_lp, next_inventory_count) = pre_scan_settlement_stakes(
        &ID,
        &anchor_spl::token::ID,
        supplied,
        vault_id,
        &test_settlement_clock(),
        settlement_week,
        3,
    )
    .unwrap();
    let unlocked = staker_unlocked_share(10_000, STAKER_UNLOCK_PCTS[1]).unwrap();
    let allocations = inventory
        .iter()
        .filter(|(_, lp)| *lp > 0)
        .map(|(_, lp)| staker_lp_share(unlocked, *lp, total_lp))
        .collect::<Result<Vec<_>>>()
        .unwrap();

    assert_eq!(inventory.len(), 3);
    assert_eq!(total_lp, 5);
    assert_eq!(next_inventory_count, 3);
    assert_eq!(unlocked, 300);
    assert_eq!(allocations, vec![120, 180]);
}

#[test]
fn settlement_math_bucket_shares_cover_u64_max_and_preserve_dust() {
    let config = distribution_config();

    for total_dung in [0, 1, 9_999, 10_000, MAX_SUPPLY, u64::MAX] {
        let shares = settlement_bucket_shares(total_dung, &config).unwrap();
        let nominal = [
            expected_share(
                total_dung,
                config.leaderboard_share_bps,
                BASIS_POINTS_DENOMINATOR,
            ),
            expected_share(
                total_dung,
                config.staker_share_bps,
                BASIS_POINTS_DENOMINATOR,
            ),
            expected_share(
                total_dung,
                config.local_legend_share_bps,
                BASIS_POINTS_DENOMINATOR,
            ),
            expected_share(total_dung, config.pol_share_bps, BASIS_POINTS_DENOMINATOR),
            expected_share(
                total_dung,
                config.protocol_fee_bps,
                BASIS_POINTS_DENOMINATOR,
            ),
        ];
        let nominal_total = nominal
            .iter()
            .try_fold(0u128, |sum, &share| sum.checked_add(share as u128))
            .unwrap();
        let dust = total_dung
            .checked_sub(u64::try_from(nominal_total).unwrap())
            .unwrap();

        assert_eq!(shares.record_royalty, nominal[0].checked_add(dust).unwrap());
        assert_eq!(shares.stakers, nominal[1]);
        assert_eq!(shares.local_legend, nominal[2]);
        assert_eq!(shares.pol, nominal[3]);
        assert_eq!(shares.treasury, nominal[4]);
        assert_eq!(shares.total().unwrap(), total_dung);
    }
}

#[test]
fn settlement_math_rejects_invalid_configs_without_panicking() {
    let invalid_configs = [
        DistributionConfig {
            protocol_fee_bps: 999,
            ..distribution_config()
        },
        DistributionConfig {
            leaderboard_share_bps: 10_001,
            staker_share_bps: 0,
            local_legend_share_bps: 0,
            pol_share_bps: 0,
            protocol_fee_bps: 0,
        },
        DistributionConfig {
            leaderboard_share_bps: u64::MAX,
            staker_share_bps: 1,
            local_legend_share_bps: 0,
            pol_share_bps: 0,
            protocol_fee_bps: 0,
        },
        DistributionConfig {
            leaderboard_share_bps: u64::MAX,
            staker_share_bps: u64::MAX,
            local_legend_share_bps: u64::MAX,
            pol_share_bps: u64::MAX,
            protocol_fee_bps: u64::MAX,
        },
    ];

    for config in invalid_configs {
        assert!(!config.validate());
        assert_error_code(
            settlement_bucket_shares(u64::MAX, &config),
            ErrorCode::InvalidDistributionConfig,
        );
    }
}

#[test]
fn settlement_math_checked_helpers_return_anchor_errors() {
    assert_error_code(
        checked_mul_div_u64(u64::MAX, u64::MAX, 1),
        ErrorCode::Overflow,
    );
    assert_error_code(checked_mul_div_u64(1, 1, 0), ErrorCode::DivisionByZero);
    assert_error_code(checked_sum_u64([u64::MAX, 1]), ErrorCode::Overflow);
    assert_error_code(
        staker_unlocked_share(u64::MAX, u8::MAX),
        ErrorCode::Overflow,
    );
    assert_error_code(staker_lp_share(u64::MAX, u64::MAX, 1), ErrorCode::Overflow);
    assert_error_code(staker_lp_share(1, 1, 0), ErrorCode::DivisionByZero);

    let mut mint_state = dung_mint_state(0, 0, 0);
    assert_eq!(mint_state.apply_emission_rate(u64::MAX).unwrap(), u64::MAX);
    mint_state.current_emission_rate_bps = u64::MAX;
    assert_error_code(
        mint_state.apply_emission_rate(u64::MAX),
        ErrorCode::Overflow,
    );
}

#[test]
fn settlement_math_leaderboard_entry_shares_conserve_for_every_tie_partition() {
    for num_entries in 1..=LEADERBOARD_RANK_PCTS.len() {
        for partition_mask in 0..(1usize << (num_entries - 1)) {
            let mut time_s = 100u32;
            let entries = (0..num_entries)
                .map(|index| {
                    if index > 0 && partition_mask & (1usize << (index - 1)) != 0 {
                        time_s += 1;
                    }
                    LeaderEntry {
                        user: Pubkey::new_from_array([u8::try_from(index + 1).unwrap(); 32]),
                        time_s,
                        recorded_at: i64::try_from(index).unwrap(),
                    }
                })
                .collect::<Vec<_>>();

            let allocations = leaderboard_entry_shares(u64::MAX, &entries).unwrap();
            assert_eq!(allocations.len(), num_entries);

            let mut group_start = 0usize;
            while group_start < num_entries {
                let mut group_end = group_start + 1;
                while group_end < num_entries
                    && entries[group_end].time_s == entries[group_start].time_s
                {
                    group_end += 1;
                }
                assert!(allocations[group_start..group_end]
                    .iter()
                    .all(|share| *share == allocations[group_start]));
                group_start = group_end;
            }

            let distributed = checked_sum_u64(allocations).unwrap();
            let carry = u64::MAX.checked_sub(distributed).unwrap();
            assert_eq!(checked_sum_u64([distributed, carry]).unwrap(), u64::MAX);
        }
    }
}

#[test]
fn record_board_ties_pool_occupied_rank_shares_equally() {
    let entries = vec![
        LeaderEntry {
            user: Pubkey::new_from_array([1; 32]),
            time_s: 100,
            recorded_at: 10,
        },
        LeaderEntry {
            user: Pubkey::new_from_array([2; 32]),
            time_s: 120,
            recorded_at: 20,
        },
        LeaderEntry {
            user: Pubkey::new_from_array([3; 32]),
            time_s: 120,
            recorded_at: 30,
        },
    ];

    let shares = leaderboard_entry_shares(650, &entries).unwrap();

    assert_eq!(shares, vec![300, 175, 175]);
    assert_eq!(checked_sum_u64(shares).unwrap(), 650);
}

#[test]
fn record_board_tie_rounding_is_equal_and_remains_in_record_royalty() {
    let entries = vec![
        LeaderEntry {
            user: Pubkey::new_from_array([1; 32]),
            time_s: 100,
            recorded_at: 10,
        },
        LeaderEntry {
            user: Pubkey::new_from_array([2; 32]),
            time_s: 120,
            recorded_at: 20,
        },
        LeaderEntry {
            user: Pubkey::new_from_array([3; 32]),
            time_s: 120,
            recorded_at: 30,
        },
        LeaderEntry {
            user: Pubkey::new_from_array([4; 32]),
            time_s: 140,
            recorded_at: 40,
        },
    ];

    let shares = leaderboard_entry_shares(101, &entries).unwrap();
    let distributed = checked_sum_u64(shares.iter().copied()).unwrap();

    assert_eq!(shares, vec![40, 23, 23, 13]);
    assert_eq!(shares[1], shares[2]);
    assert_eq!(101 - distributed, 2);
}

#[test]
fn record_board_equal_times_have_ingestion_independent_order() {
    let earlier = Pubkey::new_from_array([2; 32]);
    let later = Pubkey::new_from_array([1; 32]);
    let mut first = VaultLeaderboard {
        vault_id: 1,
        entries: vec![],
        last_updated: 0,
        bump: 1,
    };
    let mut second = VaultLeaderboard {
        vault_id: 1,
        entries: vec![],
        last_updated: 0,
        bump: 1,
    };

    first.update_entry(later, 120, 20);
    first.update_entry(earlier, 120, 10);
    second.update_entry(earlier, 120, 10);
    second.update_entry(later, 120, 20);

    assert_eq!(
        first
            .entries
            .iter()
            .map(|entry| entry.user)
            .collect::<Vec<_>>(),
        second
            .entries
            .iter()
            .map(|entry| entry.user)
            .collect::<Vec<_>>()
    );
    assert_eq!(first.entries[0].user, earlier);
}

#[test]
fn record_board_same_rider_equal_time_keeps_earliest_completion() {
    let rider = Pubkey::new_from_array([7; 32]);
    let mut late_first = VaultLeaderboard {
        vault_id: 1,
        entries: vec![],
        last_updated: 0,
        bump: 1,
    };
    let mut early_first = VaultLeaderboard {
        vault_id: 1,
        entries: vec![],
        last_updated: 0,
        bump: 1,
    };

    late_first.update_entry(rider, 120, 20);
    late_first.update_entry(rider, 120, 10);
    early_first.update_entry(rider, 120, 10);
    early_first.update_entry(rider, 120, 20);

    assert_eq!(late_first.entries[0].recorded_at, 10);
    assert_eq!(early_first.entries[0].recorded_at, 10);
    assert_eq!(
        late_first.entries[0].recorded_at,
        early_first.entries[0].recorded_at
    );
    assert_eq!(late_first.last_updated, 20);
    assert_eq!(early_first.last_updated, 20);
}

#[test]
fn record_board_canonicalization_keeps_one_best_row_per_rider() {
    let repeated = Pubkey::new_from_array([7; 32]);
    let other = Pubkey::new_from_array([8; 32]);
    let mut board = VaultLeaderboard {
        vault_id: 1,
        entries: vec![
            LeaderEntry {
                user: repeated,
                time_s: 120,
                recorded_at: 20,
            },
            LeaderEntry {
                user: other,
                time_s: 110,
                recorded_at: 15,
            },
            LeaderEntry {
                user: repeated,
                time_s: 100,
                recorded_at: 10,
            },
        ],
        last_updated: 0,
        bump: 1,
    };

    board.canonicalize_entries();

    assert_eq!(board.entries.len(), 2);
    assert_eq!(board.entries[0].user, repeated);
    assert_eq!(board.entries[0].time_s, 100);
    assert_eq!(board.entries[1].user, other);
}

#[test]
fn settlement_math_staker_unlock_curve_conserves_at_u64_max() {
    assert_eq!(staker_unlocked_share(u64::MAX, 0).unwrap(), 0);

    let mut previous_unlocked = 0;
    for &unlock_pct in &STAKER_UNLOCK_PCTS {
        let unlocked = staker_unlocked_share(u64::MAX, unlock_pct).unwrap();
        let locked = u64::MAX.checked_sub(unlocked).unwrap();

        assert_eq!(
            unlocked,
            expected_share(
                u64::MAX,
                (unlock_pct as u64) * PERCENT_TO_BPS,
                BASIS_POINTS_DENOMINATOR,
            )
        );
        assert!(unlocked >= previous_unlocked);
        assert_eq!(checked_sum_u64([unlocked, locked]).unwrap(), u64::MAX);
        previous_unlocked = unlocked;
    }
}

#[test]
fn settlement_math_prior_unlocked_dust_is_added_after_current_week_curve() {
    let plan = staker_week_plan(27_001, 7, 1).unwrap();

    assert_eq!(plan.unlock_pct, 1);
    assert_eq!(plan.weekly_unlocked, 270);
    assert_eq!(plan.staker_distributable, 277);
    assert_eq!(plan.locked_staker_amount, 26_731);
    assert_eq!(staker_carry_after(plan, 275).unwrap(), 2);
}

#[test]
fn settlement_math_one_staker_week_never_recurves_locked_policy_amount() {
    let weekly_staker_maximum = 27_000_000_000u64;
    let expected_weekly_unlock = weekly_staker_maximum / 100;
    let mut carry_stakers = 0u64;
    let mut cumulative_distributed = 0u64;

    for _ in 0..52 {
        let plan = staker_week_plan(weekly_staker_maximum, carry_stakers, 1).unwrap();
        let distributed = plan.staker_distributable;

        assert_eq!(plan.weekly_unlocked, expected_weekly_unlock);
        cumulative_distributed = cumulative_distributed.checked_add(distributed).unwrap();
        carry_stakers = staker_carry_after(plan, distributed).unwrap();
    }

    assert_eq!(
        cumulative_distributed,
        expected_weekly_unlock.checked_mul(52).unwrap()
    );
    assert_eq!(carry_stakers, 0);
}

#[test]
fn settlement_math_52_changing_weeks_cover_zero_one_two_and_ten_stakers() {
    let counts = [0u32, 1, 2, 10];
    let mut prior_unlocked_dust = 5u64;

    for week in 0..52u64 {
        let eligible_count = counts[(week as usize) % counts.len()];
        let base_stakers = 27_001 + week;
        let plan = staker_week_plan(base_stakers, prior_unlocked_dust, eligible_count).unwrap();
        let expected_pct = staker_unlock_pct(eligible_count);
        let expected_weekly_unlocked =
            staker_unlocked_share(base_stakers, expected_pct).unwrap();

        assert_eq!(plan.unlock_pct, expected_pct);
        assert_eq!(plan.weekly_unlocked, expected_weekly_unlocked);
        assert_eq!(
            plan.staker_distributable,
            expected_weekly_unlocked + prior_unlocked_dust
        );

        let lp_tokens: Vec<u64> = (1..=eligible_count).map(u64::from).collect();
        let total_lp = lp_tokens.iter().map(|&lp| lp as u128).sum::<u128>();
        let distributed = if total_lp == 0 {
            0
        } else {
            checked_sum_u64(
                lp_tokens
                    .iter()
                    .map(|&lp| staker_lp_share(plan.staker_distributable, lp, total_lp))
                    .collect::<Result<Vec<_>>>()
                    .unwrap(),
            )
            .unwrap()
        };
        let next_dust = staker_carry_after(plan, distributed).unwrap();

        assert_eq!(
            checked_sum_u64([base_stakers, prior_unlocked_dust]).unwrap(),
            checked_sum_u64([plan.locked_staker_amount, distributed, next_dust]).unwrap()
        );
        if eligible_count == 0 {
            assert_eq!(plan.locked_staker_amount, base_stakers);
            assert_eq!(next_dust, prior_unlocked_dust);
        }
        prior_unlocked_dust = next_dust;
    }
}

#[test]
fn settlement_math_staker_counts_curve_only_the_current_week() {
    let base_stakers = 10_000u64;
    let prior_unlocked_dust = 7u64;

    for (count, expected_pct) in [(0, 0), (1, 1), (2, 3), (10, 100)] {
        let plan = staker_week_plan(base_stakers, prior_unlocked_dust, count).unwrap();
        let weekly_unlocked = expected_share(
            base_stakers,
            (expected_pct as u64) * PERCENT_TO_BPS,
            BASIS_POINTS_DENOMINATOR,
        );

        assert_eq!(plan.unlock_pct, expected_pct);
        assert_eq!(plan.weekly_unlocked, weekly_unlocked);
        assert_eq!(
            plan.staker_distributable,
            weekly_unlocked + prior_unlocked_dust
        );
        assert_eq!(plan.locked_staker_amount, base_stakers - weekly_unlocked);
        assert_eq!(
            checked_sum_u64([weekly_unlocked, plan.locked_staker_amount]).unwrap(),
            base_stakers
        );
    }

    let empty_plan = staker_week_plan(base_stakers, prior_unlocked_dust, 0).unwrap();
    assert_eq!(
        staker_carry_after(empty_plan, 0).unwrap(),
        prior_unlocked_dust
    );
}

#[test]
fn settlement_math_changing_counts_preserve_prior_unlocked_dust() {
    let base_stakers = 10_034u64;

    let two_staker_week = staker_week_plan(base_stakers, 0, 2).unwrap();
    assert_eq!(two_staker_week.staker_distributable, 301);
    let first_allocation = staker_lp_share(two_staker_week.staker_distributable, 1, 2).unwrap();
    let first_distributed = checked_sum_u64([first_allocation, first_allocation]).unwrap();
    let prior_unlocked_dust = staker_carry_after(two_staker_week, first_distributed).unwrap();
    assert_eq!(prior_unlocked_dust, 1);

    let one_staker_week = staker_week_plan(base_stakers, prior_unlocked_dust, 1).unwrap();
    assert_eq!(one_staker_week.staker_distributable, 101);
    assert_eq!(one_staker_week.locked_staker_amount, 9_934);
    assert_eq!(
        staker_carry_after(one_staker_week, one_staker_week.staker_distributable).unwrap(),
        0
    );

    let ten_staker_week = staker_week_plan(base_stakers, 0, 10).unwrap();
    assert_eq!(ten_staker_week.staker_distributable, base_stakers);
    assert_eq!(ten_staker_week.locked_staker_amount, 0);
}

#[test]
fn settlement_math_pro_rata_dust_is_the_only_staker_carry() {
    let plan = staker_week_plan(10_034, 0, 2).unwrap();
    let allocation = staker_lp_share(plan.staker_distributable, 1, 2).unwrap();
    let distributed = checked_sum_u64([allocation, allocation]).unwrap();
    let carry = staker_carry_after(plan, distributed).unwrap();

    assert_eq!(plan.staker_distributable, 301);
    assert_eq!(plan.locked_staker_amount, 9_733);
    assert_eq!(distributed, 300);
    assert_eq!(carry, 1);

    let next_week = staker_week_plan(10_000, carry, 1).unwrap();
    assert_eq!(next_week.staker_distributable, 101);
}

#[test]
fn settlement_math_staker_week_plan_covers_u64_boundaries() {
    let weekly_unlocked = expected_share(u64::MAX, PERCENT_TO_BPS, BASIS_POINTS_DENOMINATOR);
    let plan = staker_week_plan(u64::MAX, 0, 1).unwrap();
    assert_eq!(plan.staker_distributable, weekly_unlocked);
    assert_eq!(
        checked_sum_u64([plan.staker_distributable, plan.locked_staker_amount]).unwrap(),
        u64::MAX
    );

    let largest_prior_dust = u64::MAX - weekly_unlocked;
    let full = staker_week_plan(u64::MAX, largest_prior_dust, 1).unwrap();
    assert_eq!(full.staker_distributable, u64::MAX);
    assert_eq!(staker_carry_after(full, u64::MAX).unwrap(), 0);

    assert_error_code(
        staker_week_plan(u64::MAX, largest_prior_dust + 1, 1),
        ErrorCode::Overflow,
    );
    assert_error_code(staker_week_plan(u64::MAX, 1, 10), ErrorCode::Overflow);
}

#[test]
fn settlement_math_empty_record_board_keeps_reallocated_value_in_record_carry() {
    let total_dung = 10_003u64;
    let prior_record_carry = 11u64;
    let prior_staker_dust = 7u64;
    let buckets = settlement_bucket_shares(total_dung, &distribution_config()).unwrap();
    let staker_plan = staker_week_plan(buckets.stakers, prior_staker_dust, 0).unwrap();
    let record_carry = checked_sum_u64([
        buckets.record_royalty,
        prior_record_carry,
        staker_plan.locked_staker_amount,
    ])
    .unwrap();
    let staker_carry = staker_carry_after(staker_plan, 0).unwrap();

    assert_eq!(staker_carry, prior_staker_dust);
    assert_eq!(staker_plan.locked_staker_amount, buckets.stakers);
    assert_eq!(
        checked_sum_u64([
            record_carry,
            staker_carry,
            buckets.local_legend,
            buckets.pol,
            buckets.treasury,
        ])
        .unwrap(),
        checked_sum_u64([total_dung, prior_record_carry, prior_staker_dust]).unwrap()
    );
}

#[test]
fn settlement_math_legacy_staker_carry_is_reallocated_exactly_once() {
    assert!(STAKER_REMAINDER_POLICY_MARKER > MAX_SUPPLY);

    let legacy = classify_prior_staker_carry(0, 2_673);
    assert_eq!(legacy.unlocked_dust, 0);
    assert_eq!(legacy.legacy_locked, 2_673);

    let current = classify_prior_staker_carry(STAKER_REMAINDER_POLICY_MARKER, 7);
    assert_eq!(current.unlocked_dust, 7);
    assert_eq!(current.legacy_locked, 0);
}

#[test]
fn settlement_math_full_conservation_preserves_all_reserved_liabilities() {
    let total_dung = 1_000_003u64;
    let prior_record_carry = 11u64;
    let prior_legacy_staker_carry = 2_673u64;
    let prior_legend_carry = 13u64;
    let prior_carry = SettlementBucketShares {
        record_royalty: prior_record_carry,
        stakers: prior_legacy_staker_carry,
        local_legend: prior_legend_carry,
        pol: 0,
        treasury: 0,
    };
    let prior_reserved = prior_carry.community_total().unwrap();
    let mut mint_state = dung_mint_state(0, 0, prior_reserved);
    let emission_plan =
        plan_settlement_emission(&mint_state, total_dung, prior_carry, &distribution_config())
            .unwrap();
    assert_eq!(emission_plan.base_emission, total_dung);
    mint_state
        .reserve_community(emission_plan.base_shares.community_total().unwrap())
        .unwrap();

    let prior_staker_carry = classify_prior_staker_carry(0, prior_legacy_staker_carry);
    let staker_plan = staker_week_plan(
        emission_plan.base_shares.stakers,
        prior_staker_carry.unlocked_dust,
        2,
    )
    .unwrap();

    let leaderboard_total = checked_sum_u64([
        emission_plan.bucket_totals.record_royalty,
        prior_staker_carry.legacy_locked,
        staker_plan.locked_staker_amount,
    ])
    .unwrap();
    let leaderboard_entries = (0..3)
        .map(|index| LeaderEntry {
            user: Pubkey::new_from_array([u8::try_from(index + 1).unwrap(); 32]),
            time_s: u32::try_from(100 + index).unwrap(),
            recorded_at: i64::try_from(index).unwrap(),
        })
        .collect::<Vec<_>>();
    let record_distributed = checked_sum_u64(
        leaderboard_entry_shares(leaderboard_total, &leaderboard_entries).unwrap(),
    )
    .unwrap();
    let record_carry = leaderboard_total.checked_sub(record_distributed).unwrap();

    let staker_lps = [1u64, 2];
    let total_lp = 3u128;
    let staker_distributed = checked_sum_u64(
        staker_lps
            .iter()
            .map(|&lp| staker_lp_share(staker_plan.staker_distributable, lp, total_lp))
            .collect::<Result<Vec<_>>>()
            .unwrap(),
    )
    .unwrap();
    let staker_carry = staker_carry_after(staker_plan, staker_distributed).unwrap();
    let legend_distributed = emission_plan.bucket_totals.local_legend;
    let pol_distributed = emission_plan.bucket_totals.pol;
    let treasury_distributed = emission_plan.bucket_totals.treasury;

    mint_state
        .consume_community_reservation(record_distributed)
        .unwrap();
    mint_state
        .consume_community_reservation(legend_distributed)
        .unwrap();
    mint_state
        .record_mint(pol_distributed, AllocationBucket::Pol)
        .unwrap();
    mint_state
        .record_mint(treasury_distributed, AllocationBucket::Treasury)
        .unwrap();
    let immediate_minted = checked_sum_u64([
        record_distributed,
        legend_distributed,
        pol_distributed,
        treasury_distributed,
    ])
    .unwrap();
    assert_eq!(mint_state.total_minted, immediate_minted);
    let expected_reserved =
        checked_sum_u64([record_carry, staker_distributed, staker_carry]).unwrap();
    assert_eq!(mint_state.community_reserved, expected_reserved);
    let incoming = checked_sum_u64([
        total_dung,
        prior_record_carry,
        prior_legacy_staker_carry,
        prior_legend_carry,
    ])
    .unwrap();
    assert_eq!(mint_state.committed_total().unwrap(), incoming);
    mint_state.assert_solvent().unwrap();

    let accounted =
        checked_sum_u64([mint_state.total_minted, mint_state.community_reserved]).unwrap();
    assert_eq!(accounted, incoming);
}

#[test]
fn settlement_math_staker_lp_shares_conserve_with_u128_total() {
    let unlocked = staker_unlocked_share(u64::MAX, 70).unwrap();
    let lp_tokens = [u64::MAX, u64::MAX - 1, 1];
    let total_lp = lp_tokens
        .iter()
        .try_fold(0u128, |sum, &lp| sum.checked_add(lp as u128))
        .unwrap();
    assert!(total_lp > u64::MAX as u128);

    let allocations: Vec<u64> = lp_tokens
        .iter()
        .map(|&lp| staker_lp_share(unlocked, lp, total_lp))
        .collect::<Result<Vec<_>>>()
        .unwrap();
    for (&allocation, &lp) in allocations.iter().zip(&lp_tokens) {
        let expected = u64::try_from(
            (unlocked as u128)
                .checked_mul(lp as u128)
                .unwrap()
                .checked_div(total_lp)
                .unwrap(),
        )
        .unwrap();
        assert_eq!(allocation, expected);
    }

    let distributed = checked_sum_u64(allocations.iter().copied()).unwrap();
    let carry = unlocked.checked_sub(distributed).unwrap();
    assert_eq!(checked_sum_u64([distributed, carry]).unwrap(), unlocked);
    assert!(carry < u64::try_from(lp_tokens.len()).unwrap());
}

#[test]
fn settlement_math_all_share_paths_conserve_at_u64_max() {
    let buckets = settlement_bucket_shares(u64::MAX, &distribution_config()).unwrap();

    let staker_plan = staker_week_plan(buckets.stakers, 0, 9).unwrap();
    let leaderboard_total =
        checked_sum_u64([buckets.record_royalty, staker_plan.locked_staker_amount]).unwrap();
    let leaderboard_entries = (0..LEADERBOARD_RANK_PCTS.len())
        .map(|index| LeaderEntry {
            user: Pubkey::new_from_array([u8::try_from(index + 1).unwrap(); 32]),
            time_s: u32::try_from(100 + index).unwrap(),
            recorded_at: i64::try_from(index).unwrap(),
        })
        .collect::<Vec<_>>();
    let leaderboard_distributed = checked_sum_u64(
        leaderboard_entry_shares(leaderboard_total, &leaderboard_entries).unwrap(),
    )
    .unwrap();
    let leaderboard_carry = leaderboard_total
        .checked_sub(leaderboard_distributed)
        .unwrap();

    let lp_tokens = [1, 2, 3, 4, 5, 6, 7, 8, 9];
    let total_lp = lp_tokens
        .iter()
        .try_fold(0u128, |sum, &lp| sum.checked_add(lp as u128))
        .unwrap();
    let staker_distributed = checked_sum_u64(
        lp_tokens
            .iter()
            .map(|&lp| staker_lp_share(staker_plan.staker_distributable, lp, total_lp))
            .collect::<Result<Vec<_>>>()
            .unwrap(),
    )
    .unwrap();
    let staker_carry = staker_carry_after(staker_plan, staker_distributed).unwrap();

    assert_eq!(
        checked_sum_u64([leaderboard_distributed, leaderboard_carry]).unwrap(),
        leaderboard_total
    );
    assert_eq!(
        checked_sum_u64([staker_distributed, staker_carry]).unwrap(),
        staker_plan.staker_distributable
    );
    assert_eq!(
        checked_sum_u64([
            leaderboard_distributed,
            leaderboard_carry,
            staker_distributed,
            staker_carry,
            buckets.local_legend,
            buckets.pol,
            buckets.treasury,
        ])
        .unwrap(),
        u64::MAX
    );
}

#[test]
fn current_epoch_saturates_before_economy_anchor() {
    let clock = test_settlement_clock();
    assert_eq!(clock.week_at(SETTLEMENT_WEEK_V2_ANCHOR - 1).unwrap(), 0);
    assert_eq!(clock.week_at(SETTLEMENT_WEEK_V2_ANCHOR).unwrap(), 0);
    assert_eq!(
        clock
            .week_at(SETTLEMENT_WEEK_V2_ANCHOR + EPOCH_DURATION_SECONDS)
            .unwrap(),
        1
    );
}

#[test]
fn settlement_clock_v2_preserves_history_and_moves_future_weeks_to_monday() {
    let transition_week = 200;
    let cutover = SETTLEMENT_WEEK_V2_ANCHOR
        + i64::try_from(transition_week).unwrap() * EPOCH_DURATION_SECONDS;
    let clock = SettlementClock::with_legacy_cutover(cutover).unwrap();

    assert_eq!(clock.week_at(cutover - 1).unwrap(), transition_week);
    assert_eq!(clock.week_at(cutover).unwrap(), transition_week);

    let historical_week = transition_week - 1;
    assert_eq!(
        clock.week_start(historical_week).unwrap(),
        LEGACY_SETTLEMENT_WEEK_ANCHOR
            + i64::try_from(historical_week).unwrap() * EPOCH_DURATION_SECONDS
    );
    assert_eq!(
        clock.week_end(historical_week).unwrap(),
        LEGACY_SETTLEMENT_WEEK_ANCHOR
            + i64::try_from(transition_week).unwrap() * EPOCH_DURATION_SECONDS
    );

    assert_eq!(
        clock.week_start(transition_week).unwrap(),
        LEGACY_SETTLEMENT_WEEK_ANCHOR
            + i64::try_from(transition_week).unwrap() * EPOCH_DURATION_SECONDS
    );
    assert_eq!(
        clock.week_end(transition_week).unwrap(),
        cutover + EPOCH_DURATION_SECONDS
    );
    assert_eq!(
        clock.week_end(transition_week).unwrap() - clock.week_start(transition_week).unwrap(),
        EPOCH_DURATION_SECONDS + SETTLEMENT_CLOCK_PHASE_SHIFT_SECONDS
    );

    let first_full_v2_week = transition_week + 1;
    assert_eq!(
        clock.week_start(first_full_v2_week).unwrap(),
        cutover + EPOCH_DURATION_SECONDS
    );
    assert_eq!(
        clock.week_end(first_full_v2_week).unwrap()
            - clock.week_start(first_full_v2_week).unwrap(),
        EPOCH_DURATION_SECONDS
    );

    let sunday_noon = clock.week_start(first_full_v2_week).unwrap() + 6 * 86_400;
    assert_eq!(clock.week_at(sunday_noon).unwrap(), first_full_v2_week);
}

#[test]
fn settlement_clock_v2_cutover_must_be_week_aligned() {
    let cutover = SETTLEMENT_WEEK_V2_ANCHOR + 200 * EPOCH_DURATION_SECONDS;

    assert!(SettlementClock::with_legacy_cutover(cutover).is_ok());
    assert!(SettlementClock::with_legacy_cutover(cutover + 1).is_err());
    assert!(SettlementClock::with_legacy_cutover(SETTLEMENT_WEEK_V2_ANCHOR - 1).is_err());
}

#[test]
fn fresh_settlement_clock_uses_monday_anchor_without_a_bridge() {
    let clock = SettlementClock::v2_only();

    assert_eq!(clock.week_at(SETTLEMENT_WEEK_V2_ANCHOR - 1).unwrap(), 0);
    assert_eq!(clock.week_at(SETTLEMENT_WEEK_V2_ANCHOR).unwrap(), 0);
    assert_eq!(clock.week_start(0).unwrap(), SETTLEMENT_WEEK_V2_ANCHOR);
    assert_eq!(
        clock.week_end(0).unwrap() - clock.week_start(0).unwrap(),
        EPOCH_DURATION_SECONDS
    );
}

#[test]
fn latest_finalizable_week_respects_the_monday_grace_boundary() {
    let clock = SettlementClock::v2_only();
    let current_week = 10;
    let handoff = clock.week_start(current_week).unwrap();

    assert_eq!(clock.latest_finalizable_week(handoff).unwrap(), 8);
    assert_eq!(
        clock
            .latest_finalizable_week(handoff + SETTLEMENT_FINALIZATION_GRACE_SECONDS - 1,)
            .unwrap(),
        8
    );
    assert_eq!(
        clock
            .latest_finalizable_week(handoff + SETTLEMENT_FINALIZATION_GRACE_SECONDS)
            .unwrap(),
        9
    );
}

#[test]
fn ride_timestamp_guard_rejects_future_stale_and_impossible_durations() {
    let now = EPOCH_ANCHOR + (40 * 24 * 60 * 60);
    let valid_completed = now - 60;
    let valid_started = valid_completed - 3_600;
    assert!(require_valid_ride_timestamps(valid_started, valid_completed, now).is_ok());

    let oldest_accepted_completed = now - MAX_RIDE_AGE_SECONDS;
    assert!(require_valid_ride_timestamps(
        oldest_accepted_completed - 3_600,
        oldest_accepted_completed,
        now,
    )
    .is_ok());

    assert!(require_valid_ride_timestamps(
        valid_started,
        now + MAX_RIDE_CLOCK_SKEW_SECONDS + 1,
        now
    )
    .is_err());
    assert!(require_valid_ride_timestamps(
        now - MAX_RIDE_AGE_SECONDS - 3_600,
        now - MAX_RIDE_AGE_SECONDS - 1,
        now
    )
    .is_err());
    assert!(require_valid_ride_timestamps(valid_completed, valid_started, now).is_err());
    assert!(require_valid_ride_timestamps(
        valid_completed - MAX_RIDE_DURATION_SECONDS - 1,
        valid_completed,
        now
    )
    .is_err());
}
