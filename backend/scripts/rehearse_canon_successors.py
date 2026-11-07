#!/usr/bin/env python3
"""Rehearse the successor runbook on an owned, TCP-disabled PostgreSQL 17.

Accepts local schema-only/ledger exports and the retained September geography.
Never accepts a remote DSN or reads application .env files.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from scripts.rehearse_stage1_migrations import cluster, postgres_bin, restore, apply_stack, run, ledger_rows
from scripts import publish_canon_successors as publication
from scripts.apply_sql_migrations import discover_migrations, assert_checksums_match
from scripts.export_open_data import read_registry, build_release
from app.services.geographic_data import _index


def rehearsal_environment():
    env={key:os.environ[key] for key in ('PATH','TMPDIR','SYSTEMROOT') if key in os.environ}
    env.update(ENVIRONMENT='test', SOLANA_STUB='true', NATS_ENABLED='false',
               ACCESS_TOKEN_SECRET='local-test-only', REFRESH_TOKEN_SECRET='local-test-only-2',
               JWT_SECRET='local-test-only', LC_ALL='en_US.UTF-8')
    return env


def seed(connection, path, cells_path, sql_dir):
    rows = json.loads(path.read_text())
    if len(rows) != 57 or any(r['version'] != 1 or r['status'] != 'ratified' for r in rows):
        raise ValueError('Expected exactly 57 v1 ratified snapshot rows')
    with connection.cursor() as cursor:
        # The public-only schema export intentionally omits private objects.
        # Create the real canonical 152 prerequisites with a NEW local key;
        # use the actual user-creation fence rather than disabling triggers.
        private_ddl=(sql_dir/'152_account_deletion_lifecycle.sql').read_text().split(
            'CREATE OR REPLACE FUNCTION public.br_account_deletion_wallet_fingerprint(',1)[0]
        cursor.execute(private_ddl)
        cursor.execute('SELECT count(*) FROM public.canon_climbs')
        if cursor.fetchone()[0]:
            raise ValueError('Local schema restore unexpectedly contained canon rows')
        for row in rows:
            # Preserve EVERY provided field exactly, including retained EWKB.
            # Missing public metadata comes from the committed retained export.
            value = dict(row)
            exported = _index()[row['id']][-1]['exported']
            value.update({key:exported[key] for key in ('centerline_polyline','dem_source','ratified_at')})
            value['ratified_by'] = 'PRIVATE-APPROVER-CANARY'
            geometries = {'centerline_geom','corridor_geom','gate_start_line','gate_end_line'}
            columns = list(value)
            values = [Json(value[k]) if isinstance(value[k], (dict,list)) else value[k] for k in columns]
            placeholders = [sql.SQL("ST_GeomFromEWKB(decode(%s,'hex'))") if k in geometries else sql.Placeholder() for k in columns]
            cursor.execute(sql.SQL('INSERT INTO public.canon_climbs ({}) VALUES ({})').format(
                sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(placeholders)), values)
        cells = json.loads(cells_path.read_text())
        assert len(cells) == 2923 and any(c['coverage_role']=='gate_start' for c in cells)
        for cell in cells:
            cursor.execute('INSERT INTO public.canon_corridor_cells(canon_climb_id,h3_resolution,tile_id,coverage_role) VALUES(%s,%s,%s,%s)',
                           tuple(cell[k] for k in ('canon_climb_id','h3_resolution','tile_id','coverage_role')))
        # A synthetic Shawmont binding exercises its immutability fence; no
        # claim that this row is a retained/live on-chain observation.
        sh = next(r for r in rows if r['id'] == publication.SHAWMONT_ID)
        cursor.execute('''INSERT INTO public.indexed_climbs(pda,canon_climb_id,canon_commitment_hex,commitment_hash_hex,
            canon_id,canon_version,canonical_profile_hash_hex,record_continuity_policy,name,vert_m,distance_m,
            avg_gradient_pct,registered_at,registered_by,chain_slot)
            VALUES(%s,%s,%s,%s,%s,1,%s,'new_record_board',%s,%s,%s,%s,now(),'LOCAL SYNTHETIC',1)''',
            ('LOCAL-SYNTHETIC-SHAWMONT',sh['id'],'01'*64,'02'*32,sh['canon_id'],'03'*32,sh['display_name'],sh['vert_m'],round(sh['length_m']),sh['avg_gradient_pct']))
        # Synthetic legacy boards: no target chain binding is invented.
        for index in range(3):
            cursor.execute('INSERT INTO public.indexed_leaderboards(vault_id,entries) VALUES(%s,%s)',
                           (900000+index,Json([{'wallet':f'LOCAL-SYNTHETIC-{index}','time_seconds':100+index}])))
            cursor.execute("INSERT INTO public.vault_leaderboards(vault_signature,rank,wallet,best_time_seconds,achieved_at) VALUES(%s,1,%s,%s,'2026-09-10T00:00:00Z')",
                           (f'LOCAL-SYNTHETIC-{index}',f'LOCAL-SYNTHETIC-{index}',100+index))
        # Actual predecessor-keyed read-side effort rows exercise fresh boards
        # and their FK/dependent-row archive, with synthetic users/rides only.
        user, ride = str(uuid4()), str(uuid4())
        cursor.execute("SELECT * FROM public.br_get_or_create_active_user(%s,'LOCAL-SYNTHETIC-RIDER')", (user,))
        cursor.execute('INSERT INTO public.rides(id,user_id) VALUES(%s,%s)', (ride,user))
        for row in publication.load_successors()[:3]:
            effort = str(uuid4())
            cursor.execute("INSERT INTO public.patterns_climb(id,activity_id,wallet,vert_m,time_s,match_trace) VALUES(%s,%s,'PRIVATE-RIDER-CANARY',10,100,%s)",
                           (effort,ride,Json({'registry_id':row['supersedes_climb_id'],'private_evidence':'PRIVATE-TRACE-CANARY'})))
            cursor.execute("""INSERT INTO public.climb_efforts(id,ride_id,user_id,climb_id,canon_version,start_offset_s,end_offset_s,
                achieved_at,time_s,avg_power_w,power_kind,metrics,engine_version)
                VALUES(%s,%s,%s,%s,1,0,100,'2026-09-10T00:00:00Z',100,200,'measured','{}',1)""",
                (effort,ride,user,row['supersedes_climb_id']))
    connection.commit()
    return {'snapshot_rows':57,'sealed_cells':len(cells),'synthetic_indexed_boards':3,'synthetic_legacy_boards':3,
            'synthetic_predecessor_efforts':3,'synthetic_shawmont_binding':True}, user, ride


class LocalQuery:
    """Small SQL-backed transport adapter for the actual HTTP routes below."""
    def __init__(self, dsn, table=None, rpc=None):
        self.dsn,self.table,self.rpc_call=dsn,table,rpc
        self.columns='*'; self.filters=[]; self.parameters=[]; self.maximum=None
    def select(self, columns): self.columns=columns; return self
    def eq(self, column, value):
        self.filters.append(sql.SQL('{}=%s').format(sql.Identifier(column))); self.parameters.append(value); return self
    def in_(self, column, value):
        self.filters.append(sql.SQL('{}=ANY(%s)').format(sql.Identifier(column))); self.parameters.append(value); return self
    def limit(self, maximum): self.maximum=maximum; return self
    def execute(self):
        with closing(psycopg2.connect(self.dsn)) as connection:
            connection.set_session(readonly=True)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if self.rpc_call:
                    name,params=self.rpc_call
                    assert name=='get_canon_climb_runtime_states'
                    cursor.execute('SELECT canon_climb_id::text,runtime_state FROM public.get_canon_climb_runtime_states(%s::uuid[])', (params['p_canon_climb_ids'],))
                else:
                    columns=sql.SQL(',').join(sql.Identifier(k.strip()) for k in self.columns.split(',')) if self.columns!='*' else sql.SQL('*')
                    query=sql.SQL('SELECT {} FROM {}').format(columns,sql.Identifier('public',self.table))
                    if self.filters: query+=sql.SQL(' WHERE ')+sql.SQL(' AND ').join(self.filters)
                    if self.maximum is not None: query+=sql.SQL(' LIMIT {}').format(sql.Literal(self.maximum))
                    cursor.execute(query,self.parameters)
                # PostgREST returns JSON numbers/timestamps, not psycopg's
                # Decimal/datetime objects. Exercise the real route contract.
                return SimpleNamespace(data=json.loads(publication.json_text([dict(r) for r in cursor.fetchall()])))


def http_probe(dsn, result):
    # Route imports construct clients. Make this an explicitly offline test
    # process before those imports; every database read below uses our socket.
    os.environ['ENVIRONMENT']='test'
    os.environ['SOLANA_STUB']='true'
    os.environ['NATS_ENABLED']='false'
    from app import config
    config.load_dotenv=None
    config.get_environment.cache_clear()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import climbs
    client=SimpleNamespace(from_=lambda table:LocalQuery(dsn,table),rpc=lambda name,params:LocalQuery(dsn,rpc=(name,params)))
    app=FastAPI();app.include_router(climbs.router,prefix='/climbs')
    app.dependency_overrides[climbs.get_repository]=lambda:SimpleNamespace(client=client)
    app.dependency_overrides[climbs.get_optional_current_user]=lambda:None
    selected=next(r for r in result if r['name']=='Lafayette Road')
    with TestClient(app) as http:
        for current in (result[0], selected):
            detail=http.get('/climbs/'+current['id']); board=http.get('/climbs/'+current['id']+'/leaderboard')
            assert detail.status_code==200,detail.text
            assert board.status_code==200,board.text
            value=detail.json();assert value['version']==2 and value['revision_state']=='current'
            assert board.json()['entries']==[]
            previous=http.get('/climbs/'+current['predecessor_id']);assert previous.status_code==200
            assert previous.json()['revision_state']=='retired'
            for response in (value,previous.json()):
                assert any(n['id']=='usgs_3dep' for s in response['geographic_data']['sources'] for n in s['notices'])
    # Execute the indexer's actual registry SELECT against the same DB.
    source=(BACKEND.parent/'indexer/src/api.ts').read_text()
    query=re.search(r'const CANON_CLIMB_SELECT = `(.+?)`;',source,re.S).group(1)
    with closing(psycopg2.connect(dsn)) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query+' WHERE canon.id=%s::uuid',(selected['id'],))
            indexed=cursor.fetchone();assert indexed['version']==2 and indexed['climb_pda'] is None and indexed['vault_id'] is None
    return {'evidence_class':'local HTTP routes with SQL transport; actual indexer SELECT, no indexer HTTP server',
            'climbs':[result[0]['name'],'Lafayette Road'],'detail_http':200,'predecessor_http':200,'leaderboard_http':200,
            'version':2,'new_board_entries':0,'indexer_registry_version':2,'chain_binding':None}


def local_digests(connection):
    """Test oracle only: hashes of synthetic local data, never table copies."""
    with connection.cursor() as cursor:
        publication.configure(cursor)
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        names = [r[0] for r in cursor.fetchall()]
        result = {name:publication.row_digest(cursor,sql.SQL('SELECT * FROM {}').format(sql.Identifier('public',name)).as_string(cursor)) for name in names}
    connection.rollback()
    return result


def insert_pattern(connection, registry_id, ride_id):
    pattern = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO public.patterns_climb(id,activity_id,wallet,vert_m,time_s,match_trace) VALUES(%s,%s,'PRIVATE-RIDER-CANARY',10,100,%s)",
                       (pattern,ride_id,Json({'registry_id':registry_id,'private_evidence':'PRIVATE-TRACE-CANARY'})))
    return pattern


def insert_scope(connection, canon_id):
    identity = 'LOCAL-' + str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO public.stage1_keeper_scopes(id,program,city,hill,mint,canon_id,launch,next_week) VALUES(%s,'LOCAL-PROGRAM','LOCAL-CITY',%s,'LOCAL-MINT',%s,0,0)",
                       (identity,identity,canon_id))
    return identity


def create_publisher_role(connection, dsn):
    from psycopg2.extensions import make_dsn
    with connection.cursor() as cursor:
        cursor.execute('CREATE ROLE local_canon_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS')
        cursor.execute('GRANT USAGE ON SCHEMA public,extensions TO local_canon_publisher')
        for name in ('canon_climbs','canon_corridor_cells',*publication.REFERENCE_TABLES):
            cursor.execute(sql.SQL('GRANT SELECT ON {} TO local_canon_publisher').format(sql.Identifier('public',name)))
        cursor.execute('GRANT INSERT,UPDATE,DELETE ON public.canon_climbs,public.canon_corridor_cells TO local_canon_publisher')
    connection.commit()
    result = make_dsn(dsn,user='local_canon_publisher')
    with closing(psycopg2.connect(result)) as restricted:
        with restricted.cursor() as cursor:
            cursor.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
            assert cursor.fetchone() == (False,True)
            cursor.execute("SELECT has_table_privilege(current_user,'public.users','SELECT'),has_table_privilege(current_user,'public.strava_connections','SELECT')")
            assert cursor.fetchone() == (False,False)
    return result


def prepare_runtime(root, name):
    runtime = root/name; runtime.mkdir()
    (runtime/'app').symlink_to(BACKEND/'app',target_is_directory=True)
    # Like the API image, this directory has app/, no tools/, scripts/, history/.
    shutil.copyfile(publication.SUCCESSORS,runtime/'SUCCESSORS.json')
    shutil.copyfile(publication.PREDECESSORS,runtime/'COMPILER-BEFORE.json')
    return runtime


def rehearse(args):
    root=args.archive_root;root.mkdir(mode=0o700,parents=False,exist_ok=False)
    try:
        return rehearse_owned(args,root)
    finally:
        # Only the directory this invocation exclusively created, not inputs.
        shutil.rmtree(root)


def rehearse_owned(args,root):
    rows=publication.load_successors();binaries=postgres_bin()
    sql_dir=root/'sql';shutil.copytree(args.sql_dir,sql_dir)
    guard=BACKEND/'sql'/publication.GUARD_MIGRATION
    mirror=BACKEND/'supabase/migrations/20261021090000_179_canon_reference_guards.sql'
    assert guard.read_bytes()==mirror.read_bytes(), 'Canonical 179 and deployment mirror differ'
    # First prove the missing-reference bug against unchanged main, then apply
    # the new canonical migration through the actual runner on the same DB.
    if (sql_dir/guard.name).exists(): (sql_dir/guard.name).unlink()
    schema=args.schema_file.read_text();ledger=json.loads(args.ledger_file.read_text())['rows']
    with cluster(binaries) as (admin_dsn,env):
        dsn,baseline=restore(admin_dsn,'canon_successors_rehearsal',schema,ledger,binaries,env)
        migration_output=apply_stack(dsn,sql_dir,env)
        with closing(psycopg2.connect(dsn)) as admin:
            seed_result,user,ride=seed(admin,args.registry_snapshot,args.corridor_cells,sql_dir)
            dangling=str(uuid4())
            insert_pattern(admin,dangling,ride)
            admin.rollback()  # This should fail before the guard; it did not.
        shutil.copyfile(guard,sql_dir/guard.name)
        migration_output += apply_stack(dsn,sql_dir,env)
        invariants=run([sys.executable,'scripts/check_schema_invariants.py'],env={**env,'DATABASE_URL':dsn})
        with closing(psycopg2.connect(dsn)) as admin:
            try: insert_pattern(admin,dangling,ride)
            except psycopg2.errors.ForeignKeyViolation: admin.rollback()
            else: raise AssertionError('Dangling pattern still accepted after '+publication.GUARD_MIGRATION)
            applied=ledger_rows(admin);migrations=discover_migrations(sql_dir)
            assert_checksums_match({r['filename']:r['checksum'] for r in applied},migrations)
            assert {m.filename for m in migrations} <= {r['filename'] for r in applied}
            role_dsn=create_publisher_role(admin,dsn)
        runtime=prepare_runtime(root,'api-runtime');archives=root/'archives';archives.mkdir(mode=0o700)
        worker_env={**rehearsal_environment(),'DATABASE_URL':role_dsn}
        source=(BACKEND/'scripts/publish_canon_successors.py').read_text()
        def command(action, archive=None, receipt=None, expected_error=None):
            command_args=[sys.executable,'-',action,'--local-rehearsal','--successors',str(runtime/'SUCCESSORS.json'),
                          '--predecessors',str(runtime/'COMPILER-BEFORE.json')]
            if archive: command_args += ['--archive',str(archive)]
            if receipt: command_args += ['--receipt',str(receipt)]
            if action in ('publish','rollback'): command_args += ['--execute','--confirm-successors-sha256',publication.SUCCESSORS_SHA256]
            if action=='publish': command_args += ['--ratified-by','PRIVATE-APPROVER-CANARY','--ratified-at','2026-10-21T01:00:00Z',
                                                  '--approval-reference','PRIVATE-APPROVAL-REFERENCE-CANARY']
            result=subprocess.run(command_args,input=source,text=True,capture_output=True,cwd=runtime,env=worker_env,timeout=60)
            if expected_error:
                assert result.returncode != 0 and expected_error in result.stderr,result.stderr[-2000:]
                return
            if result.returncode: raise RuntimeError(result.stderr[-3500:])
            return json.loads(result.stdout)
        def archive_and_publish(number):
            directory=archives/str(number);directory.mkdir(mode=0o700)
            started=time.monotonic();archive=command('archive');archive_seconds=time.monotonic()-started
            path=directory/'before.json';publication.write_json(path,archive)
            receipt=command('publish',path);receipt_path=directory/'published.json';publication.write_json(receipt_path,receipt)
            assert 'PRIVATE-' not in path.read_text() + receipt_path.read_text()
            publication.validate_archive(archive,rows)
            return path,receipt_path,archive,receipt,archive_seconds
        assert command('plan')['count']==16
        checked=command('check')
        assert len(checked['predecessors'])==16 and all(isinstance(r['updated_at'],str) for r in checked['predecessors'])
        assert checked['census']=={'malformed_pattern_registry_ids':0,'non_ratified_cell_rows':0}
        with closing(psycopg2.connect(dsn)) as admin:
            initial=local_digests(admin)
            # These are uncommitted synthetic adversarial states; the real
            # preflight sees each, then rollback removes it without residue.
            def refused(statement,parameters,reason):
                try:
                    with admin.cursor() as cursor:
                        cursor.execute(statement,parameters)
                        try: publication.preflight(cursor,rows)
                        except RuntimeError as exc: assert reason in str(exc),str(exc)
                        else: raise AssertionError('Preflight accepted '+reason)
                finally: admin.rollback()
            refused('ALTER TABLE public.climb_efforts RENAME TO local_hidden_climb_efforts',(),'climb_efforts')
            refused("UPDATE public.patterns_climb SET match_trace=jsonb_set(match_trace,'{registry_id}',%s)",
                    (Json('PRIVATE-MALFORMED-CANARY'),), 'Malformed patterns_climb registry_id values: 3; expected 0')
            refused("UPDATE public.canon_climbs SET status='candidate' WHERE id=%s",
                    (rows[0]['supersedes_climb_id'],), 'Cells owned by non-ratified registry rows:')
            # A keeper repeats this INSERT even for a retained family with no
            # active revision. No version-specific trigger belongs on scopes.
            scope=insert_scope(admin,rows[0]['canon_id'])
            with admin.cursor() as cursor:
                cursor.execute("UPDATE public.canon_climbs SET status='retired',retired_at=now() WHERE id=%s", (rows[0]['supersedes_climb_id'],))
                cursor.execute('''INSERT INTO public.stage1_keeper_scopes(id,program,city,hill,mint,canon_id,launch,next_week)
                    SELECT id,program,city,hill,mint,canon_id,launch,next_week FROM public.stage1_keeper_scopes
                    WHERE id=%s ON CONFLICT DO NOTHING''', (scope,))
                cursor.execute("SELECT count(*) FROM pg_trigger WHERE tgname='br_stage1_canon_reference'")
                assert cursor.fetchone()==(0,)
                cursor.execute("SELECT to_regprocedure('public.br_lock_stage1_canon_reference()')")
                assert cursor.fetchone()==(None,)
            admin.rollback()
            clone=str(uuid4());family=str(uuid4())
            refused('''INSERT INTO public.canon_climbs SELECT (jsonb_populate_record(NULL::public.canon_climbs,
                to_jsonb(c)||jsonb_build_object('id',%s::text,'canon_id',%s::text,'candidate_fingerprint',%s::text))).*
                FROM public.canon_climbs c WHERE id=%s::uuid''',
                (clone,family,rows[0]['publish_payload']['climb']['candidate_fingerprint'],rows[0]['supersedes_climb_id']), 'successor fingerprint')
            refused('''INSERT INTO public.canon_vault_activations(canon_climb_id,creator_wallet,payment_method,client_request_id,
                canon_commitment_hex,commitment_hash_hex,climb_pda,vault_id,vault_pda,vault_activation_pda,
                prepared_blockhash,last_valid_block_height)
                VALUES(%s,'LOCAL-SYNTHETIC','dung',%s,%s,%s,'LOCAL-CLIMB',888888,'LOCAL-VAULT',
                'LOCAL-ACTIVATION','LOCAL-BLOCKHASH',1)''',
                (rows[0]['supersedes_climb_id'],str(uuid4()),'09'*64,'0a'*32), 'canon_vault_activations')
            refused('''INSERT INTO public.indexed_vaults(id,signature_hex,signature_hash_hex,minter,name,vert_m,distance_m,avg_gradient_pct,pda,created_at,canon_climb_id)
                VALUES(888888,%s,%s,'LOCAL-SYNTHETIC','LOCAL',10,100,10,'LOCAL-VAULT',now(),%s)''',
                ('07'*64,'08'*32,rows[0]['supersedes_climb_id']), 'indexed_vaults')
        archive_path,receipt_path,archive,receipt,archive_seconds=archive_and_publish(1)
        verified=command('verify',archive_path)
        assert len(verified['successors'])==16 and verified['open_data']['versions_projected']==32
        command('publish',archive_path,expected_error='Cells owned by non-ratified registry rows:')
        # The application/indexer read more tables than the bounded publisher
        # needs. Keep those read-only HTTP probes off the publisher role.
        api=http_probe(dsn,receipt['successors'])
        with closing(psycopg2.connect(role_dsn)) as connection:
            public_rows,cells,commitments=read_registry(connection)
            release=build_release(public_rows,cells,root/'release',published_at='2026-10-21T00:00:00Z')
            released=[json.loads(line) for line in (release/'climbs.jsonl').read_text().splitlines()]
            assert len(released)==73 and sum(r['canon_version']==2 for r in released)==16
            assert 'PRIVATE-' not in (release/'climbs.jsonl').read_text()
            by_id={r['registry_id']:r for r in released}
            for row in released:
                if row['canon_version']!=2: continue
                previous=by_id[row['supersedes_climb_id']]
                assert row['provenance']['launch_ratification']['decision_id'] != previous['provenance']['launch_ratification']['decision_id']
        # Unrelated normal writes and an in-flight predecessor match must not
        # disable rollback. Keep the writes and verify their bytes afterward.
        with closing(psycopg2.connect(dsn)) as admin:
            with admin.cursor() as cursor:
                cursor.execute("SELECT acquire_background_job_lock('LOCAL-NEW-JOB','PRIVATE-LEASE-CANARY',900)")
                assert cursor.fetchone()[0]
                other_ride=str(uuid4());cursor.execute('INSERT INTO public.rides(id,user_id) VALUES(%s,%s)',(other_ride,user))
            insert_pattern(admin,publication.SHAWMONT_ID,other_ride)
            inflight=insert_pattern(admin,rows[0]['supersedes_climb_id'],ride)
            admin.commit();with_unrelated=local_digests(admin)
        # A new interpreter and image-like directory simulate an API restart;
        # host archive/receipt are the only operation state required to resume.
        runtime=prepare_runtime(root,'api-runtime-after-restart')
        undone=command('rollback',archive_path,receipt_path)
        assert undone['scoped_rows_restored'];assert command('check')['census']==checked['census']
        with closing(psycopg2.connect(dsn)) as admin:
            restored=local_digests(admin)
            for table in restored:
                expected=initial[table] if table in ('canon_climbs','canon_corridor_cells') else with_unrelated[table]
                assert restored[table]==expected,table
        # A committed new match must refuse rollback with its real selector.
        archive2_path,receipt2_path,archive2,receipt2,_=archive_and_publish(2)
        new=receipt2['successors'][0]
        with closing(psycopg2.connect(dsn)) as admin:
            pattern=insert_pattern(admin,new['id'].replace('-',''),ride);admin.commit()
        command('rollback',archive2_path,receipt2_path,expected_error='successor referenced by patterns_climb')
        with closing(psycopg2.connect(dsn)) as admin:
            with admin.cursor() as cursor: cursor.execute('DELETE FROM public.patterns_climb WHERE id=%s',(pattern,))
            admin.commit();scope=insert_scope(admin,new['canon_id']);admin.commit()
        command('rollback',archive2_path,receipt2_path,expected_error='successor referenced by stage1_keeper_scopes')
        with closing(psycopg2.connect(dsn)) as admin:
            with admin.cursor() as cursor: cursor.execute('DELETE FROM public.stage1_keeper_scopes WHERE id=%s',(scope,))
            admin.commit()
        # Opposite race order: rollback holds row locks; queued soft-reference
        # inserts must fail when the successor disappears, never orphan data.
        def queued_pattern_refusal(archived, recorded):
            with closing(psycopg2.connect(role_dsn)) as writer, closing(psycopg2.connect(dsn)) as reader:
                with writer.cursor() as cursor: publication.lock_rows(cursor,[r['id'] for r in recorded['successors']]+[r['supersedes_climb_id'] for r in rows])
                queued_pid=reader.get_backend_pid()
                def queued():
                    try:
                        insert_pattern(reader,recorded['successors'][0]['id'],ride)
                        reader.commit();return 'unexpected commit'
                    except psycopg2.errors.ForeignKeyViolation:
                        reader.rollback();return 'missing reference refused'
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(queued);deadline=time.monotonic()+3
                    with closing(psycopg2.connect(dsn)) as observer:
                        while True:
                            with observer.cursor() as cursor:
                                cursor.execute('SELECT cardinality(pg_blocking_pids(%s))',(queued_pid,));blocked=cursor.fetchone()[0]
                            if blocked: break
                            assert time.monotonic()<deadline and not future.done()
                            time.sleep(.02)
                    publication.rollback(writer,rows,archived,recorded)
                    assert future.result(timeout=5)=='missing reference refused'
        queued_pattern_refusal(archive2,receipt2)
        with closing(psycopg2.connect(dsn)) as admin: before_failures=local_digests(admin)
        # Bound lock waiting on one predecessor row, never a table lock.
        payloads=publication.approved_payloads(rows,publication.SUCCESSORS_SHA256,'LOCAL','2026-10-21T01:00:00Z')
        with closing(psycopg2.connect(dsn)) as blocker, closing(psycopg2.connect(role_dsn)) as writer:
            with blocker.cursor() as cursor: publication.lock_rows(cursor,[rows[0]['supersedes_climb_id']])
            started=time.monotonic()
            try: publication.publish(writer,rows,payloads,archive2,'local')
            except psycopg2.errors.LockNotAvailable: lock_wait=time.monotonic()-started
            else: raise AssertionError('Row lock timeout did not fire')
            assert 4.5<lock_wait<8;blocker.rollback()
        # A known lock timeout aborts before commit. The unchanged original
        # archive is reusable; the normal preflight/staleness checks still run.
        retry_receipt=command('publish',archive2_path)
        retry_path=receipt2_path.with_name('retry-published.json');publication.write_json(retry_path,retry_receipt)
        command('rollback',archive2_path,retry_path)
        original=publication.publish_canon_climb_payload_to_db;counter=0
        def fail_eighth(*a,**kw):
            nonlocal counter
            counter+=1
            if counter==8: raise RuntimeError('injected eighth-row failure')
            return original(*a,**kw)
        publication.publish_canon_climb_payload_to_db=fail_eighth
        try:
            with closing(psycopg2.connect(role_dsn)) as writer:
                try: publication.publish(writer,rows,payloads,archive2,'local')
                except RuntimeError as exc: assert 'eighth-row' in str(exc),str(exc)
                else: raise AssertionError('Injected failure not reached')
        finally: publication.publish_canon_climb_payload_to_db=original
        with closing(psycopg2.connect(dsn)) as admin: assert local_digests(admin)==before_failures
        return {'evidence_class':'local PostgreSQL; retained geography/cells, synthetic riders and chain binding',
            'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.schema_file,args.ledger_file,args.registry_snapshot,args.corridor_cells,guard,mirror)},
            'baseline_ledger_rows':len(baseline),'applied_ledger_rows':len(applied),'latest_canonical_migration':migrations[-1].filename,
            'migration_output':migration_output,'schema_invariants':invariants,'seed':seed_result,
            'role':{'superuser':False,'bypassrls':True,'read_tables':['canon_climbs','canon_corridor_cells',*publication.REFERENCE_TABLES],
                    'write_tables':['canon_climbs','canon_corridor_cells'],'users_and_tokens_readable':False},
            'archive':{'tables':{k:len(v) for k,v in archive['tables'].items()},'columns':publication.ARCHIVE_COLUMNS,
                       'bytes':archive_path.stat().st_size,'seconds':archive_seconds,'private_canaries_absent':True},
            'publication_seconds':receipt['seconds'],'rollback_seconds':undone['seconds'],'locks':receipt['locks'],
            'cli':['plan','check','archive','publish','verify','rollback','check after rollback'], 'preflight_census':checked['census'],
            'transport':'stdin in image-like app-only working directory; fresh interpreter after simulated restart',
            'restoration':'exact predecessor and cell digests; unrelated writes retained',
            'checks':{'missing_efforts':'refused','existing_successor_fingerprint':'refused','target_vault':'refused','target_activation':'refused',
                      'repeated_publish':'refused','matched_successor':'rollback refused','stage1_scope':'rollback refused',
                      'queued_pattern_after_rollback':'missing reference refused','keeper_repeat_after_retirement':'succeeds; no scope trigger/function',
                      'malformed_pattern_registry_id':'clear count refusal','non_ratified_cell_rows':'clear count refusal',
                      'legacy_pattern_update':'allowed; check diagnoses malformed value','publish_lock_timeout_retry':'same archive; publish and rollback succeed',
                      'inflight_predecessor_match':'retained','background_job_and_other_ride':'retained across rollback',
                      'eighth_row_failure':'all local table hashes unchanged','guard_red_to_green':'dangling trace accepted before 179, refused after'},
            'open_data':{'release_rows':len(released),'successors':16,'private_canaries_absent':True,'successor_decision_references':'16 own decisions'},'api':api,'row_lock_timeout_seconds':lock_wait,
            'cleanup':'owned cluster stopped; scratch data deleted after return'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('schema-file','ledger-file','registry-snapshot','corridor-cells','archive-root','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--sql-dir',type=Path,default=BACKEND/'sql')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not args.worker:
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--worker'],env=rehearsal_environment(),check=False)
        raise SystemExit(result.returncode)
    env=rehearsal_environment();os.environ.clear();os.environ.update(env)
    result=rehearse(args);publication.write_json(args.output,result)
    print(publication.json_text({k:v for k,v in result.items() if k not in ('locks','source_sha256','role')}))


if __name__=='__main__':main()
