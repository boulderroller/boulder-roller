use anchor_lang::AccountDeserialize;
use boulder_rollers::stage1_dung::*;
use boulder_rollers::{Stage1CityConfig, Stage1HillBond};

fn blank<T: AccountDeserialize>() -> T {
    T::try_deserialize_unchecked(&mut &[0u8; 8192][..]).unwrap()
}

#[test]
fn prospective_start_ceiling_and_admin_policy_changes() {
    let mut city: Stage1CityConfig = blank();
    city.season_anchor = 1_791_201_600;
    let now = city.season_anchor + 100;
    configure_policy(&mut city, 0, None, now).unwrap();
    assert_eq!(city.dung_tss_ceiling_micros, 0);
    assert!(next_publication_week(&city, 0).is_err());
    assert!(check_publication(&city, 1, 1, 1).is_err());
    assert!(next_publication_week(&city, 1).is_err());
    assert!(configure_policy(&mut city, S1_DUNG_TSS_CEILING, Some(0), now).is_err());
    configure_policy(&mut city, S1_DUNG_TSS_CEILING, Some(3), now).unwrap();
    assert_eq!(next_publication_week(&city, 1).unwrap(), 3);
    assert!(check_publication(&city, 1, 2, 1).is_err());
    for tss in [S1_DUNG_TSS_CEILING - 1, S1_DUNG_TSS_CEILING] {
        check_publication(&city, 1, 3, tss).unwrap();
    }
    for tss in [S1_DUNG_TSS_CEILING + 1, u64::MAX] {
        assert!(check_publication(&city, 1, 3, tss).is_err());
    }
    // A cap-only update preserves an already active start; changed starts
    // must be prospective, including re-enabling after disablement.
    let later = now + 4 * 604800;
    configure_policy(&mut city, S1_DUNG_TSS_CEILING + 1, Some(3), later).unwrap();
    check_publication(&city, 3, 3, S1_DUNG_TSS_CEILING + 1).unwrap();
    assert!(configure_policy(&mut city, 1, Some(2), later).is_err());
    configure_policy(&mut city, 1, None, later).unwrap();
    assert!(configure_policy(&mut city, 1, Some(3), later).is_err());
    configure_policy(&mut city, 1, Some(5), later).unwrap();
    assert_eq!(next_publication_week(&city, 9).unwrap(), 9);
    assert!(configure_policy(&mut city, 1, Some(u64::MAX), later).is_err());
    assert!(configure_policy(&mut city, 0, Some(5), later).is_err());
}

#[test]
fn claim_wait_is_exact_and_checked() {
    let publication = 1_791_201_600;
    assert!(check_claim_time(publication, publication + 172799).is_err());
    check_claim_time(publication, publication + 172800).unwrap();
    assert!(check_claim_time(publication + 1, publication + 172800).is_err());
    assert!(check_claim_time(i64::MAX, i64::MAX).is_err());
}

#[test]
fn opening_weights_obey_hill_bonus_lock_expiry_and_basis_bounds() {
    let mut city: Stage1CityConfig = blank();
    city.season_anchor = 1_791_201_600;
    let mut hill: Stage1HillBond = blank();
    hill.bonded = true;
    hill.bonded_at = city.season_anchor + 100;
    hill.founding_count = 1;
    hill.campaign_count = 1;
    hill.dung_deposited_basis = 200;
    hill.dung_founding_basis = 100;
    hill.dung_lock_ends[1] = hill.bonded_at + 26 * 604800;
    let mut opening = Stage1DungOpening {
        basis: [0; 8],
        backing: [0; 8],
    };
    opening.basis[2] = 100;
    opening.basis[6] = 100;
    opening.backing = opening.basis;
    assert_eq!(backer_weight(&city, &hill, 26, &opening).unwrap(), 900);
    assert!(backer_weight(&city, &hill, 27, &opening).is_err());
    opening.basis = [100, 0, 0, 0, 100, 0, 0, 0];
    opening.backing = opening.basis;
    assert_eq!(backer_weight(&city, &hill, 27, &opening).unwrap(), 200);
    opening.backing[0] = 101;
    assert!(backer_weight(&city, &hill, 27, &opening).is_err());
}

