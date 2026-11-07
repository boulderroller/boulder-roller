"""Offline differential evidence; generated people are not verified riders."""
import random
import sys
from pathlib import Path

import pytest

from app.services.stage1_keeper_allocation import allocate
from app.services.stage1_keeper_merkle import claim_set
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from stage1_reference.keeper import recompute


def measurement(n=5, board=None, legend="r0", live=True):
    return {"context": ["program", "city", "hill", 1, "mint"],
            "live": live, "field": n >= 5, "field_people": [f"r{i}" for i in range(n)],
            "ascents": {f"r{i}": 1 for i in range(n)},
            "board": board if board is not None else [f"r{i}" for i in range(min(n, 10))],
            "legend": legend if n else None,
            "recipients": {f"r{i}": f"wallet{i}" for i in range(12)}}


def source(amount=1000, born=1, buckets=None):
    return {"id": f"source-{born}", "born": born, "due": born, "kind": "yield",
            "buckets": buckets or [amount, 0, 0, 0, 0], "lineage": "ab" * 32}


def test_five_riders_match_independent_oracle():
    snapshot, sources = measurement(), [source()]
    result = allocate(snapshot, sources)
    assert result == recompute(snapshot, sources)
    assert sum(result["payments"].values()) == 1000
    assert result["payments"]["r0"] == 280


@pytest.mark.parametrize('parameter',['field','split','cap_multiplier','held_weeks'])
def test_reference_policy_parameters_are_loaded_independently(parameter):
    from dataclasses import replace
    from fractions import Fraction
    from stage1_reference.config import load_config
    config=load_config()
    value={'field':6,'split':{'every_rider_by_ascents':Fraction(1),'top_ten':Fraction(0),'local_legend':Fraction(0)},
           'cap_multiplier':Fraction(1),'held_weeks':1}[parameter]
    snapshot,sources=measurement(),[source(born=0)]
    assert recompute(snapshot,sources,replace(config,**{parameter:value})) != allocate(snapshot,sources)


def test_unregistered_share_is_reserved_then_released_without_reassignment():
    snapshot, sources = measurement(), [source()]
    del snapshot["recipients"]["r0"]
    first = allocate(snapshot, sources)
    assert "r0" not in first["payments"]
    assert first["reserved"]["source-1"] == {"r0": 280}
    assert first["holds"]["source-1"][4] == 280
    snapshot["context"][3] = 2
    snapshot.update(ascents={}, board=[], legend=None, recipients={"r0": "wallet0"})
    later = [{**sources[0], "buckets": first["holds"]["source-1"], "reserved": first["reserved"]["source-1"]}]
    result = allocate(snapshot, later)
    assert result == recompute(snapshot, later)
    assert result["payments"] == {"r0": 280}
    snapshot["context"][3] = 27
    expired = allocate(snapshot, later)
    assert expired["payments"] == {} and expired["pool"]["source-1"] == 280


def test_leaf_hashes_preserve_root_after_person_erasure():
    from app.services.stage1_keeper_merkle import root_from_hashes
    original = claim_set(measurement()["context"], {"r0": 100, "r1": 200}, measurement()["recipients"])
    for leaf in original["leaves"]:
        leaf["person"] = leaf["recipient"] = "anonymous:erased"
    assert root_from_hashes(original["context"], original["leaves"]) == (original["root"], original["total"])


@pytest.mark.parametrize("n", [0, 1, 4, 5])
@pytest.mark.parametrize("amount", [0, 1, 2, 7, 999, 1000, 2**32 + 7])
@pytest.mark.parametrize("live", [False, True])
def test_field_and_rounding(n, amount, live):
    snapshot, sources = measurement(n, live=live), [source(amount)]
    assert allocate(snapshot, sources) == recompute(snapshot, sources)


def test_randomized_holds_cap_and_utf8_ties():
    rng = random.Random(41031)
    for _ in range(250):
        n = rng.randrange(0, 12)
        snapshot = measurement(n, board=[f"r{i}" for i in range(rng.randrange(11))],
                               legend=rng.choice([None, "r0", "r11"]))
        snapshot["ascents"] = {p: rng.randrange(1, 8) for p in snapshot["ascents"]}
        snapshot["context"][3] = 27
        sources = [source(rng.randrange(10000), born=b,
                          buckets=[rng.randrange(500) for _ in range(5)]) for b in [0, 1, 2, 26, 27]]
        actual = allocate(snapshot, sources)
        assert actual == recompute(snapshot, sources)
        assert all(0 < v <= actual["cap"] for v in actual["payments"].values())
        assert sum(actual["payments"].values()) + sum(sum(v) for v in actual["holds"].values()) + sum(actual["pool"].values()) == sum(sum(s["buckets"]) for s in sources)


def test_merkle_matches_oracle_canonical_json():
    from stage1_reference.merkle import ClaimSet, Context
    for n in [0, 1, 4, 5, 11]:
        snapshot = measurement(n)
        result = allocate(snapshot, [source()])
        actual = claim_set(snapshot["context"], result["payments"], snapshot["recipients"])
        oracle = ClaimSet.build(Context(*snapshot["context"]), result["payments"], snapshot["recipients"])
        assert actual["root"] == oracle.root.hash.hex()
        assert actual["total"] == oracle.root.total
        for leaf, expected in zip(actual["leaves"], oracle.leaves):
            assert leaf["amount"] == expected.amount
            assert leaf["proof"] == [{"hash": p.hash.hex(), "sum": p.total} for p in oracle.proof(expected.index)]


@pytest.mark.asyncio
async def test_actual_oracle_subprocess_with_backend_on_pythonpath(monkeypatch):
    from app.services.stage1_keeper_worker import independent
    import os
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[2]) + ":" + os.environ.get("PYTHONPATH", ""))
    snapshot, sources = measurement(), [source()]
    allocated = allocate(snapshot, sources)
    assert await independent(snapshot, sources) == {
        "allocation": allocated,
        "claims": claim_set(snapshot["context"], allocated["payments"], snapshot["recipients"])}


@pytest.mark.parametrize("name", ["zero", "one", "four", "five", "empty-board", "tied-board", "cap-redistribution", "odd-median", "even-median", "zeros-excluded", "release", "expire"])
def test_retained_original_model_vectors(name):
    import json
    from stage1_reference.claim_vectors import CASES, key
    vectors = json.loads((Path(__file__).resolve().parents[3]/"protocol/anchor/tests/fixtures/stage1_claim_vectors.json").read_text())
    case = vectors["cases"][name]
    step = case["steps"][0]
    n, seats, legend = CASES[name]
    people = [key(i+10) for i in range(12)]
    snapshot = {"context": case["context"], "live": True, "field": n>=5, "field_people": people[:n],
                "ascents": {p: 7 if name=="cap-redistribution" and i==0 else 1 for i,p in enumerate(people[:n])},
                "board": people[:seats], "legend": people[legend] if legend is not None else None,
                "recipients": dict(zip(people,[key(i+30) for i in range(12)]))}
    net = case["harvest"] - step["before_claims"]["fees"]
    allocated = allocate(snapshot, [source(net)])
    claims = claim_set(snapshot["context"], allocated["payments"], snapshot["recipients"])
    assert claims["root"] == step["root"]
    assert claims["total"] == int(step["total"])
    assert allocated["cap"] == int(step["cap"])
    assert allocated["holds"]["source-1"] == step["holds"].get("1", {"buckets": [0]*5})["buckets"]
