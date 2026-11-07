from copy import deepcopy

import pytest

from tools.stage1_reference.model import WEEK
from .conftest import close


def test_boost_start_horizon_and_minimum_apply_after_hamilton(factory):
    model = factory()
    model.add_hill("other")
    for amount, start in [(6_000_000, 14), (5_999_999, 13)]:
        before = deepcopy(model.__dict__)
        with pytest.raises(ValueError):
            model.boost("brand", ["h", "other"], amount, start, 3)
        assert model.__dict__ == before
    source = model.boost("brand", ["h", "other"], 6_000_005, 13, 3)
    assert [n for _, _, n in model.boosts[source].schedule] == [1_000_001] * 5 + [1_000_000]


def test_quiet_skip_stops_before_original_maturity_and_changes_no_money(factory):
    model = factory()
    model.sponsor("h", 90)
    close(model, 0)
    model.advance(model.launch + 28 * WEEK + model.config.grace)
    ledger, tranches = deepcopy(model.ledgers), deepcopy(model.tranches)
    model.skip_empty("h", 15)
    model.skip_empty("h", 25)
    assert model.ledgers == ledger and model.tranches == tranches
    with pytest.raises(ValueError):
        model.skip_empty("h", 26)
    close(model, 26)
    assert {(t.born, t.bucket) for t in model.tranches} == {(0, "pool")}
    assert model.balances("USDC")["held"] == 90
    model.skip_empty("h", 27)


def test_quiet_skip_stops_before_next_boost_due_and_never_strands_it(factory):
    model = factory()
    model.boost("brand", ["h"], 2_000_000, 13, 2)
    model.advance(model.launch + 42 * WEEK + model.config.grace)
    ledger = deepcopy(model.ledgers)
    with pytest.raises(ValueError):
        model.skip_empty("h", 13)
    model.skip_empty("h", 12)
    assert model.ledgers == ledger
    for week in [13, 14]:
        with pytest.raises(ValueError):
            model.skip_empty("h", week)
        close(model, week)
    model.skip_empty("h", 30)
    model.skip_empty("h", 38)
    with pytest.raises(ValueError):
        model.skip_empty("h", 39)
    close(model, 39)
    with pytest.raises(ValueError):
        model.skip_empty("h", 40)
    close(model, 40)
    assert {(t.born, t.bucket) for t in model.tranches} == {(13, "pool"), (14, "pool")}
    assert model.balances("USDC")["held"] == 2_000_000


def test_boost_ids_are_scoped_to_the_funder(factory):
    model = factory()
    first = model.boost("alice", ["h"], 1_000_000, 1, 1, boost_id="published-id")
    second = model.boost("bob", ["h"], 1_000_000, 1, 1, boost_id="published-id")
    assert first != second
    before = deepcopy(model.__dict__)
    with pytest.raises(ValueError):
        model.boost("alice", ["h"], 1_000_000, 1, 1, boost_id="published-id")
    assert model.__dict__ == before
