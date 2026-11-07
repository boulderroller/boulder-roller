"""Seeded state-machine fuzzer: Hypothesis is not installed in the M0 runtime."""

from fractions import Fraction
from copy import deepcopy
import random

import pytest

from tools.stage1_reference.model import DAY, WEEK


@pytest.mark.parametrize("seed", [19, 73, 271, 919, 2026, 65537])
def test_long_random_action_sequences_preserve_every_asset_and_rejection_atomicity(factory, seed):
    rng = random.Random(seed)
    model = factory()
    model.allow_asset("other-lst", 12, Fraction(1, 1000))
    model.pledge("founder", "h", "lst", 100)
    accepted, rejected = 0, 0
    for step in range(800):
        before = deepcopy(model.__dict__)
        asset = rng.choice(["lst", "other-lst"])
        lot = rng.choice(list(model.lots.values())) if model.lots else None
        operation = rng.randrange(15)
        try:
            if operation == 0:
                model.pledge(f"owner{rng.randrange(4)}", "h", asset, rng.randrange(1, 201), rng.choice([0, 13, 26, 52]))
            elif operation == 1:
                model.observe_rate(asset, Fraction(rng.randrange(1, 12), rng.choice([1, 2, 3, 1000])))
            elif operation == 2 and lot:
                original_units, original_basis = lot.units, lot.basis
                amount = model.harvest(lot.id, rng.choice([None, 1, 10, 100]))
                if amount:
                    remaining = model.lots[lot.id]
                    assert remaining.units * model.rate(remaining) >= original_basis
                    assert original_units - remaining.units == amount
            elif operation == 3:
                model.sponsor("h", rng.randrange(1, 100_001))
            elif operation == 4:
                model.advance(model.now + rng.randrange(1, 6) * DAY)
            elif operation == 5:
                model.upload(f"receipt-{step}", "h", f"p{rng.randrange(12)}", max(model.launch, model.now - rng.randrange(9) * DAY), rng.randrange(1_000_001))
            elif operation == 6:
                model.set_board("h", rng.sample([f"p{i}" for i in range(12)], rng.randrange(11)), rng.choice([None, "p0", "p1"]))
            elif operation == 7:
                model.settle("h", model.hills["h"].next_settle)
            elif operation == 8 and model.settlements:
                settlement = rng.choice(list(model.settlements.values()))
                claims = rng.choice(list(settlement.claims.values()))
                if claims.leaves:
                    leaf = rng.choice(claims.leaves)
                    model.claim("h", settlement.week, claims.context.asset, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)
            elif operation == 9 and lot and lot.basis:
                model.notice(lot.id, lot.owner, rng.randrange(1, lot.basis + 1))
            elif operation == 10 and lot:
                model.cancel_notice(lot.id, lot.owner)
            elif operation == 11 and lot:
                model.begin_exit(lot.id, lot.owner)
            elif operation == 12 and lot:
                model.finish_exit(lot.id, lot.owner, liquid=rng.choice([True, False]))
            elif operation == 13:
                duration = rng.randrange(1, 4)
                model.boost("sponsor", ["h"], duration * 1_000_000 + rng.randrange(10001), model.week + 1, duration)
            else:
                model.pay_fees(asset)
            accepted += 1
        except ValueError:
            rejected += 1
            assert model.__dict__ == before, (seed, step, operation)
        model.check()
        for mint, ledger in model.ledgers.items():
            balances = model.balances(mint)
            assert ledger.fees == ledger.realized // 10
            assert balances["paid"] + balances["fees"] + balances["claimable"] + balances["held"] <= balances["realized"] + balances["cash"]
            for settlement in model.settlements.values():
                claims = settlement.claims.get(mint)
                if claims:
                    assert claims.root.total == sum(leaf.amount for leaf in claims.leaves)
                    assert all(leaf.amount <= settlement.caps[mint] for leaf in claims.leaves)
    assert accepted > 300 and rejected > 20


def test_random_partial_exit_partitions_never_create_unchanged_rate_income(factory):
    rng = random.Random(80421)
    exercised = 0
    for _ in range(120):
        model = factory()
        model.pledge("founder", "h", "lst", 100)
        model.observe_rate("lst", Fraction(rng.randrange(1, 20), rng.randrange(1, 20)))
        lot = model.pledge("owner", "h", "lst", rng.randrange(2, 100))
        model.observe_rate("lst", model.assets["lst"].rate * Fraction(rng.randrange(1, 5), 2))
        model.harvest(lot)
        before = model.balances("lst")["realized"]
        basis = model.lots[lot].basis
        model.notice(lot, "owner", rng.randrange(1, basis + 1))
        model.advance(model.now + 4 * WEEK)
        try:
            exit_id = model.begin_exit(lot, "owner")
        except ValueError as error:
            assert "base unit" in str(error)
            model.cancel_notice(lot, "owner")
            model.notice(lot, "owner", basis)
            model.advance(model.now + 4 * WEEK)
            exit_id = model.begin_exit(lot, "owner")
        assert model.harvest(lot) == 0
        assert model.harvest(exit_id) == 0
        model.finish_exit(exit_id, "owner", liquid=True)
        assert model.balances("lst")["realized"] == before
        model.check()
        exercised += 1
    assert exercised == 120
