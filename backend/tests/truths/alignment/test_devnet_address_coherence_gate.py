"""Devnet address coherence gate.

This is a small static gate for the fresh devnet lane. It prevents active
runtime surfaces from quietly pointing at retired program or mint addresses
after the canonical registry moves.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = REPO_ROOT / "protocol" / "anchor" / "addresses.devnet.json"

RETIRED_ACTIVE_LANE_ADDRESSES = {
    # Split strings so this gate does not match its own source file.
    "EUjDN" + "CrJuCjbDUD4u6iSj8vddGgc7meanDW9Ti31jWAd": "retired boulder_rollers program",
    "2EG8" + "euB8APrZa4YMscBvMptiAMZMaSysWYt8qforA7dU": "retired CAL mint",
    "8eUu" + "v1irYCmmrTbcr9RLncZj89pcDmJGCe155DNvB6up": "retired DUNG mint",
}

RETIRED_ADDRESS_ALLOWLIST_PREFIXES = (
    ".beads/",
    "archive/",
    "history/",
)

TEXT_FILE_SUFFIXES = {
    ".cfg",
    ".env",
    ".example",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yml",
    ".yaml",
}


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _current_addresses() -> dict[str, str]:
    registry = _registry()
    return {
        "program": registry["programs"]["boulder_rollers"],
        "cal_mint": registry["mints"]["cal_mint"]["address"],
        "dung_mint": registry["mints"]["dung_mint"]["address"],
    }


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _env_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}=(?P<value>[^\s#]+)", text, re.MULTILINE)
    assert match, f"missing {key}= assignment"
    return match.group("value").strip().strip('"').strip("'")


def _single_match(pattern: str, text: str, label: str) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    assert len(matches) == 1, f"expected exactly one {label}, found {len(matches)}"
    return matches[0]


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _is_allowed_historical_path(path: str) -> bool:
    return path.startswith(RETIRED_ADDRESS_ALLOWLIST_PREFIXES)


def _is_text_file(path: str) -> bool:
    file_path = Path(path)
    if file_path.name.startswith(".env"):
        return True
    return file_path.suffix in TEXT_FILE_SUFFIXES


def test_retired_devnet_addresses_do_not_appear_in_active_tracked_files() -> None:
    """Retired lane addresses -> active repo surfaces - STATUS: PASS.

    Retired program/mint addresses may appear only in explicit historical
    locations. If they appear in config, docs, app code, or operator guides,
    someone can copy/paste a stale lane into production work.
    """
    offenders: list[str] = []

    for path in _tracked_files():
        if _is_allowed_historical_path(path) or not _is_text_file(path):
            continue

        try:
            text = _read(path)
        except (FileNotFoundError, UnicodeDecodeError):
            continue

        for address, label in RETIRED_ACTIVE_LANE_ADDRESSES.items():
            if address in text:
                offenders.append(f"{path}: contains {label} {address}")

    assert not offenders, (
        "retired devnet addresses leaked into active tracked files:\n  "
        + "\n  ".join(offenders)
    )


def test_program_id_runtime_surfaces_match_devnet_registry() -> None:
    """boulder_rollers program id -> runtime surfaces - STATUS: PASS."""
    expected = _current_addresses()["program"]

    lib_rs = _read("protocol/anchor/programs/boulder_rollers/src/lib.rs")
    assert (
        _single_match(
            r'#\[cfg\(not\(feature = "stage1-localnet"\)\)\]\s*declare_id!\("([^"]+)"\);',
            lib_rs, "default Anchor declare_id",
        )
        == expected
    )
    localnet = _single_match(
        r'#\[cfg\(feature = "stage1-localnet"\)\]\s*declare_id!\("([^"]+)"\);',
        lib_rs, "feature-only Anchor declare_id",
    )
    assert localnet != expected
    assert re.findall(r'declare_id!\("([^"]+)"\);', lib_rs) == [expected, localnet]
    for path in ("protocol/anchor/scripts/build-stage1-localnet.py", "protocol/anchor/scripts/check-deployable-artifact.py"):
        assert _single_match(r'^LOCAL_ID = "([^"]+)"$', _read(path), path) == localnet

    anchor_toml = _read("protocol/anchor/Anchor.toml")
    anchor_programs = re.findall(r'^boulder_rollers\s*=\s*"([^"]+)"', anchor_toml, re.MULTILINE)
    assert anchor_programs, "Anchor.toml must define boulder_rollers program IDs"
    assert set(anchor_programs) == {expected}

    backend_env = _read("backend/app/solana_env.py")
    assert (
        _single_match(
            r'FALLBACK_BOULDER_ROLLERS_PROGRAM_ID\s*=\s*"([^"]+)"',
            backend_env,
            "backend program fallback",
        )
        == expected
    )

    indexer_config = _read("indexer/src/config.ts")
    assert (
        _single_match(
            r"FALLBACK_PROGRAM_ID\s*=\s*'([^']+)'",
            indexer_config,
            "indexer program fallback",
        )
        == expected
    )

    mobile_config = _read("mobile/src/constants/config.ts")
    assert (
        _single_match(
            r"SOLANA_PROGRAM_ID\s*=\s*'([^']+)'",
            mobile_config,
            "mobile program fallback",
        )
        == expected
    )

    portal_solana = _read("web/portal/src/lib/solana.ts")
    assert (
        _single_match(
            r"boulder_rollers:\s*'([^']+)'",
            portal_solana,
            "portal program fallback",
        )
        == expected
    )

    docker_compose = _read("docker-compose.yml")
    assert expected in docker_compose
    assert "BOULDER_ROLLERS_PROGRAM_ID" in docker_compose

    dashboard_config = _read("tools/dashboard/config.py")
    assert expected in dashboard_config


def test_env_examples_and_production_envs_match_devnet_registry() -> None:
    """Registry addresses -> env surfaces - STATUS: PASS."""
    expected = _current_addresses()

    root_env = _read(".env.example")
    assert _env_value(root_env, "BOULDER_ROLLERS_PROGRAM_ID") == expected["program"]
    assert _env_value(root_env, "VITE_BOULDER_ROLLERS_PROGRAM_ID") == expected["program"]
    assert _env_value(root_env, "BR_DASH_PROGRAM_BOULDER_ROLLERS") == expected["program"]
    assert _env_value(root_env, "CAL_MINT_ADDRESS") == expected["cal_mint"]
    assert _env_value(root_env, "CAL_MINT_PUBKEY") == expected["cal_mint"]
    assert _env_value(root_env, "VITE_CAL_MINT_ADDRESS") == expected["cal_mint"]
    assert _env_value(root_env, "DUNG_MINT_ADDRESS") == expected["dung_mint"]
    assert _env_value(root_env, "VITE_DUNG_MINT_ADDRESS") == expected["dung_mint"]

    portal_env = _read("web/portal/.env.production")
    assert _env_value(portal_env, "VITE_BOULDER_ROLLERS_PROGRAM_ID") == expected["program"]
    assert _env_value(portal_env, "VITE_CAL_MINT_ADDRESS") == expected["cal_mint"]
    assert _env_value(portal_env, "VITE_DUNG_MINT_ADDRESS") == expected["dung_mint"]

    scan_env = _read("web/scan/.env.production")
    assert _env_value(scan_env, "VITE_BOULDER_ROLLERS_PROGRAM_ID") == expected["program"]


def test_mint_runtime_surfaces_match_devnet_registry() -> None:
    """CAL/DUNG mint addresses -> runtime surfaces - STATUS: PASS."""
    expected = _current_addresses()

    backend_env = _read("backend/app/solana_env.py")
    assert (
        _single_match(
            r'FALLBACK_CAL_MINT_ADDRESS\s*=\s*"([^"]+)"',
            backend_env,
            "backend CAL mint fallback",
        )
        == expected["cal_mint"]
    )
    assert (
        _single_match(
            r'FALLBACK_DUNG_MINT_ADDRESS\s*=\s*"([^"]+)"',
            backend_env,
            "backend DUNG mint fallback",
        )
        == expected["dung_mint"]
    )

    mobile_config = _read("mobile/src/constants/config.ts")
    assert (
        _single_match(r"CAL_MINT\s*=\s*'([^']+)'", mobile_config, "mobile CAL mint")
        == expected["cal_mint"]
    )
    assert (
        _single_match(r"DUNG_MINT\s*=\s*'([^']+)'", mobile_config, "mobile DUNG mint")
        == expected["dung_mint"]
    )

    portal_solana = _read("web/portal/src/lib/solana.ts")
    assert expected["cal_mint"] in portal_solana
    assert expected["dung_mint"] in portal_solana


def test_active_operator_docs_name_current_devnet_addresses() -> None:
    """Registry addresses -> operator docs; agent entrypoint -> registry."""
    expected = _current_addresses()

    agent_entrypoint = _read("CLAUDE.md")
    assert "protocol/anchor/addresses.devnet.json" in agent_entrypoint
    assert all(address not in agent_entrypoint for address in expected.values())

    doc_paths = [
        "docs/CI_CD_SECRETS_GUIDE.md",
        "docs/CLIENT_SIDE_BUILDING.md",
        "docs/DEVNET_TEST_DATA.md",
        "docs/FRESHEST_SPEC.md",
        "docs/INTEGRATION_REGISTRY.md",
        "docs/INTEGRATION_TEST_PLAN.md",
        "docs/PORTAL_PROTOCOL_VALIDATION_REPORT.md",
        "docs/SOLANA_PROGRAMS_GUIDE.md",
        "docs/security/ANCHOR_SECURITY.md",
    ]

    missing: list[str] = []
    for path in doc_paths:
        text = _read(path)
        if expected["program"] not in text:
            missing.append(f"{path}: missing current boulder_rollers program")

    docs_with_mints = [
        "docs/CI_CD_SECRETS_GUIDE.md",
        "docs/DEVNET_TEST_DATA.md",
        "docs/FRESHEST_SPEC.md",
        "docs/INTEGRATION_REGISTRY.md",
        "docs/INTEGRATION_TEST_PLAN.md",
        "docs/PORTAL_PROTOCOL_VALIDATION_REPORT.md",
        "docs/SOLANA_PROGRAMS_GUIDE.md",
    ]
    for path in docs_with_mints:
        text = _read(path)
        if expected["cal_mint"] not in text:
            missing.append(f"{path}: missing current CAL mint")
        if expected["dung_mint"] not in text:
            missing.append(f"{path}: missing current DUNG mint")

    assert not missing, "active operator docs drifted from registry:\n  " + "\n  ".join(missing)
