use anchor_lang::{prelude::Pubkey, AccountDeserialize};
use boulder_rollers::stage1_claims::*;
use boulder_rollers::stage1_sponsor::*;

fn blank<T: AccountDeserialize>() -> T {
    T::try_deserialize_unchecked(&mut &[0u8; 4096][..]).unwrap()
}

#[test]
fn cash_is_received_once_without_yield_fees_or_owner_inventory() {
    let mut cash = Stage1Ledger::default();
    cash.admit_cash(101).unwrap();
    cash.check(0, 0).unwrap();
    assert_eq!(cash.admitted_cash_lifetime, 101);
    assert_eq!(cash.deposited, 0);
    assert_eq!(cash.owner_custody, 0);
    cash.publish(65).unwrap();
    cash.claim(65).unwrap();
    cash.check(0, 0).unwrap();
    assert_eq!(cash.held, 36);
}

#[test]
fn schedule_hamilton_ties_use_hill_text_then_week() {
    let hills = vec![
        Pubkey::new_from_array([1; 32]),
        Pubkey::new_from_array([16; 32]),
    ];
    let sorted = sorted_hills(hills).unwrap();
    assert!(sorted[0].to_string() < sorted[1].to_string());
    assert!(
        sorted[0] > sorted[1],
        "text order deliberately differs from binary order"
    );
    assert_eq!(
        schedule(6_000_005, 2, 3, 0).unwrap(),
        [1_000_001, 1_000_001, 1_000_001, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    );
    assert_eq!(
        schedule(6_000_005, 2, 3, 1).unwrap(),
        [1_000_001, 1_000_001, 1_000_000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    );
    assert!(sorted_hills(vec![sorted[0], sorted[0]]).is_err());
    assert!(sorted_hills((1..=16).map(|i| Pubkey::new_from_array([i; 32])).collect()).is_ok());
    assert!(sorted_hills((1..=17).map(|i| Pubkey::new_from_array([i; 32])).collect()).is_err());
    assert_eq!(
        S1_MAINNET_USDC.to_string(),
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    );
}

#[test]
fn future_streams_allow_skips_strictly_before_their_due_week() {
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.active_cash_streams = 1;
    cursor.future_cash = 10;
    cursor.admit_boost_due(13).unwrap();
    assert!(cursor.skip_end(13).is_err());
    cursor.skip_end(12).unwrap();
    assert!(cursor.skip_end(13).is_err());
    assert_eq!(cursor.holds, [0; 26]);
}

fn buckets(value: &serde_json::Value) -> [u64; 5] {
    std::array::from_fn(|i| value[i].as_u64().unwrap())
}

#[test]
fn independent_sponsor_oracle_matches_production_stream_transitions_and_claims() {
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/stage1_sponsor_vectors.json"
    ))
    .unwrap();
    for (name, case) in fixture["cases"].as_object().unwrap() {
        let mut ledger = Stage1Ledger::default();
        let mut cursor: Stage1SettlementCursor = blank();
        let cash = case["cash"].as_bool().unwrap();
        let start = case["start"].as_u64().unwrap();
        let weeks = case["duration"].as_u64().unwrap() as u8;
        let amounts: Vec<u64> = case["amounts"]
            .as_array()
            .unwrap()
            .iter()
            .map(|a| a.as_u64().unwrap())
            .collect();
        let mut streams: Vec<Stage1BoostHill> = Vec::new();
        for (i, amount) in amounts.iter().enumerate() {
            ledger.admit_cash(*amount).unwrap();
            ledger.check(0, 0).unwrap();
            if !cash {
                let mut stream: Stage1BoostHill = blank();
                stream.sequence = i as u64;
                stream.start_week = start;
                stream.weeks = weeks;
                stream.scheduled = schedule(*amount, 1, weeks, 0).unwrap();
                for j in 0..13 {
                    stream.holds[j][0] = stream.scheduled[j];
                }
                cursor.cash_sequence += 1;
                cursor.active_cash_streams += 1;
                cursor.future_cash += amount;
                cursor.admit_boost_due(start).unwrap();
                streams.push(stream);
            }
        }
        for step in case["steps"].as_array().unwrap() {
            let w = step["week"].as_u64().unwrap();
            if step["skip"].as_bool() == Some(true) {
                let before = ledger.clone();
                if let Some(refused) = step["refused"].as_u64() { assert!(cursor.skip_end(refused).is_err()); }
                cursor.skip_end(w).unwrap();
                assert_eq!(ledger, before);
                ledger.check(0, 0).unwrap();
                continue;
            }
            let mut book: Stage1WeekFunding = blank();
            book.week = w;
            book.due_week = w;
            book.snapshot = [1; 32];
            book.cash_sequence = cursor.cash_sequence;
            book.cash_expected = cursor.active_cash_streams;
            for (i, stream) in streams.iter_mut().enumerate() {
                if stream.retired {
                    continue;
                }
                let remaining = std::array::from_fn(|j| buckets(&step["streams"][i][j]));
                stream
                    .process(&mut book, &mut cursor, &mut ledger, remaining)
                    .unwrap();
                ledger.check(0, 0).unwrap();
                assert_eq!(
                    stream.pool,
                    step["pools"][i].as_u64().unwrap(),
                    "{name} week {w}"
                );
                assert!(stream
                    .process(&mut book, &mut cursor, &mut ledger, remaining)
                    .is_err());
            }
            assert_eq!(book.cash_processed, book.cash_expected);
            let value = &step["sponsor_holds"][w.to_string()]["buckets"];
            let held = if cash && !value.is_null() {
                bucket_sum(&buckets(value)).unwrap()
            } else {
                0
            };
            let total = step["total"].as_str().unwrap().parse::<u64>().unwrap();
            if cash {
                assert_eq!(total + held, amounts[0]);
            } else {
                assert_eq!(total, book.boost_released);
            }
            cursor.finish_week(w, held).unwrap();
            ledger.publish(total).unwrap();
            ledger.check(0, 0).unwrap();
            assert_eq!(
                ledger.held,
                step["before_claims"]["held"].as_u64().unwrap() as u128,
                "{name} week {w}"
            );
            for leaf in step["leaves"].as_array().unwrap() {
                ledger.claim(leaf["amount"].as_u64().unwrap()).unwrap();
                ledger.check(0, 0).unwrap();
            }
            assert_eq!(
                ledger.paid,
                step["after_claims"]["paid"].as_u64().unwrap() as u128
            );
        }
    }
}

