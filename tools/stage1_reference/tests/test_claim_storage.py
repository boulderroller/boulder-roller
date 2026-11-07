from copy import deepcopy
from dataclasses import replace

import pytest

from tools.stage1_reference.merkle import ClaimSet, Leaf, parent
from .conftest import close, riders
from .test_dung_claims import ready


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_publisher_duplicate_person_allocation_pays_each_index_once(factory, order):
    model = factory()
    riders(model, 5)
    model.sponsor('h', 10000)
    claims = close(model, 0).claims['USDC']
    total = claims.root.total
    leaves = (Leaf(0, 'p0', 'wallet0', total // 2), Leaf(1, 'p0', 'wallet0', total - total // 2))
    nodes = tuple(leaf.node(claims.context) for leaf in leaves)
    malicious = ClaimSet(claims.context, leaves, (nodes, (parent(*nodes),)))
    model.settlements['h', 0].claims['USDC'] = malicious
    first, second = (leaves[i] for i in order)
    model.claim('h', 0, 'USDC', first, malicious.proof(first.index), 'p0', 'wallet0')
    model.claim('h', 0, 'USDC', second, malicious.proof(second.index), 'p0', 'wallet0')
    before = deepcopy(model.__dict__)
    with pytest.raises(ValueError, match='replayed'):
        model.claim('h', 0, 'USDC', first, malicious.proof(first.index), 'p0', 'wallet0')
    assert model.__dict__ == before


def test_cash_batch_bad_final_proof_and_duplicate_set_are_atomic(factory):
    model = factory()
    entries = []
    for week in range(2):
        riders(model, 5)
        model.sponsor('h', 10000)
        claims = close(model, week).claims['USDC']
        leaf = claims.leaves[0]
        entries.append(('h', week, leaf, claims.proof(leaf.index)))
    before = deepcopy(model.__dict__)
    bad = entries[1][:2] + (replace(entries[1][2], amount=1), entries[1][3])
    for values in ([entries[0], bad], [entries[0], entries[0]], [], entries * 3):
        with pytest.raises(ValueError):
            model.claim_batch('USDC', values, 'p0', 'wallet0')
        assert model.__dict__ == before
    assert model.claim_batch('USDC', entries, 'p0', 'wallet0') == sum(e[2].amount for e in entries)
    assert all(model.claim_bits['h', week, 'USDC'] == b'\x01' for week in range(2))


def test_dung_batch_preserves_both_roles_and_rollback(factory):
    model = ready(factory)
    model.publish_dung('h', 1)
    entries = []
    for role in ('riders', 'backers'):
        claims = model.publish_dung_claim_set('h', 1, 'mint', role)
        leaf = next(leaf for leaf in claims.leaves if leaf.person == 'p0')
        entries.append(('h', 1, role, leaf, claims.proof(leaf.index)))
    model.advance(model.now + 172800)
    before = deepcopy(model.__dict__)
    bad = entries[1][:3] + (replace(entries[1][3], recipient='redirect'), entries[1][4])
    with pytest.raises(ValueError):
        model.claim_dung_batch('mint', [entries[0], bad], 'p0', 'wallet0')
    assert model.__dict__ == before
    assert model.claim_dung_batch('mint', entries, 'p0', 'wallet0') == sum(e[3].amount for e in entries)
