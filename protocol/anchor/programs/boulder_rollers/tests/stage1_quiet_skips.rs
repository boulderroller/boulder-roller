use anchor_lang::AccountDeserialize;
use boulder_rollers::{stage1_claims::*, stage1_sponsor::*};

fn blank<T: AccountDeserialize>() -> T {
    T::try_deserialize_unchecked(&mut &[0u8; 4096][..]).unwrap()
}

#[test]
fn boost_minimum_is_checked_for_every_hamilton_slot() {
    assert!(schedule(5_999_999, 2, 3, 0).is_err());
    assert!(schedule(5_999_999, 2, 3, 1).is_err());
    assert_eq!(
        schedule(6_000_005, 2, 3, 1).unwrap()[..3],
        [1_000_001, 1_000_001, 1_000_000]
    );
}

#[test]
fn ordinary_and_cash_holds_allow_quiet_skips_but_keep_original_maturity() {
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 100;
    cursor.finish_week(100, 90).unwrap();
    cursor.pending_current_holds = 70;
    cursor.finish_week(101, 0).unwrap();
    cursor.skip_end(117).unwrap();
    cursor.skip_end(125).unwrap();
    assert!(cursor.skip_end(126).is_err());
    assert!(cursor.finish_week(126, 0).is_err());
    cursor.transition_hold(100, 90, 0).unwrap();
    cursor.finish_week(126, 0).unwrap();
    assert!(cursor.skip_end(127).is_err());
    assert!(cursor.finish_week(127, 0).is_err());
    cursor.transition_cash_hold(101, 70, 0).unwrap();
    cursor.finish_week(127, 0).unwrap();
    cursor.skip_end(140).unwrap();
    assert!(cursor
        .holds
        .iter()
        .chain(&cursor.cash_holds)
        .all(|n| *n == 0));
}

fn post(
    cursor: &mut Stage1SettlementCursor,
    ledger: &mut Stage1Ledger,
    streams: &mut Vec<Stage1BoostHill>,
    start: u64,
    weeks: u8,
) {
    let mut stream: Stage1BoostHill = blank();
    stream.sequence = cursor.cash_sequence;
    stream.start_week = start;
    stream.weeks = weeks;
    let total = weeks as u64 * S1_BOOST_MIN_TRANCHE;
    stream.scheduled = schedule(total, 1, weeks, 0).unwrap();
    for j in 0..13 {
        stream.holds[j][0] = stream.scheduled[j];
    }
    cursor.cash_sequence += 1;
    cursor.active_cash_streams += 1;
    cursor.future_cash += total;
    cursor.admit_boost_due(start).unwrap();
    ledger.admit_cash(total).unwrap();
    ledger.check(0, 0).unwrap();
    streams.push(stream);
}

fn audit(cursor: &Stage1SettlementCursor, ledger: &Stage1Ledger, streams: &[Stage1BoostHill]) {
    let mut due = u64::MAX;
    let mut future = 0;
    let mut ring = [0; 26];
    for stream in streams {
        for j in 0..stream.weeks as usize {
            let born = stream.start_week + j as u64;
            let amount = bucket_sum(&stream.holds[j]).unwrap();
            if amount == 0 {
                continue;
            }
            if born >= cursor.next_week {
                due = due.min(born);
                future += amount;
            } else {
                assert!(cursor.next_week <= born + 26, "no stranded hold");
                ring[(born % 26) as usize] += amount;
            }
        }
    }
    assert_eq!(
        cursor.next_boost_due_week,
        if due == u64::MAX { 0 } else { due }
    );
    assert_eq!(cursor.future_cash, future);
    assert_eq!(cursor.cash_holds, ring);
    assert_eq!(
        cursor.active_cash_streams,
        streams.iter().filter(|s| !s.retired).count() as u64
    );
    ledger.check(0, 0).unwrap();
}

