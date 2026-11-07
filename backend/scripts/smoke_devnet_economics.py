#!/usr/bin/env python3
"""
Fresh-lane devnet economics smoke test.

Runs the real V4-A protocol path on devnet:
1. Create or resume a vault on the fresh lane
2. Seed and activate a newly created vault
3. Bind the run to one exact, already-finalizable Settlement Week
4. Record a receipt-backed completion and credit its CAL
5. Create or resume one exact CAL stake
6. Finalize the bound Settlement Week
7. Unstake the exact remaining LP position
8. Harvest DUNG rewards if still unclaimed

Fresh vaults use an admin-only devnet helper to rewind the open Settlement
Week before any live activity begins. This keeps Gate 1 deterministic on the
fresh lane without weakening runtime settlement rules. A retry must provide
both the printed vault ID and Settlement Week so the script can reconcile the
same receipts, settlement flow, and stake instead of applying a second run.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.repositories.base import get_supabase_client
from app.services.cal_tribute_policy import (
    calculate_ride_tribute_budget,
    calculate_segment_tss_base_units,
)
from app.services.ride_chain_accounts import (
    RideAttestationAccount,
    decode_cal_mint_receipt,
    decode_climb_completion_receipt,
    decode_ride_attestation,
    read_finalized_chain_snapshot,
    validate_cal_mint_receipt,
    validate_climb_completion_receipt,
    validate_ride_attestation,
)
from app.services.settlement_transport import SettlementTransportManager
from app.services.solana_submit import submit_and_confirm
from app.services.vault_activation_policy import REWARD_AUTHORITATIVE_SEED_GENERATION
from app.services.vault_completion_evidence import build_climb_completion_evidence_v2
from app.settlement_clock import SettlementClock
from app.solana_direct import (
    DirectConfig,
    SETTLEMENT_COMPUTE_UNIT_LIMIT,
    VAULT_CAL_TO_DUNG_THRESHOLD,
    _derive_ata,
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_ride_attestation_pda,
    _derive_vault_pda,
    _load_keypair,
    build_settlement_distribution_plan,
    get_program_config_account,
    require_direct_vault_creation_supported,
    get_program_settlement_clock,
    get_vault_account,
    get_vault_stake_account,
    make_admin_activate_vault_ix,
    make_admin_replace_vault_leaderboard_ix,
    make_admin_seed_vault_completion_summary_ix,
    make_create_ata_ix,
    send_credit_cal,
    send_distribute_epoch_rewards,
    send_harvest_rewards,
    send_record_climb_completion,
    send_record_ride,
    send_stake_cal_in_vault,
    send_unstake_cal_from_vault,
)
from app.solana_env import (
    DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
    DEFAULT_CAL_MINT_ADDRESS,
    DEFAULT_DUNG_MINT_ADDRESS,
    DEFAULT_SOLANA_RPC_URL,
)

LAMPORT_DECIMALS = 1_000_000_000
MAX_RIDE_AGE_SECONDS = 30 * 24 * 60 * 60
SMOKE_COMPLETION_TIME_S = 2_275
SMOKE_ADMIN_VAULT_CAL_DEPOSIT = 1_000 * LAMPORT_DECIMALS
SMOKE_SEGMENT_NP_MILLIWATTS = 300_000
SMOKE_REWARD_FTP_W = 250
SMOKE_CAL_CREDIT_RIDE_S = 3600
# record_ride admits at most one whole CAL per declared TSS, and at most the
# TSS that intensity factor 40 sustains over the elapsed ride (IF^2 / 36 per
# second, MAX_RIDE_INTENSITY_FACTOR on chain) within the 36-hour ride limit.
SMOKE_RIDE_MAX_INTENSITY_FACTOR = 40
SMOKE_RIDE_MAX_DURATION_S = 36 * 60 * 60
REHEARSAL_TRANSPORT_SCHEMA = "boulderroller_rehearsal_settlement_transport_v1"


def smoke_ride_economics(cal_earned: int, minimum_duration_s: int) -> tuple[int, int]:
    """Return the (total_tss, duration_s) record_ride admits for synthetic CAL."""
    total_tss = cal_earned // LAMPORT_DECIMALS
    per_second = SMOKE_RIDE_MAX_INTENSITY_FACTOR * SMOKE_RIDE_MAX_INTENSITY_FACTOR
    duration_s = max(minimum_duration_s, -(-total_tss * 36 // per_second))
    if duration_s > SMOKE_RIDE_MAX_DURATION_S:
        raise RuntimeError(
            f"synthetic CAL {cal_earned} exceeds what one admissible ride can carry"
        )
    return total_tss, duration_s


def require_smoke_ride_shape(
    decoded_attestation: RideAttestationAccount,
    *,
    attestation: Pubkey,
    cal_earned: int,
    minimum_duration_s: int,
) -> None:
    """Accept a resumed synthetic ride only in a shape this script records.

    Attestations recorded before the on-chain ride bound carry 0 TSS over the
    minimum duration; credit_cal still pays them exactly.
    """
    completed_at = decoded_attestation.completed_at
    total_tss, duration_s = smoke_ride_economics(cal_earned, minimum_duration_s)
    accepted = {
        (max(completed_at - duration_s, 0), total_tss),
        (max(completed_at - minimum_duration_s, 0), 0),
    }
    if (decoded_attestation.started_at, decoded_attestation.total_tss) not in accepted:
        raise RuntimeError(
            f"RideAttestation {attestation} has a foreign deterministic duration"
        )


@dataclass(frozen=True)
class SmokeSettlementPlan:
    stage: str
    completed_at: int
    expected_pending_rewards: int
    expected_cal_remainder: int


def load_keypair(path_str: str) -> Keypair:
    return _load_keypair(path_str)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test the fresh devnet economics lane")
    parser.add_argument(
        "--backend-authority-keypair",
        default=os.getenv(
            "BACKEND_AUTHORITY_KEYPAIR",
            os.getenv(
                "SOLANA_BACKEND_AUTHORITY_PATH",
                str(Path.home() / ".config/solana/boulderroller-backend-authority.json"),
            ),
        ),
        help="Backend authority keypair path",
    )
    parser.add_argument(
        "--fee-payer-keypair",
        default=os.getenv(
            "FEE_PAYER_KEYPAIR",
            os.getenv(
                "SOLANA_PAYER_PATH",
                str(Path.home() / ".config/solana/boulderroller-fee-payer.json"),
            ),
        ),
        help="General fee payer / POL owner keypair path",
    )
    parser.add_argument(
        "--staker-keypair",
        default=os.getenv("USER_KEYPAIR", str(Path.home() / ".config/solana/id.json")),
        help="Staker keypair path",
    )
    parser.add_argument(
        "--user-cal",
        type=int,
        default=250_000 * LAMPORT_DECIMALS,
        help="CAL base units to mint to the staker before staking",
    )
    parser.add_argument(
        "--stake-cal",
        type=int,
        default=100_000 * LAMPORT_DECIMALS,
        help="CAL base units to stake into the vault",
    )
    parser.add_argument(
        "--vault-alloc-cal",
        type=int,
        default=1_000_000 * LAMPORT_DECIMALS,
        help="CAL base units earned and tributed through a receipt-backed completion",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=10,
        help="Seconds to wait between distribution and cleanup",
    )
    parser.add_argument(
        "--existing-vault-id",
        type=int,
        default=None,
        help="Resume an existing smoke vault; requires --settlement-week",
    )
    parser.add_argument(
        "--settlement-week",
        type=int,
        default=None,
        help="Exact smoke Settlement Week to resume with --existing-vault-id",
    )
    parser.add_argument(
        "--rpc-url",
        default=DEFAULT_SOLANA_RPC_URL,
        help="RPC URL for the fresh lane",
    )
    parser.add_argument(
        "--program-id",
        default=DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
        help="Fresh-lane Boulder Rollers program ID",
    )
    parser.add_argument(
        "--cal-mint",
        default=DEFAULT_CAL_MINT_ADDRESS,
        help="Fresh-lane CAL mint address",
    )
    parser.add_argument(
        "--dung-mint",
        default=DEFAULT_DUNG_MINT_ADDRESS,
        help="Fresh-lane DUNG mint address",
    )
    return parser.parse_args()


def create_test_signature(label: str) -> str:
    gradient_hash = hashlib.sha256(label.encode("utf-8")).digest()
    vert_m = struct.pack(">f", 612.4)
    avg_gradient = struct.pack(">f", 7.92)
    distance_m = struct.pack(">f", 7740.0)
    duration_s = struct.pack(">I", 2275)
    checksum = hashlib.md5(
        gradient_hash + vert_m + avg_gradient + distance_m + duration_s
    ).digest()
    return (gradient_hash + vert_m + avg_gradient + distance_m + duration_s + checksum).hex()


async def ensure_token_ata(
    rpc_url: str,
    payer: Keypair,
    owner: Pubkey,
    mint: Pubkey,
    tx_type: str,
    reference_id: str,
) -> Pubkey:
    ata = _derive_ata(owner, mint)
    async with AsyncClient(rpc_url, commitment=Confirmed) as client:
        info = await client.get_account_info(ata)

    if info.value is not None:
        return ata

    result = await submit_and_confirm(
        instructions=[make_create_ata_ix(payer=payer.pubkey(), owner=owner, mint=mint)],
        signers=[payer],
        fee_payer=payer.pubkey(),
        tx_type=tx_type,
        reference_type="wallet",
        reference_id=reference_id,
        wallet=str(owner),
        rpc_url=rpc_url,
    )
    if result.failed:
        raise RuntimeError(f"Failed to create ATA for {owner}: {result.error}")
    return ata


async def read_canonical_settlement_accounts(
    config: DirectConfig,
) -> tuple[Pubkey, Pubkey]:
    program_config = await get_program_config_account(config)
    if program_config is None:
        raise RuntimeError("ProgramConfig is unavailable; settlement accounts are unknown")

    try:
        pol_account = Pubkey.from_string(str(program_config["pol_token_account"]))
        treasury_account = Pubkey.from_string(
            str(program_config["treasury_token_account"])
        )
    except (KeyError, ValueError) as exc:
        raise RuntimeError("ProgramConfig settlement accounts are malformed") from exc

    if pol_account == Pubkey.default() or treasury_account == Pubkey.default():
        raise RuntimeError("ProgramConfig settlement accounts are not configured")
    return pol_account, treasury_account


async def wait_for_smoke_time(config: DirectConfig, timestamp: int) -> None:
    """Wait on finalized chain time; a devnet Settlement Week is not accelerated."""
    from app.services.settlement_chain import SettlementChain
    chain = SettlementChain(config)
    while True:
        now = await chain.read_chain_time()
        if now >= timestamp:
            return
        print(f"waiting for chain time {timestamp}: {timestamp - now}s remaining", flush=True)
        await asyncio.sleep(min(60, timestamp - now))


async def wait_for_smoke_finalization(config: DirectConfig, settlement_week: int) -> None:
    clock = await get_program_settlement_clock(config)
    await wait_for_smoke_time(config, clock.week_finalization_time(settlement_week))


async def wait_for_smoke_open_week(*, config: DirectConfig, vault_id: int, settlement_week: int, advance_week=None) -> None:
    """Wait for the configured ordinary crank; never borrow ambient signing authority."""
    while True:
        vault = await read_vault_state(config, vault_id)
        open_week = int(vault["open_settlement_week"])
        if open_week >= settlement_week:
            if open_week > settlement_week:
                raise RuntimeError("smoke target week already advanced; reconcile existing receipts before resuming")
            clock = await get_program_settlement_clock(config)
            await wait_for_smoke_time(config, clock.week_start(settlement_week) + 86_400)
            return
        await wait_for_smoke_finalization(config, open_week)
        if advance_week is not None:
            await advance_week(vault_id, open_week)
        else:
            print(f"waiting for the ordinary crank on {config.program_id}: Vault {vault_id}, open week {open_week}", flush=True)
            await asyncio.sleep(60)


async def prepare_smoke_settlement_transport(
    *,
    config: DirectConfig,
    vault_id: int,
    settlement_week: int,
    database: object | None = None,
    on_plan=None,
) -> dict[str, object]:
    distribution = await build_settlement_distribution_plan(
        config=config,
        vault_id=vault_id,
        settlement_week=settlement_week,
    )
    manager = SettlementTransportManager(
        db=database if database is not None else get_supabase_client(),
        config=config,
    )
    return await manager.prepare(
        vault_id=vault_id,
        settlement_week=settlement_week,
        distribution=distribution,
        compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
        on_plan=on_plan,
    )


def _exact_u64_text(value: object, field: str) -> int:
    text = str(value)
    if not text.isascii() or not text.isdigit():
        raise RuntimeError(f"{field} must be a canonical u64 decimal string")
    parsed = int(text)
    if parsed > 18_446_744_073_709_551_615:
        raise RuntimeError(f"{field} is outside the u64 range")
    return parsed


def _atomic_write_json(path: Path, payload: dict) -> None:
    if not path.is_absolute():
        raise RuntimeError("rehearsal state paths must be absolute")
    if not path.parent.is_dir():
        raise RuntimeError(f"rehearsal state parent directory does not exist: {path.parent}")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@contextlib.contextmanager
def _exclusive_json_lock(path: Path):
    """Serialize cross-process JSON authorities without locking the artifact."""
    lock_path = path.parent / f".{path.name}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError(
                    f"another rehearsal process is using {path}"
                ) from exc
            raise
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class _LocalRpcResponse:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _LocalRpcQuery:
    def __init__(
        self,
        store: "RehearsalSettlementTransportStore",
        name: str,
        params: dict,
    ) -> None:
        self.store = store
        self.name = name
        self.params = params

    def execute(self) -> _LocalRpcResponse:
        return self.store._execute(self.name, self.params)


class RehearsalSettlementTransportStore:
    """Atomic JSON adapter for the production manager's three durable RPCs."""

    def __init__(self, *, path: Path, program_id: Pubkey, authority: Pubkey) -> None:
        if not path.is_absolute():
            raise RuntimeError("rehearsal state paths must be absolute")
        self.path = path.resolve()
        self.program_id = str(program_id)
        self.authority = str(authority)
        self._lock = threading.Lock()
        self._run_lock_descriptor: int | None = None
        with self._lock:
            with _exclusive_json_lock(self.path):
                if self.path.exists():
                    state = self._read()
                    self._validate_state(state)
                    _atomic_write_json(self.path, state)
                else:
                    _atomic_write_json(self.path, self._new_state())

    def claim_run_lock(self) -> None:
        if self._run_lock_descriptor is not None:
            return
        lock_path = self.path.parent / f".{self.path.name}.lock"
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RuntimeError(
                    f"another rehearsal process is using {self.path}"
                ) from exc
            raise
        self._run_lock_descriptor = descriptor

    def release_run_lock(self) -> None:
        descriptor = self._run_lock_descriptor
        if descriptor is None:
            return
        self._run_lock_descriptor = None
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    @contextlib.contextmanager
    def _write_lock(self):
        if self._run_lock_descriptor is not None:
            yield
            return
        with _exclusive_json_lock(self.path):
            yield

    def _new_state(self) -> dict:
        return {
            "schema": REHEARSAL_TRANSPORT_SCHEMA,
            "program_id": self.program_id,
            "authority": self.authority,
            "generations": [],
        }

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"rehearsal transport state is unreadable: {self.path}"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError("rehearsal transport state must be a JSON object")
        return value

    def _validate_state(self, state: dict) -> None:
        if state.get("schema") != REHEARSAL_TRANSPORT_SCHEMA:
            raise RuntimeError("rehearsal transport state schema does not match")
        if state.get("program_id") != self.program_id:
            raise RuntimeError("rehearsal transport state program_id does not match")
        if state.get("authority") != self.authority:
            raise RuntimeError("rehearsal transport state authority does not match")
        generations = state.get("generations")
        if not isinstance(generations, list):
            raise RuntimeError("rehearsal transport generations must be a list")
        ids: set[str] = set()
        live: set[tuple[str, str]] = set()
        for row in generations:
            if not isinstance(row, dict) or not str(row.get("id") or ""):
                raise RuntimeError("rehearsal transport generation is malformed")
            if row["id"] in ids:
                raise RuntimeError("rehearsal transport generation id is duplicated")
            ids.add(row["id"])
            if row.get("program_id") != self.program_id:
                raise RuntimeError("rehearsal transport generation program changed")
            if row.get("authority") != self.authority:
                raise RuntimeError("rehearsal transport generation authority changed")
            _exact_u64_text(row.get("vault_id"), "vault_id")
            _exact_u64_text(row.get("recent_slot"), "recent_slot")
            generation = row.get("generation")
            if isinstance(generation, bool):
                raise RuntimeError("rehearsal transport generation is invalid")
            generation = _exact_u64_text(generation, "generation")
            if generation <= 0:
                raise RuntimeError("rehearsal transport generation must be positive")
            try:
                Pubkey.from_string(str(row.get("lookup_table_address") or ""))
            except ValueError as exc:
                raise RuntimeError(
                    "rehearsal transport lookup_table_address is invalid"
                ) from exc
            if row.get("status") not in {"planned", "active", "retired"}:
                raise RuntimeError("rehearsal transport generation status is invalid")
            if row["status"] == "active":
                _exact_u64_text(row.get("last_extended_slot"), "last_extended_slot")
                address_count = row.get("address_count")
                if isinstance(address_count, bool) or not isinstance(address_count, int):
                    raise RuntimeError(
                        "rehearsal transport active address_count is invalid"
                    )
                if not 0 <= address_count <= 256:
                    raise RuntimeError(
                        "rehearsal transport active address_count is invalid"
                    )
                manifest = str(row.get("manifest_sha256") or "")
                if len(manifest) != 64 or any(
                    character not in "0123456789abcdef" for character in manifest
                ):
                    raise RuntimeError(
                        "rehearsal transport active manifest_sha256 is invalid"
                    )
            if row["status"] in {"planned", "active"}:
                key = (row["program_id"], str(row["vault_id"]))
                if key in live:
                    raise RuntimeError("rehearsal transport has duplicate live generations")
                live.add(key)

    def rpc(self, name: str, params: dict) -> _LocalRpcQuery:
        return _LocalRpcQuery(self, name, dict(params))

    @staticmethod
    def _result(row: dict) -> _LocalRpcResponse:
        return _LocalRpcResponse([dict(row)])

    def _execute(self, name: str, params: dict) -> _LocalRpcResponse:
        with self._lock:
            with self._write_lock():
                state = self._read()
                self._validate_state(state)
                if name == "br_get_or_plan_settlement_lookup_table":
                    result = self._get_or_plan(state, params)
                elif name == "br_rotate_settlement_lookup_table":
                    result = self._rotate(state, params)
                elif name == "br_record_settlement_lookup_table_ready":
                    result = self._record_ready(state, params)
                else:
                    raise RuntimeError(f"unsupported rehearsal transport RPC {name}")
                _atomic_write_json(self.path, state)
                return self._result(result)

    def _get_or_plan(self, state: dict, params: dict) -> dict:
        vault_id = _exact_u64_text(params.get("p_vault_id"), "vault_id")
        recent_slot = _exact_u64_text(params.get("p_recent_slot"), "recent_slot")
        if params.get("p_program_id") != self.program_id:
            raise RuntimeError("rehearsal transport RPC program_id does not match")
        if params.get("p_authority") != self.authority:
            raise RuntimeError("rehearsal transport RPC authority does not match")
        lookup = str(params.get("p_lookup_table_address") or "")
        if not lookup:
            raise RuntimeError("rehearsal lookup-table address is required")
        matching = [
            row
            for row in state["generations"]
            if row["vault_id"] == str(vault_id)
            and row["status"] in {"planned", "active"}
        ]
        if matching:
            matching.sort(
                key=lambda row: (
                    0 if row["status"] == "active" else 1,
                    -int(row["generation"]),
                )
            )
            return matching[0]
        prior = [
            int(row["generation"])
            for row in state["generations"]
            if row["vault_id"] == str(vault_id)
        ]
        row = {
            "id": str(uuid.uuid4()),
            "vault_id": str(vault_id),
            "program_id": self.program_id,
            "generation": max(prior, default=0) + 1,
            "lookup_table_address": lookup,
            "authority": self.authority,
            "recent_slot": str(recent_slot),
            "status": "planned",
            "create_tx_signature": None,
            "last_tx_signature": None,
            "last_extended_slot": None,
            "address_count": 0,
            "manifest_sha256": None,
        }
        state["generations"].append(row)
        return row

    def _rotate(self, state: dict, params: dict) -> dict:
        current_id = str(params.get("p_current_id") or "")
        current = next(
            (row for row in state["generations"] if row["id"] == current_id),
            None,
        )
        if current is None or current["status"] not in {"planned", "active"}:
            raise RuntimeError("rehearsal transport rotation target is not live")
        current["status"] = "retired"
        recent_slot = _exact_u64_text(params.get("p_recent_slot"), "recent_slot")
        lookup = str(params.get("p_lookup_table_address") or "")
        if not lookup:
            raise RuntimeError("rehearsal lookup-table address is required")
        row = {
            **{
                key: value
                for key, value in current.items()
                if key not in {
                    "id",
                    "generation",
                    "lookup_table_address",
                    "recent_slot",
                    "status",
                    "create_tx_signature",
                    "last_tx_signature",
                    "last_extended_slot",
                    "address_count",
                    "manifest_sha256",
                }
            },
            "id": str(uuid.uuid4()),
            "generation": int(current["generation"]) + 1,
            "lookup_table_address": lookup,
            "recent_slot": str(recent_slot),
            "status": "planned",
            "create_tx_signature": None,
            "last_tx_signature": None,
            "last_extended_slot": None,
            "address_count": 0,
            "manifest_sha256": None,
        }
        state["generations"].append(row)
        return row

    def _record_ready(self, state: dict, params: dict) -> dict:
        generation_id = str(params.get("p_generation_id") or "")
        row = next(
            (item for item in state["generations"] if item["id"] == generation_id),
            None,
        )
        if row is None or row["status"] not in {"planned", "active"}:
            raise RuntimeError("rehearsal transport ready target is not live")
        last_slot = _exact_u64_text(
            params.get("p_last_extended_slot"),
            "last_extended_slot",
        )
        count = int(params.get("p_address_count"))
        manifest = str(params.get("p_manifest_sha256") or "")
        if not 0 <= count <= 256:
            raise RuntimeError("rehearsal transport address_count is invalid")
        if len(manifest) != 64 or any(ch not in "0123456789abcdef" for ch in manifest):
            raise RuntimeError("rehearsal transport manifest_sha256 is invalid")
        row.update(
            {
                "status": "active",
                "create_tx_signature": params.get("p_create_tx_signature"),
                "last_tx_signature": params.get("p_last_tx_signature"),
                "last_extended_slot": str(last_slot),
                "address_count": count,
                "manifest_sha256": manifest,
            }
        )
        return row


