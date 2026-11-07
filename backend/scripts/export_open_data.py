#!/usr/bin/env python3
"""Read-only, repeatable registry export. No publication, activation or DB writes.

The source is today's ratified/retired registry, NOT a pinned production release.
The full production release boundary belongs to boulderroller-v2-lfsu0.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.canon_commitment import CANON_PROFILE_HASH_DOMAIN, canonical_profile_hash_hex, build_canon_commitment
from app.services.geographic_data import inherited_source_provenance
from app.services.canon_provenance import PROVENANCE, ExportError, project_provenance, schema_from_spec
from blake3 import blake3

SCHEMA_VERSION = 'br-geography-export-1'
PACK = Path(__file__).resolve().parents[2] / 'history/pro-research-2026-09-07/files/odbl-round3'
GEOMETRIES = ('centerline_geom', 'corridor_geom', 'gate_start_line', 'gate_end_line')
FIELDS = '''id canon_id version status candidate_fingerprint display_name route_name direction
centerline_polyline canonical_profile length_m vert_m avg_gradient_pct max_gradient_pct
worthiness_score confidence dem_source compiler_version osm_way_refs odbl_source odbl_extract_at
provenance low_confidence_flags ratified_at retired_at supersedes_climb_id record_continuity_policy
created_at updated_at'''.split()
PRIVATE_COLUMNS = {'ratified_by'}

def encode(value):
    def default(v):
        if isinstance(v, Decimal): return float(v)
        if isinstance(v, datetime): return v.isoformat()
        raise TypeError(type(v).__name__)
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False, default=default)+'\n').encode()

def sha(data): return hashlib.sha256(data).hexdigest()


def profile_bytes(points):
    # Mirror the frozen byte feeder, and verify against the actual runtime codec.
    digest = canonical_profile_hash_hex(points)
    data = CANON_PROFILE_HASH_DOMAIN + b''.join(f"{float(p['dist_m']):.2f}:{float(p['elev_m']):.2f};".encode() for p in points)
    if blake3(data).hexdigest() != digest: raise ExportError('Runtime serializer drift')
    return data

def read_registry(connection):
    """One MVCC snapshot; all retired rows are public-addressable by climb detail."""
    from psycopg2.extras import RealDictCursor
    connection.set_session(isolation_level='REPEATABLE READ', readonly=True, autocommit=False)
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='canon_climbs'")
        columns = {r['column_name'] for r in cursor.fetchall()}
        if columns != set(FIELDS) | set(GEOMETRIES) | PRIVATE_COLUMNS:
            raise ExportError('Unclassified registry schema change')
        geom_sql = ','.join(f"ST_AsGeoJSON({g},15)::json AS {g}, encode(ST_AsEWKB({g}),'hex') AS {g}_ewkb" for g in GEOMETRIES)
        cursor.execute(f"SELECT {','.join(FIELDS)}, {geom_sql} FROM public.canon_climbs WHERE status IN ('ratified','retired') ORDER BY canon_id,version,id")
        rows = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT c.canon_climb_id::text,c.h3_resolution,c.tile_id,c.coverage_role FROM public.canon_corridor_cells c JOIN public.canon_climbs r ON r.id=c.canon_climb_id WHERE r.status IN ('ratified','retired') ORDER BY c.canon_climb_id,c.tile_id,c.coverage_role")
        cells = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT i.canon_climb_id::text,i.canon_commitment_hex FROM public.indexed_climbs i JOIN public.canon_climbs r ON r.id=i.canon_climb_id WHERE r.status IN ('ratified','retired')")
        commitments = {r['canon_climb_id']:r['canon_commitment_hex'] for r in cursor.fetchall()}
    return rows,cells,commitments


def build_release(rows, cells, releases, *, published_at, commitments=None):
    # Exact adopted notice bytes; resolved legacy source only.
    notices = {'osm': {'text': '© OpenStreetMap contributors'}, 'usgs_3dep': {'text': 'Data available from U.S. Geological Survey, National Geospatial Program.'}}
    parsed_time=datetime.fromisoformat(published_at.replace('Z','+00:00'))
    if parsed_time.utcoffset() != timezone.utc.utcoffset(parsed_time): raise ExportError('UTC timestamp required')
    files = {}
    climbs,profiles,sources = [],[],{}
    grouped = {}
    for cell in cells:
        if set(cell) != {'canon_climb_id','h3_resolution','tile_id','coverage_role'}: raise ExportError('Unclassified cell field')
        if cell['h3_resolution'] != 10 or not re.fullmatch('[0-9a-f]{15}',cell['tile_id']): raise ExportError('Invalid H3 cell')
        grouped.setdefault(str(cell['canon_climb_id']),[]).append({k:v for k,v in cell.items() if k!='canon_climb_id'})
    allowed = set(FIELDS) | set(GEOMETRIES) | {g+'_ewkb' for g in GEOMETRIES}
    identities=set()
    rows_by_id = {str(row['id']): row for row in rows}
    if len(rows_by_id) != len(rows): raise ExportError('Duplicate registry identity')
    for raw in sorted(rows,key=lambda r:(str(r['canon_id']),r['version'],str(r['id']))):
        if set(raw) != allowed: raise ExportError('Unclassified or missing registry fields')
        if raw['status'] not in ('ratified','retired') or not raw['canon_id'] or not raw['ratified_at']: raise ExportError('Unpublished registry row')
        row=json.loads(encode(raw))
        try:
            row['provenance'] = inherited_source_provenance(row, rows_by_id)
        except ValueError as exc:
            raise ExportError(str(exc)) from exc
        key=(row['canon_id'],row['version'])
        if key in identities: raise ExportError('Duplicate canon/version')
        identities.add(key)
        launch_manifest=row['provenance'].get('launch_ratification',{}).get('candidate_manifest_sha256')
        row['provenance']=project_provenance(row['provenance'])
        # This exact manifest is the retained Philadelphia launch authority.
        if launch_manifest == 'da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb':
            row['provenance']['region']='philadelphia'
        if not row['provenance'].get('region'): raise ExportError('Region attribution requires a public registry or launch authority')
        points=row.pop('canonical_profile')
        for point in points:
            if set(point)!={'dist_m','elev_m'}: raise ExportError('Unclassified profile sample field')
        exact=profile_bytes(points)
        if row['provenance']['canonical_profile_hash']['value'] != blake3(exact).hexdigest(): raise ExportError('Stored profile hash mismatch')
        row['h3_cells']=sorted(grouped.get(row['id'],[]),key=lambda c:(c['tile_id'],c['coverage_role']))
        if not row['h3_cells']: raise ExportError('Missing H3 coverage')
        source_label=row['dem_source']
        # This is a legacy label, not an asset admission. No inferred datum/receipts.
        if source_label != 'USGS 3DEP 10m local profile export': raise ExportError('Unresolved legacy source notice; source review required')
        source_id='legacy-'+sha(source_label.encode())
        sources[source_id]={'asset_id':source_id,'kind':'legacy_source_label','label':source_label,'provenance_status':'incomplete','admission':None,'content_sha256':None,'source_updated_at':None,'vertical_datum':None,'missing_reason':'not_recorded_in_registry','license_id':'public-domain','license_url':'https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits','notices':[{'id':'usgs_3dep','text':notices['usgs_3dep']['text'],'basis':'Guidance','requirement':'requested'}]}
        osm_id='osm-'+sha(encode({'extract_at':row['odbl_extract_at'],'source':row['odbl_source']}))
        sources[osm_id]={'asset_id':osm_id,'kind':'legacy_source_label','label':row['odbl_source'],'provenance_status':'incomplete','admission':None,'content_sha256':None,'source_updated_at':row['odbl_extract_at'],'vertical_datum':None,'missing_reason':'extract_digest_not_recorded_in_registry','license_id':'ODbL-1.0','license_url':'https://opendatacommons.org/licenses/odbl/1-0/','notices':[{'id':'osm','text':notices['osm']['text'],'basis':'Guidance','requirement':'mandatory'}]}
        row['source_ids']=[osm_id,source_id]
        row['notice_ids']=['osm','usgs_3dep']
        row['canon_version']=row.pop('version')
        row['registry_id']=row.pop('id')
        commitment=(commitments or {}).get(row['registry_id'])
        if commitment:
            expected=build_canon_commitment(canon_id=row['canon_id'],version=row['canon_version'],profile_hash_hex=blake3(exact).hexdigest()).hex()
            if commitment != expected: raise ExportError('Indexed v1 commitment mismatch')
            row['v1_commitment_hex']=commitment
        revision=sha(encode(row)+encode(points)+exact)
        row['geographic_revision_id']=revision
        for geometry in GEOMETRIES:
            data=bytes.fromhex(row.pop(geometry+'_ewkb'))
            files[f'canonical-bytes/{revision}/{geometry}.ewkb']=data
        files[f'canonical-bytes/{revision}/profile.bin']=exact
        profiles.append({'canon_id':row['canon_id'],'canon_version':row['canon_version'],'geographic_revision_id':revision,'profile_serializer_id':'blake3_canonical_profile_v1','vertical_datum':None,'distance_unit':'metre','elevation_unit':'metre','provenance_status':'incomplete','missing_reason':'datum_and_per_sample_contributions_not_recorded_in_registry','samples':[{**p,'source_contribution_ids':None} for p in points]})
        climbs.append(row)
    # Every old export remains an input to the next complete archive. Verify before
    # carrying history forward; never reconstruct an old payload from current rows.
    current_ids={r['geographic_revision_id'] for r in climbs}
    historical_ids=[]
    for old in sorted(Path(releases).glob('*/manifest.json')):
        old_manifest=json.loads(old.read_bytes())
        for name, record in old_manifest['files'].items():
            data=(old.parent/name).read_bytes()
            if sha(data)!=record['sha256'] or len(data)!=record['bytes']: raise ExportError('Corrupt retained release')
        old_rows=[json.loads(line) for line in (old.parent/'climbs.jsonl').read_text().splitlines()]
        old_profiles={r['geographic_revision_id']:r for r in map(json.loads,(old.parent/'profiles.jsonl').read_text().splitlines())}
        for row in old_rows:
            revision=row['geographic_revision_id']
            if revision in current_ids: continue
            current_ids.add(revision);historical_ids.append(revision)
            climbs.append(row);profiles.append(old_profiles[revision])
            for name in old_manifest['files']:
                if name.startswith('canonical-bytes/'+revision+'/'): files[name]=(old.parent/name).read_bytes()
        for source in map(json.loads,(old.parent/'SOURCES.jsonl').read_text().splitlines()):
            if source['asset_id'] in sources and sources[source['asset_id']] != source: raise ExportError('Mutated retained source')
            sources[source['asset_id']]=source
    climbs.sort(key=lambda r:(r['canon_id'],r['canon_version'],r['geographic_revision_id']))
    profiles.sort(key=lambda r:(r['canon_id'],r['canon_version'],r['geographic_revision_id']))
    files['climbs.jsonl']=b''.join(encode(r) for r in climbs)
    for region in sorted({r['provenance']['region'] for r in climbs}):
        if not re.fullmatch('[a-z0-9-]+',region): raise ExportError('Unsafe region identifier')
        files[f'regions/{region}.jsonl']=b''.join(encode(r) for r in climbs if r['provenance']['region']==region)
    files['profiles.jsonl']=b''.join(encode(r) for r in profiles)
    files['SOURCES.jsonl']=b''.join(encode(sources[k]) for k in sorted(sources))
    files['NOTICES.txt']=('\n'.join([notices['osm']['text'],'https://www.openstreetmap.org/copyright','ODbL 1.0','https://opendatacommons.org/licenses/odbl/1-0/']+([notices['usgs_3dep']['text']] if sources else []))+'\n').encode()
    # Machine-readable closed transport schemas, including nested objects.
    scalar={'type':['string','number','boolean','null']}
    def obj(properties): return {'type':'object','additionalProperties':False,'properties':properties,'required':list(properties)}
    geometry=obj({'type':{'enum':['LineString','MultiPolygon']},'coordinates':{'type':'array','items':{'type':'array'}}})
    climb_properties={k:scalar for k in FIELDS if k not in ('id','version','canonical_profile','provenance','osm_way_refs','low_confidence_flags')}
    climb_properties.update({k:geometry for k in GEOMETRIES})
    climb_properties.update({k:{'type':'array','items':scalar} for k in ('osm_way_refs','low_confidence_flags','source_ids','notice_ids')})
    climb_properties.update({'registry_id':scalar,'canon_version':{'type':'integer'},'geographic_revision_id':scalar,'v1_commitment_hex':scalar,'provenance':schema_from_spec(PROVENANCE),'h3_cells':{'type':'array','items':obj({'h3_resolution':{'const':10},'tile_id':{'type':'string','pattern':'^[0-9a-f]{15}$'},'coverage_role':{'enum':['corridor','gate_start','gate_end']}})}})
    climb_schema=obj(climb_properties);climb_schema['required'].remove('v1_commitment_hex')
    files['schemas/climb.schema.json']=encode(climb_schema)
    profile_schema=obj({**{k:scalar for k in ('canon_id','canon_version','geographic_revision_id','profile_serializer_id','vertical_datum','distance_unit','elevation_unit','provenance_status','missing_reason')},'samples':{'type':'array','items':obj({'dist_m':{'type':'number'},'elev_m':{'type':'number'},'source_contribution_ids':{'type':['array','null'],'items':{'type':'string'}}})}})
    files['schemas/profile.schema.json']=encode(profile_schema)
    source_schema=obj({**{k:scalar for k in ('asset_id','kind','label','provenance_status','content_sha256','source_updated_at','vertical_datum','missing_reason','license_id','license_url')},'admission':{'type':'null'},'notices':{'type':'array','items':obj({k:scalar for k in ('id','text','basis','requirement')})}})
    files['schemas/source.schema.json']=encode(source_schema)
    files['schemas/provenance.schema.json']=encode(schema_from_spec(PROVENANCE))
    files['schemas/registry-classification.json']=encode({'exported':FIELDS+list(GEOMETRIES),'operational_private':sorted(PRIVATE_COLUMNS),'provenance':PROVENANCE})
    for name in ('source-admission.schema.yaml','source-policy.yaml'):
        files['schemas/'+name]=(PACK/name).read_bytes()
    files['schemas/profile-encoding.json']=encode({'serializer':'blake3_canonical_profile_v1','encoding':'UTF-8 domain followed by each runtime float formatted .2f as distance:elevation; in stored order','domain':CANON_PROFILE_HASH_DOMAIN.decode(),'test_vector':{'samples':[{'dist_m':0.0,'elev_m':100.0},{'dist_m':12.345,'elev_m':101.234}],'bytes_hex':profile_bytes([{'dist_m':0.0,'elev_m':100.0},{'dist_m':12.345,'elev_m':101.234}]).hex(),'blake3':'8b0b5e33a5d495b913a979b2c33a948fbaca731fe067bb219e855facf5662600'}})
    files['licences/uris.json']=encode({'ODbL-1.0':'https://opendatacommons.org/licenses/odbl/1-0/','USGS':'https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits'})
    for name,data in list(files.items()):
        if name.startswith('schemas/') and name.endswith('.json'):
            files[name]=(json.dumps(json.loads(data),indent=2,ensure_ascii=False)+'\n').encode()
    manifest={'export_schema_version':SCHEMA_VERSION,'published_at_utc':published_at,'source':{'tables':['public.canon_climbs','public.canon_corridor_cells'],'predicate':"status IN ('ratified','retired')",'retired_scope':'All retired revisions remain addressable by the public climb-detail route.','consistency':'read-only repeatable-read registry snapshot; production readers do not pin this release','full_boundary_bead':'boulderroller-v2-lfsu0','commitment_source':'public.indexed_climbs.canon_commitment_hex (geographic commitment only)','region_authority':'history/canon-runtime-cutover-2026-07-21/README.md; exact Philadelphia candidate manifest SHA-256','retained_revision_ids':sorted(historical_ids)},'revisions':[{'canon_id':r['canon_id'],'canon_version':r['canon_version'],'geographic_revision_id':r['geographic_revision_id'],'registry_id':r['registry_id']} for r in climbs],'climb_identity_count':len({r['canon_id'] for r in climbs}),'geographic_revision_count':len(climbs),'regions':sorted({r['provenance']['region'] for r in climbs if r['provenance'].get('region')}),'region_count':len({r['provenance']['region'] for r in climbs if r['provenance'].get('region')}),'region_metadata_status':'incomplete_when_region_not_recorded','excluded_scope':['private_candidates','raw_rides','rider_identities','economic_accounts','private_review_evidence'],'files':{name:{'sha256':sha(data),'bytes':len(data)} for name,data in sorted(files.items())},'sources_sha256':sha(files['SOURCES.jsonl']),'notices_sha256':sha(files['NOTICES.txt'])}
    release_id=sha(encode(manifest))
    manifest['release_id']=release_id
    files['manifest.json']=encode(manifest)
    files['manifest.sha256']=(sha(files['manifest.json'])+'  manifest.json\n').encode()
    files['SHA256SUMS']=b''.join(f'{sha(data)}  {name}\n'.encode() for name,data in sorted(files.items()))
    releases=Path(releases);releases.mkdir(parents=True,exist_ok=True)
    destination=releases/release_id
    if destination.exists(): raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix='.open-data-',dir=releases) as stage:
        stage=Path(stage)
        for name,data in files.items():
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        with zipfile.ZipFile(stage/'release.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for name,data in sorted(files.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644 << 16
                archive.writestr(info,data)
        (stage/'release.zip.sha256').write_text(sha((stage/'release.zip').read_bytes())+'  release.zip\n')
        (stage/'delivery.json').write_bytes(encode({'release_id':release_id,'archive_sha256':sha((stage/'release.zip').read_bytes()),'measured_compressed_bytes':(stage/'release.zip').stat().st_size,'measured_uncompressed_bytes':sum(map(len,files.values()))}))
        # Serialize local publishers, then install the COMPLETE directory atomically.
        # Readers never observe an incomplete release; existing paths are rejected.
        import fcntl
        with (releases/'.publish.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if destination.exists(): raise FileExistsError(destination)
            stage.rename(destination)
    return destination


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--published-at',required=True,help='UTC release timestamp, reused exactly for reproducibility')
    parser.add_argument('--env-file',type=Path)
    args=parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file,override=False)
    import psycopg2
    with psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=10) as connection:
        rows,cells,commitments=read_registry(connection)
        if not rows: raise ExportError('Refuse an empty production release')
        result=build_release(rows,cells,args.output,published_at=args.published_at,commitments=commitments)
    print(result)

if __name__=='__main__': main()
