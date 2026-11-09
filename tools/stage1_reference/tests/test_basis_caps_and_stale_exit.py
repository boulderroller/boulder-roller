from fractions import Fraction

import pytest

from tools.stage1_reference.model import WEEK


def test_caps_hold_deposit_basis_through_appreciation_loss_and_return(factory):
    model = factory()
    lot = model.pledge("a", "h", "lst", 4998)
    model.observe_rate("lst", Fraction(2))
    model.pledge("b", "h", "lst", 1)
    assert model.held_basis == 5000
    model.observe_rate("lst", Fraction(1, 2))
    with pytest.raises(ValueError, match="cap"):
        model.pledge("c", "h", "lst", 1)
    model.advance(model.launch + 26 * WEEK)
    model.notice(lot, "a", 100)
    model.advance(model.now + 4 * WEEK)
    child = model.begin_exit(lot, "a")
    assert model.held_basis == 5000
    model.finish_exit(child, "a", liquid=True)
    assert model.held_basis == model.hill_basis["h"] == model.asset_basis["lst"] == 4900
    model.pledge("c", "h", "lst", 200)


def test_stale_escape_requires_full_notice_and_seven_continuous_stale_days(factory):
    model = factory()
    model.pledge("founder", "h", "lst", 100)
    lot = model.pledge("a", "h", "lst", 100)
    model.notice(lot, "a", 100)
    model.advance(model.now + 4 * WEEK)
    model.observe_rate("lst", Fraction(2))
    model.mark_rate_stale("lst")
    with pytest.raises(ValueError, match="stale"):
        model.begin_exit(lot, "a")
    model.advance(model.now + WEEK - 1)
    with pytest.raises(ValueError, match="stale"):
        model.begin_exit(lot, "a")
    model.advance(model.now + 1)
    with pytest.raises(ValueError, match="stale"):
        model.harvest(lot, 1)
    child = model.begin_exit(lot, "a")
    assert model.finish_exit(child, "a", liquid=True) == 100
    assert model.balances("lst")["realized"] == 0
    assert model.held_basis == 100


def test_fresh_readmission_resets_escape_and_partial_notice_cannot_expand(factory):
    model = factory()
    model.pledge("founder", "h", "lst", 100)
    lot = model.pledge("a", "h", "lst", 100)
    model.notice(lot, "a", 50)
    model.advance(model.now + 4 * WEEK)
    model.mark_rate_stale("lst")
    model.advance(model.now + WEEK)
    with pytest.raises(ValueError, match="full"):
        model.begin_exit(lot, "a")
    model.observe_rate("lst", Fraction(1))
    child = model.begin_exit(lot, "a")
    model.mark_rate_stale("lst")
    model.advance(model.now + WEEK - 1)
    with pytest.raises(ValueError, match="stale"):
        model.finish_exit(child, "a", liquid=True)
    model.advance(model.now + 1)
    assert model.finish_exit(child, "a", liquid=True) == 50