async def preflight_smoke_settlement_transport_prerequisites(
    *,
    state_path: Path,
    program_id: Pubkey,
    authority: Pubkey,
) -> RehearsalSettlementTransportStore:
    """Create or validate the isolated durable ALT lifecycle before mutation."""
    try:
        store = RehearsalSettlementTransportStore(
            path=state_path,
            program_id=program_id,
            authority=authority,
        )
        store.claim_run_lock()
        return store
    except Exception as exc:
        raise RuntimeError(
            "rehearsal settlement transport is not ready before chain mutation; "
            "supply --rehearsal-transport-state with an absolute JSON path in an "
            "existing writable directory (production Supabase is never used)"
        ) from exc


async def token_balance(rpc_url: str, token_account: Pubkey) -> int:
    async with AsyncClient(rpc_url, commitment=Confirmed) as client:
        resp = await client.get_token_account_balance(token_account)
    value = resp.value
    if value is None:
        return 0
    return int(value.amount)


async def read_vault_state(config: DirectConfig, vault_id: int) -> dict:
    vault = await get_vault_account(config, vault_id, commitment=Finalized)
    if vault is None:
        raise RuntimeError(f"Vault {vault_id} not found on-chain")
    return vault


def validate_smoke_resume_args(
    *,
    existing_vault_id: int | None,
    settlement_week: int | None,
) -> None:
    if existing_vault_id is not None and settlement_week is None:
        raise RuntimeError(
            "--settlement-week is required with --existing-vault-id so retries use "
            "the exact credited settlement flow"
        )
    if existing_vault_id is None and settlement_week is not None:
        raise RuntimeError(
            "--existing-vault-id is required when --settlement-week is provided"
        )
    if existing_vault_id is not None and existing_vault_id < 0:
        raise RuntimeError("--existing-vault-id must be non-negative")
    if settlement_week is not None and settlement_week < 0:
        raise RuntimeError("--settlement-week must be non-negative")


