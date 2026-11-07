from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from psycopg2.extras import RealDictCursor


LEGACY_ANCHOR_UNIX = 1_704_020_400
V2_ANCHOR_UNIX = 1_704_110_400
WEEK_SECONDS = 604_800
GRACE_SECONDS = 86_400
CUTOVER_WEEK = 200
CUTOVER_UNIX = V2_ANCHOR_UNIX + CUTOVER_WEEK * WEEK_SECONDS
POSTGRES_17_HOME = Path("/opt/homebrew/opt/postgresql@17/bin")


def _postgres_major_version(initdb: Path) -> int | None:
    try:
        result = subprocess.run(
            [str(initdb), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"\b(\d+)(?:\.\d+)?\b", result.stdout)
    return int(match.group(1)) if match else None


def _find_postgres_17_bin() -> Path | None:
    candidates = [POSTGRES_17_HOME]
    for tool in ("initdb", "pg_ctl"):
        resolved = shutil.which(tool)
        if resolved is not None:
            candidates.append(Path(resolved).resolve().parent)
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        initdb = candidate / "initdb"
        pg_ctl = candidate / "pg_ctl"
        if (
            initdb.is_file()
            and pg_ctl.is_file()
            and _postgres_major_version(initdb) == 17
        ):
            return candidate
    return None


def _unavailable_postgres_runtime(reason: str) -> None:
    required = any(
        os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in ("CI", "REQUIRE_PG_RUNTIME")
    )
    if required:
        pytest.fail(reason)
    pytest.skip(reason)


def _docker(
    *args: str,
    check: bool = True,
    timeout_s: float = 10,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


@pytest.fixture(scope="module")
def postgres_dsn() -> Iterator[str]:
    postgres_bin = _find_postgres_17_bin()
    if postgres_bin is not None:
        with tempfile.TemporaryDirectory(prefix="br-clock-pgtest-") as temporary_dir:
            root = Path(temporary_dir)
            data_dir = root / "data"
            socket_dir = root / "socket"
            socket_dir.mkdir()
            subprocess.run(
                [
                    str(postgres_bin / "initdb"),
                    "-D",
                    str(data_dir),
                    "-A",
                    "trust",
                    "--no-locale",
                    "-U",
                    "postgres",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    str(postgres_bin / "pg_ctl"),
                    "-D",
                    str(data_dir),
                    "-l",
                    str(root / "postgres.log"),
                    "-o",
                    f"-F -k {socket_dir} -c listen_addresses= -p 5432",
                    "-w",
                    "start",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            try:
                yield f"host={socket_dir} port=5432 dbname=postgres user=postgres"
            finally:
                subprocess.run(
                    [
                        str(postgres_bin / "pg_ctl"),
                        "-D",
                        str(data_dir),
                        "-m",
                        "immediate",
                        "-w",
                        "stop",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
        return

    if shutil.which("docker") is None:
        _unavailable_postgres_runtime(
            "PostgreSQL 17 tools or Docker are required for the PostgreSQL runtime contracts"
        )
    try:
        # A busy hosted runner can take well over 10 s to answer while earlier
        # modules' containers stop (CI run 38645828134 on 14 Oct 2026).
        probe = _docker("info", check=False, timeout_s=60)
    except subprocess.TimeoutExpired:
        _unavailable_postgres_runtime("Docker daemon did not respond within 60 seconds")
        return
    if probe.returncode != 0:
        _unavailable_postgres_runtime(
            "Docker daemon is unavailable for the PostgreSQL runtime contracts"
        )

    container = f"br-clock-pgtest-{uuid.uuid4().hex[:10]}"
    started = _docker(
        "run",
        "--rm",
        "-d",
        "--name",
        container,
        "-e",
        "POSTGRES_PASSWORD=postgres",
        "-P",
        "postgres:17",
        timeout_s=120,
    )
    assert started.stdout.strip()
    try:
        port_result = _docker(
            "inspect",
            "-f",
            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
            container,
        )
        port = int(port_result.stdout.strip())
        dsn = f"host=127.0.0.1 port={port} dbname=postgres user=postgres password=postgres"
        deadline = time.monotonic() + 30
        while True:
            try:
                connection = psycopg2.connect(dsn)
                connection.close()
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        yield dsn
    finally:
        _docker("rm", "-f", "-v", container, check=False)  # -v: drop the data volume too


@pytest.fixture
def isolated_postgres_dsn(postgres_dsn: str) -> Iterator[str]:
    database_name = f"br_clock_{uuid.uuid4().hex[:12]}"
    admin_connection = psycopg2.connect(postgres_dsn)
    try:
        admin_connection.autocommit = True
        with admin_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
    finally:
        admin_connection.close()

    try:
        yield make_dsn(postgres_dsn, dbname=database_name)
    finally:
        admin_connection = psycopg2.connect(postgres_dsn)
        try:
            admin_connection.autocommit = True
            with admin_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
                )
        finally:
            admin_connection.close()


@contextmanager
def _connection(dsn: str, *, dict_rows: bool = False) -> Iterator[Any]:
    connection = psycopg2.connect(
        dsn,
        cursor_factory=RealDictCursor if dict_rows else None,
    )
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _timestamp(unix_seconds: int) -> datetime:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def _bootstrap_schema(
    cursor: Any,
    *,
    include_legacy_rollover_table: bool = True,
    include_legacy_leaderboard_writer: bool = True,
) -> None:
    cursor.execute(
        """
        CREATE TABLE public.indexed_program_config (
            id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            pda TEXT NOT NULL,
            chain_slot NUMERIC(39, 0),
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE public.settlement_planning_state (
            id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE public.settlement_week_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            settlement_week NUMERIC(39, 0) NOT NULL UNIQUE,
            source_kind TEXT NOT NULL DEFAULT 'authoritative',
            settlement_clock_version SMALLINT
        );

        CREATE TABLE public.settlement_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES public.settlement_week_runs(id),
            settlement_week NUMERIC(39, 0) NOT NULL,
            settlement_clock_version SMALLINT
        );

        CREATE TABLE public.settlement_reconciliations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL REFERENCES public.settlement_jobs(id),
            settlement_clock_version SMALLINT
        );

        CREATE TABLE public.settlement_notification_outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            job_id UUID NOT NULL REFERENCES public.settlement_jobs(id),
            settlement_clock_version SMALLINT
        );

        CREATE TABLE public.vault_completions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_signature TEXT NOT NULL,
            wallet TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            on_chain_tx TEXT
        );

        CREATE TABLE public.indexed_epoch_distributions (
            tx_signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            vault_id BIGINT NOT NULL,
            epoch BIGINT NOT NULL,
            block_time BIGINT,
            finalized_at TIMESTAMPTZ GENERATED ALWAYS AS (
                CASE WHEN block_time IS NOT NULL THEN to_timestamp(block_time) END
            ) STORED,
            settlement_clock_version SMALLINT,
            PRIMARY KEY (tx_signature, event_index)
        );

        CREATE TABLE public.indexed_legends (
            vault_id BIGINT PRIMARY KEY,
            term_start_epoch BIGINT NOT NULL,
            term_end_epoch BIGINT NOT NULL,
            term_start_at TIMESTAMPTZ,
            term_end_at TIMESTAMPTZ
        );

        CREATE TABLE public.indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE
        );

        CREATE TABLE public.rides (
            id TEXT PRIMARY KEY,
            finalized_at TIMESTAMPTZ
        );

        CREATE TABLE public.epoch_distributions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            epoch BIGINT NOT NULL,
            vault_id BIGINT,
            vault_signature TEXT,
            finalized_at TIMESTAMPTZ
        );

        CREATE TABLE public.vault_leaderboards (
            wallet TEXT NOT NULL,
            rank INTEGER NOT NULL,
            achieved_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE public.points_events (
            wallet TEXT NOT NULL,
            points_delta NUMERIC NOT NULL,
            event_type TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            reference_id TEXT
        );

        CREATE FUNCTION public.br_settlement_week(p_completed_at TIMESTAMPTZ)
        RETURNS BIGINT LANGUAGE SQL STABLE AS $$
            SELECT GREATEST(
                0,
                FLOOR(
                    (EXTRACT(EPOCH FROM p_completed_at) - 1704020400)::NUMERIC
                    / 604800
                )::BIGINT
            );
        $$;
        CREATE FUNCTION public.br_refresh_ride_finalized_at(TEXT)
        RETURNS VOID LANGUAGE SQL AS 'SELECT';
        CREATE FUNCTION public.br_sync_epoch_distribution_finalized_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            v_activity_id TEXT;
        BEGIN
            FOR v_activity_id IN
                SELECT DISTINCT vc.activity_id
                FROM public.vault_completions vc
                JOIN public.indexed_vaults iv
                  ON iv.signature_hex = vc.vault_signature
                WHERE iv.id = NEW.vault_id
                  AND public.br_settlement_week(vc.completed_at) = NEW.epoch
                  AND vc.on_chain_tx IS NOT NULL
            LOOP
                PERFORM public.br_refresh_ride_finalized_at(v_activity_id);
            END LOOP;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER br_indexed_epoch_distribution_finalized_at_trigger
        AFTER INSERT OR UPDATE ON public.indexed_epoch_distributions
        FOR EACH ROW EXECUTE FUNCTION public.br_sync_epoch_distribution_finalized_at();

        CREATE FUNCTION public.elect_swanny(TEXT, INTEGER)
        RETURNS VOID LANGUAGE SQL AS 'SELECT';
        CREATE FUNCTION public.claim_inactive_seat(TEXT, TEXT)
        RETURNS VOID LANGUAGE SQL AS 'SELECT';
        CREATE FUNCTION public.get_current_epoch_for_history()
        RETURNS INTEGER LANGUAGE SQL AS 'SELECT 0';
        CREATE FUNCTION public.record_leaderboard_entry(
            TEXT, TEXT, INTEGER, INTEGER, INTEGER
        ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
        """
    )
    if include_legacy_leaderboard_writer:
        cursor.execute(
            """
            CREATE FUNCTION public.update_vault_leaderboard(
                TEXT, TEXT, INTEGER, INTEGER, UUID
            ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
            CREATE FUNCTION public.update_vault_leaderboard(
                TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ
            ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
            CREATE FUNCTION public.update_vault_leaderboard(
                TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ, TEXT, UUID
            ) RETURNS VOID LANGUAGE SQL AS 'SELECT';
            """
        )
    if include_legacy_rollover_table:
        cursor.execute(
            """
            CREATE TABLE public.local_legend_rollovers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                vault_id BIGINT NOT NULL,
                vault_signature TEXT NOT NULL,
                term_start_epoch BIGINT NOT NULL,
                term_end_epoch BIGINT NOT NULL,
                previous_holder TEXT,
                outcome TEXT NOT NULL CHECK (outcome IN ('elected', 'dormant')),
                status TEXT NOT NULL CHECK (status IN ('confirmed', 'failed')),
                winner TEXT,
                winner_completions INTEGER NOT NULL DEFAULT 0,
                runner_up TEXT,
                runner_up_completions INTEGER NOT NULL DEFAULT 0,
                tx_signature TEXT,
                error_message TEXT,
                processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                term_start_at TIMESTAMPTZ,
                term_end_at TIMESTAMPTZ,
                UNIQUE (vault_id, term_end_epoch)
            );
            """
        )


def _seed_legacy_rows(cursor: Any) -> dict[str, Any]:
    legacy_completion_at = _timestamp(LEGACY_ANCHOR_UNIX + 199 * WEEK_SECONDS + 123)
    bridge_completion_at = _timestamp(LEGACY_ANCHOR_UNIX + CUTOVER_WEEK * WEEK_SECONDS + 123)
    cursor.execute(
        """
        INSERT INTO public.indexed_program_config (id, pda, chain_slot)
        VALUES (1, 'program-config-pda', 100);
        INSERT INTO public.settlement_planning_state (id) VALUES (1);
        INSERT INTO public.settlement_week_runs (
            settlement_week, source_kind, settlement_clock_version
        ) VALUES (199, 'authoritative', 1) RETURNING id
        """
    )
    run_id = cursor.fetchone()["id"]
    cursor.execute(
        """
        INSERT INTO public.settlement_jobs (run_id, settlement_week, settlement_clock_version)
        VALUES (%s, 199, 1) RETURNING id
        """,
        (run_id,),
    )
    job_id = cursor.fetchone()["id"]
    cursor.execute(
        """
        INSERT INTO public.settlement_reconciliations (job_id, settlement_clock_version)
        VALUES (%s, 1);
        INSERT INTO public.settlement_notification_outbox (job_id, settlement_clock_version)
        VALUES (%s, 1);
        INSERT INTO public.indexed_vaults (id, signature_hex)
        VALUES (1, 'vault-1');
        INSERT INTO public.vault_completions (
            vault_signature, wallet, activity_id, completed_at, on_chain_tx
        ) VALUES
            ('vault-1', 'rider-1', 'ride-legacy', %s, 'tx-legacy'),
            ('vault-1', 'rider-2', 'ride-bridge', %s, 'tx-bridge');
        INSERT INTO public.indexed_epoch_distributions (
            tx_signature, event_index, vault_id, epoch, block_time,
            settlement_clock_version
        ) VALUES ('distribution-legacy', 0, 1, 199, %s, 2);
        INSERT INTO public.indexed_legends (
            vault_id, term_start_epoch, term_end_epoch, term_start_at, term_end_at
        ) VALUES (1, 191, 199, %s, %s);
        INSERT INTO public.local_legend_rollovers (
            vault_id, vault_signature, term_start_epoch, term_end_epoch,
            outcome, status, term_start_at, term_end_at
        ) VALUES (1, 'vault-1', 191, 199, 'elected', 'confirmed', %s, %s);
        """,
        (
            job_id,
            job_id,
            legacy_completion_at,
            bridge_completion_at,
            LEGACY_ANCHOR_UNIX + 200 * WEEK_SECONDS + GRACE_SECONDS,
            _timestamp(LEGACY_ANCHOR_UNIX + 191 * WEEK_SECONDS),
            _timestamp(LEGACY_ANCHOR_UNIX + 199 * WEEK_SECONDS),
            _timestamp(LEGACY_ANCHOR_UNIX + 191 * WEEK_SECONDS),
            _timestamp(LEGACY_ANCHOR_UNIX + 199 * WEEK_SECONDS),
        ),
    )
    return {
        "run_id": run_id,
        "job_id": job_id,
        "legacy_completion_at": legacy_completion_at,
        "bridge_completion_at": bridge_completion_at,
    }


def test_settlement_clock_migration_bootstraps_missing_rollover_table(
    isolated_postgres_dsn: str,
) -> None:
    migration = (
        Path(__file__).parents[2] / "sql" / "119_settlement_clock_v2.sql"
    ).read_text()

    with _connection(isolated_postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            _bootstrap_schema(cursor, include_legacy_rollover_table=False)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'local_legend_rollovers'
                """
            )
            columns = {row["column_name"] for row in cursor.fetchall()}
            assert {
                "vault_id",
                "vault_signature",
                "term_start_epoch",
                "term_end_epoch",
                "outcome",
                "status",
                "settlement_clock_version",
                "settlement_clock_contract_hash",
            } <= columns


def test_settlement_clock_migration_composes_after_leaderboard_writer_retirement(
    isolated_postgres_dsn: str,
) -> None:
    retirement = (
        Path(__file__).parents[2]
        / "sql"
        / "087_retire_legacy_leaderboard_write_side.sql"
    ).read_text()
    migration = (
        Path(__file__).parents[2] / "sql" / "119_settlement_clock_v2.sql"
    ).read_text()

    with _connection(isolated_postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            _bootstrap_schema(cursor)
            cursor.execute(retirement)

            cursor.execute(
                """
                SELECT
                    to_regprocedure(
                        'public.update_vault_leaderboard(text,text,integer,integer,uuid)'
                    ) AS writer_v1,
                    to_regprocedure(
                        'public.update_vault_leaderboard(text,text,integer,integer,uuid,timestamptz)'
                    ) AS writer_v2,
                    to_regprocedure(
                        'public.update_vault_leaderboard(text,text,integer,integer,uuid,timestamptz,text,uuid)'
                    ) AS writer_v3
                """
            )
            assert cursor.fetchone() == {
                "writer_v1": None,
                "writer_v2": None,
                "writer_v3": None,
            }

            cursor.execute(migration)


def test_settlement_clock_migration_revokes_legacy_writer_when_present(
    isolated_postgres_dsn: str,
) -> None:
    migration = (
        Path(__file__).parents[2] / "sql" / "119_settlement_clock_v2.sql"
    ).read_text()

    with _connection(isolated_postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            _bootstrap_schema(cursor)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_proc AS proc
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(proc.proacl, acldefault('f', proc.proowner))
                    ) AS acl
                    WHERE proc.oid = to_regprocedure(
                        'public.update_vault_leaderboard(text,text,integer,integer,uuid,timestamptz)'
                    )
                      AND acl.grantee = 0
                      AND acl.privilege_type = 'EXECUTE'
                ) AS public_execute
                """
            )
            assert cursor.fetchone() == {"public_execute": False}


def test_settlement_clock_migration_preserves_history_and_binds_future_math(
    postgres_dsn: str,
) -> None:
    migration = (
        Path(__file__).parents[2] / "sql" / "119_settlement_clock_v2.sql"
    ).read_text()

    with _connection(postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            _bootstrap_schema(cursor)
            legacy = _seed_legacy_rows(cursor)

            with pytest.raises(
                psycopg2.Error,
                match="inconsistent indexed_epoch_distributions clock provenance",
            ):
                cursor.execute(migration)
            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET settlement_clock_version = 1
                WHERE tx_signature = 'distribution-legacy'
                """
            )
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT activity_id, settlement_week, settlement_clock_version
                FROM public.vault_completions
                ORDER BY activity_id
                """
            )
            assert cursor.fetchall() == [
                {
                    "activity_id": "ride-bridge",
                    "settlement_week": CUTOVER_WEEK,
                    "settlement_clock_version": 1,
                },
                {
                    "activity_id": "ride-legacy",
                    "settlement_week": 199,
                    "settlement_clock_version": 1,
                },
            ]

            connection.autocommit = False
            try:
                with pytest.raises(
                    psycopg2.Error,
                    match="direct settlement_clock_contract insert is forbidden",
                ):
                    cursor.execute(
                        """
                        INSERT INTO public.settlement_clock_contract (
                            id, contract_version, legacy_anchor_unix, v2_anchor_unix,
                            cutover_unix, cutover_week, duration_seconds, grace_seconds,
                            has_legacy_history, program_config_pda, program_config_slot,
                            program_config_commitment, contract_hash, indexed_at
                        ) VALUES (
                            1, 2, 1704020400, 1704110400,
                            %s, %s, 604800, 86400,
                            TRUE, 'forged-pda', 999, 'finalized', repeat('0', 64), now()
                        )
                        """,
                        (CUTOVER_UNIX, CUTOVER_WEEK),
                    )
            finally:
                connection.rollback()
                connection.autocommit = True

            with pytest.raises(
                psycopg2.Error,
                match="finalized ProgramConfig projection",
            ):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET settlement_clock_v2_starts_at = %s,
                        settlement_clock_version = 2,
                        chain_slot = 101,
                        indexed_at = now()
                    WHERE id = 1
                    """,
                    (CUTOVER_UNIX,),
                )

            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET settlement_clock_v2_starts_at = %s,
                    settlement_clock_version = 2,
                    settlement_clock_source_commitment = 'finalized',
                    chain_slot = 101,
                    indexed_at = now()
                WHERE id = 1
                """,
                (CUTOVER_UNIX,),
            )
            cursor.execute("SELECT * FROM public.settlement_clock_contract WHERE id = 1")
            contract = cursor.fetchone()
            assert contract["cutover_week"] == CUTOVER_WEEK
            assert contract["has_legacy_history"] is True
            assert contract["program_config_slot"] == 101
            assert contract["program_config_commitment"] == "finalized"
            assert len(contract["contract_hash"]) == 64
            int(contract["contract_hash"], 16)

            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET chain_slot = 102, indexed_at = now()
                WHERE id = 1
                """
            )
            cursor.execute(
                """
                SELECT program_config_slot, contract_hash
                FROM public.settlement_clock_contract WHERE id = 1
                """
            )
            assert cursor.fetchone() == {
                "program_config_slot": 101,
                "contract_hash": contract["contract_hash"],
            }
            with pytest.raises(psycopg2.Error, match="ProgramConfig slot regression"):
                cursor.execute(
                    "UPDATE public.indexed_program_config SET chain_slot = 100 WHERE id = 1"
                )

            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET block_time = block_time
                WHERE tx_signature = 'distribution-legacy'
                RETURNING settlement_clock_version, settlement_clock_contract_hash
                """
            )
            assert cursor.fetchone() == {
                "settlement_clock_version": 1,
                "settlement_clock_contract_hash": "legacy-v1:1704020400:604800:86400",
            }
            cursor.execute(
                """
                UPDATE public.indexed_legends
                SET term_start_epoch = term_start_epoch
                WHERE vault_id = 1
                RETURNING settlement_clock_version, settlement_clock_contract_hash
                """
            )
            assert cursor.fetchone() == {
                "settlement_clock_version": 1,
                "settlement_clock_contract_hash": "legacy-v1:1704020400:604800:86400",
            }
            cursor.execute(
                """
                UPDATE public.settlement_week_runs
                SET source_kind = source_kind
                WHERE id = %s
                RETURNING settlement_clock_version, settlement_clock_contract_hash
                """,
                (legacy["run_id"],),
            )
            assert cursor.fetchone() == {
                "settlement_clock_version": 1,
                "settlement_clock_contract_hash": "legacy-v1:1704020400:604800:86400",
            }

            cursor.execute(
                """
                SELECT
                    public.br_settlement_week(to_timestamp(%s)) AS before_week,
                    public.br_settlement_clock_version_at(to_timestamp(%s)) AS before_version,
                    public.br_settlement_week(to_timestamp(%s)) AS fractional_before_week,
                    public.br_settlement_clock_version_at(to_timestamp(%s)) AS fractional_before_version,
                    public.br_settlement_week(to_timestamp(%s)) AS cutover_week,
                    public.br_settlement_clock_version_at(to_timestamp(%s)) AS cutover_version,
                    public.br_settlement_week_start(%s) AS bridge_start,
                    public.br_settlement_week_end(%s) AS bridge_end,
                    public.br_settlement_week_finalization_time(%s) AS bridge_finalizable,
                    public.br_settlement_week_start(%s) AS next_start,
                    public.br_settlement_week_end(%s) AS next_end
                """,
                (
                    CUTOVER_UNIX - 1,
                    CUTOVER_UNIX - 1,
                    CUTOVER_UNIX - 0.4,
                    CUTOVER_UNIX - 0.4,
                    CUTOVER_UNIX,
                    CUTOVER_UNIX,
                    CUTOVER_WEEK,
                    CUTOVER_WEEK,
                    CUTOVER_WEEK,
                    CUTOVER_WEEK + 1,
                    CUTOVER_WEEK + 1,
                ),
            )
            clock = cursor.fetchone()
            assert clock["before_week"] == CUTOVER_WEEK
            assert clock["before_version"] == 1
            assert clock["fractional_before_week"] == CUTOVER_WEEK
            assert clock["fractional_before_version"] == 1
            assert clock["cutover_week"] == CUTOVER_WEEK
            assert clock["cutover_version"] == 2
            assert clock["bridge_start"] == _timestamp(
                LEGACY_ANCHOR_UNIX + CUTOVER_WEEK * WEEK_SECONDS
            )
            assert clock["bridge_end"] == _timestamp(
                V2_ANCHOR_UNIX + (CUTOVER_WEEK + 1) * WEEK_SECONDS
            )
            assert (clock["bridge_end"] - clock["bridge_start"]).total_seconds() == 694_800
            assert clock["bridge_finalizable"] == clock["bridge_end"] + timedelta(
                seconds=GRACE_SECONDS
            )
            assert clock["next_start"] == clock["bridge_end"]
            assert (clock["next_end"] - clock["next_start"]).total_seconds() == WEEK_SECONDS

            cursor.execute(
                """
                INSERT INTO public.vault_completions (
                    vault_signature, wallet, activity_id, completed_at, on_chain_tx
                ) VALUES ('vault-1', 'rider-3', 'ride-v2', to_timestamp(%s), 'tx-v2')
                RETURNING settlement_week, settlement_clock_version
                """,
                (CUTOVER_UNIX,),
            )
            assert cursor.fetchone() == {
                "settlement_week": CUTOVER_WEEK,
                "settlement_clock_version": 2,
            }

            projected_finalized_at = int(clock["bridge_finalizable"].timestamp())
            cursor.execute(
                """
                INSERT INTO public.rides (id) VALUES ('ride-v2');
                INSERT INTO public.epoch_distributions (
                    epoch, vault_id, vault_signature
                ) VALUES (%s, 1, 'vault-1');
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-v2', 0, 1, %s, %s)
                """,
                (CUTOVER_WEEK, CUTOVER_WEEK, projected_finalized_at),
            )
            cursor.execute(
                """
                SELECT
                    (SELECT finalized_at FROM public.epoch_distributions
                     WHERE epoch = %s) AS distribution_finalized_at,
                    (SELECT finalized_at FROM public.rides
                     WHERE id = 'ride-v2') AS ride_finalized_at
                """,
                (CUTOVER_WEEK,),
            )
            finalized = cursor.fetchone()
            assert finalized["distribution_finalized_at"] == clock["bridge_finalizable"]
            assert finalized["ride_finalized_at"] == clock["bridge_finalizable"]

            cursor.execute(
                """
                INSERT INTO public.settlement_week_runs (settlement_week, source_kind)
                VALUES (%s, 'authoritative')
                RETURNING id, settlement_clock_version, settlement_clock_contract_hash,
                    week_starts_at, week_ends_at, finalizable_at, is_cutover_week
                """,
                (CUTOVER_WEEK,),
            )
            cutover_run = cursor.fetchone()
            assert cutover_run["settlement_clock_version"] == 2
            assert cutover_run["settlement_clock_contract_hash"] == contract["contract_hash"]
            assert cutover_run["week_starts_at"] == clock["bridge_start"]
            assert cutover_run["week_ends_at"] == clock["bridge_end"]
            assert cutover_run["finalizable_at"] == clock["bridge_finalizable"]
            assert cutover_run["is_cutover_week"] is True

            cursor.execute(
                """
                INSERT INTO public.settlement_jobs (run_id, settlement_week)
                VALUES (%s, %s)
                RETURNING id, settlement_clock_version, settlement_clock_contract_hash
                """,
                (cutover_run["id"], CUTOVER_WEEK),
            )
            cutover_job = cursor.fetchone()
            assert cutover_job["settlement_clock_version"] == 2
            assert cutover_job["settlement_clock_contract_hash"] == contract["contract_hash"]

            cursor.execute(
                """
                INSERT INTO public.settlement_reconciliations (job_id)
                VALUES (%s)
                RETURNING settlement_clock_version, settlement_clock_contract_hash
                """,
                (cutover_job["id"],),
            )
            assert cursor.fetchone() == {
                "settlement_clock_version": 2,
                "settlement_clock_contract_hash": contract["contract_hash"],
            }
            cursor.execute(
                """
                INSERT INTO public.settlement_notification_outbox (job_id)
                VALUES (%s)
                RETURNING settlement_clock_version, settlement_clock_contract_hash
                """,
                (cutover_job["id"],),
            )
            assert cursor.fetchone() == {
                "settlement_clock_version": 2,
                "settlement_clock_contract_hash": contract["contract_hash"],
            }

            cursor.execute(
                """
                SELECT settlement_clock_version, settlement_clock_contract_hash,
                    week_starts_at, week_ends_at, finalizable_at
                FROM public.settlement_week_runs WHERE id = %s
                """,
                (legacy["run_id"],),
            )
            legacy_run = cursor.fetchone()
            assert legacy_run["settlement_clock_version"] == 1
            assert legacy_run["settlement_clock_contract_hash"].startswith("legacy-v1:")
            assert legacy_run["week_starts_at"] == _timestamp(
                LEGACY_ANCHOR_UNIX + 199 * WEEK_SECONDS
            )

            for function_name in (
                "get_global_kom_leaderboard",
                "get_global_earnings_leaderboard",
                "count_global_kom_leaderboard",
                "count_global_earnings_leaderboard",
                "get_user_global_kom_rank",
                "get_user_global_earnings_rank",
            ):
                cursor.execute(
                    "SELECT pg_get_functiondef(oid) AS definition FROM pg_proc WHERE proname = %s",
                    (function_name,),
                )
                definition = cursor.fetchone()["definition"].lower()
                assert "br_current_settlement_week_start" in definition
                assert "date_trunc" not in definition

            with pytest.raises(psycopg2.Error, match="replace immutable settlement clock"):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET settlement_clock_v2_starts_at = %s
                    WHERE id = 1
                    """,
                    (CUTOVER_UNIX + WEEK_SECONDS,),
                )
            with pytest.raises(psycopg2.Error, match="settlement_clock_contract is immutable"):
                cursor.execute(
                    "UPDATE public.settlement_clock_contract SET cutover_week = 201 WHERE id = 1"
                )

            cursor.execute(migration)
            cursor.execute(
                "SELECT cutover_unix, cutover_week, contract_hash FROM public.settlement_clock_contract"
            )
            assert cursor.fetchone() == {
                "cutover_unix": CUTOVER_UNIX,
                "cutover_week": CUTOVER_WEEK,
                "contract_hash": contract["contract_hash"],
            }


def test_settlement_clock_program_lineage_authorizes_only_ratified_v4b_successor(
    isolated_postgres_dsn: str,
) -> None:
    predecessor_pda = "DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8"
    predecessor_contract_slot = 476_802_238
    predecessor_projection_slot = 477_399_016
    successor_pda = "59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D"
    successor_handoff_slot = 479_325_255
    successor_projection_slot = 479_331_648
    cutover_unix = 1_784_548_800
    expected_hash = (
        "0b05fb0951a522006eb3580a2bdcf8c062ae63237635eecc19cdd17417617e93"
    )
    settlement_migration = (
        Path(__file__).parents[2] / "sql" / "119_settlement_clock_v2.sql"
    ).read_text()
    lineage_migration = (
        Path(__file__).parents[2]
        / "sql"
        / "142_settlement_clock_program_lineage.sql"
    ).read_text()

    with _connection(isolated_postgres_dsn, dict_rows=True) as connection:
        with connection.cursor() as cursor:
            _bootstrap_schema(cursor)
            cursor.execute(
                """
                INSERT INTO public.indexed_program_config (id, pda, chain_slot)
                VALUES (1, %s, %s);
                INSERT INTO public.settlement_planning_state (id) VALUES (1);
                """,
                (predecessor_pda, predecessor_contract_slot),
            )
            cursor.execute(settlement_migration)
            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET settlement_clock_v2_starts_at = %s,
                    settlement_clock_version = 2,
                    settlement_clock_source_commitment = 'finalized',
                    chain_slot = %s,
                    indexed_at = now()
                WHERE id = 1
                """,
                (cutover_unix, predecessor_contract_slot),
            )
            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET chain_slot = %s, indexed_at = now()
                WHERE id = 1
                """,
                (predecessor_projection_slot,),
            )
            cursor.execute(
                """
                SELECT contract_hash, program_config_pda, program_config_slot
                FROM public.settlement_clock_contract
                WHERE id = 1
                """
            )
            contract_before = cursor.fetchone()
            assert contract_before == {
                "contract_hash": expected_hash,
                "program_config_pda": predecessor_pda,
                "program_config_slot": predecessor_contract_slot,
            }

            cursor.execute(lineage_migration)

            cursor.execute(
                """
                SELECT predecessor_program_config_pda,
                    predecessor_program_config_slot,
                    successor_program_config_pda,
                    successor_handoff_slot,
                    contract_hash
                FROM public.settlement_clock_program_lineage
                WHERE id = 1
                """
            )
            assert cursor.fetchone() == {
                "predecessor_program_config_pda": predecessor_pda,
                "predecessor_program_config_slot": predecessor_contract_slot,
                "successor_program_config_pda": successor_pda,
                "successor_handoff_slot": successor_handoff_slot,
                "contract_hash": expected_hash,
            }

            with pytest.raises(psycopg2.Error, match="successor handoff slot"):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET pda = %s, chain_slot = %s, indexed_at = now()
                    WHERE id = 1
                    """,
                    (successor_pda, successor_handoff_slot - 1),
                )

            with pytest.raises(psycopg2.Error, match="ratified successor"):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET pda = 'alternate-program-config',
                        chain_slot = %s,
                        indexed_at = now()
                    WHERE id = 1
                    """,
                    (successor_projection_slot,),
                )

            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET pda = %s, chain_slot = %s, indexed_at = now()
                WHERE id = 1
                """,
                (successor_pda, successor_projection_slot),
            )
            cursor.execute(
                """
                SELECT pda, chain_slot, settlement_clock_v2_starts_at,
                    settlement_clock_version, settlement_clock_source_commitment
                FROM public.indexed_program_config
                WHERE id = 1
                """
            )
            assert cursor.fetchone() == {
                "pda": successor_pda,
                "chain_slot": successor_projection_slot,
                "settlement_clock_v2_starts_at": cutover_unix,
                "settlement_clock_version": 2,
                "settlement_clock_source_commitment": "finalized",
            }

            cursor.execute(
                """
                UPDATE public.indexed_program_config
                SET chain_slot = %s, indexed_at = now()
                WHERE id = 1
                """,
                (successor_projection_slot + 1,),
            )

            with pytest.raises(psycopg2.Error, match="ratified successor"):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET pda = %s, chain_slot = %s, indexed_at = now()
                    WHERE id = 1
                    """,
                    (predecessor_pda, successor_projection_slot + 2),
                )

            with pytest.raises(psycopg2.Error, match="immutable settlement clock"):
                cursor.execute(
                    """
                    UPDATE public.indexed_program_config
                    SET settlement_clock_v2_starts_at = %s,
                        chain_slot = %s,
                        indexed_at = now()
                    WHERE id = 1
                    """,
                    (cutover_unix + WEEK_SECONDS, successor_projection_slot + 2),
                )

            with pytest.raises(psycopg2.Error, match="program lineage is immutable"):
                cursor.execute(
                    """
                    UPDATE public.settlement_clock_program_lineage
                    SET successor_handoff_slot = successor_handoff_slot + 1
                    WHERE id = 1
                    """
                )

            cursor.execute(
                """
                SELECT contract_hash, program_config_pda, program_config_slot
                FROM public.settlement_clock_contract
                WHERE id = 1
                """
            )
            assert cursor.fetchone() == contract_before


def test_settlement_clock_program_lineage_migration_mirror_is_byte_identical() -> None:
    backend_migration = (
        Path(__file__).parents[2]
        / "sql"
        / "142_settlement_clock_program_lineage.sql"
    ).read_bytes()
    supabase_migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "20260727_150_settlement_clock_program_lineage.sql"
    ).read_bytes()
    assert backend_migration == supabase_migration