#[test]
fn future_slot_collision_and_multiple_original_age_holds_never_reset_age() {
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 27;
    cursor.cash_holds[1] = 110;
    cursor.pending_current_holds = 7;
    assert!(cursor.finish_week(27, 0).is_err());
    cursor.transition_cash_hold(1, 60, 0).unwrap();
    assert_eq!(cursor.cash_holds[1], 50);
    assert!(cursor.finish_week(27, 0).is_err());
    cursor.transition_cash_hold(1, 50, 0).unwrap();
    cursor.finish_week(27, 0).unwrap();
    assert_eq!(cursor.cash_holds[1], 7);
    assert_eq!(cursor.pending_current_holds, 0);
}

#[test]
fn mixed_asset_fuzz_keeps_cash_and_yield_equalities_separate_after_every_transition() {
    for seed in 1u64..=128 {
        let mut state = seed;
        let mut cash = Stage1Ledger::default();
        let mut lst = Stage1Ledger::default();
        let (mut realized, mut fees) = (0u128, 0u128);
        for _ in 0..256 {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            let amount = 1 + state % 10000;
            match state % 6 {
                0 => {
                    cash.admit_cash(amount).unwrap();
                }
                1 => {
                    lst.deposit(amount).unwrap();
                }
                2 => {
                    let n = amount.min(lst.owner_custody as u64);
                    let fee = ((realized + n as u128) / 10 - realized / 10) as u64;
                    lst.harvest(n, fee).unwrap();
                    realized += n as u128;
                    fees += fee as u128;
                }
                3 => {
                    cash.publish(amount.min((cash.held - cash.pool) as u64))
                        .unwrap();
                    lst.publish(amount.min((lst.held - lst.pool) as u64))
                        .unwrap();
                }
                4 => {
                    cash.claim(amount.min(cash.claimable as u64)).unwrap();
                    lst.claim(amount.min(lst.claimable as u64)).unwrap();
                }
                _ => {
                    let n = amount.min(lst.owner_custody as u64);
                    lst.owner_return(n, 0).unwrap();
                }
            }
            cash.check(0, 0).unwrap();
            lst.check(realized, fees).unwrap();
            assert_eq!(cash.deposited, 0);
            assert_eq!(lst.admitted_cash_lifetime, 0);
        }
    }
}
