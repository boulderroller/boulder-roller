"""Finalized boundary producer. Run with python -m app.services.stage1_boundary.

STAGE1_BOUNDARY_ENABLED=true, STAGE1_BOUNDARY_DATABASE_URL and
STAGE1_BOUNDARY_EXPORT_DIR opt in. Sources come exclusively from the indexer's
single-bank checkpoints and contiguous finalized replay. No RPC or signer here.
An unavailable historical mutation or rate holds the week; it never copies a
newer projection into the past. Restart retries held weeks every 15 minutes.
"""
import argparse
import asyncio
import copy
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import uuid

from solders.pubkey import Pubkey
from .stage1_keeper_merkle import canonical, digest
from .stage1_keeper_dung import opening_weights
from ..program_compatibility import STAGE1_OBSERVED_VERSION_SQL

WEEK = 604800
ZERO = '11111111111111111111111111111111'
RECORD_EVENTS = {'recordClimbCompletion':'ClimbCompleted','recordClimbCompletionV2':'ClimbCompletedV2',
                 'recordReleasedClimbCompletion':'ReleasedClimbCompleted','electLocalLegend':'LocalLegendElected',
                 'resignLocalLegend':'LocalLegendResigned','deactivateLocalLegend':'LocalLegendDormant'}


class MissingBoundary(ValueError):
    pass


def hex_bytes(value):
    return value if isinstance(value, str) else bytes(value).hex()


def snake(value):
    import re
    if isinstance(value, dict):
        return {re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower(): snake(v) for k,v in value.items()}
    if isinstance(value, list):
        return [snake(v) for v in value]
    if isinstance(value, str) and len(value)<32 and value.lstrip('-').isdigit():
        return int(value)
    return value


def term_start(config, week):
    transition = int(config['settlementClockV2StartsAt'])
    if int(config['settlementClockVersion']) != 2 or transition < 1704110400:
        raise MissingBoundary('missing_settlement_clock_lineage')
    anchor = 1704020400 if transition > 1704110400 and week <= (transition-1704110400)//WEEK else 1704110400
    return anchor+week*WEEK


def _records(accounts, hill, at):
    canon = hex_bytes(hill['canonId'])
    climbs = [a for a in accounts if a['type']=='Climb' and hex_bytes(a['fields']['canonId'])==canon
              and (int(a['fields']['registeredAt']) < at if a['fields'].get('registeredAt') else a.get('registered_before',at+1)<=at)]
    if not climbs:
        raise MissingBoundary('missing_canon_at_boundary')
    climb = max(climbs,key=lambda a:int(a['fields']['canonVersion']))
    vaults = [a for a in accounts if a['type']=='Vault' and a['address']==climb['fields']['vault'] and a['fields']['climb']==climb['address']]
    if climb['fields']['vault'] != ZERO and len(vaults)!=1:
        raise MissingBoundary('missing_record_vault_binding')
    board, legend, anonymous = [], None, False
    if vaults:
        vault = str(vaults[0]['fields']['id'])
        boards = [a for a in accounts if a['type']=='VaultLeaderboard' and str(a['fields']['vaultId'])==vault]
        if len(boards)!=1:
            raise MissingBoundary('missing_record_board')
        source=boards[0];entries=source['fields']['entries']
        anonymous=any(e['user'].startswith('anonymous:') for e in entries)
        if anonymous:
            if not source.get('record_order') or source.get('record_not_before',at+1)>at or len(set(source['record_order']))!=len(entries):
                raise MissingBoundary('missing_anonymous_record_order')
            entries=sorted(entries,key=lambda e:source['record_order'].index(e['user']))
        board=[{'person':e['user'],'time_s':int(e['timeS']),**({'recorded_at':int(e['recordedAt'])} if not e['user'].startswith('anonymous:') else {})} for e in entries]
        legends = [a['fields'] for a in accounts if a['type']=='LocalLegend' and str(a['fields']['vaultId'])==vault]
        if legends and legends[0]['holder']!=ZERO:
            config = next((a['fields'] for a in accounts if a['type']=='ProgramConfig'),None)
            if not config:
                raise MissingBoundary('missing_settlement_clock_lineage')
            row = legends[0]
            retained=next(a for a in accounts if a.get('fields') is row).get('record_term',[])
            anonymous=anonymous or row['holder'].startswith('anonymous:')
            legend = dict(person=row['holder'],active=row['isActive'],bootstrap=row['isBootstrap'],
                          term_start=term_start(config,int(row.get('termStartEpoch',retained[0] if retained else None))),term_end=term_start(config,int(row.get('termEndEpoch',retained[1] if retained else None))))
    if not any(r['person'].startswith('anonymous:') for r in board):
        board.sort(key=lambda r:(r['time_s'],r['recorded_at'],bytes(Pubkey.from_string(r['person']))))
    if len(board)>10 or len({r['person'] for r in board})!=len(board) or any(r['time_s']<=0 or (not r['person'].startswith('anonymous:') and not 0<r['recorded_at']<at) for r in board):
        raise MissingBoundary('invalid_record_provenance')
    earned=legend['person'] if legend and legend['active'] and not legend['bootstrap'] and legend['term_start']<at<=legend['term_end'] else None
    if legend and legend['person'].startswith('anonymous:'):
        legend={k:v for k,v in legend.items() if k not in ('term_start','term_end')}
    return dict(record_climb=climb['address'],record_version=int(climb['fields']['canonVersion']),board=board,legend=legend,**({'seats':[r['person'] for r in board],'earned_legend':earned} if anonymous else {}))


