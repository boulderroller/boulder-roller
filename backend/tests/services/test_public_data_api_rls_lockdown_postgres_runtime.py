from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import (
    TRANSACTION_STATUS_IDLE,
    make_dsn,
    parse_dsn,
)

from backend.scripts import apply_sql_migrations as migration_runner
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    isolated_postgres_dsn,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "153_public_data_api_rls_lockdown.sql"
SUPABASE_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260825012923_public_data_api_rls_lockdown.sql"
)
PROJECT_REF = "qzkqjevawthyboymqrle"
FAKE_REVIEWED_DATABASE_URL = (
    f"postgresql://postgres:secret@db.{PROJECT_REF}.supabase.co:5432/postgres"
)
APP_OWNER = "app_migrator"
APP_OWNER_TEST_PASSWORD = "test-only-app-migrator-password"

SENSITIVE_TABLES = (
    "audit_log",
    "auth_identities",
    "auth_nonces",
    "auth_refresh_tokens",
    "deleted_wallets",
    "ios_diagnostics",
    "mobile_push_devices",
    "strava_connections",
    "waitlist",
)

AUDITED_VIEWS_TO_CONVERT = (
    "beetle_card_leaderboard",
    "climb_leaderboards",
    "climb_vault_active",
    "deprecated_segment_to_pattern_mapping",
    "user_stats",
    "v_active_disputes",
    "v_cell_feedback_summary",
    "v_invalid_completions",
    "v_leaderboard_with_tenure",
    "v_vault_local_legends",
)