#[test]
fn constant_dung_preserves_missing_shares_and_hamilton_dust() {
    assert_eq!(
        allocation(1, 1, 1, true, 1).unwrap(),
        Stage1DungAllocation {
            potential: 1,
            riders: 0,
            backers: 1,
            unminted: 0,
        }
    );
    assert_eq!(
        allocation(1_000_000, 1, 5, false, 1).unwrap(),
        Stage1DungAllocation {
            potential: 1_000_000,
            riders: 450_000,
            backers: 500_000,
            unminted: 50_000,
        }
    );
}

#[test]
fn excluded_conversions_keep_unknown_ordinary_expiry_attested() {
    let mut city: Stage1CityConfig = blank();
    city.season_anchor = 1_791_201_600;
    let mut hill: Stage1HillBond = blank();
    hill.bonded = true;
    hill.bonded_at = city.season_anchor + 100;
    hill.founding_count = 1;
    hill.campaign_count = 2;
    hill.dung_deposited_basis = 200;
    hill.dung_founding_basis = 100;
    let opening = Stage1DungOpening {
        basis: [0, 0, 0, 100, 0, 0, 0, 0],
        backing: [0, 0, 0, 100, 0, 0, 0, 0],
    };
    assert_eq!(backer_weight(&city, &hill, 80, &opening).unwrap(), 400);
    hill.campaign_count = 1;
    assert!(backer_weight(&city, &hill, 80, &opening).is_err());
}

#[test]
fn independent_model_weights_allocations_and_role_proofs() {
    use anchor_lang::prelude::Pubkey;
    use boulder_rollers::stage1_claims::Stage1SumNode;
    use std::str::FromStr;
    let fixtures: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/stage1_dung_vectors.json"
    ))
    .unwrap();
    let pk = |v: &serde_json::Value| Pubkey::from_str(v.as_str().unwrap()).unwrap();
    let bytes = |v: &serde_json::Value| -> [u8; 32] {
        let s = v.as_str().unwrap();
        std::array::from_fn(|i| u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).unwrap())
    };
    let mut leaves = 0;
    for (name, v) in fixtures["cases"].as_object().unwrap() {
        let mut city: Stage1CityConfig = blank();
        city.season_anchor = 1_791_201_600;
        let mut hill: Stage1HillBond = blank();
        hill.bonded = true;
        hill.bonded_at = v["bonded_at"].as_i64().unwrap();
        hill.founding_count = 1;
        hill.campaign_count = 1;
        hill.dung_deposited_basis = 20_000_000_000;
        hill.dung_founding_basis = 10_000_000_000;
        hill.dung_lock_ends = [
            hill.bonded_at + 13 * 604800,
            hill.bonded_at + 26 * 604800,
            0,
        ];
        let week = v["week"].as_u64().unwrap();
        let input = &v["input"];
        let opening = Stage1DungOpening {
            basis: std::array::from_fn(|i| input["opening"]["basis"][i].as_u64().unwrap()),
            backing: std::array::from_fn(|i| input["opening"]["backing"][i].as_u64().unwrap()),
        };
        if week == 0 {
            assert!(backer_weight(&city, &hill, week, &opening).is_err());
            continue;
        }
        let weight = backer_weight(&city, &hill, week, &opening).unwrap();
        assert_eq!(
            weight.to_string(),
            v["opening_weight_quarters"].as_str().unwrap(),
            "{name}"
        );
        if !v["admitted"].as_bool().unwrap() {
            continue;
        }
        let ceiling = allocation(
            input["postbond_tss_micros"].as_u64().unwrap(),
            input["top_count"].as_u64().unwrap() as u8,
            input["ascent_count"].as_u64().unwrap() as u32,
            input["earned_legend"].as_bool().unwrap(),
            weight,
        )
        .unwrap();
        let a = registered_allocation(ceiling, std::array::from_fn(|i| input["payable_role_totals"][i].as_u64().unwrap())).unwrap();
        for (key, n) in [
            ("potential", a.potential),
            ("riders", a.riders),
            ("backers", a.backers),
            ("unminted", a.unminted),
        ] {
            assert_eq!(n, v["allocation"][key].as_u64().unwrap(), "{name}/{key}");
        }
        let mut dung: Stage1DungMint = blank();
        let context = &v["context"];
        dung.city = pk(&context[1]);
        dung.hill = pk(&context[2]);
        dung.mint = pk(&context[4]);
        dung.week = week;
        for (role, root) in v["roots"].as_array().unwrap().iter().enumerate() {
            let mut set: Stage1DungClaimSet = blank();
            set.role = role as u8;
            set.root = bytes(&root["root"]);
            set.total = root["total"].as_str().unwrap().parse().unwrap();
            set.leaf_count = root["leaf_count"].as_u64().unwrap() as u32;
            for leaf in root["leaves"].as_array().unwrap() {
                let proof: Vec<_> = leaf["proof"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|n| Stage1SumNode {
                        hash: bytes(&n["hash"]),
                        sum: n["sum"].as_str().unwrap().parse().unwrap(),
                    })
                    .collect();
                let index = leaf["index"].as_u64().unwrap() as u32;
                let person = pk(&leaf["person"]);
                let recipient = pk(&leaf["recipient"]);
                let amount = leaf["amount"].as_u64().unwrap();
                verify_dung_proof(
                    &dung,
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    recipient,
                    amount,
                    &proof,
                )
                .unwrap();
                assert!(verify_dung_proof(
                    &dung,
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    recipient,
                    amount + 1,
                    &proof
                )
                .is_err());
                set.role ^= 1;
                assert!(verify_dung_proof(
                    &dung,
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    recipient,
                    amount,
                    &proof
                )
                .is_err());
                set.role ^= 1;
                leaves += 1;
            }
        }
    }
    assert!(leaves > 60);
}

