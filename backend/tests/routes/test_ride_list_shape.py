"""Owner ride-list shape uses stored projections, never per-ride streams."""
from uuid import uuid4
from app.routes.rides import _to_ride_record


def test_list_shape_reaches_client_contract():
    record = _to_ride_record({
        'id': str(uuid4()), 'user_id': str(uuid4()),
        '_list_shape': {
            'elevation_profile': [
                {'distance_m': 0, 'elevation_m': 10},
                {'distance_m': 100, 'elevation_m': 20},
            ],
            'counted_spans': [{'start_distance_m': 20, 'end_distance_m': 80}],
        },
    }).model_dump(by_alias=True)
    assert record['elevationProfile'][1] == {'distanceM': 100, 'elevationM': 20}
    assert record['countedSpans'] == [{'startDistanceM': 20, 'endDistanceM': 80}]

from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.ride_list_shape import build_ride_list_shape
from app.services.elevation_correction import encode_correction_profile
from app.repositories.ride import RideRepository


def points(count=101):
    return [{'distance_m': i * 10, 'elevation_m': i, 'timestamp': i} for i in range(count)]


def test_even_distance_profile_prefers_dem_and_falls_back_to_device():
    route = points()
    ride = {'elevation_correction_status': 'corrected',
            'elevation_correction_profile': encode_correction_profile([200] * 100 + [None])}
    shape = build_ride_list_shape(ride, route, [
        {'segment_start_offset_s': 20.5, 'segment_end_offset_s': 80, 'exact_tribute_base_units': '1'},
        {'segment_start_offset_s': 0, 'segment_end_offset_s': 5, 'exact_tribute_base_units': '0'},
    ])
    profile = shape['elevation_profile']
    assert len(profile) == 64
    assert profile[0] == {'distance_m': 0, 'elevation_m': 200}
    assert profile[-1] == {'distance_m': 1000, 'elevation_m': 100}
    assert [p['distance_m'] for p in profile] == pytest.approx([1000 * i / 63 for i in range(64)])
    assert shape['counted_spans'] == [{'start_distance_m': 205, 'end_distance_m': 800}]
    assert route[0]['elevation_m'] == 0


@pytest.mark.parametrize('route', [[], points(1), [{'distance_m': 0, 'elevation_m': None}],
    [{'distance_m': 0, 'elevation_m': 1}, {'distance_m': 0, 'elevation_m': 2}],
    [{'distance_m': 10, 'elevation_m': 1}, {'distance_m': 5, 'elevation_m': 2}]])
def test_unusable_profile_is_absent(route):
    assert build_ride_list_shape({}, route, []) == {}


def test_non_list_records_omit_shape_even_when_gps_exists():
    payload = _to_ride_record({'id': str(uuid4()), 'user_id': str(uuid4()), 'gps_track': points()}).model_dump(by_alias=True)
    assert 'elevationProfile' not in payload
    assert 'countedSpans' not in payload


@pytest.mark.asyncio
async def test_counted_steps_are_batched_and_terminal_only():
    client = MagicMock()
    ordinary = client.table.return_value.select.return_value.in_.return_value.eq.return_value
    ordinary.execute.return_value.data = [
        {'ride_id': 'ordinary', 'state': 'complete', 'exact_cal_base_units': '100', 'steps': [{'exact_tribute_base_units': '1'}]},
        {'ride_id': 'review', 'state': 'review', 'exact_cal_base_units': '100', 'steps': [{}]},
    ]
    client.table.return_value.select.return_value.in_.return_value.execute.return_value.data = [
        {'ride_id': 'released', 'exact_cal_base_units': '100',
         'execution': {'state': 'complete', 'terminal_projected_at': 'now'},
         'snapshot_evidence': {'steps': [{'exact_tribute_base_units': '2'}]}},
        {'ride_id': 'pending', 'exact_cal_base_units': '100',
         'execution': {'state': 'complete', 'terminal_projected_at': None},
         'snapshot_evidence': {'steps': [{}]}},
    ]
    repo = RideRepository(client)
    rows = [{'id': f'ordinary-{i}', 'processing_status': 'completed'} for i in range(100)]
    rows += [{'id': 'released', 'processing_status': 'completed', 'threshold_economy_state': 'counted'},
             {'id': 'held', 'processing_status': 'completed', 'reward_policy': 'threshold_provisional_hold_v1'}]
    result = await repo.list_counted_climb_steps(rows)
    assert result == {'ordinary': [{'exact_tribute_base_units': '1'}], 'released': [{'exact_tribute_base_units': '2'}]}
    assert client.table.call_count == 2
    ordinary_select = client.table.return_value.select.call_args_list[0].args[0]
    assert 'pattern_id' in ordinary_select
    for call in client.table.return_value.select.return_value.in_.call_args_list:
        assert 'held' not in call.args[1]


