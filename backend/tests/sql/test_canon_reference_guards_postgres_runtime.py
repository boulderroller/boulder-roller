"""Local PostgreSQL migration/legacy integrity contracts; no remote connection."""
from contextlib import closing
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import Json

from scripts import publish_canon_successors as publication
from tests.services.test_settlement_clock_postgres_runtime import postgres_dsn, isolated_postgres_dsn

REGISTRY = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
FAMILY = '11111111-1111-4111-8111-111111111111'


@pytest.fixture
def db(isolated_postgres_dsn):
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            for role in ('anon', 'authenticated', 'service_role'):
                cursor.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,))
                if not cursor.fetchone(): cursor.execute('CREATE ROLE ' + role)
            cursor.execute('''
                CREATE TABLE canon_climbs(id uuid PRIMARY KEY, canon_id uuid, status text);
                CREATE TABLE patterns_climb(id serial PRIMARY KEY, match_trace jsonb);
                CREATE TABLE stage1_keeper_scopes(id text PRIMARY KEY, canon_id uuid);
                CREATE TABLE canon_corridor_cells(canon_climb_id uuid REFERENCES canon_climbs);
            ''')
            cursor.execute((Path(__file__).parents[2]/'sql/179_canon_reference_guards.sql').read_text())
            cursor.execute("INSERT INTO canon_climbs VALUES (%s,%s,'ratified')", (REGISTRY,FAMILY))
            yield cursor


def test_canon_migration_keeps_repeated_keeper_scope_insert_after_retirement(db):
    statement = "INSERT INTO stage1_keeper_scopes VALUES ('scope',%s) ON CONFLICT DO NOTHING"
    db.execute(statement, (FAMILY,))
    db.execute("UPDATE canon_climbs SET status='retired'")
    db.execute(statement, (FAMILY,))
    db.execute('SELECT count(*) FROM stage1_keeper_scopes')
    assert db.fetchone() == (1,)


def test_canon_migration_guards_new_patterns_without_breaking_legacy_updates(db):
    db.execute("INSERT INTO patterns_climb(match_trace) VALUES ('{}')")
    db.execute('UPDATE patterns_climb SET match_trace=%s', (Json({'registry_id':'legacy-invalid'}),))
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        db.execute('INSERT INTO patterns_climb(match_trace) VALUES (%s)',
                   (Json({'registry_id': FAMILY}),))
    db.execute('SELECT count(*) FROM patterns_climb')
    assert db.fetchone() == (1,)


def test_canon_check_counts_malformed_legacy_ids_without_exporting_values(db, monkeypatch):
    monkeypatch.setattr(publication, 'require_schema', lambda cursor: None)
    for value in (REGISTRY, REGISTRY.upper(), '{'+REGISTRY+'}', REGISTRY.replace('-',''), None):
        db.execute('INSERT INTO patterns_climb(match_trace) VALUES (%s)', (Json({'registry_id': value}),))
    db.execute("INSERT INTO patterns_climb(match_trace) VALUES ('{}')")
    assert publication.preflight_integrity_counts(db) == {'malformed_pattern_registry_ids': 0, 'non_ratified_cell_rows': 0}
    for value in ('PRIVATE-INVALID', '', 7, {}, []):
        db.execute("INSERT INTO patterns_climb(match_trace) VALUES ('{}') RETURNING id")
        identity = db.fetchone()[0]
        db.execute('UPDATE patterns_climb SET match_trace=%s WHERE id=%s', (Json({'registry_id': value}),identity))
    with pytest.raises(RuntimeError, match=r'^Malformed patterns_climb registry_id values: 5; expected 0$'):
        publication.preflight(db, publication.load_successors())


def test_canon_check_counts_cells_owned_by_non_ratified_rows(db, monkeypatch):
    monkeypatch.setattr(publication, 'require_schema', lambda cursor: None)
    db.execute('INSERT INTO canon_corridor_cells VALUES (%s)', (REGISTRY,))
    db.execute("UPDATE canon_climbs SET status='candidate'")
    with pytest.raises(RuntimeError, match=r'^Cells owned by non-ratified registry rows: 1; expected 0$'):
        publication.preflight(db, publication.load_successors())
