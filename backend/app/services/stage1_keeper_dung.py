"""DUNG publication inputs from immutable riding and historical opening lots."""
from collections import Counter, defaultdict
from .stage1_keeper_allocation import hamilton
from .stage1_keeper_merkle import uint, digest, claim_set
from .stage1_keeper_snapshot import WEEK


def validate_lot(lot, context):
    from solders.pubkey import Pubkey
    program, city, hill = context[:3]
    if lot['city'] != city or lot['hill'] != hill:
        raise ValueError('foreign historical DUNG lot')
    if lot['owner'].startswith('anonymous:'):
        # Only the immutable archive's erasure path can create this form.
        # New imports reject anonymous identities and caller-supplied witnesses.
        if any(not isinstance(lot.get(k),str) or len(lot[k])!=64 or any(c not in '0123456789abcdef' for c in lot[k])
               for k in ('identity_digest','source_digest')) or type(lot.get('owner_rank')) is not int:
            raise ValueError('missing erased lot validation witness')
        return lot['identity_digest']
    owner = Pubkey.from_string(lot['owner'])
    seeds = [b's1v1_exit',bytes(Pubkey.from_string(lot['exit_request']))] if lot['exiting'] else [b's1v1_lot',bytes(owner),uint(lot['deposit_id']).to_bytes(8,'little')]
    expected = str(Pubkey.find_program_address(seeds,Pubkey.from_string(program))[0])
    if lot['address'] != expected:
        raise ValueError('foreign historical DUNG lot')
    return digest(['stage1-lot-identity-v1',program,expected])


def freeze_dung_opening(opening, context):
    if 'dung' not in opening:
        return opening
    raw = opening['dung']['lots']
    if any(l['owner'].startswith('anonymous:') for l in raw):
        raise ValueError('new anonymous lot archive is not admissible')
    ranks = {p:i for i,p in enumerate(sorted({l['owner'] for l in raw},key=lambda p:p.encode()))}
    fields = ('address','city','hill','mint','owner','deposit_id','exit_request','units','basis_lamports',
              'lock_weeks','lock_end','sequence','asset_slot','converted','cancelled','exiting','founding')
    seen, lots = set(),[]
    for lot in raw:
        identity = validate_lot(lot,context)
        if identity in seen:
            raise ValueError('duplicate historical DUNG lot')
        seen.add(identity)
        lots.append({**{k:lot[k] for k in fields if k in lot},'identity_digest':identity,
                     'source_digest':digest(lot),'owner_rank':ranks[lot['owner']]})
    return {**opening,'dung':{**opening['dung'],'lots':lots}}


def measured_tss(row):
    """Consume authenticated canonical samples; persist no GPS/sample payload."""
    from .canon_traversal_evidence import CanonTraversalEvidence, CanonTraversalEvidenceError
    from .workout_parse_adapter import calculate_segment_power_metrics_rust
    from .cal_tribute_policy import (calculate_segment_tss_base_units, CAL_TRIBUTE_POWER_METRICS_VERSION,
                                    MIN_SEGMENT_POWER_SAMPLE_COUNT, MIN_SEGMENT_POWER_COVERAGE_BPS)
    power = row.pop('_power', None)
    if not power or power.get('paid_spans_ms') is None or power.get('reward_ftp_w') is None:
        return {**row, 'tss_unavailable': 'missing_frozen_power_authority'}
    try:
        evidence = CanonTraversalEvidence.from_row(power['evidence'])
        if (str(evidence.ride_id) != power['ride_id'] or evidence.ride_hash_hex != power['ride_hash'] or
            evidence.ride_parser_version != power['parser_version']):
            raise ValueError('canonical power identity mismatch')
        start, end = (int(round(float(power[k]))) for k in ('start_offset', 'end_offset'))
        origin = power['started_at_ms']
        keep = [(int(a)-origin, int(b)-origin) for a,b in power['paid_spans_ms']]
        metrics = calculate_segment_power_metrics_rust(evidence.detector_samples(), start_offset_s=start,
                    end_offset_s=end, keep_ms_relative=keep)
        if metrics.metrics_version != CAL_TRIBUTE_POWER_METRICS_VERSION:
            raise ValueError('unsupported power metrics version')
        if metrics.normalized_power_duration_s > end-start+1 or end-start+1 > power['time_s']+2:
            raise ValueError('canonical power window mismatch')
        np = metrics.normalized_power_milliwatts
        if metrics.power_sample_count < MIN_SEGMENT_POWER_SAMPLE_COUNT or metrics.power_sample_coverage_bps < MIN_SEGMENT_POWER_COVERAGE_BPS:
            np = None
        tss = calculate_segment_tss_base_units(segment_np_duration_s=metrics.normalized_power_duration_s,
                    segment_np_milliwatts=np, reward_ftp_w=power['reward_ftp_w']) // 1000
        return {**row, 'tss_micros':tss, 'tss_provenance':digest({'sample_digest':evidence.sample_digest,
                'ftp':power['reward_ftp_w'], 'paid_spans':power['paid_spans_ms'], 'start':start, 'end':end,
                'metrics_version':metrics.metrics_version})}
    except (ValueError, TypeError, KeyError, CanonTraversalEvidenceError):
        return {**row, 'tss_unavailable':'invalid_frozen_power_evidence'}


