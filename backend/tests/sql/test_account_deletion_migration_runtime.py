from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "backend/sql/152_account_deletion_lifecycle.sql"
HEX_A = "a" * 64
HEX_B = "b" * 64
WALLET = "wallet-before-deletion"


def _bootstrap_pre_152(cursor: Any, *, legacy_completed: bool = False) -> None:
    cursor.execute(
        """
        DROP SCHEMA IF EXISTS public CASCADE;
        CREATE SCHEMA public;
        CREATE SCHEMA IF NOT EXISTS extensions;
        DO $roles$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            CREATE ROLE anon NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            CREATE ROLE authenticated NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            CREATE ROLE service_role NOLOGIN;
          END IF;
        END $roles$;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
          GRANT ALL PRIVILEGES ON TABLES TO service_role;

        CREATE TABLE public.users (
          id UUID PRIMARY KEY, wallet TEXT NOT NULL UNIQUE, email TEXT,
          username TEXT, display_name TEXT, bio TEXT, avatar_url TEXT,
          avatar_storage_path TEXT, avatar_mime_type TEXT,
          avatar_size_bytes BIGINT, avatar_updated_at TIMESTAMPTZ,
          avatar_pending_upload_id UUID, avatar_pending_storage_path TEXT,
          avatar_pending_file_name TEXT, avatar_pending_mime_type TEXT,
          avatar_pending_size_bytes BIGINT, avatar_pending_created_at TIMESTAMPTZ,
          weight_kg NUMERIC, ftp_w INTEGER, weight_kg_source TEXT,
          ftp_w_source TEXT, location TEXT, is_public BOOLEAN DEFAULT TRUE,
          follower_count INTEGER DEFAULT 0, following_count INTEGER DEFAULT 0,
          profile_setup_completed_at TIMESTAMPTZ,
          default_ride_visibility TEXT, default_map_visibility TEXT,
          default_map_hide_start_m INTEGER, default_map_hide_end_m INTEGER,
          moderation_reason TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE public.deletion_requests (
          id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES public.users(id),
          wallet TEXT NOT NULL, requested_at TIMESTAMPTZ DEFAULT now(),
          completed_at TIMESTAMPTZ, status VARCHAR(20) DEFAULT 'pending',
          error_message TEXT
        );
        CREATE TABLE public.deleted_wallets (
          wallet TEXT PRIMARY KEY, deleted_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE public.invite_codes (
          id UUID PRIMARY KEY, code TEXT NOT NULL UNIQUE,
          max_uses INTEGER, current_uses INTEGER NOT NULL DEFAULT 0,
          is_active BOOLEAN NOT NULL DEFAULT TRUE, expires_at TIMESTAMPTZ
        );
        CREATE TABLE public.invite_code_usage (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          code_id UUID NOT NULL REFERENCES public.invite_codes(id),
          wallet TEXT NOT NULL, ip_address TEXT, user_agent TEXT,
          UNIQUE(code_id, wallet)
        );
        CREATE FUNCTION public.consume_invite_code(
          p_code TEXT, p_wallet TEXT, p_ip_address TEXT DEFAULT NULL,
          p_user_agent TEXT DEFAULT NULL
        ) RETURNS TABLE(valid BOOLEAN, message TEXT, code_id UUID)
        LANGUAGE plpgsql AS $function$
        DECLARE
          v_code_record RECORD;
          v_already_used BOOLEAN;
        BEGIN
          p_code := lower(trim(p_code));
          p_wallet := trim(p_wallet);
          IF p_wallet IS NULL OR p_wallet = '' THEN
            RETURN QUERY SELECT FALSE,
              'Wallet required to consume invite code'::TEXT, NULL::UUID;
            RETURN;
          END IF;
          SELECT * INTO v_code_record FROM public.invite_codes
          WHERE lower(code) = p_code FOR UPDATE;
          IF v_code_record IS NULL THEN
            RETURN QUERY SELECT FALSE, 'Invalid invite code'::TEXT, NULL::UUID;
            RETURN;
          END IF;
          IF NOT v_code_record.is_active THEN
            RETURN QUERY SELECT FALSE,
              'Invite code is no longer active'::TEXT, NULL::UUID;
            RETURN;
          END IF;
          IF v_code_record.expires_at IS NOT NULL
             AND v_code_record.expires_at < now() THEN
            RETURN QUERY SELECT FALSE, 'Invite code has expired'::TEXT, NULL::UUID;
            RETURN;
          END IF;
          SELECT EXISTS (
            SELECT 1 FROM public.invite_code_usage AS usage
            WHERE usage.code_id = v_code_record.id AND usage.wallet = p_wallet
          ) INTO v_already_used;
          IF v_already_used THEN
            RETURN QUERY SELECT TRUE,
              'Invite code valid (already used by this wallet)'::TEXT,
              v_code_record.id;
            RETURN;
          END IF;
          IF v_code_record.max_uses IS NOT NULL
             AND v_code_record.current_uses >= v_code_record.max_uses THEN
            RETURN QUERY SELECT FALSE,
              'Invite code has reached maximum uses'::TEXT, NULL::UUID;
            RETURN;
          END IF;
          INSERT INTO public.invite_code_usage (
            code_id, wallet, ip_address, user_agent
          ) VALUES (
            v_code_record.id, p_wallet, p_ip_address, p_user_agent
          );
          UPDATE public.invite_codes
          SET current_uses = current_uses + 1
          WHERE id = v_code_record.id;
          RETURN QUERY SELECT TRUE, 'Invite code consumed'::TEXT, v_code_record.id;
        END
        $function$;
        CREATE TABLE public.user_state (
          user_id UUID PRIMARY KEY, cal_balance NUMERIC NOT NULL DEFAULT 0,
          next_cal_airdrop TIMESTAMPTZ
        );
        CREATE TABLE public.claims (id UUID PRIMARY KEY, user_id UUID NOT NULL);
        CREATE TABLE public.vesting_schedules (id UUID PRIMARY KEY, user_id UUID NOT NULL);
        CREATE TABLE public.rides (
          id UUID PRIMARY KEY, user_id UUID NOT NULL,
          processing_status TEXT DEFAULT 'completed', elapsed_time_seconds INTEGER,
          gps_track JSONB, file_name TEXT, device_name TEXT, error_message TEXT,
          description TEXT, raw_file_path TEXT, raw_file_size_bytes BIGINT,
          file_hash TEXT, avg_hr_bpm NUMERIC, max_hr_bpm NUMERIC,
          sensor_integrity JSONB, import_source TEXT, import_source_id TEXT,
          import_diagnostics JSONB, title TEXT, perceived_exertion INTEGER,
          device_provenance JSONB, device_summary JSONB, weather_temp_c NUMERIC,
          weather_wind_mps NUMERIC, weather_wind_deg NUMERIC, weather_source TEXT,
          laps JSONB, power_balance JSONB, visibility TEXT DEFAULT 'public',
          comments_enabled BOOLEAN DEFAULT TRUE, map_visibility TEXT DEFAULT 'show',
          map_hide_start_m INTEGER DEFAULT 0, map_hide_end_m INTEGER DEFAULT 0
        );
        CREATE TABLE public.vault_stakes (
          id UUID PRIMARY KEY, wallet TEXT, unstaked_at TIMESTAMPTZ,
          points_staked NUMERIC DEFAULT 0, dung_staked NUMERIC DEFAULT 0,
          lp_tokens NUMERIC DEFAULT 0
        );
        CREATE TABLE public.indexed_stakes (
          id UUID PRIMARY KEY, user_pubkey TEXT, cal_staked NUMERIC DEFAULT 0,
          lp_tokens NUMERIC DEFAULT 0, rewards_earned NUMERIC DEFAULT 0,
          amount NUMERIC DEFAULT 0, effective_lp_tokens NUMERIC DEFAULT 0,
          pending_lp_tokens NUMERIC DEFAULT 0,
          pending_effective_week_plus_one NUMERIC DEFAULT 0
        );
        CREATE TABLE public.balance_operations (
          id UUID PRIMARY KEY, user_id UUID, rider_account_id TEXT,
          protocol_wallet TEXT, confirmation_status TEXT,
          projection_status TEXT, rider_state TEXT
        );
        CREATE TABLE public.ride_economic_plans (
          id UUID PRIMARY KEY, user_id UUID, state TEXT,
          terminal_projected_at TIMESTAMPTZ
        );
        CREATE TABLE public.reward_ftp_authorities (id UUID PRIMARY KEY, user_id UUID);
        CREATE TABLE public.economic_events (id UUID PRIMARY KEY, user_id UUID, wallet TEXT);
        CREATE TABLE public.indexed_ride_attestations (id UUID PRIMARY KEY, rider_pubkey TEXT);
        CREATE TABLE public.indexed_staker_allocations (id UUID PRIMARY KEY, staker TEXT);
        CREATE TABLE public.indexed_accounts (id UUID PRIMARY KEY, owner_pubkey TEXT);
        CREATE TABLE public.indexed_rider_souls (id UUID PRIMARY KEY, rider_pubkey TEXT);
        CREATE TABLE public.indexed_cal_mint_receipts (id UUID PRIMARY KEY, rider_pubkey TEXT);
        CREATE TABLE public.indexed_beetle_cards (id UUID PRIMARY KEY, owner_pubkey TEXT);
        CREATE TABLE public.indexed_completions (id UUID PRIMARY KEY, user_pubkey TEXT);
        CREATE TABLE public.indexed_legends (id UUID PRIMARY KEY, holder TEXT, runner_up TEXT);
        CREATE TABLE public.indexed_leaderboards (
          id UUID PRIMARY KEY, entries JSONB NOT NULL DEFAULT '[]'::JSONB
        );
        CREATE TABLE public.indexed_events (
          id UUID PRIMARY KEY, user_pubkey TEXT, fields JSONB NOT NULL DEFAULT '{}'::JSONB
        );
        CREATE TABLE public.indexed_vaults (
          id UUID PRIMARY KEY, minter TEXT, kom_holder TEXT
        );
        CREATE TABLE public.tx_lifecycle (id UUID PRIMARY KEY, wallet TEXT);
        CREATE TABLE public.replay_batches (
          id UUID PRIMARY KEY, wallet TEXT, ride_ids TEXT[] NOT NULL DEFAULT '{}'
        );
        CREATE TABLE public.climb_attestations (id UUID PRIMARY KEY, user_id UUID);
        CREATE TABLE public.settlement_jobs (
          id UUID PRIMARY KEY, state TEXT,
          precondition_intent JSONB NOT NULL DEFAULT '{}'::JSONB
        );

        CREATE TABLE public.auth_refresh_tokens (
          id UUID PRIMARY KEY, wallet TEXT, token_hash TEXT, device_id TEXT
        );
        CREATE TABLE public.auth_nonces (
          id UUID PRIMARY KEY, wallet TEXT, nonce TEXT,
          issued_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
          device_id TEXT, used_at TIMESTAMPTZ
        );
        CREATE TABLE public.auth_identities (
          id UUID PRIMARY KEY, user_id UUID, provider TEXT, provider_subject TEXT
        );
        CREATE TABLE public.strava_connections (
          id UUID PRIMARY KEY, wallet TEXT, athlete_id TEXT, access_token TEXT
        );
        CREATE TABLE public.strava_imported_activities (
          id UUID PRIMARY KEY, strava_connection_id UUID,
          strava_activity_id TEXT, raw_payload JSONB
        );
        CREATE TABLE public.privacy_zones (
          id UUID PRIMARY KEY, user_id UUID, center_lat NUMERIC, center_lon NUMERIC
        );
        CREATE TABLE public.activity_streams (
          id UUID PRIMARY KEY, ride_id UUID, stream_data JSONB
        );
        CREATE TABLE public.gps_points (
          id UUID PRIMARY KEY, ride_id UUID, latitude NUMERIC, longitude NUMERIC
        );
        CREATE TABLE public.activity_tile_samples (
          id UUID PRIMARY KEY, activity_id UUID, tile_id TEXT, sample JSONB
        );
        CREATE TABLE public.wallet_tile_history (
          wallet TEXT, tile_id TEXT, PRIMARY KEY (wallet, tile_id)
        );
        CREATE TABLE public.ride_climb_backfill_reviews (
          id UUID PRIMARY KEY, activity_id UUID
        );
        CREATE TABLE public.ride_media (
          id UUID PRIMARY KEY, user_id UUID, storage_path TEXT
        );
        CREATE TABLE public.mobile_push_devices (
          id UUID PRIMARY KEY, wallet TEXT, device_token TEXT
        );
        CREATE TABLE public.mobile_push_deliveries (
          id UUID PRIMARY KEY, wallet TEXT, device_token TEXT
        );
        CREATE TABLE public.ios_diagnostics (
          id UUID PRIMARY KEY, wallet TEXT, payload JSONB
        );
        CREATE TABLE public.user_profile_snapshots (
          id UUID PRIMARY KEY, wallet TEXT, weight_kg NUMERIC, ftp_watts INTEGER
        );
        CREATE TABLE public.bot_links (
          id UUID PRIMARY KEY, wallet TEXT, chat_id TEXT,
          access_token TEXT, refresh_token TEXT
        );
        CREATE TABLE public.audit_log (
          id UUID PRIMARY KEY, user_id UUID, target_id UUID, metadata JSONB,
          ip_address INET, user_agent TEXT
        );
        CREATE TABLE public.export_requests (
          id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES public.users(id),
          requested_at TIMESTAMPTZ DEFAULT now(), completed_at TIMESTAMPTZ,
          download_url TEXT, expires_at TIMESTAMPTZ,
          status VARCHAR(20) DEFAULT 'pending'
        );
        CREATE TABLE public.segment_efforts (
          id UUID PRIMARY KEY, ride_id UUID NOT NULL, segment_id UUID NOT NULL,
          user_id UUID NOT NULL, started_at TIMESTAMPTZ,
          elapsed_time_sec INTEGER NOT NULL, effort_score DOUBLE PRECISION NOT NULL,
          average_power_w DOUBLE PRECISION, average_hr_bpm DOUBLE PRECISION,
          average_speed_mps DOUBLE PRECISION, elevation_gain_m DOUBLE PRECISION,
          distance_m DOUBLE PRECISION, rank_at_time INTEGER,
          is_pr BOOLEAN DEFAULT FALSE, is_kom BOOLEAN DEFAULT FALSE,
          created_at TIMESTAMPTZ DEFAULT now()
        );
        CREATE TABLE public.leaderboard_entries (
          segment_id UUID, epoch_number BIGINT, user_id UUID,
          rank INTEGER, time_seconds INTEGER, tss NUMERIC,
          PRIMARY KEY (segment_id, epoch_number, user_id)
        );
        CREATE TABLE public.leaderboard_history (
          id UUID PRIMARY KEY, wallet TEXT, bumped_by_wallet TEXT,
          rank INTEGER, best_time_seconds INTEGER, avg_power_w INTEGER,
          entered_at TIMESTAMPTZ, exited_at TIMESTAMPTZ
        );
        CREATE TABLE public.patterns_climb (
          id UUID PRIMARY KEY, activity_id UUID NOT NULL, wallet TEXT NOT NULL,
          arena_id UUID, vert_m NUMERIC, time_s INTEGER,
          avg_power_w NUMERIC, w_per_kg NUMERIC, avg_hr INTEGER,
          start_offset_s INTEGER NOT NULL DEFAULT 0,
          end_offset_s INTEGER NOT NULL DEFAULT 0,
          start_lat NUMERIC, start_lon NUMERIC, end_lat NUMERIC, end_lon NUMERIC,
          signature_hex TEXT,
          match_trace JSONB, reviewed_by TEXT, attribution_summary TEXT,
          abstention_reasons TEXT[]
        );
        CREATE TABLE public.proofs (
          id UUID PRIMARY KEY, ride_id UUID, effort_score NUMERIC,
          signature TEXT, user_id UUID
        );
        CREATE TABLE public.mint_events (
          id UUID PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          proof_id UUID NOT NULL REFERENCES public.proofs(id),
          amount NUMERIC, tx_hash TEXT, status TEXT
        );
        CREATE TABLE public.patterns_steady (
          id UUID PRIMARY KEY, activity_id UUID, wallet TEXT
        );
        CREATE TABLE public.patterns_exploration (
          id UUID PRIMARY KEY, activity_id UUID, wallet TEXT
        );
        CREATE TABLE public.vault_leaderboards (
          vault_signature TEXT, rank INTEGER, wallet TEXT,
          best_time_seconds INTEGER, avg_power_w INTEGER,
          completion_id UUID, achieved_at TIMESTAMPTZ,
          device_name TEXT, activity_id UUID, flagged_by TEXT,
          flag_reason TEXT, PRIMARY KEY (vault_signature, rank)
        );
        CREATE TABLE public.vault_completions (
          id UUID PRIMARY KEY, wallet TEXT, activity_id TEXT,
          on_chain_tx TEXT, completion_receipt_pda TEXT,
          chain_confirmed_at TIMESTAMPTZ,
          chain_confirmation_status TEXT DEFAULT 'legacy_unverified',
          avg_power_w INTEGER, device_name TEXT, validation_notes TEXT,
          on_chain_tx_error TEXT
        );
        CREATE TABLE public.leaderboard_disputes (
          id UUID PRIMARY KEY, disputed_wallet TEXT, disputed_rank INTEGER,
          disputed_time_seconds INTEGER, flagged_by TEXT, flag_reason TEXT,
          evidence_notes TEXT, status TEXT, resolved_by TEXT,
          resolution_notes TEXT
        );
        CREATE TABLE public.swanny_seats (
          id UUID PRIMARY KEY, wallet TEXT, is_active BOOLEAN
        );
        CREATE TABLE public.swanny_elections (
          id UUID PRIMARY KEY, winner_wallet TEXT, runner_up_wallet TEXT
        );
        CREATE TABLE public.local_legend_rollovers (
          id UUID PRIMARY KEY, previous_holder TEXT, winner TEXT,
          runner_up TEXT, tx_signature TEXT, error_message TEXT
        );
        CREATE TABLE public.distribution_receipts (
          id UUID PRIMARY KEY, wallet TEXT, amount NUMERIC
        );
        CREATE TABLE public.vault_distributions (
          id UUID PRIMARY KEY, leaderboard_details JSONB
        );
        CREATE TABLE public.vault_shadow_usdc (
          id UUID PRIMARY KEY, wallet TEXT, settled_at TIMESTAMPTZ
        );
        CREATE TABLE public.wallet_points (
          wallet TEXT PRIMARY KEY, total_points NUMERIC NOT NULL DEFAULT 0,
          points_from_tss NUMERIC NOT NULL DEFAULT 0,
          points_from_creation NUMERIC NOT NULL DEFAULT 0,
          points_from_referral NUMERIC NOT NULL DEFAULT 0,
          points_from_leaderboard NUMERIC NOT NULL DEFAULT 0,
          points_from_staking NUMERIC NOT NULL DEFAULT 0,
          lifetime_points_earned NUMERIC NOT NULL DEFAULT 0,
          referred_by TEXT REFERENCES public.wallet_points(wallet),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE public.points_events (
          id UUID PRIMARY KEY, wallet TEXT NOT NULL REFERENCES public.wallet_points(wallet),
          event_type TEXT NOT NULL, points_delta NUMERIC NOT NULL,
          points_after NUMERIC NOT NULL, reference_type TEXT,
          reference_id TEXT, metadata JSONB DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE public.cal_daily_balances (
          wallet TEXT, date DATE, PRIMARY KEY (wallet, date)
        );
        CREATE TABLE public.vault_cal_contributions (
          id UUID PRIMARY KEY, wallet TEXT, activity_id UUID, cal_amount NUMERIC
        );
        CREATE TABLE public.token_transactions (
          id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES public.users(id),
          tx_signature TEXT, reference_id UUID, metadata JSONB
        );
        CREATE TABLE public.user_stats (user_id UUID, total_rides INTEGER);
        CREATE TABLE public.achievements (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id), ride_id UUID
        );
        CREATE TABLE public.daily_training_load (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id)
        );
        CREATE TABLE public.fitness_metrics (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id)
        );
        CREATE TABLE public.activities (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id),
          actor_id UUID REFERENCES public.users(id), target_id UUID
        );
        CREATE TABLE public.notifications (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id),
          actor_id UUID REFERENCES public.users(id), wallet TEXT
        );
        CREATE TABLE public.notification_preferences (
          user_id UUID PRIMARY KEY REFERENCES public.users(id)
        );
        CREATE TABLE public.comments (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id),
          moderated_by UUID REFERENCES public.users(id), target_id UUID
        );
        CREATE TABLE public.kudos (
          id UUID PRIMARY KEY, user_id UUID REFERENCES public.users(id), target_id UUID
        );
        CREATE TABLE public.follows (
          follower_id UUID REFERENCES public.users(id),
          following_id UUID REFERENCES public.users(id),
          PRIMARY KEY (follower_id, following_id)
        );
        CREATE TABLE public.social_reports (
          id UUID PRIMARY KEY, reporter_id UUID REFERENCES public.users(id),
          target_id UUID, reviewed_by UUID REFERENCES public.users(id)
        );
        CREATE TABLE public.moderation_actions (
          id UUID PRIMARY KEY, actor_id UUID REFERENCES public.users(id),
          target_id TEXT, note TEXT, metadata JSONB
        );
        CREATE TABLE public.waitlist (
          id UUID PRIMARY KEY, email TEXT NOT NULL
        );
        CREATE TABLE public.system_controls (
          id UUID PRIMARY KEY, updated_by UUID NOT NULL REFERENCES public.users(id),
          control_value JSONB
        );
        CREATE TABLE public.climb_reviews (
          id UUID PRIMARY KEY, reviewer_wallet TEXT
        );
        CREATE TABLE public.terrain_cell_history (
          id UUID PRIMARY KEY, admin_wallet TEXT
        );
        """
    )
    if legacy_completed:
        user_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        wallet = f"legacy-{user_id}"
        cursor.execute(
            "INSERT INTO public.users (id, wallet) VALUES (%s, %s)",
            (user_id, wallet),
        )
        cursor.execute(
            """INSERT INTO public.deletion_requests
               (id, user_id, wallet, completed_at, status)
               VALUES (%s, %s, %s, now(), 'completed')""",
            (request_id, user_id, wallet),
        )