def test_stored_gps_without_device_distance_still_has_relief():
    route = [{'latitude': 40 + i / 10000, 'longitude': -75, 'distance_m': 0,
              'elevation_m': 20 + i, 'timestamp': i} for i in range(100)]
    shape = build_ride_list_shape({}, route, [
        {'segment_start_offset_s': 10, 'segment_end_offset_s': 20, 'exact_tribute_base_units': '1'},
    ])
    assert len(shape['elevation_profile']) == 64
    assert shape['elevation_profile'][-1]['distance_m'] > 1000
    assert len(shape['counted_spans']) == 1
    assert route[-1]['distance_m'] == 0


def test_packed_gps_time_origin_aligns_frozen_offsets():
    route = points(101)
    ride = {'started_at': '2026-09-03T12:00:00+00:00',
            'gps_track': {'polyline': 'stored', 'elevations': [0] * 101,
                          'timestamps': [0] * 101, 'time_origin': '2026-09-03T12:00:10+00:00'}}
    step = {'segment_start_offset_s': 20, 'segment_end_offset_s': 30, 'exact_tribute_base_units': '1'}
    assert build_ride_list_shape(ride, route, [step])['counted_spans'] == [
        {'start_distance_m': 100, 'end_distance_m': 200}]
    del ride['gps_track']['time_origin']
    assert build_ride_list_shape(ride, route, [step])['counted_spans'] == []


@pytest.mark.asyncio
async def test_gps_persistence_retains_clock_origin_for_new_rides():
    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]
    repo = RideRepository(client)
    await repo.store_gps_points(uuid4(), [
        {'timestamp': '2026-09-03T12:00:10+00:00', 'latitude': 40, 'longitude': -75, 'elevation': 10, 'distance': 0},
        {'timestamp': '2026-09-03T12:00:20+00:00', 'latitude': 40.001, 'longitude': -75, 'elevation': 20, 'distance': 100},
    ])
    stored = client.table.return_value.update.call_args.args[0]['gps_track']
    assert stored['time_origin'] == '2026-09-03T12:00:10+00:00'

@pytest.mark.parametrize('timestamp', [None, '', 'invalid', True])
@pytest.mark.parametrize('wrapped', [False, True])
def test_legacy_missing_time_never_becomes_a_counted_span(timestamp, wrapped):
    from app.utils.polyline import decode_gps_track
    raw = [
        {'latitude': 40 + i / 10000, 'longitude': -75,
         'distance_m': i * 10, 'elevation_m': 10 + i, 'timestamp': timestamp}
        for i in range(4)
    ]
    track = {'points': raw} if wrapped else raw
    shape = build_ride_list_shape({'gps_track': track}, decode_gps_track(track), [
        {'segment_start_offset_s': 1, 'segment_end_offset_s': 2, 'exact_tribute_base_units': '1'},
    ])
    assert len(shape['elevation_profile']) == 4
    assert shape['counted_spans'] == []


