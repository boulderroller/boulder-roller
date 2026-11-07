use boulder_rollers::stage1_claims::Stage1Ledger;

#[test]
fn harvested_yield_is_funded_before_any_claim_root() {
    let mut ledger = Stage1Ledger::default();
    ledger.deposit(100).unwrap();
    ledger.harvest(20, 2).unwrap();
    ledger.check(20, 2).unwrap();
    assert_eq!(ledger.held, 18);
    assert_eq!(ledger.claimable, 0);
    assert_eq!(ledger.earnings, 20);
    ledger.publish(13).unwrap();
    ledger.check(20, 2).unwrap();
    assert_eq!(ledger.held, 5);
    ledger.claim(13).unwrap();
    ledger.check(20, 2).unwrap();
    assert_eq!(ledger.paid, 13);
    assert_eq!(ledger.earnings, 7);
}

use anchor_lang::{prelude::Pubkey, AccountDeserialize};
use boulder_rollers::stage1_claims::*;
use std::str::FromStr;
fn blank<T: AccountDeserialize>() -> T {
    T::try_deserialize_unchecked(&mut &[0u8; 4096][..]).unwrap()
}

#[test]
fn sparse_cursor_starts_at_admission_and_preserves_an_active_hold() {
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 100;
    assert!(cursor.skip_end(99).is_err());
    assert!(cursor.skip_end(116).is_err());
    cursor.skip_end(102).unwrap();
    assert_eq!(cursor.next_week, 103);
    assert!(cursor.finish_week(104, 0).is_err());
    cursor.finish_week(103, 90).unwrap();
    cursor.skip_end(105).unwrap();
    assert_eq!(cursor.holds[103 % 26], 90);
    cursor.transition_hold(103, 90, 0).unwrap();
    cursor.skip_end(109).unwrap();
    assert_eq!(cursor.next_week, 110);
}

#[test]
fn sparse_cursor_requires_exact_original_maturity_but_no_empty_maturity_book() {
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 100;
    cursor.finish_week(100, 90).unwrap();
    for week in 101..126 {
        cursor.finish_week(week, 0).unwrap();
    }
    assert!(cursor.finish_week(126, 0).is_err());
    assert!(cursor.skip_end(126).is_err());
    assert!(cursor.transition_hold(100, 89, 0).is_err());
    cursor.transition_hold(100, 90, 0).unwrap();
    cursor.finish_week(126, 0).unwrap();
    cursor.skip_end(140).unwrap();
    cursor.finish_week(141, 0).unwrap();
}

#[test]
fn carried_holds_fit_all_26_original_ages_and_preserve_every_proposal() {
    use anchor_lang::{AccountSerialize, Space};
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 100;
    let ledger = Stage1Ledger::default();
    for week in 100..126 {
        let mut book: Stage1WeekFunding = blank();
        book.week = week;
        book.holds = [10, 20, 30, 40, 50];
        book.lineage = [week as u8; 32];
        book.revision = 7;
        book.proposed = true;
        book.proposal_week = week + 1;
        book.proposal_snapshot = [42; 32];
        book.proposal_revision = 7;
        book.proposal_remaining = [0, 20, 30, 40, 50];
        cursor.finish_week(week, 150).unwrap();
        cursor.carry_closed_holds(Pubkey::new_unique(), &book).unwrap();
        let carried = cursor.carried_holds.last().unwrap();
        assert_eq!(carried.week, week);
        assert_eq!(carried.holds, book.holds);
        assert_eq!(carried.lineage, book.lineage);
        assert_eq!(carried.proposal_week, week + 1);
        assert_eq!(carried.proposal_snapshot, [42; 32]);
        assert_eq!(carried.proposal_revision, 7);
        assert_eq!(carried.proposal_remaining, book.proposal_remaining);
        assert!(carried.proposed);
    }
    assert_eq!(cursor.carried_holds.len(), 26);
    assert!(cursor.finish_week(126, 0).is_err());
    let mut data = Vec::new();
    cursor.try_serialize(&mut data).unwrap();
    assert_eq!(data.len(), 8 + Stage1SettlementCursor::INIT_SPACE);
    assert!(data.len() <= 10_240);
    ledger.check(0, 0).unwrap();
}

