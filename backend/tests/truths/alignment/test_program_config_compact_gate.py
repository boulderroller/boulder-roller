"""ProgramConfig compact-layout regression gate.

The retired Merkle allocation flow used to leave two fields on ProgramConfig:
``allocation_submitter`` and ``total_vault_cal_allocated``. Those fields are
not protocol truth anymore. Legacy migration code may name them, but public
runtime surfaces must not.
"""

from __future__ import annotations

import json
import re

from ._alignment_helpers import anchor_program_source, repo_root


PUBLIC_RUNTIME_SURFACES = (
    "protocol/anchor/idl/boulder_rollers.json",
    "backend/idl/boulder_rollers.json",
    "web/portal/public/idl/boulder_rollers.json",
    "protocol/anchor/clients/typescript/boulder_rollers.ts",
    "indexer/src/writers/legend.ts",
    "backend/app/solana_direct.py",
)

RETIRED_PROGRAM_CONFIG_FIELDS = (
    "allocationSubmitter",
    "totalVaultCalAllocated",
    "allocation_submitter",
    "total_vault_cal_allocated",
)

PROTOCOL_PARAMETER_FIELDS = (
    ("vaultCreationDung", "vault_creation_dung"),
    ("vaultCreationCal", "vault_creation_cal"),
    ("harvestFeeBps", "harvest_fee_bps"),
    ("minterRightsEpochs", "minter_rights_epochs"),
    ("localLegendTermEpochs", "local_legend_term_epochs"),
    ("epochsPerHalving", "epochs_per_halving"),
)

SETTLEMENT_CLOCK_FIELDS = (
    ("settlementClockV2StartsAt", "settlement_clock_v2_starts_at"),
    ("settlementClockVersion", "settlement_clock_version"),
)


def test_program_config_public_surfaces_are_compact() -> None:
    """PROTOCOL_TRUTHS §10.1 — ProgramConfig exposes live authority only.

    Migration helpers may still recognize old account layouts. Generated IDLs,
    client types, indexer writes, and backend decoders must not expose the
    dead allocation-submit authority or aggregate allocation counter.
    """
    root = repo_root()
    leaks: list[str] = []

    for relative_path in PUBLIC_RUNTIME_SURFACES:
        text = (root / relative_path).read_text(encoding="utf-8")
        for retired_field in RETIRED_PROGRAM_CONFIG_FIELDS:
            if retired_field in text:
                leaks.append(f"{relative_path}: {retired_field}")

    assert not leaks, (
        "Retired ProgramConfig allocation fields leaked into public runtime "
        "surfaces:\n  " + "\n  ".join(leaks)
    )


def test_protocol_parameters_are_config_driven_across_runtime_surfaces() -> None:
    """Protocol economics tune through ProgramConfig, not source-only constants."""
    root = repo_root()
    surface_text = {
        relative_path: (root / relative_path).read_text(encoding="utf-8")
        for relative_path in PUBLIC_RUNTIME_SURFACES
    }
    route_text = (root / "backend/app/routes/vaults.py").read_text(encoding="utf-8")
    lib_text = anchor_program_source()

    missing: list[str] = []
    for camel_case, snake_case in PROTOCOL_PARAMETER_FIELDS:
        for relative_path, text in surface_text.items():
            expected = snake_case if relative_path.endswith(".py") else camel_case
            if expected not in text:
                missing.append(f"{relative_path}: {expected}")

    assert not missing, (
        "Governance-configurable ProgramConfig fields missing from runtime "
        "surfaces:\n  " + "\n  ".join(missing)
    )
    assert "update_protocol_parameters" in lib_text
    assert "ctx.accounts.program_config.harvest_fee_bps" in lib_text
    assert "ctx.accounts.program_config.epochs_per_halving" in lib_text
    assert "get_program_config_account(" in route_text


def test_program_config_version_gate_is_exposed_for_runtime_decoders() -> None:
    """Runtime readers use the generated current ProgramConfig expectation."""
    root = repo_root()
    manifest = json.loads(
        (root / "protocol/program-version.json").read_text(encoding="utf-8")
    )
    lib_text = anchor_program_source()

    assert manifest["current_version"] == 0x4E
    assert manifest["family_bootstrap"] == {
        "mode": "fresh_program",
        "predecessor_family": "V4-A",
        "predecessor_version": 0x44,
        "version": 0x4B,
    }
    assert manifest["previous_version"] == 0x4D
    assert "config.program_version = CURRENT_PROGRAM_VERSION" in lib_text
    assert "advance_program_version" in lib_text

    required_surfaces = {
        "protocol/anchor/idl/boulder_rollers.json": "programVersion",
        "backend/idl/boulder_rollers.json": "programVersion",
        "web/portal/public/idl/boulder_rollers.json": "programVersion",
        "protocol/anchor/clients/typescript/boulder_rollers.ts": "programVersion",
        "backend/app/solana_direct.py": "program_version",
        "indexer/src/writers/legend.ts": "program_version",
        "backend/app/generated_program_version.py": "CURRENT_PROGRAM_VERSION = 0x4E",
        "indexer/src/generated-program-version.ts": "CURRENT_PROGRAM_VERSION = 0x4e",
        "mobile/src/generated/boulderRollersProgramVersion.ts": "CURRENT_PROGRAM_VERSION = 0x4e",
        "mobile/src/lib/programVersion.ts": "verifyEnabled: false",
    }
    missing = [
        f"{relative_path}: {needle}"
        for relative_path, needle in required_surfaces.items()
        if needle not in (root / relative_path).read_text(encoding="utf-8")
    ]

    assert not missing, (
        "ProgramConfig program_version gate missing from runtime surfaces:\n  "
        + "\n  ".join(missing)
    )


def test_fee_projection_is_bound_to_the_anchor_constants() -> None:
    root = repo_root()
    anchor_source = anchor_program_source()
    backend_source = (root / "backend/app/solana_direct.py").read_text(encoding="utf-8")

    for constant in ("HARVEST_FEE_BPS", "EXIT_FEE_BPS"):
        anchor_match = re.search(
            rf"pub const {constant}: u64 = (\d+);",
            anchor_source,
        )
        backend_match = re.search(
            rf"^{constant} = (\d+)$",
            backend_source,
            re.MULTILINE,
        )
        assert anchor_match is not None
        assert backend_match is not None
        assert backend_match.group(1) == anchor_match.group(1)
    assert '"exit_fee_bps": EXIT_FEE_BPS' in backend_source


def test_settlement_clock_fields_are_independent_runtime_contract_fields() -> None:
    root = repo_root()
    missing: list[str] = []
    for relative_path in PUBLIC_RUNTIME_SURFACES:
        text = (root / relative_path).read_text(encoding="utf-8")
        for camel_case, snake_case in SETTLEMENT_CLOCK_FIELDS:
            expected = snake_case if relative_path.endswith(".py") else camel_case
            if expected not in text:
                missing.append(f"{relative_path}: {expected}")

    assert not missing, (
        "ProgramConfig settlement clock fields missing from runtime surfaces:\n  "
        + "\n  ".join(missing)
    )
