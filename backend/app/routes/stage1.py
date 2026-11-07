"""Owner reads and an explicit aggregate-only public hill projection."""
import json
import time
import struct
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from solders.pubkey import Pubkey

from ..db_pool import get_pool
from ..dependencies import AuthenticatedUser, get_current_user
from ..program_compatibility import STAGE1_OBSERVED_VERSION_SQL, STAGE1_UNAVAILABLE
from ..middleware.rate_limiter import rate_limit
from ..services.stage1_keeper_allocation import SPLIT
from ..services.stage1_transactions import SPONSOR_CASH_ADAPTER

router=APIRouter()
from .stage1_actions import router as actions_router
router.include_router(actions_router)
_bonding_cache={}


def unpack(value):
    if isinstance(value,str):
        return json.loads(value)
    return value


def row_json(row):
    return {k:str(v) if isinstance(v,Decimal) else v for k,v in dict(row).items()}


def hill_state(value):
    return {k:value[k] for k in ('bonded','foundingCutoff','foundingFreshSlots','assetLots') if k in value} if value else None


def city_state(value):
    return {k:value[k] for k in ('seasonAnchor','providerSlots','assetCount','intakePaused') if k in value} if value else None


def canon_name_sql(hill):
    return f"""(SELECT CASE WHEN count(*)=1 THEN min(c.display_name) END FROM indexed_stage1_hills nh
      JOIN indexed_climbs i ON i.pda=nh.data->>'climb' AND NOT i.quarantined
      JOIN canon_climbs c ON c.id=i.canon_climb_id AND c.status IN ('ratified','retired')
      WHERE nh.address={hill} AND NOT nh.closed)"""


async def stage1_connection(response: Response):
    response.headers['Cache-Control']='private, no-store'
    from .. import solana_direct
    config=solana_direct.load_readonly_config()
    pool=await get_pool()
    async with pool.acquire() as c:
        network=await c.fetchrow(f"""SELECT n.through_slot,n.updated_at FROM stage1_indexer_network n
          JOIN program_version_observations v ON v.genesis_hash=n.genesis AND v.program_id=n.program
          WHERE {STAGE1_OBSERVED_VERSION_SQL} AND n.program=$1 AND n.ready
          AND n.updated_at>now()-interval '90 seconds'""",str(config.program_id))
        if not network:
            raise HTTPException(503,STAGE1_UNAVAILABLE)
        response.headers['X-Indexed-Slot']=str(network['through_slot'])
        yield c


async def public_stage1_connection(request: Request,response: Response):
    # The indexer owns network observations. A public read never calls RPC.
    from .. import solana_direct
    config=solana_direct.load_readonly_config()
    pool=await get_pool()
    async with pool.acquire() as c:
        network=await c.fetchrow(f"""SELECT n.genesis,n.program,n.through_slot,n.updated_at FROM stage1_indexer_network n
          JOIN program_version_observations v ON v.genesis_hash=n.genesis AND v.program_id=n.program
          WHERE n.program=$1 AND {STAGE1_OBSERVED_VERSION_SQL} AND n.ready AND n.updated_at>now()-interval '90 seconds'""",str(config.program_id))
        if not network:
            raise HTTPException(503,STAGE1_UNAVAILABLE,headers={'Cache-Control':'no-store'})
        response.headers['Cache-Control']='public, max-age=15'
        response.headers['X-Indexed-Slot']=str(network['through_slot'])
        request.state.stage1_namespace=(network.get('genesis'),network.get('program'))
        yield c


@router.get('/me/registration')
async def registration(hill: str=None,user: AuthenticatedUser=Depends(get_current_user),c=Depends(stage1_connection)):
    row=await c.fetchrow("SELECT data,chain_slot FROM indexed_stage1_recipients WHERE data->>'person'=$1 AND NOT closed",user.wallet)
    # Only the latest completed allocation per scope is outstanding. Summing
    # historical allocations would count carried holds repeatedly.
    held=await c.fetch(f"""SELECT s.hill,{canon_name_sql("s.hill")} AS climb_name,s.mint,j.week,sum((source.value->>$1)::numeric)::text AS amount
      FROM (SELECT DISTINCT ON(scope_id) scope_id,week,allocation FROM stage1_keeper_jobs
        WHERE state='complete' ORDER BY scope_id,week DESC) j
      JOIN stage1_keeper_scopes s ON s.id=j.scope_id
      CROSS JOIN LATERAL jsonb_each(coalesce(j.allocation->'reserved','{{}}')) source
      WHERE ($2::text IS NULL OR s.hill=$2) AND (source.value->>$1)::numeric>0
      GROUP BY s.hill,s.mint,j.week ORDER BY j.week DESC,s.hill,s.mint""",user.wallet,hill)
    return {'registration':None if not row else {**unpack(row['data']),'indexed_slot':row['chain_slot']},
            'held':[row_json(r) for r in held]}


