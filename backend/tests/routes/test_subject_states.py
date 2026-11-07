from uuid import uuid4
import pytest
from app.routes.rides import _build_ride_status_response, _to_ride_record, _serialize_ride_record


def test_matching_finality_is_separate_from_saved_and_held_cal():
    ride = dict(id=str(uuid4()), user_id=str(uuid4()), processing_status='enriched', phase2_completed_at='2026-09-08T20:00:00Z', threshold_economy_state='held')
    result = _build_ride_status_response(ride['id'], ride)
    expected = {'storage': {'state': 'saved', 'reason': 'ride_stored'}, 'matching': {'state': 'finalized', 'reason': 'phase2_completed'}}
    assert result['subject_states'] == expected
    record = _to_ride_record(ride)
    assert record.model_dump(by_alias=True)['subjectStates'] == expected


@pytest.mark.parametrize('facts,state,reason', [
    ({'finalized_at':'2026-09-08T20:00:00Z','cal_earned':12},'finalized','settlement_finalized'),
    ({'reward_policy':'manual_review','review_reason':'effort_source_route_estimate_only'},'needs_review','effort_source_route_estimate_only'),
    ({'reward_policy':'not_counted'},'not_counted','not_counted'),
    ({'reward_policy':'not_counted','covered_effort_seconds':3600,'paid_effort_seconds':0},'not_counted',None),
    ({'threshold_economy_state':'held'},None,None),
    ({'ride_attestation_pda':'pda'},None,None),
])
def test_cal_state_requires_its_own_fact_and_is_private(facts,state,reason):
    ride = dict(id=str(uuid4()),user_id=str(uuid4()),processing_status='completed',**facts)
    result = _build_ride_status_response(ride['id'],ride)
    if state:
        assert result['subject_states']['cal'] == dict(state=state,reason=reason)
    else:
        assert 'cal' not in result['subject_states']
    assert 'position' not in result['subject_states']
    assert 'collection' not in result['subject_states']
    assert 'cal' not in _build_ride_status_response(ride['id'],ride,include_economy=False)['subject_states']
    assert 'cal' not in _serialize_ride_record(_to_ride_record(ride),is_owner=False)['subjectStates']


def test_paid_effort_projections_follow_owner_only_economics():
    ride=dict(id=str(uuid4()),user_id=str(uuid4()),processing_status='completed',effort_seconds=3600,covered_effort_seconds=1800,paid_effort_seconds=1800)
    owner=_build_ride_status_response(ride['id'],ride)
    public=_build_ride_status_response(ride['id'],ride,include_economy=False)
    for key in ('effort_seconds','covered_effort_seconds','paid_effort_seconds'):
        assert owner[key]==ride[key]
        assert key not in public
    owner_record=_serialize_ride_record(_to_ride_record(ride),is_owner=True)
    public_record=_serialize_ride_record(_to_ride_record(ride),is_owner=False)
    for key in ('effortSeconds','coveredEffortSeconds','paidEffortSeconds'):
        assert owner_record[key] is not None
        assert key not in public_record


def test_empty_partly_counted_slot_preserves_finalized_reason():
    ride = dict(
        id=str(uuid4()),
        finalized_at="2026-09-08T20:00:00Z",
        cal_earned=12,
        reward_policy="rewardable",
        covered_effort_seconds=600,
        paid_effort_seconds=3000,
    )
    assert _build_ride_status_response(ride["id"], ride)["subject_states"]["cal"] == {
        "state": "finalized",
        "reason": "settlement_finalized",
    }