def _replay_records(accounts, transactions):
    """Only the complete, known record event family is recoverable without bytes."""
    for tx in sorted(transactions,key=lambda t:(t['slot'],t.get('block_index',0))):
        if not tx.get('instructions') or any(i['name'] not in RECORD_EVENTS for i in tx['instructions']):
            raise MissingBoundary('unrecoverable_boundary_mutation')
        required=Counter(RECORD_EVENTS[i['name']] for i in tx['instructions'])
        vaults={str(a['fields']['vaultId']) for a in accounts if a['type'] in ('VaultLeaderboard','LocalLegend')}
        scoped_events=[e for e in tx.get('events',[]) if str(e['fields'].get('vaultId')) in vaults]
        observed=Counter(e['name'] for e in scoped_events)
        if any(observed[name]!=count for name,count in required.items()):
            raise MissingBoundary('missing_record_events')
        for event in scoped_events:
            name, f = event['name'],event['fields']
            vault = str(f.get('vaultId'))
            if name in ('ClimbCompleted','ClimbCompletedV2','ReleasedClimbCompleted'):
                row = next((a['fields'] for a in accounts if a['type']=='VaultLeaderboard' and str(a['fields']['vaultId'])==vault),None)
                if row is None:
                    continue  # Another hill's event in the same atomic transaction.
                account=next(a for a in accounts if a.get('fields') is row)
                if account.get('observed_slot',-1)>=tx['slot']:
                    continue
                entry = dict(user=f['rider'],timeS=int(f['timeS']),recordedAt=str(f['completedAt']))
                old = next((e for e in row['entries'] if e['user']==entry['user']),None)
                from functools import cmp_to_key
                original=list(row['entries'])
                def compare(a,b):
                    if int(a['timeS'])!=int(b['timeS']):
                        return int(a['timeS'])-int(b['timeS'])
                    if not a['user'].startswith('anonymous:') and not b['user'].startswith('anonymous:'):
                        rank=lambda e:(int(e['recordedAt']),bytes(Pubkey.from_string(e['user'])))
                        return (rank(a)>rank(b))-(rank(a)<rank(b))
                    if not account.get('record_order') or a not in original or b not in original:
                        raise MissingBoundary('anonymous_record_tie_order_unavailable')
                    return account['record_order'].index(a['user'])-account['record_order'].index(b['user'])
                if old is None or compare(entry,old)<0:
                    row['entries'] = sorted([e for e in row['entries'] if e['user']!=entry['user']]+[entry],key=cmp_to_key(compare))[:10]
                    if 'record_order' in account:
                        account['record_order']=[e['user'] for e in row['entries']]
            elif name in ('LocalLegendElected','LocalLegendResigned','LocalLegendDormant'):
                row = next((a['fields'] for a in accounts if a['type']=='LocalLegend' and str(a['fields']['vaultId'])==vault),None)
                if row is None:
                    raise MissingBoundary('missing_record_legend')
                account=next(a for a in accounts if a.get('fields') is row)
                if account.get('observed_slot',-1)>=tx['slot']:
                    continue
                if name=='LocalLegendElected':
                    row.update(holder=f['winner'],isActive=True,isBootstrap=f['isBootstrap'],termStartEpoch=f['termStartEpoch'],termEndEpoch=f['termEndEpoch'])
                elif name=='LocalLegendDormant':
                    row.update(isActive=False,isBootstrap=False,termStartEpoch=f['termStartEpoch'],termEndEpoch=f['termEndEpoch'])
                else:
                    row.update(isActive=False)


def dependency_accounts(accounts, hill_address, admission=None, program=None):
    hill=next((a['fields'] for a in accounts if a['address']==hill_address),None)
    if hill is None and admission:
        hill=next((a['fields'] for a in admission['accounts'] if a['address']==hill_address),None)
    if hill is None:
        return {hill_address}
    climbs=[a for a in accounts if a['type']=='Climb' and hex_bytes(a['fields']['canonId'])==hex_bytes(hill['canonId'])]
    vaults=[a for a in accounts if a['type']=='Vault' and a['address'] in {c['fields']['vault'] for c in climbs}]
    ids={str(v['fields']['id']) for v in vaults}
    optional={str(Pubkey.find_program_address([seed,int(v['fields']['id']).to_bytes(8,'little')],Pubkey.from_string(program))[0])
              for v in vaults for seed in (b'vault_leaderboard',b'local_legend')} if program else set()
    return {hill_address,hill['city']} | optional | {a['address'] for a in accounts if
        a['type']=='ProgramConfig' or a in climbs or a in vaults or
        (a['type']=='Stage1AssetConfig' and a['fields']['city']==hill['city']) or
        (a['type']=='Stage1PledgeLot' and a['fields']['hill']==hill_address) or
        (a['type'] in ('VaultLeaderboard','LocalLegend') and str(a['fields']['vaultId']) in ids)}


