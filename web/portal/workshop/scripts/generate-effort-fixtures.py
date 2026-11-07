#!/usr/bin/env python3
"""Local/offline fixtures from original recordings, D11 and the effort-data lane.

Run with that lane's native-enabled Python, passing retained geometry inputs.
No network, external database writes, source activity IDs or GPS in output.
Threshold uses the repository's dated native-anchor/SQL estimate. The 72 kg
denominator remains an explicit illustrative workshop input from r10.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import subprocess
import sqlite3
import sys
from bisect import bisect_left
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from effort_threshold import threshold_estimator, function_sources, FUNCTIONS

ROOT = Path(__file__).resolve().parents[4]

# Illustrative rider identities; sharing is one setting per rider, never per effort.
RIDERS = {
    'morgan': {'name': 'Morgan', 'share_wkg': True},
    'rowan': {'name': 'Rowan', 'share_wkg': False},
    'taylor': {'name': 'Taylor', 'share_wkg': False},
}
SOURCE_RIDERS = ['morgan', 'rowan', 'morgan', 'morgan', 'morgan', 'morgan', 'taylor']
BOARD_NAMES = 'Avery Casey Jordan Quinn Riley Cameron Drew Ellis Finley Harper Jamie Kendall Logan Parker Reese Robin Sage Sam Sidney Skyler Spencer Terry Alex Blair Devon Emery Hayden Jesse Jules Lee Marlow Noel Remy River Rory Shiloh'.split()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def at(points, distance):
    if distance <= points[0]['dist_m']:
        return points[0]['elev_m']
    for a, b in zip(points, points[1:]):
        if b['dist_m'] >= distance:
            return a['elev_m'] + (b['elev_m'] - a['elev_m']) * (distance - a['dist_m']) / (b['dist_m'] - a['dist_m'])
    return points[-1]['elev_m']


def same_recording(a, b):
    """Recognize a retained FIT exported through the corpus at GPS precision."""
    return (abs(a.started_at_ms-b.started_at_ms)<=1000
            and abs(int(a.time_ms[-1])-int(b.time_ms[-1]))<=1000
            and all(abs(int(x[i])-int(y[i]))<=100 for x,y in [(a.lat_e7,b.lat_e7),(a.lon_e7,b.lon_e7)] for i in (0,-1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-root', type=Path, required=True)
    parser.add_argument('--engine-ref', default='origin/main')
    parser.add_argument('--gate-ref', default='origin/main')
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--old-gates', type=Path, required=True)
    parser.add_argument('--new-gates', type=Path, required=True)
    parser.add_argument('--fit', type=Path, action='append', default=[])
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--ordinal', type=int, action='append', default=[])
    parser.add_argument('--output', type=Path, default=ROOT / 'web/portal/workshop/effort/fixtures.json')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for path, artifact in [(args.old_gates, 'COMPILER-BEFORE'), (args.new_gates, 'ADMITTED-AFTER')]:
        admitted = json.loads(git('show', f'{args.gate_ref}:history/codex-reports-2026-10-20/gate-rule/{artifact}.json'))
        if digest(path) != admitted['full_local_source']['sha256']:
            raise SystemExit(f'{artifact} geometry differs from the requested gate ref.')
    sha = git('rev-parse', args.engine_ref)
    source = 'backend/app/services/climb_effort_metrics.py'
    for dependency in [source, 'backend/app/services/training_metrics.py', *['backend/sql/'+file for file, _ in FUNCTIONS]]:
        if (args.engine_root / dependency).read_text().strip() != git('show', f'{sha}:{dependency}'):
            raise SystemExit(f'{dependency} differs from the requested engine ref; do not mix versions.')
    sys.path.insert(0, str(args.engine_root / 'backend'))
    import workout_parse as wp
    from shapely import wkb, wkt
    from app.models.canon import CanonClimb
    from app.services.canon_traversal import CanonTraversalEngine
    from app.services.climb_effort_metrics import (
        EFFORT_ENGINE_VERSION, effort_timeline, build_effort_rows, compute_effort, _distance_at,
    )

    registry = json.loads(args.registry.read_text())
    source_list = [{'file':p.name, 'sha256':digest(p)} for p in args.fit]
    activities = [wp.parse_bytes(p.read_bytes()) for p in args.fit]
    dated_thresholds, threshold_bases, corpus_evidence = {}, {}, {}
    if args.corpus:
        from app.services.strava_service import StravaService
        with sqlite3.connect(args.corpus.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as connection:
            ids=[r[0] for r in connection.execute('SELECT activity_id FROM activity_streams ORDER BY CAST(activity_id AS INTEGER)')]
            service=object.__new__(StravaService)
            def parse_corpus(date, streams):
                return wp.parse_file_bytes(service._streams_to_gpx({'name':'Retained recording','start_date':date}, streams).encode(),'gpx')
            for ordinal in args.ordinal:
                source_id=ids[ordinal-1]
                raw_streams=connection.execute('SELECT streams_json FROM activity_streams WHERE activity_id=?',(source_id,)).fetchone()[0]
                streams={s['type']:s for s in json.loads(raw_streams)}
                date=connection.execute('SELECT start_date FROM rides WHERE activity_id=?',(source_id,)).fetchone()[0]
                activities.append(parse_corpus(date,streams))
                source_list.append({'ordinal':ordinal,'sha256':hashlib.sha256(raw_streams.encode()).hexdigest(),'format':'production Strava GPX conversion'})
            with threshold_estimator(args.engine_root, connection, parse_corpus) as (estimate, corpus_evidence):
                for date in sorted({datetime.fromtimestamp(a.started_at_ms/1000,tz=timezone.utc).date().isoformat() for a in activities}):
                    dated_thresholds[date], threshold_bases[date] = estimate(date)
    result = {'provenance':{
        'evidence':'local/offline D11 replay of retained recordings; illustrative display identities; dated corpus-owner training estimates',
        'engine_commit':sha, 'engine_version':EFFORT_ENGINE_VERSION,
        'metrics_sha256':digest(args.engine_root/source),
        'native_sha256':digest(importlib.import_module(wp.parse_bytes.__module__).__file__),
        'gate_commit':git('rev-parse', args.gate_ref),
        'gate_inputs':{'v1':digest(args.old_gates),'v2':digest(args.new_gates),'registry':digest(args.registry)},
        'sources':source_list,
        **({'corpus_sha256':digest(args.corpus)} if args.corpus else {}),
        'training_inputs':{'weight_kg':72,'weight_basis':'illustrative workshop input from r10','threshold_basis':'threshold_cp_3_7_15_v1','threshold_sql_sha256':hashlib.sha256('\n'.join(function_sources(args.engine_root)).encode()).hexdigest(),'dated_estimates':threshold_bases,**corpus_evidence},
        'board_selection':{'method':'up to first 11 additional measured-power corpus recordings assigned to illustrative riders per climb, by numeric corpus ordinal; fastest ascent per rider; both gate sets','plausibility_rule':'CLIMB_SENSOR:high_vam > 2000 m/h, as in ride_enrichment_service; fixture exclusion, not a D11 rejection','excluded_implausible_efforts':0,'exclusion_count_unit':'gate-specific effort projections, including both gate sets','additional_unmeasured_efforts_omitted':0,'native_rejected_recordings':0,'duplicate_source_recordings_omitted':0},
        'corridors':'retained September corridors, as in the gate-rule replay; no publication claim',
    }, 'riders':RIDERS, 'efforts':[], 'board_efforts':[], 'cross_check':{}}
    for gate, path in [('v2', args.new_gates), ('v1', args.old_gates)]:
        compiled = json.loads(path.read_text())['candidates']
        by_fingerprint = {(c['provenance'].get('finish_gate_rule') or {}).get('predecessor_fingerprint',c['candidate_fingerprint']):c for c in compiled}
        climbs, candidates = [], {}
        for row in registry:
            c = by_fingerprint.get(row['candidate_fingerprint'])
            if c and c['display_name'] not in {'Wises Mill Road','Black Rock Road','Levering Street / Lyceum Avenue','Andorra Road'}:
                continue
            if c is None:
                continue
            moved = c['candidate_fingerprint'] != row['candidate_fingerprint']
            climb = CanonClimb(
                registry_id=UUID(row['id']),canon_id=UUID(row['canon_id']),version=row['version']+int(moved),
                display_name=row['display_name'],route_name=row.get('route_name'),
                centerline=wkt.loads(c['centerline_wkt']),corridor=wkb.loads(bytes.fromhex(row['corridor_geom'])),
                gate_start=wkt.loads(c['gate_start_wkt']),gate_end=wkt.loads(c['gate_end_wkt']),
                canonical_profile=tuple(c['canonical_profile']),length_m=c['length_m'],vert_m=c['vert_m'],
                avg_gradient_pct=c['avg_gradient_pct'],compiler_version=c['compiler_version'],
                profile_hash_algorithm='blake3_canonical_profile_v1',profile_hash=c['provenance']['canonical_profile_hash']['value'],
                odbl_source=row['odbl_source'],corridor_tile_ids=(),candidate_fingerprint=c['candidate_fingerprint'],provenance=c['provenance'])
            climbs.append(climb)
            candidates[str(climb.registry_id)] = c
        for source_index, activity in enumerate(activities):
            started = datetime.fromtimestamp(activity.started_at_ms / 1000, tz=timezone.utc)
            raw = [{'t':(int(t)-activity.started_at_ms)/1000,'lat':int(lat)/1e7,'lon':int(lon)/1e7,
                    'power_w':None if activity.pwr_w is None or int(activity.pwr_w[i])==65535 else int(activity.pwr_w[i]),'source_index':i}
                   for i,(t,lat,lon) in enumerate(zip(activity.time_ms,activity.lat_e7,activity.lon_e7))
                   if abs(int(lat))<=900000000 and abs(int(lon))<=1800000000]
            evaluation = CanonTraversalEngine().evaluate(activity_id=uuid5(NAMESPACE_URL,'effort-view:'+source_list[source_index]['sha256']),wallet='offline',candidates=climbs,raw_samples=raw,user_weight_kg=72)
            patterns = [asdict(p) for p in evaluation.climb_patterns]
            if not patterns:
                continue
            threshold = dated_thresholds.get(started.date().isoformat())
            inputs = {'started_at':started.isoformat(),'threshold':threshold}
            rows = build_effort_rows(activity,patterns,inputs)
            timeline = effort_timeline(activity)
            for pattern, row in zip(patterns,rows):
                c = candidates[row['climb_id']]
                start, end = row['start_offset_s'], row['end_offset_s']
                metrics, profile = row['metrics'], c['canonical_profile']
                origin, finish = _distance_at(timeline,start), _distance_at(timeline,end)
                if origin is None or finish is None or finish<=origin:
                    raise ValueError('No continuous distance channel for figure')
                length = metrics['distance_m']
                def local_distance(time):
                    value = _distance_at(timeline,time)
                    if value is None:
                        raise ValueError('Unobserved distance inside figure')
                    return min(length,max(0,(value-origin)/(finish-origin)*length))
                # Gate-relative seconds give the cursor exact 1 s / 10 s steps.
                # Read each sensor from the engine's containing one-second cell.
                times = [start+i for i in range(math.ceil(end-start))]+[end]
                samples = []
                for time in times:
                    i = min(math.floor(time),len(timeline['power_w'])-1)
                    distance = local_distance(time)
                    a,b = max(0,distance-25),min(length,distance+25)
                    sample = {'elapsed_s':time-start,'distance_m':distance,'elevation_m':at(profile,distance),'grade_pct':(at(profile,b)-at(profile,a))/(b-a)*100}
                    if metrics['power_kind']=='measured':
                        sample['power_5s_w'] = timeline['zone_5s_w'][i]
                    for key, channel, factor in [('speed_kmh','speed_mps',3.6),('cadence_rpm','cadence_rpm',1),('hr_bpm','hr_bpm',1)]:
                        if timeline[channel][i] is not None:
                            sample[key] = timeline[channel][i]*factor
                    cadence = sample.get('cadence_rpm')
                    if metrics['power_kind']=='measured' and cadence is not None and cadence>=20:
                        sample['torque_nm'] = timeline['power_w'][i]/(2*math.pi*cadence/60)
                    samples.append(sample)
                # Match the kit's adjacent 100 m grade-rung grouping, on canon elevation.
                bands=[]
                def rung(grade):
                    return 4 if grade>=12 else 3 if grade>=9 else 2 if grade>=6 else 1 if grade>=3 else 0
                for a in range(0,math.ceil(length),100):
                    b=min(a+100,length);grade=(at(profile,b)-at(profile,a))/(b-a)*100
                    if bands and bands[-1]['rung']==rung(grade):
                        bands[-1]['to']=b;bands[-1]['grade']=(at(profile,b)-at(profile,bands[-1]['from']))/(b-bands[-1]['from'])*100
                    else:
                        bands.append({'from':a,'to':b,'grade':grade,'rung':rung(grade)})
                distances = [s['distance_m'] for s in samples]
                assert all(b>=a for a,b in zip(distances,distances[1:])), 'Non-monotonic figure distance'
                def crossing(distance):
                    i=bisect_left(distances,distance)
                    if i==0:return start
                    if i>=len(samples):return end
                    a,b=samples[i-1],samples[i]
                    return start+a['elapsed_s']+(b['elapsed_s']-a['elapsed_s'])*(distance-a['distance_m'])/(b['distance_m']-a['distance_m'])
                sections=[]
                # Reconcile integer official section clocks to the official effort clock.
                offsets=[0,*[round(crossing(b['to'])-start) for b in bands[:-1]],metrics['time_s']]
                for i, band in enumerate(bands):
                    a,b=crossing(band['from']),crossing(band['to'])
                    seconds=offsets[i+1]-offsets[i]
                    if seconds<=0:raise ValueError('Section too short for an official clock')
                    section=compute_effort(timeline,start_s=a,end_s=b,time_s=seconds,distance_m=band['to']-band['from'],net_gain_m=at(profile,band['to'])-at(profile,band['from']),threshold_w=(threshold or {}).get('value'),weight_kg=72,average_start_s=pattern['start_offset_s']+offsets[i])
                    sections.append({**band,'start_s':a-start,'end_s':b-start,'metrics':section})
                slug = {'Wises Mill Road':'wises','Black Rock Road':'black-rock','Levering Street / Lyceum Avenue':'wall'}.get(c['display_name'],c['display_name'].lower().replace(' / ','-').replace(' ','-'))
                date=started.date().isoformat()
                effort_id=f'{slug}-{date}-{round(start)}'
                # Existing climb sensor sanity screen; this is fixture selection,
                # not a change to traversal admission or integrity policy.
                if metrics['vam_m_per_hour'] > 2000:
                    result['provenance']['board_selection']['excluded_implausible_efforts'] += 1
                    continue
                rider_id = SOURCE_RIDERS[source_index]
                rider = RIDERS[rider_id]
                result['efforts'].append({'id':effort_id,'gates':gate,'climb':slug,'name':c['display_name'],'date':date,'occurred_at':datetime.fromtimestamp(started.timestamp()+start,tz=timezone.utc).isoformat(),'source_index':source_index,'rider_id':rider_id,'rider_name':rider['name'],'share_wkg':rider['share_wkg'],'recording':True,'canon_version':row['canon_version'],'start_s':start,'end_s':end,'metrics':metrics,'profile':[{'d':p['dist_m'],'elevation':p['elev_m']} for p in profile],'bands':bands,'samples':samples,'sections':sections})
                if gate=='v2' and slug=='wises' and not result['cross_check']:
                    # Independent formula: no use of engine rolling averages/NP/Load.
                    cells=[(i,min(end,i+1)-max(start,i)) for i in range(math.floor(start),math.ceil(end)) if timeline['moving'][i]]
                    fourth=sum((sum(timeline['np_power_w'][max(0,i-29):i+1])/min(30,i+1))**4*dt for i,dt in cells)
                    moving=sum(dt for _,dt in cells)
                    np_value=math.floor((fourth/moving)**.25+.5)
                    load=math.floor((np_value/threshold['value'])**2*moving/3600*100+.5) if threshold else None
                    assert (np_value,load)==(metrics['np_w'],metrics.get('load'))
                    result['cross_check']={'effort':effort_id,'np_w':np_value,'load':load,'moving_s':moving,'method':'independent trailing-window sums and fractional-cell fourth-power mean'}
        # Aggregate-only additions never enter Morgan's history or carry streams,
        # physiology, source activity IDs, or a fabricated verified-power claim.
        if args.corpus:
            counts = {str(c.registry_id): set() for c in climbs}
            bounds = {str(c.registry_id): c.corridor.bounds for c in climbs}
            with sqlite3.connect(args.corpus.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as connection:
                records=connection.execute('SELECT start_date,streams_json FROM rides JOIN activity_streams USING(activity_id) ORDER BY CAST(activity_id AS INTEGER)')
                for ordinal,(date,raw_streams) in enumerate(records,1):
                    if ordinal in args.ordinal:continue
                    wanted=[c for c in climbs if len(counts[str(c.registry_id)])<11]
                    if not wanted:break
                    streams={s['type']:s for s in json.loads(raw_streams)}
                    positions=streams.get('latlng',{}).get('data',[])
                    near=[]
                    for climb in wanted:
                        west,south,east,north=bounds[str(climb.registry_id)]
                        if any(west<=p[1]<=east and south<=p[0]<=north for p in positions):near.append(climb)
                    if not near:continue
                    try:activity=parse_corpus(date,streams)
                    except (wp.ParseError,wp.DurationLimitExceeded):
                        result['provenance']['board_selection']['native_rejected_recordings']+=1
                        continue
                    if any(same_recording(activity, full) for full in activities):
                        result['provenance']['board_selection']['duplicate_source_recordings_omitted']+=1
                        continue
                    raw=[{'t':(int(t)-activity.started_at_ms)/1000,'lat':int(lat)/1e7,'lon':int(lon)/1e7,'power_w':None if activity.pwr_w is None or int(activity.pwr_w[i])==65535 else int(activity.pwr_w[i]),'source_index':i} for i,(t,lat,lon) in enumerate(zip(activity.time_ms,activity.lat_e7,activity.lon_e7)) if abs(int(lat))<=900000000 and abs(int(lon))<=1800000000]
                    evaluation=CanonTraversalEngine().evaluate(activity_id=uuid5(NAMESPACE_URL,'effort-board:'+str(ordinal)),wallet='offline',candidates=near,raw_samples=raw,user_weight_kg=72)
                    patterns=[asdict(p) for p in evaluation.climb_patterns]
                    rows=build_effort_rows(activity,patterns,{'started_at':date})
                    for row in rows:
                        metrics=row['metrics']
                        if metrics['vam_m_per_hour'] > 2000:
                            result['provenance']['board_selection']['excluded_implausible_efforts']+=1
                            continue
                        # New board identities use corroborated power recordings;
                        # no unmeasured fast ascent is admitted on estimated watts.
                        if metrics['power_kind']!='measured':
                            result['provenance']['board_selection']['additional_unmeasured_efforts_omitted']+=1
                            continue
                        c=candidates[row['climb_id']]
                        slug={'Wises Mill Road':'wises','Black Rock Road':'black-rock','Levering Street / Lyceum Avenue':'wall','Andorra Road':'andorra-road'}[c['display_name']]
                        rider_id=f'corpus-{ordinal}'
                        if rider_id not in RIDERS:RIDERS[rider_id]={'name':BOARD_NAMES[len(RIDERS)-3], 'share_wkg':False}
                        rider=RIDERS[rider_id]
                        counts[row['climb_id']].add(rider_id)
                        started=datetime.fromtimestamp(activity.started_at_ms/1000,tz=timezone.utc)
                        result['board_efforts'].append({'id':f'board-{ordinal}-{slug}-{round(row["start_offset_s"])}','gates':gate,'climb':slug,'name':c['display_name'],'date':started.date().isoformat(),'occurred_at':datetime.fromtimestamp(started.timestamp()+row['start_offset_s'],tz=timezone.utc).isoformat(),'rider_id':rider_id,'rider_name':rider['name'],'share_wkg':False,'recording':False,'metrics':{k:metrics[k] for k in ('time_s','power_kind','avg_power_w') if k in metrics}})
    result['efforts'].sort(key=lambda e:(e['gates'],e['climb'],e['date'],e['start_s']))
    # Distance-aligned comparisons are generated here, never recomputed by the view.
    def interpolate(samples, distance, key):
        pos=bisect_left([s['distance_m'] for s in samples],distance)
        if pos==0:return samples[0].get(key)
        if pos>=len(samples):return samples[-1].get(key)
        a,b=samples[pos-1],samples[pos]
        if key not in a or key not in b:return None
        return a[key]+(b[key]-a[key])*(distance-a['distance_m'])/(b['distance_m']-a['distance_m'])
    for effort in result['efforts']:
        effort['comparisons']={}
        for other in result['efforts']:
            if other['id']==effort['id'] or other['climb']!=effort['climb'] or other['gates']!=effort['gates']:continue
            effort['comparisons'][other['id']]={
                'points':[{'gap_s':s['elapsed_s']-interpolate(other['samples'],s['distance_m'],'elapsed_s'),**({'power_w':p} if (p:=interpolate(other['samples'],s['distance_m'],'power_5s_w')) is not None else {})} for s in effort['samples']],
                'section_gaps_s':[(section['end_s']-section['start_s'])-(interpolate(other['samples'],section['to'],'elapsed_s')-interpolate(other['samples'],section['from'],'elapsed_s')) for section in effort['sections']],
            }
    text=json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    if args.check:
        assert args.output.read_text()==text, 'Fixture is stale; regenerate from current inputs'
    else:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(json.dumps({'output':str(args.output),'sha256':hashlib.sha256(text.encode()).hexdigest(),'efforts':len(result['efforts']),'engine_commit':sha,'cross_check':result['cross_check']}))


if __name__=='__main__':
    main()