async def owner_pay(c,wallet,kind,hill,week,limit,offset):
    rows=await c.fetch(f"""SELECT hill,{canon_name_sql("p.hill")} AS climb_name,week,mint,recipient,amount,kind,signature,chain_slot
      FROM indexed_stage1_payouts p WHERE person=$1 AND ($2::text IS NULL OR kind=$2)
      AND ($3::text IS NULL OR hill=$3) AND ($4::numeric IS NULL OR week=$4)
      ORDER BY week DESC,hill,mint,claim_set,leaf_index LIMIT $5 OFFSET $6""",wallet,kind,hill,week,limit,offset)
    pending=await c.fetch(f"""SELECT s.hill,{canon_name_sql("s.hill")} AS climb_name,j.week,s.mint,s.program,p.role,p.leaf_index,p.leaf->>'recipient' AS recipient,
      p.leaf->>'amount' AS amount,s.kind FROM stage1_keeper_proofs p JOIN stage1_keeper_jobs j ON j.id=p.job_id
      JOIN stage1_keeper_scopes s ON s.id=j.scope_id WHERE p.person=$1 AND p.paid_slot IS NULL
      AND ($2::text IS NULL OR s.kind=$2) AND ($3::text IS NULL OR s.hill=$3) AND ($4::bigint IS NULL OR j.week=$4)
      ORDER BY j.week DESC,s.hill,s.mint,p.leaf_index,p.role,p.job_id LIMIT $5 OFFSET $6""",wallet,kind,hill,week,limit,offset)
    identities=[(claim_address(r),r['leaf_index']) for r in pending]
    finalized=await c.fetch("""SELECT claim_set,leaf_index FROM indexed_stage1_payouts
      WHERE person=$1 AND claim_set=ANY($2::text[])""",wallet,list({address for address,_ in identities})) if identities else []
    paid={(r['claim_set'],r['leaf_index']) for r in finalized}
    return {'has_more':len(rows)==limit or len(pending)==limit,'paid':[row_json(r) for r in rows],
            'pending':[row_json({k:r.get(k) for k in ('hill','climb_name','week','mint','recipient','amount','kind')})
                       for r,identity in zip(pending,identities) if identity not in paid]}


def claim_address(row):
    """Pure PDA derivation from the pinned Stage 1 ABI; never calls a signer/RPC."""
    program=Pubkey.from_string(row['program'])
    hill=bytes(Pubkey.from_string(row['hill']))
    week=struct.pack('<Q',int(row['week']))
    if row['kind']=='dung':
        dung=Pubkey.find_program_address([b's1v1_dung',hill,week],program)[0]
        seeds=[b's1v1_dung_claims',bytes(dung),bytes([row['role']])]
    else:
        seeds=[b's1v1_claims',hill,bytes(Pubkey.from_string(row['mint'])),week]
    return str(Pubkey.find_program_address(seeds,program)[0])


@router.get('/me/pay')
async def pay(hill: str=None,week: int=Query(None,ge=0),limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
              user:AuthenticatedUser=Depends(get_current_user),c=Depends(stage1_connection)):
    return await owner_pay(c,user.wallet,None,hill,week,limit,offset)


@router.get('/me/dung')
async def dung(hill: str=None,week: int=Query(None,ge=0),limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
               user:AuthenticatedUser=Depends(get_current_user),c=Depends(stage1_connection)):
    return await owner_pay(c,user.wallet,'dung',hill,week,limit,offset)