#[test]
fn next_due_survives_partial_processing_retirement_and_post_freeze_posts() {
    let mut cursor: Stage1SettlementCursor = blank();
    let mut ledger = Stage1Ledger::default();
    let mut streams = Vec::new();
    post(&mut cursor, &mut ledger, &mut streams, 1, 1);
    post(&mut cursor, &mut ledger, &mut streams, 1, 2);
    post(&mut cursor, &mut ledger, &mut streams, 13, 1);
    // City week 1000, but settlement still starts at 0: no bounded due ring.
    post(&mut cursor, &mut ledger, &mut streams, 1001, 1);
    cursor.skip_end(0).unwrap();
    let mut book: Stage1WeekFunding = blank();
    book.week = 1;
    book.snapshot = [1; 32];
    book.cash_sequence = cursor.cash_sequence;
    book.cash_expected = cursor.active_cash_streams;
    streams[0]
        .process(&mut book, &mut cursor, &mut ledger, [[0; 5]; 13])
        .unwrap();
    assert!(streams[0].retired);
    assert!(cursor.skip_end(1).is_err());
    // A post after the earliest stream retires is excluded from this frozen
    // count, but must survive promotion of the next due week.
    post(&mut cursor, &mut ledger, &mut streams, 1002, 1);
    for stream in streams.iter_mut().take(4).skip(1) {
        let holds = stream.holds;
        stream
            .process(&mut book, &mut cursor, &mut ledger, holds)
            .unwrap();
    }
    assert_eq!(book.cash_processed, book.cash_expected);
    cursor.finish_week(1, 0).unwrap();
    ledger.publish(book.boost_released).unwrap();
    audit(&cursor, &ledger, &streams);
    assert_eq!(cursor.next_boost_due_week, 2);
    assert!(cursor.skip_end(2).is_err());
}

#[test]
fn randomized_due_tracking_matches_full_schedules_and_original_age_after_every_step() {
    for seed in 1u64..=64 {
        let mut rng = seed;
        let mut roll = || {
            rng = rng.wrapping_mul(6364136223846793005).wrapping_add(1);
            rng
        };
        let mut cursor: Stage1SettlementCursor = blank();
        let mut ledger = Stage1Ledger::default();
        let mut streams = Vec::new();
        let mut wall = 0;
        for _ in 0..128 {
            wall = wall.max(cursor.next_week);
            if roll() % 8 == 0 {
                wall += roll() % 1000;
            }
            if roll() % 3 == 0 {
                post(
                    &mut cursor,
                    &mut ledger,
                    &mut streams,
                    wall + 1 + roll() % 13,
                    (1 + roll() % 13) as u8,
                );
            }
            let mut boundary = u64::MAX;
            for stream in &streams {
                for j in 0..stream.weeks as usize {
                    if bucket_sum(&stream.holds[j]).unwrap() == 0 {
                        continue;
                    }
                    let born = stream.start_week + j as u64;
                    boundary = boundary.min(if born >= cursor.next_week {
                        born
                    } else {
                        born + 26
                    });
                }
            }
            if boundary > cursor.next_week && roll() % 2 == 0 {
                let through = (cursor.next_week + 15).min(boundary - 1);
                let before = ledger.clone();
                cursor.skip_end(through).unwrap();
                assert_eq!(ledger, before);
            } else {
                let mut book: Stage1WeekFunding = blank();
                book.week = cursor.next_week;
                book.snapshot = [1; 32];
                book.cash_sequence = cursor.cash_sequence;
                book.cash_expected = cursor.active_cash_streams;
                let frozen_len = streams.len();
                for i in 0..frozen_len {
                    if !streams[i].retired {
                        let mut remaining = streams[i].holds;
                        for (j, row) in remaining.iter_mut().enumerate() {
                            if book.week >= streams[i].start_week + j as u64 + 26 {
                                *row = [0; 5];
                            }
                        }
                        streams[i]
                            .process(&mut book, &mut cursor, &mut ledger, remaining)
                            .unwrap();
                        ledger.check(0, 0).unwrap();
                    }
                    if i == frozen_len / 2 && roll() % 2 == 0 {
                        post(
                            &mut cursor,
                            &mut ledger,
                            &mut streams,
                            wall + 1 + roll() % 13,
                            (1 + roll() % 13) as u8,
                        );
                    }
                }
                if roll() % 2 == 0 {
                    post(
                        &mut cursor,
                        &mut ledger,
                        &mut streams,
                        wall + 1 + roll() % 13,
                        (1 + roll() % 13) as u8,
                    );
                }
                assert_eq!(book.cash_processed, book.cash_expected);
                cursor.finish_week(book.week, 0).unwrap();
                ledger.publish(book.boost_released).unwrap();
            }
            audit(&cursor, &ledger, &streams);
        }
    }
}