def inspect_smoke_settlement_stage(
    vault_state: dict,
    settlement_clock: SettlementClock,
    settlement_week: int,
    current_time: int,
    cal_amount: int,
    *,
    initial_cal_tribute: int = 0,
    initial_carries: dict[str, int] | None = None,
) -> SmokeSettlementPlan:
    if cal_amount <= 0:
        raise RuntimeError("smoke CAL tribute must be positive")
    if initial_cal_tribute < 0:
        raise RuntimeError("initial smoke CAL tribute must be non-negative")

    completed_at = settlement_clock.week_start(settlement_week) + 86_400
    total_tribute = initial_cal_tribute + cal_amount
    expected_pending_rewards = total_tribute // VAULT_CAL_TO_DUNG_THRESHOLD
    expected_cal_remainder = total_tribute % VAULT_CAL_TO_DUNG_THRESHOLD
    plan = SmokeSettlementPlan(
        stage="",
        completed_at=completed_at,
        expected_pending_rewards=expected_pending_rewards,
        expected_cal_remainder=expected_cal_remainder,
    )

    open_week = int(vault_state.get("open_settlement_week", -1) or 0)
    last_distribution = int(vault_state.get("last_distribution_epoch", -1) or 0)
    prior_distribution = settlement_week - 1 if settlement_week > 0 else 0
    if open_week == settlement_week + 1 and last_distribution == settlement_week:
        return SmokeSettlementPlan(**{**plan.__dict__, "stage": "distributed"})
    if open_week != settlement_week or last_distribution != prior_distribution:
        raise RuntimeError(
            "unexpected settlement flow identity: "
            f"target={settlement_week}, open={open_week}, "
            f"last_distribution={last_distribution}"
        )

    prohibited_fields = (
        "pending_rewards_next_week",
        "cal_tribute_accumulated_next",
        "carry_record_royalty",
        "carry_stakers",
        "carry_local_legend",
        "carry_pol",
        "carry_treasury",
    )
    nonzero = {
        field: int(vault_state.get(field, 0) or 0)
        for field in prohibited_fields
        if int(vault_state.get(field, 0) or 0) != int((initial_carries or {}).get(field, 0))
    }
    if nonzero:
        detail = ", ".join(f"{field}={amount}" for field, amount in nonzero.items())
        raise RuntimeError(
            f"unexpected settlement flow state for deterministic smoke: {detail}"
        )

    pending_rewards = int(vault_state.get("pending_rewards", 0) or 0)
    cal_remainder = int(vault_state.get("cal_tribute_accumulated", 0) or 0)
    if pending_rewards == 0 and cal_remainder == initial_cal_tribute:
        stage = "pristine"
    elif (
        pending_rewards == expected_pending_rewards
        and cal_remainder == expected_cal_remainder
    ):
        stage = "completed"
    else:
        raise RuntimeError(
            "unexpected settlement flow values: "
            f"pending_rewards={pending_rewards}, "
            f"cal_tribute_accumulated={cal_remainder}, "
            f"expected=({expected_pending_rewards}, {expected_cal_remainder})"
        )
    return SmokeSettlementPlan(**{**plan.__dict__, "stage": stage})


