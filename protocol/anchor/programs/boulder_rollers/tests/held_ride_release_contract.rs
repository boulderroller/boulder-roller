use boulder_rollers::{
    held_ride_release_tribute_budget, require_held_release_settlement_week,
    require_valid_held_ride_release_window, HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS,
};

const WEEK_SECONDS: i64 = 7 * 24 * 60 * 60;

#[test]
fn establishment_at_exactly_sixteen_weeks_is_eligible_but_the_next_second_lapses() {
    let admitted_at = 1_800_000_000;
    let exact_edge = admitted_at + 16 * WEEK_SECONDS;

    assert_eq!(HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS, 16 * WEEK_SECONDS);
    assert!(require_valid_held_ride_release_window(admitted_at, exact_edge, exact_edge,).is_ok());
    assert!(
        require_valid_held_ride_release_window(admitted_at, exact_edge + 1, exact_edge + 1,)
            .is_err()
    );
}

#[test]
fn released_completion_refuses_a_different_vault_flow_week() {
    assert!(require_held_release_settlement_week(118, 119).is_err());
    assert!(require_held_release_settlement_week(119, 119).is_ok());
    assert!(require_held_release_settlement_week(120, 119).is_err());
}

#[test]
fn eligible_establishment_survives_a_release_retry_after_the_window() {
    let admitted_at = 1_800_000_000;
    let established_at = admitted_at + 8 * WEEK_SECONDS;
    let retried_release_at = admitted_at + 20 * WEEK_SECONDS;

    assert!(require_valid_held_ride_release_window(
        admitted_at,
        established_at,
        retried_release_at,
    )
    .is_ok());
}

#[test]
fn already_established_threshold_accepts_a_late_upload_forward_only() {
    let admitted_at = 1_800_000_000;
    let established_at = admitted_at - WEEK_SECONDS;

    assert!(
        require_valid_held_ride_release_window(admitted_at, established_at, admitted_at,).is_ok()
    );
    assert!(
        require_valid_held_ride_release_window(admitted_at, established_at, admitted_at - 1,)
            .is_err()
    );
}

#[test]
fn release_timestamps_cannot_precede_admission_or_establishment() {
    let admitted_at = 1_800_000_000;

    assert!(require_valid_held_ride_release_window(
        admitted_at,
        admitted_at + WEEK_SECONDS,
        admitted_at + WEEK_SECONDS - 1,
    )
    .is_err());
}

#[test]
fn held_release_budget_uses_the_child_amount_and_requires_a_zero_parent() {
    let parent_attestation_cal = 0;
    let released_cal = 64_000_000_000;

    assert_eq!(
        held_ride_release_tribute_budget(parent_attestation_cal, released_cal).unwrap(),
        64_000_000_000,
    );
    assert!(held_ride_release_tribute_budget(1, released_cal).is_err());
    assert!(held_ride_release_tribute_budget(parent_attestation_cal, 0).is_err());
}

/// Native Anchor account/handler proof, not an SBF transaction test.
#[test]
fn released_budget_must_match_the_frozen_exact_child_budget() {
    use anchor_lang::prelude::*;
    use boulder_rollers::{
        HeldRideReleaseAuthority, ReleasedRideTributeBudget, RideAttestation,
        VerifyReleasedRideTributeBudget, VerifyReleasedRideTributeBudgetBumps,
        HELD_RIDE_RELEASE_SEED, ID, RIDE_ATTESTATION_SEED, RIDE_TRIBUTE_BUDGET_SEED,
    };
    use std::collections::BTreeSet;

    fn account<T: AccountSerialize>(key: Pubkey, value: &T) -> AccountInfo<'static> {
        let mut bytes = Vec::new();
        value.try_serialize(&mut bytes).unwrap();
        AccountInfo::new(
            Box::leak(Box::new(key)),
            false,
            false,
            Box::leak(Box::new(1_000_000_000)),
            Box::leak(bytes.into_boxed_slice()),
            &ID,
            false,
            0,
        )
    }

    fn verify(frozen: u64, ledger: u64, credited: u64) -> Result<()> {
        let rider = Pubkey::new_unique();
        let ride_hash = [7; 32];
        let (parent_key, parent_bump) =
            Pubkey::find_program_address(&[RIDE_ATTESTATION_SEED, rider.as_ref(), &ride_hash], &ID);
        let (child_key, child_bump) =
            Pubkey::find_program_address(&[HELD_RIDE_RELEASE_SEED, parent_key.as_ref()], &ID);
        let (budget_key, budget_bump) =
            Pubkey::find_program_address(&[RIDE_TRIBUTE_BUDGET_SEED, parent_key.as_ref()], &ID);
        let mut parent =
            RideAttestation::try_deserialize_unchecked(&mut &vec![0; RideAttestation::SIZE][..])?;
        parent.rider = rider;
        parent.ride_hash = ride_hash;
        parent.bump = parent_bump;
        let mut child = HeldRideReleaseAuthority::try_deserialize_unchecked(
            &mut &vec![0; HeldRideReleaseAuthority::SIZE][..],
        )?;
        child.ride_attestation = parent_key;
        child.rider = rider;
        child.cal_earned = 64_000_000_000;
        child.cal_tribute_budget = frozen;
        child.bump = child_bump;
        let budget = ReleasedRideTributeBudget {
            ride_attestation: parent_key,
            release_authority: child_key,
            cal_budget: ledger,
            total_cal_tributed: credited,
            bump: budget_bump,
        };
        let infos = Box::leak(Box::new([
            account(parent_key, &parent),
            account(child_key, &child),
            account(budget_key, &budget),
        ]));
        let mut remaining = &infos[..];
        let mut bumps = VerifyReleasedRideTributeBudgetBumps::default();
        let mut accounts = VerifyReleasedRideTributeBudget::try_accounts(
            &ID,
            &mut remaining,
            &[],
            &mut bumps,
            &mut BTreeSet::new(),
        )?;
        boulder_rollers::boulder_rollers::verify_released_ride_tribute_budget(Context::new(
            &ID,
            &mut accounts,
            &[],
            bumps,
        ))
    }

    let frozen_exact = 6_400_000_123;
    assert!(verify(frozen_exact, frozen_exact, frozen_exact).is_ok());
    assert!(verify(frozen_exact, frozen_exact, frozen_exact + 1).is_err());
    assert!(verify(frozen_exact, frozen_exact + 1, frozen_exact).is_err());
    assert!(verify(64_000_000_001, 64_000_000_001, 0).is_err());
}
