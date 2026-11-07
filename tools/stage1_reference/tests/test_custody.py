from fractions import Fraction

import pytest

from tools.stage1_reference.config import load_config
from tools.stage1_reference.model import Model, WEEK


def setup_model():
    model = Model(load_config(), launch=1791201600)  # Monday 5 Oct 2026, 12 UTC
    model.allow_asset("lst", decimals=9, rate=Fraction(1))
    model.add_hill("hill")
    return model


def test_only_transferred_surplus_is_income_and_split_harvests_pay_one_fee():
    model = setup_model()
    lot = model.pledge("alice", "hill", "lst", 10_000_000_000)
    model.observe_rate("lst", Fraction(2))
    assert model.balances("lst")["realized"] == 0
    for _ in range(10):
        model.harvest(lot, 1)
    balance = model.balances("lst")
    assert balance["realized"] == 10
    assert balance["fees"] == 1
    assert balance["held"] == 9
    assert model.lots[lot].basis == 10_000_000_000
    model.check()


def test_prebond_surplus_is_owner_reserve_and_cannot_bond_or_pay_riders(factory):
    model = factory()
    first = model.pledge("a", "h", "lst", 40)
    model.observe_rate("lst", Fraction(2))
    assert model.backing("h") == 40
    assert model.hills["h"].bonded_at is None
    with pytest.raises(ValueError, match="pre-bond"):
        model.harvest(first)
    second = model.pledge("b", "h", "lst", 30)
    assert model.hills["h"].founder == "b"
    assert model.hills["h"].legend is None
    assert model.lots[first].owner_units == 20
    assert model.lots[first].units == 20
    assert model.lots[second].basis == 60
    assert model.harvest(first) == 0
    with pytest.raises(ValueError, match="owner"):
        model.withdraw_prebond(first, "b")
    assert model.withdraw_prebond(first, "a") == 20
    assert model.balances("lst")["realized"] == 0


def test_losses_never_use_another_lot_and_partial_exits_preserve_basis(factory):
    model = factory()
    losing = model.pledge("a", "h", "lst", 100)
    model.observe_rate("lst", Fraction(1, 2))
    fresh = model.pledge("b", "h", "lst", 100)
    assert model.harvest(losing) == 0
    model.observe_rate("lst", Fraction(3, 4))
    assert model.harvest(losing) == 0
    assert model.harvest(fresh) == 33
    model.advance(model.launch + 26 * WEEK)
    model.notice(losing, "a", 37)
    model.advance(model.now + 4 * WEEK)
    exit_id = model.begin_exit(losing, "a")
    assert (model.lots[losing].basis, model.lots[exit_id].basis) == (63, 37)
    assert (model.lots[losing].units, model.lots[exit_id].units) == (63, 37)
    assert model.finish_exit(exit_id, "a", liquid=True) == 37
    assert model.lots[fresh].basis == 50


def test_fee_survives_split_lots_hills_and_claim_or_fee_transfers(factory):
    model = factory()
    first = model.pledge("a", "h", "lst", 100)
    second = model.pledge("b", "h", "lst", 100)
    model.add_hill("other")
    third = model.pledge("c", "other", "lst", 100)
    model.observe_rate("lst", Fraction(2))
    for lot in [first] * 4 + [second] * 3 + [third] * 3:
        model.harvest(lot, 1)
    assert model.balances("lst")["fees"] == 1
    assert model.pay_fees("lst") == 1
    assert model.pay_fees("lst") == 0
    assert model.balances("lst")["fees"] == 1
    assert model.balances("lst")["fees_due"] == 0
    model.sponsor("h", 1_000_000)
    assert model.balances("USDC")["fees"] == 0


@pytest.mark.parametrize("cancel_first", [True, False])
def test_cancellation_and_bonding_have_only_serial_atomic_outcomes(factory, cancel_first):
    model = factory()
    first = model.pledge("a", "h", "lst", 60)
    if cancel_first:
        assert model.cancel(first, "a") == 60
        model.pledge("b", "h", "lst", 40)
        assert model.hills["h"].bonded_at is None
    else:
        model.pledge("b", "h", "lst", 40)
        before = model.balances("lst")
        with pytest.raises(ValueError, match="bonded"):
            model.cancel(first, "a")
        assert model.balances("lst") == before
        assert model.lots[first].founding


