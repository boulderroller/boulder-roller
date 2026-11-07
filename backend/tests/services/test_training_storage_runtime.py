"""Real PostgreSQL training-only boundaries, with synthetic users/rides."""

import json
import re
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    postgres_dsn,
    isolated_postgres_dsn,
)

SQL = Path(__file__).resolve().parents[2] / "sql"
EVIDENCE = {"best_180s_w": 350, "best_420s_w": 293, "best_900s_w": 270}


def function(file, name):
    source = (SQL / file).read_text()
    return re.search(
        r"CREATE OR REPLACE FUNCTION public\." + name + r"\([\s\S]*?\$\$;", source
    )[0]


@pytest.fixture
def pre_cleanup_db(isolated_postgres_dsn):
    conn = psycopg2.connect(isolated_postgres_dsn)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("""DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
        END $$;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
        CREATE TABLE users(id uuid PRIMARY KEY, account_state text DEFAULT 'active');
        CREATE TABLE rides(id uuid PRIMARY KEY, user_id uuid REFERENCES users, started_at timestamptz,
            raw_file_path text, file_type text, processing_status text DEFAULT 'completed', phase1_completed_at timestamptz,
            phase2_completed_at timestamptz, phase3_completed_at timestamptz, tss numeric DEFAULT 77,
            cal_earned numeric DEFAULT 91);
        CREATE TABLE reward_ftp_authorities(id uuid PRIMARY KEY, user_id uuid, ftp_w int,
            effective_at timestamptz, verified_at timestamptz DEFAULT now(), source text, verified_by text);
        CREATE TABLE patterns_climb(id uuid PRIMARY KEY, activity_id uuid REFERENCES rides);
        CREATE TABLE ride_economic_plans(ride_id uuid, lease_expires_at timestamptz);
        CREATE TABLE reward_threshold_provisional_holds(id uuid,ride_id uuid);
        CREATE TABLE reward_threshold_release_batch_items(id uuid,hold_id uuid);
        CREATE TABLE reward_threshold_release_item_claims(batch_item_id uuid,lease_expires_at timestamptz,consumed_snapshot_id uuid,terminal_disposition text);
        CREATE TABLE reward_threshold_release_snapshots(id uuid,ride_id uuid);
        CREATE TABLE reward_threshold_release_executions(snapshot_id uuid,lease_expires_at timestamptz);
        ALTER TABLE users ADD wallet TEXT, ADD anonymous_marker UUID, ADD account_deleted_at TIMESTAMPTZ,
            ADD account_deletion_locked_at TIMESTAMPTZ, ADD account_deletion_request_id UUID;
        ALTER TABLE rides ADD economic_tss NUMERIC, ADD reward_ftp_w INTEGER, ADD reward_ftp_source TEXT,
            ADD reward_ftp_authority_id UUID, ADD reward_ftp_policy_version TEXT, ADD reward_ftp_activity_started_at TIMESTAMPTZ,
            ADD upload_verified_at TIMESTAMPTZ, ADD threshold_recording_source TEXT, ADD threshold_power_source_id UUID,
            ADD threshold_source_identity_complete BOOLEAN, ADD threshold_source_evidence JSONB,
            ADD normalized_power_raw_w DOUBLE PRECISION, ADD normalized_power_duration_s INTEGER, ADD effort_spans_ms JSONB;
        CREATE TABLE deletion_requests(id UUID PRIMARY KEY,user_id UUID,wallet TEXT,status TEXT,storage_authorized_at TIMESTAMPTZ);
        CREATE TABLE deleted_account_tombstones(wallet_fingerprint TEXT);
        CREATE TABLE deleted_wallets(wallet TEXT);
        """)
        c.execute(
            function(
                "154_derived_threshold_authority.sql", "derive_reward_threshold_cp"
            )
        )
        c.execute(
            function(
                "165_threshold_fit_plausibility.sql",
                "reward_threshold_fit_is_plausible",
            )
        )
        c.execute((SQL / "166_training_read_metrics.sql").read_text())
        deletion = "152_account_deletion_lifecycle.sql"
        c.execute((SQL / deletion).read_text().split("-- A retention decision")[0])
        for file, names in [
            (
                deletion,
                [
                    "br_account_deletion_wallet_fingerprint",
                    "br_account_deletion_write_fence_active",
                    "account_deletion_write_fence",
                    "br_user_account_lifecycle_fence",
                ],
            ),
            (
                "154_derived_threshold_authority.sql",
                ["enforce_ride_reward_ftp_snapshot", "enforce_ride_threshold_evidence"],
            ),
            (
                "155_threshold_provisional_hold.sql",
                ["enforce_ride_threshold_release_power_inputs"],
            ),
            ("164_ride_effort_trim.sql", ["br_enforce_ride_effort_immutability"]),
        ]:
            for name in names:
                c.execute(function(file, name))
        for file, trigger in [
            (deletion, "account_deletion_user_lifecycle_fence"),
            ("123_reward_ftp_authority.sql", "trg_rides_reward_ftp_immutable"),
            ("154_derived_threshold_authority.sql", "trg_rides_threshold_evidence"),
            (
                "155_threshold_provisional_hold.sql",
                "trg_rides_threshold_release_power_inputs",
            ),
            ("164_ride_effort_trim.sql", "br_enforce_ride_effort_immutability"),
        ]:
            c.execute(
                re.search(
                    r"CREATE TRIGGER " + trigger + r"\b[\s\S]*?;",
                    (SQL / file).read_text(),
                )[0]
            )
        c.execute(
            "CREATE TRIGGER account_deletion_write_fence BEFORE INSERT OR UPDATE OR DELETE ON rides FOR EACH ROW EXECUTE FUNCTION account_deletion_write_fence('false')"
        )
    yield conn
    conn.close()


