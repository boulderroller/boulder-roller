from pathlib import Path

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import isolated_postgres_dsn, postgres_dsn

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "backend/sql/180_privacy_hardening.sql"
MIRROR = ROOT / "backend/supabase/migrations/20261021180000_180_privacy_hardening.sql"


def test_privacy_migration_runtime_repeats_and_keeps_photo_publication_atomic(isolated_postgres_dsn):
    sql = CANONICAL.read_text()
    assert sql.startswith("SET LOCAL lock_timeout = '5s';")
    assert CANONICAL.read_bytes() == MIRROR.read_bytes()
    connection = psycopg2.connect(isolated_postgres_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                DO $$ BEGIN CREATE ROLE service_role BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                CREATE TABLE public.users(id UUID PRIMARY KEY, avatar_storage_path TEXT, avatar_pending_storage_path TEXT);
                CREATE TABLE public.rides(id UUID PRIMARY KEY, user_id UUID, raw_file_path TEXT);
                CREATE TABLE public.vault_creation_handoffs(id UUID);
                CREATE TABLE public.ride_effort_completion_windows(id UUID);
                CREATE TABLE public.social_reports(id UUID PRIMARY KEY);
            """)
            for table in ("efforts", "candidates", "source_envelopes", "ratchets", "pending_promotions"):
                cursor.execute(f"CREATE TABLE public.reward_threshold_{table}(id UUID PRIMARY KEY)")
                cursor.execute(f"REVOKE ALL ON public.reward_threshold_{table} FROM PUBLIC, anon, authenticated, service_role")
            cursor.execute((ROOT / "backend/sql/104_ride_media.sql").read_text())
            cursor.execute("CREATE FUNCTION public.complete_ride_media_upload(uuid,uuid,integer) RETURNS SETOF public.ride_media LANGUAGE sql AS 'SELECT * FROM public.ride_media'")
            # Baseline schema has neither the privileged reader nor the new
            # publication RPC. Exercise those refusals before applying the fix.
            cursor.execute("SELECT has_table_privilege('service_role', 'reward_threshold_efforts', 'SELECT')")
            assert cursor.fetchone() == (False,)
            with pytest.raises(psycopg2.errors.UndefinedFunction):
                cursor.execute("SELECT * FROM complete_sanitized_ride_media_upload(NULL::uuid,NULL::uuid,1,'path',1,1)")
            for _ in range(2):
                cursor.execute("BEGIN;" + sql + "COMMIT;")
            cursor.execute("SELECT to_regprocedure('public.complete_ride_media_upload(uuid,uuid,integer)')")
            assert cursor.fetchone() == (None,)
            cursor.execute("SELECT has_table_privilege('service_role', 'reward_threshold_efforts', 'SELECT'), has_table_privilege('anon', 'reward_threshold_efforts', 'SELECT'), has_table_privilege('service_role', 'reward_threshold_efforts', 'UPDATE')")
            assert cursor.fetchone() == (True, False, False)
            cursor.execute("SELECT has_function_privilege('anon', 'complete_sanitized_ride_media_upload(uuid,uuid,integer,text,integer,integer,text)', 'EXECUTE')")
            assert cursor.fetchone() == (False,)
            owner = "11111111-1111-4111-8111-111111111111"
            ride = "22222222-2222-4222-8222-222222222222"
            media = "33333333-3333-4333-8333-333333333333"
            prior = "44444444-4444-4444-8444-444444444444"
            cursor.execute("INSERT INTO users(id) VALUES (%s); INSERT INTO rides(id) VALUES (%s)", (owner, ride))
            cursor.execute("INSERT INTO ride_media(id,ride_id,user_id,storage_path,mime_type,size_bytes,role,upload_status) VALUES (%s,%s,%s,'ride-media/upload.jpg','image/jpeg',100,'cover','uploading'), (%s,%s,%s,'ride-media/old.jpg','image/jpeg',100,'cover','ready')", (media, ride, owner, prior, ride, owner))
            cursor.execute("SELECT id FROM complete_sanitized_ride_media_upload(%s,%s,90,'ride-media/upload.jpg',16,24)", (media, ride))
            assert cursor.fetchall() == []
            cursor.execute("SELECT storage_path,upload_status,width,height FROM complete_sanitized_ride_media_upload(%s,%s,90,'sanitized/ride-media/upload.jpg',16,24)", (media, ride))
            assert cursor.fetchone() == ("sanitized/ride-media/upload.jpg", "ready", 16, 24)
            cursor.execute("SELECT id FROM ride_media WHERE role='cover' AND upload_status='ready'")
            assert [str(row[0]) for row in cursor.fetchall()] == [media]
            cursor.execute("UPDATE users SET avatar_storage_path='sanitized/avatars/new.jpg', avatar_cleanup_storage_paths=ARRAY['avatars/old.jpg'] WHERE id=%s", (owner,))
            cursor.execute("UPDATE rides SET user_id=%s,raw_file_path='rides/raw.fit' WHERE id=%s", (owner, ride))
            cursor.execute("SELECT br_account_deletion_storage_paths(%s)", (owner,))
            assert cursor.fetchone()[0] == ['avatars/new.jpg', 'avatars/old.jpg', 'ride-media/old.jpg', 'ride-media/upload.jpg', 'rides/raw.fit', 'sanitized/avatars/new.jpg', 'sanitized/avatars/old.jpg', 'sanitized/ride-media/old.jpg', 'sanitized/ride-media/upload.jpg']
    finally:
        connection.close()