def _admin_roles_and_database_owner(admin_dsn: str) -> str:
    database_name = parse_dsn(admin_dsn)["dbname"]
    connection = psycopg2.connect(admin_dsn)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DO $$ BEGIN
                  CREATE ROLE app_migrator LOGIN NOSUPERUSER BYPASSRLS
                    CREATEROLE CREATEDB;
                EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                ALTER ROLE app_migrator LOGIN NOSUPERUSER BYPASSRLS
                  CREATEROLE CREATEDB PASSWORD 'test-only-app-migrator-password';

                DO $$ BEGIN CREATE ROLE anon NOLOGIN;
                  EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE authenticated NOLOGIN;
                  EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE service_role NOLOGIN NOSUPERUSER BYPASSRLS;
                  EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                ALTER ROLE service_role NOLOGIN NOSUPERUSER BYPASSRLS;
                DO $$ BEGIN CREATE ROLE supabase_admin NOLOGIN;
                  EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE non_grantor_owner NOLOGIN;
                  EXCEPTION WHEN duplicate_object THEN NULL; END $$;

                GRANT anon, authenticated, service_role TO app_migrator
                  WITH ADMIN OPTION;
                """
            )
            cursor.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO app_migrator").format(
                    sql.Identifier(database_name)
                )
            )
    finally:
        connection.close()
    return make_dsn(
        admin_dsn,
        user=APP_OWNER,
        password=APP_OWNER_TEST_PASSWORD,
    )


def _bootstrap_app_schema(app_dsn: str) -> None:
    connection = psycopg2.connect(app_dsn)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
                GRANT CREATE, USAGE ON SCHEMA public
                  TO supabase_admin, non_grantor_owner;

                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  GRANT ALL ON TABLES TO anon, authenticated, service_role;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                  GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;
                """
            )

            for table in (
                *SENSITIVE_TABLES,
                "ordinary_app_table",
                "service_read_only_table",
                "service_no_access_table",
                "service_public_only_table",
                "service_public_column_table",
                "deletion_requests",
                "deleted_account_tombstones",
            ):
                cursor.execute(
                    sql.SQL(
                        "CREATE TABLE public.{} ("
                        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                        "secret TEXT, private_value TEXT)"
                    ).format(sql.Identifier(table))
                )

            cursor.execute(
                """
                INSERT INTO public.auth_refresh_tokens (secret)
                VALUES ('sentinel-token');

                CREATE POLICY client_read_policy
                  ON public.auth_refresh_tokens
                  FOR SELECT TO PUBLIC USING (true);

                CREATE FUNCTION public.read_sensitive_value()
                RETURNS TEXT
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog, public
                AS $$ SELECT secret FROM public.auth_refresh_tokens
                       ORDER BY id LIMIT 1 $$;

                CREATE FUNCTION public.read_sensitive_value(prefix TEXT)
                RETURNS TEXT
                LANGUAGE sql
                SECURITY DEFINER
                SET search_path = pg_catalog, public
                AS $$ SELECT prefix || secret FROM public.auth_refresh_tokens
                       ORDER BY id LIMIT 1 $$;

                CREATE FUNCTION public.service_read_only_rpc()
                RETURNS INTEGER LANGUAGE sql AS $$ SELECT 1 $$;
                CREATE FUNCTION public.service_no_access_rpc()
                RETURNS INTEGER LANGUAGE sql AS $$ SELECT 1 $$;
                CREATE FUNCTION public.service_public_only_rpc()
                RETURNS INTEGER LANGUAGE sql AS $$ SELECT 1 $$;

                CREATE SEQUENCE public.service_read_only_sequence;
                CREATE SEQUENCE public.service_no_access_sequence;
                CREATE SEQUENCE public.service_public_only_sequence;

                REVOKE ALL PRIVILEGES ON TABLE public.service_read_only_table
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT SELECT ON TABLE public.service_read_only_table TO service_role;
                REVOKE ALL PRIVILEGES ON TABLE public.service_no_access_table
                  FROM PUBLIC, anon, authenticated, service_role;

                REVOKE ALL PRIVILEGES ON TABLE public.service_public_only_table
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT SELECT ON TABLE public.service_public_only_table TO PUBLIC;

                REVOKE ALL PRIVILEGES ON TABLE public.service_public_column_table
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT SELECT (secret), UPDATE (secret)
                  ON TABLE public.service_public_column_table TO PUBLIC;

                REVOKE ALL PRIVILEGES ON SEQUENCE public.service_read_only_sequence
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT USAGE ON SEQUENCE public.service_read_only_sequence
                  TO service_role;
                REVOKE ALL PRIVILEGES ON SEQUENCE public.service_no_access_sequence
                  FROM PUBLIC, anon, authenticated, service_role;
                REVOKE ALL PRIVILEGES ON SEQUENCE public.service_public_only_sequence
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT USAGE ON SEQUENCE public.service_public_only_sequence TO PUBLIC;

                REVOKE EXECUTE ON FUNCTION public.service_read_only_rpc()
                  FROM PUBLIC, anon, authenticated, service_role;
                GRANT EXECUTE ON FUNCTION public.service_read_only_rpc()
                  TO service_role;
                REVOKE EXECUTE ON FUNCTION public.service_no_access_rpc()
                  FROM PUBLIC, anon, authenticated, service_role;
                REVOKE EXECUTE ON FUNCTION public.service_public_only_rpc()
                  FROM anon, authenticated, service_role;

                -- Model migration 152's security postconditions. Migration
                -- 153 validates these objects but does not sweep them.
                ALTER TABLE public.deletion_requests ENABLE ROW LEVEL SECURITY;
                ALTER TABLE public.deleted_account_tombstones ENABLE ROW LEVEL SECURITY;
                ALTER TABLE public.deleted_wallets ENABLE ROW LEVEL SECURITY;
                REVOKE ALL PRIVILEGES ON TABLE public.deletion_requests
                  FROM PUBLIC, anon, authenticated, service_role;
                REVOKE ALL PRIVILEGES ON TABLE public.deleted_account_tombstones
                  FROM PUBLIC, anon, authenticated, service_role;
                REVOKE ALL PRIVILEGES ON TABLE public.deleted_wallets
                  FROM PUBLIC, anon, authenticated, service_role;
                """
            )

            for view in AUDITED_VIEWS_TO_CONVERT:
                cursor.execute(
                    sql.SQL(
                        "CREATE VIEW public.{} AS "
                        "SELECT id, secret FROM public.auth_refresh_tokens"
                    ).format(sql.Identifier(view))
                )
            cursor.execute(
                """
                CREATE VIEW public.confirmed_vault_completion_candidates
                  WITH (security_invoker = true) AS
                  SELECT id, secret FROM public.auth_refresh_tokens;
                """
            )
    finally:
        connection.close()


