"""Direct Solana RPC helpers for Boulder Rollers programs.

Implements direct RPC calls for:
- boulder_rollers: user initialization, vault creation, CAL credit,
  vault completion, and settlement distribution
- proof_verifier.record_proof
- dung_mint.mint_from_proof

Uses Anchor IDL decoding for account reads where that is safer than hand-rolled
offset parsing.
"""

from __future__ import annotations

import hashlib
import base64
import json
import logging
import os
import struct
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TypeVar

import base58
from anchorpy import Idl
from anchorpy.coder.accounts import AccountsCoder
from anchorpy.coder.instruction import InstructionCoder
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment, Confirmed, Finalized
from solana.rpc.types import MemcmpOpts
from solders.address_lookup_table_account import (
    AddressLookupTable,
    AddressLookupTableAccount,
)
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYS_PROGRAM_ID
from solders.transaction import Transaction

from .account_deletion_contract import VAULT_STAKE_DELETION_U64_FIELDS
from .generated_program_version import PROGRAM_VERSION_FAMILY
from .program_compatibility import (
    observe_program_version,
    program_compatibility,
    require_program_version_byte,
    require_compatible_program_version,
)
from .metrics import SOLANA_RPC_CALLS, SOLANA_RPC_ERRORS, SOLANA_RPC_LATENCY
from .services.balance_vault_operation_authority import (
    BalanceVaultOperationAuthorization,
)
from .settlement_clock import (
    SettlementClock,
)
from .solana_env import (
    boulder_rollers_program_id,
    cal_mint_address,
    dung_mint_address,
    dung_mint_program_id,
    proof_verifier_program_id,
    solana_rpc_url,
)

logger = logging.getLogger(__name__)

# SPL Token program ID
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

# Defaults to deployed devnet IDs; override via env if needed.
DEFAULT_BOULDER_PROGRAM_ID = Pubkey.from_string(boulder_rollers_program_id())
DEFAULT_PROOF_VERIFIER_ID = Pubkey.from_string(proof_verifier_program_id())
DEFAULT_DUNG_MINT_PROGRAM_ID = Pubkey.from_string(dung_mint_program_id())
DEFAULT_DUNG_MINT_ADDRESS = Pubkey.from_string(dung_mint_address())
DEFAULT_CAL_MINT_ADDRESS = Pubkey.from_string(cal_mint_address())

# Scale factor for DUNG amounts (9 decimals)
DUNG_DECIMALS_MULTIPLIER = 1_000_000_000
# Scale factor for effort scores in proof_verifier
EFFORT_SCALE = 1_000_000

# Launch default and immutable exit fee mirrored from Anchor. The alignment
# gate binds both mirrors to lib.rs; live harvest policy still comes from the
# decoded ProgramConfig account.
HARVEST_FEE_BPS = 500
EXIT_FEE_BPS = 50


def require_current_program_version(observed: object) -> int:
    """Accept exactly the two append-compatible versions in this cutover."""
    return require_compatible_program_version(observed)


def require_direct_vault_creation_supported() -> None:
    """Keep every V4-B VaultCounter mutation behind prepare/submit reservation."""
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise RuntimeError(
            "Direct V4-B Vault creation is disabled; use the canonical "
            "prepare/submit reservation flow."
        )


class AcceptedSettlementTransactionError(RuntimeError):
    """A settlement signature was accepted but still requires reconciliation."""

    def __init__(
        self,
        signature: str,
        error: str,
        *,
        durable_callback_failed: bool,
        prepared_only: bool = False,
    ) -> None:
        self.signature = signature
        self.durable_callback_failed = durable_callback_failed
        self.prepared_only = prepared_only
        super().__init__(error)


def _validate_completion_evidence_hash(evidence_hash: bytes) -> bytes:
    if len(evidence_hash) != 32:
        raise ValueError("completion evidence hash must be exactly 32 bytes")
    if evidence_hash == b"\x00" * 32:
        raise ValueError("completion evidence hash must be non-zero")
    return evidence_hash


@dataclass
class DirectConfig:
    rpc_url: str
    program_id: Pubkey
    payer: Keypair
    backend_authority: Optional[Keypair] = None
    proof_verifier_id: Pubkey = DEFAULT_PROOF_VERIFIER_ID
    dung_mint_program_id: Pubkey = DEFAULT_DUNG_MINT_PROGRAM_ID
    dung_mint_address: Pubkey = DEFAULT_DUNG_MINT_ADDRESS
    cal_mint_address: Pubkey = DEFAULT_CAL_MINT_ADDRESS


T = TypeVar("T")


async def _with_rpc_metrics(method: str, call: Callable[[], Awaitable[T]]) -> T:
    SOLANA_RPC_CALLS.labels(method=method).inc()
    start = time.perf_counter()
    try:
        return await call()
    except Exception:
        SOLANA_RPC_ERRORS.labels(method=method).inc()
        raise
    finally:
        SOLANA_RPC_LATENCY.labels(method=method).observe(time.perf_counter() - start)


def _load_keypair(path_or_json: str) -> Keypair:
    """Load a keypair from JSON, base64, or a file containing either format."""
    raw_value = path_or_json.strip()
    parsed = _parse_keypair_literal(raw_value)
    if parsed is not None:
        return parsed

    path = Path(raw_value).expanduser()
    if path.exists():
        file_value = path.read_text().strip()
        parsed = _parse_keypair_literal(file_value)
        if parsed is not None:
            return parsed
        raise ValueError(f"Unsupported keypair format in {path}")

    raise ValueError("Unsupported keypair format")


def _parse_keypair_literal(value: str) -> Optional[Keypair]:
    """Parse a keypair from an inline JSON array or base64-encoded payload."""
    try:
        data = json.loads(value)
        if isinstance(data, list):
            return Keypair.from_bytes(bytes(data))
    except json.JSONDecodeError:
        pass

    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        return None

    if len(decoded) == 64:
        return Keypair.from_bytes(decoded)

    try:
        data = json.loads(decoded.decode("utf-8"))
        if isinstance(data, list):
            return Keypair.from_bytes(bytes(data))
    except Exception:
        return None

    return None


def _first_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode("utf-8")).digest()[:8]


def _account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]


def _vault_stake_account_discriminator() -> bytes:
    return _account_discriminator("VaultStake")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _get_boulder_idl_text() -> str:
    """Load the mirrored generated Anchor IDL used by all backend coders."""
    idl_paths = [
        Path(__file__).resolve().parents[1] / "idl" / "boulder_rollers.json",
        _repo_root() / "idl" / "boulder_rollers.json",
        _repo_root() / "protocol" / "anchor" / "idl" / "boulder_rollers.json",
        _repo_root() / "protocol" / "anchor" / "target" / "idl" / "boulder_rollers.json",
    ]

    for idl_path in idl_paths:
        if idl_path.exists():
            return idl_path.read_text(encoding="utf-8")

    raise FileNotFoundError("Could not locate boulder_rollers IDL for account decoding")


@lru_cache(maxsize=1)
def _get_boulder_idl() -> Idl:
    return Idl.from_json(_get_boulder_idl_text())


@lru_cache(maxsize=1)
def _get_boulder_idl_document() -> dict[str, Any]:
    return json.loads(_get_boulder_idl_text())


@lru_cache(maxsize=1)
def _get_boulder_accounts_coder() -> AccountsCoder:
    """Load the Anchor accounts coder for Boulder Rollers account decoding."""
    return AccountsCoder(_get_boulder_idl())


@lru_cache(maxsize=1)
def _get_boulder_instruction_coder() -> InstructionCoder:
    """Encode instructions from the generated IDL rather than a handwritten ABI."""
    return InstructionCoder(_get_boulder_idl())


def _build_boulder_idl_instruction(
    *,
    instruction_name: str,
    named_accounts: dict[str, Pubkey],
    args: dict[str, Any],
    remaining_accounts: list[AccountMeta],
    program_id: Pubkey,
) -> Instruction:
    """Build one instruction with IDL-owned data and named-account ordering."""
    camel_name = "".join(
        part if index == 0 else part[:1].upper() + part[1:]
        for index, part in enumerate(instruction_name.split("_"))
    )
    specs = [
        item
        for item in _get_boulder_idl_document().get("instructions", [])
        if item.get("name") == camel_name
    ]
    if len(specs) != 1:
        raise RuntimeError(f"generated IDL instruction is unavailable: {instruction_name}")
    account_specs = specs[0].get("accounts") or []
    expected_names = [str(item.get("name")) for item in account_specs]
    if set(named_accounts) != set(expected_names):
        missing = sorted(set(expected_names) - set(named_accounts))
        extra = sorted(set(named_accounts) - set(expected_names))
        raise RuntimeError(
            f"generated IDL account mismatch for {instruction_name}: "
            f"missing={missing}, extra={extra}"
        )
    accounts = [
        AccountMeta(
            pubkey=named_accounts[spec["name"]],
            is_signer=bool(spec.get("isSigner")),
            is_writable=bool(spec.get("isMut")),
        )
        for spec in account_specs
    ]
    accounts.extend(remaining_accounts)
    data = _get_boulder_instruction_coder().encode(instruction_name, args)
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def _decode_null_padded_utf8(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, list) and all(isinstance(item, int) for item in value):
        raw = bytes(value)
    else:
        return str(value)
    return raw.rstrip(b"\x00").decode("utf-8", errors="ignore")


def _account_data_bytes(value: object) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, tuple) and value:
        candidate = value[0]
        if isinstance(candidate, str):
            return base64.b64decode(candidate)
        if isinstance(candidate, (bytes, bytearray)):
            return bytes(candidate)
    if isinstance(value, list) and value and isinstance(value[0], int):
        return bytes(value)
    return bytes(value)


_MISSING = object()


def _field(fields: dict[str, object], *names: str, default: object = _MISSING) -> object:
    for name in names:
        if name in fields:
            return fields[name]
    if default is not _MISSING:
        return default
    raise KeyError(names[0])


def _decode_anchor_vault_account(data: bytes, vault_pda: Pubkey) -> dict:
    """Decode the current Vault layout via Anchor IDL."""
    decoded = _get_boulder_accounts_coder().parse(data)
    if decoded.name != "Vault":
        raise ValueError(f"Expected Vault account, got {decoded.name}")

    fields = vars(decoded.data)
    return {
        "id": _field(fields, "id"),
        "signature_hex": bytes(_field(fields, "signature")).hex(),
        "signature_hash_hex": bytes(_field(fields, "signatureHash", "signature_hash")).hex(),
        "minter": str(_field(fields, "minter")),
        "mint_epoch": _field(fields, "mintEpoch", "mint_epoch"),
        "rights_expires_epoch": _field(fields, "rightsExpiresEpoch", "rights_expires_epoch"),
        "kom_holder": str(_field(fields, "komHolder", "kom_holder"))
        if _field(fields, "komHolder", "kom_holder") != Pubkey.default()
        else None,
        "kom_time_s": _field(fields, "komTimeS", "kom_time_s"),
        "kom_set_epoch": _field(fields, "komSetEpoch", "kom_set_epoch"),
        "name": _decode_null_padded_utf8(_field(fields, "name")),
        "cal_tribute_accumulated": _field(fields, "calTributeAccumulated", "cal_tribute_accumulated"),
        "cal_tribute_accumulated_next": _field(
            fields, "calTributeAccumulatedNext", "cal_tribute_accumulated_next", default=0
        ),
        "total_cal_burned": _field(fields, "totalCalBurned", "total_cal_burned"),
        "total_dung_emitted": _field(fields, "totalDungEmitted", "total_dung_emitted"),
        "total_completions": _field(fields, "totalCompletions", "total_completions"),
        "total_cal_staked": _field(fields, "totalCalStaked", "total_cal_staked"),
        "staker_count": _field(fields, "stakerCount", "staker_count"),
        "pending_rewards": _field(fields, "pendingRewards", "pending_rewards"),
        "pending_rewards_next_week": _field(
            fields, "pendingRewardsNextWeek", "pending_rewards_next_week", default=0
        ),
        "open_settlement_week": _field(
            fields, "openSettlementWeek", "open_settlement_week", default=0
        ),
        "carry_record_royalty": _field(
            fields, "carryRecordRoyalty", "carry_record_royalty", default=0
        ),
        "carry_stakers": _field(fields, "carryStakers", "carry_stakers", default=0),
        "carry_local_legend": _field(
            fields, "carryLocalLegend", "carry_local_legend", default=0
        ),
        "carry_pol": _field(fields, "carryPol", "carry_pol", default=0),
        "carry_treasury": _field(fields, "carryTreasury", "carry_treasury", default=0),
        "total_staked": _field(fields, "totalStaked", "total_staked"),
        "last_distribution_epoch": _field(
            fields, "lastDistributionEpoch", "last_distribution_epoch"
        ),
        "vert_m": _field(fields, "vertM", "vert_m") / 10.0,
        "distance_m": _field(fields, "distanceM", "distance_m"),
        "avg_gradient_pct": _field(fields, "avgGradientPct", "avg_gradient_pct") / 100.0,
        "created_at": _field(fields, "createdAt", "created_at"),
        "climb": str(_field(fields, "climb", default=Pubkey.default())),
        "pda": str(vault_pda),
        "account_layout": "idl",
    }


def _decode_anchor_vault_stake_account(data: bytes, stake_pda: Pubkey) -> dict:
    decoded = _get_boulder_accounts_coder().parse(data)
    if decoded.name != "VaultStake":
        raise ValueError(f"Expected VaultStake account, got {decoded.name}")

    fields = vars(decoded.data)
    lp_tokens = _field(fields, "lpTokens", "lp_tokens")
    raw_pending_week = _field(
        fields,
        "pendingEffectiveWeekPlusOne",
        "pending_effective_week_plus_one",
        "eligibleFromEpoch",
        "eligible_from_epoch",
        default=0,
    )
    effective_lp_tokens = _field(
        fields,
        "effectiveLpTokens",
        "effective_lp_tokens",
        "userRewardPerTokenPaid",
        "user_reward_per_token_paid",
    )
    pending_lp_tokens = _field(
        fields,
        "pendingLpTokens",
        "pending_lp_tokens",
        "amount",
    )
    legacy_layout = (
        int(effective_lp_tokens or 0) == 0
        and int(pending_lp_tokens or 0) == 0
        and (int(lp_tokens or 0) > 0 or int(raw_pending_week or 0) > 0)
    )

    return {
        "user": str(_field(fields, "user")),
        "vault_id": _field(fields, "vaultId", "vault_id"),
        "cal_staked": _field(fields, "calStaked", "cal_staked"),
        "lp_tokens": lp_tokens,
        "staked_at": _field(fields, "stakedAt", "staked_at"),
        "eligible_from_epoch": raw_pending_week if legacy_layout else 0,
        "pending_effective_week_plus_one": 0 if legacy_layout else raw_pending_week,
        "effective_lp_tokens": 0 if legacy_layout else effective_lp_tokens,
        "rewards_earned": _field(fields, "rewardsEarned", "rewards_earned"),
        "pending_lp_tokens": 0 if legacy_layout else pending_lp_tokens,
        "snapshot_layout": "legacy" if legacy_layout else "weekly",
        "bump": _field(fields, "bump"),
        "pda": str(stake_pda),
        "account_layout": "idl",
    }


def _stake_requires_settlement_account(stake: dict) -> bool:
    """A position stays enumerable while any live or snapshot LP can matter."""
    return any(
        int(stake.get(field) or 0) > 0
        for field in (
            "lp_tokens",
            "effective_lp_tokens",
            "pending_lp_tokens",
        )
    )


def _decode_anchor_program_config_account(data: bytes, config_pda: Pubkey, *, validate_version: bool = True) -> dict:
    decoded = _get_boulder_accounts_coder().parse(data)
    if decoded.name != "ProgramConfig":
        raise ValueError(f"Expected ProgramConfig account, got {decoded.name}")

    fields = vars(decoded.data)
    program_version = (require_current_program_version if validate_version else require_program_version_byte)(
        _field(fields, "programVersion", "program_version", default=0)
    )
    return {
        "admin_authority": str(_field(fields, "adminAuthority", "admin_authority")),
        "backend_authority": str(_field(fields, "backendAuthority", "backend_authority")),
        "program_version": program_version,
        "initialized": bool(_field(fields, "initialized")),
        "bump": _field(fields, "bump"),
        "cal_mint": str(_field(fields, "calMint", "cal_mint")),
        "dung_mint": str(_field(fields, "dungMint", "dung_mint")),
        "cal_mint_auth_bump": _field(fields, "calMintAuthBump", "cal_mint_auth_bump"),
        "dung_mint_auth_bump": _field(fields, "dungMintAuthBump", "dung_mint_auth_bump"),
        "pol_token_account": str(
            _field(fields, "polTokenAccount", "pol_token_account", default=Pubkey.default())
        ),
        "treasury_token_account": str(
            _field(fields, "treasuryTokenAccount", "treasury_token_account", default=Pubkey.default())
        ),
        "vault_creation_dung": _field(fields, "vaultCreationDung", "vault_creation_dung", default=0),
        "vault_creation_cal": _field(fields, "vaultCreationCal", "vault_creation_cal", default=0),
        "harvest_fee_bps": _field(fields, "harvestFeeBps", "harvest_fee_bps", default=0),
        "exit_fee_bps": EXIT_FEE_BPS,
        "minter_rights_epochs": _field(
            fields, "minterRightsEpochs", "minter_rights_epochs", default=0
        ),
        "local_legend_term_epochs": _field(
            fields, "localLegendTermEpochs", "local_legend_term_epochs", default=0
        ),
        "epochs_per_halving": _field(fields, "epochsPerHalving", "epochs_per_halving", default=0),
        "usdc_mint": str(
            _field(fields, "usdcMint", "usdc_mint", default=Pubkey.default())
        ),
        "usdc_treasury_token_account": str(
            _field(
                fields,
                "usdcTreasuryTokenAccount",
                "usdc_treasury_token_account",
                default=Pubkey.default(),
            )
        ),
        "vault_creation_usdc": _field(
            fields,
            "vaultCreationUsdc",
            "vault_creation_usdc",
            default=0,
        ),
        "settlement_clock_v2_starts_at": _field(
            fields,
            "settlementClockV2StartsAt",
            "settlement_clock_v2_starts_at",
            default=0,
        ),
        "settlement_clock_version": _field(
            fields,
            "settlementClockVersion",
            "settlement_clock_version",
            default=0,
        ),
        "pda": str(config_pda),
    }


def _decode_legacy_vault_account(data: bytes, vault_pda: Pubkey) -> dict:
    """Decode the 545-byte pre-V3 Vault layout as a compatibility fallback."""
    offset = 8  # Skip 8-byte discriminator

    parsed_vault_id = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    signature = data[offset:offset + 64]
    offset += 64

    signature_hash = data[offset:offset + 32]
    offset += 32

    minter = Pubkey.from_bytes(data[offset:offset + 32])
    offset += 32

    mint_epoch = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    rights_expires_epoch = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    kom_holder = Pubkey.from_bytes(data[offset:offset + 32])
    offset += 32

    kom_time_s = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    kom_set_epoch = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    name_bytes = data[offset:offset + 64]
    name = name_bytes.rstrip(b"\x00").decode("utf-8", errors="ignore")
    offset += 64

    offset += 46 + 128  # avatar_ipfs + slogan

    cal_tribute_accumulated = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    total_cal_burned = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    total_dung_emitted = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    total_completions = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    total_cal_staked = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    staker_count = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    offset += 8  # deprecated reward_per_token_stored layout slot
    offset += 8  # deprecated last_update_time layout slot
    offset += 8  # deprecated reward_rate layout slot

    pending_rewards = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    total_staked = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    vert_m = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    distance_m = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    avg_gradient_pct = struct.unpack("<H", data[offset:offset + 2])[0]
    offset += 2

    created_at = struct.unpack("<q", data[offset:offset + 8])[0]

    return {
        "id": parsed_vault_id,
        "signature_hex": signature.hex(),
        "signature_hash_hex": signature_hash.hex(),
        "minter": str(minter),
        "mint_epoch": mint_epoch,
        "rights_expires_epoch": rights_expires_epoch,
        "kom_holder": str(kom_holder) if kom_holder != Pubkey.default() else None,
        "kom_time_s": kom_time_s,
        "kom_set_epoch": kom_set_epoch,
        "name": name,
        "cal_tribute_accumulated": cal_tribute_accumulated,
        "total_cal_burned": total_cal_burned,
        "total_dung_emitted": total_dung_emitted,
        "total_completions": total_completions,
        "total_cal_staked": total_cal_staked,
        "staker_count": staker_count,
        "pending_rewards": pending_rewards,
        "total_staked": total_staked,
        "vert_m": vert_m / 10.0,
        "distance_m": distance_m,
        "avg_gradient_pct": avg_gradient_pct / 100.0,
        "created_at": created_at,
        "pda": str(vault_pda),
        "account_layout": "legacy",
    }