#[test]
fn fuzzed_mint_progress_never_exceeds_allocations() {
    let mut seed = 0x5eed_cafe_u64;
    let mut lifetime = 0u128;
    let mut reserved = 0u128;
    for _ in 0..32768 {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        let ceiling = allocation(
            seed,
            (seed % 11) as u8,
            (seed % 6) as u32,
            seed & 1 != 0,
            if seed & 2 != 0 { 1 } else { 0 },
        )
        .unwrap();
        let totals = [ceiling.riders / 2, ceiling.backers / 3];
        let a = registered_allocation(ceiling, totals).unwrap();
        assert_eq!(
            a.riders as u128 + a.backers as u128 + a.unminted as u128,
            a.potential as u128
        );
        for total in [a.riders, a.backers] {
            reserved += total as u128;
            let mut paid = 0;
            let mut count = 0;
            for _ in 0..8 {
                let amount = (total - paid) / 2;
                if amount > 0 {
                    (paid, count) = claim_progress(paid, count, total, 9, amount).unwrap();
                    lifetime += amount as u128;
                }
            }
            let rest = total - paid;
            if rest > 0 {
                (paid, count) = claim_progress(paid, count, total, 9, rest).unwrap();
                lifetime += rest as u128;
            }
            assert!(claim_progress(paid, count, total, 9, 1).is_err());
            assert!(lifetime <= reserved);
        }
    }
    assert_eq!(lifetime, reserved);
    assert!(claim_progress(u64::MAX, 1, u64::MAX, 2, 1).is_err());
}

#[test]
fn registered_totals_cannot_move_shares_between_roles() {
    let ceiling = || allocation(5_000_000, 3, 5, true, 1).unwrap();
    let a = registered_allocation(ceiling(), [2_325_000, 2_500_000]).unwrap();
    assert_eq!(a.unminted, 175_000);
    assert!(registered_allocation(ceiling(), [2_500_001, 0]).is_err());
    assert!(registered_allocation(ceiling(), [0, 2_500_001]).is_err());
    assert_eq!(registered_allocation(ceiling(), [0, 0]).unwrap().unminted, 5_000_000);
}
