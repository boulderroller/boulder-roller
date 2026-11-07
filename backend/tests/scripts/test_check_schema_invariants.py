from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_invariants.py"
spec = importlib.util.spec_from_file_location("check_schema_invariants", MODULE_PATH)
assert spec is not None
schema_check = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = schema_check
spec.loader.exec_module(schema_check)


def test_critical_requirements_cover_provider_provenance_objects() -> None:
    identifiers = {requirement.identifier for requirement in schema_check.CRITICAL_REQUIREMENTS}

    assert "public.rides.import_source" in identifiers
    assert "public.rides.import_source_id" in identifiers
    assert "public.rides.import_diagnostics" in identifiers
    assert "public.br_normalize_provider_import_source(text)" in identifiers
    assert "public.enforce_ride_provider_activity_identity()" in identifiers
    assert "public.idx_rides_provider_activity_identity_lookup" in identifiers
    assert "public.rides.trg_enforce_ride_provider_activity_identity" in identifiers


def test_critical_requirements_cover_canon_registry_objects() -> None:
    identifiers = {requirement.identifier for requirement in schema_check.CRITICAL_REQUIREMENTS}

    assert "public.canon_climbs.canon_id" in identifiers
    assert "public.canon_climbs.version" in identifiers
    assert "public.canon_climbs.centerline_geom" in identifiers
    assert "public.canon_climbs.corridor_geom" in identifiers
    assert "public.canon_climbs.gate_start_line" in identifiers
    assert "public.canon_climbs.gate_end_line" in identifiers
    assert "public.canon_climbs.canonical_profile" in identifiers
    assert "public.canon_climbs.odbl_source" in identifiers
    assert "public.canon_corridor_cells.tile_id" in identifiers
    assert "public.idx_canon_climbs_canon_version" in identifiers
    assert "public.idx_canon_climbs_corridor_geom" in identifiers
    assert "public.idx_canon_corridor_cells_resolution_tile" in identifiers


def test_critical_requirements_cover_canonical_dung_supply_observation() -> None:
    identifiers = {requirement.identifier for requirement in schema_check.CRITICAL_REQUIREMENTS}

    assert "public.indexed_supply.spl_mint_supply" in identifiers
    assert "public.indexed_supply.spl_mint_supply_slot" in identifiers
    assert "public.indexed_supply.spl_mint_supply_indexed_at" in identifiers
    assert "public.indexed_supply.community_reserved" in identifiers
    assert "public.indexed_supply.reservation_policy_version" in identifiers


def test_critical_requirements_cover_local_legend_bootstrap_projection() -> None:
    identifiers = {requirement.identifier for requirement in schema_check.CRITICAL_REQUIREMENTS}

    assert "public.indexed_legends.is_bootstrap" in identifiers


def test_critical_requirements_cover_exact_settlement_projection_identifiers() -> None:
    identifiers = {requirement.identifier for requirement in schema_check.CRITICAL_REQUIREMENTS}

    assert (
        "public.br_refresh_distribution_dependents(numeric,numeric)"
        in identifiers
    )


def test_evaluate_failures_ignores_unledgered_migration() -> None:
    requirement = schema_check.Requirement(
        migration="999_future.sql",
        kind="column",
        identifier="public.rides.future_column",
    )

    failures = schema_check.evaluate_failures(
        requirements=[requirement],
        ledger_entries={},
        existing_identifiers={requirement.identifier: False},
    )

    assert failures == []


def test_evaluate_failures_reports_missing_ledgered_requirement() -> None:
    requirement = schema_check.Requirement(
        migration="093_ride_import_diagnostics.sql",
        kind="column",
        identifier="public.rides.import_source",
    )
    ledger_entry = schema_check.LedgerEntry(
        filename="093_ride_import_diagnostics.sql",
        baseline=True,
    )

    failures = schema_check.evaluate_failures(
        requirements=[requirement],
        ledger_entries={ledger_entry.filename: ledger_entry},
        existing_identifiers={requirement.identifier: False},
    )

    assert len(failures) == 1
    assert failures[0].requirement == requirement
    assert failures[0].ledger_entry == ledger_entry


def test_evaluate_failures_accepts_present_ledgered_requirement() -> None:
    requirement = schema_check.Requirement(
        migration="109_provider_provenance_identity.sql",
        kind="function",
        identifier="public.enforce_ride_provider_activity_identity()",
    )
    ledger_entry = schema_check.LedgerEntry(
        filename="109_provider_provenance_identity.sql",
        baseline=False,
    )

    failures = schema_check.evaluate_failures(
        requirements=[requirement],
        ledger_entries={ledger_entry.filename: ledger_entry},
        existing_identifiers={requirement.identifier: True},
    )

    assert failures == []
