"""Actual archive/SQL redaction; historical lots remain offline attested inputs."""
import copy
import json
import uuid
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.services.stage1_keeper_dung import opening_weights
from tests.services.test_stage1_keeper_snapshot import inputs, PEOPLE
from tests.services.test_stage1_keeper_worker import store, migrated_template


def archive():
    data=inputs(1)
    program,city,hill,mint=[str(Keypair().pubkey()) for _ in range(4)]
    data.update(context=[program,city,hill,1,mint],canon_id=str(uuid.uuid4()))
    owner=PEOPLE[0]
    pda=lambda seed,*parts:str(Pubkey.find_program_address([seed,*parts],Pubkey.from_string(program))[0])
    lot={'address':pda(b's1v1_lot',bytes(Pubkey.from_string(owner)),(1).to_bytes(8,'little')),
        'city':city,'hill':hill,'mint':mint,'owner':owner,'deposit_id':1,'units':10,'basis_lamports':10,
        'lock_weeks':13,'lock_end':data['launch']+13*604800,'sequence':2,'asset_slot':0,
        'converted':True,'cancelled':False,'exiting':False,'founding':False,
        'pending_request':str(Keypair().pubkey()),'deposited_at':data['launch']+5,'raw_account_data':'private-bytes'}
    data['opening']['dung']={'hill':{'bonded':True,'bonded_at':data['launch'],
        'founding_cutoff':0,'founding_fresh_slots':0,'quoted_numerators':[1]*32,'quoted_denominators':[1]*32},
        'lots':[lot],'rates':{mint:{'mint':mint,'city':city,'asset':pda(b's1v1_asset',bytes(Pubkey.from_string(mint))),
        'numerator':1,'denominator':1,'boundary':data['opening']['boundary'],'slot':20,'evidence':'offline-test'}}}
    return data


@pytest.mark.asyncio
async def test_anonymized_validated_lot_retains_weight_without_personal_preimages(store):
    data=archive()
    p,c,h,w,m=data['context']
    scope=await store.add_scope(dict(program=p,city=c,hill=h,mint=m,canon_id=data['canon_id'],launch=data['launch'],next_week=w))
    await store.archive_boundary(scope,w,data)
    async with store.pool.acquire() as connection:
        saved=json.loads(await connection.fetchval('SELECT inputs FROM stage1_keeper_boundaries WHERE scope_id=$1',scope))
        erased=json.loads(await connection.fetchval('SELECT stage1_keeper_redact($1::jsonb,$2,$3)',json.dumps(saved),PEOPLE[0],'anonymous:test'))
    lot=erased['opening']['dung']['lots'][0]
    assert not set(lot)&{'address','deposit_id','exit_request','pending_request','deposited_at','raw_account_data'}
    before=opening_weights(saved['opening'],data['launch'],w,data['context'])
    after=opening_weights(erased['opening'],data['launch'],w,data['context'])
    assert before['weights']=={PEOPLE[0]:20} and after['weights']=={'anonymous:test':20}
    assert after['basis']==before['basis'] and after['backing']==before['backing']
    # Exact retry authenticates by the immutable request digest, without
    # accepting a new archive that supplies its own "validated" anonymous lot.
    with pytest.raises(ValueError,match='anonymous'):
        await store.archive_boundary(scope,2,{**erased,'context':[p,c,h,2,m]})


@pytest.mark.asyncio
async def test_archive_rejects_two_states_of_same_lot(store):
    data=archive()
    other=copy.deepcopy(data['opening']['dung']['lots'][0]);other['units']=9
    data['opening']['dung']['lots'].append(other)
    p,c,h,w,m=data['context']
    scope=await store.add_scope(dict(program=p,city=c,hill=h,mint=m,canon_id=data['canon_id'],launch=data['launch'],next_week=w))
    with pytest.raises(ValueError,match='duplicate'):
        await store.archive_boundary(scope,w,data)


@pytest.mark.asyncio
async def test_erasure_preserves_odd_rider_and_backer_shares(store):
    from app.services.stage1_keeper_dung import freeze_dung_opening,dung_plan
    from app.services.stage1_keeper_worker import independent
    data=archive()
    other=copy.deepcopy(data['opening']['dung']['lots'][0])
    other.update(owner=PEOPLE[1],deposit_id=2,address=str(Pubkey.find_program_address(
        [b's1v1_lot',bytes(Pubkey.from_string(PEOPLE[1])),(2).to_bytes(8,'little')],Pubkey.from_string(data['context'][0]))[0]))
    data['opening']['dung']['lots'].append(other)
    data['opening']=freeze_dung_opening(data['opening'],data['context'])
    snapshot={**data,'field_people':PEOPLE[:5],'board':[],'legend':None,
        'recipients':{PEOPLE[1]:PEOPLE[1]},'rider_tie_ranks':{PEOPLE[0]:0,PEOPLE[1]:1},
        'rides':[{'person':p,'paid_ascent':True,'tss_micros':3,'ridden_at':data['launch']+100} for p in PEOPLE[:2]]}
    before=dung_plan(snapshot,{'dung_tss_ceiling_micros':100})[1]
    async with store.pool.acquire() as c:
        erased=json.loads(await c.fetchval('SELECT stage1_keeper_redact($1::jsonb,$2,$3)',json.dumps(snapshot),PEOPLE[0],'anonymous:test'))
    # The bounded post-bond fact, frozen by the real admission builder, survives
    # removal of private timestamps. This fixture supplies that fact explicitly.
    for row in erased['rides']:
        if row['person'].startswith('anonymous:'):
            row.update(post_bond=True,bond_eligibility_digest='a'*64)
    after=dung_plan(erased,{'dung_tss_ceiling_micros':100})[1]
    assert before==after and after['backers'][PEOPLE[1]]==1 and after['unminted']==5
    assert (await independent({**erased,'kind':'dung'},[]))['allocation']==after
