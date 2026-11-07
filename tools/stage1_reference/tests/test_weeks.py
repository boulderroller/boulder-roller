from dataclasses import replace
from fractions import Fraction

import pytest

from tools.stage1_reference.arithmetic import apportion, median_cap, redistribute
from tools.stage1_reference.model import DAY, WEEK
from .conftest import close, paid, riders


@pytest.mark.parametrize('register', [True,False])
def test_unregistered_person_share_releases_only_to_them_or_expires_at_original_age(factory,register):
    model=factory()
    model.upload('missing-recipient','h','unregistered',model.now,0)
    model.sponsor('h',1000)
    first=close(model,0)
    assert paid(first)=={}
    assert [(t.person,t.amount,t.born) for t in model.tranches if t.person]==[('unregistered',650,0)]
    if register:
        model.register_person('unregistered','new-wallet')
        assert paid(close(model,1))=={'unregistered':650}
    else:
        for week in range(1,27):
            assert paid(close(model,week))=={}
        assert all(t.bucket=='pool' and t.person is None and t.born==0 for t in model.tranches)


def test_registered_person_hold_orders_after_ordinary_legend_for_same_source(factory):
    from tools.stage1_reference.model import Tranche
    model=factory()
    riders(model,5)
    close(model,0)
    model.upload('p1-now','h','p1',model.now,0)
    model.upload('p2-now','h','p2',model.now,0)
    model.set_board('h',[],'p0')
    # Same retained source with an earned person hold plus ordinary buckets.
    model.sponsor('h',1020)
    source=model.tranches[0].source
    model.tranches=[Tranche(source,'h','USDC',20,0,0,'sponsor','ascents'),
                    Tranche(source,'h','USDC',100,0,0,'sponsor','legend'),
                    Tranche(source,'h','USDC',900,0,0,'sponsor','cap',person='p0')]
    result=close(model,1)
    assert paid(result)=={'p0':30,'p1':30,'p2':30}
    assert sum(t.amount for t in model.tranches if t.person=='p0')==900
    assert sum(t.amount for t in model.tranches if t.bucket=='cap' and t.person is None)==30


@pytest.mark.parametrize("count", [0, 1, 4, 5])
def test_field_boundaries_pay_ascents_before_records(factory, count):
    model = factory()
    model.pledge("a", "h", "lst", 100)
    riders(model, count)
    model.set_board("h", [f"p{i}" for i in range(count)], "p0" if count else None)
    model.sponsor("h", 10000)
    settlement = close(model, 0)
    expected = 0 if count == 0 else 6500 if count < 5 else 10000
    assert sum(paid(settlement).values()) == expected
    assert model.balances("USDC")["held"] == 10000 - expected
    assert settlement.dung.potential == 0  # partial bonding week stays unminted


def test_cap_uses_positive_combined_entitlements_then_fixed_headroom(factory):
    model = factory()
    riders(model, 5)
    model.set_board("h", ["p0"], "p0")
    model.sponsor("h", 10000)
    result = close(model, 0)
    assert result.caps["USDC"] == 3900
    assert paid(result) == {"p0": 3900, "p1": 1525, "p2": 1525, "p3": 1525, "p4": 1525}
    assert median_cap({"a": 1, "b": 2, "zero": 0}, Fraction(3)) == 4
    assert median_cap({}, Fraction(3)) == 0
    assert redistribute(100, {"a": 1}, {"a": 30}, 30) == ({}, 100)


def test_cap_excess_holds_when_only_ascent_rider_has_no_headroom(factory):
    model = factory()
    riders(model, 5)
    close(model, 0)
    model.set_board("h", ["p1", "p2", "p3", "p4", "p5"])
    riders(model, 1)
    model.sponsor("h", 10000)
    result = close(model, 1)
    assert result.caps["USDC"] == 1500
    assert paid(result)["p0"] == 1500
    assert model.balances("USDC")["held"] == 6000
    assert sorted((t.bucket, t.amount, t.born) for t in model.tranches) == [("cap", 5000, 1), ("legend", 1000, 1)]