@pytest.fixture
def db(pre_cleanup_db):
    with pre_cleanup_db.cursor() as c:
        c.execute((SQL / "168_training_eligibility_terminal_replay.sql").read_text())
    return pre_cleanup_db


def row(db, day="2026-10-01T12:00:00Z", *, user=None, ride=None):
    user = user or str(uuid4())
    ride = ride or str(uuid4())
    with db.cursor() as c:
        c.execute("BEGIN; SET LOCAL app.account_deletion_user_create='on'")
        c.execute("INSERT INTO users(id) VALUES(%s) ON CONFLICT DO NOTHING", (user,))
        c.execute(
            "INSERT INTO rides(id,user_id,started_at,raw_file_path) VALUES(%s,%s,%s,'synthetic.fit')",
            (ride, user, day),
        )
        c.execute("COMMIT")
    return user, ride


def bind(db, user, ride, day="2026-10-01T12:00:00Z", evidence=EVIDENCE):
    with db.cursor() as c:
        c.execute(
            "SELECT bind_ride_training_inputs(%s,%s,%s,%s)",
            (ride, user, day, Json(evidence)),
        )
        return c.fetchone()[0]


def store(db, user, ride, inputs, metrics):
    with db.cursor() as c:
        c.execute(
            "SELECT store_ride_training_metrics(%s,%s,%s,%s,%s)",
            (ride, user, Json(inputs), Json(metrics), Json(EVIDENCE)),
        )
        return c.fetchone()[0]


def test_threshold_frozen_versioned_and_economy_untouched(db):
    user, ride = row(db)
    inputs = bind(db, user, ride)
    assert inputs["threshold"]["estimate"] is True
    assert inputs["threshold"]["value"] == 250
    assert (
        store(db, user, ride, inputs, {"engine_version": 1, "load": 64})["load"] == 64
    )
    with db.cursor() as c:
        c.execute(
            "INSERT INTO reward_ftp_authorities(id,user_id,ftp_w,effective_at,source,verified_by) VALUES(%s,%s,300,'2026-09-01','derived_eftp','derived-threshold-v1')",
            (str(uuid4()), user),
        )
    assert bind(db, user, ride) == inputs
    assert (
        store(db, user, ride, inputs, {"engine_version": 2, "load": 65})["load"] == 65
    )
    with db.cursor() as c:
        c.execute("SELECT xmin::text,tss,cal_earned FROM rides WHERE id=%s", (ride,))
        before = c.fetchone()
        assert before[1:] == (77, 91)
    store(db, user, ride, inputs, {"engine_version": 2, "load": 65})
    with db.cursor() as c:
        c.execute("SELECT xmin::text FROM rides WHERE id=%s", (ride,))
        assert c.fetchone()[0] == before[0]
    with pytest.raises(psycopg2.Error, match="regression"):
        store(db, user, ride, inputs, {"engine_version": 1, "load": 64})
    with pytest.raises(psycopg2.Error, match="conflict"):
        store(db, user, ride, {**inputs, "threshold": None}, {"engine_version": 2})
    with db.cursor() as c, pytest.raises(psycopg2.Error, match="frozen"):
        c.execute("UPDATE rides SET training_inputs=NULL WHERE id=%s", (ride,))
    with pytest.raises(psycopg2.Error):
        bind(db, str(uuid4()), ride)


