"""Independent boundary replay, using synthetic finalized sources, never rider proof."""
import copy
import hashlib
import json

import pytest
from pathlib import Path
from solders.pubkey import Pubkey

from app.services.stage1_boundary import materialize_boundary, verify_boundary, MissingBoundary

LAUNCH = 1791201600
WEEK = 604800
def key(n):
    return str(Pubkey(bytes([n]) * 32))


@pytest.mark.parametrize('vector',json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text()),ids=lambda v:v['name'])
def test_shared_typescript_python_boundary_vectors(vector):
    value=materialize_boundary(vector['checkpoint'],vector['coverage'],vector['transactions'],vector['hill'],vector['boundary'])
    assert value['digest']==vector['digest']
    assert verify_boundary(value,require_raw=True)==value

def sources():
    fields = [
        (key(1), 'Stage1CityConfig', dict(seasonAnchor=str(LAUNCH), lineLamports='10000000000', liveLamports='5000000000')),
        (key(2), 'Stage1HillBond', dict(city=key(1), climb=key(3), canonId='01'*16, bonded=True, bondedAt=str(LAUNCH-100), foundingCutoff='0', foundingFreshSlots=0, quotedNumerators=['0']*32, quotedDenominators=['0']*32)),
        (key(3), 'Climb', dict(canonId='01'*16, canonVersion=1, registeredAt=str(LAUNCH-200), vault=key(4))),
        (key(4), 'Vault', dict(id='1', climb=key(3))),
        (key(5), 'VaultLeaderboard', dict(vaultId='1', entries=[dict(user=key(8), timeS=60, recordedAt=str(LAUNCH-10))])),
        (key(6), 'Stage1AssetConfig', dict(city=key(1), mint=key(7), enabled=True, adapter=1, slot=0, admittedNumerator='1', admittedDenominator='1', admittedEpoch='0', lastFreshUntil=str(LAUNCH+3*WEEK))),
    ]
    rows = [dict(address=a, type=t, fields=f) for a,t,f in fields]
    checkpoint = dict(genesis='local-test', program=key(9), slot=100, block_time=LAUNCH-1, epoch=0, accounts=rows)
    coverage = dict(genesis='local-test', program=key(9), from_slot=90, from_time=LAUNCH-2, through_slot=200, through_time=LAUNCH+WEEK+1, cursor='head')
    return checkpoint, coverage

