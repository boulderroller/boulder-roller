import pytest
from copy import deepcopy
from tools.stage1_reference.model import DUNG_TSS_CEILING, DUNG_CLAIM_WAIT, WEEK
from .conftest import close, riders


def test_dung_claims_mint_once_without_touching_cash(factory):
    model = factory()
    model.configure_dung(20_000_000_000, 1)
    model.pledge('p0', 'h', 'lst', 100)
    close(model, 0)
    riders(model, 5)
    model.set_board('h', ['p0'], None)
    settlement = close(model, 1)
    cash = model.balances('lst').copy()
    sets = model.dung_claim_sets('h', 1, 'dung-mint')
    model.publish_dung('h', 1)
    for role in sets:
        model.publish_dung_claim_set('h', 1, 'dung-mint', role)
    assert sets['riders'].root.total == sum(settlement.dung.riders.values())
    assert sets['backers'].root.total == sum(settlement.dung.backers.values())
    leaf = sets['riders'].leaves[0]
    with pytest.raises(ValueError, match='DUNG claim wait'):
        model.claim_dung('h', 1, 'dung-mint', 'riders', leaf, sets['riders'].proof(leaf.index), leaf.person, leaf.recipient)
    model.advance(model.now + 172800)
    for role, claims in sets.items():
        for leaf in claims.leaves:
            model.claim_dung('h', 1, 'dung-mint', role, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)
            with pytest.raises(ValueError):
                model.claim_dung('h', 1, 'dung-mint', role, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)
    assert model.dung_minted == settlement.dung.potential - settlement.dung.unminted
    assert model.balances('lst') == cash


def ready(factory, *, tss=5_000_000, start=1):
    model = factory()
    if start is not None:
        model.configure_dung(DUNG_TSS_CEILING, start)
    model.pledge('p0', 'h', 'lst', 100)
    close(model, 0)
    for i in range(5):
        model.upload(f'r{i}', 'h', f'p{i}', model.now, tss if i == 0 else 0)
    model.set_board('h', ['p0'], None)
    close(model, 1)
    return model


@pytest.mark.parametrize('tss', [DUNG_TSS_CEILING - 1, DUNG_TSS_CEILING])
def test_ceiling_boundaries(factory, tss):
    model = ready(factory, tss=tss)
    assert model.publish_dung('h', 1).potential == tss


@pytest.mark.parametrize('tss', [DUNG_TSS_CEILING + 1, 2**64 - 1])
def test_ceiling_refuses_excess_atomically_but_does_not_block_cash(factory, tss):
    model = ready(factory, tss=tss)
    before = deepcopy(model.__dict__)
    with pytest.raises(ValueError, match='TSS ceiling'):
        model.publish_dung('h', 1)
    assert model.__dict__ == before
    assert ('h', 1) in model.settlements


def test_unset_prestart_and_prospective_admin_changes(factory):
    model = ready(factory, start=None)
    assert model.dung_tss_ceiling == 0
    model.configure_dung(0, None)
    with pytest.raises(ValueError, match='start unset'):
        model.publish_dung('h', 1)
    with pytest.raises(ValueError, match='start unset'):
        model.skip_dung_empty('h', 1)
    with pytest.raises(ValueError, match='admin'):
        model.configure_dung(DUNG_TSS_CEILING, 3, authority='publisher')
    with pytest.raises(ValueError, match='prospective'):
        model.configure_dung(DUNG_TSS_CEILING, 1)
    model.configure_dung(DUNG_TSS_CEILING, 3)
    with pytest.raises(ValueError, match='before start'):
        model.publish_dung('h', 1)
    model.advance(model.launch + 3 * WEEK)
    riders(model, 5)
    model.advance(model.launch + 4 * WEEK + model.config.grace)
    model.publish_dung('h', 3)  # no false empty attestation for weeks 1 and 2
    model.configure_dung(DUNG_TSS_CEILING + 1, 3)  # active start unchanged
    model.configure_dung(1, None)
    with pytest.raises(ValueError, match='prospective'):
        model.configure_dung(1, 3)


def test_admin_ceiling_revision_admits_new_limit(factory):
    model = ready(factory, tss=DUNG_TSS_CEILING + 1)
    model.configure_dung(DUNG_TSS_CEILING + 1, 1)
    assert model.publish_dung('h', 1).potential == DUNG_TSS_CEILING + 1


def test_each_late_role_publication_has_its_own_wait_and_survives_policy_change(factory):
    model = ready(factory)
    model.publish_dung('h', 1)
    model.advance(model.now + 3 * 86400)
    rider_at = model.now
    riders_set = model.publish_dung_claim_set('h', 1, 'mint', 'riders')
    model.configure_dung(1, None)
    model.advance(model.now + 60)
    backer_at = model.now
    backers_set = model.publish_dung_claim_set('h', 1, 'mint', 'backers')
    def pay(role, claims):
        leaf = claims.leaves[0]
        return model.claim_dung('h', 1, 'mint', role, leaf, claims.proof(leaf.index), leaf.person, leaf.recipient)
    model.advance(rider_at + DUNG_CLAIM_WAIT - 1)
    before = deepcopy(model.__dict__)
    with pytest.raises(ValueError, match='DUNG claim wait'):
        pay('riders', riders_set)
    assert model.__dict__ == before
    model.advance(rider_at + DUNG_CLAIM_WAIT)
    assert pay('riders', riders_set) > 0
    with pytest.raises(ValueError, match='DUNG claim wait'):
        pay('backers', backers_set)
    model.advance(backer_at + DUNG_CLAIM_WAIT)
    assert pay('backers', backers_set) > 0
