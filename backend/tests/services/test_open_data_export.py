"""Offline release integrity and closed geographic projection tests."""
import hashlib
import json
import pytest
from copy import deepcopy
from pathlib import Path
from scripts.export_open_data import build_release, project_provenance, profile_bytes, ExportError
from app.services.canon_commitment import canonical_profile_hash_hex
from app.services.geographic_data import geographic_data_for_row, _index


SUCCESSORS = Path(__file__).resolve().parents[3] / 'history/codex-reports-2026-10-20/gate-rule/SUCCESSORS.json'


@pytest.mark.parametrize('successor', json.loads(SUCCESSORS.read_text()),
                         ids=lambda s: s['publish_payload']['climb']['route_name'])
def test_all_16_successor_provenance_projects_without_private_evidence(successor):
    source = successor['publish_payload']['climb']['provenance']
    original = deepcopy(source)
    public = project_provenance(source)
    assert source == original
    if 'finish_gate_rule' in source:
        rule = public['finish_gate_rule']
        for field in ('model', 'setback_from_junction_m', 'stop_line_clearance_m',
                      'controls', 'junction', 'mapped_stop_positions_m'):
            assert rule[field] == source['finish_gate_rule'][field]
        assert rule['founder_approval']['on'] == '2026-10-20'
        assert rule['founder_approval']['approved_position'] == source['finish_gate_rule']['founder_approval']['approved_position']
        assert 'quote' not in rule['founder_approval']
        for private in ('stop_evidence_amendment', 'observed_stop_along_m', 'observed_stop_clearance_m'):
            assert private not in rule
    if 'superseded_capture_tolerance_revision' in source:
        assert public['superseded_capture_tolerance_revision']['revision']['revised_geometry_policy']['gate_end_half_extent_m'] == 35
        assert public['capture_tolerance_revision']['gate_start_half_extent_m'] == 30
        assert 'evidence' not in public['capture_tolerance_revision']
        assert 're_evidence' not in public['capture_tolerance_revision']
    if successor['publish_payload']['climb']['route_name'] == 'Lafayette Road':
        assert public['ratified_boundary']['finish_decision']['decision'] == 'extend_crest'
        assert 'evidence' not in public['ratified_boundary']


@pytest.mark.parametrize('addition', [
    {'founder_approval': {'rider_id': 'PRIVATE'}},
    {'controls': [{'tags': {'rider_id': 'PRIVATE'}}]},
    {'mapped_stop_positions_m': {'rider_id': 1}},
    {'mapped_stop_positions_m': {'node/123': {'ride_id': 'PRIVATE'}}},
    {'mapped_stop_positions_m': {'node/123': 'PRIVATE'}},
])
def test_successor_projection_stays_closed(addition):
    with pytest.raises(ExportError, match='Unclassified'):
        project_provenance({'finish_gate_rule': addition})


def test_successor_private_blocks_and_quotes_are_removed_even_with_new_nested_keys():
    assert project_provenance({'finish_gate_rule': {
        'stop_evidence_amendment': {'new_private_key': 'PRIVATE'},
        'founder_approval': {'quote': 'PRIVATE'},
    }}) == {'finish_gate_rule': {'founder_approval': {}}}