@router.get('/me/pledges')
async def pledges(hill:str=None,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),
                  user:AuthenticatedUser=Depends(get_current_user),c=Depends(stage1_connection)):
    rows=await c.fetch(f"""SELECT l.address,l.data,l.chain_slot,h.data AS hill_data,
      {canon_name_sql("l.data->>'hill'")} AS climb_name,n.through_time,n.through_epoch,a.data AS asset_data,city.data AS city_data,COALESCE((SELECT jsonb_agg(jsonb_build_object(
      'address',r.address,'data',r.data,'parent_deposit_id',(SELECT parent.data->>'depositId' FROM indexed_stage1_lots parent WHERE parent.address=r.data->>'lot'),'indexed_slot',r.chain_slot) ORDER BY r.address)
      FROM indexed_stage1_withdrawals r WHERE r.data->>'owner'=$1 AND (r.data->>'lot'=l.address OR r.data->>'exitLot'=l.address)),'[]'::jsonb) AS withdrawals
      FROM indexed_stage1_lots l LEFT JOIN indexed_stage1_hills h ON h.address=l.data->>'hill' AND NOT h.closed
      LEFT JOIN indexed_stage1_assets a ON a.data->>'mint'=l.data->>'mint' AND a.data->>'city'=l.data->>'city' AND NOT a.closed
      LEFT JOIN indexed_stage1_cities city ON city.address=l.data->>'city' AND NOT city.closed
      CROSS JOIN stage1_indexer_network n
      WHERE l.data->>'owner'=$1 AND ($4::text IS NULL OR l.data->>'hill'=$4)
      ORDER BY (l.data->>'depositedAt')::bigint DESC,l.address LIMIT $2 OFFSET $3""",user.wallet,limit,offset,hill)
    return {'pledges':[{'address':r['address'],**effective_pledge(unpack(r['data']),unpack(r['hill_data'])),
                       'climb_name':r.get('climb_name'),'hill_state':hill_state(unpack(r['hill_data'])),
                       'asset_state':unpack(r.get('asset_data')),'city_state':city_state(unpack(r.get('city_data'))),
                       'chain_time':str(r['through_time']) if r.get('through_time') is not None else None,
                       'chain_epoch':str(r['through_epoch']) if r.get('through_epoch') is not None else None,
                       'withdrawals':unpack(r['withdrawals']),'indexed_slot':r['chain_slot']} for r in rows]}