def input_mutation(tx, dependencies, hill_address, accounts=None, checkpoint_slot=None):
    if not set(tx.get('writes',[])) & dependencies:
        return None
    instructions=[]
    for ix in tx.get('instructions',[]):
        target=(ix.get('accounts',{}).get('vault') or ix.get('accounts',{}).get('localLegend')) if ix['name'] in RECORD_EVENTS else None
        if target and target not in dependencies:
            continue
        if ix.get('keys') and not set(ix['keys']) & dependencies:
            continue
        # These instructions cannot change the consumed board/Legend tenure or
        # bond/lot/rate fields. Vault reward counters are not boundary inputs.
        if ix['name'] in ('recordRide','creditCal','creditReleasedCal','distributeEpochRewards',
            'updateVaultMetadata','stakeCalInVault','depositCalFromBalance','unstakeCalFromVault','withdrawCalToBalance','harvestRewards','collectStakeRewardsFor','sponsorStage1',
            'postStage1Boost','processStage1Boost','expireStage1Hold','publishStage1ClaimSet','claimStage1','claimStage1Batch'):
            continue
        other=ix.get('accounts',{}).get('hill')
        if other and other!=hill_address and ix['name'] in ('pledge','bond') and accounts is not None:
            assets=[a for a in accounts if a['type']=='Stage1AssetConfig' and a['address'] in tx['writes']]
            if all(int(a['fields']['adapter'])==1 or
                   a.get('observed_slot',checkpoint_slot)<tx['slot'] and int(a['fields']['admittedDenominator'])>0 and tx.get('epoch')==int(a['fields']['admittedEpoch']) for a in assets):
                continue
        if other and other!=hill_address and ix['name'] in (
            'refreshCampaignLot','materializeStage1Lot','convertExcludedPledge','cancelPledge',
            'withdrawPrebond','requestWithdrawal','beginWithdrawal','completeWithdrawal','harvestStage1'):
            continue
        instructions.append(ix)
    if tx.get('instructions') and not instructions:
        return None
    return {**tx,'instructions':instructions}


def boundary_mutations(accounts,checkpoint,coverage,transactions,dependencies,hill,boundary):
    by_address={a['address']:a for a in accounts}
    forward=[]
    def route(address):
        erased='anonymous:lot:'+digest(['stage1-lot-identity-v1',checkpoint['program'],address])
        return erased if erased in dependencies else address
    for original in transactions:
        tx={**original,'writes':[route(a) for a in original.get('writes',[])],
            'instructions':[{**ix,**({'keys':[route(a) for a in ix['keys']]} if 'keys' in ix else {})} for ix in original.get('instructions',[])]}
        mutation=input_mutation(tx,dependencies,hill,accounts,checkpoint['slot'])
        if not mutation:
            continue
        needed=False
        for address in set(tx['writes']) & dependencies:
            row=by_address.get(address,{})
            slot=row.get('observed_slot',checkpoint['slot'])
            at=row.get('observed_time',checkpoint['block_time'])
            if at>=boundary and coverage['from_slot']<=tx['slot']<=slot and tx['block_time']>=boundary:
                raise MissingBoundary('unrecoverable_boundary_mutation')
            needed |= at<boundary and slot<tx['slot']<=coverage['through_slot'] and tx['block_time']<boundary
        if needed:
            forward.append(mutation)
    return forward