def test_live_is_frozen_at_open_and_partial_bond_week_yield_waits(factory):
    model = factory()
    lot = model.pledge("a", "h", "lst", 100)
    model.observe_rate("lst", Fraction(2))
    model.harvest(lot, 20)
    riders(model, 1)
    close(model, 0)
    assert model.balances("lst")["held"] == 18
    assert model.openings["h", 1][0]
    model.observe_rate("lst", Fraction(1, 4))
    assert model.backing("h") < 50
    riders(model, 1)
    result = close(model, 1)
    assert sum(paid(result, "lst").values()) > 0
    assert not model.openings["h", 2][0]


def test_held_seats_keep_bucket_and_original_age_and_claims_do_not_expire(factory):
    model = factory()
    riders(model, 1)
    model.sponsor("h", 10000)
    original = close(model, 0)
    assert model.balances("USDC")["claimable"] == 6500
    for week in range(1, 26):
        close(model, week)
    assert all(t.born == 0 and t.bucket in ("top", "legend") for t in model.tranches)
    close(model, 26)
    assert all(t.bucket == "pool" and t.born == 0 for t in model.tranches)
    assert model.balances("USDC")["held"] == 3500
    assert model.balances("USDC")["claimable"] == 6500
    leaf = original.claims["USDC"].leaves[0]
    assert model.claim("h", 0, "USDC", leaf, original.claims["USDC"].proof(0), leaf.person, leaf.recipient) == 6500


def test_field_resets_on_city_season_and_held_releases_only_to_original_bucket(factory):
    model = factory()
    model.sponsor("h", 10000)
    close(model, 0)
    riders(model, 5)
    model.set_board("h", ["p0"], "p1")
    result = close(model, 1)
    assert sum(paid(result).values()) == 10000
    for week in range(2, 26):
        close(model, week)
    model.sponsor("h", 10000)
    riders(model, 1)
    result = close(model, 26)
    assert sum(paid(result).values()) == 6500
    assert not model.snapshots["h", 26].field


def test_delayed_keeper_cannot_rewrite_board_or_paid_week(factory):
    model = factory()
    riders(model, 5)
    model.set_board("h", ["p0"], "p1")
    model.sponsor("h", 10000)
    model.advance(model.launch + WEEK)
    model.set_board("h", ["p2"], "p3")
    with pytest.raises(ValueError, match="finalizable"):
        model.settle("h", 0)
    result = close(model, 0)
    assert model.snapshots["h", 0].board == ("p0",)
    assert paid(result)["p0"] > paid(result)["p2"]
    with pytest.raises(ValueError):
        model.settle("h", 0)


def test_upload_tail_boundary_and_day_dedup_cross_upload_weeks(factory):
    model = factory()
    model.upload("first", "h", "p0", model.now, 1_000_000)
    model.advance(model.launch + WEEK)
    model.upload("at-seven-days", "h", "p0", model.launch, 1_000_000)
    model.upload("other-person", "h", "p1", model.launch, 1_000_000)
    model.advance(model.now + 1)
    with pytest.raises(ValueError, match="window"):
        model.upload("too-late", "h", "p2", model.launch, 1_000_000)
    close(model, 0)
    model.sponsor("h", 10000)
    result = close(model, 1)
    assert paid(result) == {"p1": 6500}


def test_split_harvests_cannot_change_weekly_split_rounding(factory):
    def outcome(split):
        model = factory()
        lot = model.pledge("a", "h", "lst", 100)
        close(model, 0)
        model.observe_rate("lst", Fraction(2))
        for amount in ([1] * 20 if split else [20]):
            model.harvest(lot, amount)
        riders(model, 5)
        model.set_board("h", ["p0"], "p1")
        result = close(model, 1)
        return paid(result, "lst"), model.balances("lst")
    assert outcome(True) == outcome(False)


def test_fractional_distribution_tie_break_is_exact_and_stable():
    assert apportion(2, {"c": 1, "b": 1, "a": 1}) == {"c": 0, "b": 1, "a": 1}
    with pytest.raises(ValueError):
        apportion(2, {"a": 0.5})
