"""Independent allocation -> Merkle-sum -> local-program differential vectors.

Runtime mode reads public namespaces/recipients and a scenario from JSON stdin.
No account balances, expected allocations or roots are supplied by the program.
"""
from dataclasses import asdict
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

from .arithmetic import median_cap
from .config import load_config
from .merkle import ClaimSet, Context, Leaf, parent, encode, empty
from .model import Model, WEEK

BUCKETS = ('full', 'ascents', 'top', 'legend', 'cap')
CASES = {
    'zero': (0, 0, None), 'one': (1, 1, 0), 'four': (4, 4, 0),
    'five': (5, 5, 0), 'empty-board': (5, 0, None), 'tied-board': (5, 5, 1),
    'cap-redistribution': (5, 10, 0), 'odd-median': (5, 3, None),
    'even-median': (4, 0, None), 'zeros-excluded': (5, 10, None),
    'release': (0, 0, None), 'expire': (0, 0, None),
}


def key(n):
    raw = bytes([n]) * 32
    num, result = int.from_bytes(raw, 'big'), ''
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    while num:
        num, d = divmod(num, 58)
        result = alphabet[d] + result
    return result


def vector(request):
    name = request.get('case', 'five')
    count, seats, legend = CASES[name]
    people = request.get('people', [key(i + 10) for i in range(12)])
    recipients = request.get('recipients', [key(i + 30) for i in range(12)])
    deployment, city, hill, asset = (request.get(k, key(i + 1)) for i, k in enumerate(('deployment', 'city', 'hill', 'asset')))
    model = Model(load_config(), 1791201600, city=city, deployment=deployment)
    model.allow_asset(asset, 9, Fraction(1))
    model.add_hill(hill)
    for p, r in zip(people, recipients):
        model.register_person(p, r)
    model.pledge('backer', hill, asset, 10_000_000_000)
    model.advance(model.launch + WEEK + model.config.grace)
    model.skip_empty(hill, 0)
    model.observe_rate(asset, Fraction(2))
    # Model actions, not inserted ledger/tranche values.
    harvested = int(request.get('harvest', 1000 if name != 'zeros-excluded' else 7))
    model.harvest(next(iter(model.lots)), harvested)
    model.set_board(hill, people[:seats], people[legend] if legend is not None else None)

    def uploads(n, many=False):
        for i in range(n):
            for day in range(7 if many and i == 0 else 1):
                model.upload(f'{model.week}-{i}-{day}', hill, people[i], model.now - day * 86400, 1_000_000)

    uploads(count, name == 'cap-redistribution')
    steps, skipped, refused = [], [0], []

    def output(week):
        model.advance(model.launch + (week + 1) * WEEK + model.config.grace)
        settlement = model.settle(hill, week)
        claims = settlement.claims[asset]
        frozen = {'measurement': asdict(model.snapshots[hill, week]), 'cap': settlement.caps.get(asset, 0)}
        commitment = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':'), default=str).encode()).hexdigest()
        holds = {}
        for t in model.tranches:
            if t.asset != asset:
                continue
            row = holds.setdefault(str(t.born), {'buckets': [0]*5, 'pool': 0})
            if t.bucket == 'pool':
                row['pool'] += t.amount
            else:
                row['buckets'][BUCKETS.index(t.bucket)] += t.amount
        before = model.balances(asset)
        leaves = []
        for leaf in claims.leaves:
            proof = claims.proof(leaf.index)
            leaves.append({**asdict(leaf), 'proof': [{'hash': n.hash.hex(), 'sum': str(n.total)} for n in proof]})
            model.claim(hill, week, asset, leaf, proof, leaf.person, leaf.recipient)
        steps.append({'week': week, 'root': claims.root.hash.hex(), 'total': str(claims.root.total),
                      'count': len(claims.leaves), 'cap': str(settlement.caps.get(asset, 0)),
                      'snapshot': commitment, 'holds': holds, 'leaves': leaves,
                      'claimed_bitmap': model.claim_bits[hill, week, asset].hex(),
                      'before_claims': before, 'after_claims': model.balances(asset)})
        balances = {mint: model.balances(mint) for mint in model.ledgers}
        for mint in list(settlement.claims):
            model.close_cash_claim_set(hill, week, mint)
            model.close_funding(hill, week, mint)
        after_close = {mint: model.balances(mint) for mint in model.ledgers}
        assert balances == after_close
        try:
            model.open_funding(hill, week, asset)
        except ValueError:
            pass
        else:
            raise AssertionError('closed funding recreated')
        steps[-1]['closure'] = {'accounting_unchanged': balances == after_close,
            'funding_absent': not any(k[:2] == (hill, week) for k in model.funding_records),
            'claim_sets_absent': (hill, week) not in model.settlements,
            'next_week': model.hills[hill].next_settle, 'recreation_refused': True}

    output(1)
    if name == 'release':
        model.set_board(hill, people[:5], people[0])
        uploads(5)
        output(2)
        model.advance(model.launch + 10 * WEEK + model.config.grace)
        model.skip_empty(hill, 9)
        skipped.extend(range(3, 10))
    if name == 'expire':
        model.advance(model.launch + 27 * WEEK + model.config.grace)
        model.skip_empty(hill, 17)
        model.skip_empty(hill, 25)
        skipped.extend(range(2, 26))
        for week in (26, 27):
            if week == 27:
                model.advance(model.launch + (week + 1) * WEEK + model.config.grace)
                try:
                    model.skip_empty(hill, week)
                except ValueError:
                    refused.append(week)
                else:
                    raise AssertionError('original hold maturity must block skip')
            output(week)
        model.advance(model.launch + 29 * WEEK + model.config.grace)
        model.skip_empty(hill, 28)
        skipped.append(28)
    return {'evidence': 'offline allocation oracle; program consumes funded roots',
            'context': [deployment, city, hill, 1, asset], 'harvest': harvested,
            'skipped_weeks': skipped, 'refused_hold_skips': refused,
            'next_week': model.hills[hill].next_settle,
            'steps': steps, 'deposited': model.ledgers[asset].deposited,
            'lot_units': sum(l.units for l in model.lots.values() if l.asset == asset)}


