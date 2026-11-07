"""ProgramConfig patch-version and ABI compatibility gates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from ._alignment_helpers import repo_root


MANIFEST_PATH = Path("protocol/program-version.json")
CHECKER_PATH = Path("protocol/scripts/check_program_version.py")
PREFLIGHT_PATH = Path("protocol/anchor/scripts/preflight.sh")
SOLANA_CI_PATH = Path(".github/workflows/solana-ci.yml")


def _load_checker():
    root = repo_root()
    spec = importlib.util.spec_from_file_location(
        "check_program_version",
        root / CHECKER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v4b_keeps_its_bootstrap_and_advances_one_abi_patch() -> None:
    manifest = json.loads((repo_root() / MANIFEST_PATH).read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["family"] == "V4-B"
    assert manifest["previous_version"] == 0x4D
    assert manifest["current_version"] == 0x4E
    assert manifest["reserved_v4b_version"] == 0x4B
    assert manifest["family_bootstrap"] == {
        "mode": "fresh_program",
        "predecessor_family": "V4-A",
        "predecessor_version": 0x44,
        "version": 0x4B,
    }


def test_checked_idl_matches_the_current_version_snapshot() -> None:
    checker = _load_checker()

    checker.check_repository(repo_root())


def test_abi_drift_requires_exactly_one_version_step() -> None:
    checker = _load_checker()
    base_surface = {"instructions": [{"name": "recordRide"}]}
    changed_surface = {
        "instructions": [
            {"name": "recordRide"},
            {"name": "advanceProgramVersion"},
        ]
    }

    with pytest.raises(checker.ProgramVersionError, match="did not advance"):
        checker.validate_version_transition(0x40, base_surface, 0x40, changed_surface)

    checker.validate_version_transition(0x40, base_surface, 0x41, changed_surface)

    with pytest.raises(checker.ProgramVersionError, match="exactly one"):
        checker.validate_version_transition(0x40, base_surface, 0x42, changed_surface)


def test_manifest_rejects_a_nonadjacent_previous_version() -> None:
    checker = _load_checker()

    with pytest.raises(checker.ProgramVersionError, match="previous version"):
        checker._validate_manifest(
            {
                "schema_version": 1,
                "family": "V4-A",
                "previous_version": 0x3F,
                "current_version": 0x41,
                "reserved_v4b_version": 0x4B,
                "abi_snapshot": "protocol/anchor/abi/v0x41.json",
            }
        )


def test_historical_snapshot_must_equal_the_base_abi() -> None:
    checker = _load_checker()

    with pytest.raises(checker.ProgramVersionError, match="historical ABI snapshot"):
        checker.validate_historical_snapshot(
            0x40,
            {"instructions": [{"name": "recordRide"}]},
            {"instructions": [{"name": "differentInstruction"}]},
        )


def test_v4b_bootstrap_transition_distinguishes_predecessor_from_same_family_base() -> None:
    checker = _load_checker()
    manifest = json.loads((repo_root() / MANIFEST_PATH).read_text(encoding="utf-8"))
    bootstrap_manifest = {
        **manifest,
        "previous_version": 0x4B,
        "current_version": 0x4B,
        "abi_snapshot": "protocol/anchor/abi/v0x4b.json",
    }
    predecessor = {
        "family": manifest["family_bootstrap"]["predecessor_family"],
        "current_version": manifest["family_bootstrap"]["predecessor_version"],
    }

    assert checker._is_fresh_family_bootstrap_transition(
        bootstrap_manifest,
        predecessor,
        predecessor["current_version"],
    )
    assert not checker._is_fresh_family_bootstrap_transition(
        manifest,
        manifest,
        manifest["current_version"],
    )
    with pytest.raises(checker.ProgramVersionError, match="base family/version"):
        checker._is_fresh_family_bootstrap_transition(
            bootstrap_manifest,
            {"family": "unexpected"},
            bootstrap_manifest["current_version"],
        )


def test_onchain_idl_exposes_admin_version_transition() -> None:
    idl = json.loads(
        (repo_root() / "protocol/anchor/idl/boulder_rollers.json").read_text(
            encoding="utf-8"
        )
    )
    instruction = next(
        item for item in idl["instructions"] if item["name"] == "advanceProgramVersion"
    )

    assert [arg["name"] for arg in instruction["args"]] == [
        "expectedCurrentVersion",
        "newVersion",
    ]
    assert [account["name"] for account in instruction["accounts"]] == [
        "programConfig",
        "admin",
    ]


def test_upgrade_preflight_verifies_existing_program_authority_without_target_key() -> None:
    source = (repo_root() / PREFLIGHT_PATH).read_text(encoding="utf-8")

    assert 'solana program show "$TARGET_PROGRAM_ID"' in source
    assert 'LIVE_UPGRADE_AUTHORITY' in source
    assert 'E_AUTHORITY_IS_PAYER' in source
    assert 'ARTIFACT_SHA256=$(shasum -a 256' in source
    assert 'if [[ "$UPGRADE_PREFLIGHT" != true ]]' in source
    assert 'VALIDATE_ARGS+=("--configuration-only")' in source


def test_solana_ci_always_compares_abi_and_watches_every_generated_contract() -> None:
    source = (repo_root() / SOLANA_CI_PATH).read_text(encoding="utf-8")

    assert "PROGRAM_VERSION_FALLBACK_REF" in source
    assert 'args+=(--base-ref "$base_ref")' in source
    for contract_path in (
        "backend/app/generated_program_version.py",
        "backend/idl/boulder_rollers.json",
        "indexer/src/generated-program-version.ts",
        "mobile/src/generated/boulderRollersProgramVersion.ts",
        "web/portal/public/idl/boulder_rollers.json",
    ):
        assert source.count(contract_path) == 2
