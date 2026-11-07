#!/usr/bin/env python3
"""Apply backend/sql migrations through DATABASE_URL.

The historical backend/sql directory predates a durable migration ledger, so
the runner supports baselining old numbered files while applying future files
exactly once. It is intentionally small and deploy-oriented: filenames are the
migration identities, checksums catch edited migrations, and every migration
runs in a transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2.extensions import connection as PgConnection, parse_dsn


MIGRATION_RE = re.compile(r"^(?P<number>\d{3})_.+\.sql$")
LEDGER_TABLE = "public.br_sql_migrations"
LOCK_KEY = "boulderroller:backend_sql_migrations"
MANUAL_APPROVAL_ENV_BY_FILENAME = {
    "153_public_data_api_rls_lockdown.sql": (
        "APPROVED_PUBLIC_DATA_API_RLS_SHA256"
    ),
}
MANUAL_APPROVAL_PROJECT_ENV_BY_FILENAME = {
    "153_public_data_api_rls_lockdown.sql": (
        "APPROVED_PUBLIC_DATA_API_RLS_PROJECT_REF"
    ),
}
MANUAL_APPROVAL_CATALOG_ENV_BY_FILENAME = {
    "153_public_data_api_rls_lockdown.sql": (
        "APPROVED_PUBLIC_DATA_API_RLS_CATALOG_SHA256"
    ),
}
EXPECTED_SUPABASE_PROJECT_REF_BY_FILENAME = {
    "153_public_data_api_rls_lockdown.sql": "qzkqjevawthyboymqrle",
}
CATALOG_MANIFEST_SUFFIX_BY_FILENAME = {
    "153_public_data_api_rls_lockdown.sql": (
        "153_public_data_api_rls_lockdown.catalog.json"
    ),
}
PUBLIC_DATA_API_RLS_CATALOG_FINGERPRINT_SQL = r"""
WITH manifest AS (
  SELECT %s::jsonb AS doc
),
predecessor_relations AS (
  SELECT
    item->>'kind' AS kind,
    item->>'name' AS name
  FROM manifest
  CROSS JOIN jsonb_array_elements(
    doc->'predecessor_152'->'relations'
  ) AS item
),
predecessor_routines AS (
  SELECT
    item->>'kind' AS kind,
    item->>'name' AS name,
    item->>'argument_types' AS argument_types
  FROM manifest
  CROSS JOIN jsonb_array_elements(
    doc->'predecessor_152'->'routines'
  ) AS item
),
excluded_columns AS (
  SELECT
    item->>'relation' AS relation_name,
    item->>'name' AS column_name
  FROM manifest
  CROSS JOIN jsonb_array_elements(
    doc->'predecessor_152'->'excluded_new_columns'
  ) AS item
),
normalized_relations AS (
  SELECT value #>> '{}' AS relation_name
  FROM manifest
  CROSS JOIN jsonb_array_elements(
    doc->'predecessor_152'->'normalized_relation_security'
  )
),
normalized_routines AS (
  SELECT
    item->>'kind' AS kind,
    item->>'name' AS name,
    item->>'argument_types' AS argument_types
  FROM manifest
  CROSS JOIN jsonb_array_elements(
    doc->'predecessor_152'->'normalized_routine_security'
  ) AS item
),
inventory(item) AS (
  SELECT concat_ws(
    '|',
    'schema',
    n.nspname,
    pg_get_userbyid(n.nspowner),
    coalesce(n.nspacl::text, '<null>')
  )
  FROM pg_namespace AS n
  WHERE n.nspname = 'public'

  UNION ALL

  SELECT concat_ws(
    '|',
    'relation',
    c.relkind::text,
    n.nspname,
      c.relname,
      pg_get_userbyid(c.relowner),
      CASE WHEN normalized.relation_name IS NULL
        THEN c.relrowsecurity::text ELSE '<predecessor-normalized>' END,
      CASE WHEN normalized.relation_name IS NULL
        THEN c.relforcerowsecurity::text ELSE '<predecessor-normalized>' END,
      coalesce(c.reloptions::text, '<null>'),
      CASE WHEN normalized.relation_name IS NULL
        THEN coalesce(c.relacl::text, '<null>')
        ELSE '<predecessor-normalized>' END,
      CASE WHEN c.relkind = 'v' THEN pg_get_viewdef(c.oid, true) ELSE '-' END
    )
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    LEFT JOIN normalized_relations AS normalized
      ON normalized.relation_name = c.relname
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
      AND NOT EXISTS (
        SELECT 1
        FROM predecessor_relations AS predecessor
        WHERE predecessor.kind = c.relkind::text
          AND predecessor.name = c.relname
      )

    UNION ALL

    SELECT concat_ws(
      '|',
      'column',
      c.relkind::text,
      n.nspname,
      c.relname,
      a.attnum::text,
      a.attname,
      format_type(a.atttypid, a.atttypmod),
      a.attidentity::text,
      a.attgenerated::text,
      coalesce(a.attacl::text, '<null>')
    )
    FROM pg_attribute AS a
    JOIN pg_class AS c ON c.oid = a.attrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND NOT EXISTS (
        SELECT 1
        FROM predecessor_relations AS predecessor
        WHERE predecessor.kind = c.relkind::text
          AND predecessor.name = c.relname
      )
      AND NOT EXISTS (
        SELECT 1
        FROM excluded_columns AS excluded
        WHERE excluded.relation_name = c.relname
          AND excluded.column_name = a.attname
      )

    UNION ALL

    SELECT concat_ws(
      '|',
      'policy',
      n.nspname,
      c.relname,
      policy.polname,
      policy.polcmd::text,
      policy.polpermissive::text,
      coalesce((
        SELECT string_agg(
          CASE WHEN policy_role.role_oid = 0
            THEN 'PUBLIC'
            ELSE pg_get_userbyid(policy_role.role_oid)
          END,
          ',' ORDER BY policy_role.role_oid
        )
        FROM unnest(policy.polroles) AS policy_role(role_oid)
      ), '<none>'),
      coalesce(pg_get_expr(policy.polqual, policy.polrelid), '<null>'),
      coalesce(pg_get_expr(policy.polwithcheck, policy.polrelid), '<null>')
    )
    FROM pg_policy AS policy
    JOIN pg_class AS c ON c.oid = policy.polrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND NOT EXISTS (
        SELECT 1
        FROM predecessor_relations AS predecessor
        WHERE predecessor.kind = c.relkind::text
          AND predecessor.name = c.relname
      )

  UNION ALL

  SELECT concat_ws(
    '|',
    'routine',
    p.prokind::text,
    n.nspname,
      p.proname,
      oidvectortypes(p.proargtypes),
      pg_get_userbyid(p.proowner),
    p.prosecdef::text,
    coalesce(p.proconfig::text, '<null>'),
    CASE WHEN normalized.kind IS NULL
      THEN coalesce(p.proacl::text, '<null>')
      ELSE '<predecessor-normalized>' END
  )
  FROM pg_proc AS p
  JOIN pg_namespace AS n ON n.oid = p.pronamespace
  LEFT JOIN normalized_routines AS normalized
    ON normalized.kind = p.prokind::text
   AND normalized.name = p.proname
   AND normalized.argument_types = oidvectortypes(p.proargtypes)
    WHERE n.nspname = 'public'
      AND p.prokind IN ('f', 'p')
      AND NOT EXISTS (
        SELECT 1
        FROM predecessor_routines AS predecessor
        WHERE predecessor.kind = p.prokind::text
          AND predecessor.name = p.proname
          AND predecessor.argument_types = oidvectortypes(p.proargtypes)
      )

  UNION ALL

  SELECT concat_ws(
    '|',
    'default_acl',
    pg_get_userbyid(d.defaclrole),
    coalesce(n.nspname, '*'),
    d.defaclobjtype::text,
    coalesce(d.defaclacl::text, '<null>')
  )
  FROM pg_default_acl AS d
  LEFT JOIN pg_namespace AS n ON n.oid = d.defaclnamespace
  WHERE d.defaclrole = (
    SELECT oid FROM pg_roles WHERE rolname = current_user
  )
    AND (d.defaclnamespace = 0 OR n.nspname = 'public')

  UNION ALL

  SELECT concat_ws(
    '|',
    'role',
    r.rolname,
      r.rolsuper::text,
      r.rolinherit::text,
      r.rolcreaterole::text,
      r.rolcreatedb::text,
      r.rolcanlogin::text,
      r.rolreplication::text,
      r.rolbypassrls::text,
      r.rolconnlimit::text,
      coalesce(r.rolvaliduntil::text, '<null>'),
    coalesce((
      SELECT string_agg(parent.rolname, ',' ORDER BY parent.rolname)
      FROM pg_auth_members AS membership
      JOIN pg_roles AS parent ON parent.oid = membership.roleid
      WHERE membership.member = r.oid
    ), '<none>')
  )
    FROM pg_roles AS r
    WHERE r.rolname IN ('anon', 'authenticated', 'service_role', current_user)

    UNION ALL

    SELECT DISTINCT concat_ws(
      '|',
      'view_dependency',
      view_namespace.nspname,
      view_class.relname,
      dependency_namespace.nspname,
      dependency_class.relname,
      dependency_class.relkind::text,
      pg_get_userbyid(dependency_class.relowner)
    )
    FROM pg_class AS view_class
    JOIN pg_namespace AS view_namespace
      ON view_namespace.oid = view_class.relnamespace
    JOIN pg_rewrite AS rewrite ON rewrite.ev_class = view_class.oid
    JOIN pg_depend AS dependency
      ON dependency.classid = 'pg_rewrite'::regclass
     AND dependency.objid = rewrite.oid
     AND dependency.refclassid = 'pg_class'::regclass
    JOIN pg_class AS dependency_class
      ON dependency_class.oid = dependency.refobjid
    JOIN pg_namespace AS dependency_namespace
      ON dependency_namespace.oid = dependency_class.relnamespace
    WHERE view_namespace.nspname = 'public'
      AND view_class.relkind = 'v'
      AND dependency_class.oid <> view_class.oid
)
SELECT encode(
  pg_catalog.sha256(
    convert_to(
      coalesce(string_agg(item, E'\n' ORDER BY item), ''),
      'UTF8'
    )
  ),
  'hex'
) AS catalog_fingerprint
FROM inventory
"""


@dataclass(frozen=True)
class Migration:
    path: Path
    filename: str
    number: int
    checksum: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sql-dir",
        default="sql",
        help="Directory containing numbered backend SQL migrations.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--baseline-through",
        type=int,
        default=None,
        help=(
            "Mark unapplied migrations with numeric prefix <= this value as "
            "already applied. Use for adopting the ledger after historical "
            "manual SQL application."
        ),
    )
    parser.add_argument(
        "--reload-postgrest",
        action="store_true",
        help="Send NOTIFY pgrst, 'reload schema' after successful changes.",
    )
    return parser.parse_args()


def discover_migrations(sql_dir: Path) -> list[Migration]:
    if not sql_dir.is_dir():
        raise SystemExit(f"SQL directory not found: {sql_dir}")

    migrations: list[Migration] = []
    for path in sorted(sql_dir.iterdir(), key=lambda p: p.name):
        match = MIGRATION_RE.match(path.name)
        if not match or not path.is_file():
            continue
        content = path.read_bytes()
        manifest_name = CATALOG_MANIFEST_SUFFIX_BY_FILENAME.get(path.name)
        if manifest_name is not None:
            manifest_path = path.with_name(manifest_name)
            if not manifest_path.is_file():
                raise SystemExit(
                    f"Approval-locked migration is missing catalog manifest: "
                    f"{manifest_path}"
                )
            content += b"\0" + manifest_path.read_bytes()
        migrations.append(
            Migration(
                path=path,
                filename=path.name,
                number=int(match.group("number")),
                checksum=hashlib.sha256(content).hexdigest(),
            )
        )
    return migrations


def ensure_ledger(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
                filename TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                execution_ms INTEGER,
                applied_by TEXT NOT NULL DEFAULT current_user,
                host TEXT,
                baseline BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
    conn.commit()


def applied_checksums(conn: PgConnection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT filename, checksum FROM {LEDGER_TABLE}")
        return {filename: checksum for filename, checksum in cur.fetchall()}


def acquire_lock(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (LOCK_KEY,))
    conn.commit()


def release_lock(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
    conn.commit()


def assert_checksums_match(applied: dict[str, str], migrations: Iterable[Migration]) -> None:
    mismatches = [
        migration.filename
        for migration in migrations
        if migration.filename in applied and applied[migration.filename] != migration.checksum
    ]
    if mismatches:
        joined = ", ".join(mismatches)
        raise SystemExit(f"Applied migration checksum mismatch: {joined}")


def _supabase_project_ref(database_url: str | None) -> str:
    if not database_url:
        raise SystemExit("Approval-locked migration is missing its database URL")

    try:
        parameters = parse_dsn(database_url)
    except psycopg2.ProgrammingError as exc:
        raise SystemExit(
            "Approval-locked migration has an invalid database URL"
        ) from exc

    host = parameters.get("host", "").lower()
    user = parameters.get("user", "").lower()
    candidates: set[str] = set()

    host_match = re.fullmatch(r"db\.([a-z0-9]+)\.supabase\.co", host)
    if host_match:
        candidates.add(host_match.group(1))

    user_match = re.fullmatch(r"postgres\.([a-z0-9]+)", user)
    if user_match:
        candidates.add(user_match.group(1))

    if len(candidates) != 1:
        raise SystemExit(
            "Approval-locked migration could not resolve exactly one Supabase "
            "project ref from its database host/user"
        )
    return next(iter(candidates))


def assert_manual_approval(
    migration: Migration,
    *,
    database_url: str | None,
    catalog_fingerprint: str | None,
    expected_catalog_fingerprint: str | None,
) -> None:
    """Fail closed for migrations whose exact bytes and target need approval."""
    approval_env = MANUAL_APPROVAL_ENV_BY_FILENAME.get(migration.filename)
    if approval_env is None:
        return

    approved_checksum = os.getenv(approval_env, "").strip().lower()
    if approved_checksum != migration.checksum:
        raise SystemExit(
            f"{migration.filename} requires explicit live approval for its exact "
            f"reviewed bytes; set {approval_env}={migration.checksum}"
        )

    project_approval_env = MANUAL_APPROVAL_PROJECT_ENV_BY_FILENAME[migration.filename]
    project_ref = _supabase_project_ref(database_url)
    expected_project_ref = EXPECTED_SUPABASE_PROJECT_REF_BY_FILENAME[
        migration.filename
    ]
    if project_ref != expected_project_ref:
        raise SystemExit(
            f"{migration.filename} was reviewed only for Supabase project "
            f"{expected_project_ref}; database URL resolves to {project_ref}"
        )
    approved_project_ref = os.getenv(project_approval_env, "").strip().lower()
    if approved_project_ref != expected_project_ref:
        raise SystemExit(
            f"{migration.filename} requires explicit target approval; set "
            f"{project_approval_env}={expected_project_ref}"
        )

    if catalog_fingerprint is None or expected_catalog_fingerprint is None:
        raise SystemExit(
            f"{migration.filename} is missing its audited catalog fingerprint"
        )
    if catalog_fingerprint != expected_catalog_fingerprint:
        raise SystemExit(
            f"{migration.filename} live catalog does not match the committed catalog "
            f"expectation {expected_catalog_fingerprint}; got {catalog_fingerprint}"
        )
    catalog_approval_env = MANUAL_APPROVAL_CATALOG_ENV_BY_FILENAME[
        migration.filename
    ]
    approved_catalog_fingerprint = os.getenv(
        catalog_approval_env, ""
    ).strip().lower()
    if approved_catalog_fingerprint != expected_catalog_fingerprint:
        raise SystemExit(
            f"{migration.filename} requires the committed catalog approval; set "
            f"{catalog_approval_env}={expected_catalog_fingerprint}"
        )


def catalog_manifest_path(migration: Migration) -> Path:
    manifest_name = CATALOG_MANIFEST_SUFFIX_BY_FILENAME.get(migration.filename)
    if manifest_name is None:
        raise RuntimeError(f"{migration.filename} has no catalog manifest")
    return migration.path.with_name(manifest_name)


def load_catalog_manifest(migration: Migration) -> dict[str, object]:
    path = catalog_manifest_path(migration)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not load reviewed catalog manifest {path}") from exc

    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise SystemExit(f"Unsupported reviewed catalog manifest {path}")
    expected_project = EXPECTED_SUPABASE_PROJECT_REF_BY_FILENAME[migration.filename]
    if manifest.get("project_ref") != expected_project:
        raise SystemExit(
            f"Catalog manifest project does not match reviewed project {expected_project}"
        )
    return manifest


def expected_catalog_fingerprint(migration: Migration) -> str:
    manifest = load_catalog_manifest(migration)
    fingerprint = str(manifest.get("expected_catalog_fingerprint", "")).lower()
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise SystemExit(
            f"Catalog manifest for {migration.filename} has no committed fingerprint"
        )
    return fingerprint


def catalog_scope_fingerprint(
    conn: PgConnection,
    manifest: dict[str, object],
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            PUBLIC_DATA_API_RLS_CATALOG_FINGERPRINT_SQL,
            (json.dumps(manifest, separators=(",", ":"), sort_keys=True),),
        )
        row = cur.fetchone()

    fingerprint = "" if row is None else str(row[0]).lower()
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise RuntimeError("Could not compute the public Data API catalog fingerprint")
    return fingerprint


def baseline_migrations(
    conn: PgConnection,
    migrations: Iterable[Migration],
    applied: dict[str, str],
    baseline_through: int | None,
) -> set[str]:
    if baseline_through is None:
        return set(applied)

    migration_list = list(migrations)
    locked_baseline = next(
        (
            migration
            for migration in migration_list
            if migration.number <= baseline_through
            and migration.filename not in applied
            and migration.filename in MANUAL_APPROVAL_ENV_BY_FILENAME
        ),
        None,
    )
    if locked_baseline is not None:
        raise SystemExit(
            "Approval-locked migration "
            f"{locked_baseline.filename} cannot be baselined"
        )

    host = socket.gethostname()
    baselined = set(applied)
    with conn.cursor() as cur:
        for migration in migration_list:
            if migration.number > baseline_through or migration.filename in baselined:
                continue
            cur.execute(
                f"""
                INSERT INTO {LEDGER_TABLE}
                    (filename, checksum, execution_ms, host, baseline)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (filename) DO NOTHING
                """,
                (migration.filename, migration.checksum, 0, host),
            )
            baselined.add(migration.filename)
            print(f"baselined {migration.filename}")
    conn.commit()
    return baselined


def apply_migration(
    conn: PgConnection,
    migration: Migration,
    *,
    database_url: str | None = None,
) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    start = time.monotonic()
    host = socket.gethostname()

    try:
        catalog_manifest = None
        catalog_fingerprint = None
        expected_fingerprint = None
        if migration.filename in MANUAL_APPROVAL_CATALOG_ENV_BY_FILENAME:
            catalog_manifest = load_catalog_manifest(migration)
            expected_fingerprint = expected_catalog_fingerprint(migration)
            # This SELECT opens the same transaction that contains the guard,
            # migration SQL, assertions, and ledger insert.
            catalog_fingerprint = catalog_scope_fingerprint(conn, catalog_manifest)
        assert_manual_approval(
            migration,
            database_url=database_url,
            catalog_fingerprint=catalog_fingerprint,
            expected_catalog_fingerprint=expected_fingerprint,
        )

        with conn.cursor() as cur:
            if catalog_fingerprint is not None:
                cur.execute(
                    """
                    SELECT
                      set_config(
                        'boulderroller.migration_runner',
                        'apply_sql_migrations_v1',
                        true
                      ),
                      set_config(
                        'boulderroller.approved_public_data_api_rls_catalog_sha256',
                        %s,
                        true
                      ),
                      set_config(
                        'boulderroller.public_data_api_rls_catalog_manifest',
                        %s,
                        true
                      )
                    """,
                    (
                        catalog_fingerprint,
                        json.dumps(
                            catalog_manifest,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    ),
                )
            cur.execute(sql)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            cur.execute(
                f"""
                INSERT INTO {LEDGER_TABLE}
                    (filename, checksum, execution_ms, host, baseline)
                VALUES (%s, %s, %s, %s, FALSE)
                """,
                (migration.filename, migration.checksum, elapsed_ms, host),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    print(f"applied {migration.filename}")


def reload_postgrest(conn: PgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute("NOTIFY pgrst, 'reload schema'")
    conn.commit()
    print("requested PostgREST schema reload")


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    migrations = discover_migrations(Path(args.sql_dir))
    if not migrations:
        print(f"no numbered SQL migrations found in {args.sql_dir}")
        return 0

    conn = psycopg2.connect(args.database_url)
    try:
        ensure_ledger(conn)
        acquire_lock(conn)
        try:
            applied = applied_checksums(conn)
            assert_checksums_match(applied, migrations)
            applied_names = baseline_migrations(
                conn,
                migrations,
                applied,
                args.baseline_through,
            )

            applied_any = False
            for migration in migrations:
                if migration.filename in applied_names:
                    continue
                apply_migration(conn, migration, database_url=args.database_url)
                applied_names.add(migration.filename)
                applied_any = True

            if (applied_any or args.baseline_through is not None) and args.reload_postgrest:
                reload_postgrest(conn)
            if not applied_any:
                print("SQL migrations up to date")
        finally:
            release_lock(conn)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