def validate_smoke_admission_window(
    *,
    completed_at: int,
    current_time: int,
    settled_at: int | None,
) -> None:
    admission_clock = current_time if settled_at is None else settled_at
    if settled_at is not None and settled_at <= 0:
        raise RuntimeError("attestation admission clock is invalid")
    if completed_at < admission_clock - MAX_RIDE_AGE_SECONDS:
        source = (
            "30-day ride admission"
            if settled_at is None
            else "attestation admission clock"
        )
        raise RuntimeError(
            f"smoke completion is outside the {source} by "
            f"{admission_clock - MAX_RIDE_AGE_SECONDS - completed_at} seconds"
        )


def require_smoke_flow_consistency(
    settlement_stage: str,
    receipt_stage: str,
) -> None:
    allowed = {
        "pristine": {"absent", "attested"},
        "seeded": {"absent", "attested"},
        "completed": {"completion_recorded", "settled"},
        "distributed": {"settled"},
    }
    if receipt_stage not in allowed.get(settlement_stage, set()):
        raise RuntimeError(
            "settlement aggregate does not match deterministic receipt evidence: "
            f"settlement={settlement_stage}, receipts={receipt_stage}"
        )


def inspect_smoke_stake_stage(
    vault_state: dict,
    stake_state: dict | None,
    stake_cal: int,
    *,
    distributed: bool,
) -> str:
    if stake_cal <= 0:
        raise RuntimeError("smoke stake amount must be positive")

    vault_total = int(vault_state.get("total_cal_staked", 0) or 0)
    staker_count = int(vault_state.get("staker_count", 0) or 0)
    if stake_state is None:
        if distributed:
            raise RuntimeError(
                "distributed smoke is missing its persistent stake account"
            )
        if vault_total == 0 and staker_count == 0:
            return "pristine"
        raise RuntimeError(
            "unexpected stake state: smoke rider has no position but vault reports "
            f"total_cal_staked={vault_total}, staker_count={staker_count}"
        )

    cal_staked = int(stake_state.get("cal_staked", 0) or 0)
    lp_tokens = int(stake_state.get("lp_tokens", 0) or 0)
    rewards_earned = int(stake_state.get("rewards_earned", 0) or 0)
    if cal_staked == stake_cal and lp_tokens == stake_cal:
        if vault_total != stake_cal or staker_count != 1:
            raise RuntimeError(
                "unexpected stake state: exact rider position does not match vault totals"
            )
        if not distributed and rewards_earned != 0:
            raise RuntimeError(
                "unexpected stake state: rewards exist before smoke distribution"
            )
        if distributed and rewards_earned <= 0:
            raise RuntimeError(
                "distributed smoke has a zero staker reward before withdrawal"
            )
        return "staked"

    if distributed and cal_staked == 0 and lp_tokens == 0:
        effective_lp = int(stake_state.get("effective_lp_tokens", 0) or 0)
        pending_lp = int(stake_state.get("pending_lp_tokens", 0) or 0)
        if effective_lp not in (0, stake_cal) or pending_lp not in (0, stake_cal):
            raise RuntimeError("unexpected stake state: foreign settlement snapshot")
        expected_inventory = 1 if effective_lp > 0 or pending_lp > 0 else 0
        if vault_total == 0 and staker_count == expected_inventory:
            return "withdrawn" if rewards_earned > 0 else "complete"

    raise RuntimeError(
        "unexpected stake state: "
        f"cal_staked={cal_staked}, lp_tokens={lp_tokens}, "
        f"vault_total={vault_total}, staker_count={staker_count}"
    )