def _derive_user_pda(owner: Pubkey, program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"user", bytes(owner)], program_id)


def _derive_proof_verifier_state(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"state"], program_id)


def _derive_proof_pda(proof_id: bytes, program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"proof", proof_id], program_id)


def _derive_dung_mint_state(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"state"], program_id)


def _derive_mint_authority(program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"mint_auth"], program_id)


def _derive_mint_event(proof_id: bytes, program_id: Pubkey) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address([b"mint_evt", proof_id], program_id)


def _derive_cal_mint_auth_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive CAL mint authority PDA."""
    return Pubkey.find_program_address([b"cal_mint_auth"], program_id)


def _derive_dung_mint_auth_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive DUNG mint authority PDA."""
    return Pubkey.find_program_address([b"dung_mint_auth"], program_id)


def _derive_program_config_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive ProgramConfig PDA."""
    return Pubkey.find_program_address([b"program_config"], program_id)


ATA_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSVAR_RENT_PUBKEY = Pubkey.from_string("SysvarRent111111111111111111111111111111111")


def _derive_ata(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """Derive Associated Token Account address."""
    pda, _ = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)],
        ATA_PROGRAM_ID
    )
    return pda


async def _account_exists(rpc_url: str, account: Pubkey) -> bool:
    async with AsyncClient(rpc_url, commitment=Confirmed) as client:
        account_info = await client.get_account_info(account)
    return account_info.value is not None


def make_create_ata_ix(
    payer: Pubkey,
    owner: Pubkey,
    mint: Pubkey,
    *,
    idempotent: bool = False,
) -> Instruction:
    """Build a create-associated-token-account instruction."""
    ata = _derive_ata(owner, mint)
    accounts = [
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=False, is_writable=False),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
    ]
    return Instruction(
        program_id=ATA_PROGRAM_ID,
        accounts=accounts,
        data=bytes([1]) if idempotent else bytes(),
    )


def make_spl_transfer_checked_ix(
    *,
    source: Pubkey,
    mint: Pubkey,
    destination: Pubkey,
    owner: Pubkey,
    amount: int,
    decimals: int,
) -> Instruction:
    """Build SPL Token transfer_checked for a single-owner token account."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    if decimals < 0 or decimals > 255:
        raise ValueError("decimals must fit in u8")

    data = bytes([12]) + struct.pack("<Q", amount) + bytes([decimals])
    accounts = [
        AccountMeta(pubkey=source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=destination, is_signer=False, is_writable=True),
        AccountMeta(pubkey=owner, is_signer=True, is_writable=False),
    ]
    return Instruction(program_id=TOKEN_PROGRAM_ID, accounts=accounts, data=data)


def _uuid_to_bytes(proof_id_str: str) -> bytes:
    """Convert UUID string to 16 bytes."""
    return uuid.UUID(proof_id_str).bytes


