#!/usr/bin/env python3
"""Online publication of the reviewed 16 successors; plan is the default.

Supports python - in the running API container. The operator retains the
public-only archive and receipts on the droplet host, never a laptop DSN.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import h3
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

BACKEND = Path(__file__).resolve().parents[1] if __file__ != '<stdin>' else Path.cwd()
sys.path.insert(0, str(BACKEND))
from app.services.canon_climb_publisher import DeferredCommitConnection, _validated_publish_parts, publish_canon_climb_payload_to_db
from app.services.canon_provenance import project_provenance
from app.services.geographic_data import inherited_source_provenance

SUCCESSORS = BACKEND.parent / 'history/codex-reports-2026-10-20/gate-rule/SUCCESSORS.json'
PREDECESSORS = SUCCESSORS.with_name('COMPILER-BEFORE.json')
SUCCESSORS_SHA256 = '43a719dbadb489cb5dfa49903936e944f27df7dc4f72dc708e1dcb3be50e34f6'
BEFORE_SHA256 = 'a48a212aa7935af9f0f7ef03ddbe6a53f6dbefcc86d4ed20d536916664ddd92b'
EXPECTED_PROJECT_REF = 'qzkqjevawthyboymqrle'
SHAWMONT_ID = '281af3df-fdd7-4b7d-92be-910012280575'
ARCHIVE_FORMAT = 'canon-successors-public-geometry-2'
GEOMETRIES = ('centerline_geom', 'corridor_geom', 'gate_start_line', 'gate_end_line')
# No opaque provenance, approver identity, rider identifier, GPS, or credential.
ARCHIVE_COLUMNS = {
    'canon_climbs': tuple('id canon_id version status retired_at updated_at candidate_fingerprint '
                         'supersedes_climb_id record_continuity_policy canonical_profile length_m '
                         'vert_m avg_gradient_pct'.split()) + GEOMETRIES,
    'canon_corridor_cells': ('canon_climb_id', 'h3_resolution', 'tile_id', 'coverage_role'),
}
REFERENCE_TABLES = ('climb_efforts', 'patterns_climb', 'indexed_climbs', 'indexed_vaults',
    'canon_vault_activations', 'stage1_keeper_scopes', 'stage1_keeper_jobs',
    'stage1_keeper_boundaries', 'vault_completions', 'indexed_completions',
    'indexed_climb_completion_flows', 'indexed_climb_completion_receipts',
    'ride_economic_completion_steps', 'reward_threshold_release_steps')
GUARD_MIGRATION = '179_canon_reference_guards.sql'
GUARDS = {'patterns_climb': 'br_pattern_canon_reference'}


def json_text(value):
    def default(item):
        if isinstance(item, datetime): return item.isoformat()
        if isinstance(item, Decimal): return float(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value, default=default, sort_keys=True, indent=2, allow_nan=False) + '\n'


def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def emit_result(result, *, committed=False):
    try:
        sys.stdout.write(json_text(result)); sys.stdout.flush()
    except OSError as exc:
        if committed: raise RuntimeError('DB COMMITTED; receipt output failed; verify and recover the receipt, do not retry publish') from exc
        raise


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(json_text(value)); handle.flush(); os.fsync(handle.fileno())


def load_successors(path=SUCCESSORS):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != SUCCESSORS_SHA256: raise ValueError('Successor digest differs from the reviewed 16-climb pack')
    rows = json.loads(data)
    if len(rows) != 16 or len({r['canon_id'] for r in rows}) != 16: raise ValueError('Expected 16 distinct canon identities')
    for row in rows:
        if (row['version'] != 2 or row['explicit_successor'] is not True
                or row['record_continuity_policy'] != 'new_record_board' or row['supersedes_climb_id'] == SHAWMONT_ID):
            raise ValueError('Unexpected successor scope')
        project_provenance(row['publish_payload']['climb']['provenance'])
    return rows


def approved_payloads(rows, confirmation, actor, at):
    if confirmation != SUCCESSORS_SHA256 or not actor.strip(): raise ValueError('Exact successor digest and actual ratification actor required')
    stamp = datetime.fromisoformat(at.replace('Z', '+00:00'))
    if stamp.tzinfo is None: raise ValueError('Ratification time requires an explicit timezone')
    payloads = []
    for row in rows:
        payload = deepcopy(row['publish_payload']); payload['compiler_run_mode'] = 'applied'
        payload['climb'].update(ratified_by=actor, ratified_at=stamp.isoformat())
        boundary = payload['climb']['provenance'].get('ratified_boundary', {})
        if 'publication_status' in boundary: boundary['publication_status'] = 'applied'
        _validated_publish_parts(payload)
        for cell in payload['corridor_cells']:
            if cell['h3_resolution'] != 10 or not h3.is_valid_cell(cell['tile_id']) or h3.get_resolution(cell['tile_id']) != 10:
                raise ValueError('Every corridor cell must be a valid H3 resolution 10 cell')
        payloads.append(payload)
    return payloads


def configure(cursor):
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute("SET LOCAL statement_timeout = '120s'")
    cursor.execute("SET LOCAL timezone = 'UTC'")


def require_schema(cursor):
    for table in (*ARCHIVE_COLUMNS, *REFERENCE_TABLES):
        cursor.execute('SELECT to_regclass(%s)', ('public.' + table,))
        if cursor.fetchone()[0] is None: raise RuntimeError(f'Required table missing: {table}; deploy canonical migrations first')
    for table, trigger in GUARDS.items():
        cursor.execute('''SELECT count(*) FROM pg_trigger WHERE tgrelid=%s::regclass
            AND tgname=%s AND tgtype=7 AND tgenabled IN ('O','A') AND NOT tgisinternal''', ('public.'+table, trigger))
        if cursor.fetchone()[0] != 1: raise RuntimeError(f'Required insert-only reference guard missing: {trigger}; deploy {GUARD_MIGRATION} first')


def lock_rows(cursor, ids):
    cursor.execute('SELECT id FROM public.canon_climbs WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE', (ids,))
    if len(cursor.fetchall()) != len(set(ids)): raise RuntimeError('Publication row disappeared')


def row_digest(cursor, query, params=()):
    # Hash inside PostgreSQL. No rider row or identifying column leaves the DB.
    cursor.execute('''SELECT count(*), encode(sha256(convert_to(COALESCE(string_agg(h, '' ORDER BY h),''),'UTF8')),'hex')
        FROM (SELECT encode(sha256(convert_to(t::text,'UTF8')),'hex') h FROM (''' + query + ') t) hashed', params)
    count, sha = cursor.fetchone()
    return {'rows': count, 'sha256': sha}


def canon_digest(cursor, ids, *, stable=False):
    query = "SELECT to_jsonb(c) - ARRAY['status','retired_at','updated_at'] AS row FROM public.canon_climbs c" if stable else 'SELECT * FROM public.canon_climbs'
    return row_digest(cursor, query + ' WHERE id=ANY(%s::uuid[])', (ids,))


def verify_pattern_registry_ids(cursor):
    cursor.execute("""SELECT count(*) FROM public.patterns_climb
        WHERE match_trace->>'registry_id' IS NOT NULL
        AND NOT pg_input_is_valid(match_trace->>'registry_id', 'uuid')""")
    count = cursor.fetchone()[0]
    if count: raise RuntimeError(f'Malformed patterns_climb registry_id values: {count}; expected 0')
    return count


def preflight_integrity_counts(cursor):
    malformed = verify_pattern_registry_ids(cursor)
    cursor.execute("""SELECT count(*) FROM public.canon_corridor_cells cells
        JOIN public.canon_climbs c ON c.id=cells.canon_climb_id
        WHERE c.status IS DISTINCT FROM 'ratified'""")
    cells = cursor.fetchone()[0]
    if cells: raise RuntimeError(f'Cells owned by non-ratified registry rows: {cells}; expected 0')
    return {'malformed_pattern_registry_ids': malformed, 'non_ratified_cell_rows': cells}


def reference_digests(cursor, ids, canon_ids):
    verify_pattern_registry_ids(cursor)
    queries = {
        'climb_efforts': ('SELECT * FROM public.climb_efforts WHERE climb_id=ANY(%s::uuid[])', (ids,)),
        # UUID comparison matches the trigger/FK semantics, including valid
        # non-hyphenated spellings. Malformed legacy values fail closed.
        # CASE protects the cast even if a legacy UPDATE races the integrity check.
        'patterns_climb': ("""SELECT * FROM public.patterns_climb WHERE
            CASE WHEN pg_input_is_valid(match_trace->>'registry_id', 'uuid')
                 THEN (match_trace->>'registry_id')::uuid END=ANY(%s::uuid[])""", (ids,)),
    }
    for table in ('indexed_climbs','indexed_vaults','canon_vault_activations'):
        queries[table] = (f'SELECT * FROM public.{table} WHERE canon_climb_id=ANY(%s::uuid[])', (ids,))
    queries['stage1_keeper_scopes'] = ('SELECT * FROM public.stage1_keeper_scopes WHERE canon_id=ANY(%s::uuid[])', (canon_ids,))
    for table in ('stage1_keeper_jobs','stage1_keeper_boundaries'):
        queries[table] = (f'SELECT t.* FROM public.{table} t JOIN public.stage1_keeper_scopes s ON s.id=t.scope_id WHERE s.canon_id=ANY(%s::uuid[])', (canon_ids,))
    for table, condition in [('vault_completions','t.vault_signature=v.signature_hex'),
                             ('indexed_completions','t.vault_id=v.id'),
                             ('indexed_climb_completion_flows','t.vault_id=v.id'),
                             ('indexed_climb_completion_receipts','t.vault_pda=v.pda')]:
        queries[table] = (f'SELECT t.* FROM public.{table} t JOIN public.indexed_vaults v ON {condition} WHERE v.canon_climb_id=ANY(%s::uuid[])', (ids,))
    for table in ('ride_economic_completion_steps','reward_threshold_release_steps'):
        queries[table] = (f'''SELECT t.* FROM public.{table} t WHERE EXISTS
            (SELECT FROM public.patterns_climb p WHERE p.id=t.pattern_id AND
                CASE WHEN pg_input_is_valid(p.match_trace->>'registry_id', 'uuid')
                     THEN (p.match_trace->>'registry_id')::uuid END=ANY(%s::uuid[]))
            OR EXISTS (SELECT FROM public.indexed_vaults v WHERE (v.id=t.vault_id OR v.signature_hex=t.vault_signature)
                       AND v.canon_climb_id=ANY(%s::uuid[]))''', (ids, ids))
    return {name: row_digest(cursor, *queries[name]) for name in REFERENCE_TABLES}


def scoped_digests(cursor, rows):
    ids = [r['supersedes_climb_id'] for r in rows]
    return {'predecessors': canon_digest(cursor, ids), 'predecessors_stable': canon_digest(cursor, ids, stable=True),
            'cells': row_digest(cursor, 'SELECT * FROM public.canon_corridor_cells WHERE canon_climb_id=ANY(%s::uuid[])', (ids,)),
            'shawmont': canon_digest(cursor, [SHAWMONT_ID]),
            'references': reference_digests(cursor, ids, [r['canon_id'] for r in rows])}


def public_tables(cursor, ids):
    result = {}
    for table, columns in ARCHIVE_COLUMNS.items():
        expressions = [sql.SQL("encode(ST_AsEWKB({}),'hex') AS {}").format(sql.Identifier(c), sql.Identifier(c))
                       if c in GEOMETRIES else sql.Identifier(c) for c in columns]
        key = 'id' if table == 'canon_climbs' else 'canon_climb_id'
        cursor.execute(sql.SQL('SELECT {} FROM {} WHERE {}=ANY(%s::uuid[]) ORDER BY {}').format(
            sql.SQL(',').join(expressions), sql.Identifier('public', table), sql.Identifier(key),
            sql.SQL(',').join(map(sql.Identifier, columns[:1] if table=='canon_climbs' else columns))), (ids,))
        result[table] = [dict(zip(columns, row)) for row in cursor.fetchall()]
    result = json.loads(json_text(result)); validate_archive_tables(result)
    return result


def validate_archive_tables(tables):
    if set(tables) != set(ARCHIVE_COLUMNS): raise ValueError('Outside archive allowlist: table')
    for table, rows in tables.items():
        for row in rows:
            if set(row) != set(ARCHIVE_COLUMNS[table]): raise ValueError('Outside archive allowlist: column')
            if table == 'canon_climbs' and any(set(p) != {'dist_m','elev_m'} or any(type(v) not in (float,int) for v in p.values()) for p in row['canonical_profile']): raise ValueError('Outside archive allowlist: profile field')


def validate_archive(archive, rows):
    if set(archive) != {'format','successors_sha256','archived_at','tables','digests','sha256'}: raise ValueError('Outside archive allowlist: envelope')
    if archive['format'] != ARCHIVE_FORMAT or archive['successors_sha256'] != SUCCESSORS_SHA256: raise ValueError('Wrong archive format or successor pack')
    if digest({k:v for k,v in archive.items() if k != 'sha256'}) != archive['sha256']: raise ValueError('Archive integrity failed')
    validate_archive_tables(archive['tables'])
    ids = {r['supersedes_climb_id'] for r in rows}; old = archive['tables']['canon_climbs']
    if len(old) != 16 or {r['id'] for r in old} != ids or any(r['version'] != 1 or r['status'] != 'ratified' for r in old): raise ValueError('Archive predecessor scope differs')
    if any(c['canon_climb_id'] not in ids for c in archive['tables']['canon_corridor_cells']): raise ValueError('Archive corridor scope differs')
    if set(archive['digests']) != {'predecessors','predecessors_stable','cells','shawmont','references'} or set(archive['digests']['references']) != set(REFERENCE_TABLES): raise ValueError('Outside archive allowlist: digest scope')
    values = [v for k,v in archive['digests'].items() if k != 'references'] + list(archive['digests']['references'].values())
    for value in values:
        if set(value) != {'rows','sha256'} or type(value['rows']) is not int or len(value['sha256']) != 64: raise ValueError('Outside archive allowlist: digest fields')


def preflight(cursor, rows, baseline_path=PREDECESSORS):
    require_schema(cursor)
    integrity_counts = preflight_integrity_counts(cursor)
    baseline_bytes = Path(baseline_path).read_bytes()
    if hashlib.sha256(baseline_bytes).hexdigest() != BEFORE_SHA256: raise ValueError('Reviewed predecessor digest drifted')
    baseline = {r['candidate_fingerprint']: r for r in json.loads(baseline_bytes)['candidates']}
    ids = [r['supersedes_climb_id'] for r in rows]
    cursor.execute('SELECT id::text, canon_id::text, version, status, candidate_fingerprint, updated_at FROM public.canon_climbs WHERE id=ANY(%s::uuid[]) ORDER BY id', (ids,))
    existing = {r[0]: r for r in cursor.fetchall()}
    if len(existing) != 16: raise RuntimeError('Missing predecessor rows')
    for row in rows:
        old = existing[row['supersedes_climb_id']]
        if old[1:4] != (row['canon_id'],1,'ratified') or old[4] not in row['publish_payload']['climb']['legacy_candidate_fingerprints']: raise RuntimeError('Predecessor lineage/status drift; do not republish')
        expected = baseline[old[4]]
        cursor.execute('''SELECT length_m=%s,vert_m=%s,avg_gradient_pct=%s,
            ST_AsEWKB(gate_start_line)=ST_AsEWKB(ST_GeomFromText(%s,4326)),
            ST_AsEWKB(gate_end_line)=ST_AsEWKB(ST_GeomFromText(%s,4326)) FROM public.canon_climbs WHERE id=%s::uuid''',
            (expected['length_m'],expected['vert_m'],expected['avg_gradient_pct'],expected['gate_start_wkt'],expected['gate_end_wkt'],old[0]))
        if not all(cursor.fetchone()): raise RuntimeError('Predecessor metrics/gates differ from the reviewed change table')
    cursor.execute('SELECT count(*) FROM public.canon_climbs WHERE canon_id=ANY(%s::uuid[])', ([r['canon_id'] for r in rows],))
    if cursor.fetchone()[0] != 16: raise RuntimeError('An unexpected version already exists')
    cursor.execute('SELECT count(*) FROM public.canon_climbs WHERE candidate_fingerprint=ANY(%s::text[])', ([r['publish_payload']['climb']['candidate_fingerprint'] for r in rows],))
    if cursor.fetchone()[0]: raise RuntimeError('A successor fingerprint already exists')
    refs = reference_digests(cursor, ids, [r['canon_id'] for r in rows])
    for table in ('indexed_climbs','indexed_vaults','canon_vault_activations','stage1_keeper_scopes'):
        if refs[table]['rows']: raise RuntimeError(f'Target has {table} references; stop for fresh review')
    cursor.execute('SELECT canon_climb_id::text FROM public.indexed_climbs ORDER BY canon_climb_id')
    if [r[0] for r in cursor.fetchall()] != [SHAWMONT_ID]: raise RuntimeError('Expected Shawmont to be the only registered climb')
    cursor.execute('SELECT status,version FROM public.canon_climbs WHERE id=%s::uuid', (SHAWMONT_ID,))
    if cursor.fetchone() != ('ratified',1): raise RuntimeError('Shawmont state drift')
    return {'predecessors': [{'id': r[0], 'updated_at': r[5]} for r in existing.values()], 'census': integrity_counts}


def create_archive(connection, rows, baseline_path=PREDECESSORS):
    connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
    try:
        with connection.cursor() as cursor:
            configure(cursor); preflight(cursor, rows, baseline_path)
            archive = {'format':ARCHIVE_FORMAT, 'successors_sha256':SUCCESSORS_SHA256,
                       'archived_at':datetime.now(timezone.utc).isoformat(),
                       'tables':public_tables(cursor, [r['supersedes_climb_id'] for r in rows]), 'digests':scoped_digests(cursor, rows)}
        archive['sha256'] = digest(archive); validate_archive(archive, rows)
        return archive
    finally:
        connection.rollback()


def locks(cursor):
    cursor.execute('''SELECT DISTINCT c.relname,l.mode FROM pg_locks l JOIN pg_class c ON c.oid=l.relation
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE l.pid=pg_backend_pid()
        AND n.nspname='public' AND l.granted ORDER BY 1,2''')
    return [{'relation':r[0],'mode':r[1]} for r in cursor.fetchall()]


def open_data_projection(cursor, rows):
    cursor.execute('SELECT id::text,canon_id::text,version,provenance,supersedes_climb_id::text FROM public.canon_climbs WHERE canon_id=ANY(%s::uuid[])', ([r['canon_id'] for r in rows],))
    by_id = {r[0]:dict(zip(('id','canon_id','version','provenance','supersedes_climb_id'),r)) for r in cursor.fetchall()}
    for row in by_id.values():
        provenance = inherited_source_provenance(row, by_id)
        if not provenance.get('region') and provenance.get('launch_ratification',{}).get('candidate_manifest_sha256') == 'da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb': provenance['region'] = 'philadelphia'
        if not provenance.get('region'): raise RuntimeError('Missing inherited open-data attribution')
        project_provenance(provenance)
    return {'versions_projected':len(by_id), 'private_evidence_and_approver_omitted':True}


def verification_receipt(cursor, rows, archive):
    verified = verify(cursor, rows)
    if canon_digest(cursor,[SHAWMONT_ID]) != archive['digests']['shawmont']: raise RuntimeError('Shawmont changed since the scoped archive')
    return {'archive_sha256':archive['sha256'], 'successors_sha256':SUCCESSORS_SHA256,
            'successors':verified, 'successor_digest':canon_digest(cursor,[r['id'] for r in verified]), 'open_data':open_data_projection(cursor,rows)}


def publish(connection, rows, payloads, archive, approval_reference, baseline_path=PREDECESSORS):
    validate_archive(archive, rows)
    if not approval_reference.strip(): raise ValueError('Separate publication approval reference required')
    started = time.monotonic()
    try:
        with connection.cursor() as cursor:
            configure(cursor); lock_rows(cursor, [r['supersedes_climb_id'] for r in rows]); preflight(cursor, rows, baseline_path)
            before = scoped_digests(cursor, rows)
            for name in ('predecessors','cells','shawmont'):
                if before[name] != archive['digests'][name]: raise RuntimeError(f'Archive is stale: {name}; make a fresh archive')
            deferred = DeferredCommitConnection(connection)
            for payload in payloads:
                publish_canon_climb_payload_to_db(payload, connection_factory=lambda:deferred, explicit_successor=True, record_continuity_policy='new_record_board')
            receipt = verification_receipt(cursor, rows, archive); after = scoped_digests(cursor, rows)
            for name in ('predecessors_stable','cells','shawmont'):
                if before[name] != after[name]: raise RuntimeError(f'Publication changed protected {name}')
            receipt.update(reference_digests_before=before['references'], reference_digests_after=after['references'], approval_reference_sha256=hashlib.sha256(approval_reference.encode()).hexdigest(), locks=locks(cursor))
        connection.commit()
    except BaseException:
        connection.rollback(); raise
    return {**receipt, 'committed':True, 'seconds':time.monotonic()-started}


def rollback(connection, rows, archive, receipt):
    validate_archive(archive, rows)
    if receipt['archive_sha256'] != archive['sha256'] or receipt['successors_sha256'] != SUCCESSORS_SHA256: raise ValueError('Receipt does not belong to this scoped archive')
    started = time.monotonic()
    try:
        with connection.cursor() as cursor:
            configure(cursor); require_schema(cursor)
            ids = [r['id'] for r in receipt['successors']]
            if len(ids) != 16: raise ValueError('Receipt must name exactly 16 successor rows')
            lock_rows(cursor, ids + [r['supersedes_climb_id'] for r in rows])
            # Unrelated writes (including Shawmont metadata) do not disable
            # rollback. Only the exact target versions are restored/deleted.
            verified = verify(cursor, rows)
            actual = {'successors': verified, 'successor_digest': canon_digest(cursor, [r['id'] for r in verified])}
            if actual['successors'] != receipt['successors'] or actual['successor_digest'] != receipt['successor_digest']: raise RuntimeError('Successor rows changed; rollback refused')
            references = reference_digests(cursor, ids, [r['canon_id'] for r in rows])
            occupied = [name for name, value in references.items() if value['rows']]
            if occupied: raise RuntimeError('Rollback refused: successor referenced by ' + ', '.join(occupied))
            current = scoped_digests(cursor, rows)
            for name in ('predecessors_stable','cells'):
                if current[name] != archive['digests'][name]: raise RuntimeError(f'Predecessor {name} changed; rollback refused')
            cursor.execute('DELETE FROM public.canon_corridor_cells WHERE canon_climb_id=ANY(%s::uuid[])', (ids,))
            cursor.execute('DELETE FROM public.canon_climbs WHERE id=ANY(%s::uuid[])', (ids,))
            for row in archive['tables']['canon_climbs']:
                cursor.execute('UPDATE public.canon_climbs SET status=%s,retired_at=%s,updated_at=%s WHERE id=%s::uuid', (row['status'],row['retired_at'],row['updated_at'],row['id']))
            restored = scoped_digests(cursor,rows)
            for name in ('predecessors','cells'):
                if restored[name] != archive['digests'][name]: raise RuntimeError(f'Rollback did not exactly restore {name}')
            held = locks(cursor)
        connection.commit()
        return {'committed':True,'scoped_rows_restored':True,'seconds':time.monotonic()-started,'locks':held}
    except BaseException:
        connection.rollback(); raise


def connect_database(dsn, *, local_rehearsal=False):
    for key in list(os.environ):
        if key.startswith('PG'): del os.environ[key]
    if local_rehearsal:
        if os.environ.get('ENVIRONMENT') != 'test' or not parse_dsn(dsn).get('host','').startswith('/'): raise ValueError('Local rehearsal requires test environment and an owned Unix socket')
    elif EXPECTED_PROJECT_REF not in dsn: raise ValueError(f'DATABASE_URL does not identify expected project {EXPECTED_PROJECT_REF}')
    connection = psycopg2.connect(dsn, connect_timeout=10, application_name='canon-successors-6ewxw')
    if local_rehearsal:
        with connection.cursor() as cursor:
            cursor.execute('SELECT inet_server_addr()')
            if cursor.fetchone()[0] is not None: connection.close(); raise ValueError('Local rehearsal cannot use TCP')
        connection.rollback()
    return connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','check','archive','publish','verify','rollback'], nargs='?', default='plan')
    parser.add_argument('--successors', type=Path, default=SUCCESSORS); parser.add_argument('--predecessors', type=Path, default=PREDECESSORS)
    parser.add_argument('--archive', type=Path); parser.add_argument('--receipt', type=Path)
    parser.add_argument('--execute', action='store_true'); parser.add_argument('--confirm-successors-sha256', default='')
    parser.add_argument('--ratified-by', default=''); parser.add_argument('--ratified-at', default=''); parser.add_argument('--approval-reference', default='')
    parser.add_argument('--local-rehearsal', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(); rows = load_successors(args.successors)
    if args.action == 'plan':
        emit_result({'successors_sha256':SUCCESSORS_SHA256,'count':16,'names':[r['publish_payload']['climb']['route_name'] for r in rows]}); return
    if args.action in ('publish','rollback') and (not args.execute or args.confirm_successors_sha256 != SUCCESSORS_SHA256): parser.error('Writes require --execute and exact --confirm-successors-sha256')
    if args.action in ('publish','verify','rollback') and not args.archive: parser.error('Scoped --archive required')
    if args.action == 'rollback' and not args.receipt: parser.error('--receipt required for exact successor identities')
    archive = json.loads(args.archive.read_text()) if args.archive else None
    if archive: validate_archive(archive, rows)
    payloads = approved_payloads(rows,args.confirm_successors_sha256,args.ratified_by,args.ratified_at) if args.action=='publish' else None
    dsn = os.environ.get('DATABASE_URL')
    if not dsn: parser.error('DATABASE_URL must already be present in the running API container')
    connection = connect_database(dsn,local_rehearsal=args.local_rehearsal)
    try:
        if args.action == 'publish': result = publish(connection,rows,payloads,archive,args.approval_reference,args.predecessors)
        elif args.action == 'rollback': result = rollback(connection,rows,archive,json.loads(args.receipt.read_text()))
        elif args.action == 'archive': result = create_archive(connection,rows,args.predecessors)
        else:
            connection.set_session(readonly=True)
            with connection.cursor() as cursor:
                configure(cursor); result = preflight(cursor,rows,args.predecessors) if args.action=='check' else verification_receipt(cursor,rows,archive)
            connection.rollback()
        emit_result(result,committed=args.action in ('publish','rollback'))
    finally:
        connection.close()


def verify(cursor, rows):
    results = []
    for row in rows:
        climb = row['publish_payload']['climb']
        cursor.execute('SELECT id::text, status, version, supersedes_climb_id::text, record_continuity_policy, candidate_fingerprint, length_m, vert_m, avg_gradient_pct FROM public.canon_climbs WHERE canon_id=%s::uuid ORDER BY version', (row['canon_id'],))
        versions = cursor.fetchall()
        if len(versions) != 2 or versions[0][:3] != (row['supersedes_climb_id'], 'retired', 1):
            raise RuntimeError('Predecessor was not retained as retired v1')
        new = versions[1]
        if new[1:6] != ('ratified', 2, row['supersedes_climb_id'], 'new_record_board', climb['candidate_fingerprint']):
            raise RuntimeError('Successor version/lineage drift')
        if [float(x) for x in new[6:9]] != [climb[k] for k in ('length_m', 'vert_m', 'avg_gradient_pct')]:
            raise RuntimeError('Successor metric drift')
        cursor.execute('''SELECT ST_AsEWKB(centerline_geom)=ST_AsEWKB(ST_GeomFromText(%s,4326)),
            ST_AsEWKB(gate_start_line)=ST_AsEWKB(ST_GeomFromText(%s,4326)),
            ST_AsEWKB(gate_end_line)=ST_AsEWKB(ST_GeomFromText(%s,4326)),
            ST_Equals(corridor_geom,ST_Multi(ST_Buffer(ST_GeomFromText(%s,4326)::geography,%s)::geometry)),
            ST_IsValid(corridor_geom), canonical_profile=%s::jsonb
            FROM public.canon_climbs WHERE id=%s::uuid''',
            (climb['centerline_wkt'], climb['gate_start_wkt'], climb['gate_end_wkt'], climb['centerline_wkt'],
             climb['corridor_half_width_m'], json.dumps(climb['canonical_profile']), new[0]))
        if not all(cursor.fetchone()):
            raise RuntimeError('Successor geometry/profile mismatch')
        cursor.execute(
            'SELECT h3_resolution,tile_id,coverage_role FROM public.canon_corridor_cells WHERE canon_climb_id=%s::uuid',
            (new[0],))
        cells = set(cursor.fetchall())
        expected = {(c['h3_resolution'], c['tile_id'], c['coverage_role']) for c in row['publish_payload']['corridor_cells']}
        if cells != expected or any(r != 10 or not h3.is_valid_cell(t) or h3.get_resolution(t) != 10 for r, t, _ in cells):
            raise RuntimeError('Successor H3 resolution 10 cells differ')
        results.append({'name': climb['route_name'], 'predecessor_id': row['supersedes_climb_id'],
                        'id': new[0], 'canon_id': row['canon_id'], 'version': 2, 'cells': len(cells)})
    return results



if __name__ == '__main__': main()