def smoke_completion_identity(
    staker: Pubkey,
    vault_id: int,
    cal_amount: int,
    completion_time_s: int,
    completed_at: int,
) -> tuple[str, bytes]:
    activity_id = (
        f"smoke-devnet:receipt-backed:{staker}:{vault_id}:{completed_at}:"
        f"{completion_time_s}:{cal_amount}"
    )
    return activity_id, hashlib.sha256(activity_id.encode("utf-8")).digest()


def measured_smoke_cal_tribute(cal_amount: int, completion_time_s: int) -> int:
    """Return the explicit measured-TSS contribution used by devnet smoke rides."""

    segment_tribute = calculate_segment_tss_base_units(
        segment_np_duration_s=completion_time_s,
        segment_np_milliwatts=SMOKE_SEGMENT_NP_MILLIWATTS,
        reward_ftp_w=SMOKE_REWARD_FTP_W,
    )
    return calculate_ride_tribute_budget(cal_amount, [segment_tribute])


async def read_smoke_receipt_stage(
    *,
    config: DirectConfig,
    staker: Pubkey,
    vault_id: int,
    vault_signature_hash_hex: str,
    cal_amount: int,
    completion_time_s: int,
    completed_at: int,
    current_time: int,
) -> str:
    cal_tribute = measured_smoke_cal_tribute(cal_amount, completion_time_s)
    if cal_tribute <= 0:
        raise RuntimeError("smoke ride CAL is too small to produce tribute")
    _, ride_hash = smoke_completion_identity(
        staker,
        vault_id,
        cal_amount,
        completion_time_s,
        completed_at,
    )
    attestation, attestation_bump = _derive_ride_attestation_pda(
        staker, ride_hash, config.program_id
    )
    vault, _ = _derive_vault_pda(vault_id, config.program_id)
    completion_evidence_hash = build_climb_completion_evidence_v2(
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
    )
    cal_receipt, cal_bump = _derive_cal_mint_receipt_pda(
        attestation, staker, config.program_id
    )
    completion_receipt, completion_bump = _derive_climb_completion_receipt_pda(
        attestation, vault, config.program_id
    )
    snapshot = await read_finalized_chain_snapshot(
        config.rpc_url,
        (attestation, completion_receipt, cal_receipt),
    )
    if snapshot.slot <= 0 or len(snapshot.accounts) != 3:
        raise RuntimeError("finalized smoke receipt snapshot is incomplete")
    attestation_raw, completion_raw, cal_raw = snapshot.accounts

    if attestation_raw is None:
        if completion_raw is not None or cal_raw is not None:
            raise RuntimeError("smoke receipt evidence is not a valid prefix")
        validate_smoke_admission_window(
            completed_at=completed_at,
            current_time=current_time,
            settled_at=None,
        )
        return "absent"

    for name, raw in (
        ("RideAttestation", attestation_raw),
        ("ClimbCompletionReceipt", completion_raw),
        ("CalMintReceipt", cal_raw),
    ):
        if raw is not None and raw.owner != config.program_id:
            raise RuntimeError(f"{name} is not owned by the configured program")

    decoded_attestation = decode_ride_attestation(attestation_raw.data)
    require_smoke_ride_shape(
        decoded_attestation,
        attestation=attestation,
        cal_earned=cal_amount,
        minimum_duration_s=max(completion_time_s, 1),
    )
    validate_ride_attestation(
        decoded_attestation,
        rider=staker,
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=1,
        source_kind=3,
        completed_at=completed_at,
        started_at=decoded_attestation.started_at,
        total_tss=decoded_attestation.total_tss,
        total_distance_m=0,
        total_vert_m=0,
        cal_earned=cal_amount,
        climbs_crossed=1,
        bump=attestation_bump,
    )
    validate_smoke_admission_window(
        completed_at=completed_at,
        current_time=current_time,
        settled_at=decoded_attestation.settled_at,
    )

    if completion_raw is None:
        if cal_raw is not None:
            raise RuntimeError("smoke receipt evidence is not a valid prefix")
        return "attested"

    validate_climb_completion_receipt(
        decode_climb_completion_receipt(completion_raw.data),
        ride_attestation=attestation,
        vault=vault,
        evidence_version=2,
        cal_tribute=cal_tribute,
        completion_evidence_hash=completion_evidence_hash,
        bump=completion_bump,
    )
    if cal_raw is None:
        return "completion_recorded"

    validate_cal_mint_receipt(
        decode_cal_mint_receipt(cal_raw.data),
        ride_attestation=attestation,
        rider=staker,
        amount=cal_amount,
        bump=cal_bump,
    )
    return "settled"


async def credit_user_cal(
    config: DirectConfig,
    staker: Pubkey,
    total_cal_amount: int,
    activity_id: str | None = None,
    completed_at: int | None = None,
) -> str:
    completed_at = int(time.time()) if completed_at is None else int(completed_at)
    total_tss, duration_s = smoke_ride_economics(total_cal_amount, SMOKE_CAL_CREDIT_RIDE_S)
    started_at = completed_at - duration_s
    if activity_id is None:
        activity_id = (
            f"smoke-devnet-economics:cal-credit:{staker}:"
            f"{total_cal_amount}:{completed_at}"
        )
    ride_hash = hashlib.sha256(activity_id.encode("utf-8")).digest()

    record_sig = await send_record_ride(
        config=config,
        rider_wallet=str(staker),
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=1,
        source_kind=3,
        completed_at=completed_at,
        started_at=started_at,
        total_tss=total_tss,
        total_distance_m=0,
        total_vert_m=0,
        cal_earned=total_cal_amount,
        climbs_crossed=0,
    )
    credit_sig = await send_credit_cal(
        config=config,
        rider_wallet=str(staker),
        ride_hash=ride_hash,
        amount=total_cal_amount,
    )
    print(f"user ride attested: {record_sig}")
    print(f"user CAL credited:  {credit_sig}")
    return credit_sig


