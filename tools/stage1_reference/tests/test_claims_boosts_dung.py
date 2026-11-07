from dataclasses import replace
from fractions import Fraction

import pytest

from tools.stage1_reference.merkle import ClaimSet, Context, Node
from tools.stage1_reference.model import DAY, WEEK
from .conftest import close, paid, riders


def test_missing_rider_recipient_leaves_dung_unminted(factory):
    model=factory()
    model.configure_dung(20_000_000_000, 1)
    model.pledge('owner','h','lst',100)
    close(model,0)
    riders(model,5)
    model.upload('unregistered','h','unregistered',model.now,1_000_000)
    model.set_board('h',['unregistered'])
    result=close(model,1).dung
    assert 'unregistered' not in result.riders
    assert result.unminted>0
    model.publish_dung('h', 1)
    roots = model.dung_claim_sets('h', 1, 'DUNG')
    allocated = model.dung_allocated
    model.advance(model.now + 1)
    model.register_person('unregistered', 'late-rider-wallet')
    model.register_person('owner', 'late-backer-wallet')
    for role in ('riders', 'backers'):
        claims = model.publish_dung_claim_set('h', 1, 'DUNG', role)
        assert claims.root == roots[role].root
        assert all(leaf.person not in ('unregistered', 'owner') for leaf in claims.leaves)
    assert model.dung_records['h', 1].unminted == result.unminted
    assert model.dung_allocated == allocated


@pytest.mark.parametrize("count", [0, 1, 2, 5, 11])
def test_merkle_sum_proofs_bind_entire_namespace_and_every_leaf_field(count):
    context = Context("program", "city", "hill", 1, "mint")
    payments = {f"p{i}": 13 + i for i in range(count)}
    recipients = {person: "wallet-" + person for person in payments}
    claims = ClaimSet.build(context, payments, recipients)
    assert claims.root.total == sum(payments.values())
    assert claims.root == ClaimSet.build(context, dict(reversed(list(payments.items()))), recipients).root
    for leaf in claims.leaves:
        proof = claims.proof(leaf.index)
        assert claims.verify(leaf, proof)
        for changed in [replace(leaf, person="other"), replace(leaf, recipient="other"), replace(leaf, amount=leaf.amount + 1), replace(leaf, index=leaf.index + 1)]:
            assert not claims.verify(changed, proof)
        for key, value in {"deployment": "other", "city": "other", "hill": "other", "week": 2, "asset": "other"}.items():
            assert not replace(claims, context=replace(context, **{key: value})).verify(leaf, proof)
        for i, node in enumerate(proof):
            for bad in [Node(bytes(32), node.total), Node(node.hash, node.total + 1), Node(node.hash, -1)]:
                corrupt = proof[:i] + (bad,) + proof[i + 1:]
                assert not claims.verify(leaf, corrupt)
    if count == 0:
        assert len(claims.leaves) == 0


def test_claim_replay_and_redirects_preserve_custody_and_original_root(factory):
    model = factory()
    riders(model, 5)
    model.sponsor("h", 10000)
    result = close(model, 0)
    claims = result.claims["USDC"]
    leaf, proof = claims.leaves[0], claims.proof(0)
    before = model.balances("USDC")
    with pytest.raises(ValueError):
        model.claim("h", 0, "USDC", leaf, proof, "p11", leaf.recipient)
    with pytest.raises(ValueError):
        model.claim("h", 0, "USDC", leaf, proof, leaf.person, "redirect")
    assert model.balances("USDC") == before
    assert model.claim("h", 0, "USDC", leaf, proof, leaf.person, leaf.recipient) == leaf.amount
    after = model.balances("USDC")
    assert after["claimable"] == before["claimable"] - leaf.amount
    assert after["paid"] == before["paid"] + leaf.amount
    with pytest.raises(ValueError, match="replayed"):
        model.claim("h", 0, "USDC", leaf, proof, leaf.person, leaf.recipient)
    assert model.balances("USDC") == after
    assert model.settlements["h", 0].claims["USDC"].root == claims.root


