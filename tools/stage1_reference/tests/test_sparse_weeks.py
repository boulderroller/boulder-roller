from copy import deepcopy
from fractions import Fraction

import pytest

from tools.stage1_reference.model import WEEK
from .conftest import close, riders


def test_late_admission_skips_without_creating_settlements(factory):
    model = factory()
    model.advance(model.launch + 100 * WEEK)
    model.add_hill("late")
    model.advance(model.launch + 110 * WEEK + model.config.grace)
    model.skip_empty("late", 109)
    assert model.hills["late"].next_settle == 110
    assert not any(hill == "late" for hill, _ in model.settlements)


def test_skip_is_bounded_finalized_and_atomic(factory):
    model = factory()
    with pytest.raises(ValueError):
        model.skip_empty("h", 0)
    model.advance(model.launch + 20 * WEEK + model.config.grace)
    for through in (-1, 16):
        with pytest.raises(ValueError):
            model.skip_empty("h", through)
    model.skip_empty("h", 15)
    model.skip_empty("h", 19)
    assert model.hills["h"].next_settle == 20


def test_quiet_hold_skip_keeps_original_age_expiry(factory):
    model = factory()
    model.sponsor("h", 90)
    close(model, 0)
    model.advance(model.launch + 28 * WEEK + model.config.grace)
    before = deepcopy(model.ledgers)
    model.skip_empty("h", 15)
    model.skip_empty("h", 25)
    assert model.ledgers == before
    with pytest.raises(ValueError):
        model.skip_empty("h", 26)
    close(model, 26)
    assert {(t.born, t.bucket) for t in model.tranches} == {(0, "pool")}
    assert sum(t.amount for t in model.tranches) == 90
    model.skip_empty("h", 27)
    assert model.balances("USDC")["held"] == 90


def test_all_fee_harvest_is_income_even_without_net_tranche(factory):
    model = factory()
    lot = model.pledge("a", "h", "lst", 100)
    close(model, 0)
    model.observe_rate("lst", Fraction(2))
    model.harvest(lot, 9)
    riders(model, 5)
    model.set_board("h", [f"p{i}" for i in range(5)], "p0")
    close(model, 1)
    assert not model.tranches
    model.harvest(lot, 1)
    assert not model.tranches
    model.advance(model.launch + 3 * WEEK + model.config.grace)
    with pytest.raises(ValueError):
        model.skip_empty("h", 2)


def test_oracle_skip_never_discards_other_asset_or_dung(factory):
    model = factory()
    model.pledge("a", "h", "lst", 100)
    close(model, 0)
    riders(model, 5)
    model.advance(model.launch + 2 * WEEK + model.config.grace)
    assert model._dung("h", model.snapshots["h", 1]).potential > 0
    with pytest.raises(ValueError):
        model.skip_empty("h", 1)
