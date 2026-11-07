"""Independent frozen-input adapter for the milestone 0 arithmetic oracle.

Inputs are attestations, not proof of real riding. No backend imports. This
adapter deliberately uses the oracle's Fraction arithmetic and Merkle encoder.
"""
from collections import Counter, defaultdict
from fractions import Fraction
import json
import sys

from .arithmetic import apportion, median_cap, redistribute
from .merkle import ClaimSet, Context
from .config import load_config

POLICY = load_config()

NAMES = ("full", "ascents", "top", "legend", "cap")


def recompute(snapshot, sources, config=POLICY):
    candidates, held, pool, reserved = [], {}, {}, {}
    field = len(snapshot["field_people"]) >= config.field
    for source in sources:
        sid, born = source["id"], source["born"]
        held[sid], pool[sid], reserved[sid] = [0] * 5, 0, {}
        attributed = source.get("reserved", {})
        amounts = list(source["buckets"])
        if sum(attributed.values()) > amounts[4]:
            raise ValueError("reserved funds exceed custody")
        age = snapshot["context"][3] - born
        if source["due"] > snapshot["context"][3]:
            held[sid] = list(source["buckets"])
            reserved[sid] = dict(attributed)
        elif age >= config.held_weeks:
            pool[sid] = sum(source["buckets"])
        else:
            amounts[4] -= sum(attributed.values())
            for person, amount in attributed.items():
                if person in snapshot["recipients"]:
                    candidates.append((born, sid, "reserved:" + person, {person: amount}, {}))
                else:
                    held[sid][4] += amount
                    reserved[sid][person] = amount
            if ((source["kind"] == "yield" and not snapshot["live"]) or
                  (source.get("last_ride_week") is not None and snapshot["context"][3] > source["last_ride_week"])):
                held[sid] = [a+b for a,b in zip(held[sid], amounts)]
                continue
            ascent_weights = source["ascents"] if source["kind"] == "boost" else snapshot["ascents"]
            pieces = [(NAMES[i], n) for i, n in enumerate(amounts) if i and n]
            labels = {"every_rider_by_ascents": "ascents", "top_ten": "top", "local_legend": "legend"}
            pieces.extend((labels[k], n) for k, n in apportion(amounts[0], config.split).items() if n)
            for bucket, amount in pieces:
                weights = ascent_weights if bucket in ("ascents", "cap") else dict.fromkeys(snapshot["board"], 1) if bucket == "top" and field else {snapshot["legend"]: 1} if bucket == "legend" and field and snapshot["legend"] else {}
                shares = apportion(amount, weights)
                if shares:
                    candidates.append((born, sid, bucket, shares, ascent_weights))
                else:
                    held[sid][NAMES.index(bucket)] += amount
    candidates.sort(key=lambda c: (c[0], c[1].encode(), c[2].encode()))
    combined = defaultdict(int)
    for _, _, _, shares, _ in candidates:
        for person, amount in shares.items():
            combined[person] += amount
    cap = median_cap(combined, config.cap_multiplier)
    paid, assigned, remainders = defaultdict(int), defaultdict(lambda: defaultdict(int)), []
    for _, sid, bucket, shares, weights in candidates:
        spill = 0
        for person, amount in shares.items():
            take = min(amount, cap - paid[person])
            paid[person] += take
            assigned[sid][person] += take
            spill += amount - take
        if bucket.startswith("reserved:") and spill:
            person = bucket.split(":",1)[1]
            reserved[sid][person] = reserved[sid].get(person, 0) + spill
            held[sid][4] += spill
        else:
            remainders.append((sid, weights, spill))
    for sid, weights, spill in remainders:
        additions, remainder = redistribute(spill, weights, paid, cap)
        for person, amount in additions.items():
            paid[person] += amount
            assigned[sid][person] += amount
        held[sid][4] += remainder
    for sid, shares in assigned.items():
        for person, amount in shares.items():
            if person not in snapshot["recipients"] and amount:
                paid[person] -= amount
                reserved[sid][person] = reserved[sid].get(person, 0) + amount
                held[sid][4] += amount
    return {"payments": {p: n for p, n in paid.items() if n}, "cap": cap, "holds": held, "pool": pool, "reserved": reserved}


