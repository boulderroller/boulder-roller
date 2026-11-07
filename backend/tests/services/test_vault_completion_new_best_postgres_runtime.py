"""PostgreSQL runtime contract for the ride page "New best" flag.

``vault_completions.is_pr`` feeds the portal ride page "New best" and the iOS
reveal's leaderboard and mark beat (``vaultMatch.isPR``). Migration 176 makes
it one table rule that every writer gets: a completion is a new best when it
is the rider's first validated, chain-confirmed, timed effort on that climb,
or strictly faster, in whole seconds, than every earlier one by original ride
``completed_at``. A tie is not a new best, and processing order never decides.

Every case runs on the production trigger stack of ``vault_completions`` (the
real 114, 119, 120, 152 and 155 trigger functions; see
vault_completion_trigger_stack) and writes through the production writers:
128's projection and reconcile, 155's held-ride release, 152's account
anonymization, and the service_role REST fallback and tx mirror.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2
import pytest

from backend.scripts.apply_sql_migrations import (
    apply_migration,
    discover_migrations,
    ensure_ledger,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    isolated_postgres_dsn,
    postgres_dsn,
)
from backend.tests.services.vault_completion_trigger_stack import (
    NEW_BEST_MIGRATION,
    anonymize_vault_completions,
    install_stack,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / NEW_BEST_MIGRATION
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20261020120000_176_vault_completion_new_best.sql"
)
BACKFILL_SCRIPT = (
    BACKEND_ROOT / "scripts" / "backfill_vault_completion_new_best.sql"
)

CLIMB = "vault-a"
OTHER_CLIMB = "vault-b"
VAULT_IDS = {CLIMB: 7, OTHER_CLIMB: 8}
RIDER = "rider-a"
OTHER_RIDER = "rider-b"
MONDAY = datetime(2026, 10, 12, 7, 0, tzinfo=timezone.utc)

NEW_BEST_FUNCTIONS = (
    "public.br_vault_completion_counts_toward_best(boolean,text,bigint)",
    "public.br_vault_completion_is_new_best(uuid,text,text,timestamp with time zone,bigint,boolean,text)",
    "public.br_lock_vault_completion_new_best(text,text)",
    "public.br_refresh_vault_completion_new_bests_after(text,text,timestamp with time zone,uuid)",
    "public.br_set_vault_completion_new_best()",
    "public.br_refresh_later_vault_completion_new_bests()",
)

LOCK_MODES_ON_COMPLETIONS = """
SELECT mode FROM pg_locks
WHERE locktype = 'relation'
  AND relation = 'public.vault_completions'::regclass
  AND pid = pg_backend_pid()
"""


def _install(cursor: Any, *, with_new_best: bool) -> None:
    install_stack(cursor, riders=(RIDER, OTHER_RIDER), climbs=VAULT_IDS)
    if with_new_best:
        _apply_new_best(cursor)


def _apply_new_best(cursor: Any) -> None:
    cursor.execute(CANONICAL_MIGRATION.read_text(encoding="utf-8"))


@pytest.fixture
def db(isolated_postgres_dsn: str) -> Any:
    with _connection(isolated_postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install(cursor, with_new_best=True)
            yield cursor


@pytest.fixture
def db_before_new_best(isolated_postgres_dsn: str) -> Any:
    """The production stack and writers as they stand before migration 176."""
    with _connection(isolated_postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install(cursor, with_new_best=False)
            yield cursor


# ---------------------------------------------------------------------------
# Production writers
# ---------------------------------------------------------------------------


def _ride_time(day: float) -> datetime:
    return MONDAY + timedelta(days=day)


def _digest(label: str) -> psycopg2.Binary:
    return psycopg2.Binary(hashlib.sha256(label.encode("utf-8")).digest())


def _new_ride(cursor: Any) -> uuid.UUID:
    ride_id = uuid.uuid4()
    cursor.execute("INSERT INTO public.rides (id) VALUES (%s)", (str(ride_id),))
    return ride_id


def _record_pending(
    cursor: Any,
    *,
    day: float,
    time_s: Optional[int],
    wallet: str = RIDER,
    climb: str = CLIMB,
    ride_id: Optional[uuid.UUID] = None,
) -> str:
    """Ride processing records unconfirmed evidence through 128's projection."""
    ride_id = ride_id or _new_ride(cursor)
    cursor.execute(
        """
        SELECT inserted FROM public.record_vault_completion_projection(
            %s, %s, %s, %s, %s, true, NULL, 0
        )
        """,
        (climb, wallet, str(ride_id), time_s, _ride_time(day)),
    )
    assert cursor.fetchone()[0] is True
    return str(ride_id)


