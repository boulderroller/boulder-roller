#!/usr/bin/env python3
"""Verify critical schema invariants after backend SQL migrations.

The migration ledger can be adopted with historical baselines, which means a
ledger row alone is not enough proof that a production database actually has
the schema objects later code expects. This deploy check fails when a critical
migration is recorded in the ledger but its required columns, functions,
triggers, or indexes are missing.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Iterable, Literal

import psycopg2
from psycopg2.extensions import connection as PgConnection


LEDGER_TABLE = "public.br_sql_migrations"

RequirementKind = Literal["column", "function", "index", "trigger"]


@dataclass(frozen=True)
class Requirement:
    migration: str
    kind: RequirementKind
    identifier: str
    table_schema: str | None = None
    table_name: str | None = None
    column_name: str | None = None
    trigger_name: str | None = None


@dataclass(frozen=True)
class LedgerEntry:
    filename: str
    baseline: bool


@dataclass(frozen=True)
class RequirementFailure:
    requirement: Requirement
    ledger_entry: LedgerEntry


CRITICAL_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        migration="169_stage1_program_version_window.sql",
        kind="column",
        identifier="public.program_version_observations.highest_version",
        table_schema="public",
        table_name="program_version_observations",
        column_name="highest_version",
    ),
    Requirement(
        migration="169_stage1_program_version_window.sql",
        kind="function",
        identifier="public.observe_program_version(text,text,smallint)",
    ),
    Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="column",
        identifier="public.rides.import_source",
        table_schema="public",
        table_name="rides",
        column_name="import_source",
    ),
    Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="column",
        identifier="public.rides.import_source_id",
        table_schema="public",
        table_name="rides",
        column_name="import_source_id",
    ),
    Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="column",
        identifier="public.rides.import_diagnostics",
        table_schema="public",
        table_name="rides",
        column_name="import_diagnostics",
    ),
    Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="index",
        identifier="public.idx_rides_import_source",
    ),
    Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="index",
        identifier="public.idx_rides_import_source_id",
    ),
    Requirement(
        migration="109_provider_provenance_identity.sql",
        kind="function",
        identifier="public.br_normalize_provider_import_source(text)",
    ),
    Requirement(
        migration="109_provider_provenance_identity.sql",
        kind="function",
        identifier="public.enforce_ride_provider_activity_identity()",
    ),
    Requirement(
        migration="109_provider_provenance_identity.sql",
        kind="index",
        identifier="public.idx_rides_provider_activity_identity_lookup",
    ),
    Requirement(
        migration="109_provider_provenance_identity.sql",
        kind="trigger",
        identifier="public.rides.trg_enforce_ride_provider_activity_identity",
        table_schema="public",
        table_name="rides",
        trigger_name="trg_enforce_ride_provider_activity_identity",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.canon_id",
        table_schema="public",
        table_name="canon_climbs",
        column_name="canon_id",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.version",
        table_schema="public",
        table_name="canon_climbs",
        column_name="version",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.centerline_geom",
        table_schema="public",
        table_name="canon_climbs",
        column_name="centerline_geom",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.corridor_geom",
        table_schema="public",
        table_name="canon_climbs",
        column_name="corridor_geom",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.gate_start_line",
        table_schema="public",
        table_name="canon_climbs",
        column_name="gate_start_line",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.gate_end_line",
        table_schema="public",
        table_name="canon_climbs",
        column_name="gate_end_line",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.canonical_profile",
        table_schema="public",
        table_name="canon_climbs",
        column_name="canonical_profile",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_climbs.odbl_source",
        table_schema="public",
        table_name="canon_climbs",
        column_name="odbl_source",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="column",
        identifier="public.canon_corridor_cells.tile_id",
        table_schema="public",
        table_name="canon_corridor_cells",
        column_name="tile_id",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="index",
        identifier="public.idx_canon_climbs_canon_version",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="index",
        identifier="public.idx_canon_climbs_corridor_geom",
    ),
    Requirement(
        migration="111_canon_climb_registry.sql",
        kind="index",
        identifier="public.idx_canon_corridor_cells_resolution_tile",
    ),
    Requirement(
        migration="132_dung_circulating_supply_authority.sql",
        kind="column",
        identifier="public.indexed_supply.spl_mint_supply",
        table_schema="public",
        table_name="indexed_supply",
        column_name="spl_mint_supply",
    ),
    Requirement(
        migration="132_dung_circulating_supply_authority.sql",
        kind="column",
        identifier="public.indexed_supply.spl_mint_supply_slot",
        table_schema="public",
        table_name="indexed_supply",
        column_name="spl_mint_supply_slot",
    ),
    Requirement(
        migration="132_dung_circulating_supply_authority.sql",
        kind="column",
        identifier="public.indexed_supply.spl_mint_supply_indexed_at",
        table_schema="public",
        table_name="indexed_supply",
        column_name="spl_mint_supply_indexed_at",
    ),
    Requirement(
        migration="133_dung_reservation_observability_backfill.sql",
        kind="column",
        identifier="public.indexed_supply.community_reserved",
        table_schema="public",
        table_name="indexed_supply",
        column_name="community_reserved",
    ),
    Requirement(
        migration="133_dung_reservation_observability_backfill.sql",
        kind="column",
        identifier="public.indexed_supply.reservation_policy_version",
        table_schema="public",
        table_name="indexed_supply",
        column_name="reservation_policy_version",
    ),
    Requirement(
        migration="134_indexed_legends_bootstrap_projection.sql",
        kind="column",
        identifier="public.indexed_legends.is_bootstrap",
        table_schema="public",
        table_name="indexed_legends",
        column_name="is_bootstrap",
    ),
    Requirement(
        migration="138_settlement_projection_numeric_identifiers.sql",
        kind="function",
        identifier="public.br_refresh_distribution_dependents(numeric,numeric)",
    ),
    Requirement(
        migration="148_ride_titles.sql",
        kind="column",
        identifier="public.rides.title",
        table_schema="public",
        table_name="rides",
        column_name="title",
    ),
    Requirement(
        migration="149_ride_elevation_correction.sql",
        kind="column",
        identifier="public.rides.elevation_correction_status",
        table_schema="public",
        table_name="rides",
        column_name="elevation_correction_status",
    ),
    Requirement(
        migration="149_ride_elevation_correction.sql",
        kind="column",
        identifier="public.rides.elevation_corrected_gain_m",
        table_schema="public",
        table_name="rides",
        column_name="elevation_corrected_gain_m",
    ),
    Requirement(
        migration="149_ride_elevation_correction.sql",
        kind="column",
        identifier="public.rides.elevation_correction_profile",
        table_schema="public",
        table_name="rides",
        column_name="elevation_correction_profile",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print failures.",
    )
    return parser.parse_args()


def migration_names(requirements: Iterable[Requirement]) -> list[str]:
    return sorted({requirement.migration for requirement in requirements})


def ledger_table_exists(conn: PgConnection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (LEDGER_TABLE,))
        return bool(cur.fetchone()[0])


def load_ledger_entries(conn: PgConnection, migrations: list[str]) -> dict[str, LedgerEntry]:
    if not migrations:
        return {}

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT filename, baseline
            FROM {LEDGER_TABLE}
            WHERE filename = ANY(%s)
            """,
            (migrations,),
        )
        return {
            filename: LedgerEntry(filename=filename, baseline=bool(baseline))
            for filename, baseline in cur.fetchall()
        }


