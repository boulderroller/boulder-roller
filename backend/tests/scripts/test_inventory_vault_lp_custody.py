from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "inventory_vault_lp_custody.py"
)
SPEC = importlib.util.spec_from_file_location("inventory_vault_lp_custody", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inventory
SPEC.loader.exec_module(inventory)


PROGRAM_ID = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
LEGACY_V4A_PROGRAM_ID = "HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst"
GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"


def _row() -> dict:
    return {
        "vault_id": 2,
        "rider": "Rider1111111111111111111111111111111111111",
        "vault_stake": "Stake1111111111111111111111111111111111111",
        "lp_mint": "Mint11111111111111111111111111111111111111",
        "legacy_wallet_ata": "Source11111111111111111111111111111111111",
        "recorded_lp_tokens": 100,
        "canonical_position": "Position111111111111111111111111111111111",
        "canonical_observation": None,
        "attributable_total": 100,
        "attributable_sources": [
            {
                "address": "Source11111111111111111111111111111111111",
                "authority": "Rider1111111111111111111111111111111111111",
                "mint": "Mint11111111111111111111111111111111111111",
                "amount_base_units": 100,
                "state": "initialized",
                "account_sha256": "source-hash",
            }
        ],
        "decision": "restore",
        "actions": [
            {
                "action": "restore",
                "source_kind": "legacy_wallet_ata",
                "source": "Source11111111111111111111111111111111111",
                "amount_base_units": 100,
            }
        ],
        "vault_stake_observation": {
            "account_sha256": "stake-hash",
            "snapshot_layout": "legacy",
            "cal_staked": 100,
            "effective_lp_tokens": 0,
            "pending_lp_tokens": 0,
            "pending_effective_week_plus_one": 0,
            "rewards_earned": 0,
        },
        "vault_activation_observation": {
            "address": "Activation1111111111111111111111111111111",
            "account_sha256": "activation-hash",
            "is_active": True,
            "seed_generation": 1,
            "economics_start_epoch": 0,
        },
    }


def _vault() -> dict:
    return {
        "vault_id": 2,
        "lp_mint": "Mint11111111111111111111111111111111111111",
        "lp_mint_account_sha256": "mint-hash",
        "mint_supply": 100,
        "token_account_total": 100,
        "vault_stake_recorded_total": 100,
        "unattributed_holders": [],
    }


def _manifest() -> dict:
    return {
        "schema": inventory.RETIREMENT_SCHEMA,
        "retirement_id": "devnet-test-fixtures",
        "network": "devnet",
        "genesis_hash": GENESIS_HASH,
        "program_id": PROGRAM_ID,
        "retired_at": "2026-07-18T00:00:00Z",
        "mutation": "none",
        "transaction_signatures": [],
        "fixtures": [
            {
                "vault_id": 2,
                "rider": "Rider1111111111111111111111111111111111111",
                "vault_stake": "Stake1111111111111111111111111111111111111",
                "vault_activation": "Activation1111111111111111111111111111111",
                "lp_mint": "Mint11111111111111111111111111111111111111",
                "source_lp_account": "Source11111111111111111111111111111111111",
                "canonical_position": "Position111111111111111111111111111111111",
                "amount_base_units": 100,
                "rewards_earned": 0,
                "economics_start_epoch": 0,
                "reason": "Ephemeral test fixture.",
                "account_sha256": {
                    "vault_stake": "stake-hash",
                    "vault_activation": "activation-hash",
                    "lp_mint": "mint-hash",
                    "source_lp_account": "source-hash",
                },
            }
        ],
    }


def test_retirement_reclassifies_only_exact_quarantined_devnet_fixture() -> None:
    rows = [_row()]
    vaults = [_vault()]

    result = inventory._apply_retirement_manifest(
        rows,
        vaults,
        _manifest(),
        genesis_hash=GENESIS_HASH,
        program_id=PROGRAM_ID,
    )

    assert result == {
        "retirement_id": "devnet-test-fixtures",
        "retirement_count": 1,
        "mutation": "none",
        "transaction_signatures": [],
    }
    assert rows[0]["decision"] == "retired_fixture"
    assert rows[0]["actions"] == []
    assert rows[0]["retirement"]["account_state_mutated"] is False
    assert vaults[0]["retired_stake_recorded_total"] == 100
    assert vaults[0]["surviving_stake_recorded_total"] == 0


@pytest.mark.parametrize(
    ("field", "actual"),
    [("genesis_hash", "mainnet"), ("program_id", "OtherProgram")],
)
def test_retirement_rejects_wrong_chain_or_program(field: str, actual: str) -> None:
    kwargs = {"genesis_hash": GENESIS_HASH, "program_id": PROGRAM_ID}
    kwargs[field] = actual

    with pytest.raises(RuntimeError, match=field.replace("_", " ")):
        inventory._apply_retirement_manifest(
            [_row()],
            [_vault()],
            _manifest(),
            **kwargs,
        )


def test_retirement_rejects_account_drift() -> None:
    row = _row()
    row["attributable_sources"][0]["account_sha256"] = "changed"

    with pytest.raises(RuntimeError, match="source LP account hash"):
        inventory._apply_retirement_manifest(
            [row],
            [_vault()],
            _manifest(),
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
        )


def test_retirement_rejects_authoritative_or_mutable_fixture() -> None:
    row = _row()
    row["vault_activation_observation"]["seed_generation"] = 2

    with pytest.raises(RuntimeError, match="generation-1 quarantine"):
        inventory._apply_retirement_manifest(
            [row],
            [_vault()],
            _manifest(),
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
        )


def test_retirement_rejects_any_onchain_mutation_claim() -> None:
    manifest = _manifest()
    manifest["mutation"] = "admin"
    manifest["transaction_signatures"] = ["tx"]

    with pytest.raises(RuntimeError, match="mutation must be none"):
        inventory._apply_retirement_manifest(
            [_row()],
            [_vault()],
            manifest,
            genesis_hash=GENESIS_HASH,
            program_id=PROGRAM_ID,
        )


def test_checked_in_retirement_manifest_names_only_the_six_dead_key_fixtures() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "design"
        / "evidence"
        / "LP_CUSTODY_DEVNET_RETIREMENTS_2026-07-18.json"
    )

    manifest, manifest_sha256 = inventory._load_retirement_manifest(path)

    assert manifest_sha256 == manifest["manifest_sha256"]
    assert manifest["genesis_hash"] == GENESIS_HASH
    assert manifest["program_id"] == LEGACY_V4A_PROGRAM_ID
    assert manifest["mutation"] == "none"
    assert manifest["transaction_signatures"] == []
    assert {fixture["vault_id"] for fixture in manifest["fixtures"]} == {
        2,
        3,
        4,
        5,
        6,
        15,
    }


def test_surviving_position_gate_requires_frozen_exact_custody() -> None:
    ready = deepcopy(_row())
    ready["decision"] = "ready"
    ready["actions"] = []
    ready["canonical_observation"] = {
        "amount_base_units": 100,
        "state": "initialized",
    }

    with pytest.raises(RuntimeError, match="frozen canonical custody"):
        inventory._validate_surviving_positions([ready], [_vault()])