def test_equal_timestamps_have_deterministic_backfill_order(db):
    user, first = row(db, ride="00000000-0000-0000-0000-000000000001")
    _, second = row(db, user=user, ride="00000000-0000-0000-0000-000000000002")
    frozen = bind(db, user, second)
    assert frozen["history_complete"] is False
    assert frozen["missing_history_count"] == 1
    bind(db, user, first)
    assert bind(db, user, second) == frozen


def test_owner_timezone_can_fill_only_absent_dates_without_rescoring_physiology(db):
    day = "2026-10-07T23:00:00Z"
    user, ride = row(db, day)
    inputs = bind(db, user, ride, day, {})
    store(db, user, ride, inputs, {"engine_version": 2, "local_date": None, "load": 80})
    with db.cursor() as c:
        c.execute(
            "SELECT initialize_training_timezone(%s,%s)", (user, "America/New_York")
        )
        assert c.fetchone()[0]["timezone"] == "America/New_York"
        c.execute("SELECT initialize_training_timezone(%s,%s)", (user, "Asia/Tokyo"))
        assert c.fetchone()[0]["timezone"] == "America/New_York"
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
    result = store(
        db, user, ride, inputs, {"engine_version": 2, "local_date": None, "load": 80}
    )
    assert result["local_date"] == "2026-10-07"
    assert result["timezone"] == "America/New_York"
    assert result["timezone_basis"] == "inferred_after_score"
    with db.cursor() as c:
        c.execute(
            "SELECT append_training_settings(%s,%s)",
            (user, Json({"timezone": "Asia/Tokyo"})),
        )
    # A later setting or engine replay cannot move an already dated ride.
    result = store(
        db,
        user,
        ride,
        inputs,
        {"engine_version": 2, "local_date": "2026-10-08", "load": 80},
    )
    assert result["local_date"] == "2026-10-07"
    assert bind(db, user, ride, day, {}) == inputs


@pytest.mark.parametrize("captured_zone", ["Europe/London", "UTC"])
def test_inferred_zone_never_overrides_later_device_dates(db, captured_zone):
    from datetime import timedelta, timezone

    user, _ = row(db)
    with db.cursor() as c:
        c.execute("SELECT initialize_training_timezone(%s,%s)", (user, captured_zone))
        settings = c.fetchone()[0]
        assert settings["timezone_source"] == "inferred"
        c.execute(
            "SELECT append_training_settings(%s,%s)", (user, Json({"max_hr_bpm": 190}))
        )
        assert c.fetchone()[0]["settings"]["timezone_source"] == "inferred"
        c.execute("SELECT now()+interval '1 day'")
        started = (
            c.fetchone()[0]
            .astimezone(timezone.utc)
            .replace(hour=1, minute=0, second=0, microsecond=0)
        )
    _, home = row(db, started.isoformat(), user=user)
    frozen = bind(
        db, user, home, started.isoformat(), {"utc_offset_s": -14400, "timezone": None}
    )
    assert frozen["local_date"] == (started - timedelta(hours=4)).date().isoformat()
    assert frozen["timezone_basis"] == "device"
    assert frozen["timezone"] is None
    assert frozen["utc_offset_s"] == -14400
    # Indoor rides without a device clock retain the inferred-zone fallback.
    _, indoor = row(db, started.isoformat(), user=user)
    inferred = bind(db, user, indoor, started.isoformat(), {})
    assert inferred["timezone"] == captured_zone
    assert inferred["timezone_basis"] == "inferred"
    with db.cursor() as c:
        # An explicit Settings choice, even of the same zone, becomes authority.
        c.execute(
            "SELECT append_training_settings(%s,%s)",
            (user, Json({"timezone": captured_zone})),
        )
        assert c.fetchone()[0]["settings"]["timezone_source"] == "rider"
    _, explicit = row(db, started.isoformat(), user=user)
    configured = bind(db, user, explicit, started.isoformat(), {"utc_offset_s": -14400})
    assert configured["timezone_basis"] == "rider"
    assert configured["timezone"] == captured_zone
    assert bind(db, user, home, started.isoformat(), {}) == frozen
    with db.cursor() as c:
        c.execute(
            "SELECT append_training_settings(%s,%s)", (user, Json({"timezone": None}))
        )
        cleared = c.fetchone()[0]["settings"]
        assert "timezone" not in cleared and "timezone_source" not in cleared