def test_boost_escrows_only_riding_weeks_and_shares_budget_with_late_uploads(factory):
    model = factory()
    boost = model.boost("brand", ["h"], 2_000_000, start_week=1, weeks=1)
    assert model.boosts[boost].funder == "brand"
    assert model.boosts[boost].schedule == (("h", 1, 2_000_000),)
    assert model.balances("USDC")["cash"] == model.balances("USDC")["held"] == 2_000_000
    close(model, 0)
    model.upload("prompt", "h", "p0", model.now, 0)
    late_ride_time = model.now + 1
    model.advance(model.launch + 2 * WEEK + model.config.grace - 1)
    model.upload("late", "h", "p1", late_ride_time, 0)
    first = close(model, 1)
    assert paid(first) == {"p0": 650000, "p1": 650000}
    second = close(model, 2)
    assert paid(second) == {}
    assert model.balances("USDC")["held"] == 700000
    assert model.balances("USDC")["fees"] == 0
    assert second.dung.potential == 0  # cash never creates DUNG
    assert first.claims["USDC"].root == model.settlements["h", 1].claims["USDC"].root


def test_boost_no_riders_never_refunds_or_spills_to_post_window_rides(factory):
    model = factory()
    model.boost("brand", ["h"], 1000000, 1, 1)
    for week in range(3):
        close(model, week)
    riders(model, 5)
    model.set_board("h", ["p0"], "p1")
    assert paid(close(model, 3)) == {}
    for week in range(4, 29):
        close(model, week)
    assert model.balances("USDC")["held"] == 1000000
    assert all(tranche.bucket == "pool" for tranche in model.tranches)
    assert {tranche.born for tranche in model.tranches} == {1}


def test_boost_window_filter_and_posting_boundaries(factory):
    model = factory()
    for duration in [0, 14]:
        with pytest.raises(ValueError):
            model.boost("brand", ["h"], 1000, 1, duration)
    with pytest.raises(ValueError):
        model.boost("brand", ["h"], 1000, 0, 1)
    with pytest.raises(ValueError):
        model.boost("brand", ["h", "h"], 1000, 1, 1)
    model.add_hill("other")
    boost = model.boost("brand", ["h", "other"], 2_000_005, 1, 1)
    assert sum(amount for _, _, amount in model.boosts[boost].schedule) == 2_000_005
    close(model, 0)
    model.upload("prewindow", "h", "p0", model.launch + WEEK - 1, 0)
    assert paid(close(model, 1)) == {}


@pytest.mark.parametrize("count", [0, 1, 4, 5])
def test_constant_dung_field_and_fixed_halves(factory, count):
    model = factory()
    model.register_person('founder','founder')
    model.register_person('later','later')
    model.pledge("founder", "h", "lst", 100)
    model.pledge("later", "h", "lst", 100, lock_weeks=26)
    close(model, 0)
    riders(model, count)
    model.set_board("h", ["p0"] if count else [], "p1" if count > 1 else None)
    dung = close(model, 1).dung
    if count < 5:
        assert dung.potential == 0
        assert dung.riders == dung.backers == {}
    else:
        assert dung.potential == 5_000_000
        assert sum(dung.riders.values()) == 2_500_000
        assert dung.backers == {"founder": 1_666_667, "later": 833_333}
        assert dung.unminted == 0


def test_dung_has_no_halving_or_field_backpay_and_bonus_expires(factory):
    model = factory()
    model.register_person('founder','founder')
    model.register_person('later','later')
    model.pledge("founder", "h", "lst", 100)
    model.pledge("later", "h", "lst", 100, lock_weeks=26)
    riders(model, 4)
    assert close(model, 0).dung.potential == 0
    riders(model, 5)
    model.set_board("h", ["p0"], "p1")
    first = close(model, 1).dung
    for week in range(2, 27):
        close(model, week)
    riders(model, 5)
    later = close(model, 27).dung
    assert first.potential == later.potential == 5_000_000
    assert later.backers == {"founder": 1_250_000, "later": 1_250_000}


@pytest.mark.parametrize("bond_week", [0, 25, 26])
def test_founder_bonus_covers_hills_own_26_full_bonded_weeks(factory, bond_week):
    model = factory()
    model.advance(model.launch + bond_week * WEEK + DAY)
    model.pledge("founder", "h", "lst", 100)
    model.pledge("later", "h", "lst", 100, lock_weeks=26)
    first_week = bond_week + 1
    assert not model.openings["h", bond_week][1]
    for week in range(first_week, first_week + 26):
        model.advance(model.launch + week * WEEK)
        weights = dict(model.openings["h", week][2])
        assert weights["founder"] == 2 * weights["later"], week
    model.advance(model.launch + (first_week + 26) * WEEK)
    weights = dict(model.openings["h", first_week + 26][2])
    assert weights["founder"] == weights["later"]


