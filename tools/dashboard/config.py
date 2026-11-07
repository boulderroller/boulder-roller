from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


DEFAULT_LOCAL_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "backend" / ".uvicorn.log"
DEFAULT_DEVNET_ADDRESS_REGISTRY = (
    Path(__file__).resolve().parent.parent
    / "protocol"
    / "anchor"
    / "addresses.devnet.json"
)


def _load_devnet_registry_program() -> str:
    try:
        registry = json.loads(DEFAULT_DEVNET_ADDRESS_REGISTRY.read_text())
        return registry["programs"]["boulder_rollers"]
    except Exception:
        return "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"


@dataclass
class DashboardConfig:
    remote_host: str
    local_log_path: Path
    local_api_base: str
    remote_api_base: str
    local_redis_host: str
    local_redis_port: int
    remote_redis_host: str
    remote_redis_port: int
    local_nats_monitor: str
    remote_nats_monitor: str
    solana_rpc_devnet: str
    solana_rpc_mainnet: str
    boulder_program: str
    dung_mint_program: str
    proof_verifier_program: str

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        return cls(
            remote_host=_env("BR_DASH_REMOTE_HOST", "root@localhost"),
            local_log_path=Path(
                _env("BR_DASH_LOCAL_LOG_PATH", str(DEFAULT_LOCAL_LOG_PATH))
            ),
            local_api_base=_env("BR_DASH_LOCAL_API_BASE", "http://localhost:8000"),
            remote_api_base=_env("BR_DASH_REMOTE_API_BASE", "http://localhost:8080"),
            local_redis_host=_env("BR_DASH_LOCAL_REDIS_HOST", "localhost"),
            local_redis_port=_env_int("BR_DASH_LOCAL_REDIS_PORT", 6379),
            remote_redis_host=_env("BR_DASH_REMOTE_REDIS_HOST", "localhost"),
            remote_redis_port=_env_int("BR_DASH_REMOTE_REDIS_PORT", 6379),
            local_nats_monitor=_env("BR_DASH_LOCAL_NATS_MONITOR", "http://localhost:8222"),
            remote_nats_monitor=_env("BR_DASH_REMOTE_NATS_MONITOR", "http://localhost:8222"),
            solana_rpc_devnet=_env("BR_DASH_SOLANA_RPC_DEVNET", "https://api.devnet.solana.com"),
            solana_rpc_mainnet=_env(
                "BR_DASH_SOLANA_RPC_MAINNET", "https://api.mainnet-beta.solana.com"
            ),
            boulder_program=_env(
                "BR_DASH_PROGRAM_BOULDER_ROLLERS",
                _load_devnet_registry_program(),
            ),
            dung_mint_program=_env(
                "BR_DASH_PROGRAM_DUNG_MINT",
                "A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ",
            ),
            proof_verifier_program=_env(
                "BR_DASH_PROGRAM_PROOF_VERIFIER",
                "Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC",
            ),
        )

    def program_list(self) -> List[Tuple[str, str]]:
        return [
            ("BoulderRollers", self.boulder_program),
            ("DungMint", self.dung_mint_program),
            ("ProofVerifier", self.proof_verifier_program),
        ]