@pytest.mark.parametrize("captured_zone", ["UTC", "Europe/London"])
def test_ios_evening_geography_outranks_inferred_zone(db, captured_zone):
    from datetime import timedelta, timezone

    import workout_parse as wp

    from app.services.riding_days import aggregate_riding_days, undated_count
    from app.services.training_metrics import compute, evidence_for

    with db.cursor() as c:
        c.execute("SELECT now()+interval '1 day'")
        started = (
            c.fetchone()[0]
            .astimezone(timezone.utc)
            .replace(hour=1, minute=0, second=0, microsecond=0)
        )
    user, ride = row(db, started.isoformat())
    with db.cursor() as c:
        c.execute("SELECT initialize_training_timezone(%s,%s)", (user, captured_zone))
        assert c.fetchone()[0] == {
            "timezone": captured_zone,
            "timezone_source": "inferred",
        }

    # Synthetic iOS GPX: Philadelphia evening, no device UTC offset. Use the
    # production writer's creator, namespaces and UTC timestamp vocabulary.
    points = "".join(
        f'<trkpt lat="{40 + second * 0.00005:.7f}" lon="-75.2"><ele>100</ele>'
        f'<time>{(started + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")}</time>'
        "<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>150</gpxtpx:hr>"
        "</gpxtpx:TrackPointExtension></extensions></trkpt>"
        for second in range(60)
    )
    raw = (
        '<gpx version="1.1" creator="Boulder Roller iOS" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        f"<trk><trkseg>{points}</trkseg></trk></gpx>"
    ).encode()
    activity = wp.parse_file_bytes(raw, "gpx")
    assert activity.training_context["indoor_or_virtual"] is False
    evidence = evidence_for(activity)
    assert evidence["utc_offset_s"] is None
    assert evidence["timezone"] == "America/New_York"

    expected_day = started.date() - timedelta(days=1)
    inputs = bind(db, user, ride, started.isoformat(), evidence)
    assert inputs["local_date"] == expected_day.isoformat()
    assert inputs["timezone"] == "America/New_York"
    assert inputs["timezone_basis"] == "start_position"
    metrics = compute(activity, inputs)
    with db.cursor() as c:
        c.execute(
            "SELECT store_ride_training_metrics(%s,%s,%s,%s,%s)",
            (ride, user, Json(inputs), Json(metrics), Json(evidence)),
        )
        stored = c.fetchone()[0]
        c.execute(
            "SELECT training_settings_history->-1->'settings' FROM users WHERE id=%s",
            (user,),
        )
        assert c.fetchone()[0] == {
            "timezone": captured_zone,
            "timezone_source": "inferred",
        }
        c.execute("SELECT to_jsonb(r) FROM rides r WHERE id=%s", (ride,))
        rides = [c.fetchone()[0]]
    assert stored["local_date"] == expected_day.isoformat()
    assert stored["timezone"] == "America/New_York"
    assert stored["timezone_basis"] == "start_position"
    assert stored["utc_offset_s"] is None
    assert stored["load"] > 0
    days = aggregate_riding_days(
        rides, start_date=expected_day, end_date=started.date()
    )
    assert [day["date"] for day in days] == [expected_day.isoformat()]
    assert days[0]["ride_count"] == 1
    assert days[0]["moving_s"] == 59
    assert undated_count(rides, expected_day, started.date()) == 0


def test_replay_cannot_claim_rides_between_payment_phases(db):
    with db.cursor() as c:
        for status in (
            "processing",
            "metrics_ready",
            "enriched",
            "under_review",
            "recovery_pending",
        ):
            user, ride = row(db)
            c.execute(
                "UPDATE rides SET processing_status=%s WHERE id=%s", (status, ride)
            )
        user, completed = row(db)
        _, failed = row(db, user=user)
        c.execute("UPDATE rides SET processing_status='failed' WHERE id=%s", (failed,))
        _, reviewed = row(db, user=user)
        c.execute(
            "UPDATE rides SET processing_status='under_review',phase3_completed_at=now() WHERE id=%s",
            (reviewed,),
        )
        c.execute("SELECT claim_training_replay(50)")
        assert {r["id"] for r in c.fetchone()[0]} == {completed, reviewed}