def fixture():
    return {'cases': {name: vector({'case': name}) for name in CASES},
            'median_boundaries': [
                {'values': values, 'cap': median_cap(dict(enumerate(values)), Fraction(3))}
                for values in ([1, 2, 3], [1, 2], [0, 1, 2, 0], [0, 0], [1, 1, 7, 7], [1, 2, 2, 9, 20])
            ]}


def merkle_probe(request):
    """Synthetic tree complexity/adversarial evidence, never riding allocation."""
    context = Context(*request['context'])
    person, recipient = request.get('person'), request.get('recipient')
    if request['kind'] == 'payments':
        leaves = tuple(Leaf(i, p, r, int(amount)) for i, (p, r, amount) in enumerate(request['payments']))
        nodes = tuple(leaf.node(context) for leaf in leaves) or (empty(context),)
        levels = [nodes]
        while len(nodes) > 1:
            nodes = tuple(parent(nodes[i], nodes[i+1] if i+1 < len(nodes) else empty(context))
                          for i in range(0, len(nodes), 2))
            levels.append(nodes)
        claims = ClaimSet(context, leaves, tuple(levels))
        indices = request.get('indices', list(range(len(leaves))))
    elif request['kind'] == 'single':
        claims = ClaimSet.build(context, {person: int(request.get('amount', 100))}, {person: recipient})
        indices = [0]
    elif request['kind'] == 'duplicate':
        leaves = (Leaf(0, person, recipient, 100), Leaf(1, person, recipient, 100))
        nodes = tuple(leaf.node(context) for leaf in leaves)
        claims = ClaimSet(context, leaves, (nodes, (parent(*nodes),)))
        indices = [0, 1]
    else:
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        def pubkey(i):
            raw = hashlib.sha256(f'stage1-depth-person-{i}'.encode()).digest()
            n, result = int.from_bytes(raw, 'big'), ''
            while n:
                n, d = divmod(n, 58)
                result = alphabet[d] + result
            return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + result
        people = [person] + [pubkey(i) for i in range(65535)]
        claims = ClaimSet.build(context, dict.fromkeys(people, 1), dict.fromkeys(people, recipient))
        indices = [next(leaf.index for leaf in claims.leaves if leaf.person == person)]
    return {'root': claims.root.hash.hex(), 'total': str(claims.root.total), 'count': len(claims.leaves),
            'leaves': [{**asdict(claims.leaves[i]), 'proof': [{'hash': n.hash.hex(), 'sum': str(n.total)}
             for n in claims.proof(i)]} for i in indices]}


if __name__ == '__main__':
    path = Path(__file__).resolve().parents[2] / 'protocol/anchor/tests/fixtures/stage1_claim_vectors.json'
    if '--merkle-stdin' in sys.argv:
        print(json.dumps(merkle_probe(json.load(sys.stdin))))
    elif '--stdin' in sys.argv:
        print(json.dumps(vector(json.load(sys.stdin))))
    else:
        text = json.dumps(fixture(), indent=2) + '\n'
        if '--check' in sys.argv:
            if path.read_text() != text:
                raise SystemExit('claim vectors differ from independent oracle')
            print(f'{len(CASES)} allocation/claim traces and 6 median boundary vectors match')
        else:
            path.write_text(text)