async def ensure_user_cal_credit(
    config: DirectConfig,
    staker: Pubkey,
    total_cal_amount: int,
    activity_id: str,
    completed_at: int,
) -> str:
    """Create or resume one exact record_ride -> credit_cal prefix.

    A retry with a finalized RideAttestation credits only the missing receipt;
    a finalized CalMintReceipt is validated and reused without another write.
    """
    if total_cal_amount <= 0:
        raise RuntimeError("deterministic CAL credit amount must be positive")
    ride_hash = hashlib.sha256(activity_id.encode("utf-8")).digest()
    attestation, attestation_bump = _derive_ride_attestation_pda(
        staker,
        ride_hash,
        config.program_id,
    )
    receipt, receipt_bump = _derive_cal_mint_receipt_pda(
        attestation,
        staker,
        config.program_id,
    )
    snapshot = await read_finalized_chain_snapshot(
        config.rpc_url,
        (attestation, receipt),
    )
    if snapshot.slot <= 0 or len(snapshot.accounts) != 2:
        raise RuntimeError(
            "deterministic CAL recovery snapshot is incomplete for "
            f"RideAttestation {attestation} and CalMintReceipt {receipt}"
        )
    attestation_raw, receipt_raw = snapshot.accounts
    if attestation_raw is None:
        if receipt_raw is not None:
            raise RuntimeError(
                "deterministic CAL recovery prefix is invalid: missing "
                f"RideAttestation {attestation} for CalMintReceipt {receipt}"
            )
        return await credit_user_cal(
            config=config,
            staker=staker,
            total_cal_amount=total_cal_amount,
            activity_id=activity_id,
            completed_at=completed_at,
        )

    if attestation_raw.owner != config.program_id:
        raise RuntimeError(
            f"RideAttestation {attestation} is not owned by the configured program"
        )
    decoded_attestation = decode_ride_attestation(attestation_raw.data)
    require_smoke_ride_shape(
        decoded_attestation,
        attestation=attestation,
        cal_earned=total_cal_amount,
        minimum_duration_s=SMOKE_CAL_CREDIT_RIDE_S,
    )
    validate_ride_attestation(
        decoded_attestation,
        rider=staker,
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=1,
        source_kind=3,
        completed_at=decoded_attestation.completed_at,
        started_at=decoded_attestation.started_at,
        total_tss=decoded_attestation.total_tss,
        total_distance_m=0,
        total_vert_m=0,
        cal_earned=total_cal_amount,
        climbs_crossed=0,
        bump=attestation_bump,
    )

    if receipt_raw is not None:
        if receipt_raw.owner != config.program_id:
            raise RuntimeError(
                f"CalMintReceipt {receipt} is not owned by the configured program"
            )
        validate_cal_mint_receipt(
            decode_cal_mint_receipt(receipt_raw.data),
            ride_attestation=attestation,
            rider=staker,
            amount=total_cal_amount,
            bump=receipt_bump,
        )
        return f"existing CalMintReceipt {receipt}"

    credit_sig = await send_credit_cal(
        config=config,
        rider_wallet=str(staker),
        ride_hash=ride_hash,
        amount=total_cal_amount,
    )
    print(f"user CAL credited:  {credit_sig} (resumed {attestation})")
    return credit_sig


async def record_receipt_backed_tribute(
    config: DirectConfig,
    staker: Pubkey,
    vault_id: int,
    vault_signature_hash_hex: str,
    cal_amount: int,
    completion_time_s: int,
    completed_at: int,
    receipt_stage: str = "absent",
) -> str:
    if receipt_stage not in {"absent", "attested", "completion_recorded"}:
        raise RuntimeError(f"cannot resume mutation from receipt stage {receipt_stage!r}")
    cal_tribute = measured_smoke_cal_tribute(cal_amount, completion_time_s)
    if cal_tribute <= 0:
        raise RuntimeError("smoke ride CAL is too small to produce tribute")

    _, ride_hash = smoke_completion_identity(
        staker,
        vault_id,
        cal_amount,
        completion_time_s,
        completed_at,
    )
    attestation, _ = _derive_ride_attestation_pda(
        staker, ride_hash, config.program_id
    )
    vault, _ = _derive_vault_pda(vault_id, config.program_id)
    completion_evidence_hash = build_climb_completion_evidence_v2(
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
    )

    if receipt_stage == "absent":
        total_tss, duration_s = smoke_ride_economics(
            cal_amount, max(completion_time_s, 1)
        )
        ride_sig = await send_record_ride(
            config=config,
            rider_wallet=str(staker),
            ride_hash=ride_hash,
            attestation_commitment=ride_hash,
            parser_version=1,
            source_kind=3,
            completed_at=completed_at,
            started_at=max(completed_at - duration_s, 0),
            total_tss=total_tss,
            total_distance_m=0,
            total_vert_m=0,
            cal_earned=cal_amount,
            climbs_crossed=1,
        )
        print(f"ride attested:      {ride_sig}")

    completion_sig: str | None = None
    if receipt_stage in {"absent", "attested"}:
        completion_sig = await send_record_climb_completion(
            config=config,
            rider_wallet=str(staker),
            ride_hash=ride_hash,
            vault_id=vault_id,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
            completion_evidence_version=2,
            completion_evidence_hash=completion_evidence_hash,
        )
        print(
            f"climb completion:   {completion_sig} "
            f"evidence={completion_evidence_hash.hex()[:16]}..."
        )

    credit_sig = await send_credit_cal(
        config=config,
        rider_wallet=str(staker),
        ride_hash=ride_hash,
        amount=cal_amount,
    )
    print(f"ride CAL credited:  {credit_sig}")
    return completion_sig or credit_sig