def _apply(cursor: Any, *, legacy_completed: bool = False) -> None:
    _bootstrap_pre_152(cursor, legacy_completed=legacy_completed)
    cursor.execute(MIGRATION.read_text(encoding="utf-8"))


def _insert_user(cursor: Any) -> str:
    user_id = str(uuid.uuid4())
    cursor.execute(
        """
        SELECT user_id
        FROM public.br_get_or_create_active_user(
          %s, %s, 'rider@example.com'
        )
        """,
        (user_id, WALLET),
    )
    assert str(cursor.fetchone()[0]) == user_id
    cursor.execute(
        """
        UPDATE public.users
        SET username = 'rider', display_name = 'Rider', bio = 'bio',
            location = 'Boulder', is_public = TRUE,
            follower_count = 3, following_count = 4,
            default_ride_visibility = 'public', default_map_visibility = 'show'
        WHERE id = %s
        """,
        (user_id,),
    )
    return user_id


def _insert_other_user(cursor: Any) -> str:
    user_id = str(uuid.uuid4())
    cursor.execute(
        """
        SELECT user_id
        FROM public.br_get_or_create_active_user(
          %s, 'other-active-wallet', 'other@example.com'
        )
        """,
        (user_id,),
    )
    assert str(cursor.fetchone()[0]) == user_id
    return user_id


