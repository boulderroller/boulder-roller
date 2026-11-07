"""Independent model actions -> frozen opening weights -> DUNG role claims.

--stdin accepts only public identities and a case name, never allocations.
"""
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
import sys
from pathlib import Path

from .claim_vectors import key
from .config import load_config
from .merkle import encode
from .model import Model, WEEK

CASES = ('five', 'field-four', 'zero-tss', 'missing-legend', 'no-board',
         'zero-weight', 'partial-week', 'founder-26', 'founder-27',
         'lock-13', 'lock-expired', 'loss', 'rounding-1', 'rounding-3',
         'boundary-bond', 'late-prebond', 'ceiling-minus-one', 'ceiling',
         'unregistered-rider', 'unregistered-backer', 'unregistered-all')


def vector(request):
    name = request.get('case', 'five')
    if name not in CASES:
        raise ValueError('unknown case')
    deployment, city, hill, mint = (request.get(k, key(i + 1)) for i, k in enumerate(('deployment', 'city', 'hill', 'mint')))
    people = request.get('people', [key(i + 10) for i in range(12)])
    recipients = request.get('recipients', [key(i + 30) for i in range(12)])
    model = Model(load_config(), 1791201600, city=city, deployment=deployment)
    model.configure_dung(20_000_000_000, 1)
    model.allow_asset('lst', 9, Fraction(1))
    model.add_hill(hill)
    for i, (p, r) in enumerate(zip(people, recipients)):
        if name == 'unregistered-all' or (name == 'unregistered-rider' and i == 4) or (name == 'unregistered-backer' and i == 1):
            continue
        model.register_person(p, r)
    bond_at = model.launch if name == 'boundary-bond' else model.launch + 100
    model.advance(bond_at)
    model.pledge(people[0], hill, 'lst', 10_000_000_000)
    model.pledge(people[1], hill, 'lst', 5_000_000_000, lock_weeks=26)
    model.pledge(people[0], hill, 'lst', 5_000_000_000, lock_weeks=13)
    week = {'partial-week': 0, 'founder-26': 26, 'founder-27': 27,
            'lock-13': 13, 'lock-expired': 14}.get(name, 1)
    rate = Fraction(1, 10**12) if name == 'zero-weight' else Fraction(1, 3) if name == 'loss' else Fraction(1)
    model.observe_rate('lst', rate)
    model.advance(max(model.now, model.launch + week * WEEK))
    opening = {'basis': [0]*8, 'backing': [0]*8}
    # Produce the aggregate from independent per-lot model semantics.
    if week:
        for lot in model.lots.values():
            if lot.exiting or lot.lock_end is None:
                continue
            lock = lot.lock_weeks if model.now < lot.lock_end else 0
            bucket = (4 if lot.founding else 0) + (0, 13, 26, 52).index(lock)
            opening['basis'][bucket] += lot.basis
            opening['backing'][bucket] += min(lot.basis, int(lot.units * model.rate(lot)))
    count = 4 if name == 'field-four' else 5
    for i in range(count):
        tss = 0 if name == 'zero-tss' else (int(name[-1]) if i == 0 else 0) if name.startswith('rounding-') else 1_000_000
        if name.startswith('ceiling'):
            tss = (20_000_000_000 - (name == 'ceiling-minus-one')) if i == 0 else 0
        model.upload(f'r-{i}', hill, people[i], model.now, tss)
    if name == 'late-prebond':
        model.upload('prebond', hill, people[5], model.launch + 50, 99_000_000)
    model.set_board(hill, [] if name == 'no-board' else people[:3], None if name == 'missing-legend' else people[1])
    model.advance(model.launch + (week + 1) * WEEK + model.config.grace)
    for w in range(week + 1):
        result = model.settle(hill, w)
    snapshot = model.snapshots[hill, week]
    eligible = [r for r in snapshot.rides if r.ridden_at >= bond_at]
    source = hashlib.sha256(encode({
        'snapshot': json.loads(json.dumps(asdict(snapshot), default=str)), 'opening': opening,
    })).hexdigest()
    input_data = {'source_snapshot': source, 'field_count': count + (name == 'late-prebond'),
                  'postbond_tss_micros': sum(r.tss for r in eligible),
                  'top_count': len(snapshot.board), 'ascent_count': sum(model._ascents(replace(snapshot, rides=tuple(eligible))).values()),
                  'earned_legend': snapshot.legend is not None, 'opening': opening}
    sets = model.dung_claim_sets(hill, week, mint)
    if snapshot.bonded and snapshot.field:
        for start in range(1, week, 16):
            model.skip_dung_empty(hill, min(week - 1, start + 15))
        model.publish_dung(hill, week)
        for role in sets:
            model.publish_dung_claim_set(hill, week, mint, role)
        model.advance(model.now + 172800)
    roots = []
    for role, claims in sets.items():
        leaves = []
        for leaf in claims.leaves:
            proof = claims.proof(leaf.index)
            leaves.append({**asdict(leaf), 'proof': [{'hash': n.hash.hex(), 'sum': str(n.total)} for n in proof]})
            model.claim_dung(hill, week, mint, role, leaf, proof, leaf.person, leaf.recipient)
        roots.append({'root': claims.root.hash.hex(), 'total': str(claims.root.total), 'leaf_count': len(leaves), 'leaves': leaves,
                      **({'claimed_bitmap': model.dung_claim_bits[hill, week, role].hex()}
                         if (hill, week, role) in model.dung_claim_bits else {})})
    closure = None
    if snapshot.bonded and snapshot.field:
        lifetime = (model.dung_allocated, model.dung_minted)
        for role in sets:
            model.close_dung_claim_set(hill, week, role)
        model.close_dung_mint(hill, week)
        assert lifetime == (model.dung_allocated, model.dung_minted)
        try:
            model.publish_dung(hill, week)
        except ValueError:
            pass
        else:
            raise AssertionError('closed DUNG record republished')
        closure = {'mint_record_absent': (hill, week) not in model.dung_records,
                   'lifetime_unchanged': True, 'republication_refused': True,
                   'next_week': model.dung_next_week[hill]}
    dung = result.dung
    input_data['payable_role_totals'] = [sum(dung.riders.values()), sum(dung.backers.values())]
    return {'case': name, 'context': [deployment, city, hill, week, mint], 'week': week,
            'bonded_at': bond_at, 'input': input_data,
            'opening_weight_quarters': str(sum(w for _, w in snapshot.backers) * 4),
            'owner_weights_quarters': {p: str(w * 4) for p, w in snapshot.backers if w > 0},
            'admitted': snapshot.bonded and snapshot.field,
            'allocation': {'potential': dung.potential, 'riders': sum(dung.riders.values()),
                           'backers': sum(dung.backers.values()), 'unminted': dung.unminted},
            'minted': model.dung_minted, 'roots': roots, 'closure': closure}


def fixture():
    return {'evidence': 'offline synthetic riding, independently modeled allocation and claims',
            'cases': {name: vector({'case': name}) for name in CASES}}


if __name__ == '__main__':
    result = vector(json.load(sys.stdin)) if '--stdin' in sys.argv else fixture()
    if '--check' in sys.argv:
        retained = Path(__file__).resolve().parents[2] / 'protocol/anchor/tests/fixtures/stage1_dung_vectors.json'
        assert json.loads(retained.read_text()) == result, 'DUNG vectors stale'
        print(f'{len(CASES)} DUNG vectors match')
    else:
        print(json.dumps(result, indent=2))