def make_initialize_user_ix(payer: Pubkey, program_id: Pubkey) -> Instruction:
    """Build initialize_user instruction."""
    user_state, _bump = _derive_user_pda(payer, program_id)
    data = _discriminator("initialize_user")
    accounts = [
        AccountMeta(pubkey=user_state, is_signer=False, is_writable=True),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


@dataclass
class UserStateData:
    """Parsed on-chain UserState account data.

    The CAL-related fields are legacy pre-TGE snapshots only. Live CAL balances
    come from SPL token accounts.
    """
    owner: Pubkey
    legacy_cal_snapshot: int
    legacy_cal_earned_today: int
    legacy_last_cal_mint: int
    total_rides: int
    total_tss: int
    bio_score: int
    bump: int


def parse_user_state(data: bytes) -> Optional[UserStateData]:
    """Parse UserState account data (skips 8-byte discriminator)."""
    if len(data) < 8 + 32 + 8 + 8 + 8 + 8 + 8 + 2 + 1:
        return None

    offset = 8  # Skip discriminator
    owner = Pubkey(data[offset:offset + 32])
    offset += 32
    legacy_cal_snapshot = int.from_bytes(data[offset:offset + 8], "little")
    offset += 8
    legacy_cal_earned_today = int.from_bytes(data[offset:offset + 8], "little")
    offset += 8
    legacy_last_cal_mint = int.from_bytes(data[offset:offset + 8], "little", signed=True)
    offset += 8
    total_rides = int.from_bytes(data[offset:offset + 8], "little")
    offset += 8
    total_tss = int.from_bytes(data[offset:offset + 8], "little")
    offset += 8
    bio_score = int.from_bytes(data[offset:offset + 2], "little")
    offset += 2
    bump = data[offset]

    return UserStateData(
        owner=owner,
        legacy_cal_snapshot=legacy_cal_snapshot,
        legacy_cal_earned_today=legacy_cal_earned_today,
        legacy_last_cal_mint=legacy_last_cal_mint,
        total_rides=total_rides,
        total_tss=total_tss,
        bio_score=bio_score,
        bump=bump,
    )


async def get_user_state(wallet: str, rpc_url: Optional[str] = None, program_id: Optional[Pubkey] = None) -> Optional[UserStateData]:
    """Read on-chain UserState for a wallet. Returns None if account doesn't exist.

    This is a read-only operation. The CAL fields in this account are retained
    only as legacy snapshots; live CAL should be read from the SPL ATA.
    """
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    owner = Pubkey.from_string(wallet)
    user_pda, _ = _derive_user_pda(owner, program_id)

    async def _call() -> Optional[UserStateData]:
        async with AsyncClient(rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(user_pda)
            if account_info.value is None:
                return None
            return parse_user_state(bytes(account_info.value.data))

    return await _with_rpc_metrics("get_user_state", _call)


CAL_SPL_DECIMALS = 9  # CAL mint has 9 decimal places on Solana

SPL_TOKEN_ACCOUNT_LEN = 165
SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET = 64
SPL_TOKEN_ACCOUNT_STATE_OFFSET = 108
SPL_TOKEN_MINT_LEN = 82
SPL_TOKEN_MINT_INITIALIZED_OFFSET = 45
SPL_TOKEN_MINT_FREEZE_AUTHORITY_OFFSET = 46
RIDER_BALANCE_ACCOUNT_LEN = 123


@dataclass(frozen=True)
class ExactTokenAccountBalanceSource:
    """One exact SPL token-account observation at a named custody boundary."""

    amount_base_units: int
    token_account: str
    mint: str
    source: str
    status: str
    exists: bool
    slot: int


@dataclass(frozen=True)
class VaultLpCustodyObservation:
    """Live proof that one VaultStake is backed by its sealed LP account."""

    token_account: str
    token_authority: str
    mint: str
    recorded_lp_tokens: int
    amount_base_units: Optional[int]
    token_state: Optional[int]
    status: str
    sealed: bool
    slot: int
    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None
    lp_supply_base_units: Optional[int] = None


@dataclass(frozen=True)
class VaultPositionQuoteSnapshot:
    slot: int
    vault: dict
    stake: dict
    custody: VaultLpCustodyObservation


def _decode_spl_coption_pubkey(data: bytes, offset: int) -> Optional[Pubkey]:
    tag = struct.unpack_from("<I", data, offset)[0]
    if tag == 0:
        return None
    if tag != 1:
        raise ValueError(f"Invalid SPL COption tag {tag}")
    return Pubkey.from_bytes(data[offset + 4 : offset + 36])


@dataclass(frozen=True)
class RiderBalanceHeaderSource:
    """One decoded RiderBalance header observation."""

    initialized: bool
    status: Optional[str]
    account: str
    source: str
    source_status: str
    authority_model: Optional[str]
    policy_hash: Optional[str]
    delegate_authority: Optional[str]
    last_authority_rotation_at: Optional[int]
    revoked_at: Optional[int]
    slot: int


@dataclass(frozen=True)
class RiderBalanceAccountSnapshot:
    """Header and configured CAL/USDC Balance accounts observed together."""

    header: RiderBalanceHeaderSource
    cal: ExactTokenAccountBalanceSource
    usdc: ExactTokenAccountBalanceSource
    program_config_account: str
    program_config_slot: int
    harvest_fee_bps: int
    exit_fee_bps: int


_RIDER_BALANCE_STATUS_VARIANTS = {
    "Active": "active",
    "Locked": "locked",
    "Recovering": "recovering",
    "Revoked": "revoked",
}
_BALANCE_AUTHORITY_MODEL_VARIANTS = {
    "AppBalance": "app_balance",
    "Policy": "policy",
    "Delegate": "delegate",
}


def _anchor_enum_name(value: object, variants: dict[str, str], label: str) -> str:
    variant = type(value).__name__
    try:
        return variants[variant]
    except KeyError as exc:
        raise ValueError(f"Unknown {label} variant: {variant}") from exc


def _decode_rider_balance_header(
    data: bytes,
    *,
    expected_rider: Pubkey,
    expected_bump: int,
) -> dict:
    """Decode and bind the current RiderBalance IDL layout to its PDA seeds."""
    if len(data) != RIDER_BALANCE_ACCOUNT_LEN:
        raise ValueError(
            f"RiderBalance account is {len(data)} bytes, expected {RIDER_BALANCE_ACCOUNT_LEN}"
        )

    decoded = _get_boulder_accounts_coder().parse(data)
    if decoded.name != "RiderBalance":
        raise ValueError(f"Expected RiderBalance account, got {decoded.name}")

    fields = vars(decoded.data)
    rider = _field(fields, "rider")
    if rider != expected_rider:
        raise ValueError(f"RiderBalance rider is {rider}, expected {expected_rider}")

    bump = int(_field(fields, "bump"))
    if bump != expected_bump:
        raise ValueError(f"RiderBalance bump is {bump}, expected {expected_bump}")

    status = _anchor_enum_name(
        _field(fields, "status"),
        _RIDER_BALANCE_STATUS_VARIANTS,
        "RiderBalance status",
    )
    authority_model = _anchor_enum_name(
        _field(fields, "activeAuthorityModel", "active_authority_model"),
        _BALANCE_AUTHORITY_MODEL_VARIANTS,
        "Balance authority model",
    )
    revoked_at = int(_field(fields, "revokedAt", "revoked_at"))
    if status == "revoked" and revoked_at <= 0:
        raise ValueError("Revoked RiderBalance must have a positive revoked_at timestamp")

    delegate = _field(fields, "delegateAuthority", "delegate_authority")
    return {
        "rider": str(rider),
        "status": status,
        "authority_model": authority_model,
        "policy_hash": bytes(_field(fields, "policyHash", "policy_hash")).hex(),
        "delegate_authority": str(delegate) if delegate != Pubkey.default() else None,
        "last_authority_rotation_at": int(
            _field(fields, "lastAuthorityRotationAt", "last_authority_rotation_at")
        ),
        "revoked_at": revoked_at,
        "bump": bump,
    }


def _require_account_program_owner(
    account: object,
    *,
    expected_owner: Pubkey,
    label: str,
) -> None:
    observed_owner = Pubkey.from_string(str(getattr(account, "owner")))
    if observed_owner != expected_owner:
        raise ValueError(
            f"{label} has program owner {observed_owner}, expected {expected_owner}"
        )


async def _decode_verified_program_config(
    account: object,
    *,
    config_pda: Pubkey,
    program_id: Pubkey,
    rpc_url: str,
    client: AsyncClient,
) -> dict:
    try:
        _require_account_program_owner(account, expected_owner=program_id, label="ProgramConfig")
        config = _decode_anchor_program_config_account(
            _account_data_bytes(getattr(account, "data")), config_pda, validate_version=False,
        )
        if not config.get("initialized"):
            raise ValueError("ProgramConfig is not initialized")
        await observe_program_version(client, rpc_url, str(program_id), config.get("program_version"))
        return config
    except Exception as exc:
        program_compatibility(rpc_url, str(program_id)).invalidate(exc)
        raise


def _configured_program_mint(config: dict, field: str) -> Pubkey:
    mint = Pubkey.from_string(str(config[field]))
    if mint == Pubkey.default():
        raise ValueError(f"ProgramConfig {field} is not configured")
    return mint


def _balance_token_source_from_account(
    account: object | None,
    *,
    token_account: Pubkey,
    mint: Pubkey,
    balance_authority: Pubkey,
    slot: int,
) -> ExactTokenAccountBalanceSource:
    if account is None:
        return ExactTokenAccountBalanceSource(
            amount_base_units=0,
            token_account=str(token_account),
            mint=str(mint),
            source="rider_balance_token_pda",
            status="not_initialized",
            exists=False,
            slot=slot,
        )

    amount_base_units = _decode_exact_spl_token_account(
        account,
        expected_mint=mint,
        expected_token_owner=balance_authority,
    )
    return ExactTokenAccountBalanceSource(
        amount_base_units=amount_base_units,
        token_account=str(token_account),
        mint=str(mint),
        source="rider_balance_token_pda",
        status="live",
        exists=True,
        slot=slot,
    )


def _decode_exact_spl_token_account(
    account: object,
    *,
    expected_mint: Pubkey,
    expected_token_owner: Pubkey,
) -> int:
    account_program = Pubkey.from_string(str(getattr(account, "owner")))
    if account_program != TOKEN_PROGRAM_ID:
        raise ValueError(
            f"SPL token account has program owner {account_program}, expected {TOKEN_PROGRAM_ID}"
        )

    data = _account_data_bytes(getattr(account, "data"))
    if len(data) != SPL_TOKEN_ACCOUNT_LEN:
        raise ValueError(
            f"SPL token account is {len(data)} bytes, expected {SPL_TOKEN_ACCOUNT_LEN}"
        )

    observed_mint = Pubkey.from_bytes(data[0:32])
    if observed_mint != expected_mint:
        raise ValueError(
            f"SPL token account mint is {observed_mint}, expected {expected_mint}"
        )

    observed_token_owner = Pubkey.from_bytes(data[32:64])
    if observed_token_owner != expected_token_owner:
        raise ValueError(
            "SPL token account token owner is "
            f"{observed_token_owner}, expected {expected_token_owner}"
        )

    state = data[SPL_TOKEN_ACCOUNT_STATE_OFFSET]
    if state not in (1, 2):
        raise ValueError(f"SPL token account state {state} is not initialized")

    return struct.unpack_from("<Q", data, SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET)[0]


async def _read_exact_spl_token_account_source(
    *,
    rpc_url: str,
    token_account: Pubkey,
    expected_mint: Pubkey,
    expected_token_owner: Pubkey,
    source: str,
    metric_name: str,
    commitment: Commitment = Confirmed,
) -> ExactTokenAccountBalanceSource:
    async def _call() -> ExactTokenAccountBalanceSource:
        async with AsyncClient(rpc_url, commitment=commitment) as client:
            response = await client.get_account_info(token_account)

        slot = int(response.context.slot)
        if response.value is None:
            return ExactTokenAccountBalanceSource(
                amount_base_units=0,
                token_account=str(token_account),
                mint=str(expected_mint),
                source=source,
                status="not_initialized",
                exists=False,
                slot=slot,
            )

        amount_base_units = _decode_exact_spl_token_account(
            response.value,
            expected_mint=expected_mint,
            expected_token_owner=expected_token_owner,
        )
        return ExactTokenAccountBalanceSource(
            amount_base_units=amount_base_units,
            token_account=str(token_account),
            mint=str(expected_mint),
            source=source,
            status="live",
            exists=True,
            slot=slot,
        )

    return await _with_rpc_metrics(metric_name, _call)


async def get_wallet_cal_balance_source(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
) -> ExactTokenAccountBalanceSource:
    """Read CAL held by the rider's wallet ATA, never an issuance projection."""
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    rider = Pubkey.from_string(wallet)
    token_account = _derive_ata(rider, DEFAULT_CAL_MINT_ADDRESS)
    return await _read_exact_spl_token_account_source(
        rpc_url=rpc_url,
        token_account=token_account,
        expected_mint=DEFAULT_CAL_MINT_ADDRESS,
        expected_token_owner=rider,
        source="spl_wallet_ata",
        metric_name="get_wallet_cal_balance",
    )


async def get_wallet_dung_balance_source(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
) -> ExactTokenAccountBalanceSource:
    """Read DUNG held by the rider's wallet ATA, never an issuance projection."""
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    rider = Pubkey.from_string(wallet)
    token_account = _derive_ata(rider, DEFAULT_DUNG_MINT_ADDRESS)
    return await _read_exact_spl_token_account_source(
        rpc_url=rpc_url,
        token_account=token_account,
        expected_mint=DEFAULT_DUNG_MINT_ADDRESS,
        expected_token_owner=rider,
        source="spl_wallet_ata",
        metric_name="get_wallet_dung_balance",
    )


async def get_balance_dung_balance_source(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
    *,
    commitment: Commitment = Confirmed,
) -> ExactTokenAccountBalanceSource:
    """Read DUNG held inside the rider's Boulder Roller Balance token PDA."""
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    rider = Pubkey.from_string(wallet)
    token_account, _ = _derive_rider_balance_token_pda(
        rider,
        DEFAULT_DUNG_MINT_ADDRESS,
        program_id,
    )
    token_owner, _ = _derive_rider_balance_auth_pda(rider, program_id)
    return await _read_exact_spl_token_account_source(
        rpc_url=rpc_url,
        token_account=token_account,
        expected_mint=DEFAULT_DUNG_MINT_ADDRESS,
        expected_token_owner=token_owner,
        source="rider_balance_token_pda",
        metric_name="get_balance_dung_balance",
        commitment=commitment,
    )


async def get_finalized_balance_dung_balance_source(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
) -> ExactTokenAccountBalanceSource:
    """Deletion-grade DUNG read from finalized Boulder Roller Balance state."""
    return await get_balance_dung_balance_source(
        wallet,
        rpc_url=rpc_url,
        program_id=program_id,
        commitment=Finalized,
    )


async def get_rider_balance_account_snapshot(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
) -> RiderBalanceAccountSnapshot:
    """Read the RiderBalance header and configured CAL/USDC token PDAs exactly."""
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    rider = Pubkey.from_string(wallet)
    config_pda, _ = _derive_program_config_pda(program_id)
    header_pda, header_bump = _derive_rider_balance_pda(rider, program_id)
    balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)

    async def _call() -> RiderBalanceAccountSnapshot:
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            bootstrap = await client.get_account_info(config_pda, commitment=Finalized)
            if bootstrap.value is None:
                raise RuntimeError("ProgramConfig is unavailable; Balance mints are unknown")
            config = await _decode_verified_program_config(
                bootstrap.value,
                config_pda=config_pda,
                program_id=program_id,
                rpc_url=rpc_url,
                client=client,
            )

            for attempt in range(2):
                cal_mint = _configured_program_mint(config, "cal_mint")
                usdc_mint = _configured_program_mint(config, "usdc_mint")
                cal_pda, _ = _derive_rider_balance_token_pda(
                    rider,
                    cal_mint,
                    program_id,
                )
                usdc_pda, _ = _derive_rider_balance_token_pda(
                    rider,
                    usdc_mint,
                    program_id,
                )
                response = await client.get_multiple_accounts(
                    [config_pda, header_pda, cal_pda, usdc_pda],
                    commitment=Finalized,
                )
                if len(response.value) != 4:
                    raise RuntimeError("Balance account snapshot returned an incomplete response")

                observed_config_account, header_account, cal_account, usdc_account = response.value
                if observed_config_account is None:
                    raise RuntimeError("ProgramConfig disappeared during Balance snapshot")
                observed_config = await _decode_verified_program_config(
                    observed_config_account,
                    config_pda=config_pda,
                    program_id=program_id,
                    rpc_url=rpc_url,
                    client=client,
                )
                observed_mints = (
                    _configured_program_mint(observed_config, "cal_mint"),
                    _configured_program_mint(observed_config, "usdc_mint"),
                )
                if observed_mints != (cal_mint, usdc_mint):
                    if attempt == 0:
                        config = observed_config
                        continue
                    raise RuntimeError("ProgramConfig mints changed during Balance snapshot")

                slot = int(response.context.slot)
                if header_account is None:
                    header = RiderBalanceHeaderSource(
                        initialized=False,
                        status=None,
                        account=str(header_pda),
                        source="rider_balance_header_pda",
                        source_status="not_initialized",
                        authority_model=None,
                        policy_hash=None,
                        delegate_authority=None,
                        last_authority_rotation_at=None,
                        revoked_at=None,
                        slot=slot,
                    )
                else:
                    _require_account_program_owner(
                        header_account,
                        expected_owner=program_id,
                        label="RiderBalance",
                    )
                    decoded_header = _decode_rider_balance_header(
                        _account_data_bytes(getattr(header_account, "data")),
                        expected_rider=rider,
                        expected_bump=header_bump,
                    )
                    header = RiderBalanceHeaderSource(
                        initialized=True,
                        status=str(decoded_header["status"]),
                        account=str(header_pda),
                        source="rider_balance_header_pda",
                        source_status="live",
                        authority_model=str(decoded_header["authority_model"]),
                        policy_hash=str(decoded_header["policy_hash"]),
                        delegate_authority=decoded_header["delegate_authority"],
                        last_authority_rotation_at=int(
                            decoded_header["last_authority_rotation_at"]
                        ),
                        revoked_at=int(decoded_header["revoked_at"]),
                        slot=slot,
                    )

                return RiderBalanceAccountSnapshot(
                    header=header,
                    cal=_balance_token_source_from_account(
                        cal_account,
                        token_account=cal_pda,
                        mint=cal_mint,
                        balance_authority=balance_authority,
                        slot=slot,
                    ),
                    usdc=_balance_token_source_from_account(
                        usdc_account,
                        token_account=usdc_pda,
                        mint=usdc_mint,
                        balance_authority=balance_authority,
                        slot=slot,
                    ),
                    program_config_account=str(config_pda),
                    program_config_slot=slot,
                    harvest_fee_bps=int(
                        observed_config.get("harvest_fee_bps", HARVEST_FEE_BPS)
                    ),
                    exit_fee_bps=int(
                        observed_config.get("exit_fee_bps", EXIT_FEE_BPS)
                    ),
                )

        raise RuntimeError("Unable to obtain a stable Balance account snapshot")

    try:
        return await _with_rpc_metrics("get_rider_balance_account_snapshot", _call)
    except Exception as exc:
        program_compatibility(rpc_url, str(program_id)).invalidate(exc)
        raise


async def get_cal_balance_base_units(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
) -> int:
    """Get the exact on-chain SPL CAL balance in atomic base units."""
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    owner = Pubkey.from_string(wallet)
    cal_ata = _derive_ata(owner, DEFAULT_CAL_MINT_ADDRESS)

    async def _call() -> int:
        async with AsyncClient(rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(cal_ata)
            if account_info.value is None:
                return 0

            balance = await client.get_token_account_balance(cal_ata)
            return int(balance.value.amount)

    return await _with_rpc_metrics("get_cal_balance", _call)


async def get_cal_balance(wallet: str, rpc_url: Optional[str] = None, program_id: Optional[Pubkey] = None) -> float:
    """Compatibility reader returning human-readable CAL as a float."""
    base_units = await get_cal_balance_base_units(wallet, rpc_url=rpc_url, program_id=program_id)
    return base_units / (10 ** CAL_SPL_DECIMALS)


# =============================================================================
# proof_verifier: record_proof
# =============================================================================

def make_record_proof_ix(
    payer: Pubkey,
    proof_id: bytes,
    effort_score_scaled: int,
    wallet: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build record_proof instruction for proof_verifier program."""
    state_pda, _ = _derive_proof_verifier_state(program_id)
    proof_pda, _ = _derive_proof_pda(proof_id, program_id)

    # Data: discriminator + proof_id (16 bytes) + effort_score_scaled (u64) + wallet (32 bytes)
    data = (
        _discriminator("record_proof")
        + proof_id
        + struct.pack("<Q", effort_score_scaled)
        + bytes(wallet)
    )

    accounts = [
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=proof_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def send_record_proof(
    config: DirectConfig,
    proof_id_str: str,
    effort_score: float,
    wallet_address: str,
) -> str:
    """Record a ride proof on-chain via proof_verifier program.

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.
    """
    from .services.solana_submit import submit_and_confirm

    proof_id = _uuid_to_bytes(proof_id_str)
    effort_score_scaled = int(effort_score * EFFORT_SCALE)
    wallet = Pubkey.from_string(wallet_address)

    ix = make_record_proof_ix(
        payer=config.payer.pubkey(),
        proof_id=proof_id,
        effort_score_scaled=effort_score_scaled,
        wallet=wallet,
        program_id=config.proof_verifier_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=[config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="record_proof",
        reference_type="proof",
        reference_id=proof_id_str,
        wallet=wallet_address,
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"record_proof failed: {result.error}")

    return result.signature


# =============================================================================
# dung_mint: mint_from_proof
# =============================================================================

def make_mint_from_proof_ix(
    payer: Pubkey,
    proof_id: bytes,
    amount: int,
    wallet: Pubkey,
    config: DirectConfig,
) -> Instruction:
    """Build mint_from_proof instruction for dung_mint program."""
    state_pda, _ = _derive_dung_mint_state(config.dung_mint_program_id)
    mint_authority, _ = _derive_mint_authority(config.dung_mint_program_id)
    proof_pda, _ = _derive_proof_pda(proof_id, config.proof_verifier_id)
    mint_event_pda, _ = _derive_mint_event(proof_id, config.dung_mint_program_id)
    destination_ata = _derive_ata(wallet, config.dung_mint_address)

    # Data: discriminator + proof_id (16 bytes) + amount (u64)
    data = (
        _discriminator("mint_from_proof")
        + proof_id
        + struct.pack("<Q", amount)
    )

    accounts = [
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=config.dung_mint_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=proof_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=destination_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint_event_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=config.proof_verifier_id, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=config.dung_mint_program_id, accounts=accounts, data=data)


async def send_mint_from_proof(
    config: DirectConfig,
    proof_id_str: str,
    amount: int,
    wallet_address: str,
) -> str:
    """Mint DUNG tokens from a recorded proof.

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.
    """
    from .services.solana_submit import submit_and_confirm

    proof_id = _uuid_to_bytes(proof_id_str)
    wallet = Pubkey.from_string(wallet_address)
    # Scale amount to 9 decimals (1 DUNG = 1_000_000_000)
    scaled_amount = amount * DUNG_DECIMALS_MULTIPLIER

    instructions = []

    # Check if ATA exists, create if not
    destination_ata = _derive_ata(wallet, config.dung_mint_address)
    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        ata_info = await client.get_account_info(destination_ata)
    if ata_info.value is None:
        create_ata_ix = make_create_ata_ix(
            payer=config.payer.pubkey(),
            owner=wallet,
            mint=config.dung_mint_address,
        )
        instructions.append(create_ata_ix)

    # Add mint instruction
    mint_ix = make_mint_from_proof_ix(
        payer=config.payer.pubkey(),
        proof_id=proof_id,
        amount=scaled_amount,
        wallet=wallet,
        config=config,
    )
    instructions.append(mint_ix)

    result = await submit_and_confirm(
        instructions=instructions,
        signers=[config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="mint_from_proof",
        reference_type="proof",
        reference_id=proof_id_str,
        wallet=wallet_address,
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"mint_from_proof failed: {result.error}")

    return result.signature


async def record_proof_and_mint_dung(
    config: DirectConfig,
    proof_id_str: str,
    tss: float,
    wallet_address: str,
) -> dict:
    """
    Complete flow: record proof on-chain, then mint DUNG.

    Args:
        config: Solana configuration
        proof_id_str: UUID string for the proof
        tss: Training Stress Score (1 TSS = 1 DUNG)
        wallet_address: User's wallet to receive DUNG

    Returns:
        dict with proof_signature and mint_signature
    """
    # Step 1: Record proof on proof_verifier
    proof_sig = await send_record_proof(
        config=config,
        proof_id_str=proof_id_str,
        effort_score=tss,
        wallet_address=wallet_address,
    )

    # Step 2: Mint DUNG from proof
    dung_amount = int(tss)  # 1 TSS = 1 DUNG
    mint_sig = await send_mint_from_proof(
        config=config,
        proof_id_str=proof_id_str,
        amount=dung_amount,
        wallet_address=wallet_address,
    )

    return {
        "proof_signature": proof_sig,
        "mint_signature": mint_sig,
        "dung_minted": dung_amount,
    }


# =============================================================================
# Program Initialization
# =============================================================================

def make_initialize_proof_verifier_ix(
    payer: Pubkey,
    admin: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize instruction for proof_verifier program."""
    state_pda, _ = _derive_proof_verifier_state(program_id)

    # Data: discriminator + admin pubkey
    data = _discriminator("initialize") + bytes(admin)

    accounts = [
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def initialize_proof_verifier(config: DirectConfig, admin: Optional[Pubkey] = None) -> str:
    """Initialize the proof_verifier program state."""
    admin_key = admin or config.payer.pubkey()

    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        # Check if already initialized
        state_pda, _ = _derive_proof_verifier_state(config.proof_verifier_id)
        account_info = await client.get_account_info(state_pda)
        if account_info.value is not None:
            raise ValueError("proof_verifier already initialized")

        ix = make_initialize_proof_verifier_ix(
            payer=config.payer.pubkey(),
            admin=admin_key,
            program_id=config.proof_verifier_id,
        )

        latest = await client.get_latest_blockhash()
        bh = latest.value.blockhash
        tx = Transaction.new_signed_with_payer([ix], config.payer.pubkey(), [config.payer], bh)
        resp = await client.send_raw_transaction(bytes(tx))
        sig = resp.value
        await client.confirm_transaction(sig, commitment=Confirmed)
        return str(sig)


def make_initialize_dung_mint_ix(
    admin: Pubkey,
    mint: Pubkey,
    mint_authority: Pubkey,
    proof_verifier_program: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize instruction for dung_mint program."""
    state_pda, _ = _derive_dung_mint_state(program_id)

    # Data: discriminator + mint pubkey
    data = _discriminator("initialize") + bytes(mint)

    accounts = [
        AccountMeta(pubkey=admin, is_signer=True, is_writable=True),
        AccountMeta(pubkey=state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=proof_verifier_program, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def initialize_dung_mint(config: DirectConfig) -> str:
    """Initialize the dung_mint program state."""
    mint_authority, _ = _derive_mint_authority(config.dung_mint_program_id)

    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        # Check if already initialized
        state_pda, _ = _derive_dung_mint_state(config.dung_mint_program_id)
        account_info = await client.get_account_info(state_pda)
        if account_info.value is not None:
            raise ValueError("dung_mint already initialized")

        ix = make_initialize_dung_mint_ix(
            admin=config.payer.pubkey(),
            mint=config.dung_mint_address,
            mint_authority=mint_authority,
            proof_verifier_program=config.proof_verifier_id,
            program_id=config.dung_mint_program_id,
        )

        latest = await client.get_latest_blockhash()
        bh = latest.value.blockhash
        tx = Transaction.new_signed_with_payer([ix], config.payer.pubkey(), [config.payer], bh)
        resp = await client.send_raw_transaction(bytes(tx))
        sig = resp.value
        await client.confirm_transaction(sig, commitment=Confirmed)
        return str(sig)


# =============================================================================
# dung_mint: admin_mint (TGE conversion)
# =============================================================================


def make_admin_mint_ix(
    admin: Pubkey,
    destination_ata: Pubkey,
    amount: int,
    config: DirectConfig,
) -> Instruction:
    """Build admin_mint instruction for dung_mint program (TGE conversion).

    This instruction allows the admin to mint DUNG directly to any destination
    without requiring a proof record. Used for TGE point-to-DUNG conversion.
    """
    state_pda, _ = _derive_dung_mint_state(config.dung_mint_program_id)
    mint_authority, _ = _derive_mint_authority(config.dung_mint_program_id)

    # Data: discriminator + amount (u64)
    data = _discriminator("admin_mint") + struct.pack("<Q", amount)

    accounts = [
        AccountMeta(pubkey=admin, is_signer=True, is_writable=True),
        AccountMeta(pubkey=state_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=config.dung_mint_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=destination_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=config.dung_mint_program_id, accounts=accounts, data=data)


async def send_admin_mint_dung(
    config: DirectConfig,
    wallet_address: str,
    amount: int,
) -> str:
    """
    Mint DUNG tokens via admin_mint (for TGE conversion).

    This bypasses the proof system and directly mints DUNG to a user's wallet.
    Used for converting points to DUNG at TGE.

    Uses the unified submit_and_confirm() framework with finalized commitment
    for this high-value operation.

    Args:
        config: Solana configuration (payer must be dung_mint admin)
        wallet_address: User's wallet to receive DUNG
        amount: DUNG amount to mint (will be scaled to 9 decimals)

    Returns:
        Transaction signature
    """
    from .services.solana_submit import submit_and_confirm

    wallet = Pubkey.from_string(wallet_address)
    # Scale amount to 9 decimals (1 DUNG = 1_000_000_000)
    scaled_amount = amount * DUNG_DECIMALS_MULTIPLIER

    instructions = []

    # Check if ATA exists, create if not
    destination_ata = _derive_ata(wallet, config.dung_mint_address)
    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        ata_info = await client.get_account_info(destination_ata)
    if ata_info.value is None:
        create_ata_ix = make_create_ata_ix(
            payer=config.payer.pubkey(),
            owner=wallet,
            mint=config.dung_mint_address,
        )
        instructions.append(create_ata_ix)

    # Add admin mint instruction
    mint_ix = make_admin_mint_ix(
        admin=config.payer.pubkey(),
        destination_ata=destination_ata,
        amount=scaled_amount,
        config=config,
    )
    instructions.append(mint_ix)

    result = await submit_and_confirm(
        instructions=instructions,
        signers=[config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="admin_mint_dung",
        reference_type="tge_conversion",
        reference_id=wallet_address,
        wallet=wallet_address,
        commitment="finalized",
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"admin_mint_dung failed: {result.error}")

    return result.signature


async def mint_tge_dung(
    wallet_address: str,
    dung_amount: int,
) -> dict:
    """
    Mint DUNG for TGE conversion (convenience wrapper).

    Args:
        wallet_address: User's wallet to receive DUNG
        dung_amount: DUNG amount to mint (unscaled, will be multiplied by 10^9)

    Returns:
        dict with signature and amount
    """
    config = load_default_config()
    sig = await send_admin_mint_dung(
        config=config,
        wallet_address=wallet_address,
        amount=dung_amount,
    )
    return {
        "signature": sig,
        "dung_minted": dung_amount,
        "wallet": wallet_address,
    }


@dataclass
class ReadOnlyConfig:
    """Config for read-only RPC operations (no payer needed)."""
    rpc_url: str
    program_id: Pubkey


def load_readonly_config() -> ReadOnlyConfig:
    """Load config for read-only operations (no payer keypair required)."""
    rpc_url = solana_rpc_url()
    program_id = DEFAULT_BOULDER_PROGRAM_ID
    return ReadOnlyConfig(rpc_url=rpc_url, program_id=program_id)


def load_fee_payer_keypair() -> Keypair:
    """Load the fee payer from modern or legacy env configuration."""
    payer_secret = _first_env(
        "FEE_PAYER_KEYPAIR",
        "SOLANA_PAYER_SECRET",
        "SOLANA_PAYER_PATH",
        default="~/.config/solana/boulderroller-fee-payer.json",
    )
    return _load_keypair(payer_secret)


def _validate_expected_backend_authority(authority: Keypair) -> None:
    expected_pubkey = _first_env("EXPECTED_BACKEND_AUTHORITY")
    if expected_pubkey and str(authority.pubkey()) != expected_pubkey:
        raise ValueError(
            "Configured backend authority does not match EXPECTED_BACKEND_AUTHORITY "
            f"({authority.pubkey()} != {expected_pubkey})"
        )


def load_backend_authority_keypair() -> Keypair:
    """Load the backend authority from a role-specific secret or keypair file."""
    authority_secret = _first_env(
        "BACKEND_AUTHORITY_KEYPAIR",
        "SOLANA_BACKEND_AUTHORITY_SECRET",
        "SOLANA_BACKEND_AUTHORITY_PATH",
        default="~/.config/solana/boulderroller-backend-authority.json",
    )
    authority = _load_keypair(authority_secret)
    _validate_expected_backend_authority(authority)
    return authority


def load_default_config() -> DirectConfig:
    rpc_url = solana_rpc_url()
    payer = load_fee_payer_keypair()
    program_id = DEFAULT_BOULDER_PROGRAM_ID
    return DirectConfig(
        rpc_url=rpc_url,
        program_id=program_id,
        payer=payer,
        backend_authority=load_backend_authority_keypair(),
        cal_mint_address=DEFAULT_CAL_MINT_ADDRESS,
    )


def resolve_backend_authority(config: DirectConfig) -> Keypair:
    """Return the configured backend authority, falling back to the payer."""
    return config.backend_authority or config.payer


def _unique_signers(*signers: Keypair) -> list[Keypair]:
    """Preserve signer order while removing duplicate pubkeys."""
    unique: list[Keypair] = []
    seen: set[str] = set()
    for signer in signers:
        signer_key = str(signer.pubkey())
        if signer_key in seen:
            continue
        seen.add(signer_key)
        unique.append(signer)
    return unique


# =============================================================================
# Vault Instructions (boulder_rollers)
# =============================================================================

# Vault seeds (must match on-chain constants)
VAULT_SEED = b"vault"
VAULT_COUNTER_SEED = b"vault_counter"
VAULT_COMPLETION_SEED = b"vault_completion"
VAULT_LP_MINT_SEED = b"vault_lp"
VAULT_STAKE_SEED = b"vault_stake"
VAULT_POSITION_LP_SEED = b"vault_position_lp"
VAULT_ACTIVATION_SEED = b"vault_activation"
RIDER_SOUL_SEED = b"rider_soul"
RIDE_ATTESTATION_SEED = b"ride_attestation"
HELD_RIDE_RELEASE_SEED = b"held_ride_release"
RIDE_TRIBUTE_BUDGET_SEED = b"ride_tribute_budget"
CAL_MINT_RECEIPT_SEED = b"cal_mint_receipt"
CLIMB_COMPLETION_RECEIPT_SEED = b"climb_completion_receipt"
RIDER_BALANCE_SEED = b"rider_balance"
RIDER_BALANCE_AUTH_SEED = b"rider_balance_auth"
RIDER_BALANCE_TOKEN_SEED = b"rider_balance_token"
BALANCE_VAULT_AUTHORITY_SEED = b"balance_vault_auth"

# Vault economics


def _derive_vault_counter_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive vault counter PDA."""
    return Pubkey.find_program_address([VAULT_COUNTER_SEED], program_id)


def _derive_vault_activation_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive vault activation PDA from vault ID."""
    return Pubkey.find_program_address(
        [VAULT_ACTIVATION_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive vault PDA from vault ID."""
    return Pubkey.find_program_address(
        [VAULT_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_completion_pda(
    user: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive vault completion PDA for a user/vault pair."""
    return Pubkey.find_program_address(
        [VAULT_COMPLETION_SEED, bytes(user), struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_lp_mint_pda(
    vault_id: int,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive vault LP mint PDA."""
    return Pubkey.find_program_address(
        [VAULT_LP_MINT_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_stake_pda(
    staker: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive vault stake PDA for a staker/vault pair."""
    return Pubkey.find_program_address(
        [VAULT_STAKE_SEED, bytes(staker), struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_position_lp_pda(
    rider: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive the sealed LP custody account for a rider/vault position."""
    return Pubkey.find_program_address(
        [VAULT_POSITION_LP_SEED, bytes(rider), struct.pack("<Q", vault_id)],
        program_id,
    )


def _derive_vault_cal_escrow_pda(
    vault_id: int,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive vault CAL escrow PDA."""
    return Pubkey.find_program_address(
        [b"vault_cal_escrow", struct.pack("<Q", vault_id)],
        program_id,
    )


def _derive_rider_balance_pda(rider: Pubkey, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive RiderBalance PDA for a rider."""
    return Pubkey.find_program_address(
        [RIDER_BALANCE_SEED, bytes(rider)],
        program_id,
    )


def _derive_rider_balance_auth_pda(
    rider: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive RiderBalance token authority PDA for a rider."""
    return Pubkey.find_program_address(
        [RIDER_BALANCE_AUTH_SEED, bytes(rider)],
        program_id,
    )


def _derive_balance_vault_authority_pda(
    rider: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive the rider-scoped Balance-funded Vault authority PDA."""

    return Pubkey.find_program_address(
        [BALANCE_VAULT_AUTHORITY_SEED, bytes(rider)],
        program_id,
    )


def _derive_rider_balance_token_pda(
    rider: Pubkey,
    mint: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive mint-scoped RiderBalance token account PDA."""
    return Pubkey.find_program_address(
        [RIDER_BALANCE_TOKEN_SEED, bytes(rider), bytes(mint)],
        program_id,
    )


def _derive_rider_soul_pda(rider: Pubkey, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive RiderSoul PDA."""
    return Pubkey.find_program_address([RIDER_SOUL_SEED, bytes(rider)], program_id)


def _derive_ride_attestation_pda(
    rider: Pubkey,
    ride_hash: bytes,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive RideAttestation PDA."""
    return Pubkey.find_program_address(
        [RIDE_ATTESTATION_SEED, bytes(rider), ride_hash],
        program_id,
    )


def derive_ride_attestation_pda(
    rider: Pubkey,
    ride_hash: bytes,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Public wrapper for RideAttestation PDA derivation."""
    return _derive_ride_attestation_pda(rider, ride_hash, program_id)


def _derive_held_ride_release_pda(
    ride_attestation: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive the immutable release authority for one held ride."""
    return Pubkey.find_program_address(
        [HELD_RIDE_RELEASE_SEED, bytes(ride_attestation)],
        program_id,
    )


def derive_held_ride_release_pda(
    ride_attestation: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Public wrapper for held-ride release PDA derivation."""
    return _derive_held_ride_release_pda(ride_attestation, program_id)


def _derive_ride_tribute_budget_pda(
    ride_attestation: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive the aggregate tribute budget PDA for one ride attestation."""
    return Pubkey.find_program_address(
        [RIDE_TRIBUTE_BUDGET_SEED, bytes(ride_attestation)],
        program_id,
    )


def _derive_cal_mint_receipt_pda(
    ride_attestation: Pubkey,
    rider: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive CalMintReceipt PDA."""
    return Pubkey.find_program_address(
        [CAL_MINT_RECEIPT_SEED, bytes(ride_attestation), bytes(rider)],
        program_id,
    )


def _derive_climb_completion_receipt_pda(
    ride_attestation: Pubkey,
    vault: Pubkey,
    program_id: Pubkey,
) -> tuple[Pubkey, int]:
    """Derive ClimbCompletionReceipt PDA."""
    return Pubkey.find_program_address(
        [CLIMB_COMPLETION_RECEIPT_SEED, bytes(ride_attestation), bytes(vault)],
        program_id,
    )


def derive_vault_pot_address(
    vault_id: int,
    program_id: Pubkey,
    dung_mint: Pubkey,
) -> Pubkey:
    """Derive vault pot ATA (owner = vault PDA, mint = DUNG mint)."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    return _derive_ata(vault_pda, dung_mint)


def make_record_ride_ix(
    authority: Pubkey,
    payer: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    attestation_commitment: bytes,
    parser_version: int,
    source_kind: int,
    completed_at: int,
    started_at: int,
    total_tss: int,
    total_distance_m: int,
    total_vert_m: int,
    cal_earned: int,
    climbs_crossed: int,
    program_id: Pubkey,
) -> Instruction:
    """Build record_ride instruction."""
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, program_id)
    rider_soul_pda, _ = _derive_rider_soul_pda(rider, program_id)
    program_config_pda, _ = _derive_program_config_pda(program_id)

    data = (
        _discriminator("record_ride")
        + ride_hash
        + attestation_commitment
        + struct.pack("<I", parser_version)
        + struct.pack("<B", source_kind)
        + struct.pack("<q", completed_at)
        + struct.pack("<q", started_at)
        + struct.pack("<I", total_tss)
        + struct.pack("<I", total_distance_m)
        + struct.pack("<I", total_vert_m)
        + struct.pack("<Q", cal_earned)
        + struct.pack("<H", climbs_crossed)
    )

    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_soul_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def send_record_ride(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
    attestation_commitment: bytes,
    parser_version: int,
    source_kind: int,
    completed_at: int,
    started_at: int,
    total_tss: int,
    total_distance_m: int,
    total_vert_m: int,
    cal_earned: int,
    climbs_crossed: int,
) -> str:
    """Record a canonical ride attestation on-chain."""
    from .services.solana_submit import submit_and_confirm

    rider = Pubkey.from_string(rider_wallet)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, config.program_id)
    if await _account_exists(config.rpc_url, ride_attestation_pda):
        return f"exists:{ride_attestation_pda}"

    ix = make_record_ride_ix(
        authority=authority.pubkey(),
        payer=config.payer.pubkey(),
        rider=rider,
        ride_hash=ride_hash,
        attestation_commitment=attestation_commitment,
        parser_version=parser_version,
        source_kind=source_kind,
        completed_at=completed_at,
        started_at=started_at,
        total_tss=total_tss,
        total_distance_m=total_distance_m,
        total_vert_m=total_vert_m,
        cal_earned=cal_earned,
        climbs_crossed=climbs_crossed,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="record_ride",
        reference_type="ride",
        reference_id=ride_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )

    if result.failed:
        raise RuntimeError(f"record_ride failed: {result.error}")

    return result.signature


def make_authorize_held_ride_release_ix(
    authority: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    threshold_authority_id: bytes,
    threshold_authority_commitment: bytes,
    threshold_effective_at: int,
    threshold_w: int,
    threshold_policy_version: int,
    economic_tss: int,
    cal_earned: int,
    cal_tribute_budget: int,
    release_plan_hash: bytes,
    program_id: Pubkey,
) -> Instruction:
    """Build the immutable held-ride release authority instruction."""
    if len(ride_hash) != 32:
        raise ValueError("ride_hash must be exactly 32 bytes")
    if len(threshold_authority_id) != 16 or threshold_authority_id == b"\x00" * 16:
        raise ValueError("threshold_authority_id must be a non-zero 16-byte UUID")
    if (
        len(threshold_authority_commitment) != 32
        or threshold_authority_commitment == b"\x00" * 32
    ):
        raise ValueError(
            "threshold_authority_commitment must be exactly 32 non-zero bytes"
        )
    if len(release_plan_hash) != 32 or release_plan_hash == b"\x00" * 32:
        raise ValueError("release_plan_hash must be exactly 32 non-zero bytes")

    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, program_id
    )
    release_authority_pda, _ = _derive_held_ride_release_pda(
        ride_attestation_pda, program_id
    )
    program_config_pda, _ = _derive_program_config_pda(program_id)
    data = b"".join(
        (
            _discriminator("authorize_held_ride_release"),
            threshold_authority_id,
            threshold_authority_commitment,
            struct.pack("<q", threshold_effective_at),
            struct.pack("<H", threshold_w),
            struct.pack("<B", threshold_policy_version),
            struct.pack("<I", economic_tss),
            struct.pack("<Q", cal_earned),
            struct.pack("<Q", cal_tribute_budget),
            release_plan_hash,
        )
    )
    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=release_authority_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def send_authorize_held_ride_release(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
    threshold_authority_id: bytes,
    threshold_authority_commitment: bytes,
    threshold_effective_at: int,
    threshold_w: int,
    threshold_policy_version: int,
    economic_tss: int,
    cal_earned: int,
    cal_tribute_budget: int,
    release_plan_hash: bytes,
) -> str:
    """Create or resolve the one-time authority for released economics."""
    from .services.solana_submit import submit_and_confirm

    rider = Pubkey.from_string(rider_wallet)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, config.program_id
    )
    release_authority_pda, _ = _derive_held_ride_release_pda(
        ride_attestation_pda, config.program_id
    )
    if await _account_exists(config.rpc_url, release_authority_pda):
        return f"exists:{release_authority_pda}"

    ix = make_authorize_held_ride_release_ix(
        authority=authority.pubkey(),
        rider=rider,
        ride_hash=ride_hash,
        threshold_authority_id=threshold_authority_id,
        threshold_authority_commitment=threshold_authority_commitment,
        threshold_effective_at=threshold_effective_at,
        threshold_w=threshold_w,
        threshold_policy_version=threshold_policy_version,
        economic_tss=economic_tss,
        cal_earned=cal_earned,
        cal_tribute_budget=cal_tribute_budget,
        release_plan_hash=release_plan_hash,
        program_id=config.program_id,
    )
    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="authorize_held_ride_release",
        reference_type="held_ride_release",
        reference_id=release_plan_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )
    if result.failed:
        raise RuntimeError(f"authorize_held_ride_release failed: {result.error}")
    return result.signature


def make_credit_released_cal_ix(
    authority: Pubkey,
    payer: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    config: DirectConfig,
) -> Instruction:
    """Build released CAL credit; amount comes only from the release authority."""
    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, config.program_id
    )
    release_authority_pda, _ = _derive_held_ride_release_pda(
        ride_attestation_pda, config.program_id
    )
    cal_mint_receipt_pda, _ = _derive_cal_mint_receipt_pda(
        ride_attestation_pda, rider, config.program_id
    )
    rider_soul_pda, _ = _derive_rider_soul_pda(rider, config.program_id)
    program_config_pda, _ = _derive_program_config_pda(config.program_id)
    cal_mint_auth_pda, _ = _derive_cal_mint_auth_pda(config.program_id)
    destination = _derive_ata(rider, config.cal_mint_address)
    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=release_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=cal_mint_receipt_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_soul_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=config.cal_mint_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=cal_mint_auth_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=destination, is_signer=False, is_writable=True),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(
        program_id=config.program_id,
        accounts=accounts,
        data=_discriminator("credit_released_cal"),
    )


async def send_credit_released_cal(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
) -> str:
    """Mint exactly the CAL frozen in an existing held-ride release authority."""
    from .services.solana_submit import submit_and_confirm

    rider = Pubkey.from_string(rider_wallet)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, config.program_id
    )
    cal_mint_receipt_pda, _ = _derive_cal_mint_receipt_pda(
        ride_attestation_pda, rider, config.program_id
    )
    if await _account_exists(config.rpc_url, cal_mint_receipt_pda):
        return f"exists:{cal_mint_receipt_pda}"

    destination = _derive_ata(rider, config.cal_mint_address)
    instructions: list[Instruction] = []
    if not await _account_exists(config.rpc_url, destination):
        instructions.append(
            make_create_ata_ix(
                payer=config.payer.pubkey(),
                owner=rider,
                mint=config.cal_mint_address,
            )
        )
    instructions.append(
        make_credit_released_cal_ix(
            authority=authority.pubkey(),
            payer=config.payer.pubkey(),
            rider=rider,
            ride_hash=ride_hash,
            config=config,
        )
    )
    result = await submit_and_confirm(
        instructions=instructions,
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="credit_released_cal",
        reference_type="held_ride_release",
        reference_id=ride_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )
    if result.failed:
        raise RuntimeError(f"credit_released_cal failed: {result.error}")
    return result.signature


def make_credit_cal_ix(
    authority: Pubkey,
    payer: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    amount: int,
    config: DirectConfig,
) -> Instruction:
    """Build credit_cal instruction."""
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, config.program_id)
    cal_mint_receipt_pda, _ = _derive_cal_mint_receipt_pda(
        ride_attestation_pda,
        rider,
        config.program_id,
    )
    program_config_pda, _ = _derive_program_config_pda(config.program_id)
    cal_mint_auth_pda, _ = _derive_cal_mint_auth_pda(config.program_id)
    destination = _derive_ata(rider, config.cal_mint_address)

    data = _discriminator("credit_cal") + struct.pack("<Q", amount)
    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=cal_mint_receipt_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=config.cal_mint_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=cal_mint_auth_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=destination, is_signer=False, is_writable=True),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=config.program_id, accounts=accounts, data=data)


async def send_credit_cal(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
    amount: int,
) -> str:
    """Credit CAL for a recorded ride via the receipt-protected wdvr.7 path."""
    from .services.solana_submit import submit_and_confirm

    rider = Pubkey.from_string(rider_wallet)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, config.program_id)
    cal_mint_receipt_pda, _ = _derive_cal_mint_receipt_pda(
        ride_attestation_pda,
        rider,
        config.program_id,
    )
    destination = _derive_ata(rider, config.cal_mint_address)
    instructions: list[Instruction] = []

    if await _account_exists(config.rpc_url, cal_mint_receipt_pda):
        return f"exists:{cal_mint_receipt_pda}"

    if not await _account_exists(config.rpc_url, destination):
        instructions.append(
            make_create_ata_ix(
                payer=config.payer.pubkey(),
                owner=rider,
                mint=config.cal_mint_address,
            )
        )

    instructions.append(
        make_credit_cal_ix(
            authority=authority.pubkey(),
            payer=config.payer.pubkey(),
            rider=rider,
            ride_hash=ride_hash,
            amount=amount,
            config=config,
        )
    )

    result = await submit_and_confirm(
        instructions=instructions,
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="credit_cal",
        reference_type="ride",
        reference_id=ride_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )

    if result.failed:
        raise RuntimeError(f"credit_cal failed: {result.error}")

    return result.signature


def make_record_released_climb_completion_ix(
    authority: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    vault_id: int,
    completion_time_s: int,
    cal_tribute: int,
    completion_evidence_hash: bytes,
    program_id: Pubkey,
) -> Instruction:
    """Build the release-bound V3 climb completion instruction."""
    from .services.vault_completion_evidence import (
        build_released_climb_completion_evidence_v3,
    )

    completion_evidence_hash = _validate_completion_evidence_hash(
        completion_evidence_hash
    )
    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, program_id
    )
    release_authority_pda, _ = _derive_held_ride_release_pda(
        ride_attestation_pda, program_id
    )
    ride_tribute_budget_pda, _ = _derive_ride_tribute_budget_pda(
        ride_attestation_pda, program_id
    )
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    expected_evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release_authority_pda,
        ride_attestation=ride_attestation_pda,
        vault=vault_pda,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
    )
    if completion_evidence_hash != expected_evidence_hash:
        raise ValueError(
            "V3 released completion evidence hash does not match exact tribute"
        )
    climb_completion_receipt_pda, _ = _derive_climb_completion_receipt_pda(
        ride_attestation_pda, vault_pda, program_id
    )
    completion_pda, _ = _derive_vault_completion_pda(rider, vault_id, program_id)
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    program_config_pda, _ = _derive_program_config_pda(program_id)
    data = (
        _discriminator("record_released_climb_completion")
        + struct.pack("<I", completion_time_s)
        + struct.pack("<Q", cal_tribute)
        + completion_evidence_hash
    )
    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=release_authority_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=climb_completion_receipt_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=completion_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=leaderboard_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        # Anchor consumes this as the first writable remaining account.
        AccountMeta(pubkey=ride_tribute_budget_pda, is_signer=False, is_writable=True),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def send_record_released_climb_completion(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
    vault_id: int,
    completion_time_s: int,
    cal_tribute: int,
    completion_evidence_version: int,
    completion_evidence_hash: bytes,
) -> str:
    """Apply a release-bound V3 climb completion exactly once."""
    from .services.solana_submit import submit_and_confirm

    if completion_evidence_version != 3:
        raise ValueError("released completion writes require V3 evidence")
    rider = Pubkey.from_string(rider_wallet)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(
        rider, ride_hash, config.program_id
    )
    vault_pda, _ = _derive_vault_pda(vault_id, config.program_id)
    receipt_pda, _ = _derive_climb_completion_receipt_pda(
        ride_attestation_pda, vault_pda, config.program_id
    )
    if await _account_exists(config.rpc_url, receipt_pda):
        return f"exists:{receipt_pda}"

    ix = make_record_released_climb_completion_ix(
        authority=authority.pubkey(),
        rider=rider,
        ride_hash=ride_hash,
        vault_id=vault_id,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
        completion_evidence_hash=completion_evidence_hash,
        program_id=config.program_id,
    )
    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="record_released_climb_completion",
        reference_type="released_vault_completion",
        reference_id=completion_evidence_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )
    if result.failed:
        raise RuntimeError(
            f"record_released_climb_completion failed: {result.error}"
        )
    return result.signature


def make_record_climb_completion_v2_ix(
    authority: Pubkey,
    rider: Pubkey,
    ride_hash: bytes,
    vault_id: int,
    completion_time_s: int,
    cal_tribute: int,
    completion_evidence_hash: bytes,
    program_id: Pubkey,
) -> Instruction:
    """Build tribute-bound record_climb_completion_v2 instruction."""
    completion_evidence_hash = _validate_completion_evidence_hash(
        completion_evidence_hash
    )
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, program_id)
    ride_tribute_budget_pda, _ = _derive_ride_tribute_budget_pda(
        ride_attestation_pda,
        program_id,
    )
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    climb_completion_receipt_pda, _ = _derive_climb_completion_receipt_pda(
        ride_attestation_pda,
        vault_pda,
        program_id,
    )
    completion_pda, _ = _derive_vault_completion_pda(rider, vault_id, program_id)
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    program_config_pda, _ = _derive_program_config_pda(program_id)

    data = (
        _discriminator("record_climb_completion_v2")
        + struct.pack("<I", completion_time_s)
        + struct.pack("<Q", cal_tribute)
        + completion_evidence_hash
    )
    accounts = [
        AccountMeta(pubkey=ride_attestation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=climb_completion_receipt_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=completion_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=leaderboard_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=ride_tribute_budget_pda, is_signer=False, is_writable=True),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def send_record_climb_completion(
    config: DirectConfig,
    rider_wallet: str,
    ride_hash: bytes,
    vault_id: int,
    completion_time_s: int,
    cal_tribute: int,
    completion_evidence_version: int,
    completion_evidence_hash: bytes,
) -> str:
    """Apply a tribute-bound V2 climb completion to a vault."""
    from .services.solana_submit import submit_and_confirm
    from .services.vault_completion_evidence import (
        build_climb_completion_evidence_v2,
    )

    if completion_evidence_version != 2:
        raise ValueError("V1 completion evidence cannot accept new writes")
    rider = Pubkey.from_string(rider_wallet)
    completion_evidence_hash = _validate_completion_evidence_hash(completion_evidence_hash)
    authority = resolve_backend_authority(config)
    ride_attestation_pda, _ = _derive_ride_attestation_pda(rider, ride_hash, config.program_id)
    vault_pda, _ = _derive_vault_pda(vault_id, config.program_id)
    expected_evidence_hash = build_climb_completion_evidence_v2(
        ride_attestation=ride_attestation_pda,
        vault=vault_pda,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
    )
    if completion_evidence_hash != expected_evidence_hash:
        raise ValueError("V2 completion evidence hash does not match exact tribute")
    climb_completion_receipt_pda, _ = _derive_climb_completion_receipt_pda(
        ride_attestation_pda,
        vault_pda,
        config.program_id,
    )
    if await _account_exists(config.rpc_url, climb_completion_receipt_pda):
        return f"exists:{climb_completion_receipt_pda}"

    ix = make_record_climb_completion_v2_ix(
        authority=authority.pubkey(),
        rider=rider,
        ride_hash=ride_hash,
        vault_id=vault_id,
        completion_time_s=completion_time_s,
        cal_tribute=cal_tribute,
        completion_evidence_hash=completion_evidence_hash,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="record_climb_completion_v2",
        reference_type="vault_completion",
        reference_id=completion_evidence_hash.hex(),
        wallet=rider_wallet,
        rpc_url=config.rpc_url,
        commitment="finalized",
    )

    if result.failed:
        raise RuntimeError(f"record_climb_completion_v2 failed: {result.error}")

    return result.signature


# ---------------------------------------------------------------------------
# Admin vault activation lifecycle instructions (Phase B)
# ---------------------------------------------------------------------------


def make_admin_seed_vault_completion_summary_ix(
    authority: Pubkey,
    vault_id: int,
    total_completions: int,
    best_time_s: int,
    best_time_holder: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """
    Build admin_seed_vault_completion_summary instruction.

    Sets vault completion summary and KOM from historical data.
    Can only be called while vault_activation.is_active == false.

    Accounts: vault (mut), vault_activation (mut), program_config, authority (signer).
    Args: total_completions (u64), best_time_s (u32), best_time_holder (Pubkey).
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    data = (
        _discriminator("admin_seed_vault_completion_summary")
        + struct.pack("<Q", total_completions)
        + struct.pack("<I", best_time_s)
        + bytes(best_time_holder)
    )

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_admin_replace_vault_leaderboard_ix(
    authority: Pubkey,
    vault_id: int,
    entries: list[tuple[Pubkey, int, int]],
    program_id: Pubkey,
) -> Instruction:
    """
    Build admin_replace_vault_leaderboard instruction.

    Replaces entire leaderboard with historical entries (absolute, not delta).
    Can only be called while vault_activation.is_active == false.

    Accounts: vault, vault_leaderboard (init_if_needed, mut), vault_activation (mut),
              program_config, authority (signer), system_program.
    Args: entries (Vec<LeaderEntry>) where LeaderEntry = {user: Pubkey, time_s: u32, recorded_at: i64}.

    entries: list of (user_pubkey, time_s, recorded_at) tuples.
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    # Borsh Vec: u32 length prefix + entries
    data = _discriminator("admin_replace_vault_leaderboard")
    data += struct.pack("<I", len(entries))
    for user_pk, time_s, recorded_at in entries:
        data += bytes(user_pk) + struct.pack("<I", time_s) + struct.pack("<q", recorded_at)

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=leaderboard_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_admin_activate_vault_ix(
    authority: Pubkey,
    vault_id: int,
    total_completions: int,
    kom_holder: Pubkey,
    kom_time_s: int,
    kom_recorded_at: int,
    seed_generation: int,
    seed_cutoff_at: int,
    matched_users: int,
    matched_completions: int,
    evidence_hash: bytes,
    program_id: Pubkey,
) -> Instruction:
    """
    Build admin_activate_vault instruction.

    One-way finalization: freezes the historical seed audit state, updates
    vault completion/KOM state, and sets vault_activation.is_active = true.
    After this, seed instructions are blocked and live operations are unblocked.

    Accounts: vault, vault_activation (mut), program_config, authority (signer).
    Args mirror Anchor admin_activate_vault:
      vault_id, total_completions, kom_holder, kom_time_s, kom_recorded_at,
      seed_generation, seed_cutoff_at, matched_users, matched_completions,
      evidence_hash[32].
    """
    if len(evidence_hash) != 32:
        raise ValueError("evidence_hash must be exactly 32 bytes")

    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    data = (
        _discriminator("admin_activate_vault")
        + struct.pack("<Q", vault_id)
        + struct.pack("<Q", total_completions)
        + bytes(kom_holder)
        + struct.pack("<I", kom_time_s)
        + struct.pack("<q", kom_recorded_at)
        + struct.pack("<I", seed_generation)
        + struct.pack("<q", seed_cutoff_at)
        + struct.pack("<I", matched_users)
        + struct.pack("<I", matched_completions)
        + evidence_hash
    )

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_admin_backfill_vault_activation_ix(
    authority: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> Instruction:
    """
    Build admin_backfill_vault_activation instruction.

    Creates a VaultActivation PDA for pre-Phase-B vaults and sets is_active = true.
    One-shot per vault: init constraint prevents replay. Admin-only.

    Accounts: vault, vault_activation (init, mut), program_config,
              authority (signer, mut), system_program.
    Args: vault_id (u64) — used for PDA derivation instead of deserializing vault.
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    data = _discriminator("admin_backfill_vault_activation") + struct.pack("<Q", vault_id)

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=activation_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_initialize_vault_lp_mint_ix(
    payer: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize_vault_lp_mint instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    data = _discriminator("initialize_vault_lp_mint")
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_initialize_vault_position_lp_ix(
    sponsor_authority: Pubkey,
    rider: Pubkey,
    vault_id: int,
    program_id: Pubkey,
) -> Instruction:
    """Build the idempotent initializer for one sealed LP position account."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    position_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, program_id
    )
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=position_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(
        program_id=program_id,
        accounts=accounts,
        data=_discriminator("initialize_vault_position_lp"),
    )


def make_stake_cal_in_vault_ix(
    sponsor_authority: Pubkey,
    staker: Pubkey,
    vault_id: int,
    amount: int,
    cal_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build stake_cal_in_vault instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(staker, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    staker_cal_ata = _derive_ata(staker, cal_mint)
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    staker_lp_account, _ = _derive_vault_position_lp_pda(staker, vault_id, program_id)

    data = _discriminator("stake_cal_in_vault") + struct.pack("<Q", amount)
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=staker, is_signer=True, is_writable=True),
        AccountMeta(pubkey=staker_cal_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_cal_escrow, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=staker_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_unstake_cal_from_vault_ix(
    staker: Pubkey,
    vault_id: int,
    lp_amount: int,
    cal_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build unstake_cal_from_vault instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(staker, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    staker_cal_ata = _derive_ata(staker, cal_mint)
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    staker_lp_account, _ = _derive_vault_position_lp_pda(staker, vault_id, program_id)

    data = _discriminator("unstake_cal_from_vault") + struct.pack("<Q", lp_amount)
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=staker, is_signer=True, is_writable=True),
        AccountMeta(pubkey=staker_cal_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_cal_escrow, is_signer=False, is_writable=True),
        AccountMeta(pubkey=cal_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=staker_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_harvest_rewards_ix(
    staker: Pubkey,
    vault_id: int,
    protocol_treasury: Pubkey,
    dung_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build harvest_rewards instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(staker, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    staker_dung_ata = _derive_ata(staker, dung_mint)
    dung_mint_state, _ = _derive_dung_mint_state_pda(program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    dung_mint_auth, _ = _derive_dung_mint_auth_pda(program_id)

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=staker, is_signer=True, is_writable=True),
        AccountMeta(pubkey=dung_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=staker_dung_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=protocol_treasury, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dung_mint_state, is_signer=False, is_writable=True),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=dung_mint_auth, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(
        program_id=program_id,
        accounts=accounts,
        data=_discriminator("harvest_rewards"),
    )


def make_collect_stake_rewards_for_ix(
    staker: Pubkey,
    payer: Pubkey,
    vault_id: int,
    protocol_treasury: Pubkey,
    dung_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build collect_stake_rewards_for instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(staker, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    staker_dung_ata = _derive_ata(staker, dung_mint)
    dung_mint_state, _ = _derive_dung_mint_state_pda(program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    dung_mint_auth, _ = _derive_dung_mint_auth_pda(program_id)

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=staker, is_signer=False, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=dung_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=staker_dung_ata, is_signer=False, is_writable=True),
        AccountMeta(pubkey=protocol_treasury, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dung_mint_state, is_signer=False, is_writable=True),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=dung_mint_auth, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(
        program_id=program_id,
        accounts=accounts,
        data=_discriminator("collect_stake_rewards_for"),
    )


def make_initialize_vault_cal_escrow_ix(
    payer: Pubkey,
    vault_id: int,
    cal_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize_vault_cal_escrow instruction."""
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    program_config_pda, _ = _derive_program_config_pda(program_id)
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)

    data = _discriminator("initialize_vault_cal_escrow")
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_cal_escrow, is_signer=False, is_writable=True),
        AccountMeta(pubkey=cal_mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_initialize_rider_balance_ix(
    payer: Pubkey,
    rider: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize_rider_balance instruction."""
    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    data = _discriminator("initialize_rider_balance")
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_initialize_rider_balance_token_ix(
    payer: Pubkey,
    rider: Pubkey,
    mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build initialize_rider_balance_token instruction for one Balance mint."""
    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    rider_balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    rider_balance_token, _ = _derive_rider_balance_token_pda(
        rider,
        mint,
        program_id,
    )
    data = _discriminator("initialize_rider_balance_token")
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_token, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_set_rider_balance_status_ix(
    admin: Pubkey,
    rider: Pubkey,
    status: int,
    program_id: Pubkey,
) -> Instruction:
    """Build set_rider_balance_status instruction.

    Status is the Anchor enum variant index:
    0 Active, 1 Locked, 2 Recovering, 3 Revoked.
    """
    if status < 0 or status > 3:
        raise ValueError("RiderBalance status must be between 0 and 3")

    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    data = _discriminator("set_rider_balance_status") + struct.pack("<B", status)
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=True),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=admin, is_signer=True, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_configure_balance_vault_authority_ix(
    sponsor_authority: Pubkey,
    rider: Pubkey,
    operation_authority: Pubkey,
    policy_hash: bytes,
    expires_at: int,
    program_id: Pubkey,
) -> Instruction:
    """Build the rider-signed Vault-action session configuration boundary."""

    if operation_authority == Pubkey.default():
        raise ValueError("operation_authority must be non-default")
    if len(policy_hash) != 32 or policy_hash == bytes(32):
        raise ValueError("policy_hash must be exactly 32 non-zero bytes")
    if expires_at <= 0 or expires_at > (1 << 63) - 1:
        raise ValueError("expires_at must be a positive signed 64-bit Unix timestamp")

    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    balance_vault_authority, _ = _derive_balance_vault_authority_pda(rider, program_id)
    data = (
        _discriminator("configure_balance_vault_authority")
        + bytes(operation_authority)
        + policy_hash
        + struct.pack("<q", expires_at)
    )
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=True, is_writable=False),
        AccountMeta(pubkey=balance_vault_authority, is_signer=False, is_writable=True),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_revoke_balance_vault_authority_ix(
    rider: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build the rider-signed Vault-action session revocation boundary."""

    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    balance_vault_authority, _ = _derive_balance_vault_authority_pda(rider, program_id)
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider, is_signer=True, is_writable=False),
        AccountMeta(pubkey=balance_vault_authority, is_signer=False, is_writable=True),
    ]
    return Instruction(
        program_id=program_id,
        accounts=accounts,
        data=_discriminator("revoke_balance_vault_authority"),
    )


def make_deposit_cal_from_balance_ix(
    sponsor_authority: Pubkey,
    rider: Pubkey,
    operation_authority: Pubkey,
    vault_id: int,
    amount: int,
    authorization: BalanceVaultOperationAuthorization,
    cal_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build deposit_cal_from_balance instruction.

    Moves CAL from the rider's Boulder Roller Balance token PDA into the vault
    CAL escrow and mints vault LP into the rider's sealed position account.
    The rider wallet is not a signer. Its configured per-rider operation
    authority signs the exact action and consumes the on-chain nonce.
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    rider_balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    balance_vault_authority, _ = _derive_balance_vault_authority_pda(rider, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    rider_balance_cal_account, _ = _derive_rider_balance_token_pda(
        rider,
        cal_mint,
        program_id,
    )
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    rider_balance_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, program_id
    )

    data = (
        _discriminator("deposit_cal_from_balance")
        + struct.pack("<Q", amount)
        + authorization.encode()
    )
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=balance_vault_authority, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operation_authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_cal_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_cal_escrow, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_balance_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_withdraw_cal_to_balance_ix(
    rider: Pubkey,
    operation_authority: Pubkey,
    vault_id: int,
    lp_amount: int,
    authorization: BalanceVaultOperationAuthorization,
    cal_mint: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build withdraw_cal_to_balance instruction.

    Burns sealed position LP and returns CAL to the rider's Boulder Roller
    Balance token PDA. The rider wallet is not a signer; its configured
    per-rider operation authority signs the exact action.
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    vault_activation, _ = _derive_vault_activation_pda(vault_id, program_id)
    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    rider_balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    balance_vault_authority, _ = _derive_balance_vault_authority_pda(rider, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    rider_balance_cal_account, _ = _derive_rider_balance_token_pda(
        rider,
        cal_mint,
        program_id,
    )
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    rider_balance_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, program_id
    )

    data = (
        _discriminator("withdraw_cal_to_balance")
        + struct.pack("<Q", lp_amount)
        + authorization.encode()
    )
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_activation, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=balance_vault_authority, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operation_authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_cal_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_cal_escrow, is_signer=False, is_writable=True),
        AccountMeta(pubkey=cal_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_balance_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_restore_vault_lp_custody_ix(
    sponsor_authority: Pubkey,
    rider: Pubkey,
    source_authority: Pubkey,
    source_lp_account: Pubkey,
    vault_id: int,
    amount: int,
    program_id: Pubkey,
) -> Instruction:
    """Move legacy wallet/custom LP into the rider's sealed position account."""
    if amount <= 0:
        raise ValueError("amount must be positive")

    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    position_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, program_id
    )
    data = _discriminator("restore_vault_lp_custody") + struct.pack("<Q", amount)
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=source_authority, is_signer=True, is_writable=False),
        AccountMeta(pubkey=source_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=position_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_restore_balance_vault_lp_custody_ix(
    sponsor_authority: Pubkey,
    rider: Pubkey,
    vault_id: int,
    amount: int,
    program_id: Pubkey,
) -> Instruction:
    """Move legacy Balance-held LP into the rider's sealed position account."""
    if amount <= 0:
        raise ValueError("amount must be positive")

    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, program_id)
    rider_balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
    rider_balance_lp_account, _ = _derive_rider_balance_token_pda(
        rider, vault_lp_mint, program_id
    )
    position_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, program_id
    )
    data = _discriminator("restore_balance_vault_lp_custody") + struct.pack(
        "<Q", amount
    )
    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=vault_stake, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=False, is_writable=False),
        AccountMeta(
            pubkey=rider_balance_authority, is_signer=False, is_writable=False
        ),
        AccountMeta(pubkey=vault_lp_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_balance_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=position_lp_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=sponsor_authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_withdraw_to_wallet_ix(
    rider: Pubkey,
    mint: Pubkey,
    amount: int,
    program_id: Pubkey,
) -> Instruction:
    """Build withdraw_to_wallet instruction.

    Moves a mint-scoped RiderBalance token PDA to the rider's wallet ATA. The
    rider signs because this is a Balance boundary action.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    rider_balance, _ = _derive_rider_balance_pda(rider, program_id)
    rider_balance_authority, _ = _derive_rider_balance_auth_pda(rider, program_id)
    program_config, _ = _derive_program_config_pda(program_id)
    rider_balance_source, _ = _derive_rider_balance_token_pda(
        rider,
        mint,
        program_id,
    )
    rider_wallet_destination = _derive_ata(rider, mint)

    data = _discriminator("withdraw_to_wallet") + struct.pack("<Q", amount)
    accounts = [
        AccountMeta(pubkey=rider_balance, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider, is_signer=True, is_writable=False),
        AccountMeta(pubkey=rider_balance_authority, is_signer=False, is_writable=False),
        AccountMeta(pubkey=program_config, is_signer=False, is_writable=False),
        AccountMeta(pubkey=rider_balance_source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=rider_wallet_destination, is_signer=False, is_writable=True),
        AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


async def ensure_vault_pot_account(
    config: DirectConfig,
    vault_id: int,
) -> str:
    """Ensure vault pot ATA exists, returning its address."""
    vault_pot = derive_vault_pot_address(vault_id, config.program_id, config.dung_mint_address)

    async def _call() -> str:
        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(vault_pot)
            if account_info.value is not None:
                return str(vault_pot)

            ix = make_create_ata_ix(
                payer=config.payer.pubkey(),
                owner=_derive_vault_pda(vault_id, config.program_id)[0],
                mint=config.dung_mint_address,
            )
            latest = await client.get_latest_blockhash()
            bh = latest.value.blockhash
            tx = Transaction.new_signed_with_payer([ix], config.payer.pubkey(), [config.payer], bh)
            resp = await client.send_raw_transaction(bytes(tx))
            sig = resp.value
            await client.confirm_transaction(sig, commitment=Confirmed)
            return str(vault_pot)

    return await _with_rpc_metrics("ensure_vault_pot_account", _call)


async def send_stake_cal_in_vault(
    config: DirectConfig,
    staker_keypair: Keypair,
    vault_id: int,
    amount: int,
) -> str:
    """Stake CAL in a vault on-chain.

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.

    Note: Pre-flight setup transactions (LP mint init, ATA creation)
    are sent via submit_and_confirm individually before the main stake tx.
    The staker_keypair is an additional signer alongside the payer.
    """
    from .services.solana_submit import submit_and_confirm

    sponsor_authority = resolve_backend_authority(config)
    staker = staker_keypair.pubkey()
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, config.program_id)
    vault_cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, config.program_id)
    staker_lp_account, _ = _derive_vault_position_lp_pda(
        staker, vault_id, config.program_id
    )
    staker_cal_ata = _derive_ata(staker, config.cal_mint_address)

    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        # Ensure vault LP mint exists
        lp_info = await client.get_account_info(vault_lp_mint)
        if lp_info.value is None:
            init_lp_ix = make_initialize_vault_lp_mint_ix(
                payer=config.payer.pubkey(),
                vault_id=vault_id,
                program_id=config.program_id,
            )
            lp_result = await submit_and_confirm(
                instructions=[init_lp_ix],
                signers=[config.payer],
                fee_payer=config.payer.pubkey(),
                tx_type="initialize_vault_lp_mint",
                reference_type="vault",
                reference_id=str(vault_id),
                rpc_url=config.rpc_url,
            )
            if lp_result.failed:
                raise RuntimeError(f"initialize_vault_lp_mint failed: {lp_result.error}")

        # Ensure vault CAL escrow exists
        escrow_info = await client.get_account_info(vault_cal_escrow)
        if escrow_info.value is None:
            init_escrow_ix = make_initialize_vault_cal_escrow_ix(
                payer=config.payer.pubkey(),
                vault_id=vault_id,
                cal_mint=config.cal_mint_address,
                program_id=config.program_id,
            )
            escrow_result = await submit_and_confirm(
                instructions=[init_escrow_ix],
                signers=[config.payer],
                fee_payer=config.payer.pubkey(),
                tx_type="initialize_vault_cal_escrow",
                reference_type="vault",
                reference_id=str(vault_id),
                rpc_url=config.rpc_url,
            )
            if escrow_result.failed:
                raise RuntimeError(
                    f"initialize_vault_cal_escrow failed: {escrow_result.error}"
                )

        # Ensure deterministic sealed LP custody exists.
        position_info = await client.get_account_info(staker_lp_account)
        if position_info.value is None:
            init_position_ix = make_initialize_vault_position_lp_ix(
                sponsor_authority=sponsor_authority.pubkey(),
                rider=staker,
                vault_id=vault_id,
                program_id=config.program_id,
            )
            position_result = await submit_and_confirm(
                instructions=[init_position_ix],
                signers=_unique_signers(config.payer, sponsor_authority),
                fee_payer=config.payer.pubkey(),
                tx_type="initialize_vault_position_lp",
                reference_type="vault",
                reference_id=str(vault_id),
                wallet=str(staker),
                rpc_url=config.rpc_url,
            )
            if position_result.failed:
                raise RuntimeError(
                    "initialize_vault_position_lp failed: "
                    f"{position_result.error}"
                )

        # Ensure staker CAL ATA exists
        staker_cal_info = await client.get_account_info(staker_cal_ata)
        if staker_cal_info.value is None:
            raise RuntimeError("staker has no CAL token account")

    # Stake CAL
    ix = make_stake_cal_in_vault_ix(
        sponsor_authority=sponsor_authority.pubkey(),
        staker=staker,
        vault_id=vault_id,
        amount=amount,
        cal_mint=config.cal_mint_address,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, sponsor_authority, staker_keypair),
        fee_payer=config.payer.pubkey(),
        tx_type="stake_cal_in_vault",
        reference_type="vault",
        reference_id=str(vault_id),
        wallet=str(staker),
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"stake_cal_in_vault failed: {result.error}")

    return result.signature


async def send_unstake_cal_from_vault(
    config: DirectConfig,
    staker_keypair: Keypair,
    vault_id: int,
    lp_amount: int,
) -> str:
    """Unstake CAL from a vault on-chain.

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.

    Note: The staker_keypair is an additional signer alongside the payer.
    """
    from .services.solana_submit import submit_and_confirm

    staker = staker_keypair.pubkey()
    ix = make_unstake_cal_from_vault_ix(
        staker=staker,
        vault_id=vault_id,
        lp_amount=lp_amount,
        cal_mint=config.cal_mint_address,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=[config.payer, staker_keypair],
        fee_payer=config.payer.pubkey(),
        tx_type="unstake_cal_from_vault",
        reference_type="vault",
        reference_id=str(vault_id),
        wallet=str(staker),
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"unstake_cal_from_vault failed: {result.error}")

    return result.signature


async def send_harvest_rewards(
    config: DirectConfig,
    staker_wallet: str,
    vault_id: int,
    staker_keypair: Optional[Keypair] = None,
) -> dict:
    """
    Harvest DUNG rewards from CAL staking in a vault (discrete Settlement Week allocation).

    This calls the harvest_rewards instruction which:
    1. Reads claimable DUNG directly from VaultStake.rewards_earned (credited at Settlement Week finalization)
    2. Mints DUNG to staker (minus 5% collect fee)
    3. Sends 5% fee to protocol treasury

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.

    Args:
        config: DirectConfig with RPC and program details
        staker_wallet: Public key of the staker
        vault_id: On-chain vault ID

    Returns:
        Dict with tx_signature and amounts harvested

    If staker_keypair is omitted, this returns an error dict indicating
    frontend wallet signing is required.
    """
    from .services.solana_submit import submit_and_confirm

    staker = Pubkey.from_string(staker_wallet)
    staker_dung_ata = _derive_ata(staker, config.dung_mint_address)

    # Protocol treasury for fee
    protocol_treasury_str = os.getenv("PROTOCOL_TREASURY_ACCOUNT", "")
    if not protocol_treasury_str:
        return {
            "error": "PROTOCOL_TREASURY_ACCOUNT not configured",
            "tx_signature": None,
        }

    protocol_treasury = Pubkey.from_string(protocol_treasury_str)

    try:
        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            vault_stake_pda, _ = _derive_vault_stake_pda(staker, vault_id, config.program_id)

            # Check vault stake exists
            stake_info = await client.get_account_info(vault_stake_pda)
            if stake_info.value is None:
                return {
                    "error": "No stake found for this wallet in vault",
                    "tx_signature": None,
                }

        instructions: list[Instruction] = []

        # Ensure staker DUNG ATA exists
        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            ata_info = await client.get_account_info(staker_dung_ata)
        if ata_info.value is None:
            instructions.append(
                make_create_ata_ix(
                    payer=config.payer.pubkey(),
                    owner=staker,
                    mint=config.dung_mint_address,
                )
            )

        if staker_keypair is None:
            return {
                "error": "Harvest requires user signature - use frontend wallet signing",
                "tx_signature": None,
                "note": "Pass staker_keypair for backend/devnet smoke tests or sign via wallet adapter",
            }

        if staker_keypair.pubkey() != staker:
            return {
                "error": "Provided staker_keypair does not match staker wallet",
                "tx_signature": None,
            }

        instructions.append(
            make_harvest_rewards_ix(
                staker=staker,
                vault_id=vault_id,
                protocol_treasury=protocol_treasury,
                dung_mint=config.dung_mint_address,
                program_id=config.program_id,
            )
        )

        result = await submit_and_confirm(
            instructions=instructions,
            signers=[config.payer, staker_keypair],
            fee_payer=config.payer.pubkey(),
            tx_type="harvest_rewards",
            reference_type="vault",
            reference_id=str(vault_id),
            wallet=staker_wallet,
            rpc_url=config.rpc_url,
        )

        if result.failed:
            return {
                "error": f"harvest_rewards failed: {result.error}",
                "tx_signature": None,
            }

        return {
            "error": None,
            "tx_signature": result.signature,
        }

    except Exception as e:
        logger.error(f"[solana_direct] harvest_rewards failed: {e}")
        return {
            "error": str(e),
            "tx_signature": None,
        }


async def get_vault_account(
    config: DirectConfig,
    vault_id: int,
    *,
    commitment: Commitment = Confirmed,
) -> Optional[dict]:
    """
    Fetch vault account data from chain.

    Returns parsed vault data or None if not found.
    """
    async def _call() -> Optional[dict]:
        vault_pda, _ = _derive_vault_pda(vault_id, config.program_id)

        async with AsyncClient(config.rpc_url, commitment=commitment) as client:
            account_info = await client.get_account_info(
                vault_pda,
                commitment=commitment,
            )
            if account_info.value is None:
                return None

            data = bytes(account_info.value.data)
            try:
                return _decode_anchor_vault_account(data, vault_pda)
            except Exception as exc:
                logger.warning(
                    "[SolanaDirect] Falling back to legacy Vault decode for vault_id=%s pda=%s: %s",
                    vault_id,
                    vault_pda,
                    exc,
                )
                return _decode_legacy_vault_account(data, vault_pda)

    return await _with_rpc_metrics("get_vault_account", _call)


async def get_vault_stake_account(
    config: DirectConfig,
    vault_id: int,
    user_wallet: str,
) -> Optional[dict]:
    """Fetch a specific VaultStake account from chain."""

    async def _call() -> Optional[dict]:
        staker = Pubkey.from_string(user_wallet)
        vault_stake_pda, expected_bump = _derive_vault_stake_pda(
            staker,
            vault_id,
            config.program_id,
        )

        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(vault_stake_pda)
            if account_info.value is None:
                return None
            if account_info.value.owner != config.program_id:
                raise ValueError(
                    f"VaultStake {vault_stake_pda} has unexpected owner "
                    f"{account_info.value.owner}"
                )
            decoded = _decode_anchor_vault_stake_account(
                _account_data_bytes(account_info.value.data),
                vault_stake_pda,
            )
            if decoded.get("user") != str(staker):
                raise ValueError(f"VaultStake {vault_stake_pda} rider mismatch")
            if _vault_stake_u64(decoded, "vault_id") != vault_id:
                raise ValueError(f"VaultStake {vault_stake_pda} vault mismatch")
            if _vault_stake_u64(decoded, "bump") != expected_bump:
                raise ValueError(f"VaultStake {vault_stake_pda} bump mismatch")
            return decoded

    return await _with_rpc_metrics("get_vault_stake_account", _call)


def _decode_vault_lp_custody_observation(
    *,
    account: object,
    mint_account: object,
    slot: int,
    vault: Pubkey,
    vault_stake: Pubkey,
    vault_lp_mint: Pubkey,
    position_lp_account: Pubkey,
    recorded_lp_tokens: int,
) -> VaultLpCustodyObservation:
    def observation(
        status: str,
        *,
        amount_base_units: Optional[int] = None,
        token_state: Optional[int] = None,
        sealed: bool = False,
        mint_authority: Optional[str] = None,
        freeze_authority: Optional[str] = None,
        lp_supply_base_units: Optional[int] = None,
    ) -> VaultLpCustodyObservation:
        return VaultLpCustodyObservation(
            token_account=str(position_lp_account),
            token_authority=str(vault_stake),
            mint=str(vault_lp_mint),
            recorded_lp_tokens=recorded_lp_tokens,
            amount_base_units=amount_base_units,
            token_state=token_state,
            status=status,
            sealed=sealed,
            slot=slot,
            mint_authority=mint_authority,
            freeze_authority=freeze_authority,
            lp_supply_base_units=lp_supply_base_units,
        )

    if account is None:
        return observation("missing")
    try:
        account_program = Pubkey.from_string(str(account.owner))
    except Exception:
        return observation("invalid_program_owner")
    if account_program != TOKEN_PROGRAM_ID:
        return observation("invalid_program_owner")

    data = _account_data_bytes(account.data)
    if len(data) != SPL_TOKEN_ACCOUNT_LEN:
        return observation("invalid_data_length")

    observed_mint = Pubkey.from_bytes(data[0:32])
    observed_authority = Pubkey.from_bytes(data[32:64])
    amount_base_units = struct.unpack_from(
        "<Q", data, SPL_TOKEN_ACCOUNT_AMOUNT_OFFSET
    )[0]
    token_state = data[SPL_TOKEN_ACCOUNT_STATE_OFFSET]
    common = {
        "amount_base_units": amount_base_units,
        "token_state": token_state,
    }
    if observed_mint != vault_lp_mint:
        return observation("invalid_mint", **common)
    if observed_authority != vault_stake:
        return observation("invalid_authority", **common)
    if token_state != 2:
        return observation("not_frozen", **common)
    if amount_base_units != recorded_lp_tokens:
        return observation("amount_mismatch", **common)

    if mint_account is None:
        return observation("missing_lp_mint", **common)
    try:
        mint_program = Pubkey.from_string(str(mint_account.owner))
    except Exception:
        return observation("invalid_lp_mint_program_owner", **common)
    if mint_program != TOKEN_PROGRAM_ID:
        return observation("invalid_lp_mint_program_owner", **common)

    mint_data = _account_data_bytes(mint_account.data)
    if len(mint_data) != SPL_TOKEN_MINT_LEN:
        return observation("invalid_lp_mint_data_length", **common)
    if mint_data[SPL_TOKEN_MINT_INITIALIZED_OFFSET] != 1:
        return observation("uninitialized_lp_mint", **common)
    try:
        observed_mint_authority = _decode_spl_coption_pubkey(mint_data, 0)
        lp_supply_base_units = struct.unpack_from("<Q", mint_data, 36)[0]
        observed_freeze_authority = _decode_spl_coption_pubkey(
            mint_data,
            SPL_TOKEN_MINT_FREEZE_AUTHORITY_OFFSET,
        )
    except ValueError:
        return observation("invalid_lp_mint_data", **common)
    authority_common = {
        **common,
        "mint_authority": (
            str(observed_mint_authority)
            if observed_mint_authority is not None
            else None
        ),
        "freeze_authority": (
            str(observed_freeze_authority)
            if observed_freeze_authority is not None
            else None
        ),
        "lp_supply_base_units": lp_supply_base_units,
    }
    if observed_mint_authority != vault:
        return observation("invalid_lp_mint_authority", **authority_common)
    if observed_freeze_authority != vault:
        return observation("invalid_lp_freeze_authority", **authority_common)
    return observation("sealed", sealed=True, **authority_common)


async def get_vault_lp_custody_observation(
    config: DirectConfig,
    vault_id: int,
    user_wallet: str,
    recorded_lp_tokens: int,
) -> VaultLpCustodyObservation:
    """Read and reconcile the deterministic LP custody account from chain."""
    if (
        isinstance(recorded_lp_tokens, bool)
        or not isinstance(recorded_lp_tokens, int)
        or not 0 <= recorded_lp_tokens <= (2**64 - 1)
    ):
        raise ValueError("VaultStake.lp_tokens must be an unsigned 64-bit integer")

    rider = Pubkey.from_string(user_wallet)
    vault, _ = _derive_vault_pda(vault_id, config.program_id)
    vault_stake, _ = _derive_vault_stake_pda(rider, vault_id, config.program_id)
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, config.program_id)
    position_lp_account, _ = _derive_vault_position_lp_pda(
        rider, vault_id, config.program_id
    )

    async def _call() -> VaultLpCustodyObservation:
        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            response = await client.get_multiple_accounts(
                [position_lp_account, vault_lp_mint]
            )
        account, mint_account = response.value
        return _decode_vault_lp_custody_observation(
            account=account,
            mint_account=mint_account,
            slot=int(response.context.slot),
            vault=vault,
            vault_stake=vault_stake,
            vault_lp_mint=vault_lp_mint,
            position_lp_account=position_lp_account,
            recorded_lp_tokens=recorded_lp_tokens,
        )

    return await _with_rpc_metrics("get_vault_lp_custody_observation", _call)


async def get_vault_position_quote_snapshot(
    config: DirectConfig,
    vault_id: int,
    user_wallet: str,
) -> Optional[VaultPositionQuoteSnapshot]:
    """Read every account used by a withdrawal quote in one RPC snapshot."""
    rider = Pubkey.from_string(user_wallet)
    vault_pda, _ = _derive_vault_pda(vault_id, config.program_id)
    vault_stake_pda, expected_bump = _derive_vault_stake_pda(
        rider,
        vault_id,
        config.program_id,
    )
    vault_lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, config.program_id)
    position_lp_account, _ = _derive_vault_position_lp_pda(
        rider,
        vault_id,
        config.program_id,
    )

    async def _call() -> Optional[VaultPositionQuoteSnapshot]:
        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            response = await client.get_multiple_accounts(
                [vault_pda, vault_stake_pda, position_lp_account, vault_lp_mint]
            )

        slot = int(response.context.slot)
        vault_account, stake_account, position_account, mint_account = response.value
        if vault_account is None:
            raise ValueError(f"Vault {vault_pda} is missing")
        if Pubkey.from_string(str(vault_account.owner)) != config.program_id:
            raise ValueError(f"Vault {vault_pda} has unexpected owner")
        vault_data = _account_data_bytes(vault_account.data)
        try:
            vault = _decode_anchor_vault_account(vault_data, vault_pda)
        except Exception as exc:
            logger.warning(
                "[SolanaDirect] Falling back to legacy Vault decode for quote "
                "vault_id=%s pda=%s: %s",
                vault_id,
                vault_pda,
                exc,
            )
            vault = _decode_legacy_vault_account(vault_data, vault_pda)

        if stake_account is None:
            return None
        if Pubkey.from_string(str(stake_account.owner)) != config.program_id:
            raise ValueError(f"VaultStake {vault_stake_pda} has unexpected owner")
        stake = _decode_anchor_vault_stake_account(
            _account_data_bytes(stake_account.data),
            vault_stake_pda,
        )
        if stake.get("user") != str(rider):
            raise ValueError(f"VaultStake {vault_stake_pda} rider mismatch")
        if _vault_stake_u64(stake, "vault_id") != vault_id:
            raise ValueError(f"VaultStake {vault_stake_pda} vault mismatch")
        if _vault_stake_u64(stake, "bump") != expected_bump:
            raise ValueError(f"VaultStake {vault_stake_pda} bump mismatch")

        recorded_lp_tokens = _vault_stake_u64(stake, "lp_tokens")
        custody = _decode_vault_lp_custody_observation(
            account=position_account,
            mint_account=mint_account,
            slot=slot,
            vault=vault_pda,
            vault_stake=vault_stake_pda,
            vault_lp_mint=vault_lp_mint,
            position_lp_account=position_lp_account,
            recorded_lp_tokens=recorded_lp_tokens,
        )
        return VaultPositionQuoteSnapshot(
            slot=slot,
            vault=vault,
            stake=stake,
            custody=custody,
        )

    return await _with_rpc_metrics("get_vault_position_quote_snapshot", _call)


def _vault_stake_u64(stake: dict, field: str) -> int:
    value = stake.get(field)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= (2**64 - 1)
    ):
        raise ValueError(f"VaultStake {stake.get('pda')} has invalid {field}")
    return value


def _vault_stake_inventory_for_settlement(
    stakes: list[dict],
    *,
    vault_id: int,
    expected_inventory_count: int,
    program_id: Pubkey,
) -> list[dict]:
    if (
        isinstance(expected_inventory_count, bool)
        or not isinstance(expected_inventory_count, int)
        or not 0 <= expected_inventory_count <= (2**32 - 1)
    ):
        raise ValueError("Vault staker_count must be a u32")
    if expected_inventory_count > SETTLEMENT_MAX_STAKE_INVENTORY:
        raise ValueError(
            "settlement supports at most "
            f"{SETTLEMENT_MAX_STAKE_INVENTORY} settlement-relevant "
            "VaultStake accounts within the compute-proven envelope"
        )

    inventory: list[dict] = []
    seen_pdas: set[str] = set()
    for stake in stakes:
        try:
            stake_vault_id = _vault_stake_u64(stake, "vault_id")
            user = Pubkey.from_string(str(stake["user"]))
            pda = Pubkey.from_string(str(stake["pda"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("VaultStake has malformed identity fields") from exc

        if stake_vault_id != vault_id:
            raise ValueError(
                f"VaultStake {pda} belongs to vault {stake_vault_id}, expected {vault_id}"
            )

        pda_key = str(pda)
        if pda_key in seen_pdas:
            raise ValueError(f"duplicate VaultStake PDA {pda_key}")
        seen_pdas.add(pda_key)

        expected_pda, expected_bump = _derive_vault_stake_pda(user, vault_id, program_id)
        if pda != expected_pda or stake.get("bump") != expected_bump:
            raise ValueError(f"VaultStake {pda_key} PDA or bump mismatch")

        for field in VAULT_STAKE_DELETION_U64_FIELDS:
            _vault_stake_u64(stake, field)
        if _stake_requires_settlement_account(stake):
            inventory.append(stake)

    inventory.sort(key=lambda row: str(row["pda"]))
    if len(inventory) != expected_inventory_count:
        raise RuntimeError(
            "expected "
            f"{expected_inventory_count} VaultStake inventory accounts, "
            f"found {len(inventory)}"
        )
    return inventory


async def get_vault_stake_accounts(
    config: DirectConfig,
    vault_id: int,
    *,
    commitment: Commitment = Confirmed,
) -> list[dict]:
    """Fetch the complete VaultStake inventory for a vault directly from chain."""

    async def _call() -> list[dict]:
        async with AsyncClient(config.rpc_url, commitment=commitment) as client:
            response = await client.get_program_accounts(
                config.program_id,
                commitment=commitment,
                encoding="base64",
            )

        if not hasattr(response, "value") or response.value is None:
            raise RuntimeError(f"get_program_accounts failed: {response}")

        stakes: list[dict] = []
        seen_pdas: set[str] = set()
        discriminator = _vault_stake_account_discriminator()
        for account in response.value:
            if account.account.owner != config.program_id:
                raise RuntimeError(f"Program account {account.pubkey} owner mismatch")

            data = _account_data_bytes(account.account.data)
            if len(data) < len(discriminator) or data[: len(discriminator)] != discriminator:
                continue

            try:
                decoded = _decode_anchor_vault_stake_account(
                    data,
                    account.pubkey,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to decode VaultStake {account.pubkey}"
                ) from exc
            if decoded["vault_id"] != vault_id:
                continue

            pda_key = str(account.pubkey)
            if pda_key in seen_pdas:
                raise RuntimeError(f"duplicate VaultStake PDA {pda_key} in RPC inventory")
            seen_pdas.add(pda_key)
            stakes.append(decoded)

        stakes.sort(key=lambda row: str(row["pda"]))
        return stakes

    return await _with_rpc_metrics("get_vault_stake_accounts", _call)


async def get_rider_vault_stake_accounts(
    wallet: str,
    rpc_url: Optional[str] = None,
    program_id: Optional[Pubkey] = None,
    *,
    commitment: Commitment = Finalized,
) -> list[dict]:
    """Read every VaultStake owned by one rider from finalized chain state.

    Account deletion cannot rely on the indexed projection to prove absence:
    an omitted or lagging projection row would turn an active stake into a
    false zero. This finalized direct-chain read uses discriminator and rider
    memcmp filters, then verifies raw rider bytes before Anchor decoding.
    """
    if rpc_url is None or program_id is None:
        ro_config = load_readonly_config()
        rpc_url = rpc_url or ro_config.rpc_url
        program_id = program_id or ro_config.program_id

    rider = Pubkey.from_string(wallet)

    async def _call() -> list[dict]:
        async with AsyncClient(rpc_url, commitment=commitment) as client:
            response = await client.get_program_accounts(
                program_id,
                commitment=commitment,
                encoding="base64",
                filters=[
                    MemcmpOpts(
                        offset=0,
                        bytes=base58.b58encode(
                            _vault_stake_account_discriminator()
                        ).decode(),
                    ),
                    MemcmpOpts(offset=8, bytes=str(rider)),
                ],
            )

        if not hasattr(response, "value") or response.value is None:
            raise RuntimeError(f"get_program_accounts failed: {response}")

        stakes: list[dict] = []
        seen_pdas: set[str] = set()
        discriminator = _vault_stake_account_discriminator()
        for account in response.value:
            if account.account.owner != program_id:
                raise RuntimeError(f"Program account {account.pubkey} owner mismatch")
            data = _account_data_bytes(account.account.data)
            if len(data) < len(discriminator) or data[: len(discriminator)] != discriminator:
                continue
            if (
                len(data) < len(discriminator) + 32
                or data[len(discriminator) : len(discriminator) + 32] != bytes(rider)
            ):
                continue
            try:
                decoded = _decode_anchor_vault_stake_account(data, account.pubkey)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to decode VaultStake {account.pubkey}"
                ) from exc
            if str(decoded.get("user") or "") != str(rider):
                continue

            pda_key = str(account.pubkey)
            if pda_key in seen_pdas:
                raise RuntimeError(f"duplicate VaultStake PDA {pda_key}")
            seen_pdas.add(pda_key)
            vault_id = _vault_stake_u64(decoded, "vault_id")
            expected_pda, expected_bump = _derive_vault_stake_pda(
                rider,
                vault_id,
                program_id,
            )
            if account.pubkey != expected_pda or decoded.get("bump") != expected_bump:
                raise RuntimeError(f"VaultStake {pda_key} PDA or bump mismatch")
            for field in VAULT_STAKE_DELETION_U64_FIELDS:
                _vault_stake_u64(decoded, field)
            stakes.append(decoded)

        stakes.sort(key=lambda row: str(row["pda"]))
        return stakes

    return await _with_rpc_metrics("get_rider_vault_stake_accounts", _call)


async def get_program_config_account(config: DirectConfig) -> Optional[dict]:
    """Fetch canonical ProgramConfig from chain."""

    async def _call() -> Optional[dict]:
        config_pda, _ = _derive_program_config_pda(config.program_id)

        async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
            account_info = await client.get_account_info(
                config_pda,
                commitment=Finalized,
            )
            if account_info.value is None:
                program_compatibility(config.rpc_url, str(config.program_id)).invalidate(
                    RuntimeError("ProgramConfig is missing")
                )
                return None
            decoded = await _decode_verified_program_config(
                account_info.value,
                config_pda=config_pda,
                program_id=config.program_id,
                rpc_url=config.rpc_url,
                client=client,
            )
            return decoded

    try:
        return await _with_rpc_metrics("get_program_config_account", _call)
    except Exception as exc:
        program_compatibility(config.rpc_url, str(config.program_id)).invalidate(exc)
        raise


async def get_stage1_program_config_account(config: DirectConfig) -> dict:
    """Shared boundary for Stage 1 reads, routes, and keeper scopes.

    Legacy services use get_program_config_account and continue on either
    version. Stage 1 consumers must reread config before doing any work.
    """
    decoded = await get_program_config_account(config)
    if decoded is None:
        raise RuntimeError("Stage 1 is not available on this network")
    state = program_compatibility(config.rpc_url, str(config.program_id))
    state.require_stage1()
    return decoded


async def get_program_settlement_clock(config: DirectConfig) -> SettlementClock:
    """Fetch and validate the immutable clock from canonical ProgramConfig."""
    program_config = await get_program_config_account(config)
    if program_config is None:
        raise RuntimeError("ProgramConfig is unavailable; settlement clock is unknown")
    return SettlementClock.from_program_config(program_config)


# =============================================================================
# Vault Creation (boulder_rollers.create_vault)
# =============================================================================


def make_create_vault_ix(
    sponsor_authority: Pubkey,
    creator: Pubkey,
    creator_dung_account: Pubkey,
    dung_mint: Pubkey,
    vault_counter_pda: Pubkey,
    vault_pda: Pubkey,
    climb_pda: Pubkey,
    vault_leaderboard_pda: Pubkey,
    local_legend_pda: Pubkey,
    vault_activation_pda: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build the IDL-exact DUNG constructor from one on-chain Climb."""
    program_config_pda, _ = _derive_program_config_pda(program_id)
    dung_mint_state_pda, _ = _derive_dung_mint_state_pda(program_id)
    return _build_boulder_idl_instruction(
        instruction_name="create_vault",
        named_accounts={
            "vaultCounter": vault_counter_pda,
            "vault": vault_pda,
            "climb": climb_pda,
            "vaultLeaderboard": vault_leaderboard_pda,
            "localLegend": local_legend_pda,
            "vaultActivation": vault_activation_pda,
            "sponsorAuthority": sponsor_authority,
            "creator": creator,
            "dungMintState": dung_mint_state_pda,
            "tokenProgram": TOKEN_PROGRAM_ID,
            "systemProgram": SYS_PROGRAM_ID,
        },
        args={},
        remaining_accounts=[
            # The V4-B handler owns this exact remaining-account order.
            AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
            AccountMeta(pubkey=dung_mint, is_signer=False, is_writable=True),
            AccountMeta(pubkey=creator_dung_account, is_signer=False, is_writable=True),
        ],
        program_id=program_id,
    )


def make_create_vault_with_usdc_ix(
    sponsor_authority: Pubkey,
    creator: Pubkey,
    creator_cal_account: Pubkey,
    cal_mint: Pubkey,
    creator_usdc_account: Pubkey,
    protocol_usdc_account: Pubkey,
    vault_counter_pda: Pubkey,
    vault_pda: Pubkey,
    climb_pda: Pubkey,
    vault_leaderboard_pda: Pubkey,
    local_legend_pda: Pubkey,
    vault_activation_pda: Pubkey,
    program_id: Pubkey,
) -> Instruction:
    """Build the IDL-exact CAL+USDC constructor from one on-chain Climb."""
    program_config_pda, _ = _derive_program_config_pda(program_id)
    return _build_boulder_idl_instruction(
        instruction_name="create_vault_with_usdc",
        named_accounts={
            "vaultCounter": vault_counter_pda,
            "vault": vault_pda,
            "climb": climb_pda,
            "vaultLeaderboard": vault_leaderboard_pda,
            "localLegend": local_legend_pda,
            "vaultActivation": vault_activation_pda,
            "sponsorAuthority": sponsor_authority,
            "creator": creator,
            "creatorCalAccount": creator_cal_account,
            "protocolUsdcAccount": protocol_usdc_account,
            "tokenProgram": TOKEN_PROGRAM_ID,
            "systemProgram": SYS_PROGRAM_ID,
        },
        args={},
        remaining_accounts=[
            AccountMeta(pubkey=cal_mint, is_signer=False, is_writable=True),
            AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
            AccountMeta(pubkey=creator_usdc_account, is_signer=False, is_writable=True),
        ],
        program_id=program_id,
    )


def make_configure_usdc_payment_ix(
    admin: Pubkey,
    usdc_mint: Pubkey,
    usdc_treasury_token_account: Pubkey,
    vault_creation_usdc: int,
    program_id: Pubkey,
) -> Instruction:
    """Build configure_usdc_payment instruction."""
    if vault_creation_usdc <= 0:
        raise ValueError("vault_creation_usdc must be positive")

    program_config_pda, _ = _derive_program_config_pda(program_id)
    data = _discriminator("configure_usdc_payment") + struct.pack("<Q", vault_creation_usdc)
    accounts = [
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=admin, is_signer=True, is_writable=False),
        AccountMeta(pubkey=usdc_mint, is_signer=False, is_writable=False),
        AccountMeta(pubkey=usdc_treasury_token_account, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


@dataclass
class VaultCounterData:
    """Parsed VaultCounter account data."""
    count: int
    bump: int


def parse_vault_counter(data: bytes) -> Optional[VaultCounterData]:
    """Parse VaultCounter account data (skips 8-byte discriminator)."""
    if len(data) < 8 + 8 + 1:
        return None
    offset = 8  # Skip discriminator
    count = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8
    bump = data[offset]
    return VaultCounterData(count=count, bump=bump)


async def get_next_vault_id(
    config: DirectConfig,
) -> int:
    """Get the next vault ID from VaultCounter."""
    async def _call() -> int:
        vault_counter_pda, _ = _derive_vault_counter_pda(config.program_id)

        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(vault_counter_pda)
            if account_info.value is None:
                return 0  # Counter not initialized yet
            counter = parse_vault_counter(bytes(account_info.value.data))
            return counter.count if counter else 0

    return await _with_rpc_metrics("get_next_vault_id", _call)


async def send_create_vault(
    config: DirectConfig,
    creator_wallet: str,
    signature_hex: str,
    name: str,
    vert_m: float,
    distance_m: int,
    avg_gradient_pct: float,
) -> dict:
    """
    Create a new vault on-chain.

    Burns the configured DUNG creation amount from creator's account and creates vault PDA.
    Creator becomes first Local Legend.

    Uses the unified submit_and_confirm() framework for priority fees,
    retry with blockhash expiry detection, and tx_lifecycle tracking.

    Args:
        config: Solana configuration
        creator_wallet: Wallet address of vault creator
        signature_hex: 64-byte climb signature as hex (128 chars)
        name: Vault name (3-64 characters)
        vert_m: Vertical gain in meters (float, will be scaled *10)
        distance_m: Distance in meters
        avg_gradient_pct: Average gradient percent (float, will be scaled *100)

    Returns:
        dict with vault_id, pda, and tx_signature
    """
    from .services.solana_submit import submit_and_confirm

    require_direct_vault_creation_supported()

    sponsor_authority = resolve_backend_authority(config)
    if str(sponsor_authority.pubkey()) != creator_wallet:
        raise ValueError(
            "send_create_vault now requires the creator signer. Use the prepared wallet-signed flow for end-user vault creation."
        )
    creator = sponsor_authority.pubkey()

    # Convert signature from hex to bytes
    signature = bytes.fromhex(signature_hex)
    if len(signature) != 64:
        raise ValueError(f"Signature must be 64 bytes, got {len(signature)}")

    # V4-B copies identity and metrics from the registered Climb account. The
    # legacy display arguments remain only for caller compatibility.
    del vert_m, distance_m, avg_gradient_pct

    # Pre-flight reads: vault counter and creator's DUNG ATA
    async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
        # Get current vault counter to know next ID
        vault_counter_pda, _ = _derive_vault_counter_pda(config.program_id)
        counter_info = await client.get_account_info(vault_counter_pda)
        if counter_info.value is None:
            raise ValueError("VaultCounter not initialized")

        counter = parse_vault_counter(bytes(counter_info.value.data))
        next_vault_id = counter.count

        # Get creator's DUNG ATA
        creator_dung_ata = _derive_ata(creator, config.dung_mint_address)

        # Check if creator has DUNG account
        ata_info = await client.get_account_info(creator_dung_ata)
        if ata_info.value is None:
            raise ValueError("Creator has no DUNG token account")

    # Derive PDAs using next ID
    vault_pda, _ = _derive_vault_pda(next_vault_id, config.program_id)
    climb_pda, _ = Pubkey.find_program_address(
        [b"climb", hashlib.sha256(signature).digest()],
        config.program_id,
    )
    vault_leaderboard_pda, _ = _derive_vault_leaderboard_pda(
        next_vault_id,
        config.program_id,
    )
    local_legend_pda, _ = _derive_local_legend_pda(next_vault_id, config.program_id)
    activation_pda, _ = _derive_vault_activation_pda(next_vault_id, config.program_id)

    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        climb_info = await client.get_account_info(climb_pda, commitment=Finalized)
        if climb_info.value is None or climb_info.value.owner != config.program_id:
            raise ValueError(
                "exact registered V4-B Climb is unavailable for Vault creation"
            )

    # Build instruction
    ix = make_create_vault_ix(
        sponsor_authority=sponsor_authority.pubkey(),
        creator=creator,
        creator_dung_account=creator_dung_ata,
        dung_mint=config.dung_mint_address,
        vault_counter_pda=vault_counter_pda,
        vault_pda=vault_pda,
        climb_pda=climb_pda,
        vault_leaderboard_pda=vault_leaderboard_pda,
        local_legend_pda=local_legend_pda,
        vault_activation_pda=activation_pda,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, sponsor_authority),
        fee_payer=config.payer.pubkey(),
        tx_type="vault_create",
        reference_type="vault",
        reference_id=signature_hex,
        wallet=creator_wallet,
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"create_vault failed: {result.error}")

    return {
        "vault_id": next_vault_id,
        "pda": str(vault_pda),
        "tx_signature": result.signature,
        "name": name,
    }


async def send_elect_local_legend(
    config: DirectConfig,
    vault_id: int,
    term_start_epoch: int,
    winner: str | Pubkey,
    winner_completions: int,
    runner_up: str | Pubkey | None = None,
    runner_up_completions: int = 0,
) -> str:
    """Submit elect_local_legend with the configured backend authority."""
    from .services.solana_submit import submit_and_confirm

    backend_authority = resolve_backend_authority(config)
    winner_pubkey = winner if isinstance(winner, Pubkey) else Pubkey.from_string(winner)
    runner_up_pubkey = (
        runner_up
        if isinstance(runner_up, Pubkey)
        else Pubkey.from_string(runner_up)
        if runner_up
        else Pubkey.default()
    )
    ix = make_elect_local_legend_ix(
        authority=backend_authority.pubkey(),
        vault_id=vault_id,
        winner=winner_pubkey,
        winner_completions=winner_completions,
        runner_up=runner_up_pubkey,
        runner_up_completions=runner_up_completions,
        term_start_epoch=term_start_epoch,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, backend_authority),
        fee_payer=config.payer.pubkey(),
        tx_type="local_legend_election",
        reference_type="vault",
        reference_id=str(vault_id),
        wallet=str(backend_authority.pubkey()),
        commitment="finalized",
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"elect_local_legend failed: {result.error}")

    return result.signature


async def send_deactivate_local_legend(
    config: DirectConfig,
    vault_id: int,
    term_start_epoch: int,
) -> str:
    """Submit deactivate_local_legend with the configured backend authority."""
    from .services.solana_submit import submit_and_confirm

    backend_authority = resolve_backend_authority(config)
    ix = make_deactivate_local_legend_ix(
        authority=backend_authority.pubkey(),
        vault_id=vault_id,
        term_start_epoch=term_start_epoch,
        program_id=config.program_id,
    )

    result = await submit_and_confirm(
        instructions=[ix],
        signers=_unique_signers(config.payer, backend_authority),
        fee_payer=config.payer.pubkey(),
        tx_type="local_legend_dormant",
        reference_type="vault",
        reference_id=str(vault_id),
        wallet=str(backend_authority.pubkey()),
        commitment="finalized",
        rpc_url=config.rpc_url,
    )

    if result.failed:
        raise RuntimeError(f"deactivate_local_legend failed: {result.error}")

    return result.signature


# =============================================================================
# Epoch Distribution (Tokenomics V2)
# =============================================================================

VAULT_CAL_TO_DUNG_THRESHOLD = 1_000  # 1000 CAL = 1 DUNG

# PDA seeds
VAULT_LEADERBOARD_SEED = b"vault_leaderboard"
LOCAL_LEGEND_SEED = b"local_legend"
DUNG_MINT_STATE_SEED = b"dung_mint_state"

# Distribution config (basis points, must sum to 10000)
DISTRIBUTION_CONFIG = {
    "leaderboard_share_bps": 5500,  # 55%
    "staker_share_bps": 2700,       # 27%
    "local_legend_share_bps": 300,  # 3%
    "pol_share_bps": 500,           # 5%
    "protocol_fee_bps": 1000,       # 10%
}

# Local-validator measurement covers a full ten-place Leaderboard, an active
# Local Legend, and ten settlement-relevant VaultStake accounts. That complete
# shape consumed at most 317,185 CU in repeated randomized-PDA runs; 450K
# retains 132,815 CU of measured headroom at that observed high-water mark.
SETTLEMENT_COMPUTE_UNIT_LIMIT = 450_000
SETTLEMENT_MAX_STAKE_INVENTORY = 10
U64_MAX = 18_446_744_073_709_551_615


def _settlement_lookup_required_addresses(ix: Instruction) -> list[Pubkey]:
    """Return every non-signer account the v0 settlement must compress."""
    return list(
        {
            meta.pubkey: None
            for meta in ix.accounts
            if not meta.is_signer
        }
    )


def _validate_settlement_program_account(
    *,
    account: Any,
    address: Pubkey,
    account_name: str,
    program_id: Pubkey,
    vault_id: int,
) -> bytes:
    if account.owner != program_id:
        raise ValueError(f"{account_name} {address} owner mismatch")
    data = _account_data_bytes(account.data)
    if len(data) < 16 or data[:8] != _account_discriminator(account_name):
        raise ValueError(f"{account_name} {address} discriminator is invalid")
    decoded_vault_id = struct.unpack("<Q", data[8:16])[0]
    if decoded_vault_id != vault_id:
        raise ValueError(
            f"{account_name} {address} belongs to vault {decoded_vault_id}, "
            f"expected {vault_id}"
        )
    return data


def _validate_settlement_token_account(
    *,
    account: Any,
    address: Pubkey,
    dung_mint: Pubkey,
    expected_owner: Optional[Pubkey] = None,
) -> None:
    if account.owner != TOKEN_PROGRAM_ID:
        raise ValueError(f"DUNG token account {address} owner mismatch")
    data = _account_data_bytes(account.data)
    if len(data) < 165:
        raise ValueError(f"DUNG token account {address} is malformed")
    if Pubkey.from_bytes(data[:32]) != dung_mint:
        raise ValueError(f"DUNG token account {address} mint mismatch")
    if expected_owner is not None and Pubkey.from_bytes(data[32:64]) != expected_owner:
        raise ValueError(f"DUNG token account {address} recipient mismatch")
    if data[108] != 1:
        raise ValueError(f"DUNG token account {address} is not initialized and active")


def _validate_settlement_lookup_table_state(
    *,
    address: Pubkey,
    state: AddressLookupTable,
    current_slot: int,
    expected_authority: Optional[Pubkey],
    required_addresses: list[Pubkey],
) -> AddressLookupTableAccount:
    """Fail closed unless a managed lookup table is active and complete."""
    if state.meta.deactivation_slot != U64_MAX:
        raise ValueError(f"settlement lookup table {address} is deactivated")
    if state.meta.authority != expected_authority:
        raise ValueError(
            f"settlement lookup table {address} authority mismatch: "
            f"{state.meta.authority} != {expected_authority}"
        )
    if current_slot <= state.meta.last_extended_slot:
        raise ValueError(
            f"settlement lookup table {address} is not active yet; "
            f"current slot {current_slot} <= extension slot "
            f"{state.meta.last_extended_slot}"
        )

    available = set(state.addresses)
    missing = [key for key in required_addresses if key not in available]
    if missing:
        raise ValueError(
            f"settlement lookup table {address} is missing "
            f"{len(missing)} required account"
            f"{'s' if len(missing) != 1 else ''}: "
            + ", ".join(str(key) for key in missing)
        )
    return AddressLookupTableAccount(address, state.addresses)


async def _prepare_settlement_recipient_atas(
    *,
    rpc_url: str,
    payer: Keypair,
    vault_id: int,
    instructions: list[Instruction],
) -> list[str]:
    """Create missing recipient ATAs in separate idempotent transactions."""
    from .services.solana_submit import submit_and_confirm

    signatures: list[str] = []
    for instruction in instructions:
        result = await submit_and_confirm(
            instructions=[instruction],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="settlement_recipient_ata_prepare",
            reference_type="vault",
            reference_id=str(vault_id),
            commitment="finalized",
            rpc_url=rpc_url,
        )
        if result.failed or not result.signature:
            raise RuntimeError(
                "associated token account preparation failed: "
                f"{result.error or result.status}"
            )
        signatures.append(result.signature)
    return signatures


def _canonical_distribution_config(config: Optional[dict] = None) -> dict:
    """Return the only distribution policy accepted by the on-chain program."""
    candidate = DISTRIBUTION_CONFIG if config is None else config
    if candidate != DISTRIBUTION_CONFIG:
        raise ValueError(
            "distribution config must equal the canonical distribution policy "
            "(55% leaderboard pool, 27% stakers, 3% Local Legend, "
            "5% POL, 10% treasury)"
        )
    return DISTRIBUTION_CONFIG


@dataclass
class VaultLeaderboardEntry:
    user: Pubkey
    time_s: int
    recorded_at: int


@dataclass
class LocalLegendData:
    holder: Pubkey
    is_active: bool
    is_bootstrap: bool
    term_start_epoch: int
    term_end_epoch: int


def parse_vault_leaderboard(data: bytes) -> Optional[list[VaultLeaderboardEntry]]:
    """Parse VaultLeaderboard account data."""
    min_len = 8 + 8 + 4 + 8 + 1  # discriminator + vault_id + vec_len + last_updated + bump
    if len(data) < min_len:
        return None

    offset = 8  # Skip discriminator
    offset += 8  # vault_id

    entries_len = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    entries: list[VaultLeaderboardEntry] = []
    for _ in range(entries_len):
        if len(data) < offset + 32 + 4 + 8:
            return None
        user = Pubkey.from_bytes(data[offset:offset + 32])
        offset += 32
        time_s = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4
        recorded_at = struct.unpack("<q", data[offset:offset + 8])[0]
        offset += 8
        entries.append(VaultLeaderboardEntry(user=user, time_s=time_s, recorded_at=recorded_at))

    return entries


def parse_local_legend(data: bytes) -> Optional[LocalLegendData]:
    """Parse LocalLegend account data."""
    legacy_min_len = 8 + 8 + 32 + 8 + 8 + 8 + 4 + 32 + 4 + 8 + 1 + 1
    bootstrap_min_len = legacy_min_len + 1
    if len(data) < legacy_min_len:
        return None

    offset = 8  # Skip discriminator
    offset += 8  # vault_id
    holder = Pubkey.from_bytes(data[offset:offset + 32])
    offset += 32
    offset += 8  # election_period
    term_start_epoch = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8
    term_end_epoch = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8
    offset += 4  # completions_at_election
    offset += 32  # runner_up
    offset += 4  # runner_up_completions
    offset += 8  # total_earned
    is_active = data[offset] != 0
    offset += 1
    is_bootstrap = data[offset] != 0 if len(data) >= bootstrap_min_len else False

    return LocalLegendData(
        holder=holder,
        is_active=is_active,
        is_bootstrap=is_bootstrap,
        term_start_epoch=term_start_epoch,
        term_end_epoch=term_end_epoch,
    )


def _derive_vault_leaderboard_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive vault leaderboard PDA."""
    return Pubkey.find_program_address(
        [VAULT_LEADERBOARD_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_local_legend_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive local legend PDA."""
    return Pubkey.find_program_address(
        [LOCAL_LEGEND_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def make_elect_local_legend_ix(
    authority: Pubkey,
    vault_id: int,
    winner: Pubkey,
    winner_completions: int,
    runner_up: Pubkey,
    runner_up_completions: int,
    term_start_epoch: int,
    program_id: Pubkey,
) -> Instruction:
    """
    Build elect_local_legend instruction.

    Accounts: vault, local_legend (init_if_needed), winner, program_config,
    authority (payer/signer), system_program.
    Args: winner_completions (u32), runner_up (Pubkey),
    runner_up_completions (u32), term_start_epoch (u64).
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    local_legend_pda, _ = _derive_local_legend_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    data = (
        _discriminator("elect_local_legend")
        + struct.pack("<I", int(winner_completions))
        + bytes(runner_up)
        + struct.pack("<I", int(runner_up_completions))
        + struct.pack("<Q", int(term_start_epoch))
    )

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=local_legend_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=winner, is_signer=False, is_writable=False),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
        AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(program_id=program_id, accounts=accounts, data=data)


def make_deactivate_local_legend_ix(
    authority: Pubkey,
    vault_id: int,
    term_start_epoch: int,
    program_id: Pubkey,
) -> Instruction:
    """
    Build deactivate_local_legend instruction.

    Accounts: vault, local_legend, program_config, authority.
    Args: term_start_epoch (u64).
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    local_legend_pda, _ = _derive_local_legend_pda(vault_id, program_id)
    config_pda, _ = _derive_program_config_pda(program_id)

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=local_legend_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=True),
    ]
    return Instruction(
        program_id=program_id,
        accounts=accounts,
        data=(
            _discriminator("deactivate_local_legend")
            + struct.pack("<Q", int(term_start_epoch))
        ),
    )


def _derive_dung_mint_state_pda(program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive DUNG mint state PDA."""
    return Pubkey.find_program_address([DUNG_MINT_STATE_SEED], program_id)


def make_distribute_epoch_rewards_ix(
    authority: Pubkey,
    vault_id: int,
    settlement_week: int,
    pol_account: Pubkey,
    protocol_treasury: Pubkey,
    dung_mint: Pubkey,
    program_id: Pubkey,
    local_legend: Optional[Pubkey] = None,
    extra_accounts: Optional[list[AccountMeta]] = None,
    config: Optional[dict] = None,
) -> Instruction:
    """
    Build distribute_epoch_rewards instruction.

    This finalizes a settlement week and distributes according to config:
    - 55% base to the Leaderboard pool (top 10), plus current locked staker share
    - Up to 27% to eligible stakers, plus prior unlocked pro-rata dust
    - 3% to local legend
    - 5% to POL
    - 10% to protocol treasury
    """
    vault_pda, _ = _derive_vault_pda(vault_id, program_id)
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, program_id)
    local_legend_pda, _ = _derive_local_legend_pda(vault_id, program_id)
    vault_activation_pda, _ = _derive_vault_activation_pda(vault_id, program_id)
    dung_mint_state_pda, _ = _derive_dung_mint_state_pda(program_id)
    program_config_pda, _ = _derive_program_config_pda(program_id)
    dung_mint_auth_pda, _ = _derive_dung_mint_auth_pda(program_id)

    cfg = _canonical_distribution_config(config)

    # Data: discriminator + settlement_week (u64) + DistributionConfig
    data = (
        _discriminator("distribute_epoch_rewards")
        + struct.pack("<Q", settlement_week)
        + struct.pack("<Q", cfg["leaderboard_share_bps"])
        + struct.pack("<Q", cfg["staker_share_bps"])
        + struct.pack("<Q", cfg["local_legend_share_bps"])
        + struct.pack("<Q", cfg["pol_share_bps"])
        + struct.pack("<Q", cfg["protocol_fee_bps"])
    )

    accounts = [
        AccountMeta(pubkey=vault_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=leaderboard_pda, is_signer=False, is_writable=False),
    ]

    if local_legend:
        accounts.append(AccountMeta(pubkey=local_legend, is_signer=False, is_writable=False))

    accounts.extend([
        AccountMeta(pubkey=vault_activation_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=pol_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=protocol_treasury, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dung_mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=dung_mint_state_pda, is_signer=False, is_writable=True),
        AccountMeta(pubkey=program_config_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=authority, is_signer=True, is_writable=False),  # backend_authority
        AccountMeta(pubkey=dung_mint_auth_pda, is_signer=False, is_writable=False),
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ])

    if extra_accounts:
        accounts.extend(extra_accounts)
    return Instruction(program_id=program_id, accounts=accounts, data=data)


@dataclass(frozen=True)
class SettlementDistributionPlan:
    instruction: Instruction
    recipient_ata_instructions: tuple[Instruction, ...]
    leaderboard_recipient_count: int
    local_legend_recipient_count: int
    stake_inventory_count: int
    recipient_token_accounts: tuple[tuple[Pubkey, Pubkey, Pubkey], ...] = ()


async def build_settlement_distribution_plan(
    *,
    config: DirectConfig,
    vault_id: int,
    settlement_week: int,
    pol_account: Optional[str] = None,
    protocol_treasury: Optional[str] = None,
    distribution_config: Optional[dict] = None,
) -> SettlementDistributionPlan:
    """Read finalized chain state and build the exact settlement account manifest."""
    _canonical_distribution_config(distribution_config)
    extra_accounts: list[AccountMeta] = []
    create_ata_instructions: list[Instruction] = []
    queued_atas: set[str] = set()
    recipient_token_accounts: list[tuple[Pubkey, Pubkey, Pubkey]] = []
    registered_recipient_atas: set[str] = set()
    authority = resolve_backend_authority(config)

    def queue_create_ata(owner: Pubkey, ata: Pubkey) -> None:
        ata_key = str(ata)
        if ata_key in queued_atas:
            return
        queued_atas.add(ata_key)
        create_ata_instructions.append(
            make_create_ata_ix(
                payer=config.payer.pubkey(),
                owner=owner,
                mint=config.dung_mint_address,
                idempotent=True,
            )
        )

    def register_recipient(owner: Pubkey, ata: Pubkey) -> None:
        ata_key = str(ata)
        if ata_key in registered_recipient_atas:
            return
        registered_recipient_atas.add(ata_key)
        recipient_token_accounts.append((ata, owner, config.dung_mint_address))

    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        program_config = await get_program_config_account(config)
        if program_config is None:
            raise ValueError("ProgramConfig not found on-chain")

        configured_dung_mint = program_config.get("dung_mint")
        if configured_dung_mint != str(config.dung_mint_address):
            raise ValueError(
                "DirectConfig DUNG mint does not match canonical ProgramConfig: "
                f"{config.dung_mint_address} != {configured_dung_mint}"
            )
        if int(program_config.get("epochs_per_halving") or 0) != 26:
            raise ValueError("ProgramConfig emission interval must be the canonical 26 weeks")

        configured_pol = program_config.get("pol_token_account")
        configured_treasury = program_config.get("treasury_token_account")
        if pol_account is not None and pol_account != configured_pol:
            raise ValueError("POL account does not match canonical ProgramConfig")
        if protocol_treasury is not None and protocol_treasury != configured_treasury:
            raise ValueError("treasury account does not match canonical ProgramConfig")
        pol_account = configured_pol
        protocol_treasury = configured_treasury
        if not pol_account or not protocol_treasury:
            raise ValueError("ProgramConfig missing POL or treasury token account")

        leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, config.program_id)
        leaderboard_info = await client.get_account_info(
            leaderboard_pda,
            commitment=Finalized,
        )
        if leaderboard_info.value is None:
            raise ValueError(f"VaultLeaderboard {leaderboard_pda} does not exist")
        leaderboard_data = _validate_settlement_program_account(
            account=leaderboard_info.value,
            address=leaderboard_pda,
            account_name="VaultLeaderboard",
            program_id=config.program_id,
            vault_id=vault_id,
        )
        parsed = parse_vault_leaderboard(leaderboard_data)
        if parsed is None:
            raise ValueError(f"VaultLeaderboard {leaderboard_pda} is malformed")
        leaderboard_entries = parsed

        for entry in leaderboard_entries[:10]:
            ata = _derive_ata(entry.user, config.dung_mint_address)
            register_recipient(entry.user, ata)
            ata_info = await client.get_account_info(ata, commitment=Finalized)
            if ata_info.value is None:
                queue_create_ata(entry.user, ata)
            else:
                _validate_settlement_token_account(
                    account=ata_info.value,
                    address=ata,
                    dung_mint=config.dung_mint_address,
                    expected_owner=entry.user,
                )
            extra_accounts.append(
                AccountMeta(pubkey=ata, is_signer=False, is_writable=True)
            )

        local_legend_pda, _ = _derive_local_legend_pda(vault_id, config.program_id)
        local_legend_info = await client.get_account_info(
            local_legend_pda,
            commitment=Finalized,
        )
        local_legend = None
        local_legend_recipient_count = 0
        if local_legend_info.value is not None:
            local_legend = local_legend_pda
            local_legend_data = _validate_settlement_program_account(
                account=local_legend_info.value,
                address=local_legend_pda,
                account_name="LocalLegend",
                program_id=config.program_id,
                vault_id=vault_id,
            )
            legend_data = parse_local_legend(local_legend_data)
            if legend_data is None:
                raise ValueError(f"LocalLegend {local_legend_pda} is malformed")
            if legend_data.is_active and legend_data.holder != Pubkey.default():
                legend_ata = _derive_ata(
                    legend_data.holder,
                    config.dung_mint_address,
                )
                register_recipient(legend_data.holder, legend_ata)
                legend_info = await client.get_account_info(
                    legend_ata,
                    commitment=Finalized,
                )
                if legend_info.value is None:
                    queue_create_ata(legend_data.holder, legend_ata)
                else:
                    _validate_settlement_token_account(
                        account=legend_info.value,
                        address=legend_ata,
                        dung_mint=config.dung_mint_address,
                        expected_owner=legend_data.holder,
                    )
                extra_accounts.append(
                    AccountMeta(
                        pubkey=legend_ata,
                        is_signer=False,
                        is_writable=True,
                    )
                )
                local_legend_recipient_count = 1

        pol_account_pubkey = Pubkey.from_string(pol_account)
        protocol_treasury_pubkey = Pubkey.from_string(protocol_treasury)
        pol_account_info = await client.get_account_info(
            pol_account_pubkey,
            commitment=Finalized,
        )
        if pol_account_info.value is None:
            raise ValueError(f"POL account {pol_account} does not exist")
        _validate_settlement_token_account(
            account=pol_account_info.value,
            address=pol_account_pubkey,
            dung_mint=config.dung_mint_address,
        )
        treasury_info = await client.get_account_info(
            protocol_treasury_pubkey,
            commitment=Finalized,
        )
        if treasury_info.value is None:
            raise ValueError(f"Protocol treasury {protocol_treasury} does not exist")
        _validate_settlement_token_account(
            account=treasury_info.value,
            address=protocol_treasury_pubkey,
            dung_mint=config.dung_mint_address,
        )

    vault = await get_vault_account(
        config,
        vault_id,
        commitment=Finalized,
    )
    if vault is None:
        raise ValueError(f"Vault {vault_id} not found on-chain")
    stake_inventory = await get_vault_stake_accounts(
        config,
        vault_id,
        commitment=Finalized,
    )
    settlement_stake_inventory = _vault_stake_inventory_for_settlement(
        stake_inventory,
        vault_id=vault_id,
        expected_inventory_count=int(vault["staker_count"]),
        program_id=config.program_id,
    )
    for stake in settlement_stake_inventory:
        extra_accounts.append(
            AccountMeta(
                pubkey=Pubkey.from_string(str(stake["pda"])),
                is_signer=False,
                is_writable=True,
            )
        )

    instruction = make_distribute_epoch_rewards_ix(
        authority=authority.pubkey(),
        vault_id=vault_id,
        settlement_week=settlement_week,
        pol_account=pol_account_pubkey,
        protocol_treasury=protocol_treasury_pubkey,
        dung_mint=config.dung_mint_address,
        program_id=config.program_id,
        local_legend=local_legend,
        extra_accounts=extra_accounts or None,
        config=distribution_config,
    )
    return SettlementDistributionPlan(
        instruction=instruction,
        recipient_ata_instructions=tuple(create_ata_instructions),
        leaderboard_recipient_count=min(len(leaderboard_entries), 10),
        local_legend_recipient_count=local_legend_recipient_count,
        stake_inventory_count=len(settlement_stake_inventory),
        recipient_token_accounts=tuple(recipient_token_accounts),
    )


async def send_distribute_epoch_rewards(
    config: DirectConfig,
    vault_id: int,
    settlement_week: int,
    pol_account: Optional[str] = None,
    protocol_treasury: Optional[str] = None,
    distribution_config: Optional[dict] = None,
    compute_unit_limit: int = SETTLEMENT_COMPUTE_UNIT_LIMIT,
    on_prepared: Optional[Callable[[str], Awaitable[None]]] = None,
    on_submitted: Optional[Callable[[str], Awaitable[None]]] = None,
    transport_plan: Optional[dict[str, Any]] = None,
) -> str:
    """
    Distribute epoch rewards for a vault on-chain.

    This finalizes a settlement week and distributes according to:
    - 55% base to leaderboard recipients, plus current locked staker share
    - Up to 27% to eligible stakers, plus prior unlocked pro-rata dust
    - 3% to local legend
    - 5% to POL (protocol-owned liquidity)
    - 10% to protocol treasury

    Uses the unified submit_and_confirm() framework with finalized commitment
    for this high-value operation. Includes priority fees, retry with blockhash
    expiry detection, and tx_lifecycle tracking. Before signing, it performs a
    full program-account census and requires the settlement-relevant VaultStake
    count to equal the Vault's on-chain staker_count.

    Args:
        config: Solana configuration
        vault_id: ID of the vault to distribute
        settlement_week: Settlement week being finalized
        pol_account: Optional token account for protocol-owned liquidity
        protocol_treasury: Optional token account for protocol treasury
        distribution_config: Compatibility input; if supplied it must exactly
            equal the canonical TOKENOMICS_V2 policy.
        compute_unit_limit: Measured settlement-only transaction limit. The
            generic submitter validates the runtime bound.
        on_prepared: Durable locally signed transaction callback invoked before send.
        on_submitted: Durable accepted-signature callback invoked before
            confirmation polling.
        transport_plan: Frozen v0 lookup-table generation, account-manifest,
            activation-slot, and signed-size evidence from preparation.

    Returns:
        Transaction signature
    """
    from .services.solana_submit import submit_and_confirm

    authority = resolve_backend_authority(config)
    distribution_plan = await build_settlement_distribution_plan(
        config=config,
        vault_id=vault_id,
        settlement_week=settlement_week,
        pol_account=pol_account,
        protocol_treasury=protocol_treasury,
        distribution_config=distribution_config,
    )
    if distribution_plan.recipient_ata_instructions:
        from .services.settlement_transport import SettlementTransportStaleError

        raise SettlementTransportStaleError(
            "settlement recipient ATA preparation is stale"
        )
    from .services.settlement_transport import validate_frozen_settlement_transport

    lookup_table = await validate_frozen_settlement_transport(
        config=config,
        vault_id=vault_id,
        settlement_week=settlement_week,
        instruction=distribution_plan.instruction,
        transport_plan=transport_plan,
        compute_unit_limit=compute_unit_limit,
    )

    result = await submit_and_confirm(
        instructions=[distribution_plan.instruction],
        signers=_unique_signers(config.payer, authority),
        fee_payer=config.payer.pubkey(),
        tx_type="epoch_distribute",
        reference_type="vault",
        reference_id=str(vault_id),
        commitment="finalized",
        compute_units=compute_unit_limit,
        rpc_url=config.rpc_url,
        on_prepared=on_prepared,
        on_submitted=on_submitted,
        address_lookup_table_accounts=[lookup_table],
    )

    if result.failed:
        if result.signature and result.status in {
            "submitted",
            "accepted_ambiguous",
            "prepared_ambiguous",
        }:
            raise AcceptedSettlementTransactionError(
                result.signature,
                f"distribute_epoch_rewards requires reconciliation: {result.error}",
                durable_callback_failed=result.status == "accepted_ambiguous",
                prepared_only=result.status == "prepared_ambiguous",
            )
        raise RuntimeError(f"distribute_epoch_rewards failed: {result.error}")

    return result.signature


def get_current_epoch(
    settlement_clock: SettlementClock,
    *,
    timestamp: Optional[int] = None,
) -> int:
    """Return a numeric week from an explicitly supplied ProgramConfig clock."""
    current_time = int(time.time()) if timestamp is None else int(timestamp)
    return settlement_clock.week_at(current_time)


def get_epoch_start_time(
    epoch: int, settlement_clock: SettlementClock
) -> int:
    """Get the authoritative start for a numeric Settlement Week."""
    return settlement_clock.week_start(epoch)


def get_epoch_end_time(
    epoch: int, settlement_clock: SettlementClock
) -> int:
    """Get the authoritative end, including the explicit bridge week."""
    return settlement_clock.week_end(epoch)


def get_seconds_until_next_epoch(
    settlement_clock: SettlementClock,
    *,
    timestamp: Optional[int] = None,
) -> int:
    """Get seconds remaining until the current authoritative week ends."""
    current_time = int(time.time()) if timestamp is None else int(timestamp)
    current_epoch = settlement_clock.week_at(current_time)
    return settlement_clock.week_end(current_epoch) - current_time


async def get_vaults_ready_for_distribution(
    config: DirectConfig,
    min_pending_rewards: int = 1,
) -> list[dict]:
    """
    Fetch all vaults with pending DUNG rewards ready for settlement.

    Returns list of vault data dicts ready for epoch distribution.
    """
    from .services.vault_indexer import get_vault_signature_cache

    cache = get_vault_signature_cache()
    if not cache.is_loaded:
        return []

    ready_vaults = []
    for vault in cache._vaults.values():
        try:
            # Fetch fresh on-chain data for accurate pending reward balance
            vault_data = await get_vault_account(config, vault.id)
            if vault_data and int(vault_data.get("pending_rewards", 0) or 0) >= min_pending_rewards:
                ready_vaults.append(vault_data)
        except Exception:
            continue

    return ready_vaults


if __name__ == "__main__":  # pragma: no cover
    print("Import solana_direct helpers from the backend runtime; no standalone CLI.")