def test_boundary_digest_replays_independently_and_excludes_exact_timestamp_writes():
    checkpoint, coverage = sources()
    value = materialize_boundary(checkpoint, coverage, [], key(2), LAUNCH)
    # Independent serializer/hash, not the production digest helper.
    expected = hashlib.sha256(json.dumps(value['records'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert value['records_digest'] == expected
    assert verify_boundary(value) == value
    assert value['opening']['live'] is False
    same_instant = dict(signature='new', slot=150, block_time=LAUNCH, writes=[key(5)], events=[], instructions=[])
    assert materialize_boundary(checkpoint, coverage, [same_instant], key(2), LAUNCH)['records'] == value['records']

def test_missing_history_and_changed_or_created_accounts_hold_instead_of_guessing():
    checkpoint, coverage = sources()
    unrelated=dict(signature='other-hill',slot=120,block_time=LAUNCH-1,writes=[key(20)],events=[],instructions=[])
    assert materialize_boundary(checkpoint,coverage,[unrelated],key(2),LAUNCH)['records']['record_version']==1
    for writes in ([key(2)], [key(5)]):
        tx = dict(signature='gap', slot=120, block_time=LAUNCH-1, writes=writes, events=[], instructions=[])
        with pytest.raises(MissingBoundary):
            materialize_boundary(checkpoint, coverage, [tx], key(2), LAUNCH)
    with pytest.raises(MissingBoundary):
        materialize_boundary(checkpoint, {**coverage, 'through_time':LAUNCH-1}, [], key(2), LAUNCH)


def test_same_slot_block_position_orders_records_and_missing_position_holds():
    checkpoint,coverage=sources()
    txs=[dict(signature=str(n),slot=120,block_time=LAUNCH-1,block_index=n,writes=[key(5)],
        instructions=[dict(name='recordClimbCompletionV2')],events=[dict(name='ClimbCompletedV2',
        fields=dict(vaultId='1',rider=key(n+10),timeS=50,completedAt=str(LAUNCH-1)))]) for n in (1,0)]
    result=materialize_boundary(checkpoint,coverage,txs,key(2),LAUNCH)
    assert [e['person'] for e in result['records']['board']][:2]==[key(10),key(11)]
    del txs[0]['block_index']
    with pytest.raises(MissingBoundary,match='order'):
        materialize_boundary(checkpoint,coverage,txs,key(2),LAUNCH)

def test_later_checkpoint_recovers_only_with_no_post_boundary_mutation():
    checkpoint, coverage = sources()
    checkpoint.update(slot=180, block_time=LAUNCH+1)
    assert materialize_boundary(checkpoint, coverage, [], key(2), LAUNCH)['records']['record_version'] == 1
    with pytest.raises(MissingBoundary):
        materialize_boundary(checkpoint, coverage, [dict(signature='x',slot=160,block_time=LAUNCH,writes=[key(2)],events=[],instructions=[])],key(2),LAUNCH)

def test_witness_tampering_and_network_changes_are_refused():
    checkpoint, coverage = sources()
    value = materialize_boundary(checkpoint, coverage, [], key(2), LAUNCH)
    altered = copy.deepcopy(value)
    altered['records']['board'][0]['time_s'] = 1
    with pytest.raises(ValueError):
        verify_boundary(altered)
    with pytest.raises(MissingBoundary):
        materialize_boundary(checkpoint, {**coverage, 'genesis':'other'}, [], key(2), LAUNCH)

def test_raw_account_bytes_do_not_authorize_forged_erasure_metadata():
    from pathlib import Path
    vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[2]
    next(a for a in vector['checkpoint']['accounts'] if a['type']=='Stage1PledgeLot')['lot_owner_rank']=12345
    value=materialize_boundary(vector['checkpoint'],vector['coverage'],[],vector['hill'],vector['boundary'])
    with pytest.raises(ValueError,match='unverified source redaction'):
        verify_boundary(value,require_raw=True)


def test_erased_transaction_is_a_gap_not_evidence_of_no_writes():
    checkpoint, coverage = sources()
    erased = dict(signature='erased',slot=120,block_time=LAUNCH-1,writes=[],instructions=[],events=[],erased=True)
    with pytest.raises(MissingBoundary, match='erased'):
        materialize_boundary(checkpoint,coverage,[erased],key(2),LAUNCH)


def test_dormant_event_recovery_matches_the_final_account_projection():
    checkpoint, coverage = sources()
    epoch=(LAUNCH-1704110400)//WEEK
    checkpoint['accounts'] += [dict(address=key(11),type='ProgramConfig',fields=dict(settlementClockVersion=2,settlementClockV2StartsAt='1704110400')),
        dict(address=key(12),type='LocalLegend',fields=dict(vaultId='1',holder=key(8),isActive=True,isBootstrap=True,termStartEpoch=str(epoch-2),termEndEpoch=str(epoch)))]
    tx=dict(signature='dormant',slot=120,block_time=LAUNCH-1,writes=[key(12)],instructions=[dict(name='deactivateLocalLegend')],events=[dict(name='LocalLegendDormant',fields=dict(vaultId='1',termStartEpoch=str(epoch),termEndEpoch=str(epoch+2)))])
    event_value=materialize_boundary(checkpoint,coverage,[tx],key(2),LAUNCH)
    after=copy.deepcopy(checkpoint);after.update(slot=130)
    after['accounts'][-1]['fields'].update(isActive=False,isBootstrap=False,termStartEpoch=str(epoch),termEndEpoch=str(epoch+2))
    account_value=materialize_boundary(after,coverage,[],key(2),LAUNCH)
    assert event_value['records_digest']==account_value['records_digest']


def test_partial_event_logs_never_certify_an_unreplayed_record_mutation():
    checkpoint,coverage=sources()
    event=dict(name='ClimbCompletedV2',fields=dict(vaultId='1',rider=key(8),timeS=40,completedAt=str(LAUNCH-1)))
    for instructions,events in [
        ([dict(name='recordClimbCompletionV2')],[dict(name='BeetleScoreIncremented',fields={})]),
        ([dict(name='recordClimbCompletionV2')]*2,[event]),
    ]:
        tx=dict(signature='truncated',slot=120,block_time=LAUNCH-1,writes=[key(5)],instructions=instructions,events=events)
        with pytest.raises(MissingBoundary,match='missing_record_events'):
            materialize_boundary(checkpoint,coverage,[tx],key(2),LAUNCH)


def test_absent_opening_uses_proven_later_admission_without_inventing_a_bond():
    checkpoint, coverage=sources()
    admission=copy.deepcopy(checkpoint);admission.update(slot=180,block_time=LAUNCH+10)
    admission['accounts'][1]['fields'].update(admittedWeek='0',bondedAt=str(LAUNCH+5))
    checkpoint['accounts']=[a for a in checkpoint['accounts'] if a['type']!='Stage1HillBond']
    result=materialize_boundary(checkpoint,coverage,[],key(2),LAUNCH,admission=admission)
    assert result['opening']['absent'] and result['opening']['backing']==0
    assert result['opening']['live'] is False and result['opening']['dung']['lots']==[]


def test_excluded_prebond_lot_does_not_require_a_fresh_opening_rate():
    checkpoint,coverage=sources()
    h=checkpoint['accounts'][1]['fields'];h.update(foundingCutoff='1',foundingFreshSlots=0)
    asset=checkpoint['accounts'][-1]['fields'];asset['lastFreshUntil']=str(LAUNCH-1)
    address=str(Pubkey.find_program_address([b's1v1_lot',bytes(Pubkey.from_string(key(8))),(1).to_bytes(8,'little')],Pubkey.from_string(key(9)))[0])
    checkpoint['accounts'].append(dict(address=address,type='Stage1PledgeLot',fields=dict(city=key(1),hill=key(2),owner=key(8),mint=key(7),depositId='1',units='100',basisLamports='100',assetSlot=0,sequence='1',converted=False,founding=False,cancelled=False,exiting=False,lockWeeks=0,lockEnd='0')))
    result=materialize_boundary(checkpoint,coverage,[],key(2),LAUNCH)
    assert result['opening'] is not None and result['opening']['backing']==0
