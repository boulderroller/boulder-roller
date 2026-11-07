from unittest.mock import AsyncMock
import pytest
from fastapi import Response
from test_public_preview_contracts import FakePreviewRepo
from app.routes import public_previews


def shaped_repo(mode='show_all'):
    repo = FakePreviewRepo()
    repo._client = repo.client
    repo._run = AsyncMock(side_effect=lambda query: query())
    ride = repo.rides[repo.public_ride_id]
    ride.update(map_visibility=mode, map_hide_start_m=200, map_hide_end_m=200,
        gps_track=[{'latitude': 40 + i * .001, 'longitude': -75,
                    'distance_m': i * 100, 'elevation_m': i * 10,
                    'timestamp': i * 30} for i in range(11)])
    repo.list_counted_climb_steps = AsyncMock(return_value={repo.public_ride_id: [
        {'segment_start_offset_s': 90, 'segment_end_offset_s': 210,
         'exact_tribute_base_units': '1', 'pattern_id': 'visible-climb'},
        {'segment_start_offset_s': 0, 'segment_end_offset_s': 90,
         'exact_tribute_base_units': '1', 'pattern_id': 'hidden-climb'}]})
    return repo


@pytest.mark.asyncio
async def test_public_shape_contract_trims_endpoints_and_hidden_pattern():
    repo = shaped_repo('hide_start_end')
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    shape = result['ride']
    assert shape['elevation_profile'][0] == {'distance_m': 200, 'elevation_m': 20}
    assert shape['elevation_profile'][-1] == {'distance_m': 800, 'elevation_m': 80}
    assert shape['counted_spans'] == [{'start_distance_m': 300, 'end_distance_m': 700, 'pattern_id': 'visible-climb'}]
    assert shape['distanceM'] == 18000


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['hide_entire', None])
async def test_hidden_shape_fields_are_absent(mode):
    repo = shaped_repo(mode)
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    assert 'elevation_profile' not in result['ride']
    assert 'counted_spans' not in result['ride']


@pytest.mark.asyncio
async def test_public_shape_reuses_owner_binning():
    from app.services.ride_list_shape import build_ride_list_shape
    from app.routes.rides import _decode_ride_gps_points
    repo = shaped_repo()
    ride = repo.rides[repo.public_ride_id]
    expected = build_ride_list_shape(ride, _decode_ride_gps_points(ride), repo.list_counted_climb_steps.return_value[repo.public_ride_id])
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    for key, value in expected.items():
        assert result['ride'][key] == value


@pytest.mark.asyncio
async def test_zone_gap_is_not_interpolated_or_counted():
    repo = shaped_repo()
    repo.client.tables['privacy_zones'] = [{'user_id': repo.public_user_id,
        'latitude': 40.005, 'longitude': -75, 'radius_m': 200}]
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    profile = result['ride']['elevation_profile']
    assert [p['distance_m'] for p in profile] == [0, 100, 200, 300, 700, 800, 900, 1000]
    assert profile[4]['break_before'] is True
    assert result['ride']['counted_spans'] == [{'start_distance_m': 0, 'end_distance_m': 300, 'pattern_id': 'hidden-climb'}]


@pytest.mark.asyncio
async def test_corrected_elevation_keeps_original_index_after_trim():
    from app.services.elevation_correction import encode_correction_profile
    repo = shaped_repo('hide_start_end')
    repo.rides[repo.public_ride_id].update(elevation_correction_status='corrected',
        elevation_correction_profile=encode_correction_profile([100 + i for i in range(11)]))
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    assert result['ride']['elevation_profile'][0]['elevation_m'] == 102
    assert result['ride']['elevation_profile'][-1]['elevation_m'] == 108


@pytest.mark.asyncio
async def test_fresh_released_authority_is_passed_to_shared_reader():
    repo = shaped_repo()
    repo.rides[repo.public_ride_id].update(reward_policy='threshold_provisional_hold_v1', threshold_economy_state='held')
    repo.get_reward_threshold_ride_projections = AsyncMock(return_value={repo.public_ride_id: {'state': 'counted'}})
    await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    assert repo.list_counted_climb_steps.call_args.args[0][0]['threshold_economy_state'] == 'counted'


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['elevation_m', 'timestamp'])
async def test_missing_shape_or_timing_is_not_fabricated(missing):
    repo = shaped_repo()
    for point in repo.rides[repo.public_ride_id]['gps_track']:
        point.pop(missing)
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    if missing == 'elevation_m':
        assert 'elevation_profile' not in result['ride']
        assert 'counted_spans' not in result['ride']
    else:
        assert result['ride'].get('counted_spans', []) == []


@pytest.mark.asyncio
async def test_undrawable_geometry_has_no_shape_and_no_pattern_without_authority():
    repo = shaped_repo()
    for point in repo.rides[repo.public_ride_id]['gps_track']:
        point['timestamp'] = 0
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    assert 'elevation_profile' not in result['ride']
    assert 'counted_spans' not in result['ride']
    repo = shaped_repo()
    for step in repo.list_counted_climb_steps.return_value[repo.public_ride_id]:
        step.pop('pattern_id')
    result = await public_previews.get_ride_public_preview(repo.public_ride_id, Response(), repo)
    assert result['ride']['counted_spans'] == []


def test_distance_plateau_cannot_reveal_pattern_across_hidden_time():
    from app.services.public_ride_shape import build_public_ride_shape
    raw = [{'distance_m': d, 'elevation_m': i, 'timestamp': i*30,
            'latitude': 40+i*.0001, 'longitude': -75}
           for i,d in enumerate([0,10,10,10,20,30])]
    projected = [dict(p) for p in raw]
    projected[2].update(latitude=None, longitude=None, redacted=True)
    shape = build_public_ride_shape({'gps_track':raw},raw,projected,[{
        'segment_start_offset_s':30,'segment_end_offset_s':120,
        'pattern_id':'crosses-hidden-time','exact_tribute_base_units':'1'}],{'segments':[[{},{}]]})
    assert shape['counted_spans'] == []