def test_get_or_create_reloads_the_winner_after_a_handled_wallet_conflict(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            candidate_id = str(uuid.uuid4())
            winner_id = str(uuid.uuid4())
            wallet = "wallet-created-by-conflicting-insert"
            cursor.execute(
                """
                CREATE FUNCTION public.br_test_inject_user_wallet_conflict()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $function$
                BEGIN
                  IF pg_trigger_depth() = 1
                     AND NEW.wallet = 'wallet-created-by-conflicting-insert' THEN
                    INSERT INTO public.users (id, wallet, email)
                    VALUES (
                      %s,
                      'wallet-created-by-conflicting-insert',
                      'winner@example.com'
                    );
                  END IF;
                  RETURN NEW;
                END
                $function$;
                CREATE TRIGGER aa_br_test_inject_user_wallet_conflict
                BEFORE INSERT ON public.users
                FOR EACH ROW
                EXECUTE FUNCTION public.br_test_inject_user_wallet_conflict();
                """,
                (winner_id,),
            )

            cursor.execute(
                """
                SELECT user_id, was_created
                FROM public.br_get_or_create_active_user(%s, %s, %s)
                """,
                (candidate_id, wallet, "candidate@example.com"),
            )
            returned_user_id, was_created = cursor.fetchone()
            assert str(returned_user_id) == winner_id
            assert was_created is False
            cursor.execute(
                "SELECT id, email FROM public.users WHERE wallet = %s",
                (wallet,),
            )
            stored_user_id, email = cursor.fetchone()
            assert str(stored_user_id) == winner_id
            assert email == "winner@example.com"
            cursor.execute(
                "SELECT current_setting('app.account_deletion_user_create', TRUE)"
            )
            assert cursor.fetchone() == ("",)


def test_auth_authority_gives_tombstone_precedence_over_an_active_user(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            _insert_user(cursor)
            cursor.execute(
                "INSERT INTO public.deleted_wallets (wallet) VALUES (%s)",
                (WALLET,),
            )

            cursor.execute(
                "SELECT user_id, account_state FROM public.br_get_auth_account_authority(%s)",
                (WALLET,),
            )
            assert cursor.fetchone() == (None, "anonymized")


def _create_request(
    cursor: Any,
    user_id: str,
    *,
    request_id: str | None = None,
    token_hash: str | None = HEX_B,
    acknowledged: bool | None = True,
    storage_paths: list[str] | None = None,
    preflight_snapshot: dict[str, Any] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    request_id = request_id or str(uuid.uuid4())
    storage_paths = [] if storage_paths is None else storage_paths
    if preflight_snapshot is None:
        preflight_snapshot = {
            "allowed": True,
            "available": True,
            "destructive_boundary_available": True,
            "blockers": [],
        }
    for storage_path in storage_paths:
        cursor.execute(
            """
            INSERT INTO public.ride_media (id, user_id, storage_path)
            SELECT gen_random_uuid(), %s, %s
            WHERE NOT EXISTS (
              SELECT 1 FROM public.users
              WHERE id = %s
                AND %s IN (avatar_storage_path, avatar_pending_storage_path)
            )
              AND NOT EXISTS (
                SELECT 1 FROM public.rides
                WHERE user_id = %s AND raw_file_path = %s
              )
              AND NOT EXISTS (
                SELECT 1 FROM public.ride_media
                WHERE user_id = %s AND storage_path = %s
              )
            """,
            (
                user_id, storage_path, user_id, storage_path,
                user_id, storage_path, user_id, storage_path,
            ),
        )
    cursor.execute(
        """
        SELECT id, status
        FROM public.create_account_deletion_request(
          %s, %s, %s, %s, %s, %s::JSONB, %s::JSONB
        )
        """,
        (
            request_id, user_id, WALLET, acknowledged, token_hash,
            json.dumps(preflight_snapshot),
            json.dumps({"unuploaded_rides_reviewed": acknowledged}),
        ),
    )
    return request_id, cursor.fetchone()


def _claim(cursor: Any, request_id: str) -> str:
    cursor.execute(
        "SELECT worker_lease_token FROM public.claim_account_deletion_request(%s, %s, 300)",
        (request_id, str(uuid.uuid4())),
    )
    lease_token = cursor.fetchone()[0]
    assert lease_token is not None
    return str(lease_token)


def _storage_removed(cursor: Any, request_id: str, lease_token: str) -> None:
    _authorize_storage(cursor, request_id, lease_token)
    cursor.execute(
        """SELECT storage_completed_at
           FROM public.mark_account_deletion_storage_removed(%s, %s, %s::JSONB)""",
        (
            request_id,
            lease_token,
            json.dumps(
                {
                    "allowed": True,
                    "available": True,
                    "destructive_boundary_available": True,
                    "blockers": [],
                }
            ),
        ),
    )
    assert cursor.fetchone()[0] is not None


def _authorize_storage(
    cursor: Any,
    request_id: str,
    lease_token: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> tuple[str, Any]:
    snapshot = snapshot or {
        "allowed": True,
        "available": True,
        "destructive_boundary_available": True,
        "blockers": [],
    }
    cursor.execute(
        """
        SELECT status, storage_authorized_at
        FROM public.authorize_account_deletion_storage(%s, %s, %s::JSONB)
        """,
        (request_id, lease_token, json.dumps(snapshot)),
    )
    row = cursor.fetchone()
    assert row is not None
    return row


def _assert_error(
    cursor: Any,
    expected_code: str,
    expected_message: str,
    call: Callable[[], None],
) -> None:
    with pytest.raises(psycopg2.Error) as captured:
        call()
    assert captured.value.pgcode == expected_code
    assert expected_message in str(captured.value)


def test_migration_applies_to_representative_pre_152_schema_and_is_retry_safe(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """SELECT relrowsecurity FROM pg_class
                   WHERE oid = 'public.deleted_account_tombstones'::regclass"""
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                """SELECT
                     has_table_privilege('anon', 'public.deleted_account_tombstones', 'SELECT'),
                     has_table_privilege('authenticated', 'public.deleted_account_tombstones', 'SELECT')"""
            )
            assert cursor.fetchone() == (False, False)
            cursor.execute(
                """
                SELECT
                  has_schema_privilege('service_role', 'br_private', 'USAGE'),
                  has_table_privilege(
                    'service_role',
                    'br_private.account_deletion_keyring',
                    'SELECT'
                  ),
                  has_table_privilege(
                    'service_role',
                    'br_private.account_deletion_identity_policy',
                    'SELECT'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.br_account_deletion_wallet_fingerprint(text)',
                    'EXECUTE'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.br_is_account_deleted(text)',
                    'EXECUTE'
                  )
                """
            )
            assert cursor.fetchone() == (False, False, False, False, True)
            cursor.execute(
                """
                SELECT
                  has_table_privilege('service_role', 'public.deletion_requests', 'SELECT'),
                  has_table_privilege('service_role', 'public.deletion_requests', 'INSERT'),
                  has_table_privilege('service_role', 'public.deletion_requests', 'UPDATE'),
                  has_table_privilege('service_role', 'public.deletion_requests', 'DELETE'),
                  has_table_privilege('service_role', 'public.deletion_requests', 'TRUNCATE'),
                  has_table_privilege('service_role', 'public.deleted_account_tombstones', 'SELECT'),
                  has_table_privilege('service_role', 'public.deleted_account_tombstones', 'INSERT'),
                  has_table_privilege('service_role', 'public.deleted_account_tombstones', 'UPDATE'),
                  has_table_privilege('service_role', 'public.deleted_account_tombstones', 'DELETE'),
                  has_table_privilege('service_role', 'public.deleted_account_tombstones', 'TRUNCATE'),
                  has_table_privilege('service_role', 'public.deleted_wallets', 'SELECT'),
                  has_table_privilege('service_role', 'public.deleted_wallets', 'INSERT'),
                  has_table_privilege('service_role', 'public.deleted_wallets', 'UPDATE'),
                  has_table_privilege('service_role', 'public.deleted_wallets', 'DELETE'),
                  has_table_privilege('service_role', 'public.deleted_wallets', 'TRUNCATE'),
                  has_function_privilege(
                    'service_role',
                    'public.consume_invite_code(text,text,text,text)',
                    'EXECUTE'
                  ),
                  pg_catalog.to_regprocedure(
                    'public.consume_invite_code(text,text,text,text,text)'
                  ) IS NULL
                """
            )
            assert cursor.fetchone() == (
                True, False, False, False, False,
                False, False, False, False, False,
                False, False, False, False, False,
                True, True,
            )


def test_migration_uses_pgcrypto_from_its_installed_schema(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap_pre_152(cursor)
            cursor.execute("DROP EXTENSION IF EXISTS pgcrypto CASCADE")
            cursor.execute("CREATE EXTENSION pgcrypto WITH SCHEMA public")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """
                SELECT namespace.nspname
                FROM pg_extension AS extension
                JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
                WHERE extension.extname = 'pgcrypto'
                """
            )
            assert cursor.fetchone() == ("public",)
            cursor.execute(
                "SELECT length(public.br_account_deletion_wallet_fingerprint(%s))",
                (WALLET,),
            )
            assert cursor.fetchone() == (64,)


def test_migration_145_invite_behavior_is_preserved_behind_the_lifecycle_fence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            cursor.execute(
                "SELECT valid, message FROM public.consume_invite_code('missing', '')"
            )
            assert cursor.fetchone() == (
                False,
                "Wallet required to consume invite code",
            )
            invite_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO public.invite_codes (
                  id, code, max_uses, current_uses, is_active
                ) VALUES (%s, 'DEFAULTS', 1, 0, TRUE)
                """,
                (invite_id,),
            )
            cursor.execute(
                "SELECT valid, code_id FROM public.consume_invite_code('DEFAULTS', 'signup-wallet')"
            )
            valid, consumed_code_id = cursor.fetchone()
            assert valid is True
            assert str(consumed_code_id) == invite_id
            cursor.execute(
                "SELECT ip_address, user_agent FROM public.invite_code_usage WHERE code_id = %s",
                (invite_id,),
            )
            assert cursor.fetchone() == (None, None)


def test_guard_capabilities_do_not_leak_across_successful_rpc_calls(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                "SELECT current_setting('app.account_deletion_user_create', TRUE)"
            )
            assert cursor.fetchone() == ("",)
            request_id, _ = _create_request(cursor, user_id)
            cursor.execute(
                "SELECT current_setting('app.account_deletion_request_id', TRUE)"
            )
            assert cursor.fetchone() == ("",)
            _assert_error(
                cursor,
                "55000",
                "account_user_write_fenced",
                lambda: cursor.execute(
                    "UPDATE public.users SET account_state = 'active' WHERE id = %s",
                    (user_id,),
                ),
            )
            cursor.execute(
                "SELECT status FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == ("queued",)


def test_hot_ride_children_install_only_statement_level_fences(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            for table in (
                "activity_streams",
                "gps_points",
                "activity_tile_samples",
                "ride_climb_backfill_reviews",
                "segment_efforts",
            ):
                cursor.execute(
                    """
                    SELECT count(*), bool_and((trigger.tgtype & 1) = 0)
                    FROM pg_trigger AS trigger
                    WHERE trigger.tgrelid = %s::regclass
                      AND trigger.tgname LIKE 'account_deletion_write_fence%%'
                      AND NOT trigger.tgisinternal
                    """,
                    (f"public.{table}",),
                )
                assert cursor.fetchone() == (3, True)


def test_unverified_legacy_processing_request_is_demoted(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap_pre_152(cursor)
            user_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.users (id, wallet) VALUES (%s, %s)",
                (user_id, WALLET),
            )
            cursor.execute(
                """
                INSERT INTO public.deletion_requests (id, user_id, wallet, status)
                VALUES (%s, %s, %s, 'processing')
                """,
                (request_id, user_id, WALLET),
            )

            cursor.execute(MIGRATION.read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT status, contract_version, retryable, completion_verified_at
                FROM public.deletion_requests WHERE id = %s
                """,
                (request_id,),
            )
            assert cursor.fetchone() == (
                "legacy_unverified",
                "account-deletion.legacy",
                False,
                None,
            )


def test_preflight_runs_when_balance_operations_is_not_installed(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap_pre_152(cursor)
            cursor.execute("DROP TABLE public.balance_operations")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            user_id = _insert_user(cursor)
            cursor.execute(
                "SELECT * FROM public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, WALLET),
            )
            assert cursor.fetchone() == ([],)


@pytest.mark.parametrize("owner_state", ["pending", "deleted"])
def test_balance_created_after_152_retains_account_deletion_fence(
    postgres_dsn: str, owner_state: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _bootstrap_pre_152(cursor)
        cursor.execute("DROP TABLE public.balance_operations")
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        cursor.execute((MIGRATION.parent / "172_balance_operations.sql").read_text())
        user_id = _insert_user(cursor)
        if owner_state == "pending":
            _create_request(cursor, user_id)
        else:
            cursor.execute("INSERT INTO public.deleted_wallets(wallet) VALUES (%s)", (WALLET,))
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState):
            cursor.execute("""INSERT INTO public.balance_operations
                (operation_id,rider_account_id,protocol_wallet,action_type,authority_model,idempotency_key)
                VALUES ('late-operation',%s,%s,'stage1_pledge','wallet_boundary','late-key')""",
                (user_id, WALLET))


@pytest.mark.parametrize("failure_path", ["dispatch", "worker"])
def test_retry_requeues_the_same_pending_request_after_failure(
    postgres_dsn: str,
    failure_path: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            if failure_path == "dispatch":
                cursor.execute(
                    "SELECT status FROM public.fail_account_deletion_dispatch(%s)",
                    (request_id,),
                )
            else:
                lease_token = _claim(cursor, request_id)
                cursor.execute(
                    "SELECT status FROM public.fail_account_deletion_request(%s, %s, 'worker_error')",
                    (request_id, lease_token),
                )
            assert cursor.fetchone() == ("failed_retryable",)
            cursor.execute(
                """
                SELECT status FROM public.retry_account_deletion_request(
                  %s, %s::JSONB
                )
                """,
                (
                    request_id,
                    json.dumps(
                        {
                            "allowed": True,
                            "available": True,
                            "destructive_boundary_available": True,
                            "blockers": [],
                        }
                    ),
                ),
            )
            assert cursor.fetchone() == ("queued",)
            cursor.execute(
                "SELECT account_state, account_deletion_request_id FROM public.users WHERE id = %s",
                (user_id,),
            )
            state, locked_request_id = cursor.fetchone()
            assert state == "deletion_pending"
            assert str(locked_request_id) == request_id


def test_json_anonymizer_preserves_empty_containers(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            cursor.execute(
                """
                SELECT public.br_jsonb_replace_exact_string(
                  '{"wallet":"old","empty_array":[],"empty_object":{}}'::JSONB,
                  'old', 'anonymous'
                )
                """
            )
            assert cursor.fetchone()[0] == {
                "wallet": "anonymous",
                "empty_array": [],
                "empty_object": {},
            }


def test_legacy_completed_request_is_not_trusted_as_completed(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor, legacy_completed=True)
            cursor.execute(
                "SELECT status, completion_verified_at, failure_code FROM public.deletion_requests"
            )
            assert cursor.fetchone() == (
                "legacy_unverified", None, "legacy_completion_unverified"
            )


def test_legacy_request_does_not_prevent_a_verified_v1_completion(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap_pre_152(cursor)
            user_id = str(uuid.uuid4())
            legacy_request_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.users (id, wallet, email) VALUES (%s, %s, %s)",
                (user_id, WALLET, "legacy@example.com"),
            )
            cursor.execute(
                """
                INSERT INTO public.deletion_requests (
                  id, user_id, wallet, status, error_message
                ) VALUES (%s, %s, %s, 'pending', %s)
                """,
                (legacy_request_id, user_id, WALLET, f"failed for {WALLET}"),
            )
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "queued"
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)
            cursor.execute(
                """
                SELECT user_id, wallet, status, error_message
                FROM public.deletion_requests WHERE id = %s
                """,
                (legacy_request_id,),
            )
            assert cursor.fetchone() == (None, None, "legacy_unverified", None)


@pytest.mark.parametrize(
    "late_write",
    [
        "INSERT INTO public.economic_events (id, user_id, wallet) VALUES (gen_random_uuid(), NULL, %s)",
        "INSERT INTO public.indexed_accounts (id, owner_pubkey) VALUES (gen_random_uuid(), %s)",
    ],
)
def test_completed_wallet_cannot_be_reintroduced_by_a_late_writer(
    postgres_dsn: str,
    late_write: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)
            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(late_write, (WALLET,)),
            )


def test_legacy_deleted_wallet_blocks_late_projector_writes(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            cursor.execute(
                "INSERT INTO public.deleted_wallets (wallet) VALUES (%s)",
                (WALLET,),
            )

            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(
                    "INSERT INTO public.economic_events (id, wallet) VALUES (gen_random_uuid(), %s)",
                    (WALLET,),
                ),
            )


@pytest.mark.parametrize("column", ["minter", "kom_holder"])
def test_completed_wallet_blocks_late_indexed_vault_replay(
    postgres_dsn: str,
    column: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)

            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(
                    f"INSERT INTO public.indexed_vaults (id, {column}) VALUES (gen_random_uuid(), %s)",
                    (WALLET,),
                ),
            )


@pytest.mark.parametrize("token_hash", [None, "b" * 63, "b" * 65, "z" * 64])
def test_request_requires_exact_32_byte_hex_status_digest(
    postgres_dsn: str,
    token_hash: str | None,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            _assert_error(
                cursor,
                "22023",
                "invalid_account_deletion_request",
                lambda: _create_request(cursor, user_id, token_hash=token_hash),
            )
            cursor.execute(
                "SELECT account_state FROM public.users WHERE id = %s", (user_id,)
            )
            assert cursor.fetchone() == ("active",)


def test_duplicate_request_id_rejects_a_different_status_token(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, first = _create_request(cursor, user_id)
            cursor.execute(
                "SELECT blockers FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert first[1:] == ("queued",), cursor.fetchone()[0]
            _, duplicate = _create_request(cursor, user_id, request_id=request_id)
            assert duplicate == first
            _assert_error(
                cursor,
                "23505",
                "account_deletion_request_id_conflict",
                lambda: _create_request(
                    cursor, user_id, request_id=request_id, token_hash="c" * 64
                ),
            )


@pytest.mark.parametrize("acknowledged", [False, None])
def test_request_requires_unuploaded_rides_acknowledgement(
    postgres_dsn: str,
    acknowledged: bool | None,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            _assert_error(
                cursor,
                "22023",
                "invalid_account_deletion_request",
                lambda: _create_request(cursor, user_id, acknowledged=acknowledged),
            )
            cursor.execute("SELECT count(*) FROM public.deletion_requests")
            assert cursor.fetchone() == (0,)


def test_request_storage_inventory_is_derived_inside_the_fencing_transaction(
    postgres_dsn: str,
) -> None:
    storage_path = "rides/server-authoritative.fit"
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                """
                INSERT INTO public.rides (
                  id, user_id, processing_status, raw_file_path
                ) VALUES (gen_random_uuid(), %s, 'completed', %s)
                """,
                (user_id, storage_path),
            )

            request_id, request = _create_request(cursor, user_id)

            assert request[1] == "queued"
            cursor.execute(
                "SELECT storage_paths FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == ([storage_path],)


def test_storage_phase_requires_a_confirmed_receipt_for_every_path(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(
                cursor, user_id, storage_paths=["rides/private.fit"]
            )
            lease_token = _claim(cursor, request_id)
            _assert_error(
                cursor,
                "55000",
                "stale_or_unsafe_account_deletion_storage_phase",
                lambda: _storage_removed(cursor, request_id, lease_token),
            )
            cursor.execute(
                """SELECT storage_receipts
                   FROM public.record_account_deletion_storage_receipt(
                     %s, %s, 'rides/private.fit', 'confirmed_absent'
                   )""",
                (request_id, lease_token),
            )
            assert cursor.fetchone() == ({"rides/private.fit": "confirmed_absent"},)
            _storage_removed(cursor, request_id, lease_token)


def test_storage_authorization_atomically_blocks_late_database_authority(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            cursor.execute(
                "ALTER TABLE public.swanny_seats DISABLE TRIGGER account_deletion_write_fence"
            )
            cursor.execute(
                """
                INSERT INTO public.swanny_seats (id, wallet, is_active)
                VALUES (gen_random_uuid(), %s, TRUE)
                """,
                (WALLET,),
            )
            cursor.execute(
                "ALTER TABLE public.swanny_seats ENABLE TRIGGER account_deletion_write_fence"
            )

            status, authorized_at = _authorize_storage(
                cursor, request_id, lease_token
            )
            assert status == "blocked"
            assert authorized_at is None
            cursor.execute(
                "SELECT account_state, account_deletion_request_id FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == ("active", None)


def test_inactive_local_legend_seat_is_scrubbed_by_the_shared_identity_policy(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            seat_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.swanny_seats (id, wallet, is_active) VALUES (%s, %s, FALSE)",
                (seat_id, WALLET),
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "queued"
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)
            cursor.execute(
                "SELECT wallet, is_active FROM public.swanny_seats WHERE id = %s",
                (seat_id,),
            )
            scrubbed_wallet, is_active = cursor.fetchone()
            assert scrubbed_wallet.startswith("anonymous:")
            assert is_active is False
            cursor.execute(
                "SELECT count(*) FROM public.swanny_seats WHERE wallet = %s",
                (WALLET,),
            )
            assert cursor.fetchone() == (0,)


def test_failure_before_authorization_unlocks_but_after_authorization_recovers_locked(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            cursor.execute(
                "SELECT status FROM public.fail_account_deletion_request(%s, %s, 'pre_storage')",
                (request_id, lease_token),
            )
            assert cursor.fetchone() == ("failed_retryable",)
            cursor.execute(
                "SELECT retryable FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT account_state, account_deletion_request_id FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == ("active", None)

            cursor.execute(
                """
                SELECT status FROM public.retry_account_deletion_request(%s, %s::JSONB)
                """,
                (
                    request_id,
                    json.dumps(
                        {
                            "available": True,
                            "destructive_boundary_available": True,
                            "blockers": [],
                        }
                    ),
                ),
            )
            assert cursor.fetchone() == ("queued",)
            recovery_lease = _claim(cursor, request_id)
            assert _authorize_storage(cursor, request_id, recovery_lease)[0] == "processing"
            cursor.execute(
                "SELECT status FROM public.fail_account_deletion_request(%s, %s, 'post_storage')",
                (request_id, recovery_lease),
            )
            assert cursor.fetchone() == ("failed_retryable",)
            cursor.execute(
                "SELECT retryable FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == (False,)
            cursor.execute(
                "SELECT account_state, account_deletion_request_id FROM public.users WHERE id = %s",
                (user_id,),
            )
            state, linked_request = cursor.fetchone()
            assert state == "deletion_pending"
            assert str(linked_request) == request_id
            cursor.execute(
                "SELECT id FROM public.list_recoverable_account_deletions(100)"
            )
            assert request_id in {str(row[0]) for row in cursor.fetchall()}
            assert _claim(cursor, request_id)


def test_storage_receipts_require_authorization_and_confirmed_absence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(
                cursor, user_id, storage_paths=["rides/private.fit"]
            )
            lease_token = _claim(cursor, request_id)
            _assert_error(
                cursor,
                "55000",
                "stale_or_invalid_account_deletion_storage_receipt",
                lambda: cursor.execute(
                    """
                    SELECT * FROM public.record_account_deletion_storage_receipt(
                      %s, %s, 'rides/private.fit', 'confirmed_absent'
                    )
                    """,
                    (request_id, lease_token),
                ),
            )
            assert _authorize_storage(cursor, request_id, lease_token)[0] == "processing"
            _assert_error(
                cursor,
                "55000",
                "stale_or_invalid_account_deletion_storage_receipt",
                lambda: cursor.execute(
                    """
                    SELECT * FROM public.record_account_deletion_storage_receipt(
                      %s, %s, 'rides/private.fit', 'deleted'
                    )
                    """,
                    (request_id, lease_token),
                ),
            )
            cursor.execute(
                """
                SELECT storage_receipts
                FROM public.record_account_deletion_storage_receipt(
                  %s, %s, 'rides/private.fit', 'confirmed_absent'
                )
                """,
                (request_id, lease_token),
            )
            assert cursor.fetchone() == ({"rides/private.fit": "confirmed_absent"},)


def test_storage_phase_rejects_a_snapshot_that_claims_allowed_with_blockers(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            unsafe_snapshot = json.dumps(
                {
                    "allowed": True,
                    "available": True,
                    "destructive_boundary_available": True,
                    "blockers": [
                        {
                            "code": "policy_review_required",
                            "category": "policy",
                            "source": "on_chain_deletion_boundary",
                            "action": "contact_support",
                        }
                    ],
                }
            )

            _assert_error(
                cursor,
                "55000",
                "stale_or_unsafe_account_deletion_storage_phase",
                lambda: cursor.execute(
                    "SELECT * FROM public.mark_account_deletion_storage_removed(%s, %s, %s::JSONB)",
                    (request_id, lease_token, unsafe_snapshot),
                ),
            )
            cursor.execute(
                "SELECT storage_authorized_at, storage_completed_at FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == (None, None)
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_finalizer_rejects_a_stored_preflight_snapshot_with_blockers(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                """
                UPDATE public.deletion_requests
                SET preflight_checked_at = now(),
                    preflight_snapshot = %s::JSONB
                WHERE id = %s
                """,
                (
                    json.dumps(
                        {
                            "allowed": True,
                            "available": True,
                            "destructive_boundary_available": True,
                            "blockers": [
                                {
                                    "code": "claim_remains",
                                    "category": "claim",
                                    "source": "settlement_jobs",
                                    "action": "contact_support",
                                }
                            ],
                        }
                    ),
                    request_id,
                ),
            )

            _assert_error(
                cursor,
                "55000",
                "account_deletion_finalization_precondition_failed",
                lambda: cursor.execute(
                    "SELECT * FROM public.finalize_account_anonymization(%s, %s, %s)",
                    (request_id, user_id, lease_token),
                ),
            )
            cursor.execute("SELECT wallet, account_state FROM public.users WHERE id = %s", (user_id,))
            assert cursor.fetchone() == (WALLET, "deletion_pending")
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_retry_cannot_mutate_the_durable_unuploaded_rides_acknowledgement(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            cursor.execute(
                "SELECT status FROM public.fail_account_deletion_request(%s, %s, 'worker_error')",
                (request_id, lease_token),
            )
            assert cursor.fetchone() == ("failed_retryable",)
            cursor.execute(
                "UPDATE public.deletion_requests SET unuploaded_rides_acknowledged = FALSE WHERE id = %s",
                (request_id,),
            )
            _assert_error(
                cursor,
                "55000",
                "account_deletion_acknowledgement_required",
                lambda: cursor.execute(
                    "SELECT * FROM public.retry_account_deletion_request(%s, %s::JSONB)",
                    (
                        request_id,
                        json.dumps(
                            {
                                "available": True,
                                "destructive_boundary_available": True,
                                "blockers": [],
                            }
                        ),
                    ),
                ),
            )
            cursor.execute(
                "SELECT status, unuploaded_rides_acknowledged FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == ("failed_retryable", False)
            cursor.execute("SELECT wallet, account_state FROM public.users WHERE id = %s", (user_id,))
            assert cursor.fetchone() == (WALLET, "active")
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_retry_at_the_on_chain_boundary_raises_without_mutating_durable_evidence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            cursor.execute(
                "SELECT status FROM public.fail_account_deletion_request(%s, %s, 'worker_error')",
                (request_id, lease_token),
            )
            assert cursor.fetchone() == ("failed_retryable",)
            cursor.execute(
                """
                SELECT status, unuploaded_rides_acknowledged, preflight_snapshot,
                       blockers, storage_paths, storage_receipts, failure_code,
                       updated_at
                FROM public.deletion_requests WHERE id = %s
                """,
                (request_id,),
            )
            before = cursor.fetchone()
            _assert_error(
                cursor,
                "55000",
                "account_deletion_retry_requires_support",
                lambda: cursor.execute(
                    "SELECT * FROM public.retry_account_deletion_request(%s, %s::JSONB)",
                    (
                        request_id,
                        json.dumps(
                            {
                                "available": True,
                                "destructive_boundary_available": False,
                                "blockers": [
                                    {
                                        "code": "boundary_unavailable",
                                        "category": "chain",
                                        "source": "on_chain_deletion_boundary",
                                        "action": "contact_support",
                                    }
                                ],
                            }
                        ),
                    ),
                ),
            )
            cursor.execute(
                """
                SELECT status, unuploaded_rides_acknowledged, preflight_snapshot,
                       blockers, storage_paths, storage_receipts, failure_code,
                       updated_at
                FROM public.deletion_requests WHERE id = %s
                """,
                (request_id,),
            )
            assert cursor.fetchone() == before
            cursor.execute(
                "SELECT account_state, account_deletion_request_id FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == ("active", None)


def test_retry_refreshes_storage_inventory_before_authorization(
    postgres_dsn: str,
) -> None:
    old_path = "rides/original.fit"
    new_path = "rides/created-while-blocked.fit"
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id, storage_paths=[old_path])
            lease_token = _claim(cursor, request_id)
            cursor.execute(
                "SELECT status FROM public.mark_account_deletion_blocked(%s, %s::JSONB, %s)",
                (
                    request_id,
                    json.dumps(
                        [
                            {
                                "code": "claim_remains",
                                "category": "processing",
                                "source": "rides",
                                "action": "retry",
                            }
                        ]
                    ),
                    lease_token,
                ),
            )
            assert cursor.fetchone() == ("blocked",)
            cursor.execute(
                """
                INSERT INTO public.rides (
                  id, user_id, processing_status, raw_file_path
                ) VALUES (gen_random_uuid(), %s, 'completed', %s)
                """,
                (user_id, new_path),
            )

            cursor.execute(
                """
                SELECT status, storage_paths, storage_receipts, storage_completed_at
                FROM public.retry_account_deletion_request(
                  %s, %s::JSONB
                )
                """,
                (
                    request_id,
                    json.dumps(
                        {
                            "allowed": True,
                            "available": True,
                            "destructive_boundary_available": True,
                            "blockers": [],
                        }
                    ),
                ),
            )
            assert cursor.fetchone() == (
                "queued",
                [new_path, old_path],
                {},
                None,
            )
            retry_lease = _claim(cursor, request_id)
            assert _authorize_storage(cursor, request_id, retry_lease)[0] == "processing"
            cursor.execute(
                """
                SELECT storage_receipts
                FROM public.record_account_deletion_storage_receipt(
                  %s, %s, %s, 'confirmed_absent'
                )
                """,
                (request_id, retry_lease, old_path),
            )
            _assert_error(
                cursor,
                "55000",
                "stale_or_unsafe_account_deletion_storage_phase",
                lambda: _storage_removed(cursor, request_id, retry_lease),
            )
            cursor.execute(
                """
                SELECT storage_receipts
                FROM public.record_account_deletion_storage_receipt(
                  %s, %s, %s, 'confirmed_absent'
                )
                """,
                (request_id, retry_lease, new_path),
            )
            _storage_removed(cursor, request_id, retry_lease)


@pytest.mark.parametrize(
    ("blocker_insert", "expected_status"),
    [
        (
            "INSERT INTO public.user_state (user_id, cal_balance) VALUES (%s, 1)",
            "blocked",
        ),
        (
            "INSERT INTO public.claims (id, user_id) VALUES (gen_random_uuid(), %s)",
            "needs_support",
        ),
        (
            "INSERT INTO public.vault_stakes (id, wallet, points_staked) VALUES (gen_random_uuid(), %s, 1)",
            "blocked",
        ),
    ],
)
def test_server_preflight_durably_blocks_database_value_or_claims(
    postgres_dsn: str,
    blocker_insert: str,
    expected_status: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            parameter = WALLET if "vault_stakes" in blocker_insert else user_id
            cursor.execute(blocker_insert, (parameter,))
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == expected_status
            cursor.execute(
                "SELECT blockers, retryable FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            blockers, retryable = cursor.fetchone()
            assert blockers
            assert retryable is (expected_status == "blocked")
            cursor.execute(
                "SELECT account_state FROM public.users WHERE id = %s", (user_id,)
            )
            assert cursor.fetchone() == ("active",)


@pytest.mark.parametrize(
    ("insert_sql", "parameter_kind", "source"),
    [
        (
            "INSERT INTO public.vault_stakes (id, wallet, points_staked) "
            "VALUES (gen_random_uuid(), %s, 1)",
            "wallet",
            "vault_stakes",
        ),
        (
            "INSERT INTO public.indexed_stakes (id, user_pubkey, cal_staked) "
            "VALUES (gen_random_uuid(), %s, 1)",
            "wallet",
            "indexed_stakes",
        ),
        (
            "INSERT INTO public.balance_operations (id, rider_account_id) "
            "VALUES (gen_random_uuid(), %s)",
            "user",
            "balance_operations",
        ),
        (
            "INSERT INTO public.ride_economic_plans (id, user_id, state) "
            "VALUES (gen_random_uuid(), %s, 'pending')",
            "user",
            "ride_economic_plans",
        ),
        (
            "INSERT INTO public.reward_ftp_authorities (id, user_id) "
            "VALUES (gen_random_uuid(), %s)",
            "user",
            "reward_ftp_authorities",
        ),
    ],
)
def test_database_blocker_sources_are_not_double_counted(
    postgres_dsn: str,
    insert_sql: str,
    parameter_kind: str,
    source: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                insert_sql,
                (WALLET if parameter_kind == "wallet" else user_id,),
            )
            cursor.execute(
                "SELECT public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, WALLET),
            )
            blockers = cursor.fetchone()[0]
            assert sum(blocker.get("source") == source for blocker in blockers) == 1


def test_request_creation_deduplicates_reader_and_database_blockers(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                "INSERT INTO public.user_state (user_id, cal_balance) VALUES (%s, 1)",
                (user_id,),
            )
            cursor.execute(
                "SELECT public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, WALLET),
            )
            reader_blockers = cursor.fetchone()[0]
            assert sum(
                blocker.get("source") == "app_cal_state"
                for blocker in reader_blockers
            ) == 1

            request_id, request = _create_request(
                cursor,
                user_id,
                preflight_snapshot={
                    "allowed": False,
                    "available": True,
                    "destructive_boundary_available": True,
                    "blockers": reader_blockers,
                },
            )
            assert request[1] == "blocked"
            cursor.execute(
                "SELECT blockers FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            stored_blockers = cursor.fetchone()[0]
            assert sum(
                blocker.get("source") == "app_cal_state"
                for blocker in stored_blockers
            ) == 1


def test_request_retry_deduplicates_reader_and_database_blockers(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                "INSERT INTO public.user_state (user_id, cal_balance) VALUES (%s, 1)",
                (user_id,),
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "blocked"
            cursor.execute(
                "SELECT public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, WALLET),
            )
            reader_blockers = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT status
                FROM public.retry_account_deletion_request(%s, %s::JSONB)
                """,
                (
                    request_id,
                    json.dumps(
                        {
                            "allowed": False,
                            "available": True,
                            "destructive_boundary_available": True,
                            "blockers": reader_blockers,
                        }
                    ),
                ),
            )
            assert cursor.fetchone() == ("blocked",)
            cursor.execute(
                "SELECT blockers FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            stored_blockers = cursor.fetchone()[0]
            assert sum(
                blocker.get("source") == "app_cal_state"
                for blocker in stored_blockers
            ) == 1


@pytest.mark.parametrize(
    ("insert_sql", "source"),
    [
        (
            "INSERT INTO public.settlement_jobs (id, state, precondition_intent) "
            "VALUES (gen_random_uuid(), 'confirmed', jsonb_build_object('wallet', %s))",
            "wallet_keyed_provenance",
        ),
        (
            "INSERT INTO public.indexed_events (id, user_pubkey) "
            "VALUES (gen_random_uuid(), %s)",
            "indexed_events",
        ),
        (
            "INSERT INTO public.indexed_vaults (id, minter) "
            "VALUES (gen_random_uuid(), %s)",
            "indexed_vaults",
        ),
        (
            "INSERT INTO public.tx_lifecycle (id, wallet) "
            "VALUES (gen_random_uuid(), %s)",
            "tx_lifecycle",
        ),
        (
            "INSERT INTO public.replay_batches (id, wallet) "
            "VALUES (gen_random_uuid(), %s)",
            "replay_batches",
        ),
    ],
)
def test_unratified_wallet_provenance_blocks_before_destruction(
    postgres_dsn: str,
    insert_sql: str,
    source: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(insert_sql, (WALLET,))
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "needs_support"
            cursor.execute(
                "SELECT blockers FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            sources = {blocker["source"] for blocker in cursor.fetchone()[0]}
            assert source in sources
            cursor.execute(
                "SELECT wallet, account_state FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == (WALLET, "active")
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_legacy_mint_schema_is_linked_through_proof_and_blocks_destruction(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            proof_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.proofs (id, user_id) VALUES (%s, %s)",
                (proof_id, user_id),
            )
            cursor.execute(
                "INSERT INTO public.mint_events (id, proof_id) VALUES (gen_random_uuid(), %s)",
                (proof_id,),
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "needs_support"
            cursor.execute(
                "SELECT blockers FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            sources = {blocker["source"] for blocker in cursor.fetchone()[0]}
            assert {"proofs", "mint_events"}.issubset(sources)
            cursor.execute(
                "SELECT wallet, account_state FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == (WALLET, "active")
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_active_request_fences_a_concurrent_value_creating_write(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            _claim(cursor, request_id)
            _assert_error(
                cursor,
                "55000",
                "account_identity_write_fenced",
                lambda: cursor.execute(
                    "INSERT INTO public.claims (id, user_id) VALUES (%s, %s)",
                    (str(uuid.uuid4()), user_id),
                ),
            )


@pytest.mark.parametrize(
    "update_sql",
    [
        "UPDATE public.users SET id = gen_random_uuid() WHERE id = %s",
        "UPDATE public.users SET anonymous_marker = gen_random_uuid() WHERE id = %s",
        "UPDATE public.users SET account_deleted_at = now() WHERE id = %s",
        "UPDATE public.users SET account_deletion_locked_at = now() WHERE id = %s",
        "UPDATE public.users SET account_deletion_request_id = gen_random_uuid() WHERE id = %s",
    ],
)
def test_active_user_cannot_rewrite_database_owned_lifecycle_identity(
    postgres_dsn: str,
    update_sql: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            _assert_error(
                cursor,
                "55000",
                "account_user_write_fenced",
                lambda: cursor.execute(update_sql, (user_id,)),
            )


def test_active_request_fences_owner_changing_update_from_pending_user(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            other_user_id = _insert_other_user(cursor)
            activity_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.activities (id, user_id) VALUES (%s, %s)",
                (activity_id, user_id),
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "queued"
            _assert_error(
                cursor,
                "55000",
                "account_identity_write_fenced",
                lambda: cursor.execute(
                    "UPDATE public.activities SET user_id = %s WHERE id = %s",
                    (other_user_id, activity_id),
                ),
            )


@pytest.mark.parametrize(
    ("table", "late_insert", "expected_status"),
    [
        (
            "claims",
            "INSERT INTO public.claims (id, user_id) VALUES (gen_random_uuid(), %s)",
            "needs_support",
        ),
        (
            "user_state",
            "INSERT INTO public.user_state (user_id, cal_balance) VALUES (%s, 1)",
            "needs_support",
        ),
    ],
)
def test_final_preflight_blocks_claims_or_value_after_worker_preflight(
    postgres_dsn: str,
    table: str,
    late_insert: str,
    expected_status: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                f"ALTER TABLE public.{table} DISABLE TRIGGER account_deletion_write_fence"
            )
            cursor.execute(late_insert, (user_id,))
            cursor.execute(
                f"ALTER TABLE public.{table} ENABLE TRIGGER account_deletion_write_fence"
            )
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == (expected_status,)
            cursor.execute(
                "SELECT wallet, account_state FROM public.users WHERE id = %s",
                (user_id,),
            )
            # Storage authorization is irreversible: a new database blocker
            # requires support without restoring identity access.
            assert cursor.fetchone() == (WALLET, "deletion_pending")


def test_counterparty_social_writes_toward_a_pending_rider_remain_available(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            pending_user_id = _insert_user(cursor)
            actor_user_id = _insert_other_user(cursor)
            _create_request(cursor, pending_user_id)

            cursor.execute(
                "INSERT INTO public.follows (follower_id, following_id) VALUES (%s, %s)",
                (actor_user_id, pending_user_id),
            )
            cursor.execute(
                """
                INSERT INTO public.notifications (id, user_id, actor_id, wallet)
                VALUES (gen_random_uuid(), %s, %s, %s)
                """,
                (pending_user_id, actor_user_id, WALLET),
            )
            cursor.execute(
                """
                UPDATE public.users
                SET follower_count = follower_count + 1,
                    updated_at = clock_timestamp()
                WHERE id = %s
                """,
                (pending_user_id,),
            )
            cursor.execute(
                "SELECT count(*) FROM public.follows WHERE following_id = %s",
                (pending_user_id,),
            )
            assert cursor.fetchone() == (1,)

            _assert_error(
                cursor,
                "55000",
                "account_identity_write_fenced",
                lambda: cursor.execute(
                    "INSERT INTO public.follows (follower_id, following_id) VALUES (%s, %s)",
                    (pending_user_id, actor_user_id),
                ),
            )
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_finalizer_requires_storage_completion_and_current_lease(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _assert_error(
                cursor,
                "55000",
                "account_deletion_finalization_precondition_failed",
                lambda: cursor.execute(
                    "SELECT * FROM public.finalize_account_anonymization(%s, %s, %s)",
                    (request_id, user_id, lease_token),
                ),
            )
            wrong_lease = str(uuid.uuid4())
            _assert_error(
                cursor,
                "55000",
                "stale_account_deletion_lease",
                lambda: cursor.execute(
                    "SELECT * FROM public.fail_account_deletion_request(%s, %s, 'worker_error')",
                    (request_id, wrong_lease),
                ),
            )
            cursor.execute(
                "SELECT status FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == ("processing",)
            _assert_error(
                cursor,
                "55000",
                "stale_or_unsafe_account_deletion_storage_authorization",
                lambda: _storage_removed(cursor, request_id, wrong_lease),
            )
            _storage_removed(cursor, request_id, lease_token)
            _assert_error(
                cursor,
                "55000",
                "account_deletion_finalization_precondition_failed",
                lambda: cursor.execute(
                    "SELECT * FROM public.finalize_account_anonymization(%s, %s, %s)",
                    (request_id, user_id, wrong_lease),
                ),
            )
            cursor.execute(
                """UPDATE public.deletion_requests
                   SET unuploaded_rides_acknowledged = FALSE WHERE id = %s""",
                (request_id,),
            )
            _assert_error(
                cursor,
                "55000",
                "account_deletion_finalization_precondition_failed",
                lambda: cursor.execute(
                    "SELECT * FROM public.finalize_account_anonymization(%s, %s, %s)",
                    (request_id, user_id, lease_token),
                ),
            )
            cursor.execute(
                "SELECT wallet, account_state FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == (WALLET, "deletion_pending")
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)


def test_clean_account_atomically_anonymizes_and_completes(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                "INSERT INTO public.privacy_zones (id, user_id) VALUES (%s, %s)",
                (str(uuid.uuid4()), user_id),
            )

            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                """
                SELECT status, storage_authorized_at, completed_at,
                       completion_verified_at
                FROM public.finalize_account_anonymization(%s, %s, %s)
                """,
                (request_id, user_id, lease_token),
            )
            status, authorized_at, completed_at, verified_at = cursor.fetchone()
            assert status == "completed"
            assert authorized_at is not None
            assert completed_at is not None
            assert verified_at is not None

            cursor.execute(
                """
                SELECT id, wallet, email, username, display_name, bio, location,
                       account_state, anonymous_marker, account_deleted_at
                FROM public.users WHERE anonymous_marker IS NOT NULL
                """
            )
            user = cursor.fetchone()
            assert str(user[0]) != user_id
            assert user[1].startswith("anonymous:")
            assert user[2:7] == (None, None, None, None, None)
            assert user[7] == "anonymized"
            assert user[8] is not None and user[9] is not None

            cursor.execute(
                """
                SELECT wallet_fingerprint, anonymous_marker, deletion_request_id
                FROM public.deleted_account_tombstones
                """
            )
            fingerprint, marker, tombstone_request_id = cursor.fetchone()
            cursor.execute(
                "SELECT public.br_account_deletion_wallet_fingerprint(%s)",
                (WALLET,),
            )
            assert fingerprint == cursor.fetchone()[0]
            assert fingerprint != HEX_A
            assert marker == user[8]
            assert marker == user[0]
            assert str(tombstone_request_id) == request_id
            cursor.execute(
                "SELECT user_id, wallet, status FROM public.deletion_requests WHERE id = %s",
                (request_id,),
            )
            assert cursor.fetchone() == (None, None, "completed")
            cursor.execute("SELECT count(*) FROM public.deleted_wallets")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM public.privacy_zones WHERE user_id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == (0,)

            # A later migration replay must not demote a completion that this
            # authoritative finalizer verified.
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """SELECT status, storage_authorized_at, completion_verified_at
                   FROM public.deletion_requests WHERE id = %s""",
                (request_id,),
            )
            replayed_status, replayed_authorized_at, replayed_verified_at = cursor.fetchone()
            assert replayed_status == "completed"
            assert replayed_authorized_at == authorized_at
            assert replayed_verified_at == verified_at


def test_completed_wallet_cannot_bypass_database_tombstone(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            invite_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.invite_codes (id, code) VALUES (%s, 'AFTER-DELETE')",
                (invite_id,),
            )
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)

            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(
                    "SELECT * FROM public.br_issue_auth_nonce(%s, %s, 'late', now(), now() + interval '5 minutes', 'phone')",
                    (str(uuid.uuid4()), WALLET),
                ),
            )
            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(
                    "SELECT * FROM public.consume_invite_code('AFTER-DELETE', %s, '127.0.0.1', 'agent')",
                    (WALLET,),
                ),
            )
            _assert_error(
                cursor,
                "55000",
                "account_deleted",
                lambda: cursor.execute(
                    "SELECT * FROM public.br_get_or_create_active_user(%s, %s, 'late@example.com')",
                    (str(uuid.uuid4()), WALLET),
                ),
            )
            cursor.execute(
                "SELECT public.br_is_account_deleted(%s)",
                (WALLET,),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT count(*) FROM public.users WHERE wallet = %s",
                (WALLET,),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM public.auth_nonces WHERE wallet = %s",
                (WALLET,),
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT count(*) FROM public.invite_code_usage WHERE wallet = %s",
                (WALLET,),
            )
            assert cursor.fetchone() == (0,)


def test_completion_rolls_back_when_broad_residue_verifier_finds_personal_data(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                "CREATE TABLE public.late_personal_store (id UUID PRIMARY KEY, owner_note TEXT)"
            )
            cursor.execute(
                "INSERT INTO public.late_personal_store VALUES (gen_random_uuid(), %s)",
                (f"unhandled:{WALLET}",),
            )
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            _assert_error(
                cursor,
                "55000",
                "account_deletion_personal_residue",
                lambda: cursor.execute(
                    "SELECT * FROM public.finalize_account_anonymization(%s, %s, %s)",
                    (request_id, user_id, lease_token),
                ),
            )
            cursor.execute(
                "SELECT wallet, account_state FROM public.users WHERE id = %s",
                (user_id,),
            )
            assert cursor.fetchone() == (WALLET, "deletion_pending")
            cursor.execute(
                """
                SELECT status, storage_authorized_at, completed_at,
                       completion_verified_at
                FROM public.deletion_requests WHERE id = %s
                """,
                (request_id,),
            )
            status, authorized_at, completed_at, verified_at = cursor.fetchone()
            assert status == "processing"
            assert authorized_at is not None
            assert completed_at is None
            assert verified_at is None
            cursor.execute("SELECT count(*) FROM public.deleted_account_tombstones")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM public.late_personal_store")
            assert cursor.fetchone() == (1,)


def test_residue_scan_skips_a_physically_empty_heap_but_scans_it_after_insert(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            anonymous_marker = str(uuid.uuid4())
            cursor.execute(
                "CREATE TABLE public.late_empty_identity_store (id UUID PRIMARY KEY, owner_note TEXT)"
            )
            cursor.execute(
                "SELECT pg_relation_size('public.late_empty_identity_store'::regclass)"
            )
            assert cursor.fetchone() == (0,)
            cursor.execute(
                """
                SELECT public.br_account_deletion_personal_residue(
                  %s, %s, 'rider@example.com', ARRAY[]::UUID[], %s
                )
                """,
                (user_id, WALLET, anonymous_marker),
            )
            empty_residue = cursor.fetchone()[0]
            assert not any(
                entry.get("table") == "late_empty_identity_store"
                for entry in empty_residue
            )

            cursor.execute(
                "INSERT INTO public.late_empty_identity_store VALUES (gen_random_uuid(), %s)",
                (f"original:{WALLET}",),
            )
            cursor.execute(
                "SELECT pg_relation_size('public.late_empty_identity_store'::regclass)"
            )
            assert cursor.fetchone()[0] > 0
            cursor.execute(
                """
                SELECT public.br_account_deletion_personal_residue(
                  %s, %s, 'rider@example.com', ARRAY[]::UUID[], %s
                )
                """,
                (user_id, WALLET, anonymous_marker),
            )
            nonempty_residue = cursor.fetchone()[0]
            assert any(
                entry.get("table") == "late_empty_identity_store"
                for entry in nonempty_residue
            )


def test_finalizer_serializes_with_concurrent_account_recreation(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as setup_connection:
        with setup_connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            request_id, _ = _create_request(cursor, user_id)
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)

    finalizer_connection = psycopg2.connect(postgres_dsn)
    finalizer_connection.autocommit = False
    recreation_errors: list[BaseException] = []
    recreation_results: list[tuple[Any, ...]] = []
    recreation_started = threading.Event()

    def recreate() -> None:
        connection = psycopg2.connect(postgres_dsn)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                recreation_started.set()
                cursor.execute(
                    "SELECT * FROM public.br_get_or_create_active_user(%s, %s, 'late@example.com')",
                    (str(uuid.uuid4()), WALLET),
                )
                recreation_results.append(cursor.fetchone())
        except BaseException as exc:  # captured for assertion in the test thread
            recreation_errors.append(exc)
        finally:
            connection.close()

    try:
        with finalizer_connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)

        thread = threading.Thread(target=recreate, daemon=True)
        thread.start()
        assert recreation_started.wait(timeout=2)
        thread.join(timeout=0.2)
        assert thread.is_alive(), "recreation did not wait for the deletion wallet lock"

        finalizer_connection.commit()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert recreation_results == []
        assert len(recreation_errors) == 1
        assert isinstance(recreation_errors[0], psycopg2.Error)
        assert recreation_errors[0].pgcode == "55000"
        assert "account_deleted" in str(recreation_errors[0])
    finally:
        if not finalizer_connection.closed:
            finalizer_connection.rollback()
            finalizer_connection.close()


def test_zero_balance_settled_points_history_rekeys_without_fk_breakage(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                """
                INSERT INTO public.wallet_points (
                  wallet, total_points, points_from_tss, lifetime_points_earned
                ) VALUES (%s, 0, 7, 7)
                """,
                (WALLET,),
            )
            cursor.execute(
                """
                INSERT INTO public.points_events (
                  id, wallet, event_type, points_delta, points_after,
                  reference_type, reference_id, metadata
                ) VALUES
                  (%s, %s, 'TSS_EARN', 7, 7, 'ride', %s, %s::JSONB),
                  (%s, %s, 'ADMIN_ADJUST', -7, 0, 'account', %s, %s::JSONB)
                """,
                (
                    str(uuid.uuid4()), WALLET, str(uuid.uuid4()),
                    json.dumps({"wallet": WALLET}),
                    str(uuid.uuid4()), WALLET, user_id,
                    json.dumps({"user_id": user_id}),
                ),
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "queued"
            lease_token = _claim(cursor, request_id)
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)
            cursor.execute(
                """
                SELECT wallet, total_points, points_from_tss,
                       lifetime_points_earned
                FROM public.wallet_points
                """
            )
            anonymous_wallet, total, from_tss, lifetime = cursor.fetchone()
            assert anonymous_wallet.startswith("anonymous:")
            assert (total, from_tss, lifetime) == (0, 7, 7)
            cursor.execute(
                """
                SELECT count(*), min(wallet), bool_and(reference_id IS NULL),
                       bool_and(metadata = '{}'::JSONB), sum(points_delta)
                FROM public.points_events
                """
            )
            assert cursor.fetchone() == (2, anonymous_wallet, True, True, 0)


def test_full_personal_fixture_is_removed_and_ratified_history_is_anonymized(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _apply(cursor)
            user_id = _insert_user(cursor)
            _insert_other_user(cursor)
            ride_id = str(uuid.uuid4())
            segment_id = str(uuid.uuid4())
            connection_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO public.rides (
                  id, user_id, processing_status, elapsed_time_seconds,
                  gps_track, file_name, device_name, raw_file_path,
                  file_hash, avg_hr_bpm, title, description
                ) VALUES (
                  %s, %s, 'completed', 3600, '[{"lat":40,"lon":-105}]'::JSONB,
                  'private.fit', 'Personal Head Unit', 'rides/private.fit',
                  'private-hash', 151, 'Private ride', 'Private notes'
                );
                INSERT INTO public.auth_refresh_tokens
                  (id, wallet, token_hash, device_id)
                  VALUES (gen_random_uuid(), %s, 'refresh-secret', 'phone-1');
                INSERT INTO public.auth_identities
                  (id, user_id, provider, provider_subject)
                  VALUES (gen_random_uuid(), %s, 'privy', 'provider-subject');
                INSERT INTO public.strava_connections
                  (id, wallet, athlete_id, access_token)
                  VALUES (%s, %s, 'athlete-1', 'provider-token');
                INSERT INTO public.strava_imported_activities
                  (id, strava_connection_id, strava_activity_id, raw_payload)
                  VALUES (gen_random_uuid(), %s, 'strava-ride', '{"private":true}');
                INSERT INTO public.privacy_zones
                  (id, user_id, center_lat, center_lon)
                  VALUES (gen_random_uuid(), %s, 40, -105);
                INSERT INTO public.gps_points
                  (id, ride_id, latitude, longitude)
                  VALUES (gen_random_uuid(), %s, 40, -105);
                INSERT INTO public.activity_streams
                  (id, ride_id, stream_data)
                  VALUES (gen_random_uuid(), %s, '{"watts":[300]}');
                INSERT INTO public.activity_tile_samples
                  (id, activity_id, tile_id, sample)
                  VALUES (gen_random_uuid(), %s, 'tile-private', '{"lat":40}');
                INSERT INTO public.wallet_tile_history (wallet, tile_id)
                  VALUES (%s, 'tile-private');
                INSERT INTO public.ride_climb_backfill_reviews (id, activity_id)
                  VALUES (gen_random_uuid(), %s);
                INSERT INTO public.ride_media (id, user_id, storage_path)
                  VALUES (gen_random_uuid(), %s, 'media/private.jpg');
                INSERT INTO public.mobile_push_devices (id, wallet, device_token)
                  VALUES (gen_random_uuid(), %s, 'push-secret');
                INSERT INTO public.mobile_push_deliveries (id, wallet, device_token)
                  VALUES (gen_random_uuid(), %s, 'push-secret');
                INSERT INTO public.ios_diagnostics (id, wallet, payload)
                  VALUES (gen_random_uuid(), %s, '{"device":"private"}');
                INSERT INTO public.user_profile_snapshots
                  (id, wallet, weight_kg, ftp_watts)
                  VALUES (gen_random_uuid(), %s, 72, 300);
                INSERT INTO public.bot_links
                  (id, wallet, chat_id, access_token, refresh_token)
                  VALUES (gen_random_uuid(), %s, 'chat-private', 'a', 'r');
                INSERT INTO public.export_requests
                  (id, user_id, download_url, status)
                  VALUES (gen_random_uuid(), %s, 'data:private', 'completed');
                INSERT INTO public.waitlist (id, email)
                  VALUES (gen_random_uuid(), 'rider@example.com');
                """,
                (
                    ride_id, user_id, WALLET, user_id, connection_id, WALLET,
                    connection_id, user_id, ride_id, ride_id, ride_id, WALLET,
                    ride_id, user_id, WALLET, WALLET, WALLET, WALLET, WALLET,
                    user_id,
                ),
            )
            cursor.execute(
                "SELECT nonce FROM public.br_issue_auth_nonce(%s, %s, 'nonce-private', now(), now() + interval '5 minutes', 'phone-1')",
                (str(uuid.uuid4()), WALLET),
            )
            assert cursor.fetchone()[0] == "nonce-private"
            invite_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO public.invite_codes (id, code) VALUES (%s, 'DELETE-ME')",
                (invite_id,),
            )
            cursor.execute(
                "SELECT valid FROM public.consume_invite_code('DELETE-ME', %s, '127.0.0.1', 'agent')",
                (WALLET,),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                """
                INSERT INTO public.achievements (id, user_id, ride_id)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.daily_training_load (id, user_id)
                  VALUES (gen_random_uuid(), %s);
                INSERT INTO public.fitness_metrics (id, user_id)
                  VALUES (gen_random_uuid(), %s);
                INSERT INTO public.activities (id, user_id, target_id)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.notifications (id, user_id, actor_id, wallet)
                  VALUES (gen_random_uuid(), %s, %s, %s);
                INSERT INTO public.notification_preferences (user_id) VALUES (%s);
                INSERT INTO public.comments (id, user_id, target_id)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.kudos (id, user_id, target_id)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.social_reports (id, reporter_id, target_id, reviewed_by)
                  VALUES (gen_random_uuid(), %s, %s, %s);
                INSERT INTO public.audit_log
                  (id, user_id, target_id, metadata, ip_address, user_agent)
                  VALUES (gen_random_uuid(), %s, %s, %s::JSONB, '127.0.0.1', 'private-agent');
                INSERT INTO public.moderation_actions
                  (id, actor_id, target_id, note, metadata)
                  VALUES (gen_random_uuid(), %s, %s, 'private-note', %s::JSONB);
                INSERT INTO public.system_controls (id, updated_by, control_value)
                  VALUES (gen_random_uuid(), %s, '{}'::JSONB);
                """,
                (
                    user_id, ride_id, user_id, user_id, user_id, ride_id,
                    user_id, user_id, WALLET, user_id, user_id, ride_id,
                    user_id, ride_id, user_id, ride_id, user_id,
                    user_id, ride_id, json.dumps({"wallet": WALLET}),
                    user_id, ride_id, json.dumps({"user_id": user_id}),
                    user_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.segment_efforts (
                  id, ride_id, segment_id, user_id, started_at,
                  elapsed_time_sec, effort_score, average_power_w,
                  average_hr_bpm, average_speed_mps, elevation_gain_m,
                  distance_m, rank_at_time, is_pr
                ) VALUES (
                  gen_random_uuid(), %s, %s, %s, now(), 321, 99, 300,
                  151, 8, 120, 1000, 2, TRUE
                );
                INSERT INTO public.leaderboard_entries
                  (segment_id, epoch_number, user_id, rank, time_seconds, tss)
                  VALUES (%s, 10, %s, 2, 321, 77);
                INSERT INTO public.patterns_climb (
                  id, activity_id, wallet, vert_m, time_s, avg_power_w,
                  w_per_kg, avg_hr, start_offset_s, end_offset_s,
                  start_lat, start_lon, end_lat, end_lon, signature_hex,
                  match_trace, reviewed_by, attribution_summary, abstention_reasons
                ) VALUES (
                  gen_random_uuid(), %s, %s, 120, 321, 300, 4.2, 151,
                  10, 331, 40, -105, 40.1, -105.1, 'ride-signature',
                  %s::JSONB, %s, 'private-route', ARRAY['private']
                );
                INSERT INTO public.patterns_steady (id, activity_id, wallet)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.patterns_exploration (id, activity_id, wallet)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.leaderboard_history (
                  id, wallet, rank, best_time_seconds, avg_power_w,
                  entered_at, exited_at
                ) VALUES (gen_random_uuid(), %s, 2, 321, 300, now(), now());
                INSERT INTO public.vault_leaderboards (
                  vault_signature, rank, wallet, best_time_seconds,
                  avg_power_w, achieved_at, device_name, activity_id,
                  flagged_by, flag_reason
                ) VALUES ('vault-1', 2, %s, 321, 300, now(), 'private-device',
                          %s, %s, 'private-reason');
                INSERT INTO public.vault_completions (
                  id, wallet, activity_id, chain_confirmation_status,
                  avg_power_w, device_name, validation_notes
                ) VALUES (gen_random_uuid(), %s, %s, 'legacy_unverified',
                          300, 'private-device', 'private-note');
                INSERT INTO public.leaderboard_disputes (
                  id, disputed_wallet, disputed_rank, disputed_time_seconds,
                  flagged_by, flag_reason, evidence_notes, status,
                  resolved_by, resolution_notes
                ) VALUES (gen_random_uuid(), %s, 2, 321, %s, 'private',
                          'private', 'resolved', %s, 'private');
                INSERT INTO public.swanny_seats (id, wallet, is_active)
                  VALUES (gen_random_uuid(), %s, FALSE);
                INSERT INTO public.swanny_elections
                  (id, winner_wallet, runner_up_wallet)
                  VALUES (gen_random_uuid(), %s, %s);
                INSERT INTO public.local_legend_rollovers
                  (id, previous_holder, winner, runner_up)
                  VALUES (gen_random_uuid(), %s, %s, %s);
                INSERT INTO public.distribution_receipts (id, wallet, amount)
                  VALUES (gen_random_uuid(), %s, 12);
                INSERT INTO public.vault_distributions (id, leaderboard_details)
                  VALUES (gen_random_uuid(), %s::JSONB);
                INSERT INTO public.vault_shadow_usdc (id, wallet, settled_at)
                  VALUES (gen_random_uuid(), %s, now());
                INSERT INTO public.cal_daily_balances (wallet, date)
                  VALUES (%s, CURRENT_DATE);
                INSERT INTO public.vault_cal_contributions
                  (id, wallet, activity_id, cal_amount)
                  VALUES (gen_random_uuid(), %s, %s, 5);
                INSERT INTO public.token_transactions
                  (id, user_id, reference_id, metadata)
                  VALUES (gen_random_uuid(), %s, %s, %s::JSONB);
                INSERT INTO public.user_state (user_id, cal_balance)
                  VALUES (%s, 0);
                INSERT INTO public.climb_reviews (id, reviewer_wallet)
                  VALUES (gen_random_uuid(), %s);
                INSERT INTO public.terrain_cell_history (id, admin_wallet)
                  VALUES (gen_random_uuid(), %s);
                """,
                (
                    # segment effort and leaderboard entry
                    ride_id, segment_id, user_id, segment_id, user_id,
                    # climb, steady, exploration, leaderboard history
                    ride_id, WALLET, json.dumps({"wallet": WALLET}), WALLET,
                    ride_id, WALLET, ride_id, WALLET, WALLET,
                    # vault leaderboard, completion, dispute
                    WALLET, ride_id, WALLET, WALLET, ride_id,
                    WALLET, WALLET, WALLET,
                    # seat, election, rollover
                    WALLET, WALLET, WALLET, WALLET, WALLET, WALLET,
                    # receipt, distribution JSON, shadow, daily balance
                    WALLET, json.dumps({"winner": WALLET, "empty": []}),
                    WALLET, WALLET,
                    # CAL contribution, token transaction, user state
                    WALLET, ride_id, user_id, ride_id,
                    json.dumps({"wallet": WALLET}), user_id,
                    # retained operational references are anonymized
                    WALLET, WALLET,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.vault_leaderboards (
                  vault_signature, rank, wallet, best_time_seconds,
                  achieved_at, flagged_by, flag_reason
                ) VALUES (
                  'vault-1', 3, 'other-active-wallet', 654, now(), %s,
                  'deleter-authored-reason'
                )
                """,
                (WALLET,),
            )

            request_id, request = _create_request(
                cursor,
                user_id,
                storage_paths=["rides/private.fit", "media/private.jpg"],
            )
            assert request[1] == "queued"
            lease_token = _claim(cursor, request_id)
            assert _authorize_storage(cursor, request_id, lease_token)[0] == "processing"
            for path in ("rides/private.fit", "media/private.jpg"):
                cursor.execute(
                    "SELECT storage_receipts FROM public.record_account_deletion_storage_receipt(%s, %s, %s, 'confirmed_absent')",
                    (request_id, lease_token, path),
                )
            _storage_removed(cursor, request_id, lease_token)
            cursor.execute(
                "SELECT status FROM public.finalize_account_anonymization(%s, %s, %s)",
                (request_id, user_id, lease_token),
            )
            assert cursor.fetchone() == ("completed",)

            for table in (
                "rides", "auth_refresh_tokens", "auth_nonces", "auth_identities",
                "strava_connections", "strava_imported_activities", "privacy_zones",
                "gps_points", "activity_streams", "activity_tile_samples",
                "wallet_tile_history", "ride_climb_backfill_reviews", "ride_media",
                "mobile_push_devices", "mobile_push_deliveries", "ios_diagnostics",
                "user_profile_snapshots", "bot_links", "export_requests", "waitlist",
                "invite_code_usage", "achievements", "daily_training_load",
                "fitness_metrics", "activities", "notifications",
                "notification_preferences", "comments", "kudos", "social_reports",
                "patterns_steady", "patterns_exploration",
            ):
                cursor.execute(f"SELECT count(*) FROM public.{table}")
                assert cursor.fetchone() == (0,), table

            cursor.execute(
                "SELECT id, wallet FROM public.users WHERE account_state = 'anonymized'"
            )
            marker, anonymous_wallet = cursor.fetchone()
            assert anonymous_wallet == f"anonymous:{marker}"
            cursor.execute("SELECT updated_by FROM public.system_controls")
            assert cursor.fetchone() == (marker,)
            cursor.execute("SELECT reviewer_wallet FROM public.climb_reviews")
            assert cursor.fetchone() == (anonymous_wallet,)
            cursor.execute("SELECT admin_wallet FROM public.terrain_cell_history")
            assert cursor.fetchone() == (anonymous_wallet,)
            cursor.execute(
                """
                SELECT user_id, ride_id, elapsed_time_sec, effort_score,
                       average_power_w, average_hr_bpm, rank_at_time, is_pr
                FROM public.segment_efforts
                """
            )
            assert cursor.fetchone() == (
                marker, None, 321, None, None, None, 2, True
            )
            cursor.execute(
                "SELECT user_id, rank, time_seconds, tss FROM public.leaderboard_entries"
            )
            assert cursor.fetchone() == (marker, 2, 321, None)
            cursor.execute(
                """
                SELECT wallet, activity_id, time_s, avg_power_w, avg_hr,
                       start_lat, signature_hex, match_trace, reviewed_by
                FROM public.patterns_climb
                """
            )
            assert cursor.fetchone() == (
                anonymous_wallet, None, 321, None, None, None, None, None, None
            )
            cursor.execute(
                "SELECT wallet, rank, best_time_seconds, avg_power_w FROM public.leaderboard_history"
            )
            assert cursor.fetchone() == (anonymous_wallet, 2, 321, None)
            cursor.execute(
                """
                SELECT wallet, best_time_seconds, avg_power_w, device_name,
                       activity_id, flagged_by, flag_reason
                FROM public.vault_leaderboards
                ORDER BY rank
                """
            )
            assert cursor.fetchall() == [
                (anonymous_wallet, 321, None, None, None, anonymous_wallet, None),
                ('other-active-wallet', 654, None, None, None, anonymous_wallet, None),
            ]
            cursor.execute(
                "SELECT wallet, amount FROM public.distribution_receipts"
            )
            assert cursor.fetchone() == (anonymous_wallet, 12)
            cursor.execute(
                "SELECT leaderboard_details FROM public.vault_distributions"
            )
            assert cursor.fetchone()[0] == {"winner": anonymous_wallet, "empty": []}
            cursor.execute(
                "SELECT user_id, reference_id, tx_signature, metadata FROM public.token_transactions"
            )
            assert cursor.fetchone() == (marker, None, None, {})
            cursor.execute(
                "SELECT public.br_account_deletion_personal_residue(%s, %s, %s, %s::UUID[], %s)",
                (user_id, WALLET, "rider@example.com", [ride_id], marker),
            )
            assert cursor.fetchone() == ([],)