def requirement_exists(conn: PgConnection, requirement: Requirement) -> bool:
    with conn.cursor() as cur:
        if requirement.kind == "column":
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = %s
                      AND column_name = %s
                )
                """,
                (
                    requirement.table_schema,
                    requirement.table_name,
                    requirement.column_name,
                ),
            )
        elif requirement.kind == "function":
            cur.execute("SELECT to_regprocedure(%s) IS NOT NULL", (requirement.identifier,))
        elif requirement.kind == "index":
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (requirement.identifier,))
        elif requirement.kind == "trigger":
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_trigger tg
                    JOIN pg_class rel ON rel.oid = tg.tgrelid
                    JOIN pg_namespace namespace ON namespace.oid = rel.relnamespace
                    WHERE namespace.nspname = %s
                      AND rel.relname = %s
                      AND tg.tgname = %s
                      AND NOT tg.tgisinternal
                )
                """,
                (
                    requirement.table_schema,
                    requirement.table_name,
                    requirement.trigger_name,
                ),
            )
        else:
            raise AssertionError(f"Unhandled requirement kind: {requirement.kind}")

        return bool(cur.fetchone()[0])


def evaluate_failures(
    requirements: Iterable[Requirement],
    ledger_entries: dict[str, LedgerEntry],
    existing_identifiers: dict[str, bool],
) -> list[RequirementFailure]:
    failures: list[RequirementFailure] = []
    for requirement in requirements:
        ledger_entry = ledger_entries.get(requirement.migration)
        if ledger_entry is None:
            continue
        if not existing_identifiers.get(requirement.identifier, False):
            failures.append(
                RequirementFailure(
                    requirement=requirement,
                    ledger_entry=ledger_entry,
                )
            )
    return failures


def check_schema_invariants(
    conn: PgConnection,
    requirements: tuple[Requirement, ...] = CRITICAL_REQUIREMENTS,
) -> tuple[dict[str, LedgerEntry], dict[str, bool], list[RequirementFailure]]:
    migrations = migration_names(requirements)
    if not ledger_table_exists(conn):
        return {}, {}, []

    ledger_entries = load_ledger_entries(conn, migrations)
    existing_identifiers = {
        requirement.identifier: requirement_exists(conn, requirement)
        for requirement in requirements
        if requirement.migration in ledger_entries
    }
    failures = evaluate_failures(requirements, ledger_entries, existing_identifiers)
    return ledger_entries, existing_identifiers, failures


def print_summary(
    ledger_entries: dict[str, LedgerEntry],
    existing_identifiers: dict[str, bool],
    failures: list[RequirementFailure],
    quiet: bool,
) -> None:
    if failures:
        print("Schema invariant check failed:", file=sys.stderr)
        for failure in failures:
            baseline_note = "baseline=true" if failure.ledger_entry.baseline else "baseline=false"
            print(
                f"- {failure.requirement.migration} is ledgered ({baseline_note}) "
                f"but {failure.requirement.kind} {failure.requirement.identifier} is missing",
                file=sys.stderr,
            )
        return

    if quiet:
        return

    ledgered_count = len(ledger_entries)
    checked_count = len(existing_identifiers)
    if ledgered_count == 0:
        print("Schema invariant check passed: no critical migrations are ledgered yet")
        return

    print(
        "Schema invariant check passed: "
        f"{ledgered_count} critical migrations ledgered, "
        f"{checked_count} schema requirements present"
    )


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    conn = psycopg2.connect(args.database_url)
    try:
        ledger_entries, existing_identifiers, failures = check_schema_invariants(conn)
    finally:
        conn.close()

    print_summary(ledger_entries, existing_identifiers, failures, args.quiet)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