def test_replay_stale_completion_cannot_open_an_active_retry(db):
    with db.cursor() as c:
        for status in (
            "processing",
            "metrics_ready",
            "enriched",
            "under_review",
            "recovery_pending",
        ):
            _, ride = row(db)
            c.execute(
                """UPDATE rides SET processing_status=%s,
                phase1_completed_at=now()-interval '1 minute',
                phase2_completed_at=now()-interval '30 seconds',
                phase3_completed_at=now()-interval '1 day' WHERE id=%s""",
                (status, ride),
            )
        c.execute("SELECT claim_training_replay(50)")
        assert c.fetchone()[0] == []


@pytest.mark.parametrize("status", ["metrics_ready", "enriched"])
def test_returned_pay_failure_scores_but_restarted_attempt_vetoes_bind_and_store(
    db, status
):
    user, ride = row(db)
    token, newer = str(uuid4()), str(uuid4())
    with db.cursor() as c:
        c.execute(
            "UPDATE rides SET processing_status=%s,phase1_completed_at=now() WHERE id=%s",
            (status, ride),
        )
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)", (ride, user, token)
        )
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []
        c.execute("SELECT set_training_pay_attempt(%s,%s,%s,true)", (ride, user, token))
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
    inputs = bind(db, user, ride)
    with db.cursor() as c:
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)", (ride, user, newer)
        )
        c.execute("SELECT set_training_pay_attempt(%s,%s,%s,true)", (ride, user, token))
    for write in [
        lambda: bind(db, user, ride),
        lambda: store(db, user, ride, inputs, {"engine_version": 2}),
    ]:
        with pytest.raises(psycopg2.Error, match="payment attempt active"):
            write()
    with db.cursor() as c:
        c.execute("SELECT set_training_pay_attempt(%s,%s,%s,true)", (ride, user, newer))
    store(db, user, ride, inputs, {"engine_version": 2})
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,NULL)", (ride, user))
        c.execute("SELECT active FROM training_pay_attempts WHERE ride_id=%s", (ride,))
        assert c.fetchone() == (False,)
        c.execute("SELECT tss,cal_earned FROM rides WHERE id=%s", (ride,))
        assert c.fetchone() == (77, 91)


def test_startup_recovers_historical_and_crashed_attempts_but_not_new_attempts(db):
    user, historical = row(db)
    _, crashed = row(db, user=user)
    _, current = row(db, user=user)
    with db.cursor() as c:
        c.execute(
            "UPDATE rides SET processing_status='enriched',phase1_completed_at=now()"
        )
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)",
            (crashed, user, str(uuid4())),
        )
        c.execute("SELECT training_replay_startup_cutoff()")
        cutoff = c.fetchone()[0]
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)",
            (current, user, str(uuid4())),
        )
        c.execute("SELECT claim_training_replay(10,%s)", (cutoff,))
        assert {r["id"] for r in c.fetchone()[0]} == {historical, crashed}
    for ride in [historical, crashed]:
        inputs = bind(db, user, ride)
        store(db, user, ride, inputs, {"engine_version": 2})


def test_completed_economic_recovery_does_not_invalidate_finished_pay_attempt(db):
    user, ride = row(db)
    token = str(uuid4())
    with db.cursor() as c:
        c.execute(
            "UPDATE rides SET processing_status='enriched',phase1_completed_at=now(),phase2_completed_at=now() WHERE id=%s",
            (ride,),
        )
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)", (ride, user, token)
        )
        c.execute("SELECT set_training_pay_attempt(%s,%s,%s,true)", (ride, user, token))
        # The durable economic recovery loop completes after the NATS ACK.
        c.execute(
            "UPDATE rides SET processing_status='completed',phase3_completed_at=now() WHERE id=%s",
            (ride,),
        )
        c.execute("SELECT claim_training_replay(10)")
        assert [r["id"] for r in c.fetchone()[0]] == [ride]
    inputs = bind(db, user, ride)
    assert (
        store(db, user, ride, inputs, {"engine_version": 2, "load": 80})["load"] == 80
    )


def test_startup_does_not_recover_failed_upload_before_phase1(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute("UPDATE rides SET processing_status='failed' WHERE id=%s", (ride,))
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)",
            (ride, user, str(uuid4())),
        )
        c.execute("SELECT training_replay_startup_cutoff()")
        cutoff = c.fetchone()[0]
        c.execute("SELECT claim_training_replay(10,%s)", (cutoff,))
        assert c.fetchone()[0] == []
    with pytest.raises(psycopg2.Error, match="ineligible"):
        bind(db, user, ride)