async def ensure_receipt_backed_smoke_flow(
    *,
    config: DirectConfig,
    settlement_clock: SettlementClock,
    staker: Pubkey,
    vault_id: int,
    settlement_week: int,
    vault_signature_hash_hex: str,
    cal_amount: int,
    completion_time_s: int,
    current_time: int,
    retry_attempts: int = 20,
    retry_delay_s: float = 1.5,
    initial_cal_tribute: int = 0,
) -> SmokeSettlementPlan:
    if retry_attempts <= 0:
        raise RuntimeError("smoke retry attempts must be positive")
    cal_tribute = measured_smoke_cal_tribute(cal_amount, completion_time_s)
    if cal_tribute <= 0:
        raise RuntimeError("smoke ride CAL is too small to produce tribute")

    plan: SmokeSettlementPlan | None = None
    receipt_stage = ""
    initial_carries = None
    for attempt in range(retry_attempts):
        snapshot = await read_vault_state(config, vault_id)
        if initial_carries is None:
            # Earlier ordinary settlements may leave reserved bucket dust. Freeze
            # that liability and require completion to leave it exactly unchanged.
            initial_carries = {field: _exact_u64_text(snapshot.get(field, 0), field)
                               for field in ("carry_record_royalty", "carry_stakers", "carry_local_legend", "carry_pol", "carry_treasury")}
        plan = inspect_smoke_settlement_stage(
            snapshot,
            settlement_clock,
            settlement_week,
            current_time,
            cal_tribute,
            initial_cal_tribute=initial_cal_tribute,
            initial_carries=initial_carries,
        )
        receipt_stage = await read_smoke_receipt_stage(
            config=config,
            staker=staker,
            vault_id=vault_id,
            vault_signature_hash_hex=vault_signature_hash_hex,
            cal_amount=cal_amount,
            completion_time_s=completion_time_s,
            completed_at=plan.completed_at,
            current_time=current_time,
        )
        try:
            require_smoke_flow_consistency(plan.stage, receipt_stage)
            break
        except RuntimeError:
            if attempt + 1 >= retry_attempts:
                raise
            await asyncio.sleep(retry_delay_s)

    if plan is None:
        raise RuntimeError("smoke flow state was not observed")
    receipt_args = {
        "config": config,
        "staker": staker,
        "vault_id": vault_id,
        "vault_signature_hash_hex": vault_signature_hash_hex,
        "cal_amount": cal_amount,
        "completion_time_s": completion_time_s,
        "completed_at": plan.completed_at,
        "current_time": current_time,
    }
    if plan.stage == "distributed":
        return plan
    if plan.stage == "completed" and receipt_stage == "settled":
        return plan

    await record_receipt_backed_tribute(
        config=config,
        staker=staker,
        vault_id=vault_id,
        vault_signature_hash_hex=vault_signature_hash_hex,
        cal_amount=cal_amount,
        completion_time_s=completion_time_s,
        completed_at=plan.completed_at,
        receipt_stage=receipt_stage,
    )

    latest_plan = plan
    for attempt in range(retry_attempts):
        latest_plan = inspect_smoke_settlement_stage(
            await read_vault_state(config, vault_id),
            settlement_clock,
            settlement_week,
            current_time,
            cal_tribute,
            initial_cal_tribute=initial_cal_tribute,
            initial_carries=initial_carries,
        )
        latest_receipt_stage = await read_smoke_receipt_stage(**receipt_args)
        try:
            require_smoke_flow_consistency(
                latest_plan.stage,
                latest_receipt_stage,
            )
        except RuntimeError:
            if attempt + 1 >= retry_attempts:
                raise
            await asyncio.sleep(retry_delay_s)
            continue
        if (
            latest_plan.stage in {"completed", "distributed"}
            and latest_receipt_stage == "settled"
        ):
            return latest_plan
        if attempt + 1 < retry_attempts:
            await asyncio.sleep(retry_delay_s)

    raise RuntimeError(
        "receipt-backed smoke completion did not reach its exact expected state; "
        f"last stage={latest_plan.stage}"
    )