def effective_pledge(lot,hill):
    result=dict(lot)
    if not hill:
        # Raw lazy fields are not evidence of the effective lock/founder state.
        for key in ('founding','lockWeeks','lockEnd'):
            result.pop(key,None)
        return result
    slot=int(lot['assetSlot'])
    founding=hill['bonded'] and not lot['cancelled'] and not lot['exiting'] and not lot['converted'] \
        and 0<int(lot['sequence'])<=int(hill['foundingCutoff']) and 0<=slot<32 \
        and bool(int(hill['foundingFreshSlots']) & (1<<slot))
    if founding:
        result.update(founding=True,lockWeeks=26,lockEnd=str(int(hill['bondedAt'])+26*604800))
        if not lot['founding']:
            n,d=int(hill['quotedNumerators'][slot]),int(hill['quotedDenominators'][slot])
            if n<=0 or d<=0:
                raise HTTPException(503,'Pledge projection incomplete')
            result['units']=str(min(int(lot['units']),(int(lot['basisLamports'])*d+n-1)//n))
    return result


@router.get('/climbs/{climb_id}/hill')
@rate_limit(category='leaderboard')
async def climb_hill(climb_id:UUID,request:Request,c=Depends(public_stage1_connection)):
    # A route UUID is not a hill PDA. Resolve only an unambiguous admitted
    # canonical climb; no client-side address guesses or legacy-vault aliases.
    rows=await c.fetch("""SELECT h.address AS hill FROM indexed_stage1_hills h
      JOIN indexed_climbs i ON i.pda=h.data->>'climb' AND NOT i.quarantined
      JOIN canon_climbs c ON c.id=i.canon_climb_id
      WHERE c.id=$1 AND c.status IN ('ratified','retired') AND NOT h.closed LIMIT 2""",climb_id)
    return {'hill':rows[0]['hill'] if len(rows)==1 else None}


@router.get('/hills/{hill}/bonding')
@rate_limit(category='leaderboard')
async def bonding(hill:str,request:Request,c=Depends(public_stage1_connection)):
    try:
        Pubkey.from_string(hill)
    except ValueError:
        raise HTTPException(422,'Invalid hill') from None
    cache_key=(getattr(request.state,'stage1_namespace',id(c)),hill)
    cached=_bonding_cache.get(cache_key)
    if cached and cached[0]>time.monotonic():
        return cached[1]
    row=await c.fetchrow("""SELECT h.data AS hill,c.data AS city,h.chain_slot,n.through_time,n.through_epoch
      FROM indexed_stage1_hills h JOIN indexed_stage1_cities c ON c.address=h.data->>'city'
      CROSS JOIN stage1_indexer_network n WHERE h.address=$1 AND NOT h.closed""",hill)
    if not row:
        raise HTTPException(404,'Hill not found')
    h,city=unpack(row['hill']),unpack(row['city'])
    week=max(0,(row['through_time']-int(city['seasonAnchor']))//604800)
    assets=await c.fetch("SELECT address,data AS asset FROM indexed_stage1_assets WHERE data->>'city'=$1 AND NOT closed ORDER BY data->>'mint'",h['city'])
    lots=[unpack(r['data']) for r in await c.fetch("SELECT data FROM indexed_stage1_lots WHERE data->>'hill'=$1 AND NOT closed",hill)]
    books=await c.fetch("SELECT data FROM indexed_stage1_funding WHERE data->>'hill'=$1 AND (data->>'week')::numeric=$2",hill,week)
    by_mint={unpack(r['data'])['mint']:unpack(r['data']) for r in books}
    result=[]
    for r in assets:
        asset=unpack(r['asset']);mint=asset['mint']
        # Sponsor cash funds weekly pools; it never backs the bonding line.
        item={'mint':mint,'backing_eligible':int(asset['adapter'])!=SPONSOR_CASH_ADAPTER,'config':asset}
        fresh=(int(asset['adapter'])==1 and row['through_time']<int(asset['lastFreshUntil'])) or (
            int(asset['adapter']) in (2,3,4,5) and int(asset['admittedEpoch'])==row['through_epoch'])
        if not h['bonded']:
            slot=int(asset['slot'])
            fresh=fresh and int(h['rateEpochs'][slot])==int(city['rateEpochs'][slot]) and int(h['quotedCount'][slot])==int(h['assetLots'][slot])
        if fresh and int(asset['admittedNumerator'])>0 and int(asset['admittedDenominator'])>0:
            item['backing_lamports']=str(asset_backing(h,lots,asset))
        if mint in by_mint:
            b=by_mint[mint];item['week_pool']={k:b[k] for k in ('available','pool','published')}
        result.append(item)
    # Cash sponsorship can fund a hill without an admitted staking asset.
    for mint,b in by_mint.items():
        if not any(item['mint']==mint for item in result):
            result.append({'mint':mint,'backing_eligible':False,'week_pool':{k:b[k] for k in ('available','pool','published')}})
    result={'hill':hill,'bonded':h['bonded'],'founding_count':h['foundingCount'],'line_lamports':city['lineLamports'],
            'week':week,'climb':h.get('climb'),'hill_state':hill_state(h),
            'city_state':city_state(city),
            'chain_time':str(row['through_time']),'chain_epoch':str(row['through_epoch']),'assets':result,'split':SPLIT,'indexed_slot':row['chain_slot']}
    if len(_bonding_cache)>=128:
        _bonding_cache.clear()
    _bonding_cache[cache_key]=(time.monotonic()+15,result)
    return result


def asset_backing(hill,lots,asset):
    """Per-lot conservative principal; immutable founding quotes precede floors."""
    total=0
    n,d=int(asset['admittedNumerator']),int(asset['admittedDenominator'])
    for lot in lots:
        if lot['mint']!=asset['mint'] or lot['cancelled'] or lot['exiting']:
            continue
        units,basis=int(lot['units']),int(lot['basisLamports'])
        slot=int(lot['assetSlot'])
        if hill['bonded'] and not lot['converted'] and int(lot['sequence'])<=int(hill['foundingCutoff']):
            if not (int(hill['foundingFreshSlots']) & (1<<slot)):
                continue
            if not lot['founding']:
                qn,qd=int(hill['quotedNumerators'][slot]),int(hill['quotedDenominators'][slot])
                if not qn or not qd:
                    raise HTTPException(503,'Bonding projection incomplete')
                units=min(units,(basis*qd+qn-1)//qn)
        elif not hill['bonded']:
            # Before bonding, current quotes value every unconverted pledge.
            # A stale refresh cannot count towards the automatic bonding line.
            if lot['converted'] or int(lot['quoteEpoch'])!=int(hill['rateEpochs'][slot]):
                continue
        total+=min(basis,units*n//d)
    return total


@router.get('/mints')
@rate_limit(category='leaderboard')
async def mint_registry(request: Request, c=Depends(public_stage1_connection)):
    # The canonical singleton is immutable and admission enforces 9 decimals.
    from ..solana_direct import load_readonly_config
    program = load_readonly_config().program_id
    address = str(Pubkey.find_program_address([b's1v1_test_pool'], program)[0])
    row = await c.fetchrow("SELECT data FROM indexed_stage1_test_pools WHERE address=$1 AND NOT closed", address)
    return {'test_pool_mint': unpack(row['data'])['mint'] if row else None}