def _freeze_completion_step(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    day: float,
    time_s: Optional[int],
    wallet: str,
    climb: str,
    finalized: bool,
) -> uuid.UUID:
    """The coordinator's confirmed plan step: 128's frozen evidence authority.

    finalized also indexes the Settlement Flow and the finalized epoch
    distribution, so the ride's finalized_at is set when it is projected.
    """
    lease_owner = uuid.uuid4()
    params = {
        "ride_id": str(ride_id),
        "wallet": wallet,
        "lease_owner": str(lease_owner),
        "attestation": f"attestation-{ride_id}",
        "vault_id": VAULT_IDS[climb],
        "climb": climb,
        "time_s": time_s,
        "completed_at": _ride_time(day),
        "tribute": 5,
        "tx": f"tx-{ride_id}",
        "receipt": f"receipt-{ride_id}-{climb}",
        "evidence": _digest(f"completion-{ride_id}-{climb}"),
    }
    cursor.execute(
        """
        INSERT INTO public.ride_economic_plans (
            ride_id, wallet, state, lease_owner, lease_expires_at,
            expected_attestation_pda
        ) VALUES (
            %(ride_id)s, %(wallet)s, 'cal_confirmed', %(lease_owner)s,
            now() + interval '5 minutes', %(attestation)s
        );
        INSERT INTO public.ride_economic_completion_steps (
            ride_id, step_index, state, chain_confirmed_at, vault_id,
            vault_signature, completion_time_s, completed_at,
            exact_tribute_base_units, actual_tx_signature, expected_receipt_pda,
            completion_evidence_hash, completion_evidence_version
        ) VALUES (
            %(ride_id)s, 0, 'confirmed', now(), %(vault_id)s, %(climb)s,
            %(time_s)s, %(completed_at)s, %(tribute)s, %(tx)s, %(receipt)s,
            %(evidence)s, 2
        );
        """,
        params,
    )
    if finalized:
        cursor.execute(
            """
            INSERT INTO public.indexed_climb_completion_flows (
                vault_id, ride_attestation, completion_evidence_hash,
                credited_settlement_week, cal_tributed,
                completion_evidence_version
            ) VALUES (
                %(vault_id)s, %(attestation)s, %(evidence)s,
                public.br_settlement_week(%(completed_at)s), %(tribute)s, 2
            );
            INSERT INTO public.indexed_epoch_distributions (
                vault_id, epoch, finalized_at
            )
            SELECT %(vault_id)s, public.br_settlement_week(%(completed_at)s),
                   %(completed_at)s + interval '8 days'
            WHERE NOT EXISTS (
                SELECT 1 FROM public.indexed_epoch_distributions
                WHERE vault_id = %(vault_id)s
                  AND epoch = public.br_settlement_week(%(completed_at)s)
            );
            """,
            params,
        )
    return lease_owner


def _reconcile(cursor: Any, ride_id: str, lease_owner: uuid.UUID) -> None:
    cursor.execute(
        "SELECT public.reconcile_confirmed_vault_completion(%s::UUID, %s::UUID, 0)",
        (ride_id, str(lease_owner)),
    )
    assert cursor.fetchone()[0] is not None


def _record_confirmed(
    cursor: Any,
    *,
    day: float,
    time_s: Optional[int],
    wallet: str = RIDER,
    climb: str = CLIMB,
    ride_id: Optional[uuid.UUID] = None,
    finalized: bool = False,
) -> str:
    """Freeze one plan step and project it through 128's reconcile."""
    ride_id = ride_id or _new_ride(cursor)
    lease_owner = _freeze_completion_step(
        cursor,
        ride_id=ride_id,
        day=day,
        time_s=time_s,
        wallet=wallet,
        climb=climb,
        finalized=finalized,
    )
    _reconcile(cursor, str(ride_id), lease_owner)
    return str(ride_id)


