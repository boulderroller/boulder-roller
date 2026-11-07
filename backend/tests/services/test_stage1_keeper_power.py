"""Synthetic native-power inputs in real migrated PostgreSQL source tables."""
import json
import os
import uuid

import asyncpg
import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_dung import measured_tss
from app.services.stage1_keeper_snapshot import COMPLETIONS_SQL
from tests.services.stage1_keeper_schema import schema
from tests.services.stage1_keeper_localnet import seed_canon, seed_ride


@pytest.mark.asyncio
async def test_canonical_power_uses_verified_frozen_ftp_and_paid_spans():
    dsn = os.getenv('STAGE1_KEEPER_TEST_DSN')
    if not dsn:
        pytest.skip('disposable local PostgreSQL required')
    admin = await asyncpg.connect(dsn)
    database = 'keeper_power_' + uuid.uuid4().hex
    await admin.execute(f'CREATE DATABASE "{database}"')
    c = await asyncpg.connect(dsn,database=database)
    try:
        person,canon,launch = str(Keypair().pubkey()),uuid.uuid4(),1791201600
        await schema(c,[person])
        await seed_canon(c,canon)
        async with c.transaction():
            await seed_ride(c,str(canon),person,1,launch,0,powered=True)
        rows = await c.fetch(COMPLETIONS_SQL,canon,launch+2*604800+86400)
        assert len(rows) == 1
        row = dict(rows[0])
        row['_power'] = json.loads(row['_power'])
        assert row['_power']['reward_ftp_w'] == 200
        result = measured_tss(row)
        assert result['tss_micros'] == 1_666_666
        assert '_power' not in result and len(result['tss_provenance']) == 64
    finally:
        await c.close()
        await admin.execute(f'DROP DATABASE "{database}"')
        await admin.close()
