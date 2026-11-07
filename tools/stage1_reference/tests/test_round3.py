from fractions import Fraction

import pytest

from tools.stage1_reference.model import WEEK


def test_stale_slot_cannot_jam_bond_and_excluded_lots_keep_owner_yield(factory):
    model = factory()
    model.allow_asset("x", 9, Fraction(1))
    model.pledge("backer", "h", "lst", 60)
    dust = model.pledge("dust", "h", "x", 1)
    excluded = model.pledge("owner", "h", "x", 10)
    recovered = model.pledge("recovering", "h", "x", 3)
    model.mark_rate_stale("x")
    assert model.backing("h") == 60
    model.pledge("backer", "h", "lst", 1)
    model.pledge("trigger", "h", "lst", 39)
    assert model.hills["h"].founder == "trigger"
    assert not model.lots[dust].founding and not model.lots[excluded].founding
    assert model.lots[excluded].lock_end is None
    assert "owner" not in dict(model._backers("h", 1))
    assert model.backing("h") == 100
    with pytest.raises(ValueError, match="wrong lot owner"):
        model.cancel(dust, "stranger")
    assert model.cancel(dust, "dust") == 1
    with pytest.raises(ValueError, match="stale"):
        model.convert(excluded, "owner", 13)
    model.observe_rate("x", Fraction(2))
    assert model.cancel(recovered, "recovering") == 3
    before = model.held_basis
    # Readmission alone cannot activate stake or redirect the owner's yield.
    assert model.backing("h") == 100
    assert "owner" not in dict(model._backers("h", 1))
    with pytest.raises(ValueError, match="pre-bond"):
        model.harvest(excluded, 1)
    with pytest.raises(ValueError, match="unlocked"):
        model.notice(excluded, "owner", 1)
    with pytest.raises(ValueError, match="wrong lot owner"):
        model.convert(excluded, "stranger", 13)
    with pytest.raises(ValueError, match="lock"):
        model.convert(excluded, "owner", 1)
    model.convert(excluded, "owner", 13)
    lot = model.lots[excluded]
    assert (lot.units, lot.owner_units, lot.basis, lot.founding) == (5, 5, 10, False)
    assert lot.lock_end == model.now + 13 * WEEK
    assert model.held_basis == before
    assert model.backing("h") == 110
    assert dict(model._backers("h", 1))["owner"] == 10 * model.config.lock_weights[13]
    with pytest.raises(ValueError, match="pre-bond"):
        model.convert(excluded, "owner", 0)
    with pytest.raises(ValueError, match="bonded"):
        model.cancel(excluded, "owner")
    assert model.withdraw_prebond(excluded, "owner") == 5
    assert model.ledgers["x"].realized == 0
    model.advance(lot.lock_end)
    model.notice(excluded, "owner", 10)
    model.advance(model.now + 4 * WEEK)
    child = model.begin_exit(excluded, "owner")
    assert model.finish_exit(child, "owner", liquid=True) == 5
    assert model.held_basis == 100


def test_all_stale_campaign_has_zero_backing_and_rejects_a_stale_deposit(factory):
    model = factory()
    lot = model.pledge("owner", "h", "lst", 90)
    model.mark_rate_stale("lst")
    assert model.backing("h") == 0
    with pytest.raises(ValueError, match="stale"):
        model.pledge("trigger", "h", "lst", 10)
    assert model.hills["h"].bonded_at is None
    assert model.cancel(lot, "owner") == 90
    assert model.held_basis == 0


def test_readmitted_slot_counts_before_bond_and_founding_never_changes_after(factory):
    model = factory()
    model.allow_asset("x", 9, Fraction(1))
    x = model.pledge("x-owner", "h", "x", 40)
    model.pledge("backer", "h", "lst", 50)
    model.mark_rate_stale("x")
    assert model.backing("h") == 50
    model.observe_rate("x", Fraction(2))
    assert model.backing("h") == 90
    model.pledge("trigger", "h", "lst", 10)
    assert model.lots[x].founding
    assert model.lots[x].owner_units == 20
    model.mark_rate_stale("x")
    with pytest.raises(ValueError, match="bonded"):
        model.cancel(x, "x-owner")
    assert model.lots[x].founding
    assert model.held_basis == 100