def _release_held_ride(
    cursor: Any,
    *,
    day: float,
    time_s: int,
    wallet: str = RIDER,
    climb: str = CLIMB,
) -> str:
    """A ride held for Threshold review, released through 155's writer.

    The release projects the ride long after it was ridden, after newer rides.
    """
    ride_id = _new_ride(cursor)
    snapshot_id, lease_owner = uuid.uuid4(), uuid.uuid4()
    cursor.execute("SELECT public.br_settlement_week(now())")
    release_week = cursor.fetchone()[0]
    params = {
        "ride_id": str(ride_id),
        "snapshot_id": str(snapshot_id),
        "lease_owner": str(lease_owner),
        "wallet": wallet,
        "attestation": f"attestation-{ride_id}",
        "authority": f"release-{snapshot_id}",
        "vault_id": VAULT_IDS[climb],
        "climb": climb,
        "time_s": time_s,
        "completed_at": _ride_time(day),
        "tribute": 9,
        "tx": f"release-tx-{ride_id}",
        "receipt": f"release-receipt-{ride_id}-{climb}",
        "evidence": _digest(f"release-{ride_id}-{climb}"),
        "release_week": release_week,
    }
    cursor.execute(
        """
        INSERT INTO public.ride_economic_plans (
            ride_id, wallet, state, expected_attestation_pda
        ) VALUES (%(ride_id)s, %(wallet)s, 'complete', %(attestation)s);
        INSERT INTO public.reward_threshold_release_snapshots (id, ride_id)
        VALUES (%(snapshot_id)s, %(ride_id)s);
        INSERT INTO public.reward_threshold_release_executions (
            snapshot_id, state, lease_owner, lease_expires_at,
            expected_release_authority_pda, wallet
        ) VALUES (
            %(snapshot_id)s, 'completions_confirmed', %(lease_owner)s,
            now() + interval '5 minutes', %(authority)s, %(wallet)s
        );
        INSERT INTO public.reward_threshold_release_steps (
            snapshot_id, step_index, state, chain_confirmed_at, vault_id,
            vault_signature, completion_time_s, completed_at,
            exact_tribute_base_units, actual_tx_signature, expected_receipt_pda,
            completion_evidence_hash, completion_evidence_version
        ) VALUES (
            %(snapshot_id)s, 0, 'confirmed', now(), %(vault_id)s, %(climb)s,
            %(time_s)s, %(completed_at)s, %(tribute)s, %(tx)s, %(receipt)s,
            %(evidence)s, 3
        );
        INSERT INTO public.indexed_held_ride_release_authorities (
            pda, release_settlement_week
        ) VALUES (%(authority)s, %(release_week)s);
        INSERT INTO public.indexed_climb_completion_receipts (
            pda, ride_attestation_pda, release_authority_pda,
            completion_evidence_version, completion_evidence_hash,
            cal_tributed, credited_settlement_week
        ) VALUES (
            %(receipt)s, %(attestation)s, %(authority)s, 3, %(evidence)s,
            %(tribute)s, %(release_week)s
        );
        INSERT INTO public.indexed_climb_completion_flows (
            vault_id, ride_attestation, completion_evidence_hash,
            credited_settlement_week, cal_tributed,
            completion_evidence_version, release_authority_pda
        ) VALUES (
            %(vault_id)s, %(attestation)s, %(evidence)s, %(release_week)s,
            %(tribute)s, 3, %(authority)s
        );
        """,
        params,
    )
    cursor.execute(
        """
        SELECT public.reconcile_confirmed_reward_threshold_release_completion(
            %s::UUID, %s::UUID, 0
        )
        """,
        (str(snapshot_id), str(lease_owner)),
    )
    assert cursor.fetchone()[0] is not None
    return str(ride_id)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def _flag(cursor: Any, activity_id: str, climb: str = CLIMB) -> Optional[bool]:
    cursor.execute(
        """
        SELECT is_pr FROM public.vault_completions
        WHERE vault_signature = %s AND activity_id = %s
        """,
        (climb, activity_id),
    )
    row = cursor.fetchone()
    assert row is not None, activity_id
    return row[0]


def _flags(cursor: Any, wallet: str = RIDER, climb: str = CLIMB) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT activity_id, is_pr FROM public.vault_completions
        WHERE wallet = %s AND vault_signature = %s
        """,
        (wallet, climb),
    )
    return dict(cursor.fetchall())


def _climb_page_bests(
    cursor: Any, wallet: str = RIDER, climb: str = CLIMB
) -> dict[str, bool]:
    """The climb effort history's read-time running best (vault.py), exactly.

    Confirmed, validated, timed efforts ordered by completed_at then id; an
    effort is a PR when there is no best yet or it is strictly faster.
    """
    cursor.execute(
        """
        SELECT activity_id, time_seconds, validated, chain_confirmation_status
        FROM public.vault_completions
        WHERE wallet = %s AND vault_signature = %s
        ORDER BY completed_at, id
        """,
        (wallet, climb),
    )
    running_best: Optional[int] = None
    bests: dict[str, bool] = {}
    for activity_id, time_s, validated, status in cursor.fetchall():
        if validated is not True or status != "confirmed" or time_s is None:
            bests[activity_id] = False
            continue
        is_pr = running_best is None or time_s < running_best
        if is_pr:
            running_best = time_s
        bests[activity_id] = is_pr
    return bests


def _assert_ride_page_matches_climb_page(
    cursor: Any, wallet: str = RIDER, climb: str = CLIMB
) -> None:
    assert _flags(cursor, wallet, climb) == _climb_page_bests(cursor, wallet, climb)


def _completion_rows_without_flag(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT id::TEXT, to_jsonb(completion) - 'is_pr'
        FROM public.vault_completions AS completion
        """
    )
    return dict(cursor.fetchall())


def _ride_finalization(cursor: Any) -> dict[str, Any]:
    cursor.execute("SELECT id::TEXT, finalized_at FROM public.rides")
    return dict(cursor.fetchall())


