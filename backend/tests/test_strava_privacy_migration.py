from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "backend/sql/147_strava_privacy_package.sql"
SUPABASE = (
    REPO_ROOT
    / "backend/supabase/migrations/20260802200606_strava_privacy_package.sql"
)


def test_strava_privacy_migration_is_exactly_mirrored() -> None:
    assert CANONICAL.read_bytes() == SUPABASE.read_bytes()


def test_strava_privacy_migration_preserves_existing_rides_and_hardens_zones() -> None:
    sql = CANONICAL.read_text(encoding="utf-8")

    assert "default_map_visibility VARCHAR(20)" in sql
    assert "default_map_hide_start_m INTEGER" in sql
    assert "default_map_hide_end_m INTEGER" in sql
    assert "map_visibility VARCHAR(20)" in sql
    assert "map_hide_start_m INTEGER" in sql
    assert "map_hide_end_m INTEGER" in sql
    assert "SET map_visibility = 'hide_entire'" in sql
    assert "ALTER COLUMN map_visibility SET DEFAULT 'hide_start_end'" in sql
    assert "IN ('show_all', 'hide_start_end', 'hide_entire')" in sql
    assert "IN (0, 200, 400, 800, 1600)" in sql
    assert "users_default_map_endpoint_distance_check" in sql
    assert "rides_map_endpoint_distance_check" in sql

    for policy in (
        "privacy_zones_select",
        "privacy_zones_insert",
        "privacy_zones_update",
        "privacy_zones_delete",
    ):
        assert f"DROP POLICY IF EXISTS {policy}" in sql

    assert (
        "REVOKE ALL ON TABLE public.privacy_zones FROM PUBLIC, anon, authenticated"
        in sql
    )
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.privacy_zones TO service_role"
        in sql
    )


def test_strava_privacy_migration_runtime_outcome(postgres_dsn: str) -> None:
    existing_user_id = str(uuid4())
    existing_ride_id = str(uuid4())
    new_user_id = str(uuid4())
    new_ride_id = str(uuid4())
    migration = CANONICAL.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DROP SCHEMA public CASCADE;
                CREATE SCHEMA public;
                DO $$ BEGIN
                    CREATE ROLE anon NOLOGIN;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
                DO $$ BEGIN
                    CREATE ROLE authenticated NOLOGIN;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
                DO $$ BEGIN
                    CREATE ROLE service_role NOLOGIN;
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$;
                ALTER ROLE service_role BYPASSRLS;
                GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

                CREATE TABLE public.users (
                    id UUID PRIMARY KEY,
                    default_ride_visibility VARCHAR(20) NOT NULL DEFAULT 'public'
                );
                CREATE TABLE public.rides (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES public.users(id),
                    visibility VARCHAR(20) NOT NULL DEFAULT 'public'
                );
                CREATE TABLE public.privacy_zones (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES public.users(id)
                );

                ALTER TABLE public.privacy_zones ENABLE ROW LEVEL SECURITY;
                CREATE POLICY privacy_zones_select ON public.privacy_zones
                    FOR SELECT USING (true);
                CREATE POLICY privacy_zones_insert ON public.privacy_zones
                    FOR INSERT WITH CHECK (true);
                CREATE POLICY privacy_zones_update ON public.privacy_zones
                    FOR UPDATE USING (true);
                CREATE POLICY privacy_zones_delete ON public.privacy_zones
                    FOR DELETE USING (true);
                GRANT ALL ON TABLE public.privacy_zones TO anon, authenticated, service_role;
                """
            )
            cursor.execute(
                "INSERT INTO public.users (id) VALUES (%s)",
                (existing_user_id,),
            )
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (existing_ride_id, existing_user_id),
            )

            # A deploy retry is safe and does not loosen the backfill.
            cursor.execute(migration)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT map_visibility, map_hide_start_m, map_hide_end_m
                FROM public.rides
                WHERE id = %s
                """,
                (existing_ride_id,),
            )
            assert cursor.fetchone() == ("hide_entire", 200, 200)

            cursor.execute(
                "INSERT INTO public.users (id) VALUES (%s)",
                (new_user_id,),
            )
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (new_ride_id, new_user_id),
            )
            cursor.execute(
                """
                SELECT
                    u.default_map_visibility,
                    u.default_map_hide_start_m,
                    u.default_map_hide_end_m,
                    r.map_visibility,
                    r.map_hide_start_m,
                    r.map_hide_end_m
                FROM public.users AS u
                JOIN public.rides AS r ON r.user_id = u.id
                WHERE r.id = %s
                """,
                (new_ride_id,),
            )
            assert cursor.fetchone() == (
                "hide_start_end",
                200,
                200,
                "hide_start_end",
                200,
                200,
            )

            cursor.execute(
                """
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'privacy_zones'
                """
            )
            assert cursor.fetchone() == (0,)

            for role in ("anon", "authenticated"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege(%s, 'public.privacy_zones', %s)",
                        (role, privilege),
                    )
                    assert cursor.fetchone() == (False,), (role, privilege)

            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cursor.execute(
                    "SELECT has_table_privilege('service_role', 'public.privacy_zones', %s)",
                    (privilege,),
                )
                assert cursor.fetchone() == (True,), privilege

            cursor.execute("SAVEPOINT invalid_map_visibility")
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE public.rides SET map_visibility = 'full' WHERE id = %s",
                    (new_ride_id,),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT invalid_map_visibility")

            cursor.execute("SAVEPOINT zero_endpoint_distance")
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    """
                    UPDATE public.rides
                    SET map_visibility = 'hide_start_end', map_hide_start_m = 0
                    WHERE id = %s
                    """,
                    (new_ride_id,),
                )
            cursor.execute("ROLLBACK TO SAVEPOINT zero_endpoint_distance")

            cursor.execute("SAVEPOINT browser_read")
            cursor.execute("SET ROLE anon")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("SELECT * FROM public.privacy_zones")
            cursor.execute("ROLLBACK TO SAVEPOINT browser_read")
            cursor.execute("RESET ROLE")

            cursor.execute("SET ROLE service_role")
            cursor.execute("SELECT count(*) FROM public.privacy_zones")
            assert cursor.fetchone() == (0,)
            cursor.execute("RESET ROLE")