@pytest.mark.parametrize("lease", ["ordinary", "held_planner", "held_executor"])
def test_active_economic_leases_veto_every_training_write(db, lease):
    user, ride = row(db)
    inputs = bind(db, user, ride)
    with db.cursor() as c:
        if lease == "ordinary":
            c.execute(
                "INSERT INTO ride_economic_plans VALUES(%s,now()+interval '5 minutes')",
                (ride,),
            )
        elif lease == "held_planner":
            hold, item = str(uuid4()), str(uuid4())
            c.execute(
                "INSERT INTO reward_threshold_provisional_holds VALUES(%s,%s)",
                (hold, ride),
            )
            c.execute(
                "INSERT INTO reward_threshold_release_batch_items VALUES(%s,%s)",
                (item, hold),
            )
            c.execute(
                "INSERT INTO reward_threshold_release_item_claims VALUES(%s,now()+interval '5 minutes',NULL,NULL)",
                (item,),
            )
        else:
            snapshot = str(uuid4())
            c.execute(
                "INSERT INTO reward_threshold_release_snapshots VALUES(%s,%s)",
                (snapshot, ride),
            )
            c.execute(
                "INSERT INTO reward_threshold_release_executions VALUES(%s,now()+interval '5 minutes')",
                (snapshot,),
            )
        c.execute("SELECT claim_training_replay(10)")
        assert c.fetchone()[0] == []
    for write in [
        lambda: bind(db, user, ride),
        lambda: store(db, user, ride, inputs, {"engine_version": 2}),
    ]:
        with pytest.raises(psycopg2.Error, match="payment attempt active"):
            write()


@pytest.mark.parametrize(
    "setting,offset,zone,expected,basis",
    [
        ("America/New_York", 39600, "Pacific/Guadalcanal", "2026-10-07", "rider"),
        (None, -14400, "Pacific/Guadalcanal", "2026-10-07", "device"),
        (None, 0, "America/New_York", "2026-10-07", "device"),
        (None, None, "America/New_York", "2026-10-07", "start_position"),
        (None, None, None, None, None),
    ],
)
def test_frozen_date_uses_rider_then_device_then_outdoor_position(
    db, setting, offset, zone, expected, basis
):
    day = "2026-10-07T23:00:00Z"
    user, ride = row(db, day)
    if setting:
        with db.cursor() as c:
            c.execute(
                "UPDATE users SET training_settings_history=%s WHERE id=%s",
                (
                    Json(
                        [
                            {
                                "effective_at": "2026-10-01T00:00:00Z",
                                "settings": {"timezone": setting},
                            }
                        ]
                    ),
                    user,
                ),
            )
    inputs = bind(db, user, ride, day, {"timezone": zone, "utc_offset_s": offset})
    assert inputs["local_date"] == expected
    assert inputs["timezone_basis"] == basis
    assert inputs.get("utc_offset_s") == (offset if basis == "device" else None)
    assert bind(db, user, ride, day, {"timezone": "Asia/Tokyo"}) == inputs


def test_replay_claim_advances_past_poison_rows_and_retries_them(db):
    user, first = row(db, "2026-09-01")
    _, second = row(db, "2026-09-02", user=user)
    _, good = row(db, "2026-09-03", user=user)
    with db.cursor() as c:
        c.execute("SELECT claim_training_replay(2)")
        claimed = c.fetchone()[0]
        assert {r["id"] for r in claimed} == {first, second}
        for ride in claimed:
            c.execute(
                "SELECT finish_training_replay(%s,%s,'parse_error')", (ride["id"], user)
            )
        c.execute("SELECT claim_training_replay(2)")
        assert [r["id"] for r in c.fetchone()[0]] == [good]
        c.execute(
            "UPDATE training_replay_state SET next_attempt_at=now()-interval '1 second'"
        )
        c.execute("SELECT claim_training_replay(2)")
        assert {r["id"] for r in c.fetchone()[0]} == {first, second}


def test_started_at_cannot_be_spoofed(db):
    user, ride = row(db)
    with pytest.raises(psycopg2.Error, match="date conflict"):
        bind(db, user, ride, "2026-11-01T12:00:00Z")


