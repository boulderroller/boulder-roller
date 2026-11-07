import asyncio
import json

import pytest

from app.services.stage1_keeper_snapshot import COMPLETIONS_SQL
from tests.services.test_stage1_keeper_worker import store, migrated_template
from tests.services.stage1_keeper_localnet import seed_canon, seed_ride
from tests.services.test_stage1_keeper_snapshot import inputs, PEOPLE, LAUNCH, WEEK
from app.services.stage1_keeper_store import KeeperStore
from app.services.stage1_keeper_merkle import digest


@pytest.fixture
def source_store(store):
    async def setup():
        async with store.pool.acquire() as c:
            scope = dict(await c.fetchrow("SELECT * FROM stage1_keeper_scopes"))
            canon = scope["canon_id"]
            await seed_canon(c, canon)
        return scope
    store.test_scope = asyncio.run(setup())
    # Use the actual SQL/snapshot implementation, not the worker fixture's fake.
    del store.snapshot
    return store


@pytest.mark.asyncio
async def test_canon_traversals_enter_field_without_any_legacy_vault(source_store):
    store, scope = source_store, source_store.test_scope
    async with store.pool.acquire() as c:
        for i, person in enumerate(PEOPLE[:5]):
            await seed_ride(c, str(scope["canon_id"]), person, 1, LAUNCH, i, release=i==4)
        rows = await c.fetch(COMPLETIONS_SQL, scope["canon_id"], LAUNCH+2*WEEK)
        assert len(rows) == 5 and all(r["trusted"] for r in rows)
        assert await c.fetchval("SELECT count(*) FROM indexed_vaults") == 0
    data = inputs()
    data["canon_id"] = str(scope["canon_id"])
    await store.archive_boundary(scope["id"], 1, data)
    claim = await store.claim(scope["id"])
    frozen = await store.snapshot(claim, data["recipients"])
    assert frozen["field"] and len(frozen["rides"]) == 5
    assert PEOPLE[4] in frozen["ascents"]


@pytest.mark.asyncio
async def test_prior_admission_survives_private_ride_deletion(source_store):
    store, scope = source_store, source_store.test_scope
    async with store.pool.acquire() as c:
        for i, person in enumerate(PEOPLE[:5]):
            await seed_ride(c, str(scope["canon_id"]), person, 0, LAUNCH, i, offset=WEEK-10)
        await c.execute("UPDATE stage1_keeper_scopes SET next_week=0 WHERE id=$1", scope["id"])
    data = inputs(0)
    data["canon_id"] = str(scope["canon_id"])
    await store.archive_boundary(scope["id"], 0, data)
    first = await store.claim(scope["id"])
    frozen = await store.snapshot(first, data["recipients"])
    assert frozen["field"]
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_jobs SET snapshot=$1::jsonb,state='complete' WHERE id=$2", json.dumps(frozen), first["job"]["id"])
        # Model the existing privacy deletion, in this disposable test database.
        await c.execute("DELETE FROM rides WHERE id IN (SELECT ride_id FROM ride_economic_plans)")
        await c.execute("UPDATE stage1_keeper_scopes SET next_week=1 WHERE id=$1", scope["id"])
        await seed_ride(c, str(scope["canon_id"]), PEOPLE[0], 1, LAUNCH, 0, offset=10)
    await store.release(first)
    second = inputs(1)
    second["canon_id"] = str(scope["canon_id"])
    await store.archive_boundary(scope["id"], 1, second)
    claim = await store.claim(scope["id"])
    result = await store.snapshot(claim, second["recipients"])
    assert result["field"] and result["ascents"] == {}


@pytest.mark.asyncio
async def test_boundary_is_immutable_and_migration_mirror_exact(source_store):
    from pathlib import Path
    store, scope = source_store, source_store.test_scope
    data = inputs(1)
    await store.archive_boundary(scope["id"], 1, data)
    with pytest.raises(ValueError, match="conflicts"):
        await store.archive_boundary(scope["id"], 1, {**data, "launch": 1})
    async with store.pool.acquire() as c:
        with pytest.raises(Exception, match="immutable"):
            await c.execute("DELETE FROM stage1_keeper_boundaries WHERE scope_id=$1", scope["id"])
    backend = Path(__file__).parents[2]
    assert (backend/"sql/170_stage1_keeper.sql").read_bytes() == (backend/"supabase/migrations/20261015010000_170_stage1_keeper.sql").read_bytes()


