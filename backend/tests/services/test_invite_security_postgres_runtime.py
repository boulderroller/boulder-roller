from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASE_INVITE_MIGRATION = (
    BACKEND_ROOT / "supabase" / "migrations" / "20260106120000_invite_codes.sql"
)
CANONICAL_INVITE_MIGRATION = (
    BACKEND_ROOT / "sql" / "145_split_invite_check_and_consume.sql"
)
SUPABASE_INVITE_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260421_103_split_invite_check_and_consume.sql"
)
CANONICAL_SECURITY_MIGRATION = (
    BACKEND_ROOT / "sql" / "146_invite_security_boundary.sql"
)
SUPABASE_SECURITY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260731174134_invite_security_boundary.sql"
)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        ALTER ROLE service_role BYPASSRLS;
        GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
        """
    )
    cursor.execute(BASE_INVITE_MIGRATION.read_text(encoding="utf-8"))


def _call_invite_rpc(cursor: Any, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
    cursor.execute("SET ROLE service_role")
    try:
        cursor.execute(sql, params)
        return cursor.fetchone()
    finally:
        cursor.execute("RESET ROLE")


def _invite_counts(cursor: Any, code_id: str) -> tuple[int, int]:
    cursor.execute(
        """
        SELECT
            code.current_uses,
            count(usage.id)::INTEGER
        FROM public.invite_codes AS code
        LEFT JOIN public.invite_code_usage AS usage ON usage.code_id = code.id
        WHERE code.id = %s
        GROUP BY code.id, code.current_uses
        """,
        (code_id,),
    )
    return cursor.fetchone()


def _digest(code):
    return hmac.new(b'test-invite-secret',code.strip().lower().encode(),hashlib.sha256).hexdigest()


def test_invite_migrations_are_exactly_mirrored() -> None:
    for canonical, mirror in [('159_access_door_hashed_invites.sql','20260908204139_access_door_hashed_invites.sql'),('160_cohort_admission.sql','20260908204432_cohort_admission.sql'),('161_access_admin_audit.sql','20260908204643_access_admin_audit.sql')]:
        assert (BACKEND_ROOT/'sql'/canonical).read_bytes() == (BACKEND_ROOT/'supabase/migrations'/mirror).read_bytes()
    assert CANONICAL_INVITE_MIGRATION.read_bytes() == SUPABASE_INVITE_MIGRATION.read_bytes()
    assert CANONICAL_SECURITY_MIGRATION.read_bytes() == (
        SUPABASE_SECURITY_MIGRATION.read_bytes()
    )


def test_invite_check_consume_and_security_boundary(postgres_dsn: str) -> None:
    code_id = str(uuid4())
    invite_sql = CANONICAL_INVITE_MIGRATION.read_text(encoding="utf-8")
    security_sql = CANONICAL_SECURITY_MIGRATION.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)

            # Both forward migrations must remain safe if a deploy retries them.
            cursor.execute(invite_sql)
            cursor.execute(security_sql)
            cursor.execute(invite_sql)
            cursor.execute(security_sql)

            cursor.execute(
                """
                INSERT INTO public.invite_codes (
                    id, code, description, max_uses, current_uses, is_active
                ) VALUES (%s, 'limited-code', 'One-use runtime proof', 1, 0, true)
                """,
                (code_id,),
            )

            cursor.execute("SELECT set_config('app.invite_code_secret','test-invite-secret',false)")
            cursor.execute((BACKEND_ROOT/'sql/159_access_door_hashed_invites.sql').read_text())
            cursor.execute((BACKEND_ROOT/'sql/159_access_door_hashed_invites.sql').read_text())

            checked = _call_invite_rpc(
                cursor,
                "SELECT * FROM public.check_invite_code(%s)",
                (_digest(" LIMITED-CODE "),),
            )
            assert (checked[0], checked[1], str(checked[2])) == (
                True,
                "Invite code valid",
                code_id,
            )
            assert _invite_counts(cursor, code_id) == (0, 0)

            consumed = _call_invite_rpc(
                cursor,
                "SELECT * FROM public.consume_invite_code(%s, %s, %s, %s)",
                (_digest("limited-code"), "wallet-one", "127.0.0.1", "runtime-test"),
            )
            assert (consumed[0], consumed[1], str(consumed[2])) == (
                True,
                "Invite code consumed",
                code_id,
            )
            assert _invite_counts(cursor, code_id) == (1, 1)

            retried = _call_invite_rpc(
                cursor,
                "SELECT * FROM public.consume_invite_code(%s, %s, %s, %s)",
                (_digest("limited-code"), "wallet-one", "127.0.0.1", "runtime-test"),
            )
            assert retried == (False, "Invite code has reached maximum uses", None)
            assert _invite_counts(cursor, code_id) == (1, 1)

            exhausted = _call_invite_rpc(
                cursor,
                "SELECT * FROM public.consume_invite_code(%s, %s, %s, %s)",
                (_digest("limited-code"), "wallet-two", "127.0.0.2", "runtime-test"),
            )
            assert exhausted == (
                False,
                "Invite code has reached maximum uses",
                None,
            )
            assert _invite_counts(cursor, code_id) == (1, 1)

            cursor.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_class
                WHERE oid IN (
                    'public.invite_codes'::regclass,
                    'public.invite_code_usage'::regclass
                )
                ORDER BY relname
                """
            )
            assert cursor.fetchall() == [
                ("invite_code_usage", True),
                ("invite_codes", True),
            ]

            for role in ("anon", "authenticated"):
                for table in ("public.invite_codes", "public.invite_code_usage"):
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (role, table, privilege),
                        )
                        assert cursor.fetchone()[0] is False, (role, table, privilege)

            for table in ("public.invite_codes", "public.invite_code_usage"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege('service_role', %s, %s)",
                        (table, privilege),
                    )
                    assert cursor.fetchone()[0] is True, (table, privilege)

            for signature in (
                "public.check_invite_code(text,text,text)",
                "public.consume_invite_code(text,text,text,text,text)",
                "public.validate_invite_code(text,text,text,text)",
            ):
                cursor.execute(
                    """
                    SELECT
                        has_function_privilege('service_role', %s, 'EXECUTE'),
                        has_function_privilege('anon', %s, 'EXECUTE'),
                        has_function_privilege('authenticated', %s, 'EXECUTE')
                    """,
                    (signature, signature, signature),
                )
                assert cursor.fetchone() == (True, False, False), signature

            cursor.execute("SET ROLE anon")
            try:
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT * FROM public.invite_codes")
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute("SELECT * FROM public.check_invite_code('limited-code')")
            finally:
                cursor.execute("RESET ROLE")
