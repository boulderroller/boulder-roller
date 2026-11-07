"""Composed-release contracts; encoded local accounts, never provider evidence."""
import base64
import copy
import hashlib
import json
import struct

import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_chain import KeeperChain
from app.services.stage1_keeper_paths import IDL


def test_filtered_offsets_refuse_a_moved_release_layout(tmp_path):
    idl = json.loads(IDL.read_text())
    account = next(a for a in idl['accounts'] if a['name'] == 'Stage1WeekFunding')
    account['type']['fields'].insert(3, {'name': 'movedLayout', 'type': 'bool'})
    changed = tmp_path / 'moved.json'
    changed.write_text(json.dumps(idl))
    with pytest.raises(ValueError, match='layout'):
        KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/unused', idl_path=changed)


@pytest.mark.asyncio
async def test_claim_inventory_fetches_bitmap_only_when_paid_changes():
    program, mint, hill = [str(Keypair().pubkey()) for _ in range(3)]
    chain = KeeperChain('http://127.0.0.1:8899', program, '/unused')
    scope = {'mint': mint, 'hill': hill}
    address = chain.claim_address(scope, 1)
    from solders.pubkey import Pubkey
    raw = bytearray(276)
    raw[:8] = hashlib.sha256(b'account:Stage1ClaimSet').digest()[:8]
    raw[40:72], raw[104:136] = bytes(Pubkey.from_string(hill)), bytes(Pubkey.from_string(mint))
    struct.pack_into('<Q', raw, 136, 1)
    raw[176:192] = (10).to_bytes(16, 'little')
    struct.pack_into('<I', raw, 192, 2)
    raw[273:275] = bytes([2, 0])
    bitmap_reads = []
    def account(data):
        return {'owner': program, 'executable': False, 'lamports': 1234,
                'data': [base64.b64encode(data).decode(), 'base64']}
    async def rpc(method, params):
        if method == 'getProgramAccounts':
            assert params[1]['dataSlice'] == {'offset': 260, 'length': 12}
            return {'context': {'slot': 100}, 'value': [{'pubkey': address, 'account': account(raw[260:272])}]}
        assert method == 'getMultipleAccounts'
        if 'dataSlice' in params[1]:
            assert params[1]['dataSlice'] == {'offset': 0, 'length': 275}
            return {'context': {'slot': 100}, 'value': [account(raw[:275])]}
        bitmap_reads.append(copy.deepcopy(params))
        return {'context': {'slot': 100}, 'value': [account(raw)]}
    chain.rpc = rpc
    try:
        _, first = await chain.cash_claim_inventory(scope, 0)
        assert first[address]['bitmap'] == '00' and not bitmap_reads
        raw[144:176] = bytes.fromhex('33'*32)
        raw[274] = 1
        _, sealed = await chain.cash_claim_inventory(scope, 0)
        assert sealed[address]['sealed'] and sealed[address]['root'] == '33'*32
        struct.pack_into('<QI', raw, 260, 5, 1)
        raw[275] = 1
        _, changed = await chain.cash_claim_inventory(scope, 0)
        assert changed[address]['bitmap'] == '01' and len(bitmap_reads) == 1
        await chain.cash_claim_inventory(scope, 0)
        assert len(bitmap_reads) == 1
        struct.pack_into('<QI', raw, 260, 10, 2)
        raw[275] = 3
        _, final = await chain.cash_claim_inventory(scope, 0)
        assert final[address]['bitmap'] == '03' and len(bitmap_reads) == 2
    finally:
        await chain.close()


def test_keeper_migration_has_its_new_number_and_timeout():
    from pathlib import Path
    backend = Path(__file__).parents[2]
    migration = backend / 'sql/170_stage1_keeper.sql'
    assert migration.read_bytes() == (backend / 'supabase/migrations/20261015010000_170_stage1_keeper.sql').read_bytes()
    assert migration.read_text().splitlines()[3] == "SET LOCAL lock_timeout = '5s';"
    assert not (backend / 'sql/169_stage1_keeper.sql').exists()

