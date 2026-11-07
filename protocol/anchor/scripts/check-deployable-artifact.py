#!/usr/bin/env python3
"""Reject localnet artifacts everywhere and devnet artifacts on other targets."""
import argparse
import hashlib
from pathlib import Path
import sys

LOCAL_ID = "5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt"
PRODUCTION_ID = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
DEVNET_DISPATCH = b"global:register_stage1_test_pool"
LOCALNET_DISPATCH = b"global:set_test_lst_rate"
# Test setup handlers compiled only with the localnet-only smoke-helpers feature.
SMOKE_DISPATCH = (b"global:admin_override_open_settlement_week", b"global:admin_seed_pending_rewards",
                  b"global:admin_override_stake_eligibility")


def pubkey(text):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value = 0
    for char in text:
        value = value * 58 + alphabet.index(char)
    return value.to_bytes(32, "big")


def check(path, cluster="mainnet-beta"):
    if cluster not in {"mainnet-beta", "devnet"}:
        raise ValueError("deployment target must be mainnet-beta or devnet")
    data = Path(path).read_bytes()
    if not data.startswith(b"\x7fELF"):
        raise ValueError("not an ELF program")
    if b"BOULDERROLLER_STAGE1_LOCALNET_ONLY" in data or LOCALNET_DISPATCH in data or pubkey(LOCAL_ID) in data:
        raise ValueError("stage1-localnet binary is forbidden for deployment")
    if any(name in data for name in SMOKE_DISPATCH):
        raise ValueError("test setup helper binary is forbidden for deployment")
    if (DEVNET_DISPATCH in data or b"BOULDERROLLER_STAGE1_DEVNET_TEST_POOL" in data) and cluster != "devnet":
        raise ValueError("stage1-devnet test-pool binary requires target cluster devnet")
    if pubkey(PRODUCTION_ID) not in data:
        raise ValueError("deployable program ID missing")
    return hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("artifact")
        parser.add_argument("--cluster", choices=["mainnet-beta", "devnet"], default="mainnet-beta")
        args = parser.parse_args()
        print("Deployable artifact SHA-256:", check(args.artifact, args.cluster))
    except (ValueError, OSError, IndexError) as error:
        sys.exit(f"Artifact refused: {error}")