def test_legacy_explicit_time_keeps_genuine_counted_span():
    from app.utils.polyline import decode_gps_track
    raw = [
        {'latitude': 40 + i / 10000, 'longitude': -75,
         'distance_m': i * 10, 'elevation_m': 10 + i, 't': i}
        for i in range(4)
    ]
    shape = build_ride_list_shape({'gps_track': raw}, decode_gps_track(raw), [
        {'segment_start_offset_s': 1, 'segment_end_offset_s': 2, 'exact_tribute_base_units': '1'},
    ])
    assert shape['counted_spans'] == [{'start_distance_m': 10, 'end_distance_m': 20}]


@pytest.mark.parametrize('pattern_id', ['frozen-climb-a', None, ''])
@pytest.mark.parametrize('released', [False, True])
@pytest.mark.asyncio
async def test_counted_span_matches_frozen_climb_identity(pattern_id, released):
    from app.dependencies import AuthenticatedUser
    from app.routes.rides import list_rides, _fetch_ride_climb_earnings

    ride_id, user_id = str(uuid4()), str(uuid4())
    step = {'segment_start_offset_s': 20, 'segment_end_offset_s': 80,
            'exact_tribute_base_units': '1', 'vault_signature': 'fixture-vault'}
    if pattern_id is not None:
        step['pattern_id'] = pattern_id
    ride = {'id': ride_id, 'user_id': user_id, 'processing_status': 'completed',
            'reward_ftp_source': 'measured', 'visibility': 'private',
            'gps_track': [{**p, 'latitude': 40 + i / 10000, 'longitude': -75}
                          for i, p in enumerate(points())], 'patterns': [{'id': 'unfrozen-detected-id'}]}
    repo = MagicMock()
    repo.list_rides_for_user = AsyncMock(return_value=[ride])
    repo.list_ride_media_for_rides = AsyncMock(return_value={})
    repo.list_counted_climb_steps = AsyncMock(return_value={ride_id: [step]})
    records = await list_rides(
        current_user=AuthenticatedUser(wallet='fixture-wallet', user_id=user_id, device_id='fixture-device'),
        ride_repo=repo, limit=50, offset=0,
    )

    rows = {
        'ride_economic_completion_steps': [step],
        'vault_completions': [{'vault_signature': 'fixture-vault', 'activity_id': ride_id,
            'chain_confirmation_status': 'confirmed', 'completion_receipt_pda': 'fixture-receipt',
            'completion_evidence_hash': '\\x' + 'ab' * 32, 'completion_evidence_version': 2,
            'chain_confirmed_at': '2026-09-06T12:00:00+00:00'}],
    }
    def table(name):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.order.return_value = query
        query.execute.return_value.data = rows.get(name, [])
        return query
    repo.client.table.side_effect = table
    climbs = _fetch_ride_climb_earnings(
        repo, ride_id, ride,
        release_resolution=('terminal', {}, [step]) if released else None,
    )
    assert len(climbs) == 1
    span = records[0].model_dump(by_alias=True)['countedSpans'][0]
    assert span['startDistanceM'] == 200
    assert span['endDistanceM'] == 800
    if pattern_id:
        assert span['patternId'] == climbs[0].pattern_id == pattern_id
        assert records[0].model_dump()['counted_spans'][0]['pattern_id'] == pattern_id
    else:
        assert climbs[0].pattern_id is None
        assert 'patternId' not in span
        assert 'pattern_id' not in records[0].model_dump()['counted_spans'][0]
    repo.get_activity_stream.assert_not_called()


def test_counted_span_openapi_identity_is_optional():
    from fastapi import FastAPI
    from app.routes.rides import router
    app = FastAPI()
    app.include_router(router, prefix='/rides')
    schema = app.openapi()['components']['schemas']['RideCountedSpan']
    assert {'type': 'string'} in schema['properties']['patternId']['anyOf']
    assert 'patternId' not in schema['required']