def test_non_ios_authority_and_failed_ride_power_evidence_are_ignored(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute(
            "INSERT INTO reward_ftp_authorities(id,user_id,ftp_w,effective_at,source,verified_by) VALUES(%s,%s,450,'2026-09-01','external','admin')",
            (str(uuid4()), user),
        )
        c.execute(
            "INSERT INTO rides(id,user_id,started_at,processing_status,training_evidence) VALUES(%s,%s,'2026-09-01','failed',%s)",
            (str(uuid4()), user, Json({k: v * 1.5 for k, v in EVIDENCE.items()})),
        )
    assert bind(db, user, ride)["threshold"]["value"] == 250
    with db.cursor() as c:
        c.execute("SELECT current_training_threshold(%s,'2026-10-02')", (user,))
        assert c.fetchone()[0]["value"] == 250
        for role in ("anon", "authenticated"):
            c.execute(
                "SELECT has_function_privilege(%s, 'bind_ride_training_inputs(uuid,uuid,timestamptz,jsonb)', 'execute')",
                (role,),
            )
            assert c.fetchone()[0] is False


def test_forward_only_settings_and_retry_error_clear(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute(
            "SELECT append_training_settings(%s,%s)",
            (user, Json({"threshold_hr_bpm": 170, "timezone": "America/New_York"})),
        )
    inputs = bind(db, user, ride)
    assert inputs["settings"] == {}
    metrics = {"engine_version": 2, "load": 64}
    store(db, user, ride, inputs, metrics)
    with db.cursor() as c:
        c.execute("UPDATE rides SET training_error='retry' WHERE id=%s", (ride,))
    store(db, user, ride, inputs, metrics)
    with db.cursor() as c:
        c.execute("SELECT training_error FROM rides WHERE id=%s", (ride,))
        assert c.fetchone()[0] is None


def test_retry_state_service_role_cannot_bypass_owner_locks(db):
    with db.cursor() as c:
        c.execute(
            "SELECT has_table_privilege('service_role','training_replay_state','INSERT,UPDATE,DELETE')"
        )
        assert c.fetchone()[0] is False
        c.execute(
            "SELECT has_table_privilege('service_role','training_replay_state','SELECT')"
        )
        assert c.fetchone()[0] is True


def test_all_training_rpcs_private_and_claim_limits_bounded(db):
    names = [
        "bind_ride_training_inputs(uuid,uuid,timestamptz,jsonb)",
        "store_ride_training_metrics(uuid,uuid,jsonb,jsonb,jsonb)",
        "append_training_settings(uuid,jsonb)",
        "current_training_threshold(uuid,timestamptz)",
        "claim_training_replay(integer,timestamptz,uuid[],integer)",
        "finish_training_replay(uuid,uuid,text,integer,jsonb)",
        "training_counted_statuses()",
        "initialize_training_timezone(uuid,text)",
        "training_has_payment_lease(uuid)",
        "training_payment_idle(uuid)",
        "set_training_pay_attempt(uuid,uuid,uuid,boolean)",
        "training_replay_startup_cutoff()",
    ]
    with db.cursor() as c:
        for name in names:
            for role in ("anon", "authenticated", "service_role"):
                c.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE')", (role, name)
                )
                assert c.fetchone()[0] is (role == "service_role")
        for limit in (None, 0, 51):
            with pytest.raises(psycopg2.Error, match="invalid training batch size"):
                c.execute("SELECT claim_training_replay(%s)", (limit,))


@pytest.mark.parametrize("kind", ["null", "historical", "default", "derived"])
def test_real_guards_preserve_economic_and_source_snapshots(db, kind):
    user, ride = row(db)
    with db.cursor() as c:
        authority = str(uuid4()) if kind == "derived" else None
        if authority:
            c.execute(
                "INSERT INTO reward_ftp_authorities(id,user_id,ftp_w,effective_at,source,verified_by) VALUES(%s,%s,300,'2026-09-01','derived_eftp','derived-threshold-v1')",
                (authority, user),
            )
        if kind == "historical":
            # Synthetic legacy row predates the current policy, as migration164's
            # backfill can. Restore the exact production trigger before replay.
            c.execute(
                "ALTER TABLE rides DISABLE TRIGGER trg_rides_reward_ftp_immutable"
            )
        if kind != "null":
            c.execute(
                "UPDATE rides SET reward_ftp_w=%s,reward_ftp_source=%s,reward_ftp_authority_id=%s,reward_ftp_policy_version=%s,reward_ftp_activity_started_at=started_at,economic_tss=77 WHERE id=%s",
                (
                    300 if authority else 200,
                    "derived_eftp" if authority else "network_default",
                    authority,
                    (
                        "reward_ftp_policy_2026_07_14"
                        if kind == "historical"
                        else "reward_ftp_policy_2026_08_24_threshold_v1"
                    ),
                    ride,
                ),
            )
        if kind == "historical":
            c.execute("ALTER TABLE rides ENABLE TRIGGER trg_rides_reward_ftp_immutable")
        c.execute(
            "SELECT to_jsonb(r)-ARRAY['training_inputs','training_evidence','training_metrics','training_error'] FROM rides r WHERE id=%s",
            (ride,),
        )
        before = c.fetchone()[0]
    inputs = bind(db, user, ride, evidence={**EVIDENCE, "timezone": "America/New_York"})
    assert inputs["local_date"] == "2026-10-01"
    store(db, user, ride, inputs, {"engine_version": 2, "load": 80})
    with db.cursor() as c:
        c.execute(
            "SELECT to_jsonb(r)-ARRAY['training_inputs','training_evidence','training_metrics','training_error'] FROM rides r WHERE id=%s",
            (ride,),
        )
        assert c.fetchone()[0] == before


def test_invalid_legacy_snapshot_does_not_block_later_training(db):
    user, bad = row(db, "2026-09-30")
    _, good = row(db, user=user)
    with db.cursor() as c:
        c.execute("ALTER TABLE rides DISABLE TRIGGER trg_rides_reward_ftp_immutable")
        c.execute(
            "UPDATE rides SET reward_ftp_w=999,reward_ftp_policy_version='invalid' WHERE id=%s",
            (bad,),
        )
        c.execute("ALTER TABLE rides ENABLE TRIGGER trg_rides_reward_ftp_immutable")
    with pytest.raises(psycopg2.Error, match="invalid ride reward FTP snapshot"):
        bind(db, user, bad, "2026-09-30")
    with db.cursor() as c:
        c.execute("SELECT finish_training_replay(%s,%s,'CheckViolation')", (bad, user))
        c.execute("SELECT claim_training_replay(1)")
        assert [r["id"] for r in c.fetchone()[0]] == [good]
    inputs = bind(db, user, good)
    assert inputs["history_complete"] is False
    assert (
        store(db, user, good, inputs, {"engine_version": 2, "load": 80})["load"] == 80
    )


def test_deletion_clears_retry_state_and_fences_later_work(db):
    user, ride = row(db)
    inputs = bind(db, user, ride)
    with db.cursor() as c:
        token = str(uuid4())
        c.execute(
            "SELECT set_training_pay_attempt(%s,%s,%s,false)", (ride, user, token)
        )
        c.execute("SELECT set_training_pay_attempt(%s,%s,%s,true)", (ride, user, token))
        c.execute("SELECT claim_training_replay(1)")
        assert len(c.fetchone()[0]) == 1
        with pytest.raises(psycopg2.Error, match="owner unavailable"):
            c.execute(
                "SELECT finish_training_replay(%s,%s,'error')", (ride, str(uuid4()))
            )
        c.execute(
            "BEGIN; SET LOCAL app.account_deletion_request_id='synthetic-request'"
        )
        c.execute(
            "UPDATE users SET account_state='deletion_pending' WHERE id=%s", (user,)
        )
        c.execute("COMMIT")
        c.execute("SELECT count(*) FROM training_replay_state")
        assert c.fetchone()[0] == 0
        c.execute("SELECT count(*) FROM training_pay_attempts")
        assert c.fetchone()[0] == 0
        c.execute("SELECT claim_training_replay(1)")
        assert c.fetchone()[0] == []
        with pytest.raises(psycopg2.Error, match="owner unavailable"):
            c.execute("SELECT finish_training_replay(%s,%s,'error')", (ride, user))
        with pytest.raises(psycopg2.Error, match="owner unavailable"):
            c.execute(
                "SELECT set_training_pay_attempt(%s,%s,%s,false)", (ride, user, token)
            )
        with pytest.raises(psycopg2.Error):
            c.execute(
                "SELECT initialize_training_timezone(%s,%s)", (user, "America/New_York")
            )
    with pytest.raises(psycopg2.Error, match="owner unavailable"):
        store(db, user, ride, inputs, {"engine_version": 2, "load": 80})


def test_older_worker_never_claims_future_engine_version(db):
    user, ride = row(db)
    with db.cursor() as c:
        c.execute(
            "UPDATE rides SET training_metrics='{"
            + '"engine_version":3'
            + "}',training_error='retry' WHERE id=%s",
            (ride,),
        )
        c.execute(
            "INSERT INTO patterns_climb(id,activity_id) VALUES(%s,%s)",
            (str(uuid4()), ride),
        )
        c.execute("SELECT claim_training_replay(1)")
        assert c.fetchone()[0] == []