@pytest.mark.asyncio
async def test_rotation_prevents_signing_even_if_rpc_keeps_genesis(tmp_path):
    signer = Keypair()
    path = tmp_path / 'publisher.json'
    path.write_text(json.dumps(list(bytes(signer))))
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), path)
    chain.genesis = 'local'
    chain.signer = signer
    async def rpc(method, params):
        if method == 'getGenesisHash':
            return 'local'
        raise AssertionError('must verify city authorization before obtaining blockhash')
    async def multiple(addresses, floor=0, **kwargs):
        return 100, {addresses[0]: {'publisher': str(Keypair().pubkey())}}
    chain.rpc, chain.multiple = rpc, multiple
    chain.decode = lambda row, kind: row
    try:
        with pytest.raises(ValueError, match='publisher'):
            await chain.prepare({'city': chain.pda('s1v1_city')}, {'kind': 'init'})
    finally:
        await chain.close()


def test_batches_create_ata_and_split_by_serialized_packet_size():
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/unused')
    chain.signer = Keypair()
    scope = {name: str(Keypair().pubkey()) for name in ('city', 'hill', 'mint')}
    person, recipient = str(Keypair().pubkey()), str(Keypair().pubkey())
    leaves = [{'claim_set': str(Keypair().pubkey()), 'person': person, 'recipient': recipient,
               'index': 0, 'amount': 1, 'proof': [{'hash': '11'*32, 'sum': 1}]*8,
               'terms': {'cap': 2, 'frozen_at': 1, 'audit_hash': '22'*32}} for _ in range(4)]
    groups = chain.payout_batches(scope, leaves, dung=False)
    assert len(groups) > 1
    assert all(not op.get('lookup_addresses') for op in groups), 'split ordinary proofs before spending lookup rent'
    assert sum(len(op['leaves']) for op in groups) == 4
    for op in groups:
        assert chain.packet_size(scope, op) <= 1232
        ix = chain.instructions(scope, op)
        assert len(ix) == 2 and bytes(ix[0].data) == b'\x01'  # idempotent ATA


def test_paid_bitmap_reconciles_without_receipt_accounts():
    from app.services.stage1_keeper_worker import check_accounting
    from app.services.stage1_keeper_merkle import claim_set
    person = str(Keypair().pubkey())
    context = [str(Keypair().pubkey()) for _ in range(3)] + [1, str(Keypair().pubkey())]
    claims = claim_set(context, {person: 5}, {person: person})
    ledger = dict(paid=5,claimable=0,held=0,pool=0,owner_custody=0,owner_returns=0,earnings=0,deposited=0,admitted_cash_lifetime=5)
    observed = {'slot': 10, 'asset': {'ledger': ledger, 'harvested_units': 0, 'fees_assessed': 0},
                'books': {'book': {'available': 0, 'holds': [0]*5, 'pool': 0, 'harvested_net': 0, 'admitted_cash': 5}},
                'lots': [], 'earnings_balance': 0, 'sets': {'set': {'hill': context[2], 'week': 1,
                'root': claims['root'], 'total': 5, 'leaf_count': 1, 'paid': 5, 'claimed_count': 1, 'bitmap': '01'}},
                'receipts': [], 'recipients': {}}
    job = {'week': 1, 'claims': claims, 'allocation': {'cap': 5}, 'snapshot': {'commitment': '11'*32}, 'state': 'complete', 'operations': [{'kind': 'publish'}]}
    assert check_accounting(observed, [job])['ledger']['paid'] == 5

@pytest.mark.asyncio
async def test_guardian_wait_precedes_signing_and_cash_claims_remain_available():
    from app.services.stage1_keeper_chain import SettlementPaused
    signer = Keypair()
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/unused')
    chain.signer, chain.genesis = signer, 'local'
    async def multiple(addresses, floor=0, **kwargs):
        return 10, {addresses[0]: {'publisher': str(signer.pubkey()), 'settlement_paused': True, 'intake_paused': True}}
    chain.multiple, chain.decode = multiple, lambda row, kind: row
    try:
        with pytest.raises(SettlementPaused):
            await chain.authorize('publish', 0)
        await chain.authorize('cash_claim', 0)
        await chain.authorize('cash_close', 0)
    finally:
        await chain.close()