@pytest.mark.asyncio
async def test_assets_share_admission_after_private_ride_deletion(source_store):
    store, scope = source_store, source_store.test_scope
    data = inputs(1)
    data["canon_id"] = str(scope["canon_id"])
    data["closing"]["assets"].append("mint2")
    async with store.pool.acquire() as c:
        for i, person in enumerate(PEOPLE[:5]):
            await seed_ride(c, str(scope["canon_id"]), person, 1, LAUNCH, i)
    await store.archive_boundary(scope["id"], 1, data)
    first = await store.claim(scope["id"])
    one = await store.snapshot(first, data["recipients"])
    async with store.pool.acquire() as c:
        await c.execute("DELETE FROM rides")
    two_id = await store.add_scope({**scope, "canon_id": str(scope["canon_id"]), "mint": "mint2"})
    data["context"][-1] = "mint2"
    await store.archive_boundary(two_id, 1, data)
    second = await store.claim(two_id)
    two = await store.snapshot(second, data["recipients"])
    assert one["ascents"] == two["ascents"] and two["field"]
    assert len(two["rides"]) == 5


@pytest.mark.asyncio
async def test_record_archive_retry_uses_frozen_records_after_indexer_advances(source_store):
    store, scope = source_store, source_store.test_scope
    async with store.pool.acquire() as c:
        await c.execute("""INSERT INTO indexed_climbs(pda,canon_climb_id,canon_commitment_hex,commitment_hash_hex,
            canon_id,canon_version,canonical_profile_hash_hex,record_continuity_policy,vault_pda,name,vert_m,
            distance_m,avg_gradient_pct,registered_at,registered_by,chain_slot)
            VALUES('climb',$1,repeat('a',128),repeat('b',64),$1,1,repeat('c',64),'new_record_board',
            'vault','fixture',100,1000,10,to_timestamp($2),'fixture',30)""", scope['canon_id'],LAUNCH)
        await c.execute("""INSERT INTO indexed_vaults(id,signature_hex,signature_hash_hex,minter,name,vert_m,
            distance_m,avg_gradient_pct,pda,created_at,climb_pda,canon_climb_id,canon_commitment_hex,canon_binding_status)
            VALUES(1,repeat('a',128),repeat('b',64),'fixture','fixture',100,1000,10,'vault',to_timestamp($2),
            'climb',$1,repeat('a',128),'active')""", scope['canon_id'],LAUNCH)
        await c.execute("""INSERT INTO indexed_program_config(admin_authority,backend_authority,pda,chain_slot,
            settlement_clock_v2_starts_at,settlement_clock_version,settlement_clock_source_commitment)
            VALUES('fixture','fixture','config',30,1704110400,2,'finalized')""")
        await c.execute("INSERT INTO indexed_leaderboards(vault_id,entries,chain_slot) VALUES(1,$1::jsonb,30)", json.dumps([{"user": PEOPLE[0], "time_s": 60, "recorded_at": str(LAUNCH)}]))
        epoch = (LAUNCH-1704110400)//WEEK
        await c.execute("""INSERT INTO indexed_legends(vault_id,holder,is_active,is_bootstrap,chain_slot,term_start_epoch,term_end_epoch)
            VALUES(1,$1,true,false,30,$2,$3)""", PEOPLE[1], epoch,epoch+3)
        records = await store.records_at_boundary(c, scope["canon_id"], inputs()["closing"])
    data = inputs()
    data["canon_id"] = str(scope["canon_id"])
    data["closing"]["records_digest"] = digest(records)
    await store.archive_boundary(scope["id"], 1, data)
    async with store.pool.acquire() as c:
        await c.execute("UPDATE indexed_leaderboards SET chain_slot=100,entries='[]'")
        await c.execute("UPDATE indexed_legends SET chain_slot=100,is_active=false")
    await store.archive_boundary(scope["id"], 1, data)
    claim = await store.claim(scope["id"])
    frozen = await store.snapshot(claim, data["recipients"])
    assert frozen["board"] == [PEOPLE[0]] and frozen["legend"] == PEOPLE[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("lag,admitted", [(1,True),(86399,True),(86400,False)])
async def test_indexer_lag_uses_upload_week_grace(source_store, lag, admitted):
    store, scope = source_store, source_store.test_scope
    async with store.pool.acquire() as c:
        await seed_ride(c, str(scope["canon_id"]), PEOPLE[0], 1, LAUNCH, 0, offset=WEEK-1)
        await c.execute("UPDATE patterns_climb SET created_at=to_timestamp($1)", LAUNCH+2*WEEK+lag)
        rows = await c.fetch(COMPLETIONS_SQL, scope["canon_id"], LAUNCH+2*WEEK)
    data = inputs()
    data["canon_id"] = str(scope["canon_id"])
    from app.services.stage1_keeper_snapshot import build_snapshot
    assert bool(build_snapshot(data, [dict(r) for r in rows])["rides"]) == admitted