def _new_best_triggers(cursor: Any) -> list[str]:
    cursor.execute(
        """
        SELECT tgname FROM pg_trigger
        WHERE tgrelid = 'public.vault_completions'::regclass
          AND tgname LIKE 'trg_vault_completion_new_best%'
        ORDER BY tgname
        """
    )
    return [row[0] for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Migration shape, locks and grants
# ---------------------------------------------------------------------------


def test_new_best_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_new_best_migration_sets_its_lock_timeout_first(
    isolated_postgres_dsn: str,
) -> None:
    sql = CANONICAL_MIGRATION.read_text(encoding="utf-8")
    statements = [
        line
        for line in sql.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    assert statements[0] == "SET LOCAL lock_timeout = '5s';"

    # The runner applies the file in one transaction; SET LOCAL lasts for it.
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            _install(cursor, with_new_best=False)
            cursor.execute(sql)
            cursor.execute("SHOW lock_timeout")
            assert cursor.fetchone() == ("5s",)
        connection.rollback()


def test_new_best_migration_never_takes_access_exclusive(
    isolated_postgres_dsn: str,
) -> None:
    """Every ride page reads vault_completions; none may queue behind the deploy."""
    with closing(psycopg2.connect(isolated_postgres_dsn)) as connection:
        with connection.cursor() as cursor:
            _install(cursor, with_new_best=False)
            connection.commit()
            for attempt in ("first apply", "re-apply"):
                _apply_new_best(cursor)
                cursor.execute(LOCK_MODES_ON_COMPLETIONS)
                modes = {row[0] for row in cursor.fetchall()}
                assert "ShareRowExclusiveLock" in modes, attempt
                assert modes <= {
                    "AccessShareLock",
                    "ShareUpdateExclusiveLock",
                    "ShareRowExclusiveLock",
                }, (attempt, modes)
                connection.commit()


def _wait_until_blocked(monitor: Any, pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    with monitor.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s AND NOT granted)",
                (pid,),
            )
            if cursor.fetchone()[0]:
                return True
            time.sleep(0.05)
    return False


def test_deploy_behind_an_open_ride_write_stops_fast_and_never_queues_readers(
    isolated_postgres_dsn: str,
) -> None:
    """The runner applies 176 behind an uncommitted ride write.

    It waits only on SHARE ROW EXCLUSIVE, which readers pass, and gives up
    after its 5 s lock_timeout with nothing applied, instead of holding the
    queue. Once the write commits, the same deploy applies.
    """
    with _connection(isolated_postgres_dsn) as setup:
        with setup.cursor() as cursor:
            _install(cursor, with_new_best=False)
            activity_id = _record_confirmed(cursor, day=0, time_s=300)
    migration = next(
        migration
        for migration in discover_migrations(BACKEND_ROOT / "sql")
        if migration.filename == NEW_BEST_MIGRATION
    )

    runner = psycopg2.connect(isolated_postgres_dsn)
    try:
        writer = psycopg2.connect(isolated_postgres_dsn)
        reader = psycopg2.connect(isolated_postgres_dsn)
        monitor = psycopg2.connect(isolated_postgres_dsn)
        reader.autocommit = True
        monitor.autocommit = True
        deploy: dict[str, Any] = {}
        thread: Optional[threading.Thread] = None
        try:
            ensure_ledger(runner)
            runner_pid = runner.get_backend_pid()
            with writer.cursor() as cursor:
                cursor.execute(
                    "UPDATE public.vault_completions SET on_chain_tx_error = 'held' "
                    "WHERE activity_id = %s",
                    (activity_id,),
                )

            def _deploy() -> None:
                started = time.monotonic()
                try:
                    apply_migration(runner, migration)
                    deploy["outcome"] = "applied"
                except psycopg2.Error as exc:
                    deploy["outcome"] = exc.pgcode
                deploy["seconds"] = time.monotonic() - started

            thread = threading.Thread(target=_deploy)
            thread.start()
            assert _wait_until_blocked(monitor, runner_pid)

            with reader.cursor() as cursor:
                cursor.execute("SET statement_timeout = '1s'")
                cursor.execute("SELECT count(*) FROM public.vault_completions")
                assert cursor.fetchone() == (1,)

            thread.join(timeout=15.0)
            assert not thread.is_alive(), "the deploy waited past its lock_timeout"
            assert deploy["outcome"] == "55P03", deploy  # lock_not_available
            assert 4.5 <= deploy["seconds"] < 10.0, deploy
        finally:
            writer.rollback()
            if thread is not None:
                thread.join(timeout=15.0)
            writer.close()
            reader.close()
            monitor.close()

        with runner.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.br_sql_migrations")
            assert cursor.fetchone() == (0,)
            assert _new_best_triggers(cursor) == []
        runner.commit()

        apply_migration(runner, migration)
        with runner.cursor() as cursor:
            cursor.execute("SELECT filename FROM public.br_sql_migrations")
            assert cursor.fetchall() == [(NEW_BEST_MIGRATION,)]
            assert len(_new_best_triggers(cursor)) == 4
        runner.commit()
    finally:
        runner.close()


def test_new_best_migration_reapplies_without_duplicating_triggers(db: Any) -> None:
    _apply_new_best(db)
    assert _new_best_triggers(db) == [
        "trg_vault_completion_new_best",
        "trg_vault_completion_new_best_after_delete",
        "trg_vault_completion_new_best_after_insert",
        "trg_vault_completion_new_best_after_update",
    ]


def test_new_best_functions_are_internal_to_the_owner(db: Any) -> None:
    """Supabase lets the API roles execute every new function by default.

    176 revokes all six from them, service_role included, as 152 does for its
    internal helpers: only the SECURITY DEFINER triggers call them.
    """
    db.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_proc, LATERAL aclexplode(pg_proc.proacl) AS acl
            WHERE pg_proc.oid =
                    'public.br_refresh_ride_finalized_at(text)'::regprocedure
              AND acl.grantee = 'service_role'::regrole
              AND acl.privilege_type = 'EXECUTE'
        )
        """
    )
    assert db.fetchone() == (True,), "the stack must start from Supabase's defaults"

    for signature in NEW_BEST_FUNCTIONS:
        db.execute(
            """
            SELECT has_function_privilege('anon', %s, 'EXECUTE'),
                   has_function_privilege('authenticated', %s, 'EXECUTE'),
                   has_function_privilege('service_role', %s, 'EXECUTE')
            """,
            (signature, signature, signature),
        )
        assert db.fetchone() == (False, False, False), signature

    db.execute("SET ROLE service_role")
    try:
        with pytest.raises(psycopg2.Error) as refused:
            db.execute(
                "SELECT public.br_lock_vault_completion_new_best(%s, %s)",
                (RIDER, CLIMB),
            )
        assert refused.value.pgcode == "42501"  # insufficient_privilege
    finally:
        db.execute("RESET ROLE")


def test_runs_on_the_production_vault_completions_trigger_stack(db: Any) -> None:
    db.execute(
        """
        SELECT CASE WHEN tgtype::INTEGER & 2 = 2 THEN 'BEFORE' ELSE 'AFTER' END,
               tgname
        FROM pg_trigger
        WHERE tgrelid = 'public.vault_completions'::regclass
          AND NOT tgisinternal
        ORDER BY 1 DESC, 2
        """
    )
    assert db.fetchall() == [
        ("BEFORE", "account_deletion_write_fence"),
        ("BEFORE", "br_bind_vault_completion_evidence_version"),
        ("BEFORE", "br_vault_completion_settlement_clock"),
        ("BEFORE", "enforce_vault_completion_chain_authority_trigger"),
        ("BEFORE", "trg_vault_completion_new_best"),
        ("AFTER", "br_vault_completion_finalized_at_trigger"),
        ("AFTER", "trg_vault_completion_new_best_after_delete"),
        ("AFTER", "trg_vault_completion_new_best_after_insert"),
        ("AFTER", "trg_vault_completion_new_best_after_update"),
    ]

    # 155 binds every confirmed row to exactly one frozen evidence authority,
    # so a hand-inserted confirmed row cannot stand in for a writer.
    with pytest.raises(psycopg2.Error, match="lacks one frozen evidence authority"):
        db.execute(
            """
            INSERT INTO public.vault_completions (
                vault_signature, wallet, activity_id, time_seconds,
                completed_at, chain_confirmation_status, completion_receipt_pda,
                completion_evidence_hash, chain_confirmed_at
            ) VALUES (%s, %s, %s, 300, %s, 'confirmed', 'receipt', %s, now())
            """,
            (CLIMB, RIDER, str(uuid.uuid4()), _ride_time(0), _digest("unbound")),
        )
    # 152's fence checks every write: a wallet without an account is refused.
    with pytest.raises(psycopg2.Error, match="account_identity_write_fenced"):
        _record_pending(db, day=0, time_s=300, wallet="rider-without-account")


# ---------------------------------------------------------------------------
# The four rider-visible cases, through the production reconcile writer
# ---------------------------------------------------------------------------


def test_current_writer_never_sets_new_best_before_this_migration(
    db_before_new_best: Any,
) -> None:
    """Root cause, pinned: migration 128's writer leaves the false default."""
    first = _record_confirmed(db_before_new_best, day=0, time_s=300)
    assert _flag(db_before_new_best, first) is False


