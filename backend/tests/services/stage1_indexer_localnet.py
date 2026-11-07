"""Local validator bridge: actual indexed boundaries, explicitly synthetic ride sources."""
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

import asyncpg
from app.services.stage1_boundary import produce_once, verify_boundary
from tests.services.stage1_keeper_localnet import execute as settle, seed_canon
from tests.services.stage1_keeper_schema import schema


async def execute(request):
    dsn=os.environ['STAGE1_KEEPER_TEST_DSN']
    if urlparse(dsn).hostname!='127.0.0.1' or urlparse(request['rpc']).hostname!='127.0.0.1':
        raise ValueError('local test endpoints required')
    if request['action']=='settle':
        entries=json.loads(Path(request['archive']).read_text())
        selected=next(e for e in entries if e['week']==1 and e['inputs']['context'][-1]==request['mint'])
        return await settle({**request,**selected['inputs'],'week':1})
    if request['action']=='payout':
        return await settle({**request,'payout':True,'week':1})
    pool=await asyncpg.create_pool(dsn,min_size=1,max_size=3)
    try:
        if request['action']=='initialize':
            async with pool.acquire() as c:
                await schema(c)
                await seed_canon(c,request['canon_id'])
            return {'initialized':True}
        result=await produce_once(pool,request['boundary_export_dir'])
        async with pool.acquire() as c:
            rows=await c.fetch('SELECT witness FROM stage1_boundary_witnesses ORDER BY boundary')
            witnesses=[verify_boundary(json.loads(r['witness']),require_raw=True) for r in rows]
            result['witnesses']=[{'boundary':w['boundary'],'digest':w['digest'],'records_digest':w['records_digest'],'opening_live':w['opening']['live'] if w['opening'] else None} for w in witnesses]
            result['tasks']=[dict(r) for r in await c.fetch('SELECT week,state,error FROM stage1_boundary_tasks ORDER BY week')]
        return result
    finally:
        await pool.close()

if __name__=='__main__':
    print(json.dumps(asyncio.run(execute(json.load(sys.stdin)))))
