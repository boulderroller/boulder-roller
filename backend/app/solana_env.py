import json
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_SOLANA_RPC_URL = "https://api.devnet.solana.com"
FALLBACK_BOULDER_ROLLERS_PROGRAM_ID = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
DEFAULT_PROOF_VERIFIER_PROGRAM_ID = "Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC"
DEFAULT_DUNG_MINT_PROGRAM_ID = "A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ"
FALLBACK_DUNG_MINT_ADDRESS = "CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk"
FALLBACK_CAL_MINT_ADDRESS = "4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh"


@lru_cache(maxsize=1)
def load_devnet_address_registry() -> dict:
    """Load canonical devnet addresses from the Anchor registry if present."""
    registry_path = (
        Path(__file__).resolve().parents[2]
        / "protocol"
        / "anchor"
        / "addresses.devnet.json"
    )
    try:
        return json.loads(registry_path.read_text())
    except Exception:
        return {}


def _registry_program_id() -> str:
    registry = load_devnet_address_registry()
    return (
        registry.get("programs", {}).get("boulder_rollers")
        or FALLBACK_BOULDER_ROLLERS_PROGRAM_ID
    )


def _registry_mint(name: str, fallback: str) -> str:
    registry = load_devnet_address_registry()
    return registry.get("mints", {}).get(name, {}).get("address") or fallback


DEFAULT_BOULDER_ROLLERS_PROGRAM_ID = _registry_program_id()
DEFAULT_DUNG_MINT_ADDRESS = _registry_mint("dung_mint", FALLBACK_DUNG_MINT_ADDRESS)
DEFAULT_CAL_MINT_ADDRESS = _registry_mint("cal_mint", FALLBACK_CAL_MINT_ADDRESS)


def solana_rpc_url() -> str:
    return os.getenv("SOLANA_RPC_URL", DEFAULT_SOLANA_RPC_URL)


def boulder_rollers_program_id() -> str:
    return os.getenv("BOULDER_ROLLERS_PROGRAM_ID", DEFAULT_BOULDER_ROLLERS_PROGRAM_ID)


def proof_verifier_program_id() -> str:
    return os.getenv("PROOF_VERIFIER_PROGRAM_ID", DEFAULT_PROOF_VERIFIER_PROGRAM_ID)


def dung_mint_program_id() -> str:
    return os.getenv("DUNG_MINT_PROGRAM_ID", DEFAULT_DUNG_MINT_PROGRAM_ID)


def dung_mint_address() -> str:
    return os.getenv("DUNG_MINT_ADDRESS", DEFAULT_DUNG_MINT_ADDRESS)


def cal_mint_address() -> str:
    return os.getenv("CAL_MINT_ADDRESS", DEFAULT_CAL_MINT_ADDRESS)