def test_first_effort_on_a_climb_is_a_new_best(db: Any) -> None:
    first = _record_confirmed(db, day=0, time_s=300)

    assert _flag(db, first) is True


def test_faster_effort_is_a_new_best(db: Any) -> None:
    first = _record_confirmed(db, day=0, time_s=300)
    faster = _record_confirmed(db, day=2, time_s=299)

    assert _flags(db) == {first: True, faster: True}


def test_slower_effort_is_not_a_new_best(db: Any) -> None:
    first = _record_confirmed(db, day=0, time_s=300)
    slower = _record_confirmed(db, day=2, time_s=301)

    assert _flags(db) == {first: True, slower: False}


def test_tied_effort_is_not_a_new_best(db: Any) -> None:
    first = _record_confirmed(db, day=0, time_s=300)
    tie = _record_confirmed(db, day=2, time_s=300)
    faster_after_tie = _record_confirmed(db, day=4, time_s=299)

    assert _flags(db) == {first: True, tie: False, faster_after_tie: True}
    _assert_ride_page_matches_climb_page(db)


# ---------------------------------------------------------------------------
# Order, scope and lifecycle
# ---------------------------------------------------------------------------


def test_processing_order_never_decides(db: Any) -> None:
    """A held ride released after newer rides re-decides them (§6.3)."""
    wednesday = _record_confirmed(db, day=2, time_s=300)
    assert _flag(db, wednesday) is True

    monday = _release_held_ride(db, day=0, time_s=290)
    assert _flags(db) == {monday: True, wednesday: False}

    friday = _record_confirmed(db, day=4, time_s=295)
    sunday = _release_held_ride(db, day=-1, time_s=310)
    assert _flags(db) == {
        sunday: True,
        monday: True,
        wednesday: False,
        friday: False,
    }
    _assert_ride_page_matches_climb_page(db)


def test_a_late_slower_ride_leaves_later_bests_alone(db: Any) -> None:
    wednesday = _record_confirmed(db, day=2, time_s=300)
    monday = _release_held_ride(db, day=0, time_s=320)

    assert _flags(db) == {monday: True, wednesday: True}


