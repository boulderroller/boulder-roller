#!/usr/bin/env python3
"""Rehearse canonical Stage 1 migrations against local-only production exports.

Owns a disposable PostgreSQL 17 cluster with TCP disabled. Never accepts a
database URL, reads application configuration, or copies the input artifacts.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import psycopg2
from psycopg2 import sql

if __package__:
    from .apply_sql_migrations import discover_migrations
else:
    from apply_sql_migrations import discover_migrations

BACKEND = Path(__file__).resolve().parents[1]
LEDGER_COLUMNS = (
    "filename", "checksum", "applied_at", "execution_ms", "applied_by", "host", "baseline",
)
STAGE1_START = 169


def expected_migrations(sql_dir: Path) -> list[str]:
    """Rehearse the complete canonical tail after the pre-Stage-1 export."""
    return [migration.filename for migration in discover_migrations(sql_dir)
            if migration.number >= STAGE1_START]

# These are local platform prerequisites, not replacements for app objects.
ROLES = """
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
"""
EXTENSIONS = """
CREATE EXTENSION postgis WITH SCHEMA public;
CREATE EXTENSION pg_trgm WITH SCHEMA public;
CREATE SCHEMA extensions;
CREATE EXTENSION btree_gist WITH SCHEMA extensions;
CREATE EXTENSION pgcrypto WITH SCHEMA extensions;
"""

# A separate restore measures DDL locks without perturbing the timed run.
# The observer executes within the DDL transaction and sees newly created
# relation OIDs; a polling connection could miss these short empty-table locks.
LOCK_OBSERVER = """
CREATE SCHEMA rehearsal;
CREATE TABLE rehearsal.locks (
    migration integer, command text, relation text, mode text, granted boolean
);
CREATE FUNCTION rehearsal.capture_locks() RETURNS event_trigger
LANGUAGE plpgsql SET search_path='' AS $$
DECLARE migration_number integer;
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM pg_catalog.pg_event_trigger_ddl_commands()
        WHERE object_identity='public.idx_balance_stage1_pending_intent'
    ) THEN 174 ELSE 172 END INTO migration_number;
    INSERT INTO rehearsal.locks
    SELECT DISTINCT migration_number, TG_TAG, c.relname, l.mode, l.granted
    FROM pg_catalog.pg_locks l
    JOIN pg_catalog.pg_class c ON c.oid=l.relation
    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
    WHERE l.pid=pg_catalog.pg_backend_pid() AND n.nspname='public'
      AND (c.relname='balance_operations' OR c.oid IN (
          SELECT indexrelid FROM pg_catalog.pg_index
          WHERE indrelid=pg_catalog.to_regclass('public.balance_operations')
      ));
