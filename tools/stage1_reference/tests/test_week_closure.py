from copy import deepcopy

import pytest

from .conftest import close, riders
from .test_dung_claims import ready


def pay_cash(model, week, asset):
    claims = model.settlements['h', week].claims[asset]
    for leaf in claims.leaves:
        model.claim('h', week, asset, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)


def close_cash(model, week):
    for asset in list(model.settlements['h', week].claims):
        model.close_cash_claim_set('h', week, asset)
        assert model.close_funding('h', week, asset) == 'publisher'


def test_paid_week_closes_without_changing_any_equality_or_reopening(factory):
    model = factory()
    riders(model, 5)
    model.sponsor('h', 10000)
    claims = close(model, 0).claims['USDC']
    pay_cash(model, 0, 'USDC')
    balances = {asset: model.balances(asset) for asset in model.ledgers}
    close_cash(model, 0)
    assert ('h', 0) not in model.settlements
    assert balances == {asset: model.balances(asset) for asset in model.ledgers}
    assert model.check()
    for attempt in [lambda: model.settle('h', 0),
                    lambda: model.open_funding('h', 0, 'USDC'),
                    lambda: model.claim('h', 0, 'USDC', claims.leaves[0], claims.proof(0), 'p0', 'wallet0')]:
        before = deepcopy(model.__dict__)
        with pytest.raises(ValueError):
            attempt()
        assert model.__dict__ == before


def test_keeper_outage_never_closes_unpaid_claims_and_riders_can_still_claim(factory):
    model = factory()
    riders(model, 5)
    model.sponsor('h', 10000)
    close(model, 0)
    before = deepcopy(model.__dict__)
    for attempt in [lambda: model.close_cash_claim_set('h', 0, 'USDC'),
                    lambda: model.close_funding('h', 0, 'USDC')]:
        with pytest.raises(ValueError):
            attempt()
        assert model.__dict__ == before
    pay_cash(model, 0, 'USDC')
    close_cash(model, 0)
    assert model.check()


@pytest.mark.parametrize('expire', [False, True])
def test_closed_week_retains_original_holds_for_release_or_expiry(factory, expire):
    model = factory()
    model.sponsor('h', 10000)
    close(model, 0)
    held = deepcopy(model.tranches)
    before = model.balances('USDC')
    close_cash(model, 0)
    assert model.tranches == held
    assert model.balances('USDC') == before
    if expire:
        model.advance(model.launch + 27 * 604800 + model.config.grace)
        model.skip_empty('h', 16)
        model.skip_empty('h', 25)
        close(model, 26)
        assert all(t.bucket == 'pool' and t.born == 0 for t in model.tranches)
    else:
        riders(model, 5)
        close(model, 1)
        pay_cash(model, 1, 'USDC')
        assert model.balances('USDC')['paid'] > 0
    assert model.check()


def test_opened_empty_skipped_week_refunds_original_payer_and_cannot_reopen(factory):
    model = factory()
    model.open_funding('h', 0, 'USDC', payer='original')
    model.open_funding('h', 0, 'USDC', payer='later')
    model.advance(model.launch + 604800 + model.config.grace)
    model.skip_empty('h', 0)
    assert model.close_funding('h', 0, 'USDC') == 'original'
    with pytest.raises(ValueError):
        model.open_funding('h', 0, 'USDC')
    assert model.check()


def test_dung_records_close_only_after_both_roles_and_keep_lifetime_issuance(factory):
    model = ready(factory)
    model.publish_dung('h', 1)
    sets = {role: model.publish_dung_claim_set('h', 1, 'mint', role) for role in ('riders', 'backers')}
    with pytest.raises(ValueError):
        model.close_dung_mint('h', 1)
    model.advance(model.now + 172800)
    for role, claims in sets.items():
        for leaf in claims.leaves:
            model.claim_dung('h', 1, 'mint', role, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)
        model.close_dung_claim_set('h', 1, role)
        with pytest.raises(ValueError):
            model.publish_dung_claim_set('h', 1, 'mint', role)
    lifetime = (model.dung_allocated, model.dung_minted)
    balances = {asset: model.balances(asset) for asset in model.ledgers}
    assert model.close_dung_mint('h', 1) == 'publisher'
    assert ('h', 1) not in model.dung_records
    assert (model.dung_allocated, model.dung_minted) == lifetime
    assert balances == {asset: model.balances(asset) for asset in model.ledgers}
    for attempt in [lambda: model.publish_dung('h', 1),
                    lambda: model.publish_dung_claim_set('h', 1, 'mint', 'riders'),
                    lambda: model.publish_dung_claim_set('h', 1, 'mint', 'backers')]:
        with pytest.raises(ValueError):
            attempt()
    assert model.check()