def test_boost_late_upload_joins_ridden_week_before_settlement(factory):
    model = factory()
    model.boost("brand", ["h"], 1000000, 1, 1)
    close(model, 0)
    ridden_at = model.now
    model.advance(model.launch + 2 * WEEK + model.config.grace - 1)
    model.upload("late", "h", "p0", ridden_at, 0)
    assert paid(close(model, 1)) == {"p0": 650000}


@pytest.mark.parametrize("offset,expected", [(-1, {"p0": 325000, "p1": 325000}), (0, {"p0": 650000}), (1, {"p0": 650000})])
def test_boost_upload_cutoff_is_fixed_even_with_delayed_keeper(factory, offset, expected):
    model = factory()
    model.boost("brand", ["h"], 1000000, 1, 1)
    close(model, 0)
    model.upload("prompt", "h", "p0", model.now, 0)
    ridden_at = model.launch + 2 * WEEK - 1
    cutoff = model.launch + 2 * WEEK + model.config.grace
    model.advance(cutoff + offset)
    model.upload("late", "h", "p1", ridden_at, 0)
    model.advance(cutoff + DAY)
    first = close(model, 1)
    assert paid(first) == expected
    model.upload("after-root", "h", "p2", ridden_at, 0)
    assert paid(close(model, 2)) == {}
    assert model.settlements["h", 1].claims["USDC"].root == first.claims["USDC"].root


def test_boost_late_upload_preserves_field_board_dung_and_ordinary_upload_week(factory):
    model = factory()
    model.pledge("founder", "h", "lst", 100)
    model.boost("brand", ["h"], 1000000, 1, 1)
    close(model, 0)
    riders(model, 4)
    model.set_board("h", ["p0"], "p1")
    ridden_at = model.launch + 2 * WEEK - 1
    model.advance(model.launch + 2 * WEEK + 1)
    frozen = model.snapshots["h", 1]
    model.upload("late-fifth", "h", "p4", ridden_at, 1_000_000)
    model.set_board("h", ["p4"], "p4")
    first = close(model, 1)
    assert paid(first) == dict.fromkeys(["p0", "p1", "p2", "p3", "p4"], 130000)
    assert model.snapshots["h", 1] == frozen
    assert not frozen.field and frozen.board == ("p0",) and frozen.legend == "p1"
    assert first.dung.potential == 0
    model.sponsor("h", 1000000)
    second = close(model, 2)
    assert paid(second) == {"p4": 1000000}
    assert second.dung.potential == 1_000_000
    assert model.balances("USDC")["held"] == 350000


def test_boost_uses_each_ride_week_and_keeps_unused_buckets_until_window_end(factory):
    model = factory()
    boost = model.boost("brand", ["h"], 2000000, 1, 2)
    assert model.boosts[boost].schedule == (("h", 1, 1000000), ("h", 2, 1000000))
    close(model, 0)
    model.upload("first-week", "h", "p0", model.now, 0)
    model.advance(model.launch + 2 * WEEK + 1)
    model.upload("late-first-week", "h", "p1", model.launch + 2 * WEEK - 1, 0)
    model.upload("current-week", "h", "p2", model.now, 0)
    assert paid(close(model, 1)) == {"p0": 325000, "p1": 325000}
    # The late first-week receipt cannot also take the second week's boost.
    assert paid(close(model, 2)) == {"p2": 650000}
    assert model.balances("USDC")["held"] == 700000


def test_partial_bond_week_has_no_mixed_prebond_dung(factory):
    model = factory()
    model.register_person('founder','founder')
    riders(model, 5)
    model.advance(model.now + 2 * DAY)
    model.pledge("founder", "h", "lst", 100)
    model.upload("postbond", "h", "p5", model.now, 1_000_000)
    assert close(model, 0).dung.potential == 0
    model.upload("prebond-late", "h", "p6", model.launch + DAY + 50, 1_000_000)
    model.upload("eligible", "h", "p7", model.now, 1_000_000)
    model.set_board("h", [], None)
    dung = close(model, 1).dung
    assert dung.potential == 1_000_000
    assert dung.riders.get("p6", 0) == 0
    assert dung.riders["p7"] == 175000
    assert dung.unminted == 325000


def test_every_frozen_asset_gets_a_root_even_in_empty_week(factory):
    model = factory()
    result = close(model, 0)
    assert set(result.claims) == {"lst", "USDC"}
    assert all(claims.root.total == 0 for claims in result.claims.values())
