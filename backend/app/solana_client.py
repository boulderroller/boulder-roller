from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from anchorpy import Context, Idl, Program, Provider, Wallet
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .config import is_production_environment
from .metrics import SOLANA_RPC_CALLS, SOLANA_RPC_ERRORS, SOLANA_RPC_LATENCY
from .solana_env import (
    boulder_rollers_program_id,
    dung_mint_address,
    dung_mint_program_id,
    proof_verifier_program_id,
    solana_rpc_url,
)
from . import solana_direct

logger = logging.getLogger(__name__)

DEFAULT_PUBKEY = "11111111111111111111111111111111"


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class SolanaSettings:
    rpc_url: str
    fee_payer_secret: Optional[str]
    boulder_program_id: str
    dung_mint_program_id: str
    proof_verifier_program_id: str
    dung_mint_address: str
    use_stub: bool = False


def load_solana_settings() -> SolanaSettings:
    return SolanaSettings(
        rpc_url=solana_rpc_url(),
        fee_payer_secret=(
            os.getenv("FEE_PAYER_KEYPAIR")
            or os.getenv("SOLANA_PAYER_SECRET")
            or os.getenv("SOLANA_PAYER_PATH")
        ),
        boulder_program_id=boulder_rollers_program_id(),
        dung_mint_program_id=dung_mint_program_id(),
        proof_verifier_program_id=proof_verifier_program_id(),
        dung_mint_address=dung_mint_address(),
        use_stub=_parse_bool(os.getenv("SOLANA_STUB"), default=False),
    )