def test_only_the_riders_own_confirmed_timed_efforts_on_that_climb_count(
    db: Any,
) -> None:
    rival = _record_confirmed(db, day=0, time_s=200, wallet=OTHER_RIDER)
    other_climb = _record_confirmed(db, day=0, time_s=200, climb=OTHER_CLIMB)
    pending = _record_pending(db, day=1, time_s=250)
    untimed = _record_confirmed(db, day=1.5, time_s=None)
    first_timed = _record_confirmed(db, day=2, time_s=300)

    assert _flag(db, rival) is True
    assert _flag(db, other_climb, climb=OTHER_CLIMB) is True
    assert _flags(db) == {
        pending: False,
        untimed: False,
        first_timed: True,
    }
    _assert_ride_page_matches_climb_page(db)


def test_pending_evidence_becomes_a_new_best_when_confirmed(db: Any) -> None:
    ride_id = _new_ride(db)
    _record_pending(db, day=0, time_s=300, ride_id=ride_id)
    assert _flag(db, str(ride_id)) is False

    later = _record_confirmed(db, day=2, time_s=310)
    assert _flag(db, later) is True

    _record_confirmed(db, day=0, time_s=300, ride_id=ride_id)
    assert _flags(db) == {str(ride_id): True, later: False}


def test_invalidating_a_best_re_decides_later_efforts(db: Any) -> None:
    monday = _record_confirmed(db, day=0, time_s=290)
    wednesday = _record_confirmed(db, day=2, time_s=300)
    assert _flags(db) == {monday: True, wednesday: False}

    db.execute(
        "UPDATE public.vault_completions SET validated = false WHERE activity_id = %s",
        (monday,),
    )
    assert _flags(db) == {monday: False, wednesday: True}

    db.execute(
        "UPDATE public.vault_completions SET validated = true WHERE activity_id = %s",
        (monday,),
    )
    assert _flags(db) == {monday: True, wednesday: False}

    db.execute("DELETE FROM public.vault_completions WHERE activity_id = %s", (monday,))
    assert _flags(db) == {wednesday: True}


def test_retimed_or_moved_effort_is_re_decided(db: Any) -> None:
    monday = _record_confirmed(db, day=0, time_s=300)
    wednesday = _record_confirmed(db, day=2, time_s=310)
    assert _flags(db) == {monday: True, wednesday: False}

    db.execute(
        "UPDATE public.vault_completions SET time_seconds = 299 WHERE activity_id = %s",
        (wednesday,),
    )
    assert _flags(db) == {monday: True, wednesday: True}

    # A moved effort is re-decided against the efforts now before it.
    db.execute(
        "UPDATE public.vault_completions SET completed_at = completed_at + interval '3 days' "
        "WHERE activity_id = %s",
        (monday,),
    )
    assert _flags(db) == {wednesday: True, monday: False}
    _assert_ride_page_matches_climb_page(db)

    db.execute(
        "UPDATE public.vault_completions SET completed_at = completed_at - interval '3 days' "
        "WHERE activity_id = %s",
        (monday,),
    )
    assert _flags(db) == {monday: True, wednesday: True}


def test_rule_never_compares_an_effort_with_its_own_stored_version(db: Any) -> None:
    """What an UPDATE's BEFORE trigger sees while moving an effort later."""
    only = _record_confirmed(db, day=0, time_s=300)
    db.execute(
        """
        SELECT public.br_vault_completion_is_new_best(
            id, vault_signature, wallet, completed_at + interval '3 days',
            time_seconds, validated, chain_confirmation_status
        )
        FROM public.vault_completions WHERE activity_id = %s
        """,
        (only,),
    )
    assert db.fetchone()[0] is True


def test_flag_is_owned_by_the_rule_not_the_writer(db: Any) -> None:
    first = _record_confirmed(db, day=0, time_s=300)
    slower = _record_confirmed(db, day=2, time_s=310)

    db.execute(
        "UPDATE public.vault_completions SET is_pr = true WHERE activity_id = %s",
        (slower,),
    )
    db.execute(
        "UPDATE public.vault_completions SET is_pr = NULL WHERE activity_id = %s",
        (first,),
    )
    db.execute(
        "UPDATE public.vault_completions SET on_chain_tx = 'tx-mirror' "
        "WHERE activity_id IN (%s, %s)",
        (first, slower),
    )

    assert _flags(db) == {first: True, slower: False}


