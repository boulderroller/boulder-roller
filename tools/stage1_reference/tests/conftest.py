from dataclasses import replace
from fractions import Fraction

import pytest

from tools.stage1_reference.config import load_config
from tools.stage1_reference.model import Model, WEEK

LAUNCH = 1791201600


@pytest.fixture
def factory():
    def make(**overrides):
        config = replace(load_config(), line=100, token_cap=20000, hill_cap=5000, total_cap=50000, **overrides)
        model = Model(config, LAUNCH)
        model.allow_asset("lst", 9, Fraction(1))
        model.add_hill("h")
        for i in range(12):
            model.register_person(f"p{i}", f"wallet{i}")
        return model
    return make


def close(model, week, hill="h"):
    model.advance(max(model.now, model.launch + (week + 1) * WEEK + model.config.grace))
    return model.settle(hill, week)


def riders(model, n, *, day=0):
    for i in range(n):
        model.upload(f"ride-{model.week}-{day}-{i}", "h", f"p{i}", model.now, 1_000_000)


def paid(settlement, asset="USDC"):
    claims = settlement.claims.get(asset)
    return {leaf.person: leaf.amount for leaf in claims.leaves} if claims else {}