def opening_weights(opening, launch, week, context=None):
    archive = opening['dung']
    hill, lots, rates = archive['hill'], archive['lots'], archive['rates']
    boundary, bond = opening['boundary'], hill['bonded_at']
    if not hill['bonded'] or bond >= boundary:
        return {'basis':[0]*8, 'backing':[0]*8, 'weights':{}, 'tie_ranks':{}, 'bonded_at':bond}
    basis, backing, weights = [0]*8, [0]*8, defaultdict(int)
    seen = set()
    raw_ranks = {p:i for i,p in enumerate(sorted({l['owner'] for l in lots},key=lambda p:p.encode()))}
    ranks = {l['owner']:l.get('owner_rank',raw_ranks[l['owner']]) for l in lots}
    for lot in lots:
        identity = validate_lot(lot,context) if context else lot['address']
        if identity in seen:
            raise ValueError('duplicate historical DUNG lot')
        seen.add(identity)
        if lot['cancelled'] or lot['exiting']:
            continue
        slot = uint(lot['asset_slot'], 8)
        founding = (not lot['converted'] and 0 < lot['sequence'] <= hill['founding_cutoff'] and
                    slot < 32 and bool(hill['founding_fresh_slots'] & (1 << slot)))
        if not founding and not lot['converted'] and lot['sequence'] <= hill['founding_cutoff']:
            continue
        units, amount = uint(lot['units']), uint(lot['basis_lamports'])
        if founding and not lot['founding']:
            n, d = hill['quoted_numerators'][slot], hill['quoted_denominators'][slot]
            if n <= 0 or d <= 0:
                raise ValueError('missing immutable founding quote')
            units = min(units, (amount*d+n-1)//n)
        lock_end = bond + 26*WEEK if founding else lot['lock_end']
        lock_weeks = (26 if founding else lot['lock_weeks']) if boundary < lock_end else 0
        index = [0,13,26,52].index(lock_weeks) + (4 if founding else 0)
        rate = rates[lot['mint']]
        from solders.pubkey import Pubkey
        program = Pubkey.from_string(context[0]) if context else None
        if context and (rate.get('mint') != lot['mint'] or rate.get('city') != context[1]
                        or rate.get('asset') != str(Pubkey.find_program_address([b's1v1_asset',bytes(Pubkey.from_string(lot['mint']))],program)[0])
                        or not 0 < rate.get('slot',0) <= opening['slot']):
            raise ValueError('invalid historical rate namespace')
        n, d = uint(rate['numerator']), uint(rate['denominator'])
        if not n or not d or rate['boundary'] != boundary or not rate['evidence']:
            raise ValueError('missing historical opening rate')
        value = min(amount, units*n//d)  # Per-lot floor precedes owner aggregation.
        basis[index] += amount
        backing[index] += value
        bonus = 2 if founding and week-(bond-launch)//WEEK <= 26 else 1
        weights[lot['owner']] += value * (index%4+1) * bonus
    return {'basis':basis, 'backing':backing, 'weights':dict(weights), 'tie_ranks':{p:ranks[p] for p in weights}, 'bonded_at':bond}


def allocate_dung(snapshot):
    potential = uint(snapshot['tss_micros']) if len(snapshot['field_people']) >= 5 else 0
    halves = hamilton(potential, {'riders':1, 'backers':1})
    pieces = hamilton(halves.get('riders',0), {'every_rider_by_ascents':35, 'top_ten':55, 'local_legend':10})
    riders = defaultdict(int)
    weights = {'every_rider_by_ascents':snapshot['ascents'], 'top_ten':dict.fromkeys(snapshot['board'],1),
               'local_legend':{snapshot['legend']:1} if snapshot['legend'] else {}}
    for name, amount in pieces.items():
        for person, value in hamilton(amount, weights[name],snapshot.get('rider_tie_ranks')).items():
            if person in snapshot['recipients']:
                riders[person] += value
    backers = {p:n for p,n in hamilton(halves.get('backers',0), snapshot['opening']['dung']['weights'],snapshot['opening']['dung'].get('tie_ranks')).items()
               if p in snapshot['recipients']}
    return {'potential':potential, 'riders':dict(riders), 'backers':backers,
            'unminted':potential-sum(riders.values())-sum(backers.values())}


def dung_plan(snapshot, city):
    snapshot = dict(snapshot)
    witness = snapshot.get('admission_bond')
    hill = snapshot['opening']['dung']['hill']
    if witness and (hill['bonded'] and (not witness['bonded'] or hill['bonded_at'] != witness['bonded_at'])
                    or not hill['bonded'] and witness['bonded'] and witness['bonded_at'] < snapshot['opening']['boundary']):
        raise ValueError('archived opening disagrees with immutable bond witness')
    bonded = snapshot['opening']['dung']['hill']['bonded']
    opening = opening_weights(snapshot['opening'], snapshot['launch'], snapshot['context'][3],snapshot['context'])
    snapshot['opening'] = {**snapshot['opening'], 'dung':opening}
    def post_bond(row):
        if 'ridden_at' in row:
            return row.get('ridden_at_us',row['ridden_at']*1_000_000) >= opening['bonded_at']*1_000_000
        if row.get('bond_eligibility_digest') and type(row.get('post_bond')) is bool:
            return row['post_bond']
        raise ValueError('missing historical bond eligibility')
    rides = [r for r in snapshot['rides'] if post_bond(r)] if bonded and opening['bonded_at'] < snapshot['opening']['boundary'] else []
    if any('tss_micros' not in r for r in rides):
        raise ValueError('DUNG requires authenticated canonical TSS for every post-bond receipt')
    snapshot['tss_micros'] = sum(r['tss_micros'] for r in rides)
    snapshot['ascents'] = dict(Counter(r['person'] for r in rides if r['paid_ascent']))
    if any(p.startswith('anonymous:') for p in set(snapshot['ascents'])|set(snapshot['board'])|({snapshot['legend']} if snapshot['legend'] else set())) and not snapshot.get('rider_tie_ranks'):
        raise ValueError('missing historical rider allocation order')
    if len(snapshot['field_people'])>=5 and snapshot['tss_micros'] > city['dung_tss_ceiling_micros']:
        raise ValueError('DUNG TSS exceeds configured ceiling')
    allocation = allocate_dung(snapshot)
    roles = []
    for role in ('riders','backers'):
        context = snapshot['context'][:]
        context[4] += ':'+role
        roles.append(claim_set(context, allocation[role], snapshot['recipients']))
    return snapshot, allocation, roles, dung_inputs(snapshot, roles)


def dung_inputs(snapshot, roles):
    return {'source_snapshot':digest(snapshot), 'field_count':len(snapshot['field_people']),
            'postbond_tss_micros':snapshot['tss_micros'], 'top_count':len(snapshot['board']),
            'ascent_count':sum(snapshot['ascents'].values()), 'earned_legend':bool(snapshot['legend']),
            'opening':{k:snapshot['opening']['dung'][k] for k in ('basis','backing')},
            'payable_role_totals':[r['total'] for r in roles]}


def check_payable_totals(inputs, expected, week):
    """Publication totals must equal independently computed frozen recipient shares."""
    from .stage1_keeper_worker import Blocked
    totals = inputs.get('payable_role_totals') if isinstance(inputs, dict) else None
    if not isinstance(totals, list) or len(totals) != 2 or any(type(n) is not int for n in totals):
        raise Blocked('dung_payable_total_mismatch', {'week':week, 'reason':'malformed_totals'})
    for role, name in enumerate(('riders','backers')):
        payable = sum(expected['allocation'][name].values())
        if totals[role] != payable:
            raise Blocked('dung_payable_total_mismatch',
                          {'week':week, 'role':name, 'expected':payable, 'actual':totals[role]})


def dung_operations(week, allocation, roles, inputs):
    if not allocation['potential']:
        return [{'kind':'dung_skip', 'through':week, 'week':week,
                 'snapshot':inputs['source_snapshot'], 'field_count':inputs['field_count'], 'tss':inputs['postbond_tss_micros']}]
    operations = [{'kind':'dung_publish', 'week':week, 'input':inputs}]
    for role, claims in enumerate(roles):
        operations += [{'kind':'dung_prepare','week':week,'role':role,'count':claims['count']},
                       {'kind':'dung_root','week':week,'role':role,'root':claims['root'],'count':claims['count'],'total':claims['total']}]
    return operations


async def verify_dung_plan(worker, scope, job):
    """Check the current durable plan without refreshing its registration cutoff."""
    from .stage1_keeper_merkle import canonical
    from .stage1_keeper_worker import Blocked
    week = job['week']
    try:
        if not isinstance(job['snapshot'], dict):
            raise ValueError('missing frozen snapshot')
        snapshot = {k:v for k,v in job['snapshot'].items() if k != 'dung_input'}
        committed = {'schema':2, 'context':snapshot['context'], 'components':{
            k:digest(v) for k,v in snapshot.items() if k not in ('context','commitment','commitment_inputs')}}
        if canonical(committed) != canonical(snapshot['commitment_inputs']) or digest(committed) != snapshot['commitment']:
            raise Blocked('dung_payable_total_mismatch', {'week':week, 'reason':'frozen_inputs_changed'})
        expected = await worker.recompute({**snapshot, 'kind':'dung'}, [])
        inputs = job['snapshot']['dung_input']
        check_payable_totals(inputs, expected, week)
        roles = expected['roles']
        measurement = expected['measurement']
        derived = {**snapshot, 'opening':{**snapshot['opening'], 'dung':measurement['opening']},
                   'tss_micros':measurement['tss_micros'], 'ascents':measurement['ascents']}
        claims = {'kind':'dung', 'context':scope_context(scope,week), 'roles':roles,
                  'leaves':[{**leaf,'role':role} for role,c in enumerate(roles) for leaf in c['leaves']]}
        if (snapshot['context'] != claims['context'] or
            canonical(inputs) != canonical(dung_inputs(derived, roles)) or
            canonical(job['allocation']) != canonical({**expected['allocation'], 'cap':0}) or
            canonical(job['claims']) != canonical(claims) or
            canonical(job['operations']) != canonical(dung_operations(week,expected['allocation'],roles,inputs))):
            raise Blocked('dung_payable_total_mismatch', {'week':week, 'reason':'frozen_shares_changed'})
    except Blocked:
        raise
    except (KeyError, TypeError, ValueError):
        raise Blocked('dung_payable_total_mismatch', {'week':week, 'reason':'malformed_plan'}) from None


async def plan_dung(worker, claim, observation, snapshot):
    import hashlib
    from pathlib import Path
    from .stage1_keeper_snapshot import bind_recipients, recipient_people
    from .stage1_keeper_merkle import canonical
    from .stage1_keeper_worker import Blocked, proof_payload
    scope, job = claim['scope'], claim['job']
    week = job['week']
    if not observation['city']['dung_start_week_plus_one']:
        from .stage1_keeper_store import WaitingForArchive
        raise WaitingForArchive('DUNG publication is disabled')
    if max(observation['hill']['dung_next_week'],observation['city']['dung_start_week_plus_one']-1) != week:
        raise Blocked('dung_cursor_mismatch', {'week':week})
    slot, registrations = await worker.chain.recipient_registrations(recipient_people(snapshot), observation['slot'])
    snapshot = bind_recipients(snapshot, registrations)
    derived, allocation, roles, inputs = dung_plan(snapshot, observation['city'])
    # Independent Fraction/Hamilton implementation recomputes each role root.
    expected = await worker.recompute({**snapshot, 'kind':'dung'}, [])
    actual = {'allocation':allocation, 'roles':roles,
              'measurement':{'opening':derived['opening']['dung'],'tss_micros':derived['tss_micros'],'ascents':derived['ascents']}}
    if canonical(actual) != canonical(expected):
        raise Blocked('oracle_disagreement', {'kind':'dung'})
    check_payable_totals(inputs, expected, week)
    operations = dung_operations(week, allocation, roles, inputs)
    claims = {'kind':'dung','context':scope_context(scope, week), 'roles':roles,
              'leaves':[{**leaf,'role':role} for role,c in enumerate(roles) for leaf in c['leaves']]}
    allocation['cap'] = 0  # Cash-only export field; DUNG does not apply a cap.
    snapshot['dung_input'] = inputs
    path = str(Path(worker.export_dir) / f"{job['id']}.json")
    sha = hashlib.sha256(canonical(proof_payload(snapshot,allocation,claims,True))+b'\n').hexdigest()
    await worker.store.save_plan(claim, {'snapshot':snapshot,'sources':[], 'allocation':allocation,'claims':claims,
        'operations':operations,'floor_slot':slot,'export_path':path,'export_digest':sha,'through_week':week})
    return True


def scope_context(scope, week):
    return [scope['program'],scope['city'],scope['hill'],week,scope['mint']]


def check_dung(observation, jobs):
    from .stage1_keeper_merkle import root_from_hashes
    from .stage1_keeper_worker import Blocked
    receipts, known_mints, known_sets = [], set(), set()
    mints = dict(observation['mints'])
    for job in jobs:
        retained = job.get('dung_publication')
        if retained and retained.get('closed'):
            if not retained['closed'].get('signature') or retained['account']['minted']!=retained['account']['role_totals'] or retained['account']['published_roles']!=3:
                raise Blocked('dung_closure_witness_mismatch', {'week':job['week']})
            if retained['address'] in mints:
                raise Blocked('closed_dung_mint_reappeared', {'week':job['week']})
            mints[retained['address']] = retained['account']
    for job in jobs:
        if job['claims'].get('kind') != 'dung':
            raise Blocked('wrong_dung_namespace', {'week':job['week']})
        mint_row = next(((a,m) for a,m in mints.items() if m['hill']==job['claims']['context'][2] and m['week']==job['week']),None)
        if mint_row:
            mint_address,mint = mint_row
            known_mints.add(mint_address)
            if mint['role_totals'] != [c['total'] for c in job['claims']['roles']]:
                raise Blocked('dung_role_total_mismatch', {'week':job['week']})
            if (mint['unminted'] != job['allocation']['unminted'] or
                sum(mint['role_totals'])+mint['unminted'] != job['allocation']['potential']):
                raise Blocked('dung_unminted_mismatch', {'week':job['week']})
            if job.get('dung_publication') and mint['snapshot'] != job['dung_publication']['account']['snapshot']:
                raise Blocked('dung_snapshot_mismatch', {'week':job['week']})
        for role, claims in enumerate(job['claims']['roles']):
            if root_from_hashes(claims['context'], claims['leaves']) != (claims['root'],claims['total']):
                raise Blocked('dung_retained_root_mismatch', {'week':job['week']})
            found = next(((a,s) for a,s in observation['sets'].items() if s['hill']==job['claims']['context'][2] and s['week']==job['week'] and s['role']==role), None)
            if found is None:
                closed = next(((a,p['account']) for a,p in job.get('publications',{}).items()
                               if p.get('closed') and p['account']['role']==role),None)
                if closed:
                    retained = job['publications'][closed[0]]
                    if not retained['closed'].get('signature') or closed[1]['paid']!=closed[1]['total'] or closed[1]['claimed_count']!=closed[1]['leaf_count']:
                        raise Blocked('dung_closure_witness_mismatch', {'week':job['week'],'role':role})
                found = closed
            if found is None:
                if job['state']=='complete' and any(op['kind']=='dung_root' for op in job['operations']):
                    raise Blocked('missing_dung_claim_set', {'week':job['week'],'role':role})
                continue
            address, account = found
            known_sets.add(address)
            if not account['sealed']:
                continue
            if (account['root'], account['total'], account['leaf_count']) != (claims['root'],claims['total'],claims['count']):
                raise Blocked('dung_claim_set_mismatch', {'week':job['week'],'role':role})
            bits = bytes.fromhex(account['bitmap'])
            paid = [l for l in claims['leaves'] if bits[l['index']//8] & (1 << (l['index']%8))]
            if sum(l['amount'] for l in paid) != account['paid'] or len(paid)!=account['claimed_count']:
                raise Blocked('dung_paid_mismatch', {'week':job['week'],'role':role})
            if not mint_row or mint['minted'][role] != account['paid']:
                raise Blocked('dung_minted_paid_mismatch', {'week':job['week'],'role':role})
            observation['sets'][address] = account
            receipts.extend({'claim_set':address,'index':l['index'],'role':role,'amount':l['amount']} for l in paid)
    if known_mints != set(mints) or set(observation['sets'])-known_sets:
        raise Blocked('untracked_dung_inventory', {})
    if (observation['state']['allocated_lifetime'] != sum(sum(m['role_totals']) for m in mints.values()) or
        observation['state']['minted_lifetime'] != sum(sum(m['minted']) for m in mints.values())):
        raise Blocked('dung_lifetime_mismatch', {})
    observation['receipts'] = receipts
    observation['mints'] = mints
    return {'slot':observation['slot'],'commitment':'finalized','checks':'DUNG role roots and paid bitmaps'}