def successor_release_rows():
    """Real reviewed geometry plus the committed predecessor source index."""
    from uuid import UUID, uuid5
    from shapely.geometry import mapping, shape
    from shapely import from_geojson, wkt
    from scripts.export_open_data import FIELDS, GEOMETRIES
    rows, cells = [], []
    for successor in json.loads(SUCCESSORS.read_text()):
        old = deepcopy(_index()[successor['supersedes_climb_id']][-1]['exported'])
        old = {k: old[k] for k in FIELDS + list(GEOMETRIES)}
        old['status'] = 'retired'
        old['provenance']['launch_ratification']['candidate_manifest_sha256'] = 'da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb'
        for geometry in GEOMETRIES:
            # GEOS parsing, as the canon repository does: shapely 2.0.4's Python
            # multi-geometry constructors fail under numpy 2.4 (CI and the API image).
            old[geometry + '_ewkb'] = from_geojson(json.dumps(old[geometry])).wkb_hex
        public_old = _index()[old['id']][-1]['exported']
        cells.extend({'canon_climb_id': old['id'], **cell} for cell in public_old['h3_cells'])
        climb = successor['publish_payload']['climb']
        new = {k: deepcopy(climb.get(k, old[k])) for k in FIELDS}
        new.update(id=str(uuid5(UUID(old['id']), 'publication-fix-test')), canon_id=old['canon_id'],
                   version=2, status='ratified', supersedes_climb_id=old['id'],
                   record_continuity_policy='new_record_board', retired_at=None,
                   ratified_at='2026-10-21T00:00:00Z')
        for geometry, key in zip(GEOMETRIES, ('centerline_wkt','corridor_wkt','gate_start_wkt','gate_end_wkt')):
            value = wkt.loads(climb[key]);new[geometry] = mapping(value);new[geometry + '_ewkb'] = value.wkb_hex
        cells.extend({'canon_climb_id': new['id'], **cell} for cell in successor['publish_payload']['corridor_cells'])
        rows.extend([old, new])
    return rows, cells


def test_full_open_data_release_inherits_all_16_successor_sources(tmp_path):
    rows, cells = successor_release_rows()
    original = deepcopy(rows)
    destination = build_release(rows, cells, tmp_path, published_at='2026-10-21T00:00:00Z')
    exported = [json.loads(line) for line in (destination/'climbs.jsonl').read_text().splitlines()]
    assert len(exported) == 32 and rows == original
    by_id = {r['registry_id']: r for r in exported}
    for row in exported:
        assert row['provenance']['region'] == 'philadelphia'
        assert row['notice_ids'] == ['osm', 'usgs_3dep']
        if row['canon_version'] == 2:
            previous = by_id[row['supersedes_climb_id']]
            decision = row['provenance']['launch_ratification']['decision_id']
            assert decision != previous['provenance']['launch_ratification']['decision_id']
            if row['route_name'] == 'Lafayette Road':
                assert decision == 'lafayette-lump-crest'
            else:
                assert decision == ('workout-parse/resources/philly_finish_gate_decisions_v1.json'
                                    '#registry_id=' + row['supersedes_climb_id'])
            assert row['source_ids'] == previous['source_ids']


def test_geographic_credits_survive_retirement_and_follow_successor_lineage():
    rows, _ = successor_release_rows()
    for old, new in zip(rows[::2], rows[1::2]):
        old_credit = geographic_data_for_row(old)
        new_credit = geographic_data_for_row(new)
        assert old_credit and new_credit, old['display_name']
        assert old_credit['sources'] == new_credit['sources']
        assert new_credit['canon_version'] == 2
        assert 'geographic_revision_id' not in new_credit
        assert 'release_id' not in new_credit
        assert 'source_offer' not in new_credit
        changed = deepcopy(new);changed['dem_source'] = 'UNREVIEWED SOURCE'
        assert geographic_data_for_row(changed) is None


def test_approver_identity_is_private_but_decision_date_remains_public():
    public = project_provenance({'finish_gate_rule': {'founder_approval': {
        'by': 'PRIVATE APPROVER', 'quote': 'PRIVATE QUOTE', 'on': '2026-10-20'}}})
    assert public == {'finish_gate_rule': {'founder_approval': {'on': '2026-10-20'}}}


def test_existing_profile_vector_is_exact():
    points = [{'dist_m': 0.0, 'elev_m': 100.0}, {'dist_m': 12.345, 'elev_m': 101.234}]
    assert profile_bytes(points) == b'boulderroller-canon-profile-v10.00:100.00;12.35:101.23;'
    assert canonical_profile_hash_hex(points) == '8b0b5e33a5d495b913a979b2c33a948fbaca731fe067bb219e855facf5662600'


