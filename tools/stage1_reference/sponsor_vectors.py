"""USDC sponsor/boost oracle traces for the real-token local validator.

Only namespaces and scenario names enter from the program. Sporting allocations,
holds and schedules are computed by the independent ratified model.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

from .claim_vectors import BUCKETS, key
from .config import load_config
from .merkle import ClaimSet, Context
from .model import Model, USDC, WEEK, DAY

CASES = [f'{kind}-{n}' for kind in ('cash', 'boost') for n in (0, 1, 4, 5)] + [
    'retry', 'expire', 'grace-before', 'grace-at', 'late-five', 'coalesce', 'window-end',
    'window-start', 'age-seven', 'coalesce-retry', 'coalesce-expire', 'quiet-boost']


def vector(request):
    name = request.get('case', 'boost-5')
    deployment, city, hill, mint = (request.get(k, key(i+1)) for i, k in enumerate(('deployment', 'city', 'hill', 'mint')))
    people = request.get('people', [key(i+10) for i in range(5)])
    recipients = request.get('recipients', [key(i+30) for i in range(5)])
    m = Model(load_config(), 1791201600, city=city, deployment=deployment)
    m.add_hill(hill)
    for p, r in zip(people, recipients):
        m.register_person(p, r)
    cash = name.startswith('cash-')
    count = int(name.rsplit('-', 1)[1]) if name.startswith(('cash-', 'boost-')) else 0
    duration = 3 if name == 'coalesce-retry' else 2 if name in ('retry', 'quiet-boost') else 1
    amounts = [1000, 1000] if name == 'coalesce-retry' else [101, 103] if name == 'coalesce-expire' else [1, 1] if name == 'coalesce' else [10001]
    if not cash:
        amounts = [duration * 1_000_000 + amount for amount in amounts]
    start = 13 if name == 'quiet-boost' else 1
    sources = []
    if cash:
        m.sponsor(hill, amounts[0])
    else:
        sources = [m.boost('sponsor', [hill], amount, start, duration) for amount in amounts]
    steps = []
    prior = [[[0]*5 for _ in range(13)] for _ in sources]
    for i, source in enumerate(sources):
        for _, w, amount in m.boosts[source].schedule: prior[i][w-start][0] = amount
    pools = [0 for _ in sources]

    def output(week):
        nonlocal prior
        m.advance(m.launch+(week+1)*WEEK+DAY+10)
        result = m.settle(hill, week)
        original = result.claims[USDC]
        claims = ClaimSet.build(Context(deployment, city, hill, week, mint),
                                {leaf.person: leaf.amount for leaf in original.leaves}, m.recipients)
        # Coalesced holds retain all source IDs. Partition the remaining buckets
        # deterministically back into their escrow streams, without splitting or
        # allocating each source independently (which would change Hamilton dust).
        streams = [[[0]*5 for _ in range(13)] for _ in sources]
        capacity = [[list(row) for row in stream] for stream in prior]
        for i in range(len(sources)):
            for j in range(13):
                if week-(j+start) >= 26:
                    pools[i] += sum(capacity[i][j])
                    capacity[i][j] = [0]*5
        sponsor = {}
        for t in m.tranches:
            if t.kind == 'sponsor':
                row = sponsor.setdefault(str(t.born), {'buckets': [0]*5, 'pool': 0})
                if t.bucket == 'pool': row['pool'] += t.amount
                else: row['buckets'][BUCKETS.index(t.bucket)] += t.amount
                continue
            if t.bucket == 'pool': continue
            remaining, j, bucket = t.amount, t.born-start, BUCKETS.index(t.bucket)
            # Retain existing named buckets first, then split untouched full
            # money. Only cap excess may consume another named bucket. Never
            # recreate funds in a paid/retired stream on the next retry.
            allowed = [bucket] + ([0] if bucket else []) + ([1, 2, 3] if bucket == 4 else [])
            for old_bucket in allowed:
                for i, source in enumerate(sources):
                    if source not in (t.sources or (t.source,)): continue
                    take = min(remaining, capacity[i][j][old_bucket])
                    streams[i][j][bucket] += take
                    capacity[i][j][old_bucket] -= take
                    remaining -= take
            assert remaining == 0
        prior = streams
        snapshot = hashlib.sha256(json.dumps({'snapshot': asdict(m.snapshots[hill, week]),
            'rides': [asdict(r) for r in m.rides], 'cap': result.caps.get(USDC, 0)},
            sort_keys=True, default=str).encode()).hexdigest()
        leaves = [{**asdict(leaf), 'proof': [{'hash': node.hash.hex(), 'sum': str(node.total)}
                  for node in claims.proof(leaf.index)]} for leaf in claims.leaves]
        before = m.balances(USDC)
        for leaf in original.leaves:
            m.claim(hill, week, USDC, leaf, original.proof(leaf.index), leaf.person, leaf.recipient)
        steps.append({'week': week, 'root': claims.root.hash.hex(), 'total': str(claims.root.total),
            'count': len(leaves), 'cap': str(result.caps.get(USDC, 0)), 'snapshot': snapshot,
            'leaves': leaves, 'sponsor_holds': sponsor, 'streams': streams, 'pools': list(pools),
            'before_claims': before, 'after_claims': m.balances(USDC), 'dung': result.dung.potential})

    if name == 'quiet-boost':
        def quiet(through, refused=None):
            m.advance(m.launch + (max(through, refused or 0) + 1) * WEEK + DAY + 10)
            first, before = m.hills[hill].next_settle, m.balances(USDC)
            if refused is not None:
                try:
                    m.skip_empty(hill, refused)
                except ValueError:
                    pass
                else:
                    raise AssertionError('due/maturity must refuse skip')
            m.skip_empty(hill, through)
            assert m.balances(USDC) == before
            steps.append({'skip': True, 'week': through, 'start': first, 'refused': refused,
                          'after_claims': before})
        quiet(12, 13)
        output(13)
        output(14)
        quiet(30)
        quiet(38, 39)
        output(39)
        output(40)
        quiet(41)
        return {'case': name, 'amounts': amounts, 'duration': duration, 'start': start, 'cash': False,
                'schedule': [m.boosts[s].schedule for s in sources], 'steps': steps}
    if not cash:
        output(0)
    for i in range(count):
        m.upload(f'normal-{i}', hill, people[i], m.now, 1)
    m.set_board(hill, people[:count], people[0] if count else None)
    if name == 'coalesce':
        m.upload('one', hill, people[0], m.now, 1)
    if name in ('grace-before', 'grace-at', 'late-five'):
        if name == 'late-five':
            for i in range(4): m.upload(f'early-{i}', hill, people[i], m.now, 1)
            m.set_board(hill, people, people[0])
        ridden = m.launch+2*WEEK-1
        m.advance(m.launch+2*WEEK+DAY-(0 if name == 'grace-at' else 1))
        m.upload('late', hill, people[4] if name == 'late-five' else people[0], ridden, 1)
    if name == 'window-end':
        m.advance(m.launch+2*WEEK)
        m.upload('outside', hill, people[0], m.now, 1)
    if name == 'window-start':
        m.upload('first-second', hill, people[0], m.launch+WEEK, 1)
    if name == 'age-seven':
        m.advance(m.launch+2*WEEK+DAY//2)
        m.upload('seven-days-inclusive', hill, people[0], m.now-WEEK, 1)
    output(0 if cash else 1)
    if name in ('retry', 'coalesce-retry'):
        retry_count = 1 if name == 'coalesce-retry' else 5
        for i in range(retry_count): m.upload(f'retry-{i}', hill, people[i], m.now, 1)
        m.set_board(hill, people[:retry_count], people[0])
        output(2)
        if name == 'coalesce-retry':
            for i in range(5): m.upload(f'field-{i}', hill, people[i], m.now, 1)
            m.set_board(hill, people, people[0])
            output(3)
    if name in ('expire', 'coalesce-expire'):
        # Later riding cannot take the closed window; due week 1 pools at 27.
        for i in range(5): m.upload(f'after-window-{i}', hill, people[i], m.now, 1)
        m.set_board(hill, people, people[0])
        for week in range(2, 28): output(week)
    return {'case': name, 'amounts': amounts, 'duration': duration, 'start': start, 'cash': cash,
            'schedule': [m.boosts[s].schedule for s in sources], 'steps': steps}


if __name__ == '__main__':
    if '--stdin' in sys.argv:
        print(json.dumps(vector(json.load(sys.stdin))))
    else:
        path = Path(__file__).resolve().parents[2] / 'protocol/anchor/tests/fixtures/stage1_sponsor_vectors.json'
        text = json.dumps({'cases': {name: vector({'case': name}) for name in CASES}}, indent=2)+'\n'
        if '--check' in sys.argv:
            assert path.read_text() == text
            print(f'{len(CASES)} sponsor/boost oracle traces match')
        else:
            path.write_text(text)