def test_publisher_cluster_manifest_rejects_reused_key():
    public = str(Keypair().pubkey())
    with pytest.raises(ValueError, match='distinct'):
        KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/unused',
                    publisher_keys={'localnet': public, 'devnet': public, 'mainnet-beta': str(Keypair().pubkey())})


def test_boost_accepts_ride_week_grace_upload_without_adding_to_closing_field():
    from app.services.stage1_keeper_snapshot import build_snapshot, WEEK, DAY
    person = str(Keypair().pubkey())
    start = 1791201600
    inputs = {'launch': start, 'context': ['p','c','h',0,'mint'], 'canon_id': 'canon',
              'opening': {'boundary': start, 'commitment': 'finalized', 'evidence': 'local', 'slot': 1, 'live': True},
              'closing': {'boundary': start+WEEK, 'commitment': 'finalized', 'evidence': 'local', 'slot': 2,
                          'assets': ['mint'], 'board': [], 'legend': None}, 'recipients': {}}
    row = {'receipt': 'one', 'canon_id': 'canon', 'person': person, 'ridden_at': start+WEEK-10,
           'uploaded_at': start+WEEK+10, 'verified_at': start+WEEK+20, 'trusted': True, 'evidence': 'local'}
    result = build_snapshot(inputs, [row])
    assert result['boost_rides'][0]['person'] == person
    assert result['ascents'] == {} and result['field_people'] == []
    row['uploaded_at'] = start+WEEK+DAY
    assert build_snapshot(inputs, [row])['boost_rides'] == []


def test_dung_missing_individual_shares_remain_unminted_without_redistribution():
    from app.services.stage1_keeper_dung import allocate_dung
    people = [str(Keypair().pubkey()) for _ in range(5)]
    snap = {'context':['p','c','h',1,'m'], 'field_people':people, 'board':people[:2],
            'ascents':dict.fromkeys(people,1), 'legend':people[0], 'tss_micros':1_000_000,
            'recipients':dict.fromkeys(people[:4],'registered'),
            'opening':{'dung':{'bonded_at':1,'weights':{people[0]:1,people[4]:1}}}}
    result = allocate_dung(snap)
    full = allocate_dung({**snap, 'recipients':dict.fromkeys(people,'registered')})
    assert result['riders'][people[0]] == full['riders'][people[0]]
    assert result['backers'][people[0]] == full['backers'][people[0]]
    assert people[4] not in result['riders'] and people[4] not in result['backers']
    assert result['unminted'] == full['riders'][people[4]] + full['backers'][people[4]]


def test_registration_after_boost_window_releases_earned_attribution():
    from app.services.stage1_keeper_allocation import allocate
    from tests.services.test_stage1_keeper_allocation import measurement
    snap = measurement()
    snap['context'][3] = 3
    source = {'id':'boost:0','kind':'boost','born':1,'due':1,'last_ride_week':2,
              'buckets':[0,0,0,0,100], 'reserved':{'r0':100}, 'ascents':{'r0':1}}
    result = allocate(snap,[source])
    assert result['payments'] == {'r0':100} and result['reserved']['boost:0'] == {}
    snap['context'][3] = 27
    assert allocate(snap,[source])['pool']['boost:0'] == 100


def dung_snapshot():
    from tests.services.test_stage1_keeper_snapshot import inputs, PEOPLE
    from app.services.stage1_keeper_snapshot import build_snapshot
    data = inputs(1)
    data['kind'] = 'dung'
    data['opening']['dung'] = {'hill':{'bonded':True,'bonded_at':data['launch']+100,
        'founding_cutoff':0,'founding_fresh_slots':0,'quoted_numerators':[1]*32,'quoted_denominators':[1]*32},
        'lots':[], 'rates':{}}
    snap = build_snapshot(data,[])
    snap.pop('rider_tie_ranks')  # These unit cases replace the original empty ride set.
    snap['field_people'] = PEOPLE[:5]
    snap['rides'] = [{'person':PEOPLE[0],'ridden_at':data['launch']+50,'post_bond':True,
                      'tss_micros':1_000_000,'paid_ascent':True}]
    return snap


