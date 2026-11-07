//! Account type boundaries used by every legacy helper in default and devnet.
use anchor_lang::{AccountDeserialize, Discriminator};
use ::boulder_rollers::*;

fn rejects_legacy<T: Discriminator>() {
    let mut bytes = vec![0u8; 8192];
    bytes[..8].copy_from_slice(&T::discriminator());
    assert!(Vault::try_deserialize(&mut bytes.as_slice()).is_err());
    assert!(VaultStake::try_deserialize(&mut bytes.as_slice()).is_err());
    assert!(VaultActivation::try_deserialize(&mut bytes.as_slice()).is_err());
    assert!(VaultLeaderboard::try_deserialize(&mut bytes.as_slice()).is_err());
    assert!(ProgramConfig::try_deserialize(&mut bytes.as_slice()).is_err());
}

#[test]
fn every_stage1_account_is_outside_legacy_helper_and_clock_types() {
    rejects_legacy::<Stage1CityConfig>();
    rejects_legacy::<Stage1AssetConfig>();
    rejects_legacy::<Stage1HillBond>();
    rejects_legacy::<Stage1PledgeLot>();
    rejects_legacy::<Stage1WithdrawalRequest>();
    rejects_legacy::<Stage1WeekFunding>();
    rejects_legacy::<Stage1Recipient>();
    rejects_legacy::<Stage1ClaimSet>();
    rejects_legacy::<Stage1SettlementCursor>();
    rejects_legacy::<Stage1CashConfig>();
    rejects_legacy::<Stage1Boost>();
    rejects_legacy::<Stage1BoostHill>();
    rejects_legacy::<Stage1DungState>();
    rejects_legacy::<Stage1DungMint>();
    rejects_legacy::<Stage1DungClaimSet>();
    #[cfg(feature = "stage1-devnet")]
    rejects_legacy::<Stage1TestPool>();
}

#[test]
fn historical_city_layouts_preserve_roles_pauses_and_dung_policy() {
    for size in [881, 897, 914, 915, 931, 963] {
        let mut before = vec![0u8; size];
        before[..8].copy_from_slice(&Stage1CityConfig::discriminator());
        before[9..17].copy_from_slice(&10_000_000_000u64.to_le_bytes());
        if [897, 931, 963].contains(&size) {
            before[881..889].copy_from_slice(&123_000u64.to_le_bytes());
            before[889..897].copy_from_slice(&9u64.to_le_bytes());
        }
        let offset = if [914, 915].contains(&size) { 881 } else { 897 };
        if size >= 914 {
            before[offset..offset + 32].fill(42);
            before[offset + 32] = 1;
            if size != 914 { before[offset + 33] = 1; }
        }
        if size == 963 { before[931..963].fill(43); }
        let after = migrate_city_bytes(&before).unwrap();
        assert_eq!(&before[..881], &after[..881]);
        assert_eq!(migrate_city_bytes(&after).unwrap(), after);
        let city = Stage1CityConfig::try_deserialize(&mut after.as_slice()).unwrap();
        assert_eq!(city.dung_start_week_plus_one, if [897, 931, 963].contains(&size) { 9 } else { 0 });
        assert_eq!(city.dung_tss_ceiling_micros, if [897, 931, 963].contains(&size) { 123_000 } else { 0 });
        assert_eq!(city.intake_paused, size >= 914);
        assert_eq!(city.settlement_paused, size >= 915);
        assert_eq!(city.guardian.to_bytes(), [if size >= 914 { 42 } else { 0 }; 32]);
        assert_eq!(city.registrar.to_bytes(), [if size == 963 { 43 } else { 0 }; 32]);
    }
}

#[test]
fn city_migration_rejects_unknown_lengths_discriminators_and_boolean_bytes() {
    for size in [0, 880, 882, 896, 898, 913, 916, 930, 932, 962, 964] {
        assert!(migrate_city_bytes(&vec![0u8; size]).is_err());
    }
    let mut data = vec![0u8; 915];
    assert!(migrate_city_bytes(&data).is_err());
    data[..8].copy_from_slice(&Stage1CityConfig::discriminator());
    data[914] = 2;
    assert!(migrate_city_bytes(&data).is_err());
}