def _bootstrap_provider_objects(admin_dsn: str) -> None:
    connection = psycopg2.connect(admin_dsn)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SET ROLE supabase_admin;
                CREATE TABLE public.spatial_ref_sys (
                  srid INTEGER PRIMARY KEY,
                  auth_name TEXT
                );
                GRANT ALL ON TABLE public.spatial_ref_sys
                  TO anon, authenticated, service_role;
                CREATE FUNCTION public.st_estimatedextent(
                  table_name TEXT,
                  column_name TEXT
                ) RETURNS TEXT LANGUAGE sql SECURITY DEFINER
                  AS $$ SELECT table_name || '.' || column_name $$;
                GRANT EXECUTE ON FUNCTION public.st_estimatedextent(TEXT, TEXT)
                  TO anon, authenticated, service_role;
                RESET ROLE;
                """
            )
    finally:
        connection.close()


def _setup_database(admin_dsn: str) -> str:
    app_dsn = _admin_roles_and_database_owner(admin_dsn)
    _bootstrap_app_schema(app_dsn)
    _bootstrap_provider_objects(admin_dsn)
    connection = psycopg2.connect(app_dsn)
    try:
        migration_runner.ensure_ledger(connection)
    finally:
        connection.close()
    return app_dsn


def _runtime_manifest(connection: Any) -> dict[str, object]:
    predecessor_relations = {
        ("r", "deleted_account_tombstones"),
        ("r", "deletion_requests"),
    }
    predecessor_routines = {
        ("f", "service_no_access_rpc", ""),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relkind::text, c.relname
            FROM pg_class AS c
            WHERE c.relnamespace = 'public'::regnamespace
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
              AND c.relowner = (
                SELECT oid FROM pg_roles WHERE rolname = current_user
              )
            ORDER BY c.relkind::text, c.relname
            """
        )
        app_relations = [
            {"kind": kind, "name": name}
            for kind, name in cursor.fetchall()
            if (kind, name) not in predecessor_relations
        ]

        cursor.execute(
            """
            SELECT p.prokind::text, p.proname, oidvectortypes(p.proargtypes)
            FROM pg_proc AS p
            WHERE p.pronamespace = 'public'::regnamespace
              AND p.prokind IN ('f', 'p')
              AND p.proowner = (
                SELECT oid FROM pg_roles WHERE rolname = current_user
              )
            ORDER BY p.prokind::text, p.proname, oidvectortypes(p.proargtypes)
            """
        )
        app_routines = [
            {"kind": kind, "name": name, "argument_types": arguments}
            for kind, name, arguments in cursor.fetchall()
            if (kind, name, arguments) not in predecessor_routines
        ]

        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class AS c
            WHERE c.relnamespace = 'public'::regnamespace
              AND c.relkind = 'v'
              AND c.relowner = (
                SELECT oid FROM pg_roles WHERE rolname = current_user
              )
              AND NOT coalesce(
                c.reloptions @> ARRAY['security_invoker=true'], false
              )
            ORDER BY c.relname
            """
        )
        views_to_convert = [name for (name,) in cursor.fetchall()]

        cursor.execute(
            """
            SELECT c.relkind::text, c.relname, pg_get_userbyid(c.relowner)
            FROM pg_class AS c
            WHERE c.relnamespace = 'public'::regnamespace
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND pg_get_userbyid(c.relowner) = 'supabase_admin'
            ORDER BY c.relkind::text, c.relname
            """
        )
        provider_exceptions = [
            {"kind": kind, "name": name, "owner": owner}
            for kind, name, owner in cursor.fetchall()
        ]

    manifest: dict[str, object] = {
        "version": 1,
        "project_ref": PROJECT_REF,
        "expected_catalog_fingerprint": "0" * 64,
        "app_relations": app_relations,
        "app_routines": app_routines,
        "views_to_convert": views_to_convert,
        "provider_relation_exceptions": provider_exceptions,
        "predecessor_152": {
            "relations": [
                {"kind": kind, "name": name}
                for kind, name in sorted(predecessor_relations)
            ],
            "routines": [
                {"kind": kind, "name": name, "argument_types": arguments}
                for kind, name, arguments in sorted(predecessor_routines)
            ],
            "excluded_new_columns": [
                {"relation": "auth_refresh_tokens", "name": "private_value"}
            ],
            "normalized_relation_security": ["deleted_wallets"],
            "normalized_routine_security": [
                {
                    "kind": "f",
                    "name": "service_read_only_rpc",
                    "argument_types": "",
                }
            ],
        },
    }
    fingerprint = migration_runner.catalog_scope_fingerprint(connection, manifest)
    connection.rollback()
    manifest["expected_catalog_fingerprint"] = fingerprint
    return manifest


def _locked_migration() -> migration_runner.Migration:
    return next(
        migration
        for migration in migration_runner.discover_migrations(BACKEND_ROOT / "sql")
        if migration.filename == "153_public_data_api_rls_lockdown.sql"
    )


def _approve_runtime_manifest(
    monkeypatch: pytest.MonkeyPatch,
    migration: migration_runner.Migration,
    manifest: dict[str, object],
) -> None:
    fingerprint = str(manifest["expected_catalog_fingerprint"])
    monkeypatch.setattr(
        migration_runner,
        "load_catalog_manifest",
        lambda _migration: manifest,
    )
    monkeypatch.setenv(
        "APPROVED_PUBLIC_DATA_API_RLS_SHA256", migration.checksum
    )
    monkeypatch.setenv(
        "APPROVED_PUBLIC_DATA_API_RLS_PROJECT_REF", PROJECT_REF
    )
    monkeypatch.setenv(
        "APPROVED_PUBLIC_DATA_API_RLS_CATALOG_SHA256", fingerprint
    )


def _has_table_privilege(cursor: Any, role: str, table: str, privilege: str) -> bool:
    cursor.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege))
    return bool(cursor.fetchone()[0])


def _has_any_column_privilege(
    cursor: Any, role: str, table: str, privilege: str
) -> bool:
    cursor.execute(
        "SELECT has_any_column_privilege(%s, %s, %s)",
        (role, table, privilege),
    )
    return bool(cursor.fetchone()[0])


def _has_column_privilege(
    cursor: Any, role: str, table: str, column: str, privilege: str
) -> bool:
    cursor.execute(
        "SELECT has_column_privilege(%s, %s, %s, %s)",
        (role, table, column, privilege),
    )
    return bool(cursor.fetchone()[0])


def _has_function_privilege(cursor: Any, role: str, function: str) -> bool:
    cursor.execute(
        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
        (role, function),
    )
    return bool(cursor.fetchone()[0])


def _has_sequence_privilege(
    cursor: Any, role: str, sequence: str, privilege: str
) -> bool:
    cursor.execute(
        "SELECT has_sequence_privilege(%s, %s, %s)",
        (role, sequence, privilege),
    )
    return bool(cursor.fetchone()[0])


def test_public_data_api_rls_lockdown_is_exactly_mirrored_and_non_destructive() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == SUPABASE_MIGRATION.read_bytes()

    sql_text = CANONICAL_MIGRATION.read_text(encoding="utf-8")
    lock_timeout = "SET LOCAL lock_timeout = '5s';"
    statement_timeout = "SET LOCAL statement_timeout = '120s';"
    first_locking_statement = "REVOKE ALL PRIVILEGES ON SCHEMA public"
    assert lock_timeout in sql_text
    assert statement_timeout in sql_text
    assert sql_text.index(lock_timeout) < sql_text.index(first_locking_statement)
    assert sql_text.index(statement_timeout) < sql_text.index(first_locking_statement)
    assert "boulderroller.migration_runner" in sql_text
    assert "boulderroller.public_data_api_rls_catalog_manifest" in sql_text
    assert "boulderroller.approved_public_data_api_rls_catalog_sha256" in sql_text
    assert "CREATE TEMP TABLE br_153_service_acl_before" in sql_text
    assert "has_schema_privilege" in sql_text
    assert "has_table_privilege" in sql_text
    assert "has_any_column_privilege" in sql_text
    assert "has_column_privilege" in sql_text
    assert "has_sequence_privilege" in sql_text
    assert "has_function_privilege" in sql_text
    assert "MAINTAIN" in sql_text
    assert "client privilege revoke verification failed" in sql_text
    assert "service_role effective privilege changed" in sql_text
    assert "public app-owned view remains security definer" in sql_text
    assert "ALTER DEFAULT PRIVILEGES\n    REVOKE EXECUTE" not in sql_text
    assert sql_text.count("DO $migration$") == 1
    assert sql_text.count("$migration$;") == 1
    assert not re.search(
        r"(?im)^\s*(?:DROP\s+TABLE|TRUNCATE\s+(?:TABLE\s+)?|DELETE\s+FROM|"
        r"UPDATE\s+\S+\s+SET|INSERT\s+INTO\s+(?!br_153_))\b",
        sql_text,
    )

    manifest = json.loads(
        CANONICAL_MIGRATION.with_suffix(".catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(manifest["app_relations"]) == 192
    assert len(manifest["app_routines"]) == 231
    assert manifest["views_to_convert"] == list(AUDITED_VIEWS_TO_CONVERT)
    assert len(manifest["predecessor_152"]["routines"]) == 30


def test_legacy_root_supabase_migrations_are_explicitly_retired() -> None:
    readme = (REPO_ROOT / "supabase" / "README.md").read_text(encoding="utf-8")
    assert "RETIRED" in readme
    assert "backend/sql" in readme

    backend_readme = (
        REPO_ROOT / "backend" / "supabase" / "migrations" / "README.md"
    ).read_text(encoding="utf-8")
    assert "Direct psql" not in backend_readme
    assert "Supabase Dashboard" not in backend_readme

    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "backend/sql/ — canonical database migrations" in claude


def test_default_psql_continuation_cannot_reach_mutations(
    isolated_postgres_dsn: str,
) -> None:
    app_dsn = _setup_database(isolated_postgres_dsn)
    psql = shutil.which("psql")
    if psql is None:
        pytest.skip("psql is unavailable")

    result = subprocess.run(
        [psql, "-X", "-v", "ON_ERROR_STOP=0", "-d", app_dsn, "-f", str(CANONICAL_MIGRATION)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert "requires apply_sql_migrations.py" in result.stdout + result.stderr

    connection = psycopg2.connect(app_dsn)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.auth_refresh_tokens'::regclass"
            )
            assert cursor.fetchone() == (False,)
            assert _has_table_privilege(
                cursor, "anon", "public.auth_refresh_tokens", "SELECT"
            )
    finally:
        connection.close()


def test_public_data_api_rls_lockdown_runtime_outcome(
    isolated_postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_dsn = _setup_database(isolated_postgres_dsn)
    migration = _locked_migration()
    connection = psycopg2.connect(app_dsn)
    try:
        manifest = _runtime_manifest(connection)
        monkeypatch.setattr(
            migration_runner,
            "load_catalog_manifest",
            lambda _migration: manifest,
        )
        monkeypatch.delenv(
            "APPROVED_PUBLIC_DATA_API_RLS_SHA256", raising=False
        )
        monkeypatch.setenv(
            "APPROVED_PUBLIC_DATA_API_RLS_PROJECT_REF", PROJECT_REF
        )
        monkeypatch.setenv(
            "APPROVED_PUBLIC_DATA_API_RLS_CATALOG_SHA256",
            str(manifest["expected_catalog_fingerprint"]),
        )
        with pytest.raises(SystemExit, match="exact reviewed bytes"):
            migration_runner.apply_migration(
                connection,
                migration,
                database_url=FAKE_REVIEWED_DATABASE_URL,
            )
        assert connection.get_transaction_status() == TRANSACTION_STATUS_IDLE

        _approve_runtime_manifest(monkeypatch, migration, manifest)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb,
                       pg_get_userbyid(d.datdba) = current_user
                FROM pg_roles AS r
                CROSS JOIN pg_database AS d
                WHERE r.rolname = current_user
                  AND d.datname = current_database()
                """
            )
            assert cursor.fetchone() == (False, True, True, True, True)
        connection.rollback()

        blocker = psycopg2.connect(app_dsn)
        try:
            with blocker.cursor() as blocking_cursor:
                blocking_cursor.execute(
                    "LOCK TABLE public.auth_refresh_tokens IN ACCESS SHARE MODE"
                )

            started_at = time.monotonic()
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                migration_runner.apply_migration(
                    connection,
                    migration,
                    database_url=FAKE_REVIEWED_DATABASE_URL,
                )
            assert time.monotonic() - started_at < 10

            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT relrowsecurity FROM pg_class "
                    "WHERE oid = 'public.audit_log'::regclass"
                )
                assert cursor.fetchone() == (False,)
            connection.rollback()
        finally:
            blocker.rollback()
            blocker.close()

        migration_runner.apply_migration(
            connection,
            migration,
            database_url=FAKE_REVIEWED_DATABASE_URL,
        )
        connection.autocommit = True

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT secret FROM public.auth_refresh_tokens ORDER BY id LIMIT 1"
            )
            assert cursor.fetchone() == ("sentinel-token",)

            cursor.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relkind IN ('r', 'p')
                  AND relowner = (
                    SELECT oid FROM pg_roles WHERE rolname = current_user
                  )
                ORDER BY relname
                """
            )
            app_tables = cursor.fetchall()
            assert app_tables
            assert all(rls_enabled for _, rls_enabled in app_tables)

            cursor.execute(
                """
                SELECT count(*)
                FROM pg_policy AS policy
                JOIN pg_class AS relation ON relation.oid = policy.polrelid
                WHERE relation.relnamespace = 'public'::regnamespace
                  AND relation.relowner = (
                    SELECT oid FROM pg_roles WHERE rolname = current_user
                  )
                """
            )
            assert cursor.fetchone() == (0,)

            for table in (*SENSITIVE_TABLES, "ordinary_app_table"):
                qualified = f"public.{table}"
                for role in ("anon", "authenticated"):
                    for privilege in (
                        "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
                        "REFERENCES", "TRIGGER", "MAINTAIN",
                    ):
                        assert not _has_table_privilege(
                            cursor, role, qualified, privilege
                        )
                    for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                        assert not _has_any_column_privilege(
                            cursor, role, qualified, privilege
                        )
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert _has_table_privilege(
                        cursor, "service_role", qualified, privilege
                    ) is (table != "deleted_wallets")

            assert _has_table_privilege(
                cursor, "service_role", "public.service_read_only_table", "SELECT"
            )
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not _has_table_privilege(
                    cursor,
                    "service_role",
                    "public.service_read_only_table",
                    privilege,
                )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not _has_table_privilege(
                    cursor, "service_role", "public.service_no_access_table", privilege
                )

            assert _has_table_privilege(
                cursor, "service_role", "public.service_public_only_table", "SELECT"
            )
            assert not _has_table_privilege(
                cursor, "anon", "public.service_public_only_table", "SELECT"
            )
            assert not _has_table_privilege(
                cursor,
                "service_role",
                "public.service_public_column_table",
                "SELECT",
            )
            assert _has_column_privilege(
                cursor,
                "service_role",
                "public.service_public_column_table",
                "secret",
                "SELECT",
            )
            assert _has_column_privilege(
                cursor,
                "service_role",
                "public.service_public_column_table",
                "secret",
                "UPDATE",
            )
            assert not _has_any_column_privilege(
                cursor,
                "anon",
                "public.service_public_column_table",
                "SELECT",
            )

            assert _has_sequence_privilege(
                cursor,
                "service_role",
                "public.service_read_only_sequence",
                "USAGE",
            )
            assert _has_sequence_privilege(
                cursor,
                "service_role",
                "public.service_public_only_sequence",
                "USAGE",
            )
            for sequence in (
                "public.service_no_access_sequence",
                "public.service_public_only_sequence",
            ):
                assert not _has_sequence_privilege(
                    cursor, "anon", sequence, "USAGE"
                )

            assert _has_function_privilege(
                cursor, "service_role", "public.service_read_only_rpc()"
            )
            assert _has_function_privilege(
                cursor, "service_role", "public.service_public_only_rpc()"
            )
            assert not _has_function_privilege(
                cursor, "service_role", "public.service_no_access_rpc()"
            )
            assert not _has_function_privilege(
                cursor, "anon", "public.service_public_only_rpc()"
            )

            for role in ("anon", "authenticated"):
                cursor.execute(
                    "SELECT has_schema_privilege(%s, 'public', 'USAGE')", (role,)
                )
                assert cursor.fetchone() == (False,)
            cursor.execute(
                "SELECT has_schema_privilege('service_role', 'public', 'USAGE')"
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT rolbypassrls, rolsuper FROM pg_roles "
                "WHERE rolname = 'service_role'"
            )
            assert cursor.fetchone() == (True, False)

            cursor.execute(
                """
                SELECT relname,
                       coalesce(reloptions @> ARRAY['security_invoker=true'], false)
                FROM pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relkind = 'v'
                  AND relowner = (
                    SELECT oid FROM pg_roles WHERE rolname = current_user
                  )
                ORDER BY relname
                """
            )
            app_views = cursor.fetchall()
            assert len(app_views) == 11
            assert all(security_invoker for _, security_invoker in app_views)
            for view, _ in app_views:
                assert _has_table_privilege(
                    cursor, "service_role", f"public.{view}", "SELECT"
                )

            cursor.execute("SET ROLE anon")
            try:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT * FROM public.auth_refresh_tokens")
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT public.read_sensitive_value()")
            finally:
                cursor.execute("RESET ROLE")

            cursor.execute("SET ROLE service_role")
            try:
                cursor.execute(
                    "INSERT INTO public.auth_refresh_tokens (secret) "
                    "VALUES ('service-write') RETURNING id"
                )
                inserted_id = cursor.fetchone()[0]
                cursor.execute(
                    "UPDATE public.auth_refresh_tokens SET secret = 'service-updated' "
                    "WHERE id = %s",
                    (inserted_id,),
                )
                cursor.execute(
                    "DELETE FROM public.auth_refresh_tokens WHERE id = %s",
                    (inserted_id,),
                )
                cursor.execute("SELECT public.read_sensitive_value()")
                assert cursor.fetchone() == ("sentinel-token",)
            finally:
                cursor.execute("RESET ROLE")

            cursor.execute(
                """
                CREATE TABLE public.future_private_table (
                  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
                );
                CREATE FUNCTION public.future_private_rpc()
                RETURNS INTEGER LANGUAGE sql AS $$ SELECT 1 $$;
                """
            )
            for role in ("anon", "authenticated"):
                assert not _has_table_privilege(
                    cursor, role, "public.future_private_table", "SELECT"
                )
                # PostgreSQL's global routine default remains, but schema
                # denial makes the RPC uncallable.
                assert _has_function_privilege(
                    cursor, role, "public.future_private_rpc()"
                )
            cursor.execute("SET ROLE anon")
            try:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT public.future_private_rpc()")
            finally:
                cursor.execute("RESET ROLE")

            cursor.execute(
                """
                SELECT relrowsecurity, pg_get_userbyid(relowner)
                FROM pg_class
                WHERE oid = 'public.spatial_ref_sys'::regclass
                """
            )
            assert cursor.fetchone() == (False, "supabase_admin")
            assert _has_table_privilege(
                cursor, "anon", "public.spatial_ref_sys", "SELECT"
            )
            assert _has_function_privilege(
                cursor, "anon", "public.st_estimatedextent(text,text)"
            )
            cursor.execute("SET ROLE anon")
            try:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT * FROM public.spatial_ref_sys")
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute(
                        "SELECT public.st_estimatedextent('table', 'column')"
                    )
            finally:
                cursor.execute("RESET ROLE")
    finally:
        connection.close()


def test_non_grantor_acl_no_op_raises_and_rolls_back(
    isolated_postgres_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_dsn = _setup_database(isolated_postgres_dsn)

    admin = psycopg2.connect(isolated_postgres_dsn)
    try:
        admin.autocommit = True
        with admin.cursor() as cursor:
            cursor.execute(
                """
                SET ROLE non_grantor_owner;
                CREATE TABLE public.unrevokable_table (secret TEXT);
                GRANT SELECT (secret) ON public.unrevokable_table
                  TO anon, authenticated;
                RESET ROLE;
                """
            )
    finally:
        admin.close()

    migration = _locked_migration()
    connection = psycopg2.connect(app_dsn)
    try:
        manifest = _runtime_manifest(connection)
        _approve_runtime_manifest(monkeypatch, migration, manifest)

        with pytest.raises(
            psycopg2.errors.RaiseException,
            match="client privilege revoke verification failed",
        ):
            migration_runner.apply_migration(
                connection,
                migration,
                database_url=FAKE_REVIEWED_DATABASE_URL,
            )

        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.audit_log'::regclass"
            )
            assert cursor.fetchone() == (False,)
            cursor.execute("SELECT has_schema_privilege('anon', 'public', 'USAGE')")
            assert cursor.fetchone() == (True,)
            assert _has_any_column_privilege(
                cursor, "anon", "public.unrevokable_table", "SELECT"
            )
            cursor.execute(
                "SELECT count(*) FROM public.br_sql_migrations "
                "WHERE filename = '153_public_data_api_rls_lockdown.sql'"
            )
            assert cursor.fetchone() == (0,)
    finally:
        connection.close()
