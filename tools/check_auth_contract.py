#!/usr/bin/env python3
"""Static auth contract gate for portal/mobile rider auth surfaces."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "auth" / "auth_state_v1.json"
MOBILE_AUTH_STATE = ROOT / "mobile" / "src" / "lib" / "authState.ts"
PORTAL_AUTH_STATE = ROOT / "web" / "portal" / "src" / "lib" / "authState.ts"
MOBILE_EAS = ROOT / "mobile" / "eas.json"
MOBILE_API = ROOT / "mobile" / "src" / "lib" / "api.ts"

BANNED_AUTH_COPY = [
    "Social Login",
    "social login",
    "Sign-in with wallet",
    "gas",
    "Privy authenticated",
    "Opening Privy",
    "Privy wallet",
    "social account",
    "Privy embedded wallet",
    "Connected wallet (SIWS)",
    "SIWS",
]

COPY_SCAN_ROOTS = [
    ROOT / "mobile" / "src" / "screens",
    ROOT / "mobile" / "src" / "components",
    ROOT / "web" / "portal" / "src" / "components" / "auth",
]

COPY_SCAN_FILES = [
    ROOT / "web" / "portal" / "src" / "lib" / "auth-errors.ts",
    ROOT / "web" / "portal" / "src" / "hooks" / "useWalletTransactionSigner.ts",
]


def fail(message: str) -> None:
    print(f"auth gate failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_ts_string_array(path: Path, symbol: str) -> list[str]:
    text = path.read_text()
    match = re.search(rf"export const {symbol}\s*=\s*\[(.*?)\]\s*as const", text, re.S)
    if not match:
        fail(f"{path.relative_to(ROOT)} missing exported {symbol}")
    return re.findall(r"'([^']+)'", match.group(1))


def check_auth_state_contract() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    expected_phases = fixture["phases"]
    expected_access_methods = fixture["access_methods"]

    for path in (MOBILE_AUTH_STATE, PORTAL_AUTH_STATE):
        phases = extract_ts_string_array(path, "AUTH_PHASE_VALUES")
        access_methods = extract_ts_string_array(path, "AUTH_ACCESS_METHOD_VALUES")
        if phases != expected_phases:
            fail(f"{path.relative_to(ROOT)} AUTH_PHASE_VALUES drifted: {phases}")
        if access_methods != expected_access_methods:
            fail(f"{path.relative_to(ROOT)} AUTH_ACCESS_METHOD_VALUES drifted: {access_methods}")


def iter_copy_files() -> list[Path]:
    paths: list[Path] = []
    for root in COPY_SCAN_ROOTS:
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.suffix in {".ts", ".tsx"})
    paths.extend(path for path in COPY_SCAN_FILES if path.exists())
    return sorted(set(paths))


def is_dev_only_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("*")
        or stripped.startswith("//")
        or stripped.startswith("/*")
        or "console." in stripped
        or "debugLog(" in stripped
        or stripped.startswith("import ")
    )


def check_rider_auth_copy() -> None:
    violations: list[str] = []
    for path in iter_copy_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if is_dev_only_line(line):
                continue
            for term in BANNED_AUTH_COPY:
                if term in line:
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {term}")

    if violations:
        fail("rider-facing auth copy leaked provider/internal terms:\n" + "\n".join(violations))


def check_mobile_env_and_nonce_contract() -> None:
    eas = json.loads(MOBILE_EAS.read_text())
    production_api = eas["build"]["production"]["env"]["API_URL"]
    if production_api != "https://api.boulderroller.xyz":
        fail(f"mobile production API_URL must be https://api.boulderroller.xyz, got {production_api}")

    api_text = MOBILE_API.read_text()
    if "async getNonce(wallet: string, deviceId: string)" not in api_text:
        fail("mobile api.getNonce must require deviceId")
    if "this.request('POST', '/auth/nonce', { wallet, deviceId }, true)" not in api_text:
        fail("mobile api.getNonce must send deviceId to /auth/nonce")


def main() -> int:
    check_auth_state_contract()
    check_rider_auth_copy()
    check_mobile_env_and_nonce_contract()
    print("auth contract gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