def test_service_role_writers_keep_working_without_any_grant(db: Any) -> None:
    """Ride processing, the REST fallback, the coordinator and the tx mirror
    all write as service_role, which holds no grant on 176's functions."""
    monday, wednesday = _new_ride(db), _new_ride(db)
    monday_lease = _freeze_completion_step(
        db, ride_id=monday, day=0, time_s=280, wallet=RIDER, climb=CLIMB,
        finalized=False,
    )
    wednesday_lease = _freeze_completion_step(
        db, ride_id=wednesday, day=2, time_s=290, wallet=RIDER, climb=CLIMB,
        finalized=False,
    )

    db.execute("SET ROLE service_role")
    try:
        # Ride processing: 128's projection RPC.
        _record_pending(db, day=0, time_s=280, ride_id=monday)
        # The repository REST fallback: a PostgREST merge-duplicates upsert.
        db.execute(
            """
            INSERT INTO public.vault_completions (
                vault_signature, wallet, activity_id, time_seconds,
                completed_at, validated, validation_notes, cal_tribute
            ) VALUES (%s, %s, %s, %s, %s, true, NULL, 0)
            ON CONFLICT (vault_signature, activity_id) DO UPDATE SET
                wallet = EXCLUDED.wallet,
                time_seconds = EXCLUDED.time_seconds,
                completed_at = EXCLUDED.completed_at,
                validated = EXCLUDED.validated,
                validation_notes = EXCLUDED.validation_notes,
                cal_tribute = EXCLUDED.cal_tribute
            """,
            (CLIMB, RIDER, str(wednesday), 290, _ride_time(2)),
        )
        # The coordinator's reconcile RPC: Wednesday lands, then Monday late.
        _reconcile(db, str(wednesday), wednesday_lease)
        assert _flag(db, str(wednesday)) is True
        _reconcile(db, str(monday), monday_lease)
        # The projector's tx mirror.
        db.execute(
            """
            UPDATE public.vault_completions
            SET on_chain_tx = 'tx-' || activity_id, on_chain_tx_error = NULL
            WHERE vault_signature = %s
            """,
            (CLIMB,),
        )
    finally:
        db.execute("RESET ROLE")

    assert _flags(db) == {str(monday): True, str(wednesday): False}


def test_account_anonymization_keeps_the_riders_bests(db: Any) -> None:
    """152 rewrites wallet and activity_id on every row in one statement.

    Rows are stored out of ride order, so the statement visits a later ride
    before the earlier ride it ties; the AFTER pass must settle it.
    """
    efforts = {(4, 290): True, (1, 300): False, (-1, 310): True, (2, 305): False, (0, 300): True}
    activity_ids = {
        _record_confirmed(db, day=day, time_s=time_s): is_new_best
        for (day, time_s), is_new_best in efforts.items()
    }
    db.execute(
        "SELECT activity_id, id::TEXT FROM public.vault_completions WHERE wallet = %s",
        (RIDER,),
    )
    id_by_activity = dict(db.fetchall())
    expected = {
        id_by_activity[activity_id]: is_new_best
        for activity_id, is_new_best in activity_ids.items()
    }
    assert _flags(db) == activity_ids

    anonymous_wallet = f"anonymous:{uuid.uuid4()}"
    anonymize_vault_completions(db, RIDER, anonymous_wallet)

    db.execute(
        "SELECT id::TEXT, is_pr FROM public.vault_completions WHERE wallet = %s",
        (anonymous_wallet,),
    )
    assert dict(db.fetchall()) == expected
    _assert_ride_page_matches_climb_page(db, wallet=anonymous_wallet)