async def seed_and_activate_vault(
    config: DirectConfig,
    vault_id: int,
    best_time_holder: Pubkey,
    best_time_s: int,
) -> tuple[str, str, str]:
    recorded_at = int(time.time())
    authority = config.backend_authority or config.payer
    seed_ix = make_admin_seed_vault_completion_summary_ix(
        authority=authority.pubkey(),
        vault_id=vault_id,
        total_completions=1,
        best_time_s=best_time_s,
        best_time_holder=best_time_holder,
        program_id=config.program_id,
    )
    leaderboard_ix = make_admin_replace_vault_leaderboard_ix(
        authority=authority.pubkey(),
        vault_id=vault_id,
        entries=[(best_time_holder, best_time_s, recorded_at)],
        program_id=config.program_id,
    )
    activate_ix = make_admin_activate_vault_ix(
        authority=authority.pubkey(),
        vault_id=vault_id,
        total_completions=1,
        kom_holder=best_time_holder,
        kom_time_s=best_time_s,
        kom_recorded_at=recorded_at,
        seed_generation=REWARD_AUTHORITATIVE_SEED_GENERATION,
        seed_cutoff_at=recorded_at,
        matched_users=1,
        matched_completions=1,
        evidence_hash=hashlib.sha256(
            f"BR_SMOKE_ACTIVATION_V1:{vault_id}:{best_time_holder}:{best_time_s}:{recorded_at}".encode()
        ).digest(),
        program_id=config.program_id,
    )

    seed_result = await submit_and_confirm(
        instructions=[seed_ix],
        signers=[authority, config.payer] if authority.pubkey() != config.payer.pubkey() else [config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="admin_seed_vault_completion_summary",
        reference_type="vault",
        reference_id=str(vault_id),
        rpc_url=config.rpc_url,
    )
    if seed_result.failed:
        raise RuntimeError(f"seed summary failed: {seed_result.error}")

    leaderboard_result = await submit_and_confirm(
        instructions=[leaderboard_ix],
        signers=[authority, config.payer] if authority.pubkey() != config.payer.pubkey() else [config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="admin_replace_vault_leaderboard",
        reference_type="vault",
        reference_id=str(vault_id),
        rpc_url=config.rpc_url,
    )
    if leaderboard_result.failed:
        raise RuntimeError(f"leaderboard seed failed: {leaderboard_result.error}")

    activate_result = await submit_and_confirm(
        instructions=[activate_ix],
        signers=[authority, config.payer] if authority.pubkey() != config.payer.pubkey() else [config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="admin_activate_vault",
        reference_type="vault",
        reference_id=str(vault_id),
        rpc_url=config.rpc_url,
    )
    if activate_result.failed:
        raise RuntimeError(f"activate failed: {activate_result.error}")

    return seed_result.signature, leaderboard_result.signature, activate_result.signature


async def main() -> None:
    args = parse_args()
    require_direct_vault_creation_supported()
    validate_smoke_resume_args(
        existing_vault_id=args.existing_vault_id,
        settlement_week=args.settlement_week,
    )
    rpc_url = args.rpc_url
    program_id = Pubkey.from_string(args.program_id)
    cal_mint = Pubkey.from_string(args.cal_mint)
    dung_mint = Pubkey.from_string(args.dung_mint)

    backend_authority = load_keypair(args.backend_authority_keypair)
    fee_payer = load_keypair(args.fee_payer_keypair)
    staker = load_keypair(args.staker_keypair)

    admin_config = DirectConfig(
        rpc_url=rpc_url,
        program_id=program_id,
        payer=fee_payer,
        backend_authority=backend_authority,
        cal_mint_address=cal_mint,
        dung_mint_address=dung_mint,
    )
    settlement_clock = await get_program_settlement_clock(admin_config)
    pol_ata, treasury_ata = await read_canonical_settlement_accounts(admin_config)
    print("=== Fresh Devnet Economics Smoke ===")
    print(f"RPC:              {rpc_url}")
    print(f"Program:          {program_id}")
    print(f"Backend authority:{backend_authority.pubkey()}")
    print(f"Fee payer:        {fee_payer.pubkey()}")
    print(f"Staker:           {staker.pubkey()}")
    print(f"CAL mint:         {cal_mint}")
    print(f"DUNG mint:        {dung_mint}")

    now = int(time.time())
    staker_cal_ata = _derive_ata(staker.pubkey(), cal_mint)
    staker_dung_ata = _derive_ata(staker.pubkey(), dung_mint)
    os.environ["PROTOCOL_TREASURY_ACCOUNT"] = str(treasury_ata)

    if args.existing_vault_id is None:
        # Program 0x4E removed admin_create_vault. V4-B creates Vaults only
        # through the wallet-signed prepare/submit reservation flow.
        raise RuntimeError(
            "Fresh smoke vaults need the prepare/submit reservation flow; "
            "create one there and pass --existing-vault-id with --settlement-week"
        )
    vault_id = args.existing_vault_id
    settlement_week = int(args.settlement_week)
    print(f"using existing vault: {vault_id}")

    print(
        "resume identity:    "
        f"--existing-vault-id {vault_id} --settlement-week {settlement_week}"
    )

    vault_before = await read_vault_state(admin_config, vault_id)
    vault_signature_hash_hex = str(vault_before.get("signature_hash_hex") or "")
    if len(vault_signature_hash_hex) != 64:
        raise RuntimeError(
            f"Vault {vault_id} missing canonical signature_hash_hex for evidence hash"
        )
    vault_state = await read_vault_state(admin_config, vault_id)
    stake_state = await get_vault_stake_account(
        admin_config, vault_id, str(staker.pubkey())
    )
    distributed = int(vault_state["open_settlement_week"]) > settlement_week
    stake_stage = inspect_smoke_stake_stage(
        vault_state,
        stake_state,
        args.stake_cal,
        distributed=distributed,
    )

    if stake_stage == "pristine":
        cal_balance = await token_balance(rpc_url, staker_cal_ata)
        if cal_balance < args.stake_cal:
            print(
                f"staker CAL balance {cal_balance} is short; "
                f"crediting deterministic {args.user_cal} CAL top-up"
            )
            await credit_user_cal(
                config=admin_config,
                staker=staker.pubkey(),
                total_cal_amount=args.user_cal,
                activity_id=(
                    f"smoke-devnet-economics:cal-credit:{staker.pubkey()}:"
                    f"{vault_id}:{settlement_week}:{args.user_cal}"
                ),
                completed_at=now,
            )
            cal_balance = await token_balance(rpc_url, staker_cal_ata)
        if cal_balance < args.stake_cal:
            raise RuntimeError(
                f"staker CAL balance {cal_balance} remains below stake {args.stake_cal}"
            )

        stake_sig = await send_stake_cal_in_vault(
            config=admin_config,
            staker_keypair=staker,
            vault_id=vault_id,
            amount=args.stake_cal,
        )
        print(f"staked CAL:         {stake_sig}")
        vault_state = await read_vault_state(admin_config, vault_id)
        stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(staker.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            vault_state,
            stake_state,
            args.stake_cal,
            distributed=False,
        )
    elif stake_stage == "staked":
        print("stake state:        exact smoke position already present")

    if distributed:
        flow_plan = await ensure_receipt_backed_smoke_flow(
            config=admin_config,
            settlement_clock=settlement_clock,
            staker=staker.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=vault_signature_hash_hex,
            cal_amount=args.vault_alloc_cal,
            completion_time_s=SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
            initial_cal_tribute=0,
        )
        print(
            f"completion flow:    {flow_plan.stage} "
            f"pending={flow_plan.expected_pending_rewards} "
            f"remainder={flow_plan.expected_cal_remainder}"
        )

    if not distributed:
        if stake_stage != "staked":
            raise RuntimeError("smoke flow cannot distribute without the exact stake")
        await wait_for_smoke_open_week(config=admin_config, vault_id=vault_id, settlement_week=settlement_week)
        flow_plan = await ensure_receipt_backed_smoke_flow(
            config=admin_config,
            settlement_clock=settlement_clock,
            staker=staker.pubkey(),
            vault_id=vault_id,
            settlement_week=settlement_week,
            vault_signature_hash_hex=vault_signature_hash_hex,
            cal_amount=args.vault_alloc_cal,
            completion_time_s=SMOKE_COMPLETION_TIME_S,
            current_time=int(time.time()),
            initial_cal_tribute=0,
        )
        print(
            f"completion flow:    {flow_plan.stage} "
            f"pending={flow_plan.expected_pending_rewards} "
            f"remainder={flow_plan.expected_cal_remainder}"
        )

        await wait_for_smoke_finalization(admin_config, settlement_week)
        transport_plan = await prepare_smoke_settlement_transport(
            config=admin_config,
            vault_id=vault_id,
            settlement_week=settlement_week,
        )
        print(
            "settlement v0:      "
            f"{transport_plan['planned_serialized_bytes']} bytes via "
            f"{transport_plan['lookup_table_address']}"
        )

        distribute_sig = await send_distribute_epoch_rewards(
            config=admin_config,
            vault_id=vault_id,
            settlement_week=settlement_week,
            pol_account=str(pol_ata),
            protocol_treasury=str(treasury_ata),
            transport_plan=transport_plan,
        )
        print(f"epoch distributed:  {distribute_sig}")

        print(f"sleeping {args.sleep_seconds}s before cleanup...")
        await asyncio.sleep(args.sleep_seconds)
    else:
        print(f"epoch state:        Settlement Week {settlement_week} already distributed")

    vault_state = await read_vault_state(admin_config, vault_id)
    distributed_plan = inspect_smoke_settlement_stage(
        vault_state,
        settlement_clock,
        settlement_week,
        int(time.time()),
        measured_smoke_cal_tribute(
            args.vault_alloc_cal,
            SMOKE_COMPLETION_TIME_S,
        ),
        initial_cal_tribute=SMOKE_ADMIN_VAULT_CAL_DEPOSIT,
    )
    if distributed_plan.stage != "distributed":
        raise RuntimeError("distribution transaction did not advance the exact smoke flow")
    stake_state = await get_vault_stake_account(
        admin_config, vault_id, str(staker.pubkey())
    )
    stake_stage = inspect_smoke_stake_stage(
        vault_state,
        stake_state,
        args.stake_cal,
        distributed=True,
    )

    if stake_stage == "staked":
        lp_tokens = int((stake_state or {}).get("lp_tokens", 0) or 0)
        if lp_tokens <= 0:
            raise RuntimeError("exact smoke stake disappeared before unstake")
        unstake_sig = await send_unstake_cal_from_vault(
            config=admin_config,
            staker_keypair=staker,
            vault_id=vault_id,
            lp_amount=lp_tokens,
        )
        print(f"unstaked CAL:       {unstake_sig} (exact LP={lp_tokens})")

        vault_state = await read_vault_state(admin_config, vault_id)
        stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(staker.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            vault_state,
            stake_state,
            args.stake_cal,
            distributed=True,
        )
        if stake_stage != "withdrawn":
            raise RuntimeError("smoke cleanup did not fully withdraw the LP position")

    if stake_stage == "withdrawn":
        harvest_result = await send_harvest_rewards(
            config=admin_config,
            staker_wallet=str(staker.pubkey()),
            vault_id=vault_id,
            staker_keypair=staker,
        )
        if harvest_result.get("error"):
            raise RuntimeError(harvest_result["error"])
        print(f"harvested DUNG:     {harvest_result['tx_signature']}")

        final_vault_state = await read_vault_state(admin_config, vault_id)
        final_stake_state = await get_vault_stake_account(
            admin_config, vault_id, str(staker.pubkey())
        )
        stake_stage = inspect_smoke_stake_stage(
            final_vault_state,
            final_stake_state,
            args.stake_cal,
            distributed=True,
        )
    if stake_stage != "complete":
        raise RuntimeError("smoke cleanup did not reach the durable complete state")
    print("stake state:        fully withdrawn and harvested")

    print("=== Final Balances ===")
    print(f"staker CAL ATA:     {staker_cal_ata}")
    print(f"staker CAL balance: {await token_balance(rpc_url, staker_cal_ata)}")
    print(f"staker DUNG ATA:    {staker_dung_ata}")
    print(f"staker DUNG balance:{await token_balance(rpc_url, staker_dung_ata)}")
    print(f"POL ATA:            {pol_ata}")
    print(f"POL DUNG balance:   {await token_balance(rpc_url, pol_ata)}")
    print(f"treasury ATA:       {treasury_ata}")
    print(f"treasury balance:   {await token_balance(rpc_url, treasury_ata)}")


if __name__ == "__main__":
    asyncio.run(main())