class BoulderRollersClient:
    """Thin Solana client wrapper. Uses stubbed responses when not configured."""

    def __init__(self, settings: Optional[SolanaSettings] = None) -> None:
        self.settings = settings or load_solana_settings()

        # Production stub guard: fail fast if stub mode enabled in production
        if is_production_environment() and self.settings.use_stub:
            raise RuntimeError(
                "SOLANA_STUB=true is not allowed in production! "
                "Set SOLANA_STUB=false or remove the environment variable."
            )

        # Log stub mode warning in non-production environments
        if self.settings.use_stub:
            logger.warning(
                "⚠️ Solana client running in STUB MODE - "
                "transactions will return fake signatures"
            )

        self._client = AsyncClient(self.settings.rpc_url, commitment=Confirmed)
        self._wallet = self._load_wallet(self.settings.fee_payer_secret)
        self._provider: Optional[Provider] = None
        self._boulder_program: Optional[Program] = None
        self._dung_mint_address = self.settings.dung_mint_address

        if self._wallet:
            opts = TxOpts(preflight_commitment=Confirmed, skip_preflight=False)
            self._provider = Provider(self._client, Wallet(self._wallet), opts=opts)
            self._boulder_program = self._load_program(
                "boulder_rollers",
                self.settings.boulder_program_id,
                self._provider,
            )
        else:
            logger.warning(
                "⚠️ Solana client has no wallet configured - "
                "will operate in implicit stub mode"
            )

        # Final stub mode status log
        if self.stubbed and not self.settings.use_stub:
            logger.warning(
                "⚠️ Solana client in implicit stub mode "
                "(missing wallet, program, or placeholder program ID)"
            )

    @property
    def stubbed(self) -> bool:
        return (
            self.settings.use_stub
            or self._provider is None
            or self._boulder_program is None
            or self._is_placeholder(self.settings.boulder_program_id)
        )

    def _record_stubbed_metrics(self, method: str) -> None:
        SOLANA_RPC_CALLS.labels(method=method).inc()
        SOLANA_RPC_ERRORS.labels(method=method).inc()
        SOLANA_RPC_LATENCY.labels(method=method).observe(0.0)

    async def close(self) -> None:
        await self._client.close()

    # =========================================================================
    # Vault Methods
    # =========================================================================

    async def get_vault(self, vault_id: int) -> Dict[str, Any]:
        """
        Fetch vault account data from chain.

        Args:
            vault_id: On-chain vault ID

        Returns:
            Dict with vault data or error
        """
        if self.settings.use_stub:
            self._record_stubbed_metrics("get_vault")
            return self._stub_response("get_vault")

        try:
            config = solana_direct.load_default_config()
            vault = await solana_direct.get_vault_account(config, vault_id)
            if vault is None:
                return {"error": "vault_not_found", "vault_id": vault_id}
            return vault
        except Exception as exc:
            logger.exception("get_vault failed: %s", exc)
            return self._stub_response("get_vault", error=str(exc))

    async def distribute_epoch_rewards(
        self,
        vault_id: int,
        settlement_week: int,
        pol_account: Optional[str] = None,
        protocol_treasury: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Distribute epoch rewards for a vault on-chain.

        Converts accumulated CAL to DUNG (1000:1) and distributes:
        - 55% to leaderboard (top 10)
        - 27% to stakers
        - 3% to local legend
        - 5% to POL
        - 10% to protocol treasury

        Args:
            vault_id: On-chain vault ID
            settlement_week: Settlement week being finalized
            pol_account: Optional token account for POL
            protocol_treasury: Optional token account for protocol

        Returns:
            Dict with signature and metadata
        """
        if self.settings.use_stub:
            self._record_stubbed_metrics("distribute_epoch_rewards")
            return self._stub_response("distribute_epoch_rewards")

        try:
            config = solana_direct.load_default_config()
            sig = await solana_direct.send_distribute_epoch_rewards(
                config=config,
                vault_id=vault_id,
                settlement_week=settlement_week,
                pol_account=pol_account,
                protocol_treasury=protocol_treasury,
            )
            return {
                "signature": sig,
                "vault_id": vault_id,
                "program_id": str(self.settings.boulder_program_id),
                "stubbed": False,
            }
        except Exception as exc:
            logger.exception("distribute_epoch_rewards failed: %s", exc)
            return self._stub_response("distribute_epoch_rewards", error=str(exc))

    async def _send_or_stub(
        self,
        method_name: str,
        accounts: Optional[Dict[str, Any]] = None,
        args: Optional[list[Any]] = None,
    ) -> Dict[str, Any]:
        if self.stubbed:
            self._record_stubbed_metrics(method_name)
            return self._stub_response(method_name)

        program = self._boulder_program
        if program is None:
            self._record_stubbed_metrics(method_name)
            return self._stub_response(method_name, error="program_not_loaded")

        start = time.perf_counter()
        SOLANA_RPC_CALLS.labels(method=method_name).inc()
        try:
            rpc = program.rpc.get(method_name)
            if rpc is None:
                SOLANA_RPC_ERRORS.labels(method=method_name).inc()
                return self._stub_response(method_name, error="instruction_not_found")

            context = Context(
                accounts=self._clean_accounts(accounts or {}),
                signers=[self._wallet] if self._wallet else None,
            )
            signature = await rpc(*(args or []), ctx=context)
            return {
                "signature": signature,
                "program_id": str(program.program_id),
                "stubbed": False,
            }
        except Exception as exc:  # pragma: no cover - defensive logging
            SOLANA_RPC_ERRORS.labels(method=method_name).inc()
            logger.exception("Solana call %s failed: %s", method_name, exc)
            return self._stub_response(method_name, error=str(exc))
        finally:
            SOLANA_RPC_LATENCY.labels(method=method_name).observe(time.perf_counter() - start)

    def _clean_accounts(self, accounts: Dict[str, Any]) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        for key, value in accounts.items():
            if isinstance(value, Pubkey):
                cleaned[key] = value
            elif isinstance(value, str):
                try:
                    cleaned[key] = Pubkey.from_string(value)
                except Exception:
                    cleaned[key] = value
            else:
                cleaned[key] = value
        return cleaned

    def _load_wallet(self, secret: Optional[str]) -> Optional[Keypair]:
        self._payer_path: Optional[str] = None
        if not secret:
            return None
        try:
            path = Path(secret).expanduser()
            if path.exists():
                self._payer_path = str(path)
            return solana_direct._load_keypair(secret)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load keypair from configured fee payer: %s", exc)
        return None

    def _load_program(self, name: str, program_id: str, provider: Provider) -> Optional[Program]:
        if self._is_placeholder(program_id):
            return None
        idl_dict = self._load_idl(name)
        if not idl_dict:
            logger.warning("IDL for %s not found; running in stub mode", name)
            return None
        try:
            # Convert raw dict to Idl object (anchorpy expects Idl, not dict)
            idl = Idl.from_json(json.dumps(idl_dict))
            return Program(idl, Pubkey.from_string(program_id), provider)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load program %s: %s", name, exc)
            return None

    def _load_idl(self, name: str) -> Optional[dict[str, Any]]:
        # Try multiple paths for IDL files
        repo_root = Path(__file__).resolve().parent.parent
        idl_paths = [
            repo_root / "idl" / f"{name}.json",  # Docker: /app/idl/
            repo_root.parent / "protocol" / "anchor" / "target" / "idl" / f"{name}.json",  # Local dev
        ]

        for idl_path in idl_paths:
            if idl_path.exists():
                try:
                    with idl_path.open("r", encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning("Failed to read IDL %s: %s", idl_path, exc)

        return None

    def _stub_response(self, action: str, error: Optional[str] = None) -> Dict[str, Any]:
        if is_production_environment():
            raise RuntimeError(f"Solana client attempted to stub {action} in production!")

        logger.warning("⚠️ Solana %s returning stub response (dev mode)", action)
        return {
            "signature": f"stub-{action}-{secrets.token_hex(8)}",
            "program_id": None,
            "stubbed": True,
            "error": error,
        }

    def _is_placeholder(self, program_id: str) -> bool:
        return program_id == DEFAULT_PUBKEY or program_id.strip() == ""

    def _pubkey_or_none(self, value: str) -> Optional[Pubkey]:
        try:
            return Pubkey.from_string(value)
        except Exception:
            return None


solana_client = BoulderRollersClient()


def get_solana_client() -> BoulderRollersClient:
    return solana_client