def materialize_boundary(checkpoint, coverage, transactions, hill_address, boundary, *, admission=None):
    """Pure historical replay. Strictly before T; transactions timestamped T are new-week state."""
    for k in ('genesis','program'):
        if checkpoint[k]!=coverage[k]:
            raise MissingBoundary('foreign_replay_namespace')
    if not (coverage['from_slot']<=checkpoint['slot']<=coverage['through_slot']) or coverage['through_time']<boundary:
        raise MissingBoundary('finalized_replay_not_through_boundary')
    # A checkpoint may be later than the boundary only if our observation floor
    # predates the boundary. A first checkpoint never certifies older history.
    if coverage.get('from_time',checkpoint['block_time'])>=boundary and checkpoint['block_time']>=boundary:
        raise MissingBoundary('missing_opening_history')
    # An erased source remains a positive gap witness, never an empty write set.
    for tx in transactions:
        relevant = (checkpoint['slot']<tx['slot']<=coverage['through_slot'] and tx['block_time']<boundary) if checkpoint['block_time']<boundary else (coverage['from_slot']<=tx['slot']<=checkpoint['slot'] and tx['block_time']>=boundary)
        if relevant and tx.get('erased'):
            raise MissingBoundary('erased_replay_gap')
    if checkpoint.get('erased'):
        raise MissingBoundary('erased_checkpoint')
    accounts = copy.deepcopy(checkpoint['accounts'])
    omitted=[a for a in accounts if a.get('omitted')]
    if any(a['type']=='ProgramConfig' or a['address']==hill_address or a.get('routing',{}).get('hill')==hill_address for a in omitted):
        raise MissingBoundary('erased_checkpoint_account')
    accounts=[a for a in accounts if not a.get('omitted')]
    dependencies=dependency_accounts(accounts,hill_address,admission,checkpoint['program'])
    mutations=boundary_mutations(accounts,checkpoint,coverage,transactions,dependencies,hill_address,boundary)
    if mutations:
        counts=Counter(t['slot'] for t in mutations)
        if any(counts[t['slot']]>1 and type(t.get('block_index')) is not int for t in mutations) or len({(t['slot'],t.get('block_index')) for t in mutations})!=len(mutations):
            raise MissingBoundary('ambiguous_same_slot_record_order')
        _replay_records(accounts, mutations)
    hill = next((a['fields'] for a in accounts if a['type']=='Stage1HillBond' and a['address']==hill_address),None)
    absent = hill is None
    if absent:
        if not admission or admission['genesis']!=checkpoint['genesis'] or admission['program']!=checkpoint['program'] or admission['block_time']<boundary or admission.get('erased'):
            raise MissingBoundary('missing_hill_admission')
        hill=next((a.get('fields') for a in admission['accounts'] if a['type']=='Stage1HillBond' and a['address']==hill_address),None)
        if not hill:
            raise MissingBoundary('missing_hill_admission')
    canon=hex_bytes(hill['canonId'])
    climb_addresses={a['address'] for a in accounts if a['type']=='Climb' and hex_bytes(a['fields']['canonId'])==canon}
    if any(a['address']==hill['city'] or (a['type']=='Stage1AssetConfig' and a.get('routing',{}).get('city')==hill['city']) or (a['type']=='Climb' and hex_bytes(a.get('routing',{}).get('canonId',[]))==canon) or (a['type']=='Vault' and a.get('routing',{}).get('climb') in climb_addresses) for a in omitted):
        raise MissingBoundary('erased_checkpoint_account')
    identity_accounts=admission['accounts'] if absent else accounts
    city = next(a['fields'] for a in identity_accounts if a['type']=='Stage1CityConfig' and a['address']==hill['city'])
    launch = int(city['seasonAnchor'])
    date = datetime.fromtimestamp(launch,timezone.utc)
    if date.weekday()!=0 or (date.hour,date.minute,date.second)!=(12,0,0) or (boundary-launch)%WEEK or boundary<launch:
        raise MissingBoundary('invalid_week_boundary')
    if absent and int(hill['admittedWeek'])!=(boundary-launch)//WEEK:
        raise MissingBoundary('missing_hill_before_admission_week')
    assets = [a for a in accounts if a['type']=='Stage1AssetConfig' and a['fields']['city']==hill['city']]
    lots = [{**snake({k:v for k,v in a['fields'].items() if k in ('city','hill','mint','owner','depositId','exitRequest','units','basisLamports','lockWeeks','lockEnd','sequence','assetSlot','converted','cancelled','exiting','founding')}),
             **({'identity_digest':a['lot_identity_digest'],'source_digest':a['lot_source_digest']} if a['fields']['owner'].startswith('anonymous:') else {'address':a['address']}),
             **({'owner_rank':a['lot_owner_rank']} if 'lot_owner_rank' in a else {})} for a in accounts if a['type']=='Stage1PledgeLot' and a['fields']['hill']==hill_address]
    rates = {}
    opening_error=None
    for asset in assets:
        f = asset['fields']
        if int(f['adapter'])==254:
            continue
        if int(f['adapter'])==1:
            fresh = boundary<int(f['lastFreshUntil'])
        else:
            fresh = checkpoint['epoch']==coverage.get('through_epoch',checkpoint['epoch'])==int(f['admittedEpoch'])
        relevant = not absent and hill['bonded'] and int(hill['bondedAt'])<boundary and any(
            l['mint']==f['mint'] and not l['cancelled'] and not l['exiting'] and
            (l['converted'] or l['sequence']>int(hill['foundingCutoff']) or
             (l['sequence']>0 and int(hill['foundingFreshSlots']) & (1<<l['asset_slot']))) for l in lots)
        if relevant and (not fresh or int(f['admittedNumerator'])<=0 or int(f['admittedDenominator'])<=0):
            opening_error='missing_fresh_opening_rate'
        rates[f['mint']] = dict(mint=f['mint'],city=f['city'],asset=asset['address'],slot=checkpoint['slot'],
            numerator=int(f['admittedNumerator']),denominator=int(f['admittedDenominator']),boundary=boundary,evidence=digest(asset))
    if absent:
        # Complete pre-boundary GPA plus replay proves absence. Later immutable
        # admission supplies identity only; no later backing enters the opening.
        lots=[]
        opening_hill=dict(city=hill['city'],climb=hill['climb'],canon_id=hex_bytes(hill['canonId']),bonded=False,bonded_at=0)
    else:
        opening_hill=snake({k:v for k,v in hill.items() if k in ('city','climb','canonId','bonded','bondedAt','foundingCutoff','foundingFreshSlots','quotedNumerators','quotedDenominators')})
    dung = dict(hill=opening_hill,lots=lots,rates=rates)
    opening = dict(boundary=boundary,slot=checkpoint['slot'],commitment='finalized',evidence=digest(checkpoint),dung=dung)
    if opening_error:
        opening=None
    else:
        weights = opening_weights(opening,launch,(boundary-launch)//WEEK,[checkpoint['program'],hill['city'],hill_address])
        backing = sum(weights['backing'])
        opening.update(backing=backing,live=not absent and hill['bonded'] and int(hill['bondedAt'])<boundary and backing>=int(city['liveLamports']))
    if any(a['type'] in ('VaultLeaderboard','LocalLegend') and any(v['type']=='Vault' and str(v['fields']['id'])==str(a.get('routing',{}).get('vaultId')) and any(cl['type']=='Climb' and cl['address']==v['fields']['climb'] and hex_bytes(cl['fields']['canonId'])==hex_bytes(hill['canonId']) for cl in accounts) for v in accounts) for a in omitted):
        raise MissingBoundary('erased_record_account')
    if absent:
        opening['absent']=True
        records=dict(record_climb=None,record_version=None,board=[],legend=None)
    else:
        records = _records(accounts,hill,boundary)
    result = dict(schema=1,genesis=checkpoint['genesis'],program=checkpoint['program'],hill=hill_address,boundary=boundary,
        city=hill['city'],canon_id=str(uuid.UUID(hex=hex_bytes(hill['canonId']))),launch=launch,slot=checkpoint['slot'],
        opening=opening,records=records,records_digest=digest(records),assets=sorted(f['fields']['mint'] for f in assets),
        source=dict(checkpoint=checkpoint,coverage=coverage,transactions=transactions))
    if opening_error:
        result['opening_error']=opening_error
    if absent:
        result['source']['admission']=admission
    from .stage1_keeper_dung import freeze_dung_opening
    from .stage1_keeper_snapshot import freeze_records
    frozen=freeze_dung_opening(opening,[checkpoint['program'],hill['city'],hill_address]) if opening and not any(l['owner'].startswith('anonymous:') for l in lots) else None
    if opening and frozen is None:
        # Only exact database source-redaction receipts admit this form in
        # verify_boundary. Keeper caller imports retain their stricter gate.
        from .stage1_keeper_dung import validate_lot
        frozen_lots=[{**l,'identity_digest':validate_lot(l,[checkpoint['program'],hill['city'],hill_address]),
            'source_digest':l.get('source_digest',digest(l)),'owner_rank':l['owner_rank']} for l in lots]
        frozen={**opening,'dung':{**opening['dung'],'lots':frozen_lots}}
    result['erasure_basis']={'opening':frozen,
        'records':freeze_records({'boundary':boundary,**records})}
    result['source_digest']=digest(result['source'])
    result['digest']=digest(result)
    return result


def source_needs_receipt(source):
    keys={'lot_identity_digest','lot_source_digest','lot_owner_rank','record_order','record_not_before','record_term','registered_before'}
    return any(keys.intersection(a) or str(a.get('address','')).startswith('anonymous:') or
               any(p.get('erased') for p in a.get('parts',[])) for a in source['accounts'])


def verify_boundary(value, *, require_raw=False, redaction_receipt=None, source_receipts=()):
    source = value['source']
    if value.get('redacted'):
        # Only an authorized database erasure can replace the original view.
        # The immutable receipt commits the whole changed view and the original
        # ordered span manifests; it cannot be supplied by an archive caller.
        if not redaction_receipt or redaction_receipt['current_digest']!=value['digest'] or digest({k:v for k,v in value.items() if k!='digest'})!=value['digest']:
            raise ValueError('unverified boundary redaction')
        from .stage1_boundary_source import verify_accounts
        commitments=[]
        for checkpoint in [source['checkpoint']]+([source['admission']] if source.get('admission') else []):
            verify_accounts(checkpoint['accounts'])
            commitments.extend({'raw_digest':a['raw_digest'],'parts_digest':a['parts_digest']} for a in checkpoint['accounts'] if 'parts_digest' in a)
        expected=redaction_receipt['parts_commitments']
        if isinstance(expected,str):
            expected=json.loads(expected)
        if sorted(commitments,key=canonical)!=sorted(expected,key=canonical):
            raise ValueError('redacted source manifest differs from original')
        if value['opening']!=value['erasure_basis']['opening'] or value['records']!={k:v for k,v in value['erasure_basis']['records'].items() if k!='boundary'}:
            raise ValueError('redacted frozen input mismatch')
        if digest(source)!=value['source_digest'] or digest(value['records'])!=value['records_digest']:
            raise ValueError('redacted boundary digest mismatch')
        if value['opening']:
            weights=opening_weights(value['opening'],value['launch'],(value['boundary']-value['launch'])//WEEK,[value['program'],value['city'],value['hill']])
            if sum(weights['backing'])!=value['opening']['backing']:
                raise ValueError('redacted backing mismatch')
        return value
    for checkpoint in [source['checkpoint']]+([source['admission']] if source.get('admission') else []):
        if source_needs_receipt(checkpoint) and digest(checkpoint) not in source_receipts:
            raise ValueError('unverified source redaction')
    replay = materialize_boundary(source['checkpoint'],source['coverage'],source['transactions'],value['hill'],value['boundary'],admission=source.get('admission'))
    if replay!=value:
        raise ValueError('boundary witness digest/replay mismatch')
    accounts=source['checkpoint']['accounts']
    if require_raw or any('raw' in row for row in accounts):
        from .stage1_boundary_source import verify_accounts
        verify_accounts(accounts)
        if source.get('admission'):
            verify_accounts(source['admission']['accounts'])
    return replay


async def verify_retained_boundary(connection,ident,value):
    receipt=None
    if value.get('redacted'):
        receipt=await connection.fetchrow('SELECT current_digest,parts_commitments FROM stage1_boundary_redactions WHERE witness_id=$1 AND current_digest=$2',ident,value['digest'])
    sources=[value['source']['checkpoint']]+([value['source']['admission']] if value['source'].get('admission') else [])
    receipts=[]
    for source in sources:
        if source_needs_receipt(source):
            ident_source=digest(source)
            if await connection.fetchval('SELECT EXISTS(SELECT 1 FROM stage1_source_redactions WHERE digest=$1)',ident_source):
                receipts.append(ident_source)
    result=verify_boundary(value,require_raw=True,redaction_receipt=receipt,source_receipts=receipts)
    if not value.get('redacted'):
        await connection.execute('INSERT INTO stage1_boundary_checks(witness_id,digest) VALUES($1,$2) ON CONFLICT DO NOTHING',ident,value['digest'])
    return result


async def verified_archive_records(connection, genesis, scope, inputs):
    """Keeper imports resolve retained sources, never trust a caller's witness alone."""
    for side in ('opening','closing'):
        ident=inputs[side].get('producer_witness')
        raw=await connection.fetchval('SELECT witness FROM stage1_boundary_witnesses WHERE digest=$1 AND genesis=$2 AND program=$3 AND hill=$4 AND boundary=$5',
            ident,genesis,scope['program'],scope['hill'],inputs[side]['boundary'])
        if not raw:
            raise ValueError('missing retained producer witness')
        witness=await verify_retained_boundary(connection,ident,json.loads(raw) if isinstance(raw,str) else raw)
        if (witness['city']!=scope['city'] or witness['canon_id']!=str(scope['canon_id']) or witness['launch']!=inputs['launch']
            or inputs['context'] != [scope['program'],scope['city'],scope['hill'],inputs['context'][3],scope['mint']]):
            raise ValueError('archive namespace differs from retained witness')
        if side=='opening':
            if {k:v for k,v in inputs[side].items() if k!='producer_witness'}!=witness['opening']:
                raise ValueError('opening differs from retained witness')
        else:
            expected=closing_envelope(witness,ident)
            if inputs[side]!=expected:
                raise ValueError('closing differs from retained witness')
    return witness['records']


def closing_envelope(witness,ident=None):
    return dict(boundary=witness['boundary'],slot=witness['slot'],commitment='finalized',evidence=witness['source_digest'],
                assets=witness['assets'],records_digest=witness['records_digest'],producer_witness=ident or witness['digest'],**witness['records'])


def boundary_coverage(coverage,checkpoints,boundary):
    # The first observed bank after T is the historical upper fence, not today's
    # epoch. A provider rate is usable only if the selected bank straddles T in
    # that same Solana epoch. Unobserved epoch changes remain held.
    after=next((p for p in checkpoints if p['block_time']>=boundary and p['slot']<=coverage['through_slot']),None)
    if not after:
        raise MissingBoundary('finalized_replay_not_through_boundary')
    return {**coverage,'through_slot':after['slot'],'through_time':after['block_time'],'through_epoch':after['epoch']}


async def produce_once(pool, export_dir=None):
    """DB-backed task/retry schedule; advisory lock serializes writers across restarts."""
    async with pool.acquire() as c:
        locked=await c.fetchval("SELECT pg_try_advisory_lock(hashtextextended('stage1_boundaries',0))")
        if not locked:
            return {'state':'busy'}
        try:
            if export_dir:
                from .stage1_keeper_erasure import export_lock
                directory=Path(export_dir)
                for entry in await c.fetch('SELECT id,path,digest FROM stage1_boundary_exports WHERE prune_pending AND suspended LIMIT 100'):
                    path=Path(entry['path'])
                    if path.parent!=directory or path.name!=entry['id']+'.json' or path.is_symlink() or directory.is_symlink() or directory.resolve()!=directory:
                        raise ValueError('invalid boundary prune path')
                    with export_lock(directory,entry['id']):
                        if path.exists():
                            if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['digest']:
                                raise ValueError('boundary prune digest changed')
                            path.unlink()
                        await c.execute('SELECT stage1_boundary_export_pruned($1,$2)',entry['id'],entry['digest'])
            network=await c.fetchrow('SELECT n.* FROM stage1_indexer_network n JOIN program_version_observations v ON v.genesis_hash=n.genesis AND v.program_id=n.program WHERE '+STAGE1_OBSERVED_VERSION_SQL+' AND n.ready')
            if not network:
                return {'state':'not available on this network'}
            unchecked=await c.fetch('''SELECT w.digest,w.witness FROM stage1_boundary_witnesses w
                WHERE NOT EXISTS(SELECT 1 FROM stage1_boundary_failures f WHERE f.witness_id=w.digest AND f.retry_at>now())
                AND NOT EXISTS(SELECT 1 FROM stage1_boundary_checks v WHERE v.witness_id=w.digest AND v.digest=w.witness->>'digest')
                AND NOT EXISTS(SELECT 1 FROM stage1_boundary_redactions r WHERE r.witness_id=w.digest AND r.current_digest=w.witness->>'digest')
                ORDER BY boundary,hill LIMIT 100''')
            for row in unchecked:
                try:
                    await verify_retained_boundary(c,row['digest'],json.loads(row['witness']))
                except (ValueError,KeyError):
                    await c.execute("INSERT INTO stage1_boundary_failures(witness_id,retry_at) VALUES($1,now()+interval '15 minutes') ON CONFLICT(witness_id) DO UPDATE SET retry_at=EXCLUDED.retry_at",row['digest'])
                    logging.getLogger(__name__).warning('Stage 1 witness failed independent verification')
            coverage=dict(network)
            coverage.pop('singleton');coverage.pop('updated_at');coverage.pop('ready')
            current=[]
            for table,kind in [('hills','Stage1HillBond'),('cities','Stage1CityConfig')]:
                current.extend(dict(address=r['address'],type=kind,fields=json.loads(r['data'])) for r in
                    await c.fetch(f'SELECT address,data FROM indexed_stage1_{table} WHERE NOT closed'))
            tasks=await c.fetch("SELECT * FROM stage1_boundary_tasks WHERE genesis=$1 AND program=$2 AND state<>'complete' AND imported_at IS NULL AND retry_at<=now() ORDER BY updated_at,week,hill LIMIT 100",network['genesis'],network['program'])
            completed=held=0
            for task in tasks:
                await c.execute("UPDATE stage1_boundary_tasks SET updated_at=now() WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",task['genesis'],task['program'],task['hill'],task['week'])
                try:
                    witnesses=[]
                    hill=next(a['fields'] for a in current if a['address']==task['hill'])
                    city=next(a['fields'] for a in current if a['address']==hill['city'])
                    launch=int(city['seasonAnchor'])
                    for boundary in (launch+task['week']*WEEK,launch+(task['week']+1)*WEEK):
                        if boundary>coverage['through_time']:
                            break
                        row=await c.fetchrow('SELECT digest,witness FROM stage1_boundary_witnesses WHERE genesis=$1 AND program=$2 AND hill=$3 AND boundary=$4',network['genesis'],network['program'],task['hill'],boundary)
                        retained=row['witness'] if row else None
                        if retained:
                            saved=await verify_retained_boundary(c,row['digest'],json.loads(retained))
                            if not witnesses and saved['opening'] is None:
                                raise MissingBoundary(saved['opening_error'])
                            witnesses.append((row['digest'],saved))
                            continue
                        # Only the TypeScript indexer produces witnesses. Python
                        # independently verifies retained sources before export.
                        raise MissingBoundary('producer_boundary_pending')
                    if len(witnesses)<2:
                        await c.execute("UPDATE stage1_boundary_tasks SET state='waiting',error=NULL,retry_at=now()+interval '1 minute' WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",task['genesis'],task['program'],task['hill'],task['week'])
                        continue
                    (opening_id,opening),(closing_id,closing)=witnesses
                    entries=[]
                    assets=[(mint,'cash') for mint in closing['assets']]
                    frozen_accounts=closing['source']['checkpoint']['accounts']
                    city=next(a['fields'] for a in frozen_accounts if a['address']==closing['city'])
                    program_config=next((a['fields'] for a in frozen_accounts if a['type']=='ProgramConfig'),None)
                    if program_config and int(city.get('dungStartWeekPlusOne',0)) and task['week']>=int(city['dungStartWeekPlusOne'])-1:
                        assets.append((program_config['dungMint'],'dung'))
                    for mint,kind in assets:
                        inputs=dict(context=[network['program'],opening['city'],task['hill'],task['week'],mint],canon_id=opening['canon_id'],launch=launch,
                            opening={**opening['opening'],'producer_witness':opening_id},
                            closing=closing_envelope(closing,closing_id))
                        if kind=='dung':
                            inputs['kind']='dung'
                        entries.append(dict(scope_id=digest([network['program'],task['hill'],mint]),week=task['week'],inputs=inputs))
                    await c.execute("UPDATE stage1_boundary_tasks SET state='complete',archive=$5::jsonb,digest=$6,attempts=attempts+1,error=NULL,updated_at=now() WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",task['genesis'],task['program'],task['hill'],task['week'],canonical(entries).decode(),digest(entries))
                    completed+=1
                except (ValueError,KeyError) as exc:
                    # Alerts never contain wallets, source bytes or provider URLs.
                    kind=str(exc) if isinstance(exc,MissingBoundary) else 'boundary_validation_failed'
                    if kind=='producer_boundary_pending':
                        held+=1
                        continue
                    await c.execute("UPDATE stage1_boundary_tasks SET state='held',attempts=attempts+1,error=$5,retry_at=now()+interval '15 minutes',updated_at=now() WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",task['genesis'],task['program'],task['hill'],task['week'],kind)
                    await c.execute('INSERT INTO stage1_boundary_alerts(genesis,program,hill,week,kind) VALUES($1,$2,$3,$4,$5) ON CONFLICT(genesis,program,hill,week,kind) DO UPDATE SET last_seen=now()',task['genesis'],task['program'],task['hill'],task['week'],kind)
                    logging.getLogger(__name__).warning('Stage 1 boundary held: week=%s reason=%s',task['week'],kind)
                    held+=1
            if export_dir:
                from .stage1_keeper_erasure import export_lock
                import tempfile
                directory=Path(export_dir)
                if not directory.is_absolute() or directory.is_symlink():
                    raise ValueError('boundary export directory must be an absolute mounted path')
                directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                if directory.resolve()!=directory:
                    raise ValueError('boundary export directory cannot traverse a symlink')
                rows=await c.fetch("SELECT genesis,program,hill,week,archive,digest FROM stage1_boundary_tasks WHERE genesis=$1 AND program=$2 AND state='complete' AND imported_at IS NULL AND exported_digest IS DISTINCT FROM digest ORDER BY updated_at,week,hill LIMIT 100",network['genesis'],network['program'])
                if not rows:
                    previous=await c.fetchval("SELECT path FROM stage1_boundary_exports WHERE NOT suspended AND NOT prune_pending ORDER BY id LIMIT 1")
                    return {'state':'waiting','completed':completed,'held':held,**({'archive':previous} if previous else {})}
                entries=[e for row in rows for e in json.loads(row['archive'])]
                ident=digest(['stage1-boundaries',network['genesis'],network['program'],entries])
                target=directory/(ident+'.json')
                data=canonical(entries)+b'\n'
                # Commit the immutable content manifest BEFORE filesystem IO.
                # A crash leaves an erasable manifested (possibly absent) file.
                # The session producer lock also fences prepare_erasure through
                # the final file write; no unmanifested private bytes exist.
                async with c.transaction():
                    manifest=await c.fetchrow('SELECT * FROM stage1_boundary_exports WHERE id=$1 FOR UPDATE',ident)
                    if manifest and manifest['suspended']:
                        return {'state':'erasure_pending','completed':completed,'held':held}
                    if manifest and manifest['path']!=str(target):
                        raise ValueError('boundary export volume differs from retained manifest')
                    if manifest and manifest['digest']!=hashlib.sha256(data).hexdigest():
                        raise ValueError('boundary export was erased')
                    await c.execute('INSERT INTO stage1_boundary_exports(id,path,digest,payload) VALUES($1,$2,$3,$4::jsonb) ON CONFLICT DO NOTHING',ident,str(target),hashlib.sha256(data).hexdigest(),canonical(entries).decode())
                with export_lock(directory,ident):
                    fd,name=tempfile.mkstemp(prefix='.'+ident+'-',dir=directory)
                    try:
                        with os.fdopen(fd,'wb') as stream:
                            stream.write(data);stream.flush();os.fsync(stream.fileno())
                        os.replace(name,target)
                        fd=os.open(directory,os.O_RDONLY)
                        try: os.fsync(fd)
                        finally: os.close(fd)
                    finally:
                        if os.path.exists(name): os.unlink(name)
                for row in rows:
                    await c.execute('UPDATE stage1_boundary_tasks SET exported_digest=$5 WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4',row['genesis'],row['program'],row['hill'],row['week'],row['digest'])
            return {'state':'complete' if completed else 'waiting','completed':completed,'held':held,**({'archive':str(target)} if export_dir else {})}
        finally:
            await c.execute("SELECT pg_advisory_unlock(hashtextextended('stage1_boundaries',0))")


async def run(once=False):
    if os.getenv('STAGE1_BOUNDARY_ENABLED','false').lower() not in ('true','1'):
        return {'state':'disabled'}
    import asyncpg
    pool=await asyncpg.create_pool(os.environ['STAGE1_BOUNDARY_DATABASE_URL'],min_size=1,max_size=2)
    try:
        while True:
            try:
                result=await produce_once(pool,os.environ['STAGE1_BOUNDARY_EXPORT_DIR'])
                if once:
                    return result
            except Exception:
                logging.getLogger(__name__).error('Stage 1 boundary source unavailable; retrying')
                if once:
                    raise
            await asyncio.sleep(60)
    finally:
        await pool.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    print(json.dumps(asyncio.run(run(parser.parse_args().once))))
