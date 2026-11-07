from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
IDL_PATHS = (
    REPO_ROOT / "protocol" / "anchor" / "idl" / "boulder_rollers.json",
    REPO_ROOT / "backend" / "idl" / "boulder_rollers.json",
    REPO_ROOT / "web" / "portal" / "public" / "idl" / "boulder_rollers.json",
)
PROTOCOL_SOURCE = (
    REPO_ROOT
    / "protocol"
    / "anchor"
    / "programs"
    / "boulder_rollers"
    / "src"
    / "lib.rs"
)


def _named(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(item for item in items if item["name"] == name)


def _function_body(source: str, function_name: str) -> str:
    start = source.index(f"pub fn {function_name}")
    next_function = source.find("\n    pub fn ", start + 1)
    return source[start:] if next_function == -1 else source[start:next_function]


def test_dung_burn_abi_is_identical_and_requires_atomic_accounting_state() -> None:
    canonical_bytes = IDL_PATHS[0].read_bytes()
    assert all(path.read_bytes() == canonical_bytes for path in IDL_PATHS[1:])

    idl = json.loads(canonical_bytes)
    for instruction_name in ("upgradeBeetleCard", "createVault"):
        instruction = _named(idl["instructions"], instruction_name)
        burn_state = _named(instruction["accounts"], "dungMintState")
        assert burn_state["isMut"] is True
        assert burn_state["isSigner"] is False

    burn_event = _named(idl["events"], "DungBurned")
    assert [field["name"] for field in burn_event["fields"]] == [
        "actor",
        "amount",
        "burnKind",
        "totalProtocolBurned",
        "timestamp",
    ]
    assert any(
        error["name"] == "DungBurnAccountingMismatch"
        for error in idl["errors"]
    )


def test_every_protocol_dung_burn_updates_telemetry_in_the_same_instruction() -> None:
    source = PROTOCOL_SOURCE.read_text(encoding="utf-8")
    for function_name in ("upgrade_beetle_card", "create_vault"):
        body = _function_body(source, function_name)
        assert "token::burn(" in body
        assert ".record_protocol_burn(" in body
        assert "emit!(DungBurned" in body


def test_read_models_and_truth_docs_reject_the_subtraction_fallback() -> None:
    indexer_api = (REPO_ROOT / "indexer" / "src" / "api.ts").read_text(
        encoding="utf-8"
    )
    admin_api = (
        REPO_ROOT / "backend" / "app" / "routes" / "admin_platform.py"
    ).read_text(encoding="utf-8")
    protocol_truths = (REPO_ROOT / "docs" / "PROTOCOL_TRUTHS.md").read_text(
        encoding="utf-8"
    )
    backend_truths = (REPO_ROOT / "docs" / "BACKEND_TRUTHS.md").read_text(
        encoding="utf-8"
    )

    assert "row.spl_mint_supply" in indexer_api
    assert "totalMinted - totalBurned" not in indexer_api
    assert 'row.get("spl_mint_supply")' in admin_api
    assert 'row.get("circulating_supply"' not in admin_api
    assert "only circulating DUNG authority" in " ".join(protocol_truths.split())
    assert "zero are not fallbacks" in " ".join(backend_truths.split())