#[test]
fn delayed_zero_hold_closure_cannot_overwrite_a_newer_original_age_slot() {
    use anchor_lang::AccountSerialize;
    let mut cursor: Stage1SettlementCursor = blank();
    cursor.next_week = 27;
    cursor.finish_week(27, 90).unwrap();
    let mut current: Stage1WeekFunding = blank();
    current.week = 27;
    current.holds = [90, 0, 0, 0, 0];
    cursor.carry_closed_holds(Pubkey::new_unique(), &current).unwrap();
    let mut before = Vec::new();cursor.try_serialize(&mut before).unwrap();
    let mut old: Stage1WeekFunding = blank();old.week = 1;
    cursor.carry_closed_holds(Pubkey::new_unique(), &old).unwrap();
    let mut after = Vec::new();cursor.try_serialize(&mut after).unwrap();
    assert_eq!(before, after);
    old.holds[0] = 90;
    assert!(cursor.carry_closed_holds(Pubkey::new_unique(), &old).is_err());
    let mut mismatch: Stage1WeekFunding = blank();mismatch.week=27;mismatch.holds[0]=89;
    assert!(cursor.carry_closed_holds(Pubkey::new_unique(), &mismatch).is_err());
}
fn pk(value: &serde_json::Value) -> Pubkey {
    Pubkey::from_str(value.as_str().unwrap()).unwrap()
}
fn bytes(value: &serde_json::Value) -> [u8; 32] {
    let text = value.as_str().unwrap();
    std::array::from_fn(|i| u8::from_str_radix(&text[i * 2..i * 2 + 2], 16).unwrap())
}

#[test]
fn independent_oracle_allocations_have_exact_canonical_roots_and_proofs() {
    let fixtures: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/fixtures/stage1_claim_vectors.json"
    ))
    .unwrap();
    let mut verified = 0;
    for (_, case) in fixtures["cases"].as_object().unwrap() {
        let context = &case["context"];
        for step in case["steps"].as_array().unwrap() {
            let mut set: Stage1ClaimSet = blank();
            set.city = pk(&context[1]);
            set.hill = pk(&context[2]);
            set.mint = pk(&context[4]);
            set.week = step["week"].as_u64().unwrap();
            set.root = bytes(&step["root"]);
            set.total = step["total"].as_str().unwrap().parse().unwrap();
            let cap: u64 = step["cap"].as_str().unwrap().parse().unwrap();
            set.leaf_count = step["count"].as_u64().unwrap() as u32;
            if set.leaf_count == 0 {
                assert_eq!(
                    empty_node(&context_json(
                        pk(&context[0]),
                        set.city,
                        set.hill,
                        set.week,
                        set.mint
                    ))
                    .hash,
                    set.root
                );
            }
            for leaf in step["leaves"].as_array().unwrap() {
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
                verify_proof(
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    recipient,
                    amount,
                    &proof, cap)
                .unwrap();
                assert!(verify_proof(
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    recipient,
                    amount + 1,
                    &proof, cap)
                .is_err());
                assert!(verify_proof(
                    &set,
                    pk(&context[0]),
                    set.leaf_count,
                    person,
                    recipient,
                    amount,
                    &proof, cap)
                .is_err());
                assert!(verify_proof(
                    &set,
                    Pubkey::new_unique(),
                    index,
                    person,
                    recipient,
                    amount,
                    &proof, cap)
                .is_err());
                assert!(verify_proof(
                    &set,
                    pk(&context[0]),
                    index,
                    person,
                    Pubkey::new_unique(),
                    amount,
                    &proof, cap)
                .is_err());
                if !proof.is_empty() {
                    assert!(verify_proof(
                        &set,
                        pk(&context[0]),
                        index,
                        person,
                        recipient,
                        amount,
                        &proof[1..], cap)
                    .is_err());
                    let mut bad = proof.clone();
                    bad[0].sum += 1;
                    assert!(verify_proof(
                        &set,
                        pk(&context[0]),
                        index,
                        person,
                        recipient,
                        amount,
                        &bad, cap)
                    .is_err());
                    let mut bad = proof.clone();
                    bad[0].hash[0] ^= 1;
                    assert!(verify_proof(
                        &set,
                        pk(&context[0]),
                        index,
                        person,
                        recipient,
                        amount,
                        &bad, cap)
                    .is_err());
                }
                verified += 1;
            }
        }
    }
    assert!(verified > 45);
}

#[test]
fn contextual_odd_padding_cannot_be_a_duplicated_money_leaf_even_with_a_committed_root() {
    let mut set: Stage1ClaimSet = blank();
    set.leaf_count = 3;
    let cap: u64 = 100;
    let deployment = Pubkey::new_unique();
    let person = Pubkey::new_unique();
    let recipient = Pubkey::new_unique();
    let context = context_json(deployment, set.city, set.hill, set.week, set.mint);
    let leaf = leaf_node(&context, 2, person, recipient, 10);
    let other = Stage1SumNode {
        hash: [1; 32],
        sum: 20,
    };
    let fake = parent_node(&other, &parent_node(&leaf, &leaf).unwrap()).unwrap();
    set.root = fake.hash;
    set.total = fake.sum;
    assert!(verify_proof(&set, deployment, 2, person, recipient, 10, &[leaf, other], cap).is_err());
    assert!(parent_node(
        &Stage1SumNode {
            hash: [0; 32],
            sum: u128::MAX
        },
        &Stage1SumNode {
            hash: [0; 32],
            sum: 1
        }
    )
    .is_err());
}