@pytest.mark.parametrize('key', ['rider_id', 'ride', 'economic_account', 'access_token'])
def test_provenance_is_closed_at_every_depth(key):
    with pytest.raises(ExportError, match='Unclassified'):
        project_provenance({key: 'PRIVATE'})
    with pytest.raises(ExportError, match='Unclassified'):
        project_provenance({'corridor': {key: 'PRIVATE'}})


def test_private_review_evidence_is_not_exported():
    assert project_provenance({'ratified_boundary': {'evidence': {'approved_by': 'PRIVATE'}}}) == {'ratified_boundary': {}}


def test_release_is_reproducible_and_append_only(tmp_path):
    # Empty offline input tests packaging, never a production release.
    first = build_release([], [], tmp_path / 'a', published_at='2026-09-08T00:00:00Z')
    second = build_release([], [], tmp_path / 'b', published_at='2026-09-08T00:00:00Z')
    assert first.name == second.name
    assert (first / 'release.zip').read_bytes() == (second / 'release.zip').read_bytes()
    manifest = json.loads((first / 'manifest.json').read_bytes())
    for name, record in manifest['files'].items():
        data = (first / name).read_bytes()
        assert record == {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    with pytest.raises(FileExistsError):
        build_release([], [], tmp_path / 'a', published_at='2026-09-08T00:00:00Z')


def sample_row():
    from scripts.export_open_data import FIELDS, GEOMETRIES
    from shapely.geometry import mapping
    from shapely import wkt
    row={k:None for k in FIELDS}
    points=[{'dist_m':0,'elev_m':100.001},{'dist_m':100,'elev_m':110}]
    row.update(id='12345678-1234-5678-90ab-cdef12345678',canon_id='12345678-1234-5678-90ab-cdef12345678',version=1,status='ratified',ratified_at='2026-09-08T00:00:00Z',canonical_profile=points,dem_source='USGS 3DEP 10m local profile export',provenance={'region':'offline-fixture','canonical_profile_hash':{'algorithm':'blake3_canonical_profile_v1','value':canonical_profile_hash_hex(points)},'launch_ratification':{'review_labels_sha256':'PRIVATE'}},osm_way_refs=[1],low_confidence_flags=[])
    for key in GEOMETRIES:
        geom=wkt.loads('MULTIPOLYGON (((0 0, 0 1, 1 1, 0 0)))') if key=='corridor_geom' else wkt.loads('LINESTRING (0 0, 1 1)')
        row[key]=mapping(geom);row[key+'_ewkb']=geom.wkb_hex
    cells=[{'canon_climb_id':row['id'],'h3_resolution':10,'tile_id':'8a2a1342b5a7fff','coverage_role':'corridor'}]
    return row,cells


def test_complete_revision_preserves_subcentimetre_samples_and_lossless_geometry(tmp_path):
    row,cells=sample_row()
    first=build_release([row],cells,tmp_path/'first',published_at='2026-09-08T00:00:00Z')
    repeat=build_release([row],list(reversed(cells)),tmp_path/'repeat',published_at='2026-09-08T00:00:00Z')
    assert (first/'release.zip').read_bytes()==(repeat/'release.zip').read_bytes()
    climb=json.loads((first/'climbs.jsonl').read_text())
    revision=climb['geographic_revision_id']
    assert 'PRIVATE' not in (first/'climbs.jsonl').read_text()
    assert (first/f'canonical-bytes/{revision}/centerline_geom.ewkb').read_bytes()==bytes.fromhex(row['centerline_geom_ewkb'])
    assert json.loads((first/'profiles.jsonl').read_text())['samples'][0]['elev_m']==100.001
    row['canonical_profile'][0]['elev_m']=100.002
    second=build_release([row],cells,tmp_path/'second',published_at='2026-09-08T00:00:00Z')
    assert json.loads((second/'climbs.jsonl').read_text())['geographic_revision_id']!=revision
    # A new complete release retains old exact geographic revisions.
    retained=build_release([row],cells,tmp_path/'first',published_at='2026-09-09T00:00:00Z')
    assert len((retained/'climbs.jsonl').read_text().splitlines())==2