def recompute_dung(snapshot, config=POLICY):
    opening, week = snapshot['opening'], snapshot['context'][3]
    archive = opening['dung']
    hill, rates = archive['hill'], archive['rates']
    bond, boundary = hill['bonded_at'], opening['boundary']
    basis, backing, owners = [0]*8, [0]*8, defaultdict(int)
    eligible = hill['bonded'] and bond < boundary
    if eligible:
        for lot in archive['lots']:
            if lot['cancelled'] or lot['exiting']:
                continue
            slot = lot['asset_slot']
            founding = not lot['converted'] and 0 < lot['sequence'] <= hill['founding_cutoff'] and slot < 32 and bool(hill['founding_fresh_slots'] & (1 << slot))
            if not founding and not lot['converted'] and lot['sequence'] <= hill['founding_cutoff']:
                continue
            units, cost = lot['units'], lot['basis_lamports']
            if founding and not lot['founding']:
                needed = Fraction(cost*hill['quoted_denominators'][slot],hill['quoted_numerators'][slot])
                units = min(units,-(-needed.numerator//needed.denominator))
            lock = config.bond_lock_weeks if founding else lot['lock_weeks']
            end = bond+config.bond_lock_weeks*604800 if founding else lot['lock_end']
            if boundary >= end:
                lock = 0
            rate = rates[lot['mint']]
            value = min(cost,int(Fraction(units*rate['numerator'],rate['denominator'])))
            bucket = [0,13,26,52].index(lock)+(4 if founding else 0)
            basis[bucket] += cost
            backing[bucket] += value
            multiplier = config.founder_multiplier if founding and week-(bond-snapshot['launch'])//604800 <= config.season_weeks else 1
            owners[lot['owner']] += int(value*config.lock_weights[lock]*4)*multiplier
    rides = []
    for row in snapshot['rides'] if eligible else []:
        if 'ridden_at' in row:
            after = row.get('ridden_at_us',row['ridden_at']*1_000_000) >= bond*1_000_000
        elif row.get('bond_eligibility_digest') and type(row.get('post_bond')) is bool:
            after = row['post_bond']
        else:
            raise ValueError('missing historical bond eligibility')
        if after:
            rides.append(row)
    tss = sum(r['tss_micros'] for r in rides)
    ascents = dict(Counter(r['person'] for r in rides if r['paid_ascent']))
    fallback = {p:i for i,p in enumerate(sorted({l['owner'] for l in archive['lots']},key=lambda p:p.encode()))}
    ranks = {l['owner']:l.get('owner_rank',fallback[l['owner']]) for l in archive['lots']}
    measurement = {'opening':{'basis':basis,'backing':backing,'weights':dict(owners),'tie_ranks':{p:ranks[p] for p in owners},'bonded_at':bond},
                   'tss_micros':tss,'ascents':ascents}
    potential = int(Fraction(tss * config.dung_scale, config.tss_scale) * config.dung_per_tss) if len(snapshot['field_people']) >= config.field else 0
    halves = apportion(potential, config.dung_split)
    riders = defaultdict(int)
    weights = {'every_rider_by_ascents':ascents, 'top_ten':dict.fromkeys(snapshot['board'],1),
               'local_legend':{snapshot['legend']:1} if snapshot['legend'] else {}}
    for name, amount in apportion(halves.get('riders',0), config.rider_dung_split).items():
        for person, value in apportion(amount, weights[name],snapshot.get('rider_tie_ranks')).items():
            if person in snapshot['recipients']:
                riders[person] += value
    backers = {p:n for p,n in apportion(halves.get('backers',0),owners,ranks).items() if p in snapshot['recipients']}
    allocation = {'potential':potential,'riders':dict(riders),'backers':backers,'unminted':potential-sum(riders.values())-sum(backers.values())}
    roles = []
    for role in ('riders','backers'):
        context = snapshot['context'][:]
        context[4] += ':'+role
        claims = ClaimSet.build(Context(*context),allocation[role],snapshot['recipients'])
        roles.append({'context':context,'root':claims.root.hash.hex(),'total':claims.root.total,'count':len(claims.leaves),
            'leaves':[{'index':l.index,'person':l.person,'recipient':l.recipient,'amount':l.amount,
                       'leaf_hash':l.node(claims.context).hash.hex(),
                       'proof':[{'hash':n.hash.hex(),'sum':n.total} for n in claims.proof(l.index)]} for l in claims.leaves]})
    return {'allocation':allocation,'roles':roles,'measurement':measurement}


def verify(request):
    snapshot, sources = request["snapshot"], request["sources"]
    if snapshot.get('kind') == 'dung':
        return recompute_dung(snapshot)
    allocation = recompute(snapshot, sources)
    claims = ClaimSet.build(Context(*snapshot["context"]), allocation["payments"], snapshot["recipients"])
    return {"allocation": allocation, "claims": {"context": snapshot["context"],
        "root": claims.root.hash.hex(), "total": claims.root.total, "count": len(claims.leaves),
        "leaves": [{"index": l.index, "person": l.person, "recipient": l.recipient, "amount": l.amount,
                    "leaf_hash": l.node(claims.context).hash.hex(),
                    "proof": [{"hash": n.hash.hex(), "sum": n.total} for n in claims.proof(l.index)]}
                   for l in claims.leaves]}}


if __name__ == "__main__":
    print(json.dumps(verify(json.load(sys.stdin)), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