#[test]
fn hold_age_is_original_age_and_pool_is_terminal_at_exactly_26() {
    let mut ledger = Stage1Ledger::default();
    ledger.deposit(100).unwrap();
    ledger.harvest(100, 10).unwrap();
    let mut source: Stage1WeekFunding = blank();
    source.week = 7;
    source.due_week = 7;
    source.published = true;
    source.holds = [0, 0, 70, 20, 0];
    assert!(source.expire(32, &mut ledger).is_err());
    assert_eq!(ledger.pool, 0);
    source.expire(33, &mut ledger).unwrap();
    assert_eq!(ledger.pool, 90);
    assert_eq!(source.pool, 90);
    assert_eq!(source.holds, [0; 5]);
    ledger.check(100, 10).unwrap();
    let mut attempted = ledger.clone();
    assert!(attempted.publish(1).is_err());
    source.expire(34, &mut ledger).unwrap();
    assert_eq!(ledger.pool, 90);
    assert!(validate_remaining(&[0, 0, 10, 0, 0], &[0, 10, 0, 0, 0]).is_err());
    validate_remaining(&[0, 0, 10, 0, 0], &[0, 0, 0, 0, 10]).unwrap();
}

#[test]
fn seeded_long_value_sequences_preserve_every_asset_equality_after_each_step() {
    // Production arithmetic, independently enumerated lots/holds/claims. The
    // clone/commit boundary models Solana rollback; validator tests cover real
    // whole-account/transfer rollback, not just this CPU model.
    const STEPS: usize = 4000;
    for seed in 1..=8u64 {
        let mut rng = seed;
        let mut ledger = Stage1Ledger::default();
        let mut lots = Vec::<u64>::new();
        let mut holds = Vec::<(u64, u64, bool)>::new();
        let mut claims = Vec::<u64>::new();
        let mut realized = 0u128;
        let mut fees = 0u128;
        let mut deposited = 0u128;
        let mut paid = 0u128;
        let mut returned = 0u128;
        for step in 0..STEPS {
            rng ^= rng << 13;
            rng ^= rng >> 7;
            rng ^= rng << 17;
            let value = 1 + rng % 1000;
            let week = (step / 32) as u64;
            match rng % 6 {
                0 => {
                    ledger.deposit(value).unwrap();
                    lots.push(value);
                    deposited += value as u128;
                }
                1 if !lots.is_empty() => {
                    let i = rng as usize % lots.len();
                    let amount = value.min(lots[i]);
                    if amount > 0 {
                        let next = realized + amount as u128;
                        let fee = (next / 10 - fees) as u64;
                        ledger.harvest(amount, fee).unwrap();
                        lots[i] -= amount;
                        realized = next;
                        fees = realized / 10;
                        if amount > fee {
                            holds.push((week, amount - fee, false));
                        }
                    }
                }
                2 if !holds.is_empty() => {
                    let i = rng as usize % holds.len();
                    let (born, amount, pool) = holds[i];
                    if amount > 0 && !pool {
                        if week - born >= 26 {
                            let mut book: Stage1WeekFunding = blank();
                            book.week = born;
                            book.published = true;
                            book.holds[0] = amount;
                            book.expire(week, &mut ledger).unwrap();
                            holds[i].2 = true;
                        } else {
                            let payment = value.min(amount);
                            ledger.publish(payment).unwrap();
                            holds[i].1 -= payment;
                            claims.push(payment);
                        }
                    }
                }
                3 if !claims.is_empty() => {
                    let i = rng as usize % claims.len();
                    let amount = claims[i];
                    if amount > 0 {
                        ledger.claim(amount).unwrap();
                        paid += amount as u128;
                        claims[i] = 0;
                    }
                }
                4 if !lots.is_empty() => {
                    let i = rng as usize % lots.len();
                    let amount = lots[i];
                    ledger.owner_return(amount, 0).unwrap();
                    returned += amount as u128;
                    lots[i] = 0;
                }
                _ => {
                    let before = ledger.clone();
                    let mut candidate = ledger.clone();
                    let over = u64::try_from(ledger.claimable).unwrap() + 1;
                    assert!(candidate.claim(over).is_err());
                    assert_eq!(ledger, before);
                }
            }
            ledger.check(realized, fees).unwrap();
            assert_eq!(ledger.deposited, deposited);
            assert_eq!(ledger.paid, paid);
            assert_eq!(ledger.owner_returns, returned);
            assert_eq!(
                ledger.owner_custody,
                lots.iter().map(|v| *v as u128).sum::<u128>()
            );
            assert_eq!(
                ledger.held,
                holds.iter().map(|(_, v, _)| *v as u128).sum::<u128>()
            );
            assert_eq!(
                ledger.pool,
                holds
                    .iter()
                    .filter(|(_, _, p)| *p)
                    .map(|(_, v, _)| *v as u128)
                    .sum::<u128>()
            );
            assert_eq!(
                ledger.claimable,
                claims.iter().map(|v| *v as u128).sum::<u128>()
            );
        }
    }
}
