"""Local PostgreSQL checks for the canonical Stage 1 deployment path."""
from contextlib import closing
from pathlib import Path

import psycopg2

from scripts.apply_sql_migrations import apply_migration, discover_migrations, ensure_ledger
from tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn, isolated_postgres_dsn,
)

from tests.sql.test_account_deletion_migration_runtime import _bootstrap_pre_152

BACKEND = Path(__file__).parents[2]


def test_canonical_balance_creation_precedes_pending_intent_index(isolated_postgres_dsn):
    # Production has no balance_operations. Discover only deployable canonical
    # files, never the old Supabase-only creation that masked this dependency.
    migrations = [m for m in discover_migrations(BACKEND / 'sql')
                  if m.number >= 169 and 'balance_operations' in m.path.read_text()]
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            # Focused integration predecessor, not the whole-stack deployment
            # baseline: use the real 152 fence, with Balance absent when it ran.
            _bootstrap_pre_152(cursor)
            cursor.execute("DROP TABLE public.balance_operations")
            cursor.execute((BACKEND / 'sql/152_account_deletion_lifecycle.sql').read_text())
            cursor.execute("ALTER ROLE service_role BYPASSRLS")
            cursor.execute("GRANT USAGE ON SCHEMA public TO service_role")
        ensure_ledger(connection)
        for migration in migrations:
            apply_migration(connection, migration)
        with connection.cursor() as cursor:
            cursor.execute("SELECT indisvalid FROM pg_index WHERE indexrelid='idx_balance_stage1_pending_intent'::regclass")
            assert cursor.fetchone() == (True,)
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.balance_operations'::regclass")
            assert cursor.fetchone() == (True,)
            cursor.execute("SELECT count(*) FROM pg_policy WHERE polrelid='public.balance_operations'::regclass")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT has_table_privilege('service_role','public.balance_operations','INSERT,SELECT,UPDATE')")
            assert cursor.fetchone() == (True,)
            for role in ('anon', 'authenticated'):
                cursor.execute("SELECT has_table_privilege(%s,'public.balance_operations','INSERT,SELECT,UPDATE,DELETE')", (role,))
                assert cursor.fetchone() == (False,)
            cursor.execute("SET ROLE service_role")
            cursor.execute("""INSERT INTO public.balance_operations
                (operation_id,protocol_wallet,action_type,authority_model,idempotency_key)
                VALUES ('preserved-operation','local-owner','stage1_pledge','wallet_boundary','preserved-key')""")
            cursor.execute("UPDATE public.balance_operations SET retry_count=1 WHERE operation_id='preserved-operation'")
            cursor.execute("SELECT retry_count FROM public.balance_operations")
            assert cursor.fetchone() == (1,)
            cursor.execute("RESET ROLE")
        connection.commit()
        # Repeat the idempotent table/index SQL, without duplicating ledger rows.
        for migration in migrations:
            with connection.cursor() as cursor:
                cursor.execute(migration.path.read_text())
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute("SELECT operation_id FROM public.balance_operations")
            assert cursor.fetchall() == [('preserved-operation',)]