def test_lock_notice_cancellation_and_deactivation_boundaries(factory):
    model = factory()
    lot = model.pledge("a", "h", "lst", 100)
    model.advance(model.launch + 26 * WEEK - 1)
    with pytest.raises(ValueError):
        model.notice(lot, "a", 100)
    model.advance(model.now + 1)
    model.notice(lot, "a", 100)
    model.cancel_notice(lot, "a")
    model.advance(model.now + WEEK)
    model.notice(lot, "a", 100)
    model.advance(model.now + 4 * WEEK - 1)
    with pytest.raises(ValueError):
        model.begin_exit(lot, "a")
    model.advance(model.now + 1)
    exit_id = model.begin_exit(lot, "a")
    assert model.backing("h") == 0
    with pytest.raises(ValueError):
        model.finish_exit(exit_id, "a", liquid=False)
    model.observe_rate("lst", Fraction(2))
    assert model.finish_exit(exit_id, "a", liquid=True) == 50
    assert model.balances("lst")["realized"] == 50
    assert model.balances("lst")["fees"] == 5


@pytest.mark.parametrize("lock", [0, 13, 26, 52])
def test_later_locks_start_at_deposit_and_allow_no_early_notice(factory, lock):
    model = factory()
    model.pledge("a", "h", "lst", 100)
    model.advance(model.now + 123)
    lot = model.pledge("b", "h", "lst", 20, lock_weeks=lock)
    assert not model.lots[lot].founding
    assert model.lots[lot].lock_end == model.now + lock * WEEK
    model.advance(model.lots[lot].lock_end)
    model.notice(lot, "b", 20)


def test_pilot_caps_hold_basis_and_increases_wait(factory):
    model = factory()
    model.pledge("a", "h", "lst", 4999)
    with pytest.raises(ValueError, match="cap"):
        model.pledge("b", "h", "lst", 2)
    model.propose_caps(20000, 6000, 50000)
    with pytest.raises(ValueError, match="timelocked"):
        model.execute_caps()
    model.advance(model.now + model.config.cap_delay - 1)
    with pytest.raises(ValueError):
        model.execute_caps()
    model.advance(model.now + 1)
    model.execute_caps()
    model.pledge("b", "h", "lst", 2)
    model.observe_rate("lst", Fraction(2))
    model.pledge("b", "h", "lst", 1)
    model.propose_caps(100, 100, 100)
    assert model.backing("h") == 5003  # reduction never seizes prior lots


@pytest.mark.parametrize("bad", [1.1, -1, True])
def test_noninteger_or_negative_amounts_are_rejected_atomically(factory, bad):
    model = factory()
    before = model.balances("lst")
    with pytest.raises(ValueError):
        model.pledge("a", "h", "lst", bad)
    assert model.balances("lst") == before


def test_fractional_lamport_deposit_cannot_create_income_without_appreciation(factory):
    model = factory()
    model.observe_rate("lst", Fraction(1, 1000))
    model.pledge("a", "h", "lst", 100_000)
    lot = model.pledge("b", "h", "lst", 1999)
    assert model.harvest(lot) == 0


def test_inexact_partial_split_cannot_relabel_principal_as_income(factory):
    model = factory()
    model.pledge("a", "h", "lst", 100)
    model.observe_rate("lst", Fraction(3, 2))
    lot = model.pledge("b", "h", "lst", 3)
    model.notice(lot, "b", 1)
    model.advance(model.now + 4 * WEEK)
    with pytest.raises(ValueError, match="base unit"):
        model.begin_exit(lot, "b")
    assert model.harvest(lot) == 0


def test_arbitrary_partial_exit_returns_split_dust_to_owner_without_new_income(factory):
    model = factory()
    model.pledge("a", "h", "lst", 100)
    lot = model.pledge("b", "h", "lst", 100)
    model.observe_rate("lst", Fraction(3))
    assert model.harvest(lot) == 66
    model.notice(lot, "b", 4)
    model.advance(model.now + 4 * WEEK)
    exit_id = model.begin_exit(lot, "b")
    assert model.lots[lot].basis == 96
    assert model.lots[exit_id].basis == 4
    assert model.lots[exit_id].owner_units == 1
    with pytest.raises(ValueError, match="exit"):
        model.withdraw_prebond(exit_id, "b")
    assert model.harvest(lot) == 0
    assert model.harvest(exit_id) == 0
    assert model.finish_exit(exit_id, "b", liquid=True) == 2
    assert model.balances("lst")["realized"] == 66