END $$;
CREATE EVENT TRIGGER rehearsal_ddl_locks ON ddl_command_end
EXECUTE FUNCTION rehearsal.capture_locks();
"""


def local_environment() -> dict[str, str]:
    # libpq must not inherit service/host routing or connection options.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PG") and k != "DATABASE_URL"}
    env["LC_ALL"] = "en_US.UTF-8"
    return env


def run(args: list[str], *, env: dict[str, str], input_text: str | None = None,
        timeout: int | None = 180) -> str:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                            env=env, cwd=BACKEND, timeout=timeout)
    if result.returncode:
        # Do not print a schema/ledger payload on failure. psql errors identify
        # the statement and line; migration runner errors identify the file.
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}):\n"
                           f"{result.stdout[-4000:]}\n{result.stderr[-6000:]}")
    return result.stdout


def postgres_bin(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit else [
        Path("/opt/homebrew/opt/postgresql@17/bin"), Path("/usr/lib/postgresql/17/bin"),
        Path(shutil.which("initdb")).parent if shutil.which("initdb") else None,
    ]
    for candidate in candidates:
        if candidate and all((candidate / name).is_file() for name in ("initdb", "pg_ctl", "psql")):
            version = run([str(candidate / "initdb"), "--version"], env=local_environment())
            if re.search(r"\b17\.", version):
                return candidate
    raise RuntimeError("Local PostgreSQL 17 with PostGIS, pg_trgm, btree_gist and pgcrypto is required")


@contextmanager
def cluster(binaries: Path):
    root = Path(tempfile.mkdtemp(prefix="br-stage1-migrations-", dir="/tmp"))
    data = root / "data"
    socket = root / "socket"
    env = local_environment()
    start_attempted = False
    try:
        socket.mkdir(mode=0o700)
        run([str(binaries / "initdb"), "-D", str(data), "-U", "postgres",
             "-A", "trust", "-E", "UTF8", "--no-locale"], env=env)
        start_attempted = True
        run([str(binaries / "pg_ctl"), "-D", str(data), "-l", str(root / "postgres.log"),
             "-o", f"-k {socket} -c listen_addresses= -p 5432", "-w", "start"], env=env)
        dsn = f"host={socket} port=5432 dbname=postgres user=postgres"
        with closing(psycopg2.connect(dsn)) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(ROLES)
        yield dsn, env
    finally:
        if start_attempted:
            status = subprocess.run([str(binaries / "pg_ctl"), "-D", str(data), "status"],
                                    capture_output=True, env=env, timeout=30)
            if status.returncode == 0:
                # If shutdown fails, retain the owned directory for recovery.
                run([str(binaries / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"], env=env)
            elif status.returncode != 3:
                raise RuntimeError(f"Cannot confirm local cluster is stopped; retained {root}")
        shutil.rmtree(root)


def ledger_rows(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT " + ",".join(LEDGER_COLUMNS) +
                       " FROM public.br_sql_migrations ORDER BY filename")
        return [dict(zip(LEDGER_COLUMNS, row)) for row in cursor.fetchall()]


def restore(admin_dsn: str, name: str, schema_text: str, rows: list[dict],
            binaries: Path, env: dict[str, str]) -> tuple[str, list[dict]]:
    with closing(psycopg2.connect(admin_dsn)) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = psycopg2.extensions.make_dsn(admin_dsn, dbname=name)
    with closing(psycopg2.connect(dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public")
        connection.commit()
    marker = "CREATE SCHEMA public;"
    if schema_text.count(marker) != 1:
        raise ValueError("Expected exactly one public schema creation in the pg_dump export")
    # Preserve every exported statement. Add real extension prerequisites just
    # after the dump creates public, before its first geometry type reference.
    restore_text = schema_text.replace(marker, marker + "\n" + EXTENSIONS, 1)
    run([str(binaries / "psql"), "-X", "-q", "--set=ON_ERROR_STOP=1", "--single-transaction",
         "--dbname", dsn], env=env, input_text=restore_text)
    with closing(psycopg2.connect(dsn)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM public.br_sql_migrations")
            if cursor.fetchone()[0] != 0:
                raise ValueError("Expected a schema-only export with an empty migration ledger")
            for row in rows:
                # Insert exactly the supplied fields. Metadata absent from the
                # export gets local table defaults, never invented history.
                fields = [field for field in LEDGER_COLUMNS if field in row]
                cursor.execute(sql.SQL("INSERT INTO public.br_sql_migrations ({}) VALUES ({})").format(
                    sql.SQL(",").join(map(sql.Identifier, fields)),
                    sql.SQL(",").join(sql.Placeholder() for _ in fields),
                ), [row[field] for field in fields])
        connection.commit()
        baseline = ledger_rows(connection)
    return dsn, baseline


def apply_stack(dsn: str, sql_dir: Path, env: dict[str, str]) -> str:
    # Same arguments, cwd and DATABASE_URL mechanism as deploy-backend-release.sh.
    return run([sys.executable, "scripts/apply_sql_migrations.py", "--sql-dir", str(sql_dir),
                "--baseline-through", "101", "--reload-postgrest"],
               env={**env, "DATABASE_URL": dsn})


def rehearse(schema_file: Path, ledger_file: Path, *, sql_dir: Path = BACKEND / "sql",
             binaries: Path | None = None) -> dict:
    # Sanitize the worker process itself: libpq reads PGHOSTADDR/PGSERVICE even
    # when psycopg2 receives an explicit socket DSN. Leave the caller untouched.
    args = [sys.executable, str(Path(__file__).resolve()),
            "--schema-file", str(schema_file.resolve()),
            "--ledger-file", str(ledger_file.resolve()), "--sql-dir", str(sql_dir.resolve())]
    if binaries:
        args += ["--postgres-bin", str(binaries.resolve())]
    # Child commands have timeouts and the worker owns cluster cleanup. Do not
    # kill the worker on an outer timeout before its finally block can run.
    return json.loads(run(args, env=local_environment(), timeout=None))


def _rehearse(schema_file: Path, ledger_file: Path, *, sql_dir: Path,
              binaries: Path | None) -> dict:
    expected = expected_migrations(sql_dir)
    schema_text = schema_file.read_text(encoding="utf-8")
    export = json.loads(ledger_file.read_text(encoding="utf-8"))
    rows = export["rows"]
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Ledger rows must be nonempty named-column objects")
    for row in rows:
        if (not {"filename", "checksum", "baseline"} <= row.keys()
            or not row.keys() <= set(LEDGER_COLUMNS)
            or not re.fullmatch(r"\d{3}_.+\.sql", row["filename"])
            or not re.fullmatch(r"[0-9a-f]{64}", row["checksum"])
            or not isinstance(row["baseline"], bool)):
            raise ValueError("Invalid ledger row")
    names = [row["filename"] for row in rows]
    if len(names) != len(set(names)) or any(int(name[:3]) >= STAGE1_START for name in names):
        raise ValueError("Expected a unique pre-Stage-1 migration ledger")
    binaries = postgres_bin(binaries)
    with cluster(binaries) as (admin_dsn, env):
        dsn, baseline = restore(admin_dsn, "stage1_timed", schema_text, rows, binaries, env)
        first_output = apply_stack(dsn, sql_dir, env)
        if [line.removeprefix("applied ") for line in first_output.splitlines()
            if line.startswith("applied ")] != expected:
            raise AssertionError(f"Expected exactly the discovered canonical migrations, in order: {expected}")
        if any(line.startswith("baselined ") for line in first_output.splitlines()):
            raise AssertionError("The production baseline must not acquire newly baselined history")
        with closing(psycopg2.connect(dsn)) as connection:
            after = ledger_rows(connection)
            if [row for row in after if row["filename"] in names] != baseline:
                raise AssertionError("A historical ledger row changed")
            added = [row for row in after if row["filename"] not in names]
            if [row["filename"] for row in added] != expected or any(row["baseline"] for row in added):
                raise AssertionError("Unexpected migration ledger additions")
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version")
                version = cursor.fetchone()[0]
                cursor.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
                extensions = dict(cursor.fetchall())
        second_output = apply_stack(dsn, sql_dir, env)
        if "SQL migrations up to date" not in second_output or any(
            line.startswith(("applied ", "baselined ")) for line in second_output.splitlines()
        ):
            raise AssertionError("Migration re-run was not a clean no-op")
        with closing(psycopg2.connect(dsn)) as connection:
            if ledger_rows(connection) != after:
                raise AssertionError("The migration re-run changed the ledger")
        invariants = run([sys.executable, "scripts/check_schema_invariants.py"],
                         env={**env, "DATABASE_URL": dsn}).strip()

        lock_dsn, _ = restore(admin_dsn, "stage1_locks", schema_text, rows, binaries, env)
        with closing(psycopg2.connect(lock_dsn)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(LOCK_OBSERVER)
            connection.commit()
        apply_stack(lock_dsn, sql_dir, env)
        with closing(psycopg2.connect(lock_dsn)) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT migration,command,relation,mode,granted FROM rehearsal.locks ORDER BY 1,2,3,4")
            locks = [dict(zip(("migration", "command", "relation", "mode", "granted"), row))
                     for row in cursor.fetchall()]
        for number, mode in ((172, "AccessExclusiveLock"), (174, "ShareLock")):
            if not any(row["migration"] == number and row["relation"] == "balance_operations"
                       and row["mode"] == mode and row["granted"] for row in locks):
                raise AssertionError(f"Missing expected {number} table lock: {mode}")

    return {
        "evidence_class": "local schema-only restore; no production access or data",
        "postgres_version": version,
        "schema_sha256": hashlib.sha256(schema_file.read_bytes()).hexdigest(),
        "ledger_sha256": hashlib.sha256(ledger_file.read_bytes()).hexdigest(),
        "baseline_rows": len(rows), "baselined_rows": sum(row["baseline"] for row in rows),
        "supplied_ledger_fields": sorted(set.intersection(*(set(row) for row in rows))),
        "unprovided_ledger_fields": sorted(set(LEDGER_COLUMNS) - set.union(*(set(row) for row in rows))),
        "platform_stubs": ["anon NOLOGIN", "authenticated NOLOGIN", "service_role NOLOGIN BYPASSRLS"],
        "extensions": extensions, "auth_function_stubs": [],
        "migration_execution_ms": {row["filename"]: row["execution_ms"] for row in added},
        "rerun": "clean no-op; complete ledger unchanged", "invariants": invariants,
        "relation_locks_separate_run": locks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-file", type=Path, required=True)
    parser.add_argument("--ledger-file", type=Path, required=True)
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--sql-dir", type=Path, default=BACKEND / "sql")
    args = parser.parse_args()
    env = local_environment()
    os.environ.clear()
    os.environ.update(env)
    print(json.dumps(_rehearse(args.schema_file, args.ledger_file,
                               sql_dir=args.sql_dir.resolve(), binaries=args.postgres_bin), indent=2))


if __name__ == "__main__":
    main()