@pytest.mark.parametrize("holder_is_earlier", [False, True])
def test_concurrent_rides_for_one_rider_and_climb_serialize(
    isolated_postgres_dsn: str,
    holder_is_earlier: bool,
) -> None:
    """Two rides projected at once still see each other (READ COMMITTED)."""
    with _connection(isolated_postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install(cursor, with_new_best=True)

    holder = psycopg2.connect(isolated_postgres_dsn)
    waiter = psycopg2.connect(isolated_postgres_dsn)
    try:
        holder_day, waiter_day = (0, 2) if holder_is_earlier else (2, 0)
        holder_time, waiter_time = (290, 300) if holder_is_earlier else (300, 290)

        with holder.cursor() as holder_cursor:
            held = _record_confirmed(holder_cursor, day=holder_day, time_s=holder_time)

        waited: dict[str, Any] = {}

        def _write_while_held() -> None:
            try:
                with waiter.cursor() as waiter_cursor:
                    waited["activity_id"] = _record_confirmed(
                        waiter_cursor, day=waiter_day, time_s=waiter_time
                    )
                waiter.commit()
            except BaseException as exc:  # surfaced below
                waited["error"] = exc

        thread = threading.Thread(target=_write_while_held)
        thread.start()
        thread.join(timeout=1.0)
        assert thread.is_alive(), "the second write did not wait for the first"

        holder.commit()
        thread.join(timeout=10.0)
        assert not thread.is_alive()
        assert "error" not in waited, waited.get("error")
    finally:
        holder.close()
        waiter.close()

    with _connection(isolated_postgres_dsn) as connection:
        with connection.cursor() as cursor:
            monday = held if holder_is_earlier else waited["activity_id"]
            wednesday = waited["activity_id"] if holder_is_earlier else held
            assert _flags(cursor) == {monday: True, wednesday: False}


# ---------------------------------------------------------------------------
# A held ride released late, on finalized history
# ---------------------------------------------------------------------------


def _release_monday_after_the_week(cursor: Any) -> dict[str, Any]:
    """Wednesday and Friday are settled and finalized; Saturday ties Friday.

    Then Monday's held ride, the fastest of the week, is released.
    """
    rides = {
        "wednesday": _record_confirmed(cursor, day=2, time_s=300, finalized=True),
        "friday": _record_confirmed(cursor, day=4, time_s=295, finalized=True),
        "saturday": _record_confirmed(cursor, day=5, time_s=295),
    }
    before = {
        "flags": _flags(cursor),
        "rows": _completion_rows_without_flag(cursor),
        "finalized_at": _ride_finalization(cursor),
    }
    rides["monday"] = _release_held_ride(cursor, day=0, time_s=290)
    return {"rides": rides, "before": before}


def test_late_released_earlier_ride_becomes_the_new_best_and_later_rides_lose_it(
    db: Any,
) -> None:
    week = _release_monday_after_the_week(db)
    rides = week["rides"]

    assert week["before"]["flags"] == {
        rides["wednesday"]: True,
        rides["friday"]: True,
        rides["saturday"]: False,
    }
    assert _flags(db) == {
        rides["monday"]: True,
        rides["wednesday"]: False,
        rides["friday"]: False,
        rides["saturday"]: False,
    }
    _assert_ride_page_matches_climb_page(db)


def test_late_release_changes_no_other_column(db: Any) -> None:
    week = _release_monday_after_the_week(db)

    after = _completion_rows_without_flag(db)
    for completion_id, row in week["before"]["rows"].items():
        assert after[completion_id] == row, completion_id


def test_late_release_leaves_rides_finalized_at_unchanged(db: Any) -> None:
    week = _release_monday_after_the_week(db)
    rides = week["rides"]
    before = week["before"]["finalized_at"]

    finalized = {ride for ride, at in before.items() if at is not None}
    assert finalized == {rides["wednesday"], rides["friday"]}
    after = _ride_finalization(db)
    for ride_id, finalized_at in before.items():
        assert after[ride_id] == finalized_at, ride_id


# ---------------------------------------------------------------------------
# The separate, unrun backfill
# ---------------------------------------------------------------------------


def _history_written_before_new_best(cursor: Any) -> dict[str, bool]:
    """Rides recorded by the pre-176 writers, then the migration lands."""
    sunday = _record_confirmed(cursor, day=-1, time_s=310)
    monday = _record_confirmed(cursor, day=0, time_s=300)
    tuesday = _record_confirmed(cursor, day=1, time_s=300)
    wednesday = _record_confirmed(cursor, day=2, time_s=305)
    friday = _record_confirmed(cursor, day=4, time_s=290)
    rival = _record_confirmed(cursor, day=0, time_s=280, wallet=OTHER_RIDER)
    legacy = _record_pending(cursor, day=3, time_s=250)
    _apply_new_best(cursor)
    return {
        sunday: True,
        monday: True,
        tuesday: False,
        wednesday: False,
        friday: True,
        legacy: False,
    } | {f"{OTHER_RIDER}:{rival}": True}


def _all_flags(cursor: Any) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT CASE WHEN wallet = %s THEN activity_id
                    ELSE wallet || ':' || activity_id END,
               is_pr
        FROM public.vault_completions
        """,
        (RIDER,),
    )
    return dict(cursor.fetchall())


def _committing_backfill() -> str:
    script = BACKFILL_SCRIPT.read_text(encoding="utf-8")
    assert script.rstrip().endswith("ROLLBACK;")
    return script.rstrip()[: -len("ROLLBACK;")] + "COMMIT;\n"


def test_backfill_is_a_dry_run_as_written(db_before_new_best: Any) -> None:
    cursor = db_before_new_best
    expected = _history_written_before_new_best(cursor)
    before = _all_flags(cursor)
    assert before == {key: False for key in expected}

    cursor.execute(BACKFILL_SCRIPT.read_text(encoding="utf-8"))

    assert _all_flags(cursor) == before


def test_backfill_repairs_only_the_flag_when_committed(db_before_new_best: Any) -> None:
    cursor = db_before_new_best
    expected = _history_written_before_new_best(cursor)
    before_rows = _completion_rows_without_flag(cursor)

    cursor.execute(_committing_backfill())

    assert _all_flags(cursor) == expected
    assert _completion_rows_without_flag(cursor) == before_rows
    _assert_ride_page_matches_climb_page(cursor)


def test_backfill_refuses_to_rewrite_anything_but_the_flag(
    db_before_new_best: Any,
) -> None:
    cursor = db_before_new_best
    expected = _history_written_before_new_best(cursor)
    target = next(key for key, value in expected.items() if value and ":" not in key)
    cursor.execute(
        """
        ALTER TABLE public.vault_completions
            DISABLE TRIGGER br_vault_completion_settlement_clock;
        UPDATE public.vault_completions SET settlement_week = settlement_week + 1
        WHERE activity_id = %s;
        ALTER TABLE public.vault_completions
            ENABLE TRIGGER br_vault_completion_settlement_clock;
        """,
        (target,),
    )
    before = _all_flags(cursor)

    with pytest.raises(psycopg2.Error, match="besides is_pr"):
        cursor.execute(_committing_backfill())
    cursor.execute("ROLLBACK")

    assert _all_flags(cursor) == before


def test_backfill_refuses_to_run_before_the_migration(
    db_before_new_best: Any,
) -> None:
    cursor = db_before_new_best
    with pytest.raises(psycopg2.Error, match="176_vault_completion_new_best"):
        cursor.execute(_committing_backfill())
    cursor.execute("ROLLBACK")