def test_dung_rechecks_old_admissions_against_actual_bond():
    from app.services.stage1_keeper_dung import dung_plan
    snap = dung_snapshot()
    derived, allocation, _, _ = dung_plan(snap,{'dung_tss_ceiling_micros':2_000_000})
    assert derived['tss_micros'] == 0 and allocation['potential'] == 0
    # Missing historical eligibility after erasure must wait, never overmint.
    del snap['rides'][0]['ridden_at']
    with pytest.raises(ValueError, match='bond eligibility'):
        dung_plan(snap,{'dung_tss_ceiling_micros':2_000_000})


def test_below_field_dung_can_skip_above_publish_ceiling():
    from app.services.stage1_keeper_dung import dung_plan
    snap = dung_snapshot()
    snap['field_people'] = snap['field_people'][:1]
    snap['rides'][0]['ridden_at'] = snap['launch']+200
    _, allocation, _, _ = dung_plan(snap,{'dung_tss_ceiling_micros':1})
    assert allocation['potential'] == 0


def test_dung_freezes_only_registered_role_totals():
    from app.services.stage1_keeper_dung import dung_plan
    snap = dung_snapshot()
    snap['rides'][0]['ridden_at'] = snap['launch']+200
    snap['recipients'] = {}
    _, allocation, roles, inputs = dung_plan(snap, {'dung_tss_ceiling_micros':2_000_000})
    assert allocation['potential'] == allocation['unminted'] == 1_000_000
    assert inputs['payable_role_totals'] == [c['total'] for c in roles] == [0,0]


def test_invalid_canonical_power_is_unavailable_not_an_exception():
    from app.services.stage1_keeper_dung import measured_tss
    result = measured_tss({'_power':{'evidence':{},'paid_spans_ms':[],'reward_ftp_w':200}})
    assert result['tss_unavailable'] == 'invalid_frozen_power_evidence'


def test_archived_bond_time_cannot_override_finalized_admission_witness():
    from app.services.stage1_keeper_dung import dung_plan
    snap = dung_snapshot()
    snap['admission_bond'] = {'bonded':True,'bonded_at':snap['launch']+300}
    with pytest.raises(ValueError, match='bond'):
        dung_plan(snap,{'dung_tss_ceiling_micros':2_000_000})


@pytest.mark.asyncio
async def test_independent_dung_oracle_derives_founding_surplus_and_native_tss():
    from app.services.stage1_keeper_dung import dung_plan
    from app.services.stage1_keeper_worker import independent
    from solders.pubkey import Pubkey
    snap = dung_snapshot()
    snap['context'] = [str(Keypair().pubkey()) for _ in range(3)]+[1,str(Keypair().pubkey())]
    program,city,hill = snap['context'][:3]
    owner = snap['rides'][0]['person']
    mint = str(Keypair().pubkey())
    address = str(Pubkey.find_program_address([b's1v1_lot',bytes(Pubkey.from_string(owner)),(1).to_bytes(8,'little')],Pubkey.from_string(program))[0])
    lot = {'address':address,'city':city,'hill':hill,'owner':owner,'mint':mint,'deposit_id':1,
           'cancelled':False,'exiting':False,'converted':False,'founding':False,'sequence':1,'asset_slot':0,
           'units':2_000_000,'basis_lamports':1_000_000,'lock_weeks':0,'lock_end':0}
    archive = snap['opening']['dung']
    archive['hill'].update(founding_cutoff=1,founding_fresh_slots=1)
    archive['lots'] = [lot]
    archive['rates'][mint] = {'mint':mint,'city':city,'asset':str(Pubkey.find_program_address([b's1v1_asset',bytes(Pubkey.from_string(mint))],Pubkey.from_string(program))[0]),
        'numerator':1,'denominator':1,'slot':snap['opening']['slot'],'boundary':snap['opening']['boundary'],'evidence':'synthetic'}
    snap['rides'][0]['ridden_at'] = snap['launch']+200
    derived,allocation,roles,_ = dung_plan(snap,{'dung_tss_ceiling_micros':2_000_000})
    oracle = await independent({**snap,'kind':'dung'},[])
    assert oracle['allocation']==allocation and oracle['roles']==roles
    assert oracle['measurement']['opening']==derived['opening']['dung']
    assert oracle['measurement']['opening']['weights'][owner]==6_000_000
    assert oracle['measurement']['tss_micros']==1_000_000
